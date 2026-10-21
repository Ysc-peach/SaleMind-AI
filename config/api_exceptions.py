"""Stable API error envelope for throttled requests."""

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Keep DRF defaults, but expose a machine-readable throttling code.

    The default ``{"detail": ...}`` payload has no code, so a client cannot tell
    a rate limit from other 429-shaped failures. ``Retry-After`` is preserved.
    """

    response = exception_handler(exc, context)
    if isinstance(exc, Throttled) and response is not None:
        retry_after = response.get("Retry-After")
        payload = {
            "code": "rate_limited",
            "message": "Too many requests. Retry later.",
        }
        if retry_after is not None:
            payload["retry_after_seconds"] = int(retry_after)
        response.data = payload
    return response
