from __future__ import annotations

import json

import pytest

from local_agent_runtime.backlog import export_backlog, load_backlog, register_backlog
from local_agent_runtime.store import SqliteRuntimeStore


def test_load_backlog_accepts_versioned_json_and_registers_tasks(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tasks": [
                    {
                        "id": "docs",
                        "role": "docs",
                        "command": "python docs.py",
                        "workspace": "work/docs",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")

    tasks = register_backlog(store, load_backlog(path), workspace_root=tmp_path)

    assert [task.id for task in tasks] == ["docs"]
    assert store.get_task("docs").workspace == "work/docs"


def test_load_backlog_rejects_missing_required_fields(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([{"id": "docs"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="role, command, workspace"):
        load_backlog(path)


def test_export_backlog_includes_tasks_and_events(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    store.register_task("docs", "docs", "python docs.py", "work/docs")

    exported = export_backlog(store)

    assert exported["version"] == 1
    assert exported["tasks"][0]["id"] == "docs"
    assert exported["events"][0]["kind"] == "registered"
