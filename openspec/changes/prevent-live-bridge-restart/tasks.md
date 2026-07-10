- [x] Add red/green coverage for the local deploy helper refusing active in-flight work before build/recreate.
- [x] Add red/green coverage for the deploy helper starting drain and waiting before force-recreate on an idle proxy.
- [x] Add red/green coverage that single-container Compose templates pin a stable HTTP bridge instance id.
- [x] Add red/green coverage that unreadable or malformed drain status fails closed before build/drain/recreate.
- [x] Add red/green coverage that failed or timed-out post-drain deploy attempts stop-drain cleanup.
- [x] Add red/green coverage that `/internal/drain/stop` reaches the real middleware+endpoint while draining.
- [x] Implement the local deploy idle gate and drain wait.
- [x] Implement stop-drain cleanup for failed or timed-out post-drain deploys.
- [x] Allow `/internal/drain/stop` through drain and in-flight middleware while draining.
- [x] Pin the stable bridge instance id in the repo Compose templates.
- [x] Run focused tests, lint/type checks, and the full pytest suite.
- [x] Validate the OpenSpec change with the one-shot official CLI.

## AGE-3084 follow-up

- [x] Add red/green coverage that drain status/start/stop calls execute inside
  the live container and do not use the host-published port.
- [x] Route all drain calls, including failed-deploy cleanup, through the live
  container's loopback network namespace.
- [x] Add red/green coverage that a candidate image missing any running-image
  Alembic revision fails before retag or recreate.
- [x] Replace the retired SQLite live-head query with a fail-closed
  running-image-to-candidate-image migration inventory comparison.
- [x] Run focused tests, shell syntax validation, lint/type checks, and the full
  pytest suite.
- [x] Validate the updated OpenSpec change.
