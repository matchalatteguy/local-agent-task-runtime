"""Durable POSIX supervision. Only the owning runner ever signals a worker group."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import selectors
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import TaskStatus, WorkerSpec, utc_now
from .store import SqliteRuntimeStore, TaskStateConflict

ACTIVE_RUN_STATES = {"prepared", "running"}
POLL_SECONDS = 0.1
TERM_GRACE_SECONDS = 0.5
DEFAULT_LOG_LIMIT = 8 * 1024 * 1024


def require_process_support() -> None:
    if os.name != "posix" or not all(
        hasattr(os, name) for name in ("waitid", "WNOWAIT", "WEXITED", "WNOHANG", "P_PID", "killpg")
    ):
        raise RuntimeError(
            "process sessions require POSIX and os.waitid/WNOWAIT; "
            "use a supported Python build (tested on Linux and macOS Python 3.14), "
            "or select --session tmux/fake"
        )


class LogCapture:
    """Drain both pipes without allowing a noisy worker to fill the filesystem."""

    def __init__(self, child: subprocess.Popen[bytes], directory: Path, limit: int):
        self.selector = selectors.DefaultSelector()
        self.limit = limit
        self.retained = {"stdout": 0, "stderr": 0}
        self.discarded = {"stdout": 0, "stderr": 0}
        self.files = {}
        try:
            for name in ("stdout", "stderr"):
                pipe = getattr(child, name)
                assert pipe is not None
                os.set_blocking(pipe.fileno(), False)
                self.selector.register(pipe, selectors.EVENT_READ, name)
                self.files[name] = (directory / f"{name}.log").open("wb", buffering=0)
        except BaseException:
            self.close()
            raise

    def drain(self, timeout: float) -> None:
        for key, _ in self.selector.select(timeout):
            name = key.data
            # Bound work per iteration so cancellation and heartbeat processing
            # still run when a worker writes continuously.
            for _ in range(16):
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    break
                if not chunk:
                    self.selector.unregister(key.fileobj)
                    key.fileobj.close()
                    break
                keep = chunk[: max(0, self.limit - self.retained[name])]
                if keep:
                    self.files[name].write(keep)
                self.retained[name] += len(keep)
                self.discarded[name] += len(chunk) - len(keep)

    def finish(self) -> None:
        deadline = time.monotonic() + TERM_GRACE_SECONDS
        while self.selector.get_map() and time.monotonic() < deadline:
            self.drain(0.01)

    def close(self) -> None:
        for key in list(self.selector.get_map().values()):
            key.fileobj.close()
        self.selector.close()
        for log in self.files.values():
            log.close()


class ProcessStore:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self.store = store

    def directory(self, token: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("invalid launch token")
        db = self.store.path.resolve()
        return db.parent / f"{db.name}.runs" / token

    def runs(self, task_id: str) -> list[dict[str, Any]]:
        self.store.get_task(task_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM process_runs WHERE task_id=? ORDER BY rowid",
                (task_id,),
            ).fetchall()
        return [self._dict(row) for row in rows]

    def get(self, token: str) -> dict[str, Any]:
        self.directory(token)
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM process_runs WHERE launch_token=?", (token,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no process attempt: {token}")
        return self._dict(row)

    def by_session(self, session_id: str) -> dict[str, Any] | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM process_runs WHERE session_id=?", (session_id,)
            ).fetchone()
        return self._dict(row) if row else None

    def _dict(self, row: Any) -> dict[str, Any]:
        result = dict(row)
        result["argv"] = json.loads(result.pop("argv_json"))
        directory = self.directory(result["launch_token"])
        result["logs"] = {
            stream: str(directory / f"{stream}.log") for stream in ("stdout", "stderr", "runner")
        }
        return result

    def prepare(
        self,
        task_id: str,
        spec: WorkerSpec,
        timeout_seconds: float,
        log_limit_bytes: int = DEFAULT_LOG_LIMIT,
    ) -> str:
        argv = shlex.split(spec.command)
        if not argv or not argv[0]:
            raise ValueError("process command must contain an executable")
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None or task["status"] != TaskStatus.STARTING or not task["launch_token"]:
                raise TaskStateConflict("process launch requires an owned starting task")
            if task["launch_token"] != spec.launch_token:
                raise TaskStateConflict("process specification belongs to another launch attempt")
            token = task["launch_token"]
            session_id = spec.session_name or f"agent-runtime-{task_id}-{token}"
            self.directory(token).mkdir(parents=True, exist_ok=False)
            conn.execute(
                "INSERT INTO process_runs (launch_token,task_id,session_id,argv_json,workspace,"
                "timeout_seconds,state,created_at,log_limit_bytes) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    token,
                    task_id,
                    session_id,
                    json.dumps(argv),
                    str(Path(spec.cwd or ".").resolve()),
                    timeout_seconds,
                    "prepared",
                    utc_now().isoformat(),
                    log_limit_bytes,
                ),
            )
            conn.execute("UPDATE tasks SET session_kind='process' WHERE id=?", (task_id,))
        return token

    def own(self, token: str) -> bool:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT * FROM process_runs WHERE launch_token=?", (token,)
            ).fetchone()
            if run is None or run["state"] != "prepared":
                return False
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (run["task_id"],)).fetchone()
            if task["launch_token"] != token or task["status"] != TaskStatus.STARTING:
                conn.execute(
                    "UPDATE process_runs SET state='finished',reason='superseded',finished_at=? "
                    "WHERE launch_token=?",
                    (utc_now().isoformat(), token),
                )
                return False
            now = utc_now().isoformat()
            conn.execute(
                "UPDATE process_runs SET state='running',supervisor_pid=?,started_at=?,"
                "heartbeat_at=? "
                "WHERE launch_token=?",
                (os.getpid(), now, now, token),
            )
            conn.execute(
                "UPDATE tasks SET status='running',session_id=?,session_kind='process',"
                "started_at=?,heartbeat_at=?,updated_at=? WHERE id=?",
                (run["session_id"], now, now, now, run["task_id"]),
            )
            self.store._append_event(
                conn,
                run["task_id"],
                "started",
                {
                    "session_id": run["session_id"],
                    "launch_token": token,
                    "adapter": "process",
                    "workspace": run["workspace"],
                },
            )
        return True

    def heartbeat(self, token: str, worker_pid: int, logs: LogCapture | None = None) -> None:
        now = utc_now().isoformat()
        with self.store.connect() as conn:
            conn.execute(
                "UPDATE process_runs SET heartbeat_at=?,worker_pid=? WHERE launch_token=?",
                (now, worker_pid, token),
            )
            conn.execute(
                "UPDATE tasks SET heartbeat_at=?,updated_at=? "
                "WHERE launch_token=? AND status='running'",
                (now, now, token),
            )
            if logs is not None:
                conn.execute(
                    "UPDATE process_runs SET stdout_bytes=?,stderr_bytes=?,stdout_discarded=?,"
                    "stderr_discarded=? WHERE launch_token=?",
                    (*logs.retained.values(), *logs.discarded.values(), token),
                )
            if logs is not None:
                conn.execute(
                    "UPDATE process_runs SET stdout_bytes=?,stderr_bytes=?,stdout_discarded=?,"
                    "stderr_discarded=? WHERE launch_token=?",
                    (
                        logs.retained["stdout"],
                        logs.retained["stderr"],
                        logs.discarded["stdout"],
                        logs.discarded["stderr"],
                        token,
                    ),
                )

    def finish(self, token: str, exit_code: int | None, reason: str) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT * FROM process_runs WHERE launch_token=?", (token,)
            ).fetchone()
            if run is None or run["state"] not in ACTIVE_RUN_STATES:
                return
            if run["cancel_status"] and reason == "exited":
                reason = "cancelled"
            now = utc_now().isoformat()
            conn.execute(
                "UPDATE process_runs SET state='finished',finished_at=?,exit_code=?,reason=? "
                "WHERE launch_token=?",
                (now, exit_code, reason, token),
            )
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (run["task_id"],)).fetchone()
            if task["launch_token"] != token or task["status"] not in {"starting", "running"}:
                return
            status = (
                run["cancel_status"]
                if reason == "cancelled"
                else ("done" if reason == "exited" and exit_code == 0 else "failed")
            )
            notes = (
                run["cancel_notes"] if reason == "cancelled" else f"{reason}; exit code {exit_code}"
            )
            conn.execute(
                "UPDATE tasks SET status=?,notes=?,session_id=NULL,completed_at=?,updated_at=? "
                "WHERE id=?",
                (status, notes, now, now, run["task_id"]),
            )
            self.store._append_event(
                conn,
                run["task_id"],
                "process_finished",
                {
                    "launch_token": token,
                    "exit_code": exit_code,
                    "reason": reason,
                    "status": status,
                },
            )

    def cancel(self, token: str, status: TaskStatus, notes: str | None = None) -> None:
        if status not in {TaskStatus.STOPPED, TaskStatus.BLOCKED, TaskStatus.FAILED}:
            raise ValueError("cancel status must be stopped, blocked, or failed")
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT * FROM process_runs WHERE launch_token=?", (token,)
            ).fetchone()
            if run and run["state"] in ACTIVE_RUN_STATES and run["cancel_status"] is None:
                conn.execute(
                    "UPDATE process_runs SET cancel_status=?,cancel_notes=? WHERE launch_token=?",
                    (status.value, notes, token),
                )
                self.store._append_event(
                    conn,
                    run["task_id"],
                    "cancel_requested",
                    {
                        "launch_token": token,
                        "requested_status": status.value,
                        "notes": notes,
                    },
                )

            elif run is None:
                # Serialized with prepare(): cancel a claim before a runner
                # exists, so late preparation cannot launch the command.
                task = conn.execute(
                    "SELECT id FROM tasks WHERE launch_token=? AND status='starting' "
                    "AND session_kind='process'",
                    (token,),
                ).fetchone()
                if task:
                    conn.execute(
                        "UPDATE tasks SET status=?,notes=?,updated_at=? WHERE id=?",
                        (status.value, notes, utc_now().isoformat(), task["id"]),
                    )
                    self.store._append_event(
                        conn,
                        task["id"],
                        "stopped",
                        {
                            "launch_token": token,
                            "requested_status": status.value,
                            "notes": notes,
                        },
                    )

    def lost(self, token: str, acknowledge: bool = False, notes: str | None = None) -> None:
        with self.store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            run = conn.execute(
                "SELECT * FROM process_runs WHERE launch_token=?", (token,)
            ).fetchone()
            if run is None:
                raise KeyError(token)
            if run["state"] not in ACTIVE_RUN_STATES | {"lost"}:
                raise ValueError("attempt is already finished or acknowledged")
            if acknowledge and not notes:
                raise ValueError("acknowledging lost work requires inspection notes")
            state = "acknowledged" if acknowledge else "lost"
            status = "stopped" if acknowledge else "blocked"
            now = utc_now().isoformat()
            conn.execute(
                "UPDATE process_runs SET state=?,reason='runner_lost',finished_at=? "
                "WHERE launch_token=?",
                (state, now, token),
            )
            conn.execute(
                "UPDATE tasks SET status=?,session_id=NULL,notes=?,updated_at=? "
                "WHERE id=? AND launch_token=? AND status IN ('starting','running','blocked')",
                (
                    status,
                    notes or "Supervisor lost; inspect possible orphan work before recovery.",
                    now,
                    run["task_id"],
                    token,
                ),
            )
            if run["state"] != state:
                self.store._append_event(
                    conn,
                    run["task_id"],
                    "lost_acknowledged" if acknowledge else "runner_lost",
                    {"launch_token": token, "notes": notes},
                )


@contextmanager
def attempt_lock(directory: Path) -> Iterator[bool]:
    import fcntl

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "owner.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@dataclass
class ProcessSessionManager:
    db_path: Path
    timeout_seconds: float = 3600
    log_limit_bytes: int = DEFAULT_LOG_LIMIT
    kind: str = "process"
    prefix: str = "agent-runtime"

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path).resolve()
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("process timeout must be finite and positive")
        if (
            isinstance(self.log_limit_bytes, bool)
            or not isinstance(self.log_limit_bytes, int)
            or self.log_limit_bytes < 1
        ):
            raise ValueError("log byte limit must be a positive integer")

    def store(self) -> ProcessStore:
        return ProcessStore(SqliteRuntimeStore(self.db_path))

    def start(self, task_id: str, spec: WorkerSpec) -> str:
        require_process_support()
        runs = self.store()
        token = runs.prepare(task_id, spec, self.timeout_seconds, self.log_limit_bytes)
        with (runs.directory(token) / "runner.log").open("ab") as log:
            try:
                supervisor = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "local_agent_runtime.runner",
                        "--db",
                        str(self.db_path),
                        "--token",
                        token,
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    close_fds=True,
                    env=os.environ | spec.env,
                )
            except OSError:
                runs.finish(token, None, "supervisor_spawn_error")
                raise
        # Reap supervisors if an embedding process stays alive. This thread is
        # not part of task execution; a launcher exiting never stops the runner.
        threading.Thread(target=supervisor.wait, daemon=True).start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = runs.get(token)
            if run["state"] != "prepared":
                return run["session_id"]
            time.sleep(POLL_SECONDS)
        runs.cancel(token, TaskStatus.STOPPED, "supervisor startup did not acknowledge within 5s")
        raise RuntimeError("supervisor startup unconfirmed; inspect runs/runner log and recover")

    def stop(self, session_id: str) -> None:
        runs = self.store()
        run = runs.by_session(session_id)
        if run:
            runs.cancel(run["launch_token"], TaskStatus.STOPPED)

    def exists(self, session_id: str) -> bool:
        require_process_support()
        runs = self.store()
        run = runs.by_session(session_id)
        if not run or run["state"] not in ACTIVE_RUN_STATES:
            return False
        with attempt_lock(runs.directory(run["launch_token"])) as available:
            return not available

    def recover(self, token: str, acknowledge: bool = False, notes: str | None = None) -> None:
        require_process_support()
        runs = self.store()
        with attempt_lock(runs.directory(token)) as available:
            if not available:
                raise ValueError("supervisor still owns this attempt; request stop and wait")
            runs.lost(token, acknowledge, notes)

    def attach_command(self, session_id: str) -> str:
        run = self.store().by_session(session_id)
        if not run:
            raise KeyError(session_id)
        return f"tail -f {shlex.quote(run['logs']['stdout'])} {shlex.quote(run['logs']['stderr'])}"


def _exited_without_reaping(pid: int) -> bool:
    result = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    return result is not None and result.si_pid != 0


def _kill_owned_group(child: subprocess.Popen[bytes], graceful: bool) -> int:
    # Never call poll()/wait() before signalling: the unreaped leader reserves
    # its PID/group id. The caller owns this child, not a PID read from SQLite.
    if graceful:
        _signal_owned_group(child.pid, signal.SIGTERM)
        time.sleep(TERM_GRACE_SECONDS)
    _signal_owned_group(child.pid, signal.SIGKILL)
    return child.wait()


def _signal_owned_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin reports EPERM for an unreaped zombie-only group. Ignore only
        # that exact condition; a real denial with live members is a failure.
        if sys.platform != "darwin":
            raise
        result = subprocess.run(
            ["/bin/ps", "-o", "stat=", "-g", str(pgid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        states = result.stdout.split()
        if (
            result.returncode not in {0, 1}
            or result.stderr.strip()
            or any(not state.startswith("Z") for state in states)
        ):
            raise


def supervise(db_path: Path, token: str) -> int:
    require_process_support()
    # SIG_IGN can survive exec from an embedding launcher and cause automatic
    # child reaping. Restore default so the owned leader reserves its PID until
    # our explicit wait, which is essential for safe group cleanup.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    runs = ProcessStore(SqliteRuntimeStore(db_path))
    directory = runs.directory(token)
    with attempt_lock(directory) as owned:
        if not owned or not runs.own(token):
            return 3
        run = runs.get(token)
        interrupted = False

        def interrupt(signum: int, frame: Any) -> None:
            nonlocal interrupted
            interrupted = True

        signal.signal(signal.SIGTERM, interrupt)
        signal.signal(signal.SIGINT, interrupt)
        child: subprocess.Popen[bytes] | None = None
        logs: LogCapture | None = None
        worker_pid = None
        reason = "supervisor_error"
        exit_code = None
        try:
            if run["cancel_status"]:
                runs.finish(token, None, "cancelled")
                return 0
            child = subprocess.Popen(
                run["argv"],
                cwd=run["workspace"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
            )
            worker_pid = child.pid
            logs = LogCapture(child, directory, run["log_limit_bytes"])
            runs.heartbeat(token, child.pid, logs)
            deadline = time.monotonic() + run["timeout_seconds"]
            heartbeat = time.monotonic() + 1
            while True:
                current = runs.get(token)
                task = runs.store.get_task(run["task_id"])
                if current["cancel_status"]:
                    reason = "cancelled"
                    break
                if task.launch_token != token or task.status != TaskStatus.RUNNING:
                    reason = "superseded"
                    break
                if interrupted:
                    reason = "supervisor_signal"
                    break
                if time.monotonic() >= deadline:
                    reason = "timed_out"
                    break
                if _exited_without_reaping(child.pid):
                    reason = "exited"
                    break
                if time.monotonic() >= heartbeat:
                    runs.heartbeat(token, child.pid, logs)
                    heartbeat = time.monotonic() + 1
                logs.drain(POLL_SECONDS)
            exit_code = _kill_owned_group(child, graceful=reason != "exited")
            child = None
        except OSError as exc:
            reason = "spawn_error" if child is None else "supervisor_error"
            print(f"{reason}: {exc}", file=sys.stderr, flush=True)
        finally:
            if child is not None:
                exit_code = _kill_owned_group(child, graceful=True)
            try:
                if logs is not None:
                    logs.finish()
                    runs.heartbeat(token, worker_pid, logs)
            finally:
                if logs is not None:
                    logs.close()
                runs.finish(token, exit_code, reason)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    return supervise(args.db, args.token)


if __name__ == "__main__":
    raise SystemExit(main())
