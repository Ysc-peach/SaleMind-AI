"""Stable API error envelope for throttled requests and database conflicts."""

from django.db import IntegrityError
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Keep DRF defaults, and add two machine-readable codes.

    The default ``{"detail": ...}`` payload has no code, so a client cannot tell
    a rate limit from other 429-shaped failures. ``Retry-After`` is preserved.

    A unique or check constraint violation is a client-visible conflict, not an
    internal error: the default path turns it into an opaque 500. The constraint
    name and driver message are never returned.
    """

    if isinstance(exc, IntegrityError):
        return Response(
            {
                "code": "conflict",
                "message": "The resource conflicts with the current state.",
            },
            status=409,
        )

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
