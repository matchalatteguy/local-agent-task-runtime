# Run Python scripts in the background with logs and exit codes

Use a process session when a script should keep running after its launching CLI
exits and you need a durable result later. Linux supports Python 3.11–3.14;
macOS requires a Python 3.14 build exposing `waitid` and `WNOWAIT`. Run
`agent-runtime doctor` and check `process.available` before launching.

## Use the worker's own environment

The runtime does not install worker dependencies or activate a virtual
environment. Supply an absolute executable and a script path valid from its
workspace. This template assumes you already have a script and its environment:

```bash
agent-runtime --db jobs.sqlite3 --workspace-root /path/to/project register \
  --id report --role data --workspace . \
  --command '/path/to/project/.venv/bin/python -u /path/to/project/report.py'
agent-runtime --db jobs.sqlite3 --workspace-root /path/to/project start report --session process --timeout 1800
```

The task runs in the registered workspace, with the launcher's environment and
closed stdin. Use `-u` so Python output reaches the log promptly. File artifacts
belong in the workspace; they are not automatically uploaded or interpreted.
The runtime records exit 0 as done and other exits as failed. Your script must
raise or return a nonzero exit code when its work fails.

Commands use POSIX quoting and direct execution. `$HOME`, `~`, wildcards, pipes,
redirects and `&&` are not expanded. If your task needs a shell, explicitly use
`sh -c '...'` and treat that command as trusted code.

## Inspect from a fresh terminal

```bash
agent-runtime --db jobs.sqlite3 show report
agent-runtime --db jobs.sqlite3 logs report --stream stderr
agent-runtime --db jobs.sqlite3 wait report --timeout 30
agent-runtime --db jobs.sqlite3 runs report
```

`show` includes the current row and latest attempt. `runs` includes every launch
token, command argument vector, workspace, timestamps, exit code, reason and
log paths. Logs retain the first 8 MiB per stream by default. The counters
`stdout_discarded` / `stderr_discarded` tell you whether output was truncated;
choose a different cap with `start --log-limit BYTES` before launching. `logs`
shows the tail of retained content, up to 64 KiB, decoding invalid UTF-8 with
replacement. Raw files remain byte-for-byte for the retained portion.

`wait --timeout 30` limits this inspection call. The worker's deadline comes from
`start --timeout 1800` and remains active after the launcher exits. A deadline
failure has `reason: timed_out`; a script failure has `reason: exited` and its
actual nonzero `exit_code`. Exit codes after cancellation/timeout may be negative
POSIX signal numbers.

## Cancel or retry

```bash
agent-runtime --db jobs.sqlite3 stop report --status stopped --notes 'Cancelled by operator'
agent-runtime --db jobs.sqlite3 wait report
agent-runtime --db jobs.sqlite3 retry report
agent-runtime --db jobs.sqlite3 --workspace-root /path/to/project start report --session process
```

Cancellation is asynchronous. Wait until the result becomes final before
restarting. The runner sends TERM to its owned process group, waits 0.5 seconds,
then sends KILL. The same group cleanup occurs when the main command finishes,
so a successful script cannot leave ordinary background children running.
Children that deliberately start their own session/group fall outside this
cleanup guarantee.

If the supervisor is lost, the runtime blocks a restart to avoid duplicate orphan
work. Follow [the lost-supervisor procedure](operations-recipes.md#lost-supervisor).
Keep the database, WAL files and sibling `.runs` directory together on one local
filesystem. Do not move the store, remove its interpreter, or upgrade its package
while a process runner is active.
