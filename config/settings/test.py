"""Test settings backed by the configured PostgreSQL database."""

import os


# Test secrets are deterministic for repeatability, but real environment values
# still win when a test runner supplies them. DATABASE_URL intentionally has no
# fallback: tests must exercise PostgreSQL rather than silently using SQLite.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-django-secret-key")
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-signing-key-at-least-32-bytes-long")

from .base import *  # noqa: E402,F401,F403


DEBUG = False

# Automated tests must never inherit real verifier credentials or make external
# model calls from a developer's local environment.
VERIFIER_PROVIDER = ""
VERIFIER_MODEL = ""
VERIFIER_API_KEY = ""
VERIFIER_BASE_URL = ""

DATABASES["default"].setdefault("TEST", {})["TEMPLATE"] = env(
    "TEST_DATABASE_TEMPLATE",
    default="salesmind_test_template",
)
