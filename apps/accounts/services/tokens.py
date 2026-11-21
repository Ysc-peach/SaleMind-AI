"""Revoking every live session a user holds.

A refresh token is a seven-day credential. Anything that changes what a session
is allowed to do — a password change, a role change, deactivation — has to kill
those tokens, otherwise the change applies only to the next sign-in and the old
device keeps the old rights.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def revoke_outstanding_tokens(user) -> int:
    """Blacklist every unexpired refresh token for one user. Returns the count."""

    now = timezone.now()
    revoked = 0
    for token in OutstandingToken.objects.filter(user=user, expires_at__gt=now):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        revoked += int(created)
    return revoked
