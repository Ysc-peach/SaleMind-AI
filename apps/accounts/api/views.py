"""Views for account APIs."""

from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import IsAuthenticated

from .serializers import CurrentUserSerializer


class CurrentUserView(RetrieveAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = CurrentUserSerializer

    def get_object(self):
        return self.request.user
