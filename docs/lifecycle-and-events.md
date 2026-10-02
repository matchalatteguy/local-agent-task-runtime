# Lifecycle and events

SQLite stores the current task row and append-only events. Process attempts also
have durable command, logs, owner and result metadata accessible with `runs ID`.

```text
ready -> starting -> running -> done
                       |-----> blocked / stopped / failed
```

Claims reserve STARTING and dispatch capacity atomically. Every attempt gets a
launch token; state updates check ownership. Process runners own their own
STARTING-to-RUNNING and final transitions. Generic adapter launch failures restore
the previous state. A fast completion cannot be overwritten by a launcher.

Done and failed are terminal for dispatch. `retry ID` explicitly requeues a final
task and preserves previous attempts. Stopped/blocked tasks can also be started
directly once all previous process attempts are resolved. Unacknowledged lost
attempts prevent both retry and start.

## Completion and cancellation

Process exit 0 records done, nonzero records failed. Deadline or spawn failure
records failed with a stable attempt reason. The supervisor drains logs and
cleans up ordinary process-group children before recording the final result.
Cancellation writes a token-scoped request; the task remains running until the
runner finishes cleanup. A cancellation request accepted before exit publication
wins over normal exit completion. `wait` is an observation call and never cancels.

Tmux/fake tasks require explicit `done` or `stop`. A missing session becomes
stopped; the runtime does not infer success from its disappearance.

## Events and heartbeat

```bash
agent-runtime --db jobs.sqlite3 events report --json
```

Events have an ordered SQLite id, task id, kind, payload and UTC timestamp.
Consumers must allow additional kinds. Common events:

| Event | Meaning |
| --- | --- |
| `registered`, `start_claimed`, `started`, `start_failed` | Registration and attempt launch |
| `process_finished` | Token, actual exit code, reason and final process state |
| `cancel_requested` | Requested state and notes for one process attempt |
| `runner_lost`, `lost_acknowledged` | Lost owner and explicit operator recovery |
| `retried` | Explicit requeue from a final state |
| `done`, `stopped`, `sync_stopped` | Tmux/fake completion and reconciliation |
| `heartbeat`, `stale` | Explicit heartbeat and stale-session finding |

Process heartbeats update timestamps automatically, roughly once per second;
they do not add an event every second. A heartbeat establishes supervisor activity,
not that a script is making useful progress. Tmux/fake heartbeats are explicit.

## Reconciliation

`sync`/`tick` use recorded adapter identities. Reason codes are `session_missing`,
`heartbeat_stale`, `launch_stale`, and `process_runner_missing`.

Missing tmux/fake sessions and old interrupted generic launches become stopped.
A missing process owner becomes blocked with a lost attempt. Interrupted prepared
process launches become blocked after the stale threshold; explicit `recover`
can resolve them sooner. Heartbeat staleness appends an event for inspection,
without killing the worker. Reconciliation checks the launch token and preserves
terminal results recorded concurrently.

See [recovery](operations-recipes.md#lost-supervisor) before restarting lost work.
