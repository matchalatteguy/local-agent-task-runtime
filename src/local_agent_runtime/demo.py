"""Run isolated tests, build a zip artifact, and verify it with detached workers."""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from .config import RuntimeConfig
from .models import TaskStatus
from .process import ProcessStore, require_process_support

REPORT_SOURCE = """import csv
from decimal import Decimal


def summarize(path):
    with open(path, newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    return {
        "items": len(rows),
        "total_units": sum(int(row["quantity"]) for row in rows),
        "inventory_value": str(sum(
            (Decimal(row["unit_price"]) * int(row["quantity"]) for row in rows),
            start=Decimal("0.00"),
        )),
    }
"""
TEST_SOURCE = """import unittest
from report import summarize


class InventoryTest(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(summarize("inventory.csv"), {
            "items": 3, "total_units": 18, "inventory_value": "82.49",
        })
"""
BUILD_SOURCE = """from pathlib import Path
from zipfile import ZipFile

Path("dist").mkdir(exist_ok=True)
with ZipFile("dist/report.zip", "w") as archive:
    archive.write("report.py")
    archive.write("inventory.csv")
print("Built dist/report.zip")
"""
VERIFY_SOURCE = """import json
from zipfile import ZipFile
import sys

with ZipFile("report.zip") as archive:
    assert archive.testzip() is None
    with open("inventory.csv", "wb") as destination:
        destination.write(archive.read("inventory.csv"))
sys.path.insert(0, "report.zip")
import report
summary = report.summarize("inventory.csv")
assert summary == {"items": 3, "total_units": 18, "inventory_value": "82.49"}
with open("verified.json", "w", encoding="utf-8") as destination:
    json.dump(summary, destination, sort_keys=True)
print("Verified archive import and inventory totals")
"""
INVENTORY = "item,quantity,unit_price\nnotebook,5,3.50\ncable,10,4.00\nstand,3,8.33\n"


def run_demo(output: Path) -> dict[str, object]:
    require_process_support()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = output / "workspaces"
    for name in ("checks", "build", "verify"):
        (root / name).mkdir(parents=True)
    checks = root / "checks"
    # The first run deliberately contains a bug, so its exit code and failure
    # log remain inspectable after a successful retry.
    (checks / "report.py").write_text(
        REPORT_SOURCE.replace(
            'sum(int(row["quantity"]) for row in rows)',
            'sum(int(row["quantity"]) + 1 for row in rows)',
        ),
        encoding="utf-8",
    )
    (checks / "test_report.py").write_text(TEST_SOURCE, encoding="utf-8")
    (checks / "inventory.csv").write_text(INVENTORY, encoding="utf-8")
    config = RuntimeConfig(
        db_path=output / "runtime.sqlite3", workspace_root=root, session="process"
    )
    runtime = config.create_runtime()
    runtime.register_task(
        "checks",
        "test",
        shlex.join(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-v",
            ]
        ),
        "checks",
    )
    runtime.register_task("build", "build", shlex.join([sys.executable, "build.py"]), "build")
    runtime.register_task("verify", "verify", shlex.join([sys.executable, "verify.py"]), "verify")

    def launch_and_reopen(task_id: str, expected: TaskStatus) -> None:
        # This launcher exits before inspection. The detached runner, not this
        # demo process, persists the result and owns child-group cleanup.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "local_agent_runtime.cli",
                "--db",
                str(config.db_path),
                "--workspace-root",
                str(root),
                "start",
                task_id,
                "--session",
                "process",
                "--timeout",
                "15",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        reopened = RuntimeConfig(db_path=config.db_path).create_runtime()
        result = reopened.wait_task(task_id, 20)
        if result.status != expected:
            raise RuntimeError(
                f"{task_id}: expected {expected}, got {result.status}; inspect its logs"
            )

    launch_and_reopen("checks", TaskStatus.FAILED)
    (checks / "report.py").write_text(REPORT_SOURCE, encoding="utf-8")
    # Avoid reusing bytecode for a same-size, same-second source correction.
    shutil.rmtree(checks / "__pycache__", ignore_errors=True)
    runtime.store.retry_task("checks")
    launch_and_reopen("checks", TaskStatus.DONE)
    for name in ("report.py", "inventory.csv"):
        shutil.copyfile(checks / name, root / "build" / name)
    (root / "build/build.py").write_text(BUILD_SOURCE, encoding="utf-8")
    launch_and_reopen("build", TaskStatus.DONE)
    shutil.copyfile(root / "build/dist/report.zip", root / "verify/report.zip")
    (root / "verify/verify.py").write_text(VERIFY_SOURCE, encoding="utf-8")
    launch_and_reopen("verify", TaskStatus.DONE)
    reopened = RuntimeConfig(db_path=config.db_path).create_runtime()
    runs = ProcessStore(reopened.store)
    return {
        "counts": reopened.store.counts_by_status(),
        "checks_attempt_exit_codes": [run["exit_code"] for run in runs.runs("checks")],
        "artifact": "workspaces/build/dist/report.zip",
        "verified_summary": json.loads((root / "verify/verified.json").read_text(encoding="utf-8")),
        "restored_states": {task.id: task.status.value for task in reopened.store.list_tasks()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".agent-runtime/demo"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_demo(args.output), indent=2, sort_keys=True))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
