from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from local_agent_runtime.backlog import load_backlog, register_backlog
from local_agent_runtime.store import SqliteRuntimeStore


def _example_tasks() -> list[dict[str, str]]:
    example_path = Path(__file__).parents[1] / "examples" / "repo-maintenance" / "tasks.yaml"
    text = example_path.read_text(encoding="utf-8")
    tasks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("- id:"):
            current = {"id": line.split(":", 1)[1].strip()}
            tasks.append(current)
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    return tasks


def test_repo_maintenance_example_tasks_are_valid_runtime_inputs(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    tasks = _example_tasks()

    assert [task["id"] for task in tasks] == [
        "docs-quickstart",
        "tests-fixtures",
        "style-cleanup",
    ]
    for task in tasks:
        assert set(task) == {"id", "role", "command", "workspace"}
        record = store.register_task(
            task["id"],
            task["role"],
            task["command"],
            task["workspace"],
            workspace_root=tmp_path / "workspaces-root",
        )
        assert record.workspace.startswith("workspaces/")
        assert ".." not in Path(record.workspace).parts

    assert store.counts_by_status() == {"ready": 3}


def test_repo_maintenance_json_backlog_imports(tmp_path):
    example_path = Path(__file__).parents[1] / "examples" / "repo-maintenance" / "tasks.json"
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")

    imported = register_backlog(store, load_backlog(example_path), workspace_root=tmp_path)

    assert [task.id for task in imported] == [
        "docs-quickstart",
        "tests-fixtures",
        "style-cleanup",
    ]
    assert store.counts_by_status() == {"ready": 3}


def test_repo_maintenance_example_commands_run_in_task_workspaces(tmp_path):
    source = Path(__file__).parents[1] / "examples" / "repo-maintenance"
    example = tmp_path / "repo-maintenance"
    shutil.copytree(source, example)
    tasks = _example_tasks()

    for task in tasks:
        workspace = example / task["workspace"]
        workspace.mkdir(parents=True)
        result = subprocess.run(
            task["command"].replace("python", sys.executable, 1),
            cwd=workspace,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        assert task["id"] in result.stdout

    assert (example / "workspaces" / "docs-quickstart" / "quickstart-notes.md").is_file()
    assert (example / "workspaces" / "tests-fixtures" / "fixtures.json").is_file()
    assert (example / "workspaces" / "style-cleanup" / "formatted-notes.md").is_file()
