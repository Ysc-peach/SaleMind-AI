"""TXT parser tests."""

from io import BytesIO


def test_txt_parser_returns_plain_utf8_text_with_source_reference():
    from apps.knowledge.parsers import parse_document

    segments = parse_document(
        BytesIO("第一行\r\n第二行".encode("utf-8")),
        "customer-notes.txt",
    )

    assert len(segments) == 1
    assert segments[0].content == "第一行\n第二行"
    assert segments[0].page_number is None
    assert segments[0].section_title is None
    assert segments[0].source_reference == "《customer-notes.txt》"
    assert segments[0].metadata == {"file_type": "text"}


def test_txt_parser_accepts_utf8_bom_without_returning_the_bom():
    from apps.knowledge.parsers import parse_document

    segments = parse_document(
        BytesIO(b"\xef\xbb\xbf" + "BOM 文本".encode("utf-8")),
        "bom.txt",
    )

    assert segments[0].content == "BOM 文本"
