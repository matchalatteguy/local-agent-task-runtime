# Quickstart

Process sessions require Linux Python 3.11+ or macOS Python 3.14 with
`os.waitid`/`WNOWAIT`. Native Windows is unsupported. From a checkout:

```bash
uv sync --locked --python 3.14
uv run --no-sync agent-runtime doctor
uv run --no-sync agent-runtime demo --output .agent-runtime/demo
```

Expect three done tasks, test attempt exit codes `[1, 0]`, a verified inventory
value of `82.49`, and a zip at `.agent-runtime/demo/workspaces/build/dist/report.zip`.
All commands run through detached process supervisors. The failed attempt remains
in SQLite and its stderr log; a new CLI can inspect it after the launchers exit.
Use a fresh output directory for another demo.

```bash
uv run --no-sync agent-runtime --db .agent-runtime/demo/runtime.sqlite3 runs checks
uv run --no-sync agent-runtime --db .agent-runtime/demo/runtime.sqlite3 logs checks --stream stderr
uv run --no-sync agent-runtime --db .agent-runtime/demo/runtime.sqlite3 events checks --json
```

## Command reference

Global `--db` and `--workspace-root` flags precede the command. Mutations and
`show`, `runs`, `wait`, `doctor` emit JSON. `list`, `events`, `summary`, `logs`
support `--json`. `start`/`dispatch`/`tick` select the adapter and accept process
`--timeout SECONDS` (default 3600) and `--log-limit BYTES` (default 8388608).

| Need | Command |
| --- | --- |
| Register / load tasks | `register`, `import backlog.json` |
| Launch one / fill available capacity | `start ID --session process`, `dispatch --max-concurrent 2 --session process` |
| Inspect one / attempt history / logs | `show ID`, `runs ID`, `logs ID --stream stderr --attempt TOKEN` |
| Wait for a result | `wait ID --timeout 30` |
| Request cancellation | `stop ID --status stopped --notes "cancelled"`, then `wait ID` |
| Retry a final task | `retry ID`, then `start ID --session process` |
| Reconcile / reconcile and dispatch | `sync`, `tick --max-concurrent 2 --session process` |
| Inspect all state / export | `summary --json`, `list --json`, `export --output snapshot.json` |
| Inspect a lost process runner | `recover ID`; see [recovery](operations-recipes.md#lost-supervisor) |

`wait` exits 0 for done, 1 for another final state, 124 for a waiting deadline,
and 2 for an invalid request. Waiting never cancels a worker. A ready task is
returned immediately with exit 1; `wait` does not dispatch it.

Environment defaults are `LOCAL_AGENT_RUNTIME_DB`,
`LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT` and `LOCAL_AGENT_RUNTIME_SESSION`. Flags
win. Tmux remains the default; process adapters are recorded per launch.

## Simulate without executing commands

```bash
uv run --no-sync agent-runtime --db .agent-runtime/fake.sqlite3 register \
  --id practice --role docs --workspace practice --command "printf 'hello'"
uv run --no-sync agent-runtime --db .agent-runtime/fake.sqlite3 start practice --session fake
uv run --no-sync agent-runtime --db .agent-runtime/fake.sqlite3 done practice --notes "Lifecycle exercise complete."
```

The fake adapter executes nothing. For interactive tmux workers and their manual
completion semantics, read [session managers](session-managers.md). For actual
scripts with dependencies, use [the background Python guide](background-python.md).
