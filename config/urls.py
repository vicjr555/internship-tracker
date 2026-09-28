from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("applications/", include("applications.urls")),
    path("stats/", include("stats.urls")),
    path("", include("listings.urls")),
]
