"""A "related cases" page for the export, assembled from the case library.

Deliberately not written by the model. A case is our own claim about our own
delivery record; letting the model phrase it invites exactly the sentences nobody
can defend. The page is data: one paragraph per case, the customer name only when
that customer agreed to be named.
"""

from __future__ import annotations

from apps.sales.services.solution_export_document import (
    DocumentBlock,
    DocumentSection,
)

TITLE = "相关案例"
PREAMBLE = (
    "以下为本公司已交付的同类项目，按行业与客户规模排序；"
    "未标注客户名称的案例，客户未授权对外点名，因此以匿名方式列出。"
)
MAX_CASES = 3
_CELL_LIMIT = 160


def _shorten(text: str) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= _CELL_LIMIT:
        return cleaned
    return cleaned[: _CELL_LIMIT - 1] + "…"


def _customer(case) -> str:
    # The permission flag decides this, not whether a name happens to be filled
    # in: a name typed in years ago is not consent.
    if case.referenceable and case.customer_name:
        return case.customer_name
    return "匿名客户"


def build_case_section(cases) -> tuple[DocumentSection, ...]:
    chosen = list(cases)[:MAX_CASES]
    if not chosen:
        return ()

    blocks: list[DocumentBlock] = [DocumentBlock("paragraph", PREAMBLE)]
    for case in chosen:
        label = (
            f"{case.title}（{case.get_size_band_display()}·{_customer(case)}）"
        )
        details = "；".join(
            item
            for item in (
                f"痛点：{_shorten(case.pain_points)}" if case.pain_points else "",
                f"做法：{_shorten(case.approach)}" if case.approach else "",
                f"结果：{_shorten(case.results)}" if case.results else "",
            )
            if item
        )
        blocks.append(
            DocumentBlock("paragraph", f"{label} {details}".strip())
        )
    return (DocumentSection(TITLE, tuple(blocks)),)
