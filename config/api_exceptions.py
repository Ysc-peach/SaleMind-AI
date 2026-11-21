"""Stable API error envelope for throttled requests and database conflicts."""

from django.db import IntegrityError
from rest_framework.exceptions import APIException, Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler

#: Refusals whose code the client is expected to branch on.
_CODED_REFUSALS = frozenset(
    {
        # An archived record: ask an administrator to restore it.
        "record_inactive",
        # A negative claim about a third party: cite their own words instead.
        "competitor_negative_claim",
        # A quote priced against a superseded draft version: re-price first.
        "quote_outdated",
        # A quote was asked for on an opportunity that has none.
        "quote_missing",
        # Nothing to price yet: generate a solution version first.
        "quote_no_draft",
        # A discount above the authorised threshold has no administrator decision.
        "discount_not_approved",
    }
)


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

    # A few refusals carry a rule the client has to explain to a person, so they
    # get the same code/message envelope as a constraint conflict instead of a
    # bare detail string. Matched on the declared code rather than the class, to
    # keep this module free of app imports.
    if isinstance(exc, APIException) and getattr(
        exc, "default_code", ""
    ) in _CODED_REFUSALS:
        return Response(
            {"code": exc.default_code, "message": str(exc.detail)},
            status=exc.status_code,
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
