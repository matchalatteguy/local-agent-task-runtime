# Session managers

A session manager starts, stops, checks, and describes how to attach to a worker session. The built-in fake manager is deterministic for tests. The tmux manager launches detached tmux sessions and is recommended on Linux, macOS, and WSL.

The interface keeps the runtime testable and leaves room for future adapters without changing task storage.
