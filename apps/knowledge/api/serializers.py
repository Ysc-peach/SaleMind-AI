"""Explicit serializers for safe Knowledge Document management."""

from hashlib import sha256

from rest_framework import serializers

from apps.knowledge.exceptions import KnowledgeDocumentError
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.parsers.validation import validate_document_file

from .errors import KnowledgeAPIError


class RejectForbiddenFieldsMixin:
    """Return 400 when a client attempts to set server-controlled fields."""

    forbidden_fields = ()

    def to_internal_value(self, data):
        errors = {
            field: "This field is controlled by the server."
            for field in self.forbidden_fields
            if field in data
        }
        if errors:
            raise serializers.ValidationError(errors)
        return super().to_internal_value(data)


class KnowledgeDocumentReadSerializer(serializers.ModelSerializer):
    """Expose safe document metadata without files, chunks, or run IDs."""

    is_indexing = serializers.SerializerMethodField()

    class Meta:
        model = KnowledgeDocument
        fields = (
            "id",
            "title",
            "document_type",
            "original_filename",
            "mime_type",
            "file_size",
            "status",
            "error_code",
            "error_message",
            "embedding_provider",
            "embedding_model",
            "embedding_dimensions",
            "chunk_count",
            "is_indexing",
            "processing_started_at",
            "last_indexed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_is_indexing(self, obj):
        return bool(
            obj.indexing_run_id is not None
            and obj.processing_started_at is not None
        )


class KnowledgeDocumentCreateSerializer(
    RejectForbiddenFieldsMixin,
    serializers.ModelSerializer,
):
    """Accept only upload inputs and derive trusted file metadata."""

    forbidden_fields = (
        "id",
        "original_filename",
        "mime_type",
        "file_size",
        "checksum_sha256",
        "status",
        "error_code",
        "error_message",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
        "chunk_count",
        "indexing_run_id",
        "processing_started_at",
        "last_indexed_at",
        "created_by",
        "created_at",
        "updated_at",
    )

    class Meta:
        model = KnowledgeDocument
        fields = ("title", "document_type", "source_file")

    def validate(self, attrs):
        source_file = attrs["source_file"]
        try:
            validated_file = validate_document_file(
                source_file,
                source_file.name,
            )
        except KnowledgeDocumentError as error:
            raise KnowledgeAPIError(error) from None
        finally:
            try:
                source_file.seek(0)
            except (AttributeError, OSError, TypeError, ValueError):
                pass

        self._validated_file = validated_file
        return attrs

    def create(self, validated_data):
        validated_file = self._validated_file
        return KnowledgeDocument.objects.create(
            **validated_data,
            original_filename=validated_file.original_filename,
            mime_type=validated_file.mime_type,
            file_size=len(validated_file.data),
            checksum_sha256=sha256(validated_file.data).hexdigest(),
        )
