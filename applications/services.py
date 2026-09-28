from django.db import transaction
from django.utils import timezone

from .models import Application, StatusChange


@transaction.atomic
def track_listing(user, listing):
    """Start tracking a listing as SAVED. Safe to call twice (e.g. a double click).

    Returns (application, created).
    """
    application, created = Application.objects.get_or_create(
        user=user, listing=listing, defaults={"status": Application.Status.SAVED}
    )
    if created:
        # The first history entry, so the funnel knows when tracking started.
        StatusChange.objects.create(application=application, from_status="", to_status=application.status)
    return application, created


@transaction.atomic
def change_status(application, new_status):
    """Move an application to a new status and record the change in its history.

    Any status other than SAVED means the user has applied, so applied_at is filled
    in the first time the application leaves SAVED (even if it jumps straight to OA).
    Returns True if the status changed.
    """
    if new_status not in Application.Status.values:
        raise ValueError(f"Unknown status: {new_status!r}")
    if new_status == application.status:
        return False

    now = timezone.now()
    StatusChange.objects.create(
        application=application, from_status=application.status, to_status=new_status, changed_at=now
    )
    application.status = new_status
    if new_status != Application.Status.SAVED and application.applied_at is None:
        application.applied_at = now
    application.save(update_fields=["status", "applied_at", "updated_at"])
    return True
