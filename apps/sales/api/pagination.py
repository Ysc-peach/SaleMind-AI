"""Pagination used by sales-domain collection endpoints."""

from rest_framework.pagination import PageNumberPagination


class DefaultPageNumberPagination(PageNumberPagination):
    """Keep customer and opportunity collections at a predictable page size."""

    page_size = 20
