"""Heading-aware Markdown parser producing searchable plain text."""

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)

from .types import ParsedSegment, ValidatedDocumentFile
from .validation import decode_validated_text


def parse_markdown(document: ValidatedDocumentFile) -> list[ParsedSegment]:
    # HTML tokenization lets us discard raw HTML without ever rendering it.
    markdown = MarkdownIt("commonmark", {"html": True})
    tokens = markdown.parse(decode_validated_text(document))
    headings: dict[int, str] = {}
    content_blocks: list[str] = []
    segments: list[ParsedSegment] = []

    def flush_segment() -> None:
        content = "\n\n".join(content_blocks).strip()
        content_blocks.clear()
        if not content:
            return

        section_path = [headings[level] for level in sorted(headings)]
        section_title = " > ".join(section_path) or None
        source_reference = f"《{document.original_filename}》"
        if section_title:
            source_reference = f"{source_reference} > {section_title}"
        segments.append(
            ParsedSegment(
                content=content,
                page_number=None,
                section_title=section_title,
                source_reference=source_reference,
                metadata={
                    "file_type": "markdown",
                    "section_path": section_path,
                },
            )
        )

    token_index = 0
    while token_index < len(tokens):
        token = tokens[token_index]
        if token.type == "heading_open":
            flush_segment()
            heading_level = int(token.tag.removeprefix("h"))
            heading_token = tokens[token_index + 1]
            heading_text = _inline_plain_text(heading_token)
            for level in [level for level in headings if level >= heading_level]:
                del headings[level]
            if heading_text:
                headings[heading_level] = heading_text
            token_index += 3
            continue

        if token.type == "inline":
            content = _inline_plain_text(token)
            if content:
                content_blocks.append(content)
        elif token.type in {"fence", "code_block"}:
            content = _normalize_block_text(token.content)
            if content:
                content_blocks.append(content)

        token_index += 1

    flush_segment()
    if not segments:
        raise KnowledgeDocumentError(
            KnowledgeDocumentErrorCode.NO_EXTRACTABLE_TEXT
        )
    return segments


def _inline_plain_text(token: Token) -> str:
    parts = []
    for child in token.children or []:
        if child.type in {"text", "code_inline", "image"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
    return _normalize_block_text("".join(parts))


def _normalize_block_text(text: str) -> str:
    normalized_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        normalized_line = re.sub(r"[^\S\n]+", " ", line).strip()
        if normalized_line:
            normalized_lines.append(normalized_line)
    return "\n".join(normalized_lines)
