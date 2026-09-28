from django.urls import include, path

from . import views

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    # Django's built-in login, logout, and password views (names: "login", "logout", ...).
    path("", include("django.contrib.auth.urls")),
]
