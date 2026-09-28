from datetime import timedelta

from django.db import models
from django.utils import timezone


class Listing(models.Model):
    """One internship posting mirrored from the SimplifyJobs listings.json file.

    Rows are never deleted by the sync. When a posting closes or disappears from the
    source it is soft-closed (is_active=False, closed_at set) so history and any
    Application pointing at it survive.
    """

    # --- Fields copied from the source ---
    external_id = models.CharField(max_length=64, unique=True, help_text="The source's `id` (a UUID).")
    company = models.CharField(max_length=200, db_index=True)
    title = models.CharField(max_length=300)
    locations = models.JSONField(default=list, help_text='List of strings, e.g. ["SF", "Remote in USA"].')
    url = models.URLField(max_length=1000)
    company_url = models.URLField(max_length=500, blank=True)
    category = models.CharField(max_length=50, blank=True, help_text="Normalized during sync.")
    terms = models.JSONField(default=list)
    sponsorship = models.CharField(max_length=100, blank=True)
    degrees = models.JSONField(default=list)
    source = models.CharField(max_length=100, blank=True, help_text="Who added the posting upstream.")
    date_posted = models.DateTimeField(db_index=True)
    date_updated = models.DateTimeField()

    # --- Our own tracking fields ---
    is_active = models.BooleanField(default=True, db_index=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    raw = models.JSONField(default=dict, help_text="The original source entry, for debugging.")

    class Meta:
        ordering = ["-date_posted"]
        indexes = [
            # Matches the listings page query: active postings, newest first.
            models.Index(fields=["is_active", "-date_posted"], name="listing_active_posted_idx"),
        ]

    def __str__(self):
        return f"{self.company}: {self.title}"

    @property
    def is_new(self):
        """True if this app first saw the posting in the last 24 hours."""
        return self.first_seen_at >= timezone.now() - timedelta(hours=24)


class SyncRun(models.Model):
    """An audit record of one attempt to sync listings from the source."""

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        NOT_MODIFIED = "not_modified", "Not modified"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING)
    total_in_source = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    closed_count = models.PositiveIntegerField(default=0)
    reopened_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"SyncRun {self.started_at:%Y-%m-%d %H:%M} ({self.status})"

    @property
    def duration(self):
        if self.finished_at is None:
            return None
        return self.finished_at - self.started_at


class SyncState(models.Model):
    """A single-row table holding state shared between syncs.

    - etag: the ETag from the last successful download, sent back as If-None-Match.
    - locked_at: set while a sync is running so two syncs can't run at once. It is a
      timestamp rather than a boolean so a lock left behind by a crashed process
      can be treated as stale and taken over.
    """

    SINGLETON_ID = 1

    etag = models.CharField(max_length=200, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "sync state"
        verbose_name_plural = "sync state"

    def __str__(self):
        return "Sync state"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        state, _ = cls.objects.get_or_create(pk=cls.SINGLETON_ID)
        return state
