"""Tell the assigned reviewer that a draft is waiting for them.

Two opt-in channels: a JSON webhook for chat bots and mail for anyone who lives
in their inbox. Both are pointers rather than copies — project name, version and
a link — so the review record stays the only place the content lives.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

from apps.sales.services.webhook_delivery import post_json

logger = logging.getLogger(__name__)

REVIEW_EVENT = "solution_review_assigned"
PAYLOAD_VERSION = 1


def review_url(solution_draft_id: int) -> str:
    base = (settings.SALESMIND_PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/solutions/{solution_draft_id}" if base else ""


def _display(user) -> str:
    if user is None:
        return ""
    return user.get_full_name().strip() or user.username


def build_payload(review) -> dict:
    """The same facts the mail carries, in a shape a chat bot can post."""

    draft = review.solution_draft
    return {
        "version": PAYLOAD_VERSION,
        "kind": REVIEW_EVENT,
        "review_id": review.pk,
        "project": draft.opportunity.project_name,
        "solution_version": draft.version,
        "reviewer": _display(review.reviewer),
        "submitted_by": _display(review.submitted_by),
        "url": review_url(draft.pk),
    }


def _message(review) -> tuple[str, str, str]:
    draft = review.solution_draft
    project = draft.opportunity.project_name
    reviewer = review.reviewer
    name = _display(reviewer)
    lines = [
        f"{name}，你有一份方案等待技术审核。",
        "",
        f"商机：{project}",
        f"方案版本：V{draft.version}",
    ]
    link = review_url(draft.pk)
    if link:
        lines += ["", f"打开：{link}"]
    lines += ["", "本邮件只提示待办，方案正文请在系统内查看。"]
    return f"新方案待审核：{project}", "\n".join(lines), reviewer.email


def _deliver_webhook(review) -> bool:
    url = (getattr(settings, "REVIEW_WEBHOOK_URL", "") or "").strip()
    if not url:
        return False
    try:
        post_json(
            url,
            build_payload(review),
            timeout=max(1, settings.WEBHOOK_TIMEOUT_SECONDS),
        )
    except Exception:
        # Do not log the endpoint or the payload: both identify the deployment
        # and, for the payload, the customer.
        logger.warning("review webhook failed for review %s", review.pk)
        return False
    return True


def _deliver_mail(review) -> bool:
    if not settings.NOTIFICATION_EMAIL_ENABLED:
        return False
    reviewer = getattr(review, "reviewer", None)
    recipient = (getattr(reviewer, "email", "") or "").strip() if reviewer else ""
    if not recipient:
        return False
    subject, body, _ = _message(review)
    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
    except Exception:
        # Do not log the message or the address: both identify a person.
        logger.warning("review notification failed for review %s", review.pk)
        return False
    return True


def notify_review_assigned(review) -> bool:
    """Try every configured channel; report whether any of them delivered.

    Callers must treat this as best-effort: a webhook or mail server problem is
    logged and swallowed so a business transition never fails because of it.
    """

    delivered = False
    if _deliver_webhook(review):
        delivered = True
    if _deliver_mail(review):
        delivered = True
    return delivered
