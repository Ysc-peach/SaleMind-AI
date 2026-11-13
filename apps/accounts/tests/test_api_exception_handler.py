"""The global API envelope must map database conflicts to 409, not 500."""

from django.db import IntegrityError
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from config.api_exceptions import api_exception_handler


def _context():
    return {"request": None, "view": None}


def test_integrity_error_becomes_a_safe_conflict():
    error = IntegrityError(
        'duplicate key value violates unique constraint "sales_secret_unique"'
    )

    response = api_exception_handler(error, _context())

    assert isinstance(response, Response)
    assert response.status_code == 409
    assert response.data == {
        "code": "conflict",
        "message": "The resource conflicts with the current state.",
    }
    assert "sales_secret_unique" not in str(response.data)


def test_drf_errors_keep_their_default_shape():
    response = api_exception_handler(NotFound(), _context())

    assert response.status_code == 404
