import re
from datetime import timedelta

from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import Listing

STATE_CODE = re.compile(r"^[A-Za-z]{2}$")


class ListingFilterForm(forms.Form):
    POSTED_WITHIN_CHOICES = [
        ("", "Any time"),
        (1, "Last 24 hours"),
        (3, "Last 3 days"),
        (7, "Last 7 days"),
        (30, "Last 30 days"),
    ]

    q = forms.CharField(
        required=False,
        label="Search",
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Company or title"}),
    )
    location = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "Denver, Remote, CO…"}),
    )
    category = forms.ChoiceField(required=False)
    posted_within = forms.TypedChoiceField(
        required=False, coerce=int, empty_value=None, choices=POSTED_WITHIN_CHOICES, label="Posted"
    )
    hide_tracked = forms.BooleanField(required=False, label="Hide ones I've tracked")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Categories come from the data, so a new upstream category shows up automatically.
        categories = (
            Listing.objects.filter(is_active=True)
            .exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        self.fields["category"].choices = [("", "All categories")] + [(c, c) for c in categories]

    def filter_queryset(self, queryset, user):
        """Apply the submitted filters. Invalid input is ignored rather than erroring."""
        if not self.is_valid():
            return queryset
        data = self.cleaned_data

        if data["q"]:
            queryset = queryset.filter(Q(company__icontains=data["q"]) | Q(title__icontains=data["q"]))

        if location := data["location"].strip():
            queryset = queryset.filter(location_query(location))

        if data["category"]:
            queryset = queryset.filter(category=data["category"])

        if data["posted_within"]:
            queryset = queryset.filter(date_posted__gte=timezone.now() - timedelta(days=data["posted_within"]))

        if data["hide_tracked"] and user.is_authenticated:
            queryset = queryset.exclude(applications__user=user)

        return queryset


def location_query(text):
    """Build a filter for the `locations` JSON list.

    `icontains` on a JSONField searches the list's JSON text, e.g. '["Denver, CO"]'.
    A plain substring match for a state code like "CO" would also hit "San Francisco",
    so a two-letter query is matched as a state suffix instead: ', CO"'.
    """
    if STATE_CODE.match(text):
        return Q(locations__icontains=f', {text.upper()}"')
    return Q(locations__icontains=text)
