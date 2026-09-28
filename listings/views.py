from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Value
from django.shortcuts import render

from applications.models import Application

from .forms import ListingFilterForm
from .models import Listing

PAGE_SIZE = 50


def listing_list(request):
    """Active postings, newest first, with filters and pagination.

    HTMX requests (filter changes, page links) get only the results partial;
    a normal page load gets the full page.
    """
    form = ListingFilterForm(request.GET)
    listings = form.filter_queryset(Listing.objects.filter(is_active=True), request.user)

    # Mark rows the user already tracks, in the same query (no per-row lookups).
    if request.user.is_authenticated:
        tracked = Application.objects.filter(user=request.user, listing=OuterRef("pk"))
        listings = listings.annotate(is_tracked=Exists(tracked))
    else:
        listings = listings.annotate(is_tracked=Value(False))

    page = Paginator(listings.order_by("-date_posted", "-id"), PAGE_SIZE).get_page(request.GET.get("page"))
    context = {"form": form, "page": page}

    if is_htmx_partial_request(request):
        return render(request, "listings/_results.html", context)
    return render(request, "listings/listing_list.html", context)


def is_htmx_partial_request(request):
    # When the user hits Back, HTMX may re-request the URL to restore the page;
    # that request needs the full page, not the partial.
    return request.headers.get("HX-Request") == "true" and not request.headers.get("HX-History-Restore-Request")
