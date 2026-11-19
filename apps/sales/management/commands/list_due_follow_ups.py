"""Report overdue follow-up tasks as one JSON line.

A follow-up nobody notices is the same as no follow-up at all, so this is
shaped like the queue check: readable output plus a non-zero exit code that a
scheduler can act on without parsing anything.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.sales.services.follow_ups import overdue_tasks


class Command(BaseCommand):
    help = "List overdue follow-up tasks; exit non-zero past --max-overdue."

    def add_arguments(self, parser):
        parser.add_argument("--max-overdue", type=int, default=0)

    def handle(self, *args, **options):
        today = timezone.localdate()
        rows = [
            {
                "id": task.pk,
                "opportunity_id": task.opportunity_id,
                "project_name": task.opportunity.project_name,
                "title": task.title,
                "due_on": task.due_on.isoformat(),
                "days_late": (today - task.due_on).days,
                "owner": task.owner.get_username(),
            }
            for task in overdue_tasks(today=today)
        ]
        self.stdout.write(
            json.dumps(
                {
                    "today": today.isoformat(),
                    "overdue": len(rows),
                    "thresholds": {"max_overdue": options["max_overdue"]},
                    "tasks": rows,
                },
                sort_keys=True,
            )
        )
        if len(rows) > options["max_overdue"]:
            raise CommandError(
                f"follow-up check failed: {len(rows)} overdue task(s)"
            )
