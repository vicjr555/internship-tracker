import hmac
from datetime import datetime
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Value
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from applications.models import Application

from .forms import ListingFilterForm
from .models import Listing, SyncRun
from .services.sync import last_successful_run, run_summary, sync_if_stale, sync_listings

PAGE_SIZE = 50


def listing_list(request):
    """Active postings, newest first, with filters and pagination.

    HTMX requests (filter changes, page links, "Refresh list") get only the results
    partial; a normal page load gets the full page.
    """
    partial = is_htmx_partial_request(request)
    if not partial:
        # Lazy refresh: if the data is stale (e.g. the host was asleep), sync first.
        sync_if_stale()

    form = ListingFilterForm(request.GET)
    listings = form.filter_queryset(Listing.objects.filter(is_active=True), request.user)

    # Mark rows the user already tracks, in the same query (no per-row lookups).
    if request.user.is_authenticated:
        tracked = Application.objects.filter(user=request.user, listing=OuterRef("pk"))
        listings = listings.annotate(is_tracked=Exists(tracked))
    else:
        listings = listings.annotate(is_tracked=Value(False))

    page = Paginator(listings.order_by("-date_posted", "-id"), PAGE_SIZE).get_page(request.GET.get("page"))
    context = {
        "form": form,
        "page": page,
        # The live-status poller counts changes after this moment.
        **live_status_context(request, since=timezone.now()),
    }
    template = "listings/_results.html" if partial else "listings/listing_list.html"
    return render(request, template, context)


def listing_updates(request):
    """Polled by HTMX every 60s: how many postings matching the current filters
    opened or closed since the page (or results) were loaded."""
    since = parse_timestamp(request.GET.get("since")) or timezone.now()
    context = live_status_context(request, since=since)

    matching = ListingFilterForm(request.GET).filter_queryset(Listing.objects.all(), request.user)
    context["new_count"] = matching.filter(is_active=True, first_seen_at__gt=since).count()
    context["closed_count"] = matching.filter(is_active=False, closed_at__gt=since).count()
    return render(request, "listings/_live_status.html", context)


@csrf_exempt  # Called by GitHub Actions with a token, not by a browser with a session cookie.
@require_POST
def internal_sync(request):
    """Run a sync. Requires `Authorization: Bearer <SYNC_TOKEN>`."""
    if not has_valid_sync_token(request):
        return JsonResponse({"error": "Missing or invalid token."}, status=401)

    run = sync_listings()
    if run is None:
        return JsonResponse({"status": "skipped", "detail": "Another sync is already running."}, status=409)
    # A non-2xx status makes the GitHub Actions job fail, so failures are visible there.
    status_code = 502 if run.status == SyncRun.Status.FAILED else 200
    return JsonResponse(run_summary(run), status=status_code)


# --- Helpers ------------------------------------------------------------------------

def has_valid_sync_token(request):
    expected = settings.SYNC_TOKEN
    if not expected:
        return False  # The endpoint stays locked until SYNC_TOKEN is configured.
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    # compare_digest takes the same time whether the first or the last character is
    # wrong, so response timing can't be used to guess the token one character at a time.
    return scheme == "Bearer" and hmac.compare_digest(token.encode(), expected.encode())


def live_status_context(request, since):
    filters = request.GET.copy()
    for key in ("page", "since"):
        filters.pop(key, None)
    return {
        "since_ts": int(since.timestamp()),
        "filter_query": filters.urlencode(),
        "last_sync": last_successful_run(),
        "new_count": 0,
        "closed_count": 0,
    }


def parse_timestamp(value):
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def is_htmx_partial_request(request):
    # When the user hits Back, HTMX may re-request the URL to restore the page;
    # that request needs the full page, not the partial.
    return request.headers.get("HX-Request") == "true" and not request.headers.get("HX-History-Restore-Request")
