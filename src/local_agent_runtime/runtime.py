from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .models import StaleTask, TaskRecord, TaskStatus, WorkerSpec, utc_now
from .sessions import SessionManager
from .store import SqliteRuntimeStore, TaskStateConflict, task_dicts
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

    def start_task(self, task_id: str, max_concurrent: int | None = None) -> TaskRecord:
        task = self.store.claim_for_start(task_id, max_concurrent=max_concurrent)
        try:
            workspace = self.workspaces.prepare(task)
            prefix = getattr(self.sessions, "prefix", "agent-runtime")
            session_name = f"{prefix}-{task.id}-{task.launch_token}"
            spec = WorkerSpec(
                command=task.command,
                cwd=str(workspace),
                session_name=session_name,
            )
            session_id = self.sessions.start(task.id, spec)
        except Exception as exc:
            with suppress(TaskStateConflict):  # preserve an operator's intervening state change
                self.store.update_task(
                    task.id,
                    status=task.status,
                    expected_status=TaskStatus.STARTING,
                    expected_launch_token=task.launch_token,
                    event_kind="start_failed",
                    event_payload={"error": str(exc)},
                )
            raise
        now = utc_now()
        try:
            return self.store.update_task(
                task.id,
                status=TaskStatus.RUNNING,
                expected_status=TaskStatus.STARTING,
                expected_launch_token=task.launch_token,
                session_id=session_id,
                started_at=now,
                heartbeat_at=now,
                event_kind="started",
                event_payload={"session_id": session_id, "workspace": str(workspace)},
            )
        except TaskStateConflict:
            # A fast worker or operator may have completed/stopped the task while
            # the adapter was launching. Never overwrite that final state.
            current = self.store.get_task(task_id)
            if current.session_id != session_id:
                self.sessions.stop(session_id)
            return self.store.get_task(task_id)

    def stop_task(
        self, task_id: str, status: TaskStatus | str = TaskStatus.BLOCKED, notes: str | None = None
    ) -> TaskRecord:
        next_status = TaskStatus(status)
        if next_status not in {TaskStatus.STOPPED, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise ValueError("stop status must be stopped, blocked, or failed")
        task = self.store.get_task(task_id)
        result = self.store.update_task(
            task.id,
            status=next_status,
            notes=notes,
            session_id=None,
            event_kind="stopped",
            event_payload={"notes": notes, "requested_status": next_status.value},
            expected_launch_token=task.launch_token,
        )
        if task.session_id:
            self.sessions.stop(task.session_id)
        return result

    def mark_done(self, task_id: str, notes: str | None = None) -> TaskRecord:
        task = self.store.get_task(task_id)
        result = self.store.update_task(
            task.id,
            status=TaskStatus.DONE,
            notes=notes,
            session_id=None,
            completed_at=utc_now(),
            event_kind="done",
            event_payload={"notes": notes},
            expected_launch_token=task.launch_token,
        )
        # Persist completion first: calling `done` inside a tmux worker may
        # terminate the calling process when its own session is stopped.
        if task.session_id and self.sessions.exists(task.session_id):
            self.sessions.stop(task.session_id)
        return result

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
        for task in self.store.list_tasks(TaskStatus.STARTING):
            if now - task.updated_at > stale_after:
                stale.append(
                    StaleTask(
                        task.id,
                        "launch_stale",
                        "worker launch was interrupted",
                        task.launch_token,
                    )
                )
        for task in self.store.list_tasks(TaskStatus.RUNNING):
            if not task.session_id:
                stale.append(
                    StaleTask(
                        task.id,
                        "session_missing",
                        "running task has no session id",
                        task.launch_token,
                    )
                )
                continue
            if not self.sessions.exists(task.session_id):
                stale.append(
                    StaleTask(
                        task.id,
                        "session_missing",
                        f"session not found: {task.session_id}",
                        task.launch_token,
                    )
                )
                continue
            if task.heartbeat_at and now - task.heartbeat_at > stale_after:
                stale.append(
                    StaleTask(
                        task.id,
                        "heartbeat_stale",
                        f"last heartbeat: {task.heartbeat_at.isoformat()}",
                        task.launch_token,
                    )
                )
        return stale

    def sync_runtime(self, stale_after: timedelta = timedelta(minutes=30)) -> dict[str, Any]:
        stale = self.compute_stale_tasks(stale_after)
        stopped: list[str] = []
        for item in stale:
            if item.reason in {"session_missing", "launch_stale"}:
                expected = (
                    TaskStatus.STARTING if item.reason == "launch_stale" else TaskStatus.RUNNING
                )
                try:
                    self.store.update_task(
                        item.task_id,
                        status=TaskStatus.STOPPED,
                        session_id=None,
                        expected_status=expected,
                        expected_launch_token=item.launch_token,
                        event_kind="sync_stopped",
                        event_payload={"reason": item.reason, "detail": item.detail},
                    )
                except TaskStateConflict:
                    continue
                stopped.append(item.task_id)
            else:
                self.store.append_event(item.task_id, "stale", item.to_dict())
        return {"stale": [item.to_dict() for item in stale], "stopped": stopped}

    def summary(self, stale_after: timedelta = timedelta(minutes=30)) -> dict[str, Any]:
        running = self.store.active_tasks()
        recent_events = [event.to_dict() for event in reversed(self.store.read_events(limit=20))]
        return {
            "counts": self.store.counts_by_status(),
            "active_tasks": task_dicts(running),
            "stale_after_seconds": int(stale_after.total_seconds()),
            "stale_tasks": [item.to_dict() for item in self.compute_stale_tasks(stale_after)],
            "recent_events": recent_events,
        }
