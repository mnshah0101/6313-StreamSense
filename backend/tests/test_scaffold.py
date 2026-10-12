"""Verify the preparation boundary without connecting to client services."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_is_only_a_liveness_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stage": "development-readiness"}


def test_product_endpoints_are_not_implemented():
    for path in ("/assets", "/analysis-jobs", "/alerts"):
        assert client.post(path, json={}).status_code == 404
