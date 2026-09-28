from django.urls import path

from . import views

app_name = "listings"

urlpatterns = [
    path("", views.listing_list, name="list"),
    path("listings/updates/", views.listing_updates, name="updates"),
    path("internal/sync/", views.internal_sync, name="internal_sync"),
    path("sync/", views.sync_status, name="sync_status"),
]
