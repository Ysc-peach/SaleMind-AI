"""Deliver a generation-health breach to the channel the operator configured.

`check_generation_health` already fails with a non-zero exit code, so anything
that can watch an exit code works. This covers the remaining case: a scheduler
that only records the failure, where nobody reads the log until someone notices
the queue has stopped draining. Two channels are supported — a JSON webhook that
chat bots and paging tools accept, and a plain mail to a fixed recipient list.

Nothing here may raise. An alert that fails to send must not turn a reported
breach into a crashed check, and must not be silently reported as delivered.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)

PAYLOAD_VERSION = 1


@dataclass(frozen=True)
class AlertDelivery:
    """What actually happened, so the caller can log it without guessing."""

    attempted: tuple[str, ...] = ()
    delivered: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    skipped_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "attempted": list(self.attempted),
            "delivered": list(self.delivered),
            "failed": list(self.failed),
            "skipped": self.skipped_reason,
        }


def build_payload(report: dict) -> dict:
    """One compact document: counts and breach names, never business content."""

    return {
        "version": PAYLOAD_VERSION,
        "kind": "generation_health_breach",
        "breaches": list(report.get("breaches") or []),
        "health": dict(report.get("health") or {}),
        "thresholds": dict(report.get("thresholds") or {}),
        "generated_at": timezone.now().isoformat(),
    }


def _post_json(url: str, payload: dict, timeout: int) -> None:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "salesmind-alert/1")
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
    if status >= 300:
        raise RuntimeError(f"webhook answered {status}")


def _alert_recipients() -> tuple[str, ...]:
    raw = getattr(settings, "ALERT_EMAIL_TO", "") or ""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _send_webhook(payload: dict) -> None:
    _post_json(
        settings.ALERT_WEBHOOK_URL,
        payload,
        max(1, settings.ALERT_WEBHOOK_TIMEOUT_SECONDS),
    )


def _send_email(payload: dict) -> None:
    breaches = ", ".join(payload["breaches"]) or "unknown"
    lines = [f"方案生成队列健康检查触发告警：{breaches}", ""]
    lines += [f"{key}: {value}" for key, value in payload["health"].items()]
    lines += ["", "阈值："]
    lines += [f"{key}: {value}" for key, value in payload["thresholds"].items()]
    lines += ["", "本邮件由 check_generation_health --notify 自动发送，只含计数，不含业务内容。"]
    send_mail(
        f"[SalesMind] 生成队列告警：{breaches}",
        "\n".join(lines),
        settings.DEFAULT_FROM_EMAIL,
        list(_alert_recipients()),
        fail_silently=False,
    )


def deliver_breach_alert(report: dict) -> AlertDelivery:
    """Send one alert; report what happened instead of assuming it worked."""

    channels: list[tuple[str, Any]] = []
    if getattr(settings, "ALERT_WEBHOOK_URL", ""):
        channels.append(("webhook", _send_webhook))
    if _alert_recipients():
        channels.append(("email", _send_email))
    if not channels:
        return AlertDelivery(skipped_reason="no alert channel configured")

    payload = build_payload(report)
    attempted: list[str] = []
    delivered: list[str] = []
    failed: list[str] = []
    for name, sender in channels:
        attempted.append(name)
        try:
            sender(payload)
        except Exception:
            # Never include the payload: the recipient list and the endpoint are
            # deployment details that do not belong in a log line.
            logger.warning("alert delivery failed via %s", name)
            failed.append(name)
        else:
            delivered.append(name)
    return AlertDelivery(tuple(attempted), tuple(delivered), tuple(failed))
