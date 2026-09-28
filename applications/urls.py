from django.urls import path

from . import views

app_name = "applications"

urlpatterns = [
    path("track/<int:listing_id>/", views.track, name="track"),
]
