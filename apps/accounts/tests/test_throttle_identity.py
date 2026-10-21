"""Anonymous throttle identity must not be the client-supplied X-Forwarded-For.

DRF 3.18 falls back to the whole header string when ``NUM_PROXIES`` is unset,
so a client could mint a fresh bucket per request. These tests pin both the
configuration surface and the resulting bucket behaviour.
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserRole


LOGIN_URL = "/api/auth/login/"
REFRESH_URL = "/api/auth/refresh/"
WRONG = {"username": "nobody", "password": "wrong-password"}


@pytest.fixture
def user(user_data):
    return get_user_model().objects.create_user(**user_data)


def _lower(monkeypatch, scope, rate):
    monkeypatch.setitem(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], scope, rate)


def _login(client, forwarded_for):
    return client.post(
        LOGIN_URL, WRONG, format="json", HTTP_X_FORWARDED_FOR=forwarded_for,
    )


def test_base_settings_wire_num_proxies():
    from config.settings import base as base_settings

    assert "NUM_PROXIES" in base_settings.REST_FRAMEWORK


def test_effective_num_proxies_matches_a_single_trusted_proxy():
    assert settings.REST_FRAMEWORK.get("NUM_PROXIES") == 1


def test_production_rejects_missing_proxy_hops(monkeypatch):
    from config.settings.env_checks import require_proxy_hops

    monkeypatch.delenv("DRF_NUM_PROXIES", raising=False)

    with pytest.raises(ImproperlyConfigured):
        require_proxy_hops()


@pytest.mark.parametrize("value", ["", "0", "-1", "two", "1.5"])
def test_production_rejects_invalid_proxy_hops(monkeypatch, value):
    from config.settings.env_checks import require_proxy_hops

    monkeypatch.setenv("DRF_NUM_PROXIES", value)

    with pytest.raises(ImproperlyConfigured):
        require_proxy_hops()


@pytest.mark.django_db
def test_spoofed_prefix_cannot_open_a_new_anonymous_bucket(monkeypatch):
    _lower(monkeypatch, "login", "2/min")
    client = APIClient()

    for spoof in ("1.1.1.1", "3.3.3.3"):
        assert _login(client, f"{spoof}, 10.0.0.5").status_code == 401

    assert _login(client, "4.4.4.4, 10.0.0.5").status_code == 429


@pytest.mark.django_db
def test_distinct_proxy_segments_keep_distinct_buckets(monkeypatch):
    _lower(monkeypatch, "login", "2/min")
    client = APIClient()

    for hop in ("10.0.0.5", "10.0.0.6"):
        assert _login(client, f"1.1.1.1, {hop}").status_code == 401


@pytest.mark.django_db
def test_authenticated_generation_ignores_forwarded_for(monkeypatch, user):
    from apps.sales.models import Customer, Opportunity, OpportunityStatus

    _lower(monkeypatch, "solution_generation", "2/min")
    customer = Customer.objects.create(name="Identity customer", created_by=user)
    opportunity = Opportunity.objects.create(
        project_name="Identity opportunity",
        customer=customer,
        sales_owner=user,
        created_by=user,
        raw_requirement="客户需要私有化部署。",
        status=OpportunityStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)
    url = f"/api/opportunities/{opportunity.pk}/solution-drafts/"

    for spoof in ("1.1.1.1", "2.2.2.2"):
        response = client.post(
            url, {"analysis_id": 999999}, format="json",
            HTTP_X_FORWARDED_FOR=f"{spoof}, 10.0.0.5",
        )
        assert response.status_code == 400

    response = client.post(
        url, {"analysis_id": 999999}, format="json",
        HTTP_X_FORWARDED_FOR="3.3.3.3, 10.0.0.5",
    )

    assert response.status_code == 429


@pytest.mark.django_db
def test_login_exhaustion_does_not_block_a_valid_refresh(monkeypatch, user):
    _lower(monkeypatch, "login", "1/min")
    client = APIClient()
    assert _login(client, "10.0.0.5").status_code == 401
    assert _login(client, "10.0.0.5").status_code == 429

    response = client.post(
        REFRESH_URL, {"refresh": str(RefreshToken.for_user(user))}, format="json",
        HTTP_X_FORWARDED_FOR="10.0.0.5",
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_refresh_has_its_own_scope_with_the_structured_code(monkeypatch, user):
    _lower(monkeypatch, "token_refresh", "2/min")
    client = APIClient()
    token = str(RefreshToken.for_user(user))

    for _ in range(2):
        assert client.post(REFRESH_URL, {"refresh": token}, format="json").status_code == 200

    response = client.post(REFRESH_URL, {"refresh": token}, format="json")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
