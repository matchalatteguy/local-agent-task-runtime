# Contributing

Thanks for considering a contribution.

## Development setup

This project uses Python, `uv`, `pytest`, and `ruff`.

```bash
uv sync --group dev
uv run --group dev ruff check .
uv run --group dev pytest
```

## Pull requests

Before opening a pull request, please:

- keep changes focused and easy to review;
- add or update tests for behavior changes;
- update docs or examples when public behavior changes;
- run the local checks above;
- avoid committing local caches, generated build outputs, secrets, credentials, or machine-specific paths.

## Project scope

Keep the package generic and reusable. Avoid domain-specific private context, organization-specific assumptions, and hardcoded local paths.
