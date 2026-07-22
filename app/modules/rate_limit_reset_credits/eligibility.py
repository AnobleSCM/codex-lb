from __future__ import annotations

from app.core.clients.rate_limit_reset_credits import RateLimitResetCreditsSnapshot
from app.db.models import AccountStatus
from app.modules.rate_limit_reset_credits.store import RateLimitResetCreditsStore

_INELIGIBLE_STATUS_VALUES = frozenset(
    {AccountStatus.PAUSED.value, AccountStatus.REAUTH_REQUIRED.value, AccountStatus.DEACTIVATED.value}
)


def reset_credits_account_is_eligible(
    *,
    status: str | AccountStatus,
    chatgpt_account_id: str | None,
) -> bool:
    """Return whether an account can have a current reset-credit snapshot."""

    status_value = status.value if isinstance(status, AccountStatus) else status
    return status_value not in _INELIGIBLE_STATUS_VALUES and bool(chatgpt_account_id)


def eligible_reset_credits_snapshot(
    store: RateLimitResetCreditsStore,
    *,
    account_id: str,
    status: str | AccountStatus,
    chatgpt_account_id: str | None,
) -> RateLimitResetCreditsSnapshot | None:
    """Read a cached snapshot only when the scheduler considers the account eligible."""

    if not reset_credits_account_is_eligible(
        status=status,
        chatgpt_account_id=chatgpt_account_id,
    ):
        return None
    return store.get(account_id)
