"""Shared rules for records an administrator has stopped using.

Customers and opportunities are archived rather than deleted, because drafts,
reviews and provenance all point at them. "Archived" therefore has to mean three
things consistently everywhere: history still reads, new work is refused, and
only an administrator can change the flag.
"""

from rest_framework.exceptions import APIException, PermissionDenied

from apps.accounts.models import UserRole

#: Query parameter that asks a list endpoint to include archived rows.
INCLUDE_INACTIVE_PARAM = "include_inactive"


class RecordInactive(APIException):
    """409, not 400: the request is well formed, the record's state is not."""

    status_code = 409
    default_detail = "该记录已停用，需管理员恢复后才能继续。"
    default_code = "record_inactive"


def require_active(record):
    """Refuse new work on an archived record, e.g. generating a solution."""

    if not getattr(record, "is_active", True):
        raise RecordInactive()
    return record


def include_inactive_requested(request) -> bool:
    raw = (request.query_params.get(INCLUDE_INACTIVE_PARAM) or "").strip().lower()
    return raw in {"1", "true", "yes"}


def require_admin_for_archived_view(request) -> None:
    """Only an administrator may ask a list for the archived rows."""

    if (
        include_inactive_requested(request)
        and getattr(request.user, "role", None) != UserRole.ADMIN
    ):
        raise PermissionDenied("只有管理员可以查看已停用的记录。")


def require_admin(user) -> None:
    if getattr(user, "role", None) != UserRole.ADMIN:
        raise PermissionDenied("只有管理员可以停用或恢复记录。")
