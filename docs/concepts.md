# Concepts

Local Agent Task Runtime has two durable primitives:

- `TaskRecord`: the current state of one local unit of work.
- `TaskEvent`: an append-only record of how that state changed.

A single SQLite database stores both. Supervisors can poll JSON commands such as `summary`, `list`, and `events` without reading process logs.

## Task records

A task record includes:

- `id`: stable operator-chosen identifier, such as `docs-quickstart`.
- `role`: a lightweight category such as `docs`, `tests`, `maintenance`, or `data-cleanup`.
- `command`: the local command a session manager should run.
- `workspace`: a relative or contained path for task files.
- `status`: one of the runtime statuses below.
- `session_id`: the adapter-specific session name while running.
- timestamps: created, updated, started, completed, and heartbeat times.
- `notes`: optional handoff text from stop or completion commands.

## Status model

- `ready`: eligible for dispatch.
- `running`: owned by a worker session.
- `stopped`: was running but the session disappeared or was stopped.
- `blocked`: paused until a human or manager provides input.
- `done`: completed with optional handoff notes.
- `failed`: ended unsuccessfully.

`done` and `failed` are terminal for normal dispatch. `blocked` and `stopped` are non-running states that can be inspected, updated, or started again by an operator.

## Events

Events explain how a task reached its current state. Typical event kinds include:

- `registered`
- `started`
- `heartbeat`
- `stopped`
- `sync_stopped`
- `stale`
- `done`

Events are ordered by SQLite autoincrement ids and include JSON payloads. This makes them easy to display in dashboards or include in handoff reports.

## Local-first operating model

The runtime is designed for one local machine and one SQLite file. It does not attempt multi-host locking or distributed scheduling. A human, cron job, shell loop, or supervising agent can call `tick` repeatedly to reconcile state and start ready tasks up to a concurrency cap.
