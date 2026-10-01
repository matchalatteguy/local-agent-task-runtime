# Local Agent Task Runtime

[![CI](https://github.com/matchalatteguy/local-agent-task-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/matchalatteguy/local-agent-task-runtime/actions/workflows/ci.yml)

Coordinate local workers with a durable SQLite task record, an append-only event
log, contained workspaces, and detached tmux sessions. Inspect a task after your
supervisor exits, reconcile a lost session, and leave a completion note that the
next operator can read.

**This project manages the lifecycle of tasks you register.** Its sibling
[Agent Backlog Runner](https://github.com/matchalatteguy/agent-backlog-runner)
creates tasks from a template catalog and runs short commands synchronously.
Choose this runtime when workers need independent sessions, heartbeat tracking,
or separate workspaces. Neither project is a distributed workflow engine.

## Run a real example

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From a fresh checkout:

```bash
uv sync --locked
uv run python -m local_agent_runtime.demo --output .agent-runtime/demo
```

The example launches a **real Python subprocess**, reads a three-row inventory
CSV, and writes an inventory summary. The supervisor records the lifecycle and
reopens SQLite before reporting the result. Expected output:

```json
{
  "counts": {"done": 1},
  "events": ["registered", "start_claimed", "started", "heartbeat", "done"],
  "summary": {"inventory_value": "82.49", "items": 3, "total_units": 18}
}
```

Whitespace in the printed JSON differs. Inspect the output at
`.agent-runtime/demo/workspaces/inventory/summary.json`. The SQLite record lives
at `.agent-runtime/demo/runtime.sqlite3`. Use a new `--output` path for another
run; the demo refuses to overwrite an existing directory.

```bash
uv run agent-runtime --db .agent-runtime/demo/runtime.sqlite3 list --json
uv run agent-runtime --db .agent-runtime/demo/runtime.sqlite3 events inventory --json
```

The demo adapter stays inside one supervisor process. It shows actual execution
without requiring tmux; it does not provide detached process recovery.

## Start a detached worker

Install `tmux` for Linux, macOS, or WSL. This runnable example writes a file in its
workspace and leaves the session open for inspection:

```bash
uv run agent-runtime --db .agent-runtime/worker.sqlite3 --workspace-root .agent-runtime/workspaces register \
  --id hello --role docs --workspace hello \
  --command "printf 'worker finished\\n' > result.txt; sleep 600"

uv run agent-runtime --db .agent-runtime/worker.sqlite3 --workspace-root .agent-runtime/workspaces start hello --session tmux
uv run agent-runtime --db .agent-runtime/worker.sqlite3 heartbeat hello
cat .agent-runtime/workspaces/hello/result.txt
uv run agent-runtime --db .agent-runtime/worker.sqlite3 done hello --session tmux --notes "result.txt written and checked."
```

The file contains `worker finished`. `done` persists the note and stops the
session. To watch a live worker, copy `session_id` from the `start` JSON result
into `tmux attach-session -t =SESSION_ID`. Each attempt receives a unique name
such as `agent-runtime-hello-<launch-token>`.
Commands passed to tmux are shell commands: use trusted commands.

A session disappearing does **not** establish success. `sync` moves a missing
session to `stopped`; the supervisor or worker must explicitly record `done` or
`failed` after checking its result. Heartbeats are explicit too.

## Lifecycle and concurrency

```text
ready -> starting -> running -> done
                       |-----> blocked / stopped / failed
```

- Task and capacity reservations are atomic SQLite transactions. Two local
  dispatchers cannot claim the same task or exceed their shared concurrency cap
  when they use the same cap. Direct `start` is an explicit manual override of
  dispatch capacity.
- `starting` reserves capacity while a workspace and session are prepared. Failed
  launches restore the prior status; interrupted launches remain inspectable and
  become `stopped` after the stale threshold.
- `sync` preserves terminal states recorded while reconciliation is in progress.
  A fast worker's completion cannot be overwritten by the launch finishing.
  Launch-token checks prevent an old attempt from overwriting or stopping a
  replacement after an operator stops and restarts the task.
- Relative and absolute workspace paths must remain under the configured root,
  including when a path passes through a symlink. Directory containment is path
  validation, not an execution sandbox.

Use one tick in a manager loop:

```bash
uv run agent-runtime --db .agent-runtime/worker.sqlite3 --workspace-root .agent-runtime/workspaces tick --max-concurrent 3 --session tmux
```

Choose unique task ids for workers. Each launch has its own session name. If a
crash leaves an unrecorded session behind, inspect it before restarting the task.
The adapter refuses to silently reuse an explicitly requested existing session.

## CLI and Python API

| Operation | Commands |
| --- | --- |
| Create tasks | `register`, JSON `import` |
| Operate workers | `start`, `dispatch`, `tick`, `heartbeat`, `sync`, `stop`, `done` |
| Inspect state | `list`, `summary`, `events`, `doctor`, `export` |

Inspection supports `--json`; mutations emit JSON. `--db` and `--workspace-root`
precede the command. Environment defaults are `LOCAL_AGENT_RUNTIME_DB`,
`LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT`, and `LOCAL_AGENT_RUNTIME_SESSION`; explicit
flags override them. `--session fake` records simulated sessions and executes no
commands.

```python
from local_agent_runtime import AgentTaskRuntime, FakeSessionManager

runtime = AgentTaskRuntime.local(
    ".agent-runtime/example.sqlite3", FakeSessionManager(), ".agent-runtime/workspaces"
)
runtime.register_task("docs", "docs", "python write_docs.py", "docs")
runtime.start_task("docs")  # simulated session in this example
runtime.mark_done("docs", notes="Reviewed the proposed documentation.")
print(runtime.store.get_task("docs").to_dict())
```

Replace the adapter with `TmuxSessionManager` for detached workers.
`GitWorktreeWorkspaceManager` is available through the library when code-editing
workers need separate checkouts.

## Verification and boundaries

```bash
uv run pytest
uv run ruff check .
uv build
```

CI tests Python 3.11–3.14, exercises a real tmux worker, and runs the example from
an installed wheel outside the checkout. See [CHANGELOG.md](CHANGELOG.md) before
upgrading a 0.1 database: 0.2 introduces schema version 2 and the `starting` state.

This is an alpha library for one machine. It provides no exactly-once execution,
automatic retries, exit-code collection for arbitrary tmux commands, multi-host
leases, secret storage, or process sandbox. A crash between external session
creation and SQLite recording can require operator reconciliation. Commands,
notes, and event payloads are stored verbatim; protect the database accordingly.

[Quickstart](docs/quickstart.md) · [Sessions](docs/session-managers.md) ·
[Workspaces](docs/workspace-isolation.md) · [Lifecycle](docs/lifecycle-and-events.md) ·
[Operations](docs/operations-recipes.md)
