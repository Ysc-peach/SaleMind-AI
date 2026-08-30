"""Explicit request and safe response schemas for grounded RAG answers."""

from rest_framework import serializers

from apps.knowledge.api.serializers import RejectForbiddenFieldsMixin
from apps.knowledge.models import KnowledgeDocumentType


class RAGAnswerRequestSerializer(
    RejectForbiddenFieldsMixin,
    serializers.Serializer,
):
    """Accept only the user query and the optional document-type filter."""

    forbidden_fields = (
        "top_k",
        "provider",
        "model",
        "system_prompt",
        "messages",
        "api_key",
        "sources",
    )

    query = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=2000,
    )
    document_type = serializers.ChoiceField(
        choices=KnowledgeDocumentType.choices,
        required=False,
    )


class RAGSourceResponseSerializer(serializers.Serializer):
    """Expose authoritative citation metadata without chunk content or internals."""

    label = serializers.CharField(read_only=True)
    chunk_id = serializers.IntegerField(read_only=True)
    document_id = serializers.IntegerField(read_only=True)
    document_title = serializers.CharField(read_only=True)
    document_type = serializers.CharField(read_only=True)
    original_filename = serializers.CharField(read_only=True)
    page_number = serializers.IntegerField(read_only=True, allow_null=True)
    section_title = serializers.CharField(read_only=True, allow_null=True)
    source_reference = serializers.CharField(read_only=True)
    similarity = serializers.FloatField(read_only=True)


class RAGAnswerResponseSerializer(serializers.Serializer):
    """Serialize one grounded answer and its ranked source authority."""

    answer = serializers.CharField(read_only=True)
    sources = RAGSourceResponseSerializer(many=True, read_only=True)
