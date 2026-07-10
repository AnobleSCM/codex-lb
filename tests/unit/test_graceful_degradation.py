from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Iterator, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.openai.model_registry import ModelRegistry, ReasoningLevel, UpstreamModel
from app.core.resilience.degradation import (
    get_available_accounts,
    get_status,
    is_degraded,
    set_degraded,
    set_normal,
)
from app.modules.accounts.repository import AccountsRepository
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.proxy import load_balancer as load_balancer_module
from app.modules.proxy.load_balancer import LoadBalancer
from app.modules.proxy.repo_bundle import ProxyRepositories
from app.modules.proxy.sticky_repository import StickySessionsRepository
from app.modules.request_logs.repository import RequestLogsRepository
from app.modules.usage.repository import AdditionalUsageRepository, UsageRepository

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_degradation_state() -> Iterator[None]:
    set_normal()
    yield
    set_normal()


def _model(slug: str) -> UpstreamModel:
    return UpstreamModel(
        slug=slug,
        display_name=slug,
        description=f"Model {slug}",
        context_window=128000,
        input_modalities=("text",),
        supported_reasoning_levels=(ReasoningLevel(effort="medium", description="balanced"),),
        default_reasoning_level="medium",
        supports_reasoning_summaries=False,
        support_verbosity=False,
        default_verbosity=None,
        prefer_websockets=False,
        supports_parallel_tool_calls=True,
        supported_in_api=True,
        minimal_client_version=None,
        priority=0,
        available_in_plans=frozenset(),
        raw={},
    )


class _StubAccountsRepository:
    def __init__(self, accounts: list[object]) -> None:
        self._accounts = accounts

    async def list_accounts(self) -> list[object]:
        return list(self._accounts)

    async def update_status_if_current(self, *args, **kwargs) -> bool:
        return True

    async def update_status(self, *args, **kwargs) -> bool:
        return True


class _StubUsageRepository:
    async def latest_by_account(self, window: str | None = None) -> dict[str, object]:
        return {}


class _StubStickyRepository:
    async def get_account_id(self, *args, **kwargs) -> str | None:
        return None

    async def upsert(self, *args, **kwargs):
        return None

    async def delete(self, *args, **kwargs) -> bool:
        return False


class _StubAdditionalUsageRepository:
    async def latest_by_account(self, *args, **kwargs) -> dict[str, object]:
        return {}

    async def latest_by_quota_key(self, *args, **kwargs) -> dict[str, object]:
        return {}


@asynccontextmanager
async def _repo_factory(accounts: list[object]):
    yield ProxyRepositories(
        accounts=cast(AccountsRepository, _StubAccountsRepository(accounts)),
        usage=cast(UsageRepository, _StubUsageRepository()),
        request_logs=cast(RequestLogsRepository, SimpleNamespace()),
        sticky_sessions=cast(StickySessionsRepository, _StubStickyRepository()),
        api_keys=cast(ApiKeysRepository, SimpleNamespace()),
        additional_usage=cast(AdditionalUsageRepository, _StubAdditionalUsageRepository()),
    )


def test_set_degraded_sets_status() -> None:
    set_degraded("all upstream accounts are unavailable")

    assert is_degraded() is True
    assert get_status() == {
        "level": "degraded",
        "reason": "all upstream accounts are unavailable",
    }


def test_set_normal_clears_degraded_state() -> None:
    set_degraded("temporary outage")

    set_normal()

    assert is_degraded() is False
    assert get_status() == {"level": "normal", "reason": None}


def test_set_degraded_records_available_accounts() -> None:
    set_degraded("all upstream accounts are unavailable", available_accounts=4)

    # get_status() shape is unchanged; the count is exposed via its own accessor.
    assert get_status() == {
        "level": "degraded",
        "reason": "all upstream accounts are unavailable",
    }
    assert get_available_accounts() == 4


def test_set_normal_records_available_accounts() -> None:
    set_normal(available_accounts=6)

    assert is_degraded() is False
    assert get_available_accounts() == 6


def test_degradation_transition_logs_once_per_edge(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="app.core.resilience.degradation")
    caplog.clear()

    # set_degraded fires on every failed selection; the WARNING transition marker
    # must appear exactly once, on the normal -> degraded edge.
    set_degraded("all upstream accounts are unavailable", available_accounts=0)
    set_degraded("all upstream accounts are unavailable", available_accounts=0)
    set_degraded("all upstream accounts are unavailable", available_accounts=0)
    enters = [r for r in caplog.records if "DEGRADATION_TRANSITION normal->degraded" in r.getMessage()]
    assert len(enters) == 1

    caplog.clear()
    set_normal(available_accounts=3)
    exits = [r for r in caplog.records if "DEGRADATION_TRANSITION degraded->normal" in r.getMessage()]
    assert len(exits) == 1


@pytest.mark.asyncio
async def test_health_check_reports_degradation() -> None:
    from app.modules.health.api import health_check

    set_degraded("all upstream accounts are unavailable", available_accounts=2)
    response = await health_check()

    assert response.status == "ok"
    assert response.degradation is not None
    assert response.degradation.level == "degraded"
    assert response.degradation.reason == "all upstream accounts are unavailable"
    assert response.available_accounts == 2


@pytest.mark.asyncio
async def test_health_check_reports_normal_when_not_degraded() -> None:
    from app.modules.health.api import health_check

    set_normal(available_accounts=5)
    response = await health_check()

    assert response.status == "ok"
    assert response.degradation is not None
    assert response.degradation.level == "normal"
    assert response.degradation.reason is None
    assert response.available_accounts == 5


@pytest.mark.asyncio
async def test_health_ready_succeeds_when_degraded() -> None:
    from app.modules.health.api import health_ready

    set_degraded("all upstream accounts are unavailable")
    mock_session = AsyncMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("app.core.draining._draining", False),
        patch("app.modules.health.api.SessionLocal") as mock_session_local,
    ):

        @asynccontextmanager
        async def _session_cm():
            yield mock_session

        mock_session_local.return_value = _session_cm()

        result = await health_ready()

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_model_registry_keeps_cached_models_when_refresh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ModelRegistry(ttl_seconds=60.0)
    await registry.update({"plus": [_model("cached-model")]})

    def _raise_runtime_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.openai.model_registry.ModelRegistrySnapshot", _raise_runtime_error)

    with pytest.raises(RuntimeError, match="boom"):
        await registry.update({"pro": [_model("new-model")]})

    assert set(registry.get_models_with_fallback()) == {"cached-model"}


@pytest.mark.asyncio
async def test_load_balancer_returns_degraded_message_when_no_accounts_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.proxy.load_balancer.get_settings", lambda: SimpleNamespace(circuit_breaker_enabled=False)
    )

    balancer = LoadBalancer(lambda: _repo_factory([]))
    selection = await balancer.select_account()

    assert selection.account is None
    assert selection.error_message == (
        "No available accounts. Service is operating in degraded mode: all upstream accounts are unavailable"
    )
    assert is_degraded() is True
    # The empty pool is recorded so /health can report it (0 accounts present).
    assert get_available_accounts() == 0


@pytest.mark.asyncio
async def test_load_balancer_clears_stale_degraded_state_for_typed_selection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.proxy.load_balancer.get_settings", lambda: SimpleNamespace(circuit_breaker_enabled=False)
    )

    balancer = LoadBalancer(lambda: _repo_factory([]))
    monkeypatch.setattr(
        balancer,
        "_load_selection_inputs",
        AsyncMock(
            return_value=load_balancer_module._SelectionInputs(
                accounts=[],
                latest_primary={},
                latest_secondary={},
                latest_monthly={},
                error_message="No accounts with a plan supporting model 'gpt-5.3-codex-spark'",
                error_code=load_balancer_module.NO_PLAN_SUPPORT_FOR_MODEL,
            )
        ),
    )

    set_degraded("all upstream accounts are unavailable")
    selection = await balancer.select_account(model="gpt-5.3-codex-spark")

    assert selection.account is None
    assert selection.error_code == load_balancer_module.NO_PLAN_SUPPORT_FOR_MODEL
    assert is_degraded() is False
