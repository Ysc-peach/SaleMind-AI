"""Closed generation IR for placing verified proposals in Solution Domain V2."""

import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from html import escape
from typing import NoReturn

from apps.knowledge.models import EnterpriseGroundingFactStatus
from apps.knowledge.evidence import format_source
from apps.llm.base import LLMMessage
from apps.sales.services.requirement_analysis import (
    OpportunityRequirementAnalysis,
    RequirementDimension,
    RequirementStatus,
)
from apps.sales.services.solution_admission import GroundingAdmission
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_readiness import SolutionReadiness
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import SolutionStatementType
from apps.sales.services.solution_prompt_v2_text import (
    _ASSURANCE_PASS_CONTRACT,
    _ASSURANCE_PASS_EXAMPLE,
    _CORE_PASS_CONTRACT,
    _CORE_PASS_EXAMPLE,
    _IMPLEMENTATION_PASS_CONTRACT,
    _IMPLEMENTATION_PASS_EXAMPLE,
    _SYSTEM_PROMPT,
)


from apps.sales.services.solution_generation_contract import (
    MAX_ARCHITECTURE_COMPONENTS,
    CORE_PROPOSED_SOLUTION_LIMIT,
    CORE_ARCHITECTURE_OVERVIEW_LIMIT,
    CORE_COMPONENT_FIELD_LIMITS,
    CORE_DEPLOYMENT_TOPIC_LIMITS,
    CORE_CAPABILITY_GROUP_LIMIT,
    CORE_CAPABILITY_GROUP_ITEMS_LIMIT,
    MAX_CORE_PROPOSALS,
    MAX_IMPLEMENTATION_PROPOSALS,
    MAX_ASSURANCE_PROPOSALS,
    MAX_ASSURANCE_RISKS,
    ASSURANCE_RISK_FIELDS,
    MAX_ASSURANCE_ACCEPTANCE,
    MAX_ASSURANCE_OUT_OF_SCOPE,
    MAX_ASSURANCE_PHASE_ACCEPTANCE,
    MAX_SOLUTION_V2_PROPOSALS,
    MAX_IMPLEMENTATION_PHASES,
    IMPLEMENTATION_PHASE_FIELD_LIMITS,
    MAX_IMPLEMENTATION_MILESTONES,
    IMPLEMENTATION_MILESTONE_FIELD_LIMITS,
    IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
    ASSURANCE_SECTION_PROPOSAL_LIMITS,
    LOCAL_REF,
    MANAGED_LINKAGE_PLACEMENTS,
    SEMANTIC_IR_VERSION,
    SEMANTIC_ROOT_KEYS,
    validate_claim_fields,
    validate_citation_allowlist,
    closed_object,
    reject_contract,
)

_MAX_LEGACY_SINGLE_PASS_PROPOSALS = 38

class SolutionV2Section(StrEnum):
    PROPOSED_SOLUTION = "proposed_solution"
    ARCHITECTURE = "architecture"
    DEPLOYMENT_AND_INTEGRATION = "deployment_and_integration"
    IMPLEMENTATION_PLAN = "implementation_plan"
    RISKS = "risks"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    MILESTONES = "milestones"
    OUT_OF_SCOPE = "out_of_scope"


class SolutionV2ContainerKind(StrEnum):
    ROOT = "root"
    CAPABILITY_GROUP = "capability_group"
    ARCHITECTURE_COMPONENT = "architecture_component"
    TOPIC_BLOCK = "topic_block"
    IMPLEMENTATION_PHASE = "implementation_phase"
    RISK = "risk"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    MILESTONE = "milestone"
    SCOPE = "scope"


class SolutionV2PlacementField(StrEnum):
    OVERVIEW = "overview"
    ITEMS = "items"
    IDENTITY = "identity"
    RESPONSIBILITIES = "responsibilities"
    RATIONALE = "rationale"
    INTERFACES = "interfaces"
    OBJECTIVE = "objective"
    TASKS = "tasks"
    DELIVERABLES = "deliverables"
    TIMING = "timing"
    CONDITION = "condition"
    IMPACT = "impact"
    MITIGATION = "mitigation"
    TRIGGER = "trigger"
    CRITERION = "criterion"
    OUTCOME = "outcome"
    SCOPE = "scope"


class SolutionV2StructureRelationType(StrEnum):
    COMPONENT_DEPENDENCY = "component_dependency"
    COMPONENT_REQUEST_FLOW = "component_request_flow"
    COMPONENT_DATA_FLOW = "component_data_flow"
    PHASE_DEPENDENCY = "phase_dependency"
    PHASE_ACCEPTANCE = "phase_acceptance"
    MILESTONE_PHASE = "milestone_phase"


class SolutionV2OutputDiagnosticCategory(StrEnum):
    """Safe evaluation-only categories; never exposed by the runtime API."""

    MALFORMED_JSON = "malformed_json"
    UNKNOWN_KEY = "unknown_key"
    WRONG_VALUE_TYPE = "wrong_value_type"
    PROPOSAL_COUNT_EXCEEDED = "proposal_count_exceeded"
    COMPONENT_COUNT_EXCEEDED = "component_count_exceeded"
    MISSING_COMPONENT_IDENTITY = "missing_component_identity"
    MISSING_COMPONENT_RESPONSIBILITY = "missing_component_responsibility"
    MISSING_COMPONENT_RATIONALE = "missing_component_rationale"
    MISSING_COMPONENT_INTERFACE = "missing_component_interface"
    INVALID_PLACEMENT = "invalid_placement"
    INVALID_RELATION_TYPE = "invalid_relation_type"
    DANGLING_RELATION = "dangling_relation"
    SELF_RELATION = "self_relation"
    DUPLICATE_RELATION = "duplicate_relation"
    DEPENDENCY_CYCLE = "dependency_cycle"
    MISSING_REQUEST_FLOW = "missing_request_flow"
    MALFORMED_REQUIREMENT_LINKAGE = "malformed_requirement_linkage"
    INVALID_CITATION = "invalid_citation"
    IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED = (
        "implementation_total_budget_exceeded"
    )
    ASSURANCE_TOTAL_BUDGET_EXCEEDED = "assurance_total_budget_exceeded"
    IMPLEMENTATION_BUDGET_EXCEEDED = "implementation_budget_exceeded"
    RISK_BUDGET_EXCEEDED = "risk_budget_exceeded"
    ACCEPTANCE_BUDGET_EXCEEDED = "acceptance_budget_exceeded"
    MILESTONE_BUDGET_EXCEEDED = "milestone_budget_exceeded"
    ASSUMPTION_BUDGET_EXCEEDED = "assumption_budget_exceeded"
    OPEN_QUESTION_BUDGET_EXCEEDED = "open_question_budget_exceeded"
    OUT_OF_SCOPE_BUDGET_EXCEEDED = "out_of_scope_budget_exceeded"
    UNCLASSIFIED_CONTRACT_FAILURE = "unclassified_contract_failure"


@dataclass(frozen=True, slots=True)
class SolutionV2Placement:
    section: SolutionV2Section
    container_kind: SolutionV2ContainerKind
    container_key: str | None
    field: SolutionV2PlacementField


@dataclass(frozen=True, slots=True)
class SolutionV2StructureRelation:
    relation_type: SolutionV2StructureRelationType
    source_container_kind: SolutionV2ContainerKind
    source_container_key: str
    target_container_kind: SolutionV2ContainerKind
    target_container_key: str


@dataclass(frozen=True, slots=True)
class AtomicSolutionProposalV2:
    placement: SolutionV2Placement
    text: str
    citations: tuple[str, ...]
    related_requirement_fields: tuple[RequirementDimension, ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicSolutionProposalSetV2:
    proposals: tuple[AtomicSolutionProposalV2, ...]
    structure_relations: tuple[SolutionV2StructureRelation, ...] = ()


_ALLOWED_PLACEMENTS = {
    (SolutionV2Section.PROPOSED_SOLUTION, SolutionV2ContainerKind.ROOT): {
        SolutionV2PlacementField.OVERVIEW,
    },
    (SolutionV2Section.PROPOSED_SOLUTION, SolutionV2ContainerKind.CAPABILITY_GROUP): {
        SolutionV2PlacementField.ITEMS,
    },
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ROOT): {
        SolutionV2PlacementField.OVERVIEW,
    },
    (SolutionV2Section.ARCHITECTURE, SolutionV2ContainerKind.ARCHITECTURE_COMPONENT): {
        SolutionV2PlacementField.IDENTITY,
        SolutionV2PlacementField.RESPONSIBILITIES,
        SolutionV2PlacementField.RATIONALE,
        SolutionV2PlacementField.INTERFACES,
    },
    (SolutionV2Section.DEPLOYMENT_AND_INTEGRATION, SolutionV2ContainerKind.TOPIC_BLOCK): {
        SolutionV2PlacementField.ITEMS,
    },
    (SolutionV2Section.IMPLEMENTATION_PLAN, SolutionV2ContainerKind.IMPLEMENTATION_PHASE): {
        SolutionV2PlacementField.OBJECTIVE,
        SolutionV2PlacementField.TASKS,
        SolutionV2PlacementField.DELIVERABLES,
        SolutionV2PlacementField.TIMING,
    },
    (SolutionV2Section.RISKS, SolutionV2ContainerKind.RISK): {
        SolutionV2PlacementField.CONDITION,
        SolutionV2PlacementField.IMPACT,
        SolutionV2PlacementField.MITIGATION,
        SolutionV2PlacementField.TRIGGER,
    },
    (SolutionV2Section.ACCEPTANCE_CRITERIA, SolutionV2ContainerKind.ACCEPTANCE_CRITERION): {
        SolutionV2PlacementField.CRITERION,
    },
    (SolutionV2Section.MILESTONES, SolutionV2ContainerKind.MILESTONE): {
        SolutionV2PlacementField.OUTCOME,
        SolutionV2PlacementField.TIMING,
    },
    (SolutionV2Section.OUT_OF_SCOPE, SolutionV2ContainerKind.SCOPE): {
        SolutionV2PlacementField.SCOPE,
    },
}

_RELATION_KINDS = {
    SolutionV2StructureRelationType.COMPONENT_DEPENDENCY: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.COMPONENT_DATA_FLOW: (
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
        SolutionV2ContainerKind.ARCHITECTURE_COMPONENT,
    ),
    SolutionV2StructureRelationType.PHASE_DEPENDENCY: (
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
    ),
    SolutionV2StructureRelationType.PHASE_ACCEPTANCE: (
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
        SolutionV2ContainerKind.ACCEPTANCE_CRITERION,
    ),
    SolutionV2StructureRelationType.MILESTONE_PHASE: (
        SolutionV2ContainerKind.MILESTONE,
        SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
    ),
}

_CORE_SECTIONS = frozenset({
    SolutionV2Section.PROPOSED_SOLUTION,
    SolutionV2Section.ARCHITECTURE,
    SolutionV2Section.DEPLOYMENT_AND_INTEGRATION,
})
_IMPLEMENTATION_SECTIONS = frozenset({
    SolutionV2Section.IMPLEMENTATION_PLAN,
    SolutionV2Section.MILESTONES,
})
_ASSURANCE_SECTIONS = frozenset({
    SolutionV2Section.RISKS,
    SolutionV2Section.ACCEPTANCE_CRITERIA,
    SolutionV2Section.OUT_OF_SCOPE,
})
_CORE_RELATIONS = frozenset({
    SolutionV2StructureRelationType.COMPONENT_DEPENDENCY,
    SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW,
    SolutionV2StructureRelationType.COMPONENT_DATA_FLOW,
})
_IMPLEMENTATION_RELATIONS = frozenset({
    SolutionV2StructureRelationType.PHASE_DEPENDENCY,
    SolutionV2StructureRelationType.MILESTONE_PHASE,
})
_ASSURANCE_RELATIONS = frozenset({
    SolutionV2StructureRelationType.PHASE_ACCEPTANCE,
})

_CONTAINER_KEY = LOCAL_REF



def build_solution_v2_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> list[LLMMessage]:
    """Build proposal-only V2 messages from program-admitted evidence."""

    if not isinstance(analysis, OpportunityRequirementAnalysis):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    customer = escape(json.dumps(asdict(analysis), ensure_ascii=False), quote=False)
    readiness_data = escape(json.dumps(asdict(readiness), ensure_ascii=False), quote=False)
    admitted_claims = escape(
        json.dumps([asdict(item) for item in admission.claims.claims], ensure_ascii=False),
        quote=False,
    )
    allowed = frozenset(admission.allowed_proposal_source_labels)
    evidence = "\n\n".join(
        format_source(source, source_id=source.label)
        for source in sources
        if source.label in allowed
    )
    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.replace(
                "__REQUIREMENT_DIMENSIONS__",
                ", ".join(item.value for item in RequirementDimension),
            ),
        },
        {"role": "user", "content": (
            f"<customer_requirements>\n{customer}\n</customer_requirements>\n"
            f"<solution_readiness>\n{readiness_data}\n</solution_readiness>\n"
            f"<program_admitted_claims>\n{admitted_claims}\n</program_admitted_claims>\n"
            f"<allowed_enterprise_capabilities>\n{evidence}\n</allowed_enterprise_capabilities>"
        )},
    ]




def _solution_v2_input_context(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> str:
    if not isinstance(analysis, OpportunityRequirementAnalysis):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    customer = escape(json.dumps(asdict(analysis), ensure_ascii=False), quote=False)
    readiness_data = escape(json.dumps(asdict(readiness), ensure_ascii=False), quote=False)
    # Project for generation only: negative facts keep their original admission
    # and durable provenance, but are not offered as positive capability citations.
    # Source membership alone is insufficient: one chunk may support one subject
    # while explicitly denying another.
    # Classify the existing dimensions only. Do not infer confirmed subfacts
    # from an unclear value or mutate the saved analysis/admission authority.
    design_scope = {"confirmed_fields": [], "conditional_fields": {}}
    for dimension in RequirementDimension:
        requirement = getattr(analysis.requirements, dimension.value)
        if requirement.status is RequirementStatus.KNOWN:
            design_scope["confirmed_fields"].append(dimension.value)
        else:
            design_scope["conditional_fields"][dimension.value] = requirement.status.value
    design_scope_json = escape(json.dumps(design_scope, ensure_ascii=False), quote=False)
    supported_subjects = {
        item.subject_key for item in admission.enterprise_decisions
        if item.status == EnterpriseGroundingFactStatus.CONFIRMED_SUPPORTED
    }
    supported_claims = {
        item.claim for item in admission.enterprise_provenance
        if item.subject_key in supported_subjects
    }
    usable, boundaries = [], []
    for item in admission.claims.claims:
        projected = asdict(item)
        if (
            item.statement_type == SolutionStatementType.UNRESOLVED
            or (item.statement_type == SolutionStatementType.ENTERPRISE_FACT
                and item not in supported_claims)
        ):
            projected.pop("citations")
            boundaries.append(projected)
        else:
            usable.append(projected)
    admitted_claims = escape(json.dumps(usable, ensure_ascii=False), quote=False)
    boundary_claims = escape(json.dumps(boundaries, ensure_ascii=False), quote=False)
    allowed = frozenset(admission.allowed_proposal_source_labels)
    evidence = "\n\n".join(
        format_source(source, source_id=source.label)
        for source in sources
        if source.label in allowed
    )
    return (
        f"<customer_requirements>\n{customer}\n</customer_requirements>\n"
        f"<requirement_design_scope>\n{design_scope_json}\n</requirement_design_scope>\n"
        f"<solution_readiness>\n{readiness_data}\n</solution_readiness>\n"
        f"<program_admitted_claims>\n{admitted_claims}\n</program_admitted_claims>\n"
        f"<solution_boundaries>\n{boundary_claims}\n</solution_boundaries>\n"
        "<generation_context_rules>\n"
        "solution_boundaries 保留已确认不支持、冲突和待确认的方案边界；"
        "不得忽略、改写或将其升格为支持，也不得从该块生成 proposal citation。"
        "边界中的企业事实仍保留既有事实状态，不因未展示来源编号而变为未确认。"
        "proposal 只引用 allowed_citation_ids 中的编号，且实际证据必须支持对应判断。"
        "\n</generation_context_rules>\n"
        "<allowed_citation_ids>\n"
        f"{escape(json.dumps(admission.allowed_proposal_source_labels), quote=False)}\n"
        "</allowed_citation_ids>\n"
        f"<allowed_enterprise_capabilities>\n{evidence}\n</allowed_enterprise_capabilities>"
    )


def _pass_system_prompt(contract: str, example: str) -> str:
    prompt = _SYSTEM_PROMPT.replace(
            "__REQUIREMENT_DIMENSIONS__",
            ", ".join(item.value for item in RequirementDimension),
        )
    prompt = prompt.replace(
        "顶层恰好只有 proposals、structure_relations；proposals 数量为 0 至 38，绝对不得超过 38，这是最大上限而不是目标数量；只生成完成当前方案真正需要的 proposal。",
        "顶层恰好只有 proposals、structure_relations；只生成完成当前 pass 真正需要的 proposal，并严格遵守下方当前 pass 上限。",
    ).replace(
        "使用 4 个组件时，identity、responsibility、rationale、interface 至少占用 16 条 proposal，其余所有 section 必须共享剩余最多 22 条，不得通过增加低价值 claim 挤占预算。",
        "使用 4 个组件时，identity、responsibility、rationale、interface 至少占用 16 条 proposal，不得通过增加低价值 claim 挤占当前 pass 预算。",
    ).replace(
        "proposal 总数不超过 38；组件不超过 4；",
        "proposal 总数不超过当前 pass 的明确上限；组件不超过 4；",
    )
    example_start = "只返回一个 JSON 对象，不含 Markdown 或解释：\n"
    example_end = "\n顶层恰好只有 proposals、structure_relations；"
    prefix, marker, remainder = prompt.partition(example_start)
    _old_example, suffix_marker, suffix = remainder.partition(example_end)
    if not marker or not suffix_marker:
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    prompt = prefix + example_start + example + example_end + suffix
    return prompt + contract


def _semantic_pass_prompt(
    pass_name: str, runtime_budget: int, *, allowed_source_labels: tuple[str, ...],
) -> str:
    """Keep proposal semantics while replacing repeated placement envelopes."""

    validate_citation_allowlist(allowed_source_labels)
    if not allowed_source_labels:
        _invalid(SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE)
    claim = {"text": "独立应用边界便于隔离业务入口。", "citations": [allowed_source_labels[0]],
             "related_requirement_fields": ["business_goal"]}
    def sample(text: str, *, related_fields: tuple[str, ...] = ("business_goal",)) -> dict:
        return {**claim, "text": text, "related_requirement_fields": list(related_fields)}
    if pass_name == "core":
        example = {
            "ir_version": SEMANTIC_IR_VERSION, "proposed_solution": [sample("设置受控的企业应用入口。")],
            "capability_groups": [{
                "ref": "capability_basis",
                "items": [sample("已批准能力可支撑受控的企业应用入口。")],
            }],
            "architecture": {"overview": [sample("建议将入口与业务处理边界分离。")],
                "components": [{
                "ref": "application", "identity": sample("企业应用入口"),
                "responsibilities": [sample("应用入口接收业务请求。")],
                "rationale": [sample("独立入口便于隔离客户端与内部服务。")],
                "interfaces": [sample("应用入口通过受控接口调用业务服务。")],
            }, {
                "ref": "service", "identity": sample("业务服务"),
                "responsibilities": [sample("业务服务处理应用入口转发的请求。")],
                "rationale": [sample("独立业务边界便于约束内部处理职责。")],
                "interfaces": [sample("业务服务向应用入口返回处理结果。")],
            }], "dependencies": [{"from": "application", "to": "service"}],
                "request_flows": [{"from": "application", "to": "service"}],
                "data_flows": [{"from": "service", "to": "application"}]},
            "deployment_and_integration": {
                "deployment": [sample(
                    "若客户确认目标环境符合本期部署条件，则依照确认后的边界安排部署。",
                    related_fields=("deployment_requirement",),
                )],
                "integration": [], "data_security": [], "environment": [],
            },
        }
        contract = (
            f"Pass 1 — Technical Core：proposals 最多 {MAX_CORE_PROPOSALS} 条，"
            f"组件最多 {MAX_ARCHITECTURE_COMPONENTS} 个；这是上限不是目标。"
            "仅生成 proposed_solution、architecture、deployment_and_integration。"
            "Core 顶层必须有 ir_version、proposed_solution、architecture、deployment_and_integration；"
            "仅可额外有 capability_groups。capability_groups 是 TOP-LEVEL 字段，不属于 architecture，"
            "也不属于任何 component 或 deployment_and_integration。"
            "architecture 必须有 components；只可额外有 overview、dependencies、request_flows、data_flows。"
            "deployment_and_integration 只能包含 deployment、integration、data_security、environment。"
            "capability_groups 的每项必须且只能有 ref、items；items 是 claim 对象列表。"
            "每层 MUST contain only the documented keys。"
            "Do not move fields between levels。Do not add sibling or nested keys。"
            f"局部上限：proposed_solution 最多 {CORE_PROPOSED_SOLUTION_LIMIT} 条；"
            f"architecture.overview 最多 {CORE_ARCHITECTURE_OVERVIEW_LIMIT} 条；"
            f"capability_groups 最多 {CORE_CAPABILITY_GROUP_LIMIT} 组，每组 items 最多 "
            f"{CORE_CAPABILITY_GROUP_ITEMS_LIMIT} 条。"
            "architecture.components 每项恰好一个 identity claim，"
            f"responsibilities 为 1～{CORE_COMPONENT_FIELD_LIMITS['responsibilities']} 条，"
            f"rationale 为 1～{CORE_COMPONENT_FIELD_LIMITS['rationale']} 条，"
            f"interfaces 为 1～{CORE_COMPONENT_FIELD_LIMITS['interfaces']} 条。"
            "architecture.components[].responsibilities：每条 responsibility 只表达一个可独立判断的组件职责。"
            "如果一个组件承担多个独立能力或处理链路，必须拆成多个 responsibility claim。"
            "以下仅示范职责拆分，不要求输出这些能力："
            "BAD responsibility：对文档内容执行知识检索，并处理扫描版 PDF 的 OCR 后内容。"
            "GOOD responsibility claim：负责对文档内容执行知识检索。"
            "GOOD responsibility claim：负责处理扫描版 PDF 的 OCR 后内容。"
            "responsibility 不禁止所有“和/与”句式；只有可以独立成立、独立失败或独立审核的职责才需要拆分。"
            "architecture.components 每项必须且只能包含 ref、identity、responsibilities、rationale、interfaces 五个键；"
            "不得添加 identity_note、description、summary、notes、metadata 或任何其他额外键。"
            "示例中的 architecture.components 即合法五键格式。"
            "ref 是小写结构引用，匹配 [a-z][a-z0-9_]{0,63}；ref 不是展示名称。"
            "dependencies 表示 source 依赖 target；request_flows 表示请求 from 进入 to；"
            "data_flows 表示数据 from 流向 to。三者不可混淆，边端点必须引用本次组件 ref。"
            "dependencies、request_flows、data_flows 中的每个 relation item 只能有 from、to 两个键，"
            "必须恰好是 {\"from\":\"component_a\",\"to\":\"component_b\"} 这样的 JSON 对象；"
            "不得在 relation item 中增加 citations、related_requirement_fields、text、rationale、type、"
            "container_kind、field 或任何其他键。citations、related_requirement_fields 只属于 claim，"
            "绝不属于 relation objects。"
            "两个以上组件至少一条 request_flows；存在真实数据读写时生成 data_flows。"
            "proposed_solution 是总体技术推荐的 atomic claims；architecture.overview 可选；"
            "capability_groups 可选，每项为 ref 与 items。"
            "proposed_solution 数组对应最终 proposed_solution.overview，每条 claim 必须代表一个独立可审核的总体技术推荐。"
            "如果一句 overview 同时包含多个独立技术选型、多个独立系统集成决策，"
            "或多个可以分别批准/拒绝的能力建设，必须拆成多个 overview claim。"
            "以下仅示范拆分方式，不要求输出这些技术选择："
            "BAD overview：建议通过标准接口对接 OA 门户并接入企业 SSO 统一身份。"
            "GOOD overview claim：建议通过标准接口对接现有 OA 门户。"
            "GOOD overview claim：建议接入企业 SSO 实现统一身份管理。"
            "允许同一推荐的目的、条件或紧密配套描述；不按动词数量判断，也不禁止所有“和/与”句式。"
            "允许 overview：建设统一智能服务平台，提升企业知识管理能力。"
            "BAD overview：采用 Kafka、Redis、Kubernetes 完成消息、缓存、高可用部署。"
            "proposed_solution.items（包括 capability_groups[].items）的每个 item 必须只表达一个可独立批准/拒绝的技术判断。"
            "如果一句话包含两个独立能力、技术选择或交付项，必须拆成两个独立 item。"
            "BAD：接口服务能力可支撑 JWT 身份认证与 CSV 批量导出。"
            "GOOD：两个独立 item：接口服务能力可支撑 JWT 身份认证。接口服务能力可支撑 CSV 批量导出。"
            "不禁止所有“和/与”句式；只有可以独立成立、独立失败、独立审批的技术判断才必须拆分。"
            "deployment_and_integration 中 deployment、integration、data_security、environment 的每条 item"
            "只表达一个可独立审核的部署、集成、数据或环境技术判断。"
            "如果一句话同时包含多个可以分别批准/拒绝的技术选型或能力决策，应拆成多条 claim。"
            "以下仅示范拆分方式，不要求输出这些技术选择："
            "BAD deployment_and_integration：建议知识数据服务采用 PostgreSQL，并使用 pgvector 支撑知识检索。"
            "GOOD deployment_and_integration claim：建议知识数据服务采用 PostgreSQL。"
            "GOOD deployment_and_integration claim：建议使用 pgvector 支撑向量检索。"
            "deployment_and_integration 不禁止所有“和/与”句式；"
            "仅拆分可以独立成立、独立失败或独立审核的技术判断。"
            "deployment_and_integration 只允许四个主题列表："
            + "；".join(
                f"{topic} 最多 {limit} 条"
                for topic, limit in CORE_DEPLOYMENT_TOPIC_LIMITS.items()
            ) + "。"
            "单条 proposal 不得合并多个独立技术决策；不生成实施、风险、验收或里程碑。"
        )
    elif pass_name == "implementation":
        example = {
            "ir_version": SEMANTIC_IR_VERSION,
            "phases": [
                {"ref": "discovery", "objective": [sample("确认本期实施边界。")],
                 "tasks": [sample("核对已确认的实施范围。")],
                 "deliverables": [sample("形成实施范围核对记录。")]},
                {"ref": "implement", "objective": [sample("落实已验证的技术方案。")],
                 "tasks": [sample("按已验证方案实施本期功能。")],
                 "deliverables": [sample("形成实施结果记录。")],
                 "timing": [sample("在准备阶段完成后开展实施。")]},
                {"ref": "validate", "objective": [sample("验证本期业务链路。")],
                 "tasks": [sample("验证约定业务场景的执行结果。")],
                 "deliverables": [sample("形成业务场景验证记录。")]}],
            "milestones": [{"ref": "ready", "outcome": [sample("本期业务场景完成验证。")],
                            "phase_refs": ["validate"]}],
            "dependencies": [{"from": "implement", "to": "discovery"},
                             {"from": "validate", "to": "implement"}],
        }
        contract = (
            f"Pass 2 — Implementation Planning：runtime proposal 总预算最多 {runtime_budget} 条，"
            f"implementation_plan 最多 {IMPLEMENTATION_SECTION_PROPOSAL_LIMITS['implementation_plan']} 条，"
            f"milestones 最多 {IMPLEMENTATION_SECTION_PROPOSAL_LIMITS['milestones']} 条；上限不是目标。"
            "只生成 phases 的 objective、tasks、deliverables、可选 timing，"
            "以及 milestones 的 outcome、可选 timing。"
            f"局部上限：phases 最多 {MAX_IMPLEMENTATION_PHASES} 个；"
            f"每个 phase 的 objective 恰好 {IMPLEMENTATION_PHASE_FIELD_LIMITS['objective'][1]} 条，"
            f"tasks 为 {IMPLEMENTATION_PHASE_FIELD_LIMITS['tasks'][0]}～{IMPLEMENTATION_PHASE_FIELD_LIMITS['tasks'][1]} 条，"
            f"deliverables 恰好 {IMPLEMENTATION_PHASE_FIELD_LIMITS['deliverables'][1]} 条，"
            f"timing 为 0～{IMPLEMENTATION_PHASE_FIELD_LIMITS['timing'][1]} 条。"
            "phase tasks + phase timing + milestone timing "
            "必须控制在剩余 Implementation proposal budget 内。"
            "dynamic maximum = MAX_IMPLEMENTATION_PROPOSALS - 2 * phase_count - milestone_count"
            f"（MAX_IMPLEMENTATION_PROPOSALS={MAX_IMPLEMENTATION_PROPOSALS}）；"
            "phase_count 和 milestone_count 是本次实际生成的阶段数和里程碑数。"
            "例如：4 phases + 2 milestones → 最多 8；"
            "4 phases + 1 milestone → 最多 9；"
            "3 phases + 2 milestones → 最多 10。"
            "这是动态剩余额度，不是填满目标；仍须遵守 runtime 总预算和各 section 上限。"
            f"milestones 最多 {MAX_IMPLEMENTATION_MILESTONES} 个；"
            f"每个 milestone 的 outcome 恰好 {IMPLEMENTATION_MILESTONE_FIELD_LIMITS['outcome'][1]} 条，"
            f"timing 为 0～{IMPLEMENTATION_MILESTONE_FIELD_LIMITS['timing'][1]} 条。"
            "dependencies 的 from 阶段依赖 to 阶段；milestone.phase_refs 只引用本次 phases 的 ref。"
            "每个 dependencies 对象恰好只有 from、to 两个必填键，值均为本次 phases 中已定义的 ref；"
            "不要输出 reason、source、target、type 或 relation_type 等额外键。"
            "先按业务需要选择阶段和里程碑数量，再使用 <implementation_budget_options> 中对应行的已计算额度；"
            "shared_work_maximum 是 tasks 与全部 timing 的合计上限，phase_work_maximum 是阶段内 tasks 与 timing 的合计上限，"
            "milestone_timing_maximum 是里程碑 timing 的上限；三项必须同时满足，并遵守每个字段的局部限制。"
            "优先紧凑且业务完整的阶段划分，不默认填满4个阶段和2个里程碑。"
            "timing 可省略；仅在相关需求或证据支持时填写，不为补齐示例添加日期或期限。"
            "示例中的阶段名称和顺序仅展示格式，不能替代对实际项目的实施设计。"
            "ref 是小写结构引用，匹配 [a-z][a-z0-9_]{0,63}。"
            "<validated_technical_core> 已验证，不得重写技术选择或组件；"
            "不生成架构、部署、风险、验收或范围外内容。"
        )
    elif pass_name == "assurance":
        example = {
            "ir_version": SEMANTIC_IR_VERSION,
            "risks": [{"ref": "integration_change", "condition": [sample("若接口契约后续发生变化。")],
                       "impact": [sample("适配器需要返工。")],
                       "mitigation": [sample("实施前验证接口契约。")],
                       "trigger": [sample("若联调时发现接口字段不一致，则触发接口兼容性风险处置。")]}],
            "acceptance": [{"ref": "integration_check", "criterion": [sample("通过适配器调用约定接口，响应中的业务标识应与请求对应。")]}],
            "out_of_scope": [sample("不替换客户现有身份系统。")],
            "phase_acceptance": [{"from": "discovery", "to": "integration_check"}],
        }
        contract = (
            f"Pass 3 — Assurance & Boundaries：runtime proposal 总预算最多 {runtime_budget} 条，"
            f"risks 最多 {MAX_ASSURANCE_RISKS} 个，每个 risk 的 condition、impact、mitigation、trigger 各恰好 1 条；"
            f"acceptance 最多 {MAX_ASSURANCE_ACCEPTANCE} 个，每个 criterion 恰好 1 条；"
            f"out_of_scope 最多 {MAX_ASSURANCE_OUT_OF_SCOPE} 条，"
            f"phase_acceptance 最多 {MAX_ASSURANCE_PHASE_ACCEPTANCE} 条；"
            "phase_acceptance 不计入 proposal 总预算，只表达关系；所有上限都不是生成目标。"
            "只生成 risks 的 condition、impact、mitigation、trigger；"
            "acceptance 的 criterion；out_of_scope。"
            "acceptance 中每个对象恰好只有 ref、criterion 两个必填键。"
            "criterion 是恰好包含 1 个 claim 对象的数组；每个 claim 恰好只有 "
            "text、citations、related_requirement_fields 三个必填键。"
            "验收正文、引用和原始需求关联必须放在 criterion[0] 内，不能提到 acceptance 对象外层；"
            "acceptance 外层不得添加 text、citations、related_requirement_fields、phase_ref 或 phase_refs。"
            "阶段关联只写在顶层 phase_acceptance 数组，每个关系对象恰好只有 from、to 两个必填键。"
            "phase_acceptance 关系不能承载正文、引用或理由，不添加 criterion、citations 或 reason。"
            "acceptance[].criterion 对应最终 acceptance_criteria，按独立验收检查而非阶段成果包组织。"
            "检索相关性与 OCR 可检索性、授权访问与越权阻断、业务结果与引用来源定位，"
            "分别具有独立 PASS/FAIL 结果，应分别验收。"
            "不得使用“端到端集成测试通过”或“阶段验收完成”代替具体检查。"
            "BAD criterion：以交付案例为查询输入执行企业知识查询，返回结果与所查询交付案例相关，且扫描版 PDF 案例经 OCR 后可被检索到。"
            "GOOD criterion：以交付案例为查询输入执行企业知识查询，返回结果应与所查询交付案例相关。"
            "GOOD criterion：扫描版 PDF 案例经 OCR 处理后应能够被企业知识查询检索到。"
            "BAD criterion：授权用户能够获取受限资料，且未授权用户无法获取受限资料。"
            "GOOD criterion：使用具有相应权限的身份查询，能够获取该身份获准访问的受限资料。"
            "GOOD criterion：使用不具有相应权限的身份查询，无法获取受限资料。"
            "risks.condition 描述风险发生条件：如果条件本身有明确客户事实或 grounding fact 支持，可以直接陈述；"
            "如果只是潜在风险场景或尚未证实的问题，必须使用明确条件式表达，"
            "例如若……、如果……、当……发生时、在……未满足的情况下。"
            "禁止把 hypothetical risk 写成当前已存在的客户事实。"
            "以下 BAD 示例在没有事实支持时不可直接断言："
            "BAD：文档级访问控制未覆盖全部知识分类。"
            "GOOD：若角色权限划分未覆盖全部知识分类……"
            "BAD：接口契约发生变化。"
            "GOOD：若接口契约后续发生变化……"
            "BAD：当前权限模型存在遗漏。"
            "GOOD：如果权限模型未覆盖新增知识分类……"
            "条件式表达只说明风险触发条件，不能借此引入没有依据的精确数值、能力或承诺。"
            "risks.trigger 表示未来可观测的风险触发/检测信号，不默认表示客户当前已经出现该问题。"
            "尚未证实的风险信号必须使用条件式或事件式表达，例如："
            "若权限核验发现某类知识文档未映射到任何访问控制维度，则将其视为风险触发信号。"
            "当联调发现接口字段不一致时，触发接口兼容性风险处置。"
            "只有当客户需求或 grounding fact 明确证明问题已经发生时，才允许直接写成既有事实。"
            "条件式表达不能用于包装无依据的数字、能力或承诺。"
            "BAD/AMBIGUOUS trigger：联调时发现接口字段不一致。"
            "GOOD trigger：若联调时发现接口字段不一致，则触发接口兼容性风险处置。"
            "phase_acceptance.from 必须引用 <validated_implementation_plan> 中真实 phase ref，"
            "to 必须引用本次 acceptance.ref。"
            "已确认的 Core/Implementation 不得重写；assumptions 和 open_questions 由程序保留，不生成。"
            "不生成架构、部署、实施或里程碑。"
        )
    else:
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    semantics = _SYSTEM_PROMPT.partition("placement 只用于")[0]
    clarification_guidance = (
        "<clarification_action_style> 仅指导其 targets 中真实核验动作的表达，不是输出字段或事实依据。"
        "若阶段目标、任务或风险措施的真实用途是核验未确认前提，应明确写待执行的核验动作，"
        "例如核验部署条件、评估服务器容量是否满足本期部署需求；不要把待核验的结果写成环境可用或容量足够。"
        "纯核验动作不主张结果已确认；随后依赖核验结果的部署、性能或交付安排仍须体现真实确认前提。"
        "核验完成不等于核验通过或条件满足；条件性建设应明确经核验确认部署条件满足后开展建设。"
        "deliverables 使用计划形成的核验记录；milestones.outcome 使用完成核验并记录结果，不保证条件满足。"
        "risk condition/impact 使用若容量不满足则部署可能受影响的假设，不写成已发生事实。"
        "示例不批准任何能力、状态、引用或建议，实际建议仍须由允许证据支持并通过全部审核。"
        "不得把事实断言或承诺机械改写成核验动作来规避校验，不得改变原始需求关联。"
        "涉及部署条件、服务器容量或承载条件的规划条目，related_requirement_fields 必须包含 deployment_requirement，"
        "不能只用 existing_environment 或 integration_requirement 代替；现有环境配置另保留真实的 existing_environment 关联。"
        "条件性技术接入可以表达为经核验确认部署条件满足后，完成检索入口的接入；"
        "具体技术对象和动作必须由已准入证据支持，按已验证方案等措辞不是批准事实或省略需求关联的依据。"
        "不得将 clarification_action_style 或 targets 等指导键写进输出 JSON。"
        if pass_name in {"implementation", "assurance"} else ""
    )
    return (
        semantics + "\n" + contract + "\n" + clarification_guidance
        + "设计前读取 requirement_design_scope：它只重述当前需求维度状态，不是新的事实或能力审批。"
        "confirmed_fields 中的原始 value/evidence 可作为已确认客户背景，仍必须忠实于其实际内容。"
        "conditional_fields 中 unknown/unclear/conflict 维度不是已确认需求；"
        "如果建议直接依赖其中任一维度，必须在该条 claim 自身说明真实的未确认前提及确认后的安排，"
        "例如若客户确认目标环境满足部署条件，再按确认结果安排部署；不要只在其它条目写一次免责声明。"
        "混合已知背景和未确认容量的维度仍保持原状态，不可自行提取其中一部分并升格为 confirmed。"
        "例如 existing_environment 已确认且 deployment_requirement 尚不明确时，"
        "可以围绕已确认的现有环境提出建议，但不能由此断言其服务器容量足够或部署位置已经确定。"
        "related_requirement_fields 必须保持真实直接关联，不能为了避开边界改关联、清空关联或挂到 business_goal。"
        "不得机械给原句加若、如果、待确认来包装无依据事实、容量、性能、期限或能力；"
        "条件性建议仍需企业证据支持并经过正式语义审核。"
        "只返回紧凑 JSON，不含 Markdown 或 JSON 之外的文字。"
        f"顶层必须使用示例中的 ir_version={SEMANTIC_IR_VERSION} 和本 pass 专用字段，不得输出旧版 proposals 列表。"
        "每条 claim 恰好只有 text、citations、related_requirement_fields。"
        "citations 至少一项且只使用 <allowed_citation_ids> 中逐项列出的准确编号；"
        "编号可能不连续，不得从 S1...Sn 推断、补齐或重编号，不可编造或自动补引用。"
        "其他上下文或已准入事实中出现的 citation 编号不自动获得 proposal 引用许可。"
        "示例使用本次合法编号只为展示格式，不证明示例技术结论；"
        "实际 claim 仍必须由其所引用的、允许使用的企业能力证据支持。"
        "related_requirement_fields 只允许当前分析中确实存在、且直接相关的维度；"
        f"合法 RequirementDimension：{', '.join(item.value for item in RequirementDimension)}。"
        "无直接相关维度时使用 []。所有列表的最大值不是填充目标；优先简洁且不重复的原子判断。"
        "示例仅展示格式，不能照抄示例的技术结论："
        + json.dumps(example, ensure_ascii=False, separators=(",", ":"))
    )


def build_solution_v2_core_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
) -> list[LLMMessage]:
    """Build the bounded Technical Core generation request."""

    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "core", MAX_CORE_PROPOSALS,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": _solution_v2_input_context(
                analysis, readiness, sources, admission
            ),
        },
    ]


def _clarification_action_style_context(pass_name: str) -> str:
    """Input-only inquiry style; neither output intent tags nor admission."""
    from .solution_unresolved_policy import unresolved_v2_generation_guidance

    guidance = unresolved_v2_generation_guidance(pass_name)
    if guidance is None:
        return ""
    style = asdict(guidance)
    payload = escape(json.dumps(style, ensure_ascii=False, separators=(",", ":")), quote=False)
    return f"\n<clarification_action_style>{payload}</clarification_action_style>"


def build_solution_v2_implementation_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
    core: AtomicSolutionProposalSetV2,
) -> list[LLMMessage]:
    """Build Implementation Planning from one already validated core."""

    _validate_pass_contract(
        core,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    compact_core = escape(
        json.dumps(asdict(core), ensure_ascii=False, separators=(",", ":")),
        quote=False,
    )
    runtime_budget = implementation_runtime_proposal_budget(len(core.proposals))
    budget_options = json.dumps(_implementation_budget_options(runtime_budget), separators=(",", ":"))
    contract = _IMPLEMENTATION_PASS_CONTRACT.replace(
        "__IMPLEMENTATION_RUNTIME_BUDGET__", str(runtime_budget)
    )
    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "implementation", runtime_budget,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": (
                _solution_v2_input_context(analysis, readiness, sources, admission)
                + _clarification_action_style_context("implementation")
                + f"\n<validated_technical_core>\n{compact_core}\n"
                "</validated_technical_core>"
                + f"\n<implementation_budget_options>{budget_options}</implementation_budget_options>"
            ),
        },
    ]


def build_solution_v2_assurance_messages(
    analysis: OpportunityRequirementAnalysis,
    readiness: SolutionReadiness,
    sources: tuple[SolutionSource, ...],
    admission: GroundingAdmission,
    core: AtomicSolutionProposalSetV2,
    implementation: AtomicSolutionProposalSetV2,
) -> list[LLMMessage]:
    """Build Assurance & Boundaries from validated earlier passes."""

    _validate_pass_contract(
        core,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    _validate_pass_contract(
        implementation,
        max_proposals=MAX_IMPLEMENTATION_PROPOSALS,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    _validate_section_budgets(
        implementation,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=implementation_runtime_proposal_budget(len(core.proposals)),
    )
    compact_core = escape(
        json.dumps(asdict(core), ensure_ascii=False, separators=(",", ":")),
        quote=False,
    )
    compact_implementation = escape(
        json.dumps(
            asdict(implementation), ensure_ascii=False, separators=(",", ":")
        ),
        quote=False,
    )
    runtime_budget = assurance_runtime_proposal_budget(
        len(core.proposals), len(implementation.proposals)
    )
    contract = _ASSURANCE_PASS_CONTRACT.replace(
        "__ASSURANCE_RUNTIME_BUDGET__", str(runtime_budget)
    )
    return [
        {
            "role": "system",
            "content": _semantic_pass_prompt(
                "assurance", runtime_budget,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
        },
        {
            "role": "user",
            "content": (
                _solution_v2_input_context(analysis, readiness, sources, admission)
                + _clarification_action_style_context("assurance")
                + f"\n<validated_technical_core>\n{compact_core}\n"
                "</validated_technical_core>"
                + f"\n<validated_implementation_plan>\n{compact_implementation}\n"
                "</validated_implementation_plan>"
            ),
        },
    ]


def _implementation_budget_options(runtime_budget: int) -> list[dict[str, int]]:
    """Compute feasible shape allowances without changing the formal contract.

    The model chooses the business plan; these program-owned numbers only
    remove arithmetic over total, section and per-container limits.
    """
    options = []
    phase_field_maximum = sum(IMPLEMENTATION_PHASE_FIELD_LIMITS[field][1]
                              for field in ("tasks", "timing"))
    for phases in range(1, MAX_IMPLEMENTATION_PHASES + 1):
        phase_base = phases * (IMPLEMENTATION_PHASE_FIELD_LIMITS["objective"][0]
                               + IMPLEMENTATION_PHASE_FIELD_LIMITS["deliverables"][0])
        for milestones in range(MAX_IMPLEMENTATION_MILESTONES + 1):
            milestone_base = milestones * IMPLEMENTATION_MILESTONE_FIELD_LIMITS["outcome"][0]
            remaining = runtime_budget - phase_base - milestone_base
            if remaining < phases * IMPLEMENTATION_PHASE_FIELD_LIMITS["tasks"][0]:
                continue
            phase_work = min(phases * phase_field_maximum,
                             IMPLEMENTATION_SECTION_PROPOSAL_LIMITS["implementation_plan"] - phase_base,
                             remaining)
            milestone_timing = min(milestones * IMPLEMENTATION_MILESTONE_FIELD_LIMITS["timing"][1],
                                   IMPLEMENTATION_SECTION_PROPOSAL_LIMITS["milestones"] - milestone_base)
            options.append({
                "phase_count": phases, "milestone_count": milestones,
                "shared_work_maximum": min(remaining, phase_work + milestone_timing),
                "phase_work_maximum": phase_work,
                "milestone_timing_maximum": milestone_timing,
            })
    return options


def implementation_runtime_proposal_budget(core_proposal_count: int) -> int:
    """Return the bounded Implementation allowance left by Technical Core."""

    if (
        not isinstance(core_proposal_count, int)
        or isinstance(core_proposal_count, bool)
        or not 0 <= core_proposal_count <= MAX_CORE_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    return min(
        MAX_IMPLEMENTATION_PROPOSALS,
        MAX_SOLUTION_V2_PROPOSALS - core_proposal_count,
    )


def assurance_runtime_proposal_budget(
    core_proposal_count: int,
    implementation_proposal_count: int,
) -> int:
    """Return the bounded Assurance allowance left by both earlier passes."""

    if (
        not isinstance(core_proposal_count, int)
        or isinstance(core_proposal_count, bool)
        or not 0 <= core_proposal_count <= MAX_CORE_PROPOSALS
        or not isinstance(implementation_proposal_count, int)
        or isinstance(implementation_proposal_count, bool)
        or not 0 <= implementation_proposal_count <= MAX_IMPLEMENTATION_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    return min(
        MAX_ASSURANCE_PROPOSALS,
        MAX_SOLUTION_V2_PROPOSALS
        - core_proposal_count
        - implementation_proposal_count,
    )


_SECTION_BUDGET_CATEGORIES = {
    "implementation_plan": (
        SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_BUDGET_EXCEEDED
    ),
    "risks": SolutionV2OutputDiagnosticCategory.RISK_BUDGET_EXCEEDED,
    "acceptance_criteria": (
        SolutionV2OutputDiagnosticCategory.ACCEPTANCE_BUDGET_EXCEEDED
    ),
    "milestones": SolutionV2OutputDiagnosticCategory.MILESTONE_BUDGET_EXCEEDED,
    "assumptions": SolutionV2OutputDiagnosticCategory.ASSUMPTION_BUDGET_EXCEEDED,
    "open_questions": (
        SolutionV2OutputDiagnosticCategory.OPEN_QUESTION_BUDGET_EXCEEDED
    ),
    "out_of_scope": (
        SolutionV2OutputDiagnosticCategory.OUT_OF_SCOPE_BUDGET_EXCEEDED
    ),
}


def _section_budget_failure_category(
    section_counts: dict[str, int],
    *,
    limits: dict[str, int],
    max_proposals: int,
    maximum_ceiling: int,
    total_category: SolutionV2OutputDiagnosticCategory,
) -> SolutionV2OutputDiagnosticCategory | None:
    """Classify bounded pass counts without exposing proposal content."""

    if (
        not isinstance(section_counts, dict)
        or set(section_counts) - set(limits)
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in section_counts.values()
        )
        or not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= maximum_ceiling
    ):
        return SolutionV2OutputDiagnosticCategory.WRONG_VALUE_TYPE
    for section, maximum in limits.items():
        if section_counts.get(section, 0) > maximum:
            return _SECTION_BUDGET_CATEGORIES[section]
    if sum(section_counts.values()) > max_proposals:
        return total_category
    return None


def implementation_budget_failure_category(
    section_counts: dict[str, int],
    *,
    max_proposals: int,
) -> SolutionV2OutputDiagnosticCategory | None:
    return _section_budget_failure_category(
        section_counts,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
        maximum_ceiling=MAX_IMPLEMENTATION_PROPOSALS,
        total_category=(
            SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED
        ),
    )


def assurance_budget_failure_category(
    section_counts: dict[str, int],
    *,
    max_proposals: int,
) -> SolutionV2OutputDiagnosticCategory | None:
    return _section_budget_failure_category(
        section_counts,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
        maximum_ceiling=MAX_ASSURANCE_PROPOSALS,
        total_category=(
            SolutionV2OutputDiagnosticCategory.ASSURANCE_TOTAL_BUDGET_EXCEEDED
        ),
    )


def _section_counts(
    value: AtomicSolutionProposalSetV2,
    *,
    limits: dict[str, int],
) -> dict[str, int]:
    counts = {section: 0 for section in limits}
    for proposal in value.proposals:
        counts[proposal.placement.section.value] += 1
    return counts


def _validate_section_budgets(
    value: AtomicSolutionProposalSetV2,
    *,
    limits: dict[str, int],
    max_proposals: int,
    section_paths: dict[str, str] | None = None,
) -> None:
    maximum_ceiling = (
        MAX_IMPLEMENTATION_PROPOSALS
        if limits is IMPLEMENTATION_SECTION_PROPOSAL_LIMITS
        else MAX_ASSURANCE_PROPOSALS
    )
    total_category = (
        SolutionV2OutputDiagnosticCategory.IMPLEMENTATION_TOTAL_BUDGET_EXCEEDED
        if limits is IMPLEMENTATION_SECTION_PROPOSAL_LIMITS
        else SolutionV2OutputDiagnosticCategory.ASSURANCE_TOTAL_BUDGET_EXCEEDED
    )
    counts = _section_counts(value, limits=limits)
    category = _section_budget_failure_category(
        counts,
        limits=limits,
        max_proposals=max_proposals,
        maximum_ceiling=maximum_ceiling,
        total_category=total_category,
    )
    if category is not None:
        for section, maximum in limits.items():
            if counts[section] > maximum:
                indices = [index for index, proposal in enumerate(value.proposals)
                           if proposal.placement.section.value == section]
                index = indices[maximum]
                path = (section_paths or {}).get(section, f"$.proposals[{index}]")
                reject_contract(category.value, path, f"at most {maximum} {section} claims", f"{counts[section]} claims")
        reject_contract(category.value, "$.proposals", f"at most {max_proposals} proposals", str(sum(counts.values())))


def parse_atomic_solution_v2_proposals(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    _max_proposals: int = _MAX_LEGACY_SINGLE_PASS_PROPOSALS,
    _external_containers: frozenset[tuple[SolutionV2ContainerKind, str]] = frozenset(),
    _proposal_paths: tuple[str, ...] = (),
    _relation_paths: tuple[str, ...] = (),
) -> AtomicSolutionProposalSetV2:
    """Strictly parse the closed V2 proposal-placement IR without repairs."""

    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, RecursionError):
        reject_contract("malformed_json", "$", "complete unique-key JSON", "malformed JSON")
    closed_object(payload, {"proposals"}, {"structure_relations"})
    items = payload["proposals"]
    if (
        not isinstance(_max_proposals, int)
        or isinstance(_max_proposals, bool)
        or _max_proposals < 0
    ):
        _invalid()
    if not isinstance(items, list):
        reject_contract("wrong_type", "$.proposals", "array", type(items).__name__)
    if len(items) > _max_proposals:
        reject_contract("proposal_count_exceeded", "$.proposals", f"at most {_max_proposals} proposals", str(len(items)))
    validate_citation_allowlist(allowed_source_labels)

    proposals: list[AtomicSolutionProposalV2] = []
    for index, item in enumerate(items):
        path = _proposal_paths[index] if index < len(_proposal_paths) else f"$.proposals[{index}]"
        closed_object(item, {"placement", "text", "citations"}, {"related_requirement_fields"}, path=path)
        placement_data = item["placement"]
        closed_object(placement_data, {"section", "container_kind", "container_key", "field"}, path=path + ".placement")
        try:
            section = SolutionV2Section(placement_data["section"])
            container_kind = SolutionV2ContainerKind(placement_data["container_kind"])
            field = SolutionV2PlacementField(placement_data["field"])
        except (TypeError, ValueError):
            reject_contract("invalid_enum", path + ".placement", "allowed placement enums", "unknown enum or wrong type")
        if field not in _ALLOWED_PLACEMENTS.get((section, container_kind), set()):
            _invalid()
        container_key = placement_data["container_key"]
        if container_kind is SolutionV2ContainerKind.ROOT:
            if container_key is not None:
                _invalid()
        elif not isinstance(container_key, str) or _CONTAINER_KEY.fullmatch(container_key) is None:
            _invalid()
        managed_linkage = (
            (section.value, container_kind.value, field.value)
            in MANAGED_LINKAGE_PLACEMENTS
        )
        claim_text, citations, related_requirement_fields = validate_claim_fields(
            {key: value for key, value in item.items() if key != "placement"},
            allowed_source_labels=allowed_source_labels, path=path,
            require_linkage=managed_linkage,
        )
        if managed_linkage and not related_requirement_fields:
            # Same contract as the Semantic IR parser: an empty linkage would
            # leave the unresolved policy and its guard with nothing to inspect.
            reject_contract(
                "invalid_requirement_link", path + ".related_requirement_fields",
                "at least one RequirementDimension for this placement", "empty",
            )
        proposals.append(AtomicSolutionProposalV2(
            placement=SolutionV2Placement(section, container_kind, container_key, field),
            text=claim_text,
            citations=citations,
            related_requirement_fields=related_requirement_fields,
        ))
    relations_data = payload.get("structure_relations", [])
    if not isinstance(relations_data, list):
        reject_contract("wrong_type", "$.structure_relations", "array", type(relations_data).__name__)
    relations: list[SolutionV2StructureRelation] = []
    for index, item in enumerate(relations_data):
        path = _relation_paths[index] if index < len(_relation_paths) else f"$.structure_relations[{index}]"
        closed_object(item, {
            "relation_type",
            "source_container_kind",
            "source_container_key",
            "target_container_kind",
            "target_container_key",
        }, path=path)
        try:
            relation_type = SolutionV2StructureRelationType(item["relation_type"])
            source_kind = SolutionV2ContainerKind(item["source_container_kind"])
            target_kind = SolutionV2ContainerKind(item["target_container_kind"])
        except (TypeError, ValueError):
            reject_contract("invalid_relation", path, "allowed relation type and endpoint kinds", "unknown enum or wrong type")
        source_key = item["source_container_key"]
        target_key = item["target_container_key"]
        if (
            not isinstance(source_key, str)
            or _CONTAINER_KEY.fullmatch(source_key) is None
            or not isinstance(target_key, str)
            or _CONTAINER_KEY.fullmatch(target_key) is None
        ):
            _invalid()
        expected_kinds = _RELATION_KINDS[relation_type]
        if (source_kind, target_kind) != expected_kinds:
            _invalid()
        relations.append(SolutionV2StructureRelation(
            relation_type=relation_type,
            source_container_kind=source_kind,
            source_container_key=source_key,
            target_container_kind=target_kind,
            target_container_key=target_key,
        ))
    result = AtomicSolutionProposalSetV2(tuple(proposals), tuple(relations))
    validate_solution_v2_structure_relations(
        result,
        max_proposals=_max_proposals,
        external_containers=_external_containers,
        relation_paths=_relation_paths,
    )
    return result


def parse_solution_v2_core_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
) -> AtomicSolutionProposalSetV2:
    """Parse one bounded Technical Core response without moving placements."""

    result = _parse_generation_output(
        content, pass_name="core", allowed_source_labels=allowed_source_labels,
        max_proposals=MAX_CORE_PROPOSALS,
    )
    _validate_pass_contract(
        result,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    return result


def parse_solution_v2_implementation_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    max_proposals: int = MAX_IMPLEMENTATION_PROPOSALS,
) -> AtomicSolutionProposalSetV2:
    """Parse one bounded Implementation Planning response without repairs."""

    if (
        not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= MAX_IMPLEMENTATION_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    result = _parse_generation_output(
        content, pass_name="implementation",
        allowed_source_labels=allowed_source_labels, max_proposals=max_proposals,
    )
    _validate_pass_contract(
        result,
        max_proposals=max_proposals,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    _validate_section_budgets(
        result,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
    )
    return result


def parse_solution_v2_assurance_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
    implementation: AtomicSolutionProposalSetV2,
    max_proposals: int = MAX_ASSURANCE_PROPOSALS,
) -> AtomicSolutionProposalSetV2:
    """Parse Assurance while validating phase references against Pass 2."""

    if (
        not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or not 0 <= max_proposals <= MAX_ASSURANCE_PROPOSALS
    ):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    _validate_pass_contract(
        implementation,
        max_proposals=MAX_IMPLEMENTATION_PROPOSALS,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    phase_containers = frozenset(
        (
            SolutionV2ContainerKind.IMPLEMENTATION_PHASE,
            proposal.placement.container_key,
        )
        for proposal in implementation.proposals
        if proposal.placement.container_kind
        is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
    )
    result = _parse_generation_output(
        content, pass_name="assurance", allowed_source_labels=allowed_source_labels,
        max_proposals=max_proposals, external_containers=phase_containers,
    )
    _validate_pass_contract(
        result,
        max_proposals=max_proposals,
        allowed_sections=_ASSURANCE_SECTIONS,
        allowed_relations=_ASSURANCE_RELATIONS,
    )
    _validate_section_budgets(
        result,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=max_proposals,
    )
    return result


def _parse_generation_output(
    content: str, *, pass_name: str, allowed_source_labels: tuple[str, ...],
    max_proposals: int,
    external_containers: frozenset[tuple[SolutionV2ContainerKind, str]] = frozenset(),
) -> AtomicSolutionProposalSetV2:
    """Explicitly distinguish new Semantic IR from the legacy demo envelope."""

    candidate = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", candidate, flags=re.DOTALL)
    if fence is not None:
        candidate = fence.group(1)
    try:
        payload = json.loads(candidate, object_pairs_hook=_unique_object,
                             parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        reject_contract("malformed_json", "$", "complete unique-key JSON", "malformed JSON")
    if isinstance(payload, dict) and ("ir_version" in payload or ("proposals" not in payload and SEMANTIC_ROOT_KEYS & payload.keys())):
        from apps.sales.services.solution_semantic_ir_v2 import (
            convert_semantic_solution_v2_output,
        )

        result = convert_semantic_solution_v2_output(
            candidate, pass_name=pass_name,
            allowed_source_labels=allowed_source_labels, max_proposals=max_proposals,
            external_phases=tuple(
                key for kind, key in external_containers
                if kind is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
            ),
        )
        if pass_name in {"implementation", "assurance"}:
            _validate_section_budgets(
                result, max_proposals=max_proposals,
                limits=(IMPLEMENTATION_SECTION_PROPOSAL_LIMITS if pass_name == "implementation"
                        else ASSURANCE_SECTION_PROPOSAL_LIMITS),
                section_paths={"implementation_plan": "$.phases", "milestones": "$.milestones",
                               "risks": "$.risks", "acceptance_criteria": "$.acceptance",
                               "out_of_scope": "$.out_of_scope"},
            )
        return result
    return parse_atomic_solution_v2_proposals(
        content, allowed_source_labels=allowed_source_labels,
        _max_proposals=max_proposals, _external_containers=external_containers,
    )


def _validate_pass_contract(
    value: AtomicSolutionProposalSetV2,
    *,
    max_proposals: int,
    allowed_sections: frozenset[SolutionV2Section],
    allowed_relations: frozenset[SolutionV2StructureRelationType],
) -> None:
    if not isinstance(value, AtomicSolutionProposalSetV2):
        reject_contract("wrong_type", "$", "AtomicSolutionProposalSetV2", type(value).__name__)
    if len(value.proposals) > max_proposals:
        reject_contract("proposal_count_exceeded", "$.proposals", f"at most {max_proposals} proposals", str(len(value.proposals)))
    for index, proposal in enumerate(value.proposals):
        if proposal.placement.section not in allowed_sections:
            reject_contract("invalid_placement", f"$.proposals[{index}].placement.section",
                            "current pass allowed section", proposal.placement.section.value)
    for index, relation in enumerate(value.structure_relations):
        if relation.relation_type not in allowed_relations:
            reject_contract("invalid_relation", f"$.structure_relations[{index}].relation_type",
                            "current pass allowed relation", relation.relation_type.value)


def _proposal_sort_key(proposal: AtomicSolutionProposalV2) -> tuple:
    section_priority = {value: index for index, value in enumerate(SolutionV2Section)}
    kind_priority = {
        value: index for index, value in enumerate(SolutionV2ContainerKind)
    }
    field_priority = {
        value: index for index, value in enumerate(SolutionV2PlacementField)
    }
    return (
        section_priority[proposal.placement.section],
        kind_priority[proposal.placement.container_kind],
        proposal.placement.container_key or "",
        field_priority[proposal.placement.field],
        tuple(field.value for field in proposal.related_requirement_fields),
        proposal.text,
        proposal.citations,
    )


def _relation_sort_key(relation: SolutionV2StructureRelation) -> tuple:
    relation_priority = {
        value: index for index, value in enumerate(SolutionV2StructureRelationType)
    }
    kind_priority = {
        value: index for index, value in enumerate(SolutionV2ContainerKind)
    }
    return (
        relation_priority[relation.relation_type],
        kind_priority[relation.source_container_kind],
        relation.source_container_key,
        kind_priority[relation.target_container_kind],
        relation.target_container_key,
    )


def merge_solution_v2_proposal_passes(
    core: AtomicSolutionProposalSetV2,
    implementation: AtomicSolutionProposalSetV2,
    assurance: AtomicSolutionProposalSetV2,
) -> AtomicSolutionProposalSetV2:
    """Combine three validated passes deterministically without new semantics."""

    _validate_pass_contract(
        core,
        max_proposals=MAX_CORE_PROPOSALS,
        allowed_sections=_CORE_SECTIONS,
        allowed_relations=_CORE_RELATIONS,
    )
    _validate_pass_contract(
        implementation,
        max_proposals=MAX_IMPLEMENTATION_PROPOSALS,
        allowed_sections=_IMPLEMENTATION_SECTIONS,
        allowed_relations=_IMPLEMENTATION_RELATIONS,
    )
    implementation_budget = implementation_runtime_proposal_budget(
        len(core.proposals)
    )
    _validate_section_budgets(
        implementation,
        limits=IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
        max_proposals=implementation_budget,
    )
    _validate_pass_contract(
        assurance,
        max_proposals=MAX_ASSURANCE_PROPOSALS,
        allowed_sections=_ASSURANCE_SECTIONS,
        allowed_relations=_ASSURANCE_RELATIONS,
    )
    assurance_budget = assurance_runtime_proposal_budget(
        len(core.proposals), len(implementation.proposals)
    )
    _validate_section_budgets(
        assurance,
        limits=ASSURANCE_SECTION_PROPOSAL_LIMITS,
        max_proposals=assurance_budget,
    )
    merged = AtomicSolutionProposalSetV2(
        proposals=tuple(sorted(
            core.proposals + implementation.proposals + assurance.proposals,
            key=_proposal_sort_key,
        )),
        structure_relations=tuple(sorted(
            core.structure_relations
            + implementation.structure_relations
            + assurance.structure_relations,
            key=_relation_sort_key,
        )),
    )
    if len(merged.proposals) > MAX_SOLUTION_V2_PROPOSALS:
        _invalid()
    validate_solution_v2_structure_relations(
        merged, max_proposals=MAX_SOLUTION_V2_PROPOSALS
    )
    return merged


def diagnose_solution_v2_output(
    content: str,
    *,
    allowed_source_labels: tuple[str, ...],
) -> SolutionV2OutputDiagnosticCategory | None:
    """Compatibility adapter over the executing parser, never a second validator."""
    try:
        parse_atomic_solution_v2_proposals(content, allowed_source_labels=allowed_source_labels)
    except SolutionDraftError as error:
        failure = getattr(error, "contract_failure", None)
        category = failure.category if failure else "unclassified_contract_failure"
        category = {
            "wrong_type": "wrong_value_type",
            "invalid_requirement_link": "malformed_requirement_linkage",
            "invalid_local_ref": "dangling_relation",
        }.get(category, category)
        return SolutionV2OutputDiagnosticCategory._value2member_map_.get(
            category, SolutionV2OutputDiagnosticCategory.UNCLASSIFIED_CONTRACT_FAILURE,
        )
    return None


def validate_solution_v2_structure_relations(
    value: AtomicSolutionProposalSetV2,
    *,
    max_proposals: int = MAX_SOLUTION_V2_PROPOSALS,
    external_containers: frozenset[
        tuple[SolutionV2ContainerKind, str]
    ] = frozenset(),
    relation_paths: tuple[str, ...] = (),
) -> None:
    """Validate the closed transient relation graph without inferring edges."""

    if not isinstance(value, AtomicSolutionProposalSetV2):
        _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    if (
        not isinstance(value.proposals, tuple)
        or not isinstance(max_proposals, int)
        or isinstance(max_proposals, bool)
        or max_proposals < 0
        or len(value.proposals) > max_proposals
        or not isinstance(value.structure_relations, tuple)
        or not isinstance(external_containers, frozenset)
    ):
        _invalid()
    for external in external_containers:
        if (
            not isinstance(external, tuple)
            or len(external) != 2
            or not isinstance(external[0], SolutionV2ContainerKind)
            or not isinstance(external[1], str)
            or _CONTAINER_KEY.fullmatch(external[1]) is None
        ):
            _invalid(SolutionDraftErrorCode.INVALID_INPUT)
    containers = {
        (proposal.placement.container_kind, proposal.placement.container_key)
        for proposal in value.proposals
        if proposal.placement.container_key is not None
    }
    containers.update(external_containers)
    architecture_components = {
        proposal.placement.container_key
        for proposal in value.proposals
        if proposal.placement.container_kind
        is SolutionV2ContainerKind.ARCHITECTURE_COMPONENT
    }
    if len(architecture_components) > MAX_ARCHITECTURE_COMPONENTS:
        reject_contract("component_count_exceeded", "$.architecture.components",
                        f"at most {MAX_ARCHITECTURE_COMPONENTS} components", str(len(architecture_components)))
    component_field_counts = {
        key: {
            SolutionV2PlacementField.IDENTITY: 0,
            SolutionV2PlacementField.RESPONSIBILITIES: 0,
            SolutionV2PlacementField.RATIONALE: 0,
            SolutionV2PlacementField.INTERFACES: 0,
        }
        for key in architecture_components
    }
    for proposal in value.proposals:
        if proposal.placement.container_kind is SolutionV2ContainerKind.ARCHITECTURE_COMPONENT:
            component_field_counts[proposal.placement.container_key][
                proposal.placement.field
            ] += 1
    for key, counts in sorted(component_field_counts.items()):
        for field, category in (
            (SolutionV2PlacementField.IDENTITY, "missing_component_identity"),
            (SolutionV2PlacementField.RESPONSIBILITIES, "missing_component_responsibility"),
            (SolutionV2PlacementField.RATIONALE, "missing_component_rationale"),
            (SolutionV2PlacementField.INTERFACES, "missing_component_interface"),
        ):
            if counts[field] < 1 or (field is SolutionV2PlacementField.IDENTITY and counts[field] != 1):
                reject_contract(category, "$.architecture.components", "complete component fields", str(counts[field]))
    seen = set()
    dependency_edges = {
        SolutionV2StructureRelationType.COMPONENT_DEPENDENCY: [],
        SolutionV2StructureRelationType.PHASE_DEPENDENCY: [],
    }
    request_flow_count = 0
    for index, relation in enumerate(value.structure_relations):
        path = relation_paths[index] if index < len(relation_paths) else f"$.structure_relations[{index}]"
        if not isinstance(relation, SolutionV2StructureRelation):
            _invalid()
        expected_kinds = _RELATION_KINDS.get(relation.relation_type)
        if expected_kinds != (
            relation.source_container_kind,
            relation.target_container_kind,
        ):
            _invalid()
        signature = (
            relation.relation_type,
            relation.source_container_kind,
            relation.source_container_key,
            relation.target_container_kind,
            relation.target_container_key,
        )
        if signature in seen:
            reject_contract("duplicate_identifier", path, "unique relation", "duplicate edge")
        seen.add(signature)
        if (
            (relation.source_container_kind, relation.source_container_key)
            not in containers
            or (relation.target_container_kind, relation.target_container_key)
            not in containers
        ):
            reject_contract("invalid_local_ref", path, "existing relation endpoints", "dangling endpoint")
        if relation.relation_type in dependency_edges:
            if relation.source_container_key == relation.target_container_key:
                reject_contract("invalid_relation", path, "distinct dependency endpoints", "self-loop")
            dependency_edges[relation.relation_type].append(
                (relation.source_container_key, relation.target_container_key)
            )
        elif relation.relation_type in {
            SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW,
            SolutionV2StructureRelationType.COMPONENT_DATA_FLOW,
        }:
            if relation.source_container_key == relation.target_container_key:
                reject_contract("invalid_relation", path, "distinct flow endpoints", "self-loop")
            if relation.relation_type is SolutionV2StructureRelationType.COMPONENT_REQUEST_FLOW:
                request_flow_count += 1
    if len(architecture_components) >= 2 and request_flow_count == 0:
        reject_contract("invalid_relation", "$.architecture.request_flows", "at least one request flow for multiple components", "0 flows")
    for edges in dependency_edges.values():
        _reject_dependency_cycle(edges)


def _reject_dependency_cycle(edges: list[tuple[str, str]]) -> None:
    dependencies: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for source, target in edges:
        nodes.update((source, target))
        dependencies.setdefault(source, set()).add(target)
    resolved: set[str] = set()
    remaining = set(nodes)
    while remaining:
        ready = {
            node for node in remaining if dependencies.get(node, set()) <= resolved
        }
        if not ready:
            reject_contract("invalid_relation", "$", "acyclic dependency graph", "dependency cycle")
        resolved.update(ready)
        remaining -= ready


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid()
    return value.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    raise ValueError("Nonstandard JSON constant.")


def _invalid(
    code: SolutionDraftErrorCode = SolutionDraftErrorCode.INVALID_RESPONSE,
) -> NoReturn:
    if code is SolutionDraftErrorCode.INVALID_RESPONSE:
        reject_contract("other_contract_failure", "$", "valid solution generation contract", "contract rejected")
    raise SolutionDraftError(code)
