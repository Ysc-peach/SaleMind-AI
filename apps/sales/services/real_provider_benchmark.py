"""Isolated Stage 8 knowledge preparation for real-provider evaluation."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

from openai import OpenAIError

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction

from apps.knowledge.embeddings import get_embedding_provider
from apps.knowledge.embeddings.base import EmbeddingProvider
from apps.knowledge.exceptions import KnowledgeDocumentError, KnowledgeDocumentErrorCode
from apps.knowledge.models import (
    EnterpriseGroundingFact,
    EnterpriseGroundingFactApprovalStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
)
from apps.knowledge.parsers.validation import validate_document_file
from apps.knowledge.services.grounding_fact_approval import approve_grounding_facts
from apps.knowledge.services.grounding_facts import extract_grounding_facts
from apps.knowledge.services.indexing import index_document
from apps.knowledge.services.search import search_knowledge
from apps.llm.base import LLMProvider
from apps.llm.base import LLMGeneration
from apps.llm.exceptions import LLMProviderError
from apps.sales.demo_fixtures import (
    DEMO_KNOWLEDGE,
    DemoGroundingExtractionProvider,
    DemoKnowledgeFixture,
)
from apps.sales.models import SolutionDraftProvenance
from apps.sales.services.solution_persistence import generate_and_persist_solution_draft
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services.solution_evaluation import BenchmarkEvaluationReport, evaluation_scope
from apps.sales.services.solution_prompt_v2 import AtomicSolutionProposalSetV2


_TITLE_PREFIX = "SalesMind Stage 8 real-provider benchmark"


def _evaluation_provider_metadata(provider: LLMProvider) -> tuple[dict, tuple[str, ...]]:
    """Read configuration only; never make a request or expose credentials."""

    config = getattr(provider, "_config", None)
    url = urlsplit(getattr(config, "base_url", ""))
    secrets = tuple(value for value in (
        getattr(config, "api_key", None),
        unquote(url.username or ""), unquote(url.password or ""),
        *(value for _, value in parse_qsl(url.query)),
    ) if isinstance(value, str) and value)

    def safe(value):
        if not isinstance(value, str) or any(secret in value for secret in secrets):
            return None
        return value

    return {
        "provider": safe(provider.provider_name),
        "model": safe(provider.model_name),
        "base_url": {"host": safe(url.hostname), "path": safe(url.path)},
    }, secrets


def evaluation_verifier_config_snapshot(
    provider: LLMProvider, *, max_concurrency: int,
) -> dict[str, object]:
    """Evaluation-only snapshot of actual wrapper configuration, without secrets."""

    metadata, _ = _evaluation_provider_metadata(provider)
    config = getattr(provider, "_config", None)
    # The wrapper currently sends only false, and only with capability support.
    explicit_off = (
        getattr(provider, "_supports_enable_thinking", False)
        and getattr(config, "thinking_enabled", None) is False
    )
    return {
        **metadata,
        "enable_thinking": False if explicit_off else None,
        "timeout": getattr(config, "timeout_seconds", None),
        "concurrency": max_concurrency,
    }


def evaluation_llm_provider_error(
    error: LLMProviderError, *, provider: LLMProvider,
) -> dict[str, object]:
    """Observe existing exceptions without reclassification or raw error logging.

    ``raise ... from None`` hides a traceback but may retain the SDK exception
    in ``__context__``. Never stringify it: that can include credentials or
    request content. Unknown/untrusted messages are omitted; recognized messages
    are reduced to fixed safe summaries, not copied from provider text.
    """

    metadata, secrets = _evaluation_provider_metadata(provider)
    candidate = error.__cause__ or error.__context__
    sdk_error = None
    for _ in range(4):
        if isinstance(candidate, OpenAIError):
            sdk_error = candidate
            break
        if candidate is None:
            break
        candidate = candidate.__cause__ or candidate.__context__
    body = getattr(sdk_error, "body", None)
    detail = body.get("error", body) if isinstance(body, Mapping) else None
    code = getattr(sdk_error, "code", None)
    if not isinstance(code, str) and isinstance(detail, Mapping):
        code = detail.get("code")
    if (
        not isinstance(code, str)
        or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", code) is None
        or any(secret in code for secret in secrets)
    ):
        code = None
    message = detail.get("message") if isinstance(detail, Mapping) else None
    safe_message = None
    if isinstance(message, str):
        normalized = message.casefold()
        for terms, summary in (
            (("inappropriate content", "content policy", "content-policy"),
             "Provider reported a content-policy rejection."),
            (("invalid api key", "incorrect api key"),
             "Provider reported an invalid API key."),
            (("permission denied", "access denied", "insufficient permissions"),
             "Provider reported an access-permission rejection."),
        ):
            if any(term in normalized for term in terms):
                safe_message = summary
                break
    return {
        "mapped_category": error.failure_kind.value if error.failure_kind else None,
        "exception_class": type(error).__name__,
        "sdk_exception_class": type(sdk_error).__name__ if sdk_error else None,
        "http_status": error.http_status,
        **metadata,
        "provider_error_code": code,
        "sanitized_provider_message": safe_message,
    }


class RealBenchmarkRetrievalError(Exception):
    """Safe evaluation failure without provider output or embedding vectors."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class RealBenchmarkKnowledgeOwnership:
    run_id: UUID
    document_ids: tuple[int, ...]
    fact_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RealBenchmarkRetrievalPreflight:
    provider_name: str
    model_name: str
    dimensions: int
    compatible_chunk_count: int
    retrieval_result_count: int
    retrieved_document_ids: tuple[int, ...]
    grounding_fact_count: int


@dataclass(frozen=True, slots=True)
class RealBenchmarkGateResult:
    preflight: RealBenchmarkRetrievalPreflight
    solution: object
    evaluation: dict | None = None


@dataclass(frozen=True, slots=True)
class EvaluationPassDiagnostic:
    """Safe pass boundary metadata, without provider response content."""

    pass_name: str
    started: bool
    provider_completed: bool
    latency_seconds: float
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    json_parse_succeeded: bool | None
    strict_parse_succeeded: bool | None
    proposal_count: int | None
    category: str | None
    citation_failure: EvaluationCitationFailure | None = None
    json_path: str | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationCitationFailure:
    """Only source identifiers observed at the parser's citation rejection site."""

    allowed_ids: tuple[str, ...]
    offending_ids: tuple[str, ...]
    subtype: str


class EvaluationPassFailure(Exception):
    """Evaluation-only failure; intentionally carries no raw provider output."""

    def __init__(self, diagnostic: EvaluationPassDiagnostic):
        self.diagnostic = diagnostic
        super().__init__(f"{diagnostic.pass_name}_{diagnostic.category}")


_PassValue = TypeVar("_PassValue")


@dataclass(frozen=True, slots=True)
class EvaluationPassResult:
    value: object
    diagnostic: EvaluationPassDiagnostic


def diagnose_generation_pass(
    *, pass_name: str, generate: Callable[[], LLMGeneration],
    parse: Callable[[str], _PassValue], allowed_source_labels: tuple[str, ...],
    max_proposals: int,
) -> EvaluationPassResult:
    """Consume formal rejection evidence; never inspect frames or guess validity."""
    if pass_name not in {"core", "implementation", "assurance"}:
        raise ValueError("Unknown evaluation pass.")
    started = time.perf_counter()
    try:
        generation = generate()
    except Exception:
        raise EvaluationPassFailure(EvaluationPassDiagnostic(
            pass_name, True, False, time.perf_counter() - started,
            None, None, None, None, None, None, "provider_error",
        )) from None
    elapsed = time.perf_counter() - started
    finish_reason = getattr(generation, "finish_reason", None)
    prompt_tokens = getattr(generation, "prompt_tokens", None)
    completion_tokens = getattr(generation, "completion_tokens", None)
    # Syntax and count observations only; the supplied formal parser decides.
    try:
        payload = json.loads(generation.content)
        json_ok = True
    except (TypeError, ValueError, RecursionError):
        payload, json_ok = None, False
    items = payload.get("proposals") if isinstance(payload, dict) else None
    count = len(items) if isinstance(items, list) else None
    try:
        value = parse(generation.content)
    except SolutionDraftError as error:
        failure = getattr(error, "contract_failure", None)
        category = failure.category if failure else "unknown_contract_failure"
        if category == "malformed_json" and finish_reason == "length":
            category = "truncation_or_length_finish"
        citation = (
            EvaluationCitationFailure(failure.allowed_ids, failure.offending_ids, failure.citation_subtype)
            if failure is not None and failure.citation_subtype else None
        )
        raise EvaluationPassFailure(EvaluationPassDiagnostic(
            pass_name, True, True, elapsed,
            finish_reason, prompt_tokens, completion_tokens,
            json_ok, False, count, category, citation,
            failure.json_path if failure else None,
            failure.expected if failure else None,
            failure.actual if failure else None,
        )) from None
    return EvaluationPassResult(value, EvaluationPassDiagnostic(
        pass_name, True, True, elapsed, finish_reason, prompt_tokens, completion_tokens,
        json_ok, True,
        len(value.proposals) if isinstance(value, AtomicSolutionProposalSetV2) else count,
        None,
    ))


def create_real_benchmark_reviewer(*, run_id: UUID):
    """Create a run-owned reviewer satisfying the formal approval boundary."""

    if not isinstance(run_id, UUID):
        raise RealBenchmarkRetrievalError("invalid_benchmark_input")
    return get_user_model().objects.create_user(
        username="stage8gate_" + run_id.hex,
        email=run_id.hex + "@benchmark.salesmind.invalid",
        role="admin",
        is_active=True,
        is_staff=True,
    )


def create_real_benchmark_knowledge(
    *,
    run_id: UUID,
    created_by,
    embedding_provider: EmbeddingProvider | None = None,
    fixtures: tuple[DemoKnowledgeFixture, ...] = DEMO_KNOWLEDGE,
) -> RealBenchmarkKnowledgeOwnership:
    """Create a run-owned index through formal parsing, chunking, and embedding."""

    if (
        not isinstance(run_id, UUID)
        or not isinstance(fixtures, tuple)
        or not fixtures
        or any(not isinstance(item, DemoKnowledgeFixture) for item in fixtures)
    ):
        raise RealBenchmarkRetrievalError("invalid_benchmark_input")
    provider = embedding_provider or get_embedding_provider()
    document_ids: list[int] = []
    fact_ids: list[int] = []
    ownership = RealBenchmarkKnowledgeOwnership(run_id, (), ())
    try:
        for fixture in fixtures:
            title = _benchmark_title(run_id, fixture.key)
            if KnowledgeDocument.objects.filter(title=title).exists():
                raise RealBenchmarkRetrievalError("benchmark_identity_conflict")
            content = fixture.content.encode("utf-8")
            source = ContentFile(content, name=fixture.filename)
            validated = validate_document_file(source, fixture.filename)
            source.seek(0)
            document = KnowledgeDocument.objects.create(
                title=title,
                document_type=fixture.document_type,
                source_file=source,
                original_filename=validated.original_filename,
                mime_type=validated.mime_type,
                file_size=len(validated.data),
                checksum_sha256=hashlib.sha256(validated.data).hexdigest(),
                created_by=created_by,
            )
            document_ids.append(document.pk)
            index_document(document.pk, provider=provider)
            proposed = extract_grounding_facts(
                document.pk,
                llm_provider=DemoGroundingExtractionProvider(fixture),
            )
            fact_ids.extend(fact.pk for fact in proposed)
            approve_grounding_facts(
                [fact.pk for fact in proposed], actor=created_by
            )
        return RealBenchmarkKnowledgeOwnership(
            run_id=run_id,
            document_ids=tuple(document_ids),
            fact_ids=tuple(fact_ids),
        )
    except Exception:
        ownership = RealBenchmarkKnowledgeOwnership(
            run_id=run_id,
            document_ids=tuple(document_ids),
            fact_ids=tuple(fact_ids),
        )
        clear_real_benchmark_knowledge(ownership)
        raise


def preflight_real_benchmark_retrieval(
    ownership: RealBenchmarkKnowledgeOwnership,
    *,
    query: str,
    embedding_provider: EmbeddingProvider | None = None,
) -> RealBenchmarkRetrievalPreflight:
    """Prove exact embedding-space compatibility before any LLM generation."""

    _validate_ownership(ownership)
    if not isinstance(query, str) or not query.strip():
        raise RealBenchmarkRetrievalError("invalid_benchmark_input")
    provider = embedding_provider or get_embedding_provider()
    documents = tuple(
        KnowledgeDocument.objects.filter(pk__in=ownership.document_ids).order_by("pk")
    )
    if {document.pk for document in documents} != set(ownership.document_ids):
        raise RealBenchmarkRetrievalError("benchmark_document_missing")
    expected_space = (
        provider.provider_name,
        provider.model_name,
        provider.dimensions,
    )
    if any(
        document.status != KnowledgeDocumentStatus.READY
        or (
            document.embedding_provider,
            document.embedding_model,
            document.embedding_dimensions,
        )
        != expected_space
        for document in documents
    ):
        raise RealBenchmarkRetrievalError("embedding_space_mismatch")
    compatible_chunk_count = KnowledgeChunk.objects.filter(
        document_id__in=ownership.document_ids
    ).count()
    if compatible_chunk_count <= 0:
        raise RealBenchmarkRetrievalError("compatible_chunks_missing")
    results = tuple(
        search_knowledge(
            query=query.strip(),
            top_k=compatible_chunk_count,
            provider=provider,
        )
    )
    if not results or any(
        result.document_id not in ownership.document_ids for result in results
    ):
        raise RealBenchmarkRetrievalError("benchmark_retrieval_isolation_failed")
    current_facts = EnterpriseGroundingFact.objects.filter(
        pk__in=ownership.fact_ids,
        source_document_id__in=ownership.document_ids,
        approval_status=EnterpriseGroundingFactApprovalStatus.APPROVED,
        is_stale=False,
    ).count()
    return RealBenchmarkRetrievalPreflight(
        provider_name=provider.provider_name,
        model_name=provider.model_name,
        dimensions=provider.dimensions,
        compatible_chunk_count=compatible_chunk_count,
        retrieval_result_count=len(results),
        retrieved_document_ids=tuple(sorted({item.document_id for item in results})),
        grounding_fact_count=current_facts,
    )


def run_real_provider_benchmark_gate(
    *,
    opportunity,
    analysis,
    created_by,
    ownership: RealBenchmarkKnowledgeOwnership,
    query: str,
    embedding_provider: EmbeddingProvider,
    llm_provider: LLMProvider | None,
    verifier_provider: LLMProvider | None,
    idempotency_key: UUID,
    evaluation_report: BenchmarkEvaluationReport | None = None,
) -> RealBenchmarkGateResult:
    """Run production persistence only after the isolated retrieval preflight."""

    report = evaluation_report if evaluation_report is not None else BenchmarkEvaluationReport()
    with evaluation_scope(report):
        try:
            preflight = preflight_real_benchmark_retrieval(
                ownership, query=query, embedding_provider=embedding_provider,
            )
            report.observe("embedding_provider", success=True)
            solution = generate_and_persist_solution_draft(
                opportunity, analysis, created_by=created_by,
                embedding_provider=embedding_provider, llm_provider=llm_provider,
                verifier_provider=verifier_provider, idempotency_key=idempotency_key,
                schema_version=2,
            )
        except Exception as error:
            # Original exception/behavior survives; only safe counters are attached.
            # Setup/retrieval failure is not automatically a provider outage.
            if isinstance(error, KnowledgeDocumentError) and error.code in {
                KnowledgeDocumentErrorCode.EMBEDDING_PROVIDER_ERROR.value,
                KnowledgeDocumentErrorCode.EMBEDDING_INVALID_RESPONSE.value,
            }:
                report.observe("embedding_provider", success=False, category=error.code)
            report.finish_failure()
            error.evaluation_report = report.to_dict()
            raise
        if report.to_dict()["persistence"]["status"] != "PASS":
            # Idempotency replay / externally supplied persistence adapter:
            # the return proves the record, not an unobserved provenance count.
            report.observe("persistence", success=True, provenance=None)
    return RealBenchmarkGateResult(preflight=preflight, solution=solution,
                                   evaluation=report.to_dict())


def clear_real_benchmark_knowledge(
    ownership: RealBenchmarkKnowledgeOwnership,
) -> None:
    """Delete only the exact run-owned documents after references are removed."""

    _validate_ownership(ownership, allow_empty=True)
    documents = tuple(
        KnowledgeDocument.objects.filter(pk__in=ownership.document_ids).order_by("pk")
    )
    if any(
        document.title != _benchmark_title(
            ownership.run_id,
            document.title.rsplit(" ", 1)[-1],
        )
        for document in documents
    ):
        raise RealBenchmarkRetrievalError("benchmark_ownership_conflict")
    if SolutionDraftProvenance.objects.filter(
        source_document_id__in=ownership.document_ids
    ).exists():
        raise RealBenchmarkRetrievalError("benchmark_knowledge_still_referenced")
    file_refs = tuple(
        (document.source_file.storage, document.source_file.name)
        for document in documents
        if document.source_file.name
    )
    with transaction.atomic():
        EnterpriseGroundingFact.objects.filter(
            pk__in=ownership.fact_ids,
            source_document_id__in=ownership.document_ids,
        ).delete()
        KnowledgeDocument.objects.filter(pk__in=ownership.document_ids).delete()
    for storage, name in file_refs:
        if storage.exists(name):
            storage.delete(name)


def _benchmark_title(run_id: UUID, fixture_key: str) -> str:
    return f"{_TITLE_PREFIX} {run_id} {fixture_key}"


def _validate_ownership(
    ownership: RealBenchmarkKnowledgeOwnership,
    *,
    allow_empty: bool = False,
) -> None:
    if (
        not isinstance(ownership, RealBenchmarkKnowledgeOwnership)
        or not isinstance(ownership.run_id, UUID)
        or not isinstance(ownership.document_ids, tuple)
        or (not ownership.document_ids and not allow_empty)
        or len(set(ownership.document_ids)) != len(ownership.document_ids)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in ownership.document_ids
        )
        or not isinstance(ownership.fact_ids, tuple)
        or len(set(ownership.fact_ids)) != len(ownership.fact_ids)
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in ownership.fact_ids
        )
    ):
        raise RealBenchmarkRetrievalError("invalid_benchmark_input")
