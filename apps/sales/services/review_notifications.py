"""Tell the assigned reviewer that a draft is waiting for them.

The mail is a pointer, not a copy: it names the project, the version and a link,
and never repeats draft text. That keeps the review record the single place the
content lives, and keeps customer material out of mail servers.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def review_url(solution_draft_id: int) -> str:
    base = (settings.SALESMIND_PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/solutions/{solution_draft_id}" if base else ""


def _message(review) -> tuple[str, str, str]:
    draft = review.solution_draft
    project = draft.opportunity.project_name
    reviewer = review.reviewer
    name = reviewer.get_full_name().strip() or reviewer.username
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


def notify_review_assigned(review) -> bool:
    """Send one notice; return whether a mail was actually handed to the backend.

    Callers must treat this as best-effort: a mail server problem is logged and
    swallowed so a business transition never fails because of it.
    """

    if not settings.NOTIFICATION_EMAIL_ENABLED:
        return False
    reviewer = getattr(review, "reviewer", None)
    if reviewer is None or not (getattr(reviewer, "email", "") or "").strip():
        return False

    subject, body, recipient = _message(review)
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
