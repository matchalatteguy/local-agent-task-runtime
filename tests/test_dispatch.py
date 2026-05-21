from __future__ import annotations

from local_agent_runtime import (
    AgentTaskRuntime,
    DirectoryWorkspaceManager,
    FakeSessionManager,
    SqliteRuntimeStore,
)
from local_agent_runtime.dispatch import Dispatcher
from local_agent_runtime.models import TaskStatus


def test_dispatch_respects_capacity_and_order(tmp_path):
    runtime = AgentTaskRuntime(
        SqliteRuntimeStore(tmp_path / "runtime.sqlite3"),
        FakeSessionManager(),
        DirectoryWorkspaceManager(tmp_path / "workspaces"),
    )
    for name in ["a", "b", "c"]:
        runtime.register_task(name, "docs", f"python {name}.py", name)
    result = Dispatcher(runtime).dispatch_ready(max_concurrent=2)
    assert result.started == ["a", "b"]
    assert result.capacity_remaining == 0
    assert runtime.store.get_task("c").status == TaskStatus.READY


def test_blocked_and_done_tasks_are_not_dispatched(tmp_path):
    runtime = AgentTaskRuntime(
        SqliteRuntimeStore(tmp_path / "runtime.sqlite3"),
        FakeSessionManager(),
        DirectoryWorkspaceManager(tmp_path / "workspaces"),
    )
    runtime.register_task("blocked", "docs", "python blocked.py", "blocked")
    runtime.register_task("done", "docs", "python done.py", "done")
    runtime.store.update_task("blocked", status=TaskStatus.BLOCKED)
    runtime.store.update_task("done", status=TaskStatus.DONE)
    result = Dispatcher(runtime).dispatch_ready(max_concurrent=2)
    assert result.started == []
