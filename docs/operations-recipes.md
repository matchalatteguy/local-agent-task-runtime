# Operations recipes

## One-shot tick

```bash
uv run agent-runtime tick --db .agent-runtime/runtime.sqlite3 --max-concurrent 3 --json
```

Run this from cron, a shell loop, or a supervising agent. It reconciles running tasks, dispatches ready tasks up to the cap, and prints a JSON summary.

## Inspect current state

```bash
uv run agent-runtime summary --db .agent-runtime/runtime.sqlite3 --json
uv run agent-runtime list --db .agent-runtime/runtime.sqlite3 --status running --json
```

## Record a handoff

```bash
uv run agent-runtime done --db .agent-runtime/runtime.sqlite3 docs-quickstart --notes "Updated quickstart and examples."
```
