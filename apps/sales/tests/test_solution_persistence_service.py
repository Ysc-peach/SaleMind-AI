"""Application-service tests for atomic Solution Draft persistence."""

import hashlib
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from django.db.utils import OperationalError
from django.utils import timezone

from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeChunk, KnowledgeDocument
from apps.sales.models import Customer, Opportunity, OpportunityRequirementAnalysis
from apps.sales.services.requirement_analysis_history import analysis_record_to_domain
from apps.sales.services.solution_admission import build_solution_admission
from apps.sales.services.solution_draft import (
    GroundedSolutionDraftResult,
    SolutionGenerationStatus,
)
from apps.sales.services.solution_readiness import SolutionReadiness, SolutionReadinessStatus
from apps.sales.services.solution_retrieval import SolutionSource
from apps.sales.services.solution_schema import assemble_solution_draft, build_solution_unresolved_items
from apps.sales.tests.solution_fakes import analysis_payload


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def persistence_context(make_user):
    owner = make_user()
    customer = Customer.objects.create(name="Persistence customer", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="Persistence opportunity",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
        raw_requirement="客户需要私有化部署。",
    )

    def create_analysis(*, for_opportunity=opportunity, summary="客户需要私有化部署。"):
        payload = analysis_payload()
        return OpportunityRequirementAnalysis.objects.create(
            opportunity=for_opportunity,
            created_by=owner,
            summary=summary,
            requirements=payload["requirements"],
            conflicts=payload["conflicts"],
            clarifying_questions=payload["clarifying_questions"],
            source_raw_requirement=for_opportunity.raw_requirement,
            source_context={"opportunity": {"project_name": for_opportunity.project_name}},
            analysis_version="v1",
            llm_provider="fake",
            llm_model="fake-model",
        )

    analysis = create_analysis()
    return owner, customer, opportunity, analysis, create_analysis


@pytest.fixture
def generated_artifact(persistence_context):
    owner, _, _, analysis, _ = persistence_context
    run_id = uuid4()
    source_content = "SalesMind 当前版本支持企业私有化部署。"
    document = KnowledgeDocument.objects.create(
        title="Private deployment",
        document_type="technical",
        source_file="knowledge/documents/private-deployment.md",
        original_filename="private-deployment.md",
        mime_type="text/markdown",
        file_size=len(source_content.encode()),
        checksum_sha256="a" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=run_id,
        created_by=owner,
    )
    source = SolutionSource(
        chunk_id=811,
        document_id=document.pk,
        document_title=document.title,
        document_type=document.document_type,
        original_filename=document.original_filename,
        content=source_content,
        page_number=None,
        section_title="部署能力",
        source_reference="Private deployment / 部署能力",
        similarity=0.99,
        label="S1",
    )
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement=source_content,
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=source.chunk_id,
        source_excerpt=source_content,
        source_index_run_id=run_id,
        source_content_hash=hashlib.sha256(source_content.encode()).hexdigest(),
        approval_status="approved",
        approved_by=owner,
        approved_at=timezone.now(),
    )
    KnowledgeChunk.objects.create(
        pk=source.chunk_id,
        document=document,
        chunk_index=0,
        content=source_content,
        embedding=[0.0] * 1024,
        section_title=source.section_title,
        source_reference=source.source_reference,
        char_count=len(source_content),
    )
    typed = analysis_record_to_domain(analysis)
    admission = build_solution_admission(typed, (source,))
    draft = assemble_solution_draft(admission.claims, typed)
    result = GroundedSolutionDraftResult(
        analysis_id=analysis.pk,
        readiness=SolutionReadiness(SolutionReadinessStatus.READY, (), (), ()),
        generation_status=SolutionGenerationStatus.GENERATED,
        draft=draft,
        sources=(source,),
        unresolved_items=build_solution_unresolved_items(typed),
        admission=admission,
    )
    return result, fact, document


def _patch_generation(monkeypatch, result, *, assertion=None):
    from apps.sales.services import solution_persistence

    def generate(analysis, **kwargs):
        if assertion is not None:
            assertion(analysis, kwargs)
        return replace(result, analysis_id=analysis.pk)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)


def test_successful_generation_persists_one_version_and_exact_analysis(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, _, opportunity, analysis, _ = persistence_context
    result, fact, _ = generated_artifact

    def outside_transaction(actual_analysis, kwargs):
        assert actual_analysis.pk == analysis.pk
        assert connection.in_atomic_block is False
        assert connection.get_autocommit() is True

    _patch_generation(monkeypatch, result, assertion=outside_transaction)

    from apps.sales.services.solution_evaluation import BenchmarkEvaluationReport, evaluation_scope
    measured = BenchmarkEvaluationReport()
    with evaluation_scope(measured):
        record = generate_and_persist_solution_draft(
            opportunity,
            analysis,
            created_by=owner,
        )
    assert measured.to_dict()["persistence"] == {
        "status": "PASS", "solution_persisted": True, "provenance_persisted": True,
    }

    assert SolutionDraftRecord.objects.count() == 1
    assert record.opportunity_id == opportunity.pk
    assert record.requirement_analysis_id == analysis.pk
    assert record.version == 1
    assert record.review_status == "draft"
    assert record.draft_payload["title"] == result.draft.title
    entries = tuple(SolutionDraftProvenance.objects.filter(solution_draft=record))
    assert entries
    assert {entry.enterprise_grounding_fact_id for entry in entries} == {fact.pk}
    deployment = next(
        section for section in result.draft.solution_sections if section.key == "deployment"
    )
    enterprise_index = next(
        index for index, statement in enumerate(deployment.statements) if statement.citations
    )
    assert {entry.statement_path for entry in entries} == {
        f"solution_sections.deployment.statements[{enterprise_index}]",
    }
    assert {entry.citation_label for entry in entries} == {"S1"}


def test_generating_from_explicit_historical_analysis_never_substitutes_latest(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, _, opportunity, historical, create_analysis = persistence_context
    create_analysis(summary="A newer analysis")
    result, _, _ = generated_artifact
    _patch_generation(monkeypatch, result)

    record = generate_and_persist_solution_draft(
        opportunity,
        historical,
        created_by=owner,
    )

    assert record.requirement_analysis_id == historical.pk
    assert record.is_stale is True
    assert record.stale_reasons == ["newer_requirement_analysis"]


def test_analysis_from_another_opportunity_is_rejected_before_generation(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftRecord
    from apps.sales.services.solution_persistence import (
        SolutionPersistenceError,
        generate_and_persist_solution_draft,
    )

    owner, customer, opportunity, _, create_analysis = persistence_context
    other = Opportunity.objects.create(
        project_name="Other",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
    )
    other_analysis = create_analysis(for_opportunity=other)
    called = False

    def should_not_run(*args, **kwargs):
        nonlocal called
        called = True

    _patch_generation(monkeypatch, generated_artifact[0], assertion=should_not_run)

    with pytest.raises(SolutionPersistenceError):
        generate_and_persist_solution_draft(opportunity, other_analysis, created_by=owner)

    assert called is False
    assert SolutionDraftRecord.objects.count() == 0


def test_successful_generations_append_per_opportunity_versions(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, _, opportunity, analysis, _ = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])

    first = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    second = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)

    assert (first.version, second.version) == (1, 2)


def test_generation_idempotency_replay_returns_existing_without_provider_call(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    result = generated_artifact[0]
    calls = 0

    def generate(actual_analysis, **kwargs):
        nonlocal calls
        calls += 1
        return replace(result, analysis_id=actual_analysis.pk)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)
    key = uuid4()

    first = solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, idempotency_key=key
    )
    replay = solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, idempotency_key=key
    )

    assert replay.pk == first.pk
    assert replay.generation_idempotency_key == key
    assert calls == 1
    assert SolutionDraftRecord.objects.count() == 1


def test_generation_idempotency_key_rejects_mismatched_inputs_before_provider(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, create_analysis = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])
    key = uuid4()
    solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, idempotency_key=key
    )
    other_analysis = create_analysis(summary="Different explicit analysis")
    called = False

    def should_not_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        solution_persistence, "generate_grounded_solution_draft", should_not_run
    )

    with pytest.raises(solution_persistence.SolutionPersistenceError):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, other_analysis, created_by=owner, idempotency_key=key
        )

    assert called is False


def test_different_generation_idempotency_keys_create_independent_versions(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])

    first = solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, idempotency_key=uuid4()
    )
    second = solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner, idempotency_key=uuid4()
    )

    assert (first.version, second.version) == (1, 2)


def test_concurrent_same_idempotency_key_calls_provider_once_and_persists_once(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    result = generated_artifact[0]
    start = Barrier(2)
    counter_lock = Lock()
    calls = 0
    key = uuid4()

    def generate(actual_analysis, **kwargs):
        nonlocal calls
        with counter_lock:
            calls += 1
        sleep(0.2)
        return replace(result, analysis_id=actual_analysis.pk)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)

    def persist():
        close_old_connections()
        try:
            local_opportunity = Opportunity.objects.get(pk=opportunity.pk)
            local_analysis = OpportunityRequirementAnalysis.objects.get(pk=analysis.pk)
            local_owner = type(owner).objects.get(pk=owner.pk)
            start.wait(timeout=10)
            return solution_persistence.generate_and_persist_solution_draft(
                local_opportunity,
                local_analysis,
                created_by=local_owner,
                idempotency_key=key,
            ).pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = [future.result() for future in [executor.submit(persist) for _ in range(2)]]

    assert ids[0] == ids[1]
    assert calls == 1
    assert SolutionDraftRecord.objects.count() == 1


def test_different_opportunities_have_independent_version_sequences(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import generate_and_persist_solution_draft

    owner, customer, opportunity, analysis, create_analysis = persistence_context
    other = Opportunity.objects.create(
        project_name="Other",
        customer=customer,
        sales_owner=owner,
        created_by=owner,
    )
    other_analysis = create_analysis(for_opportunity=other)
    first_result = generated_artifact[0]
    _patch_generation(monkeypatch, first_result)

    first = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    other_first = generate_and_persist_solution_draft(other, other_analysis, created_by=owner)

    assert first.version == 1
    assert other_first.version == 1


def test_concurrent_generation_allocates_unique_monotonic_versions(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    result = generated_artifact[0]
    barrier = Barrier(2)

    def generate(actual_analysis, **kwargs):
        barrier.wait(timeout=10)
        return replace(result, analysis_id=actual_analysis.pk)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)

    def persist():
        close_old_connections()
        try:
            return solution_persistence.generate_and_persist_solution_draft(
                Opportunity.objects.get(pk=opportunity.pk),
                OpportunityRequirementAnalysis.objects.get(pk=analysis.pk),
                created_by=type(owner).objects.get(pk=owner.pk),
            ).version
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(persist) for _ in range(2)]
        versions = sorted(future.result() for future in futures)

    assert versions == [1, 2]
    assert list(
        SolutionDraftRecord.objects.filter(opportunity=opportunity)
        .order_by("version")
        .values_list("version", flat=True)
    ) == [1, 2]


def test_insert_time_provenance_change_creates_no_records(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    result, fact, _ = generated_artifact

    def generate(actual_analysis, **kwargs):
        fact.is_stale = True
        fact.stale_at = timezone.now()
        fact.save(update_fields=["is_stale", "stale_at"])
        return result

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", generate)

    with pytest.raises(solution_persistence.SolutionPersistenceError):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner
        )

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0


def test_provenance_insert_failure_rolls_back_solution_record(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])

    def fail(*args, **kwargs):
        raise RuntimeError("controlled persistence failure")

    monkeypatch.setattr(SolutionDraftProvenance.objects, "bulk_create", fail)

    from apps.sales.services.solution_evaluation import BenchmarkEvaluationReport, evaluation_scope
    measured = BenchmarkEvaluationReport()
    with evaluation_scope(measured), pytest.raises(RuntimeError, match="controlled persistence failure"):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner
        )

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0
    measured.finish_failure()
    assert measured.to_dict()["persistence"] == {
        "status": "FAIL", "solution_persisted": False, "provenance_persisted": False,
    }


def test_generation_or_verifier_provider_failure_creates_no_records(
    monkeypatch,
    persistence_context,
):
    from apps.llm.exceptions import LLMErrorCode, LLMProviderError
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context

    def fail(*args, **kwargs):
        raise LLMProviderError(LLMErrorCode.LLM_PROVIDER_ERROR)

    monkeypatch.setattr(solution_persistence, "generate_grounded_solution_draft", fail)

    with pytest.raises(LLMProviderError):
        solution_persistence.generate_and_persist_solution_draft(
            opportunity, analysis, created_by=owner
        )

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0


def test_draft_without_enterprise_citations_persists_with_zero_provenance_rows(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services import solution_persistence

    owner, _, opportunity, analysis, _ = persistence_context
    original, fact, _ = generated_artifact
    fact.delete()
    typed = analysis_record_to_domain(analysis)
    admission = build_solution_admission(typed, original.sources)
    result = replace(
        original,
        admission=admission,
        draft=assemble_solution_draft(admission.claims, typed),
    )
    _patch_generation(monkeypatch, result)

    record = solution_persistence.generate_and_persist_solution_draft(
        opportunity, analysis, created_by=owner
    )

    assert record.pk is not None
    assert SolutionDraftProvenance.objects.filter(solution_draft=record).count() == 0


def test_current_fact_and_snapshot_keep_solution_fresh(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import (
        evaluate_solution_draft_stale_reasons,
        generate_and_persist_solution_draft,
        refresh_solution_draft_staleness,
    )

    owner, _, opportunity, analysis, _ = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])
    record = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)

    assert evaluate_solution_draft_stale_reasons(record) == ()
    assert refresh_solution_draft_staleness(record).is_stale is False
    assert record.review_status == "draft"


def test_stale_fact_marks_solution_stale_without_changing_review_status(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import (
        generate_and_persist_solution_draft,
        refresh_solution_draft_staleness,
    )

    owner, _, opportunity, analysis, _ = persistence_context
    result, fact, _ = generated_artifact
    _patch_generation(monkeypatch, result)
    record = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    fact.is_stale = True
    fact.stale_at = timezone.now()
    fact.save(update_fields=["is_stale", "stale_at"])

    refresh_solution_draft_staleness(record)

    assert record.is_stale is True
    assert record.stale_reasons == ["grounding_fact_invalid"]
    assert record.review_status == "draft"


def test_invalid_current_provenance_marks_solution_stale_and_keeps_snapshot(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.models import SolutionDraftProvenance
    from apps.sales.services.solution_persistence import (
        generate_and_persist_solution_draft,
        refresh_solution_draft_staleness,
    )

    owner, _, opportunity, analysis, _ = persistence_context
    result, fact, document = generated_artifact
    _patch_generation(monkeypatch, result)
    record = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    snapshot = SolutionDraftProvenance.objects.get(solution_draft=record)
    old_excerpt = snapshot.source_excerpt
    KnowledgeChunk.objects.filter(pk=fact.source_chunk_id).delete()

    refresh_solution_draft_staleness(record)

    snapshot.refresh_from_db()
    assert record.is_stale is True
    assert record.stale_reasons == ["grounding_provenance_invalid"]
    assert snapshot.source_document_id == document.pk
    assert snapshot.source_chunk_id == fact.source_chunk_id
    assert snapshot.source_excerpt == old_excerpt


def test_index_run_or_content_hash_drift_marks_provenance_invalid(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import (
        generate_and_persist_solution_draft,
        refresh_solution_draft_staleness,
    )

    owner, _, opportunity, analysis, _ = persistence_context
    result, fact, document = generated_artifact
    _patch_generation(monkeypatch, result)
    record = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    KnowledgeChunk.objects.filter(pk=fact.source_chunk_id).update(content="changed")
    document.last_index_run_id = uuid4()
    document.save(update_fields=["last_index_run_id"])

    refresh_solution_draft_staleness(record)

    assert record.stale_reasons == ["grounding_provenance_invalid"]


def test_newer_analysis_marks_existing_solution_stale(
    monkeypatch,
    persistence_context,
    generated_artifact,
):
    from apps.sales.services.solution_persistence import (
        generate_and_persist_solution_draft,
        refresh_solution_draft_staleness,
    )

    owner, _, opportunity, analysis, create_analysis = persistence_context
    _patch_generation(monkeypatch, generated_artifact[0])
    record = generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)
    create_analysis(summary="newer")

    refresh_solution_draft_staleness(record)

    assert record.is_stale is True
    assert record.stale_reasons == ["newer_requirement_analysis"]


@pytest.mark.parametrize(
    "status",
    [
        SolutionGenerationStatus.BLOCKED_BY_READINESS,
        SolutionGenerationStatus.INSUFFICIENT_EVIDENCE,
    ],
)
def test_unsuccessful_generation_creates_no_persistence(
    monkeypatch,
    persistence_context,
    generated_artifact,
    status,
):
    from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
    from apps.sales.services.solution_persistence import (
        SolutionPersistenceError,
        generate_and_persist_solution_draft,
    )

    owner, _, opportunity, analysis, _ = persistence_context
    original = generated_artifact[0]
    result = GroundedSolutionDraftResult(
        analysis_id=analysis.pk,
        readiness=original.readiness,
        generation_status=status,
        draft=None,
        sources=(),
        unresolved_items=original.unresolved_items,
        admission=None,
    )
    _patch_generation(monkeypatch, result)

    with pytest.raises(SolutionPersistenceError):
        generate_and_persist_solution_draft(opportunity, analysis, created_by=owner)

    assert SolutionDraftRecord.objects.count() == 0
    assert SolutionDraftProvenance.objects.count() == 0


class _RecordingCursor:
    def __init__(self, *, fail_lock=False):
        self.statements = []
        self.fail_lock = fail_lock

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        if self.fail_lock and "pg_advisory_lock(" in sql and "try" not in sql:
            raise OperationalError("canceling statement due to lock timeout")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patch_cursor(monkeypatch, cursor):
    from apps.sales.services import solution_persistence

    monkeypatch.setattr(solution_persistence.connection, "cursor", lambda: cursor)


def test_generation_lock_bounds_wait_and_restores_session(monkeypatch):
    from apps.sales.services.solution_persistence import _generation_idempotency_lock

    cursor = _RecordingCursor()
    _patch_cursor(monkeypatch, cursor)

    with _generation_idempotency_lock(uuid4()):
        pass

    assert any("SET lock_timeout" in sql for sql, _ in cursor.statements)
    assert any("RESET lock_timeout" in sql for sql, _ in cursor.statements)
    assert any("pg_advisory_unlock(" in sql for sql, _ in cursor.statements)


def test_generation_lock_timeout_fails_closed_without_unlock(monkeypatch):
    from apps.sales.services.solution_persistence import (
        SolutionPersistenceError,
        _generation_idempotency_lock,
    )

    cursor = _RecordingCursor(fail_lock=True)
    _patch_cursor(monkeypatch, cursor)

    with pytest.raises(SolutionPersistenceError):
        with _generation_idempotency_lock(uuid4()):
            pass

    assert not any("pg_advisory_unlock(" in sql for sql, _ in cursor.statements)
    assert any("RESET lock_timeout" in sql for sql, _ in cursor.statements)
