from __future__ import annotations

from fastapi import APIRouter, Depends, Security

from app.core.auth.dependencies import set_dashboard_error_format, validate_fleet_api_key
from app.dependencies import AccountsContext, get_accounts_context
from app.modules.fleet.mappers import build_fleet_account_summaries
from app.modules.fleet.schemas import FleetSummaryResponse

router = APIRouter(
    prefix="/api/fleet",
    tags=["fleet"],
    # Auth is the codex-lb API key ONLY (never the dashboard session).
    # ``validate_fleet_api_key`` always enforces a valid key, independent of
    # the ``api_key_auth_enabled`` proxy toggle, so this route cannot be
    # reached unauthenticated even when proxy key-auth is disabled.
    dependencies=[Security(validate_fleet_api_key), Depends(set_dashboard_error_format)],
)


@router.get("/summary", response_model=FleetSummaryResponse)
async def get_fleet_summary(
    context: AccountsContext = Depends(get_accounts_context),
) -> FleetSummaryResponse:
    """Read-only, minimal per-account capacity summary for fleet consumers.

    Reuses the same ``AccountsService.list_accounts()`` the dashboard uses, so
    no new data is collected; this only re-projects state codex-lb already
    computes. No state mutation, no upstream calls, no token refresh.
    """
    accounts = await context.service.list_accounts()
    return FleetSummaryResponse(accounts=build_fleet_account_summaries(accounts))
