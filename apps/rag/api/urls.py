"""URL routes for grounded RAG answers."""

from django.urls import path

from .views import RAGAnswerView


urlpatterns = [
    path("rag/answer/", RAGAnswerView.as_view(), name="rag-answer"),
]
