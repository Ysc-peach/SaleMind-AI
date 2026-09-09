"""Authoritative persisted Solution schema discriminator contracts."""

import pytest

from apps.sales.models import SolutionDraftRecord


pytestmark = pytest.mark.django_db


def test_solution_schema_version_is_a_database_column():
    """Removing the discriminator column would make V1/V2 reads ambiguous."""
    field = SolutionDraftRecord._meta.get_field("schema_version")

    assert field.default == 1
    assert field.null is False
