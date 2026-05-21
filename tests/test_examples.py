from __future__ import annotations

from pathlib import Path

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
