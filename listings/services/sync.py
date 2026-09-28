"""Mirror the SimplifyJobs listings.json file into the Listing table.

The single entry point is `sync_listings()`. It can be called from the management
command, the protected /internal/sync/ endpoint, or a view doing a lazy refresh.

One sync:
1. Takes a database lock so two syncs never run at the same time.
2. Downloads the file with `If-None-Match: <last ETag>`. A 304 means nothing changed.
3. Inside one transaction: creates new listings, updates changed ones, soft-closes
   ones that closed or disappeared, and reopens ones that came back.
4. Records the outcome in a SyncRun, even when something fails.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from listings.models import Listing, SyncRun, SyncState

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = (10, 60)  # (connect, read) seconds. The file is about 13 MB.
LOCK_TIMEOUT = timedelta(minutes=10)  # A lock older than this was left by a crashed sync.
LAZY_REFRESH_AFTER = timedelta(minutes=10)  # Page loads trigger a sync when data is older.
RETRY_BACKOFF = timedelta(minutes=2)  # Minimum gap between lazy attempts after a failure.
BATCH_SIZE = 500

# The source uses a few different names for the same category.
CATEGORY_ALIASES = {
    "Software Engineering": "Software",
    "Data Science, AI & Machine Learning": "AI/ML/Data",
    "Hardware Engineering": "Hardware",
    "Quantitative Finance": "Quant",
    "Product Management": "Product",
}

REQUIRED_KEYS = {"id", "company_name", "title", "url", "date_posted", "active"}

# A change to any of these counts as an "update" to a listing.
CONTENT_FIELDS = [
    "company", "title", "locations", "url", "company_url", "category",
    "terms", "sponsorship", "degrees", "source", "date_posted",
]
# Everything bulk_update writes when a listing changed.
UPDATE_FIELDS = CONTENT_FIELDS + ["date_updated", "raw", "is_active", "closed_at"]


class SourceFormatError(ValueError):
    """The source responded, but not with the data we expected."""


@dataclass
class SyncCounts:
    total_in_source: int = 0  # Entries in the source for settings.LISTINGS_TERM.
    new: int = 0
    updated: int = 0
    closed: int = 0
    reopened: int = 0


def sync_listings(force=False):
    """Sync listings from the source and return the SyncRun.

    Returns None without doing anything if another sync is already running.
    `force=True` skips the ETag check and always downloads and processes the file.
    """
    if not _acquire_lock():
        logger.info("Sync skipped: another sync is already running.")
        return None

    run = SyncRun.objects.create()
    try:
        _run_sync(run, force=force)
    except Exception as exc:
        # Deliberately broad: whatever goes wrong (network, bad JSON, a bug), the run
        # must be recorded as failed and the lock released. The transaction in
        # _run_sync has already rolled back any partial changes.
        logger.exception("Listing sync failed")
        run.status = SyncRun.Status.FAILED
        run.error_message = f"{type(exc).__name__}: {exc}"
    finally:
        run.finished_at = timezone.now()
        run.save()
        _release_lock()
    return run


def last_successful_run():
    """The most recent run that confirmed our data matches the source (200 or 304)."""
    return (
        SyncRun.objects.filter(
            status__in=[SyncRun.Status.SUCCESS, SyncRun.Status.NOT_MODIFIED],
            finished_at__isnull=False,
        )
        .order_by("-finished_at")
        .first()
    )


def sync_if_stale(max_age=LAZY_REFRESH_AFTER):
    """Lazy refresh: sync only if the last successful sync is older than max_age.

    Returns the SyncRun, or None if no sync was needed (or another one is running).
    """
    now = timezone.now()
    last_success = last_successful_run()
    if last_success and last_success.finished_at > now - max_age:
        return None
    # If a sync was attempted very recently (and failed), wait before retrying, so
    # every page load doesn't hit a source that is down.
    if SyncRun.objects.filter(started_at__gt=now - RETRY_BACKOFF).exists():
        return None
    return sync_listings()


def run_summary(run):
    """A JSON-serializable summary of a SyncRun."""
    return {
        "id": run.pk,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": round(run.duration.total_seconds(), 2) if run.duration else None,
        "total_in_source": run.total_in_source,
        "new": run.new_count,
        "updated": run.updated_count,
        "closed": run.closed_count,
        "reopened": run.reopened_count,
        "error_message": run.error_message,
    }


def normalize_category(category):
    return CATEGORY_ALIASES.get(category, category)


# --- Locking -----------------------------------------------------------------

def _acquire_lock():
    """Atomically claim the lock. Returns True if this process now holds it.

    A single conditional UPDATE is atomic in both SQLite and PostgreSQL: if two
    processes race, only one of them matches the WHERE clause and updates the row.
    """
    SyncState.load()  # Make sure the row exists.
    now = timezone.now()
    lock_is_free = Q(locked_at__isnull=True) | Q(locked_at__lt=now - LOCK_TIMEOUT)
    claimed = SyncState.objects.filter(pk=SyncState.SINGLETON_ID).filter(lock_is_free).update(locked_at=now)
    return claimed == 1


def _release_lock():
    SyncState.objects.filter(pk=SyncState.SINGLETON_ID).update(locked_at=None)


# --- Fetching ----------------------------------------------------------------

def _run_sync(run, force):
    state = SyncState.load()
    headers = {}
    if state.etag and not force:
        headers["If-None-Match"] = state.etag

    response = requests.get(settings.LISTINGS_SOURCE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code == 304:
        run.status = SyncRun.Status.NOT_MODIFIED
        return
    response.raise_for_status()
    entries = _parse_entries(response)

    with transaction.atomic():
        counts = _apply_entries(entries, now=timezone.now())
        # Saved in the same transaction, so a failed sync never records the new ETag
        # (which would make the next sync skip data it never processed).
        SyncState.objects.filter(pk=state.pk).update(etag=response.headers.get("ETag", ""))

    run.status = SyncRun.Status.SUCCESS
    run.total_in_source = counts.total_in_source
    run.new_count = counts.new
    run.updated_count = counts.updated
    run.closed_count = counts.closed
    run.reopened_count = counts.reopened


def _parse_entries(response):
    try:
        data = response.json()
    except ValueError as exc:
        raise SourceFormatError("Response was not valid JSON.") from exc
    # An empty list would close every listing, so treat it as an error, not as data.
    if not isinstance(data, list) or not data:
        raise SourceFormatError("Expected a non-empty JSON list of listings.")
    return data


# --- Applying changes ----------------------------------------------------------

def _apply_entries(entries, now):
    """Upsert entries into the Listing table and soft-close missing ones."""
    term = settings.LISTINGS_TERM
    incoming = {}
    for entry in entries:
        if not isinstance(entry, dict) or not REQUIRED_KEYS <= entry.keys():
            logger.warning("Skipping malformed source entry: %r", entry)
            continue
        if term in (entry.get("terms") or []):
            incoming[entry["id"]] = entry

    # One query loads everything we already have, keyed by source id.
    existing = {listing.external_id: listing for listing in Listing.objects.all()}
    counts = SyncCounts(total_in_source=len(incoming))
    to_create, to_update = [], []

    for external_id, entry in incoming.items():
        fields = _listing_fields(entry)
        should_be_active = bool(entry["active"]) and bool(entry.get("is_visible", True))
        listing = existing.get(external_id)

        if listing is None:
            to_create.append(Listing(
                external_id=external_id,
                is_active=should_be_active,
                first_seen_at=now,
                last_seen_at=now,
                # A posting that is already closed the first time we see it gets
                # closed_at == first_seen_at, so stats can tell we never saw it open.
                closed_at=None if should_be_active else now,
                **fields,
            ))
            counts.new += 1
            continue

        content_changed = any(getattr(listing, name) != fields[name] for name in CONTENT_FIELDS)
        closing = listing.is_active and not should_be_active
        reopening = not listing.is_active and should_be_active
        if not (content_changed or closing or reopening):
            continue

        counts.updated += content_changed
        counts.closed += closing
        counts.reopened += reopening
        for name, value in fields.items():
            setattr(listing, name, value)
        listing.is_active = should_be_active
        if closing:
            listing.closed_at = now
        elif reopening:
            listing.closed_at = None
        to_update.append(listing)

    # Postings that vanished from the source (or lost the term tag) are soft-closed.
    for external_id, listing in existing.items():
        if listing.is_active and external_id not in incoming:
            listing.is_active = False
            listing.closed_at = now
            to_update.append(listing)
            counts.closed += 1

    Listing.objects.bulk_create(to_create, batch_size=BATCH_SIZE)
    Listing.objects.bulk_update(to_update, UPDATE_FIELDS, batch_size=BATCH_SIZE)
    # Every listing that is open now was seen open in this sync.
    Listing.objects.filter(is_active=True).update(last_seen_at=now)
    return counts


def _listing_fields(entry):
    """Map one source entry to Listing field values."""
    return {
        "company": entry["company_name"],
        "title": entry["title"],
        "locations": entry.get("locations") or [],
        "url": entry["url"],
        "company_url": entry.get("company_url") or "",
        "category": normalize_category(entry.get("category") or ""),
        "terms": entry.get("terms") or [],
        "sponsorship": entry.get("sponsorship") or "",
        "degrees": entry.get("degrees") or [],
        "source": entry.get("source") or "",
        "date_posted": _from_timestamp(entry["date_posted"]),
        "date_updated": _from_timestamp(entry.get("date_updated") or entry["date_posted"]),
        "raw": entry,
    }


def _from_timestamp(seconds):
    """The source stores dates as Unix timestamps (seconds, UTC)."""
    return datetime.fromtimestamp(seconds, tz=dt_timezone.utc)
