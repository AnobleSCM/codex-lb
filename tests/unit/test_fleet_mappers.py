from __future__ import annotations

import pytest

from app.core.clients.rate_limit_reset_credits import RateLimitResetCreditsSnapshot
from app.modules.accounts.schemas import AccountSummary, AccountUsage
from app.modules.fleet.mappers import fleet_account_summary_from_account
from app.modules.rate_limit_reset_credits.store import RateLimitResetCreditsStore


def _account(
    *,
    status: str = "active",
    chatgpt_account_id: str | None = "chatgpt-account-1",
) -> AccountSummary:
    return AccountSummary(
        account_id="account-1",
        chatgpt_account_id=chatgpt_account_id,
        email="account@example.com",
        display_name="Account 1",
        plan_type="plus",
        status=status,
        usage=AccountUsage(primary_remaining_percent=90.0, secondary_remaining_percent=80.0),
    )


@pytest.mark.asyncio
async def test_fleet_mapper_preserves_confirmed_zero_reset_credits() -> None:
    store = RateLimitResetCreditsStore()
    await store.set("account-1", RateLimitResetCreditsSnapshot(available_count=0, credits=[]))

    summary = fleet_account_summary_from_account(_account(), reset_credits_store=store)

    assert summary.rate_limit_reset_credits is not None
    assert summary.rate_limit_reset_credits.available_count == 0


def test_fleet_mapper_marks_missing_reset_credit_snapshot_unavailable() -> None:
    summary = fleet_account_summary_from_account(
        _account(),
        reset_credits_store=RateLimitResetCreditsStore(),
    )

    assert summary.rate_limit_reset_credits is None


@pytest.mark.parametrize(
    ("status", "chatgpt_account_id"),
    [
        ("paused", "chatgpt-account-1"),
        ("reauth_required", "chatgpt-account-1"),
        ("deactivated", "chatgpt-account-1"),
        ("active", None),
    ],
)
@pytest.mark.asyncio
async def test_fleet_mapper_hides_stale_snapshot_for_ineligible_account(
    status: str,
    chatgpt_account_id: str | None,
) -> None:
    store = RateLimitResetCreditsStore()
    await store.set("account-1", RateLimitResetCreditsSnapshot(available_count=2, credits=[]))

    summary = fleet_account_summary_from_account(
        _account(status=status, chatgpt_account_id=chatgpt_account_id),
        reset_credits_store=store,
    )

    assert summary.rate_limit_reset_credits is None


@pytest.mark.asyncio
async def test_fleet_mapper_hides_reset_credits_when_usage_is_suppressed() -> None:
    store = RateLimitResetCreditsStore()
    await store.set("account-1", RateLimitResetCreditsSnapshot(available_count=2, credits=[]))

    summary = fleet_account_summary_from_account(
        _account(),
        include_usage=False,
        reset_credits_store=store,
    )

    assert summary.rate_limit_reset_credits is None
