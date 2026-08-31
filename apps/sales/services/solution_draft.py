"""Read-only grounded drafting from one explicit historical analysis record."""

from dataclasses import dataclass
from enum import StrEnum

from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.services.search import search_knowledge
from apps.llm.base import LLMProvider
from apps.llm.factory import get_llm_provider
from apps.sales.models import OpportunityRequirementAnalysis as AnalysisRecord
from apps.sales.services.requirement_analysis_history import analysis_record_to_domain
from apps.sales.services.solution_errors import SolutionDraftError, SolutionDraftErrorCode
from apps.sales.services.solution_prompt import build_solution_messages
from apps.sales.services.solution_readiness import (
    SolutionReadiness, SolutionReadinessStatus, check_solution_readiness,
)
from apps.sales.services.solution_retrieval import SolutionSource, build_retrieval_intents, merge_evidence
from apps.sales.services.solution_schema import SolutionDraft, parse_solution_draft


class SolutionGenerationStatus(StrEnum):
    GENERATED = "generated"
    BLOCKED_BY_READINESS = "blocked_by_readiness"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class GroundedSolutionDraftResult:
    analysis_id: int
    readiness: SolutionReadiness
    generation_status: SolutionGenerationStatus
    draft: SolutionDraft | None
    sources: tuple[SolutionSource, ...]


def generate_grounded_solution_draft(
    analysis: AnalysisRecord,
    *,
    embedding_provider: EmbeddingProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> GroundedSolutionDraftResult:
    """No latest lookup, persistence, HTTP, SDK logic, or exception rewriting.

    Callers resolve authorization and supply the chosen saved history record.
    Neither current Opportunity facts nor full raw input are re-read here.
    """
    if not isinstance(analysis, AnalysisRecord) or analysis.pk is None or analysis._state.adding:
        raise SolutionDraftError(SolutionDraftErrorCode.INVALID_INPUT)
    analysis_id = analysis.pk
    typed = analysis_record_to_domain(analysis)
    readiness = check_solution_readiness(typed)
    if readiness.status in {
        SolutionReadinessStatus.NEEDS_SALES_CLARIFICATION,
        SolutionReadinessStatus.NEEDS_PRESALES_INVOLVEMENT,
    }:
        return GroundedSolutionDraftResult(
            analysis_id, readiness, SolutionGenerationStatus.BLOCKED_BY_READINESS, None, (),
        )
    groups = [search_knowledge(
        query=intent.query, top_k=3, document_type=None, provider=embedding_provider,
    ) for intent in build_retrieval_intents(typed)]
    sources = merge_evidence(groups)
    if not sources:
        return GroundedSolutionDraftResult(
            analysis_id, readiness, SolutionGenerationStatus.INSUFFICIENT_EVIDENCE, None, (),
        )
    provider = llm_provider if llm_provider is not None else get_llm_provider()
    generation = provider.generate(build_solution_messages(typed, readiness, sources))
    draft = parse_solution_draft(generation.content, source_count=len(sources))
    return GroundedSolutionDraftResult(
        analysis_id, readiness, SolutionGenerationStatus.GENERATED, draft, sources,
    )
