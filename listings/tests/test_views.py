from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from applications.models import Application
from listings.models import Listing, SyncRun

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_sync():
    """Mark the data as just synced so page loads don't trigger a lazy refresh."""
    SyncRun.objects.create(status=SyncRun.Status.SUCCESS, finished_at=timezone.now())


def make_listing(external_id, days_old=1, **overrides):
    posted = timezone.now() - timedelta(days=days_old)
    fields = {
        "company": "Acme",
        "title": "Software Engineer Intern",
        "locations": ["Denver, CO"],
        "url": f"https://example.com/{external_id}",
        "category": "Software",
        "date_posted": posted,
        "date_updated": posted,
    }
    fields.update(overrides)
    return Listing.objects.create(external_id=external_id, **fields)


def get_list(client, **params):
    return client.get(reverse("listings:list"), params)


def shown_ids(response):
    return {listing.external_id for listing in response.context["page"].object_list}


def test_listings_page_loads_for_anonymous_users(client):
    make_listing("a")

    response = get_list(client)

    assert response.status_code == 200
    assert b"Software Engineer Intern" in response.content


def test_only_active_listings_are_shown(client):
    make_listing("open")
    make_listing("closed", is_active=False, closed_at=timezone.now())

    assert shown_ids(get_list(client)) == {"open"}


def test_newest_first(client):
    make_listing("old", days_old=10)
    make_listing("new", days_old=1)

    page = get_list(client).context["page"]

    assert [listing.external_id for listing in page.object_list] == ["new", "old"]


def test_keyword_search_matches_company_or_title(client):
    make_listing("a", company="Stripe")
    make_listing("b", title="Quant Research Intern")
    make_listing("c")

    assert shown_ids(get_list(client, q="stripe")) == {"a"}
    assert shown_ids(get_list(client, q="quant")) == {"b"}


def test_location_filter(client):
    make_listing("denver", locations=["Denver, CO"])
    make_listing("sf", locations=["San Francisco, CA"])
    make_listing("remote", locations=["Remote in USA"])

    assert shown_ids(get_list(client, location="remote")) == {"remote"}
    assert shown_ids(get_list(client, location="denver")) == {"denver"}
    # "CO" is a state code: it must not match "San Francisco".
    assert shown_ids(get_list(client, location="CO")) == {"denver"}


def test_category_and_posted_within_filters(client):
    make_listing("hw-recent", category="Hardware", days_old=1)
    make_listing("hw-old", category="Hardware", days_old=20)
    make_listing("sw-recent", category="Software", days_old=1)

    assert shown_ids(get_list(client, category="Hardware")) == {"hw-recent", "hw-old"}
    assert shown_ids(get_list(client, category="Hardware", posted_within=3)) == {"hw-recent"}


def test_hide_tracked(client):
    user = User.objects.create_user("student")
    tracked = make_listing("tracked")
    make_listing("untracked")
    Application.objects.create(user=user, listing=tracked)
    client.force_login(user)

    assert shown_ids(get_list(client)) == {"tracked", "untracked"}
    assert shown_ids(get_list(client, hide_tracked="on")) == {"untracked"}


def test_paginates_50_per_page(client):
    for i in range(51):
        make_listing(f"id-{i}")

    first = get_list(client)
    second = get_list(client, page=2)

    assert len(first.context["page"].object_list) == 50
    assert len(second.context["page"].object_list) == 1


def test_new_badge_only_for_recently_first_seen(client):
    make_listing("fresh")
    make_listing("stale", first_seen_at=timezone.now() - timedelta(days=3))

    content = get_list(client).content.decode()

    assert content.count(">NEW<") == 1


def test_htmx_request_returns_only_the_results_partial(client):
    make_listing("a")

    response = client.get(reverse("listings:list"), headers={"HX-Request": "true"})

    assert b"<html" not in response.content
    assert b"Software Engineer Intern" in response.content
