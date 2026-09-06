"""Customer and opportunity persistence models."""

from django.conf import settings
from django.core.exceptions import ValidationError
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
        _("预算"), max_digits=14, decimal_places=2, null=True, blank=True
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
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="sales_solution_version_positive",
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


class SolutionDraftProvenance(models.Model):
    """Immutable citation provenance that survives KnowledgeChunk replacement."""

    solution_draft = models.ForeignKey(
        SolutionDraftRecord,
        on_delete=models.CASCADE,
        related_name="provenance_entries",
        verbose_name=_("方案草稿版本"),
    )
    statement_path = models.CharField(_("陈述路径"), max_length=255)
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
