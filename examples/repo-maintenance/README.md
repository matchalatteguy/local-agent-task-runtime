# Repo maintenance example

This offline example describes a tiny synthetic backlog for a documentation and test cleanup sprint. It has no external services, credentials, network calls, or publishing steps.

## Tasks

`tasks.json` and `tasks.yaml` contain three runnable tasks:

- `docs-quickstart`: writes `quickstart-notes.md` in its task workspace.
- `tests-fixtures`: writes `fixtures.json` in its task workspace.
- `style-cleanup`: writes `formatted-notes.md` in its task workspace.

The CLI imports JSON directly. The YAML file is kept as a human-friendly fixture for
users who prefer writing their own importer around the Python API.

## Import the runnable backlog

From this example directory:

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 init

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root . \
  import tasks.json
```

That creates all three task records with commands that write visible output inside their
`workspaces/<task-id>/` directories.

## Manual registration

```bash
uv run agent-runtime --db .agent-runtime/runtime.sqlite3 init

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root . \
  register \
  --id docs-quickstart \
  --role docs \
  --command "python ../../scripts/write_docs.py" \
  --workspace workspaces/docs-quickstart

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root . \
  register \
  --id tests-fixtures \
  --role tests \
  --command "python ../../scripts/refresh_fixtures.py" \
  --workspace workspaces/tests-fixtures

uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root . \
  register \
  --id style-cleanup \
  --role maintenance \
  --command "python ../../scripts/format_notes.py" \
  --workspace workspaces/style-cleanup
```

## Dry-run dispatch

Use the fake adapter to verify runtime behavior without executing the commands:

```bash
uv run agent-runtime \
  --db .agent-runtime/runtime.sqlite3 \
  --workspace-root . \
  dispatch --max-concurrent 2 --session fake

uv run agent-runtime --db .agent-runtime/runtime.sqlite3 summary --json
```

To run one task for real after the fake exercise, use a separate database and the tmux adapter:

```bash
uv run agent-runtime \
  --db .agent-runtime/real.sqlite3 --workspace-root . import tasks.json

uv run agent-runtime \
  --db .agent-runtime/real.sqlite3 --workspace-root . \
  start docs-quickstart --session tmux
```

The command writes `workspaces/docs-quickstart/quickstart-notes.md`.

The short worker exits after writing the file. Verify that output, then record
completion explicitly:

```bash
cat workspaces/docs-quickstart/quickstart-notes.md
uv run agent-runtime --db .agent-runtime/real.sqlite3 done docs-quickstart --session tmux --notes "quickstart-notes.md verified."
```

A closed session alone does not establish a successful result.
