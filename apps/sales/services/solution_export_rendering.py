"""Bounded in-memory export dispatch with controlled failures."""
from io import BytesIO
from typing import Literal
from apps.sales.services.solution_export_guard import SolutionExportError
from apps.sales.services.solution_export_document import ExportDocument

MAX_EXPORT_BYTES = 10 * 1024 * 1024


class BoundedBytesIO(BytesIO):
    def __init__(self, *, limit=MAX_EXPORT_BYTES):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise SolutionExportError('solution_export_too_large')
        return super().write(data)

    def truncate(self, size=None):
        if (self.tell() if size is None else size) > self.limit:
            raise SolutionExportError('solution_export_too_large')
        return super().truncate(size)


def render_export(document: ExportDocument, *, file_type: Literal['docx','pdf']) -> bytes:
    if file_type not in {'docx','pdf'}:
        raise SolutionExportError('solution_export_unsupported_format')
    try:
        if file_type == 'docx':
            from apps.sales.services.solution_export_docx import render_docx
            return render_docx(document)
        from apps.sales.services.solution_export_pdf import render_pdf
        return render_pdf(document)
    except SolutionExportError:
        raise
    except Exception:
        # Never log the renderer's message/stack: it can contain document text.
        # A renderer defect is a payload problem, not an infrastructure outage.
        raise SolutionExportError('solution_export_invalid_payload') from None
