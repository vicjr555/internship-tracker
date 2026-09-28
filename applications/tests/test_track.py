import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from applications.models import Application, StatusChange
from listings.models import Listing

pytestmark = pytest.mark.django_db


@pytest.fixture
def listing():
    now = timezone.now()
    return Listing.objects.create(
        external_id="a", company="Acme", title="SWE Intern", url="https://example.com/a",
        date_posted=now, date_updated=now,
    )


@pytest.fixture
def user_client(client):
    client.force_login(User.objects.create_user("student"))
    return client


def test_track_creates_saved_application_and_history(user_client, listing):
    response = user_client.post(reverse("applications:track", args=[listing.pk]))

    assert response.status_code == 200
    assert b"Tracked" in response.content
    application = Application.objects.get()
    assert application.status == Application.Status.SAVED
    assert StatusChange.objects.get().to_status == Application.Status.SAVED


def test_tracking_twice_does_not_duplicate(user_client, listing):
    url = reverse("applications:track", args=[listing.pk])
    user_client.post(url)
    user_client.post(url)

    assert Application.objects.count() == 1
    assert StatusChange.objects.count() == 1


def test_track_requires_post(user_client, listing):
    response = user_client.get(reverse("applications:track", args=[listing.pk]))

    assert response.status_code == 405
    assert Application.objects.count() == 0
