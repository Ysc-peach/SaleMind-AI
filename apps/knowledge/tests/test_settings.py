"""Configuration contract tests for the knowledge application."""

from importlib import import_module

import pytest
from django.apps import apps
from django.conf import settings


def test_knowledge_app_is_registered():
    app_config = apps.get_app_config("knowledge")

    assert app_config.name == "apps.knowledge"


@pytest.mark.parametrize(
    ("module_name", "public_attribute"),
    [
        ("pgvector.django", "VectorField"),
        ("pypdf", "PdfReader"),
        ("markdown_it", "MarkdownIt"),
        ("openai", "OpenAI"),
    ],
)
def test_knowledge_runtime_dependencies_are_importable(module_name, public_attribute):
    module = import_module(module_name)

    assert hasattr(module, public_attribute)


@pytest.mark.parametrize(
    ("setting_name", "expected_value"),
    [
        ("EMBEDDING_PROVIDER", "openai_compatible"),
        ("EMBEDDING_MODEL", "BAAI/bge-m3"),
        ("EMBEDDING_DIMENSIONS", 1024),
        ("EMBEDDING_TIMEOUT_SECONDS", 30),
        ("EMBEDDING_MAX_RETRIES", 2),
        ("EMBEDDING_BATCH_SIZE", 32),
        ("KNOWLEDGE_MAX_FILE_SIZE_BYTES", 20 * 1024 * 1024),
        ("KNOWLEDGE_MAX_PDF_PAGES", 300),
        ("KNOWLEDGE_MAX_CHUNKS", 500),
        ("KNOWLEDGE_CHUNK_SIZE", 1200),
        ("KNOWLEDGE_CHUNK_OVERLAP", 150),
        ("KNOWLEDGE_INDEXING_STALE_SECONDS", 3600),
    ],
)
def test_knowledge_settings_have_documented_defaults(setting_name, expected_value):
    assert getattr(settings, setting_name) == expected_value


@pytest.mark.parametrize("setting_name", ["EMBEDDING_API_KEY", "EMBEDDING_BASE_URL"])
def test_optional_embedding_settings_are_available(setting_name):
    assert isinstance(getattr(settings, setting_name), str)


def test_knowledge_uploads_use_the_project_media_directory():
    assert settings.MEDIA_ROOT == settings.BASE_DIR / "media"


def test_postgresql_tests_clone_the_vector_enabled_template():
    assert settings.DATABASES["default"]["TEST"]["TEMPLATE"] == "salesmind_test_template"
