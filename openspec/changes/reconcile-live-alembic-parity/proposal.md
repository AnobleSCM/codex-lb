## Why

The local live `codex-lb-data` volume is stamped at Alembic revision
`20260630_020000_merge_warmup_threshold_and_main_heads`, but the fork `main`
image at `9005277b` does not contain that revision file. The deploy runbook
correctly refused to retag/recreate the live container because a missing applied
revision can crash-loop startup with `MigrationBootstrapError`.

The missing revision is part of the upstream migration spine. The fork has since
merged local runtime fixes on top of an older migration base, including
`20260705_000000_harden_dashboard_session_ttl`, so the branch must reconcile
the upstream spine before the merged runtime fixes can be safely deployed.

## What Changes

- Restore the upstream Alembic migration spine from
  `20260426_000000_add_dashboard_relative_availability_settings` through
  `20260701_000000_add_weekly_pace_smoothing_minutes`.
- Rebase `20260705_000000_harden_dashboard_session_ttl` onto
  `20260701_000000_add_weekly_pace_smoothing_minutes`, preserving a single
  Alembic head.
- Sync ORM metadata and migration tests with the restored schema so the
  migration policy and drift guards keep proving the same graph CI will deploy.

## Impact

- The deploy image can recognize the live applied revision
  `20260630_020000_merge_warmup_threshold_and_main_heads` and upgrade forward
  to the single head `20260705_000000_harden_dashboard_session_ttl`.
- This does not delete pool accounts, mutate credentials, or re-auth any
  account.
- The live deploy still goes through the normal PR gate and the existing
  runbook parity guard before `codex-lb:active` is retagged.
