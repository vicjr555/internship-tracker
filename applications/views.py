from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from listings.models import Listing

from .models import Application
from .services import change_status, track_listing


@login_required
def application_list(request):
    """The user's applications, optionally filtered to one status."""
    applications = (
        Application.objects.filter(user=request.user)
        .select_related("listing")
        .prefetch_related("status_changes")
    )

    # Count per status in one GROUP BY query, for the filter tabs.
    counts = dict(applications.order_by().values_list("status").annotate(n=Count("id")))
    status_tabs = [(value, label, counts.get(value, 0)) for value, label in Application.Status.choices]

    selected = request.GET.get("status", "")
    if selected in Application.Status.values:
        applications = applications.filter(status=selected)

    return render(request, "applications/application_list.html", {
        "applications": applications,
        "status_tabs": status_tabs,
        "selected": selected,
        "total": sum(counts.values()),
        "status_choices": Application.Status.choices,
    })


@login_required
@require_POST
def update_status(request, application_id):
    """HTMX endpoint for the inline status dropdown. Returns the updated table row."""
    # Filtering by user means another user's application is a 404, not a leak.
    application = get_object_or_404(
        Application.objects.select_related("listing"), pk=application_id, user=request.user
    )
    new_status = request.POST.get("status", "")
    if new_status not in Application.Status.values:
        return HttpResponseBadRequest("Unknown status.")

    change_status(application, new_status)
    return render(request, "applications/_application_row.html", {
        "application": application,
        "status_choices": Application.Status.choices,
    })


@login_required
@require_POST
def track(request, listing_id):
    """HTMX endpoint behind the Track button. Returns the replacement for the button."""
    listing = get_object_or_404(Listing, pk=listing_id)
    track_listing(request.user, listing)
    return render(request, "applications/_tracked.html")
