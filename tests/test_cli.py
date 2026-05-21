from __future__ import annotations

import pytest

from local_agent_runtime.cli import main


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "agent-runtime 0.1.0" in capsys.readouterr().out


def test_cli_register_list_events_summary(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    work = tmp_path / "work"
    assert main(["--db", str(db), "--workspace-root", str(work), "init"]) == 0
    assert (
        main(
            [
                "--db",
                str(db),
                "--workspace-root",
                str(work),
                "register",
                "--id",
                "docs",
                "--role",
                "docs",
                "--command",
                "python docs.py",
                "--workspace",
                "docs",
            ]
        )
        == 0
    )
    assert main(["--db", str(db), "list", "--status", "ready", "--json"]) == 0
    assert '"id": "docs"' in capsys.readouterr().out
    assert main(["--db", str(db), "events", "docs", "--json"]) == 0
    assert '"kind": "registered"' in capsys.readouterr().out
    assert main(["--db", str(db), "--workspace-root", str(work), "summary", "--json"]) == 0
    assert '"counts"' in capsys.readouterr().out


def test_cli_invalid_task_returns_nonzero(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    assert main(["--db", str(db), "events", "missing", "--json"]) == 2
    assert main(["--db", str(db), "start", "missing", "--session", "fake"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_fake_session_start_sync_done_smoke(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    work = tmp_path / "work"
    common = ["--db", str(db), "--workspace-root", str(work)]

    assert (
        main(
            [
                *common,
                "register",
                "--id",
                "style-cleanup",
                "--role",
                "maintenance",
                "--command",
                "python scripts/format_notes.py",
                "--workspace",
                "workspaces/style-cleanup",
            ]
        )
        == 0
    )
    assert main([*common, "start", "style-cleanup", "--session", "fake"]) == 0
    assert (work / "workspaces" / "style-cleanup").is_dir()
    assert main([*common, "sync"]) == 0
    assert '"stale": []' in capsys.readouterr().out
    assert (
        main([*common, "done", "style-cleanup", "--notes", "formatted", "--session", "fake"])
        == 0
    )
    assert main([*common, "events", "style-cleanup", "--json"]) == 0
    output = capsys.readouterr().out
    assert '"kind": "started"' in output
    assert '"kind": "done"' in output
