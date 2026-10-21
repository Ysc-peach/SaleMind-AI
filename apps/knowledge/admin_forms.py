"""Small Admin confirmation forms; uploaded metadata remains server-controlled."""
from django import forms
from rest_framework.exceptions import APIException

from .api.serializers import KnowledgeDocumentCreateSerializer
from .models import KnowledgeDocumentType


class KnowledgeDocumentUploadForm(forms.Form):
    title = forms.CharField(label='文档标题', max_length=255)
    document_type = forms.ChoiceField(label='文档类型', choices=KnowledgeDocumentType.choices)
    source_file = forms.FileField(label='资料文件（TXT / Markdown / 可提取文字的 PDF）')

    def clean(self):
        cleaned = super().clean()
        forbidden = set(KnowledgeDocumentCreateSerializer.forbidden_fields) | {
            'last_index_run_id', 'approval_status', 'approved_by', 'approved_at',
        }
        if any(key in self.data or key in self.files for key in forbidden):
            raise forms.ValidationError('不能提交由服务器维护的状态、身份或索引字段。')
        if not all(key in cleaned for key in ('title', 'document_type', 'source_file')):
            return cleaned
        serializer = KnowledgeDocumentCreateSerializer(data=cleaned)
        try:
            serializer.is_valid(raise_exception=True)
        except APIException:
            raise forms.ValidationError('资料未通过文件或字段校验，请检查格式、大小、页数和内容。') from None
        self._upload_serializer = serializer
        return cleaned

    def save(self, *, actor):
        return self._upload_serializer.save(created_by=actor)


class DocumentIndexConfirmationForm(forms.Form):
    expected_index_run_id = forms.UUIDField(widget=forms.HiddenInput)


class FactExtractionConfirmationForm(DocumentIndexConfirmationForm):
    retry_after_attempt_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)


class ExtractionCancellationForm(forms.Form):
    confirm = forms.BooleanField(label='我确认撤销这次执行的结果写入资格', required=True)
