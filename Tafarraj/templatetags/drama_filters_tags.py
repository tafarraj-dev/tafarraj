# tafarraj/templatetags/drama_filters_tags.py
#
# USAGE in templates:
#   {% load drama_filters_tags %}
#   {% url_replace request 'page' 3 %}        → current URL with page=3
#   {% url_replace request 'countries' 'korean' %}  → current URL with countries=korean
#   {% url_replace request 'countries' '' %}   → current URL with countries removed
#
# This replaces ALL manual ?key=value&search={{ search }}&... chains in the template.

from django import template
from urllib.parse import urlencode

register = template.Library()


@register.simple_tag
def url_replace(request, key, value):
    """
    Return the current query string with one key replaced/added/removed.
    Empty string value = remove the key entirely.
    """
    params = request.GET.copy()

    if value == '' or value is None:
        params.pop(key, None)
    else:
        params[key] = value

    encoded = params.urlencode()
    return f'?{encoded}' if encoded else '?'