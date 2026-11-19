"""The comparison matrix says which rows have evidence on both sides."""

import hashlib
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.knowledge.models import EnterpriseGroundingFact, KnowledgeDocument
from apps.sales.models import (
    Competitor,
    CompetitorStatement,
    CompetitorStatementStatus,
)

pytestmark = pytest.mark.django_db


def _matrix_url(opportunity_id: int, competitor_id: int | None = None) -> str:
    base = f"/api/opportunities/{opportunity_id}/competitor-matrix/"
    return f"{base}?competitor={competitor_id}" if competitor_id else base


def _fact(subject: str, statement: str, *, owner, approved=True, stale=False):
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
        approval_status="approved" if approved else "proposed",
        approved_by=owner if approved else None,
        approved_at=timezone.now() if approved else None,
        is_stale=stale,
        stale_at=timezone.now() if stale else None,
    )


def _competitor(owner, name="竞品甲"):
    return Competitor.objects.create(name=name, created_by=owner)


def _statement(competitor, *, dimension="deployment", status="approved", owner):
    return CompetitorStatement.objects.create(
        competitor=competitor,
        dimension=dimension,
        statement="支持容器化部署",
        source_url="https://example.com/deploy",
        published_on=timezone.localdate(),
        captured_on=timezone.localdate(),
        status=status,
        created_by=owner,
        reviewed_by=owner if status != "proposed" else None,
        reviewed_at=timezone.now() if status != "proposed" else None,
    )


def _row(payload, competitor_id, dimension="deployment"):
    for entry in payload["dimensions"]:
        if entry["dimension"] != dimension:
            continue
        for row in entry["competitors"]:
            if row["competitor_id"] == competitor_id:
                return row
    raise AssertionError(f"{dimension} / {competitor_id} not in matrix")


def test_every_dimension_appears_even_with_no_evidence(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    api_client.force_authenticate(user=seller)

    response = api_client.get(_matrix_url(opportunity.id, competitor.id))

    assert response.status_code == 200
    assert len(response.data["dimensions"]) == 8
    row = _row(response.data, competitor.id)
    assert row["can_form"] is False
    assert row["gap"] == "missing_both"
    assert response.data["formable_rows"] == 0
    assert response.data["total_rows"] == 8


def test_both_sides_present_makes_the_row_formable(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _fact("private_deployment", "本产品支持私有化部署", owner=seller)
    _statement(competitor, owner=seller)
    api_client.force_authenticate(user=seller)

    response = api_client.get(_matrix_url(opportunity.id, competitor.id))

    row = _row(response.data, competitor.id)
    assert row["can_form"] is True
    assert row["gap"] == ""
    assert row["own_facts"][0]["subject_key"] == "private_deployment"
    assert row["statements"][0]["source_url"] == "https://example.com/deploy"
    assert response.data["formable_rows"] == 1


def test_a_missing_statement_is_named(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _fact("private_deployment", "本产品支持私有化部署", owner=seller)
    api_client.force_authenticate(user=seller)

    row = _row(
        api_client.get(_matrix_url(opportunity.id, competitor.id)).data,
        competitor.id,
    )

    assert row["gap"] == "missing_competitor_statement"
    assert row["can_form"] is False


def test_a_missing_own_fact_is_named(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _statement(competitor, owner=seller)
    api_client.force_authenticate(user=seller)

    row = _row(
        api_client.get(_matrix_url(opportunity.id, competitor.id)).data,
        competitor.id,
    )

    assert row["gap"] == "missing_own_fact"


def test_a_proposed_statement_does_not_count(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _fact("private_deployment", "本产品支持私有化部署", owner=seller)
    _statement(competitor, status="proposed", owner=seller)
    api_client.force_authenticate(user=seller)

    row = _row(
        api_client.get(_matrix_url(opportunity.id, competitor.id)).data,
        competitor.id,
    )

    # An unapproved claim must not make a row look writable.
    assert row["statements"] == []
    assert row["gap"] == "missing_competitor_statement"


def test_a_stale_fact_does_not_count(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _fact("private_deployment", "本产品支持私有化部署", owner=seller, stale=True)
    _statement(competitor, owner=seller)
    api_client.force_authenticate(user=seller)

    row = _row(
        api_client.get(_matrix_url(opportunity.id, competitor.id)).data,
        competitor.id,
    )

    assert row["own_facts"] == []
    assert row["gap"] == "missing_own_fact"


def test_a_fact_stays_inside_its_own_dimension(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    competitor = _competitor(seller)
    _fact("csv_bulk_export", "支持 CSV 批量导出", owner=seller)
    _statement(competitor, dimension="deliverables", owner=seller)
    api_client.force_authenticate(user=seller)

    payload = api_client.get(_matrix_url(opportunity.id, competitor.id)).data

    assert _row(payload, competitor.id, "deliverables")["can_form"] is True
    deployment = _row(payload, competitor.id, "deployment")
    assert deployment["own_facts"] == []
    assert deployment["gap"] == "missing_both"


def test_an_unknown_competitor_is_not_found(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=seller)

    response = api_client.get(_matrix_url(opportunity.id, 999999))

    assert response.status_code == 404


def test_a_matrix_is_only_available_on_a_visible_opportunity(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    stranger = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    api_client.force_authenticate(user=stranger)

    assert api_client.get(_matrix_url(opportunity.id)).status_code == 404


def test_without_a_competitor_parameter_active_ones_are_used(
    api_client, user_factory, customer_factory, opportunity_factory
):
    seller = user_factory(UserRole.SALES)
    opportunity = opportunity_factory(
        customer_factory(name="Acme"), sales_owner=seller
    )
    active = _competitor(seller, name="竞品甲")
    archived = _competitor(seller, name="竞品乙")
    archived.is_active = False
    archived.save(update_fields=["is_active"])
    api_client.force_authenticate(user=seller)

    payload = api_client.get(_matrix_url(opportunity.id)).data

    ids = {row["competitor_id"] for row in payload["dimensions"][0]["competitors"]}
    assert ids == {active.pk}
