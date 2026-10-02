# Operations

The examples assume tasks already registered in `jobs.sqlite3`, with contained
workspaces under `jobs`. Global path flags precede the command.

## Dispatch a bounded batch

```bash
agent-runtime --db jobs.sqlite3 --workspace-root jobs tick --max-concurrent 3 --session process --timeout 900
agent-runtime --db jobs.sqlite3 summary --json
```

Tick reconciles first and dispatches ready tasks up to the shared cap. It returns
after launch acknowledgments; it does not wait for workers or generate new tasks.
A timer can call it again. All dispatchers should use the same cap. Direct `start`
bypasses dispatch capacity.

## Inspect a failure and retry

```bash
agent-runtime --db jobs.sqlite3 show report
agent-runtime --db jobs.sqlite3 runs report
agent-runtime --db jobs.sqlite3 logs report --stream stderr
agent-runtime --db jobs.sqlite3 retry report
agent-runtime --db jobs.sqlite3 --workspace-root jobs start report --session process --timeout 900
```

Fix the command's inputs or script before retrying. Artifacts are not rolled back
or cleared, and retries may repeat side effects. There are no automatic retries.

## Cancel a process group

```bash
agent-runtime --db jobs.sqlite3 stop report --status stopped --notes "Cancelled by operator"
agent-runtime --db jobs.sqlite3 wait report --timeout 10
```

The stop JSON can still say running: cancellation is persisted before cleanup.
Wait for the final result. TERM has a 0.5-second grace before KILL. The runner
signals its owned group, never a PID supplied through CLI inspection. Descendants
that detach into a new session/group escape this scope.

## Lost supervisor

A killed supervisor, reboot or control permission failure may leave work running
without a recoverable owner. `wait` and `sync` detect a missing owner lock, mark
the task blocked and record `runner_lost`. They never kill historical PIDs, which
may have been reused. Inspect `runs ID`, raw logs and workspace artifacts. For an
interrupted STARTING process attempt, use `recover ID` explicitly or wait for the
stale threshold used by sync.

```bash
agent-runtime --db jobs.sqlite3 recover report
agent-runtime --db jobs.sqlite3 runs report
```

Verify possible orphan work has ended using your normal process tools and the
command/workspace context; do not blindly signal a PID copied from SQLite. Resolve
or retain outputs as appropriate. Then explicitly acknowledge your inspection:

```bash
agent-runtime --db jobs.sqlite3 recover report --acknowledge-lost --notes "Inspected orphan work and outputs; no worker remains"
agent-runtime --db jobs.sqlite3 retry report
agent-runtime --db jobs.sqlite3 --workspace-root jobs start report --session process
```

The note is required. A live supervisor holding the lock rejects recovery; request
stop and wait instead. Acknowledgment records operator judgment; it is not proof
that orphan work was automatically cleaned up.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Process adapter unavailable | `doctor`; use Linux Python 3.11+ or macOS Python 3.14 with waitid/WNOWAIT |
| Import error in runner log | Keep the launch interpreter/package installed; install the wheel or use uv's synced environment |
| Script import fails | Register its own absolute virtual-environment Python executable |
| No recent output | Use Python `-u`; check stderr and byte truncation counters |
| Spawn error | Check executable, arguments and workspace permissions in `show` and runner log |
| Timed out | Worker deadline is `start --timeout`; `wait --timeout` only limits inspection |
| Unresolved process attempt | Wait/cancel the owner, or follow lost-supervisor inspection above |
| Workspace escapes root | Choose a contained path; symlink escapes are rejected |
| Tmux missing | Install tmux or select process/fake; tmux has explicit completion |

Keep database, SQLite WAL/SHM files and sibling `<db>.runs` directory together on
a local filesystem. Stop runners before moving/backing up/upgrading the store.
Commands, environment-derived output, notes and event payloads may be sensitive.
