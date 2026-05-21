from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .models import StaleTask, TaskRecord, TaskStatus, WorkerSpec, utc_now
from .sessions import SessionManager
from .store import SqliteRuntimeStore, task_dicts
from .workspaces import DirectoryWorkspaceManager, WorkspaceManager


@dataclass
class AgentTaskRuntime:
    store: SqliteRuntimeStore
    sessions: SessionManager
    workspaces: WorkspaceManager

    @classmethod
    def local(
        cls,
        db_path: str | Path,
        sessions: SessionManager,
        workspace_root: str | Path,
    ) -> AgentTaskRuntime:
        return cls(
            store=SqliteRuntimeStore(db_path),
            sessions=sessions,
            workspaces=DirectoryWorkspaceManager(Path(workspace_root)),
        )

    def register_task(
        self,
        task_id: str,
        role: str,
        command: str,
        workspace: str,
        branch: str | None = None,
    ) -> TaskRecord:
        root = (
            self.workspaces.root if isinstance(self.workspaces, DirectoryWorkspaceManager) else None
        )
        return self.store.register_task(task_id, role, command, workspace, branch, root)

    def start_task(self, task_id: str) -> TaskRecord:
        task = self.store.get_task(task_id)
        if task.status not in {TaskStatus.READY, TaskStatus.STOPPED, TaskStatus.BLOCKED}:
            raise ValueError(f"cannot start task in status {task.status.value}")
        workspace = self.workspaces.prepare(task)
        spec = WorkerSpec(command=task.command, cwd=str(workspace))
        session_id = self.sessions.start(task.id, spec)
        now = utc_now()
        return self.store.update_task(
            task.id,
            status=TaskStatus.RUNNING,
            session_id=session_id,
            started_at=now,
            heartbeat_at=now,
            event_kind="started",
            event_payload={"session_id": session_id, "workspace": str(workspace)},
        )

    def stop_task(
        self, task_id: str, status: TaskStatus | str = TaskStatus.BLOCKED, notes: str | None = None
    ) -> TaskRecord:
        next_status = TaskStatus(status)
        if next_status not in {TaskStatus.STOPPED, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise ValueError("stop status must be stopped, blocked, or failed")
        task = self.store.get_task(task_id)
        if task.session_id:
            self.sessions.stop(task.session_id)
        return self.store.update_task(
            task.id,
            status=next_status,
            notes=notes,
            session_id=None,
            event_kind="stopped",
            event_payload={"notes": notes, "requested_status": next_status.value},
        )

    def mark_done(self, task_id: str, notes: str | None = None) -> TaskRecord:
        task = self.store.get_task(task_id)
        if task.session_id and self.sessions.exists(task.session_id):
            self.sessions.stop(task.session_id)
        return self.store.update_task(
            task.id,
            status=TaskStatus.DONE,
            notes=notes,
            session_id=None,
            completed_at=utc_now(),
            event_kind="done",
            event_payload={"notes": notes},
        )

    def heartbeat(self, task_id: str) -> TaskRecord:
        return self.store.update_task(
            task_id,
            heartbeat_at=utc_now(),
            event_kind="heartbeat",
            event_payload={},
        )

    def compute_stale_tasks(self, stale_after: timedelta) -> list[StaleTask]:
        now = utc_now()
        stale: list[StaleTask] = []
        for task in self.store.list_tasks(TaskStatus.RUNNING):
            if not task.session_id:
                stale.append(
                    StaleTask(task.id, "session_missing", "running task has no session id")
                )
                continue
            if not self.sessions.exists(task.session_id):
                stale.append(
                    StaleTask(task.id, "session_missing", f"session not found: {task.session_id}")
                )
                continue
            if task.heartbeat_at and now - task.heartbeat_at > stale_after:
                stale.append(
                    StaleTask(
                        task.id,
                        "heartbeat_stale",
                        f"last heartbeat: {task.heartbeat_at.isoformat()}",
                    )
                )
        return stale

    def sync_runtime(self, stale_after: timedelta = timedelta(minutes=30)) -> dict[str, Any]:
        stale = self.compute_stale_tasks(stale_after)
        stopped: list[str] = []
        for item in stale:
            if item.reason == "session_missing":
                self.store.update_task(
                    item.task_id,
                    status=TaskStatus.STOPPED,
                    session_id=None,
                    event_kind="sync_stopped",
                    event_payload={"reason": item.reason, "detail": item.detail},
                )
                stopped.append(item.task_id)
            else:
                self.store.append_event(item.task_id, "stale", item.to_dict())
        return {"stale": [item.to_dict() for item in stale], "stopped": stopped}

    def summary(self) -> dict[str, Any]:
        running = self.store.list_tasks(TaskStatus.RUNNING)
        recent_events = [event.to_dict() for event in self.store.read_events(limit=20)]
        return {
            "counts": self.store.counts_by_status(),
            "active_tasks": task_dicts(running),
            "stale_tasks": [
                item.to_dict() for item in self.compute_stale_tasks(timedelta(minutes=30))
            ],
            "recent_events": recent_events,
        }
