from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from listings.models import Listing

from .services import track_listing


@login_required
@require_POST
def track(request, listing_id):
    """HTMX endpoint behind the Track button. Returns the replacement for the button."""
    listing = get_object_or_404(Listing, pk=listing_id)
    track_listing(request.user, listing)
    return render(request, "applications/_tracked.html")
