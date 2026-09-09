"""Safe API projection for immutable V1 and V2 Solution records."""

from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord
from apps.sales.services.solution_payloads import serialize_solution_domain
from apps.sales.tests.test_solution_draft_api import api_context, client_for
from apps.sales.tests.test_solution_schema_v2 import valid_draft


pytestmark = pytest.mark.django_db


@pytest.fixture
def v2_api_record(api_context):
    owner = api_context["owner"]
    document = KnowledgeDocument.objects.create(
        title="V2 enterprise source",
        document_type="technical",
        source_file="knowledge/documents/v2-source.md",
        original_filename="v2-source.md",
        mime_type="text/markdown",
        file_size=32,
        checksum_sha256="a" * 64,
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    excerpt = "系统支持私有化部署。"
    fact = EnterpriseGroundingFact.objects.create(
        subject_key="private_deployment",
        statement=excerpt,
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=901,
        source_excerpt=excerpt,
        source_index_run_id=document.last_index_run_id,
        source_content_hash="b" * 64,
        approval_status="approved",
        approved_by=owner,
        approved_at=timezone.now(),
    )
    serialized = serialize_solution_domain(valid_draft())
    record = SolutionDraftRecord.objects.create(
        opportunity=api_context["opportunity"],
        requirement_analysis=api_context["analysis"],
        version=2,
        title=valid_draft().title,
        draft_payload=serialized.payload,
        generation_metadata={"generation_status": "generated"},
        schema_version=2,
        created_by=owner,
    )
    for claim_id in ("C0002", "C0003"):
        SolutionDraftProvenance.objects.create(
            solution_draft=record,
            statement_path=f"claims.{claim_id}",
            claim_id=claim_id,
            citation_label="S1",
            enterprise_grounding_fact=fact,
            source_document=document,
            source_chunk_id=fact.source_chunk_id,
            source_index_run_id=fact.source_index_run_id,
            source_content_hash=fact.source_content_hash,
            source_excerpt=fact.source_excerpt,
        )
    return record


def test_v1_and_v2_list_items_expose_authoritative_schema_version(api_context, v2_api_record):
    response = client_for(api_context["owner"]).get(
        reverse("solution-draft-list", kwargs={"opportunity_id": api_context["opportunity"].pk})
    )

    assert response.status_code == 200
    assert [(item["version"], item["schema_version"]) for item in response.json()["results"]] == [
        (2, 2), (1, 1)
    ]
    assert all("draft_payload" not in item for item in response.json()["results"])


def test_v2_detail_derives_deduplicated_claim_sources_from_durable_provenance(
    api_context, v2_api_record
):
    response = client_for(api_context["owner"]).get(
        reverse("solution-draft-detail", kwargs={"solution_id": v2_api_record.pk})
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 2
    assert body["draft_payload"] == v2_api_record.draft_payload
    assert body["source_registry"] == [{
        "source_id": "S1",
        "document_id": v2_api_record.provenance_entries.first().source_document_id,
        "document_title": "V2 enterprise source",
        "source_excerpt": "系统支持私有化部署。",
    }]
    assert body["claim_sources"] == {"C0002": ["S1"], "C0003": ["S1"]}
    assert "provenance" not in body


def test_v2_business_detail_omits_internal_provenance_and_provider_data(
    api_context, v2_api_record
):
    response = client_for(api_context["owner"]).get(
        reverse("solution-draft-detail", kwargs={"solution_id": v2_api_record.pk})
    )
    rendered = str(response.json())

    for forbidden in (
        "source_content_hash", "source_index_run_id", "source_chunk_id",
        "enterprise_grounding_fact_id", "provider_raw_response", "prompt",
        "API_KEY", "DATABASE_URL",
    ):
        assert forbidden not in rendered


def test_create_requests_v2_without_changing_explicit_analysis_selection(monkeypatch, api_context):
    from apps.sales.api import solution_draft_views

    captured = {}

    def persist(opportunity, analysis, *, created_by, **kwargs):
        captured.update(analysis_id=analysis.pk, schema_version=kwargs.get("schema_version"))
        return api_context["record"]

    monkeypatch.setattr(solution_draft_views, "generate_and_persist_solution_draft", persist)
    response = client_for(api_context["owner"]).post(
        reverse("solution-draft-list", kwargs={"opportunity_id": api_context["opportunity"].pk}),
        {"analysis_id": api_context["analysis"].pk},
        format="json",
    )

    assert response.status_code == 201
    assert captured == {"analysis_id": api_context["analysis"].pk, "schema_version": 2}
