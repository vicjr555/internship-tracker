from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from applications.models import Application, StatusChange
from applications.services import change_status, track_listing
from listings.models import Listing
from stats.services import market_stats, personal_stats

pytestmark = pytest.mark.django_db


def make_listing(external_id, **overrides):
    now = timezone.now()
    fields = {"company": "Acme", "title": "SWE Intern", "url": f"https://example.com/{external_id}",
              "date_posted": now, "date_updated": now, "locations": ["Denver, CO"]}
    fields.update(overrides)
    return Listing.objects.create(external_id=external_id, **fields)


def move(application, status, days_after_start):
    """Change status, then backdate the change so timings are deterministic."""
    change_status(application, status)
    when = timezone.now() - timedelta(days=30) + timedelta(days=days_after_start)
    StatusChange.objects.filter(application=application, to_status=status).update(changed_at=when)
    if status == "APPLIED":
        Application.objects.filter(pk=application.pk).update(applied_at=when)
        application.refresh_from_db()


# --- Market -------------------------------------------------------------------------

def test_top_companies_and_locations_count_only_open_postings():
    make_listing("a", company="Stripe", locations=["SF", "Remote in USA"])
    make_listing("b", company="Stripe", locations=["SF"])
    make_listing("c", company="Globex", locations=["Denver, CO"])
    make_listing("d", company="Closed Co", is_active=False, closed_at=timezone.now())

    stats = market_stats()

    assert stats["top_companies"]["rows"][0] == ("Stripe", 2)
    assert "Closed Co" not in stats["top_companies"]["labels"]
    assert stats["top_locations"][0] == ("SF", 2)


def test_postings_per_week_groups_by_week():
    now = timezone.now()
    make_listing("a", date_posted=now)
    make_listing("b", date_posted=now)
    make_listing("c", date_posted=now - timedelta(weeks=2))

    values = market_stats()["weekly_postings"]["values"]

    assert sorted(values) == [1, 2]


def test_median_days_open_uses_only_postings_seen_open_then_closed():
    now = timezone.now()
    make_listing("a", is_active=False, first_seen_at=now - timedelta(days=4), closed_at=now)
    make_listing("b", is_active=False, first_seen_at=now - timedelta(days=10), closed_at=now)
    make_listing("c", is_active=False, first_seen_at=now - timedelta(days=6), closed_at=now)
    # Closed when we first saw it: excluded (closed_at == first_seen_at).
    make_listing("d", is_active=False, first_seen_at=now, closed_at=now)

    stats = market_stats()

    assert stats["median_days_open"] == 6.0
    assert stats["closed_sample_size"] == 3


def test_median_is_none_without_data():
    assert market_stats()["median_days_open"] is None


# --- Personal -------------------------------------------------------------------------

@pytest.fixture
def user():
    return User.objects.create_user("student")


def test_funnel_counts_and_conversion_rates(user):
    apps = [track_listing(user, make_listing(f"l{i}"))[0] for i in range(4)]
    for app in apps:
        move(app, "APPLIED", 0)
    move(apps[0], "OA", 3)
    move(apps[1], "OA", 5)
    move(apps[1], "INTERVIEW", 10)
    move(apps[2], "INTERVIEW", 7)  # Skipped OA: still counts as passing that stage.
    move(apps[2], "REJECTED", 12)  # Rejected later: still reached Interview.

    funnel = {stage["label"]: stage for stage in personal_stats(user)["funnel"]}

    assert [funnel[s]["count"] for s in ["Applied", "OA", "Interview", "Offer"]] == [4, 3, 2, 0]
    assert funnel["OA"]["rate_from_previous"] == 75
    assert funnel["Interview"]["rate_from_previous"] == 67
    assert funnel["Applied"]["rate_from_previous"] is None


def test_median_days_from_applied_to_oa(user):
    apps = [track_listing(user, make_listing(f"l{i}"))[0] for i in range(3)]
    for app in apps:
        move(app, "APPLIED", 0)
    move(apps[0], "OA", 2)
    move(apps[1], "OA", 4)
    move(apps[2], "OA", 9)

    stats = personal_stats(user)

    assert stats["median_days_to_oa"] == 4.0
    assert stats["oa_sample_size"] == 3


def test_personal_stats_only_include_the_users_applications(user):
    other = User.objects.create_user("other")
    app, _ = track_listing(other, make_listing("a"))
    change_status(app, "APPLIED")

    assert personal_stats(user)["tracked"] == 0


def test_personal_stats_use_a_fixed_number_of_queries(user, django_assert_max_num_queries):
    for i in range(20):
        app, _ = track_listing(user, make_listing(f"l{i}"))
        change_status(app, "APPLIED")

    # Aggregation in the database: the query count doesn't grow with the number of applications.
    with django_assert_max_num_queries(3):
        personal_stats(user)


# --- Page ---------------------------------------------------------------------------------

def test_stats_page_is_public_but_hides_personal_section(client):
    make_listing("a")

    response = client.get(reverse("stats:stats"))

    assert response.status_code == 200
    assert "personal" not in response.context
    assert b"to see your application funnel" in response.content


def test_stats_page_shows_personal_section_when_logged_in(client, user):
    client.force_login(user)

    response = client.get(reverse("stats:stats"))

    assert response.status_code == 200
    assert "personal" in response.context
