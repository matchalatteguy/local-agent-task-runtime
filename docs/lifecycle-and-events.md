# Lifecycle and events

Every important state change appends an event. The current task row is optimized for quick inspection; the event stream is optimized for auditability and handoff.

## Common lifecycle

```text
ready -> running -> done
ready -> running -> blocked
ready -> running -> stopped
ready -> running -> failed
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

Typical event kinds are `registered`, `started`, `heartbeat`, `stopped`, `sync_stopped`, `stale`, and `done`.

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

Missing sessions are moved to `stopped` with a `sync_stopped` event. Stale heartbeat findings append a `stale` event so an operator can decide whether to wait, inspect, or stop the task.

## Handoff notes

Use notes to summarize human-readable outcomes:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 done docs-quickstart --notes "Updated README and examples."
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 stop docs-quickstart --status blocked --notes "Needs sample input file."
```

Notes are durable. Do not store secrets, credentials, or private operational details in notes.
