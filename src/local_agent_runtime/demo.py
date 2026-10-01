"""Run a real file-processing worker and inspect its persisted lifecycle.

The process adapter below is deliberately scoped to this demo's supervisor. It
does not provide detached session recovery; use the tmux adapter for that.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from .models import TaskStatus, WorkerSpec
from .runtime import AgentTaskRuntime


class DemoProcessSessions:
    def __init__(self) -> None:
        self.processes: dict[str, subprocess.Popen[str]] = {}

    def start(self, task_id: str, spec: WorkerSpec) -> str:
        session_id = f"demo-{task_id}"
        self.processes[session_id] = subprocess.Popen(
            shlex.split(spec.command),
            cwd=spec.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return session_id

    def stop(self, session_id: str) -> None:
        process = self.processes[session_id]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def exists(self, session_id: str) -> bool:
        process = self.processes.get(session_id)
        return process is not None and process.poll() is None

    def attach_command(self, session_id: str) -> str:
        raise NotImplementedError("the demo adapter has no interactive session")


def run_worker() -> None:
    with Path("inventory.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    summary = {
        "items": len(rows),
        "total_units": sum(int(row["quantity"]) for row in rows),
        "inventory_value": str(
            sum(
                (Decimal(row["unit_price"]) * int(row["quantity"]) for row in rows),
                start=Decimal("0.00"),
            )
        ),
    }
    Path("summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def run_demo(output: Path) -> dict[str, object]:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / "workspaces" / "inventory"
    workspace.mkdir(parents=True)
    (workspace / "inventory.csv").write_text(
        "item,quantity,unit_price\nnotebook,5,3.50\ncable,10,4.00\nstand,3,8.33\n",
        encoding="utf-8",
    )
    sessions = DemoProcessSessions()
    runtime = AgentTaskRuntime.local(output / "runtime.sqlite3", sessions, output / "workspaces")
    runtime.register_task(
        "inventory",
        "data",
        shlex.join(
            [
                sys.executable,
                "-m",
                "local_agent_runtime.demo",
                "--worker",
            ]
        ),
        "inventory",
    )
    task = runtime.start_task("inventory")
    runtime.heartbeat("inventory")
    assert task.session_id is not None
    process = sessions.processes[task.session_id]
    try:
        _, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        runtime.stop_task("inventory", TaskStatus.FAILED, "demo worker timed out")
        raise RuntimeError("demo worker timed out") from None
    if process.returncode != 0:
        runtime.stop_task("inventory", TaskStatus.FAILED, stderr[-500:])
        raise RuntimeError(f"demo worker failed: {stderr}")
    summary = json.loads((workspace / "summary.json").read_text(encoding="utf-8"))
    runtime.mark_done("inventory", "Summarized three inventory rows; summary.json is ready.")
    # Reopen the database to prove the report comes from persisted state.
    reopened = AgentTaskRuntime.local(
        output / "runtime.sqlite3",
        sessions,
        output / "workspaces",
    )
    return {
        "counts": reopened.store.counts_by_status(),
        "events": [event.kind for event in reopened.store.read_events("inventory")],
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".agent-runtime/demo"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            run_worker()
        else:
            print(json.dumps(run_demo(args.output), indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
