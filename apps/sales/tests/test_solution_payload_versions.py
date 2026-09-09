"""Authoritative persisted Solution schema discriminator and mapper contracts."""

import pytest

from apps.sales.models import SolutionDraftRecord
from apps.sales.tests.test_solution_persistence_mapping import domain_draft as v1_fixture
from apps.sales.tests.test_solution_schema_v2 import valid_draft


pytestmark = pytest.mark.django_db


def test_solution_schema_version_is_a_database_column():
    """Removing the discriminator column would make V1/V2 reads ambiguous."""
    field = SolutionDraftRecord._meta.get_field("schema_version")

    assert field.default == 1
    assert field.null is False


def test_v1_dispatch_preserves_the_existing_payload(v1_fixture):
    """Changing V1 canonical bytes would break historical records."""
    from apps.sales.services.solution_payloads import (
        deserialize_solution_payload,
        serialize_solution_domain,
    )

    serialized = serialize_solution_domain(v1_fixture)

    assert serialized.schema_version == 1
    assert "schema_version" not in serialized.payload
    assert deserialize_solution_payload(1, serialized.payload) == v1_fixture


def test_v2_round_trip_preserves_every_reference():
    """A V2 save/load cycle must not regenerate or reorder stable claim IDs."""
    from apps.sales.services.solution_payloads import (
        deserialize_solution_payload,
        serialize_solution_domain,
    )

    draft = valid_draft()
    serialized = serialize_solution_domain(draft)

    assert serialized.schema_version == 2
    assert "schema_version" not in serialized.payload
    assert [item["claim_id"] for item in serialized.payload["claims"]] == [
        "C0001",
        "C0002",
        "C0003",
        "C0004",
        "C0005",
    ]
    assert deserialize_solution_payload(2, serialized.payload) == draft


@pytest.mark.parametrize("schema_version", [0, 3, 99, "2", None])
def test_unknown_schema_version_fails_closed(schema_version):
    from apps.sales.services.solution_payloads import (
        SolutionPayloadError,
        deserialize_solution_payload,
    )

    with pytest.raises(SolutionPayloadError):
        deserialize_solution_payload(schema_version, {})


def test_v2_payload_rejects_extra_nested_business_text():
    """Nested JSON cannot add a free-form semantic channel around claim references."""
    from apps.sales.services.solution_payloads import (
        SolutionPayloadError,
        deserialize_solution_payload,
        serialize_solution_domain,
    )

    payload = serialize_solution_domain(valid_draft()).payload
    payload["architecture"]["components"][0]["responsibilities"] = (
        "采用 PostgreSQL 双节点高可用。"
    )

    with pytest.raises(SolutionPayloadError):
        deserialize_solution_payload(2, payload)
