import copy
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obed_edom.web.app import _assert_range_within_deck, app


def test_range_past_the_last_slide_is_an_error_not_a_blank_screen():
    # A range typed for a bigger deck (slide 124 fed to a 9-slide extract) used to
    # inspect nothing and propose nothing, leaving the operator on an empty framing
    # screen. It now raises a clear error naming the deck's real length.
    with pytest.raises(RuntimeError) as err:
        _assert_range_within_deck("wall_extracted.key", 9, frozenset({124}))
    message = str(err.value)
    assert "9 slides" in message
    assert "124" in message
    # A partly-out range names only the slides that are actually beyond the deck.
    with pytest.raises(RuntimeError) as partial:
        _assert_range_within_deck("deck.key", 9, frozenset({5, 10, 11}))
    assert "10" in str(partial.value) and "5" not in str(partial.value)
    # In range, whole-deck (no range), and an unknown length are all silent.
    _assert_range_within_deck("deck.key", 9, frozenset({1, 9}))
    _assert_range_within_deck("deck.key", 9, None)
    _assert_range_within_deck("deck.key", 0, frozenset({124}))


def _cached_wall(reader="jxa"):
    return {
        "reader": reader,
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": 3,
        "slides": [
            {"number": 1, "index": 0, "items": []},
            {"number": 2, "index": 1, "skipped": True, "items": []},
            {"number": 3, "index": 2, "items": []},
        ],
    }


@pytest.mark.parametrize("reader", ["jxa", "offline"])
def test_complete_cached_wall_payload_accepts_supported_readers(reader):
    from obed_edom.web.app import _complete_cached_wall_payload

    assert _complete_cached_wall_payload(_cached_wall(reader)) is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("reader"),
        lambda payload: payload.update(reader="other"),
        lambda payload: payload.update(slideCount=2),
        lambda payload: payload.update(slideCount="3"),
        lambda payload: payload.update(slideCount=3.0),
        lambda payload: payload.update(slideCount=True),
        lambda payload: payload["slides"][1].update(number=3),
        lambda payload: payload["slides"][1].update(number="2"),
        lambda payload: payload["slides"][1].update(number=2.0),
        lambda payload: payload["slides"][1].update(number=True),
        lambda payload: payload["slides"][1].update(index="1"),
        lambda payload: payload["slides"][1].update(index=1.0),
        lambda payload: payload["slides"][1].update(index=True),
        lambda payload: payload["slides"].pop(),
    ],
)
def test_complete_cached_wall_payload_rejects_partial_or_malformed_payloads(mutate):
    from obed_edom.web.app import _complete_cached_wall_payload

    payload = _cached_wall()
    mutate(payload)
    assert _complete_cached_wall_payload(payload) is False


def test_ranged_propose_reuses_complete_cache_without_renumbering_or_mutating_it(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    cached = _cached_wall("offline")
    original = copy.deepcopy(cached)
    seen = {"inspects": [], "acquires": []}
    logs = []

    def fake_acquire(source, *, slide_range, mode, say):
        seen["acquires"].append((Path(source), slide_range))
        return cached

    def fake_inspect(path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None):
        seen["inspects"].append((Path(path), {
            "export_dir": export_dir, "slide_range": slide_range,
            "use_cache": use_cache, "is_cancelled": is_cancelled,
        }))
        assert Path(path) == template
        return {"slideWidth": 1920, "slideHeight": 1080, "slides": []}

    def fake_propose(_wall, _template, **kwargs):
        seen["proposal"] = kwargs
        return {
            "wallDigests": ["d1", "d2", "d3"],
            "templateDigest": "template",
            "pages": [{"slide": 3, "index": 2, "noUsableFraming": False}],
        }

    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": True})
    monkeypatch.setattr(
        app_mod,
        "load_framings",
        lambda *_args: {
            "wallDigests": ["d1", "d2", "d3"],
            "templateDigest": "template",
            "decisions": [{"wallIndex": 2, "state": "pinned", "templateSlide": 9}],
        },
    )
    monkeypatch.setattr(
        app_mod,
        "deck_slide_digests",
        lambda payload: [f"d{slide['number']}" for slide in payload["slides"]],
    )
    monkeypatch.setattr(app_mod, "deck_digest", lambda _path: "template")

    result = app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(), wall, template, frozenset({2}), False
    )

    proposal = seen["proposal"]
    assert [slide["number"] for slide in proposal["wall_payload"]["slides"]] == [3]
    assert [slide["number"] for slide in proposal["full_wall_payload"]["slides"]] == [1, 2, 3]
    assert proposal["wall_payload"]["slides"][0] is not proposal["full_wall_payload"]["slides"][2]
    assert proposal["slide_range"] == frozenset({3})
    assert seen["acquires"] == [(wall, None)]
    assert seen["inspects"] == [(template, {
        "export_dir": None, "slide_range": None, "use_cache": None, "is_cancelled": None,
    })]
    assert result["pages"][0]["index"] == 2
    assert result["pages"][0]["decision"]["wallIndex"] == 2
    assert result["pages"][0]["decision"]["templateSlide"] == 9
    assert result["slideRange"] == [3]
    assert result["slideRangeTyped"] == [2]
    assert "Skip Slide" in result["numberingNote"]
    assert cached == original


def test_ranged_propose_falls_back_for_malformed_cache_and_rejects_valid_cache_overflow(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    logs = []

    monkeypatch.setattr(
        app_mod, "acquire_wall_payload", lambda source, *, slide_range, mode, say: _cached_wall()
    )
    monkeypatch.setattr(
        app_mod, "inspect_keynote",
        lambda path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None: {
            "slideWidth": 1920, "slideHeight": 1080, "slides": []
        },
    )
    monkeypatch.setattr(
        app_mod,
        "propose_framings",
        lambda *_args, **_kwargs: {"wallDigests": [], "templateDigest": "", "pages": []},
    )
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": False})

    # _cached_wall() shows 2 visible slides (slide 2 is Skip Slide); a range past that
    # must reject against the navigator count before any template read.
    with pytest.raises(RuntimeError, match="shows 2 slides"):
        app_mod._run_resize_propose(
            type("Job", (), {"log": logs.append})(), wall, template, frozenset({4}), False
        )


def test_ranged_propose_rejects_navigator_range_past_visible_slides(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    monkeypatch.setattr(
        app_mod, "acquire_wall_payload", lambda source, *, slide_range, mode, say: _cached_wall()
    )
    def fail_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None,
                      is_cancelled=None):
        pytest.fail("valid navigator range must reject before the template read")

    monkeypatch.setattr(app_mod, "inspect_keynote", fail_inspect)

    logs: list[str] = []
    with pytest.raises(RuntimeError, match="shows 2 slides"):
        app_mod._run_resize_propose(
            type("Job", (), {"log": logs.append})(),
            wall,
            template,
            frozenset({3}),
            False,
        )


def test_health_and_stubs():
    client = TestClient(app)
    assert client.get("/api/health").json()["ok"] is True
    assert client.post("/api/dsk").status_code == 501
    missing = client.post("/api/resize")
    assert missing.status_code == 422
    missing_file = client.post("/api/resize", data={"path": "/no/such/deck.key"})
    assert missing_file.status_code == 400


def test_open_path_missing_is_404():
    client = TestClient(app)
    res = client.post("/api/open", data={"path": "/no/such/deck.key"})
    assert res.status_code == 404
    assert "Not found" in res.json()["detail"]


def test_open_path_launches_open(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    target = tmp_path / "deck.key"
    target.write_text("placeholder")
    calls = []
    monkeypatch.setattr(
        app_mod.subprocess, "run", lambda argv, **kw: calls.append(argv)
    )
    client = TestClient(app)
    res = client.post("/api/open", data={"path": str(target)})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert calls == [["open", str(target)]]


def test_open_path_rejects_app_bundle(tmp_path):
    client = TestClient(app)
    target = tmp_path / "Evil.app"
    target.mkdir()
    res = client.post("/api/open", data={"path": str(target)})
    assert res.status_code == 400
    assert "Not an openable artifact" in res.json()["detail"]


def test_open_path_rejects_non_artifact_suffix(tmp_path):
    client = TestClient(app)
    target = tmp_path / "run.sh"
    target.write_text("echo hi")
    res = client.post("/api/open", data={"path": str(target)})
    assert res.status_code == 400
    assert "Not an openable artifact" in res.json()["detail"]


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


def test_generate_rejects_pdf_upload(tmp_path):
    client = TestClient(app)
    template = tmp_path / "Sermon_GW.key"
    template.write_text("placeholder")
    res = client.post(
        "/api/generate",
        data={"lw_template": str(template)},
        files={"files": ("outline.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 400
    assert "expected .docx" in res.json()["detail"].lower()


def _write_cued_pdf(path: Path) -> Path:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    y = 800
    for line in (
        "[LW] [DSK-PP]",
        "Ezekiel 36:26 I will give you a new heart.",
        "[LW-TITLE]",
        "Faith",
    ):
        c.drawString(72, y, line)
        y -= 18
    c.save()
    return path


def test_outline_endpoint_accepts_pdf(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    client = TestClient(app)
    started = client.post("/api/outline", data={"path": str(path)})
    assert started.status_code == 200
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["kind"] == "outline"
    assert (result["lwCues"], result["dskCues"]) == (2, 1)


def test_outline_endpoint_rejects_unsupported_suffix(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("[LW] hello")
    client = TestClient(app)
    res = client.post("/api/outline", data={"path": str(path)})
    assert res.status_code == 400
    assert ".docx or .pdf" in res.json()["detail"].lower()


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


def test_settings_unrelated_change_does_not_revalidate_export_dir(monkeypatch, tmp_path):
    from obed_edom import settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda root=None: tmp_path / "settings.json")
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    client = TestClient(app)
    put = client.put("/api/settings", json={"defaultExportDir": str(export_dir)})
    assert put.status_code == 200

    # The stored export dir is now a file — re-validating it on an unrelated change
    # would 400 and would try to mkdir over it.
    export_dir.rmdir()
    export_dir.write_text("now a file")

    res = client.put("/api/settings", json={"reusePreviews": False})
    assert res.status_code == 200
    assert res.json()["reusePreviews"] is False
    assert export_dir.is_file()


def test_settings_rejects_private_root_export_dir(monkeypatch, tmp_path):
    from obed_edom import settings as settings_mod

    monkeypatch.setattr(settings_mod, "settings_path", lambda root=None: tmp_path / "settings.json")
    client = TestClient(app)
    from obed_edom.paths import output_root

    res = client.put("/api/settings", json={"defaultExportDir": str(output_root() / ".maps")})
    assert res.status_code == 400


def test_outline_endpoint_writes_findings_pdf_to_export_dir(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    export_dir = tmp_path / "exports"
    client = TestClient(app)
    started = client.post("/api/outline", data={"path": str(path), "export_dir": str(export_dir)})
    assert started.status_code == 200
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    outline_report = Path(job["result"]["outlineReport"])
    assert outline_report.parent == export_dir.resolve()
    assert outline_report.is_file()


def test_outline_export_dir_removed_between_submit_and_run_fails_the_job(tmp_path):
    from obed_edom.web.app import _run_outline
    from obed_edom.web.jobs import Job

    path = _write_cued_pdf(tmp_path / "cued.pdf")
    export_dir = tmp_path / "exports"  # never created — simulates removal before the job runs
    job = Job(id="job-1", kind="outline", result={"exportDir": str(export_dir)})

    with pytest.raises(ValueError, match="no longer exists"):
        _run_outline(job, path)


def test_outline_endpoint_rejects_private_root_export_dir(tmp_path):
    from obed_edom.paths import output_root

    path = _write_cued_pdf(tmp_path / "cued.pdf")
    client = TestClient(app)
    res = client.post(
        "/api/outline", data={"path": str(path), "export_dir": str(output_root() / ".outline")}
    )
    assert res.status_code == 400


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


def test_resize_asks_for_framings_before_remapping(tmp_path, monkeypatch):
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

    def fake_acquire(source, *, slide_range, mode, say):
        return {"slideWidth": 7680, "slideHeight": 1080, "slideCount": 1, "slides": []}

    def fake_inspect(path, **kwargs):
        return {"slideWidth": 1920, "slideHeight": 1080, "slides": []}

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

    monkeypatch.setattr(app_mod, "remap_and_inspect", fake_remap)
    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
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


def test_resize_apply_writes_cg_to_export_dir(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    seen = {}

    def fake_remap(path, dest, **kwargs):
        seen["dest"] = dest
        dest.write_text("cg")
        return {"dest": str(dest), "counts": {}, "applied": 1, "missed": 0}

    def fake_acquire(source, *, slide_range, mode, say):
        return {"slideWidth": 7680, "slideHeight": 1080, "slideCount": 1, "slides": []}

    def fake_inspect(path, **kwargs):
        return {"slideWidth": 1920, "slideHeight": 1080, "slides": []}

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
                {"slide": 1, "index": 0, "autoTemplateSlide": 2, "autoFellBack": False,
                 "needsAttention": False, "noUsableFraming": False, "candidates": []}
            ],
            "needAttention": [],
            "noUsableFraming": [],
        }

    monkeypatch.setattr(app_mod, "remap_and_inspect", fake_remap)
    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    client = TestClient(app)
    deck = tmp_path / "Wall.key"
    deck.write_text("placeholder")
    template = tmp_path / "Base_CG_Assets.key"
    template.write_text("placeholder")
    export_dir = tmp_path / "exports"
    started = client.post(
        "/api/resize",
        data={
            "path": str(deck),
            "template_path": str(template),
            "export": "false",
            "export_dir": str(export_dir),
        },
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    _wait(client, job_id)

    confirmed = client.post(f"/api/resize/{job_id}/apply")
    assert confirmed.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["dest"].parent == export_dir.resolve()
    assert Path(job["result"]["destPath"]).parent == export_dir.resolve()


def test_side_content_whitelist_and_undo_round_trip(tmp_path, monkeypatch):
    """Whitelisting a page keeps its side content on Apply, and un-whitelisting it
    (which drops it from the submitted set) actually reverts — the stale decision on
    the in-memory page must be cleared, or Apply keeps reading the old whitelist."""
    import obed_edom.web.app as app_mod

    seen = {}

    def fake_remap(path, dest, **kwargs):
        seen["side_content_slides"] = kwargs.get("side_content_slides")
        return {"dest": str(dest), "counts": {}, "applied": 1, "missed": 0}

    def fake_acquire(source, *, slide_range, mode, say):
        return {"slideWidth": 7680, "slideHeight": 1080, "slideCount": 1, "slides": []}

    def fake_inspect(path, **kwargs):
        return {"slideWidth": 1920, "slideHeight": 1080, "slides": []}

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
                {"slide": 1, "index": 0, "autoTemplateSlide": 2, "autoFellBack": False,
                 "needsAttention": False, "noUsableFraming": False, "candidates": []}
            ],
            "needAttention": [],
            "noUsableFraming": [],
        }

    monkeypatch.setattr(app_mod, "remap_and_inspect", fake_remap)
    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    client = TestClient(app)
    deck = tmp_path / "Wall.key"
    deck.write_text("placeholder")
    template = tmp_path / "Base_CG_Assets.key"
    template.write_text("placeholder")
    started = client.post(
        "/api/resize",
        data={"path": str(deck), "template_path": str(template), "export": "false"},
    )
    job_id = started.json()["id"]
    _wait(client, job_id)

    # Whitelist the auto page, then apply: its side content is kept.
    client.post(
        f"/api/resize/{job_id}/apply",
        json={"decisions": [{"wallIndex": 0, "state": "auto", "keepSideContent": True}]},
    )
    _wait(client, job_id)
    assert seen["side_content_slides"] == {1}

    # Un-whitelist: the page is back on the default, so collect() omits it and the
    # submitted set is empty. Apply must now drop the side content again.
    client.post(f"/api/resize/{job_id}/apply", json={"decisions": []})
    _wait(client, job_id)
    assert seen["side_content_slides"] == set()


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


def test_diagnostics_endpoint_404_without_a_diagnostics_path():
    from obed_edom.web.app import RUNNER
    from obed_edom.web.jobs import Job

    job = Job(id="diag-missing", kind="diff", result={})
    RUNNER._jobs[job.id] = job
    client = TestClient(app)
    assert client.get(f"/api/jobs/{job.id}/diagnostics").status_code == 404
    assert client.post(f"/api/jobs/{job.id}/diagnostics/reveal").status_code == 404


def test_diagnostics_endpoint_serves_the_file_with_a_dated_filename():
    from obed_edom.diagnostics import DiagnosticsWriter
    from obed_edom.inspect import diff_work_dir
    from obed_edom.web.app import RUNNER
    from obed_edom.web.jobs import Job

    job_id = "diag-ready"
    diag_path = diff_work_dir(job_id) / "diagnostics.jsonl"
    with DiagnosticsWriter(diag_path) as diag:
        diag.header(leftLabel="LW", rightLabel="DSK")

    job = Job(id=job_id, kind="diff", result={"diagnosticsPath": str(diag_path)})
    RUNNER._jobs[job.id] = job
    client = TestClient(app)
    res = client.get(f"/api/jobs/{job.id}/diagnostics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")
    date = time.strftime("%Y-%m-%d", time.localtime(job.created_at))
    assert f"sermon-diagnostics-{date}-{job.id}.jsonl" in res.headers["content-disposition"]
    first_line = res.text.splitlines()[0]
    assert json.loads(first_line)["kind"] == "header"


def test_diagnostics_reveal_runs_open_dash_r_without_a_shell(monkeypatch):
    from obed_edom.inspect import diff_work_dir
    from obed_edom.web.app import RUNNER
    from obed_edom.web.jobs import Job

    job_id = "diag-reveal"
    diag_path = (diff_work_dir(job_id) / "diagnostics.jsonl").resolve()
    diag_path.write_text('{"kind": "header", "schema": 1}\n', encoding="utf-8")
    job = Job(id=job_id, kind="diff", result={"diagnosticsPath": str(diag_path)})
    RUNNER._jobs[job.id] = job

    calls = []
    monkeypatch.setattr(
        "obed_edom.web.app.subprocess.run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    client = TestClient(app)
    res = client.post(f"/api/jobs/{job.id}/diagnostics/reveal")
    assert res.status_code == 200
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (["open", "-R", str(diag_path)],)
    assert kwargs == {"check": False}


def test_diagnostics_endpoints_404_when_the_result_path_escapes_the_work_dir(tmp_path):
    """`result` is client-patchable via PATCH /api/jobs/{id}; a diagnosticsPath pointing
    outside the job's own work dir must never be served or revealed."""
    from obed_edom.web.app import RUNNER
    from obed_edom.web.jobs import Job

    outside = tmp_path / "not-diagnostics.jsonl"
    outside.write_text('{"kind": "header", "schema": 1}\n', encoding="utf-8")

    job = Job(id="diag-escaped", kind="diff", result={"diagnosticsPath": str(outside)})
    RUNNER._jobs[job.id] = job
    client = TestClient(app)
    assert client.get(f"/api/jobs/{job.id}/diagnostics").status_code == 404
    assert client.post(f"/api/jobs/{job.id}/diagnostics/reveal").status_code == 404


def test_diagnostics_endpoints_404_when_the_canonical_file_is_a_symlink():
    """Replacing the canonical `diagnostics.jsonl` with a symlink must not be served
    or revealed, even though its resolved path matches the expected location."""
    from obed_edom.inspect import diff_work_dir
    from obed_edom.web.app import RUNNER
    from obed_edom.web.jobs import Job

    job_id = "diag-symlinked"
    work_dir = diff_work_dir(job_id)
    secret = work_dir.parent / "secret.txt"
    secret.write_text("do not touch", encoding="utf-8")
    diag_path = work_dir / "diagnostics.jsonl"
    diag_path.symlink_to(secret)

    job = Job(id=job_id, kind="diff", result={"diagnosticsPath": str(diag_path)})
    RUNNER._jobs[job.id] = job
    client = TestClient(app)
    assert client.get(f"/api/jobs/{job.id}/diagnostics").status_code == 404
    assert client.post(f"/api/jobs/{job.id}/diagnostics/reveal").status_code == 404


def test_run_diff_check_discards_diagnostics_when_the_writer_dies_mid_run(tmp_path, monkeypatch):
    """A writer that fails partway through must not be published as though it succeeded:
    the log line and the diagnosticsPath should both reflect the failure."""
    import obed_edom.web.app as app_module
    from obed_edom.web.jobs import Job

    left_inspect = tmp_path / "left.json"
    right_inspect = tmp_path / "right.json"
    left_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")
    right_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")

    class DyingWriter:
        def __init__(self, path):
            self.path = Path(path)
            self.error = None

        def commit(self):
            self.error = "I/O operation on closed file."
            return False

        def close(self):
            self.error = self.error or "I/O operation on closed file."

    def fake_compare_inspects(*args, **kwargs):
        return {"flags": [], "pairs": [], "sameType": True, "leftCatalog": [], "rightCatalog": []}

    monkeypatch.setattr(app_module, "DiagnosticsWriter", DyingWriter)
    monkeypatch.setattr(app_module, "compare_inspects", fake_compare_inspects)

    job = Job(
        id="diag-dies",
        kind="diff",
        result={
            "leftInspect": str(left_inspect),
            "rightInspect": str(right_inspect),
            "leftPreviews": str(tmp_path),
            "rightPreviews": str(tmp_path),
            "heatDir": str(tmp_path / "heat"),
            "workDir": str(tmp_path),
            "pairs": [],
        },
    )
    result = app_module._run_diff_check(job)

    assert result["diagnosticsPath"] is None
    assert any("Diagnostics were incomplete" in msg for msg in job.logs)


def test_run_diff_check_ignores_a_patched_external_work_dir(tmp_path, monkeypatch):
    """`result["workDir"]` is client-patchable via PATCH /api/jobs/{id}; the diagnostics
    file must always land under the server-owned `diff_work_dir(job.id)`, never wherever
    a patched `workDir` points."""
    import obed_edom.web.app as app_module
    from obed_edom.inspect import diff_work_dir
    from obed_edom.web.jobs import Job

    left_inspect = tmp_path / "left.json"
    right_inspect = tmp_path / "right.json"
    left_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")
    right_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")

    outside_work_dir = tmp_path / "attacker-controlled"
    outside_work_dir.mkdir()

    def fake_compare_inspects(*args, **kwargs):
        return {"flags": [], "pairs": [], "sameType": True, "leftCatalog": [], "rightCatalog": []}

    monkeypatch.setattr(app_module, "compare_inspects", fake_compare_inspects)

    job = Job(
        id="diag-workdir-spoof",
        kind="diff",
        result={
            "leftInspect": str(left_inspect),
            "rightInspect": str(right_inspect),
            "leftPreviews": str(tmp_path),
            "rightPreviews": str(tmp_path),
            "heatDir": str(tmp_path / "heat"),
            "workDir": str(outside_work_dir),
            "pairs": [],
        },
    )
    result = app_module._run_diff_check(job)

    canonical = diff_work_dir(job.id) / "diagnostics.jsonl"
    assert result["diagnosticsPath"] == str(canonical)
    assert canonical.is_file()
    assert not any(outside_work_dir.iterdir())


def test_diagnostics_writer_refuses_to_write_through_a_symlink(tmp_path):
    """A pre-existing symlink at the canonical diagnostics path must be treated as a
    writer failure — the target is never followed and truncated."""
    from obed_edom.diagnostics import DiagnosticsWriter

    secret = tmp_path / "secret.txt"
    secret.write_text("do not touch", encoding="utf-8")
    diag_path = tmp_path / "diagnostics.jsonl"
    diag_path.symlink_to(secret)

    with pytest.raises(OSError):
        DiagnosticsWriter(diag_path)

    assert secret.read_text(encoding="utf-8") == "do not touch"


def test_run_diff_check_discards_diagnostics_when_the_path_is_unwritable(tmp_path, monkeypatch):
    """The diagnostics path is computed without creating any directories; if its
    parent can't be created (e.g. a file sits where a directory is needed), the
    check pass must still complete with diagnosticsPath=None, not raise."""
    import obed_edom.web.app as app_module
    from obed_edom.web.jobs import Job

    left_inspect = tmp_path / "left.json"
    right_inspect = tmp_path / "right.json"
    left_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")
    right_inspect.write_text(json.dumps({"slides": []}), encoding="utf-8")

    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    unusable = blocker / "job" / "diagnostics.jsonl"

    def fake_compare_inspects(*args, **kwargs):
        return {"flags": [], "pairs": [], "sameType": True, "leftCatalog": [], "rightCatalog": []}

    monkeypatch.setattr(app_module, "_diagnostics_path", lambda job_id: unusable)
    monkeypatch.setattr(app_module, "compare_inspects", fake_compare_inspects)

    job = Job(
        id="diag-unwritable",
        kind="diff",
        result={
            "leftInspect": str(left_inspect),
            "rightInspect": str(right_inspect),
            "leftPreviews": str(tmp_path),
            "rightPreviews": str(tmp_path),
            "heatDir": str(tmp_path / "heat"),
            "workDir": str(tmp_path),
            "pairs": [],
        },
    )
    result = app_module._run_diff_check(job)

    assert result["diagnosticsPath"] is None
    assert any("Could not open diagnostics file" in msg for msg in job.logs)


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


def test_relocate_maps_job_is_rejected():
    """Maps jobs never relocate: their outputDir is stable and stateRevision-gated
    writes go through POST /api/maps/{id}/state, not the generic relocate endpoint."""
    client = TestClient(app)
    job = client.post("/api/maps").json()
    response = client.post(f"/api/jobs/{job['id']}/relocate", json={"folder": "/tmp"})
    assert response.status_code == 409, response.text
    assert "state" in response.json()["detail"]


def test_patch_name_returns_public_dict_with_new_name(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    client = TestClient(app)
    started = client.post("/api/outline", data={"path": str(path)})
    job = _wait(client, started.json()["id"])

    target = f"quiet-jordan-{job['id']}"
    renamed = client.patch(f"/api/jobs/{job['id']}/name", json={"name": target})
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == target
    assert body["id"] == job["id"]
    assert "artifacts" in body


def test_patch_name_rejects_invalid_name(tmp_path):
    path = _write_cued_pdf(tmp_path / "cued.pdf")
    client = TestClient(app)
    started = client.post("/api/outline", data={"path": str(path)})
    job = _wait(client, started.json()["id"])

    res = client.patch(f"/api/jobs/{job['id']}/name", json={"name": "../evil"})
    assert res.status_code == 400


def test_patch_name_404_on_unknown_job():
    client = TestClient(app)
    res = client.patch("/api/jobs/not-a-real-job/name", json={"name": "quiet-jordan"})
    assert res.status_code == 404


def _propose_stubs(monkeypatch, tmp_path):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    monkeypatch.setattr(
        app_mod, "acquire_wall_payload", lambda source, *, slide_range, mode, say: _cached_wall()
    )
    monkeypatch.setattr(
        app_mod, "inspect_keynote",
        lambda path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None: {
            "slideWidth": 1920, "slideHeight": 1080, "slides": []
        },
    )
    monkeypatch.setattr(
        app_mod, "propose_framings",
        lambda *_args, **_kwargs: {"wallDigests": [], "templateDigest": "", "pages": []},
    )
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": False})
    return app_mod, wall, template


def test_resize_propose_stores_resolved_export_dir_with_no_override(tmp_path, monkeypatch):
    from obed_edom.paths import output_root

    app_mod, wall, template = _propose_stubs(monkeypatch, tmp_path)
    logs: list[str] = []
    result = app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(), wall, template, None, False
    )
    assert "exportDir" not in result
    assert result["resolvedExportDir"] == str(output_root())


def test_resize_propose_stores_resolved_export_dir_with_override(tmp_path, monkeypatch):
    app_mod, wall, template = _propose_stubs(monkeypatch, tmp_path)
    override = tmp_path / "chosen"
    override.mkdir()
    logs: list[str] = []
    result = app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(),
        wall, template, None, False, export_dir=str(override),
    )
    assert result["exportDir"] == str(override)
    assert result["resolvedExportDir"] == str(override)


def test_resize_apply_uses_the_resolved_export_dir_frozen_at_propose_time(
    tmp_path, monkeypatch
):
    """A Settings default change between propose and apply must not silently redirect
    the write — apply uses the effective destination captured on the proposal, not a
    fresh `export_destination(job)` lookup."""
    import obed_edom.web.app as app_mod

    frozen_dest = tmp_path / "frozen"
    frozen_dest.mkdir()
    later_default = tmp_path / "later-default"
    later_default.mkdir()

    def fake_remap_and_inspect(path, dest, *, export_dir=None, **_kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        return {
            "inspect": {"slideWidth": 1920, "slideHeight": 1080, "slideCount": 0, "exported": False},
            "payload": {"path": str(dest), "slideWidth": 1920, "slideHeight": 1080, "slides": []},
            "counts": {},
            "applied": 0,
            "missed": 0,
        }

    monkeypatch.setattr(app_mod, "remap_and_inspect", fake_remap_and_inspect)
    # If apply re-resolved the destination instead of using the frozen value, it would
    # land here instead.
    from obed_edom import settings as settings_mod

    monkeypatch.setattr(
        settings_mod, "load_settings", lambda *a, **k: {"defaultExportDir": str(later_default)}
    )

    job = type(
        "Job",
        (),
        {"log": lambda self, msg: None, "name": "job", "result": {"resolvedExportDir": str(frozen_dest)}},
    )()
    result = app_mod._run_resize(
        job, tmp_path / "source.key", tmp_path / "template.key", None, False
    )
    assert Path(result["destPath"]).parent == frozen_dest


def test_write_outline_pdf_propagates_a_vanished_destination_as_job_error(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    vanished = tmp_path / "gone"  # never created
    logs: list[str] = []
    job = type("Job", (), {"log": logs.append})()
    with pytest.raises(ValueError, match="no longer a directory"):
        app_mod._write_outline_pdf(job, vanished / "findings.pdf", {"rows": [], "outlineFlags": []})
    assert not logs
