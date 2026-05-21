from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .dispatch import Dispatcher
from .models import TaskStatus
from .runtime import AgentTaskRuntime
from .sessions import FakeSessionManager, TmuxSessionManager
from .store import SqliteRuntimeStore
from .workspaces import DirectoryWorkspaceManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-runtime")
    parser.add_argument(
        "--db", default=".agent-runtime/runtime.sqlite3", help="SQLite runtime path"
    )
    parser.add_argument("--workspace-root", default=".", help="Root for relative task workspaces")
    sub = parser.add_subparsers(dest="command_name", required=True)

    sub.add_parser("init")

    register = sub.add_parser("register")
    register.add_argument("--id", required=True)
    register.add_argument("--role", required=True)
    register.add_argument("--command", required=True)
    register.add_argument("--workspace", required=True)
    register.add_argument("--branch")

    start = sub.add_parser("start")
    start.add_argument("task_id")
    start.add_argument("--session", choices=["fake", "tmux"], default="tmux")

    stop = sub.add_parser("stop")
    stop.add_argument("task_id")
    stop.add_argument("--status", choices=["stopped", "blocked", "failed"], default="blocked")
    stop.add_argument("--notes")
    stop.add_argument("--session", choices=["fake", "tmux"], default="tmux")

    done = sub.add_parser("done")
    done.add_argument("task_id")
    done.add_argument("--notes")
    done.add_argument("--session", choices=["fake", "tmux"], default="tmux")

    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("task_id")

    sub.add_parser("sync")

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--max-concurrent", type=int, default=1)
    dispatch.add_argument("--session", choices=["fake", "tmux"], default="tmux")

    tick = sub.add_parser("tick")
    tick.add_argument("--max-concurrent", type=int, default=1)
    tick.add_argument("--session", choices=["fake", "tmux"], default="tmux")

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--status", choices=[status.value for status in TaskStatus])
    list_cmd.add_argument("--json", action="store_true")

    events = sub.add_parser("events")
    events.add_argument("task_id")
    events.add_argument("--json", action="store_true")

    summary = sub.add_parser("summary")
    summary.add_argument("--json", action="store_true")
    return parser


def _session(name: str, db_path: str | Path = ".agent-runtime/runtime.sqlite3"):
    if name == "fake":
        return FakeSessionManager(state_path=Path(str(db_path) + ".fake-sessions.json"))
    return TmuxSessionManager()


def _runtime(args: argparse.Namespace) -> AgentTaskRuntime:
    session_name = getattr(args, "session", "fake")
    return AgentTaskRuntime(
        SqliteRuntimeStore(args.db),
        _session(session_name, args.db),
        DirectoryWorkspaceManager(Path(args.workspace_root)),
    )


def emit(data: object, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(data)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_name == "init":
            store = SqliteRuntimeStore(args.db)
            emit({"db": str(store.path), "initialized": True})
        elif args.command_name == "register":
            store = SqliteRuntimeStore(args.db)
            task = store.register_task(
                args.id,
                args.role,
                args.command,
                args.workspace,
                args.branch,
                Path(args.workspace_root),
            )
            emit(task.to_dict())
        elif args.command_name == "start":
            emit(_runtime(args).start_task(args.task_id).to_dict())
        elif args.command_name == "stop":
            emit(_runtime(args).stop_task(args.task_id, args.status, args.notes).to_dict())
        elif args.command_name == "done":
            emit(_runtime(args).mark_done(args.task_id, args.notes).to_dict())
        elif args.command_name == "heartbeat":
            store = SqliteRuntimeStore(args.db)
            emit(
                store.update_task(
                    args.task_id,
                    heartbeat_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                    event_kind="heartbeat",
                ).to_dict()
            )
        elif args.command_name == "sync":
            emit(_runtime(args).sync_runtime())
        elif args.command_name == "dispatch":
            emit(Dispatcher(_runtime(args)).dispatch_ready(args.max_concurrent).to_dict())
        elif args.command_name == "tick":
            emit(Dispatcher(_runtime(args)).tick(args.max_concurrent))
        elif args.command_name == "list":
            tasks = [task.to_dict() for task in SqliteRuntimeStore(args.db).list_tasks(args.status)]
            emit(tasks, as_json=args.json)
        elif args.command_name == "events":
            events = [
                event.to_dict() for event in SqliteRuntimeStore(args.db).read_events(args.task_id)
            ]
            emit(events, as_json=args.json)
        elif args.command_name == "summary":
            emit(_runtime(args).summary(), as_json=args.json)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
