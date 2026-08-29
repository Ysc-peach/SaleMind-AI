"""PostgreSQL migration contract tests for the knowledge application."""

from importlib import import_module

import pytest
from django.db import connection
from pgvector.django import VectorExtension


pytestmark = pytest.mark.django_db


def test_vector_extension_migration_uses_official_operation():
    migration_module = import_module(
        "apps.knowledge.migrations.0001_enable_vector"
    )

    assert len(migration_module.Migration.operations) == 1
    assert isinstance(migration_module.Migration.operations[0], VectorExtension)


def test_test_database_has_pgvector_0_8_6():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        )
        row = cursor.fetchone()

    assert row == ("0.8.6",)


def test_embedding_column_is_vector_1024():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = 'knowledge_knowledgechunk'
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
        )
        row = cursor.fetchone()

    assert row == ("vector(1024)",)
