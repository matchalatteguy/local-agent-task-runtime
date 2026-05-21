# Concepts

A runtime database contains task records and append-only task events. A task record is the current state; events explain how it reached that state.

Core statuses:

- `ready`: eligible for dispatch.
- `running`: owned by a worker session.
- `stopped`: was running but the session disappeared or was stopped.
- `blocked`: paused until a human or manager provides input.
- `done`: completed with optional handoff notes.
- `failed`: ended unsuccessfully.

The runtime is designed for one local machine and one SQLite file. Supervisors can poll JSON commands such as `summary`, `list`, and `events`.
