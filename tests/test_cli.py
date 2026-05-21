from __future__ import annotations

from local_agent_runtime.cli import main


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
    assert main(["--db", str(db), "events", "missing", "--json"]) == 0
    assert main(["--db", str(db), "start", "missing", "--session", "fake"]) == 2
    assert "error:" in capsys.readouterr().err
