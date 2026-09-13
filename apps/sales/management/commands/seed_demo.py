"""Create or recover the exact SalesMind demo dataset."""

import os

from django.core.management.base import BaseCommand, CommandError

from apps.sales.services.demo_dataset import DemoDatasetError, seed_demo_dataset


class Command(BaseCommand):
    help = "Create/recover the offline SalesMind demo dataset."

    def handle(self, *args, **options):
        del args, options
        password = os.environ.get("SALESMIND_DEMO_PASSWORD")
        if not password:
            raise CommandError("SALESMIND_DEMO_PASSWORD is required.")
        try:
            result = seed_demo_dataset(password)
        except DemoDatasetError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(
            self.style.SUCCESS(
                "Demo dataset ready: "
                f"{result.users} users, {result.opportunities} opportunities, "
                f"{result.solutions} solutions."
            )
        )
