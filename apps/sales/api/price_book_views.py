"""Read-only price book.

Writing happens in the Django Admin, because a price edit is a commercial act
rather than a form submission: it should be rare, deliberate and recorded with
the person who did it. Quotes freeze the price they used, so changing the book
never rewrites history.
"""

from datetime import date

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.sales.api.serializers import PriceBookEntrySerializer
from apps.sales.services import price_book

from .pagination import DefaultPageNumberPagination
from .permissions import SolutionDraftPermission


def _date_param(value: str) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({"as_of": "Expected an ISO date (YYYY-MM-DD)."}) from None


class PriceBookAPIView(APIView):
    permission_classes = (SolutionDraftPermission,)
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        params = request.query_params
        include_inactive = (params.get("include_inactive") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        if include_inactive and request.user.role != UserRole.ADMIN:
            raise PermissionDenied("只有管理员可以查看已停用的价目条目。")
        queryset = price_book.current_entries(
            as_of=_date_param(params.get("as_of", "")),
            sku=(params.get("sku") or "").strip(),
            search=(params.get("q") or "").strip(),
            include_inactive=include_inactive,
        )
        paginator = DefaultPageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            PriceBookEntrySerializer(page, many=True).data
        )
