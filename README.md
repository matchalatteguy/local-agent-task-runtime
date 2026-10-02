# Local Agent Task Runtime

[![CI](https://github.com/matchalatteguy/local-agent-task-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/matchalatteguy/local-agent-task-runtime/actions/workflows/ci.yml)

Run Python scripts in the background with logs and exit codes. Close the launching
terminal, reopen the CLI, and inspect the result in SQLite. The process adapter
collects completion automatically, retains bounded stdout/stderr logs, and
cancels an owned process group on request or deadline. No service or runtime
dependency is required.

**Platform:** Linux Python 3.11–3.14; macOS Python **3.14** for process sessions.
Your interpreter must expose POSIX `waitid`/`WNOWAIT`; `doctor` reports whether it
does. Tmux and fake adapters remain available on Python 3.11+. Native Windows
process sessions are unsupported.

## Try it

Install the tagged source with [uv](https://docs.astral.sh/uv/) (no PyPI release):

```bash
uv tool install --python 3.14 'git+https://github.com/matchalatteguy/local-agent-task-runtime.git@v0.3.0'
agent-runtime doctor
agent-runtime demo --output runtime-demo
```

The packaged showcase creates three separate workspaces, runs a deliberately
failing unit test, fixes the sample code, retries it, builds a zip artifact, and
verifies that artifact in another worker. Each launcher exits before the result
is inspected. No tmux or test dependency is required. Expected JSON, ignoring
whitespace:

```json
{
  "artifact": "workspaces/build/dist/report.zip",
  "checks_attempt_exit_codes": [1, 0],
  "counts": {"done": 3},
  "restored_states": {"build": "done", "checks": "done", "verify": "done"},
  "verified_summary": {"inventory_value": "82.49", "items": 3, "total_units": 18}
}
```

Inspect the preserved failure and successful retry:

```bash
agent-runtime --db runtime-demo/runtime.sqlite3 runs checks
agent-runtime --db runtime-demo/runtime.sqlite3 logs checks --stream stderr
agent-runtime --db runtime-demo/runtime.sqlite3 show verify
```

`runs` lists both attempts, their exit codes, truncation counts and log paths.
Use `logs --attempt LAUNCH_TOKEN --stream stderr` for the first failure. The zip
is `runtime-demo/workspaces/build/dist/report.zip`. A repeat demo requires a fresh
output directory; it refuses to overwrite existing work.

From a checkout, use `uv sync --locked --python 3.14`, then prefix the commands
above with `uv run --no-sync`.

## Run your own script

Commands for process sessions are split into an argument vector using POSIX
quoting. There is no implicit shell expansion. This complete example runs in a
contained workspace and writes an artifact:

```bash
agent-runtime --db jobs.sqlite3 --workspace-root jobs register \
  --id hello --role report --workspace hello \
  --command "python3 -u -c 'import time; from pathlib import Path; time.sleep(2); Path(\"result.txt\").write_text(\"finished\\n\"); print(\"artifact ready\")'"
agent-runtime --db jobs.sqlite3 --workspace-root jobs start hello --session process --timeout 60
agent-runtime --db jobs.sqlite3 wait hello --timeout 10
agent-runtime --db jobs.sqlite3 logs hello
cat jobs/hello/result.txt
```

`wait` returns `done`, `logs` prints `artifact ready`, and the artifact contains
`finished`. `start` returns after the detached supervisor acknowledges ownership;
it may already return a terminal state for a fast command. The launching CLI can
exit immediately. `wait` exit codes are **0** for done, **1** for any other final
state, **124** if inspection times out (the worker continues), and **2** for an
invalid request.

Use the absolute Python executable from your worker's virtual environment for a
script with dependencies. See [the script guide](docs/background-python.md).

For a task that is still running, substitute its id for `TASK_ID`:

```bash
agent-runtime --db jobs.sqlite3 stop TASK_ID --status stopped --notes "No longer needed"
agent-runtime --db jobs.sqlite3 wait TASK_ID
agent-runtime --db jobs.sqlite3 retry TASK_ID
agent-runtime --db jobs.sqlite3 --workspace-root jobs start TASK_ID --session process
```

Cancellation is a durable request; the task becomes final after group cleanup.
Retry is explicit and preserves previous attempts. `done` is for tmux/fake tasks;
process completion comes from the exit code.

## Guarantees and limits

- SQLite transactions claim tasks and reserve concurrency slots. Dispatchers
  sharing a database must use the same cap; direct `start` bypasses that cap.
- Each attempt has a unique token, owner lock, logs and result. An old runner
  cannot record completion for a newer attempt. CLI commands never signal PIDs
  read from the database.
- The supervisor keeps its direct child unreaped until process-group cleanup,
  preventing PID reuse during signalling. Timeout and cancellation send TERM,
  allow 0.5 seconds, then KILL. Normal command exit also cleans up group members.
  Descendants that deliberately create another session/group escape this scope.
- Stdout and stderr each retain their **first 8 MiB** by default; excess output
  is drained and counted. `start --log-limit BYTES` changes that limit. Logs are
  raw bytes; `logs` decodes UTF-8 with replacement and reads at most the final
  64 KiB of retained data. Python workers should use `-u` for timely output.
- SIGTERM/SIGINT of the supervisor request cleanup. SIGKILL, reboot, or a control
  permission failure can leave orphan work. `wait`/`sync` record a missing runner
  as **blocked**. Restart remains blocked until explicit acknowledgment after
  inspection. [Recovery instructions](docs/operations-recipes.md#lost-supervisor).

This is a single-machine alpha tool, with no automatic retries, dependency DAG,
remote execution, exactly-once execution or security sandbox. Store the database
and its `.runs` directory together on a local filesystem; keep the interpreter
and package used by active runners installed. Workspace containment validates
paths, but workers can access files your account can access.

## Other adapters and APIs

| Adapter | Execution | Completion | Primary use |
| --- | --- | --- | --- |
| `process` | Detached owned subprocess group | Automatic exit code, logs, heartbeat | Scripts, tests, builds |
| `tmux` | Detached shell session | Explicit `done` / `stop`; lost session means stopped | Interactive workers |
| `fake` | No command execution | Explicit lifecycle calls | Integration tests / dry runs |

Tmux is the default for backward compatibility. Recorded adapter identities route
later inspection and cancellation; you do not need to repeat `--session process`.
Legacy rows without an identity use the selected adapter. See [session details](docs/session-managers.md).

The sibling [Agent Backlog Runner](https://github.com/matchalatteguy/agent-backlog-runner)
replenishes a queue from templates and executes short commands synchronously.
This runtime operates registered tasks whose workers outlive the launching call.

```python
from pathlib import Path
from local_agent_runtime import RuntimeConfig

runtime = RuntimeConfig(
    db_path=Path("jobs.sqlite3"), workspace_root=Path("jobs"), session="process",
    process_timeout_seconds=60, process_log_limit_bytes=1024 * 1024,
).create_runtime()
runtime.register_task("report", "data", "/absolute/path/.venv/bin/python -u report.py", "report")
runtime.start_task("report")
result = runtime.wait_task("report", timeout_seconds=30)
print(result.status, result.notes)
```

[CLI quickstart](docs/quickstart.md) · [Lifecycle](docs/lifecycle-and-events.md) ·
[Workspace isolation](docs/workspace-isolation.md) · [Operations](docs/operations-recipes.md)

## Development and upgrades

```bash
uv sync --locked --python 3.14
uv run --no-sync ruff check .
uv run --no-sync pytest
uv build --no-sources
```

CI tests Linux Python 3.11–3.14, real tmux sessions, macOS Python 3.14 process
ownership and crash recovery, and the showcase from an installed wheel outside
the checkout. See [CHANGELOG.md](CHANGELOG.md): v0.3 upgrades schema 1/2 databases
transactionally to schema 3, preserving task fields and events. Stop old runners
and back up the database before upgrading; older versions reject schema 3.
