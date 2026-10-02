from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from local_agent_runtime import RuntimeConfig, TaskStatus, WorkerSpec
from local_agent_runtime.cli import main
from local_agent_runtime.process import (
    ProcessSessionManager,
    ProcessStore,
    require_process_support,
)
from local_agent_runtime.store import TaskStateConflict

SUPPORTED = os.name == "posix" and hasattr(os, "waitid") and hasattr(os, "WNOWAIT")
process_required = pytest.mark.skipif(not SUPPORTED, reason="requires POSIX waitid/WNOWAIT")


def runtime_at(tmp_path, timeout=10, cap=8388608):
    return RuntimeConfig(
        db_path=tmp_path / "runtime.sqlite3",
        workspace_root=tmp_path,
        session="process",
        process_timeout_seconds=timeout,
        process_log_limit_bytes=cap,
    ).create_runtime()


def register_script(runtime, code, task_id="worker"):
    runtime.register_task(task_id, "test", shlex.join([sys.executable, "-c", code]), task_id)


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_timeout_requires_finite_positive_value(tmp_path, timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        ProcessSessionManager(tmp_path / "runtime.db", timeout)
    with pytest.raises(ValueError, match="finite and positive"):
        RuntimeConfig.from_env(process_timeout_seconds=timeout)
    with pytest.raises(ValueError, match="finite and positive"):
        runtime_at(tmp_path).wait_task("unknown", timeout)


@pytest.mark.parametrize("cap", [0, -1, 1.5, True])
def test_log_limit_requires_positive_integer(tmp_path, cap):
    with pytest.raises(ValueError, match="positive integer"):
        ProcessSessionManager(tmp_path / "runtime.db", log_limit_bytes=cap)
    with pytest.raises(ValueError, match="positive integer"):
        RuntimeConfig(process_log_limit_bytes=cap)


def test_unsupported_platform_has_actionable_diagnostic(monkeypatch):
    monkeypatch.delattr(os, "waitid", raising=False)
    with pytest.raises(RuntimeError, match="tmux/fake"):
        require_process_support()


@process_required
@pytest.mark.parametrize("exit_code", [0, 7])
def test_exit_code_and_binary_logs_survive_reopening(tmp_path, exit_code):
    runtime = runtime_at(tmp_path)
    register_script(
        runtime,
        f"import sys; sys.stdout.buffer.write(b'hello\\n\\xff'); "
        f"sys.stderr.write('details\\n'); sys.exit({exit_code})",
    )
    runtime.start_task("worker")
    # A fresh CLI/library instance routes by the persisted adapter, not its default.
    reopened = RuntimeConfig(db_path=runtime.store.path).create_runtime()
    result = reopened.wait_task("worker", 5)
    assert result.status == (TaskStatus.DONE if exit_code == 0 else TaskStatus.FAILED)
    run = ProcessStore(reopened.store).runs("worker")[-1]
    assert run["exit_code"] == exit_code
    assert run["reason"] == "exited"
    assert run["worker_pid"] is not None
    assert Path(run["logs"]["stdout"]).read_bytes() == b"hello\n\xff"
    assert Path(run["logs"]["stderr"]).read_text() == "details\n"
    assert Path(run["logs"]["runner"]).read_text() == ""
    assert result.completed_at is not None


@process_required
def test_noisy_worker_logs_are_capped_and_drained(tmp_path):
    runtime = runtime_at(tmp_path, cap=128)
    register_script(
        runtime,
        "import sys; sys.stdout.buffer.write(b'a'*200000); sys.stderr.buffer.write(b'b'*300000)",
    )
    runtime.start_task("worker")
    assert runtime.wait_task("worker", 5).status == TaskStatus.DONE
    run = ProcessStore(runtime.store).runs("worker")[-1]
    assert Path(run["logs"]["stdout"]).read_bytes() == b"a" * 128
    assert Path(run["logs"]["stderr"]).read_bytes() == b"b" * 128
    assert run["stdout_bytes"] == run["stderr_bytes"] == 128
    assert run["stdout_discarded"] == 200000 - 128
    assert run["stderr_discarded"] == 300000 - 128


@process_required
def test_spawn_failure_is_recorded_and_retry_keeps_attempt_history(tmp_path):
    runtime = runtime_at(tmp_path)
    runtime.register_task("missing", "test", "/definitely/absent/runtime-command", "missing")
    runtime.start_task("missing")
    assert runtime.wait_task("missing", 5).status == TaskStatus.FAILED
    first = ProcessStore(runtime.store).runs("missing")[-1]
    assert first["reason"] == "spawn_error" and first["exit_code"] is None
    assert "spawn_error" in Path(first["logs"]["runner"]).read_text()
    runtime.store.retry_task("missing")
    runtime.start_task("missing")
    runtime.wait_task("missing", 5)
    runs = ProcessStore(runtime.store).runs("missing")
    assert len(runs) == 2 and runs[0]["launch_token"] != runs[1]["launch_token"]


@process_required
def test_cli_launcher_exits_before_worker_and_wait_timeout_does_not_cancel(tmp_path, capsys):
    runtime = runtime_at(tmp_path)
    register_script(runtime, "import time; time.sleep(.7); print('after launcher exit')")
    launched = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_agent_runtime.cli",
            "--db",
            str(runtime.store.path),
            "--workspace-root",
            str(tmp_path),
            "start",
            "worker",
            "--session",
            "process",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(launched.stdout)["session_kind"] == "process"
    assert main(["--db", str(runtime.store.path), "wait", "worker", "--timeout", ".01"]) == 124
    assert "worker continues" in capsys.readouterr().err
    assert runtime.wait_task("worker", 5).status == TaskStatus.DONE
    assert main(["--db", str(runtime.store.path), "logs", "worker", "--json"]) == 0
    assert "after launcher exit" in json.loads(capsys.readouterr().out)["content"]
    assert main(["--db", str(runtime.store.path), "done", "worker"]) == 2
    assert "complete from their exit code" in capsys.readouterr().err


@process_required
@pytest.mark.parametrize("operation", ["cancel", "timeout", "leader_exit"])
def test_owned_group_cleanup_includes_grandchild(tmp_path, operation):
    runtime = runtime_at(tmp_path, timeout=0.7 if operation == "timeout" else 10)
    child = (
        "import time, signal; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "Path('child-ready').touch(); time.sleep(1.8); Path('child-survived').touch()"
    )
    parent = (
        "import subprocess,sys,time,signal; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
    )
    if operation == "leader_exit":
        parent += "\nwhile not Path('child-ready').exists(): time.sleep(.01)\n"
    else:
        parent += "time.sleep(3)"
    register_script(runtime, parent)
    runtime.start_task("worker")
    workspace = tmp_path / "worker"
    eventually(lambda: (workspace / "child-ready").exists())
    if operation == "cancel":
        requested = runtime.stop_task("worker", "stopped", "cancelled by test")
        assert requested.status in {TaskStatus.RUNNING, TaskStatus.STOPPED}
    result = runtime.wait_task("worker", 5)
    expected = {
        "cancel": TaskStatus.STOPPED,
        "timeout": TaskStatus.FAILED,
        "leader_exit": TaskStatus.DONE,
    }[operation]
    assert result.status == expected
    time.sleep(1.9)
    assert not (workspace / "child-survived").exists()
    run = ProcessStore(runtime.store).runs("worker")[-1]
    assert (
        run["reason"]
        == {"cancel": "cancelled", "timeout": "timed_out", "leader_exit": "exited"}[operation]
    )
    if operation == "cancel":
        assert result.notes == "cancelled by test"


def prepare_manual(runtime, code):
    register_script(runtime, code)
    task = runtime.store.claim_for_start("worker")
    workspace = runtime.workspaces.prepare(task)
    runs = ProcessStore(runtime.store)
    token = runs.prepare(
        "worker",
        WorkerSpec(command=task.command, cwd=str(workspace), launch_token=task.launch_token),
        5,
    )
    return runs, token


def launch_owned_runner(runtime, token):
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "local_agent_runtime.runner",
            "--db",
            str(runtime.store.path),
            "--token",
            token,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@process_required
def test_competing_supervisors_run_an_attempt_only_once(tmp_path):
    runtime = runtime_at(tmp_path)
    runs, token = prepare_manual(
        runtime,
        "import time; from pathlib import Path; "
        "Path('started').open('a').write('once\\n'); time.sleep(.2)",
    )
    first, second = launch_owned_runner(runtime, token), launch_owned_runner(runtime, token)
    try:
        assert sorted([first.wait(timeout=5), second.wait(timeout=5)]) == [0, 3]
    finally:
        for runner in (first, second):
            if runner.poll() is None:
                runner.terminate()
                runner.wait(timeout=5)
    assert runtime.store.get_task("worker").status == TaskStatus.DONE
    assert (tmp_path / "worker/started").read_text() == "once\n"
    assert runs.get(token)["state"] == "finished"


@process_required
def test_killed_supervisor_blocks_relaunch_until_explicit_orphan_acknowledgment(tmp_path):
    runtime = runtime_at(tmp_path)
    runs, token = prepare_manual(
        runtime,
        "import time; from pathlib import Path; "
        "Path('ready').touch(); time.sleep(.8); Path('orphan-finished').touch()",
    )
    runner = launch_owned_runner(runtime, token)
    try:
        eventually(lambda: (tmp_path / "worker/ready").exists())
        with pytest.raises(ValueError, match="still owns"):
            ProcessSessionManager(runtime.store.path).recover(token)
        runner.kill()  # This test owns the unreaped supervisor Popen; never a stored PID.
        runner.wait(timeout=5)
    finally:
        if runner.poll() is None:
            runner.terminate()
            runner.wait(timeout=5)
    assert runtime.wait_task("worker", 5).status == TaskStatus.BLOCKED
    with pytest.raises(TaskStateConflict, match="unresolved"):
        runtime.start_task("worker")
    with pytest.raises(TaskStateConflict, match="unresolved"):
        runtime.store.retry_task("worker")
    with pytest.raises(ValueError, match="inspection notes"):
        ProcessSessionManager(runtime.store.path).recover(token, acknowledge=True)
    eventually(lambda: (tmp_path / "worker/orphan-finished").exists())
    ProcessSessionManager(runtime.store.path).recover(
        token, acknowledge=True, notes="bounded orphan exited; outputs inspected"
    )
    assert runs.get(token)["state"] == "acknowledged"
    assert runtime.store.retry_task("worker").status == TaskStatus.READY
    runtime.start_task("worker")
    assert runtime.wait_task("worker", 5).status == TaskStatus.DONE


def test_stale_process_spec_cannot_claim_a_new_generation(tmp_path):
    runtime = runtime_at(tmp_path)
    register_script(runtime, "print('hello')")
    first = runtime.store.claim_for_start("worker")
    runtime.store.update_task("worker", status=TaskStatus.STOPPED)
    second = runtime.store.claim_for_start("worker")
    with pytest.raises(TaskStateConflict, match="another launch"):
        ProcessStore(runtime.store).prepare(
            "worker", WorkerSpec(command=first.command, launch_token=first.launch_token), 5
        )
    assert runtime.store.get_task("worker").launch_token == second.launch_token
    assert ProcessStore(runtime.store).runs("worker") == []


def test_cancellation_before_preparation_prevents_worker_launch(tmp_path):
    runtime = runtime_at(tmp_path)
    register_script(runtime, "print('must not run')")
    claimed = runtime.store.claim_for_start("worker")
    runtime.store.update_task("worker", session_kind="process")
    runtime.stop_task("worker", "stopped", "cancelled during setup")
    with pytest.raises(TaskStateConflict, match="owned starting"):
        ProcessStore(runtime.store).prepare(
            "worker", WorkerSpec(command=claimed.command, launch_token=claimed.launch_token), 5
        )
    assert runtime.store.get_task("worker").status == TaskStatus.STOPPED
    assert ProcessStore(runtime.store).runs("worker") == []


@process_required
def test_cancellation_of_prepared_attempt_is_observed_before_execution(tmp_path):
    runtime = runtime_at(tmp_path)
    runs, token = prepare_manual(
        runtime, "from pathlib import Path; Path('must-not-exist').touch()"
    )
    runtime.stop_task("worker", "stopped", "cancelled before runner")
    runner = launch_owned_runner(runtime, token)
    assert runner.wait(timeout=5) == 0
    assert runtime.store.get_task("worker").status == TaskStatus.STOPPED
    assert runs.get(token)["reason"] == "cancelled"
    assert not (tmp_path / "worker/must-not-exist").exists()


@process_required
def test_interrupted_prepared_launch_is_blocked_by_sync(tmp_path):
    from datetime import timedelta

    from local_agent_runtime.models import utc_now

    runtime = runtime_at(tmp_path)
    runs, token = prepare_manual(runtime, "print('never launched')")
    with runtime.store.connect() as conn:
        conn.execute(
            "UPDATE tasks SET updated_at=? WHERE id='worker'",
            ((utc_now() - timedelta(minutes=31)).isoformat(),),
        )
    summary = runtime.sync_runtime()
    assert summary["stale"][0]["reason"] == "process_runner_missing"
    assert runtime.store.get_task("worker").status == TaskStatus.BLOCKED
    assert runs.get(token)["state"] == "lost"
    runner = launch_owned_runner(runtime, token)
    assert runner.wait(timeout=5) == 3  # a late launcher cannot take recovered ownership


@process_required
def test_supervisor_term_cleans_up_its_group(tmp_path):
    runtime = runtime_at(tmp_path)
    runs, token = prepare_manual(
        runtime,
        "import time; from pathlib import Path; "
        "Path('ready').touch(); time.sleep(1.5); Path('survived').touch()",
    )
    runner = launch_owned_runner(runtime, token)
    try:
        eventually(lambda: (tmp_path / "worker/ready").exists())
        runner.terminate()
        assert runner.wait(timeout=5) == 0
    finally:
        if runner.poll() is None:
            runner.terminate()
            runner.wait(timeout=5)
    assert runtime.store.get_task("worker").status == TaskStatus.FAILED
    assert runs.get(token)["reason"] == "supervisor_signal"
    time.sleep(1.6)
    assert not (tmp_path / "worker/survived").exists()


def test_darwin_permission_denial_is_only_ignored_for_zombie_only_group(monkeypatch):
    from local_agent_runtime import process

    monkeypatch.setattr(sys, "platform", "darwin")

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "killpg", denied)
    for states in ("", "Z\nZ+\n"):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, states=states, **k: subprocess.CompletedProcess(a, 0, states, ""),
        )
        process._signal_owned_group(123, 15)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "Z\nS\n", "")
    )
    with pytest.raises(PermissionError):
        process._signal_owned_group(123, 15)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 2, "", "failed")
    )
    with pytest.raises(PermissionError):
        process._signal_owned_group(123, 15)


@process_required
def test_launcher_ignoring_sigchld_does_not_auto_reap_runner_worker(tmp_path):
    runtime = runtime_at(tmp_path)
    register_script(runtime, "import time; time.sleep(.2); print('safe child ownership')")
    launcher = (
        "import signal; from pathlib import Path; from local_agent_runtime import RuntimeConfig; "
        "signal.signal(signal.SIGCHLD, signal.SIG_IGN); "
        f"RuntimeConfig(db_path=Path({str(runtime.store.path)!r}), "
        f"workspace_root=Path({str(tmp_path)!r}), session='process')"
        ".create_runtime().start_task('worker')"
    )
    subprocess.run([sys.executable, "-c", launcher], check=True, timeout=10)
    assert runtime.wait_task("worker", 5).status == TaskStatus.DONE
    assert ProcessStore(runtime.store).runs("worker")[-1]["exit_code"] == 0
