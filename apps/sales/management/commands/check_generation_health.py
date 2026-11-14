"""Fail-fast queue health check for cron / task scheduler monitoring.

Prints one JSON line with the current signal and any threshold breaches. A
non-zero exit code means a scheduler can alert without parsing the payload.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.sales.services.generation_health import collect_health


class Command(BaseCommand):
    help = "Report generation queue health; exit non-zero on threshold breaches."

    def add_arguments(self, parser):
        parser.add_argument("--max-queued", type=int, default=10)
        parser.add_argument("--max-wait-seconds", type=int, default=600)
        parser.add_argument("--max-failed-last-hour", type=int, default=5)

    def handle(self, *args, **options):
        health = collect_health()
        breaches = []
        if health.queued > options["max_queued"]:
            breaches.append("queued")
        if health.oldest_queued_wait_seconds > options["max_wait_seconds"]:
            breaches.append("oldest_queued_wait_seconds")
        if health.failed_last_hour > options["max_failed_last_hour"]:
            breaches.append("failed_last_hour")

        self.stdout.write(
            json.dumps(
                {
                    "health": health.as_dict(),
                    "thresholds": {
                        "max_queued": options["max_queued"],
                        "max_wait_seconds": options["max_wait_seconds"],
                        "max_failed_last_hour": options["max_failed_last_hour"],
                    },
                    "breaches": breaches,
                },
                sort_keys=True,
            )
        )
        if breaches:
            raise CommandError(
                "generation queue health check failed: " + ", ".join(breaches)
            )
