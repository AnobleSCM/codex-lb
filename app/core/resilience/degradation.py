from __future__ import annotations

import logging
from enum import Enum
from typing import TypedDict

logger = logging.getLogger(__name__)


class DegradationLevel(Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class DegradationStatus(TypedDict):
    """Shape returned by :func:`get_status` — the /health degradation contract.

    ``level`` is always one of the :class:`DegradationLevel` values (never
    absent), so consumers may index it directly and fail loud on a contract
    break; ``reason`` is null in the normal state.
    """

    level: str
    reason: str | None


class DegradationManager:
    def __init__(self) -> None:
        self._level = DegradationLevel.NORMAL
        self._reason: str | None = None
        # Accounts the balancer last considered (present, not deactivated/paused).
        # Recorded at each selection cycle so /health can report it without a DB
        # read. ``None`` until the first selection populates it.
        self._available_accounts: int | None = None

    def set_degraded(self, reason: str | None = None, *, available_accounts: int | None = None) -> None:
        # ``available_accounts`` is the count observed at *this* transition. When
        # a caller cannot provide a fresh count, clear it to ``None`` (unknown)
        # rather than preserving a stale pool count on /health.
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
        # ``available_accounts`` is the count observed at *this* transition. When
        # a caller cannot provide a fresh count, clear it to ``None`` (unknown)
        # so /health does not keep reporting a stale pool count after recovery.
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

    def get_status(self) -> DegradationStatus:
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


def get_status() -> DegradationStatus:
    return _manager.get_status()


def get_available_accounts() -> int | None:
    return _manager.get_available_accounts()
