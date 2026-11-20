"""The comparison appendix is built from approved data, never phrased by a model."""

import hashlib
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
from apps.sales.models import Competitor, CompetitorStatement
from apps.sales.services.competitor_appendix import (
    APPENDIX_TITLE,
    HEADER,
    build_comparison_appendix,
)
from apps.sales.tests.export_fixtures import make_export_case

pytestmark = pytest.mark.django_db(transaction=True)


def _fact(subject, statement, *, owner):
    document = KnowledgeDocument.objects.create(
        title=f"Doc {subject}",
        document_type="technical",
        source_file=f"knowledge/documents/{subject}.md",
        original_filename=f"{subject}.md",
        mime_type="text/markdown",
        file_size=len(statement.encode()),
        checksum_sha256=hashlib.sha256(statement.encode()).hexdigest(),
        status="ready",
        chunk_count=1,
        embedding_provider="fake",
        embedding_model="fake-model",
        embedding_dimensions=1024,
        last_indexed_at=timezone.now(),
        last_index_run_id=uuid4(),
        created_by=owner,
    )
    return EnterpriseGroundingFact.objects.create(
        subject_key=subject,
        statement=statement,
        status="confirmed_supported",
        source_document=document,
        source_chunk_id=1,
        source_excerpt=statement,
        source_index_run_id=uuid4(),
        source_content_hash=hashlib.sha256(statement.encode()).hexdigest(),
        approval_status="approved",
        approved_by=owner,
        approved_at=timezone.now(),
    )


def _competitor(owner, name="竞品甲"):
    return Competitor.objects.create(name=name, created_by=owner)


def _statement(competitor, *, status="approved", owner):
    return CompetitorStatement.objects.create(
        competitor=competitor,
        dimension="deployment",
        statement="支持容器化部署与私有化交付",
        source_url="https://example.com/deploy",
        published_on=timezone.localdate(),
        captured_on=timezone.localdate(),
        status=status,
        created_by=owner,
        reviewed_by=owner if status != "proposed" else None,
        reviewed_at=timezone.now() if status != "proposed" else None,
    )


def _text(section) -> str:
    return " ".join(block.text for block in section.blocks if block.text)


def test_a_row_is_written_only_when_both_sides_have_approved_evidence(
    make_export_case,
):
    case = make_export_case()
    competitor = _competitor(case.owner)
    _fact("private_deployment", "本产品支持私有化部署", owner=case.owner)
    _statement(competitor, owner=case.owner)

    sections = build_comparison_appendix([competitor])

    assert len(sections) == 1
    section = sections[0]
    assert section.title == APPENDIX_TITLE
    table = next(block for block in section.blocks if block.kind == "table")
    assert table.rows[0] == HEADER
    row = table.rows[1]
    assert row[0] == "部署形态"
    assert row[1] == "竞品甲"
    assert row[2] == "本产品支持私有化部署"
    # The source travels with the statement, so a reader can check it.
    assert "https://example.com/deploy" in row[3]


def test_a_dimension_without_evidence_is_named_instead_of_omitted_silently(
    make_export_case,
):
    case = make_export_case()
    competitor = _competitor(case.owner)
    _fact("private_deployment", "本产品支持私有化部署", owner=case.owner)

    section = build_comparison_appendix([competitor])[0]

    assert "未纳入" in _text(section)
    assert "缺竞品可引用陈述" in _text(section)
    assert not any(block.kind == "table" for block in section.blocks)


def test_a_proposed_statement_never_reaches_the_appendix(make_export_case):
    case = make_export_case()
    competitor = _competitor(case.owner)
    _fact("private_deployment", "本产品支持私有化部署", owner=case.owner)
    _statement(competitor, status="proposed", owner=case.owner)

    section = build_comparison_appendix([competitor])[0]

    assert not any(block.kind == "table" for block in section.blocks)
    assert "缺竞品可引用陈述" in _text(section)


def test_an_export_with_a_competitor_still_renders(make_export_case):
    case = make_export_case()
    competitor = _competitor(case.owner, name="竞品乙")
    _fact("private_deployment", "本产品支持私有化部署", owner=case.owner)
    _statement(competitor, owner=case.owner)

    client = APIClient()
    client.force_authenticate(case.owner)
    url = (
        f"/api/solution-drafts/{case.solution.pk}/export/"
        f"?file_type=pdf&competitor={competitor.pk}"
    )

    response = client.get(url)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_an_export_without_the_parameter_is_unchanged(make_export_case):
    case = make_export_case()
    client = APIClient()
    client.force_authenticate(case.owner)

    plain = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/?file_type=pdf"
    )

    assert plain.status_code == 200


def test_an_unknown_competitor_is_not_found(make_export_case):
    case = make_export_case()
    client = APIClient()
    client.force_authenticate(case.owner)

    response = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/"
        "?file_type=pdf&competitor=999999"
    )

    assert response.status_code == 404


def test_a_non_numeric_competitor_is_rejected(make_export_case):
    case = make_export_case()
    client = APIClient()
    client.force_authenticate(case.owner)

    response = client.get(
        f"/api/solution-drafts/{case.solution.pk}/export/"
        "?file_type=pdf&competitor=abc"
    )

    assert response.status_code == 400
