"""Isolated Stage 8 knowledge preparation for real-provider evaluation."""

from __future__ import annotations

import hashlib
import ast
import inspect
import json
import re
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction

from apps.knowledge.embeddings import get_embedding_provider
from apps.knowledge.embeddings.base import EmbeddingProvider
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
from apps.sales.demo_fixtures import (
    DEMO_KNOWLEDGE,
    DemoGroundingExtractionProvider,
    DemoKnowledgeFixture,
)
from apps.sales.models import SolutionDraftProvenance
from apps.sales.services.solution_persistence import generate_and_persist_solution_draft
from apps.sales.services.solution_errors import SolutionDraftError
from apps.sales.services import solution_prompt_v2
from apps.sales.services.solution_prompt_v2 import (
    AtomicSolutionProposalSetV2,
    ASSURANCE_SECTION_PROPOSAL_LIMITS,
    IMPLEMENTATION_SECTION_PROPOSAL_LIMITS,
    SolutionV2ContainerKind,
    SolutionV2PlacementField,
    SolutionV2Section,
    SolutionV2StructureRelationType,
    SolutionV2OutputDiagnosticCategory,
    assurance_budget_failure_category,
    diagnose_solution_v2_output,
    implementation_budget_failure_category,
)


_TITLE_PREFIX = "SalesMind Stage 8 real-provider benchmark"


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
    *,
    pass_name: str,
    generate: Callable[[], LLMGeneration],
    parse: Callable[[str], _PassValue],
    allowed_source_labels: tuple[str, ...],
    max_proposals: int,
) -> EvaluationPassResult:
    """Run one real pass once, then attribute rejection without persisting text."""

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
    try:
        payload = json.loads(generation.content)
        json_ok = True
    except (TypeError, ValueError, RecursionError):
        payload = None
        json_ok = False
    items = payload.get("proposals") if isinstance(payload, dict) else None
    count = len(items) if isinstance(items, list) else None
    citation_observer = _CitationRejectionObserver()
    core_observer = _CoreSemanticRejectionObserver() if pass_name == "core" else None
    previous_profile = sys.getprofile()
    def observe(frame, event, arg):
        citation_observer.observe(frame, event, arg)
        if core_observer is not None:
            core_observer.observe(frame, event, arg)

    sys.setprofile(observe)
    try:
        try:
            value = parse(generation.content)
        finally:
            sys.setprofile(previous_profile)
    except SolutionDraftError:
        citation_failure = citation_observer.failure
        core_failure = core_observer.failure if core_observer is not None else None
        semantic_core = isinstance(payload, dict) and bool(
            {"ir_version", "architecture", "proposed_solution", "deployment_and_integration"}
            & payload.keys()
        )
        if citation_failure is not None:
            category = "invalid_citation"
        elif core_failure is not None:
            category = core_failure.category
        elif pass_name == "core" and semantic_core:
            category = "other_contract_failure"
        else:
            category = _pass_failure_category(
                pass_name, generation.content, allowed_source_labels,
                max_proposals, payload, count, finish_reason,
            )
        if not json_ok:
            category = "truncation_or_length_finish" if finish_reason == "length" else "malformed_json"
        raise EvaluationPassFailure(EvaluationPassDiagnostic(
            pass_name, True, True, elapsed,
            finish_reason, prompt_tokens, completion_tokens,
            json_ok, False, count, category, citation_failure,
            core_failure.json_path if core_failure else ("$" if not json_ok else None),
            core_failure.expected if core_failure else None,
            core_failure.actual if core_failure else None,
        )) from None
    diagnostic = EvaluationPassDiagnostic(
        pass_name, True, True, elapsed,
        finish_reason, prompt_tokens, completion_tokens,
        json_ok, True,
        len(value.proposals) if isinstance(value, AtomicSolutionProposalSetV2) else count,
        None,
    )
    return EvaluationPassResult(value, diagnostic)


@dataclass(frozen=True, slots=True)
class _SafeCoreRejection:
    category: str
    json_path: str
    expected: str
    actual: str


_SAFE_JSON_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def _semantic_ir_paths(payload: object) -> dict[int, str]:
    """Locate parser-owned values; never copy claim text into diagnostics."""

    paths: dict[int, str] = {}

    def visit(value: object, path: str) -> None:
        paths.setdefault(id(value), path)
        if isinstance(value, dict):
            for key, child in value.items():
                safe_key = key if isinstance(key, str) and _SAFE_JSON_KEY.fullmatch(key) else "<key>"
                visit(child, f"{path}.{safe_key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload, "$")
    return paths


def _convert_frame(frame):
    from apps.sales.services import solution_semantic_ir_v2

    while frame is not None:
        if frame.f_code is solution_semantic_ir_v2._convert.__code__:
            return frame
        frame = frame.f_back
    return None


@lru_cache(maxsize=1)
def _core_cardinality_rejection_lines() -> frozenset[int]:
    """Anchor attribution to actual validator branches, not a mirror validator."""

    lines, first = inspect.getsourcelines(solution_prompt_v2.validate_solution_v2_structure_relations)
    tree = ast.parse(textwrap.dedent("".join(lines)))
    result = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        condition = ast.unparse(node.test)
        if "architecture_components" not in condition and "component_field_counts" not in condition:
            continue
        for child in node.body:
            if (isinstance(child, ast.Expr) and isinstance(child.value, ast.Call)
                and isinstance(child.value.func, ast.Name) and child.value.func.id == "_invalid"):
                result.add(first + child.lineno - 1)
    return frozenset(result)


@lru_cache(maxsize=1)
def _requirement_rejection_lines() -> frozenset[int]:
    lines, first = inspect.getsourcelines(solution_prompt_v2.parse_atomic_solution_v2_proposals)
    start = next(i for i, line in enumerate(lines) if "related_fields_data =" in line)
    end = next(i for i, line in enumerate(lines[start:], start) if "proposals.append(" in line)
    return frozenset(range(first + start, first + end))


class _CoreSemanticRejectionObserver:
    """Observe the production parser's _invalid call site, without re-parsing."""

    def __init__(self):
        self.failure: _SafeCoreRejection | None = None
        self.claim_paths: list[str] = []

    def observe(self, frame, event, _arg):
        if event != "call":
            return
        if frame.f_code.co_name == "add":
            convert = _convert_frame(frame)
            if convert is not None and "value" in frame.f_locals:
                paths = _semantic_ir_paths(convert.f_locals["payload"])
                self.claim_paths.append(paths.get(id(frame.f_locals["value"]), "$"))
            return
        if frame.f_code is not solution_prompt_v2._invalid.__code__:
            return
        caller = frame.f_back
        if caller is None or self.failure is not None:
            return
        convert = _convert_frame(caller)
        paths = _semantic_ir_paths(convert.f_locals["payload"]) if convert is not None else {}
        from apps.sales.services import solution_semantic_ir_v2 as ir

        code = caller.f_code
        values = caller.f_locals
        path = lambda value: paths.get(id(value), "$")
        if code is ir._object.__code__:
            value = values["value"]
            location = path(value)
            if not isinstance(value, dict):
                self.failure = _SafeCoreRejection("wrong_type", location, "object", type(value).__name__)
                return
            missing = set(values["required"]) - value.keys()
            if missing:
                key = sorted(missing)[0]
                self.failure = _SafeCoreRejection("missing_required_key", f"{location}.{key}", "required key present", "missing")
                return
            unknown = value.keys() - (set(values["required"]) | set(values["optional"]))
            if unknown:
                key = sorted(unknown)[0]
                safe = key if isinstance(key, str) and _SAFE_JSON_KEY.fullmatch(key) else "<key>"
                self.failure = _SafeCoreRejection("unknown_key", f"{location}.{safe}", "allowed key", "unknown key")
                return
        if code is ir._array.__code__:
            value = values["value"]
            self.failure = _SafeCoreRejection("wrong_type", path(value), "array", type(value).__name__)
            return
        if code is ir._bounded_array.__code__:
            value = values["items"]
            self.failure = _SafeCoreRejection(
                "local_cardinality", path(value),
                f"at most {values['maximum']} items", f"{len(value)} items",
            )
            return
        if code is ir._ref.__code__:
            parent = caller.f_back
            location = "$"
            if parent is not None:
                container = parent.f_locals.get("component") or parent.f_locals.get("group")
                if isinstance(container, dict) and container.get("ref") is values["value"]:
                    location = path(container) + ".ref"
                elif parent.f_code is ir._edge.__code__:
                    edge = parent.f_locals["value"]
                    direction = "from" if edge.get("from") is values["value"] else "to"
                    location = path(edge) + f".{direction}"
            self.failure = _SafeCoreRejection("invalid_local_ref", location, "lowercase local ref", type(values["value"]).__name__)
            return
        if code is ir._edge.__code__:
            edge = values["value"]
            direction = "from" if values["source"] not in values["sources"] else "to"
            location = path(edge) + f".{direction}"
            prefix = path(edge)
            category = (
                "dangling_request_flow" if ".request_flows[" in prefix else
                "dangling_data_flow" if ".data_flows[" in prefix else
                "dangling_dependency" if ".dependencies[" in prefix else
                "invalid_local_ref"
            )
            self.failure = _SafeCoreRejection(category, location, "existing architecture component ref", "unknown local ref")
            return
        if code.co_name == "add" and convert is not None and "proposals" in values:
            self.failure = _SafeCoreRejection(
                "proposal_budget", path(values["item"]),
                f"at most {values['max_proposals']} proposal claims",
                f"{len(values['proposals'])} claims",
            )
            return
        if code is solution_prompt_v2.parse_atomic_solution_v2_proposals.__code__:
            index = len(values.get("proposals", ()))
            claim_path = self.claim_paths[index] if index < len(self.claim_paths) else "$"
            if caller.f_lineno == _parser_citation_rejection_line():
                self.failure = _SafeCoreRejection(
                    "invalid_citation", claim_path + ".citations",
                    "non-empty unique allowed citation IDs", "rejected citations",
                )
                return
            if caller.f_lineno in _requirement_rejection_lines():
                self.failure = _SafeCoreRejection(
                    "invalid_requirement_link", claim_path + ".related_requirement_fields",
                    "unique RequirementDimension values", "rejected requirement linkage",
                )
                return
        if (code is solution_prompt_v2.validate_solution_v2_structure_relations.__code__
            and caller.f_lineno in _core_cardinality_rejection_lines()):
            components = convert.f_locals["payload"]["architecture"]["components"] if convert is not None else []
            counts = values.get("component_field_counts", {})
            for index, component in enumerate(components):
                fields = counts.get(component.get("ref"), {})
                for field, member in (("identity", solution_prompt_v2.SolutionV2PlacementField.IDENTITY),
                                      ("responsibilities", solution_prompt_v2.SolutionV2PlacementField.RESPONSIBILITIES),
                                      ("rationale", solution_prompt_v2.SolutionV2PlacementField.RATIONALE),
                                      ("interfaces", solution_prompt_v2.SolutionV2PlacementField.INTERFACES)):
                    if fields.get(member, 0) < 1 or (field == "identity" and fields.get(member, 0) != 1):
                        self.failure = _SafeCoreRejection("component_cardinality", f"$.architecture.components[{index}].{field}", "required component claim", "missing or duplicate")
                        return
            self.failure = _SafeCoreRejection("component_cardinality", "$.architecture.components", "at most 4 components", "component count exceeded")
            return
        if code is solution_prompt_v2.parse_atomic_solution_v2_proposals.__code__ and convert is None:
            rejected_payload = values.get("payload")
            if isinstance(rejected_payload, dict) and (
                {"architecture", "proposed_solution", "deployment_and_integration"}
                & rejected_payload.keys()
            ):
                self.failure = _SafeCoreRejection("missing_required_key", "$.ir_version", "required key present", "missing")
                return
        if code is solution_prompt_v2._parse_generation_output.__code__:
            self.failure = _SafeCoreRejection("malformed_json", "$", "valid JSON", "malformed")
            return
        self.failure = _SafeCoreRejection("other_contract_failure", "$", "valid Core Semantic IR", "rejected at parser branch")


@lru_cache(maxsize=1)
def _parser_citation_rejection_line() -> int:
    """Locate the real parser branch, failing closed if its shape changes."""

    lines, first_line = inspect.getsourcelines(
        solution_prompt_v2.parse_atomic_solution_v2_proposals
    )
    source = textwrap.dedent("".join(lines))
    tree = ast.parse(source)
    candidates = [
        first_line + node.body[0].lineno - 1
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(child, ast.Name) and child.id == "citations"
            for child in ast.walk(node.test)
        )
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Call)
        and isinstance(node.body[0].value.func, ast.Name)
        and node.body[0].value.func.id == "_invalid"
    ]
    if len(candidates) != 1:
        raise RuntimeError("Citation parser branch could not be identified.")
    return candidates[0]


class _CitationRejectionObserver:
    """Observe _invalid at the citation branch; never decide parser validity."""

    def __init__(self):
        self.failure: EvaluationCitationFailure | None = None

    def observe(self, frame, event, _arg):
        if event != "call" or frame.f_code is not solution_prompt_v2._invalid.__code__:
            return
        caller = frame.f_back
        if (
            caller is None
            or caller.f_code is not solution_prompt_v2.parse_atomic_solution_v2_proposals.__code__
            or caller.f_lineno != _parser_citation_rejection_line()
        ):
            return
        self.failure = _describe_rejected_citations(
            caller.f_locals["citations"],
            caller.f_locals["allowed_source_labels"],
        )


_SAFE_SOURCE_ID = re.compile(r"S[1-9][0-9]*\Z")


def _describe_rejected_citations(
    citations: object, allowed_ids: tuple[str, ...],
) -> EvaluationCitationFailure:
    """Classify an already-rejected value; never re-evaluate acceptance."""

    if not isinstance(citations, list):
        subtype = "wrong_type"
        offending = (f"<{type(citations).__name__}>",)
    elif not citations:
        subtype = "empty"
        offending = ()
    elif len(set(citations)) != len(citations):
        subtype = "duplicate"
        seen: set[object] = set()
        duplicates = []
        for value in citations:
            if value in seen:
                duplicates.append(value)
            seen.add(value)
        offending = tuple(_safe_source_id(value) for value in duplicates)
    elif any(not isinstance(value, str) for value in citations):
        subtype = "wrong_type"
        offending = tuple(
            f"<{type(value).__name__}>"
            for value in citations if not isinstance(value, str)
        )
    elif any(_SAFE_SOURCE_ID.fullmatch(value) is None for value in citations):
        subtype = "malformed"
        offending = tuple(
            _safe_source_id(value)
            for value in citations if _SAFE_SOURCE_ID.fullmatch(value) is None
        )
    else:
        subtype = "not_in_allowlist"
        offending = tuple(value for value in citations if value not in allowed_ids)
    return EvaluationCitationFailure(allowed_ids, offending, subtype)


def _safe_source_id(value: object) -> str:
    return value if isinstance(value, str) and _SAFE_SOURCE_ID.fullmatch(value) else "<redacted>"


def _pass_failure_category(
    pass_name: str,
    content: str,
    allowed_source_labels: tuple[str, ...],
    max_proposals: int,
    payload: object,
    count: int | None,
    finish_reason: str | None,
) -> str:
    if not isinstance(payload, dict):
        return (
            "truncation_or_length_finish"
            if finish_reason == "length" else "malformed_json"
        )
    if "proposals" not in payload:
        return "missing_required_key"
    if count is not None and count > max_proposals:
        return (
            "proposal_count_exceeded" if pass_name == "core"
            else f"{pass_name}_total_budget_exceeded"
        )
    items = payload.get("proposals")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if not {"placement", "text", "citations"} <= item.keys():
                return "missing_required_key"
            placement = item.get("placement")
            if not isinstance(placement, dict):
                continue
            if not {"section", "container_kind", "container_key", "field"} <= placement.keys():
                return "missing_required_key"
            enum_fields = (
                ("section", SolutionV2Section),
                ("container_kind", SolutionV2ContainerKind),
                ("field", SolutionV2PlacementField),
            )
            if any(
                isinstance(placement[name], str)
                and placement[name] not in enum_type._value2member_map_
                for name, enum_type in enum_fields
            ):
                return "invalid_enum"
    relations = payload.get("structure_relations")
    if isinstance(relations, list):
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            if "relation_type" not in relation:
                return "missing_required_key"
            value = relation["relation_type"]
            if (
                isinstance(value, str)
                and value not in SolutionV2StructureRelationType._value2member_map_
            ):
                return "invalid_enum"
    if isinstance(items, list) and pass_name in {"implementation", "assurance"}:
        section_counts: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            placement = item.get("placement")
            if not isinstance(placement, dict):
                continue
            section = placement.get("section")
            if isinstance(section, str):
                section_counts[section] = section_counts.get(section, 0) + 1
        limits = (
            IMPLEMENTATION_SECTION_PROPOSAL_LIMITS
            if pass_name == "implementation"
            else ASSURANCE_SECTION_PROPOSAL_LIMITS
        )
        if set(section_counts) <= set(limits):
            classify = (
                implementation_budget_failure_category
                if pass_name == "implementation"
                else assurance_budget_failure_category
            )
            budget_category = classify(section_counts, max_proposals=max_proposals)
            if budget_category is not None:
                return budget_category.value
    category = diagnose_solution_v2_output(
        content, allowed_source_labels=allowed_source_labels,
    )
    if category is SolutionV2OutputDiagnosticCategory.INVALID_CITATION:
        # Citation attribution is only valid when the actual parser branch was
        # observed. A mirror scan must not invent a citation failure reason.
        return "unknown_contract_failure"
    return category.value if category is not None else "unknown_contract_failure"


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
) -> RealBenchmarkGateResult:
    """Run production persistence only after the isolated retrieval preflight."""

    preflight = preflight_real_benchmark_retrieval(
        ownership,
        query=query,
        embedding_provider=embedding_provider,
    )
    solution = generate_and_persist_solution_draft(
        opportunity,
        analysis,
        created_by=created_by,
        embedding_provider=embedding_provider,
        llm_provider=llm_provider,
        verifier_provider=verifier_provider,
        idempotency_key=idempotency_key,
        schema_version=2,
    )
    return RealBenchmarkGateResult(preflight=preflight, solution=solution)


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
