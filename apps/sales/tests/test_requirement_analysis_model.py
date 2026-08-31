"""PostgreSQL schema and ordinary-instance guards for analysis history."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from apps.sales.models import Customer, Opportunity
from apps.sales.tests.requirement_fakes import valid_analysis_payload


pytestmark = pytest.mark.django_db


@pytest.fixture
def history_inputs(make_user):
    from apps.sales.models import OpportunityRequirementAnalysis

    owner, actor = make_user(), make_user()
    customer = Customer.objects.create(name="客户", created_by=owner)
    opportunity = Opportunity.objects.create(
        project_name="项目", customer=customer, sales_owner=owner, created_by=owner,
    )
    payload = {
        **valid_analysis_payload(), "opportunity": opportunity, "created_by": actor,
        "source_raw_requirement": "预算最多30万元。",
        "source_context": {"opportunity": {"budget": "500000.00"}, "customer": {"name": "客户"}},
        "analysis_version": "v1", "llm_provider": "fake", "llm_model": "fake-model",
    }
    return OpportunityRequirementAnalysis, payload


def test_history_schema_and_real_jsonb_storage(history_inputs):
    model, payload = history_inputs
    record = model.objects.create(**payload)
    record.refresh_from_db()
    assert record.pk is not None
    assert record.opportunity_id == payload["opportunity"].pk
    assert record.created_by_id == payload["created_by"].pk
    assert set(field.name for field in model._meta.fields) == {
        "id", "opportunity", "created_by", "summary", "requirements", "conflicts",
        "clarifying_questions", "source_raw_requirement", "source_context",
        "analysis_version", "llm_provider", "llm_model", "created_at",
    }
    assert record in payload["opportunity"].requirement_analyses.all()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = %s",
            [model._meta.db_table],
        )
        column_types = dict(cursor.fetchall())
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE tablename = %s", [model._meta.db_table])
        indexes = [row[0] for row in cursor.fetchall()]
    for name in ("requirements", "conflicts", "clarifying_questions", "source_context"):
        assert column_types[name] == "jsonb"
    assert any("(opportunity_id, created_at DESC, id DESC)" in definition for definition in indexes)


@pytest.mark.parametrize("field", ["summary", "analysis_version", "llm_provider", "llm_model"])
@pytest.mark.parametrize("value", ["", " \n\t"])
def test_database_rejects_empty_history_metadata(history_inputs, field, value):
    model, payload = history_inputs
    payload[field] = value
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(**payload)


@pytest.mark.parametrize("field", ["opportunity", "created_by"])
def test_history_relations_are_required(history_inputs, field):
    model, payload = history_inputs
    payload[field] = None
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(**payload)


def test_triggering_user_is_protected(history_inputs):
    model, payload = history_inputs
    model.objects.create(**payload)
    with pytest.raises(ProtectedError):
        payload["created_by"].delete()


def test_opportunity_deletion_cascades_owned_history(history_inputs):
    model, payload = history_inputs
    record = model.objects.create(**payload)
    payload["opportunity"].delete()
    assert not model.objects.filter(pk=record.pk).exists()
    assert payload["created_by"].__class__.objects.filter(pk=payload["created_by"].pk).exists()


@pytest.mark.parametrize("operation", ["save", "delete", "clone_with_existing_pk"])
def test_normal_instance_cannot_overwrite_or_delete_history(history_inputs, operation):
    model, payload = history_inputs
    record = model.objects.create(**payload)
    original = model.objects.values().get(pk=record.pk)
    with pytest.raises(ValidationError) as caught:
        if operation == "delete":
            record.delete()
        elif operation == "clone_with_existing_pk":
            model(id=record.pk, **{**payload, "summary": "改写旧记录"}).save()
        else:
            record.summary = "改写旧记录"
            record.save()
    assert caught.value.code == "immutable_requirement_analysis"
    assert model.objects.values().get(pk=record.pk) == original


def test_default_history_order_uses_id_to_break_timestamp_ties(history_inputs, monkeypatch):
    model, payload = history_inputs
    instant = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: instant)
    first = model.objects.create(**payload)
    second = model.objects.create(**payload)
    assert first.created_at == second.created_at
    assert list(model.objects.values_list("pk", flat=True)) == [second.pk, first.pk]
