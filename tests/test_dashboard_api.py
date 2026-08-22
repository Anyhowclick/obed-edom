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


def _wait(client, job_id, tries=120):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _cued_offering(tmp_path):
    from pathlib import Path

    from obed_edom.annotate import annotate_outline
    from obed_edom.parse_outline import parse_outline
    from obed_edom.slide_map import map_slides

    source = Path(__file__).resolve().parents[1] / "Sermon Outlines" / "Offering JX.docx"
    if not source.is_file():
        return None
    outline = parse_outline(source)
    lw, dsk, _ = map_slides(outline)
    return annotate_outline(outline, lw, dsk, tmp_path / "Offering_CUED.docx")


def test_outline_endpoint_reads_the_cues(tmp_path):
    cued = _cued_offering(tmp_path)
    if cued is None:
        import pytest

        pytest.skip("Sermon Outlines/ fixtures are local operator files")
    client = TestClient(app)
    started = client.post("/api/outline", data={"path": str(cued)})
    assert started.status_code == 200
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["kind"] == "outline"
    assert (result["lwCues"], result["dskCues"]) == (6, 7)
    assert len(result["rows"]) == 7
    assert result["paragraphs"]
    assert client.get(f"/api/jobs/{started.json()['id']}/outline.pdf").status_code == 200


def test_outline_endpoint_rejects_a_pre_generate_outline():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "Sermon Outlines" / "Sermon BC.docx"
    if not source.is_file():
        import pytest

        pytest.skip("Sermon Outlines/ fixtures are local operator files")
    client = TestClient(app)
    res = client.post("/api/outline", data={"path": str(source)})
    assert res.status_code == 400
    assert "Sermon Base Generator" in res.json()["detail"]


def test_outline_endpoint_rejects_a_missing_file():
    client = TestClient(app)
    res = client.post("/api/outline", data={"path": "/no/such/outline.docx"})
    assert res.status_code == 400
    assert "not found" in res.json()["detail"].lower()


def test_diff_rejects_a_bad_outline(tmp_path):
    client = TestClient(app)
    left = tmp_path / "Sermon_LW.key"
    right = tmp_path / "Sermon_DSK.key"
    left.write_text("placeholder")
    right.write_text("placeholder")
    res = client.post(
        "/api/diff",
        data={
            "left_path": str(left),
            "right_path": str(right),
            "outline_path": str(tmp_path / "missing.docx"),
        },
    )
    assert res.status_code == 400
    assert "not found" in res.json()["detail"].lower()


def test_validate_keynote_rejects_a_bad_outline(tmp_path):
    client = TestClient(app)
    deck = tmp_path / "Sermon_LW.key"
    deck.write_text("placeholder")
    res = client.post(
        "/api/validate-keynote",
        data={"path": str(deck), "outline_path": str(tmp_path / "missing.docx")},
    )
    assert res.status_code == 400


def test_validate_keynote_records_whether_the_wall_is_final(tmp_path):
    """The answer has to survive into the job, since the check pass reads it."""
    from obed_edom.web import app as app_mod

    seen = {}

    def fake_inspect(job, path, export, slide_range, *, outline=None, lw_final=True):
        seen["lw_final"] = lw_final
        return {"path": str(path), "lwFinal": lw_final, "flags": []}

    original = app_mod._run_inspect
    app_mod._run_inspect = fake_inspect
    try:
        client = TestClient(app)
        deck = tmp_path / "Sermon_LW.key"
        deck.write_text("placeholder")
        started = client.post(
            "/api/validate-keynote", data={"path": str(deck), "lw_final": "false"}
        )
        assert started.status_code == 200
        job = _wait(client, started.json()["id"])
        assert job["status"] == "done", job.get("error")
        assert seen["lw_final"] is False
        assert job["result"]["lwFinal"] is False
    finally:
        app_mod._run_inspect = original
