# Repo maintenance example

This offline example describes a tiny synthetic backlog for a documentation and test cleanup sprint. It has no external services, credentials, network calls, or publishing steps.

## Tasks

`tasks.yaml` contains three illustrative tasks:

- `docs-quickstart`: improve first-run documentation.
- `tests-fixtures`: refresh local test fixtures.
- `style-cleanup`: format notes or generated text.

The current CLI does not import YAML directly. Register the tasks manually or write a small importer around the Python API.

## Manual registration

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 init

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id docs-quickstart \
  --role docs \
  --command "python scripts/write_docs.py" \
  --workspace docs-quickstart

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id tests-fixtures \
  --role tests \
  --command "python scripts/refresh_fixtures.py" \
  --workspace tests-fixtures

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  register \
  --id style-cleanup \
  --role maintenance \
  --command "python scripts/format_notes.py" \
  --workspace style-cleanup
```

## Dry-run dispatch

Use the fake adapter to verify runtime behavior without executing the commands:

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root .agent-runtime/workspaces \
  dispatch --max-concurrent 2 --session fake

uv run agent-runtime --db .agent-runtime/runtime.sqlite3 summary --json
```

Switch to `--session tmux` only after replacing the synthetic commands with real local scripts.
