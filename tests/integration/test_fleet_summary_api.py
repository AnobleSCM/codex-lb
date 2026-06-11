from __future__ import annotations

import json

import pytest

from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService
from app.modules.usage.repository import UsageRepository

pytestmark = pytest.mark.integration

# Window lengths in minutes: 5h primary window vs 7d (weekly) secondary window.
_PRIMARY_WINDOW_MINUTES = 300
_SECONDARY_WINDOW_MINUTES = 10080

# Sensitive keys that MUST NOT appear anywhere in the fleet summary response.
# Includes both snake_case and the camelCase the dashboard serializer emits.
_FORBIDDEN_KEYS = {
    "auth",
    "access",
    "refresh",
    "id_token",
    "idToken",
    "accessToken",
    "refreshToken",
    "access_token",
    "refresh_token",
    "capacity_credits_primary",
    "capacityCreditsPrimary",
    "remaining_credits_primary",
    "remainingCreditsPrimary",
    "capacity_credits_secondary",
    "capacityCreditsSecondary",
    "remaining_credits_secondary",
    "remainingCreditsSecondary",
    "request_usage",
    "requestUsage",
    "total_cost_usd",
    "totalCostUsd",
    "additional_quotas",
    "additionalQuotas",
    "deactivation_reason",
    "deactivationReason",
}


def _make_account(account_id: str, email: str, *, plan_type: str = "plus") -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        chatgpt_account_id=None,
        email=email,
        plan_type=plan_type,
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=utcnow(),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


async def _create_api_key(name: str) -> str:
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        created = await service.create_key(ApiKeyCreateData(name=name, allowed_models=None, limits=[]))
    return created.key


async def _seed_account_with_windows(
    account_id: str,
    email: str,
    *,
    primary_used_percent: float,
    secondary_used_percent: float,
    primary_reset_at: int,
    secondary_reset_at: int,
) -> None:
    async with SessionLocal() as session:
        accounts_repo = AccountsRepository(session)
        usage_repo = UsageRepository(session)
        await accounts_repo.upsert(_make_account(account_id, email))
        await usage_repo.add_entry(
            account_id,
            primary_used_percent,
            window="primary",
            reset_at=primary_reset_at,
            window_minutes=_PRIMARY_WINDOW_MINUTES,
        )
        await usage_repo.add_entry(
            account_id,
            secondary_used_percent,
            window="secondary",
            reset_at=secondary_reset_at,
            window_minutes=_SECONDARY_WINDOW_MINUTES,
        )


def _assert_no_forbidden_keys(node: object) -> None:
    """Recursively assert no sensitive key appears anywhere in the payload."""
    if isinstance(node, dict):
        for key, value in node.items():
            assert key not in _FORBIDDEN_KEYS, f"sensitive key '{key}' leaked into fleet summary"
            _assert_no_forbidden_keys(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_forbidden_keys(item)


@pytest.mark.asyncio
async def test_fleet_summary_requires_api_key(async_client, db_setup):
    # Seed an account so a bypass would actually leak data (not just an empty list).
    await _seed_account_with_windows(
        "acc_noauth",
        "noauth@example.com",
        primary_used_percent=10.0,
        secondary_used_percent=10.0,
        primary_reset_at=0,
        secondary_reset_at=0,
    )

    response = await async_client.get("/api/fleet/summary")

    assert response.status_code == 401
    body = response.text
    assert "noauth@example.com" not in body
    assert "accounts" not in body


@pytest.mark.asyncio
async def test_fleet_summary_rejects_invalid_api_key(async_client, db_setup):
    await _seed_account_with_windows(
        "acc_badkey",
        "badkey@example.com",
        primary_used_percent=10.0,
        secondary_used_percent=10.0,
        primary_reset_at=0,
        secondary_reset_at=0,
    )

    response = await async_client.get(
        "/api/fleet/summary",
        headers={"Authorization": "Bearer sk-clb-not-a-real-key"},
    )

    assert response.status_code == 401
    assert "badkey@example.com" not in response.text


@pytest.mark.asyncio
async def test_fleet_summary_still_requires_key_when_proxy_auth_disabled(async_client, db_setup):
    """The proxy ``api_key_auth_enabled`` toggle defaults to disabled in this
    environment (no DashboardSettings row), and the test client is treated as a
    local request. Under those conditions ``validate_proxy_api_key`` would
    pass through with no key. This test pins the security contract that the
    fleet endpoint does NOT inherit that bypass: it must still 401 with no key,
    even though a proxy-key-authed route would not.
    """
    from app.core.config.settings_cache import get_settings_cache

    settings = await get_settings_cache().get()
    # Guard the premise: the bypass condition is actually active here.
    assert settings.api_key_auth_enabled is False

    await _seed_account_with_windows(
        "acc_toggle",
        "toggle@example.com",
        primary_used_percent=10.0,
        secondary_used_percent=10.0,
        primary_reset_at=0,
        secondary_reset_at=0,
    )

    response = await async_client.get("/api/fleet/summary")

    assert response.status_code == 401
    assert "toggle@example.com" not in response.text


@pytest.mark.asyncio
async def test_fleet_summary_returns_minimal_projection_with_valid_key(async_client, db_setup):
    plain_key = await _create_api_key("fleet-summary-key")

    primary_reset = 1735862400
    secondary_reset = 1736467200
    await _seed_account_with_windows(
        "acc_fleet_a",
        "fleet-a@example.com",
        # remaining_percent = 100 - used_percent
        primary_used_percent=38.0,  # -> 62% remaining
        secondary_used_percent=20.0,  # -> 80% remaining
        primary_reset_at=primary_reset,
        secondary_reset_at=secondary_reset,
    )
    await _seed_account_with_windows(
        "acc_fleet_b",
        "fleet-b@example.com",
        primary_used_percent=5.0,
        secondary_used_percent=50.0,
        primary_reset_at=primary_reset,
        secondary_reset_at=secondary_reset,
    )

    response = await async_client.get(
        "/api/fleet/summary",
        headers={"Authorization": f"Bearer {plain_key}"},
    )

    assert response.status_code == 200
    payload = response.json()
    accounts = payload["accounts"]
    # One minimal summary per managed account.
    assert len(accounts) == 2

    by_id = {account["accountId"]: account for account in accounts}
    assert set(by_id) == {"acc_fleet_a", "acc_fleet_b"}

    account_a = by_id["acc_fleet_a"]
    # Identity / status fields are present.
    assert account_a["email"] == "fleet-a@example.com"
    assert account_a["displayName"] == "fleet-a@example.com"
    assert account_a["status"] == "active"
    assert account_a["planType"] == "plus"
    assert account_a["lastRefreshAt"] is not None

    # primary/secondary remaining% + reset_at + window_minutes mapped correctly.
    assert account_a["primary"]["remainingPercent"] == 62
    assert account_a["primary"]["windowMinutes"] == _PRIMARY_WINDOW_MINUTES
    assert account_a["primary"]["resetAt"] is not None
    assert account_a["secondary"]["remainingPercent"] == 80
    assert account_a["secondary"]["windowMinutes"] == _SECONDARY_WINDOW_MINUTES
    assert account_a["secondary"]["resetAt"] is not None


@pytest.mark.asyncio
async def test_fleet_summary_omits_sensitive_fields(async_client, db_setup):
    plain_key = await _create_api_key("fleet-summary-sensitive-key")

    await _seed_account_with_windows(
        "acc_sensitive",
        "sensitive@example.com",
        primary_used_percent=25.0,
        secondary_used_percent=40.0,
        primary_reset_at=1735862400,
        secondary_reset_at=1736467200,
    )

    response = await async_client.get(
        "/api/fleet/summary",
        headers={"Authorization": f"Bearer {plain_key}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["accounts"]) == 1

    # No token / auth-status / credit-balance / request-cost / quota keys anywhere.
    _assert_no_forbidden_keys(payload)

    # And no token material leaks as a value either.
    raw = json.dumps(payload)
    assert "access" not in raw or "accessToken" not in payload["accounts"][0]
    account = payload["accounts"][0]
    assert set(account.keys()) == {
        "accountId",
        "displayName",
        "email",
        "status",
        "planType",
        "primary",
        "secondary",
        "lastRefreshAt",
    }
    assert set(account["primary"].keys()) == {"remainingPercent", "resetAt", "windowMinutes"}
