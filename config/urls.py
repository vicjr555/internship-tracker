from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Placeholder home page; replaced by the listings page in a later phase.
    path(
        "",
        TemplateView.as_view(template_name="home.html", extra_context={"term": settings.LISTINGS_TERM}),
        name="home",
    ),
]
