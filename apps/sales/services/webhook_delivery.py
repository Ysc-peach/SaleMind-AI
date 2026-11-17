"""One JSON-over-HTTP POST, shared by every outbound notification channel.

Both the queue alarm and the review ping need the same three things: a JSON
body, a short timeout, and a failure the caller can report without leaking the
endpoint. Keeping the transport here means the two channels cannot drift on the
status check or on how Chinese text is encoded.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

USER_AGENT = "salesmind-notify/1"


def post_json(url: str, payload: dict, *, timeout: int) -> None:
    """POST one JSON document; raise when the receiver does not accept it.

    A 2xx response is the only success. Everything else raises, including a
    redirect, because an alert that lands on a login page was not delivered and
    must not be reported as if it had been.
    """

    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, method="POST")
    # The charset matters: project names and reviewer names are Chinese, and a
    # receiver that assumes latin-1 would mangle them.
    request.add_header("Content-Type", "application/json; charset=utf-8")
    request.add_header("User-Agent", USER_AGENT)
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
    if status >= 300:
        raise RuntimeError(f"webhook answered {status}")
