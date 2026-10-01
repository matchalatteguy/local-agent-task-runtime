from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class TaskStatus(StrEnum):
    READY = "ready"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


TERMINAL_STATUSES = {TaskStatus.DONE, TaskStatus.FAILED}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass(frozen=True)
class WorkerSpec:
    command: str
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    session_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskRecord:
    id: str
    role: str
    command: str
    workspace: str
    status: TaskStatus = TaskStatus.READY
    session_id: str | None = None
    branch: str | None = None
    notes: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "command": self.command,
            "workspace": self.workspace,
            "status": self.status.value,
            "session_id": self.session_id,
            "branch": self.branch,
            "notes": self.notes,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
            "started_at": to_iso(self.started_at),
            "completed_at": to_iso(self.completed_at),
            "heartbeat_at": to_iso(self.heartbeat_at),
        }


@dataclass(frozen=True)
class TaskEvent:
    task_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "kind": self.kind,
            "payload": self.payload,
            "created_at": to_iso(self.created_at),
        }


@dataclass(frozen=True)
class StaleTask:
    task_id: str
    reason: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DispatchResult:
    started: list[str]
    skipped: dict[str, str]
    active_count: int
    capacity_remaining: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def require_relative_or_contained(path: str, root: Path | None = None) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        if root is None:
            raise ValueError("absolute workspace paths require an explicit root")
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        if resolved_root != resolved_candidate and resolved_root not in resolved_candidate.parents:
            raise ValueError("workspace path must stay inside the workspace root")
        return str(resolved_candidate)
    if ".." in candidate.parts:
        raise ValueError("workspace path must not contain '..'")
    if root is not None:
        resolved_root = root.resolve()
        resolved_candidate = (resolved_root / candidate).resolve()
        if resolved_root != resolved_candidate and resolved_root not in resolved_candidate.parents:
            raise ValueError("workspace path must stay inside the workspace root")
    return str(candidate)
