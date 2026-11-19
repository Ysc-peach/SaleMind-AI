"""Shapes for the case library."""

from rest_framework import serializers

from apps.sales.api.serializers import user_display_name
from apps.sales.models import CaseStudy, CaseStudySizeBand


class CaseStudySerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CaseStudy
        fields = (
            "id",
            "title",
            "industry",
            "size_band",
            "customer_name",
            "pain_points",
            "approach",
            "results",
            "referenceable",
            "is_active",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str:
        return user_display_name(obj.created_by)


class CaseStudyCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    industry = serializers.CharField(max_length=64)
    size_band = serializers.ChoiceField(choices=CaseStudySizeBand.choices)
    customer_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    pain_points = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    approach = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    results = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    referenceable = serializers.BooleanField(required=False, default=False)


class CaseStudyUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    industry = serializers.CharField(max_length=64, required=False)
    size_band = serializers.ChoiceField(
        choices=CaseStudySizeBand.choices, required=False
    )
    customer_name = serializers.CharField(
        max_length=120, required=False, allow_blank=True
    )
    pain_points = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    approach = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    results = serializers.CharField(
        max_length=4000, required=False, allow_blank=True
    )
    referenceable = serializers.BooleanField(required=False)
