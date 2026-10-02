# Concepts

A task is one registered command and workspace, identified by an operator-chosen
id. A task row records its current status, role, command, workspace, launch token,
adapter identity, session name, notes and lifecycle timestamps. Events record
ordered state changes. Process attempts preserve separate logs and results for
every launch, including failed attempts before a retry.

| State | Meaning |
| --- | --- |
| ready | Eligible for dispatch |
| starting | Claimed; workspace/adapter setup is in progress |
| running | Owned by a worker session or process supervisor |
| stopped | Cancelled or a generic session disappeared |
| blocked | Operator input needed, including unresolved lost process work |
| done | Exit 0 for process tasks; explicit completion for tmux/fake |
| failed | Nonzero exit/deadline/spawn failure, or explicit failure |

The package handles one machine and a local SQLite file. Claims and capacity
reservations include starting tasks. Dispatchers sharing a database must use the
same concurrency cap; direct start is an explicit override. Workspaces may be
separate directories or library-created Git worktrees, but neither is a process
sandbox. There is no dependency graph or automatic task generation.

Use `process` for detached scripts and automatic results, `tmux` for interactive
shell sessions with manual completion, and `fake` to simulate lifecycle calls.
The sibling Agent Backlog Runner generates queue entries from templates and
executes commands synchronously. Read [the lifecycle reference](lifecycle-and-events.md)
and [the process guide](background-python.md) for exact behavior.
