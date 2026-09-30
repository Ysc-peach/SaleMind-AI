"""Evaluation-only, secret-safe diagnostics for Qwen verifier calls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from threading import Lock
from time import perf_counter

from apps.llm.exceptions import LLMErrorCode, LLMProviderError, LLMProviderFailureKind


class QwenFailureCategory(StrEnum):
    TIMEOUT = "qwen_timeout"
    RATE_LIMITED = "qwen_rate_limited"
    CONNECTION_ERROR = "qwen_connection_error"
    SERVER_ERROR = "qwen_server_error"
    AUTH_ERROR = "qwen_auth_error"
    QUOTA_ERROR = "qwen_quota_error"
    INVALID_RESPONSE = "qwen_invalid_response"
    RESPONSE_PARSE_ERROR = "qwen_response_parse_error"
    UNKNOWN_PROVIDER_ERROR = "qwen_unknown_provider_error"


class UnsupportedPrecisionCategory(StrEnum):
    LATENCY = "unsupported_latency_precision"
    CAPACITY = "unsupported_capacity_precision"
    NODE_COUNT = "unsupported_node_count"
    DURATION = "unsupported_duration"
    STAFFING = "unsupported_staffing"
    SLA = "unsupported_sla"
    COST = "unsupported_cost"
    NUMERIC = "unsupported_numeric_precision"


class DeterministicGuardReason(StrEnum):
    INVALID_GROUNDING_REFERENCE = "invalid_grounding_reference"
    INVALID_REQUIREMENT_LINKAGE = "invalid_requirement_linkage"
    UNRESOLVED_AS_CONFIRMED = "unresolved_as_confirmed"
    UNSUPPORTED_PRECISION = "unsupported_precision"


_CATEGORY_BY_KIND = {
    LLMProviderFailureKind.TIMEOUT: QwenFailureCategory.TIMEOUT,
    LLMProviderFailureKind.RATE_LIMITED: QwenFailureCategory.RATE_LIMITED,
    LLMProviderFailureKind.CONNECTION_ERROR: QwenFailureCategory.CONNECTION_ERROR,
    LLMProviderFailureKind.SERVER_ERROR: QwenFailureCategory.SERVER_ERROR,
    LLMProviderFailureKind.AUTH_ERROR: QwenFailureCategory.AUTH_ERROR,
    LLMProviderFailureKind.QUOTA_ERROR: QwenFailureCategory.QUOTA_ERROR,
    LLMProviderFailureKind.INVALID_RESPONSE: QwenFailureCategory.INVALID_RESPONSE,
    LLMProviderFailureKind.RESPONSE_PARSE_ERROR: QwenFailureCategory.RESPONSE_PARSE_ERROR,
    LLMProviderFailureKind.UNKNOWN_PROVIDER_ERROR: QwenFailureCategory.UNKNOWN_PROVIDER_ERROR,
}


@dataclass(frozen=True, slots=True)
class _VerifierCallStart:
    call_index: int
    claim_count: int
    attempt_number: int
    started_at: datetime
    started_counter: float


@dataclass(frozen=True, slots=True)
class VerifierCallDiagnostic:
    call_index: int
    claim_count: int
    attempt_number: int
    started_at: datetime
    ended_at: datetime
    latency_seconds: float
    success: bool
    failure_category: QwenFailureCategory | None
    http_status: int | None
    provider_request_id: str | None

    def safe_dict(self) -> dict[str, object]:
        return {
            "call_index": self.call_index,
            "claim_count": self.claim_count,
            "attempt_number": self.attempt_number,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "latency_seconds": self.latency_seconds,
            "success": self.success,
            "failure_category": (
                self.failure_category.value if self.failure_category is not None else None
            ),
            "http_status": self.http_status,
            "provider_request_id": self.provider_request_id,
        }


@dataclass(frozen=True, slots=True)
class UnsupportedPrecisionDiagnostic:
    """Safe local evidence for a deterministic pre-verifier rejection."""

    claim_id: str
    placement: dict[str, str | None]
    claim_type: str
    precision_category: UnsupportedPrecisionCategory
    matched_value: str
    related_requirement_fields: tuple[str, ...]
    citation_count: int
    grounding_present: bool
    reason_code: str
    proposal_excerpt: str

    def safe_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "placement": dict(self.placement),
            "claim_type": self.claim_type,
            "precision_category": self.precision_category.value,
            "matched_value": self.matched_value,
            "related_requirement_fields": list(self.related_requirement_fields),
            "citation_count": self.citation_count,
            "grounding_present": self.grounding_present,
            "reason_code": self.reason_code,
            "proposal_excerpt": self.proposal_excerpt,
        }


@dataclass(frozen=True, slots=True)
class DeterministicGuardDiagnostic:
    """Metadata emitted at the actual rejecting pre-verifier branch."""

    proposal_index: int
    claim_id: str
    placement: dict[str, str | None]
    claim_type: str
    guard_name: str
    reason_code: DeterministicGuardReason
    matched_category: str | None
    matched_value: str | None
    related_requirement_fields: tuple[str, ...]
    citation_count: int
    grounding_present: bool
    proposal_excerpt: str

    def safe_dict(self) -> dict[str, object]:
        return {
            "proposal_index": self.proposal_index,
            "claim_id": self.claim_id,
            "placement": dict(self.placement),
            "claim_type": self.claim_type,
            "guard_name": self.guard_name,
            "reason_code": self.reason_code.value,
            "matched_category": self.matched_category,
            "matched_value": self.matched_value,
            "related_requirement_fields": list(self.related_requirement_fields),
            "citation_count": self.citation_count,
            "grounding_present": self.grounding_present,
            "proposal_excerpt": self.proposal_excerpt,
        }


class VerifierEvaluationDiagnostics:
    """Thread-safe collector containing metadata only, never prompts or responses."""

    def __init__(self):
        self._lock = Lock()
        self._calls: list[VerifierCallDiagnostic] = []
        self._precision_rejections: list[UnsupportedPrecisionDiagnostic] = []
        self._deterministic_rejections: list[DeterministicGuardDiagnostic] = []

    @property
    def calls(self) -> tuple[VerifierCallDiagnostic, ...]:
        with self._lock:
            return tuple(sorted(self._calls, key=lambda item: item.call_index))

    @property
    def precision_rejections(self) -> tuple[UnsupportedPrecisionDiagnostic, ...]:
        with self._lock:
            return tuple(self._precision_rejections)

    @property
    def deterministic_rejections(self) -> tuple[DeterministicGuardDiagnostic, ...]:
        with self._lock:
            return tuple(self._deterministic_rejections)

    def deterministic_rejection(
        self,
        *,
        proposal_index: int,
        placement: dict[str, str | None],
        guard_name: str,
        reason_code: DeterministicGuardReason,
        related_requirement_fields: tuple[str, ...],
        citation_count: int,
        grounding_present: bool,
        proposal_text: str,
        matched_category: str | None = None,
        matched_value: str | None = None,
    ) -> None:
        item = DeterministicGuardDiagnostic(
            proposal_index=proposal_index,
            claim_id=f"proposals[{proposal_index}]",
            placement=dict(placement),
            claim_type="proposal",
            guard_name=guard_name,
            reason_code=reason_code,
            matched_category=matched_category,
            matched_value=matched_value,
            related_requirement_fields=related_requirement_fields,
            citation_count=citation_count,
            grounding_present=grounding_present,
            proposal_excerpt=" ".join(proposal_text.split())[:160],
        )
        with self._lock:
            self._deterministic_rejections.append(item)

    def unsupported_precision(
        self,
        *,
        claim_id: str,
        placement: dict[str, str | None],
        claim_type: str,
        precision_category: UnsupportedPrecisionCategory,
        matched_value: str,
        related_requirement_fields: tuple[str, ...],
        citation_count: int,
        grounding_present: bool,
        proposal_text: str,
    ) -> None:
        excerpt = " ".join(proposal_text.split())[:160]
        item = UnsupportedPrecisionDiagnostic(
            claim_id=claim_id,
            placement=dict(placement),
            claim_type=claim_type,
            precision_category=precision_category,
            matched_value=matched_value,
            related_requirement_fields=related_requirement_fields,
            citation_count=citation_count,
            grounding_present=grounding_present,
            reason_code=precision_category.value,
            proposal_excerpt=excerpt,
        )
        with self._lock:
            self._precision_rejections.append(item)

    def begin(self, *, call_index: int, claim_count: int) -> _VerifierCallStart:
        return _VerifierCallStart(
            call_index=call_index,
            claim_count=claim_count,
            attempt_number=1,
            started_at=datetime.now(timezone.utc),
            started_counter=perf_counter(),
        )

    def success(
        self,
        started: _VerifierCallStart,
        *,
        provider_request_id: str | None,
    ) -> None:
        self._finish(
            started,
            success=True,
            failure_category=None,
            http_status=None,
            provider_request_id=provider_request_id,
        )

    def failure(
        self,
        started: _VerifierCallStart,
        *,
        failure_category: QwenFailureCategory,
        http_status: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        self._finish(
            started,
            success=False,
            failure_category=failure_category,
            http_status=http_status,
            provider_request_id=provider_request_id,
        )

    def _finish(
        self,
        started: _VerifierCallStart,
        *,
        success: bool,
        failure_category: QwenFailureCategory | None,
        http_status: int | None,
        provider_request_id: str | None,
    ) -> None:
        ended_at = datetime.now(timezone.utc)
        item = VerifierCallDiagnostic(
            call_index=started.call_index,
            claim_count=started.claim_count,
            attempt_number=started.attempt_number,
            started_at=started.started_at,
            ended_at=ended_at,
            latency_seconds=max(0.0, perf_counter() - started.started_counter),
            success=success,
            failure_category=failure_category,
            http_status=http_status,
            provider_request_id=provider_request_id,
        )
        with self._lock:
            self._calls.append(item)


def qwen_failure_category(error: LLMProviderError) -> QwenFailureCategory:
    if error.failure_kind in _CATEGORY_BY_KIND:
        return _CATEGORY_BY_KIND[error.failure_kind]
    if error.code == LLMErrorCode.LLM_INVALID_RESPONSE.value:
        return QwenFailureCategory.INVALID_RESPONSE
    return QwenFailureCategory.UNKNOWN_PROVIDER_ERROR
