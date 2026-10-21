"""Environment checks shared by the settings modules."""

import os

from django.core.exceptions import ImproperlyConfigured


def require_proxy_hops(name: str = "DRF_NUM_PROXIES") -> int:
    """Return the trusted proxy hop count, or fail closed.

    The value must equal the number of reverse proxies between the client and
    this process. Too small merges every client behind the nearest proxy into a
    single rate-limit bucket; too large reads the client-supplied segment of
    ``X-Forwarded-For`` and reopens the spoofing hole.
    """

    raw = os.environ.get(name, "").strip()
    if not raw.isdigit() or int(raw) < 1:
        raise ImproperlyConfigured(
            f"{name} must be a positive integer equal to the number of trusted "
            "reverse proxies. Too small merges every client into one bucket; too "
            "large reads the client-supplied X-Forwarded-For segment."
        )
    return int(raw)
