"""The quote page appended to an export.

Built from stored lines, so the number in the document is the number that was
priced — not a recomputation against today's price book.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from apps.sales.services import quotes
from apps.sales.services.solution_export_document import (
    DocumentBlock,
    DocumentSection,
)

CENT = Decimal("0.01")
TITLE = "报价（未含税）"
HEADER = ("物料编码", "名称", "单位", "数量", "单价（未含税）", "小计")
PREAMBLE = (
    "以下金额为未含税参考价，按报价时的价目条目计算；"
    "折扣须按公司授权规则审批，正式报价以商务合同为准。"
)


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def build_quote_section(quote) -> tuple[DocumentSection, ...]:
    lines = list(quotes.active_lines(quote))
    if not lines:
        return ()

    totals = quotes.totals(quote)
    rows = [HEADER]
    for line in lines:
        rows.append(
            (
                line.sku,
                line.name,
                line.unit,
                str(line.quantity),
                str(line.unit_price),
                _money(line.unit_price * line.quantity),
            )
        )

    summary = (
        f"小计 {_money(totals['subtotal'])}；"
        f"折扣 {totals['discount_percent']}%（折让 {_money(totals['discount_amount'])}）；"
        f"合计 {_money(totals['total'])} {totals['currency']}（未含税）"
    )
    blocks = [
        DocumentBlock("paragraph", PREAMBLE),
        DocumentBlock("table", rows=tuple(rows)),
        DocumentBlock("paragraph", summary),
    ]
    if quote.note:
        blocks.append(DocumentBlock("paragraph", f"备注：{quote.note}"))
    return (DocumentSection(TITLE, tuple(blocks)),)
