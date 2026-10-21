"""Views for Knowledge Document management and authenticated search."""

from rest_framework import mixins, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.throttling import ScopedActionThrottleMixin
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.knowledge.models import KnowledgeDocument
from apps.knowledge.services import indexing, search

from .errors import KnowledgeAPIError
from .pagination import KnowledgeDocumentPagination
from .permissions import IsBusinessAdmin, IsKnowledgeSearchUser
from .serializers import (
    KnowledgeDocumentCreateSerializer,
    KnowledgeDocumentReadSerializer,
    KnowledgeSearchRequestSerializer,
    KnowledgeSearchResultSerializer,
)


_REINDEX_CONFLICT_CODES = {
    KnowledgeDocumentErrorCode.INVALID_REINDEX_STATE.value,
    KnowledgeDocumentErrorCode.INDEXING_ALREADY_IN_PROGRESS.value,
    KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT.value,
}
_INITIAL_INDEX_CONFLICT_CODES = {
    KnowledgeDocumentErrorCode.INVALID_INDEXING_STATE.value,
    KnowledgeDocumentErrorCode.INDEXING_RUN_CONFLICT.value,
}
_EMBEDDING_CONFIGURATION_CODES = {
    KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED.value,
    KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER.value,
}


class KnowledgeDocumentViewSet(
    ScopedActionThrottleMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create and read Knowledge Documents without mutation or deletion."""

    queryset = KnowledgeDocument.objects.order_by("-updated_at", "-id")
    permission_classes = (IsBusinessAdmin,)
    parser_classes = (MultiPartParser, FormParser)
    pagination_class = KnowledgeDocumentPagination
    http_method_names = ["get", "post", "head", "options"]
    scoped_throttle_actions = {
        "create": "knowledge_write",
        "reindex": "knowledge_write",
    }

    def get_serializer_class(self):
        if getattr(self, "action", None) == "create":
            return KnowledgeDocumentCreateSerializer
        return KnowledgeDocumentReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = serializer.save(created_by=request.user)

        try:
            indexing.index_document(document.pk)
        except KnowledgeDocumentError as error:
            document.refresh_from_db()
            if document.status != KnowledgeDocument.Status.FAILED:
                error_status = (
                    status.HTTP_409_CONFLICT
                    if error.code in _INITIAL_INDEX_CONFLICT_CODES
                    else status.HTTP_422_UNPROCESSABLE_ENTITY
                )
                raise KnowledgeAPIError(error, status_code=error_status) from None

        document.refresh_from_db()
        output = KnowledgeDocumentReadSerializer(
            document,
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=status.HTTP_201_CREATED)

    def reindex(self, request, *args, **kwargs):
        document = self.get_object()
        try:
            document = indexing.reindex_document(document.pk)
        except KnowledgeDocumentError as error:
            error_status = (
                status.HTTP_409_CONFLICT
                if error.code in _REINDEX_CONFLICT_CODES
                else status.HTTP_422_UNPROCESSABLE_ENTITY
            )
            raise KnowledgeAPIError(error, status_code=error_status) from None

        output = KnowledgeDocumentReadSerializer(
            document,
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=status.HTTP_200_OK)


class KnowledgeSearchView(APIView):
    """Return exact vector matches with citation-safe source metadata."""

    permission_classes = (IsKnowledgeSearchUser,)
    parser_classes = (JSONParser,)

    def post(self, request):
        serializer = KnowledgeSearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            results = search.search_knowledge(**serializer.validated_data)
        except KnowledgeDocumentError as error:
            error_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.code in _EMBEDDING_CONFIGURATION_CODES
                else status.HTTP_502_BAD_GATEWAY
            )
            raise KnowledgeAPIError(error, status_code=error_status) from None

        output = KnowledgeSearchResultSerializer(results, many=True)
        return Response({"results": output.data}, status=status.HTTP_200_OK)
