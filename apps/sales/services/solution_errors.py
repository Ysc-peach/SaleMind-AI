"""Stable, data-free errors belonging only to solution orchestration."""

from enum import StrEnum


class SolutionDraftErrorCode(StrEnum):
    INVALID_INPUT = "invalid_solution_draft_input"
    INVALID_RESPONSE = "solution_draft_invalid_response"


class SolutionDraftError(Exception):
    def __init__(self, code: SolutionDraftErrorCode):
        self.code = code.value
        self.safe_message = {
            SolutionDraftErrorCode.INVALID_INPUT: "The solution draft input is invalid.",
            SolutionDraftErrorCode.INVALID_RESPONSE: "The solution draft response is invalid.",
        }[code]
        super().__init__(self.safe_message)
