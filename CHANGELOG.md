# Changelog

## 0.3.0

- Add a detached POSIX process adapter with automatic exit-code completion,
  per-attempt stdout/stderr logs, heartbeat and inspection after launcher exit.
- Retain the first 8 MiB per output stream by default; continue draining excess
  output and persist discarded byte counts. Allow configurable byte caps.
- Add generation-owned cancellation and deadlines with process-group cleanup.
  Keep the direct child unreaped until signalling, avoiding PID reuse. Support
  Linux Python 3.11–3.14 and macOS Python 3.14 with waitid/WNOWAIT. Unsupported
  builds fail explicitly. Native Windows process sessions are unsupported.
- Detect a lost supervisor through an exclusive owner lock. Record blocked lost
  work and require explicit inspection notes before requeueing; never signal a
  stored PID. Preserve tmux/fake APIs and manual completion semantics.
- Add show/runs/logs/wait/recover/retry commands, a real isolated test/build/verify
  showcase, and macOS process fault tests plus installed-wheel smoke checks.

### Upgrading from 0.1 / 0.2

Stop active older supervisors and keep a database backup before upgrading.
Opening schema 1 or 2 migrates atomically to schema 3, adds nullable
`session_kind` (and `launch_token` when missing), and creates the process-attempt
metadata table. Existing task fields and events are preserved; old rows without
adapter identity use the configured adapter during inspection. Future schema
versions are rejected before initialization writes. Older package versions
reject schema 3; downgrade requires the backup.

Task JSON adds `session_kind`; `WorkerSpec` adds an optional launch token used by
the process adapter. Tmux remains the default. Process completion comes from the
command's exit code; explicit `done` is rejected for those tasks. Cancellation is
asynchronous, so wait for cleanup before retrying. Retry records a new event and
preserves earlier attempts; it does not roll back files or external effects.


## 0.2.0

- Reserve tasks and concurrency slots atomically before launching a worker. The
  new `starting` state distinguishes a launch in progress from a live session.
- Give each attempt a launch token and a unique session identity. An old launch
  cannot overwrite or stop a replacement after a stop/restart, including while
  the replacement is still `starting`.
- Preserve completion recorded by a fast worker; persist `done` before stopping
  a session so a worker can finish from inside its own tmux session.
- Recover abandoned launches with `sync` after the configured stale threshold.
- Reject relative workspace paths that escape through a symlink. Use exact tmux
  targets and refuse to silently reuse a session belonging to an earlier launch.
- Add an executable inventory example, wheel smoke checks, and CI.

### Upgrading from 0.1

Opening a version 1 database upgrades its `PRAGMA user_version` to `2` in a
transaction, adds a nullable `launch_token` column, and preserves the existing
task fields and event log. Initial version 2 stores created without this column
also receive it atomically. Version 2 records may contain `starting`; an old 0.1
runtime therefore refuses to open the upgraded store. Stop older supervisors
before upgrading, and keep a copy of the database if you need to downgrade.

The event log now includes `start_claimed` before `started`, and `start_failed`
when a launch raises an exception. Consumers should allow additional event
kinds. Task JSON now includes `launch_token`; custom session adapters must honor
the unique requested `WorkerSpec.session_name`. Databases from a future
unsupported version are rejected before schema
initialization writes occur.
