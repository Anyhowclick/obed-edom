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


def test_resize_requires_template(tmp_path):
    client = TestClient(app)
    wall = tmp_path / "wall.key"
    wall.write_text("placeholder")
    res = client.post("/api/resize", data={"path": str(wall)})
    assert res.status_code == 400
    assert "template" in res.json()["detail"].lower()


def test_generate_requires_templates():
    client = TestClient(app)
    res = client.post(
        "/api/generate",
        files={
            "files": (
                "outline.docx",
                b"not-a-real-docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 400
    assert "at least one" in res.json()["detail"].lower()


def test_generate_rejects_missing_single_template(tmp_path):
    client = TestClient(app)
    res = client.post(
        "/api/generate",
        data={"lw_template": str(tmp_path / "missing.key")},
        files={
            "files": (
                "outline.docx",
                b"not-a-real-docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 400
    assert "lw template not found" in res.json()["detail"].lower()


def test_resolve_drop_unknown_name():
    client = TestClient(app)
    res = client.post("/api/resolve-drop", data={"name": "definitely-not-a-real-deck-zzzz.key"})
    assert res.status_code == 404


def test_settings_roundtrip(tmp_path, monkeypatch):
    from obed_edom import settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda root=None: tmp_path / "settings.json")
    client = TestClient(app)
    got = client.get("/api/settings").json()
    assert got["reusePairings"] is True
    assert got["reusePreviews"] is True
    put = client.put("/api/settings", json={"reuseThreshold": 0.8, "reusePairings": False})
    assert put.status_code == 200
    body = put.json()
    assert body["reuseThreshold"] == 0.8
    assert body["reusePairings"] is False
    assert body["reusePreviews"] is True
    assert client.get("/api/settings").json()["reuseThreshold"] == 0.8
