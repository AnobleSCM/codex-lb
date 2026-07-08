## Alembic Revisions

The deploy-blocking live volume revision is
`20260630_020000_merge_warmup_threshold_and_main_heads`.

This reconciliation restores the upstream migration path through
`20260701_000000_add_weekly_pace_smoothing_minutes`, then makes the fork-local
dashboard session TTL migration
`20260705_000000_harden_dashboard_session_ttl` the single head.

The deploy script must still verify that the image contains the live volume
revision before retagging `codex-lb:active`.

## Operational Notes

- The previous deploy attempt stopped before `codex-lb:active` retag/recreate.
- The next deploy should build from the merged fork `main` commit, verify the
  live revision file exists in the new image, recreate the live container, and
  confirm `/health` plus clean logs.
- The account probe requested by AGE-2961 remains post-deploy verification only;
  this change does not re-authenticate or mutate account credentials.
