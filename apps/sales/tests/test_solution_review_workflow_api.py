"""HTTP transport contract for the durable Solution review workflow."""

from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.sales.models import (
    Customer,
    Opportunity,
    OpportunityRequirementAnalysis,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
    SolutionReviewStatus,
)
from apps.sales.services.solution_review import (
    approve_solution_draft,
    submit_solution_draft_for_review,
)
from apps.sales.services.solution_payloads import serialize_solution_domain
from apps.sales.tests.solution_fakes import analysis_payload
from apps.sales.tests.test_solution_schema_v2 import valid_draft


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def workflow_api_context(make_user, monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver

    sales = make_user(UserRole.SALES)
    presales = make_user(UserRole.PRESALES)
    other_sales = make_user(UserRole.SALES)
    customer = Customer.objects.create(name="Workflow API customer", created_by=sales)
    opportunity = Opportunity.objects.create(
        project_name="Workflow API opportunity",
        customer=customer,
        sales_owner=sales,
        presales_owner=presales,
        created_by=sales,
    )
    other_customer = Customer.objects.create(
        name="Other workflow customer",
        created_by=other_sales,
    )
    other_opportunity = Opportunity.objects.create(
        project_name="Other workflow opportunity",
        customer=other_customer,
        sales_owner=other_sales,
        created_by=other_sales,
    )
    payload = analysis_payload()

    def create_analysis(parent, creator):
        return OpportunityRequirementAnalysis.objects.create(
            opportunity=parent,
            created_by=creator,
            summary=payload["summary"],
            requirements=payload["requirements"],
            conflicts=payload["conflicts"],
            clarifying_questions=payload["clarifying_questions"],
            source_raw_requirement="synthetic workflow HTTP input",
            source_context={},
            analysis_version="v1",
            llm_provider="fake",
            llm_model="fake-model",
        )

    analysis = create_analysis(opportunity, sales)
    other_analysis = create_analysis(other_opportunity, other_sales)
    generation_calls = []
    serialized_solution = serialize_solution_domain(valid_draft())

    def generate(
        actual_opportunity,
        actual_analysis,
        *,
        created_by,
        idempotency_key,
        **kwargs,
    ):
        generation_calls.append(
            {
                "opportunity_id": actual_opportunity.pk,
                "analysis_id": actual_analysis.pk,
                "created_by_id": created_by.pk,
                "idempotency_key": idempotency_key,
            }
        )
        existing = SolutionDraftRecord.objects.filter(
            generation_idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return existing
        return SolutionDraftRecord.objects.create(
            opportunity=actual_opportunity,
            requirement_analysis=actual_analysis,
            version=actual_opportunity.solution_drafts.count() + 1,
            schema_version=serialized_solution.schema_version,
            title=serialized_solution.payload["title"],
            draft_payload=serialized_solution.payload,
            generation_metadata={"generation_status": "generated"},
            generation_idempotency_key=idempotency_key,
            created_by=created_by,
        )

    from apps.sales.services import solution_review_workflow

    monkeypatch.setattr(
        solution_review_workflow,
        "generate_and_persist_solution_draft",
        generate,
    )

    saver = InMemorySaver()

    @contextmanager
    def open_checkpointer():
        yield saver

    # The API owns the checkpointer lifecycle. The focused tests replace only
    # the external PostgreSQL storage with the real LangGraph memory saver;
    # graph execution and Django business services remain real.
    import apps.sales.api.solution_workflow_views as workflow_views

    monkeypatch.setattr(
        workflow_views,
        "open_solution_workflow_checkpointer",
        open_checkpointer,
    )
    return {
        "sales": sales,
        "presales": presales,
        "other_sales": other_sales,
        "opportunity": opportunity,
        "analysis": analysis,
        "other_analysis": other_analysis,
        "generation_calls": generation_calls,
    }


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def _start_url(context):
    return f"/api/opportunities/{context['opportunity'].pk}/solution-workflows/"


def _status_url(workflow_id):
    return f"/api/solution-workflows/{workflow_id}/"


def _resume_url(workflow_id):
    return f"/api/solution-workflows/{workflow_id}/resume/"


def _start(context, *, user=None, key=None, payload=None):
    return _client(user or context["sales"]).post(
        _start_url(context),
        payload if payload is not None else {"analysis_id": context["analysis"].pk},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(key or uuid4()),
    )


def _resume(context, workflow_id, payload, *, user=None):
    return _client(user or context["sales"]).post(
        _resume_url(workflow_id),
        payload,
        format="json",
    )


@pytest.mark.parametrize("statuses,code", [
    ({"business_goal": "unknown", "use_scenario": "unknown"},
     "solution_needs_sales_clarification"),
    ({"budget": "conflict"}, "solution_needs_sales_clarification"),
    ({"deployment_requirement": "conflict"}, "solution_needs_presales_involvement"),
])
def test_readiness_failure_keeps_its_actionable_code_on_http_and_replay(
    workflow_api_context, monkeypatch, statuses, code,
):
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services import solution_draft, solution_review_workflow
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    context = dict(workflow_api_context)
    payload = analysis_payload(**statuses)
    context["analysis"] = OpportunityRequirementAnalysis.objects.create(
        opportunity=context["opportunity"], created_by=context["sales"],
        **payload, source_raw_requirement="synthetic workflow HTTP input",
        source_context={}, analysis_version="v1", llm_provider="fake", llm_model="fake-model",
    )
    monkeypatch.setattr(solution_review_workflow, "generate_and_persist_solution_draft",
                        generate_and_persist_solution_draft)
    def unexpected_provider_call(*args, **kwargs):
        pytest.fail("Readiness must stop before retrieval or model calls")
    monkeypatch.setattr(solution_draft, "search_knowledge", unexpected_provider_call)
    monkeypatch.setattr(solution_draft, "get_llm_provider", unexpected_provider_call)

    key = uuid4()
    response = _start(context, key=key)
    assert response.status_code == 422
    assert response.data["code"] == code
    replay = _start(context, key=key)
    assert replay.status_code == 200
    assert replay.data["status"] == "FAILED"
    assert replay.data["error_code"] == code
    assert replay.data["solution_draft_id"] is None
    assert replay.data["allowed_actions"] == []
    assert "synthetic workflow HTTP input" not in repr(response.data) + repr(replay.data)
    assert not SolutionDraftRecord.objects.exists()
    assert not SolutionDraftProvenance.objects.exists()
    assert not SolutionReview.objects.exists()


def test_unknown_user_scale_is_not_reclassified_as_a_readiness_block(
    workflow_api_context, monkeypatch,
):
    from apps.sales.services import solution_draft, solution_review_workflow
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    context = dict(workflow_api_context)
    context["analysis"] = OpportunityRequirementAnalysis.objects.create(
        opportunity=context["opportunity"], created_by=context["sales"],
        **analysis_payload(user_scale="unknown"), source_raw_requirement="offline gap input",
        source_context={}, analysis_version="v1", llm_provider="fake", llm_model="fake-model",
    )
    monkeypatch.setattr(solution_review_workflow, "generate_and_persist_solution_draft",
                        generate_and_persist_solution_draft)
    searches = []
    def no_documents(**kwargs):
        searches.append(kwargs["query"])
        return []
    monkeypatch.setattr(solution_draft, "search_knowledge", no_documents)
    monkeypatch.setattr(solution_draft, "get_llm_provider",
                        lambda: pytest.fail("Missing evidence must stop before generation"))
    response = _start(context)
    assert searches  # The formal readiness check allowed retrieval.
    assert response.status_code == 422
    assert response.data["code"] == "solution_draft_insufficient_approved_evidence"
    assert not SolutionDraftRecord.objects.exists()


def test_start_returns_actionable_evidence_code_without_model_calls_or_partial_rows(
    workflow_api_context, monkeypatch,
):
    from apps.rag.tests.test_answering import search_result
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services import solution_draft, solution_review_workflow
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    monkeypatch.setattr(solution_review_workflow, "generate_and_persist_solution_draft",
                        generate_and_persist_solution_draft)
    searches = []
    def search(**kwargs):
        searches.append(kwargs)
        return [search_result()]
    monkeypatch.setattr(solution_draft, "search_knowledge", search)
    monkeypatch.setattr(solution_draft, "get_llm_provider",
                        lambda: pytest.fail("An evidence failure must not construct a generator"))
    key = uuid4()
    response = _start(workflow_api_context, key=key)
    assert response.status_code == 422
    assert response.json()["code"] == "solution_draft_insufficient_approved_evidence"
    assert set(response.json()) == {"code", "message"}
    initial_search_count = len(searches)
    assert initial_search_count > 0
    repeated = _start(workflow_api_context, key=key)
    # An idempotent replay returns the existing terminal projection, not a new
    # generation request or a rewritten HTTP outcome.
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "FAILED"
    assert repeated.json()["error_code"] == "solution_draft_insufficient_approved_evidence"
    assert repeated.json()["allowed_actions"] == []
    assert len(searches) == initial_search_count
    assert not SolutionDraftRecord.objects.exists()
    assert not SolutionDraftProvenance.objects.exists()
    assert not SolutionReview.objects.exists()


@pytest.mark.parametrize("code", (
    "solution_draft_not_grounded", "invalid_solution_grounding_input",
    "solution_grounding_invalid_response",
    "solution_draft_unconfirmed_assertion", "solution_draft_unqualified_precondition",
    "solution_draft_expression_unclassified",
    "solution_draft_invalid_response", "llm_provider_error", "llm_invalid_response",
    "llm_not_configured", "unsupported_llm_provider",
))
def test_grounding_rejection_returns_422_and_terminal_replay_without_partial_rows(
    workflow_api_context, monkeypatch, caplog, code,
):
    import logging
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services import solution_review_workflow
    from apps.sales.services.solution_grounding import (
        SolutionDraftGroundingError, SolutionGroundingErrorCode,
    )

    calls = []
    from apps.llm.exceptions import LLMErrorCode, LLMProviderError
    from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
    if code in {item.value for item in LLMErrorCode}:
        error = LLMProviderError(LLMErrorCode(code))
    elif code == "solution_draft_invalid_response":
        error = SolutionDraftError(SolutionDraftErrorCode.INVALID_RESPONSE)
    else:
        error = SolutionDraftGroundingError(SolutionGroundingErrorCode(code))
    error.__cause__ = RuntimeError("private raw output and Authorization secret")
    def reject(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(solution_review_workflow, "generate_and_persist_solution_draft", reject)
    key = uuid4()
    with caplog.at_level(logging.WARNING):
        response = _start(workflow_api_context, key=key)
    assert response.status_code == 422
    assert response.json()["code"] == code
    assert set(response.json()) == {"code", "message"}
    repeated = _start(workflow_api_context, key=key)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "FAILED"
    assert repeated.json()["error_code"] == code
    assert repeated.json()["allowed_actions"] == []
    assert len(calls) == 1
    assert not SolutionDraftRecord.objects.exists()
    assert not SolutionDraftProvenance.objects.exists()
    assert not SolutionReview.objects.exists()
    diagnostic = next(r.solution_workflow_failure for r in caplog.records
                      if hasattr(r, "solution_workflow_failure"))
    assert diagnostic["exception_class"] == type(error).__name__
    if isinstance(error, SolutionDraftGroundingError):
        assert diagnostic["category"] == "grounding_rejection"
    assert "private raw" not in caplog.text + response.content.decode() + repr(repeated.json())
    assert "Authorization secret" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)


@pytest.mark.parametrize("payload", [{}, {"analysis_id": 1, "actor_id": 999}])
def test_start_requires_only_explicit_analysis_id(workflow_api_context, payload):
    response = _start(workflow_api_context, payload=payload)

    assert response.status_code == 400
    assert SolutionDraftRecord.objects.count() == 0


def test_start_rejects_analysis_from_another_opportunity(workflow_api_context):
    response = _start(
        workflow_api_context,
        payload={"analysis_id": workflow_api_context["other_analysis"].pk},
    )

    assert response.status_code == 400
    assert SolutionDraftRecord.objects.count() == 0


def test_start_derives_actor_and_reaches_sales_confirmation(workflow_api_context):
    response = _start(workflow_api_context)

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["workflow_id"])
    assert body["status"] == "WAITING_FOR_SALES_CONFIRMATION"
    assert body["allowed_actions"] == ["SUBMIT_FOR_REVIEW"]
    assert set(body) == {
        "workflow_id",
        "status",
        "solution_draft_id",
        "solution_version",
        "solution_review_id",
        "reviewer_id",
        "allowed_actions",
        "error_code",
    }
    assert workflow_api_context["generation_calls"][0]["created_by_id"] == workflow_api_context["sales"].pk
    draft = SolutionDraftRecord.objects.get(pk=body["solution_draft_id"])
    assert draft.review_status == SolutionReviewStatus.DRAFT
    assert not SolutionReview.objects.exists()


def test_start_response_exposes_no_checkpoint_or_solution_payload(workflow_api_context):
    body = _start(workflow_api_context).json()

    serialized = repr(body).lower()
    for forbidden in (
        "checkpoint",
        "thread_id",
        "workflow_run_id",
        "draft_payload",
        "provider",
        "provenance",
        "__interrupt__",
    ):
        assert forbidden not in serialized


def test_start_returns_429_when_every_generation_slot_is_busy(
    workflow_api_context, monkeypatch,
):
    from apps.sales.api import solution_workflow_views
    from apps.sales.services.solution_generation_capacity import (
        GenerationCapacityReached,
    )

    @contextmanager
    def busy():
        raise GenerationCapacityReached()
        yield  # pragma: no cover - unreachable, keeps the contextmanager shape

    monkeypatch.setattr(solution_workflow_views, "generation_slot", busy)

    response = _start(workflow_api_context)

    assert response.status_code == 429
    assert response.json()["code"] == "workflow_capacity_reached"
    assert not SolutionDraftRecord.objects.exists()
    assert not workflow_api_context["generation_calls"]


def test_duplicate_start_key_reuses_workflow_and_solution(workflow_api_context):
    key = uuid4()

    first = _start(workflow_api_context, key=key)
    second = _start(workflow_api_context, key=key)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["workflow_id"] == first.json()["workflow_id"]
    assert second.json()["solution_draft_id"] == first.json()["solution_draft_id"]
    assert SolutionDraftRecord.objects.count() == 1
    assert len(workflow_api_context["generation_calls"]) == 1


def test_status_reconstructs_from_a_new_graph_instance(workflow_api_context):
    started = _start(workflow_api_context).json()

    response = _client(workflow_api_context["sales"]).get(
        _status_url(started["workflow_id"])
    )

    assert response.status_code == 200
    assert response.json() == started


def test_unknown_workflow_returns_safe_404(workflow_api_context):
    response = _client(workflow_api_context["sales"]).get(_status_url(uuid4()))

    assert response.status_code == 404
    assert "checkpoint" not in repr(response.json()).lower()


def test_unrelated_technical_superuser_cannot_read_workflow(workflow_api_context):
    started = _start(workflow_api_context).json()
    actor = workflow_api_context["other_sales"]
    actor.is_staff = True
    actor.is_superuser = True
    actor.save(update_fields=["is_staff", "is_superuser"])

    response = _client(actor).get(_status_url(started["workflow_id"]))

    assert response.status_code == 404


def test_business_database_pending_review_overrides_stale_checkpoint(workflow_api_context):
    started = _start(workflow_api_context).json()
    draft = SolutionDraftRecord.objects.get(pk=started["solution_draft_id"])
    review = submit_solution_draft_for_review(
        draft,
        actor=workflow_api_context["sales"],
    )

    response = _client(workflow_api_context["presales"]).get(
        _status_url(started["workflow_id"])
    )

    assert response.status_code == 200
    assert response.json()["status"] == "WAITING_FOR_PRESALES_REVIEW"
    assert response.json()["solution_review_id"] == review.pk
    assert response.json()["reviewer_id"] == workflow_api_context["presales"].pk


def test_sales_resume_submits_existing_draft_and_reaches_second_interrupt(workflow_api_context):
    started = _start(workflow_api_context).json()

    response = _resume(
        workflow_api_context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "WAITING_FOR_PRESALES_REVIEW"
    assert body["allowed_actions"] == ["APPROVE", "REQUEST_REVISION"]
    review = SolutionReview.objects.get(pk=body["solution_review_id"])
    assert review.submitted_by_id == workflow_api_context["sales"].pk
    assert review.reviewer_id == workflow_api_context["presales"].pk


def test_duplicate_sales_resume_recovers_one_pending_review(workflow_api_context):
    started = _start(workflow_api_context).json()
    first = _resume(
        workflow_api_context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
    )

    second = _resume(
        workflow_api_context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "WAITING_FOR_PRESALES_REVIEW"
    assert SolutionReview.objects.count() == 1


def test_stale_submit_is_blocked_by_existing_service(workflow_api_context):
    started = _start(workflow_api_context).json()
    OpportunityRequirementAnalysis.objects.create(
        opportunity=workflow_api_context["opportunity"],
        created_by=workflow_api_context["sales"],
        summary="newer snapshot",
        requirements={},
        conflicts=[],
        clarifying_questions=[],
        source_raw_requirement="newer synthetic input",
        source_context={},
        analysis_version="v2",
        llm_provider="fake",
        llm_model="fake-model",
    )

    response = _resume(
        workflow_api_context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "solution_review_submit_blocked"
    assert not SolutionReview.objects.exists()

    status_response = _client(workflow_api_context["sales"]).get(
        _status_url(started["workflow_id"])
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "BLOCKED"
    assert status_response.json()["allowed_actions"] == []
    assert status_response.json()["error_code"] == "solution_review_submit_blocked"


def test_self_review_remains_blocked_by_existing_service(workflow_api_context):
    started = _start(
        workflow_api_context,
        user=workflow_api_context["presales"],
    ).json()

    response = _resume(
        workflow_api_context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
        user=workflow_api_context["presales"],
    )

    assert response.status_code == 409
    assert response.json()["code"] == "solution_review_submit_blocked"
    assert not SolutionReview.objects.exists()


def _reach_presales(context):
    started = _start(context).json()
    submitted = _resume(
        context,
        started["workflow_id"],
        {"action": "SUBMIT_FOR_REVIEW"},
    )
    assert submitted.status_code == 200
    return submitted.json()


def test_presales_resume_approves(workflow_api_context):
    pending = _reach_presales(workflow_api_context)

    response = _resume(
        workflow_api_context,
        pending["workflow_id"],
        {"action": "APPROVE"},
        user=workflow_api_context["presales"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["allowed_actions"] == []
    assert SolutionReview.objects.get().status == "approved"


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        (SolutionReturnReason.CUSTOMER_INFO_REQUIRED, "CUSTOMER_INFO_REQUIRED"),
        (
            SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
            "TECHNICAL_REVISION_REQUIRED",
        ),
    ],
)
def test_presales_resume_routes_both_revision_reasons(
    workflow_api_context,
    reason,
    expected_status,
):
    pending = _reach_presales(workflow_api_context)

    response = _resume(
        workflow_api_context,
        pending["workflow_id"],
        {
            "action": "REQUEST_REVISION",
            "return_reason": reason.upper(),
            "comment": "Please follow the selected business handoff.",
        },
        user=workflow_api_context["presales"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    review = SolutionReview.objects.get()
    assert review.return_reason == reason


def test_duplicate_approve_resume_recovers_terminal_success(workflow_api_context):
    pending = _reach_presales(workflow_api_context)
    payload = {"action": "APPROVE"}

    first = _resume(
        workflow_api_context,
        pending["workflow_id"],
        payload,
        user=workflow_api_context["presales"],
    )
    second = _resume(
        workflow_api_context,
        pending["workflow_id"],
        payload,
        user=workflow_api_context["presales"],
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "APPROVED"
    assert SolutionReview.objects.count() == 1


def test_duplicate_return_resume_recovers_exact_terminal_handoff(workflow_api_context):
    pending = _reach_presales(workflow_api_context)
    payload = {
        "action": "REQUEST_REVISION",
        "return_reason": "CUSTOMER_INFO_REQUIRED",
        "comment": "Need the customer database version.",
    }

    first = _resume(
        workflow_api_context,
        pending["workflow_id"],
        payload,
        user=workflow_api_context["presales"],
    )
    second = _resume(
        workflow_api_context,
        pending["workflow_id"],
        payload,
        user=workflow_api_context["presales"],
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "CUSTOMER_INFO_REQUIRED"
    assert SolutionReview.objects.count() == 1


def test_conflicting_terminal_replay_fails_closed(workflow_api_context):
    pending = _reach_presales(workflow_api_context)
    approved = _resume(
        workflow_api_context,
        pending["workflow_id"],
        {"action": "APPROVE"},
        user=workflow_api_context["presales"],
    )
    assert approved.status_code == 200

    conflict = _resume(
        workflow_api_context,
        pending["workflow_id"],
        {
            "action": "REQUEST_REVISION",
            "return_reason": "CUSTOMER_INFO_REQUIRED",
            "comment": "Conflicting retry must not win.",
        },
        user=workflow_api_context["presales"],
    )

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "workflow_decision_conflict"
    assert SolutionReview.objects.get().status == "approved"


def test_resume_rejects_actor_and_reviewer_spoofing(workflow_api_context):
    started = _start(workflow_api_context).json()

    response = _resume(
        workflow_api_context,
        started["workflow_id"],
        {
            "action": "SUBMIT_FOR_REVIEW",
            "actor_id": workflow_api_context["presales"].pk,
            "reviewer_id": workflow_api_context["presales"].pk,
        },
    )

    assert response.status_code == 400
    assert not SolutionReview.objects.exists()


def test_invalid_idempotency_key_is_a_safe_request_error(workflow_api_context):
    response = _client(workflow_api_context["sales"]).post(
        _start_url(workflow_api_context),
        {"analysis_id": workflow_api_context["analysis"].pk},
        format="json",
        HTTP_IDEMPOTENCY_KEY="not-a-uuid",
    )

    assert response.status_code == 400
    assert "traceback" not in repr(response.json()).lower()


@pytest.mark.parametrize("header", [None, "", "   "])
def test_start_requires_an_explicit_idempotency_key(workflow_api_context, header):
    client = _client(workflow_api_context["sales"])
    extra = {} if header is None else {"HTTP_IDEMPOTENCY_KEY": header}

    response = client.post(
        _start_url(workflow_api_context),
        {"analysis_id": workflow_api_context["analysis"].pk},
        format="json",
        **extra,
    )

    assert response.status_code == 400
    assert "idempotency_key" in repr(response.json()).lower()
    assert not SolutionDraftRecord.objects.exists()
    assert not workflow_api_context["generation_calls"]


def test_business_database_approved_state_overrides_checkpoint(workflow_api_context):
    pending = _reach_presales(workflow_api_context)
    draft = SolutionDraftRecord.objects.get(pk=pending["solution_draft_id"])
    approve_solution_draft(draft, actor=workflow_api_context["presales"])

    response = _client(workflow_api_context["sales"]).get(
        _status_url(pending["workflow_id"])
    )

    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"
    assert response.json()["allowed_actions"] == []


def test_solution_detail_exposes_opaque_workflow_id_for_cross_session_recovery(
    workflow_api_context,
):
    started = _start(workflow_api_context).json()

    response = _client(workflow_api_context["sales"]).get(
        f"/api/solution-drafts/{started['solution_draft_id']}/"
    )

    assert response.status_code == 200
    assert response.json()["workflow_id"] == started["workflow_id"]
    assert "generation_idempotency_key" not in response.json()
