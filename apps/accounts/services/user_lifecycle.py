"""Who may create, change and stop a user account, and what stops a lockout.

Two rules shape this module and both exist to prevent a system nobody can
administer:

* the last active administrator cannot be deactivated or demoted;
* an administrator cannot deactivate themselves.

Everything else here is ordinary validation, plus revoking tokens whenever a
change alters what a live session is allowed to do.
"""

from __future__ import annotations

from enum import StrEnum

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import UserRole
from apps.accounts.services.tokens import revoke_outstanding_tokens


class UserAdminErrorCode(StrEnum):
    INVALID_INPUT = "user_invalid_input"
    FORBIDDEN = "user_forbidden"
    DUPLICATE = "user_duplicate"
    LAST_ADMIN = "user_last_admin"
    SELF_DEACTIVATION = "user_self_deactivation"


class UserAdminError(Exception):
    def __init__(self, code: UserAdminErrorCode, detail: str = ""):
        super().__init__(code.value)
        self.code = code
        self.detail = detail


def _require_admin(actor) -> None:
    if actor is None or actor.role != UserRole.ADMIN:
        raise UserAdminError(UserAdminErrorCode.FORBIDDEN)


def _active_admin_count() -> int:
    return (
        get_user_model()
        .objects.filter(role=UserRole.ADMIN, is_active=True)
        .count()
    )


def _is_only_active_admin(user) -> bool:
    return (
        user.role == UserRole.ADMIN
        and user.is_active
        and _active_admin_count() <= 1
    )


def _clean_name(value: str | None) -> str:
    return (value or "").strip()[:150]


def _validate_password(password: str, user) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as error:
        raise UserAdminError(
            UserAdminErrorCode.INVALID_INPUT, "; ".join(error.messages)
        ) from None


def create_user(
    *,
    actor,
    username: str,
    email: str,
    role: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
):
    _require_admin(actor)
    username = (username or "").strip()[:150]
    email = (email or "").strip()
    if not username or not email:
        raise UserAdminError(
            UserAdminErrorCode.INVALID_INPUT, "username and email are required"
        )
    if role not in UserRole.values:
        raise UserAdminError(UserAdminErrorCode.INVALID_INPUT, "unknown role")
    model = get_user_model()
    candidate = model(username=username, email=email)
    _validate_password(password, candidate)
    try:
        with transaction.atomic():
            return model.objects.create_user(
                username=username,
                email=email,
                role=role,
                password=password,
                first_name=_clean_name(first_name),
                last_name=_clean_name(last_name),
            )
    except IntegrityError:
        # Username and email are both unique; the message must not say which
        # rows exist, only that the pair is already taken.
        raise UserAdminError(
            UserAdminErrorCode.DUPLICATE, "username or email already exists"
        ) from None


def update_user(
    user,
    *,
    actor,
    role: str | None = None,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
):
    _require_admin(actor)
    changing_role = role is not None and role != user.role
    if changing_role:
        if role not in UserRole.values:
            raise UserAdminError(UserAdminErrorCode.INVALID_INPUT, "unknown role")
        if _is_only_active_admin(user):
            # Demoting the last administrator leaves nobody who can promote
            # anyone back, including whoever did the demotion.
            raise UserAdminError(UserAdminErrorCode.LAST_ADMIN)

    fields: list[str] = []
    if changing_role:
        user.role = role
        fields.append("role")
    if email is not None:
        email = email.strip()
        if not email:
            raise UserAdminError(UserAdminErrorCode.INVALID_INPUT, "email is empty")
        user.email = email
        fields.append("email")
    if first_name is not None:
        user.first_name = _clean_name(first_name)
        fields.append("first_name")
    if last_name is not None:
        user.last_name = _clean_name(last_name)
        fields.append("last_name")
    if not fields:
        return user

    try:
        with transaction.atomic():
            user.save(update_fields=fields)
    except IntegrityError:
        raise UserAdminError(
            UserAdminErrorCode.DUPLICATE, "email already exists"
        ) from None
    if changing_role:
        # The session was issued under the old role; keep it and the old rights
        # survive until the token expires.
        revoke_outstanding_tokens(user)
    return user


def set_user_active(user, *, actor, active: bool):
    _require_admin(actor)
    if user.is_active == active:
        return user
    if not active:
        if user.pk == getattr(actor, "pk", None):
            raise UserAdminError(UserAdminErrorCode.SELF_DEACTIVATION)
        if _is_only_active_admin(user):
            raise UserAdminError(UserAdminErrorCode.LAST_ADMIN)
    with transaction.atomic():
        user.is_active = active
        user.save(update_fields=["is_active"])
    if not active:
        revoke_outstanding_tokens(user)
    return user


def reset_password(user, *, actor, password: str):
    _require_admin(actor)
    _validate_password(password, user)
    user.set_password(password)
    with transaction.atomic():
        user.save(update_fields=["password"])
    revoke_outstanding_tokens(user)
    return user


def revoke_sessions(user, *, actor) -> int:
    _require_admin(actor)
    return revoke_outstanding_tokens(user)
