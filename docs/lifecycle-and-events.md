# Lifecycle and events

Every important state change appends an event. The current task row is optimized for quick inspection; the event stream is optimized for auditability and handoff.

## Common lifecycle

```text
ready -> starting -> running -> done
                       |-----> blocked / stopped / failed
```

A stopped or blocked task can be started again by an operator. Done and failed tasks are treated as terminal for normal dispatch.

## Event stream

Inspect events for one task:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 events docs-quickstart --json
```

Events are ordered by SQLite ids and include:

- `task_id`
- `kind`
- `payload`
- `created_at`

Typical event kinds are `registered`, `start_claimed`, `started`, `start_failed`,
`heartbeat`, `stopped`, `sync_stopped`, `stale`, and `done`. A launch claims the
task in SQLite before starting external work. A failed launch returns to the
previous status. A worker that finishes during launch keeps its final state.

## Heartbeats

Heartbeats indicate worker liveness:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 heartbeat docs-quickstart
```

Long-running workers can call this periodically. A supervising loop can then use `summary`, `sync`, or `tick` to identify stale work.

## Stale and missing sessions

`sync` checks running tasks against the selected session adapter.

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 sync
```

Stable reason codes include:

- `session_missing`: a running task has no live session or no recorded session id.
- `heartbeat_stale`: the session exists, but the last heartbeat is older than the configured threshold.
- `launch_stale`: a `starting` task is older than the configured threshold, so
  its launching supervisor may have exited unexpectedly.

Missing sessions and stale launches are moved to `stopped` with a `sync_stopped`
event. This is a finding about liveness, not success or failure. Stale heartbeat
findings append a `stale` event for operator review. Completion recorded during
reconciliation is preserved. If a crash created a tmux session before its id was
recorded, inspect that session before attempting a restart.

## Handoff notes

Use notes to summarize human-readable outcomes:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 done docs-quickstart --notes "Updated README and examples."
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 stop docs-quickstart --status blocked --notes "Needs sample input file."
```

Notes are durable. Do not store secrets, credentials, or private operational details in notes.
