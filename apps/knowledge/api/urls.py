"""URL routes for Knowledge Document management APIs."""

from django.urls import path

from .views import KnowledgeDocumentViewSet, KnowledgeSearchView


document_collection_view = KnowledgeDocumentViewSet.as_view(
    {"get": "list", "post": "create"}
)
document_detail_view = KnowledgeDocumentViewSet.as_view({"get": "retrieve"})
document_reindex_view = KnowledgeDocumentViewSet.as_view({"post": "reindex"})


urlpatterns = [
    path(
        "knowledge/search/",
        KnowledgeSearchView.as_view(),
        name="knowledge-search",
    ),
    path(
        "knowledge/documents/<int:pk>/reindex/",
        document_reindex_view,
        name="knowledge-document-reindex",
    ),
    path(
        "knowledge/documents/<int:pk>/",
        document_detail_view,
        name="knowledge-document-detail",
    ),
    path(
        "knowledge/documents/",
        document_collection_view,
        name="knowledge-document-list",
    ),
]
