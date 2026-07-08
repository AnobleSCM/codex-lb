# deployment-installation Specification Delta

## Requirements

### Requirement: Local container recreation requires bridge idle drain

The local deploy helper MUST prove the live proxy has no active in-flight HTTP
work before it builds or recreates the live single-container deployment. The
helper MUST read the loopback-only `/internal/drain/status` endpoint and abort
without building, retagging, or force-recreating when that endpoint reports
active in-flight work, an already active drain, or malformed/unreadable status.
After image build and alembic parity checks pass, the helper MUST start drain,
wait until in-flight work is zero, and only then recreate the container. If the
deploy exits unsuccessfully after drain start and before a successful completion,
the helper MUST attempt to stop the live drain before it exits so the old
container does not remain stuck in draining mode.

#### Scenario: Active executor work blocks local deploy

- **WHEN** `/internal/drain/status` reports `in_flight > 0`
- **THEN** the local deploy helper exits non-zero
- **AND** it does not build, retag, or force-recreate the container

#### Scenario: Idle proxy is drained before force-recreate

- **WHEN** `/internal/drain/status` reports no in-flight work
- **AND** the image build and alembic parity checks pass
- **THEN** the local deploy helper calls `/internal/drain/start`
- **AND** waits for `/internal/drain/status` to report `in_flight = 0`
- **AND** only then runs the force-recreate command

#### Scenario: Failed post-drain deploy clears drain state

- **WHEN** the local deploy helper has started live drain
- **AND** the post-drain wait, retag, recreate, or verification step fails
- **THEN** the helper calls `/internal/drain/stop` before exiting
- **AND** the old live proxy is not left in draining mode when it remains
  available to receive the stop request

#### Scenario: Unreadable drain status blocks local deploy

- **WHEN** `/internal/drain/status` cannot be read or parsed
- **THEN** the local deploy helper exits non-zero
- **AND** it does not build, start drain, retag, or force-recreate the container

### Requirement: Single-container Compose uses a stable bridge instance id

Single-container Docker Compose templates MUST configure
`CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_INSTANCE_ID` with a stable logical value
instead of relying on the container hostname default.

#### Scenario: Compose recreation preserves bridge instance identity

- **WHEN** a single-container Compose deployment is recreated
- **THEN** its configured HTTP Responses bridge instance id remains stable
- **AND** durable bridge owner rows are not tied to the transient container id
