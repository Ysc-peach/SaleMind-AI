"""Quote endpoints: read the priced rows, edit them, and never re-price silently."""

from decimal import ROUND_HALF_UP, Decimal

from rest_framework import status, viewsets
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.sales.models import PriceBookEntry, QuoteLine
from apps.sales.services import quotes as service
from apps.sales.services.quotes import QuoteError, QuoteErrorCode
from apps.sales.services.visibility import visible_opportunities_for

from .opportunity_access import OpportunityVisibilityMixin
from .permissions import SolutionDraftPermission

CENT = Decimal("0.01")


class QuoteOutdated(APIException):
    status_code = 409
    default_detail = "报价对应的方案版本已过期，请先重新绑定当前版本再导出或修改。"
    default_code = "quote_outdated"


class QuoteNoDraft(APIException):
    status_code = 409
    default_detail = "该商机还没有方案版本，先生成方案再报价。"
    default_code = "quote_no_draft"


class QuoteMissing(APIException):
    status_code = 409
    default_detail = "该方案还没有报价，无法导出报价页。"
    default_code = "quote_missing"


def _translate(error: QuoteError):
    if error.code == QuoteErrorCode.FORBIDDEN:
        raise PermissionDenied("只有该商机的销售负责人或管理员可以修改报价。")
    if error.code == QuoteErrorCode.NO_DRAFT:
        raise QuoteNoDraft()
    if error.code == QuoteErrorCode.OUTDATED:
        raise QuoteOutdated()
    raise ValidationError({"detail": "报价参数不符合要求。"})


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def serialize_line(line: QuoteLine) -> dict:
    return {
        "id": line.pk,
        "sku": line.sku,
        "name": line.name,
        "unit": line.unit,
        "quantity": str(line.quantity),
        "unit_price": str(line.unit_price),
        "currency": line.currency,
        "subtotal": _money(line.unit_price * line.quantity),
        "removed_at": line.removed_at,
        "created_at": line.created_at,
    }


def serialize_quote(quote) -> dict:
    totals = service.totals(quote)
    return {
        "id": quote.pk,
        "opportunity": quote.opportunity_id,
        "solution_draft": quote.solution_draft_id,
        "discount_percent": str(quote.discount_percent),
        "note": quote.note,
        "currency": totals["currency"],
        "lines": [
            serialize_line(line) for line in service.active_lines(quote)
        ],
        "line_count": totals["line_count"],
        "subtotal": str(totals["subtotal"]),
        "discount_amount": str(totals["discount_amount"]),
        "total": str(totals["total"]),
        "updated_at": quote.updated_at,
    }


class OpportunityQuoteViewSet(
    OpportunityVisibilityMixin, viewsets.GenericViewSet
):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    lookup_url_kwarg = "opportunity_id"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def retrieve_quote(self, request, *args, **kwargs):
        opportunity = self.get_object()
        quote = service.get_quote(opportunity)
        if quote is None:
            return Response({"opportunity": opportunity.pk, "quote": None})
        return Response(serialize_quote(quote))

    def update_quote(self, request, *args, **kwargs):
        opportunity = self.get_object()
        quote = service.ensure_quote(opportunity=opportunity, actor=request.user)
        payload = request.data or {}
        try:
            if "discount_percent" in payload:
                quote = service.set_discount(
                    quote,
                    actor=request.user,
                    percent=payload["discount_percent"],
                    note=payload.get("note"),
                )
            elif "note" in payload:
                quote = service.set_discount(
                    quote,
                    actor=request.user,
                    percent=quote.discount_percent,
                    note=payload["note"],
                )
        except QuoteError as error:
            _translate(error)
        return Response(serialize_quote(quote))

    def add_line(self, request, *args, **kwargs):
        opportunity = self.get_object()
        payload = request.data or {}
        entry_id = payload.get("price_book_entry")
        if not isinstance(entry_id, int):
            raise ValidationError({"price_book_entry": "Expected an integer."})
        entry = PriceBookEntry.objects.filter(
            pk=entry_id, is_active=True
        ).first()
        if entry is None:
            raise NotFound()
        try:
            quote = service.ensure_quote(
                opportunity=opportunity, actor=request.user
            )
            service.add_line(
                quote=quote,
                actor=request.user,
                entry=entry,
                quantity=payload.get("quantity", 1),
            )
        except QuoteError as error:
            _translate(error)
        return Response(
            serialize_quote(quote), status=status.HTTP_201_CREATED
        )

    def rebind(self, request, *args, **kwargs):
        opportunity = self.get_object()
        quote = service.get_quote(opportunity)
        if quote is None:
            raise NotFound()
        try:
            quote = service.rebind(quote, actor=request.user)
        except QuoteError as error:
            _translate(error)
        return Response(serialize_quote(quote))


class QuoteLineViewSet(viewsets.GenericViewSet):
    permission_classes = (SolutionDraftPermission,)
    parser_classes = (JSONParser,)
    http_method_names = ["patch", "post", "head", "options"]

    def _line(self) -> QuoteLine:
        line = (
            QuoteLine.objects.select_related("quote__opportunity")
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if line is None or not visible_opportunities_for(
            self.request.user
        ).filter(pk=line.quote.opportunity_id).exists():
            raise NotFound()
        return line

    def partial_update(self, request, *args, **kwargs):
        line = self._line()
        payload = request.data or {}
        if "quantity" not in payload:
            raise ValidationError({"quantity": "This field is required."})
        try:
            line = service.set_quantity(
                line, actor=request.user, quantity=payload["quantity"]
            )
        except QuoteError as error:
            _translate(error)
        return Response(serialize_line(line))

    def remove(self, request, *args, **kwargs):
        line = self._line()
        try:
            line = service.remove_line(line, actor=request.user)
        except QuoteError as error:
            _translate(error)
        return Response(serialize_line(line))
