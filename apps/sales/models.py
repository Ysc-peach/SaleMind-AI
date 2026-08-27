"""Customer and opportunity persistence models."""

from django.conf import settings
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
