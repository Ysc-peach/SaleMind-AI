"""Explicit Admin operations live outside the default change-form transaction."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.views.decorators.http import require_http_methods

from .admin_forms import (
    KnowledgeDocumentUploadForm, DocumentIndexConfirmationForm,
    FactExtractionConfirmationForm, ExtractionCancellationForm,
)
from .exceptions import KnowledgeDocumentError
from .services import indexing
from .services.grounding_fact_attempts import (
    FactExtractionOperationError, require_actor, require_no_outer_transaction, cancel_extraction,
)
from .services.grounding_fact_operations import run_document_fact_extraction


class DocumentOperationsMixin:
    def get_urls(self):
        def operation(view):
            return transaction.non_atomic_requests(
                self.admin_site.admin_view(require_http_methods(['GET', 'POST'])(view)))
        return [
            path('upload/', operation(self.upload_document), name='knowledge_knowledgedocument_upload'),
            path('<int:object_id>/reindex/', operation(self.reindex_document),
                 name='knowledge_knowledgedocument_reindex'),
            path('<int:object_id>/extract/', operation(self.extract_document_facts),
                 name='knowledge_knowledgedocument_extract'),
            path('<int:object_id>/extractions/<int:attempt_id>/cancel/', operation(self.cancel_document_extraction),
                 name='knowledge_knowledgedocument_cancel_extraction'),
        ] + super().get_urls()

    def _actor(self, request):
        try:
            return require_actor(request.user.pk)
        except FactExtractionOperationError:
            raise PermissionDenied from None

    def _operation_page(self, request, *, title, form, explanation, document=None, upload=False):
        context = {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': title, 'form': form, 'explanation': explanation,
            'document': document, 'back_url': self._document_url(document),
        }
        template = 'upload.html' if upload else 'operation_confirm.html'
        return TemplateResponse(request, 'admin/knowledge/knowledgedocument/'+template, context)

    def _document_url(self, document=None):
        if document is None:
            return reverse('admin:knowledge_knowledgedocument_changelist')
        return reverse('admin:knowledge_knowledgedocument_change', args=[document.pk])

    def upload_document(self, request):
        actor = self._actor(request)
        form = KnowledgeDocumentUploadForm(
            request.POST if request.method == 'POST' else None,
            request.FILES if request.method == 'POST' else None,
        )
        if request.method == 'POST' and form.is_valid():
            document = None
            try:
                require_no_outer_transaction()
                actor = self._actor(request)
                document = form.save(actor=actor)
                indexing.index_document(document.pk)
            except FactExtractionOperationError as error:
                form.add_error(None, error.safe_message)
            except KnowledgeDocumentError:
                self._actor(request)
                if document is not None:
                    messages.error(request, '索引未完成，已保留文档及安全错误状态；请检查后重新上传。')
                    return redirect(self._document_url(document))
                form.add_error(None, '资料处理失败，请检查文件后重新上传。')
            except Exception:
                self._actor(request)
                form.add_error(None, '上传或存储未完成，请联系维护人员检查；不要连续重复提交。')
            else:
                self._actor(request)
                messages.success(request, '文档已上传并完成索引；尚未抽取或批准企业事实。')
                return redirect(self._document_url(document))
        return self._operation_page(request, title='上传知识文档', form=form, upload=True,
            explanation='提交后进行索引，可能调用已配置的 embedding 服务并产生费用；不会自动抽取或批准事实。')

    def reindex_document(self, request, object_id):
        self._actor(request)
        document = get_object_or_404(self.get_queryset(request), pk=object_id)
        form = DocumentIndexConfirmationForm(
            request.POST if request.method == 'POST' else None,
            initial={'expected_index_run_id':document.last_index_run_id},
        )
        if request.method == 'POST' and form.is_valid():
            try:
                require_no_outer_transaction()
                self._actor(request)
                indexing.reindex_document(document.pk,
                    expected_index_run_id=form.cleaned_data['expected_index_run_id'])
            except FactExtractionOperationError as error:
                form.add_error(None, error.safe_message)
            except KnowledgeDocumentError:
                self._actor(request)
                form.add_error(None, '重建索引未完成或确认版本已变化；请刷新文档详情核对，旧索引按原规则保留。')
            except Exception:
                self._actor(request)
                form.add_error(None, '索引操作未完成，请联系维护人员检查，不要连续重复提交。')
            else:
                self._actor(request)
                messages.success(request, '索引已重建；旧事实已过期，新版本需要重新抽取和人工审核。')
                return redirect(self._document_url(document))
        return self._operation_page(request, title='确认重建索引', form=form, document=document,
            explanation='此操作可能调用 embedding 服务并产生费用。成功后旧事实过期，不会自动抽取或继承批准。')

    def extract_document_facts(self, request, object_id):
        self._actor(request)
        document = get_object_or_404(self.get_queryset(request), pk=object_id)
        latest = document.fact_extraction_attempts.filter(
            index_run_id=document.last_index_run_id).order_by('-pk').first()
        retry_id = latest.pk if latest is not None and latest.status in ['failed', 'cancelled'] else None
        form = FactExtractionConfirmationForm(
            request.POST if request.method == 'POST' else None,
            initial={'expected_index_run_id':document.last_index_run_id, 'retry_after_attempt_id':retry_id},
        )
        if request.method == 'POST' and form.is_valid():
            try:
                actor = self._actor(request)
                result = run_document_fact_extraction(document.pk, actor_id=actor.pk,
                    expected_index_run_id=form.cleaned_data['expected_index_run_id'],
                    retry_after_attempt_id=form.cleaned_data['retry_after_attempt_id'])
            except FactExtractionOperationError as error:
                self._actor(request)
                form.add_error(None, error.safe_message)
            except Exception:
                self._actor(request)
                form.add_error(None, '执行状态未确认，请检查文档执行记录，勿连续重复提交。')
            else:
                self._actor(request)
                if result.state == 'running':
                    text = '已有抽取执行正在进行；本次未再次调用模型。请刷新检查，状态未确认时可明确取消。'
                elif result.state == 'legacy_facts':
                    text = '当前版本已有历史事实，未重复抽取或伪造执行记录；请查看事实审核列表。'
                elif result.proposed_count == 0:
                    text = '抽取已成功完成，无候选事实；不会自动再次调用模型，也不代表已确认任何企业能力。'
                else:
                    text = f'抽取已完成：{result.proposed_count} 条候选事实，请到事实列表核对并人工审核。未自动批准。'
                messages.info(request, text)
                return redirect(self._document_url(document))
        return self._operation_page(request, title='确认抽取待审事实', form=form, document=document,
            explanation='此操作可能调用模型并产生费用；只提议待审核事实，必须人工批准。失败或取消后重新执行需单独确认，不会自动重试。')

    def cancel_document_extraction(self, request, object_id, attempt_id):
        self._actor(request)
        document = get_object_or_404(self.get_queryset(request), pk=object_id)
        attempt = get_object_or_404(document.fact_extraction_attempts, pk=attempt_id)
        form = ExtractionCancellationForm(request.POST if request.method == 'POST' else None)
        if request.method == 'POST' and form.is_valid():
            try:
                actor = self._actor(request)
                cancel_extraction(document.pk, actor_id=actor.pk, attempt_id=attempt.pk)
            except FactExtractionOperationError as error:
                form.add_error(None, error.safe_message)
            else:
                self._actor(request)
                messages.info(request, '已撤销该执行的写入资格；不能保证中止外部请求或取消已产生的费用。重新抽取仍需确认。')
                return redirect(self._document_url(document))
        return self._operation_page(request, title=f'确认取消抽取执行 #{attempt.pk}', form=form, document=document,
            explanation='取消只撤销本次结果的保存资格，不保证中止外部模型请求或计费；旧结果返回也不得再写入。请先核对执行状态。')
