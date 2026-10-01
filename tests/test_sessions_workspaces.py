from __future__ import annotations

import shlex

import pytest

from local_agent_runtime.models import TaskRecord, WorkerSpec, require_relative_or_contained
from local_agent_runtime.sessions import FakeSessionManager, TmuxSessionManager
from local_agent_runtime.workspaces import DirectoryWorkspaceManager


def test_fake_session_lifecycle(tmp_path):
    manager = FakeSessionManager(state_path=tmp_path / "sessions.json")
    session_id = manager.start("docs", WorkerSpec("python docs.py"))
    assert manager.exists(session_id)
    assert FakeSessionManager(state_path=tmp_path / "sessions.json").exists(session_id)
    assert manager.attach_command(session_id).startswith("fake attach")
    manager.stop(session_id)
    assert not manager.exists(session_id)


def test_tmux_attach_command_quotes_session_name():
    session = "agent task; rm sample"
    assert TmuxSessionManager().attach_command(session) == "tmux attach-session -t " + shlex.quote(
        f"={session}"
    )


@pytest.mark.parametrize("name", ["release.v1", "release:one"])
def test_tmux_rejects_names_it_would_normalize_before_start(name, monkeypatch):
    monkeypatch.setattr("local_agent_runtime.sessions.shutil.which", lambda _: "tmux")
    with pytest.raises(ValueError, match="cannot contain"):
        TmuxSessionManager().start("task", WorkerSpec("worker", session_name=name))


def test_directory_workspace_stays_in_root(tmp_path):
    manager = DirectoryWorkspaceManager(tmp_path)
    task = TaskRecord(id="docs", role="docs", command="python docs.py", workspace="docs")
    assert manager.prepare(task) == tmp_path / "docs"
    with pytest.raises(ValueError):
        require_relative_or_contained("../outside")


def test_relative_symlink_cannot_escape_workspace_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    manager = DirectoryWorkspaceManager(root)
    task = TaskRecord(id="docs", role="docs", command="python docs.py", workspace="escape/docs")
    with pytest.raises(ValueError, match="stay inside"):
        manager.prepare(task)
    assert not (outside / "docs").exists()
