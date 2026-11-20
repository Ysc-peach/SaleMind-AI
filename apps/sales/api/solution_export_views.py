"""Authenticated, non-streaming approved solution document download."""
import logging

from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.api.permissions import SolutionDraftPermission
from apps.sales.models import Competitor
from apps.sales.services.competitor_appendix import build_comparison_appendix
from apps.sales.services.solution_export_guard import (
    load_export_snapshot, revalidate_export_snapshot, SolutionExportError,
)
from apps.sales.services.solution_export_document import build_export_document
from apps.sales.services.solution_export_rendering import render_export

logger = logging.getLogger(__name__)
MIMES = {'pdf':'application/pdf','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


MAX_APPENDIX_COMPETITORS = 5


def _comparison_appendix(request):
    """Optional appendix, built only when the caller names competitors.

    The reviewed draft stays exactly what it was; the appendix is assembled from
    approved facts and approved competitor statements, and its own preamble says
    so. Nothing here is model-written.
    """

    raw_ids = request.query_params.getlist("competitor")
    if not raw_ids:
        return ()
    try:
        wanted = [int(value) for value in raw_ids]
    except (TypeError, ValueError):
        raise ValidationError({"competitor": "Expected competitor ids."}) from None
    competitors = list(
        Competitor.objects.filter(pk__in=wanted)
        .order_by("name", "id")[:MAX_APPENDIX_COMPETITORS]
    )
    if len(competitors) != len(set(wanted)):
        raise NotFound()
    return build_comparison_appendix(competitors)


class SolutionExportAPIView(APIView):
    permission_classes = (SolutionDraftPermission,)
    http_method_names = ['get','head','options']

    def get(self,request,solution_id):
        file_type = request.query_params.get('file_type','')
        now = timezone.now()
        version = None
        try:
            snapshot = load_export_snapshot(actor_id=request.user.pk,solution_id=solution_id,exported_at=now)
            version = snapshot.version
            if len(request.query_params.getlist('file_type')) != 1 or file_type not in MIMES:
                raise SolutionExportError('solution_export_unsupported_format')
            appendix = _comparison_appendix(request)
            try:
                document = build_export_document(snapshot, appendix)
                content = render_export(document,file_type=file_type)
            except SolutionExportError:
                raise
            except Exception as error:
                # A payload or template defect is not an infrastructure outage.
                # Never surface the renderer's message: it can contain正文.
                raise SolutionExportError('solution_export_invalid_payload') from error
            with transaction.atomic():
                revalidate_export_snapshot(snapshot,actor_id=request.user.pk)
            response = HttpResponse(content,content_type=MIMES[file_type])
            response['Content-Disposition'] = f'attachment; filename="SalesMind-solution-{solution_id}-v{version}.{file_type}"'
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Content-Length'] = str(len(content))
            logger.info('solution_export actor=%s solution=%s version=%s file_type=%s result=success time=%s',
                request.user.pk,solution_id,version,file_type,now.isoformat())
            return response
        except (NotFound,PermissionDenied,ValidationError):
            raise
        except Exception as error:
            code = error.code if isinstance(error,SolutionExportError) else 'solution_export_unavailable'
            status = error.status if isinstance(error,SolutionExportError) else 503
            # No cause, traceback, raw file_type input, source excerpt or document body.
            logger.info('solution_export actor=%s solution=%s version=%s file_type=%s result=%s time=%s',
                request.user.pk,solution_id,version,file_type if file_type in MIMES else 'invalid',code,now.isoformat())
            response = Response({'code':code},status=status)
            response['Cache-Control'] = 'private, no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
