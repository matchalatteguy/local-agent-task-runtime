# Local Agent Task Runtime

Local Agent Task Runtime is a small Python library and CLI for coordinating local AI-agent or script tasks without running a server. It gives a local operator durable SQLite state, append-only lifecycle events, recoverable worker sessions, isolated workspaces, heartbeat/stale detection, and JSON output that a human, dashboard, cron job, or supervising agent can inspect.

It is intentionally local-first: one machine, one SQLite database, no network services, no hosted control plane, and no secret storage.

## When this helps

Use this when you have a backlog of local work such as documentation updates, tests, refactors, data cleanup, or repository maintenance scripts and you need to answer:

- what is `ready`, `running`, `blocked`, `stopped`, `done`, or `failed`;
- which session owns each running task;
- when a worker last sent a heartbeat;
- whether a running task lost its session;
- how many tasks can be dispatched safely at once;
- what happened to a task, in append-only lifecycle events;
- what final notes or handoff a worker left behind.

The runtime is useful before you need Kubernetes, Celery, Temporal, a hosted agent platform, or a custom dashboard.

## Install for development

Prerequisites:

- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/) for dependency and virtualenv management
- optional: `tmux` for real detached worker sessions on Linux, macOS, or WSL

```bash
uv sync
uv run pytest
uv run ruff check .
```

Then run the CLI from the checkout:

```bash
uv run agent-runtime init --db .agent-runtime/runtime.sqlite3
```

## Five-minute quickstart

This quickstart uses the fake session adapter, so it is safe to run on any development machine and does not require `tmux`.

```bash
# 1. Create the local SQLite runtime store.
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 init

# 2. Register a synthetic docs task under a contained workspace root.
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id docs-quickstart \
  --role docs \
  --command "python scripts/write_docs.py" \
  --workspace docs-quickstart

# 3. Start the task with the deterministic fake session adapter.
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  start docs-quickstart --session fake

# 4. Inspect state and events as JSON.
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 list --status running --json
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 events docs-quickstart --json
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 summary --json

# 5. Record liveness and then complete the task with a handoff note.
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 heartbeat docs-quickstart
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 done docs-quickstart --session fake --notes "README quickstart updated."
```

For real detached execution, use `--session tmux`. The tmux adapter names sessions as `agent-runtime-<task-id>` by default and starts each command in the prepared task workspace.

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 start docs-quickstart --session tmux
tmux attach-session -t agent-runtime-docs-quickstart
```

## Core lifecycle

1. `register`: insert a task record with an id, role, command, workspace, and optional branch.
2. `dispatch` or `start`: prepare the workspace and start a worker session.
3. `heartbeat`: refresh liveness for long-running work.
4. `sync`: reconcile running tasks with the session adapter and record stale or missing-session events.
5. `stop`: move a task to `blocked`, `stopped`, or `failed` with notes.
6. `done`: mark the task complete and preserve final handoff notes.

Statuses are intentionally small and stable:

- `ready`: eligible for dispatch.
- `running`: owned by a worker session.
- `stopped`: no longer running, often because a session disappeared or was manually stopped.
- `blocked`: paused until a human or manager provides input.
- `done`: completed successfully with optional notes.
- `failed`: ended unsuccessfully.

## CLI command map

| Command | Purpose |
| --- | --- |
| `init` | Create or update the SQLite schema. |
| `register` | Insert a task with an id, role, command, workspace, and optional branch. |
| `start` | Prepare the workspace and start one task. |
| `stop` | Stop a session and record `stopped`, `blocked`, or `failed`. |
| `done` | Stop any live session and record a final handoff note. |
| `heartbeat` | Update task liveness. |
| `sync` | Check running tasks for missing sessions or stale heartbeats. |
| `dispatch` | Start ready tasks up to `--max-concurrent`. |
| `tick` | Run `sync` and then `dispatch`; useful from cron or a manager loop. |
| `list` | List task records, optionally filtered by status. |
| `summary` | Print counts, active tasks, stale tasks, and recent events. |
| `events` | Print a task's append-only event stream. |

Most inspection commands support `--json`; state-changing commands emit JSON by default.

## Library usage

```python
from pathlib import Path

from local_agent_runtime.runtime import AgentTaskRuntime
from local_agent_runtime.sessions import FakeSessionManager

runtime = AgentTaskRuntime.local(
    db_path=".agent-runtime/runtime.sqlite3",
    sessions=FakeSessionManager(),
    workspace_root=Path(".agent-runtime/workspaces"),
)

runtime.register_task(
    task_id="docs-quickstart",
    role="docs",
    command="python scripts/write_docs.py",
    workspace="docs-quickstart",
)
runtime.start_task("docs-quickstart")
runtime.heartbeat("docs-quickstart")
runtime.mark_done("docs-quickstart", notes="Updated README and examples.")
```

## Workspace isolation

Relative task workspaces are resolved under `--workspace-root`. Paths containing `..` are rejected. Absolute paths are accepted only when they stay inside the configured root. Use plain directories for scripts and read-only tasks. Use the `GitWorktreeWorkspaceManager` from Python when parallel code-editing tasks need isolated checkouts from the same repository.

## Manager loop pattern

A simple local supervisor can run one tick at a time:

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  tick --max-concurrent 3 --session tmux --json
```

Run that command from cron, a shell loop, or another local agent. `tick` first reconciles current state, then dispatches ready work up to the concurrency cap.

## Documentation

- `docs/quickstart.md`: first-run walkthrough and expected outputs.
- `docs/concepts.md`: data model, statuses, and operating model.
- `docs/session-managers.md`: fake and tmux adapters, naming, and platform notes.
- `docs/workspace-isolation.md`: contained paths, directory workspaces, and git worktrees.
- `docs/lifecycle-and-events.md`: event streams, heartbeats, stale detection, and handoff notes.
- `docs/operations-recipes.md`: practical commands for local supervisors.
- `examples/repo-maintenance/`: offline synthetic backlog for documentation/test cleanup.

## Non-goals

This project is not a hosted service, distributed queue, CI platform, remote repository bot, secret manager, or multi-host scheduler. It does not publish anything, call external APIs, manage credentials, or automate authenticated services. SQLite is used as a local runtime store, not as a distributed lock service.

## Safety and privacy notes

Examples are synthetic and use relative paths. Keep task commands, notes, and event payloads free of secrets because they are stored durably in SQLite and may be exported to logs, dashboards, or supervising agents.
