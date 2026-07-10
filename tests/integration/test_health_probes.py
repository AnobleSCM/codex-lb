from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_health_endpoint_reports_status_and_degradation(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    # Liveness stays "ok"; the response also carries degradation observability.
    assert payload["status"] == "ok"
    assert payload["degradation"]["level"] in {"normal", "degraded", "critical"}
    assert "available_accounts" in payload


@pytest.mark.asyncio
async def test_health_live_endpoint(async_client):
    response = await async_client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_ready_endpoint_db_ok(async_client):
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["checks"] == {"database": "ok"}


@pytest.mark.asyncio
async def test_health_startup_endpoint(async_client):
    response = await async_client.get("/health/startup")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
