# Lifecycle and events

Every important state change appends an event: registration, start, heartbeat, stop, sync stop, stale detection, and completion. Events are ordered by SQLite autoincrement ids and carry JSON payloads suitable for dashboards or log export.

Heartbeats indicate worker liveness. `sync` checks running tasks for missing sessions and stale heartbeats. Missing sessions move tasks to `stopped`; stale heartbeats are reported with a stable reason code.
