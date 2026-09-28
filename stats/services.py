"""Market and personal statistics, computed with database aggregation.

Counting, grouping by week, and date subtraction happen in SQL. Two things are
finished in Python on small value lists, because there's no portable ORM way to
do them on both SQLite and PostgreSQL:
- medians (PostgreSQL has percentile_cont, SQLite has no median at all);
- counting individual locations (they live inside a JSON list, and unnesting JSON
  arrays needs database-specific SQL: jsonb_array_elements vs. json_each).
"""

from collections import Counter
from statistics import median

from django.db.models import Count, DurationField, Exists, ExpressionWrapper, F, Min, OuterRef, Q
from django.db.models.functions import TruncWeek

from applications.models import Application, StatusChange
from listings.models import Listing

TOP_N = 10

# An application has "reached" a stage if it was ever moved to that stage or a later one
# (so jumping straight from Applied to Interview still counts as passing the OA stage).
REACHED = {
    "oa": ["OA", "INTERVIEW", "OFFER"],
    "interview": ["INTERVIEW", "OFFER"],
    "offer": ["OFFER"],
}


def market_stats():
    listings = Listing.objects.all()
    active = listings.filter(is_active=True)

    weekly = (
        listings.annotate(week=TruncWeek("date_posted"))
        .values("week")
        .annotate(count=Count("id"))
        .order_by("week")
    )
    top_companies = active.values("company").annotate(count=Count("id")).order_by("-count", "company")[:TOP_N]
    location_counts = Counter(
        location for locations in active.values_list("locations", flat=True) for location in locations
    )

    # Only postings we saw open and then saw close. Ones that were already closed at
    # first sight have closed_at == first_seen_at and are excluded.
    open_durations = list(
        listings.filter(is_active=False, closed_at__gt=F("first_seen_at"))
        .annotate(open_for=ExpressionWrapper(F("closed_at") - F("first_seen_at"), output_field=DurationField()))
        .values_list("open_for", flat=True)
    )

    return {
        "active_count": active.count(),
        "weekly_postings": chart_data([(row["week"], row["count"]) for row in weekly], date_labels=True),
        "top_companies": chart_data([(row["company"], row["count"]) for row in top_companies]),
        "top_locations": location_counts.most_common(TOP_N),
        "median_days_open": median_days(open_durations),
        "closed_sample_size": len(open_durations),
    }


def personal_stats(user):
    applications = Application.objects.filter(user=user)

    def reached(stage):
        # True if the application's current status or any past status is at/after the stage.
        history = StatusChange.objects.filter(application=OuterRef("pk"), to_status__in=REACHED[stage])
        return Q(status__in=REACHED[stage]) | Q(Exists(history))

    # One query returns every funnel count.
    counts = applications.aggregate(
        tracked=Count("id"),
        applied=Count("id", filter=Q(applied_at__isnull=False)),
        oa=Count("id", filter=reached("oa")),
        interview=Count("id", filter=reached("interview")),
        offer=Count("id", filter=reached("offer")),
    )

    funnel = []
    previous = None
    for key, label in [("applied", "Applied"), ("oa", "OA"), ("interview", "Interview"), ("offer", "Offer")]:
        count = counts[key]
        rate = round(100 * count / previous) if previous else None
        funnel.append({"label": label, "count": count, "rate_from_previous": rate})
        previous = count

    # Time from applying to the first move to OA, subtracted in SQL.
    waits = list(
        applications.filter(applied_at__isnull=False)
        .annotate(first_oa=Min("status_changes__changed_at", filter=Q(status_changes__to_status="OA")))
        .filter(first_oa__gt=F("applied_at"))
        .annotate(wait=ExpressionWrapper(F("first_oa") - F("applied_at"), output_field=DurationField()))
        .values_list("wait", flat=True)
    )

    weekly = (
        applications.filter(applied_at__isnull=False)
        .annotate(week=TruncWeek("applied_at"))
        .values("week")
        .annotate(count=Count("id"))
        .order_by("week")
    )

    return {
        "tracked": counts["tracked"],
        "funnel": funnel,
        "median_days_to_oa": median_days(waits),
        "oa_sample_size": len(waits),
        "weekly_applications": chart_data([(row["week"], row["count"]) for row in weekly], date_labels=True),
    }


# --- Helpers ------------------------------------------------------------------------

def median_days(durations):
    days = [d.total_seconds() / 86400 for d in durations]
    return round(median(days), 1) if days else None


def chart_data(pairs, date_labels=False):
    """[(label, value), ...] -> labels/values lists for Chart.js, plus rows for the data table."""
    labels = [f"{label:%b} {label.day}" if date_labels else label for label, _ in pairs]
    values = [value for _, value in pairs]
    return {"labels": labels, "values": values, "rows": list(zip(labels, values))}
