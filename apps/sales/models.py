"""Customer and opportunity persistence models."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class OpportunityStage(models.TextChoices):
    INITIAL_CONTACT = "initial_contact", _("初步接触")
    REQUIREMENT_ANALYSIS = "requirement_analysis", _("需求分析")
    PRESALES_SUPPORT = "presales_support", _("售前支持")
    SOLUTION = "solution", _("方案制定")
    QUOTATION = "quotation", _("报价")
    NEGOTIATION = "negotiation", _("商务谈判")


class OpportunityStatus(models.TextChoices):
    ACTIVE = "active", _("进行中")
    WON = "won", _("赢单")
    LOST = "lost", _("丢单")
    CLOSED = "closed", _("已关闭")


class SolutionReviewStatus(models.TextChoices):
    DRAFT = "draft", _("草稿")
    PENDING_REVIEW = "pending_review", _("待审核")
    APPROVED = "approved", _("已批准")
    NEEDS_REVISION = "needs_revision", _("需要修改")


class SolutionReviewDecisionStatus(models.TextChoices):
    PENDING = "pending", _("待审核")
    APPROVED = "approved", _("已批准")
    RETURNED = "returned", _("已退回")


class SolutionReturnReason(models.TextChoices):
    CUSTOMER_INFO_REQUIRED = "customer_info_required", _("需要补充客户信息")
    TECHNICAL_REVISION_REQUIRED = (
        "technical_revision_required",
        _("需要修改技术方案"),
    )


class SolutionStaleReason(models.TextChoices):
    NEWER_REQUIREMENT_ANALYSIS = (
        "newer_requirement_analysis",
        _("存在更新的需求分析"),
    )
    GROUNDING_FACT_INVALID = "grounding_fact_invalid", _("Grounding Fact 已失效")
    GROUNDING_PROVENANCE_INVALID = (
        "grounding_provenance_invalid",
        _("Grounding 来源已失效"),
    )


class Customer(models.Model):
    name = models.CharField(_("客户名称"), max_length=200)
    industry = models.CharField(_("行业"), max_length=100, blank=True, default="")
    company_size = models.CharField(_("公司规模"), max_length=100, blank=True, default="")
    basic_info = models.TextField(_("基本信息"), blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_customers",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)
    # Archiving instead of deleting: drafts and reviews point at the customer, so
    # removing the row would either cascade or orphan evidence.
    is_active = models.BooleanField(_("启用"), default=True, db_index=True)

    class Meta:
        verbose_name = _("客户")
        verbose_name_plural = _("客户")

    def __str__(self) -> str:
        return self.name


class Opportunity(models.Model):
    project_name = models.CharField(_("项目名称"), max_length=200)
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="opportunities",
        verbose_name=_("客户"),
    )
    sales_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales_opportunities",
        verbose_name=_("销售负责人"),
    )
    presales_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="presales_opportunities",
        null=True,
        blank=True,
        verbose_name=_("售前负责人"),
    )
    raw_requirement = models.TextField(_("原始需求"), blank=True, default="")
    budget = models.DecimalField(
        _("预算"), max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    stage = models.CharField(
        _("阶段"),
        max_length=32,
        choices=OpportunityStage.choices,
        default=OpportunityStage.INITIAL_CONTACT,
    )
    status = models.CharField(
        _("状态"),
        max_length=16,
        choices=OpportunityStatus.choices,
        default=OpportunityStatus.ACTIVE,
    )
    expected_launch_date = models.DateField(_("预计上线日期"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_opportunities",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)
    # Archive flag, orthogonal to ``status``: status is the business outcome,
    # this is "stop working on it". Reviews and drafts keep pointing at the row.
    is_active = models.BooleanField(_("启用"), default=True, db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stage__in=OpportunityStage.values),
                name="sales_opportunity_stage_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=OpportunityStatus.values),
                name="sales_opportunity_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["sales_owner", "status"]),
            models.Index(fields=["presales_owner", "status"]),
            models.Index(fields=["customer", "status"]),
        ]
        verbose_name = _("商机")
        verbose_name_plural = _("商机")

    def __str__(self) -> str:
        return self.project_name


class OpportunityRequirementAnalysis(models.Model):
    """Append-only business history, created through the analysis service.

    Ordinary instance updates/deletes are blocked. QuerySet maintenance and
    direct SQL are not a security boundary; Opportunity cascade remains valid.
    JSON correctness belongs to the shared domain validator and create service.
    """

    opportunity = models.ForeignKey(
        Opportunity, on_delete=models.CASCADE, related_name="requirement_analyses",
        verbose_name=_("商机"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="triggered_requirement_analyses", verbose_name=_("分析触发人"),
    )
    summary = models.TextField(_("需求摘要"))
    requirements = models.JSONField(_("结构化需求"))
    conflicts = models.JSONField(_("需求冲突"))
    clarifying_questions = models.JSONField(_("澄清问题"))
    source_raw_requirement = models.TextField(_("原始需求快照"), blank=True)
    source_context = models.JSONField(_("业务上下文快照"))
    analysis_version = models.CharField(_("分析契约版本"), max_length=32)
    llm_provider = models.CharField(_("模型服务提供方"), max_length=64)
    llm_model = models.CharField(_("模型名称"), max_length=200)
    created_at = models.DateTimeField(_("分析时间"), auto_now_add=True)

    class Meta:
        verbose_name = _("商机需求分析历史")
        verbose_name_plural = _("商机需求分析历史")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["opportunity", "-created_at", "-id"],
                name="sales_reqanalysis_history_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(summary__regex=r"\S"), name="sales_analysis_summary_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(analysis_version__regex=r"\S"), name="sales_analysis_version_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(llm_provider__regex=r"\S"), name="sales_analysis_provider_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(llm_model__regex=r"\S"), name="sales_analysis_model_nonempty",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None:
            raise ValidationError(
                "Requirement analysis history is immutable.", code="immutable_requirement_analysis",
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Requirement analysis history is immutable.", code="immutable_requirement_analysis",
        )


class SolutionDraftRecord(models.Model):
    """Immutable persisted content for one generated Solution Draft version."""

    ReviewStatus = SolutionReviewStatus
    StaleReason = SolutionStaleReason

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="solution_drafts",
        verbose_name=_("商机"),
    )
    requirement_analysis = models.ForeignKey(
        OpportunityRequirementAnalysis,
        on_delete=models.PROTECT,
        related_name="solution_drafts",
        verbose_name=_("需求分析快照"),
    )
    version = models.PositiveIntegerField(_("方案版本"))
    title = models.CharField(_("方案标题"), max_length=255)
    draft_payload = models.JSONField(_("方案结构化快照"))
    generation_metadata = models.JSONField(_("生成元数据"), default=dict)
    generation_idempotency_key = models.UUIDField(
        _("生成幂等键"),
        null=True,
        blank=True,
        editable=False,
    )
    schema_version = models.PositiveSmallIntegerField(
        _("方案结构版本"),
        default=1,
        editable=False,
    )
    review_status = models.CharField(
        _("审核状态"),
        max_length=24,
        choices=SolutionReviewStatus.choices,
        default=SolutionReviewStatus.DRAFT,
    )
    is_stale = models.BooleanField(_("已过期"), default=False)
    stale_at = models.DateTimeField(_("过期时间"), null=True, blank=True)
    stale_reasons = models.JSONField(_("过期原因"), default=list)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_solution_drafts",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    _IMMUTABLE_FIELDS = (
        "opportunity_id",
        "requirement_analysis_id",
        "version",
        "title",
        "draft_payload",
        "generation_metadata",
        "generation_idempotency_key",
        "schema_version",
        "created_by_id",
    )
    _LIFECYCLE_FIELDS = frozenset(
        {"review_status", "is_stale", "stale_at", "stale_reasons"}
    )

    class Meta:
        ordering = ["-version", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "version"],
                name="sales_solution_opportunity_version_unique",
            ),
            models.UniqueConstraint(
                fields=["generation_idempotency_key"],
                condition=models.Q(generation_idempotency_key__isnull=False),
                name="sales_solution_generation_idempotency_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="sales_solution_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(schema_version__in=(1, 2)),
                name="sales_solution_schema_version_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(review_status__in=SolutionReviewStatus.values),
                name="sales_solution_review_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_stale=True, stale_at__isnull=False)
                    | models.Q(
                        is_stale=False,
                        stale_at__isnull=True,
                        stale_reasons=[],
                    )
                ),
                name="sales_solution_stale_metadata",
            ),
            models.CheckConstraint(
                condition=models.Q(title__regex=r"\S"),
                name="sales_solution_title_nonempty",
            ),
        ]
        indexes = [
            models.Index(
                fields=["opportunity", "-version"],
                name="sales_solution_history_idx",
            ),
            models.Index(
                fields=["review_status", "is_stale"],
                name="sales_solution_state_idx",
            ),
        ]
        verbose_name = _("解决方案草稿版本")
        verbose_name_plural = _("解决方案草稿版本")

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            update_fields = kwargs.get("update_fields")
            if update_fields is None or not set(update_fields) <= self._LIFECYCLE_FIELDS:
                original = type(self).objects.values(*self._IMMUTABLE_FIELDS).get(pk=self.pk)
                if any(getattr(self, field) != original[field] for field in self._IMMUTABLE_FIELDS):
                    raise ValidationError(
                        "Solution Draft version content is immutable.",
                        code="immutable_solution_draft",
                    )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Solution Draft versions are immutable.",
            code="immutable_solution_draft",
        )


class SolutionReview(models.Model):
    """Version-scoped audit record for one Solution review attempt."""

    Status = SolutionReviewDecisionStatus
    ReturnReason = SolutionReturnReason

    solution_draft = models.ForeignKey(
        SolutionDraftRecord,
        on_delete=models.PROTECT,
        related_name="reviews",
        verbose_name=_("解决方案草稿版本"),
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_solution_reviews",
        verbose_name=_("提交人"),
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_solution_reviews",
        verbose_name=_("审核人"),
    )
    status = models.CharField(
        _("审核决定状态"),
        max_length=16,
        choices=SolutionReviewDecisionStatus.choices,
        default=SolutionReviewDecisionStatus.PENDING,
    )
    return_reason = models.CharField(
        _("退回原因"),
        max_length=40,
        choices=SolutionReturnReason.choices,
        blank=True,
        default="",
    )
    comment = models.TextField(_("审核意见"), blank=True, default="")
    submitted_at = models.DateTimeField(_("提交时间"), auto_now_add=True)
    decided_at = models.DateTimeField(_("决定时间"), null=True, blank=True)

    _IMMUTABLE_FIELDS = (
        "solution_draft_id",
        "submitted_by_id",
        "reviewer_id",
        "submitted_at",
    )
    _DECISION_FIELDS = ("status", "return_reason", "comment", "decided_at")

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["solution_draft"],
                condition=models.Q(status=SolutionReviewDecisionStatus.PENDING),
                name="sales_solution_one_pending_review",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=SolutionReviewDecisionStatus.values),
                name="sales_solution_review_decision_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status=SolutionReviewDecisionStatus.PENDING,
                        return_reason="",
                        comment="",
                        decided_at__isnull=True,
                    )
                    | models.Q(
                        status=SolutionReviewDecisionStatus.APPROVED,
                        return_reason="",
                        decided_at__isnull=False,
                    )
                    | models.Q(
                        status=SolutionReviewDecisionStatus.RETURNED,
                        return_reason__in=SolutionReturnReason.values,
                        comment__regex=r"\S",
                        decided_at__isnull=False,
                    )
                ),
                name="sales_solution_review_decision_state",
            ),
        ]
        indexes = [
            models.Index(
                fields=["solution_draft", "-submitted_at", "-id"],
                name="sales_solreview_history_idx",
            ),
            models.Index(
                fields=["reviewer", "status"],
                name="sales_solreview_reviewer_idx",
            ),
        ]
        verbose_name = _("解决方案审核记录")
        verbose_name_plural = _("解决方案审核记录")

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            original = type(self).objects.values(
                *self._IMMUTABLE_FIELDS,
                *self._DECISION_FIELDS,
            ).get(pk=self.pk)
            if any(
                getattr(self, field) != original[field]
                for field in self._IMMUTABLE_FIELDS
            ):
                raise ValidationError(
                    "Solution Review identity is immutable.",
                    code="immutable_solution_review",
                )
            if (
                original["status"] != SolutionReviewDecisionStatus.PENDING
                and any(
                    getattr(self, field) != original[field]
                    for field in self._DECISION_FIELDS
                )
            ):
                raise ValidationError(
                    "Completed Solution Review decisions are immutable.",
                    code="immutable_solution_review",
                )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Solution Review history is immutable.",
            code="immutable_solution_review",
        )


class SolutionDraftProvenance(models.Model):
    """Immutable citation provenance that survives KnowledgeChunk replacement."""

    solution_draft = models.ForeignKey(
        SolutionDraftRecord,
        on_delete=models.CASCADE,
        related_name="provenance_entries",
        verbose_name=_("方案草稿版本"),
    )
    statement_path = models.CharField(_("陈述路径"), max_length=255)
    claim_id = models.CharField(
        _("原子声明 ID"),
        max_length=64,
        null=True,
        blank=True,
        editable=False,
    )
    citation_label = models.CharField(_("引用标签"), max_length=32)
    enterprise_grounding_fact = models.ForeignKey(
        "knowledge.EnterpriseGroundingFact",
        on_delete=models.PROTECT,
        related_name="solution_provenance_entries",
        verbose_name=_("企业 Grounding 事实"),
    )
    source_document = models.ForeignKey(
        "knowledge.KnowledgeDocument",
        on_delete=models.PROTECT,
        related_name="solution_provenance_entries",
        verbose_name=_("来源文档"),
    )
    source_chunk_id = models.PositiveBigIntegerField(_("来源分块快照 ID"))
    source_index_run_id = models.UUIDField(_("来源索引运行 ID"))
    source_content_hash = models.CharField(_("来源内容 SHA-256"), max_length=64)
    source_excerpt = models.TextField(_("来源摘录"))
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "solution_draft",
                    "statement_path",
                    "citation_label",
                    "enterprise_grounding_fact",
                ],
                name="sales_solution_provenance_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(statement_path__regex=r"\S"),
                name="sales_solution_statement_path_nonempty",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(claim_id__isnull=True)
                    | models.Q(claim_id__regex=r"\S")
                ),
                name="sales_solution_claim_id_nonempty",
            ),
            models.CheckConstraint(
                condition=models.Q(citation_label__regex=r"^S[1-9][0-9]*$"),
                name="sales_solution_citation_label_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["solution_draft", "statement_path"],
                name="sales_solprov_path_idx",
            ),
            models.Index(
                fields=["enterprise_grounding_fact"],
                name="sales_solprov_fact_idx",
            ),
            models.Index(
                fields=["solution_draft", "claim_id"],
                name="sales_solprov_claim_idx",
            ),
        ]
        verbose_name = _("解决方案引用来源")
        verbose_name_plural = _("解决方案引用来源")

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None:
            raise ValidationError(
                "Solution Draft provenance is immutable.",
                code="immutable_solution_provenance",
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Solution Draft provenance is immutable.",
            code="immutable_solution_provenance",
        )


class SolutionGenerationJobStatus(models.TextChoices):
    QUEUED = "queued", _("排队中")
    RUNNING = "running", _("执行中")
    SUCCEEDED = "succeeded", _("已成功")
    FAILED = "failed", _("已失败")


class SolutionGenerationJob(models.Model):
    """Durable queue entry for one asynchronous Solution generation.

    The LangGraph checkpoint stays the source of truth for workflow state; this
    row only records who asked for a run, whether a worker claimed it, and why it
    stopped. It exists so an HTTP request no longer waits 95-98 seconds.
    """

    workflow_id = models.UUIDField(_("工作流标识"), unique=True)
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.PROTECT,
        related_name="generation_jobs",
        verbose_name=_("商机"),
    )
    requirement_analysis = models.ForeignKey(
        OpportunityRequirementAnalysis,
        on_delete=models.PROTECT,
        related_name="generation_jobs",
        verbose_name=_("需求分析"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generation_jobs",
        verbose_name=_("发起人"),
    )
    status = models.CharField(
        _("状态"),
        max_length=16,
        choices=SolutionGenerationJobStatus.choices,
        default=SolutionGenerationJobStatus.QUEUED,
    )
    attempts = models.PositiveSmallIntegerField(_("已尝试次数"), default=0)
    error_code = models.CharField(
        _("错误代码"), max_length=64, blank=True, default="",
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    started_at = models.DateTimeField(_("开始时间"), null=True, blank=True)
    finished_at = models.DateTimeField(_("结束时间"), null=True, blank=True)
    heartbeat_at = models.DateTimeField(_("心跳时间"), null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                # A claimed job must record when it started, otherwise a crashed
                # worker cannot be distinguished from a job nobody picked up.
                condition=(
                    models.Q(status="queued")
                    | models.Q(started_at__isnull=False)
                ),
                name="sales_genjob_started_when_claimed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(status__in=["queued", "running"])
                    | models.Q(finished_at__isnull=False)
                ),
                name="sales_genjob_finished_when_terminal",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="sales_genjob_pick_idx",
            ),
        ]
        verbose_name = _("方案生成任务")
        verbose_name_plural = _("方案生成任务")


class FollowUpTaskStatus(models.TextChoices):
    OPEN = "open", _("待跟进")
    DONE = "done", _("已完成")


class FollowUpTask(models.Model):
    """One dated action someone owes on an opportunity.

    Kept separate from the draft and review tables because it is the only thing
    here that is about the *future*: "call the customer back", "send the POC
    plan". Without a dated record the workspace can only show what already
    happened.
    """

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="follow_up_tasks",
        verbose_name=_("商机"),
    )
    title = models.CharField(_("事项"), max_length=200)
    due_on = models.DateField(_("到期日"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_follow_up_tasks",
        verbose_name=_("负责人"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_follow_up_tasks",
        verbose_name=_("创建人"),
    )
    status = models.CharField(
        _("状态"),
        max_length=16,
        choices=FollowUpTaskStatus.choices,
        default=FollowUpTaskStatus.OPEN,
    )
    completed_at = models.DateTimeField(_("完成时间"), null=True, blank=True)
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                # The same rule the generation queue follows: a terminal state
                # and its timestamp are recorded together or not at all.
                condition=(
                    models.Q(status="open", completed_at__isnull=True)
                    | models.Q(status="done", completed_at__isnull=False)
                ),
                name="sales_followup_completed_when_done",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "due_on"], name="sales_followup_due_idx"
            ),
            models.Index(
                fields=["owner", "status"], name="sales_followup_owner_idx"
            ),
        ]
        ordering = ["due_on", "id"]
        verbose_name = _("跟进事项")
        verbose_name_plural = _("跟进事项")

    def __str__(self) -> str:
        return f"{self.title} ({self.due_on})"


class CaseStudySizeBand(models.TextChoices):
    SMALL = "small", _("小型（200 人以下）")
    MEDIUM = "medium", _("中型（200-1000 人）")
    LARGE = "large", _("大型（1000 人以上）")


class CaseStudy(models.Model):
    """A delivered engagement that a proposal may point at.

    Deliberately separate from the document knowledge base: a document is
    evidence for a *fact*, while a case is a story with a shape (industry, size,
    what hurt, what we did, what changed). Presales pick cases by resemblance,
    not by full-text similarity.
    """

    title = models.CharField(_("案例名称"), max_length=200)
    industry = models.CharField(_("行业"), max_length=64)
    size_band = models.CharField(
        _("客户规模"), max_length=16, choices=CaseStudySizeBand.choices
    )
    customer_name = models.CharField(
        _("客户名称"), max_length=120, blank=True, default=""
    )
    pain_points = models.TextField(_("客户痛点"), blank=True, default="")
    approach = models.TextField(_("我们的做法"), blank=True, default="")
    results = models.TextField(_("结果"), blank=True, default="")
    # Naming a customer in a proposal needs their permission, so this is an
    # explicit flag rather than something inferred from the name field.
    referenceable = models.BooleanField(_("可对外引用"), default=False)
    is_active = models.BooleanField(_("是否启用"), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_case_studies",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(size_band__in=CaseStudySizeBand.values),
                name="sales_case_size_band_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["industry", "size_band"], name="sales_case_match_idx"
            ),
            models.Index(
                fields=["is_active", "referenceable"], name="sales_case_visible_idx"
            ),
        ]
        ordering = ["-updated_at", "-id"]
        verbose_name = _("案例")
        verbose_name_plural = _("案例")

    def __str__(self) -> str:
        return self.title


class CompetitorDimension(models.TextChoices):
    """Comparison axes, each anchored to subjects the evidence chain knows.

    A dimension is not a new kind of evidence: it is a second way to look at the
    same approved facts, which is why the list stays short and fixed.
    """

    DEPLOYMENT = "deployment", _("部署形态")
    DATA_RESIDENCY = "data_residency", _("数据驻留")
    IDENTITY_INTEGRATION = "identity_integration", _("身份与集成")
    DATA_STORAGE = "data_storage", _("数据存储")
    DOCUMENT_PROCESSING = "document_processing", _("文档处理")
    DELIVERABLES = "deliverables", _("交付物")
    SERVER_COMPATIBILITY = "server_compatibility", _("服务器兼容")
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval", _("知识检索")


class CompetitorStatementStatus(models.TextChoices):
    PROPOSED = "proposed", _("待审批")
    APPROVED = "approved", _("已批准")
    REJECTED = "rejected", _("已拒绝")


class Competitor(models.Model):
    """A named other vendor.

    A row rather than a string, because "华为云 / 华为云Stack / Huawei Cloud"
    typed three ways can never be compared, and because a comparison table is
    reused across proposals for years.
    """

    name = models.CharField(_("竞品名称"), max_length=120, unique=True)
    aliases = models.CharField(
        _("别名"), max_length=240, blank=True, default="",
        help_text=_("逗号分隔，仅用于检索，不参与比较"),
    )
    is_active = models.BooleanField(_("是否启用"), default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_competitors",
        verbose_name=_("创建人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = _("竞品")
        verbose_name_plural = _("竞品")

    def __str__(self) -> str:
        return self.name


class CompetitorStatement(models.Model):
    """What a competitor publicly claims, with the source that says so.

    Only neutral, attributable statements are stored. A negative claim about a
    third party ("X does not support Y") ages badly and cannot be defended in
    front of a customer unless the vendor said it themselves, so the service
    refuses those outright.
    """

    competitor = models.ForeignKey(
        Competitor,
        on_delete=models.CASCADE,
        related_name="statements",
        verbose_name=_("竞品"),
    )
    dimension = models.CharField(
        _("比较维度"), max_length=32, choices=CompetitorDimension.choices
    )
    statement = models.TextField(_("公开陈述"))
    source_url = models.URLField(_("来源链接"), max_length=500)
    published_on = models.DateField(_("来源发布日期"), null=True, blank=True)
    captured_on = models.DateField(_("采集日期"))
    status = models.CharField(
        _("审批状态"),
        max_length=16,
        choices=CompetitorStatementStatus.choices,
        default=CompetitorStatementStatus.PROPOSED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_competitor_statements",
        null=True,
        blank=True,
        verbose_name=_("审批人"),
    )
    reviewed_at = models.DateTimeField(_("审批时间"), null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_competitor_statements",
        verbose_name=_("登记人"),
    )
    created_at = models.DateTimeField(_("创建时间"), auto_now_add=True)
    updated_at = models.DateTimeField(_("更新时间"), auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(dimension__in=CompetitorDimension.values),
                name="sales_competitor_dimension_valid",
            ),
            models.CheckConstraint(
                # A decision and who made it are recorded together, the same
                # way every other decision in this project works.
                condition=(
                    models.Q(
                        status=CompetitorStatementStatus.PROPOSED,
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | models.Q(
                        status__in=[
                            CompetitorStatementStatus.APPROVED,
                            CompetitorStatementStatus.REJECTED,
                        ],
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="sales_competitor_reviewed_when_decided",
            ),
        ]
        indexes = [
            models.Index(
                fields=["competitor", "dimension", "status"],
                name="sales_competitor_matrix_idx",
            ),
        ]
        ordering = ["-created_at", "-id"]
        verbose_name = _("竞品陈述")
        verbose_name_plural = _("竞品陈述")

    def __str__(self) -> str:
        return f"{self.competitor.name} · {self.get_dimension_display()}"
