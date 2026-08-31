"""Pure, citation-safe evidence representation shared by grounded services."""

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.knowledge.services.search import KnowledgeSearchResult


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    chunk_id: int
    document_id: int
    document_title: str
    document_type: str
    original_filename: str
    content: str
    page_number: int | None
    section_title: str | None
    source_reference: str
    similarity: float


def source_from_result(result: "KnowledgeSearchResult") -> EvidenceSource:
    return EvidenceSource(
        chunk_id=result.chunk_id, document_id=result.document_id,
        document_title=result.document_title, document_type=result.document_type,
        original_filename=result.original_filename, content=result.content,
        page_number=result.page_number, section_title=result.section_title,
        source_reference=result.source_reference, similarity=result.similarity,
    )


def format_source(source: EvidenceSource, *, source_id: str) -> str:
    """source_id is program-generated; all retrieved text stays escaped data."""
    lines = [
        f'<source id="{source_id}">',
        f"文档：{escape(source.document_title, quote=False)}",
        f"文件：{escape(source.original_filename, quote=False)}",
    ]
    if source.page_number is not None:
        lines.append(f"页码：{source.page_number}")
    if source.section_title:
        lines.append(f"章节：{escape(source.section_title, quote=False)}")
    lines.extend([
        f"来源：{escape(source.source_reference, quote=False)}", "内容：",
        escape(source.content, quote=False), "</source>",
    ])
    return "\n".join(lines)
