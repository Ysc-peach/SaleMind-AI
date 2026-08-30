"""Pagination for Knowledge Document collections."""

from rest_framework.pagination import PageNumberPagination


class KnowledgeDocumentPagination(PageNumberPagination):
    """Keep the Admin document list at a predictable page size."""

    page_size = 20
