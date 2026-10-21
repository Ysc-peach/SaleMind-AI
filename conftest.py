"""Project-wide test fixtures."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def clear_rate_limit_cache():
    """Throttle counters are process-wide; never leak them between tests."""

    cache.clear()
    yield
    cache.clear()
