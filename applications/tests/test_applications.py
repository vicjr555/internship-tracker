import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from applications.models import Application, StatusChange
from applications.services import change_status, track_listing
from listings.models import Listing

pytestmark = pytest.mark.django_db


def make_listing(external_id="a", **overrides):
    now = timezone.now()
    fields = {"company": "Acme", "title": "SWE Intern", "url": f"https://example.com/{external_id}",
              "date_posted": now, "date_updated": now}
    fields.update(overrides)
    return Listing.objects.create(external_id=external_id, **fields)


@pytest.fixture
def user():
    return User.objects.create_user("student")


@pytest.fixture
def user_client(client, user):
    client.force_login(user)
    return client


# --- Auth ---------------------------------------------------------------------

def test_signup_creates_user_and_logs_them_in(client):
    response = client.post(reverse("signup"), {
        "username": "newstudent", "password1": "a-Str0ng-passphrase", "password2": "a-Str0ng-passphrase",
    })

    assert response.status_code == 302
    assert User.objects.filter(username="newstudent").exists()
    assert client.get(reverse("applications:list")).status_code == 200  # Logged in.


def test_login_page_loads(client):
    assert client.get(reverse("login")).status_code == 200


def test_my_applications_requires_login(client):
    response = client.get(reverse("applications:list"))

    assert response.status_code == 302
    assert reverse("login") in response.url


# --- My Applications page -----------------------------------------------------------

def test_only_the_users_own_applications_are_listed(user_client, user):
    track_listing(user, make_listing("mine", company="MyCo"))
    track_listing(User.objects.create_user("other"), make_listing("theirs", company="TheirCo"))

    response = user_client.get(reverse("applications:list"))

    assert b"MyCo" in response.content
    assert b"TheirCo" not in response.content


def test_filter_by_status(user_client, user):
    applied, _ = track_listing(user, make_listing("a", company="AppliedCo"))
    change_status(applied, "APPLIED")
    track_listing(user, make_listing("b", company="SavedCo"))

    response = user_client.get(reverse("applications:list"), {"status": "APPLIED"})

    assert b"AppliedCo" in response.content
    assert b"SavedCo" not in response.content


def test_closed_listing_still_shows_with_closed_label(user_client, user):
    listing = make_listing(is_active=False, closed_at=timezone.now())
    track_listing(user, listing)

    response = user_client.get(reverse("applications:list"))

    assert b"SWE Intern" in response.content
    assert b"Closed" in response.content


# --- Inline status changes -------------------------------------------------------------

def test_status_change_updates_status_and_records_history(user_client, user):
    application, _ = track_listing(user, make_listing())

    response = user_client.post(reverse("applications:update_status", args=[application.pk]), {"status": "OA"})

    assert response.status_code == 200
    assert b"<tr" in response.content  # The updated row, for HTMX to swap in.
    application.refresh_from_db()
    assert application.status == "OA"
    assert application.applied_at is not None  # Skipping APPLIED still counts as applied.
    last = StatusChange.objects.filter(application=application).last()
    assert (last.from_status, last.to_status) == ("SAVED", "OA")


def test_same_status_does_not_record_a_change(user):
    application, _ = track_listing(user, make_listing())

    assert change_status(application, "SAVED") is False
    assert application.status_changes.count() == 1  # Only the initial "tracked" entry.


def test_applied_at_is_not_overwritten_by_later_changes(user):
    application, _ = track_listing(user, make_listing())
    change_status(application, "APPLIED")
    first_applied_at = application.applied_at

    change_status(application, "INTERVIEW")

    assert application.applied_at == first_applied_at


def test_cannot_change_another_users_application(user_client):
    other_app, _ = track_listing(User.objects.create_user("other"), make_listing())

    response = user_client.post(reverse("applications:update_status", args=[other_app.pk]), {"status": "OFFER"})

    assert response.status_code == 404
    other_app.refresh_from_db()
    assert other_app.status == "SAVED"


def test_invalid_status_is_rejected(user_client, user):
    application, _ = track_listing(user, make_listing())

    response = user_client.post(reverse("applications:update_status", args=[application.pk]), {"status": "HIRED!!"})

    assert response.status_code == 400
    assert Application.objects.get().status == "SAVED"
