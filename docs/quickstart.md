# Quickstart

This page walks through a safe first run with the fake session adapter. It creates local files under `.agent-runtime/` and does not require tmux or external services.

If you prefer not to repeat common flags, set environment defaults once per shell:

```bash
export LOCAL_AGENT_RUNTIME_DB=.agent-runtime/runtime.sqlite3
export LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT=.agent-runtime/workspaces
export LOCAL_AGENT_RUNTIME_SESSION=fake
```

Explicit `--db`, `--workspace-root`, and `--session` flags override those variables.

## 1. Initialize the runtime store

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 init
```

Expected shape:

```json
{
  "db": ".agent-runtime/runtime.sqlite3",
  "initialized": true
}
```

## 2. Register a task

Use a relative workspace path. It will be resolved under `--workspace-root`.

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id docs-quickstart \
  --role docs \
  --command "python scripts/write_docs.py" \
  --workspace docs-quickstart
```

The command is intentionally synthetic. With `--session fake`, the runtime records session state without executing the command.

## 3. Start and inspect

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  start docs-quickstart --session fake

uv run agent-runtime --db .agent-runtime/runtime.sqlite3 list --status running --json
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 events docs-quickstart --json
```

You should see `status: "running"`, a session id like `agent-runtime-docs-quickstart`, and events such as `registered` and `started`.

With the environment defaults shown at the top of this page, the same start command can be shortened to:

```bash
uv run agent-runtime start docs-quickstart
```

## 4. Send a heartbeat

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 heartbeat docs-quickstart
```

Heartbeats update `heartbeat_at` and append a `heartbeat` event. Supervisors use this timestamp to identify tasks that may need attention.

## 5. Complete with a handoff note

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  done docs-quickstart --session fake --notes "README quickstart updated."
```

The task moves to `done`, the fake session is removed, and the note is stored on the task record and in the event stream.

## Next steps

- Replace `--session fake` with `--session tmux` when you want real detached execution.
- Run `tick --max-concurrent 2` to reconcile and dispatch several registered tasks.
- Read `workspace-isolation.md` before using absolute paths or git worktrees.
