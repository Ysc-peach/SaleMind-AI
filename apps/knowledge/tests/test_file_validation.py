"""Security-focused validation tests for uploaded knowledge files."""

from io import BytesIO

import pytest
from django.conf import settings

from apps.knowledge.exceptions import KnowledgeDocumentError


def assert_error_code(expected_code, operation):
    with pytest.raises(KnowledgeDocumentError) as exc_info:
        operation()

    assert exc_info.value.code == expected_code
    assert "\\" not in str(exc_info.value)


def test_utf8_text_is_validated_as_text():
    from apps.knowledge.parsers.validation import (
        DocumentFileType,
        validate_document_file,
    )

    validated = validate_document_file(BytesIO("企业知识库".encode()), "notes.txt")

    assert validated.file_type is DocumentFileType.TEXT
    assert validated.data == "企业知识库".encode()


@pytest.mark.parametrize("filename", ["notes.txt", "guide.md"])
@pytest.mark.parametrize(
    "binary_content",
    [
        b"text\x00binary",
        "text\u0080binary".encode("utf-8"),
    ],
)
def test_binary_content_disguised_as_text_is_rejected(filename, binary_content):
    from apps.knowledge.parsers.validation import validate_document_file

    assert_error_code(
        "invalid_file",
        lambda: validate_document_file(BytesIO(binary_content), filename),
    )


def test_non_utf8_text_is_rejected_with_stable_error():
    from apps.knowledge.parsers.validation import validate_document_file

    assert_error_code(
        "invalid_text_encoding",
        lambda: validate_document_file(BytesIO(b"\xff\xfe\xfa"), "notes.txt"),
    )


def test_pdf_filename_without_pdf_signature_is_rejected():
    from apps.knowledge.parsers.validation import validate_document_file

    assert_error_code(
        "invalid_file",
        lambda: validate_document_file(BytesIO(b"not a pdf"), "report.pdf"),
    )


def test_valid_text_with_unsupported_extension_is_rejected():
    from apps.knowledge.parsers.validation import validate_document_file

    assert_error_code(
        "unsupported_file_type",
        lambda: validate_document_file(BytesIO(b"plain text"), "notes.csv"),
    )


def test_file_over_20_mib_is_rejected_before_parsing():
    from apps.knowledge.parsers.validation import validate_document_file

    oversized = b"a" * (settings.KNOWLEDGE_MAX_FILE_SIZE_BYTES + 1)

    assert_error_code(
        "file_too_large",
        lambda: validate_document_file(BytesIO(oversized), "notes.txt"),
    )
