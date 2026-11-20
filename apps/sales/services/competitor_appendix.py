"""Deterministic comparison appendix for an approved export.

The appendix is built from data, not written by a model. Every cell is either an
approved fact of ours or a competitor's own approved statement with its source
link, so nothing in it can be invented, and nothing in it is a judgement about a
third party. A generator would have to phrase the comparison itself, and phrasing
is exactly what this pipeline refuses to do without evidence.
"""

from __future__ import annotations

from apps.sales.services.competitor_matrix import (
    GAP_MISSING_BOTH,
    GAP_MISSING_FACT,
    GAP_MISSING_STATEMENT,
    build_matrix,
)
from apps.sales.services.solution_export_document import (
    DocumentBlock,
    DocumentSection,
)

APPENDIX_TITLE = "附录：竞品公开陈述对照"
HEADER = ("比较维度", "竞品", "我方已批准事实", "竞品公开陈述（含来源）")

_GAP_REASONS = {
    GAP_MISSING_FACT: "缺我方已批准事实",
    GAP_MISSING_STATEMENT: "缺竞品可引用陈述",
    GAP_MISSING_BOTH: "双方均缺",
}

PREAMBLE = (
    "本附录仅并列我方已批准事实与竞品公开陈述，逐条附来源链接与发布日期；"
    "不构成对竞品的评价、优劣判断或能力贬损，未列出不等于对方不具备。"
)


def _cell(value: str) -> str:
    """Collapse whitespace so a long fact cannot distort the table layout."""

    return " ".join((value or "").split())


def _source_cell(statement: dict) -> str:
    published = statement.get("published_on")
    suffix = f"（发布于 {published}）" if published else ""
    return f"{_cell(statement['statement'])}｜{statement['source_url']}{suffix}"


def build_comparison_appendix(competitors) -> tuple[DocumentSection, ...]:
    """One table, or a note explaining why no row qualified."""

    matrix = build_matrix(competitors=competitors, limit=1)
    rows: list[tuple[str, ...]] = []
    omitted: list[str] = []

    for dimension in matrix["dimensions"]:
        for entry in dimension["competitors"]:
            if not entry["can_form"]:
                reason = _GAP_REASONS.get(entry["gap"], entry["gap"])
                omitted.append(
                    f"{dimension['label']}×{entry['competitor_name']}（{reason}）"
                )
                continue
            fact = entry["own_facts"][0]
            statement = entry["statements"][0]
            rows.append(
                (
                    dimension["label"],
                    entry["competitor_name"],
                    _cell(fact["statement"]),
                    _source_cell(statement),
                )
            )

    blocks: list[DocumentBlock] = [
        DocumentBlock("paragraph", PREAMBLE),
    ]
    if rows:
        blocks.append(DocumentBlock("table", rows=(HEADER, *rows)))
    if omitted:
        # Saying what was left out, and why, is the difference between a thin
        # comparison and a misleading one.
        blocks.append(
            DocumentBlock(
                "paragraph",
                "未纳入对照的维度（缺少可引用依据）：" + "；".join(omitted),
            )
        )
    return (DocumentSection(APPENDIX_TITLE, tuple(blocks)),)
