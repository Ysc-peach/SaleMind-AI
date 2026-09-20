"""Strict create input and bounded Solution Draft history representations."""

from rest_framework import serializers

from apps.sales.models import (
    SolutionDraftProvenance,
    SolutionDraftRecord,
    SolutionReturnReason,
    SolutionReview,
)
from apps.sales.services.solution_payloads import (
    SolutionPayloadError,
    deserialize_solution_payload,
)


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
            "schema_version",
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


class _SolutionDraftV1DetailSerializer(SolutionDraftListSerializer):
    workflow_id = serializers.UUIDField(
        source="generation_idempotency_key",
        read_only=True,
        allow_null=True,
    )
    provenance = SolutionDraftProvenanceSerializer(
        source="provenance_entries", many=True, read_only=True
    )

    class Meta(SolutionDraftListSerializer.Meta):
        fields = SolutionDraftListSerializer.Meta.fields + (
            "workflow_id",
            "draft_payload",
            "provenance",
        )
        read_only_fields = fields


class SolutionDraftDetailSerializer(SolutionDraftListSerializer):
    workflow_id = serializers.UUIDField(
        source="generation_idempotency_key",
        read_only=True,
        allow_null=True,
    )
    provenance = SolutionDraftProvenanceSerializer(
        source="provenance_entries", many=True, read_only=True
    )
    source_registry = serializers.SerializerMethodField()
    claim_sources = serializers.SerializerMethodField()

    class Meta(SolutionDraftListSerializer.Meta):
        fields = SolutionDraftListSerializer.Meta.fields + (
            "workflow_id",
            "draft_payload",
            "provenance",
            "source_registry",
            "claim_sources",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        if instance.schema_version == 1:
            return _SolutionDraftV1DetailSerializer(
                instance,
                context=self.context,
            ).data
        if instance.schema_version != 2:
            raise serializers.ValidationError("Unsupported Solution Draft schema version.")
        try:
            deserialize_solution_payload(instance.schema_version, instance.draft_payload)
        except SolutionPayloadError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        data = super().to_representation(instance)
        data.pop("provenance", None)
        return data

    def get_source_registry(self, instance):
        registry = {}
        for entry in instance.provenance_entries.all():
            registry.setdefault(entry.citation_label, {
                "source_id": entry.citation_label,
                "document_id": entry.source_document_id,
                "document_title": entry.source_document.title,
                "source_excerpt": entry.source_excerpt,
            })
        return list(registry.values())

    def get_claim_sources(self, instance):
        result = {}
        for entry in instance.provenance_entries.all():
            if not entry.claim_id:
                raise serializers.ValidationError("V2 claim provenance is incomplete.")
            labels = result.setdefault(entry.claim_id, [])
            if entry.citation_label not in labels:
                labels.append(entry.citation_label)
        return result


class SolutionReviewSubmitSerializer(serializers.Serializer):
    reviewer_id = serializers.IntegerField(min_value=1, required=False)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or not set(data) <= {"reviewer_id"}:
            raise serializers.ValidationError(
                {"non_field_errors": "Only an optional reviewer_id is accepted."}
            )
        return super().to_internal_value(data)


class SolutionReviewApproveSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")

    def to_internal_value(self, data):
        if not isinstance(data, dict) or not set(data) <= {"comment"}:
            raise serializers.ValidationError(
                {"non_field_errors": "Only an optional comment is accepted."}
            )
        return super().to_internal_value(data)


class SolutionReviewReturnSerializer(serializers.Serializer):
    return_reason = serializers.ChoiceField(choices=SolutionReturnReason.choices)
    comment = serializers.CharField(allow_blank=False, trim_whitespace=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {"return_reason", "comment"}:
            raise serializers.ValidationError(
                {"non_field_errors": "return_reason and comment are required."}
            )
        return super().to_internal_value(data)


class SolutionReviewSerializer(serializers.ModelSerializer):
    solution_draft = serializers.IntegerField(source="solution_draft_id", read_only=True)
    submitted_by = serializers.IntegerField(source="submitted_by_id", read_only=True)
    reviewer = serializers.IntegerField(source="reviewer_id", read_only=True)

    class Meta:
        model = SolutionReview
        fields = (
            "id",
            "solution_draft",
            "submitted_by",
            "reviewer",
            "status",
            "return_reason",
            "comment",
            "submitted_at",
            "decided_at",
        )
        read_only_fields = fields
