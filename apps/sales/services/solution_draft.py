"""Read-only grounded drafting from one explicit historical analysis record."""

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Callable, Sequence
import logging
import json
from html import escape

from django.conf import settings

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.services.search import search_knowledge
from apps.llm.base import LLMMessage, LLMProvider
from apps.llm.factory import get_llm_provider
from apps.llm.exceptions import LLMProviderError
from apps.llm.verifier_factory import get_verifier_provider
from apps.sales.models import OpportunityRequirementAnalysis as AnalysisRecord
from apps.sales.services.requirement_analysis_history import analysis_record_to_domain
from apps.sales.services.solution_admission import GroundingAdmission, build_solution_admission
from apps.sales.services.solution_errors import (
    SolutionContractFailure, SolutionDraftError, SolutionDraftErrorCode,
)
from apps.sales.services.solution_evaluation import emit_evaluation
from apps.sales.services.solution_grounding import (
    verify_atomic_solution_proposals,
    verify_atomic_solution_v2_proposals,
)
from apps.sales.services.solution_prompt import build_solution_messages
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    assurance_runtime_proposal_budget,
    build_solution_v2_assurance_messages,
    build_solution_v2_core_messages,
    build_solution_v2_implementation_messages,
    implementation_runtime_proposal_budget,
    merge_solution_v2_proposal_passes,
    parse_solution_v2_assurance_output,
    parse_solution_v2_core_output,
    parse_solution_v2_implementation_output,
)
from apps.sales.services.solution_readiness import (
    SolutionReadiness, SolutionReadinessStatus, check_solution_readiness,
)
from apps.sales.services.solution_retrieval import SolutionSource, build_retrieval_intents, merge_evidence
from apps.sales.services.solution_schema import (
    SolutionDraft,
    AtomicSolutionClaimSet,
    SolutionUnresolvedItem,
    assemble_solution_draft,
    build_solution_unresolved_items,
    parse_atomic_solution_proposals,
)
from apps.sales.services.solution_schema_v2 import (
    SolutionDraftV2,
    V2ClaimProvenanceBinding,
    assemble_solution_draft_v2,
    build_v2_deterministic_items,
)


logger = logging.getLogger(__name__)


class SolutionGenerationStatus(StrEnum):
    GENERATED = "generated"
    BLOCKED_BY_READINESS = "blocked_by_readiness"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class GroundedSolutionDraftResult:
    analysis_id: int
    readiness: SolutionReadiness
    generation_status: SolutionGenerationStatus
    draft: SolutionDraft | SolutionDraftV2 | None
    sources: tuple[SolutionSource, ...]
    unresolved_items: tuple[SolutionUnresolvedItem, ...]
    admission: GroundingAdmission | None
    schema_version: int = 1
    v2_provenance_bindings: tuple[V2ClaimProvenanceBinding, ...] = ()


def _contract_rejection_diagnostic(failure: SolutionContractFailure) -> dict:
    """Project only formal parser metadata; unknown provider keys are redacted."""
    path = failure.json_path
    if failure.category == "unknown_key":
        path = path.rsplit(".", 1)[0] + ".<key>"
    diagnostic = {
        "category": failure.category, "json_path": path,
        "expected": failure.expected, "actual": failure.actual,
    }
    if failure.allowed_keys:
        # These names come from the executing closed-object contract, never
        # from the model's extra keys or values.
        diagnostic["allowed_keys"] = failure.allowed_keys
    if failure.category == "invalid_citation":
        diagnostic.update(citation_subtype=failure.citation_subtype,
                          allowed_ids=failure.allowed_ids,
                          offending_ids=failure.offending_ids)
    return diagnostic


def _contract_regeneration_message(failure: SolutionContractFailure | None) -> LLMMessage:
    """Feedback for the existing second attempt, never a repaired proposal."""
    diagnostic = (
        _contract_rejection_diagnostic(failure)
        if isinstance(failure, SolutionContractFailure)
        else {"category": "unknown_contract_failure"}
    )
    # Do not repeat disallowed IDs in generation input. The formal allowlist is
    # sufficient; originals remain in the secret-safe parser diagnostic log.
    diagnostic.pop("offending_ids", None)
    metadata = escape(json.dumps(diagnostic, ensure_ascii=False), quote=False)
    return {
        "role": "user",
        "content": (
            "<contract_regeneration>\n"
            f"<contract_failure>{metadata}</contract_failure>\n"
            "<instructions>上一版输出未通过正式合同校验。依据原始需求、已准入依据和上述错误，"
            "重新生成本 pass 的完整合法 JSON，而不是差异补丁。所有原始约束和数量上限保持不变。"
            "不得机械替换引用编号；每条判断必须由实际允许引用的证据支持。"
            "不得编造事实、能力、承诺或引用，不得删除关键结构来绕过安全校验。"
            "只返回完整 JSON。</instructions>\n"
            "</contract_regeneration>"
        ),
    }


def _generate_and_parse_v2_pass(
    provider: LLMProvider,
    messages: Sequence[LLMMessage],
    parse: Callable[[str], AtomicSolutionProposalSetV2],
    *,
    pass_name: str | None = None,
) -> AtomicSolutionProposalSetV2:
    """Regenerate once only when strict parsing rejects provider output."""

    request_messages = messages
    for attempt in range(2):
        try:
            generation = provider.generate_json(
                request_messages,
                max_output_tokens=settings.SOLUTION_DRAFT_MAX_OUTPUT_TOKENS,
            )
        except LLMProviderError as error:
            emit_evaluation("generation_provider", phase=pass_name, success=False,
                            category=error.failure_kind.value if error.failure_kind else None)
            diagnostic = {
                "phase": pass_name, "attempt": attempt + 1,
                "exception_class": type(error).__name__, "code": error.code,
                "category": error.failure_kind.value if error.failure_kind else "unknown_provider_error",
                "http_status": error.http_status,
            }
            logger.warning("Solution generation provider failed: %s", diagnostic,
                           extra={"solution_generation_failure": diagnostic})
            raise
        emit_evaluation("generation_provider", phase=pass_name, success=True)
        try:
            result = parse(generation.content)
        except SolutionDraftError as error:
            failure = getattr(error, "contract_failure", None)
            emit_evaluation("generation_parser", phase=pass_name, success=False,
                            category=failure.category if failure else "unknown_contract_failure")
            diagnostic = {
                "phase": pass_name, "attempt": attempt + 1,
                "exception_class": type(error).__name__, "code": error.code,
                "category": "unknown_contract_failure",
            }
            if isinstance(failure, SolutionContractFailure):
                diagnostic.update(_contract_rejection_diagnostic(failure))
            finish_reason = getattr(generation, "finish_reason", None)
            diagnostic["finish_reason"] = finish_reason if finish_reason in {
                "stop", "length", "content_filter", "tool_calls", "function_call",
                "insufficient_system_resource", "aborted",
            } else None
            for key in ("prompt_tokens", "completion_tokens"):
                value = getattr(generation, key, None)
                diagnostic[key] = value if type(value) is int and value >= 0 else None
            logger.warning("Solution generation contract rejected: %s", diagnostic,
                           extra={"solution_generation_failure": diagnostic})
            if (
                attempt == 1
                or error.code != SolutionDraftErrorCode.INVALID_RESPONSE.value
            ):
                raise
            request_messages = [*messages, _contract_regeneration_message(failure)]
        else:
            emit_evaluation("generation_parser", phase=pass_name, success=True,
                            count=len(result.proposals))
            return result
    raise AssertionError("unreachable after two generation attempts")


def generate_grounded_solution_draft(
    analysis: AnalysisRecord,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
    verifier_provider: LLMProvider | None = None,
    schema_version: int = 1,
) -> GroundedSolutionDraftResult:
    """No latest lookup, persistence, HTTP, SDK logic, or exception rewriting.

    Callers resolve authorization and supply the chosen saved history record.
    Neither current Opportunity facts nor full raw input are re-read here.
    """
    if (
        not isinstance(analysis, AnalysisRecord)
        or analysis.pk is None
        or analysis._state.adding
        or not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version not in {1, 2}
    ):
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_INPUT)
    analysis_id = analysis.pk
    typed = analysis_record_to_domain(analysis)
    readiness = check_solution_readiness(typed)
    unresolved_items = build_solution_unresolved_items(typed)
    if readiness.status in {
        SolutionReadinessStatus.NEEDS_SALES_CLARIFICATION,
        SolutionReadinessStatus.NEEDS_PRESALES_INVOLVEMENT,
    }:
        return GroundedSolutionDraftResult(
            analysis_id, readiness, SolutionGenerationStatus.BLOCKED_BY_READINESS,
            None, (), unresolved_items, None, schema_version=schema_version,
        )
    groups = [search_knowledge(
        query=intent.query, top_k=3, document_type=None, provider=embedding_provider,
    ) for intent in build_retrieval_intents(typed)]
    sources = merge_evidence(groups)
    if not sources:
        if schema_version == 2:
            raise SolutionDraftError(SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE)
        return GroundedSolutionDraftResult(
            analysis_id, readiness, SolutionGenerationStatus.INSUFFICIENT_EVIDENCE,
            None, (), unresolved_items, None, schema_version=schema_version,
        )
    try:
        admission = build_solution_admission(typed, sources)
    except Exception:
        emit_evaluation("deterministic_admission", success=False)
        raise
    if schema_version == 2 and not admission.allowed_proposal_source_labels:
        raise SolutionDraftError(SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE)
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    if schema_version == 1:
        generation = provider.generate(
            build_solution_messages(typed, readiness, sources, admission),
            max_output_tokens=settings.SOLUTION_DRAFT_MAX_OUTPUT_TOKENS,
        )
        proposals = parse_atomic_solution_proposals(
            generation.content,
            allowed_source_labels=admission.allowed_proposal_source_labels,
        )
        has_proposals = bool(proposals.claims)
    else:
        core = _generate_and_parse_v2_pass(
            provider,
            build_solution_v2_core_messages(typed, readiness, sources, admission),
            lambda content: parse_solution_v2_core_output(
                content,
                allowed_source_labels=admission.allowed_proposal_source_labels,
            ),
            pass_name="core",
        )
        implementation_budget = implementation_runtime_proposal_budget(
            len(core.proposals)
        )
        implementation = _generate_and_parse_v2_pass(
            provider,
            build_solution_v2_implementation_messages(
                typed, readiness, sources, admission, core
            ),
            lambda content: parse_solution_v2_implementation_output(
                content,
                allowed_source_labels=admission.allowed_proposal_source_labels,
                max_proposals=implementation_budget,
            ),
            pass_name="implementation",
        )
        assurance_budget = assurance_runtime_proposal_budget(
            len(core.proposals), len(implementation.proposals)
        )
        assurance = _generate_and_parse_v2_pass(
            provider,
            build_solution_v2_assurance_messages(
                typed, readiness, sources, admission, core, implementation
            ),
            lambda content: parse_solution_v2_assurance_output(
                content,
                allowed_source_labels=admission.allowed_proposal_source_labels,
                implementation=implementation,
                max_proposals=assurance_budget,
            ),
            pass_name="assurance",
        )
        try:
            proposals = merge_solution_v2_proposal_passes(
                core, implementation, assurance
            )
            if not proposals.proposals:
                # Deterministic facts alone are not a newly generated deliverable.
                # Empty individual passes remain legal; never invent filler claims.
                raise SolutionDraftError(SolutionDraftErrorCode.NO_PROPOSALS)
        except SolutionDraftError:
            emit_evaluation("global_structure", success=False)
            raise
        emit_evaluation("global_structure", success=True, count=len(proposals.proposals))
        has_proposals = bool(proposals.proposals)
    if has_proposals:
        active_verifier = verifier_provider
        if active_verifier is None:
            configured_verifier = settings.VERIFIER_PROVIDER
            active_verifier = (
                get_verifier_provider()
                if isinstance(configured_verifier, str) and configured_verifier.strip()
                else provider
            )
        if schema_version == 1:
            verify_atomic_solution_proposals(
                analysis=typed,
                proposals=proposals,
                sources=sources,
                llm_provider=active_verifier,
            )
        else:
            verify_atomic_solution_v2_proposals(
                analysis=typed,
                proposals=proposals,
                sources=sources,
                allowed_source_labels=admission.allowed_proposal_source_labels,
                llm_provider=active_verifier,
            )
    # External model calls must stay outside database transactions. Rebuild the
    # deterministic admission afterward so a concurrent reindex/approval change
    # cannot return claims whose provenance is no longer current.
    try:
        current_admission = build_solution_admission(typed, sources)
    except Exception:
        emit_evaluation("deterministic_admission", success=False)
        raise
    if current_admission != admission:
        emit_evaluation("deterministic_admission", success=False)
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_INPUT)
    emit_evaluation("deterministic_admission", success=True)
    if schema_version == 1:
        claims = AtomicSolutionClaimSet(admission.claims.claims + proposals.claims)
        draft = assemble_solution_draft(claims, typed)
        bindings = ()
    else:
        emit_evaluation("assembly_started")
        assembly = assemble_solution_draft_v2(
            build_v2_deterministic_items(typed, admission),
            proposals,
        )
        draft = assembly.draft
        bindings = assembly.provenance_bindings
        emit_evaluation("assembly", success=True)
    return GroundedSolutionDraftResult(
        analysis_id, readiness, SolutionGenerationStatus.GENERATED,
        draft, sources, unresolved_items, admission,
        schema_version=schema_version,
        v2_provenance_bindings=bindings,
    )
