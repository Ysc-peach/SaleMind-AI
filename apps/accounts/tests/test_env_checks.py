"""Production must not silently fall back to the generation model as verifier."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings.env_checks import require_independent_verifier


BASE = {
    "verifier_provider": "deepseek",
    "verifier_model": "deepseek-flash",
    "verifier_base_url": "https://api.deepseek.com",
    "llm_provider": "deepseek",
    "llm_model": "deepseek-v4-flash",
}


def test_a_distinct_verifier_model_is_accepted():
    require_independent_verifier(**BASE)


@pytest.mark.parametrize(
    "missing",
    ["verifier_provider", "verifier_model", "verifier_base_url"],
)
def test_a_missing_verifier_setting_fails_closed(missing):
    with pytest.raises(ImproperlyConfigured, match=missing.upper()):
        require_independent_verifier(**{**BASE, missing: ""})


def test_reusing_the_generation_model_fails_closed():
    with pytest.raises(ImproperlyConfigured, match="must not reuse"):
        require_independent_verifier(**{**BASE, "verifier_model": BASE["llm_model"]})


def test_a_different_provider_with_the_same_model_name_is_allowed():
    # Provider identity is part of independence; only the exact pair is reused.
    require_independent_verifier(**{**BASE, "verifier_provider": "qwen"})
