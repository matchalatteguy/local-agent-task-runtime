# Workspace isolation

Relative workspace paths are resolved under a configured workspace root. Paths containing `..` are rejected. Absolute paths are accepted only when they stay inside the configured root.

Use plain directory workspaces for scripts or read-only tasks. Use git worktrees when multiple code-editing tasks need isolated checkouts from the same repository.
