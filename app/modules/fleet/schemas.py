from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.modules.shared.schemas import DashboardModel


class FleetWindowSummary(DashboardModel):
    """One usage window (primary or secondary) for a single account.

    A deliberately minimal capacity projection: how much headroom is left,
    when it resets, and the window length. No credit balances or request-cost
    detail are exposed.
    """

    remaining_percent: float | None = None
    reset_at: datetime | None = None
    window_minutes: int | None = None


class FleetAccountSummary(DashboardModel):
    """Minimal, non-sensitive per-account capacity summary for fleet consumers.

    Projects only the headroom/reset/status fields a fleet view needs from the
    dashboard's ``AccountSummary``. Excludes OAuth tokens, auth/token status,
    raw credit balances, request-cost detail, and additional-quota detail.
    """

    account_id: str
    display_name: str
    email: str
    status: str
    plan_type: str
    primary: FleetWindowSummary
    secondary: FleetWindowSummary
    last_refresh_at: datetime | None = None


class FleetSummaryResponse(DashboardModel):
    accounts: list[FleetAccountSummary] = Field(default_factory=list)
