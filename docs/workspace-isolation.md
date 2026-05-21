# Workspace isolation

Workspace isolation keeps parallel local tasks from overwriting one another. Each task has a `workspace` value, and the runtime prepares that workspace before starting a session.

## Directory workspaces

The CLI uses `DirectoryWorkspaceManager` with `--workspace-root`.

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id style-cleanup \
  --role maintenance \
  --command "python scripts/format_notes.py" \
  --workspace style-cleanup
```

When the task starts, the runtime creates:

```text
.agent-runtime/workspaces/style-cleanup/
```

Use directory workspaces for scripts, generated scratch files, read-only checks, and tasks that do not need separate git checkouts.

## Path containment

The runtime rejects relative paths containing `..`. Absolute paths are accepted only when they stay inside the configured workspace root. This prevents accidentally placing task workspaces outside the intended local sandbox.

Good:

```text
docs-quickstart
maintenance/style-cleanup
```

Rejected:

```text
../outside-root
```

## Git worktrees from Python

For parallel code-editing tasks, use `GitWorktreeWorkspaceManager` from Python so each task can get an isolated checkout.

```python
from pathlib import Path

from local_agent_runtime.runtime import AgentTaskRuntime
from local_agent_runtime.sessions import TmuxSessionManager
from local_agent_runtime.workspaces import GitWorktreeWorkspaceManager
from local_agent_runtime.store import SqliteRuntimeStore

runtime = AgentTaskRuntime(
    store=SqliteRuntimeStore(".agent-runtime/runtime.sqlite3"),
    sessions=TmuxSessionManager(),
    workspaces=GitWorktreeWorkspaceManager(
        root=Path(".agent-runtime/worktrees"),
        repository=Path("."),
        base_ref="HEAD",
    ),
)
```

The default branch name for a worktree is `task/<task-id>` unless a task has an explicit branch.

## Cleanup

This project creates local runtime files but does not delete workspaces automatically. Review generated files before removing them, especially when a worker wrote artifacts or handoff notes refer to workspace paths.
