"""Strict create input and bounded Solution Draft history representations."""

from rest_framework import serializers

from apps.sales.models import SolutionDraftProvenance, SolutionDraftRecord


class SolutionDraftCreateSerializer(serializers.Serializer):
    analysis_id = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {"analysis_id"}:
            raise serializers.ValidationError(
                {"non_field_errors": "Only an explicit analysis_id is accepted."}
            )
        return super().to_internal_value(data)


class SolutionDraftListSerializer(serializers.ModelSerializer):
    opportunity = serializers.IntegerField(source="opportunity_id", read_only=True)
    analysis_id = serializers.IntegerField(source="requirement_analysis_id", read_only=True)
    created_by = serializers.IntegerField(source="created_by_id", read_only=True)

    class Meta:
        model = SolutionDraftRecord
        fields = (
            "id",
            "opportunity",
            "analysis_id",
            "version",
            "title",
            "review_status",
            "is_stale",
            "stale_reasons",
            "created_by",
            "created_at",
        )
        read_only_fields = fields


class SolutionDraftProvenanceSerializer(serializers.ModelSerializer):
    enterprise_grounding_fact_id = serializers.IntegerField(read_only=True)
    source_document_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SolutionDraftProvenance
        fields = (
            "statement_path",
            "citation_label",
            "enterprise_grounding_fact_id",
            "source_document_id",
            "source_chunk_id",
            "source_index_run_id",
            "source_content_hash",
            "source_excerpt",
        )
        read_only_fields = fields


class SolutionDraftDetailSerializer(SolutionDraftListSerializer):
    provenance = SolutionDraftProvenanceSerializer(
        source="provenance_entries", many=True, read_only=True
    )

    class Meta(SolutionDraftListSerializer.Meta):
        fields = SolutionDraftListSerializer.Meta.fields + (
            "draft_payload",
            "provenance",
        )
        read_only_fields = fields
