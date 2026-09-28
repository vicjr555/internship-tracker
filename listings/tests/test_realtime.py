"""Tests for the /internal/sync/ endpoint, lazy refresh, and the live-status poller."""

from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from listings.models import Listing, SyncRun
from listings.services.sync import sync_if_stale

pytestmark = pytest.mark.django_db

TOKEN = "test-token-123"


@pytest.fixture(autouse=True)
def sync_token(settings):
    settings.SYNC_TOKEN = TOKEN


def post_sync(client, auth_header=None):
    headers = {"Authorization": auth_header} if auth_header else {}
    return client.post(reverse("listings:internal_sync"), headers=headers)


def finished_run(minutes_ago, status=SyncRun.Status.SUCCESS):
    when = timezone.now() - timedelta(minutes=minutes_ago)
    return SyncRun.objects.create(status=status, started_at=when, finished_at=when)


def make_listing(external_id, **overrides):
    now = timezone.now()
    fields = {"company": "Acme", "title": "SWE Intern", "url": f"https://example.com/{external_id}",
              "date_posted": now, "date_updated": now}
    fields.update(overrides)
    return Listing.objects.create(external_id=external_id, **fields)


# --- /internal/sync/ ------------------------------------------------------------------

def test_sync_endpoint_rejects_missing_token(client):
    with mock.patch("listings.views.sync_listings") as sync:
        response = post_sync(client)

    assert response.status_code == 401
    sync.assert_not_called()


def test_sync_endpoint_rejects_wrong_token(client):
    with mock.patch("listings.views.sync_listings") as sync:
        response = post_sync(client, "Bearer wrong-token")

    assert response.status_code == 401
    sync.assert_not_called()


def test_sync_endpoint_rejects_everything_when_no_token_is_configured(client, settings):
    settings.SYNC_TOKEN = ""

    with mock.patch("listings.views.sync_listings") as sync:
        response = post_sync(client, "Bearer ")

    assert response.status_code == 401
    sync.assert_not_called()


def test_sync_endpoint_rejects_get(client):
    response = client.get(reverse("listings:internal_sync"), headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 405


def test_sync_endpoint_runs_sync_and_returns_summary(client):
    run = finished_run(0)
    run.new_count = 7
    run.save()

    with mock.patch("listings.views.sync_listings", return_value=run):
        response = post_sync(client, f"Bearer {TOKEN}")

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["new"] == 7


def test_sync_endpoint_returns_409_when_already_running(client):
    with mock.patch("listings.views.sync_listings", return_value=None):
        response = post_sync(client, f"Bearer {TOKEN}")

    assert response.status_code == 409


def test_sync_endpoint_returns_502_when_sync_failed(client):
    failed = finished_run(0, status=SyncRun.Status.FAILED)

    with mock.patch("listings.views.sync_listings", return_value=failed):
        response = post_sync(client, f"Bearer {TOKEN}")

    assert response.status_code == 502


# --- Lazy refresh -------------------------------------------------------------------------

def test_lazy_refresh_syncs_when_data_is_stale():
    finished_run(minutes_ago=30)

    with mock.patch("listings.services.sync.sync_listings") as sync:
        sync_if_stale()

    sync.assert_called_once()


def test_lazy_refresh_skips_when_data_is_fresh():
    finished_run(minutes_ago=3)

    with mock.patch("listings.services.sync.sync_listings") as sync:
        sync_if_stale()

    sync.assert_not_called()


def test_lazy_refresh_backs_off_after_a_recent_failure():
    finished_run(minutes_ago=30)
    finished_run(minutes_ago=1, status=SyncRun.Status.FAILED)

    with mock.patch("listings.services.sync.sync_listings") as sync:
        sync_if_stale()

    sync.assert_not_called()


def test_full_page_load_triggers_lazy_refresh_but_htmx_partials_do_not(client):
    with mock.patch("listings.views.sync_if_stale") as lazy:
        client.get(reverse("listings:list"))
        client.get(reverse("listings:list"), headers={"HX-Request": "true"})

    assert lazy.call_count == 1


# --- Live status poller ---------------------------------------------------------------------

def test_updates_counts_new_and_closed_since_page_load(client):
    loaded_at = timezone.now() - timedelta(minutes=5)
    make_listing("old", first_seen_at=loaded_at - timedelta(days=1))
    make_listing("new1")
    make_listing("new2")
    make_listing("closed", is_active=False, first_seen_at=loaded_at - timedelta(days=1), closed_at=timezone.now())

    response = client.get(reverse("listings:updates"), {"since": int(loaded_at.timestamp())})

    assert response.context["new_count"] == 2
    assert response.context["closed_count"] == 1
    assert b"2 new postings" in response.content
    assert b"Refresh list" in response.content


def test_updates_respect_current_filters(client):
    loaded_at = timezone.now() - timedelta(minutes=5)
    make_listing("match", company="Stripe")
    make_listing("other", company="Globex")

    response = client.get(reverse("listings:updates"), {"since": int(loaded_at.timestamp()), "q": "stripe"})

    assert response.context["new_count"] == 1


def test_updates_shows_last_synced_time(client):
    finished_run(minutes_ago=5)

    response = client.get(reverse("listings:updates"), {"since": int(timezone.now().timestamp())})

    assert b"Last synced 5" in response.content
    assert b"Refresh list" not in response.content  # Nothing changed.
