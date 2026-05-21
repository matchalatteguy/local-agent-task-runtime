from __future__ import annotations

from datetime import timedelta

from local_agent_runtime import (
    AgentTaskRuntime,
    DirectoryWorkspaceManager,
    FakeSessionManager,
    SqliteRuntimeStore,
)
from local_agent_runtime.models import TaskStatus, utc_now


def make_runtime(tmp_path):
    return AgentTaskRuntime(
        SqliteRuntimeStore(tmp_path / "runtime.sqlite3"),
        FakeSessionManager(),
        DirectoryWorkspaceManager(tmp_path / "workspaces"),
    )


def test_start_heartbeat_done_records_lifecycle(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.register_task("docs", "docs", "python write_docs.py", "docs")
    started = runtime.start_task("docs")
    assert started.status == TaskStatus.RUNNING
    assert (tmp_path / "workspaces" / "docs").is_dir()
    assert started.session_id in runtime.sessions.live
    heartbeat = runtime.heartbeat("docs")
    assert heartbeat.heartbeat_at is not None
    done = runtime.mark_done("docs", "finished")
    assert done.status == TaskStatus.DONE
    assert done.notes == "finished"
    assert [event.kind for event in runtime.store.read_events("docs")] == [
        "registered",
        "started",
        "heartbeat",
        "done",
    ]


def test_sync_stops_missing_sessions(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.register_task("cleanup", "maint", "python cleanup.py", "cleanup")
    started = runtime.start_task("cleanup")
    runtime.sessions.live.remove(started.session_id)
    result = runtime.sync_runtime()
    assert result["stopped"] == ["cleanup"]
    assert runtime.store.get_task("cleanup").status == TaskStatus.STOPPED


def test_stale_heartbeat_reason_is_stable(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.register_task("slow", "docs", "python slow.py", "slow")
    runtime.start_task("slow")
    old = utc_now() - timedelta(hours=2)
    runtime.store.update_task("slow", heartbeat_at=old)
    stale = runtime.compute_stale_tasks(timedelta(minutes=30))
    assert [(item.task_id, item.reason) for item in stale] == [("slow", "heartbeat_stale")]
