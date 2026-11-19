"""Competitors and public statements: who writes, who approves, what is refused."""

import pytest

from apps.accounts.models import UserRole
from apps.sales.models import (
    Competitor,
    CompetitorStatement,
    CompetitorStatementStatus,
)

pytestmark = pytest.mark.django_db

COMPETITORS_URL = "/api/competitors/"

STATEMENT = {
    "dimension": "deployment",
    "statement": "支持私有化部署与容器化交付",
    "source_url": "https://example.com/product/deployment",
    "published_on": "2026-06-01",
}


def _competitor(api_client, user, name="竞品甲"):
    api_client.force_authenticate(user=user)
    return api_client.post(COMPETITORS_URL, {"name": name}, format="json")


def _statement(api_client, competitor_id, **overrides):
    body = dict(STATEMENT)
    body.update(overrides)
    return api_client.post(
        f"{COMPETITORS_URL}{competitor_id}/statements/", body, format="json"
    )


def test_presales_registers_a_competitor(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)

    response = _competitor(api_client, presales, name="  竞品甲  ")

    assert response.status_code == 201
    assert response.data["name"] == "竞品甲"
    assert response.data["is_active"] is True


def test_a_seller_cannot_register_a_competitor(api_client, user_factory):
    response = _competitor(api_client, user_factory(UserRole.SALES))

    assert response.status_code == 403
    assert Competitor.objects.count() == 0


def test_a_duplicate_name_is_refused(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    _competitor(api_client, presales, name="竞品甲")

    # The same competitor typed twice must not become two rows: a comparison
    # table has to be able to point at one identity.
    duplicate = _competitor(api_client, presales, name="竞品甲")

    assert duplicate.status_code == 400
    assert Competitor.objects.count() == 1


def test_a_statement_starts_as_proposed(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]

    response = _statement(api_client, competitor_id)

    assert response.status_code == 201
    assert response.data["status"] == "proposed"
    assert response.data["reviewed_by_name"] == ""


def test_a_negative_claim_is_refused(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]

    response = _statement(
        api_client, competitor_id, statement="不支持私有化部署"
    )

    assert response.status_code == 400
    assert response.data["code"] == "competitor_negative_claim"
    assert CompetitorStatement.objects.count() == 0


def test_a_statement_needs_an_http_source(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]

    missing = _statement(api_client, competitor_id, source_url="")
    bad_scheme = _statement(
        api_client, competitor_id, source_url="ftp://example.com/page"
    )

    assert missing.status_code == 400
    assert bad_scheme.status_code == 400


def test_an_unknown_dimension_is_refused(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]

    response = _statement(api_client, competitor_id, dimension="pricing")

    assert response.status_code == 400


def test_only_an_admin_can_approve(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]
    statement_id = _statement(api_client, competitor_id).data["id"]

    refused = api_client.post(
        f"/api/competitor-statements/{statement_id}/approve/"
    )

    admin = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=admin)
    allowed = api_client.post(
        f"/api/competitor-statements/{statement_id}/approve/"
    )

    assert refused.status_code == 403
    assert allowed.status_code == 200
    assert allowed.data["status"] == "approved"
    assert allowed.data["reviewed_by_name"] != ""
    assert allowed.data["reviewed_at"] is not None


def test_approving_twice_is_idempotent(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    admin = user_factory(UserRole.ADMIN)
    competitor_id = _competitor(api_client, presales).data["id"]
    statement_id = _statement(api_client, competitor_id).data["id"]

    api_client.force_authenticate(user=admin)
    first = api_client.post(f"/api/competitor-statements/{statement_id}/approve/")
    second = api_client.post(f"/api/competitor-statements/{statement_id}/approve/")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.data["reviewed_at"] == second.data["reviewed_at"]


def test_rejecting_records_the_decision(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    admin = user_factory(UserRole.ADMIN)
    competitor_id = _competitor(api_client, presales).data["id"]
    statement_id = _statement(api_client, competitor_id).data["id"]

    api_client.force_authenticate(user=admin)
    response = api_client.post(
        f"/api/competitor-statements/{statement_id}/reject/"
    )

    assert response.status_code == 200
    assert response.data["status"] == "rejected"
    assert CompetitorStatement.objects.get(pk=statement_id).reviewed_by_id == admin.pk


def test_the_statement_list_filters_by_state_and_dimension(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]
    _statement(api_client, competitor_id)
    second = _statement(
        api_client, competitor_id, dimension="identity_integration"
    ).data["id"]
    admin = user_factory(UserRole.ADMIN)
    api_client.force_authenticate(user=admin)
    api_client.post(f"/api/competitor-statements/{second}/approve/")

    approved = api_client.get(
        f"{COMPETITORS_URL}{competitor_id}/statements/", {"status": "approved"}
    ).data
    by_dimension = api_client.get(
        f"{COMPETITORS_URL}{competitor_id}/statements/",
        {"dimension": "deployment"},
    ).data
    unknown = api_client.get(
        f"{COMPETITORS_URL}{competitor_id}/statements/", {"dimension": "pricing"}
    )

    assert approved["count"] == 1
    assert approved["results"][0]["dimension"] == "identity_integration"
    assert by_dimension["count"] == 1
    assert unknown.status_code == 400


def test_an_archived_competitor_leaves_the_default_list(
    api_client, user_factory
):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales, name="竞品乙").data["id"]

    api_client.post(f"{COMPETITORS_URL}{competitor_id}/archive/")

    assert api_client.get(COMPETITORS_URL).data["count"] == 0
    # Its statements stay readable: history must not vanish with the entity.
    assert (
        api_client.get(f"{COMPETITORS_URL}{competitor_id}/statements/").status_code
        == 200
    )


def test_only_an_admin_sees_archived_competitors(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales, name="竞品丙").data["id"]
    api_client.post(f"{COMPETITORS_URL}{competitor_id}/archive/")

    refused = api_client.get(COMPETITORS_URL, {"include_inactive": "1"})

    api_client.force_authenticate(user=user_factory(UserRole.ADMIN))
    allowed = api_client.get(COMPETITORS_URL, {"include_inactive": "1"})

    assert refused.status_code == 403
    assert allowed.data["count"] == 1


def test_a_statement_records_who_registered_it(api_client, user_factory):
    presales = user_factory(UserRole.PRESALES)
    competitor_id = _competitor(api_client, presales).data["id"]

    response = _statement(api_client, competitor_id)

    statement = CompetitorStatement.objects.get(pk=response.data["id"])
    assert statement.created_by_id == presales.pk
    assert statement.status == CompetitorStatementStatus.PROPOSED
    assert statement.captured_on is not None
