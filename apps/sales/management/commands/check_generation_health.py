"""Fail-fast queue health check for cron / task scheduler monitoring.

Prints one JSON line with the current signal and any threshold breaches. A
non-zero exit code means a scheduler can alert without parsing the payload, and
``--notify`` additionally pushes the same report to the configured channel for
schedulers that only record the failure.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.sales.services.alerting import deliver_breach_alert
from apps.sales.services.generation_health import collect_health


class Command(BaseCommand):
    help = "Report generation queue health; exit non-zero on threshold breaches."

    def add_arguments(self, parser):
        parser.add_argument("--max-queued", type=int, default=10)
        parser.add_argument("--max-wait-seconds", type=int, default=600)
        parser.add_argument("--max-failed-last-hour", type=int, default=5)
        parser.add_argument("--max-stale-running", type=int, default=0)
        parser.add_argument(
            "--notify",
            action="store_true",
            help=(
                "Push a breach to ALERT_WEBHOOK_URL / ALERT_EMAIL_TO. The exit "
                "code is unchanged, so delivery can never mask the breach."
            ),
        )

    def handle(self, *args, **options):
        health = collect_health()
        breaches = []
        if health.queued > options["max_queued"]:
            breaches.append("queued")
        if health.oldest_queued_wait_seconds > options["max_wait_seconds"]:
            breaches.append("oldest_queued_wait_seconds")
        if health.failed_last_hour > options["max_failed_last_hour"]:
            breaches.append("failed_last_hour")
        # Any job whose worker stopped beating is a breach by default: if the
        # only worker is gone, no one else will reclaim it.
        if health.stale_running > options["max_stale_running"]:
            breaches.append("stale_running")

        report = {
            "health": health.as_dict(),
            "thresholds": {
                "max_queued": options["max_queued"],
                "max_wait_seconds": options["max_wait_seconds"],
                "max_failed_last_hour": options["max_failed_last_hour"],
                "max_stale_running": options["max_stale_running"],
            },
            "breaches": breaches,
        }
        if breaches and options["notify"]:
            delivery = deliver_breach_alert(report)
            report["alert"] = delivery.as_dict()
            if not delivery.attempted:
                # Silence is the worst outcome for a monitoring cron, so say it
                # out loud instead of exiting quietly.
                self.stderr.write(
                    "no alert channel configured: set ALERT_WEBHOOK_URL or "
                    "ALERT_EMAIL_TO to receive this breach"
                )

        self.stdout.write(json.dumps(report, sort_keys=True))
        if breaches:
            raise CommandError(
                "generation queue health check failed: " + ", ".join(breaches)
            )
