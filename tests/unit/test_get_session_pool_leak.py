"""Regression tests for the async-generator DB session pool leak.

Background
----------
``app.db.session.get_session`` is a *bare async generator* whose ``finally``
block returns the connection to the pool. FastAPI calls ``aclose()`` on
generator dependencies, so ``Depends(get_session)`` request paths are safe.

Non-request callers that did ``async for session in get_session(): ... return``
abandoned the generator without ``aclose()``. The ``finally`` (and therefore the
connection checkin) then ran only at non-deterministic garbage collection, so
the connection stayed checked out under load. After ~5 days the live container
exhausted ``QueuePool limit of size 100 overflow 100`` and every Codex request
hung ~30s until a restart.

The fix replaces the borrow-the-generator pattern in the three non-request
callers (``LeaderElection.try_acquire``/``renew``, ``AuditService`` writes, and
``health_ready``) with ``async with SessionLocal() as session: ...`` so the
connection is returned on every exit path, including early ``return``/``raise``.

These tests run each fixed path many times against an isolated temp-file SQLite
engine (a real ``AsyncAdaptedQueuePool`` with ``checkedout()`` accounting) and
assert the pool returns to baseline with no monotonic growth. A control case
reproduces the original leak signature so the assertion cannot silently pass if
the detection mechanism breaks.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db.models import Base

pytestmark = pytest.mark.unit

# A small pool makes a leak fail fast: even a single un-returned connection per
# iteration crosses ``pool_size + max_overflow`` within the iteration count.
_POOL_SIZE = 3
_MAX_OVERFLOW = 2
_ITERATIONS = 25


@pytest_asyncio.fixture
async def isolated_engine(tmp_path: Path) -> AsyncIterator[tuple[object, async_sessionmaker[AsyncSession]]]:
    """A dedicated file-backed SQLite engine with a real connection pool.

    In-memory SQLite collapses onto a single shared connection, which hides
    pool checkin/checkout accounting. A temp file yields a genuine
    ``AsyncAdaptedQueuePool`` whose ``checkedout()`` reflects leaks.
    """
    db_path = tmp_path / "pool_leak_probe.sqlite"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_timeout=5,
    )
    # Sanity: this is the same pool family that raises the production
    # "QueuePool limit of size N overflow M reached" error.
    assert isinstance(engine.pool, AsyncAdaptedQueuePool)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield engine, factory
    finally:
        await engine.dispose()


async def test_control_abandoned_generator_leaks(isolated_engine) -> None:
    """The original borrow pattern leaks — guards against a false-negative test.

    If this stops leaking, the assertion in the fix tests below would be
    meaningless, so we assert the leak is actually observable.
    """
    engine, factory = isolated_engine

    async def _bad_get_session() -> AsyncIterator[AsyncSession]:
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    baseline = engine.pool.checkedout()

    # Reproduce ``async for session in get_session(): ... return`` enough times
    # to exceed the pool. Each abandoned generator holds its connection until GC.
    leaked = 0
    for _ in range(_POOL_SIZE + _MAX_OVERFLOW + 2):
        async for session in _bad_get_session():
            await session.execute(text("SELECT 1"))
            break  # abandons the generator without aclose() -> connection stuck
        leaked = engine.pool.checkedout() - baseline
        if leaked >= _POOL_SIZE:
            break

    assert leaked > 0, "expected the abandoned-generator pattern to leak connections"


async def test_leader_election_try_acquire_no_leak(isolated_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed leader-election acquire path returns connections every call."""
    engine, factory = isolated_engine

    import app.core.scheduling.leader_election as leader_election_module

    monkeypatch.setattr(leader_election_module, "SessionLocal", factory)
    # Force the Postgres branch (real get_session borrow) rather than the
    # sqlite/disabled short-circuit, so we exercise the fixed code path.
    monkeypatch.setattr(
        leader_election_module,
        "get_settings",
        lambda: SimpleNamespace(
            leader_election_enabled=True,
            database_url="postgresql+asyncpg://probe",
            leader_election_ttl_seconds=30,
        ),
    )

    baseline = engine.pool.checkedout()
    election = leader_election_module.LeaderElection(leader_id="node-a")
    for _ in range(_ITERATIONS):
        await election.try_acquire()

    assert engine.pool.checkedout() == baseline


async def test_leader_election_renew_no_leak(isolated_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed leader-election renew path returns connections every call."""
    engine, factory = isolated_engine

    import app.core.scheduling.leader_election as leader_election_module

    monkeypatch.setattr(leader_election_module, "SessionLocal", factory)
    monkeypatch.setattr(
        leader_election_module,
        "get_settings",
        lambda: SimpleNamespace(
            leader_election_enabled=True,
            database_url="postgresql+asyncpg://probe",
            leader_election_ttl_seconds=30,
        ),
    )

    # Seed a row this leader owns so renew takes its full body (execute+commit).
    async with factory() as seed:
        await seed.execute(
            text("INSERT INTO scheduler_leader (id, leader_id, acquired_at, expires_at) VALUES (1, :lid, :now, :exp)"),
            {"lid": "node-a", "now": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(seconds=30)},
        )
        await seed.commit()

    election = leader_election_module.LeaderElection(leader_id="node-a")
    election._is_leader = True

    baseline = engine.pool.checkedout()
    for _ in range(_ITERATIONS):
        await election.renew()

    assert engine.pool.checkedout() == baseline


async def test_audit_log_write_no_leak(isolated_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed audit-log write path returns connections every call."""
    engine, factory = isolated_engine

    import app.core.audit.service as audit_service_module

    monkeypatch.setattr(audit_service_module, "SessionLocal", factory)

    baseline = engine.pool.checkedout()
    for index in range(_ITERATIONS):
        await audit_service_module._write_audit_log(
            action="probe",
            actor_ip="127.0.0.1",
            details=None,
            request_id=f"req-{index}",
        )

    assert engine.pool.checkedout() == baseline


async def test_health_ready_no_leak(isolated_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed readiness probe returns connections on its early-return path.

    ``health_ready`` returns from *inside* the ``async with`` block, which is the
    exact shape that leaked under the old ``async for`` borrow.
    """
    engine, factory = isolated_engine

    import app.modules.health.api as health_api

    monkeypatch.setattr(health_api, "SessionLocal", factory)
    monkeypatch.setattr("app.core.draining._draining", False, raising=False)
    monkeypatch.setattr("app.core.startup._bridge_durable_schema_ready", True, raising=False)
    monkeypatch.setattr("app.core.startup._bridge_registration_complete", True, raising=False)

    async def _ring_ok(_session: object):
        from app.modules.health.schemas import BridgeRingInfo

        return BridgeRingInfo(
            ring_fingerprint="abc",
            ring_size=0,
            instance_id="pod-a",
            is_member=False,
        )

    monkeypatch.setattr(health_api, "_get_bridge_ring_info", _ring_ok)

    baseline = engine.pool.checkedout()
    for _ in range(_ITERATIONS):
        response = await health_api.health_ready()
        assert response.status == "ok"

    assert engine.pool.checkedout() == baseline


async def test_pool_returns_to_baseline_across_mixed_paths(isolated_engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: interleaving all fixed paths shows no monotonic growth."""
    engine, factory = isolated_engine

    import app.core.audit.service as audit_service_module
    import app.core.scheduling.leader_election as leader_election_module
    import app.modules.health.api as health_api

    monkeypatch.setattr(leader_election_module, "SessionLocal", factory)
    monkeypatch.setattr(audit_service_module, "SessionLocal", factory)
    monkeypatch.setattr(health_api, "SessionLocal", factory)
    monkeypatch.setattr(
        leader_election_module,
        "get_settings",
        lambda: SimpleNamespace(
            leader_election_enabled=True,
            database_url="postgresql+asyncpg://probe",
            leader_election_ttl_seconds=30,
        ),
    )
    monkeypatch.setattr("app.core.draining._draining", False, raising=False)
    monkeypatch.setattr("app.core.startup._bridge_durable_schema_ready", True, raising=False)
    monkeypatch.setattr("app.core.startup._bridge_registration_complete", True, raising=False)

    async def _ring_ok(_session: object):
        from app.modules.health.schemas import BridgeRingInfo

        return BridgeRingInfo(ring_fingerprint="abc", ring_size=0, instance_id="pod-a", is_member=False)

    monkeypatch.setattr(health_api, "_get_bridge_ring_info", _ring_ok)

    election = leader_election_module.LeaderElection(leader_id=str(uuid.uuid4()))
    baseline = engine.pool.checkedout()
    high_water = baseline

    for index in range(_ITERATIONS):
        await election.try_acquire()
        await audit_service_module._write_audit_log("probe", "127.0.0.1", None, f"req-{index}")
        await health_api.health_ready()
        high_water = max(high_water, engine.pool.checkedout())

    # No connection is held across iterations, so the pool never climbs and
    # always settles back to where it started.
    assert engine.pool.checkedout() == baseline
    assert high_water - baseline <= 1
