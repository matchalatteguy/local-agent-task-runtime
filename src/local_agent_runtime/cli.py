from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from . import __version__
from .backlog import export_backlog, load_backlog, register_backlog
from .config import RuntimeConfig
from .dispatch import Dispatcher
from .models import TaskStatus
from .process import ProcessSessionManager, ProcessStore, require_process_support
from .store import SqliteRuntimeStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-runtime")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "SQLite runtime path "
            "(default: LOCAL_AGENT_RUNTIME_DB or .agent-runtime/runtime.sqlite3)"
        ),
    )
    parser.add_argument(
        "--workspace-root",
        default=None,
        help="Root for relative task workspaces (default: LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT or .)",
    )
    sub = parser.add_subparsers(dest="command_name", required=True)

    sub.add_parser("init")

    sub.add_parser("doctor")
    demo = sub.add_parser("demo", help="Run the packaged test/build/verify showcase")
    demo.add_argument("--output", type=Path, default=Path(".agent-runtime/demo"))

    register = sub.add_parser("register")
    register.add_argument("--id", required=True)
    register.add_argument("--role", required=True)
    register.add_argument("--command", required=True)
    register.add_argument("--workspace", required=True)
    register.add_argument("--branch")

    start = sub.add_parser("start")
    start.add_argument("task_id")
    start.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )
    start.add_argument(
        "--timeout", type=float, default=None, help="Process deadline in seconds (3600)"
    )

    stop = sub.add_parser("stop")
    stop.add_argument("task_id")
    stop.add_argument("--status", choices=["stopped", "blocked", "failed"], default="blocked")
    stop.add_argument("--notes")
    stop.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )

    done = sub.add_parser("done")
    done.add_argument("task_id")
    done.add_argument("--notes")
    done.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )

    heartbeat = sub.add_parser("heartbeat")
    heartbeat.add_argument("task_id")

    sync = sub.add_parser("sync")
    sync.add_argument(
        "--stale-after", type=int, default=30, help="Minutes before a heartbeat is stale"
    )
    sync.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--max-concurrent", type=int, default=1)
    dispatch.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )
    dispatch.add_argument("--timeout", type=float, default=None, help="Process deadline in seconds")

    tick = sub.add_parser("tick")
    tick.add_argument("--max-concurrent", type=int, default=1)
    tick.add_argument(
        "--stale-after", type=int, default=30, help="Minutes before a heartbeat is stale"
    )
    tick.add_argument(
        "--session",
        choices=["fake", "tmux", "process"],
        default=None,
        help="Session adapter (default: LOCAL_AGENT_RUNTIME_SESSION or tmux)",
    )
    tick.add_argument("--timeout", type=float, default=None, help="Process deadline in seconds")

    for launcher in (start, dispatch, tick):
        launcher.add_argument(
            "--log-limit",
            type=int,
            default=None,
            help="Retained bytes per process stdout/stderr log (8388608)",
        )

    for name in ("show", "runs", "retry"):
        sub.add_parser(name).add_argument("task_id")
    wait = sub.add_parser("wait", help="Wait for a result; a wait timeout does not stop the worker")
    wait.add_argument("task_id")
    wait.add_argument("--timeout", type=float, default=30)
    recover = sub.add_parser("recover", help="Record a lost supervisor; never signal stored PIDs")
    recover.add_argument("task_id")
    recover.add_argument("--acknowledge-lost", action="store_true")
    recover.add_argument("--notes")
    logs = sub.add_parser("logs", help="Read the last lines of a process attempt log")
    logs.add_argument("task_id")
    logs.add_argument("--attempt", help="Launch token (default: latest attempt)")
    logs.add_argument("--stream", choices=["stdout", "stderr", "runner"], default="stdout")
    logs.add_argument("--lines", type=int, default=50)
    logs.add_argument("--json", action="store_true")

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--status", choices=[status.value for status in TaskStatus])
    list_cmd.add_argument("--json", action="store_true")

    events = sub.add_parser("events")
    events.add_argument("task_id")
    events.add_argument("--json", action="store_true")

    import_cmd = sub.add_parser("import")
    import_cmd.add_argument("path", help="JSON backlog file: list of tasks or {version, tasks}")

    export_cmd = sub.add_parser("export")
    export_cmd.add_argument("--output", help="Write JSON snapshot to this path instead of stdout")

    summary = sub.add_parser("summary")
    summary.add_argument(
        "--stale-after", type=int, default=30, help="Minutes before a heartbeat is stale"
    )
    summary.add_argument("--json", action="store_true")
    return parser


def _config(args: argparse.Namespace) -> RuntimeConfig:
    return RuntimeConfig.from_env(
        db_path=args.db,
        workspace_root=args.workspace_root,
        session=getattr(args, "session", None),
        process_timeout_seconds=getattr(args, "timeout", None),
        process_log_limit_bytes=getattr(args, "log_limit", None),
    )


def _store(args: argparse.Namespace) -> SqliteRuntimeStore:
    return SqliteRuntimeStore(_config(args).db_path)


def emit(data: object, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(data)


def _stale_after(minutes: int) -> timedelta:
    if minutes < 1:
        raise ValueError("--stale-after must be at least 1 minute")
    return timedelta(minutes=minutes)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_name == "demo":
            from .demo import run_demo

            emit(run_demo(args.output))
        elif args.command_name == "init":
            store = _store(args)
            emit({"db": str(store.path), "initialized": True})
        elif args.command_name == "doctor":
            config = _config(args)
            store = SqliteRuntimeStore(config.db_path)
            try:
                require_process_support()
                process_support = {"available": True}
            except RuntimeError as exc:
                process_support = {"available": False, "detail": str(exc)}
            emit(
                {
                    "db": str(store.path),
                    "schema_version": store.schema_version(),
                    "session": config.session,
                    "workspace_root": str(config.workspace_root),
                    "process": process_support,
                }
            )
        elif args.command_name == "register":
            config = _config(args)
            store = SqliteRuntimeStore(config.db_path)
            task = store.register_task(
                args.id,
                args.role,
                args.command,
                args.workspace,
                args.branch,
                config.workspace_root,
            )
            emit(task.to_dict())
        elif args.command_name == "start":
            emit(_config(args).create_runtime().start_task(args.task_id).to_dict())
        elif args.command_name == "show":
            store = _store(args)
            runs = ProcessStore(store).runs(args.task_id)
            emit(
                {
                    "task": store.get_task(args.task_id).to_dict(),
                    "latest_run": runs[-1] if runs else None,
                }
            )
        elif args.command_name == "runs":
            emit(ProcessStore(_store(args)).runs(args.task_id))
        elif args.command_name == "retry":
            emit(_store(args).retry_task(args.task_id).to_dict())
        elif args.command_name == "wait":
            task = _config(args).create_runtime().wait_task(args.task_id, args.timeout)
            emit(task.to_dict())
            return 0 if task.status == TaskStatus.DONE else 1
        elif args.command_name == "recover":
            store = _store(args)
            task = store.get_task(args.task_id)
            if task.session_kind != "process" or not task.launch_token:
                raise ValueError("recover requires a process attempt; use sync for tmux/fake")
            ProcessSessionManager(store.path).recover(
                task.launch_token, args.acknowledge_lost, args.notes
            )
            emit(store.get_task(args.task_id).to_dict())
        elif args.command_name == "logs":
            if args.lines < 1 or args.lines > 10000:
                raise ValueError("--lines must be between 1 and 10000")
            runs = ProcessStore(_store(args)).runs(args.task_id)
            run = next(
                (
                    run
                    for run in reversed(runs)
                    if not args.attempt or run["launch_token"] == args.attempt
                ),
                None,
            )
            if run is None:
                raise ValueError("no matching process attempt")
            path = Path(run["logs"][args.stream])
            content = ""
            if path.exists():
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 65536))
                    content = stream.read().decode("utf-8", errors="replace")
                content = "\n".join(content.splitlines()[-args.lines :])
            if args.json:
                emit({"launch_token": run["launch_token"], "path": str(path), "content": content})
            else:
                print(content)
        elif args.command_name == "stop":
            emit(
                _config(args)
                .create_runtime()
                .stop_task(args.task_id, args.status, args.notes)
                .to_dict()
            )
        elif args.command_name == "done":
            emit(_config(args).create_runtime().mark_done(args.task_id, args.notes).to_dict())
        elif args.command_name == "heartbeat":
            emit(_config(args).create_runtime().heartbeat(args.task_id).to_dict())
        elif args.command_name == "sync":
            emit(_config(args).create_runtime().sync_runtime(_stale_after(args.stale_after)))
        elif args.command_name == "dispatch":
            emit(
                Dispatcher(_config(args).create_runtime())
                .dispatch_ready(args.max_concurrent)
                .to_dict()
            )
        elif args.command_name == "tick":
            emit(
                Dispatcher(_config(args).create_runtime()).tick(
                    args.max_concurrent,
                    stale_after=_stale_after(args.stale_after),
                )
            )
        elif args.command_name == "list":
            tasks = [task.to_dict() for task in _store(args).list_tasks(args.status)]
            emit(tasks, as_json=args.json)
        elif args.command_name == "events":
            events = [event.to_dict() for event in _store(args).read_events(args.task_id)]
            emit(events, as_json=args.json)
        elif args.command_name == "import":
            config = _config(args)
            store = SqliteRuntimeStore(config.db_path)
            tasks = register_backlog(
                store,
                load_backlog(args.path),
                workspace_root=config.workspace_root,
            )
            emit({"imported": [task.to_dict() for task in tasks], "count": len(tasks)})
        elif args.command_name == "export":
            data = export_backlog(_store(args))
            if args.output:
                Path(args.output).write_text(
                    json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
                )
                emit(
                    {
                        "output": args.output,
                        "tasks": len(data["tasks"]),
                        "events": len(data["events"]),
                    }
                )
            else:
                emit(data)
        elif args.command_name == "summary":
            emit(
                _config(args).create_runtime().summary(stale_after=_stale_after(args.stale_after)),
                as_json=args.json,
            )
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 124
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
