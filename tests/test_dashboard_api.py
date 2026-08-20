from fastapi.testclient import TestClient

from obed_edom.web.app import app


def test_health_and_stubs():
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    assert client.post("/api/dsk").status_code == 501
    missing = client.post("/api/resize")
    assert missing.status_code == 422
    missing_file = client.post("/api/resize", data={"path": "/no/such/deck.key"})
    assert missing_file.status_code == 400


def test_resolve_drop_unknown_name():
    client = TestClient(app)
    res = client.post("/api/resolve-drop", data={"name": "definitely-not-a-real-deck-zzzz.key"})
    assert res.status_code == 404
