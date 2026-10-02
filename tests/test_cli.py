from __future__ import annotations

import json

import pytest

from local_agent_runtime.cli import main


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "agent-runtime 0.3.0" in capsys.readouterr().out


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


def test_cli_doctor_reports_schema_and_config(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    work = tmp_path / "work"

    assert main(["--db", str(db), "--workspace-root", str(work), "doctor"]) == 0

    output = capsys.readouterr().out
    assert '"schema_version": 3' in output
    assert f'"workspace_root": "{work}"' in output


def test_cli_import_export_json_backlog(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    work = tmp_path / "work"
    backlog = tmp_path / "tasks.json"
    export_path = tmp_path / "snapshot.json"
    backlog.write_text(
        json.dumps(
            {
                "version": 1,
                "tasks": [
                    {
                        "id": "docs",
                        "role": "docs",
                        "command": "python docs.py",
                        "workspace": "docs",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--db", str(db), "--workspace-root", str(work), "import", str(backlog)]) == 0
    assert '"count": 1' in capsys.readouterr().out
    assert main(["--db", str(db), "export", "--output", str(export_path)]) == 0
    exported = json.loads(export_path.read_text(encoding="utf-8"))

    assert exported["tasks"][0]["id"] == "docs"
    assert exported["events"][0]["kind"] == "registered"


def test_cli_stale_after_validation(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"

    assert main(["--db", str(db), "summary", "--stale-after", "0", "--json"]) == 2
    assert "--stale-after must be at least 1 minute" in capsys.readouterr().err


def test_cli_invalid_task_returns_nonzero(tmp_path, capsys):
    db = tmp_path / "runtime.sqlite3"
    assert main(["--db", str(db), "events", "missing", "--json"]) == 2
    assert main(["--db", str(db), "start", "missing", "--session", "fake"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_uses_environment_defaults(tmp_path, monkeypatch, capsys):
    db = tmp_path / "env" / "runtime.sqlite3"
    work = tmp_path / "env" / "work"
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_DB", str(db))
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT", str(work))
    monkeypatch.setenv("LOCAL_AGENT_RUNTIME_SESSION", "fake")

    assert main(["init"]) == 0
    assert (
        main(
            [
                "register",
                "--id",
                "env-task",
                "--role",
                "docs",
                "--command",
                "python docs.py",
                "--workspace",
                "env-task",
            ]
        )
        == 0
    )
    assert main(["start", "env-task"]) == 0

    assert db.exists()
    assert (work / "env-task").is_dir()
    assert '"session_id": "agent-runtime-env-task-' in capsys.readouterr().out


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
    assert main([*common, "sync", "--session", "fake"]) == 0
    assert '"stale": []' in capsys.readouterr().out
    assert (
        main([*common, "done", "style-cleanup", "--notes", "formatted", "--session", "fake"]) == 0
    )
    assert main([*common, "events", "style-cleanup", "--json"]) == 0
    output = capsys.readouterr().out
    assert '"kind": "started"' in output
    assert '"kind": "done"' in output
