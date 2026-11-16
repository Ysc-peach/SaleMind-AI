"""Reviewer mail is opt-in, content-free, and never breaks a submission."""

import pytest
from django.core import mail

from apps.sales.services.review_notifications import notify_review_assigned
from apps.sales.services.solution_review import submit_solution_draft_for_review
from apps.sales.tests.test_solution_review_service import (  # noqa: F401
    review_service_context,
)

# The submission commits its own transaction, so on_commit callbacks only run
# under the non-wrapping test marker.
pytestmark = pytest.mark.django_db(transaction=True)


def _submit(context):
    solution = context["make_solution"]()
    return submit_solution_draft_for_review(solution, actor=context["sales"])


def test_a_disabled_flag_sends_nothing(settings, review_service_context):
    settings.NOTIFICATION_EMAIL_ENABLED = False

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

    def explode(*args, **kwargs):
        raise OSError("smtp unreachable")

    monkeypatch.setattr(
        "apps.sales.services.review_notifications.send_mail", explode
    )

    review = _submit(review_service_context)

    assert review.pk is not None
    assert mail.outbox == []
