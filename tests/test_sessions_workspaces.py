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
        session
    )


def test_directory_workspace_stays_in_root(tmp_path):
    manager = DirectoryWorkspaceManager(tmp_path)
    task = TaskRecord(id="docs", role="docs", command="python docs.py", workspace="docs")
    assert manager.prepare(task) == tmp_path / "docs"
    with pytest.raises(ValueError):
        require_relative_or_contained("../outside")
