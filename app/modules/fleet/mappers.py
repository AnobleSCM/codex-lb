from __future__ import annotations

from app.modules.accounts.schemas import AccountSummary
from app.modules.fleet.schemas import (
    FleetAccountSummary,
    FleetRateLimitResetCreditsSummary,
    FleetWindowSummary,
)
from app.modules.rate_limit_reset_credits.eligibility import eligible_reset_credits_snapshot
from app.modules.rate_limit_reset_credits.store import (
    RateLimitResetCreditsStore,
    get_rate_limit_reset_credits_store,
)


def fleet_account_summary_from_account(
    account: AccountSummary,
    *,
    include_usage: bool = True,
    persisted_status_by_account_id: dict[str, str] | None = None,
    reset_credits_store: RateLimitResetCreditsStore | None = None,
) -> FleetAccountSummary:
    """Project a dashboard account into the minimal fleet payload."""

    usage = account.usage
    reset_credits_snapshot = None
    if include_usage:
        reset_credits_snapshot = eligible_reset_credits_snapshot(
            reset_credits_store or get_rate_limit_reset_credits_store(),
            account_id=account.account_id,
            status=account.status,
            chatgpt_account_id=account.chatgpt_account_id,
        )
    if include_usage:
        status = account.status
    elif persisted_status_by_account_id is None:
        status = "unknown"
    else:
        status = persisted_status_by_account_id.get(account.account_id, "unknown")
    return FleetAccountSummary(
        account_id=account.account_id,
        display_name=account.display_name,
        email=account.email,
        status=status,
        plan_type=account.plan_type,
        primary=FleetWindowSummary(
            remaining_percent=usage.primary_remaining_percent if include_usage and usage is not None else None,
            reset_at=account.reset_at_primary if include_usage else None,
            window_minutes=account.window_minutes_primary if include_usage else None,
        ),
        secondary=FleetWindowSummary(
            remaining_percent=usage.secondary_remaining_percent if include_usage and usage is not None else None,
            reset_at=account.reset_at_secondary if include_usage else None,
            window_minutes=account.window_minutes_secondary if include_usage else None,
        ),
        last_refresh_at=account.last_refresh_at if include_usage else None,
        rate_limit_reset_credits=(
            FleetRateLimitResetCreditsSummary(
                available_count=reset_credits_snapshot.available_count,
                nearest_expires_at=reset_credits_snapshot.nearest_expires_at,
            )
            if reset_credits_snapshot is not None
            else None
        ),
    )


def build_fleet_account_summaries(
    accounts: list[AccountSummary],
    *,
    include_usage: bool = True,
    persisted_status_by_account_id: dict[str, str] | None = None,
    reset_credits_store: RateLimitResetCreditsStore | None = None,
) -> list[FleetAccountSummary]:
    store = reset_credits_store or get_rate_limit_reset_credits_store()
    return [
        fleet_account_summary_from_account(
            account,
            include_usage=include_usage,
            persisted_status_by_account_id=persisted_status_by_account_id,
            reset_credits_store=store,
        )
        for account in accounts
    ]
