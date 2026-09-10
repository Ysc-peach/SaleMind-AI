"""Strict business-action inputs for Solution workflow transport APIs."""

from rest_framework import serializers

from apps.sales.models import SolutionReturnReason


class SolutionWorkflowStartSerializer(serializers.Serializer):
    analysis_id = serializers.IntegerField(min_value=1)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != {"analysis_id"}:
            raise serializers.ValidationError(
                {"non_field_errors": "Only an explicit analysis_id is accepted."}
            )
        return super().to_internal_value(data)


class SolutionWorkflowResumeSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=(
            "SUBMIT_FOR_REVIEW",
            "APPROVE",
            "REQUEST_REVISION",
        )
    )
    return_reason = serializers.ChoiceField(
        choices=(
            "CUSTOMER_INFO_REQUIRED",
            "TECHNICAL_REVISION_REQUIRED",
        ),
        required=False,
    )
    comment = serializers.CharField(required=False, allow_blank=False, trim_whitespace=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("A business action object is required.")
        action = data.get("action")
        expected = (
            {"action", "return_reason", "comment"}
            if action == "REQUEST_REVISION"
            else {"action"}
        )
        if set(data) != expected:
            raise serializers.ValidationError(
                {"non_field_errors": "Only fields required by the selected action are accepted."}
            )
        result = super().to_internal_value(data)
        if action == "REQUEST_REVISION":
            result["return_reason"] = {
                "CUSTOMER_INFO_REQUIRED": SolutionReturnReason.CUSTOMER_INFO_REQUIRED,
                "TECHNICAL_REVISION_REQUIRED": SolutionReturnReason.TECHNICAL_REVISION_REQUIRED,
            }[result["return_reason"]]
        return result
