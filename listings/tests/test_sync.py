"""Tests for listings.services.sync. HTTP is always mocked; no real network calls."""

import json
from datetime import timedelta
from unittest import mock

import pytest
import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

from applications.models import Application
from listings.models import Listing, SyncRun, SyncState
from listings.services.sync import sync_listings

pytestmark = pytest.mark.django_db

GET_PATH = "listings.services.sync.requests.get"


def make_entry(external_id="id-1", **overrides):
    """A source entry shaped like the real listings.json."""
    entry = {
        "source": "Simplify",
        "category": "Software",
        "company_name": "Acme",
        "id": external_id,
        "title": "Software Engineer Intern",
        "active": True,
        "terms": ["Summer 2027"],
        "date_updated": 1790000000,
        "date_posted": 1790000000,
        "url": f"https://example.com/jobs/{external_id}",
        "locations": ["Denver, CO"],
        "company_url": "https://simplify.jobs/c/Acme",
        "is_visible": True,
        "sponsorship": "Other",
        "degrees": ["Bachelor's"],
    }
    entry.update(overrides)
    return entry


def fake_response(entries=None, status=200, etag='"etag-1"', body=None):
    response = requests.Response()
    response.status_code = status
    response.headers["ETag"] = etag
    response._content = body if body is not None else json.dumps(entries or []).encode()
    return response


def run_sync_with(response, **kwargs):
    with mock.patch(GET_PATH, return_value=response) as mocked_get:
        run = sync_listings(**kwargs)
    return run, mocked_get


# --- Creating and updating ----------------------------------------------------

def test_new_listings_are_created():
    run, _ = run_sync_with(fake_response([make_entry("a"), make_entry("b", company_name="Globex")]))

    assert run.status == SyncRun.Status.SUCCESS
    assert run.new_count == 2
    listing = Listing.objects.get(external_id="b")
    assert listing.company == "Globex"
    assert listing.is_active
    assert listing.locations == ["Denver, CO"]
    assert listing.date_posted.year == 2026  # Unix timestamp converted to a datetime.


def test_only_the_configured_term_is_stored(settings):
    settings.LISTINGS_TERM = "Summer 2027"
    entries = [make_entry("a"), make_entry("b", terms=["Fall 2026"]), make_entry("c", terms=["Summer 2027", "Fall 2027"])]

    run, _ = run_sync_with(fake_response(entries))

    assert set(Listing.objects.values_list("external_id", flat=True)) == {"a", "c"}
    assert run.total_in_source == 2


def test_category_names_are_normalized():
    run_sync_with(fake_response([make_entry("a", category="Software Engineering")]))

    assert Listing.objects.get().category == "Software"


def test_changed_listings_are_updated():
    run_sync_with(fake_response([make_entry("a")]))

    changed = make_entry("a", title="New Title", locations=["Remote in USA"])
    run, _ = run_sync_with(fake_response([changed], etag='"etag-2"'))

    listing = Listing.objects.get()
    assert run.updated_count == 1
    assert run.new_count == 0
    assert listing.title == "New Title"
    assert listing.locations == ["Remote in USA"]


def test_syncing_identical_data_changes_nothing():
    entries = [make_entry("a"), make_entry("b")]
    run_sync_with(fake_response(entries))

    run, _ = run_sync_with(fake_response(entries, etag='"etag-2"'))

    assert (run.new_count, run.updated_count, run.closed_count, run.reopened_count) == (0, 0, 0, 0)


# --- Closing and reopening ----------------------------------------------------

def test_listing_missing_from_source_is_soft_closed_not_deleted():
    run_sync_with(fake_response([make_entry("a"), make_entry("b")]))

    run, _ = run_sync_with(fake_response([make_entry("a")], etag='"etag-2"'))

    closed = Listing.objects.get(external_id="b")  # Still in the database.
    assert run.closed_count == 1
    assert closed.is_active is False
    assert closed.closed_at is not None
    assert Listing.objects.get(external_id="a").is_active


def test_listing_marked_inactive_in_source_is_closed():
    run_sync_with(fake_response([make_entry("a")]))

    run, _ = run_sync_with(fake_response([make_entry("a", active=False)], etag='"etag-2"'))

    listing = Listing.objects.get()
    assert run.closed_count == 1
    assert listing.is_active is False
    assert listing.closed_at is not None


def test_hidden_listing_is_treated_as_closed():
    run_sync_with(fake_response([make_entry("a", is_visible=False)]))

    assert Listing.objects.get().is_active is False


def test_closed_listing_that_reappears_is_reopened():
    run_sync_with(fake_response([make_entry("a")]))
    run_sync_with(fake_response([make_entry("b")], etag='"etag-2"'))  # "a" disappears.
    assert Listing.objects.get(external_id="a").is_active is False

    run, _ = run_sync_with(fake_response([make_entry("a"), make_entry("b")], etag='"etag-3"'))

    listing = Listing.objects.get(external_id="a")
    assert run.reopened_count == 1
    assert listing.is_active is True
    assert listing.closed_at is None


def test_application_survives_its_listing_closing():
    run_sync_with(fake_response([make_entry("a")]))
    user = User.objects.create_user("student")
    application = Application.objects.create(user=user, listing=Listing.objects.get(), status="APPLIED")

    run_sync_with(fake_response([make_entry("b")], etag='"etag-2"'))

    application.refresh_from_db()
    assert application.listing.is_active is False
    assert application.status == "APPLIED"


# --- Conditional requests -----------------------------------------------------

def test_etag_is_sent_and_304_changes_nothing():
    run_sync_with(fake_response([make_entry("a")], etag='"etag-1"'))
    before = list(Listing.objects.values())

    run, mocked_get = run_sync_with(fake_response(status=304, body=b""))

    assert mocked_get.call_args.kwargs["headers"] == {"If-None-Match": '"etag-1"'}
    assert run.status == SyncRun.Status.NOT_MODIFIED
    assert list(Listing.objects.values()) == before


def test_force_skips_the_etag():
    run_sync_with(fake_response([make_entry("a")]))

    _, mocked_get = run_sync_with(fake_response([make_entry("a")]), force=True)

    assert mocked_get.call_args.kwargs["headers"] == {}


# --- Failures -------------------------------------------------------------------

def test_network_error_records_failed_run_and_leaves_data_untouched():
    run_sync_with(fake_response([make_entry("a")]))

    with mock.patch(GET_PATH, side_effect=requests.ConnectionError("network down")):
        run = sync_listings()

    assert run.status == SyncRun.Status.FAILED
    assert "network down" in run.error_message
    assert Listing.objects.get().is_active  # Not closed just because we couldn't fetch.
    assert SyncState.load().locked_at is None  # Lock released.


def test_invalid_json_records_failed_run():
    run, _ = run_sync_with(fake_response(body=b"<html>not json</html>"))

    assert run.status == SyncRun.Status.FAILED
    assert Listing.objects.count() == 0


def test_empty_source_is_rejected_instead_of_closing_everything():
    run_sync_with(fake_response([make_entry("a")]))

    run, _ = run_sync_with(fake_response([], etag='"etag-2"'))

    assert run.status == SyncRun.Status.FAILED
    assert Listing.objects.get().is_active


def test_http_error_status_records_failed_run():
    run, _ = run_sync_with(fake_response(status=500, body=b"server error"))

    assert run.status == SyncRun.Status.FAILED


def test_failure_midway_rolls_back_the_whole_sync():
    run_sync_with(fake_response([make_entry("a")]))

    with mock.patch.object(Listing.objects, "bulk_update", side_effect=RuntimeError("boom")):
        run, _ = run_sync_with(fake_response([make_entry("b")], etag='"etag-2"'))

    assert run.status == SyncRun.Status.FAILED
    # bulk_create for "b" ran before the failure, but the transaction rolled it back.
    assert not Listing.objects.filter(external_id="b").exists()
    assert SyncState.load().etag == '"etag-1"'  # New ETag not saved.


# --- Locking ------------------------------------------------------------------------

def test_sync_is_skipped_while_another_sync_holds_the_lock():
    state = SyncState.load()
    state.locked_at = timezone.now()
    state.save()

    run, mocked_get = run_sync_with(fake_response([make_entry("a")]))

    assert run is None
    mocked_get.assert_not_called()
    assert SyncRun.objects.count() == 0


def test_stale_lock_from_a_crashed_sync_is_taken_over():
    state = SyncState.load()
    state.locked_at = timezone.now() - timedelta(hours=1)
    state.save()

    run, _ = run_sync_with(fake_response([make_entry("a")]))

    assert run.status == SyncRun.Status.SUCCESS


# --- Management command -------------------------------------------------------------

def test_management_command_prints_summary(capsys):
    with mock.patch(GET_PATH, return_value=fake_response([make_entry("a")])):
        call_command("sync_listings")

    assert "New:       1" in capsys.readouterr().out
