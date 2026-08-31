"""Real PostgreSQL persistence, snapshot drift and short-transaction tests."""

import json
from datetime import date
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.sales.models import Customer, Opportunity, OpportunityRequirementAnalysis
from apps.sales.services.requirement_analysis import RequirementAnalysisError
from apps.sales.tests.requirement_fakes import AnalysisFakeLLM, input_from_messages, valid_analysis_payload


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("History tests must not access the network.")
    monkeypatch.setattr("socket.socket.connect", forbidden)


@pytest.fixture
def context(make_user):
    owner, actor = make_user(), make_user()
    customer = Customer.objects.create(
        name="宏远制造", industry="制造业", company_size="约500人",
        basic_info="企业基础资料 A", created_by=owner,
    )
    opportunity = Opportunity.objects.create(
        customer=customer, project_name="知识库项目 A", budget=Decimal("500000.00"),
        expected_launch_date=date(2026, 12, 1), raw_requirement="客户最新预算最多30万元。",
        sales_owner=owner, created_by=owner,
    )
    return opportunity, actor


def create_analysis(opportunity, actor, provider):
    from apps.sales.services.requirement_analysis_history import create_opportunity_requirement_analysis

    return create_opportunity_requirement_analysis(opportunity, created_by=actor, llm_provider=provider)


def test_create_persists_valid_analysis_and_exact_execution_snapshot(context):
    opportunity, actor = context
    before_opportunity = Opportunity.objects.values().get(pk=opportunity.pk)
    before_customer = Customer.objects.values().get(pk=opportunity.customer_id)
    provider = AnalysisFakeLLM()
    record = create_analysis(opportunity, actor, provider)
    record.refresh_from_db()
    assert OpportunityRequirementAnalysis.objects.count() == 1
    assert record.opportunity_id == opportunity.pk
    assert record.created_by_id == actor.pk != opportunity.sales_owner_id
    expected = valid_analysis_payload()
    for name in ("summary", "requirements", "conflicts", "clarifying_questions"):
        assert getattr(record, name) == expected[name]
    assert len(record.requirements) == 10
    assert type(record.requirements["budget"]["status"]) is str
    actual_context, actual_raw = input_from_messages(provider.calls[0])
    assert record.source_raw_requirement == actual_raw == "客户最新预算最多30万元。"
    assert record.source_context == actual_context
    assert record.source_context["opportunity"]["budget"] == "500000.00"
    assert record.source_context["opportunity"]["expected_launch_date"] == "2026-12-01"
    assert record.source_context["customer"]["basic_info"] == "企业基础资料 A"
    assert (record.llm_provider, record.llm_model) == ("analysis-test-provider", "analysis-test-model")
    assert record.analysis_version == "v1"
    assert Opportunity.objects.values().get(pk=opportunity.pk) == before_opportunity
    assert Customer.objects.values().get(pk=opportunity.customer_id) == before_customer


def test_null_source_values_are_stored_as_json_null(context):
    opportunity, actor = context
    opportunity.budget = opportunity.expected_launch_date = None
    opportunity.save()
    record = create_analysis(opportunity, actor, AnalysisFakeLLM())
    record.refresh_from_db()
    assert record.source_context["opportunity"]["budget"] is None
    assert record.source_context["opportunity"]["expected_launch_date"] is None


def test_llm_callback_cannot_replace_snapshot_a_with_database_snapshot_b(context):
    opportunity, actor = context

    def change_business_data():
        Opportunity.objects.filter(pk=opportunity.pk).update(
            project_name="项目 B", raw_requirement="需求 B", budget=Decimal("900000.00"),
            expected_launch_date=date(2027, 1, 1),
        )
        Customer.objects.filter(pk=opportunity.customer_id).update(name="客户 B", basic_info="资料 B")
        opportunity.refresh_from_db()
        opportunity.customer.refresh_from_db()

    provider = AnalysisFakeLLM(callback=change_business_data)
    record = create_analysis(opportunity, actor, provider)
    record.refresh_from_db()
    assert opportunity.raw_requirement == "需求 B"
    assert record.source_context == input_from_messages(provider.calls[0])[0]
    assert record.source_raw_requirement == "客户最新预算最多30万元。"
    assert record.source_context["opportunity"]["project_name"] == "知识库项目 A"
    assert record.source_context["customer"]["name"] == "宏远制造"
    assert record.source_context["customer"]["basic_info"] == "企业基础资料 A"


def test_two_executions_append_history_and_latest_is_stably_sorted(context, monkeypatch):
    from apps.sales.services.requirement_analysis_history import (
        get_latest_opportunity_requirement_analysis, list_opportunity_requirement_analyses,
    )

    opportunity, actor = context
    instant = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: instant)
    first = create_analysis(opportunity, actor, AnalysisFakeLLM())
    original_first = OpportunityRequirementAnalysis.objects.values().get(pk=first.pk)
    opportunity.raw_requirement = "需求 B"
    opportunity.save()
    opportunity.customer.basic_info = "资料 B"
    opportunity.customer.save()
    second = create_analysis(opportunity, actor, AnalysisFakeLLM())
    assert first.pk != second.pk
    assert first.created_at == second.created_at
    assert OpportunityRequirementAnalysis.objects.count() == 2
    assert OpportunityRequirementAnalysis.objects.values().get(pk=first.pk) == original_first
    assert second.source_raw_requirement == "需求 B"
    assert second.source_context["customer"]["basic_info"] == "资料 B"
    history = list_opportunity_requirement_analyses(opportunity)
    assert isinstance(history, tuple)
    assert [item.pk for item in history] == [second.pk, first.pk]
    assert get_latest_opportunity_requirement_analysis(opportunity).pk == second.pk


def test_history_queries_are_scoped_and_empty_history_is_not_an_error(context):
    from apps.sales.services.requirement_analysis_history import (
        get_latest_opportunity_requirement_analysis, list_opportunity_requirement_analyses,
    )

    opportunity, actor = context
    other = Opportunity.objects.create(
        customer=opportunity.customer, project_name="其他项目", sales_owner=actor, created_by=actor,
    )
    assert list_opportunity_requirement_analyses(opportunity) == ()
    assert get_latest_opportunity_requirement_analysis(opportunity) is None
    create_analysis(other, actor, AnalysisFakeLLM())
    assert list_opportunity_requirement_analyses(opportunity) == ()
    assert get_latest_opportunity_requirement_analysis(opportunity) is None


@pytest.mark.parametrize("code", list(LLMErrorCode))
def test_llm_failure_preserves_exception_and_creates_zero_records(context, code):
    opportunity, actor = context
    error = LLMProviderError(code)

    def fail():
        raise error

    with pytest.raises(LLMProviderError) as caught:
        create_analysis(opportunity, actor, AnalysisFakeLLM(callback=fail))
    assert caught.value is error
    assert OpportunityRequirementAnalysis.objects.count() == 0


def test_factory_configuration_failure_creates_zero_records(context, monkeypatch):
    from apps.sales.services import requirement_analysis
    from apps.sales.services.requirement_analysis_history import create_opportunity_requirement_analysis

    opportunity, actor = context
    error = LLMProviderError(LLMErrorCode.LLM_NOT_CONFIGURED)

    def fail():
        raise error

    monkeypatch.setattr(requirement_analysis, "get_llm_provider", fail)
    with pytest.raises(LLMProviderError) as caught:
        create_opportunity_requirement_analysis(opportunity, created_by=actor)
    assert caught.value is error
    assert OpportunityRequirementAnalysis.objects.count() == 0


@pytest.mark.parametrize("content", ["", "malformed JSON", json.dumps({**valid_analysis_payload(), "solution": "forbidden"})])
def test_invalid_analysis_creates_zero_records(context, content):
    opportunity, actor = context
    with pytest.raises(RequirementAnalysisError) as caught:
        create_analysis(opportunity, actor, AnalysisFakeLLM(content=content))
    assert caught.value.code == "requirement_analysis_invalid_response"
    assert OpportunityRequirementAnalysis.objects.count() == 0


def test_provider_call_is_outside_transaction_and_insert_is_inside(context, monkeypatch):
    opportunity, actor = context

    def check_provider_boundary():
        assert not connection.in_atomic_block
        assert connection.get_autocommit()

    original_create = OpportunityRequirementAnalysis.objects.create
    insert_calls = []

    def checked_create(**kwargs):
        assert connection.in_atomic_block
        insert_calls.append(True)
        return original_create(**kwargs)

    monkeypatch.setattr(OpportunityRequirementAnalysis.objects, "create", checked_create)
    record = create_analysis(opportunity, actor, AnalysisFakeLLM(callback=check_provider_boundary))
    assert record.pk is not None
    assert insert_calls == [True]


def test_existing_transaction_is_rejected_before_any_llm_call(context):
    opportunity, actor = context
    provider = AnalysisFakeLLM()
    with transaction.atomic(), pytest.raises(TransactionManagementError):
        create_analysis(opportunity, actor, provider)
    assert provider.calls == []
    assert OpportunityRequirementAnalysis.objects.count() == 0


def test_post_insert_database_failure_rolls_back_without_second_llm_call(context, monkeypatch):
    opportunity, actor = context
    provider = AnalysisFakeLLM()
    original_create = OpportunityRequirementAnalysis.objects.create

    def insert_then_database_failure(**kwargs):
        original_create(**kwargs)
        assert OpportunityRequirementAnalysis.objects.count() == 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 / 0")

    monkeypatch.setattr(OpportunityRequirementAnalysis.objects, "create", insert_then_database_failure)
    with pytest.raises(DatabaseError):
        create_analysis(opportunity, actor, provider)
    assert len(provider.calls) == 1
    assert not connection.in_atomic_block
    assert OpportunityRequirementAnalysis.objects.count() == 0


@pytest.mark.parametrize("invalid_relation", ["opportunity", "created_by"])
def test_unsaved_relations_fail_before_provider_call(context, invalid_relation):
    opportunity, actor = context
    if invalid_relation == "opportunity":
        opportunity = Opportunity(project_name="未保存")
    else:
        actor = actor.__class__(username="未保存")
    provider = AnalysisFakeLLM()
    with pytest.raises(RequirementAnalysisError) as caught:
        create_analysis(opportunity, actor, provider)
    assert caught.value.code == "invalid_requirement_analysis_input"
    assert provider.calls == []


def test_storage_round_trip_reuses_strict_domain_validation(context):
    from apps.sales.services.requirement_analysis_history import analysis_record_to_domain

    opportunity, actor = context
    record = create_analysis(opportunity, actor, AnalysisFakeLLM())
    result = analysis_record_to_domain(record)
    assert result.requirements.budget.status == "conflict"
    assert result.conflicts[0].fields == ("budget",)
    record.requirements["extra"] = {}
    with pytest.raises(RequirementAnalysisError):
        analysis_record_to_domain(record)


def test_history_does_not_store_provider_secrets_or_call_other_ai_services(context, monkeypatch):
    from apps.knowledge.services import search
    from apps.rag.services import answering

    opportunity, actor = context

    def forbidden(*args, **kwargs):
        pytest.fail("History creation must not enter Knowledge, Embedding or RAG.")

    monkeypatch.setattr(search, "search_knowledge", forbidden)
    monkeypatch.setattr(search, "get_embedding_provider", forbidden)
    monkeypatch.setattr(answering, "answer_question", forbidden)
    provider = AnalysisFakeLLM()
    provider.api_key = "secret-key-sentinel"
    provider.reasoning_content = "reasoning-sentinel"
    provider.raw_response = "raw-response-sentinel"
    record = create_analysis(opportunity, actor, provider)
    stored = json.dumps(OpportunityRequirementAnalysis.objects.values().get(pk=record.pk), default=str)
    assert "secret-key-sentinel" not in stored
    assert "reasoning-sentinel" not in stored
    assert "raw-response-sentinel" not in stored
    assert provider.calls[0][0]["content"] not in stored
