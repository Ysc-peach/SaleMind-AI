"""Shapes for competitors and their public statements."""

from rest_framework import serializers

from apps.sales.api.serializers import user_display_name
from apps.sales.models import Competitor, CompetitorDimension, CompetitorStatement


class CompetitorSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Competitor
        fields = (
            "id",
            "name",
            "aliases",
            "is_active",
            "created_by_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str:
        return user_display_name(obj.created_by)


class CompetitorCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    aliases = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )


class CompetitorUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    aliases = serializers.CharField(
        max_length=240, required=False, allow_blank=True
    )


class CompetitorStatementSerializer(serializers.ModelSerializer):
    competitor_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CompetitorStatement
        fields = (
            "id",
            "competitor",
            "competitor_name",
            "dimension",
            "statement",
            "source_url",
            "published_on",
            "captured_on",
            "status",
            "created_by_name",
            "reviewed_by_name",
            "reviewed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_competitor_name(self, obj) -> str:
        return obj.competitor.name

    def get_created_by_name(self, obj) -> str:
        return user_display_name(obj.created_by)

    def get_reviewed_by_name(self, obj) -> str:
        return user_display_name(obj.reviewed_by) if obj.reviewed_by else ""


class CompetitorStatementCreateSerializer(serializers.Serializer):
    dimension = serializers.ChoiceField(choices=CompetitorDimension.choices)
    statement = serializers.CharField(max_length=2000)
    source_url = serializers.CharField(max_length=500)
    published_on = serializers.DateField(required=False, allow_null=True)
    captured_on = serializers.DateField(required=False, allow_null=True)
