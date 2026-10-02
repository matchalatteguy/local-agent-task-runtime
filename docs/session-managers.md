# Session managers

The runtime supplies each adapter with a `WorkerSpec` containing the command,
workspace, unique session name and launch token. Custom adapters must honor the
requested name to preserve isolation across attempts.

## Process sessions

`ProcessSessionManager` launches a detached Python supervisor. That supervisor
owns one direct child with a new POSIX session/process group. It persists an
attempt before executing work, holds an exclusive file lock, records automatic
heartbeats and exit results, and drains bounded stdout/stderr logs. A fresh CLI
routes operations from the recorded `session_kind` without needing another
`--session` flag.

Requires POSIX `waitid`/`WNOWAIT`: CI covers Linux Python 3.11–3.14 and macOS
Python 3.14. Unsupported interpreters fail with a diagnostic; there is no unsafe
PID-based fallback. Native Windows is unsupported. `doctor` checks API availability;
OS permission restrictions can still prevent supervision and cleanup.

```python
from pathlib import Path
from local_agent_runtime import ProcessSessionManager

sessions = ProcessSessionManager(Path("jobs.sqlite3"), timeout_seconds=300, log_limit_bytes=1048576)
```

Use through `AgentTaskRuntime` or `RuntimeConfig`: direct `start(task_id, spec)`
requires a matching SQLite STARTING claim and `spec.launch_token`. `stop(session_id)`
is a cancellation request, `exists` checks the owner lock, and `attach_command`
returns a `tail -f` command for the retained stdout/stderr files.

Completion is automatic. Exit 0 means done; nonzero, deadline and spawn failures
mean failed. Cancellation uses the requested stopped/blocked/failed state after
cleanup. `done` is rejected for process tasks. Retries are explicit and preserve
attempt history. See [process operations](operations-recipes.md).

The supervisor never reaps its child before group signalling, so the child PID
cannot be reused during cleanup. Darwin can report EPERM for a zombie-only group;
only an exact-group `/bin/ps` check showing no live members permits that condition.
A denial with live members is a cleanup failure. CLI recovery never sends signals
to stored PIDs; a missing supervisor requires orphan inspection and acknowledgment.

## Tmux sessions

`TmuxSessionManager` is for interactive workers on Linux, macOS and WSL with tmux
on `PATH`. It executes a **shell command**, unlike process direct execution.
Tmux remains the default for existing users.

```bash
agent-runtime --db jobs.sqlite3 --workspace-root jobs register \
  --id interactive --role docs --workspace interactive \
  --command "printf 'worker finished\\n' > result.txt; sleep 600"
agent-runtime --db jobs.sqlite3 --workspace-root jobs start interactive --session tmux
```

Copy `session_id` from JSON into `tmux attach-session -t =SESSION_ID`. Attempts
have names `agent-runtime-<task-id>-<launch-token>`. Explicit `WorkerSpec.session_name`
is used unchanged; direct adapter calls without it use `<prefix>-<task-id>`.
Existing exact names fail launch. Tmux targets use `=SESSION_ID` to avoid partial
matches. Tmux rewrites periods/colons, so choose task ids without those characters.

A disappearing tmux session does not establish success. `sync` records stopped
for missing sessions. Check outputs, then call `done ID --notes "checked"`, or
have the worker call it as its last operation. Completion is persisted before
stopping the session. Tmux heartbeat calls are explicit; no exit-code or log
collection is added to this adapter.

## Fake sessions

`FakeSessionManager` executes no commands. It tracks live names in memory, or in
`<db>.fake-sessions.json` for CLI use. Use it for simulated lifecycle calls and
integration tests. It does not demonstrate actual task execution.

## Common limits

Workspace containment is path validation, not a security sandbox. Commands and
logs can contain sensitive data; protect all runtime files. Legacy rows without
`session_kind` use the selected adapter when inspected. Keep one adapter policy
per legacy database until those rows are reconciled.
