from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def age(value):
    """Compact age of a datetime: '45m', '5h', '2d', '3w'."""
    if not value:
        return ""
    seconds = max((timezone.now() - value).total_seconds(), 0)
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 14:
        return f"{days}d"
    return f"{days // 7}w"
