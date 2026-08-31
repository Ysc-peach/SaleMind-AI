"""Per-call output budgets without changing other tasks or retry behavior."""

import json

import pytest

from apps.llm.exceptions import LLMProviderError
from apps.llm.tests.test_deepseek_provider import _build_provider, _response
from apps.rag.tests.test_answering import search_result
from apps.sales.models import Customer, Opportunity
from apps.sales.tests.requirement_fakes import valid_analysis_payload
from apps.sales.tests.solution_fakes import analysis_record, SolutionFakeLLM, solution_payload


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *a, **kw: pytest.fail("Offline budget tests."))


def test_per_call_override_does_not_mutate_provider_default(monkeypatch):
    provider, endpoint, _ = _build_provider(monkeypatch)
    messages = [{"role": "user", "content": "问题"}]
    for options in ({}, {"max_output_tokens": 4000}, {"max_output_tokens": None}, {}):
        assert provider.generate(messages, **options).content == "SalesMind LLM connected"
    assert [call["max_tokens"] for call in endpoint.calls] == [321, 4000, 321, 321]
    assert all(call["extra_body"] == {"thinking": {"type": "disabled"}} for call in endpoint.calls)
    assert all(call["model"] == "deepseek-v4-flash" for call in endpoint.calls)


@pytest.mark.parametrize("budget", [0, -1, True, False, 1.5, "4000", [], {}])
def test_invalid_output_budget_fails_safely_before_sdk_call(monkeypatch, budget):
    provider, endpoint, _ = _build_provider(monkeypatch)
    with pytest.raises(LLMProviderError) as exc:
        provider.generate([{"role": "user", "content": "私密需求"}], max_output_tokens=budget)
    assert exc.value.code == "llm_not_configured"
    assert "私密需求" not in str(exc.value)
    assert endpoint.calls == []


def test_solution_default_output_budget_reaches_sdk_without_global_inflation(monkeypatch, settings):
    from apps.sales.services import solution_draft

    settings.LLM_MAX_OUTPUT_TOKENS = 321
    provider, endpoint, _ = _build_provider(monkeypatch, _response(json.dumps(solution_payload())))
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kw: [search_result()])
    result = solution_draft.generate_grounded_solution_draft(analysis_record(), llm_provider=provider)
    assert result.generation_status == "generated"
    assert len(endpoint.calls) == 1
    assert endpoint.calls[0]["max_tokens"] == 4000
    assert settings.LLM_MAX_OUTPUT_TOKENS == 321


def test_solution_server_setting_is_recorded_by_fake(monkeypatch, settings):
    from apps.sales.services import solution_draft

    settings.SOLUTION_DRAFT_MAX_OUTPUT_TOKENS = 3500
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kw: [search_result()])
    provider = SolutionFakeLLM()
    result = solution_draft.generate_grounded_solution_draft(analysis_record(), llm_provider=provider)
    assert result.generation_status == "generated"
    assert provider.requested_output_budgets == [3500]


@pytest.mark.parametrize("statuses", [{"budget": "conflict"}, {"data_security_requirement": "conflict"}, {}])
def test_short_circuits_never_request_output_budget(monkeypatch, statuses):
    from apps.sales.services import solution_draft

    def no_provider():
        pytest.fail("A short circuit must not construct a provider.")
    monkeypatch.setattr(solution_draft, "get_llm_provider", no_provider)
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kw: [])
    provider = SolutionFakeLLM()
    result = solution_draft.generate_grounded_solution_draft(analysis_record(**statuses), llm_provider=provider)
    assert result.draft is None and result.sources == ()
    assert provider.calls == []
    assert provider.requested_output_budgets == []


def test_requirement_analysis_still_uses_original_provider_default(monkeypatch):
    from apps.sales.services.requirement_analysis import analyze_opportunity_requirement

    provider, endpoint, _ = _build_provider(monkeypatch, _response(json.dumps(valid_analysis_payload())))
    opportunity = Opportunity(customer=Customer(name="测试客户"), project_name="测试项目", raw_requirement="测试需求")
    result = analyze_opportunity_requirement(opportunity, llm_provider=provider)
    assert result.requirements.budget.status == "conflict"
    assert len(endpoint.calls) == 1
    assert endpoint.calls[0]["max_tokens"] == 321


def test_rag_answer_still_uses_original_provider_default(monkeypatch):
    from apps.rag.services import answering

    provider, endpoint, _ = _build_provider(monkeypatch)
    monkeypatch.setattr(answering, "search_knowledge", lambda **kw: [search_result()])
    result = answering.answer_question("支持私有化部署吗？", llm_provider=provider)
    assert result.answer == "SalesMind LLM connected"
    assert len(endpoint.calls) == 1
    assert endpoint.calls[0]["max_tokens"] == 321


def test_truncated_solution_is_rejected_without_second_generation(monkeypatch):
    from apps.sales.services import solution_draft
    from apps.sales.services.solution_errors import SolutionDraftError

    provider, endpoint, _ = _build_provider(monkeypatch, _response('{"title": "截断'))
    monkeypatch.setattr(solution_draft, "search_knowledge", lambda **kw: [search_result()])
    with pytest.raises(SolutionDraftError) as exc:
        solution_draft.generate_grounded_solution_draft(analysis_record(), llm_provider=provider)
    assert exc.value.code == "solution_draft_invalid_response"
    assert len(endpoint.calls) == 1
    assert endpoint.calls[0]["max_tokens"] == 4000
