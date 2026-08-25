"""Identity models for SalesMind AI."""

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    SALES = "sales", "Sales"
    PRESALES = "presales", "Presales"


class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=16, choices=UserRole.choices)

    REQUIRED_FIELDS = ["email", "role"]

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=UserRole.values),
                name="accounts_user_role_valid",
            )
        ]
