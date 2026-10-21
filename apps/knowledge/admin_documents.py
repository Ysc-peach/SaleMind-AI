"""Read-only document Admin with explicit, separately authorized operations."""
from urllib.parse import urlencode

from django.contrib import admin
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.urls import reverse
from django.utils.html import format_html

from .models import GroundingFactExtractionAttempt, KnowledgeDocument
from .admin_document_operations import DocumentOperationsMixin
from .exceptions import KnowledgeDocumentError, KnowledgeDocumentErrorCode
from .services.grounding_fact_attempts import SAFE_MESSAGES
from .services.grounding_fact_approval import actor_can_review_grounding_facts


class FactExtractionAttemptInline(admin.TabularInline):
    model = GroundingFactExtractionAttempt
    fields = ('index_run_id', 'status', 'requested_by', 'started_at', 'finished_at',
              'safe_error', 'proposed_count', 'cancel_link')
    readonly_fields = fields
    extra = 0
    can_delete = False
    ordering = ('-pk',)

    def has_view_permission(self, request, obj=None):
        return actor_can_review_grounding_facts(request.user)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='执行操作')
    def cancel_link(self, obj):
        if obj.status != 'running':
            return '只读历史记录'
        url = reverse('admin:knowledge_knowledgedocument_cancel_extraction', args=[obj.document_id, obj.pk])
        return format_html('<a href="{}">核对并取消</a>', url)

    @admin.display(description='安全错误说明')
    def safe_error(self, obj):
        if not obj.error_code:
            return '—'
        return SAFE_MESSAGES.get(obj.error_code, '错误类型未识别，请联系维护人员核对；未展示原始错误。')


class KnowledgeDocumentAdmin(DocumentOperationsMixin, admin.ModelAdmin):
    list_display = ('title', 'document_type', 'status', 'extraction_overview', 'fact_review_link')
    list_filter = ('status', 'document_type')
    search_fields = ('title', 'original_filename')
    ordering = ('-created_at', '-pk')
    actions = None
    inlines = (FactExtractionAttemptInline,)
    fields = ('title', 'document_type', 'original_filename', 'mime_type', 'file_size',
              'status', 'indexing_error', 'chunk_count', 'last_indexed_at', 'created_by', 'created_at',
              'extraction_overview', 'fact_review_link')
    readonly_fields = fields
    change_form_template = 'admin/knowledge/knowledgedocument/change_form.html'
    change_list_template = 'admin/knowledge/knowledgedocument/change_list.html'

    def has_module_permission(self, request):
        return actor_can_review_grounding_facts(request.user)

    def has_view_permission(self, request, obj=None):
        return actor_can_review_grounding_facts(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        latest = GroundingFactExtractionAttempt.objects.filter(
            document_id=OuterRef('pk'), index_run_id=OuterRef('last_index_run_id'),
        ).order_by('-pk')
        current = Q(grounding_facts__source_index_run_id=F('last_index_run_id'))
        return super().get_queryset(request).select_related('created_by').annotate(
            current_attempt_status=Subquery(latest.values('status')[:1]),
            current_attempt_id=Subquery(latest.values('pk')[:1]),
            current_proposed_count=Subquery(latest.values('proposed_count')[:1]),
            current_fact_count=Count('grounding_facts', filter=current, distinct=True),
            pending_fact_count=Count('grounding_facts', filter=current & Q(
                grounding_facts__approval_status='proposed', grounding_facts__is_stale=False), distinct=True),
            approved_fact_count=Count('grounding_facts', filter=current & Q(
                grounding_facts__approval_status='approved', grounding_facts__is_stale=False), distinct=True),
            rejected_fact_count=Count('grounding_facts', filter=current & Q(
                grounding_facts__approval_status='rejected'), distinct=True),
        )

    @admin.display(description='事实抽取与审核状态')
    def extraction_overview(self, obj):
        if obj.status == 'failed':
            return '索引失败，请检查后重新上传'
        if obj.status != 'ready':
            return '尚未完成索引'
        if obj.indexing_run_id is not None:
            return '索引重建中，暂不能抽取'
        status = getattr(obj, 'current_attempt_status', None)
        if status == 'running':
            return '抽取中；如执行中断，状态未确认，请核对后显式取消'
        if status == 'failed':
            return '抽取失败，需要明确确认重试'
        if status == 'cancelled':
            return '已取消，需要明确确认重新抽取'
        if status == 'succeeded' and not obj.current_proposed_count:
            return '抽取成功，无候选事实；不等于企业已具备相关能力'
        if status == 'succeeded' or getattr(obj, 'current_fact_count', 0):
            prefix = '抽取成功' if status == 'succeeded' else '已有历史事实'
            return (f'{prefix}；待审核 {obj.pending_fact_count}，已批准 {obj.approved_fact_count}，'
                    f'已拒绝 {obj.rejected_fact_count}。已批准事实仍须通过当前来源与准入校验。')
        return '索引就绪，尚未抽取'

    @admin.display(description='事实审核')
    def fact_review_link(self, obj):
        url = reverse('admin:knowledge_enterprisegroundingfact_changelist')
        return format_html('<a href="{}?{}">查看该文档的事实与审核记录</a>', url,
                           urlencode({'source_document__exact': obj.pk}))

    @admin.display(description='索引安全错误说明')
    def indexing_error(self, obj):
        if not obj.error_code:
            return '—'
        try:
            code = KnowledgeDocumentErrorCode(obj.error_code)
        except ValueError:
            return '索引错误类型未识别，请联系维护人员检查。'
        return f'{code.value}: {KnowledgeDocumentError(code).safe_message}'
