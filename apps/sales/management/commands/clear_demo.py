"""Safely remove only the exact SalesMind demo ownership graph."""

from django.core.management.base import BaseCommand, CommandError

from apps.sales.services.demo_dataset import DemoDatasetError, clear_demo_dataset


class Command(BaseCommand):
    help = "Remove only the validated SalesMind demo dataset."

    def handle(self, *args, **options):
        del args, options
        try:
            result = clear_demo_dataset()
        except DemoDatasetError as error:
            raise CommandError(str(error)) from None
        self.stdout.write(
            self.style.SUCCESS(
                "Demo dataset cleared: "
                f"{result.users} users, {result.opportunities} opportunities, "
                f"{result.solutions} solutions."
            )
        )
