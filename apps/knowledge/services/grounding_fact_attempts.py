"""Short-transaction state transitions for explicitly requested extraction."""
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.knowledge.models import (
    EnterpriseGroundingFact, GroundingFactExtractionAttempt as Attempt, KnowledgeDocument,
)
from .grounding_fact_approval import actor_can_review_grounding_facts


SAFE_MESSAGES = {
    'fact_extraction_permission_denied': '需要有效的业务管理员角色和后台访问权限。',
    'fact_extraction_not_ready': '文档尚未就绪或正在重建索引，请先确认索引状态。',
    'fact_extraction_index_changed': '索引版本已变化，请重新打开确认页面。',
    'fact_extraction_retry_required': '上次抽取未完成，请明确确认重新抽取，不要重复提交旧请求。',
    'fact_extraction_state_conflict': '抽取状态已变化，请刷新后确认。',
    'fact_extraction_nested_transaction': '当前调用事务不符合抽取要求，请联系维护人员。',
    'fact_extraction_provider_failed': '模型调用失败，未保存候选事实；可检查配置后明确重试。',
    'fact_extraction_cancelled': '本次抽取已取消，不再接受该执行的返回结果。',
    'fact_extraction_failed': '抽取未完成，未保存候选事实，请检查执行记录。',
    'grounding_fact_invalid_response': '模型输出未通过事实格式或来源校验，未保存候选事实。',
    'grounding_fact_index_changed': '抽取期间索引或来源发生变化，未保存候选事实。',
    'invalid_grounding_fact_input': '当前文档或来源不满足事实抽取条件。',
}


class FactExtractionOperationError(Exception):
    def __init__(self, code: str):
        self.code = code if code in SAFE_MESSAGES else 'fact_extraction_failed'
        self.safe_message = SAFE_MESSAGES[self.code]
        super().__init__(self.safe_message)


@dataclass(frozen=True, slots=True)
class ExtractionBinding:
    document_id: int
    index_run_id: UUID
    attempt_id: int
    token: UUID
    actor_id: int


@dataclass(frozen=True, slots=True)
class ExtractionClaim:
    state: Literal['claimed', 'running', 'succeeded', 'legacy_facts']
    binding: ExtractionBinding | None
    attempt_id: int | None
    index_run_id: UUID
    proposed_count: int


def require_actor(actor_id: int):
    actor = None
    if isinstance(actor_id, int) and not isinstance(actor_id, bool) and actor_id > 0:
        actor = get_user_model().objects.filter(pk=actor_id).first()
    if not actor_can_review_grounding_facts(actor):
        raise FactExtractionOperationError('fact_extraction_permission_denied')
    return actor


def require_no_outer_transaction() -> None:
    if connection.in_atomic_block:
        raise FactExtractionOperationError('fact_extraction_nested_transaction')


def _locked_document(document_id: int) -> KnowledgeDocument:
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id <= 0:
        raise FactExtractionOperationError('fact_extraction_not_ready')
    document = KnowledgeDocument.objects.select_for_update().filter(pk=document_id).first()
    if document is None:
        raise FactExtractionOperationError('fact_extraction_not_ready')
    return document


def _require_current(document: KnowledgeDocument, run_id: UUID) -> None:
    if (document.status != 'ready' or document.last_index_run_id is None
            or document.indexing_run_id is not None):
        raise FactExtractionOperationError('fact_extraction_not_ready')
    if not isinstance(run_id, UUID) or document.last_index_run_id != run_id:
        raise FactExtractionOperationError('fact_extraction_index_changed')


def _claim_result(attempt: Attempt, state, binding=None) -> ExtractionClaim:
    return ExtractionClaim(state, binding, attempt.pk, attempt.index_run_id, attempt.proposed_count)


def claim_extraction(document_id: int, *, actor_id: int, expected_index_run_id: UUID,
                     retry_after_attempt_id: int | None = None) -> ExtractionClaim:
    require_no_outer_transaction()
    try:
        with transaction.atomic():
            document = _locked_document(document_id)
            actor = require_actor(actor_id)
            _require_current(document, expected_index_run_id)
            history = Attempt.objects.filter(document=document, index_run_id=expected_index_run_id)
            active = history.filter(status__in=['running', 'succeeded']).first()
            if active is not None:
                return _claim_result(active, active.status)
            legacy_count = EnterpriseGroundingFact.objects.filter(
                source_document=document, source_index_run_id=expected_index_run_id,
            ).count()
            if legacy_count:
                return ExtractionClaim('legacy_facts', None, None, expected_index_run_id, legacy_count)
            latest = history.order_by('-pk').first()
            if latest is not None:
                if retry_after_attempt_id is None:
                    raise FactExtractionOperationError('fact_extraction_retry_required')
                if (isinstance(retry_after_attempt_id, bool)
                        or retry_after_attempt_id != latest.pk):
                    raise FactExtractionOperationError('fact_extraction_state_conflict')
            elif retry_after_attempt_id is not None:
                raise FactExtractionOperationError('fact_extraction_state_conflict')
            attempt = Attempt.objects.create(document=document, requested_by=actor,
                                             index_run_id=expected_index_run_id)
            binding = ExtractionBinding(document.pk, expected_index_run_id, attempt.pk,
                                        attempt.token, actor.pk)
            return _claim_result(attempt, 'claimed', binding)
    except IntegrityError as exc:
        # The document lock normally serializes claims. A constraint race must
        # surface as the existing conflict code, not a 500 with a constraint name.
        raise FactExtractionOperationError('fact_extraction_state_conflict') from exc


def require_binding_locked(document: KnowledgeDocument, binding: ExtractionBinding) -> Attempt:
    """Caller holds the document lock; always acquire attempt locks second."""
    if not connection.in_atomic_block or document.pk != binding.document_id:
        raise FactExtractionOperationError('fact_extraction_state_conflict')
    require_actor(binding.actor_id)
    _require_current(document, binding.index_run_id)
    attempt = Attempt.objects.select_for_update().filter(
        pk=binding.attempt_id, document=document, index_run_id=binding.index_run_id,
        token=binding.token, requested_by_id=binding.actor_id,
    ).first()
    if (attempt is not None and attempt.status == 'failed'
            and attempt.error_code == 'fact_extraction_index_changed'):
        raise FactExtractionOperationError('fact_extraction_index_changed')
    if attempt is None or attempt.status != 'running':
        code = ('fact_extraction_cancelled' if attempt is not None and attempt.status == 'cancelled'
                else 'fact_extraction_state_conflict')
        raise FactExtractionOperationError(code)
    return attempt


def mark_succeeded_locked(attempt: Attempt, *, proposed_count: int) -> None:
    if (not connection.in_atomic_block or attempt.status != 'running'
            or not isinstance(proposed_count, int) or isinstance(proposed_count, bool)
            or proposed_count < 0):
        raise FactExtractionOperationError('fact_extraction_state_conflict')
    attempt.status = 'succeeded'
    attempt.proposed_count = proposed_count
    attempt.finished_at = timezone.now()
    attempt.save(update_fields=['status', 'proposed_count', 'finished_at'])


def fail_extraction(binding: ExtractionBinding, *, code: str) -> None:
    """System cleanup is fenced by token, even if the requesting actor lost access."""
    with transaction.atomic():
        document = _locked_document(binding.document_id)
        attempt = Attempt.objects.select_for_update().filter(
            pk=binding.attempt_id, document=document, token=binding.token,
            index_run_id=binding.index_run_id, requested_by_id=binding.actor_id,
        ).first()
        if attempt is not None and attempt.status == 'running':
            attempt.status = 'failed'
            attempt.error_code = FactExtractionOperationError(code).code
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=['status', 'error_code', 'finished_at'])


def cancel_extraction(document_id: int, *, actor_id: int, attempt_id: int) -> Attempt:
    with transaction.atomic():
        document = _locked_document(document_id)
        require_actor(actor_id)
        if not isinstance(attempt_id, int) or isinstance(attempt_id, bool) or attempt_id <= 0:
            raise FactExtractionOperationError('fact_extraction_state_conflict')
        attempt = Attempt.objects.select_for_update().filter(pk=attempt_id, document=document).first()
        if attempt is not None and attempt.status == 'cancelled':
            return attempt
        if attempt is None or attempt.status != 'running':
            raise FactExtractionOperationError('fact_extraction_state_conflict')
        attempt.status = 'cancelled'
        attempt.error_code = 'fact_extraction_cancelled'
        attempt.finished_at = timezone.now()
        attempt.save(update_fields=['status', 'error_code', 'finished_at'])
        return attempt
