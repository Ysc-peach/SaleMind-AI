"""Behavior tests for Customer and Opportunity persistence models."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from apps.sales.models import Customer, Opportunity, OpportunityStage, OpportunityStatus


pytestmark = pytest.mark.django_db


def create_customer(created_by, **overrides):
    return Customer.objects.create(name="Acme", created_by=created_by, **overrides)


def create_opportunity(customer, sales_owner, created_by, **overrides):
    defaults = {
        "project_name": "Platform rollout",
        "customer": customer,
        "sales_owner": sales_owner,
        "created_by": created_by,
    }
    defaults.update(overrides)
    return Opportunity.objects.create(**defaults)


def test_customer_names_are_not_unique(make_user):
    creator = make_user()

    first = create_customer(creator)
    second = create_customer(creator)

    assert first.name == second.name == "Acme"
    assert first.pk != second.pk


def test_opportunity_uses_initial_active_defaults(make_user):
    creator = make_user()
    customer = create_customer(creator)

    opportunity = create_opportunity(customer, creator, creator)

    assert opportunity.stage == OpportunityStage.INITIAL_CONTACT
    assert opportunity.status == OpportunityStatus.ACTIVE


def test_opportunity_allows_no_presales_owner(make_user):
    creator = make_user()
    customer = create_customer(creator)

    opportunity = create_opportunity(customer, creator, creator)

    assert opportunity.presales_owner is None
    assert Opportunity._meta.get_field("presales_owner").null is True


def test_customer_exposes_its_opportunities(make_user):
    creator = make_user()
    customer = create_customer(creator)
    opportunity = create_opportunity(customer, creator, creator)

    assert list(customer.opportunities.all()) == [opportunity]


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("stage", "discovery"), ("status", "paused")],
)
def test_database_rejects_invalid_opportunity_stage_and_status(
    make_user, field, invalid_value
):
    creator = make_user()
    customer = create_customer(creator)

    with pytest.raises(IntegrityError), transaction.atomic():
        create_opportunity(customer, creator, creator, **{field: invalid_value})


def test_customer_cannot_be_deleted_while_an_opportunity_references_it(make_user):
    creator = make_user()
    customer = create_customer(creator)
    create_opportunity(customer, creator, creator)

    with pytest.raises(ProtectedError):
        customer.delete()


def test_customer_creator_cannot_be_deleted(make_user):
    creator = make_user()
    create_customer(creator)

    with pytest.raises(ProtectedError):
        creator.delete()


@pytest.mark.parametrize("relation", ["sales_owner", "presales_owner", "created_by"])
def test_opportunity_user_relations_protect_their_users(make_user, relation):
    customer_creator = make_user()
    customer = create_customer(customer_creator)
    protected_user = make_user()
    sales_owner = protected_user if relation == "sales_owner" else make_user()
    presales_owner = protected_user if relation == "presales_owner" else None
    created_by = protected_user if relation == "created_by" else make_user()
    create_opportunity(
        customer,
        sales_owner,
        created_by,
        presales_owner=presales_owner,
        raw_requirement="shared requirements",
        budget="120000.00",
        expected_launch_date=date(2026, 12, 1),
    )

    with pytest.raises(ProtectedError):
        protected_user.delete()
