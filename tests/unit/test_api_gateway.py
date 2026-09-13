"""
Unit Tests for FastAPI API Gateway and Simulation Bridge (SIH 26123 - Bharat Electronics Limited).
Validates REST endpoints, Isaac Sim external position injection, Hungarian task submission,
live metrics reporting, and static dashboard serving.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from services.api_gateway.app import app


@pytest.mark.anyio
async def test_get_fleet_status():
    """Verify that /api/fleet/status returns full layout and robot fleet."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/fleet/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "warehouse" in data
        assert "robots" in data
        assert len(data["robots"]) >= 3
        assert "tasks" in data
        assert "metrics" in data


@pytest.mark.anyio
async def test_isaac_sim_position_injection():
    """Verify that POST /api/robots/{id}/position injects external coordinates (Isaac Sim / ROS2)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/robots/AMR-01/position",
            json={"x": 5, "y": 7, "heading_deg": 90.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["position"] == [5, 7]

        # Verify status endpoint reflects updated coordinate
        status_resp = await client.get("/api/fleet/status")
        status_data = status_resp.json()
        assert status_data["robots"]["AMR-01"]["position"] == [5, 7]


@pytest.mark.anyio
async def test_live_metrics_endpoint():
    """Verify /api/metrics/live reports ZERO collisions and %-improvement."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/live")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_collisions"] == 0
        assert data["zero_collisions_verified"] is True
        assert data["efficiency_improvement_pct"] >= 20.0


@pytest.mark.anyio
async def test_congestion_heatmap_endpoint():
    """Verify /api/metrics/congestion-heatmap returns rolling conflict history data."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/congestion-heatmap")
        assert resp.status_code == 200
        data = resp.json()
        assert "cells" in data
        assert "window_seconds" in data


@pytest.mark.anyio
async def test_submit_new_task():
    """Verify that POST /api/tasks/submit queues task for Hungarian matching."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "pickup_x": 1,
            "pickup_y": 2,
            "dropoff_x": 22,
            "dropoff_y": 8,
            "payload_weight_kg": 120.0,
            "priority": 3,
        }
        resp = await client.post("/api/tasks/submit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "submitted"
        assert data["task"]["payload_weight_kg"] == 120.0


@pytest.mark.anyio
async def test_dashboard_index_serving():
    """Verify root / serves the HTML dashboard."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "DECENTRALIZED AMR FLEET COORDINATION" in resp.text
        assert "Bharat Electronics Limited" in resp.text


@pytest.mark.anyio
async def test_maintenance_metrics_endpoint():
    """Verify /api/metrics/maintenance returns fleet-wide predictive maintenance data."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/maintenance")
        assert resp.status_code == 200
        data = resp.json()
        assert "robots_health" in data
        assert "active_alerts" in data
        assert "total_alerts" in data


@pytest.mark.anyio
async def test_model_status_endpoint():
    """Verify /api/model/status reports the hybrid priority model status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/model/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "hybrid_priority_model_active" in data
        assert "model_file_exists" in data
        assert "research_note" in data
