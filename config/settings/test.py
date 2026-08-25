"""Test settings backed by the configured PostgreSQL database."""

import os


# Test secrets are deterministic for repeatability, but real environment values
# still win when a test runner supplies them. DATABASE_URL intentionally has no
# fallback: tests must exercise PostgreSQL rather than silently using SQLite.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-django-secret-key")
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-signing-key")

from .base import *  # noqa: E402,F401,F403


DEBUG = False
