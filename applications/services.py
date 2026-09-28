from django.db import transaction

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
