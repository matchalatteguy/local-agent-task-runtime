from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .models import DispatchResult, TaskStatus
from .runtime import AgentTaskRuntime


@dataclass
class Dispatcher:
    runtime: AgentTaskRuntime

    def dispatch_ready(self, max_concurrent: int) -> DispatchResult:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        active_count = len(self.runtime.store.list_tasks(TaskStatus.RUNNING))
        capacity = max_concurrent - active_count
        started: list[str] = []
        skipped: dict[str, str] = {}
        if capacity <= 0:
            for task in self.runtime.store.ready_tasks():
                skipped[task.id] = "capacity_reached"
            return DispatchResult(started, skipped, active_count, 0)
        for task in self.runtime.store.ready_tasks():
            if len(started) >= capacity:
                break
            try:
                self.runtime.start_task(task.id)
                started.append(task.id)
            except Exception as exc:  # surface per-task failure without hiding other dispatches
                skipped[task.id] = f"start_failed: {exc}"
        remaining = max(0, max_concurrent - active_count - len(started))
        return DispatchResult(started, skipped, active_count + len(started), remaining)

    def tick(
        self, max_concurrent: int, stale_after: timedelta = timedelta(minutes=30)
    ) -> dict[str, object]:
        sync = self.runtime.sync_runtime(stale_after=stale_after)
        dispatch = self.dispatch_ready(max_concurrent)
        return {
            "sync": sync,
            "dispatch": dispatch.to_dict(),
            "summary": self.runtime.summary(stale_after=stale_after),
        }
