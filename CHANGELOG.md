# Changelog

## 0.2.0

- Reserve tasks and concurrency slots atomically before launching a worker. The
  new `starting` state distinguishes a launch in progress from a live session.
- Preserve completion recorded by a fast worker; persist `done` before stopping
  a session so a worker can finish from inside its own tmux session.
- Recover abandoned launches with `sync` after the configured stale threshold.
- Reject relative workspace paths that escape through a symlink. Use exact tmux
  targets and refuse to silently reuse a session belonging to an earlier launch.
- Add an executable inventory example, wheel smoke checks, and CI.

### Upgrading from 0.1

Opening a version 1 database upgrades its `PRAGMA user_version` to `2` in a
transaction and preserves the existing task rows and event log. There are no
table-layout changes. Version 2 records may contain `starting`; an old 0.1
runtime therefore refuses to open the upgraded store. Stop older supervisors
before upgrading, and keep a copy of the database if you need to downgrade.

The event log now includes `start_claimed` before `started`, and `start_failed`
when a launch raises an exception. Consumers should allow additional event
kinds. Databases from a future unsupported version are rejected before schema
initialization writes occur.
