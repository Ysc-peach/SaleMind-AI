"""Anonymous login and provider-backed generation enforce a scoped rate limit."""

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import Customer, Opportunity, OpportunityStatus


pytestmark = pytest.mark.django_db


def _lower_rate(monkeypatch, scope, rate):
    """Shrink one scope in place.

    ``SimpleRateThrottle.THROTTLE_RATES`` is bound to the dict object at import
    time, so replacing ``settings.REST_FRAMEWORK`` would not reach the throttle.
    """

    monkeypatch.setitem(settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], scope, rate)


def test_login_burst_returns_a_structured_rate_limit(monkeypatch):
    _lower_rate(monkeypatch, "login", "2/min")
    client = APIClient()

    for _ in range(2):
        response = client.post(
            "/api/auth/login/",
            {"username": "nobody", "password": "wrong-password"},
            format="json",
        )
        assert response.status_code == 401

    response = client.post(
        "/api/auth/login/",
        {"username": "nobody", "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == 429
    payload = response.json()
    assert payload["code"] == "rate_limited"
    assert payload["retry_after_seconds"] >= 1
    assert response["Retry-After"]


def test_login_within_the_rate_is_not_throttled(monkeypatch):
    _lower_rate(monkeypatch, "login", "5/min")
    client = APIClient()

    for _ in range(2):
        response = client.post(
            "/api/auth/login/",
            {"username": "nobody", "password": "wrong-password"},
            format="json",
        )
        assert response.status_code == 401


def test_solution_generation_burst_is_rate_limited_before_any_generation(monkeypatch, make_user):
    _lower_rate(monkeypatch, "solution_generation", "2/min")
    owner = make_user(UserRole.SALES)
    customer = Customer.objects.create(name="Rate customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Rate opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
        raw_requirement="客户需要私有化部署。",
        status=OpportunityStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = f"/api/opportunities/{opportunity.pk}/solution-drafts/"

    for _ in range(2):
        response = client.post(url, {"analysis_id": 999999}, format="json")
        # The analysis does not exist, so nothing is generated; the request is
        # still counted by the throttle.
        assert response.status_code == 400

    response = client.post(url, {"analysis_id": 999999}, format="json")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"


def test_solution_draft_reads_are_not_metered_by_the_generation_scope(monkeypatch, make_user):
    _lower_rate(monkeypatch, "solution_generation", "1/min")
    owner = make_user(UserRole.SALES)
    customer = Customer.objects.create(name="Read customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Read opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
        raw_requirement="客户需要私有化部署。",
        status=OpportunityStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(owner)
    url = f"/api/opportunities/{opportunity.pk}/solution-drafts/"

    for _ in range(3):
        response = client.get(url)
        assert response.status_code == 200
