## Verification report

Verified at `2026-07-22T15:23:33Z`:

- `uv run pytest --log-disable=app.main -q` across the fleet summary integration,
  fleet mapper, account mapper, reset-credit API, and reset-credit scheduler
  slices — 97 passed.
- `uvx ruff check` on all changed Python files — passed.
- `uvx ruff format --check` on all changed Python files — passed.
- `uv run ty check` — passed.
- `uv run python scripts/check_proxy_architecture.py` — passed.
- `git diff --check` — passed.

`openspec validate expose-reset-credits-in-fleet-summary --strict` was attempted
and could not run because the `openspec` executable is not installed on this
host (`command not found`). The artifacts were therefore checked directly
against the repository's existing spec-driven change layout. Remote CI remains
the authority for the repository-wide test matrix.
