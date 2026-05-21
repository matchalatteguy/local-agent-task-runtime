from __future__ import annotations

import pytest

from local_agent_runtime.models import TaskStatus
from local_agent_runtime.store import SqliteRuntimeStore


def test_init_is_idempotent(tmp_path):
    db = tmp_path / "runtime.sqlite3"
    first = SqliteRuntimeStore(db)
    second = SqliteRuntimeStore(db)
    assert first.path == second.path
    assert second.counts_by_status() == {}


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
