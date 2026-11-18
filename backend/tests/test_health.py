"""Tests for the backend health endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_api_health_returns_ok() -> None:
    """Verify GET /api/health returns 200 OK with expected metadata."""
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "ai-engineering-agent"
    assert payload["classification"] == "Preliminary"
    assert payload["version"] == "0.1.0"
