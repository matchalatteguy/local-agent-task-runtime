# Operations recipes

These recipes assume a local runtime store at `.agent-runtime/runtime.sqlite3` and task workspaces under `.agent-runtime/workspaces`.

## One-shot tick

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  tick --max-concurrent 3 --session tmux --json
```

Run this from cron, a shell loop, or a supervising agent. It reconciles running tasks, dispatches ready tasks up to the cap, and prints a JSON summary.

## Dry-run a backlog without tmux

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 --workspace-root .agent-runtime/workspaces dispatch --max-concurrent 2 --session fake
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 summary --json
```

The fake adapter records session state without executing task commands.

## Inspect current state

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 summary --json
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 list --status running --json
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 events docs-quickstart --json
```

Use these commands from dashboards, scripts, or supervising agents because they return stable JSON shapes.

## Block a task with a note

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  stop docs-quickstart --status blocked --session tmux --notes "Needs a sample Markdown file."
```

Use `blocked` when a worker needs human input. Use `stopped` when the session ended but the task may be resumed. Use `failed` when the task should not be dispatched again without intervention.

## Record a completion handoff

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  done docs-quickstart --session tmux --notes "Updated quickstart and examples."
```

Keep notes concise and public-safe. Do not include credentials or sensitive local context.

## Cron-friendly manager loop

A cron entry can run a tick every minute:

```cron
* * * * * cd /path/to/project && uv run agent-runtime --db .agent-runtime/runtime.sqlite3 --workspace-root .agent-runtime/workspaces tick --max-concurrent 3 --session tmux --json >> .agent-runtime/tick.log 2>&1
```

Use a project-relative path in your own environment. The runtime itself does not require a fixed location.

## Troubleshooting

- `tmux is not installed or not on PATH`: install tmux or use `--session fake` for dry runs.
- `workspace path must not contain '..'`: choose a relative path under `--workspace-root`.
- `workspace path must stay inside the workspace root`: adjust the root or use a contained absolute path.
- `cannot start task in status ...`: inspect the task with `list --json` and decide whether to stop, unblock, or register a new task.
