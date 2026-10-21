"""Validate new form/API budgets without rewriting historical values."""

from decimal import Decimal

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0006_solution_domain_schema_version")]

    operations = [
        migrations.AlterField(
            model_name="opportunity",
            name="budget",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=14,
                null=True,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="预算",
            ),
        ),
    ]
