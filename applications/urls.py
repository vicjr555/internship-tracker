from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    path("", views.application_list, name="list"),
    path("<int:application_id>/status/", views.update_status, name="update_status"),
    path("track/<int:listing_id>/", views.track, name="track"),
]
