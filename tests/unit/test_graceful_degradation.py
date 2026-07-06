from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Iterator, cast
from unittest.mock import AsyncMock, patch

import pytest

from app.core.crypto import TokenEncryptor
from app.core.openai.model_registry import ModelRegistry, ReasoningLevel, UpstreamModel
from app.core.resilience.degradation import (
    get_available_accounts,
    get_status,
    is_degraded,
    set_degraded,
    set_normal,
)
from app.db.models import Account, AccountStatus
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
    mock_session.execute = AsyncMock()

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
async def test_load_balancer_keeps_degraded_state_on_typed_selection_error(
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
                error_message="No accounts with a plan supporting model 'gpt-5.3-codex-spark'",
                error_code=load_balancer_module.NO_PLAN_SUPPORT_FOR_MODEL,
            )
        ),
    )

    set_degraded("all upstream accounts are unavailable")
    selection = await balancer.select_account(model="gpt-5.3-codex-spark")

    assert selection.account is None
    assert selection.error_code == load_balancer_module.NO_PLAN_SUPPORT_FOR_MODEL
    # A model-scoped routing error must NOT clear a pool-wide degraded state:
    # accounts may be down across the pool while simply not supporting this one
    # model, and clearing here would mask a real outage on /health (Cubic P2).
    assert is_degraded() is True


def _make_active_account(account_id: str) -> Account:
    encryptor = TokenEncryptor()
    return Account(
        id=account_id,
        chatgpt_account_id=f"workspace-{account_id}",
        email=f"{account_id}@example.com",
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("access"),
        refresh_token_encrypted=encryptor.encrypt("refresh"),
        id_token_encrypted=encryptor.encrypt("id"),
        last_refresh=datetime.now(tz=timezone.utc),
        status=AccountStatus.ACTIVE,
        deactivation_reason=None,
    )


@pytest.mark.asyncio
async def test_repeated_failed_selection_does_not_flap_degradation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Accounts are present in the pool but none are selectable (e.g. all in
    # transient error backoff). Before the fix, select_account marked normal on
    # mere presence and then degraded again when selection failed, flapping on
    # every failed cycle. The transition WARNING must now fire exactly once with
    # no recovery event in between.
    monkeypatch.setattr(
        "app.modules.proxy.load_balancer.get_settings",
        lambda: SimpleNamespace(circuit_breaker_enabled=False),
    )
    present = _make_active_account("a1")
    balancer = LoadBalancer(lambda: _repo_factory([]))
    monkeypatch.setattr(
        balancer,
        "_load_selection_inputs",
        AsyncMock(
            return_value=load_balancer_module._SelectionInputs(
                accounts=[present],
                latest_primary={},
                latest_secondary={},
                runtime_accounts=[present],
            )
        ),
    )
    monkeypatch.setattr(load_balancer_module, "_build_states", lambda **_kwargs: ([], {}))
    monkeypatch.setattr(
        load_balancer_module,
        "_select_account_preferring_budget_safe",
        lambda *_a, **_k: load_balancer_module.SelectionResult(account=None, error_message="No available accounts"),
    )

    caplog.set_level("INFO", logger="app.core.resilience.degradation")
    caplog.clear()

    for _ in range(3):
        result = await balancer.select_account()
        assert result.account is None

    enters = [r for r in caplog.records if "DEGRADATION_TRANSITION normal->degraded" in r.getMessage()]
    exits = [r for r in caplog.records if "DEGRADATION_TRANSITION degraded->normal" in r.getMessage()]
    assert len(enters) == 1
    assert exits == []
    assert is_degraded() is True
    # Service-wide present count, not the request-scoped selection subset.
    assert get_available_accounts() == 1


@pytest.mark.asyncio
async def test_successful_selection_recovers_from_degraded(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A stale degraded state (from a prior outage) must clear the moment a real
    # selection succeeds — recovery is now driven by a proven selection, not by
    # mere account presence.
    monkeypatch.setattr(load_balancer_module, "_is_upstream_circuit_breaker_open", lambda: False)
    account = _make_active_account("acc-recover")
    balancer = LoadBalancer(lambda: _repo_factory([account]))

    set_degraded("all upstream accounts are unavailable", available_accounts=0)
    caplog.set_level("INFO", logger="app.core.resilience.degradation")
    caplog.clear()

    selection = await balancer.select_account()

    assert selection.account is not None
    assert selection.account.id == "acc-recover"
    assert is_degraded() is False
    exits = [r for r in caplog.records if "DEGRADATION_TRANSITION degraded->normal" in r.getMessage()]
    assert len(exits) == 1
    assert get_available_accounts() == 1


@pytest.mark.asyncio
async def test_successful_selection_does_not_recover_while_circuit_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the pool-wide circuit breaker open, a single successful selection must
    # NOT clear the breaker-driven degraded state — the outage must stay visible
    # on /health until the breaker itself closes (Cubic P2).
    monkeypatch.setattr(load_balancer_module, "_is_upstream_circuit_breaker_open", lambda: True)
    account = _make_active_account("acc-breaker")
    balancer = LoadBalancer(lambda: _repo_factory([account]))

    selection = await balancer.select_account()

    assert selection.account is not None
    assert is_degraded() is True
    assert get_status()["reason"] == "upstream circuit breaker is open"


@pytest.mark.asyncio
async def test_scoped_selection_does_not_mutate_global_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A scoped request (preferred-account probe / scope-restricted key) sees only
    # a subset of the pool, so it must neither flip /health degraded nor overwrite
    # the service-wide available-account count.
    monkeypatch.setattr(
        "app.modules.proxy.load_balancer.get_settings",
        lambda: SimpleNamespace(circuit_breaker_enabled=False),
    )
    balancer = LoadBalancer(lambda: _repo_factory([]))

    set_degraded("prior outage", available_accounts=7)
    selection = await balancer.select_account(account_ids=["missing"])

    assert selection.account is None
    # The global signal is untouched by the scoped probe.
    assert is_degraded() is True
    assert get_status()["reason"] == "prior outage"
    assert get_available_accounts() == 7


def test_set_normal_clears_available_accounts_when_count_omitted() -> None:
    set_degraded("outage", available_accounts=5)
    assert get_available_accounts() == 5

    set_normal()  # recovery without a fresh count

    # None (unknown) is reported instead of a stale pool count.
    assert get_available_accounts() is None


def test_set_degraded_clears_available_accounts_when_count_omitted() -> None:
    set_normal(available_accounts=5)
    assert get_available_accounts() == 5

    set_degraded("outage")  # degrade without a fresh count

    assert get_available_accounts() is None
