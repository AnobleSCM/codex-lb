from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)


class DegradationLevel(Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class DegradationManager:
    def __init__(self) -> None:
        self._level = DegradationLevel.NORMAL
        self._reason: str | None = None
        # Accounts the balancer last considered (present, not deactivated/paused).
        # Recorded at each selection cycle so /health can report it without a DB
        # read. ``None`` until the first selection populates it.
        self._available_accounts: int | None = None

    def set_degraded(self, reason: str | None = None, *, available_accounts: int | None = None) -> None:
        if available_accounts is not None:
            self._available_accounts = available_accounts
        was_normal = self._level == DegradationLevel.NORMAL
        self._level = DegradationLevel.DEGRADED
        self._reason = reason
        if was_normal:
            # ``set_degraded`` is called on *every* failed selection (130+ times
            # during the 2026-07-05 incident). Emit the operator-facing WARNING
            # only on the normal -> degraded edge so the transition is not buried
            # in per-request noise; repeats stay at debug.
            logger.warning(
                "DEGRADATION_TRANSITION normal->degraded reason=%s available_accounts=%s",
                reason or "unknown reason",
                self._available_accounts,
            )
        else:
            logger.debug("Still degraded: %s", reason or "unknown reason")

    def set_normal(self, *, available_accounts: int | None = None) -> None:
        if available_accounts is not None:
            self._available_accounts = available_accounts
        previous = self._level
        self._level = DegradationLevel.NORMAL
        self._reason = None
        if previous != DegradationLevel.NORMAL:
            logger.info(
                "DEGRADATION_TRANSITION %s->normal available_accounts=%s",
                previous.value,
                self._available_accounts,
            )

    def is_degraded(self) -> bool:
        return self._level != DegradationLevel.NORMAL

    def get_status(self) -> dict[str, str | None]:
        return {
            "level": self._level.value,
            "reason": self._reason,
        }

    def get_available_accounts(self) -> int | None:
        return self._available_accounts


_manager = DegradationManager()


def set_degraded(reason: str | None = None, *, available_accounts: int | None = None) -> None:
    _manager.set_degraded(reason, available_accounts=available_accounts)


def set_normal(*, available_accounts: int | None = None) -> None:
    _manager.set_normal(available_accounts=available_accounts)


def is_degraded() -> bool:
    return _manager.is_degraded()


def get_status() -> dict[str, str | None]:
    return _manager.get_status()


def get_available_accounts() -> int | None:
    return _manager.get_available_accounts()
