"""Identity models for SalesMind AI."""

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class UserRole(models.TextChoices):
    ADMIN = "admin", _("管理员")
    SALES = "sales", _("销售")
    PRESALES = "presales", _("售前")


class User(AbstractUser):
    email = models.EmailField(_("邮箱地址"), unique=True)
    role = models.CharField(_("业务角色"), max_length=16, choices=UserRole.choices)

    REQUIRED_FIELDS = ["email", "role"]

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=UserRole.values),
                name="accounts_user_role_valid",
            )
        ]
