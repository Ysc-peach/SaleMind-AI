"""Explicit Admin extraction orchestration; replay never constructs a provider."""
from uuid import UUID

from apps.knowledge.models import GroundingFactExtractionAttempt
from apps.llm.base import LLMProvider
from apps.llm.exceptions import LLMProviderError
from .grounding_fact_attempts import (
    ExtractionClaim, FactExtractionOperationError, claim_extraction, fail_extraction,
)
from .grounding_facts import GroundingFactExtractionError, extract_grounding_facts


def run_document_fact_extraction(document_id: int, *, actor_id: int,
                                expected_index_run_id: UUID,
                                retry_after_attempt_id: int | None = None,
                                llm_provider: LLMProvider | None = None) -> ExtractionClaim:
    claim = claim_extraction(document_id, actor_id=actor_id,
                             expected_index_run_id=expected_index_run_id,
                             retry_after_attempt_id=retry_after_attempt_id)
    if claim.state != 'claimed':
        return claim
    try:
        extract_grounding_facts(document_id, llm_provider=llm_provider,
                               managed_attempt=claim.binding)
    except (FactExtractionOperationError, GroundingFactExtractionError) as error:
        fail_extraction(claim.binding, code=error.code)
        raise FactExtractionOperationError(error.code) from None
    except LLMProviderError:
        fail_extraction(claim.binding, code='fact_extraction_provider_failed')
        raise FactExtractionOperationError('fact_extraction_provider_failed') from None
    except Exception:
        fail_extraction(claim.binding, code='fact_extraction_failed')
        raise FactExtractionOperationError('fact_extraction_failed') from None
    attempt = GroundingFactExtractionAttempt.objects.get(pk=claim.attempt_id)
    return ExtractionClaim('succeeded', None, attempt.pk, attempt.index_run_id, attempt.proposed_count)
