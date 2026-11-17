"""Breach alerts reach a channel, and every failure mode stays visible."""

import json
from datetime import timedelta
from io import StringIO
from urllib.error import URLError
from uuid import uuid4

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.sales.models import SolutionGenerationJob, SolutionGenerationJobStatus
from apps.sales.services import alerting, webhook_delivery
from apps.sales.tests.webhook_fakes import RecordingWebhook

pytestmark = pytest.mark.django_db(transaction=True)

REPORT = {
    "health": {"queued": 4, "running": 0, "stale_running": 1},
    "thresholds": {"max_queued": 10, "max_stale_running": 0},
    "breaches": ["stale_running"],
}


@pytest.fixture
def webhook(monkeypatch, settings):
    settings.ALERT_WEBHOOK_URL = "https://alerts.internal/hooks/queue"
    settings.WEBHOOK_TIMEOUT_SECONDS = 5
    recorder = RecordingWebhook()
    # Patch the transport, not the caller: the body, the status check and the
    # header building are exactly what this suite is meant to cover.
    monkeypatch.setattr(webhook_delivery, "urlopen", recorder)
    return recorder


def test_no_configured_channel_is_reported_rather_than_guessed(settings):
    settings.ALERT_WEBHOOK_URL = ""
    settings.ALERT_EMAIL_TO = ""

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.attempted == ()
    assert delivery.delivered == ()
    assert "no alert channel" in delivery.skipped_reason


def test_the_webhook_receives_one_compact_document(webhook, settings):
    settings.ALERT_EMAIL_TO = ""

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.delivered == ("webhook",)
    assert len(webhook.requests) == 1
    payload = webhook.payload()
    assert payload["kind"] == "generation_health_breach"
    assert payload["breaches"] == ["stale_running"]
    assert payload["health"]["stale_running"] == 1
    assert payload["generated_at"]
    # Nothing from the business tables may ride along with a queue alarm.
    assert "opportunity" not in json.dumps(payload)


def test_a_webhook_exception_is_recorded_not_raised(webhook, settings):
    settings.ALERT_EMAIL_TO = ""
    webhook.error = URLError("connection refused")

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.attempted == ("webhook",)
    assert delivery.delivered == ()
    assert delivery.failed == ("webhook",)


def test_a_non_2xx_answer_is_not_treated_as_delivered(webhook, settings):
    settings.ALERT_EMAIL_TO = ""
    webhook.status = 500

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.delivered == ()
    assert delivery.failed == ("webhook",)


def test_the_mail_channel_names_the_breaches(settings):
    settings.ALERT_WEBHOOK_URL = ""
    settings.ALERT_EMAIL_TO = "ops@example.internal, sre@example.internal"
    mail.outbox.clear()

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.delivered == ("email",)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["ops@example.internal", "sre@example.internal"]
    assert "stale_running" in message.subject
    assert "queued: 4" in message.body


def test_both_channels_are_used_when_both_are_configured(webhook, settings):
    settings.ALERT_EMAIL_TO = "ops@example.internal"
    mail.outbox.clear()

    delivery = alerting.deliver_breach_alert(REPORT)

    assert delivery.attempted == ("webhook", "email")
    assert delivery.delivered == ("webhook", "email")
    assert len(mail.outbox) == 1


def _add_stale_job(owner, opportunity, analysis):
    now = timezone.now()
    return SolutionGenerationJob.objects.create(
        workflow_id=uuid4(),
        opportunity=opportunity,
        requirement_analysis=analysis,
        requested_by=owner,
        status=SolutionGenerationJobStatus.RUNNING,
        attempts=1,
        started_at=now - timedelta(hours=2),
        heartbeat_at=now - timedelta(hours=1),
    )


def test_notify_delivers_and_still_fails_the_check(
    persistence_context, monkeypatch
):
    owner, _customer, opportunity, analysis, _create = persistence_context
    _add_stale_job(owner, opportunity, analysis)
    calls = []

    def deliver(report):
        calls.append(report)
        return alerting.AlertDelivery(
            attempted=("webhook",), delivered=("webhook",),
        )

    monkeypatch.setattr(
        "apps.sales.management.commands.check_generation_health.deliver_breach_alert",
        deliver,
    )

    output = StringIO()
    with pytest.raises(CommandError, match="stale_running"):
        call_command("check_generation_health", stdout=output, notify=True)

    report = json.loads(output.getvalue())
    assert report["alert"]["delivered"] == ["webhook"]
    # Delivery must not soften the exit code: cron still sees the breach.
    assert report["breaches"] == ["stale_running"]
    assert len(calls) == 1
    assert calls[0]["breaches"] == ["stale_running"]


def test_notify_is_silent_when_the_queue_is_healthy(
    persistence_context, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        "apps.sales.management.commands.check_generation_health.deliver_breach_alert",
        lambda report: calls.append(report),
    )

    output = StringIO()
    call_command("check_generation_health", stdout=output, notify=True)

    report = json.loads(output.getvalue())
    assert report["breaches"] == []
    assert "alert" not in report
    assert calls == []


def test_notify_without_a_channel_says_so_on_stderr(
    persistence_context, settings
):
    settings.ALERT_WEBHOOK_URL = ""
    settings.ALERT_EMAIL_TO = ""
    owner, _customer, opportunity, analysis, _create = persistence_context
    _add_stale_job(owner, opportunity, analysis)

    output = StringIO()
    errors = StringIO()
    with pytest.raises(CommandError, match="stale_running"):
        call_command(
            "check_generation_health",
            stdout=output,
            stderr=errors,
            notify=True,
        )

    assert "no alert channel configured" in errors.getvalue()
    assert json.loads(output.getvalue())["alert"]["attempted"] == []
