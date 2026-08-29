"""Scope boundaries for the synchronous parser layer."""

from io import BytesIO

import openai
import pytest

from apps.knowledge.exceptions import KnowledgeDocumentError


@pytest.mark.django_db
def test_parser_performs_no_database_queries(django_assert_num_queries):
    from apps.knowledge.parsers import parse_document

    with django_assert_num_queries(0):
        segments = parse_document(BytesIO(b"plain text"), "notes.txt")

    assert segments[0].content == "plain text"


def test_parser_does_not_construct_an_embedding_client(monkeypatch):
    from apps.knowledge.parsers import parse_document

    def fail_if_called(*args, **kwargs):
        pytest.fail("The parser must not construct an embedding client.")

    monkeypatch.setattr(openai, "OpenAI", fail_if_called)

    segments = parse_document(BytesIO(b"# Guide\nBody"), "guide.md")

    assert segments[0].content == "Body"


def test_factory_rejects_a_type_that_did_not_pass_validation():
    from apps.knowledge.parsers.factory import get_parser

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        get_parser("spreadsheet")

    assert exc_info.value.code == "unsupported_file_type"
