"""Empty command input and explicit, read-only analysis history representations."""

from rest_framework import serializers

from apps.sales.models import OpportunityRequirementAnalysis


class EmptyAnalysisRequestSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or data:
            raise serializers.ValidationError("An empty object is required.")
        return {}


class RequirementAnalysisDetailSerializer(serializers.ModelSerializer):
    opportunity_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = OpportunityRequirementAnalysis
        fields = (
            "id", "opportunity_id", "summary", "requirements", "conflicts", "clarifying_questions",
            "source_raw_requirement", "source_context", "analysis_version", "llm_provider",
            "llm_model", "created_by_id", "created_at",
        )
        read_only_fields = fields


class RequirementAnalysisListSerializer(serializers.ModelSerializer):
    created_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = OpportunityRequirementAnalysis
        fields = (
            "id", "summary", "analysis_version", "llm_provider", "llm_model", "created_by_id", "created_at",
        )
        read_only_fields = fields
