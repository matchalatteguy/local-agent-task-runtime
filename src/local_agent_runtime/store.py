from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import (
    TaskEvent,
    TaskRecord,
    TaskStatus,
    parse_dt,
    require_relative_or_contained,
    utc_now,
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SENTINEL = object()
SCHEMA_VERSION = 1


class SqliteRuntimeStore:
    """SQLite-backed task table and append-only event log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    command TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    session_id TEXT,
                    branch TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    heartbeat_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id, id);
                """
            )
            current_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {current_version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if current_version == 0:
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def schema_version(self) -> int:
        """Return the SQLite schema version stored in PRAGMA user_version."""

        with self.connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def register_task(
        self,
        task_id: str,
        role: str,
        command: str,
        workspace: str,
        branch: str | None = None,
        workspace_root: Path | None = None,
    ) -> TaskRecord:
        self._validate_task_id(task_id)
        if not role.strip():
            raise ValueError("role is required")
        if not command.strip():
            raise ValueError("command is required")
        safe_workspace = require_relative_or_contained(workspace, workspace_root)
        now = utc_now()
        record = TaskRecord(
            id=task_id,
            role=role,
            command=command,
            workspace=safe_workspace,
            branch=branch,
            created_at=now,
            updated_at=now,
        )
        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO tasks
                    (id, role, command, workspace, status, session_id, branch, notes,
                     created_at, updated_at, started_at, completed_at, heartbeat_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._task_values(record),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"task already exists: {task_id}") from exc
            self._append_event(
                conn, task_id, "registered", {"role": role, "workspace": safe_workspace}
            )
        return record

    def get_task(self, task_id: str) -> TaskRecord:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    def list_tasks(self, status: TaskStatus | str | None = None) -> list[TaskRecord]:
        params: tuple[str, ...] = ()
        clause = ""
        if status:
            value = TaskStatus(status).value
            clause = "WHERE status = ?"
            params = (value,)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks {clause} ORDER BY created_at ASC, id ASC", params
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def ready_tasks(self, limit: int | None = None) -> list[TaskRecord]:
        tasks = self.list_tasks(TaskStatus.READY)
        return tasks if limit is None else tasks[:limit]

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | str | None = None,
        session_id: str | None | object = _SENTINEL,
        notes: str | None | object = _SENTINEL,
        started_at: Any = _SENTINEL,
        completed_at: Any = _SENTINEL,
        heartbeat_at: Any = _SENTINEL,
        event_kind: str | None = None,
        event_payload: dict[str, Any] | None = None,
    ) -> TaskRecord:
        current = self.get_task(task_id)
        values: dict[str, Any] = {"updated_at": utc_now().isoformat()}
        if status is not None:
            values["status"] = TaskStatus(status).value
        if session_id is not _SENTINEL:
            values["session_id"] = session_id
        if notes is not _SENTINEL:
            values["notes"] = notes
        if started_at is not _SENTINEL:
            values["started_at"] = started_at.isoformat() if started_at else None
        if completed_at is not _SENTINEL:
            values["completed_at"] = completed_at.isoformat() if completed_at else None
        if heartbeat_at is not _SENTINEL:
            values["heartbeat_at"] = heartbeat_at.isoformat() if heartbeat_at else None
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = [*values.values(), task_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", params)
            if event_kind:
                payload = event_payload or {}
                if status is not None and current.status.value != TaskStatus(status).value:
                    payload = {
                        "from": current.status.value,
                        "to": TaskStatus(status).value,
                        **payload,
                    }
                self._append_event(conn, task_id, event_kind, payload)
        return self.get_task(task_id)

    def append_event(
        self, task_id: str, kind: str, payload: dict[str, Any] | None = None
    ) -> TaskEvent:
        self.get_task(task_id)
        with self.connect() as conn:
            return self._append_event(conn, task_id, kind, payload or {})

    def read_events(self, task_id: str | None = None, limit: int | None = None) -> list[TaskEvent]:
        params: list[Any] = []
        clause = ""
        if task_id:
            self.get_task(task_id)
            clause = "WHERE task_id = ?"
            params.append(task_id)
        if limit is None:
            suffix = "ORDER BY id ASC"
        else:
            suffix = "ORDER BY id DESC LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT * FROM events {clause} {suffix}", params).fetchall()
        events = [self._row_to_event(row) for row in rows]
        if limit is not None:
            events.reverse()
        return events

    def counts_by_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    @staticmethod
    def _validate_task_id(task_id: str) -> None:
        if not _ID_RE.match(task_id):
            raise ValueError(
                "task id must be 1-128 characters of letters, numbers, '.', '_' or '-'"
            )

    @staticmethod
    def _task_values(task: TaskRecord) -> tuple[Any, ...]:
        data = task.to_dict()
        return (
            data["id"],
            data["role"],
            data["command"],
            data["workspace"],
            data["status"],
            data["session_id"],
            data["branch"],
            data["notes"],
            data["created_at"],
            data["updated_at"],
            data["started_at"],
            data["completed_at"],
            data["heartbeat_at"],
        )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            role=row["role"],
            command=row["command"],
            workspace=row["workspace"],
            status=TaskStatus(row["status"]),
            session_id=row["session_id"],
            branch=row["branch"],
            notes=row["notes"],
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            started_at=parse_dt(row["started_at"]),
            completed_at=parse_dt(row["completed_at"]),
            heartbeat_at=parse_dt(row["heartbeat_at"]),
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            id=row["id"],
            task_id=row["task_id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            created_at=parse_dt(row["created_at"]),
        )

    @staticmethod
    def _append_event(
        conn: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, Any]
    ) -> TaskEvent:
        created_at = utc_now()
        cur = conn.execute(
            "INSERT INTO events (task_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (task_id, kind, json.dumps(payload, sort_keys=True), created_at.isoformat()),
        )
        return TaskEvent(
            id=int(cur.lastrowid),
            task_id=task_id,
            kind=kind,
            payload=payload,
            created_at=created_at,
        )


def task_dicts(tasks: Iterable[TaskRecord]) -> list[dict[str, Any]]:
    return [task.to_dict() for task in tasks]
