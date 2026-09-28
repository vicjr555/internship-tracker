from unittest import mock

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from listings.models import SyncRun

pytestmark = pytest.mark.django_db

URL = reverse("listings:sync_status")


@pytest.fixture
def staff_client(client):
    client.force_login(User.objects.create_user("staff", is_staff=True, is_superuser=True))
    return client


def test_sync_status_requires_login(client):
    response = client.get(URL)

    assert response.status_code == 302
    assert reverse("login") in response.url


def test_sync_status_is_forbidden_for_non_staff(client):
    client.force_login(User.objects.create_user("student"))

    assert client.get(URL).status_code == 403
    assert client.post(URL).status_code == 403


def test_sync_status_lists_recent_runs(staff_client):
    SyncRun.objects.create(status=SyncRun.Status.FAILED, finished_at=timezone.now(), error_message="boom")

    response = staff_client.get(URL)

    assert response.status_code == 200
    assert b"boom" in response.content


def test_sync_now_runs_a_sync_and_redirects(staff_client):
    run = SyncRun.objects.create(status=SyncRun.Status.SUCCESS, finished_at=timezone.now())

    with mock.patch("listings.views.sync_listings", return_value=run) as sync:
        response = staff_client.post(URL, follow=True)

    sync.assert_called_once()
    assert response.redirect_chain[-1][0] == URL
    assert b"Sync finished" in response.content


def test_sync_now_reports_when_a_sync_is_already_running(staff_client):
    with mock.patch("listings.views.sync_listings", return_value=None):
        response = staff_client.post(URL, follow=True)

    assert b"already running" in response.content


def test_every_model_admin_changelist_loads(staff_client):
    """Smoke test: all registered admin pages render (catches bad list_display etc.)."""
    for model in admin.site._registry:
        url = reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
        assert staff_client.get(url).status_code == 200, url
