# Session managers

A session manager starts, stops, checks, and describes how to attach to a worker session. The runtime depends on a protocol so tests and future adapters can use the same task store.

## Fake session manager

`FakeSessionManager` is deterministic and safe for tests, examples, and dry runs. It records live session ids in memory, or in a small JSON sidecar file when the CLI uses `--session fake`.

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 start docs-quickstart --session fake
```

Fake sessions do not execute task commands. They let you verify lifecycle behavior without starting external processes.

## Tmux session manager

`TmuxSessionManager` starts detached tmux sessions and is the recommended built-in adapter for Linux, macOS, and WSL.

Default naming:

```text
agent-runtime-<task-id>
```

Example:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 start docs-quickstart --session tmux
tmux attach-session -t agent-runtime-docs-quickstart
```

The adapter starts the configured shell command in the prepared workspace. If a
session with the exact name already exists, launch fails and preserves the
previous task status. Inspect that session before restarting; an old session is
never silently assigned to a new launch. Targets use tmux's exact-name syntax
(`=agent-runtime-<task-id>`) to avoid matching a similarly named worker.

A process exiting closes its session. That does not establish success: `sync`
records `stopped` for a missing session. Record `done` explicitly after checking
the worker's output, or have the worker call `done` as its final operation.
Completion is persisted before the session is stopped.

## Platform notes

- Tests and the quickstart do not require tmux.
- Real detached sessions require `tmux` on `PATH`.
- Linux, macOS, and WSL are the primary tmux targets.
- The protocol can support future adapters such as subprocess, systemd, Docker, or terminal-specific managers without changing the SQLite schema.

## Operational cautions

- Store only non-secret notes and payloads; session metadata is durable.
- Choose task ids that are safe as local session names.
- Use `sync` or `tick` to detect sessions that disappeared outside the runtime.
