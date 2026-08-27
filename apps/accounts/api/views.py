"""Views for account APIs."""

from django.contrib.auth import get_user_model
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import UserRole

from .permissions import IsSales
from .serializers import CurrentUserSerializer, PresalesOptionSerializer


class CurrentUserView(RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = CurrentUserSerializer

    def get_object(self):
        return self.request.user


class PresalesOptionListView(ListAPIView):
    permission_classes = (IsAuthenticated, IsSales)
    serializer_class = PresalesOptionSerializer

    def get_queryset(self):
        return get_user_model().objects.filter(
            is_active=True,
            role=UserRole.PRESALES,
        ).order_by("username", "id")
