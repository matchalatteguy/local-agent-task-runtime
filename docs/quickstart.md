# Quickstart

Start with the real, portable example from a fresh checkout:

```bash
uv sync --locked
uv run python -m local_agent_runtime.demo --output .agent-runtime/demo
```

It executes a Python subprocess that summarizes an inventory CSV. Expect one
`done` task, an event stream of `registered`, `start_claimed`, `started`,
`heartbeat`, `done`, and this artifact:

```json
{"inventory_value": "82.49", "items": 3, "total_units": 18}
```

The artifact is `.agent-runtime/demo/workspaces/inventory/summary.json`; durable
state is `.agent-runtime/demo/runtime.sqlite3`. Use a fresh output directory for
another run. The demo adapter belongs to its supervisor process and does not
provide detached recovery.

```bash
uv run agent-runtime --db .agent-runtime/demo/runtime.sqlite3 list --json
uv run agent-runtime --db .agent-runtime/demo/runtime.sqlite3 events inventory --json
```

## Try the CLI lifecycle without executing work

The fake adapter stores simulated session ids. It executes no commands, even if
the command is runnable. Use a separate database from the real example:

```bash
export LOCAL_AGENT_RUNTIME_DB=.agent-runtime/fake.sqlite3
export LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT=.agent-runtime/workspaces
export LOCAL_AGENT_RUNTIME_SESSION=fake

uv run agent-runtime init
uv run agent-runtime register --id practice --role docs --workspace practice --command "printf 'hello'"
uv run agent-runtime start practice
uv run agent-runtime heartbeat practice
uv run agent-runtime done practice --notes "Lifecycle exercise complete."
uv run agent-runtime events practice --json
```

The final state is `done`. Explicit `--db`, `--workspace-root`, and `--session`
flags override the environment defaults. Unset these variables before following
examples that rely on the default tmux adapter.

## Run detached workers

See the [README detached-worker example](../README.md#start-a-detached-worker)
for an executable tmux command. A disappearing session is recorded as `stopped`,
not as success. Record completion after checking its output.

Use `tick --max-concurrent 2 --session tmux` to reconcile sessions and dispatch
ready work. Read [workspace isolation](workspace-isolation.md) before using git
worktrees, and [the changelog](../CHANGELOG.md) before opening a 0.1 database.
