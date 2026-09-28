from django.shortcuts import render

from .services import market_stats, personal_stats


def stats(request):
    """Market stats are public; the personal funnel is shown only when logged in."""
    context = {"market": market_stats()}
    if request.user.is_authenticated:
        context["personal"] = personal_stats(request.user)
    return render(request, "stats/stats.html", context)
