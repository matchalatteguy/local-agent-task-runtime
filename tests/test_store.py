from __future__ import annotations

import pytest

from local_agent_runtime.models import TaskStatus
from local_agent_runtime.store import SqliteRuntimeStore


def test_init_is_idempotent(tmp_path):
    db = tmp_path / "runtime.sqlite3"
    first = SqliteRuntimeStore(db)
    second = SqliteRuntimeStore(db)
    assert first.path == second.path
    assert second.schema_version() == 1
    assert second.counts_by_status() == {}


def test_newer_schema_version_is_rejected(tmp_path):
    import sqlite3

    db = tmp_path / "runtime.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer than supported"):
        SqliteRuntimeStore(db)


def test_register_validates_duplicate_and_workspace(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    task = store.register_task("docs-1", "docs", "python task.py", "work/docs-1")
    assert task.status == TaskStatus.READY
    assert store.counts_by_status() == {"ready": 1}
    with pytest.raises(ValueError, match="already exists"):
        store.register_task("docs-1", "docs", "python task.py", "work/docs-1")
    with pytest.raises(ValueError, match="workspace"):
        store.register_task("docs-2", "docs", "python task.py", "../outside")


def test_events_preserve_order_and_payload(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    store.register_task("tests", "qa", "pytest", "work/tests")
    store.append_event("tests", "note", {"message": "collect fixtures"})
    events = store.read_events("tests")
    assert [event.kind for event in events] == ["registered", "note"]
    assert events[1].payload == {"message": "collect fixtures"}


def test_limited_events_return_most_recent_events_in_chronological_order(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    store.register_task("tests", "qa", "pytest", "work/tests")
    for index in range(25):
        store.append_event("tests", f"note-{index}", {"index": index})

    events = store.read_events(limit=20)

    assert [event.kind for event in events] == [f"note-{index}" for index in range(5, 25)]
