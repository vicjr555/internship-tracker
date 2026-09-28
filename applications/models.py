from django.conf import settings
from django.db import models
from django.utils import timezone

from listings.models import Listing


class Application(models.Model):
    """A user's application to one listing. Each user can track a listing once."""

    class Status(models.TextChoices):
        SAVED = "SAVED", "Saved"
        APPLIED = "APPLIED", "Applied"
        OA = "OA", "Online assessment"
        INTERVIEW = "INTERVIEW", "Interview"
        OFFER = "OFFER", "Offer"
        REJECTED = "REJECTED", "Rejected"
        GHOSTED = "GHOSTED", "Ghosted"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications")
    # PROTECT: a listing with applications can never be deleted, even by accident in the admin.
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="applications")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SAVED, db_index=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "listing"], name="one_application_per_listing_per_user"),
        ]

    def __str__(self):
        return f"{self.user} → {self.listing} ({self.status})"


class StatusChange(models.Model):
    """History of an application's status, used to compute funnel timing."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=20, choices=Application.Status.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=Application.Status.choices)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at"]
        indexes = [models.Index(fields=["application", "changed_at"], name="statuschange_app_time_idx")]

    def __str__(self):
        return f"{self.from_status or '∅'} → {self.to_status} at {self.changed_at:%Y-%m-%d}"
