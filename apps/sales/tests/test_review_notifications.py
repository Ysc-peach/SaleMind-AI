"""Reviewer notices are opt-in, content-free, and never break a submission."""

import json
from urllib.error import URLError

import pytest
from django.core import mail

from apps.sales.services import webhook_delivery
from apps.sales.services.review_notifications import notify_review_assigned
from apps.sales.services.solution_review import submit_solution_draft_for_review
from apps.sales.tests.test_solution_review_service import (  # noqa: F401
    review_service_context,
)
from apps.sales.tests.webhook_fakes import RecordingWebhook

# The submission commits its own transaction, so on_commit callbacks only run
# under the non-wrapping test marker.
pytestmark = pytest.mark.django_db(transaction=True)


def _submit(context):
    solution = context["make_solution"]()
    return submit_solution_draft_for_review(solution, actor=context["sales"])


@pytest.fixture
def review_webhook(monkeypatch, settings):
    settings.REVIEW_WEBHOOK_URL = "https://chat.internal/hooks/reviews"
    settings.WEBHOOK_TIMEOUT_SECONDS = 5
    settings.NOTIFICATION_EMAIL_ENABLED = False
    recorder = RecordingWebhook()
    monkeypatch.setattr(webhook_delivery, "urlopen", recorder)
    return recorder


def test_a_disabled_flag_sends_nothing(settings, review_service_context):
    settings.NOTIFICATION_EMAIL_ENABLED = False
    settings.REVIEW_WEBHOOK_URL = ""

    review = _submit(review_service_context)

    assert review.pk is not None
    assert mail.outbox == []


def test_an_enabled_flag_mails_the_assigned_reviewer(
    settings, review_service_context
):
    settings.NOTIFICATION_EMAIL_ENABLED = True
    settings.SALESMIND_PUBLIC_BASE_URL = "https://salesmind.internal/"

    review = _submit(review_service_context)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [review.reviewer.email]
    assert "Review service opportunity" in message.subject
    assert "https://salesmind.internal/solutions/" in message.body
    # The mail is a pointer: the draft title itself must not be copied into it.
    assert review.solution_draft.title not in message.body


def test_a_reviewer_without_an_address_is_skipped(
    settings, review_service_context
):
    settings.NOTIFICATION_EMAIL_ENABLED = True
    review = _submit(review_service_context)
    mail.outbox.clear()
    review.reviewer.email = ""
    review.reviewer.save(update_fields=["email"])

    assert notify_review_assigned(review) is False
    assert mail.outbox == []


def test_a_mail_failure_does_not_fail_the_submission(
    settings, review_service_context, monkeypatch
):
    settings.NOTIFICATION_EMAIL_ENABLED = True
    settings.REVIEW_WEBHOOK_URL = ""

    def explode(*args, **kwargs):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(
        "apps.sales.services.review_notifications.send_mail", explode
    )

    review = _submit(review_service_context)

    assert review.pk is not None
    assert mail.outbox == []


def test_the_webhook_points_at_the_review_without_the_draft(
    settings, review_webhook, review_service_context
):
    settings.SALESMIND_PUBLIC_BASE_URL = "https://salesmind.internal"

    review = _submit(review_service_context)

    assert len(review_webhook.requests) == 1
    payload = review_webhook.payload()
    assert payload["kind"] == "solution_review_assigned"
    assert payload["review_id"] == review.pk
    assert payload["project"] == "Review service opportunity"
    assert payload["solution_version"] == review.solution_draft.version
    assert payload["url"].endswith(f"/solutions/{review.solution_draft_id}")
    # A pointer, not a copy: the draft title must not travel to a chat room.
    assert review.solution_draft.title not in json.dumps(
        payload, ensure_ascii=False
    )
    assert mail.outbox == []


def test_a_webhook_failure_does_not_fail_the_submission(
    settings, review_webhook, review_service_context
):
    review_webhook.error = URLError("connection refused")

    review = _submit(review_service_context)

    assert review.pk is not None
    assert len(review_webhook.requests) == 1
    assert mail.outbox == []


def test_both_channels_fire_when_both_are_configured(
    settings, review_webhook, review_service_context
):
    settings.NOTIFICATION_EMAIL_ENABLED = True

    review = _submit(review_service_context)

    assert review.reviewer.email
    assert len(review_webhook.requests) == 1
    assert len(mail.outbox) == 1


def test_the_webhook_still_reaches_a_reviewer_without_an_address(
    settings, review_webhook, review_service_context
):
    settings.NOTIFICATION_EMAIL_ENABLED = True
    review = _submit(review_service_context)
    review_webhook.requests.clear()
    mail.outbox.clear()
    review.reviewer.email = ""
    review.reviewer.save(update_fields=["email"])

    # The chat channel does not depend on the mailbox existing, which is the
    # whole point of supporting it.
    assert notify_review_assigned(review) is True
    assert len(review_webhook.requests) == 1
    assert mail.outbox == []
