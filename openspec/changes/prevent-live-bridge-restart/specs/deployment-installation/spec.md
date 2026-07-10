# deployment-installation Specification Delta

## ADDED Requirements

### Requirement: Local container recreation requires bridge idle drain

The local deploy helper MUST prove the live proxy has no active in-flight HTTP
work before it builds or recreates the live single-container deployment. The
helper MUST read the loopback-only `/internal/drain/status` endpoint from inside
the live container's network namespace and abort without building, retagging,
or force-recreating when that endpoint reports active in-flight work, an already
active drain, or malformed/unreadable status. After image build and alembic
parity checks pass, the helper MUST start drain from inside the live container,
wait until in-flight work is zero, and only then recreate the container. If the
deploy exits unsuccessfully after drain start and before a successful completion,
the helper MUST attempt to stop the live drain from inside the live container
before it exits so the old container does not remain stuck in draining mode.
The loopback-only stop-drain endpoint MUST remain reachable while the process is
draining and MUST NOT count as in-flight proxy work.

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
- **AND** `/internal/drain/stop` is accepted even while the live proxy is
  already draining
- **AND** the old live proxy is not left in draining mode when it remains
  available to receive the stop request

#### Scenario: Unreadable drain status blocks local deploy

- **WHEN** `/internal/drain/status` cannot be read or parsed
- **THEN** the local deploy helper exits non-zero
- **AND** it does not build, start drain, retag, or force-recreate the container

#### Scenario: Host port cannot bypass the loopback-only drain boundary

- **WHEN** Docker port publishing makes a host request appear to originate from
  the bridge gateway rather than loopback
- **THEN** the local deploy helper performs drain status, start, and stop
  requests from inside the live container
- **AND** it does not call the loopback-only drain endpoints through the
  host-published port

### Requirement: Local deploy rejects migration inventory rollback

The local deploy helper MUST compare the Alembic revision files in the running
container with those in the candidate image before retagging or recreating. The
candidate image MUST contain every revision available in the running image. An
unreadable or empty running-image inventory, an unreadable candidate-image
inventory, or any missing revision MUST fail the deploy before retag or
recreate. The check MUST NOT depend on a retired SQLite database file when the
live deployment uses PostgreSQL.

#### Scenario: Candidate image omits a deployed migration revision

- **WHEN** the running image contains an Alembic revision that the candidate
  image does not contain
- **THEN** the local deploy helper exits non-zero with the missing revision
- **AND** it does not retag or force-recreate the container
- **AND** the failure warns that deployment could trigger
  `MigrationBootstrapError`

### Requirement: Single-container Compose uses a stable bridge instance id

Single-container Docker Compose templates MUST configure
`CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_INSTANCE_ID` with a stable logical value
instead of relying on the container hostname default.

#### Scenario: Compose recreation preserves bridge instance identity

- **WHEN** a single-container Compose deployment is recreated
- **THEN** its configured HTTP Responses bridge instance id remains stable
- **AND** durable bridge owner rows are not tied to the transient container id
