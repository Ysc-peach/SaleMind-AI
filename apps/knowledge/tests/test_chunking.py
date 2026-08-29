"""Deterministic, traceable knowledge chunking contracts."""

import openai
import pytest

from apps.knowledge.exceptions import KnowledgeDocumentError
from apps.knowledge.parsers import ParsedSegment


def _segment(
    content: str,
    *,
    page_number: int | None = None,
    section_title: str | None = None,
    source_reference: str = "《Knowledge guide》",
    metadata: dict | None = None,
) -> ParsedSegment:
    return ParsedSegment(
        content=content,
        page_number=page_number,
        section_title=section_title,
        source_reference=source_reference,
        metadata=metadata or {},
    )


def test_short_business_segment_produces_one_traceable_chunk():
    from apps.knowledge.services.chunking import chunk_segments

    segment = _segment(
        "客户需要建设共享知识库。",
        page_number=3,
        section_title="需求背景",
        source_reference="《项目说明》第 3 页",
        metadata={"file_type": "pdf", "page_number": 999},
    )

    chunks = chunk_segments([segment])

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == "客户需要建设共享知识库。"
    assert chunks[0].char_count == 12
    assert chunks[0].page_number == 3
    assert chunks[0].section_title == "需求背景"
    assert chunks[0].source_reference == "《项目说明》第 3 页"
    assert chunks[0].metadata == {"file_type": "pdf", "page_number": 999}


def test_blank_segments_are_ignored_and_indices_follow_input_order():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [
            _segment("   \n\t"),
            _segment("First", source_reference="first"),
            _segment("Second", source_reference="second"),
        ]
    )

    assert [(chunk.chunk_index, chunk.content) for chunk in chunks] == [
        (0, "First"),
        (1, "Second"),
    ]
    assert [chunk.source_reference for chunk in chunks] == ["first", "second"]


def test_chunk_metadata_is_copied_without_mutating_the_input_segment():
    from apps.knowledge.services.chunking import chunk_segments

    original_metadata = {"file_type": "markdown"}
    segment = _segment("Deployment notes", metadata=original_metadata)

    chunk = chunk_segments([segment])[0]
    chunk.metadata["added_later"] = True

    assert segment.metadata == {"file_type": "markdown"}


def test_nested_chunk_metadata_does_not_alias_the_input_segment():
    from apps.knowledge.services.chunking import chunk_segments

    segment = _segment(
        "Deployment notes",
        metadata={"source": {"header_level": 2}},
    )

    chunk = chunk_segments([segment])[0]
    chunk.metadata["source"]["header_level"] = 3

    assert segment.metadata == {"source": {"header_level": 2}}


def test_long_text_uses_overlap_and_continuous_indices():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("abcdefghijABCDEFGHIJklmnopqrst")],
        chunk_size=12,
        overlap=3,
    )

    assert [chunk.content for chunk in chunks] == [
        "abcdefghijAB",
        "jABCDEFGHIJk",
        "IJklmnopqrst",
    ]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.char_count for chunk in chunks] == [12, 12, 12]


def test_paragraph_boundary_is_preferred_over_a_later_sentence_boundary():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("1234567890 sentence.\n\nGamma. trailing words")],
        chunk_size=30,
        overlap=0,
    )

    assert chunks[0].content == "1234567890 sentence."
    assert chunks[1].content == "Gamma. trailing words"


def test_chinese_sentence_boundary_is_preserved():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("第一段内容需要保留完整句子。第二段内容继续说明方案。第三段。")],
        chunk_size=20,
        overlap=0,
    )

    assert chunks[0].content == "第一段内容需要保留完整句子。"
    assert chunks[1].content == "第二段内容继续说明方案。第三段。"


def test_english_sentence_boundary_is_preserved():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("First sentence ends here. Second sentence continues. Third.")],
        chunk_size=35,
        overlap=0,
    )

    assert chunks[0].content == "First sentence ends here."
    assert chunks[1].content == "Second sentence continues. Third."


def test_text_without_natural_boundaries_is_hard_split():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("abcdefghijABCDEFGHIJklmnopqrst")],
        chunk_size=10,
        overlap=0,
    )

    assert [chunk.content for chunk in chunks] == [
        "abcdefghij",
        "ABCDEFGHIJ",
        "klmnopqrst",
    ]


def test_pdf_pages_are_chunked_independently():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [
            _segment("A" * 18, page_number=1, source_reference="page 1"),
            _segment("B" * 18, page_number=2, source_reference="page 2"),
        ],
        chunk_size=10,
        overlap=2,
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]
    assert all(set(chunk.content) == {"A"} for chunk in chunks[:2])
    assert all(chunk.page_number == 1 for chunk in chunks[:2])
    assert all(chunk.source_reference == "page 1" for chunk in chunks[:2])
    assert all(set(chunk.content) == {"B"} for chunk in chunks[2:])
    assert all(chunk.page_number == 2 for chunk in chunks[2:])
    assert all(chunk.source_reference == "page 2" for chunk in chunks[2:])


def test_markdown_sections_are_chunked_independently():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [
            _segment("A" * 18, section_title="Section A"),
            _segment("B" * 18, section_title="Section B"),
        ],
        chunk_size=10,
        overlap=2,
    )

    assert all(chunk.section_title == "Section A" for chunk in chunks[:2])
    assert all(chunk.section_title == "Section B" for chunk in chunks[2:])


def test_newline_boundary_is_used_before_hard_cutting():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("1234567890 line one\nline two continues")],
        chunk_size=25,
        overlap=0,
    )

    assert [chunk.content for chunk in chunks] == [
        "1234567890 line one",
        "line two continues",
    ]


def test_overlap_starts_on_a_natural_word_boundary_when_available():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("alpha beta gamma delta epsilon zeta")],
        chunk_size=24,
        overlap=8,
    )

    assert [chunk.content for chunk in chunks] == [
        "alpha beta gamma delta",
        "delta epsilon zeta",
    ]


def test_overlap_can_use_a_nearby_boundary_before_its_target():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("aaaa bbbbb ccccccccccccc")],
        chunk_size=17,
        overlap=4,
    )

    assert chunks[0].content == "aaaa bbbbb"
    assert chunks[1].content.startswith("bbbbb ")


def test_short_tail_is_merged_without_losing_effective_text():
    from apps.knowledge.services.chunking import chunk_segments

    content = "A" * 55

    chunks = chunk_segments([_segment(content)], chunk_size=50, overlap=10)

    assert [chunk.content for chunk in chunks] == [content]
    assert chunks[0].char_count == 55


def test_repeated_chunking_is_identical_and_does_not_mutate_segments():
    from apps.knowledge.services.chunking import chunk_segments

    segment = _segment(
        "alpha beta gamma delta epsilon zeta",
        section_title="Stable section",
        metadata={"header_level": 2},
    )

    first = chunk_segments([segment], chunk_size=24, overlap=8)
    second = chunk_segments([segment], chunk_size=24, overlap=8)

    assert first == second
    assert segment.content == "alpha beta gamma delta epsilon zeta"
    assert segment.metadata == {"header_level": 2}


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "max_chunks"),
    [
        (0, 0, 500),
        (100, -1, 500),
        (100, 100, 500),
        (100, 101, 500),
        (100, 10, 0),
    ],
)
def test_invalid_chunk_configuration_fails_explicitly(
    chunk_size,
    overlap,
    max_chunks,
):
    from apps.knowledge.services.chunking import chunk_segments

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        chunk_segments(
            [_segment("content")],
            chunk_size=chunk_size,
            overlap=overlap,
            max_chunks=max_chunks,
        )

    assert exc_info.value.code == "invalid_chunk_configuration"


def test_document_chunk_limit_fails_instead_of_truncating():
    from apps.knowledge.services.chunking import chunk_segments

    segments = [_segment(f"segment-{index}") for index in range(501)]

    with pytest.raises(KnowledgeDocumentError) as exc_info:
        chunk_segments(segments, max_chunks=500)

    assert exc_info.value.code == "chunk_limit_exceeded"


def test_exact_document_chunk_limit_is_allowed():
    from apps.knowledge.services.chunking import chunk_segments

    chunks = chunk_segments(
        [_segment("first"), _segment("second")],
        max_chunks=2,
    )

    assert [chunk.content for chunk in chunks] == ["first", "second"]


@pytest.mark.django_db
def test_chunking_performs_no_database_queries(django_assert_num_queries):
    from apps.knowledge.services.chunking import chunk_segments

    with django_assert_num_queries(0):
        chunks = chunk_segments([_segment("plain knowledge")])

    assert chunks[0].content == "plain knowledge"


def test_chunking_does_not_construct_an_embedding_client(monkeypatch):
    from apps.knowledge.services.chunking import chunk_segments

    def fail_if_called(*args, **kwargs):
        pytest.fail("Chunking must not construct an embedding client.")

    monkeypatch.setattr(openai, "OpenAI", fail_if_called)

    chunks = chunk_segments([_segment("plain knowledge")])

    assert chunks[0].content == "plain knowledge"
