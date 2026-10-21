"""Stable, data-free errors belonging only to solution orchestration."""

from enum import StrEnum
from dataclasses import dataclass


class SolutionDraftErrorCode(StrEnum):
    INVALID_INPUT = "invalid_solution_draft_input"
    INVALID_RESPONSE = "solution_draft_invalid_response"
    INSUFFICIENT_APPROVED_EVIDENCE = "solution_draft_insufficient_approved_evidence"
    NO_PROPOSALS = "solution_draft_no_proposals"


class SolutionDraftError(Exception):
    def __init__(self, code: SolutionDraftErrorCode):
        self.code = code.value
        self.safe_message = {
            SolutionDraftErrorCode.INVALID_INPUT: "The solution draft input is invalid.",
            SolutionDraftErrorCode.INVALID_RESPONSE: "The solution draft response is invalid.",
            SolutionDraftErrorCode.INSUFFICIENT_APPROVED_EVIDENCE: "No approved, current evidence is available for proposal citations.",
            SolutionDraftErrorCode.NO_PROPOSALS: "No technical proposals were generated; no deliverable solution was saved.",
        }[code]
        super().__init__(self.safe_message)


@dataclass(frozen=True, slots=True)
class SolutionContractFailure:
    """Internal rejection metadata; never provider text or public API detail."""

    category: str
    json_path: str
    expected: str
    actual: str
    citation_subtype: str | None = None
    allowed_ids: tuple[str, ...] = ()
    offending_ids: tuple[str, ...] = ()
    allowed_keys: tuple[str, ...] = ()


class SolutionContractError(SolutionDraftError):
    def __init__(self, failure: SolutionContractFailure):
        self.contract_failure = failure
        super().__init__(SolutionDraftErrorCode.INVALID_RESPONSE)
