## 1. Reconcile migration graph

- [x] 1.1 Restore the upstream migration files needed for the live applied
  revision and its descendant schema path.
- [x] 1.2 Rebase the dashboard session TTL migration onto the restored upstream
  head so Alembic has exactly one head.
- [x] 1.3 Sync ORM metadata with the restored schema.

## 2. Verification

- [x] 2.1 Run the migration policy/drift checks.
- [x] 2.2 Run focused migration tests.
- [x] 2.3 Run formatting/lint/type checks for touched Python files.
- [ ] 2.4 Open a PR and wait for the normal GitHub gate.
- [ ] 2.5 After merge, run the live deploy script and confirm `/health=200`
  with no `MigrationBootstrapError`.
- [ ] 2.6 Run OpenSpec validation. Blocked locally: `uv run openspec
  validate --specs` fails because `openspec` is not installed in this
  environment.
