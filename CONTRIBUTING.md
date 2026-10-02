# Contributing

Thanks for considering a contribution.

## Development setup

This project uses Python, `uv`, `pytest`, and `ruff`.

```bash
uv sync --locked --python 3.14
uv run --no-sync ruff check .
uv run --no-sync pytest
```

Process tests require POSIX waitid/WNOWAIT. Use Python 3.14 on macOS; unsupported
builds skip those tests while retaining fake/tmux coverage. CI exercises Linux
3.11–3.14 and real macOS 3.14 process behavior.

## Pull requests

Before opening a pull request, please:

- keep changes focused and easy to review;
- add or update tests for behavior changes;
- update docs or examples when public behavior changes;
- run the local checks above;
- avoid committing local caches, generated build outputs, secrets, credentials, or machine-specific paths.

## Project scope

Keep the package generic and reusable. Avoid domain-specific private context, organization-specific assumptions, and hardcoded local paths.
