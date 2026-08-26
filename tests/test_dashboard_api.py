from pathlib import Path

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


def test_resize_asks_for_framings_before_remapping(tmp_path):
    """Resize stops at proposals, and applying carries the confirmed framing.

    Also guards the original regression this test was written for: a blank range
    means every slide, and `format_slide_range` only accepted an iterable, so an
    empty field reached it as None and failed with "'NoneType' object is not
    iterable". That log line lives in the apply phase now.
    """
    import obed_edom.web.app as app_mod

    seen = {}

    def fake_remap(path, dest, **kwargs):
        seen["slide_range"] = kwargs.get("slide_range")
        seen["framing_overrides"] = kwargs.get("framing_overrides")
        return {"dest": str(dest), "counts": {}, "applied": 1, "missed": 0}

    def fake_inspect(path, **kwargs):
        return {"slideWidth": 7680, "slideHeight": 1080, "slideCount": 1, "slides": []}

    def fake_propose(wall, template, **kwargs):
        return {
            "wallPath": str(wall),
            "templatePath": str(template),
            "wallDigests": ["d0"],
            "templateDigest": "t0",
            "destWidth": 1920,
            "destHeight": 1080,
            "wallWidth": 7680,
            "wallHeight": 1080,
            "pages": [
                {
                    "slide": 1,
                    "index": 0,
                    "autoTemplateSlide": 2,
                    "autoFellBack": False,
                    "needsAttention": False,
                    "noUsableFraming": False,
                    "candidates": [],
                }
            ],
            "needAttention": [],
            "noUsableFraming": [],
        }

    originals = (app_mod.remap_and_inspect, app_mod.inspect_keynote, app_mod.propose_framings)
    app_mod.remap_and_inspect = fake_remap
    app_mod.inspect_keynote = fake_inspect
    app_mod.propose_framings = fake_propose
    try:
        client = TestClient(app)
        deck = tmp_path / "Wall.key"
        deck.write_text("placeholder")
        template = tmp_path / "Base_CG_Assets.key"
        template.write_text("placeholder")
        started = client.post(
            "/api/resize",
            data={"path": str(deck), "template_path": str(template), "export": "false"},
        )
        assert started.status_code == 200
        job_id = started.json()["id"]
        job = _wait(client, job_id)
        assert job["status"] == "done", job.get("error")
        # Phase one only proposes: nothing was remapped.
        assert job["result"]["phase"] == "framing"
        assert "slide_range" not in seen

        confirmed = client.post(
            f"/api/resize/{job_id}/apply",
            json={"decisions": [{"wallIndex": 0, "state": "pinned", "templateSlide": 5}]},
        )
        assert confirmed.status_code == 200
        job = _wait(client, job_id)
        assert job["status"] == "done", job.get("error")
        assert job["result"]["phase"] == "resized"
        assert seen["slide_range"] is None
        assert seen["framing_overrides"] == {1: 5}
        assert any("every slide" in line for line in job["logs"])
    finally:
        app_mod.remap_and_inspect, app_mod.inspect_keynote, app_mod.propose_framings = originals


def test_side_content_slides_reads_whitelisted_pages():
    """The apply path turns whitelisted pages into wall slide numbers, regardless of
    their framing state — an auto page can still be whitelisted."""
    from obed_edom.web.app import _side_content_slides_from_result

    result = {
        "pages": [
            {"slide": 2, "decision": {"wallIndex": 1, "state": "auto"}},
            {"slide": 5, "decision": {"wallIndex": 4, "state": "auto", "keepSideContent": True}},
            {"slide": 9, "decision": {"wallIndex": 8, "state": "pinned", "templateSlide": 3, "keepSideContent": True}},
            {"slide": 11, "decision": {"wallIndex": 10, "state": "pinned", "templateSlide": 4}},
        ]
    }
    assert _side_content_slides_from_result(result) == {5, 9}


def test_resize_form_still_takes_validate():
    """The parameter is aliased, because a form field literally named `validate`
    generates a Pydantic field that shadows BaseModel.validate and warns on
    import. The dashboard posts `validate`, so the alias is the contract."""
    from obed_edom.web.app import app as fastapi_app

    schema = fastapi_app.openapi()
    ref = schema["paths"]["/api/resize"]["post"]["requestBody"]["content"][
        "application/x-www-form-urlencoded"
    ]["schema"]["$ref"]
    body = schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert "validate" in body["properties"]
    assert "run_validation" not in body["properties"]
