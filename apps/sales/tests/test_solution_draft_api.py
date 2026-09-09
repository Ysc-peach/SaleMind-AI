"""Phase 5.6a create/list/detail HTTP contract and business visibility."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftProvenance,
    SolutionDraftRecord,
)
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db


@pytest.fixture
def api_context():
    sequence = 0

    def user(role, **flags):
        nonlocal sequence
        sequence += 1
        return get_user_model().objects.create_user(
            username=f"solution-api-{sequence}",
            email=f"solution-api-{sequence}@example.com",
            password="StrongPassword123!",
            role=role,
            **flags,
        )

    owner = user(UserRole.SALES)
    presales = user(UserRole.PRESALES)
    admin = user(UserRole.ADMIN)
    unrelated_sales = user(UserRole.SALES)
    unrelated_presales = user(UserRole.PRESALES)
    technical_admin = user(UserRole.SALES, is_staff=True, is_superuser=True)
    customer = Customer.objects.create(name="API customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="API opportunity",
        customer=customer,
        sales_owner=owner,
        presales_owner=presales,
        created_by=owner,
    )
    other = Opportunity.objects.create(
        project_name="Other opportunity",
        customer=customer,
        sales_owner=unrelated_sales,
        presales_owner=unrelated_presales,
        created_by=unrelated_sales,
    )
    payload = analysis_payload()

    def analysis(for_opportunity, created_by):
        return OpportunityRequirementAnalysis.objects.create(
            opportunity=for_opportunity,
            created_by=created_by,
            summary=payload["summary"],
            requirements=payload["requirements"],
            conflicts=payload["conflicts"],
            clarifying_questions=payload["clarifying_questions"],
            source_raw_requirement="synthetic",
            source_context={},
            analysis_version="v1",
            llm_provider="fake",
            llm_model="fake-model",
        )

    selected = analysis(opportunity, owner)
    other_analysis = analysis(other, unrelated_sales)
    record = SolutionDraftRecord.objects.create(
        opportunity=opportunity,
        requirement_analysis=selected,
        version=1,
        title="Persisted solution",
        draft_payload={
            "title": "Persisted solution",
            "executive_summary": [],
            "solution_sections": [],
            "assumptions": [],
        },
        generation_metadata={"generation_status": "generated"},
        created_by=owner,
    )
    return {
        "owner": owner,
        "presales": presales,
        "admin": admin,
        "unrelated_sales": unrelated_sales,
        "unrelated_presales": unrelated_presales,
        "technical_admin": technical_admin,
        "opportunity": opportunity,
        "other": other,
        "analysis": selected,
        "other_analysis": other_analysis,
        "record": record,
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.parametrize("actor", ["owner", "presales", "admin"])
def test_authorized_roles_can_list_and_retrieve_solution_versions(api_context, actor):
    client = client_for(api_context[actor])
    opportunity = api_context["opportunity"]
    record = api_context["record"]

    list_response = client.get(
        reverse("solution-draft-list", kwargs={"opportunity_id": opportunity.pk})
    )
    detail_response = client.get(
        reverse("solution-draft-detail", kwargs={"solution_id": record.pk})
    )

    assert list_response.status_code == 200
    item = list_response.json()["results"][0]
    assert set(item) == {
        "id", "opportunity", "analysis_id", "version", "title", "review_status",
        "schema_version", "is_stale", "stale_reasons", "created_by", "created_at",
    }
    assert "draft_payload" not in item
    assert "provenance" not in item
    assert detail_response.status_code == 200
    assert detail_response.json()["draft_payload"] == record.draft_payload
    assert detail_response.json()["provenance"] == []


@pytest.mark.parametrize(
    "actor", ["unrelated_sales", "unrelated_presales", "technical_admin"]
)
def test_unrelated_or_technical_admin_flags_do_not_bypass_visibility(api_context, actor):
    client = client_for(api_context[actor])

    assert client.get(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        )
    ).status_code == 404
    assert client.get(
        reverse(
            "solution-draft-detail",
            kwargs={"solution_id": api_context["record"].pk},
        )
    ).status_code == 404


def test_create_requires_explicit_analysis_and_passes_exact_record_to_service(
    monkeypatch,
    api_context,
):
    from apps.sales.api import solution_draft_views

    captured = {}

    def persist(opportunity, analysis, *, created_by, **kwargs):
        captured.update(
            opportunity_id=opportunity.pk,
            analysis_id=analysis.pk,
            created_by_id=created_by.pk,
            schema_version=kwargs.get("schema_version"),
        )
        return api_context["record"]

    monkeypatch.setattr(
        solution_draft_views,
        "generate_and_persist_solution_draft",
        persist,
    )
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        {"analysis_id": api_context["analysis"].pk},
        format="json",
    )

    assert response.status_code == 201
    assert captured == {
        "opportunity_id": api_context["opportunity"].pk,
        "analysis_id": api_context["analysis"].pk,
        "created_by_id": api_context["owner"].pk,
        "schema_version": 2,
    }


@pytest.mark.parametrize("payload", [{}, {"analysis_id": None}])
def test_create_never_defaults_to_latest_analysis(api_context, payload):
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        payload,
        format="json",
    )

    assert response.status_code == 400


def test_analysis_from_another_opportunity_is_rejected(api_context):
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        {"analysis_id": api_context["other_analysis"].pk},
        format="json",
    )

    assert response.status_code == 400


def test_provider_failure_returns_safe_error_and_persists_nothing(
    monkeypatch,
    api_context,
):
    from apps.llm.exceptions import LLMErrorCode, LLMProviderError
    from apps.sales.api import solution_draft_views

    def fail(*args, **kwargs):
        raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)

    monkeypatch.setattr(
        solution_draft_views,
        "generate_and_persist_solution_draft",
        fail,
    )
    before = SolutionDraftRecord.objects.count()
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        {"analysis_id": api_context["analysis"].pk},
        format="json",
    )

    assert response.status_code == 502
    assert response.json() == {
        "code": "llm_provider_error",
        "message": "The language-model provider request failed.",
    }
    assert SolutionDraftRecord.objects.count() == before


@pytest.mark.parametrize(
    ("error_code", "expected_code", "expected_message"),
    [
        (
            "INVALID_RESPONSE",
            "solution_draft_invalid_response",
            "The solution draft response is invalid.",
        ),
        (
            "INVALID_INPUT",
            "invalid_solution_draft_input",
            "The solution draft input is invalid.",
        ),
    ],
)
def test_solution_draft_validation_failure_returns_safe_error_and_persists_nothing(
    monkeypatch,
    api_context,
    error_code,
    expected_code,
    expected_message,
):
    from apps.sales.api import solution_draft_views
    from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode

    def fail(*args, **kwargs):
        raise SolutionDraftError(SolutionDraftErrorCode[error_code])

    monkeypatch.setattr(
        solution_draft_views,
        "generate_and_persist_solution_draft",
        fail,
    )
    record_count = SolutionDraftRecord.objects.count()
    provenance_count = SolutionDraftProvenance.objects.count()
    response = client_for(api_context["owner"]).post(
        reverse(
            "solution-draft-list",
            kwargs={"opportunity_id": api_context["opportunity"].pk},
        ),
        {"analysis_id": api_context["analysis"].pk},
        format="json",
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": expected_code,
        "message": expected_message,
    }
    assert SolutionDraftRecord.objects.count() == record_count
    assert SolutionDraftProvenance.objects.count() == provenance_count


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_solution_content_has_no_update_or_delete_api(api_context, method):
    client = client_for(api_context["owner"])
    response = getattr(client, method)(
        reverse(
            "solution-draft-detail",
            kwargs={"solution_id": api_context["record"].pk},
        ),
        {"title": "changed"},
        format="json",
    )

    assert response.status_code == 405
