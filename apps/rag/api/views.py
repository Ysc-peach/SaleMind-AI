"""Grounded RAG Answer API view."""

from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.knowledge.api.permissions import IsKnowledgeSearchUser
from apps.knowledge.exceptions import (
    KnowledgeDocumentError,
    KnowledgeDocumentErrorCode,
)
from apps.llm.exceptions import LLMErrorCode, LLMProviderError
from apps.rag.exceptions import RAGServiceError
from apps.rag.services import answering

from .errors import RAGDomainAPIError, RAGRequestValidationError
from .serializers import RAGAnswerRequestSerializer, RAGAnswerResponseSerializer


_KNOWLEDGE_CONFIGURATION_CODES = {
    KnowledgeDocumentErrorCode.EMBEDDING_NOT_CONFIGURED.value,
    KnowledgeDocumentErrorCode.UNSUPPORTED_EMBEDDING_PROVIDER.value,
}
_LLM_CONFIGURATION_CODES = {
    LLMErrorCode.LLM_NOT_CONFIGURED.value,
    LLMErrorCode.UNSUPPORTED_LLM_PROVIDER.value,
}


class RAGAnswerView(APIView):
    """Generate one grounded answer through the existing RAG service."""

    permission_classes = (IsKnowledgeSearchUser,)
    parser_classes = (JSONParser,)

    def post(self, request):
        try:
            request_data = request.data
        except ParseError:
            raise RAGRequestValidationError() from None

        request_serializer = RAGAnswerRequestSerializer(data=request_data)
        if not request_serializer.is_valid():
            raise RAGRequestValidationError()

        try:
            result = answering.answer_question(**request_serializer.validated_data)
        except KnowledgeDocumentError as error:
            error_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.code in _KNOWLEDGE_CONFIGURATION_CODES
                else status.HTTP_502_BAD_GATEWAY
            )
            raise RAGDomainAPIError(error, status_code=error_status) from None
        except LLMProviderError as error:
            error_status = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.code in _LLM_CONFIGURATION_CODES
                else status.HTTP_502_BAD_GATEWAY
            )
            raise RAGDomainAPIError(error, status_code=error_status) from None
        except RAGServiceError as error:
            raise RAGDomainAPIError(
                error,
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from None

        response_payload = {
            "answer": result.answer,
            "sources": [
                _source_payload(source, rank=rank)
                for rank, source in enumerate(result.sources, start=1)
            ],
        }
        response_serializer = RAGAnswerResponseSerializer(response_payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


def _source_payload(source, *, rank: int) -> dict:
    """Whitelist authoritative fields and derive labels from retrieval rank."""

    return {
        "label": f"S{rank}",
        "chunk_id": source.chunk_id,
        "document_id": source.document_id,
        "document_title": source.document_title,
        "document_type": source.document_type,
        "original_filename": source.original_filename,
        "page_number": source.page_number,
        "section_title": source.section_title,
        "source_reference": source.source_reference,
        "similarity": source.similarity,
    }
