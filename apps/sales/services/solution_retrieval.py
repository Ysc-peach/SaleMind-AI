"""Pure requirement-value intents and deterministic evidence merging."""

from dataclasses import asdict, dataclass
from itertools import zip_longest

from apps.knowledge.evidence import EvidenceSource, source_from_result
from apps.knowledge.services.search import KnowledgeSearchResult
from apps.sales.services.requirement_analysis import OpportunityRequirementAnalysis, RequirementStatus


@dataclass(frozen=True, slots=True)
class SolutionRetrievalIntent:
    key: str
    query: str


@dataclass(frozen=True, slots=True)
class SolutionSource(EvidenceSource):
    label: str


_INTENT_FIELDS = (
    ("business_product", ("business_goal", "use_scenario", "user_scale")),
    ("deployment_security", ("deployment_requirement", "data_security_requirement", "existing_environment", "technical_constraints")),
    ("integration_implementation", ("integration_requirement", "existing_environment", "timeline")),
)


def build_retrieval_intents(analysis: OpportunityRequirementAnalysis) -> tuple[SolutionRetrievalIntent, ...]:
    intents = []
    for key, names in _INTENT_FIELDS:
        values = [getattr(analysis.requirements, name) for name in names]
        query = " ".join(item.value for item in values if item.status is RequirementStatus.KNOWN)
        if query:
            intents.append(SolutionRetrievalIntent(key=key, query=query))
    return tuple(intents)


def merge_evidence(groups: list[list[KnowledgeSearchResult]]) -> tuple[SolutionSource, ...]:
    """Round-robin ranked groups, dedupe by chunk id; first occurrence wins."""
    sources, seen = [], set()
    for row in zip_longest(*groups):
        for result in row:
            if result is None or result.chunk_id in seen:
                continue
            seen.add(result.chunk_id)
            sources.append(SolutionSource(
                **asdict(source_from_result(result)), label=f"S{len(sources) + 1}",
            ))
            if len(sources) == 8:
                return tuple(sources)
    return tuple(sources)
