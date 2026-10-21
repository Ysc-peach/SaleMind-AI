"""Deterministic and probabilistic assembly boundaries for Solution V2."""

import json

import pytest

from apps.llm.base import LLMGeneration, LLMProvider
from apps.rag.tests.test_answering import search_result
from apps.sales.services.requirement_analysis import (
    ClarifyingQuestion,
    OpportunityRequirementAnalysis,
    RequirementDimension,
    RequirementDimensions,
    RequirementFieldAnalysis,
    RequirementStatus,
)
from apps.sales.services.solution_admission import (
    EnterpriseAdmissionDecision,
    EnterpriseClaimProvenance,
    GroundingAdmission,
)
from apps.sales.services.solution_schema import (
    AtomicSolutionClaim,
    AtomicSolutionClaimSet,
    SolutionSectionKey,
    SolutionStatementType,
)
from apps.sales.tests.solution_fakes import analysis_record


pytestmark = pytest.mark.django_db


def field(status, value=None):
    return RequirementFieldAnalysis(status=status, value=value, evidence=value)


def analysis_fixture():
    return OpportunityRequirementAnalysis(
        summary="客户需要企业知识查询，时间与集成协议待确认。",
        requirements=RequirementDimensions(
            business_goal=field(RequirementStatus.KNOWN, "企业知识查询"),
            use_scenario=field(RequirementStatus.KNOWN, "员工查询企业资料"),
            user_scale=field(RequirementStatus.KNOWN, "约 300 人"),
            deployment_requirement=field(RequirementStatus.KNOWN, "私有化部署"),
            data_security_requirement=field(RequirementStatus.KNOWN, "数据留在内网"),
            existing_environment=field(RequirementStatus.KNOWN, "Linux"),
            integration_requirement=field(RequirementStatus.UNCLEAR),
            timeline=field(RequirementStatus.UNKNOWN),
            budget=field(RequirementStatus.CONFLICT),
            technical_constraints=field(RequirementStatus.KNOWN, "PostgreSQL"),
        ),
        conflicts=(),
        clarifying_questions=(
            ClarifyingQuestion(
                RequirementDimension.INTEGRATION_REQUIREMENT,
                "请确认需要接入的身份协议。",
            ),
            ClarifyingQuestion(
                RequirementDimension.TIMELINE,
                "请确认期望上线日期。",
            ),
            ClarifyingQuestion(
                RequirementDimension.BUDGET,
                "请确认最终预算口径。",
            ),
        ),
    )


def admission_fixture():
    private = AtomicSolutionClaim(
        section=SolutionSectionKey.DEPLOYMENT,
        statement_type=SolutionStatementType.ENTERPRISE_FACT,
        text="SalesMind 支持私有化部署。",
        citations=("S1",),
    )
    unresolved = AtomicSolutionClaim(
        section=SolutionSectionKey.INTEGRATION,
        statement_type=SolutionStatementType.UNRESOLVED,
        text="当前企业资料未确认 SSO 集成，需要进一步确认。",
        citations=(),
    )
    return GroundingAdmission(
        claims=AtomicSolutionClaimSet((private, unresolved)),
        enterprise_decisions=(
            EnterpriseAdmissionDecision(
                subject_key="private_deployment",
                status="confirmed_supported",
                enterprise_fact_ids=(41,),
                needs_attention=False,
            ),
            EnterpriseAdmissionDecision(
                subject_key="sso_integration",
                status="unconfirmed",
                enterprise_fact_ids=(),
                needs_attention=False,
            ),
        ),
        enterprise_provenance=(
            EnterpriseClaimProvenance(
                claim=private,
                subject_key="private_deployment",
                fact_id=41,
            ),
        ),
        allowed_proposal_source_labels=("S1",),
    )


@pytest.mark.parametrize("retrieved", (False, True))
def test_v2_retrieval_without_approved_citations_stops_before_providers(monkeypatch, retrieved):
    from apps.sales.services import solution_draft as service
    from apps.sales.services.solution_errors import SolutionDraftError
    from apps.sales.models import SolutionDraftRecord, SolutionDraftProvenance

    # Keep the actual admission rules: a retrieved chunk without approved facts
    # cannot authorize any proposal citation.
    monkeypatch.setattr(service, "search_knowledge", lambda **kw: [search_result()] if retrieved else [])
    def forbidden(*args, **kwargs):
        pytest.fail("No authorized citations must stop before generation or verification")
    monkeypatch.setattr(service, "get_llm_provider", forbidden)
    monkeypatch.setattr(service, "get_verifier_provider", forbidden)
    with pytest.raises(SolutionDraftError) as caught:
        service.generate_grounded_solution_draft(analysis_record(), schema_version=2)
    assert caught.value.code == "solution_draft_insufficient_approved_evidence"
    assert not SolutionDraftRecord.objects.exists()
    assert not SolutionDraftProvenance.objects.exists()


def test_deterministic_v2_content_owns_customer_enterprise_and_unresolved_claims():
    from apps.sales.services.solution_schema_v2 import (
        SolutionClaimTypeV2,
        build_v2_deterministic_items,
    )

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    by_type = {}
    for item in result.claims:
        by_type.setdefault(item.statement_type, []).append(item)

    assert len(by_type[SolutionClaimTypeV2.CUSTOMER_FACT]) == 7
    assert any(
        item.text == "部署要求：私有化部署。"
        for item in by_type[SolutionClaimTypeV2.CUSTOMER_FACT]
    )
    assert [item.text for item in by_type[SolutionClaimTypeV2.ENTERPRISE_FACT]] == [
        "SalesMind 支持私有化部署。"
    ]
    assert len(by_type[SolutionClaimTypeV2.UNRESOLVED]) == 4
    assert any("SSO 集成" in item.text for item in by_type[SolutionClaimTypeV2.UNRESOLVED])


def test_every_nonknown_requirement_maps_once_to_open_question_and_assumption():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert [item.requirement_field for item in result.open_questions] == [
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.TIMELINE,
        RequirementDimension.BUDGET,
    ]
    assert len(result.assumption_claim_ids) == 3
    question_claims = {
        item.requirement_field: result.claim_by_id(item.unresolved_claim_id)
        for item in result.open_questions
    }
    assert question_claims[RequirementDimension.TIMELINE].text.endswith(
        "请确认期望上线日期。"
    )
    assert question_claims[RequirementDimension.BUDGET].text.startswith(
        "预算存在冲突"
    )


def test_stable_claim_ids_follow_canonical_order_and_are_not_text_hashes():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    first = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    second = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert [item.claim_id for item in first.claims] == [
        f"C{index:04d}" for index in range(1, len(first.claims) + 1)
    ]
    assert first.claims == second.claims


def test_enterprise_claim_binding_uses_exact_admission_fact_identity():
    from apps.sales.services.solution_schema_v2 import build_v2_deterministic_items

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())
    enterprise = next(item for item in result.claims if item.citations == ("S1",))

    assert result.provenance_bindings == (
        type(result.provenance_bindings[0])(
            claim_id=enterprise.claim_id,
            citation_label="S1",
            fact_id=41,
        ),
    )


def test_unconfirmed_enterprise_decision_never_becomes_enterprise_fact():
    from apps.sales.services.solution_schema_v2 import (
        SolutionClaimTypeV2,
        build_v2_deterministic_items,
    )

    result = build_v2_deterministic_items(analysis_fixture(), admission_fixture())

    assert not any(
        item.statement_type is SolutionClaimTypeV2.ENTERPRISE_FACT
        and "SSO" in item.text
        for item in result.claims
    )
    assert any(
        item.statement_type is SolutionClaimTypeV2.UNRESOLVED and "SSO" in item.text
        for item in result.claims
    )


class _GenerationProvider(LLMProvider):
    provider_name = "v2-generation-fake"
    model_name = "v2-generation-fake"

    def __init__(self, proposals, *, structure_relations=()):
        self.proposals = proposals
        self.structure_relations = structure_relations
        self.calls = []

    def generate(self, messages, *, max_output_tokens=None):
        self.calls.append(messages)
        system_prompt = messages[0]["content"]
        if "Pass 1 — Technical Core" in system_prompt:
            allowed_sections = {
                "proposed_solution", "architecture", "deployment_and_integration",
            }
            allowed_relations = {
                "component_dependency", "component_request_flow",
                "component_data_flow",
            }
        elif "Pass 2 — Implementation Planning" in system_prompt:
            allowed_sections = {"implementation_plan", "milestones"}
            allowed_relations = {"phase_dependency", "milestone_phase"}
        else:
            allowed_sections = {"risks", "acceptance_criteria", "out_of_scope"}
            allowed_relations = {"phase_acceptance"}
        return LLMGeneration(content=json.dumps({
            "proposals": [
                item for item in self.proposals
                if item["placement"]["section"] in allowed_sections
            ],
            "structure_relations": [
                item for item in self.structure_relations
                if item["relation_type"] in allowed_relations
            ],
        }, ensure_ascii=False))


class _VerifierProvider(LLMProvider):
    provider_name = "v2-verifier-fake"
    model_name = "v2-verifier-fake"

    def __init__(self, *, relation="SUPPORTED", callback=None):
        self.relation = relation
        self.callback = callback
        self.calls = []

    def generate(self, messages, *, max_output_tokens=None):
        import html
        import re

        match = re.search(
            r"<proposal_admissibility_packets>(.*?)</proposal_admissibility_packets>",
            messages[-1]["content"],
            flags=re.DOTALL,
        )
        packet = json.loads(html.unescape(match.group(1)))["proposals"]
        self.calls.append(packet)
        if self.callback:
            self.callback()
        return LLMGeneration(content=json.dumps({"results": [{
            "location": packet[0]["location"],
            "decision": (
                "ADMISSIBLE" if self.relation == "SUPPORTED" else "INADMISSIBLE"
            ),
            "atomicity": "ATOMIC",
        }]}))


def _proposal(text, *, section="architecture", kind="architecture_component", key="knowledge_service", field="responsibilities"):
    return {
        "placement": {
            "section": section,
            "container_kind": kind,
            "container_key": key,
            "field": field,
        },
        "text": text,
        "citations": ["S1"],
    }


def _complete_component(*, key, identity, responsibility):
    return (
        _proposal(identity, key=key, field="identity"),
        _proposal(responsibility, key=key),
        _proposal(f"{identity}用于形成清晰的方案职责边界。", key=key, field="rationale"),
        _proposal(f"{identity}通过受控接口与相邻组件交互。", key=key, field="interfaces"),
    )


def _generate_v2(
    monkeypatch,
    proposals,
    *,
    verifier=None,
    admissions=None,
    structure_relations=(),
):
    from apps.sales.services import solution_draft as service

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    sequence = iter(admissions or (admission_fixture(), admission_fixture()))
    monkeypatch.setattr(service, "build_solution_admission", lambda *args: next(sequence))
    generation = _GenerationProvider(
        proposals, structure_relations=structure_relations
    )
    return service.generate_grounded_solution_draft(
        analysis_record(),
        llm_provider=generation,
        verifier_provider=verifier,
        schema_version=2,
    ), generation


def test_explicit_v2_selection_rejects_deterministic_only_generation(monkeypatch):
    from apps.sales.services.solution_errors import SolutionDraftError

    verifier = _VerifierProvider()
    with pytest.raises(SolutionDraftError) as caught:
        _generate_v2(monkeypatch, [], verifier=verifier)

    assert caught.value.code == "solution_draft_no_proposals"
    assert verifier.calls == []


def test_v2_generation_uses_json_output_capability_when_available(monkeypatch):
    from apps.sales.services import solution_draft as service
    from apps.sales.services.solution_errors import SolutionDraftError

    class JsonGenerationProvider(_GenerationProvider):
        def __init__(self):
            super().__init__([])
            self.json_calls = []

        def generate(self, messages, *, max_output_tokens=None):
            pytest.fail("V2 generation must request JSON output.")

        def generate_json(self, messages, *, max_output_tokens=None):
            self.json_calls.append(max_output_tokens)
            return LLMGeneration(content=json.dumps({
                "proposals": [],
                "structure_relations": [],
            }))

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: [search_result()])
    sequence = iter((admission_fixture(), admission_fixture()))
    monkeypatch.setattr(service, "build_solution_admission", lambda *args: next(sequence))
    provider = JsonGenerationProvider()

    with pytest.raises(SolutionDraftError) as caught:
        service.generate_grounded_solution_draft(
            analysis_record(), llm_provider=provider, schema_version=2,
        )

    assert caught.value.code == "solution_draft_no_proposals"
    assert provider.json_calls == [6000, 6000, 6000]


def test_each_v2_proposal_is_verified_independently_and_placement_order_survives(monkeypatch):
    proposals = (*_complete_component(
        key="knowledge_service",
        identity="企业知识服务",
        responsibility="建议知识服务承担统一检索职责。",
    ),
        _proposal(
            "建议将私有化部署纳入总体方案。",
            section="proposed_solution",
            kind="root",
            key=None,
            field="overview",
        ),
    )
    verifier = _VerifierProvider()

    (result, _) = _generate_v2(monkeypatch, proposals, verifier=verifier)

    assert len(verifier.calls) == 5
    assert all(len(call) == 1 for call in verifier.calls)
    assert {call[0]["text"] for call in verifier.calls} == {
        item["text"] for item in proposals
    }
    component = result.draft.architecture.components[0]
    by_id = {claim.claim_id: claim for claim in result.draft.claims}
    assert by_id[component.identity_claim_id].text == proposals[0]["text"]
    assert by_id[component.responsibility_claim_ids[0]].text == proposals[1]["text"]
    assert by_id[result.draft.proposed_solution.overview_claim_ids[-1]].text == proposals[-1]["text"]


def test_generation_pipeline_preserves_validated_structure_relations(monkeypatch):
    proposals = (*_complete_component(
        key="identity_boundary",
        identity="统一身份与权限服务",
        responsibility="身份边界负责统一访问校验。",
    ), *_complete_component(
        key="application_service",
        identity="企业应用服务",
        responsibility="应用服务负责查询编排。",
    ),
        _proposal(
            "确认需求与接口边界。",
            section="implementation_plan",
            kind="implementation_phase",
            key="discovery",
            field="objective",
        ),
        _proposal(
            "实现核心查询链路。",
            section="implementation_plan",
            kind="implementation_phase",
            key="build",
            field="objective",
        ),
        _proposal(
            "未授权用户无法查询受限知识。",
            section="acceptance_criteria",
            kind="acceptance_criterion",
            key="access_control",
            field="criterion",
        ),
        _proposal(
            "核心查询链路完成验证。",
            section="milestones",
            kind="milestone",
            key="core_ready",
            field="outcome",
        ),
    )
    relations = (
        {
            "relation_type": "component_dependency",
            "source_container_kind": "architecture_component",
            "source_container_key": "application_service",
            "target_container_kind": "architecture_component",
            "target_container_key": "identity_boundary",
        },
        {
            "relation_type": "component_request_flow",
            "source_container_kind": "architecture_component",
            "source_container_key": "identity_boundary",
            "target_container_kind": "architecture_component",
            "target_container_key": "application_service",
        },
        {
            "relation_type": "phase_dependency",
            "source_container_kind": "implementation_phase",
            "source_container_key": "build",
            "target_container_kind": "implementation_phase",
            "target_container_key": "discovery",
        },
        {
            "relation_type": "phase_acceptance",
            "source_container_kind": "implementation_phase",
            "source_container_key": "build",
            "target_container_kind": "acceptance_criterion",
            "target_container_key": "access_control",
        },
        {
            "relation_type": "milestone_phase",
            "source_container_kind": "milestone",
            "source_container_key": "core_ready",
            "target_container_kind": "implementation_phase",
            "target_container_key": "build",
        },
    )

    result, _ = _generate_v2(
        monkeypatch,
        proposals,
        verifier=_VerifierProvider(),
        structure_relations=relations,
    )

    components = {
        item.component_id: item for item in result.draft.architecture.components
    }
    phases = {
        item.phase_id: item for item in result.draft.implementation_plan.phases
    }
    assert components["application_service"].dependency_component_ids == (
        "identity_boundary",
    )
    assert phases["build"].dependency_phase_ids == ("discovery",)
    assert phases["build"].acceptance_criterion_ids == ("access_control",)
    assert result.draft.milestones[0].related_phase_ids == ("build",)


def test_model_container_key_never_becomes_a_visible_semantic_label(monkeypatch):
    verifier = _VerifierProvider()
    (result, _) = _generate_v2(
        monkeypatch,
        [
            *_complete_component(
                key="supports_oracle",
                identity="兼容性评估组件",
                responsibility="建议设置兼容性评估组件。",
            ),
        ],
        verifier=verifier,
    )

    component = result.draft.architecture.components[0]
    assert component.component_id == "supports_oracle"
    assert component.name == "架构组件 1"
    assert "oracle" not in component.name.lower()


def test_v2_proposal_verifier_rejection_aborts_whole_draft_without_partial_leak(monkeypatch):
    from apps.sales.services.solution_grounding import SolutionDraftGroundingError

    verifier = _VerifierProvider(relation="INSUFFICIENT")
    with pytest.raises(SolutionDraftGroundingError):
        _generate_v2(
            monkeypatch,
            _complete_component(
                key="knowledge_service",
                identity="证据不足的方案组件",
                responsibility="该组件承担知识查询职责。",
            ),
            verifier=verifier,
        )

    assert 1 <= len(verifier.calls) <= 4
    assert all(len(call) == 1 for call in verifier.calls)


def test_v2_return_time_admission_drift_fails_before_assembly(monkeypatch):
    from dataclasses import replace
    from apps.sales.services.solution_errors import SolutionDraftError

    original = admission_fixture()
    changed = replace(original, allowed_proposal_source_labels=())

    with pytest.raises(SolutionDraftError) as exc:
        _generate_v2(
            monkeypatch,
            _complete_component(
                key="knowledge_service",
                identity="企业知识服务",
                responsibility="该服务承担知识查询职责。",
            ),
            verifier=_VerifierProvider(),
            admissions=(original, changed),
        )

    assert exc.value.code == "invalid_solution_draft_input"


def test_unknown_generation_schema_fails_before_search(monkeypatch):
    from apps.sales.services import solution_draft as service
    from apps.sales.services.solution_errors import SolutionDraftError

    monkeypatch.setattr(service, "search_knowledge", lambda **kwargs: pytest.fail("must not search"))
    with pytest.raises(SolutionDraftError):
        service.generate_grounded_solution_draft(analysis_record(), schema_version=99)
