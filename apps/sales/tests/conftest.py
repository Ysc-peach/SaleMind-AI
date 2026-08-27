"""Shared fixtures for sales domain tests."""

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import UserRole


@pytest.fixture
def make_user():
    """Create a user with a unique username and email."""

    sequence = 0

    def factory(role=UserRole.SALES):
        nonlocal sequence
        sequence += 1
        return get_user_model().objects.create_user(
            username=f"user-{sequence}",
            email=f"user-{sequence}@example.com",
            role=role,
            password="StrongPassword123!",
        )

    return factory
