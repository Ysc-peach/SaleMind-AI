"""Load a sample price book so quoting can be tried end to end.

Every row is prefixed ``DEMO-`` on purpose. A placeholder that looks like a real
price is worse than no price at all: someone will quote from it. The command is
idempotent on (sku, effective_from), so running it twice adds nothing.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import PriceBookEntry

SAMPLE = (
    ("DEMO-PLATFORM", "平台基础版（私有化部署）", "软件", "套", "380000.00"),
    ("DEMO-KB-500", "知识库授权（500 用户）", "软件", "套", "120000.00"),
    ("DEMO-OCR", "扫描件 OCR 模块", "模块", "套", "60000.00"),
    ("DEMO-SSO", "SSO 集成实施", "实施", "套", "45000.00"),
    ("DEMO-OA", "OA 集成实施", "实施", "套", "45000.00"),
    ("DEMO-IMPL", "实施服务（人天）", "服务", "人天", "3200.00"),
    ("DEMO-TRAIN", "培训（人天）", "服务", "人天", "2800.00"),
    ("DEMO-SUPPORT", "一年运维支持", "服务", "套", "96000.00"),
)


class Command(BaseCommand):
    help = "Insert a DEMO- prefixed sample price book (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--effective-from",
            default=timezone.localdate().isoformat(),
            help="Effective date for the sample rows (default: today).",
        )

    def handle(self, *args, **options):
        raw = options["effective_from"]
        try:
            effective_from = timezone.datetime.fromisoformat(raw).date()
        except ValueError:
            raise CommandError("--effective-from expects YYYY-MM-DD.") from None

        owner = (
            get_user_model()
            .objects.filter(role=UserRole.ADMIN, is_active=True)
            .order_by("pk")
            .first()
        )
        if owner is None:
            raise CommandError(
                "No active business administrator exists to own the rows."
            )

        created = 0
        skipped = 0
        for sku, name, category, unit, price in SAMPLE:
            _, was_created = PriceBookEntry.objects.get_or_create(
                sku=sku,
                effective_from=effective_from,
                defaults={
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "unit_price": Decimal(price),
                    "currency": "CNY",
                    "created_by": owner,
                },
            )
            created += int(was_created)
            skipped += int(not was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"sample price book: {created} created, {skipped} already present "
                f"(effective from {effective_from})"
            )
        )
        self.stdout.write(
            "These rows are placeholders: replace them with the real catalogue "
            "in /admin/ → 价目条目."
        )
