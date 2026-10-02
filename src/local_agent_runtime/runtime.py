from __future__ import annotations

import math
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from .models import StaleTask, TaskRecord, TaskStatus, WorkerSpec, utc_now
from .sessions import FakeSessionManager, SessionManager, TmuxSessionManager
from .store import SqliteRuntimeStore, TaskStateConflict, task_dicts
from .workspaces import DirectoryWorkspaceManager, WorkspaceManager


@dataclass
class AgentTaskRuntime:
    store: SqliteRuntimeStore
    sessions: SessionManager
    workspaces: WorkspaceManager

    def _sessions_for(self, task: TaskRecord) -> SessionManager:
        from .process import ProcessSessionManager

        if task.session_kind == "process":
            return ProcessSessionManager(self.store.path)
        if task.session_kind == "tmux" and getattr(self.sessions, "kind", None) != "tmux":
            return TmuxSessionManager()
        if task.session_kind == "fake" and getattr(self.sessions, "kind", None) != "fake":
            return FakeSessionManager(state_path=Path(str(self.store.path) + ".fake-sessions.json"))
        return self.sessions

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
            self.store.update_task(
                task_id,
                session_kind=getattr(self.sessions, "kind", None),
                expected_status=TaskStatus.STARTING,
                expected_launch_token=task.launch_token,
            )
            workspace = self.workspaces.prepare(task)
            prefix = getattr(self.sessions, "prefix", "agent-runtime")
            session_name = f"{prefix}-{task.id}-{task.launch_token}"
            spec = WorkerSpec(
                command=task.command,
                cwd=str(workspace),
                session_name=session_name,
                launch_token=task.launch_token,
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
        if getattr(self.sessions, "kind", None) == "process":
            # The independent supervisor owns start/finish recording. Returning
            # from this CLI or Python call has no bearing on worker liveness.
            return self.store.get_task(task_id)
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
                session_kind=getattr(self.sessions, "kind", None),
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
        if task.session_kind == "process" and task.launch_token:
            from .process import ProcessStore

            ProcessStore(self.store).cancel(task.launch_token, next_status, notes)
            return self.store.get_task(task_id)
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
            self._sessions_for(task).stop(task.session_id)
        return result

    def mark_done(self, task_id: str, notes: str | None = None) -> TaskRecord:
        task = self.store.get_task(task_id)
        if task.session_kind == "process":
            raise ValueError("process tasks complete from their exit code; use stop to cancel")
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
        sessions = self._sessions_for(task)
        if task.session_id and sessions.exists(task.session_id):
            sessions.stop(task.session_id)
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
                reason = "launch_stale"
                if task.session_kind == "process" and task.launch_token:
                    from .process import ProcessStore

                    try:
                        run = ProcessStore(self.store).get(task.launch_token)
                    except KeyError:
                        pass  # claim interrupted before an attempt was prepared
                    else:
                        if self._sessions_for(task).exists(run["session_id"]):
                            continue
                        reason = "process_runner_missing"
                stale.append(
                    StaleTask(
                        task.id,
                        reason,
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
            if not self._sessions_for(task).exists(task.session_id):
                stale.append(
                    StaleTask(
                        task.id,
                        "process_runner_missing"
                        if task.session_kind == "process"
                        else "session_missing",
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
            if item.reason == "process_runner_missing":
                from .process import ProcessSessionManager

                # The runner may finish or regain its lock during inspection.
                with suppress(ValueError):
                    ProcessSessionManager(self.store.path).recover(item.launch_token or "")
                continue
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

    def wait_task(self, task_id: str, timeout_seconds: float = 30) -> TaskRecord:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("wait timeout must be finite and positive")
        deadline = time.monotonic() + timeout_seconds
        while True:
            task = self.store.get_task(task_id)
            if task.status not in {TaskStatus.STARTING, TaskStatus.RUNNING}:
                return task
            if time.monotonic() >= deadline:
                raise TimeoutError(f"task {task_id} is still {task.status.value}; worker continues")
            if task.session_kind == "process" and task.session_id:
                sessions = self._sessions_for(task)
                if not sessions.exists(task.session_id):
                    self.sync_runtime()
            time.sleep(0.1)

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
