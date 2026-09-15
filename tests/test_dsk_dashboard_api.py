"""API tests for the DSK Generator (P3) and Exporter (P4) dashboard endpoints.

Everything Keynote-shaped is monkeypatched: `assemble_dsk_deck`, `export_slide_clips`,
`export_stage_pngs`, `stage_counts`, `classify_deck` and `build_preview_thumbs` are all
faked, mirroring `tests/test_dashboard_api.py`'s resize tests. No test may start Keynote.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obed_edom.dsk_plan import SlideClass
from obed_edom.web.app import app


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


def _wait(client, job_id, tries=120):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _cls(number, category, *, is_text=False, build_count=0, movie_count=0):
    return SlideClass(
        number=number,
        category=category,
        build_count=build_count,
        movie_count=movie_count,
        kept=(("shape", 0),),
        dropped_side=(),
        dropped_backdrop=(),
        transition=None,
        is_text=is_text,
    )


def _fw_payload(count=5):
    return {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": count,
        "slides": [{"number": n, "index": n - 1, "items": []} for n in range(1, count + 1)],
    }


def _dsk_payload(count=5):
    return {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": count,
        "slides": [{"number": n, "index": n - 1, "items": []} for n in range(1, count + 1)],
    }


def _patch_common(monkeypatch, app_mod, *, classes, thumbs=None):
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: list(classes.values()))
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: thumbs or {})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _p: "digest")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _d: Path("/tmp/thumbs"))


def _propose_dsk(client, deck, **extra):
    data = {"path": str(deck), **extra}
    return client.post("/api/dsk", data=data)


def test_dsk_propose_marks_text_and_empty_slides_skipped(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {
        1: _cls(1, "static"),
        2: _cls(2, "static", is_text=True),
        3: _cls(3, "empty"),
    }
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    started = _propose_dsk(client, deck)
    assert started.status_code == 200
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["phase"] == "review"
    assert result["contentOnly"] is True
    skipped = {(s["slide"], s["reason"]) for s in result["skipped"]}
    assert skipped == {(2, "text"), (3, "empty")}
    pages = {p["slide"]: p for p in result["pages"]}
    assert set(pages) == {1, 2}
    assert pages[1]["decision"]["include"] is True
    # A text page defaults to excluded under content-only.
    assert pages[2]["isText"] is True
    assert pages[2]["decision"]["include"] is False


def test_dsk_decisions_cannot_include_a_text_page_in_content_only(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "static", is_text=True)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)

    res = client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 2, "include": True}]},
    )
    assert res.status_code == 200
    pages = {p["slide"]: p for p in res.json()["result"]["pages"]}
    assert pages[2]["decision"]["include"] is False


def test_dsk_decisions_roundtrip_survives_re_propose(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "keepSide": True, "anchor": "left"}]},
    )
    job = client.get(f"/api/jobs/{job_id}").json()
    pages = {p["slide"]: p for p in job["result"]["pages"]}
    assert pages[1]["decision"]["keepSide"] is True
    assert pages[1]["decision"]["anchor"] == "left"
    assert pages[2]["needsClip"] is True


def test_dsk_apply_passes_content_only_and_derived_fields(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    clip = tmp_path / "clip.mov"
    clip.write_text("movie")
    seen = {}

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        seen["export_clips"] = (list(slides), kwargs)
        from obed_edom.dsk_movie_export import ClipResult

        return [ClipResult(slide=2, path=clip, width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920)]

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **kwargs):
        seen["assemble"] = {
            "decisions": decisions,
            "clips": clips,
            "content_only": content_only,
        }
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path,
            slides_kept=(1, 2),
            ordinals={1: 1, 2: 2},
            fits={},
            clips_inserted={2: clip},
            stroke={},
            zorder={},
            builds={},
            size_bytes=10,
            source_size_bytes=20,
            wall_s=1.0,
            warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "keepSide": True, "anchor": "right"}]},
    )
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["phase"] == "done"
    assert seen["assemble"]["content_only"] is True
    assert seen["assemble"]["decisions"][1].keep_side is True
    assert seen["assemble"]["decisions"][1].anchor == "right"
    assert seen["assemble"]["decisions"][2].action == "both"
    assert seen["export_clips"][0] == [2]
    assert 2 in seen["assemble"]["clips"]
    # dsk output lands under output/<FW stem>/dsk/<stem>_DSK.key
    assert Path(job["result"]["deckPath"]).name == "GW_DSK.key"
    assert Path(job["result"]["deckPath"]).parent.name == "dsk"


def test_dsk_apply_409_when_keynote_is_open(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: True)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    res = client.post(f"/api/dsk/{job_id}/apply")
    assert res.status_code == 409
    assert "keynote" in res.json()["detail"].lower()


def test_dsk_thumb_path_traversal_refused(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: list(classes.values()))
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: {1: "0001.jpg"})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _p: "digest")
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    (thumb_dir / "0001.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _d: thumb_dir)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    ok = client.get(f"/api/dsk/{job_id}/thumb/0001.jpg")
    assert ok.status_code == 200
    bad = client.get(f"/api/dsk/{job_id}/thumb/../secrets.txt")
    assert bad.status_code in {400, 404}


def test_dsk_export_stage_pngs_any_1920_deck(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "hand_built_DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1, 2: 1})

    seen = {}

    def fake_export_stage_pngs(deck_path, slides, out_dir, **kwargs):
        seen["export"] = (deck_path, list(slides), kwargs)
        from obed_edom.dsk_stage_export import StageAsset

        return [
            StageAsset(
                slide=n, stage_index=1, path=Path(out_dir) / f"{n:04d}.001.png",
                width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
                content_alpha_frac=1.0, transparent_frac=0.0, source_name="x",
            )
            for n in slides
        ]

    monkeypatch.setattr(app_mod, "export_stage_pngs", fake_export_stage_pngs)

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck)})
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["result"]["isStageDeck"] is True
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["phase"] == "done"
    assert seen["export"][1] == [1, 2]


def test_dsk_export_clip_refuses_a_non_fw_deck(tmp_path, monkeypatch):
    """Clip export is FW-only; the exporter has no clip-export endpoint of its own
    (§2.3) -- the FW-only refusal instead guards a stage export accidentally pointed
    at a deck that is not 1920x1080."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "Wall_FW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck)})
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["result"]["isStageDeck"] is False
    assert job["result"]["isFwDeck"] is True
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "1920x1080" in (job.get("error") or "")


def test_dsk_export_requires_slides_selected(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app)
    job_id = client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/export/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "include": False}]},
    )
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "no slides selected" in (job.get("error") or "").lower()


def test_dsk_export_tag_allowed_by_validate_keynote(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "DSK.key"
    deck.write_text("placeholder")

    def fake_inspect(job, path, export, slide_range, *, outline=None, lw_final=True):
        return {"path": str(path), "flags": []}

    monkeypatch.setattr(app_mod, "_run_inspect", fake_inspect)
    client = TestClient(app)
    started = client.post(
        "/api/validate-keynote", data={"path": str(deck), "feature": "dsk-export"}
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["feature"] == "dsk-export"
