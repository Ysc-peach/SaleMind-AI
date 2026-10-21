"""Budget and collision-search input bounds do not rewrite business history."""

from decimal import Decimal

import pytest
from django.db import connection
from django.forms import modelform_factory
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.sales.models import Customer, Opportunity


pytestmark = pytest.mark.django_db


@pytest.fixture
def input_context(make_user):
    actor = make_user()
    customer = Customer.objects.create(name="Input boundaries", created_by=actor)
    opportunity = Opportunity.objects.create(
        project_name="Original project", customer=customer, sales_owner=actor,
        created_by=actor, budget=Decimal("1200.00"),
    )
    client = APIClient()
    client.force_authenticate(actor)
    return client, customer, opportunity


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("budget", ["-0.01", "-1", "-999999999999.99"])
def test_negative_budget_is_rejected_without_saving_any_fields(input_context, action, budget):
    client, customer, opportunity = input_context
    before_count = Opportunity.objects.count()
    before_updated = opportunity.updated_at
    payload = {"budget": budget, "project_name": "Must not save"}
    if action == "create":
        response = client.post("/api/opportunities/", {**payload, "customer": customer.pk}, format="json")
    else:
        response = client.patch(f"/api/opportunities/{opportunity.pk}/", payload, format="json")

    assert response.status_code == 400
    assert "budget" in response.json()
    assert Opportunity.objects.count() == before_count
    opportunity.refresh_from_db()
    assert opportunity.budget == Decimal("1200.00")
    assert opportunity.project_name == "Original project"
    assert opportunity.updated_at == before_updated


@pytest.mark.parametrize("budget, expected", [(None, None), ("0", "0.00"), ("0.01", "0.01")])
def test_unknown_zero_and_positive_budget_remain_valid(input_context, budget, expected):
    client, customer, opportunity = input_context
    response = client.post("/api/opportunities/", {
        "project_name": "Valid budget", "customer": customer.pk, "budget": budget,
    }, format="json")
    assert response.status_code == 201
    assert response.json()["budget"] == expected

    response = client.patch(f"/api/opportunities/{opportunity.pk}/", {"budget": budget}, format="json")
    assert response.status_code == 200
    assert response.json()["budget"] == expected


def test_unrelated_patch_does_not_silently_repair_legacy_budget(input_context):
    client, _, opportunity = input_context
    # Controlled legacy fixture only, never a maintenance operation on live data.
    Opportunity.objects.filter(pk=opportunity.pk).update(budget=Decimal("-1.00"))
    response = client.patch(f"/api/opportunities/{opportunity.pk}/", {
        "project_name": "Renamed legacy project",
    }, format="json")

    assert response.status_code == 200
    opportunity.refresh_from_db()
    assert opportunity.budget == Decimal("-1.00")


@pytest.mark.parametrize("value, valid", [("-0.01", False), ("0", True), ("", True)])
def test_budget_model_form_obeys_the_same_input_contract(value, valid):
    form = modelform_factory(Opportunity, fields=["budget"])(data={"budget": value})
    assert form.is_valid() is valid
    if not valid:
        assert "budget" in form.errors


@pytest.mark.parametrize("character", ["a", "客", "😀"])
def test_search_over_200_codepoints_is_rejected_before_querying(input_context, character):
    client, _, _ = input_context
    query = "  " + character * 201 + "  "
    with CaptureQueriesContext(connection) as captured:
        response = client.get("/api/customers/search/", {"q": query})

    assert response.status_code == 400
    assert response.json()["code"] == "customer_search_query_too_long"
    assert "q" in response.json()
    assert query.strip() not in str(response.json())
    assert not captured.captured_queries


@pytest.mark.parametrize("character", ["a", "客", "😀"])
def test_search_200_codepoints_is_trimmed_not_truncated(input_context, character):
    client, customer, _ = input_context
    exact = character * 200
    customer.name = exact
    customer.save(update_fields=["name"])

    response = client.get("/api/customers/search/", {"q": "  " + exact + "  "})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["id"] == customer.pk


def test_oversized_search_cannot_bypass_authentication():
    response = APIClient().get("/api/customers/search/", {"q": "x" * 201})
    assert response.status_code == 401
