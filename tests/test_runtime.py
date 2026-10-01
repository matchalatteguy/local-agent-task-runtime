from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest

from local_agent_runtime import (
    AgentTaskRuntime,
    DirectoryWorkspaceManager,
    FakeSessionManager,
    SqliteRuntimeStore,
)
from local_agent_runtime.dispatch import Dispatcher
from local_agent_runtime.models import TaskStatus, utc_now
from local_agent_runtime.store import TaskStateConflict


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
        "start_claimed",
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


def test_sync_does_not_overwrite_completion_during_reconciliation(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    runtime.register_task("fast", "docs", "python task.py", "fast")
    started = runtime.start_task("fast")
    runtime.sessions.live.remove(started.session_id)
    compute = runtime.compute_stale_tasks

    def complete_during_sync(stale_after):
        findings = compute(stale_after)
        runtime.mark_done("fast", "completed while supervisor was inspecting")
        return findings

    monkeypatch.setattr(runtime, "compute_stale_tasks", complete_during_sync)
    assert runtime.sync_runtime()["stopped"] == []
    assert runtime.store.get_task("fast").status == TaskStatus.DONE


def test_stale_heartbeat_reason_is_stable(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.register_task("slow", "docs", "python slow.py", "slow")
    runtime.start_task("slow")
    old = utc_now() - timedelta(hours=2)
    runtime.store.update_task("slow", heartbeat_at=old)
    stale = runtime.compute_stale_tasks(timedelta(minutes=30))
    assert [(item.task_id, item.reason) for item in stale] == [("slow", "heartbeat_stale")]


def test_summary_recent_events_are_limited_to_newest_first(tmp_path):
    runtime = make_runtime(tmp_path)
    for index in range(25):
        task_id = f"task-{index:02d}"
        runtime.register_task(task_id, "docs", "python task.py", task_id)

    recent_events = runtime.summary()["recent_events"]

    assert [event["task_id"] for event in recent_events[:3]] == [
        "task-24",
        "task-23",
        "task-22",
    ]
    assert len(recent_events) == 20
    assert recent_events[-1]["task_id"] == "task-05"


def test_parallel_starts_claim_one_task_and_one_capacity_slot(tmp_path):
    entered = Event()
    release = Event()

    class SlowSessions(FakeSessionManager):
        def start(self, task_id, spec):
            entered.set()
            assert release.wait(timeout=5)
            return super().start(task_id, spec)

    first = make_runtime(tmp_path)
    first.sessions = SlowSessions()
    first.register_task("a", "docs", "python a.py", "a")
    first.register_task("b", "docs", "python b.py", "b")
    second = make_runtime(tmp_path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first.start_task, "a", max_concurrent=1)
        try:
            assert entered.wait(timeout=5)
            assert second.store.get_task("a").status == TaskStatus.STARTING
            with pytest.raises(TaskStateConflict, match="starting"):
                second.start_task("a")
            assert Dispatcher(second).dispatch_ready(1).started == []
            assert second.store.get_task("b").status == TaskStatus.READY
        finally:
            release.set()
        assert future.result(timeout=5).status == TaskStatus.RUNNING
    assert len(first.sessions.live) == 1


def test_fast_worker_completion_is_not_overwritten_by_start(tmp_path):
    runtime = make_runtime(tmp_path)

    class CompletingSessions(FakeSessionManager):
        def start(self, task_id, spec):
            runtime.mark_done(task_id, "finished during launch")
            return super().start(task_id, spec)

    runtime.sessions = CompletingSessions()
    runtime.register_task("fast", "docs", "python task.py", "fast")
    result = runtime.start_task("fast")
    assert result.status == TaskStatus.DONE
    assert result.notes == "finished during launch"
    assert not runtime.sessions.live


def test_old_launch_cannot_stop_replacement_running_session(tmp_path):
    runtime = make_runtime(tmp_path)

    class RestartingSessions(FakeSessionManager):
        calls = 0

        def start(self, task_id, spec):
            self.calls += 1
            if self.calls == 1:
                runtime.stop_task(task_id, TaskStatus.STOPPED)
                runtime.start_task(task_id)
            return super().start(task_id, spec)

    runtime.sessions = RestartingSessions()
    runtime.register_task("restart", "docs", "python task.py", "restart")
    result = runtime.start_task("restart")
    assert result.status == TaskStatus.RUNNING
    assert runtime.sessions.exists(result.session_id)
    assert runtime.sessions.live == {result.session_id}
    assert runtime.store.get_task("restart").launch_token == result.launch_token


def test_old_launch_cannot_overwrite_or_stop_replacement_while_starting(tmp_path):
    runtime = make_runtime(tmp_path)
    entered = Event()
    release = Event()

    with ThreadPoolExecutor(max_workers=1) as pool:

        class RestartingSessions(FakeSessionManager):
            calls = 0
            replacement_session = None
            replacement_future = None

            def start(self, task_id, spec):
                self.calls += 1
                if self.calls == 1:
                    runtime.stop_task(task_id, TaskStatus.STOPPED)
                    self.replacement_future = pool.submit(runtime.start_task, task_id)
                    assert entered.wait(timeout=5)
                    return super().start(task_id, spec)
                self.replacement_session = super().start(task_id, spec)
                entered.set()
                assert release.wait(timeout=5)
                return self.replacement_session

        runtime.sessions = RestartingSessions()
        runtime.register_task("restart", "docs", "python task.py", "restart")
        try:
            result = runtime.start_task("restart")
            assert result.status == TaskStatus.STARTING
            assert runtime.sessions.exists(runtime.sessions.replacement_session)
            assert runtime.sessions.live == {runtime.sessions.replacement_session}
        finally:
            release.set()
        completed = runtime.sessions.replacement_future.result(timeout=5)
        assert completed.status == TaskStatus.RUNNING
        assert completed.launch_token == result.launch_token
        assert runtime.sessions.exists(completed.session_id)


def test_stale_generation_cannot_stop_a_restarted_task(tmp_path, monkeypatch):
    runtime = make_runtime(tmp_path)
    runtime.register_task("restart", "docs", "python task.py", "restart")
    old = runtime.start_task("restart")
    runtime.sessions.live.remove(old.session_id)
    compute = runtime.compute_stale_tasks

    def restart_during_sync(stale_after):
        findings = compute(stale_after)
        runtime.stop_task("restart", TaskStatus.STOPPED)
        runtime.start_task("restart")
        return findings

    monkeypatch.setattr(runtime, "compute_stale_tasks", restart_during_sync)
    assert runtime.sync_runtime()["stopped"] == []
    current = runtime.store.get_task("restart")
    assert current.status == TaskStatus.RUNNING
    assert current.launch_token != old.launch_token
    assert runtime.sessions.exists(current.session_id)


def test_completion_is_persisted_before_stopping_own_session(tmp_path):
    runtime = make_runtime(tmp_path)

    class CheckingSessions(FakeSessionManager):
        def stop(self, session_id):
            assert runtime.store.get_task("docs").status == TaskStatus.DONE
            super().stop(session_id)

    runtime.sessions = CheckingSessions()
    runtime.register_task("docs", "docs", "python task.py", "docs")
    runtime.start_task("docs")
    runtime.mark_done("docs")


def test_interrupted_launch_reserves_slot_until_stale_and_is_recoverable(tmp_path):
    runtime = make_runtime(tmp_path)
    runtime.register_task("lost", "docs", "python task.py", "lost")
    runtime.store.claim_for_start("lost")
    assert runtime.sync_runtime()["stopped"] == []
    old = utc_now() - timedelta(hours=2)
    with runtime.store.connect() as conn:
        conn.execute("UPDATE tasks SET updated_at=? WHERE id='lost'", (old.isoformat(),))
    assert runtime.sync_runtime()["stopped"] == ["lost"]
    assert runtime.start_task("lost").status == TaskStatus.RUNNING
