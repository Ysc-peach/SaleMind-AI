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
