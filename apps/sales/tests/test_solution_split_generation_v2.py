"""Three bounded provider passes feeding one unchanged Solution V2 draft."""

import json

import pytest

from apps.llm.base import LLMGeneration, LLMProvider
from apps.rag.tests.test_answering import search_result
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.tests.solution_fakes import analysis_record
from apps.sales.tests.test_solution_v2_pipeline import (
    _VerifierProvider,
    admission_fixture,
    analysis_fixture,
)


def _proposal(index, *, section, kind, key, field):
    return {
        "placement": {
            "section": section,
            "container_kind": kind,
            "container_key": key,
            "field": field,
        },
        "text": f"Proposal {index}",
        "citations": ["S1"],
        "related_requirement_fields": ["business_goal"],
    }


def _component(key="knowledge_service"):
    return [
        _proposal(
            index,
            section="architecture",
            kind="architecture_component",
            key=key,
            field=field,
        )
        for index, field in enumerate(
            ("identity", "responsibilities", "rationale", "interfaces"),
            start=1,
        )
    ]


def _core_payload(count=5):
    proposals = _component()
    proposals.extend(
        _proposal(
            index,
            section="proposed_solution",
            kind="root",
            key=None,
            field="overview",
        )
        for index in range(5, count + 1)
    )
    return {"proposals": proposals, "structure_relations": []}


def _implementation_payload(implementation=1, milestones=0):
    proposals = [
        _proposal(
            index,
            section="implementation_plan",
            kind="implementation_phase",
            key="delivery",
            field="tasks",
        )
        for index in range(1, implementation + 1)
    ]
    proposals.extend(
        _proposal(
            100 + index,
            section="milestones",
            kind="milestone",
            key=f"milestone_{index}",
            field="outcome",
        )
        for index in range(1, milestones + 1)
    )
    return {"proposals": proposals, "structure_relations": []}


def _assurance_payload(risks=0, acceptance=1, out_of_scope=0, *, phase="delivery"):
    proposals = [
        _proposal(
            index,
            section="risks",
            kind="risk",
            key=f"risk_{index}",
            field="condition",
        )
        for index in range(1, risks + 1)
    ]
    proposals.extend(
        _proposal(
            100 + index,
            section="acceptance_criteria",
            kind="acceptance_criterion",
            key=f"criterion_{index}",
            field="criterion",
        )
        for index in range(1, acceptance + 1)
    )
    proposals.extend(
        _proposal(
            200 + index,
            section="out_of_scope",
            kind="scope",
            key=f"scope_{index}",
            field="scope",
        )
        for index in range(1, out_of_scope + 1)
    )
    relations = []
    if acceptance:
        relations.append({
            "relation_type": "phase_acceptance",
            "source_container_kind": "implementation_phase",
            "source_container_key": phase,
            "target_container_kind": "acceptance_criterion",
            "target_container_key": "criterion_1",
        })
    return {"proposals": proposals, "structure_relations": relations}


def _parse_core(payload):
    from apps.sales.services.solution_prompt_v2 import parse_solution_v2_core_output

    return parse_solution_v2_core_output(
        json.dumps(payload), allowed_source_labels=("S1",)
    )


def _parse_implementation(payload, *, max_proposals=16):
    from apps.sales.services.solution_prompt_v2 import (
        parse_solution_v2_implementation_output,
    )

    return parse_solution_v2_implementation_output(
        json.dumps(payload),
        allowed_source_labels=("S1",),
        max_proposals=max_proposals,
    )


def _parse_assurance(payload, implementation, *, max_proposals=20):
    from apps.sales.services.solution_prompt_v2 import parse_solution_v2_assurance_output

    return parse_solution_v2_assurance_output(
        json.dumps(payload),
        allowed_source_labels=("S1",),
        implementation=implementation,
        max_proposals=max_proposals,
    )


def test_three_pass_limits_are_bounded_without_changing_core():
    from apps.sales.services.solution_prompt_v2 import (
        MAX_ASSURANCE_PROPOSALS,
        MAX_CORE_PROPOSALS,
        MAX_IMPLEMENTATION_PROPOSALS,
        MAX_SOLUTION_V2_PROPOSALS,
    )

    assert MAX_CORE_PROPOSALS == 46
    assert MAX_IMPLEMENTATION_PROPOSALS == 16
    assert MAX_ASSURANCE_PROPOSALS == 20
    assert MAX_SOLUTION_V2_PROPOSALS == 82


def test_core_accepts_46_and_rejects_47_proposals():
    assert len(_parse_core(_core_payload(46)).proposals) == 46
    with pytest.raises(SolutionDraftError):
        _parse_core(_core_payload(47))


@pytest.mark.parametrize(("core_count", "expected"), ((22, 16), (25, 16), (46, 16)))
def test_implementation_runtime_budget_uses_remaining_global_capacity(
    core_count, expected
):
    from apps.sales.services.solution_prompt_v2 import (
        implementation_runtime_proposal_budget,
    )

    assert implementation_runtime_proposal_budget(core_count) == expected


@pytest.mark.parametrize(
    ("core_count", "implementation_count", "expected"),
    ((22, 16, 20), (25, 16, 20), (46, 16, 20)),
)
def test_assurance_runtime_budget_uses_remaining_global_capacity(
    core_count, implementation_count, expected
):
    from apps.sales.services.solution_prompt_v2 import assurance_runtime_proposal_budget

    assert assurance_runtime_proposal_budget(
        core_count, implementation_count
    ) == expected


def test_pass_prompts_publish_runtime_and_section_contracts():
    from apps.sales.services.solution_prompt_v2 import (
        build_solution_v2_assurance_messages,
        build_solution_v2_core_messages,
        build_solution_v2_implementation_messages,
    )
    from apps.sales.services.solution_readiness import check_solution_readiness

    analysis = analysis_fixture()
    readiness = check_solution_readiness(analysis)
    admission = admission_fixture()
    core_prompt = build_solution_v2_core_messages(
        analysis, readiness, (), admission
    )[0]["content"]
    core = _parse_core(_core_payload(25))
    implementation_messages = build_solution_v2_implementation_messages(
        analysis, readiness, (), admission, core
    )
    implementation = _parse_implementation(_implementation_payload(14, 2))
    assurance_messages = build_solution_v2_assurance_messages(
        analysis, readiness, (), admission, core, implementation
    )

    implementation_prompt = implementation_messages[0]["content"]
    assurance_prompt = assurance_messages[0]["content"]
    assert "proposals 最多 46 条" in core_prompt
    assert "proposed_solution" in core_prompt
    assert "多个独立技术决策" in core_prompt
    assert "单条 proposal" in core_prompt
    assert "runtime proposal 总预算最多 16 条" in implementation_prompt
    assert "implementation_plan 最多 14 条" in implementation_prompt
    assert "milestones 最多 4 条" in implementation_prompt
    assert "runtime proposal 总预算最多 20 条" in assurance_prompt
    assert "risks 最多 3 个" in assurance_prompt
    assert "acceptance 最多 6 个" in assurance_prompt
    assert "out_of_scope 最多 2 条" in assurance_prompt
    assert "validated_technical_core" in implementation_messages[1]["content"]
    assert "validated_technical_core" in assurance_messages[1]["content"]
    assert "validated_implementation_plan" in assurance_messages[1]["content"]


def test_implementation_accepts_16_total_and_rejects_17():
    assert len(_parse_implementation(_implementation_payload(14, 2)).proposals) == 16
    with pytest.raises(SolutionDraftError):
        _parse_implementation(_implementation_payload(15, 2))


def test_implementation_section_ceilings_fail_closed():
    assert len(_parse_implementation(_implementation_payload(14, 0)).proposals) == 14
    with pytest.raises(SolutionDraftError):
        _parse_implementation(_implementation_payload(15, 0))
    assert len(_parse_implementation(_implementation_payload(1, 2)).proposals) == 3
    assert len(_parse_implementation(_implementation_payload(1, 4)).proposals) == 5
    with pytest.raises(SolutionDraftError):
        _parse_implementation(_implementation_payload(1, 5))


def test_assurance_accepts_20_total_and_rejects_21():
    implementation = _parse_implementation(_implementation_payload())
    assert len(
        _parse_assurance(_assurance_payload(12, 6, 2), implementation).proposals
    ) == 20
    with pytest.raises(SolutionDraftError):
        _parse_assurance(_assurance_payload(13, 6, 2), implementation)


def test_assurance_section_ceilings_fail_closed():
    implementation = _parse_implementation(_implementation_payload())
    assert len(_parse_assurance(_assurance_payload(12, 0, 0), implementation).proposals) == 12
    with pytest.raises(SolutionDraftError):
        _parse_assurance(_assurance_payload(13, 0, 0), implementation)
    assert len(_parse_assurance(_assurance_payload(0, 6, 0), implementation).proposals) == 6
    with pytest.raises(SolutionDraftError):
        _parse_assurance(_assurance_payload(0, 7, 0), implementation)


def test_implementation_and_assurance_reject_forbidden_placements():
    with pytest.raises(SolutionDraftError):
        _parse_implementation(_assurance_payload(1, 0, 0))

    implementation = _parse_implementation(_implementation_payload())
    with pytest.raises(SolutionDraftError):
        _parse_assurance(_implementation_payload(), implementation)


def test_assurance_rejects_dangling_phase_acceptance():
    implementation = _parse_implementation(_implementation_payload())
    with pytest.raises(SolutionDraftError):
        _parse_assurance(
            _assurance_payload(0, 1, 0, phase="missing_phase"), implementation
        )


def test_valid_three_pass_merge_is_deterministic_and_preserves_cross_pass_relation():
    from apps.sales.services.solution_prompt_v2 import (
        AtomicSolutionProposalSetV2,
        merge_solution_v2_proposal_passes,
    )

    core = _parse_core(_core_payload(46))
    implementation = _parse_implementation(_implementation_payload(14, 2))
    assurance = _parse_assurance(
        _assurance_payload(12, 6, 2), implementation, max_proposals=20
    )
    first = merge_solution_v2_proposal_passes(core, implementation, assurance)
    second = merge_solution_v2_proposal_passes(
        AtomicSolutionProposalSetV2(tuple(reversed(core.proposals)), ()),
        AtomicSolutionProposalSetV2(tuple(reversed(implementation.proposals)), ()),
        AtomicSolutionProposalSetV2(
            tuple(reversed(assurance.proposals)), assurance.structure_relations
        ),
    )

    assert len(first.proposals) == 82
    assert first == second
    assert first.structure_relations[-1].relation_type.value == "phase_acceptance"


def test_global_83_proposals_are_rejected_without_truncation():
    from apps.sales.services.solution_prompt_v2 import parse_atomic_solution_v2_proposals

    payload = json.dumps(_core_payload(83))
    with pytest.raises(SolutionDraftError):
        parse_atomic_solution_v2_proposals(
            payload, allowed_source_labels=("S1",), _max_proposals=82
        )


class _ThreePassProvider(LLMProvider):
    provider_name = "three-pass-fake"
    model_name = "three-pass-fake"

    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def generate(self, messages, *, max_output_tokens=None):
        pytest.fail("Solution V2 passes must request JSON output.")

    def generate_json(self, messages, *, max_output_tokens=None):
        self.calls.append((messages, max_output_tokens))
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return LLMGeneration(content=json.dumps(output))


def _run_pipeline_with_provider(monkeypatch, provider, *, verifier=None):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    sequence = iter((admission_fixture(), admission_fixture()))
    monkeypatch.setattr(service, "build_solution_admission", lambda *args: next(sequence))
    result = service.generate_grounded_solution_draft(
        analysis_record(),
        llm_provider=provider,
        verifier_provider=verifier,
        schema_version=2,
    )
    return result, provider


def _run_pipeline(monkeypatch, core, implementation, assurance, *, verifier=None):
    return _run_pipeline_with_provider(
        monkeypatch,
        _ThreePassProvider(core, implementation, assurance),
        verifier=verifier,
    )


@pytest.mark.parametrize("invalid_pass", ("core", "implementation", "assurance"))
def test_strict_pass_rejection_regenerates_only_that_pass_once(monkeypatch, invalid_pass):
    valid = (_core_payload(), _implementation_payload(), _assurance_payload())
    invalid = {
        "core": _implementation_payload(),
        "implementation": _core_payload(),
        "assurance": _implementation_payload(),
    }
    position = ("core", "implementation", "assurance").index(invalid_pass)
    outputs = (*valid[:position], invalid[invalid_pass], *valid[position:])
    provider = _ThreePassProvider(*outputs)
    verifier = _VerifierProvider()

    result, _ = _run_pipeline_with_provider(
        monkeypatch, provider, verifier=verifier
    )

    assert result.draft is not None
    assert len(provider.calls) == 4
    assert provider.calls[position][0] == provider.calls[position + 1][0]
    assert [budget for _, budget in provider.calls] == [6000] * 4
    assert verifier.calls


@pytest.mark.parametrize("invalid_pass", ("core", "implementation", "assurance"))
def test_two_strict_rejections_fail_closed_without_a_third_attempt(
    monkeypatch, invalid_pass
):
    valid = (_core_payload(), _implementation_payload(), _assurance_payload())
    invalid = {
        "core": _implementation_payload(),
        "implementation": _core_payload(),
        "assurance": _implementation_payload(),
    }
    position = ("core", "implementation", "assurance").index(invalid_pass)
    provider = _ThreePassProvider(
        *valid[:position], invalid[invalid_pass], invalid[invalid_pass]
    )
    verifier = _VerifierProvider()

    with pytest.raises(SolutionDraftError) as exc:
        _run_pipeline_with_provider(monkeypatch, provider, verifier=verifier)

    assert exc.value.code == "solution_draft_invalid_response"
    assert len(provider.calls) == position + 2
    assert verifier.calls == []


def test_deterministic_guard_failure_does_not_regenerate(monkeypatch):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    core = _core_payload()
    core["proposals"][0]["text"] = "建议按 10000 QPS 配置容量。"
    provider = _ThreePassProvider(
        core, _implementation_payload(), _assurance_payload()
    )
    verifier = _VerifierProvider()

    with pytest.raises(SolutionDraftGroundingError):
        _run_pipeline_with_provider(monkeypatch, provider, verifier=verifier)

    assert len(provider.calls) == 3
    assert verifier.calls == []


def test_qwen_veto_does_not_regenerate(monkeypatch):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    provider = _ThreePassProvider(
        _core_payload(), _implementation_payload(), _assurance_payload()
    )
    verifier = _VerifierProvider(relation="CONTRADICTED")

    with pytest.raises(SolutionDraftGroundingError):
        _run_pipeline_with_provider(monkeypatch, provider, verifier=verifier)

    assert len(provider.calls) == 3
    assert verifier.calls


def test_provider_failure_does_not_regenerate(monkeypatch):
    from apps.llm.exceptions import LLMErrorCode, LLMProviderError

    provider = _ThreePassProvider(
        LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR),
        _core_payload(),
    )

    with pytest.raises(LLMProviderError):
        _run_pipeline_with_provider(monkeypatch, provider)

    assert len(provider.calls) == 1


def test_v2_pipeline_generates_three_passes_then_verifies_one_unchanged_v2(monkeypatch):
    from apps.sales.services.solution_payloads import (
        serialize_solution_domain,
        solution_draft_v2_from_payload,
    )

    verifier = _VerifierProvider()
    result, provider = _run_pipeline(
        monkeypatch,
        _core_payload(),
        _implementation_payload(),
        _assurance_payload(),
        verifier=verifier,
    )

    assert [budget for _, budget in provider.calls] == [6000, 6000, 6000]
    assert len(provider.calls) == 3
    assert "validated_technical_core" in provider.calls[1][0][1]["content"]
    assert "validated_implementation_plan" in provider.calls[2][0][1]["content"]
    assert len(verifier.calls) == 7
    serialized = serialize_solution_domain(result.draft)
    assert serialized.schema_version == 2
    assert solution_draft_v2_from_payload(serialized.payload) == result.draft


@pytest.mark.parametrize("invalid_pass", ("implementation", "assurance"))
def test_any_later_pass_failure_never_reaches_verifier_or_returns_partial_draft(
    monkeypatch, invalid_pass
):
    implementation = _implementation_payload()
    assurance = _assurance_payload()
    invalid = _core_payload(4)
    if invalid_pass == "implementation":
        implementation = invalid
    else:
        assurance = invalid
    verifier = _VerifierProvider()
    outputs = (
        (_core_payload(), implementation, implementation)
        if invalid_pass == "implementation"
        else (_core_payload(), implementation, assurance, assurance)
    )
    provider = _ThreePassProvider(*outputs)

    with pytest.raises(SolutionDraftError):
        _run_pipeline_with_provider(monkeypatch, provider, verifier=verifier)
    assert verifier.calls == []


@pytest.mark.django_db(transaction=True)
def test_third_pass_failure_creates_zero_solution_or_provenance_rows(
    monkeypatch, make_user
):
    from apps.sales.models import (
        Customer,
        Opportunity,
        OpportunityRequirementAnalysis,
        SolutionDraftProvenance,
        SolutionDraftRecord,
    )
    from apps.sales.services import solution_draft as draft_service
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft
    from apps.sales.tests.solution_fakes import analysis_payload

    owner = make_user()
    customer = Customer.objects.create(name="Split failure customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Split failure opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
        raw_requirement="客户需要企业知识查询。",
    )
    payload = analysis_payload()
    analysis = OpportunityRequirementAnalysis.objects.create(
        opportunity=opportunity,
        created_by=owner,
        summary=payload["summary"],
        requirements=payload["requirements"],
        conflicts=payload["conflicts"],
        clarifying_questions=payload["clarifying_questions"],
        source_raw_requirement=opportunity.raw_requirement,
        source_context={"opportunity": {"project_name": opportunity.project_name}},
        analysis_version="v1",
        llm_provider="fake",
        llm_model="fake-model",
    )
    monkeypatch.setattr(
        draft_service, "search_knowledge", lambda **kwargs: [search_result()]
    )
    monkeypatch.setattr(
        draft_service, "build_solution_admission", lambda *args: admission_fixture()
    )

    provider = _ThreePassProvider(
        _core_payload(), _implementation_payload(),
        _core_payload(4), _core_payload(4),
    )
    with pytest.raises(SolutionDraftError):
        generate_and_persist_solution_draft(
            opportunity,
            analysis,
            created_by=owner,
            llm_provider=provider,
            verifier_provider=_VerifierProvider(),
            schema_version=2,
        )

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0
    assert len(provider.calls) == 4
