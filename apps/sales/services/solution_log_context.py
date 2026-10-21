"""Typed request correlation only; this context is not business authority."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID

_workflow_id: ContextVar[UUID | None] = ContextVar("solution_log_workflow_id", default=None)


@contextmanager
def solution_log_scope(workflow_id: UUID) -> Iterator[None]:
    if not isinstance(workflow_id, UUID):
        raise TypeError("Workflow log identifiers must be UUID instances.")
    token = _workflow_id.set(workflow_id)
    try:
        yield
    finally:
        _workflow_id.reset(token)


def current_solution_workflow_id() -> str | None:
    value = _workflow_id.get()
    return str(value) if value is not None else None
