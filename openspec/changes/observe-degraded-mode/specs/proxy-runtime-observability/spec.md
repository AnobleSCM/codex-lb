## ADDED Requirements

### Requirement: /health surfaces upstream degradation without failing liveness

`GET /health` MUST return `status = "ok"` whenever the process is alive, so a
degraded upstream never evicts the process. Alongside `status`, the response
MUST carry the current degradation `level` and `reason` and the last-known
`available_accounts` count (accounts the balancer last considered that were
present and not deactivated/paused). These fields MUST be read from in-memory
runtime state without an additional database read on the `/health` path.

#### Scenario: Healthy pool reports normal
- **GIVEN** the balancer is not degraded
- **WHEN** a client calls `GET /health`
- **THEN** the response has `status = "ok"` and `degradation.level = "normal"`
- **AND** `degradation.reason` is null

#### Scenario: Degraded pool is visible but liveness stays ok
- **GIVEN** the balancer has set degraded mode with a reason
- **WHEN** a client calls `GET /health`
- **THEN** the response still has `status = "ok"`
- **AND** `degradation.level = "degraded"` with the reason surfaced
- **AND** `available_accounts` reflects the accounts present at the last selection

### Requirement: Degradation transitions emit a single edge event

The degradation manager MUST emit its operator-facing transition log only on the
normal↔degraded edge — a WARNING when entering degraded mode and an INFO when
returning to normal — even though `set_degraded` is invoked on every failed
selection. Repeated `set_degraded` calls while already degraded MUST NOT emit a
new transition WARNING.

#### Scenario: Repeated set_degraded logs one enter event
- **GIVEN** the manager is in the normal state
- **WHEN** `set_degraded` is called multiple times in succession
- **THEN** exactly one `DEGRADATION_TRANSITION normal->degraded` WARNING is emitted

#### Scenario: Recovery logs one exit event
- **GIVEN** the manager is in the degraded state
- **WHEN** `set_normal` is called
- **THEN** exactly one `DEGRADATION_TRANSITION` recovery event is emitted at INFO
