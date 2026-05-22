from __future__ import annotations

from pathlib import Path

import pytest

from local_agent_runtime.config import RuntimeConfig
from local_agent_runtime.sessions import FakeSessionManager, TmuxSessionManager


def test_runtime_config_reads_prefixed_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_DB", "state/runtime.sqlite3")
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT", "state/workspaces")
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_SESSION", "fake")

    config = RuntimeConfig.from_env()

    assert config.db_path == Path("state/runtime.sqlite3")
    assert config.workspace_root == Path("state/workspaces")
    assert config.session == "fake"


def test_runtime_config_explicit_values_override_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_DB", "env/runtime.sqlite3")
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT", "env/workspaces")
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_SESSION", "fake")

    config = RuntimeConfig.from_env(
        db_path="cli/runtime.sqlite3",
        workspace_root="cli/workspaces",
        session="tmux",
    )

    assert config.db_path == Path("cli/runtime.sqlite3")
    assert config.workspace_root == Path("cli/workspaces")
    assert config.session == "tmux"


def test_runtime_config_rejects_unknown_session():
    with pytest.raises(ValueError, match="session must be one of"):
        RuntimeConfig(session="screen")


def test_runtime_config_builds_runtime_with_requested_session(tmp_path):
    fake_config = RuntimeConfig(
        db_path=tmp_path / "runtime.sqlite3",
        workspace_root=tmp_path / "workspaces",
        session="fake",
    )
    fake_runtime = fake_config.create_runtime()
    assert isinstance(fake_runtime.sessions, FakeSessionManager)

    tmux_config = RuntimeConfig(
        db_path=tmp_path / "runtime.sqlite3",
        workspace_root=tmp_path / "workspaces",
        session="tmux",
    )
    tmux_runtime = tmux_config.create_runtime()
    assert isinstance(tmux_runtime.sessions, TmuxSessionManager)
