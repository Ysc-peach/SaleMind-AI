"""PDF parser tests using deterministic in-memory documents."""

from io import BytesIO

import pytest

from apps.knowledge.exceptions import KnowledgeDocumentError
from apps.knowledge.parsers.validation import validate_document_file

from .parser_fixtures import build_pdf


def assert_parse_error(expected_code, data, filename="document.pdf"):
    from apps.knowledge.parsers import parse_document

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        parse_document(BytesIO(data), filename)

    assert exc_info.value.code == expected_code


def test_pdf_parser_keeps_pages_separate_and_numbers_from_one():
    from apps.knowledge.parsers import parse_document

    pdf = build_pdf(["Product   overview", "Deployment guide"])

    segments = parse_document(BytesIO(pdf), "product-whitepaper.pdf")

    assert [segment.content for segment in segments] == [
        "Product overview",
        "Deployment guide",
    ]
    assert [segment.page_number for segment in segments] == [1, 2]
    assert [segment.section_title for segment in segments] == [None, None]


def test_pdf_parser_returns_page_level_citations():
    from apps.knowledge.parsers import parse_document

    segments = parse_document(
        BytesIO(build_pdf(["Overview", "Configuration"])),
        "technical-guide.pdf",
    )

    assert [segment.source_reference for segment in segments] == [
        "《technical-guide.pdf》第 1 页",
        "《technical-guide.pdf》第 2 页",
    ]
    assert segments[1].metadata == {"file_type": "pdf", "page_number": 2}


def test_damaged_pdf_is_rejected_during_file_validation():
    with pytest.raises(KnowledgeDocumentError) as exc_info:
        validate_document_file(BytesIO(b"%PDF-1.7\ncorrupted"), "broken.pdf")

    assert exc_info.value.code == "invalid_file"


def test_encrypted_pdf_is_rejected():
    assert_parse_error(
        "encrypted_pdf",
        build_pdf(["Secret content"], password="secret"),
    )


def test_pdf_over_300_pages_is_rejected():
    assert_parse_error(
        "pdf_page_limit_exceeded",
        build_pdf([None] * 301),
    )


def test_pdf_without_extractable_text_is_rejected_without_ocr():
    assert_parse_error("no_extractable_text", build_pdf([None, None]))


def test_pdf_signature_takes_priority_over_an_incorrect_filename():
    from apps.knowledge.parsers import parse_document

    segments = parse_document(
        BytesIO(build_pdf(["Detected from content"])),
        "misnamed.txt",
    )

    assert segments[0].content == "Detected from content"
    assert segments[0].metadata["file_type"] == "pdf"
