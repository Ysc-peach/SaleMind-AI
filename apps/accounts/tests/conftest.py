"""Shared accounts test fixtures."""

import pytest

from apps.accounts.models import UserRole


@pytest.fixture
def user_data():
    return {
        "username": "alice",
        "email": "alice@example.com",
        "role": UserRole.SALES,
        "password": "StrongPassword123!",
    }
