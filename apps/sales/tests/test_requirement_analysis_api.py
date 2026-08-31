"""HTTP contracts for append-only, opportunity-scoped analysis history."""

from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.sales.models import Customer, Opportunity, OpportunityRequirementAnalysis as Analysis
from apps.sales.services import requirement_analysis, requirement_analysis_history as history
from apps.sales.tests.requirement_fakes import AnalysisFakeLLM, valid_analysis_payload


pytestmark = pytest.mark.django_db(transaction=True)


def collection_url(opportunity):
    return f"/api/opportunities/{opportunity.pk}/ai/requirement-analyses/"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Analysis API tests must never access the public network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)


@pytest.fixture
def context(monkeypatch):
    users = {
        name: get_user_model().objects.create_user(
            username=name, email=f"{name}@example.invalid", role=role,
        )
        for name, role in (
            ("admin", "admin"), ("owner", "sales"), ("assigned", "presales"),
            ("outsider", "sales"), ("unassigned", "presales"),
        )
    }
    customer = Customer.objects.create(
        name="宏远制造", industry="制造业", company_size="约500人",
        basic_info="企业资料 A", created_by=users["owner"],
    )
    opportunity = Opportunity.objects.create(
        customer=customer, project_name="企业系统", budget=Decimal("500000.00"),
        expected_launch_date=date(2026, 12, 1), raw_requirement="最新预算最多30万元。",
        sales_owner=users["owner"], presales_owner=users["assigned"], created_by=users["owner"],
    )
    provider = AnalysisFakeLLM()
    monkeypatch.setattr(requirement_analysis, "get_llm_provider", lambda: provider)
    return opportunity, users, provider


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


FULL_FIELDS = {
    "id", "opportunity_id", "summary", "requirements", "conflicts", "clarifying_questions",
    "source_raw_requirement", "source_context", "analysis_version", "llm_provider",
    "llm_model", "created_by_id", "created_at",
}


@pytest.mark.parametrize("actor", ["admin", "owner", "assigned"])
@pytest.mark.parametrize("empty_body", [False, True])
def test_authorized_actor_creates_exactly_one_analysis_from_saved_facts(context, actor, empty_body):
    opportunity, users, provider = context
    original_opportunity = Opportunity.objects.values().get(pk=opportunity.pk)
    original_customer = Customer.objects.values().get(pk=opportunity.customer_id)
    client = client_for(users[actor])
    url = collection_url(opportunity)
    response = client.generic("POST", url) if empty_body else client.post(url, {}, format="json")
    assert response.status_code == 201
    assert set(response.data) == FULL_FIELDS
    record = Analysis.objects.get()
    assert response.data["id"] == record.pk
    assert record.opportunity_id == response.data["opportunity_id"] == opportunity.pk
    assert record.created_by_id == response.data["created_by_id"] == users[actor].pk
    assert len(provider.calls) == 1
    for field, value in valid_analysis_payload().items():
        assert response.data[field] == value == getattr(record, field)
    assert len(response.data["requirements"]) == 10
    assert response.data["source_raw_requirement"] == "最新预算最多30万元。"
    assert response.data["source_context"] == record.source_context
    assert response.data["analysis_version"] == "v1"
    assert response.data["llm_provider"] == "analysis-test-provider"
    assert response.data["llm_model"] == "analysis-test-model"
    assert Opportunity.objects.values().get(pk=opportunity.pk) == original_opportunity
    assert Customer.objects.values().get(pk=opportunity.customer_id) == original_customer


def test_anonymous_cannot_trigger_analysis(context):
    opportunity, _, provider = context
    response = APIClient().post(collection_url(opportunity), {}, format="json")
    assert response.status_code == 401
    assert Analysis.objects.count() == 0
    assert provider.calls == []


@pytest.mark.parametrize("actor", ["outsider", "unassigned"])
@pytest.mark.parametrize("flag", [None, "is_staff", "is_superuser"])
def test_invisible_opportunity_matches_existing_404_even_with_django_flags(context, actor, flag):
    opportunity, users, provider = context
    user = users[actor]
    if flag:
        setattr(user, flag, True)
        user.save(update_fields=[flag])
    client = client_for(user)
    existing = client.get(f"/api/opportunities/{opportunity.pk}/")
    response = client.post(collection_url(opportunity), {}, format="json")
    assert response.status_code == existing.status_code == 404
    assert set(response.data) == {"code", "message"}
    assert Analysis.objects.count() == 0
    assert provider.calls == []


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_unknown_role_cannot_trigger_analysis_even_with_django_flags(context, flag):
    opportunity, users, provider = context
    user = users["owner"]
    user.role = "unknown"
    setattr(user, flag, True)
    response = client_for(user).post(collection_url(opportunity), {}, format="json")
    assert response.status_code == 403
    assert provider.calls == []


@pytest.mark.parametrize("field", [
    "raw_requirement", "query", "provider", "model", "api_key", "messages", "system_prompt",
    "requirements", "conflicts", "source_context", "created_by", "analysis_version",
    "llm_provider", "llm_model", "arbitrary_unknown_field",
])
def test_any_post_field_is_explicitly_rejected_without_analysis(context, field):
    opportunity, users, provider = context
    response = client_for(users["owner"]).post(
        collection_url(opportunity), {field: "private-input-sentinel"}, format="json",
    )
    assert response.status_code == 400
    assert set(response.data) == {"code", "message"}
    assert response.data["code"] == "invalid_request"
    assert "private-input-sentinel" not in response.content.decode()
    assert Analysis.objects.count() == 0
    assert provider.calls == []


@pytest.mark.parametrize("body", ["[]", "null", '"text"', "1", "true", '{"api_key":"private-input-sentinel",'])
def test_non_object_and_malformed_json_are_safe_invalid_requests(context, body):
    opportunity, users, provider = context
    response = client_for(users["owner"]).generic(
        "POST", collection_url(opportunity), body, content_type="application/json",
    )
    assert response.status_code == 400
    assert set(response.data) == {"code", "message"}
    assert response.data["code"] == "invalid_request"
    assert "private-input-sentinel" not in response.content.decode()
    assert Analysis.objects.count() == 0
    assert provider.calls == []


LIST_FIELDS = {"id", "summary", "analysis_version", "llm_provider", "llm_model", "created_by_id", "created_at"}


@pytest.fixture
def two_analyses(context, monkeypatch):
    opportunity, users, provider = context
    instant = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: instant)
    first = history.create_opportunity_requirement_analysis(opportunity, created_by=users["owner"])
    opportunity.raw_requirement = "需求已改为 B。"
    opportunity.save(update_fields=["raw_requirement"])
    opportunity.customer.basic_info = "企业资料 B"
    opportunity.customer.save(update_fields=["basic_info"])
    second = history.create_opportunity_requirement_analysis(opportunity, created_by=users["assigned"])
    return first, second


def read_url(opportunity, first, endpoint):
    suffix = {"list": "", "latest": "latest/", "detail": f"{first.pk}/"}[endpoint]
    return collection_url(opportunity) + suffix


@pytest.mark.parametrize("actor", ["admin", "owner", "assigned"])
def test_history_latest_and_detail_return_stored_snapshots_without_side_effects(context, two_analyses, actor, monkeypatch):
    opportunity, users, provider = context
    first, second = two_analyses
    before_records = list(Analysis.objects.values())
    client = client_for(users[actor])

    def forbidden():
        pytest.fail("Reading analysis history must not call the LLM factory.")
    monkeypatch.setattr(requirement_analysis, "get_llm_provider", forbidden)
    with CaptureQueriesContext(connection) as queries:
        listed = client.get(collection_url(opportunity))
        latest = client.get(collection_url(opportunity) + "latest/")
        detail = client.get(collection_url(opportunity) + f"{first.pk}/")
    assert [listed.status_code, latest.status_code, detail.status_code] == [200, 200, 200]
    assert listed.data["count"] == 2
    assert listed.data["next"] is None and listed.data["previous"] is None
    assert [row["id"] for row in listed.data["results"]] == [second.pk, first.pk]
    assert all(set(row) == LIST_FIELDS for row in listed.data["results"])
    assert latest.data["id"] == second.pk
    assert latest.data["source_raw_requirement"] == "需求已改为 B。"
    assert detail.data["id"] == first.pk
    assert detail.data["source_raw_requirement"] == "最新预算最多30万元。"
    assert detail.data["source_context"]["customer"]["basic_info"] == "企业资料 A"
    assert set(latest.data) == set(detail.data) == FULL_FIELDS
    assert list(Analysis.objects.values()) == before_records
    assert len(provider.calls) == 2
    assert all(q["sql"].lstrip().upper().startswith("SELECT") for q in queries.captured_queries)


def test_history_uses_default_20_item_pagination_and_id_tiebreak(context, monkeypatch):
    opportunity, users, _ = context
    instant = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: instant)
    rows = [history.create_opportunity_requirement_analysis(opportunity, created_by=users["owner"]) for _ in range(21)]
    client = client_for(users["owner"])
    first_page = client.get(collection_url(opportunity))
    assert first_page.status_code == 200
    assert first_page.data["count"] == 21
    assert len(first_page.data["results"]) == 20
    assert [row["id"] for row in first_page.data["results"]] == [row.pk for row in reversed(rows[1:])]
    assert first_page.data["next"].endswith("?page=2")
    second_page = client.get(collection_url(opportunity) + "?page=2")
    assert second_page.status_code == 200
    assert [row["id"] for row in second_page.data["results"]] == [rows[0].pk]


@pytest.mark.parametrize("endpoint", ["list", "latest", "detail"])
@pytest.mark.parametrize("actor", [None, "outsider", "unassigned"])
def test_history_reads_enforce_same_opportunity_visibility(context, two_analyses, endpoint, actor):
    opportunity, users, _ = context
    first, _ = two_analyses
    client = APIClient() if actor is None else client_for(users[actor])
    expected_status = client.get(f"/api/opportunities/{opportunity.pk}/").status_code
    response = client.get(read_url(opportunity, first, endpoint))
    assert response.status_code == expected_status == (401 if actor is None else 404)
    assert set(response.data) == {"code", "message"}


@pytest.mark.parametrize("actor", ["outsider", "unassigned"])
@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_django_flags_do_not_grant_history_read_access(context, two_analyses, actor, flag):
    opportunity, users, _ = context
    setattr(users[actor], flag, True)
    client = client_for(users[actor])
    for endpoint in ("list", "latest", "detail"):
        assert client.get(read_url(opportunity, two_analyses[0], endpoint)).status_code == 404


def test_detail_cannot_use_analysis_id_from_another_opportunity(context, two_analyses):
    opportunity, users, _ = context
    other = Opportunity.objects.create(
        project_name="不可见项目", customer=opportunity.customer,
        sales_owner=users["outsider"], created_by=users["outsider"],
    )
    foreign_record = history.create_opportunity_requirement_analysis(other, created_by=users["outsider"])
    client = client_for(users["owner"])
    response = client.get(collection_url(opportunity) + f"{foreign_record.pk}/")
    assert response.status_code == 404
    assert response.data["code"] == "not_found"
    assert set(response.data) == {"code", "message"}


def test_latest_without_history_and_missing_detail_are_safe_not_found(context):
    opportunity, users, provider = context
    client = client_for(users["owner"])
    listed = client.get(collection_url(opportunity))
    assert listed.status_code == 200
    assert listed.data["count"] == 0 and listed.data["results"] == []
    for suffix in ("latest/", "999999/"):
        response = client.get(collection_url(opportunity) + suffix)
        assert response.status_code == 404
        assert response.data["code"] == "not_found"
    assert provider.calls == []


def test_latest_route_and_numeric_detail_route_are_distinct(context):
    opportunity, _, _ = context
    latest = resolve(collection_url(opportunity) + "latest/")
    detail = resolve(collection_url(opportunity) + "123/")
    assert latest.url_name == "opportunity-requirement-analysis-latest"
    assert latest.kwargs == {"opportunity_id": opportunity.pk}
    assert detail.url_name == "opportunity-requirement-analysis-detail"
    assert detail.kwargs == {"opportunity_id": opportunity.pk, "analysis_id": 123}


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_no_analysis_endpoint_can_update_or_delete_history(context, two_analyses, method):
    opportunity, users, provider = context
    original_records = list(Analysis.objects.values())
    client = client_for(users["admin"])
    for endpoint in ("list", "latest", "detail"):
        response = getattr(client, method)(read_url(opportunity, two_analyses[0], endpoint), {}, format="json")
        assert response.status_code == 405
    assert list(Analysis.objects.values()) == original_records
    assert len(provider.calls) == 2


@pytest.mark.parametrize(("error", "http_status"), [
    (requirement_analysis.RequirementAnalysisError(requirement_analysis.RequirementAnalysisErrorCode.INVALID_INPUT), 400),
    (requirement_analysis.RequirementAnalysisError(requirement_analysis.RequirementAnalysisErrorCode.INVALID_RESPONSE), 502),
    (LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED), 503),
    (LLMProviderError(LLMErrorCode.UNSUPPORTED_LLM_PROVIDER), 503),
    (LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR), 502),
    (LLMProviderError(LLMErrorCode.LLM_INVALID_RESPONSE), 502),
])
def test_service_domain_errors_keep_safe_code_and_correct_http_status(context, monkeypatch, caplog, error, http_status):
    opportunity, users, _ = context
    sentinel = "private-key-Authorization-raw-body-customer-traceback"

    def fail(opportunity, *, created_by):
        raise error from RuntimeError(sentinel)

    monkeypatch.setattr(history, "create_opportunity_requirement_analysis", fail)
    response = client_for(users["owner"]).post(collection_url(opportunity), {}, format="json")
    assert response.status_code == http_status
    assert response.data == {"code": error.code, "message": error.safe_message}
    assert sentinel not in response.content.decode() + caplog.text
    assert opportunity.raw_requirement not in response.content.decode()
    assert Analysis.objects.count() == 0


def test_invalid_real_service_output_is_upstream_502_not_client_400(context):
    opportunity, users, provider = context
    provider.content = '{"solution":"raw-private-model-response"}'
    response = client_for(users["owner"]).post(collection_url(opportunity), {}, format="json")
    assert response.status_code == 502
    assert response.data["code"] == "requirement_analysis_invalid_response"
    assert set(response.data) == {"code", "message"}
    assert "raw-private-model-response" not in response.content.decode()
    assert Analysis.objects.count() == 0
    assert len(provider.calls) == 1


def test_view_uses_persistence_service_with_resolved_parent_and_actual_actor_outside_transaction(context, monkeypatch):
    opportunity, users, _ = context
    original_create = history.create_opportunity_requirement_analysis
    seen = []

    def checked_create(parent, *, created_by):
        assert not connection.in_atomic_block and connection.get_autocommit()
        seen.append((parent.pk, parent.raw_requirement, parent.customer.pk, created_by.pk))
        return original_create(parent, created_by=created_by)
    monkeypatch.setattr(history, "create_opportunity_requirement_analysis", checked_create)
    response = client_for(users["assigned"]).post(collection_url(opportunity), {}, format="json")
    assert response.status_code == 201
    assert seen == [(opportunity.pk, opportunity.raw_requirement, opportunity.customer_id, users["assigned"].pk)]
    assert Analysis.objects.get().created_by_id == users["assigned"].pk


def test_get_views_use_existing_scoped_query_services(context, two_analyses, monkeypatch):
    opportunity, users, _ = context
    original_list = history.list_opportunity_requirement_analyses
    original_latest = history.get_latest_opportunity_requirement_analysis
    calls = []

    def read_history(parent):
        calls.append(("history", parent.pk))
        return original_list(parent)

    def read_latest(parent):
        calls.append(("latest", parent.pk))
        return original_latest(parent)

    monkeypatch.setattr(history, "list_opportunity_requirement_analyses", read_history)
    monkeypatch.setattr(history, "get_latest_opportunity_requirement_analysis", read_latest)
    client = client_for(users["owner"])
    for endpoint in ("list", "latest", "detail"):
        assert client.get(read_url(opportunity, two_analyses[0], endpoint)).status_code == 200
    assert calls == [("history", opportunity.pk), ("latest", opportunity.pk), ("history", opportunity.pk)]


def test_serializers_expose_only_read_only_fields():
    from apps.sales.api.requirement_analysis_serializers import (
        RequirementAnalysisDetailSerializer, RequirementAnalysisListSerializer,
    )

    for serializer in (RequirementAnalysisDetailSerializer(), RequirementAnalysisListSerializer()):
        assert all(field.read_only for field in serializer.fields.values())


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_invalid_business_role_has_no_history_read_access(context, two_analyses, flag):
    opportunity, users, _ = context
    actor = users["owner"]
    actor.role = "unknown"
    setattr(actor, flag, True)
    client = client_for(actor)
    for endpoint in ("list", "latest", "detail"):
        assert client.get(read_url(opportunity, two_analyses[0], endpoint)).status_code == 403


def test_missing_parent_never_reaches_persistence_or_llm(context, monkeypatch):
    _, users, provider = context
    def forbidden(*args, **kwargs):
        pytest.fail("An invisible parent must fail before calling history services.")
    monkeypatch.setattr(history, "create_opportunity_requirement_analysis", forbidden)
    monkeypatch.setattr(history, "list_opportunity_requirement_analyses", forbidden)
    monkeypatch.setattr(history, "get_latest_opportunity_requirement_analysis", forbidden)
    client = client_for(users["admin"])
    base = "/api/opportunities/999999/ai/requirement-analyses/"
    assert client.post(base, {}, format="json").status_code == 404
    for suffix in ("", "latest/", "1/"):
        assert client.get(base + suffix).status_code == 404
    assert provider.calls == []


def test_response_does_not_serialize_provider_internals_or_prompts(context):
    opportunity, users, provider = context
    provider.api_key = "private-provider-key"
    provider.reasoning_content = "private-reasoning"
    provider.raw_response = "private-raw-response"
    response = client_for(users["owner"]).post(collection_url(opportunity), {}, format="json")
    assert response.status_code == 201
    assert set(response.data) == FULL_FIELDS
    for secret in (provider.api_key, provider.reasoning_content, provider.raw_response, provider.calls[0][0]["content"]):
        assert secret not in response.content.decode()


def test_authenticated_jwt_runs_full_create_and_history_chain(context):
    opportunity, users, _ = context
    actor = users["owner"]
    actor.set_password("Only-Automated-Test-Password")
    actor.save(update_fields=["password"])
    client = APIClient()
    login = client.post("/api/auth/login/", {"username": actor.username, "password": "Only-Automated-Test-Password"}, format="json")
    assert login.status_code == 200
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    created = client.post(collection_url(opportunity), {}, format="json")
    assert created.status_code == 201
    assert created.data["created_by_id"] == actor.pk
    assert client.get(collection_url(opportunity) + "latest/").data["id"] == created.data["id"]


def test_excessively_nested_json_is_safe_400_before_any_analysis(context):
    opportunity, users, provider = context
    response = client_for(users["owner"]).generic(
        "POST", collection_url(opportunity), "[" * 5000, content_type="application/json",
    )
    assert response.status_code == 400
    assert response.data["code"] == "invalid_request"
    assert set(response.data) == {"code", "message"}
    assert "traceback" not in response.content.decode().lower()
    assert Analysis.objects.count() == 0
    assert provider.calls == []
