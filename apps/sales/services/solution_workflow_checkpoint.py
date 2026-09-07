"""Explicit official PostgreSQL checkpoint lifecycle for Solution workflows."""

from __future__ import annotations

from contextlib import contextmanager

from django.conf import settings
from langgraph.checkpoint.postgres import PostgresSaver


class SolutionWorkflowCheckpointConfigurationError(Exception):
    """Raised when durable workflow checkpoint storage is not configured."""


def _checkpoint_conninfo(conninfo: str | None = None) -> str:
    configured = conninfo if conninfo is not None else settings.LANGGRAPH_CHECKPOINT_DATABASE_URL
    if not isinstance(configured, str) or not configured.strip():
        raise SolutionWorkflowCheckpointConfigurationError(
            "LangGraph PostgreSQL checkpoint storage is not configured."
        )
    return configured


@contextmanager
def open_solution_workflow_checkpointer(conninfo: str | None = None):
    """Open a durable checkpointer; callers control its complete lifetime."""

    with PostgresSaver.from_conn_string(_checkpoint_conninfo(conninfo)) as checkpointer:
        yield checkpointer


def setup_solution_workflow_checkpoint_schema(conninfo: str | None = None) -> None:
    """Explicitly create/update official checkpoint tables for one database."""

    with open_solution_workflow_checkpointer(conninfo) as checkpointer:
        checkpointer.setup()
