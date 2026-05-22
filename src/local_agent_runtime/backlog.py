from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import TaskRecord
from .store import SqliteRuntimeStore

BACKLOG_SCHEMA_VERSION = 1


def load_backlog(path: str | Path) -> list[dict[str, str | None]]:
    """Load dependency-free JSON task definitions from a file.

    Supported shapes are either a top-level list of task objects or
    ``{"version": 1, "tasks": [...]}``. Each task must include ``id``, ``role``,
    ``command``, and ``workspace``. ``branch`` is optional.
    """

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        version = raw.get("version", BACKLOG_SCHEMA_VERSION)
        if version != BACKLOG_SCHEMA_VERSION:
            raise ValueError(f"unsupported backlog version: {version}")
        tasks = raw.get("tasks")
    else:
        tasks = raw
    if not isinstance(tasks, list):
        raise ValueError("backlog JSON must be a list or an object with a tasks list")
    return [_normalize_task(item, index) for index, item in enumerate(tasks)]


def register_backlog(
    store: SqliteRuntimeStore,
    tasks: list[dict[str, str | None]],
    *,
    workspace_root: Path | None = None,
) -> list[TaskRecord]:
    """Register multiple task definitions and return created records."""

    created: list[TaskRecord] = []
    for item in tasks:
        created.append(
            store.register_task(
                item["id"] or "",
                item["role"] or "",
                item["command"] or "",
                item["workspace"] or "",
                item.get("branch"),
                workspace_root,
            )
        )
    return created


def export_backlog(store: SqliteRuntimeStore) -> dict[str, Any]:
    """Return a JSON-serializable snapshot of tasks and lifecycle events."""

    return {
        "version": BACKLOG_SCHEMA_VERSION,
        "tasks": [task.to_dict() for task in store.list_tasks()],
        "events": [event.to_dict() for event in store.read_events()],
    }


def _normalize_task(raw: Any, index: int) -> dict[str, str | None]:
    if not isinstance(raw, dict):
        raise ValueError(f"task at index {index} must be an object")
    required = ("id", "role", "command", "workspace")
    missing = [name for name in required if not str(raw.get(name, "")).strip()]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"task at index {index} is missing required fields: {joined}")
    normalized: dict[str, str | None] = {name: str(raw[name]) for name in required}
    branch = raw.get("branch")
    normalized["branch"] = None if branch is None else str(branch)
    return normalized
