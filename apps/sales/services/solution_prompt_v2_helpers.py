"""Small shared helpers for the V2 prompt modules."""

from typing import NoReturn

from apps.sales.services.solution_errors import (
    SolutionDraftError,
    SolutionDraftErrorCode,
)
from apps.sales.services.solution_generation_contract import reject_contract


def _invalid(
    code: SolutionDraftErrorCode = SolutionDraftErrorCode.INVALID_RESPONSE,
) -> NoReturn:
    if code is SolutionDraftErrorCode.INVALID_RESPONSE:
        reject_contract("other_contract_failure", "$", "valid solution generation contract", "contract rejected")
    raise SolutionDraftError(code)
