"""The readiness endpoint must report database reachability without leaking config."""

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_healthz_reports_ok_when_the_database_answers():
    response = Client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response["Cache-Control"].startswith("max-age=0")


def test_healthz_reports_degraded_when_the_database_is_unreachable(monkeypatch):
    from config import health

    class BrokenCursor:
        def __enter__(self):
            raise RuntimeError("connection refused")

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(health.connection, "cursor", lambda: BrokenCursor())

    response = Client().get("/healthz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "connection refused" not in response.content.decode()


def test_healthz_rejects_non_get_requests():
    response = Client().post("/healthz")

    assert response.status_code == 405
