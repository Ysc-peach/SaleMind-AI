"""Import price rows from a CSV file.

The book is append-only, so this never overwrites: a row that already exists for
the same (sku, effective_from) is skipped and counted, and a price *change* is a
new row with a later date — which is what makes an old quote reproducible.

Expected columns (header required, order free):
    sku, name, unit_price, effective_from[, category, unit, currency]
"""

import csv
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.sales.models import PriceBookEntry

REQUIRED = ("sku", "name", "unit_price", "effective_from")


class Command(BaseCommand):
    help = "Import price book rows from CSV without overwriting history."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the CSV file.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report without writing anything.",
        )

    def handle(self, *args, **options):
        path = options["path"]
        dry_run = options["dry_run"]
        try:
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as error:
            raise CommandError(f"Cannot read {path}: {error.strerror}") from None

        if not rows:
            raise CommandError("The file has no data rows.")
        if not set(REQUIRED) <= set(rows[0].keys()):
            raise CommandError(
                f"Missing column(s): {', '.join(sorted(set(REQUIRED) - set(rows[0])))}"
            )

        owner = (
            get_user_model()
            .objects.filter(role=UserRole.ADMIN, is_active=True)
            .order_by("pk")
            .first()
        )
        if owner is None:
            raise CommandError("No active business administrator to own the rows.")

        created = skipped = 0
        errors: list[str] = []
        payloads = []
        for number, row in enumerate(rows, start=2):
            try:
                sku = (row["sku"] or "").strip()
                name = (row["name"] or "").strip()
                if not sku or not name:
                    raise ValueError("sku and name are required")
                price = Decimal((row["unit_price"] or "").strip())
                if price < 0:
                    raise ValueError("unit_price must not be negative")
                effective_from = timezone.datetime.fromisoformat(
                    (row["effective_from"] or "").strip()
                ).date()
            except (ValueError, InvalidOperation, TypeError) as error:
                errors.append(f"line {number}: {error}")
                continue
            payloads.append(
                {
                    "sku": sku,
                    "name": name,
                    "category": (row.get("category") or "").strip(),
                    "unit": (row.get("unit") or "套").strip() or "套",
                    "unit_price": price,
                    "currency": ((row.get("currency") or "CNY").strip() or "CNY")[:3],
                    "effective_from": effective_from,
                }
            )

        if errors:
            raise CommandError(
                "Refusing to import with invalid rows:\n  " + "\n  ".join(errors)
            )

        if not dry_run:
            with transaction.atomic():
                for payload in payloads:
                    _, was_created = PriceBookEntry.objects.get_or_create(
                        sku=payload["sku"],
                        effective_from=payload["effective_from"],
                        defaults={**payload, "created_by": owner},
                    )
                    created += int(was_created)
                    skipped += int(not was_created)
        else:
            # Track what this file itself has already claimed, so a dry run
            # predicts the real run instead of promising an extra row.
            seen: set[tuple[str, object]] = set()
            for payload in payloads:
                key = (payload["sku"], payload["effective_from"])
                exists = key in seen or PriceBookEntry.objects.filter(
                    sku=payload["sku"],
                    effective_from=payload["effective_from"],
                ).exists()
                seen.add(key)
                created += int(not exists)
                skipped += int(exists)

        label = "would create" if dry_run else "created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{label} {created}, skipped {skipped} (already present)"
            )
        )
        self.stdout.write(
            "A price change is a new row with a later effective_from; "
            "existing rows are never overwritten."
        )
