"""Contracts shared by all knowledge document parsers."""

from importlib import import_module


def test_parsed_segment_preserves_content_and_source_metadata():
    parser_types = import_module("apps.knowledge.parsers.types")

    segment = parser_types.ParsedSegment(
        content="PostgreSQL deployment guidance",
        page_number=12,
        section_title="Deployment > PostgreSQL",
        source_reference="《Technical guide》第 12 页",
        metadata={"file_type": "pdf"},
    )

    assert segment.content == "PostgreSQL deployment guidance"
    assert segment.page_number == 12
    assert segment.section_title == "Deployment > PostgreSQL"
    assert segment.source_reference == "《Technical guide》第 12 页"
    assert segment.metadata == {"file_type": "pdf"}


def test_parser_error_codes_are_stable_and_complete():
    exceptions = import_module("apps.knowledge.exceptions")

    assert set(exceptions.KnowledgeDocumentErrorCode) == {
        "unsupported_file_type",
        "file_too_large",
        "invalid_file",
        "encrypted_pdf",
        "pdf_page_limit_exceeded",
        "no_extractable_text",
        "invalid_text_encoding",
    }
