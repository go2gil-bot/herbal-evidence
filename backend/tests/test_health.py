from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_never_leaks_secret_values(monkeypatch):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.text
    # Checks report presence only - "set" / "missing" - never the value itself.
    assert "sb_secret" not in body
