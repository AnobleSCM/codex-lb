from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="codex-lb-tests-"))
TEST_DB_PATH = TEST_DB_DIR / "codex-lb.db"
DEFAULT_TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
_SQLITE_RESET_ATTEMPTS = 3
_SQLITE_RESET_RETRY_SECONDS = 0.25
_HTTP_BRIDGE_TEST_CLOSE_TIMEOUT_SECONDS = 15.0

os.environ["CODEX_LB_DATABASE_URL"] = os.environ.get("CODEX_LB_TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
_RESET_BY_RECREATING_SQLITE_FILE = os.environ["CODEX_LB_DATABASE_URL"] == DEFAULT_TEST_DATABASE_URL
os.environ["CODEX_LB_UPSTREAM_BASE_URL"] = "https://example.invalid/backend-api"
os.environ["CODEX_LB_USAGE_REFRESH_ENABLED"] = "false"
os.environ["CODEX_LB_MODEL_REGISTRY_ENABLED"] = "false"
os.environ["CODEX_LB_STICKY_SESSION_CLEANUP_ENABLED"] = "false"
os.environ["CODEX_LB_HTTP_RESPONSES_SESSION_BRIDGE_ENABLED"] = "false"

from app.db.models import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import create_app  # noqa: E402


def _drop_test_migration_tables(sync_conn) -> None:
    sync_conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    sync_conn.execute(text("DROP TABLE IF EXISTS schema_migrations"))


def _recreate_test_schema(sync_conn) -> None:
    _drop_test_migration_tables(sync_conn)
    Base.metadata.drop_all(sync_conn)
    Base.metadata.create_all(sync_conn)


def _reset_test_database(sync_conn) -> None:
    _recreate_test_schema(sync_conn)


def _is_sqlite_locked_error(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


def _remove_sqlite_test_database_files() -> None:
    for path in (
        TEST_DB_PATH,
        TEST_DB_PATH.with_name(f"{TEST_DB_PATH.name}-wal"),
        TEST_DB_PATH.with_name(f"{TEST_DB_PATH.name}-shm"),
    ):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


async def _await_http_bridge_test_task(task) -> None:
    if not task.done():
        task.cancel()
    try:
        await asyncio.wait_for(task, timeout=_HTTP_BRIDGE_TEST_CLOSE_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return
    except TimeoutError as exc:
        raise AssertionError("HTTP bridge test cleanup timed out waiting for task shutdown") from exc
    except Exception:
        return


async def _close_http_bridge_sessions_for_test(service) -> None:
    async with service._http_bridge_lock:
        sessions = list(service._http_bridge_sessions.values())
        inflight_futures = list(service._http_bridge_inflight_sessions.values())
        service._http_bridge_sessions.clear()
        service._http_bridge_inflight_sessions.clear()
        service._http_bridge_turn_state_index.clear()
        service._http_bridge_previous_response_index.clear()

    for inflight_future in inflight_futures:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            if not inflight_future.done():
                inflight_future.cancel()
            sessions.append(
                await asyncio.wait_for(
                    inflight_future,
                    timeout=_HTTP_BRIDGE_TEST_CLOSE_TIMEOUT_SECONDS,
                )
            )

    for session in sessions:
        reader = getattr(session, "upstream_reader", None)
        if reader is not None:
            await _await_http_bridge_test_task(reader)
            session.upstream_reader = None
        await service._close_http_bridge_session(session)


@pytest_asyncio.fixture
async def _reset_db_state():
    from app.db.session import close_db

    await close_db()
    if _RESET_BY_RECREATING_SQLITE_FILE:
        _remove_sqlite_test_database_files()
    for attempt in range(_SQLITE_RESET_ATTEMPTS):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(_reset_test_database)
            return True
        except OperationalError as exc:
            if not _is_sqlite_locked_error(exc) or attempt == _SQLITE_RESET_ATTEMPTS - 1:
                raise
            await close_db()
            await asyncio.sleep(_SQLITE_RESET_RETRY_SECONDS * (attempt + 1))
    return True


@pytest_asyncio.fixture
async def app_instance(_reset_db_state, monkeypatch):
    del _reset_db_state
    import app.main as main_module
    import app.modules.proxy.service as proxy_service_module
    from app.modules.proxy.ring_membership import RingMembershipService

    async def _noop_init_db() -> None:
        return None

    async def _noop_ring_register(self, instance_id, *, endpoint_base_url=None) -> None:
        del self, instance_id, endpoint_base_url
        return None

    async def _noop_ring_heartbeat(self, instance_id, *, endpoint_base_url=None) -> None:
        del self, instance_id, endpoint_base_url
        return None

    async def _noop_ring_mark_stale(self, instance_id, *, stale_threshold_seconds, grace_seconds) -> int:
        del self, instance_id, stale_threshold_seconds, grace_seconds
        return 0

    async def _test_close_all_http_bridge_sessions(self) -> None:
        await _close_http_bridge_sessions_for_test(self)

    monkeypatch.setattr(main_module, "init_db", _noop_init_db)
    monkeypatch.setattr(RingMembershipService, "register", _noop_ring_register)
    monkeypatch.setattr(RingMembershipService, "heartbeat", _noop_ring_heartbeat)
    monkeypatch.setattr(RingMembershipService, "mark_stale", _noop_ring_mark_stale)
    monkeypatch.setattr(
        proxy_service_module.ProxyService,
        "close_all_http_bridge_sessions",
        _test_close_all_http_bridge_sessions,
    )
    app = create_app()
    return app


@pytest_asyncio.fixture(scope="session", autouse=True)
async def dispose_engine():
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db_setup(_reset_db_state):
    del _reset_db_state
    return True


@pytest_asyncio.fixture
async def async_client(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture(autouse=True)
def temp_key_file(monkeypatch):
    key_path = TEST_DB_DIR / f"encryption-{uuid4().hex}.key"
    monkeypatch.setenv("CODEX_LB_ENCRYPTION_KEY_FILE", str(key_path))
    from app.core.config.settings import get_settings

    get_settings.cache_clear()
    return key_path


@pytest.fixture(autouse=True)
def _reset_model_registry():
    from app.core.openai.model_registry import get_model_registry

    registry = get_model_registry()
    registry._snapshot = None
    yield
    registry._snapshot = None


@pytest.fixture(autouse=True)
def _reset_codex_version_cache():
    from app.core.clients.codex_version import get_codex_version_cache

    cache = get_codex_version_cache()
    cache._cached_version = None
    cache._cached_at = 0.0
    yield
    cache._cached_version = None
    cache._cached_at = 0.0


def _reset_global_state() -> None:
    """Reset global singletons that leak between tests."""
    try:
        from app.core.auth.api_key_cache import get_api_key_cache

        get_api_key_cache().clear()
    except Exception:
        pass
    try:
        from app.core.middleware.firewall_cache import get_firewall_ip_cache as get_firewall_cache

        get_firewall_cache().invalidate_all()
    except Exception:
        pass
    try:
        from app.modules.proxy.account_cache import get_account_selection_cache

        get_account_selection_cache().invalidate()
    except Exception:
        pass
    try:
        from app.core.resilience.degradation import set_normal

        set_normal()
    except Exception:
        pass
    try:
        from app.core.shutdown import set_bridge_drain_active

        set_bridge_drain_active(False)
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_hot_path_caches():
    """Reset T20 hot-path caches between tests to prevent state leakage."""
    _reset_global_state()
    yield
    _reset_global_state()
