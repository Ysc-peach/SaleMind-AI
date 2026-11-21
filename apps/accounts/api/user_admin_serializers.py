"""Shapes for administrator-managed user accounts.

Nothing here can set ``is_superuser`` or ``is_staff``: Django staff access is a
deployment concern (who may open /admin/), not a business role, and conflating
the two is how an operator ends up with more access than the job needs.
"""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.accounts.models import UserRole


class UserSummarySerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = get_user_model()
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_label",
            "is_active",
            "date_joined",
            "last_login",
        )
        read_only_fields = fields


class CreateUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=UserRole.choices)
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    first_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True
    )
    last_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True
    )


class UpdateUserSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True
    )
    last_name = serializers.CharField(
        max_length=150, required=False, allow_blank=True
    )


class ResetPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(trim_whitespace=False, write_only=True)
