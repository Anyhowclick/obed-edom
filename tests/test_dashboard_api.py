from fastapi.testclient import TestClient

from obed_edom.web.app import app


def test_health_and_stubs():
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    assert client.post("/api/dsk").status_code == 501
    assert client.post("/api/resize").status_code == 501
