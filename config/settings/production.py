"""Deployment settings with fail-closed security defaults."""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .env_checks import require_proxy_hops


DEBUG = False

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must contain at least one host in production")

if not CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured(
        "DJANGO_CSRF_TRUSTED_ORIGINS must contain at least one origin in production"
    )

# Rate limits are a security control, not a developer convenience: a silent
# default in production would be indistinguishable from an intentional value.
_THROTTLE_ENV_VARS = (
    "THROTTLE_ANON_RATE",
    "THROTTLE_USER_RATE",
    "THROTTLE_LOGIN_RATE",
    "THROTTLE_TOKEN_REFRESH_RATE",
    "THROTTLE_SOLUTION_GENERATION_RATE",
    "THROTTLE_REQUIREMENT_ANALYSIS_RATE",
    "THROTTLE_RAG_ANSWER_RATE",
    "THROTTLE_KNOWLEDGE_WRITE_RATE",
)
_missing_throttle_rates = [
    name for name in _THROTTLE_ENV_VARS if not os.environ.get(name, "").strip()
]
if _missing_throttle_rates:
    raise ImproperlyConfigured(
        "Production requires explicit throttle rates: "
        + ", ".join(_missing_throttle_rates)
    )

# Anonymous buckets key on the client address, so the proxy hop count decides
# which X-Forwarded-For segment is trusted. It has no safe default.
require_proxy_hops()

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# An intranet deployment without TLS is a supported but explicitly opt-in
# mode. It must be requested by name, so a missing proxy or certificate can
# never silently downgrade transport security.
if os.environ.get("DJANGO_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes"}:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
