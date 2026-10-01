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

The runtime supplies a unique name for each launch, using the adapter's prefix:

```text
agent-runtime-<task-id>-<launch-token>
```

Example:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 start docs-quickstart --session tmux
```

Copy `session_id` from the command's JSON output into
`tmux attach-session -t =SESSION_ID` to attach. If you call the adapter directly,
an explicit `WorkerSpec.session_name` is used unchanged; without it, the adapter
defaults to `<prefix>-<task-id>`.

The adapter starts the configured shell command in the prepared workspace. If a
session with the exact name already exists, launch fails and preserves the
previous task status. Inspect that session before restarting; an old session is
never silently assigned to a new launch. Targets use tmux's exact-name syntax
(`=SESSION_ID`) to avoid matching a similarly named worker.
Tmux changes names containing periods or colons, so the adapter rejects those
characters before launch. Choose task ids without periods when using tmux.

A process exiting closes its session. That does not establish success: `sync`
records `stopped` for a missing session. Record `done` explicitly after checking
the worker's output, or have the worker call `done` as its final operation.
Completion is persisted before the session is stopped.

Custom adapters must honor the unique `WorkerSpec.session_name` supplied by the
runtime. Reusing a shared id across attempts defeats safe cleanup of an old
launch. The runtime checks its launch token before recording state changes, so
an old attempt cannot overwrite a replacement that is still `starting`.

## Platform notes

- Tests and the quickstart do not require tmux.
- Real detached sessions require `tmux` on `PATH`.
- Linux, macOS, and WSL are the primary tmux targets.
- The protocol can support future adapters such as subprocess, systemd, Docker, or terminal-specific managers without changing the SQLite schema.

## Operational cautions

- Store only non-secret notes and payloads; session metadata is durable.
- Choose task ids that are safe as local session names.
- Use `sync` or `tick` to detect sessions that disappeared outside the runtime.
