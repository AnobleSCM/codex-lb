from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DegradationInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: str = "normal"
    reason: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    # Upstream degradation state, surfaced so watchdogs/daemons can pre-check
    # before claiming work. ``status`` stays "ok" (liveness) even when degraded.
    # Always present and non-null — the handler always supplies it — so generated
    # clients can rely on the field rather than treating it as optional.
    degradation: DegradationInfo = Field(default_factory=DegradationInfo)
    # Accounts the balancer last considered (present, not deactivated/paused);
    # None until the first selection cycle populates it.
    available_accounts: int | None = None


class BridgeRingInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ring_fingerprint: str | None = None
    ring_size: int = 0
    instance_id: str | None = None
    is_member: bool = False
    error: str | None = None


class HealthCheckResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    checks: dict[str, str] | None = None
    bridge_ring: BridgeRingInfo | None = None
