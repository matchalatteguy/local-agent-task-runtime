# Local Agent Task Runtime

Local Agent Task Runtime is a small Python library and CLI for coordinating local AI-agent or script tasks without a server. It stores durable task state in SQLite, records lifecycle events, starts recoverable worker sessions through an adapter interface, isolates task workspaces, detects stale work, and emits JSON for dashboards or supervising loops.

It is intentionally local-first: one machine, one SQLite database, no network services, and no secret storage.

## Why use it?

Use this when you have a backlog of local work such as documentation updates, tests, refactors, data cleanup, or repository maintenance scripts and need to know:

- what is ready, running, blocked, stopped, done, or failed;
- which session owns a task;
- when a worker last sent a heartbeat;
- whether a running task has lost its session;
- how many tasks can be dispatched safely at once;
- what happened, in append-only lifecycle events.

## Install for development

```bash
uv sync
uv run pytest
uv run ruff check .
```

Then run the CLI from the checkout:

```bash
uv run agent-runtime init --db .agent-runtime/runtime.sqlite3
```

## Quickstart

```bash
uv run agent-runtime init --db .agent-runtime/runtime.sqlite3
uv run agent-runtime register \
  --db .agent-runtime/runtime.sqlite3 \
  --id docs-quickstart \
  --role docs \
  --command "python scripts/write_docs.py" \
  --workspace workspaces/docs-quickstart
uv run agent-runtime start --db .agent-runtime/runtime.sqlite3 docs-quickstart --session fake
uv run agent-runtime heartbeat --db .agent-runtime/runtime.sqlite3 docs-quickstart
uv run agent-runtime done --db .agent-runtime/runtime.sqlite3 docs-quickstart --notes "README updated"
uv run agent-runtime events --db .agent-runtime/runtime.sqlite3 docs-quickstart --json
```

Use `--session tmux` to launch commands in tmux on Linux, macOS, or WSL. Tests use the fake adapter, so tmux is not required for development.

## CLI commands

- `init` creates or updates the SQLite schema.
- `register` inserts a task with an id, role, command, and workspace.
- `start` prepares the workspace and starts a session.
- `stop` records a controlled stop, block, or failure.
- `done` records a final handoff note.
- `heartbeat` updates task liveness.
- `sync` reconciles running tasks with session state.
- `dispatch` starts ready tasks up to a concurrency cap.
- `tick` runs `sync` then `dispatch`.
- `list`, `summary`, and `events` print JSON-friendly runtime state.

## Non-goals

This project is not a hosted service, distributed queue, CI platform, remote repository bot, or secret manager. It does not publish anything, call external APIs, or coordinate multiple machines. SQLite is used as a local runtime store, not as a distributed lock service.

## Documentation

See `docs/` for concepts, session managers, workspace isolation, lifecycle events, and operations recipes. The `examples/repo-maintenance` directory contains an offline synthetic backlog.
