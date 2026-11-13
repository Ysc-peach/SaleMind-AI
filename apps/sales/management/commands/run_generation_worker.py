"""Execute queued Solution generation jobs.

Run this next to gunicorn: ``python manage.py run_generation_worker``. It polls
the same PostgreSQL database the application uses, so no broker is required.
"""

import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.sales.services.solution_generation_jobs import (
    claim_next_job,
    execute_job,
)


class Command(BaseCommand):
    help = "Claim and execute queued Solution generation jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one job, then exit.",
        )
        parser.add_argument(
            "--poll-seconds",
            type=float,
            default=5.0,
            help="Idle wait between polls (default 5).",
        )

    def handle(self, *args, **options):
        poll_seconds = max(0.5, float(options["poll_seconds"]))
        try:
            while True:
                close_old_connections()
                job = claim_next_job()
                if job is None:
                    if options["once"]:
                        self.stdout.write("no queued job")
                        return
                    time.sleep(poll_seconds)
                    continue
                status = execute_job(job)
                self.stdout.write(f"job {job.pk} -> {status}")
                if options["once"]:
                    return
        except KeyboardInterrupt:  # pragma: no cover - operator action
            self.stdout.write("worker stopped")
