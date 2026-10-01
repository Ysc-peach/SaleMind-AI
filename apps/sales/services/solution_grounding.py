"""Independent, fail-closed semantic verification for grounded drafts."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn, TYPE_CHECKING

from django.conf import settings

from apps.llm.base import LLMProvider
from apps.llm.factory import get_llm_provider
from apps.sales.services.requirement_analysis import (
    ClarifyingQuestion,
    OpportunityRequirementAnalysis,
    RequirementConflict,
    RequirementDimension,
    RequirementFieldAnalysis,
    RequirementStatus,
)
from apps.sales.services.solution_grounding_prompt import build_solution_grounding_messages
from apps.sales.services.solution_proposal_admissibility_prompt import (
    build_proposal_admissibility_messages,
)
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import (
    AtomicSolutionClaimSet,
    SolutionDraft,
    SolutionStatement,
    SolutionStatementType,
)
from apps.sales.services.verifier_diagnostics import (
    DeterministicGuardReason,
    QwenFailureCategory,
    UnsupportedPrecisionCategory,
    VerifierEvaluationDiagnostics,
    qwen_failure_category,
)
from apps.llm.exceptions import LLMProviderError

if TYPE_CHECKING:
    from apps.sales.services.solution_prompt_v2 import SolutionV2Placement


class GroundingRelation(StrEnum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT = "INSUFFICIENT"
    CONTRADICTED = "CONTRADICTED"


class GroundingAtomicity(StrEnum):
    ATOMIC = "ATOMIC"
    COMPOUND = "COMPOUND"


class ProposalAdmissibilityDecision(StrEnum):
    ADMISSIBLE = "ADMISSIBLE"
    INADMISSIBLE = "INADMISSIBLE"


class GroundingViolationCode(StrEnum):
    CUSTOMER_FACT_NOT_SUPPORTED = "CUSTOMER_FACT_NOT_SUPPORTED"
    ENTERPRISE_FACT_NOT_SUPPORTED = "ENTERPRISE_FACT_NOT_SUPPORTED"
    UNCONFIRMED_AS_ENTERPRISE_FACT = "UNCONFIRMED_AS_ENTERPRISE_FACT"
    UNCONFIRMED_AS_NEGATIVE = "UNCONFIRMED_AS_NEGATIVE"
    REQUIREMENT_PROMOTED_TO_CAPABILITY = "REQUIREMENT_PROMOTED_TO_CAPABILITY"
    PROPOSAL_NOT_SUPPORTED = "PROPOSAL_NOT_SUPPORTED"
    PROPOSAL_NOT_ADMISSIBLE = "PROPOSAL_NOT_ADMISSIBLE"
    ENVIRONMENT_INFERENCE = "ENVIRONMENT_INFERENCE"
    MIXED_GROUNDING_STATUS = "MIXED_GROUNDING_STATUS"
    CITATION_SEMANTIC_MISMATCH = "CITATION_SEMANTIC_MISMATCH"
    OTHER_GROUNDING_VIOLATION = "OTHER_GROUNDING_VIOLATION"


@dataclass(frozen=True, slots=True)
class SolutionGroundingViolation:
    code: GroundingViolationCode
    location: str


@dataclass(frozen=True, slots=True)
class GroundingClaimPacket:
    location: str
    statement_type: SolutionStatementType
    text: str
    evidence: tuple[SolutionSource, ...]
    customer_context: "GroundingCustomerContext | OpportunityRequirementAnalysis | None"


@dataclass(frozen=True, slots=True)
class GroundingCustomerRequirement:
    field: RequirementDimension
    analysis: RequirementFieldAnalysis


@dataclass(frozen=True, slots=True)
class GroundingCustomerContext:
    requirements: tuple[GroundingCustomerRequirement, ...]
    conflicts: tuple[RequirementConflict, ...]
    clarifying_questions: tuple[ClarifyingQuestion, ...]


@dataclass(frozen=True, slots=True)
class GroundingClaimResult:
    location: str
    relation: GroundingRelation
    atomicity: GroundingAtomicity


@dataclass(frozen=True, slots=True)
class ProposalAdmissibilityPacket:
    location: str
    text: str
    related_requirement_fields: tuple[RequirementDimension, ...]
    capability_basis: tuple[SolutionSource, ...]
    customer_context: "GroundingCustomerContext"
    atomicity_required: bool = True
    placement: "SolutionV2Placement | None" = None
    phase_objective: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposalAdmissibilityResult:
    location: str
    decision: ProposalAdmissibilityDecision
    atomicity: GroundingAtomicity


@dataclass(frozen=True, slots=True)
class SolutionGroundingVerification:
    passed: bool
    results: tuple[GroundingClaimResult, ...]
    violations: tuple[SolutionGroundingViolation, ...]


class SolutionGroundingErrorCode(StrEnum):
    INVALID_INPUT = "invalid_solution_grounding_input"
    INVALID_RESPONSE = "solution_grounding_invalid_response"
    NOT_GROUNDED = "solution_draft_not_grounded"


class SolutionDraftGroundingError(Exception):
    """Stable failure with optional safe code/location pairs only."""

    def __init__(
        self,
        code: SolutionGroundingErrorCode,
        *,
        violations: tuple[SolutionGroundingViolation, ...] = (),
    ):
        self.code = code.value
        self.safe_message = {
            SolutionGroundingErrorCode.INVALID_INPUT: "The solution grounding input is invalid.",
            SolutionGroundingErrorCode.INVALID_RESPONSE: "The solution grounding response is invalid.",
            SolutionGroundingErrorCode.NOT_GROUNDED: "The solution draft did not pass grounding verification.",
        }[code]
        self.violations = violations
        super().__init__(self.safe_message)


def verify_solution_draft_grounding(
    *,
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
    llm_provider: LLMProvider | None = None,
) -> SolutionGroundingVerification:
    """Compatibility boundary for callers that already hold a final draft."""
    packets = build_grounding_claim_packets(analysis, draft, sources)
    return _verify_packets(packets, llm_provider)


def verify_atomic_solution_claims(
    *,
    analysis: OpportunityRequirementAnalysis,
    claims: AtomicSolutionClaimSet,
    sources: tuple[SolutionSource, ...],
    llm_provider: LLMProvider | None = None,
) -> SolutionGroundingVerification:
    """Verify every generated atomic claim in one type-aware batched request."""
    packets = build_atomic_grounding_claim_packets(analysis, claims, sources)
    return _verify_packets(packets, llm_provider)


def verify_atomic_solution_proposals(
    *,
    analysis: OpportunityRequirementAnalysis,
    proposals: AtomicSolutionClaimSet,
    sources: tuple[SolutionSource, ...],
    llm_provider: LLMProvider | None = None,
) -> SolutionGroundingVerification:
    """Verify one non-empty set of LLM-generated proposals only."""
    if (
        not isinstance(proposals, AtomicSolutionClaimSet)
        or not proposals.claims
        or any(
            claim.statement_type is not SolutionStatementType.PROPOSAL
            for claim in proposals.claims
        )
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    max_concurrency = settings.VERIFIER_MAX_CONCURRENCY
    if (
        not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or max_concurrency <= 0
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    packets = build_atomic_grounding_claim_packets(analysis, proposals, sources)
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    with ThreadPoolExecutor(
        max_workers=min(max_concurrency, len(packets)),
        thread_name_prefix="solution-proposal-verifier",
    ) as executor:
        futures = tuple(
            executor.submit(_verify_packets, (packet,), provider)
            for packet in packets
        )
        try:
            verifications = tuple(future.result() for future in futures)
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return SolutionGroundingVerification(
        passed=True,
        results=tuple(
            verification.results[0] for verification in verifications
        ),
        violations=(),
    )


def verify_atomic_solution_v2_proposals(
    *,
    analysis: OpportunityRequirementAnalysis,
    proposals,
    sources: tuple[SolutionSource, ...],
    allowed_source_labels: tuple[str, ...],
    llm_provider: LLMProvider | None = None,
    diagnostics: VerifierEvaluationDiagnostics | None = None,
):
    """Admit V2 engineering proposals without applying fact-entailment semantics."""

    from apps.sales.services.solution_prompt_v2 import (
        AtomicSolutionProposalSetV2,
        SolutionV2ContainerKind,
        SolutionV2PlacementField,
        SolutionV2Section,
    )

    if (
        not isinstance(analysis, OpportunityRequirementAnalysis)
        or not isinstance(proposals, AtomicSolutionProposalSetV2)
        or not proposals.proposals
        or not isinstance(allowed_source_labels, tuple)
        or len(set(allowed_source_labels)) != len(allowed_source_labels)
        or any(not isinstance(label, str) for label in allowed_source_labels)
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    _validate_sources(sources)
    source_by_label = {source.label: source for source in sources}
    allowed_labels = frozenset(allowed_source_labels)
    if not allowed_labels <= source_by_label.keys():
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)

    phase_objectives: dict[str, list[str]] = {}
    for proposal in proposals.proposals:
        placement = proposal.placement
        if (
            placement.section is SolutionV2Section.IMPLEMENTATION_PLAN
            and placement.container_kind is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
            and placement.field is SolutionV2PlacementField.OBJECTIVE
        ):
            phase_objectives.setdefault(placement.container_key, []).append(proposal.text)

    packets = []
    for index, proposal in enumerate(proposals.proposals):
        related_fields = proposal.related_requirement_fields
        invalid_citations = (
            not isinstance(proposal.citations, tuple)
            or not proposal.citations
            or len(set(proposal.citations)) != len(proposal.citations)
            or any(label not in allowed_labels for label in proposal.citations)
        )
        invalid_related_fields = invalid_citations or (
            not isinstance(related_fields, tuple)
            or len(set(related_fields)) != len(related_fields)
            or any(not isinstance(field, RequirementDimension) for field in related_fields)
            or any(not _requirement_has_context(analysis, field) for field in related_fields)
        )
        def record_rejection(
            reason: DeterministicGuardReason,
            *,
            guard_name: str,
            matched_category: str | None = None,
            matched_value: str | None = None,
        ) -> None:
            if diagnostics is None:
                return
            diagnostics.deterministic_rejection(
                proposal_index=index,
                guard_name=guard_name,
                placement={
                    "section": proposal.placement.section.value,
                    "container_kind": proposal.placement.container_kind.value,
                    "container_key": proposal.placement.container_key,
                    "field": proposal.placement.field.value,
                },
                reason_code=reason,
                related_requirement_fields=tuple(
                    field.value for field in related_fields
                    if isinstance(field, RequirementDimension)
                ) if isinstance(related_fields, tuple) else (),
                citation_count=len(proposal.citations) if isinstance(proposal.citations, tuple) else 0,
                grounding_present=not invalid_citations,
                proposal_text=proposal.text,
                matched_category=matched_category,
                matched_value=matched_value,
            )

        if invalid_related_fields:
            record_rejection(
                DeterministicGuardReason.INVALID_GROUNDING_REFERENCE
                if invalid_citations else DeterministicGuardReason.INVALID_REQUIREMENT_LINKAGE,
                guard_name=(
                    "verify_atomic_solution_v2_proposals.citation_validation"
                    if invalid_citations else
                    "verify_atomic_solution_v2_proposals.requirement_linkage_validation"
                ),
            )
            raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
        if _asserts_unresolved_as_confirmed(analysis, related_fields, proposal.text):
            record_rejection(
                DeterministicGuardReason.UNRESOLVED_AS_CONFIRMED,
                guard_name="_asserts_unresolved_as_confirmed",
            )
            _proposal_not_admissible(f"proposals[{index}]")
        basis = tuple(source_by_label[label] for label in proposal.citations)
        unsupported_precision = _unsupported_precision_match(
            proposal.text,
            analysis,
            related_fields,
            basis,
        )
        if unsupported_precision is not None:
            record_rejection(
                DeterministicGuardReason.UNSUPPORTED_PRECISION,
                guard_name="_unsupported_precision_match",
                matched_category=unsupported_precision[0].value,
                matched_value=unsupported_precision[1],
            )
            if diagnostics is not None:
                diagnostics.unsupported_precision(
                    claim_id=f"proposals[{index}]",
                    placement={
                        "section": proposal.placement.section.value,
                        "container_kind": proposal.placement.container_kind.value,
                        "container_key": proposal.placement.container_key,
                        "field": proposal.placement.field.value,
                    },
                    claim_type="proposal",
                    precision_category=unsupported_precision[0],
                    matched_value=unsupported_precision[1],
                    related_requirement_fields=tuple(
                        field.value for field in related_fields
                    ),
                    citation_count=len(proposal.citations),
                    grounding_present=bool(basis),
                    proposal_text=proposal.text,
                )
            _proposal_not_admissible(f"proposals[{index}]")
        packets.append(ProposalAdmissibilityPacket(
            location=f"proposals[{index}]",
            text=proposal.text,
            related_requirement_fields=related_fields,
            capability_basis=basis,
            customer_context=_complete_customer_context(analysis),
            atomicity_required=not (
                proposal.placement.section is SolutionV2Section.ARCHITECTURE
                and proposal.placement.container_kind is SolutionV2ContainerKind.ARCHITECTURE_COMPONENT
                and proposal.placement.field is SolutionV2PlacementField.IDENTITY
            ),
            placement=proposal.placement,
            phase_objective=(
                tuple(sorted(phase_objectives.get(proposal.placement.container_key, ())))
                if (
                    proposal.placement.section is SolutionV2Section.IMPLEMENTATION_PLAN
                    and proposal.placement.container_kind is SolutionV2ContainerKind.IMPLEMENTATION_PHASE
                    and proposal.placement.field in {
                        SolutionV2PlacementField.TASKS,
                        SolutionV2PlacementField.DELIVERABLES,
                    }
                ) else ()
            ),
        ))

    max_concurrency = settings.VERIFIER_MAX_CONCURRENCY
    if (
        not isinstance(max_concurrency, int)
        or isinstance(max_concurrency, bool)
        or max_concurrency <= 0
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    with ThreadPoolExecutor(
        max_workers=min(max_concurrency, len(packets)),
        thread_name_prefix="solution-proposal-admissibility",
    ) as executor:
        futures = tuple(
            executor.submit(
                _verify_proposal_admissibility_packet,
                packet,
                provider,
                call_index=index,
                diagnostics=diagnostics,
            )
            for index, packet in enumerate(packets, start=1)
        )
        try:
            tuple(future.result() for future in futures)
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return proposals


_CONDITIONAL_BOUNDARY_MARKERS = (
    "如果",
    "若",
    "前提",
    "待确认",
    "确认后",
    "取决于",
    "根据确认结果",
)
# Recognize a bounded confirmation prerequisite within one clause. Do not
# bridge sentence boundaries or interpret "before confirmation" as "after".
_CONFIRMATION_BOUNDARY_PATTERN = re.compile(
    r"(?<!不)(?<!无需)(?<!无须)"
    r"(?:待(?:与)?(?:客户)?确认|(?:经|在)客户确认|确认(?:完成|时间))"
    r"[^，,。.!！?？;；\r\n前]{0,64}后"
)
_PRECISION_PATTERN = re.compile(
    r"(?:"
    r"\d+(?:\.\d+)?\s*(?:个\s*)?工作日"
    r"|"
    r"\d+(?:\.\d+)?\s*(?:%|％|QPS|TPS|毫秒|ms|秒|分钟|小时|天|周|月|人天|人日|节点|台|核|GB|TB)"
    r"|\d+\s*(?:个|台)?\s*(?:应用|数据库|服务|计算|存储)?\s*节点"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
    r"|\d{4}年\d{1,2}月\d{1,2}日"
    r"|\bv\d+(?:\.\d+)+\b"
    r"|\b(?:OAuth|OIDC|SAML|TLS|HTTPS?)\s*v?\d+(?:\.\d+)+\b"
    r")",
    flags=re.IGNORECASE,
)


def _requirement_has_context(
    analysis: OpportunityRequirementAnalysis,
    field: RequirementDimension,
) -> bool:
    value = getattr(analysis.requirements, field.value)
    if value.status is RequirementStatus.KNOWN:
        return bool(value.value and value.evidence)
    return bool(
        value.evidence
        or any(field in conflict.fields for conflict in analysis.conflicts)
        or any(question.field is field for question in analysis.clarifying_questions)
    )


def _asserts_unresolved_as_confirmed(
    analysis: OpportunityRequirementAnalysis,
    related_fields: tuple[RequirementDimension, ...],
    text: str,
) -> bool:
    has_unresolved_dependency = any(
        getattr(analysis.requirements, field.value).status is not RequirementStatus.KNOWN
        for field in related_fields
    )
    return has_unresolved_dependency and not (
        any(marker in text for marker in _CONDITIONAL_BOUNDARY_MARKERS)
        or _CONFIRMATION_BOUNDARY_PATTERN.search(text) is not None
    )


def _has_unsupported_precision(
    text: str,
    analysis: OpportunityRequirementAnalysis,
    related_fields: tuple[RequirementDimension, ...],
    basis: tuple[SolutionSource, ...],
) -> bool:
    return _unsupported_precision_match(
        text,
        analysis,
        related_fields,
        basis,
    ) is not None


def _unsupported_precision_match(
    text: str,
    analysis: OpportunityRequirementAnalysis,
    related_fields: tuple[RequirementDimension, ...],
    basis: tuple[SolutionSource, ...],
) -> tuple[UnsupportedPrecisionCategory, str] | None:
    matches = tuple(match.group(0) for match in _PRECISION_PATTERN.finditer(text))
    if not matches:
        return None
    supported_text = " ".join(
        tuple(
            value
            for field in related_fields
            for value in (
                getattr(analysis.requirements, field.value).value,
                getattr(analysis.requirements, field.value).evidence,
            )
            if isinstance(value, str)
        )
        + tuple(source.content for source in basis)
    )
    normalized_basis = "".join(supported_text.lower().split())
    for match in matches:
        if "".join(match.lower().split()) not in normalized_basis:
            return _precision_category(match, text), match
    return None


def _precision_category(
    matched_value: str,
    proposal_text: str,
) -> UnsupportedPrecisionCategory:
    token = matched_value.lower()
    context = proposal_text.lower()
    if "qps" in token or "tps" in token or any(
        unit in token for unit in ("核", "gb", "tb")
    ):
        return UnsupportedPrecisionCategory.CAPACITY
    if "节点" in token or token.rstrip().endswith("台"):
        return UnsupportedPrecisionCategory.NODE_COUNT
    if "人天" in token or "人日" in token:
        return UnsupportedPrecisionCategory.STAFFING
    if "ms" in token or "毫秒" in token or (
        "秒" in token and any(marker in context for marker in ("响应", "延迟", "latency"))
    ):
        return UnsupportedPrecisionCategory.LATENCY
    if any(
        unit in token
        for unit in ("工作日", "分钟", "小时", "天", "周", "月")
    ) or re.search(r"\d{4}(?:[-/]\d{1,2}[-/]\d{1,2}|年\d{1,2}月\d{1,2}日)", token):
        return UnsupportedPrecisionCategory.DURATION
    if "%" in token or "％" in token:
        if any(marker in context for marker in ("sla", "可用", "availability")):
            return UnsupportedPrecisionCategory.SLA
        return UnsupportedPrecisionCategory.NUMERIC
    return UnsupportedPrecisionCategory.NUMERIC


def _proposal_not_admissible(location: str) -> NoReturn:
    raise SolutionDraftGroundingError(
        SolutionGroundingErrorCode.NOT_GROUNDED,
        violations=(SolutionGroundingViolation(
            GroundingViolationCode.PROPOSAL_NOT_ADMISSIBLE,
            location,
        ),),
    )


def _verify_proposal_admissibility_packet(
    packet: ProposalAdmissibilityPacket,
    provider: LLMProvider,
    *,
    call_index: int,
    diagnostics: VerifierEvaluationDiagnostics | None,
) -> ProposalAdmissibilityResult:
    started = (
        diagnostics.begin(call_index=call_index, claim_count=1)
        if diagnostics is not None
        else None
    )
    try:
        generation = provider.generate(
            build_proposal_admissibility_messages((packet,))
        )
    except LLMProviderError as error:
        if diagnostics is not None and started is not None:
            diagnostics.failure(
                started,
                failure_category=qwen_failure_category(error),
                http_status=error.http_status,
                provider_request_id=error.request_id,
            )
        raise
    try:
        result = _parse_proposal_admissibility_results(
            generation.content,
            packets=(packet,),
        )[0]
    except SolutionDraftGroundingError as error:
        if (
            diagnostics is not None
            and started is not None
            and error.code == SolutionGroundingErrorCode.INVALID_RESPONSE.value
        ):
            diagnostics.failure(
                started,
                failure_category=QwenFailureCategory.RESPONSE_PARSE_ERROR,
                provider_request_id=generation.provider_request_id,
            )
        raise
    if diagnostics is not None and started is not None:
        diagnostics.success(
            started,
            provider_request_id=generation.provider_request_id,
        )
    if (
        result.decision is not ProposalAdmissibilityDecision.ADMISSIBLE
        or (
            packet.atomicity_required
            and result.atomicity is not GroundingAtomicity.ATOMIC
        )
    ):
        _proposal_not_admissible(packet.location)
    return result


def _parse_proposal_admissibility_results(
    content: str,
    *,
    packets: tuple[ProposalAdmissibilityPacket, ...],
) -> tuple[ProposalAdmissibilityResult, ...]:
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
        _invalid_response()
    _object(payload, {"results"})
    items = payload["results"]
    if not isinstance(items, list) or len(items) != len(packets):
        _invalid_response()
    allowed_locations = frozenset(packet.location for packet in packets)
    by_location = {}
    for item in items:
        _object(item, {"location", "decision", "atomicity"})
        location = item["location"]
        decision = item["decision"]
        atomicity = item["atomicity"]
        if (
            not isinstance(location, str)
            or location not in allowed_locations
            or location in by_location
            or not isinstance(decision, str)
            or decision not in ProposalAdmissibilityDecision._value2member_map_
            or not isinstance(atomicity, str)
            or atomicity not in GroundingAtomicity._value2member_map_
        ):
            _invalid_response()
        by_location[location] = ProposalAdmissibilityResult(
            location,
            ProposalAdmissibilityDecision(decision),
            GroundingAtomicity(atomicity),
        )
    if set(by_location) != allowed_locations:
        _invalid_response()
    return tuple(by_location[packet.location] for packet in packets)


def _verify_packets(
    packets: tuple[GroundingClaimPacket, ...],
    llm_provider: LLMProvider | None,
) -> SolutionGroundingVerification:
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    generation = provider.generate(
        build_solution_grounding_messages(packets),
    )
    results = _parse_results(generation.content, packets=packets)
    violations = []
    for packet, result in zip(packets, results, strict=True):
        if (
            result.relation is not GroundingRelation.SUPPORTED
            or result.atomicity is not GroundingAtomicity.ATOMIC
        ):
            violations.append(SolutionGroundingViolation(
                (
                    _violation_code(packet.statement_type)
                    if result.relation is not GroundingRelation.SUPPORTED
                    else GroundingViolationCode.OTHER_GROUNDING_VIOLATION
                ),
                packet.location,
            ))
    verification = SolutionGroundingVerification(
        passed=not violations,
        results=results,
        violations=tuple(violations),
    )
    if not verification.passed:
        raise SolutionDraftGroundingError(
            SolutionGroundingErrorCode.NOT_GROUNDED,
            violations=verification.violations,
        )
    return verification


def build_atomic_grounding_claim_packets(
    analysis: OpportunityRequirementAnalysis,
    claims: AtomicSolutionClaimSet,
    sources: tuple[SolutionSource, ...],
) -> tuple[GroundingClaimPacket, ...]:
    """Scope authoritative evidence independently for each atomic IR claim."""
    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(claims, AtomicSolutionClaimSet):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    _validate_sources(sources)
    source_by_label = {source.label: source for source in sources}
    packets = []
    for index, claim in enumerate(claims.claims):
        if any(label not in source_by_label for label in claim.citations):
            raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
        evidence = () if claim.statement_type is SolutionStatementType.CUSTOMER_FACT else tuple(
            source_by_label[label] for label in claim.citations
        )
        customer_context = None
        if claim.statement_type in {
            SolutionStatementType.CUSTOMER_FACT,
            SolutionStatementType.PROPOSAL,
        }:
            customer_context = _complete_customer_context(analysis)
        elif claim.statement_type is SolutionStatementType.UNRESOLVED:
            customer_context = _customer_context_for_section(analysis, claim.section.value)
        packets.append(GroundingClaimPacket(
            location=f"claims[{index}]",
            statement_type=claim.statement_type,
            text=claim.text,
            evidence=evidence,
            customer_context=customer_context,
        ))
    return tuple(packets)


_CUSTOMER_FIELDS_BY_SECTION = {
    "overall_approach": (
        RequirementDimension.BUSINESS_GOAL,
        RequirementDimension.USE_SCENARIO,
        RequirementDimension.USER_SCALE,
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
    ),
    "deployment": (
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.USER_SCALE,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "data_security": (
        RequirementDimension.DATA_SECURITY_REQUIREMENT,
        RequirementDimension.DEPLOYMENT_REQUIREMENT,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "integration": (
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.USE_SCENARIO,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
    "implementation": (
        RequirementDimension.TIMELINE,
        RequirementDimension.BUDGET,
        RequirementDimension.EXISTING_ENVIRONMENT,
        RequirementDimension.INTEGRATION_REQUIREMENT,
        RequirementDimension.TECHNICAL_CONSTRAINTS,
    ),
}


def _customer_context_for_section(
    analysis: OpportunityRequirementAnalysis,
    section: str,
) -> GroundingCustomerContext:
    fields = _CUSTOMER_FIELDS_BY_SECTION[section]
    allowed = frozenset(fields)
    return GroundingCustomerContext(
        requirements=tuple(
            GroundingCustomerRequirement(field, getattr(analysis.requirements, field.value))
            for field in fields
        ),
        conflicts=tuple(
            conflict for conflict in analysis.conflicts if any(field in allowed for field in conflict.fields)
        ),
        clarifying_questions=tuple(
            question for question in analysis.clarifying_questions if question.field in allowed
        ),
    )


def _complete_customer_context(
    analysis: OpportunityRequirementAnalysis,
) -> GroundingCustomerContext:
    return GroundingCustomerContext(
        requirements=tuple(
            GroundingCustomerRequirement(field, getattr(analysis.requirements, field.value))
            for field in RequirementDimension
        ),
        conflicts=analysis.conflicts,
        clarifying_questions=analysis.clarifying_questions,
    )


def build_grounding_claim_packets(
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
) -> tuple[GroundingClaimPacket, ...]:
    """Freeze one scoped verifier packet per structurally valid statement."""
    _validate_input(analysis, draft, sources)
    source_by_label = {source.label: source for source in sources}
    packets = []
    for location, statement in _located_statements(draft):
        if any(label not in source_by_label for label in statement.citations):
            raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
        evidence = () if statement.type is SolutionStatementType.CUSTOMER_FACT else tuple(
            source_by_label[label] for label in statement.citations
        )
        customer_context = (
            None if statement.type is SolutionStatementType.ENTERPRISE_FACT else analysis
        )
        packets.append(GroundingClaimPacket(
            location=location,
            statement_type=statement.type,
            text=statement.text,
            evidence=evidence,
            customer_context=customer_context,
        ))
    return tuple(packets)


def _validate_input(
    analysis: OpportunityRequirementAnalysis,
    draft: SolutionDraft,
    sources: tuple[SolutionSource, ...],
) -> None:
    if not isinstance(analysis, OpportunityRequirementAnalysis) or not isinstance(draft, SolutionDraft):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)
    _validate_sources(sources)


def _validate_sources(sources: tuple[SolutionSource, ...]) -> None:
    if (
        not isinstance(sources, tuple)
        or not sources
        or any(not isinstance(source, SolutionSource) for source in sources)
        or tuple(source.label for source in sources) != tuple(f"S{i}" for i in range(1, len(sources) + 1))
    ):
        raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_INPUT)


def _located_statements(draft: SolutionDraft) -> tuple[tuple[str, SolutionStatement], ...]:
    items = [
        (f"executive_summary[{index}]", statement)
        for index, statement in enumerate(draft.executive_summary)
    ]
    items.extend(
        (f"solution_sections.{section.key}.statements[{index}]", statement)
        for section in draft.solution_sections
        for index, statement in enumerate(section.statements)
    )
    return tuple(items)


def _parse_results(
    content: str,
    *,
    packets: tuple[GroundingClaimPacket, ...],
) -> tuple[GroundingClaimResult, ...]:
    text = _text(content)
    fence = re.fullmatch(r"```json[ \t]*\r?\n(.*)\r?\n```", text, flags=re.DOTALL)
    if fence is not None:
        text = fence.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        _invalid_response()
    _object(payload, {"results"})
    items = payload["results"]
    if not isinstance(items, list) or len(items) != len(packets):
        _invalid_response()
    allowed_locations = frozenset(packet.location for packet in packets)
    by_location = {}
    for item in items:
        _object(item, {"location", "relation", "atomicity"})
        location = item["location"]
        relation = item["relation"]
        atomicity = item["atomicity"]
        if (
            not isinstance(location, str)
            or location not in allowed_locations
            or location in by_location
            or not isinstance(relation, str)
            or relation not in GroundingRelation._value2member_map_
            or not isinstance(atomicity, str)
            or atomicity not in GroundingAtomicity._value2member_map_
        ):
            _invalid_response()
        by_location[location] = GroundingClaimResult(
            location,
            GroundingRelation(relation),
            GroundingAtomicity(atomicity),
        )
    if set(by_location) != allowed_locations:
        _invalid_response()
    return tuple(by_location[packet.location] for packet in packets)


def _violation_code(statement_type: SolutionStatementType) -> GroundingViolationCode:
    return {
        SolutionStatementType.CUSTOMER_FACT: GroundingViolationCode.CUSTOMER_FACT_NOT_SUPPORTED,
        SolutionStatementType.ENTERPRISE_FACT: GroundingViolationCode.ENTERPRISE_FACT_NOT_SUPPORTED,
        SolutionStatementType.PROPOSAL: GroundingViolationCode.PROPOSAL_NOT_SUPPORTED,
        SolutionStatementType.UNRESOLVED: GroundingViolationCode.OTHER_GROUNDING_VIOLATION,
    }[statement_type]


def _object(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        _invalid_response()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid_response()
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


def _invalid_response() -> NoReturn:
    raise SolutionDraftGroundingError(SolutionGroundingErrorCode.INVALID_RESPONSE)
