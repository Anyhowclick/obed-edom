import json
import shutil
import subprocess
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from obed_edom.maps_geo import CG_MIN_ZOOM, WORLD_MIN_ZOOM, camera_dict
from obed_edom.maps_keynote import export_maps_job, maps_export_plan
from obed_edom.web.app import RUNNER, app

client = TestClient(app)


def _wait(job_id, tries=120):
    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _seed():
    started = client.post("/api/maps")
    assert started.status_code == 200
    job = _wait(started.json()["id"])
    assert job["status"] == "done", job.get("error")
    return job


def _doc(job):
    result = job["result"]
    return {
        "defaultStyle": result["defaultStyle"],
        "crop": result["crop"],
        "exportLw": result["exportLw"],
        "exportCg": result["exportCg"],
        "slides": result["slides"],
        "links": result["links"],
    }


def _save(job, document):
    latest = client.get(f"/api/jobs/{job['id']}")
    assert latest.status_code == 200, latest.text
    revision = int(latest.json()["result"].get("stateRevision") or 0)
    return client.post(
        f"/api/maps/{job['id']}/state",
        json={"expectedRevision": revision, "document": document},
    )


def test_post_maps_seeds_under_output_root_without_dest():
    job = _seed()
    result = job["result"]
    assert "destPath" not in result
    assert result["exportLw"] is True
    assert result["exportCg"] is True
    assert result["hiddenLayers"] == ["roadnames", "arrows"]
    assert result["slides"][0]["hiddenLayers"] == ["roadnames", "arrows"]
    assert result["slides"][0]["id"] == "s1"
    assert result["previewDir"].endswith("/previews")
    assert "/.maps/" in result["outputDir"].replace("\\", "/")
    assert result["slides"][0]["camera"]["zoom"] >= CG_MIN_ZOOM
    assert result["slides"][0]["camera"]["zoom"] < WORLD_MIN_ZOOM


def test_state_409_while_running_and_patch_409():
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.status = "running"
    res = _save(job, _doc(job))
    assert res.status_code == 409
    stored.status = "done"
    patched = client.patch(f"/api/jobs/{job['id']}", json={"result": result_keep(job)})
    assert patched.status_code == 409


def test_cancel_maps_export_is_idempotent_for_running_job():
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.status = "running"
    first = client.post(f"/api/maps/{job['id']}/cancel")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "running"
    second = client.post(f"/api/maps/{job['id']}/cancel")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "running"


def test_state_and_frame_ok_after_error():
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.status = "error"
    stored.error = "encode failed"
    saved = _save(job, _doc(job))
    assert saved.status_code == 200, saved.text
    framed = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=2&fps=30",
        content=_tiny_jpeg(),
        headers={"content-type": "image/jpeg"},
    )
    assert framed.status_code == 200, framed.text


def test_pin_label_visibility_round_trips_with_backward_compatible_default():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    slide["churches"] = [
        {"id": "p1", "name": "Visible by default", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#ff8a00"},
        {"id": "p2", "name": "Hidden", "lat": 4.0, "lon": 102.0, "kind": "dropPin", "color": "#c44a42", "showLabel": False},
    ]
    doc["slides"] = [slide]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    churches = saved.json()["result"]["slides"][0]["churches"]
    assert [church["showLabel"] for church in churches] == [True, False]


def result_keep(job):
    return dict(job["result"])


def test_easing_stripped_unless_movie():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "zoom": slide["camera"]["zoom"]}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "morph",
            "duration": 1.2,
            "playWithoutClick": False,
            "easing": "ease-in-out",
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    links = saved.json()["result"]["links"]
    assert "easing" not in links[0]


def test_fly_opts_stripped_unless_movie():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "zoom": slide["camera"]["zoom"]}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "morph",
            "duration": 1.2,
            "playWithoutClick": False,
            "easeIn": 0.4,
            "easeOut": 0.4,
            "flyZoom": 5.0,
            "flight": "phases",
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    links = saved.json()["result"]["links"]
    assert "easeIn" not in links[0]
    assert "easeOut" not in links[0]
    assert "flyZoom" not in links[0]
    assert "flight" not in links[0]


def test_movie_fly_opts_roundtrip():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "pitch": 40}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 2.0,
            "playWithoutClick": False,
            "easing": "ease-in-out",
            "easeIn": 0.6,
            "easeOut": 0.5,
            "flyZoom": 6.2,
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    link = saved.json()["result"]["links"][0]
    assert link["kind"] == "movie"
    assert link["easeIn"] == 0.6
    assert link["easeOut"] == 0.5
    assert link["flyZoom"] == 6.2


def test_movie_flight_roundtrips_with_curve():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "pitch": 40}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 2.0,
            "playWithoutClick": False,
            "flight": "arc",
            "curve": 1.8,
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    link = saved.json()["result"]["links"][0]
    assert link["flight"] == "arc"
    assert link["curve"] == 1.8


def test_movie_flight_rejects_invalid_value():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "pitch": 40}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 2.0,
            "playWithoutClick": False,
            "flight": "spiral",
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 400, saved.text


def test_dissolve_roundtrip():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["style"] = "dark"
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "dissolve",
            "duration": 0.8,
            "playWithoutClick": True,
            "easing": "ease-in-out",
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    link = saved.json()["result"]["links"][0]
    assert link["kind"] == "dissolve"
    assert link["duration"] == 0.8
    assert link["playWithoutClick"] is True
    assert "easing" not in link


def test_route_roundtrip_and_rejects_extra_keys():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Closer"
    other["camera"] = {**slide["camera"], "pitch": 40}
    doc["slides"] = [slide, other]
    doc["links"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 1.5,
            "playWithoutClick": False,
            "easing": "ease-out",
            "route": {"points": [{"lat": 1.3, "lon": 103.8}, {"lat": 3.1, "lon": 101.7}]},
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    route = saved.json()["result"]["links"][0]["route"]
    assert route == {"points": [{"lat": 1.3, "lon": 103.8}, {"lat": 3.1, "lon": 101.7}]}
    doc["links"][0]["route"] = {"points": [{"lat": 1.3, "lon": 103.8}, {"lat": 3.1, "lon": 101.7}], "extra": True}
    bad = _save(job, doc)
    assert bad.status_code == 400
    doc["links"][0]["route"] = {"points": [{"lat": 1.3, "lon": 103.8}]}
    short = _save(job, doc)
    assert short.status_code == 400


def test_hidden_layers_roundtrip():
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois", "shields"]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["hiddenLayers"] == ["pois", "shields"]


def test_per_slide_hidden_layers_roundtrip_and_demotes_morph():
    job = _seed()
    doc = _doc(job)
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    slide2["hiddenLayers"] = ["pois"]
    doc["slides"].append(slide2)
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["slides"][0]["hiddenLayers"] == ["roadnames", "arrows"]
    assert result["slides"][1]["hiddenLayers"] == ["pois"]
    assert result["links"][0]["kind"] == "cut"


def test_deck_hidden_layers_inherited_onto_unset_slides():
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois", "shields"]
    slide = dict(doc["slides"][0])
    slide.pop("hiddenLayers", None)
    doc["slides"] = [slide]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["slides"][0]["hiddenLayers"] == ["pois", "shields"]


def test_export_plan_still_matches_deck_hidden_layers():
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois", "shields"]
    slide = dict(doc["slides"][0])
    slide.pop("hiddenLayers", None)
    doc["slides"] = [slide]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    # /state normalises hiddenLayers onto slides on the way in, which leaves
    # nothing for /export-plan to inherit. Force the stored slide back to
    # un-normalised, modelling a legacy session restored from disk verbatim.
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.result["slides"][0]["hiddenLayers"] = None
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    assert plan.json()["stills"][0]["hiddenLayers"] == ["pois", "shields"]


def test_export_maps_job_inherits_deck_hidden_layers_for_legacy_document(monkeypatch):
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois", "shields"]
    slide = dict(doc["slides"][0])
    slide.pop("hiddenLayers", None)
    doc["slides"] = [slide]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    stored = RUNNER.get(job["id"])
    assert stored is not None
    # Legacy shape: JobRunner._load_sessions restores job.result verbatim, so a
    # session saved before per-slide hiddenLayers existed comes back with None.
    stored.result["slides"][0]["hiddenLayers"] = None

    route_plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert route_plan.status_code == 200, route_plan.text

    output_dir = Path(stored.result["outputDir"])
    (output_dir / "stills").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (20, 30, 40)).save(output_dir / "stills" / "s1.png", "PNG")

    real_export_plan = maps_export_plan
    captured_slides: list[list[dict]] = []

    def spy(slides, links, **kwargs):
        captured_slides.append([dict(s) for s in slides])
        return real_export_plan(slides, links, **kwargs)

    monkeypatch.setattr("obed_edom.maps_keynote.maps_export_plan", spy)
    monkeypatch.setattr(
        "obed_edom.maps_keynote.run_osascript",
        lambda script, **_k: subprocess.CompletedProcess(["osascript"], 0, stdout="ok", stderr=""),
    )
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])

    result = export_maps_job(stored, export_lw=True, export_cg=False)

    assert result.get("destPath", "").endswith(".key")
    assert captured_slides, "export_maps_job did not call maps_export_plan"
    assert captured_slides[0][0]["hiddenLayers"] == ["pois", "shields"]
    assert captured_slides[0][0]["hiddenLayers"] == route_plan.json()["stills"][0]["hiddenLayers"]


def test_explicit_empty_slide_layers_survive_a_deck_value():
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois"]
    slide = dict(doc["slides"][0])
    slide["hiddenLayers"] = []
    doc["slides"] = [slide]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["slides"][0]["hiddenLayers"] == []


def test_bootstrap_csv_preserves_empty_deck_layers(monkeypatch):
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.result["hiddenLayers"] = []
    monkeypatch.setattr("obed_edom.maps_geo.requests.get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Nominatim")))
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name\nSingapore\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    new_slide = next(s for s in done["result"]["slides"] if s["id"] != "s1")
    assert new_slide["hiddenLayers"] == []


def test_bootstrap_csv_infers_hop_kind_against_deck_resolved_legacy_slide(monkeypatch):
    """Legacy stored deck: deck hiddenLayers != DEFAULT, slides[0].hiddenLayers is None (as
    JobRunner._load_sessions would restore it verbatim). The new CSV slide is deck-resolved by
    _row_slide; s1 must be resolved the same way before infer_hop_kind compares them."""
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    camera = camera_dict(1.3521, 103.8198, 13)
    stored.result["hiddenLayers"] = ["pois"]
    stored.result["slides"][0]["camera"] = camera
    stored.result["slides"][0]["hiddenLayers"] = None
    monkeypatch.setattr("obed_edom.maps_geo.requests.get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Nominatim")))
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name,lat,lon\nSingapore,1.3521,103.8198\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    assert done["result"]["links"][0]["kind"] == "morph"


def test_slide_hillshade_roundtrip_and_demotes_morph():
    job = _seed()
    doc = _doc(job)
    assert doc["slides"][0].get("hillshade") is False
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    slide2["hillshade"] = True
    doc["slides"].append(slide2)
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["slides"][0]["hillshade"] is False
    assert result["slides"][1]["hillshade"] is True
    assert result["links"][0]["kind"] == "cut"


def test_manual_movie_survives_state_save_on_appearance_mismatch():
    job = _seed()
    doc = _doc(job)
    assert doc["slides"][0].get("hillshade") is False
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    slide2["hillshade"] = True
    doc["slides"].append(slide2)
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.2, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["links"][0]["kind"] == "movie"


def test_geocode_empty_and_ua_and_429(monkeypatch):
    empty = client.get("/api/maps/geocode?q=")
    assert empty.status_code == 400

    captured = {}

    class Limited:
        status_code = 429
        ok = False

        def json(self):
            return []

    def fake_get(url, headers=None, **_k):
        captured["ua"] = (headers or {}).get("User-Agent")
        return Limited()

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", fake_get)
    limited = client.get("/api/maps/geocode?q=xyzzy-not-a-real-place-zzzz")
    assert limited.status_code == 429
    assert captured["ua"].startswith("Obed-Edom-Maps/1.0")


def test_kl_geocode_does_not_call_nominatim(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Nominatim")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    res = client.get("/api/maps/geocode?q=KL")
    assert res.status_code == 200
    assert res.json()["source"] == "places"


def test_png_rejects_unknown_slide_and_accepts_s1():
    job = _seed()
    bad = client.post(f"/api/maps/{job['id']}/png?slideId=nope", content=b"png")
    assert bad.status_code == 400
    ok = client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=_landmark_png())
    assert ok.status_code == 200
    still = next(s for s in ok.json()["result"]["slides"] if s["id"] == "s1")
    assert still["stillPng"] == "s1.png"


def test_frame_rejects_unknown_slide():
    job = _seed()
    bad = client.post(
        f"/api/maps/{job['id']}/frame?slideId=nope&index=0&count=1&fps=30",
        content=b"jpg-bytes",
        headers={"content-type": "image/jpeg"},
    )
    assert bad.status_code == 400


def test_frame_writes_frames_and_meta_and_wipes_on_index_zero():
    job = _seed()
    out = Path(job["result"]["outputDir"])
    first_frame = _tiny_jpeg()
    res = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=3&fps=30",
        content=first_frame,
        headers={"content-type": "image/jpeg"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "index": 0, "count": 3}
    frame_dir = out / "frames" / "s1"
    assert (frame_dir / "00000.jpg").read_bytes() == first_frame
    meta = json.loads((frame_dir / "meta.json").read_text())
    assert meta == {"fps": 30, "count": 3, "duration": 0.1}
    stale = frame_dir / "stale.jpg"
    stale.write_bytes(b"stale")
    second_frame = _tiny_jpeg()
    res2 = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=2&fps=30",
        content=second_frame,
        headers={"content-type": "image/jpeg"},
    )
    assert res2.status_code == 200
    assert not stale.exists()
    assert (frame_dir / "00000.jpg").read_bytes() == second_frame


def test_bootstrap_csv_queues_then_adds_slides(monkeypatch):
    job = _seed()

    def boom(*_a, **_k):
        raise AssertionError("Nominatim")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name\nKuala Lumpur\nSingapore\n", "replace": "false"},
    )
    assert started.status_code == 200
    assert started.json()["status"] in {"queued", "running", "done"}
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    ids = [s["id"] for s in done["result"]["slides"]]
    assert ids[0] == "s1"
    assert len(ids) == 3


def test_bootstrap_csv_replace_clears_prior_outputs(monkeypatch):
    job = _seed()
    stored = RUNNER.get(job["id"])
    assert stored is not None
    output_dir = Path(job["result"]["outputDir"])
    stale_deck = output_dir / "old.key"
    stale_preview = Path(job["result"]["previewDir"]) / "s1.png"
    stale_deck.write_bytes(b"old deck")
    stale_preview.write_bytes(b"old preview")
    stored.result.update(
        {
            "destPath": str(stale_deck),
            "flags": [{"message": "old validation"}],
            "previewFiles": {"maps": ["s1.png"]},
        }
    )
    monkeypatch.setattr("obed_edom.maps_geo.requests.get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Nominatim")))
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name\nSingapore\n", "replace": "true"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    assert "destPath" not in done["result"]
    assert "flags" not in done["result"]
    assert done["result"]["previewFiles"] == {"maps": []}
    assert not stale_deck.exists()
    assert not stale_preview.exists()


def test_bootstrap_csv_can_add_pins_to_one_slide(monkeypatch):
    job = _seed()
    monkeypatch.setattr("obed_edom.maps_geo.requests.get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("Nominatim")))
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name\nKuala Lumpur\nSingapore\n", "targetSlideId": "s1", "audience": "lw"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    pins = done["result"]["slides"][0]["churches"]
    assert [pin["id"] for pin in pins] == ["p1", "p2"]
    assert [pin["name"] for pin in pins] == ["Kuala Lumpur", "Singapore"]


def test_maps_session_roundtrip_includes_preview_and_tile_cache(tmp_path, monkeypatch):
    tile_root = tmp_path / "tile-cache"
    tile_root.mkdir()
    monkeypatch.setattr("obed_edom.web.maps.cache_root", lambda: tile_root)
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["title"] = "Portable session"
    assert _save(job, doc).status_code == 200
    preview_png = _landmark_png()
    assert client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=preview_png).status_code == 200
    tile = tile_root / "planet" / "0" / "0" / "0.pbf"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")

    response = client.get(f"/api/maps/{job['id']}/session")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert json.loads(archive.read("manifest.json"))["document"]["slides"][0]["title"] == "Portable session"
        assert archive.read("previews/s1.png") == preview_png
        assert archive.read("tile-cache/planet/0/0/0.pbf") == b"tile"

    tile.unlink()
    doc["slides"][0]["title"] = "Changed"
    _save(job, doc)
    loaded = client.post(
        f"/api/maps/{job['id']}/session",
        files={"file": ("saved.obedmaps", response.content, "application/zip")},
    )
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["result"]["slides"][0]["title"] == "Portable session"
    assert loaded.json()["sessionImport"] == {"tiles": 1, "previews": 1}
    assert tile.read_bytes() == b"tile"
    preview = Path(loaded.json()["result"]["previewDir"]) / "s1.png"
    assert preview.read_bytes() == preview_png


def test_maps_session_drops_movies_from_the_replaced_job(tmp_path, monkeypatch):
    tile_root = tmp_path / "tile-cache"
    tile_root.mkdir()
    monkeypatch.setattr("obed_edom.web.maps.cache_root", lambda: tile_root)
    job = _seed()
    saved_doc = _doc(job)
    saved_doc["slides"][0].update({"movieMov": "Map BG_s1.mov", "movieDuration": 1.5})
    assert _save(job, saved_doc).status_code == 200
    session = client.get(f"/api/maps/{job['id']}/session")
    output_dir = Path(job["result"]["outputDir"])
    stale_movie = output_dir / "movies" / "s1.mov"
    stale_movie.parent.mkdir(parents=True, exist_ok=True)
    stale_movie.write_bytes(b"old deck")
    stale_deck = output_dir / "old.key"
    stale_deck.write_bytes(b"old export")
    stored = RUNNER.get(job["id"])
    assert stored is not None
    stored.result.update({"destPath": str(stale_deck), "flags": [{"message": "old validation"}]})

    loaded = client.post(
        f"/api/maps/{job['id']}/session",
        files={"file": ("saved.obedmaps", session.content, "application/zip")},
    )
    assert loaded.status_code == 200, loaded.text
    slide = loaded.json()["result"]["slides"][0]
    assert "movieMov" not in slide
    assert "movieDuration" not in slide
    assert "destPath" not in loaded.json()["result"]
    assert "flags" not in loaded.json()["result"]
    assert not stale_movie.exists()
    assert not stale_deck.exists()


def test_maps_session_rejects_traversal():
    job = _seed()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "obed-edom-maps", "version": 1, "document": _doc(job)}))
        archive.writestr("tile-cache/../../escape", b"no")
    response = client.post(
        f"/api/maps/{job['id']}/session",
        files={"file": ("bad.obedmaps", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400


def test_maps_session_save_rejects_an_archive_that_load_would_reject(tmp_path, monkeypatch):
    tile_root = tmp_path / "tile-cache"
    tile_root.mkdir()
    monkeypatch.setattr("obed_edom.web.maps.cache_root", lambda: tile_root)
    monkeypatch.setattr("obed_edom.web.maps.SESSION_MAX_BYTES", 8)
    (tile_root / "large.pbf").write_bytes(b"too large")
    job = _seed()
    response = client.get(f"/api/maps/{job['id']}/session")
    assert response.status_code == 413


def test_maps_session_rejects_invalid_tile_path_before_replacing_preview():
    job = _seed()
    existing_preview = _landmark_png()
    assert client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=existing_preview).status_code == 200
    preview = Path(job["result"]["previewDir"]) / "s1.png"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "obed-edom-maps", "version": 1, "document": _doc(job)}))
        archive.writestr("tile-cache/not!allowed.pbf", b"no")
    response = client.post(
        f"/api/maps/{job['id']}/session",
        files={"file": ("bad.obedmaps", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert preview.read_bytes() == existing_preview


def test_maps_session_staging_failure_preserves_existing_assets(tmp_path, monkeypatch):
    from obed_edom.web.maps import _read_session_archive

    tile_root = tmp_path / "tile-cache"
    tile_root.mkdir()
    monkeypatch.setattr("obed_edom.web.maps.cache_root", lambda: tile_root)
    job_public = _seed()
    job = RUNNER.get(job_public["id"])
    assert job is not None
    preview = Path(job.result["previewDir"]) / "s1.png"
    preview.write_bytes(b"existing preview")
    existing_tile = tile_root / "existing.pbf"
    existing_tile.write_bytes(b"existing tile")
    stale_deck = Path(job.result["outputDir"]) / "existing.key"
    stale_deck.write_bytes(b"existing deck")
    job.result["destPath"] = str(stale_deck)
    archive_raw = BytesIO()
    with zipfile.ZipFile(archive_raw, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "obed-edom-maps", "version": 1, "document": _doc(job_public)}))
        archive.writestr("previews/imported.png", b"new preview")
        archive.writestr("tile-cache/new.pbf", b"new tile")
    original_copy = shutil.copyfileobj
    copies = 0

    def fail_second_copy(src, dest, *args, **kwargs):
        nonlocal copies
        copies += 1
        if copies == 2:
            raise OSError("simulated destination failure")
        return original_copy(src, dest, *args, **kwargs)

    monkeypatch.setattr("obed_edom.web.maps.shutil.copyfileobj", fail_second_copy)
    with pytest.raises(OSError, match="simulated destination failure"):
        _read_session_archive(job, BytesIO(archive_raw.getvalue()))
    assert preview.read_bytes() == b"existing preview"
    assert existing_tile.read_bytes() == b"existing tile"
    assert stale_deck.read_bytes() == b"existing deck"
    assert not (tile_root / "new.pbf").exists()


def _landmark_png() -> bytes:
    image = Image.new("RGBA", (40, 20), (180, 80, 40, 180))
    data = BytesIO()
    image.save(data, "PNG")
    return data.getvalue()


def _tiny_jpeg() -> bytes:
    image = Image.new("RGB", (16, 16), (10, 20, 30))
    data = BytesIO()
    image.save(data, "JPEG")
    return data.getvalue()


def test_landmark_assets_are_owned_referenced_and_session_portable():
    job = _seed()
    uploaded = client.post(
        f"/api/maps/{job['id']}/assets",
        files={"file": ("church.png", _landmark_png(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    upload_payload = uploaded.json()
    asset = upload_payload["asset"]
    assert isinstance(upload_payload["stateRevision"], int)
    assert upload_payload["document"]["assets"] == [asset]
    doc = _doc(job)
    doc["assets"] = [{"id": "forged", "version": "a" * 8, "width": 1, "height": 1}]
    doc["slides"][0]["churches"] = [
        {
            "id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "landmark", "color": "#c44a42",
            "assetId": asset["id"], "assetVersion": asset["version"], "assetWidth": asset["width"], "assetHeight": asset["height"], "size": 180,
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["assets"] == [asset]
    session = client.get(f"/api/maps/{job['id']}/session")
    assert session.status_code == 200, session.text
    with zipfile.ZipFile(BytesIO(session.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["document"]["assets"] == [asset]
        assert archive.read(f"assets/{asset['id']}.png")


def test_reveal_accepted_on_landmark_rejected_elsewhere():
    job = _seed()
    uploaded = client.post(
        f"/api/maps/{job['id']}/assets",
        files={"file": ("church.png", _landmark_png(), "image/png")},
    ).json()
    asset = uploaded["asset"]
    doc = _doc(job)
    doc["slides"][0]["churches"] = [
        {
            "id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "landmark", "color": "#c44a42",
            "assetId": asset["id"], "size": 180, "reveal": {"kind": "brush", "duration": 1.2},
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["slides"][0]["churches"][0]["reveal"]["duration"] == 1.2

    doc["slides"][0]["churches"][0]["kind"] = "dot"
    doc["slides"][0]["churches"][0].pop("assetId")
    rejected = _save(job, doc)
    assert rejected.status_code == 400


def test_reveal_duration_out_of_range_rejected():
    job = _seed()
    uploaded = client.post(
        f"/api/maps/{job['id']}/assets",
        files={"file": ("church.png", _landmark_png(), "image/png")},
    ).json()
    asset = uploaded["asset"]
    doc = _doc(job)
    doc["slides"][0]["churches"] = [
        {
            "id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "landmark", "color": "#c44a42",
            "assetId": asset["id"], "size": 180, "reveal": {"kind": "brush", "duration": 10},
        }
    ]
    rejected = _save(job, doc)
    assert rejected.status_code == 400


def test_church_size_allows_up_to_4000_and_rejects_above():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["churches"] = [
        {"id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "dot", "color": "#c44a42", "size": 3140}
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["slides"][0]["churches"][0]["size"] == 3140

    doc["slides"][0]["churches"][0]["size"] = 4001
    rejected = _save(job, doc)
    assert rejected.status_code == 400


def test_state_rejects_legacy_external_photo_path_and_unknown_asset():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["churches"] = [
        {"id": "p1", "name": "Unsafe", "lat": 3, "lon": 101, "kind": "dot", "color": "#c44a42", "photoPath": "/etc/passwd"}
    ]
    response = _save(job, doc)
    assert response.status_code == 400
    doc["slides"][0]["churches"][0].pop("photoPath")
    doc["slides"][0]["churches"][0]["kind"] = "landmark"
    doc["slides"][0]["churches"][0]["assetId"] = "missing"
    response = _save(job, doc)
    assert response.status_code == 400


def test_state_rejects_slide_id_ending_in_landing_suffix():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["id"] = "s2__landing"
    doc["links"] = []
    response = _save(job, doc)
    assert response.status_code == 400


def test_session_omits_asset_after_its_last_landmark_is_deleted():
    job = _seed()
    asset = client.post(f"/api/maps/{job['id']}/assets", files={"file": ("church.png", _landmark_png(), "image/png")}).json()["asset"]
    doc = _doc(job)
    slide = doc["slides"][0]
    slide["churches"] = [{"id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "landmark", "color": "#c44a42", "assetId": asset["id"]}]
    assert _save(job, doc).status_code == 200
    slide["churches"] = []
    assert _save(job, doc).status_code == 200
    session = client.get(f"/api/maps/{job['id']}/session")
    assert session.status_code == 200, session.text
    with zipfile.ZipFile(BytesIO(session.content)) as archive:
        document = json.loads(archive.read("manifest.json"))["document"]
        assert document["assets"] == []
        assert not [name for name in archive.namelist() if name.startswith("assets/")]


def test_export_requires_one_deck():
    job = _seed()
    res = client.post(
        f"/api/maps/{job['id']}/export",
        json={"exportLw": False, "exportCg": False},
    )
    assert res.status_code == 400


def test_state_allows_dsk_as_the_only_export_target():
    job = _seed()
    doc = _doc(job)
    doc.update({"exportLw": False, "exportCg": False, "exportDsk": True})
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["exportDsk"] is True


def test_first_state_save_of_a_fresh_deck_starts_at_revision_zero():
    job = _seed()
    assert job["result"]["stateRevision"] == 0
    saved = client.post(f"/api/maps/{job['id']}/state", json={"expectedRevision": 0, "document": _doc(job)})
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["stateRevision"] == 1


def test_state_revision_rejects_stale_document_save():
    job = _seed()
    doc = _doc(job)
    first = client.post(f"/api/maps/{job['id']}/state", json={"expectedRevision": 0, "document": doc})
    assert first.status_code == 200, first.text
    stale = client.post(f"/api/maps/{job['id']}/state", json={"expectedRevision": 0, "document": doc})
    assert stale.status_code == 409
    assert stale.json()["detail"]["stateRevision"] == 1


def test_state_requires_a_revision_envelope():
    job = _seed()
    response = client.post(f"/api/maps/{job['id']}/state", json=_doc(job))
    assert response.status_code == 400
    assert "envelope" in response.json()["detail"]


def test_state_rejects_duplicate_object_ids_and_invalid_links():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["churches"] = [
        {"id": "p1", "name": "One", "lat": 1, "lon": 2, "kind": "dot", "color": "#fff"},
        {"id": "p1", "name": "Two", "lat": 3, "lon": 4, "kind": "dot", "color": "#fff"},
    ]
    assert _save(job, doc).status_code == 400
    doc["slides"][0]["churches"] = []
    doc["links"] = [{"from": "s1", "to": "missing", "kind": "cut", "duration": 1, "playWithoutClick": False}]
    assert _save(job, doc).status_code == 400


def test_png_still_and_plate_filenames():
    job = _seed()
    still_png = _landmark_png()
    still = client.post(f"/api/maps/{job['id']}/png?slideId=s1&kind=still", content=still_png)
    assert still.status_code == 200
    assert still.json()["result"]["slides"][0].get("stillPng") is None
    out = Path(job["result"]["outputDir"])
    assert (out / "stills" / "s1.png").read_bytes() == still_png
    plate_png = _landmark_png()
    plate = client.post(f"/api/maps/{job['id']}/png?plateId=p-s1-s2&kind=plate", content=plate_png)
    assert plate.status_code == 200
    assert plate.json()["result"]["slides"][0].get("stillPng") is None
    assert (out / "plates" / "map BG_p-s1-s2.png").read_bytes() == plate_png
    missing = client.post(f"/api/maps/{job['id']}/png?kind=plate", content=b"x")
    assert missing.status_code == 400


def test_png_rejects_non_image_bytes():
    job = _seed()
    response = client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=b"not a real png")
    assert response.status_code == 400


def test_png_rejects_body_over_the_size_cap(monkeypatch):
    job = _seed()
    monkeypatch.setattr("obed_edom.web.maps.RASTER_MAX_BYTES", 16)
    response = client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=_landmark_png())
    assert response.status_code == 413


def test_png_rejects_oversized_dimensions(monkeypatch):
    job = _seed()
    monkeypatch.setattr("obed_edom.web.maps.RASTER_MAX_SIDE", 8)
    response = client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=_landmark_png())
    assert response.status_code == 400


def test_frame_rejects_non_image_bytes():
    job = _seed()
    response = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=1&fps=30",
        content=b"not a real frame",
        headers={"content-type": "image/jpeg"},
    )
    assert response.status_code == 400


def test_frame_rejects_count_out_of_range():
    job = _seed()
    response = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=20001&fps=30",
        content=_tiny_jpeg(),
        headers={"content-type": "image/jpeg"},
    )
    assert response.status_code == 400


def test_frame_rejects_index_not_less_than_count():
    job = _seed()
    response = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=3&count=3&fps=30",
        content=_tiny_jpeg(),
        headers={"content-type": "image/jpeg"},
    )
    assert response.status_code == 400


def test_export_plan_coerces_oversized_morph():
    job = _seed()
    doc = _doc(job)
    s1 = dict(doc["slides"][0])
    s1["includeSidePanels"] = True
    cam = dict(s1["camera"])
    s2 = dict(s1)
    s2["id"] = "s2"
    s2["title"] = "Far"
    s2["camera"] = {**cam, "lon": cam["lon"] + 80}
    doc["slides"] = [s1, s2]
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    payload = plan.json()
    assert payload["links"][0]["kind"] == "movie"
    assert "plateId" not in payload["links"][0]
    assert {row["slideId"] for row in payload["stills"]} == {"s1", "s2"}
    assert payload["plates"] == []
    assert "camera" in payload["stills"][0]


def test_export_plan_small_morph_has_plate_camera():
    job = _seed()
    doc = _doc(job)
    s1 = dict(doc["slides"][0])
    cam = dict(s1["camera"])
    s2 = dict(s1)
    s2["id"] = "s2"
    s2["title"] = "Near"
    s2["camera"] = {**cam, "lon": cam["lon"] + 0.02}
    doc["slides"] = [s1, s2]
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    payload = plan.json()
    assert payload["links"][0]["kind"] == "morph"
    assert payload["links"][0].get("plateId")
    assert payload["stills"] == []
    assert len(payload["plates"]) == 1
    plate = payload["plates"][0]
    assert plate["plateW"] >= 3840
    assert plate["plateH"] >= 1080
    assert plate["camera"]["bearing"] == 0
    assert plate["camera"]["pitch"] == 0
    assert set(plate["camera"]) >= {"lat", "lon", "zoom", "bearing", "pitch"}


def test_include_side_panels_and_cached_countries_roundtrip():
    job = _seed()
    doc = _doc(job)
    slide = dict(doc["slides"][0])
    slide["includeSidePanels"] = True
    doc["slides"] = [slide]
    doc["cachedCountries"] = ["phl", "ind"]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["slides"][0]["includeSidePanels"] is True
    assert result["cachedCountries"] == ["PHL", "IND"]
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    still = plan.json()["stills"][0]
    assert still["width"] == 7680
    assert still["height"] == 1080


def test_export_plan_default_still_is_lw():
    job = _seed()
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    still = plan.json()["stills"][0]
    assert still["width"] == 3840
    assert still["height"] == 1080


def test_tile_cache_countries_pins_series_first():
    res = client.get("/api/maps/tiles/countries")
    assert res.status_code == 200, res.text
    codes = [row["code"] for row in res.json()]
    assert codes[:4] == ["PHL", "IND", "IDN", "MYS"]


def test_tile_proxy_and_prefetch_use_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"pbf-bytes")
    tile = client.get("/api/maps/tiles/planet/0/0/0.pbf")
    assert tile.status_code == 200, tile.text
    assert tile.content == b"pbf-bytes"
    cached = client.get("/api/maps/tiles/planet/0/0/0.pbf")
    assert cached.content == b"pbf-bytes"
    prefetch = client.post(
        "/api/maps/tile-cache/prefetch",
        json={
            "cameras": [{"lat": 3.0, "lon": 101.0, "zoom": 4, "bearing": 0, "pitch": 0}],
            "width": 3840,
            "height": 1080,
            "maxzoom": 4,
        },
    )
    assert prefetch.status_code == 200, prefetch.text
    body = prefetch.json()
    assert body["ok"] is True
    assert body["tiles"] > 0
    stats = client.get("/api/maps/tile-cache")
    assert stats.status_code == 200, stats.text
    assert stats.json()["bytes"] > 0
    cleared = client.delete("/api/maps/tile-cache")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["bytes"] == 0


def test_tile_proxy_serves_terrarium_png(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"dem-png-bytes")
    tile = client.get("/api/maps/tiles/terrarium/9/3/4.png")
    assert tile.status_code == 200, tile.text
    assert tile.headers["content-type"] == "image/png"
    assert tile.content == b"dem-png-bytes"
    cached = client.get("/api/maps/tiles/terrarium/9/3/4.png")
    assert cached.status_code == 200, cached.text
    assert cached.content == b"dem-png-bytes"


def test_prefetch_terrain_flag_fetches_dem_tiles(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"bytes")
    prefetch = client.post(
        "/api/maps/tile-cache/prefetch",
        json={
            "cameras": [{"lat": 27.9, "lon": 86.9, "zoom": 9, "bearing": 0, "pitch": 0}],
            "width": 3840,
            "height": 1080,
            "maxzoom": 9,
            "terrain": True,
        },
    )
    assert prefetch.status_code == 200, prefetch.text
    body = prefetch.json()
    assert body["ok"] is True
    assert body["tiles"] > 0
    stats = client.get("/api/maps/tile-cache")
    assert stats.status_code == 200, stats.text
    assert stats.json()["files"] > 0
    without_terrain = client.post(
        "/api/maps/tile-cache/prefetch",
        json={
            "cameras": [{"lat": 27.9, "lon": 86.9, "zoom": 9, "bearing": 0, "pitch": 0}],
            "width": 3840,
            "height": 1080,
            "maxzoom": 9,
        },
    )
    assert without_terrain.status_code == 200, without_terrain.text
    assert without_terrain.json()["tiles"] < body["tiles"]
    cleared = client.delete("/api/maps/tile-cache")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["bytes"] == 0


def test_tile_cache_plan_does_not_fetch_tiles(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)

    calls: list[str] = []

    def fake_fetch(rel: str) -> bytes:
        calls.append(rel)
        if rel == "planet":
            return b'{"tiles":["https://tiles.openfreemap.org/planet/rev/{z}/{x}/{y}.pbf"]}'
        raise AssertionError(f"unexpected fetch for {rel}")

    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", fake_fetch)
    res = client.post(
        "/api/maps/tile-cache/plan",
        json={
            "cameras": [{"lat": 3.0, "lon": 101.0, "zoom": 4, "bearing": 0, "pitch": 0}],
            "width": 3840,
            "height": 1080,
            "maxzoom": 4,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["tiles"] > 0
    assert len(body["rels"]) == body["tiles"]
    assert body["cached"] == 0
    assert calls == ["planet"]


def test_tile_cache_plan_reports_capped_camera_subsample(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.MAX_PREFETCH_TILES", 40)
    monkeypatch.setattr("obed_edom.maps_tiles.planet_tile_template", lambda **_: "planet/{z}/{x}/{y}.pbf")
    cameras = [
        {"lat": 0.0, "lon": float(i) * 8.0 - 80.0, "zoom": 10, "bearing": 0, "pitch": 0} for i in range(30)
    ]
    res = client.post(
        "/api/maps/tile-cache/plan",
        json={"cameras": cameras, "width": 3840, "height": 1080, "maxzoom": 10},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["capped"] is True
    assert body["cameras"] == 30
    assert body["camerasUsed"] < 30


def test_tile_cache_prefetch_accepts_rel_batch(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    monkeypatch.setattr("obed_edom.maps_tiles.fetch_upstream", lambda rel: b"pbf-bytes")
    first = client.post("/api/maps/tile-cache/prefetch", json={"rels": ["planet/0/0/0.pbf"]})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["fetched"] == 1
    assert body["cached"] == 0
    second = client.post("/api/maps/tile-cache/prefetch", json={"rels": ["planet/0/0/0.pbf"]})
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["cached"] == 1
    assert body2["fetched"] == 0


def test_tile_cache_prefetch_rejects_bad_rel_batches(tmp_path, monkeypatch):
    monkeypatch.setattr("obed_edom.maps_tiles.output_root", lambda: tmp_path)
    traversal = client.post("/api/maps/tile-cache/prefetch", json={"rels": ["../secret"]})
    assert traversal.status_code == 400

    from obed_edom.maps_tiles import MAX_PREFETCH_BATCH

    oversized = client.post(
        "/api/maps/tile-cache/prefetch",
        json={"rels": [f"planet/0/0/{i}.pbf" for i in range(MAX_PREFETCH_BATCH + 1)]},
    )
    assert oversized.status_code == 400

    combined = client.post(
        "/api/maps/tile-cache/prefetch",
        json={
            "rels": ["planet/0/0/0.pbf"],
            "cameras": [{"lat": 0.0, "lon": 0.0, "zoom": 4, "bearing": 0, "pitch": 0}],
        },
    )
    assert combined.status_code == 400


def test_isolate_rejects_unknown_mode():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["isolate"] = {"mode": "blur", "strength": 0.5}
    response = _save(job, doc)
    assert response.status_code == 400


def test_isolate_round_trips_on_save():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["isolate"] = {"mode": "darken", "strength": 0.35}
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.35}
    fetched = client.get(f"/api/jobs/{job['id']}")
    assert fetched.json()["result"]["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.35}


def test_isolate_erase_mode_migrates_to_darken():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["isolate"] = {"mode": "erase", "strength": 0.35}
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.35}


def test_isolate_default_strength_is_065():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["isolate"] = {"mode": "darken"}
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.65}


def test_legacy_session_isolate_060_bumps_once():
    # A legacy archive (no isolateDefaultVersion marker) loaded into a fresh job is bumped.
    legacy_job = _seed()
    legacy_doc = _doc(legacy_job)
    legacy_doc["slides"][0]["isolate"] = {"mode": "darken", "strength": 0.6}
    assert _save(legacy_job, legacy_doc).status_code == 200

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": "obed-edom-maps", "version": 1, "document": legacy_doc})
        )
    fresh_job = _seed()
    loaded = client.post(
        f"/api/maps/{fresh_job['id']}/session",
        files={"file": ("legacy.obedmaps", buffer.getvalue(), "application/zip")},
    )
    assert loaded.status_code == 200, loaded.text
    result = loaded.json()["result"]
    assert result["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.65}
    assert result["isolateDefaultVersion"] == 1

    # A migrated archive (isolateDefaultVersion already 1) carrying a user-chosen 0.60
    # loaded into a different, fresh job must not be bumped again.
    migrated_job = fresh_job
    migrated_doc = _doc(migrated_job)
    migrated_doc["slides"][0]["isolate"] = {"mode": "darken", "strength": 0.6}
    assert _save(migrated_job, migrated_doc).status_code == 200
    session = client.get(f"/api/maps/{migrated_job['id']}/session")
    assert session.status_code == 200, session.text
    manifest = json.loads(zipfile.ZipFile(BytesIO(session.content)).read("manifest.json"))
    assert manifest["isolateDefaultVersion"] == 1

    other_job = _seed()
    loaded2 = client.post(
        f"/api/maps/{other_job['id']}/session",
        files={"file": ("already-migrated.obedmaps", session.content, "application/zip")},
    )
    assert loaded2.status_code == 200, loaded2.text
    result2 = loaded2.json()["result"]
    assert result2["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.6}
    assert result2["isolateDefaultVersion"] == 1


def test_fresh_job_is_seeded_with_current_isolate_default_version():
    job = _seed()
    assert job["result"]["isolateDefaultVersion"] == 1


def test_fresh_job_isolate_060_survives_session_roundtrip():
    job = _seed()
    doc = _doc(job)
    doc["slides"][0]["isolate"] = {"mode": "darken", "strength": 0.6}
    assert _save(job, doc).status_code == 200

    session = client.get(f"/api/maps/{job['id']}/session")
    assert session.status_code == 200, session.text

    other_job = _seed()
    loaded = client.post(
        f"/api/maps/{other_job['id']}/session",
        files={"file": ("saved.obedmaps", session.content, "application/zip")},
    )
    assert loaded.status_code == 200, loaded.text
    result = loaded.json()["result"]
    assert result["slides"][0]["isolate"] == {"mode": "darken", "strength": 0.6}
    assert result["isolateDefaultVersion"] == 1


def test_maps_session_rejects_invalid_isolate_default_version_before_replacing_state(tmp_path, monkeypatch):
    tile_root = tmp_path / "tile-cache"
    tile_root.mkdir()
    monkeypatch.setattr("obed_edom.web.maps.cache_root", lambda: tile_root)
    job = _seed()
    existing_preview = _landmark_png()
    assert client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=existing_preview).status_code == 200
    preview = Path(job["result"]["previewDir"]) / "s1.png"
    original_title = job["result"]["slides"][0]["title"]

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "obed-edom-maps",
                    "version": 1,
                    "document": _doc(job),
                    "isolateDefaultVersion": "invalid",
                }
            ),
        )
    response = client.post(
        f"/api/maps/{job['id']}/session",
        files={"file": ("bad.obedmaps", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert preview.read_bytes() == existing_preview
    fetched = client.get(f"/api/jobs/{job['id']}")
    assert fetched.json()["result"]["slides"][0]["title"] == original_title
    assert fetched.json()["result"]["isolateDefaultVersion"] == 1

    for index, bad_value in enumerate([-1, False, "", 0.0, None], start=2):
        buffer_bad = BytesIO()
        with zipfile.ZipFile(buffer_bad, "w") as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": "obed-edom-maps",
                        "version": 1,
                        "document": _doc(job),
                        "isolateDefaultVersion": bad_value,
                    }
                ),
            )
        response_bad = client.post(
            f"/api/maps/{job['id']}/session",
            files={"file": (f"bad{index}.obedmaps", buffer_bad.getvalue(), "application/zip")},
        )
        assert response_bad.status_code == 400, bad_value
        assert preview.read_bytes() == existing_preview
        fetched_bad = client.get(f"/api/jobs/{job['id']}")
        assert fetched_bad.json()["result"]["slides"][0]["title"] == original_title
        assert fetched_bad.json()["result"]["isolateDefaultVersion"] == 1


def test_retired_links_round_trip_on_save():
    job = _seed()
    doc = _doc(job)
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    doc["slides"].append(slide2)
    doc["retiredLinks"] = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 3.5, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    result = saved.json()["result"]
    assert result["retiredLinks"] == [
        {"from": "s1", "to": "s2", "kind": "movie", "duration": 3.5, "playWithoutClick": False}
    ]


def test_retired_links_with_unknown_slide_are_pruned_not_rejected():
    job = _seed()
    doc = _doc(job)
    doc["retiredLinks"] = [{"from": "s1", "to": "missing", "kind": "cut", "duration": 1, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["retiredLinks"] == []


def test_retired_links_do_not_break_export_plan():
    job = _seed()
    doc = _doc(job)
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    doc["slides"].append(slide2)
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    doc["retiredLinks"] = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 3.5, "playWithoutClick": False}]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    plan = client.get(f"/api/maps/{job['id']}/export-plan")
    assert plan.status_code == 200, plan.text
    kinds = {(row["from"], row["to"]): row["kind"] for row in plan.json()["links"]}
    assert kinds[("s1", "s2")] == "morph"


def test_retired_links_survive_obedmaps_save_and_load_into_fresh_job():
    job = _seed()
    doc = _doc(job)
    slide2 = dict(doc["slides"][0])
    slide2["id"] = "s2"
    doc["slides"].append(slide2)
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    doc["retiredLinks"] = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 3.5,
            "playWithoutClick": False,
            "objectTransition": "fade",
        }
    ]
    assert _save(job, doc).status_code == 200

    session = client.get(f"/api/maps/{job['id']}/session")
    assert session.status_code == 200, session.text

    fresh_job = _seed()
    loaded = client.post(
        f"/api/maps/{fresh_job['id']}/session",
        files={"file": ("retired-links.obedmaps", session.content, "application/zip")},
    )
    assert loaded.status_code == 200, loaded.text
    result = loaded.json()["result"]
    assert result["retiredLinks"] == [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 3.5,
            "playWithoutClick": False,
            "objectTransition": "fade",
        }
    ]
    assert result["links"] == [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]


def test_watercolour_add_to_map_seeds_default_landmark_size_not_180():
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]

    wash_response = client.post(
        "/api/watercolour",
        files=[("files", ("landmark.png", _landmark_png(), "image/png"))],
        data={"masks": json.dumps({"0": {"transparent": True, "rect": [4, 2, 30, 14]}})},
    )
    assert wash_response.status_code == 200, wash_response.text
    wash_job_id = wash_response.json()["id"]
    wash_job = None
    for _ in range(80):
        wash_job = client.get(f"/api/jobs/{wash_job_id}").json()
        if wash_job["status"] in {"done", "error"}:
            break
        time.sleep(0.03)
    assert wash_job["status"] == "done", wash_job.get("error")
    item = wash_job["result"]["items"][0]
    assert item["status"] == "done" and item["transparent"] is True

    from obed_edom.web.watercolour import _default_landmark_size

    added = client.post(f"/api/watercolour/{wash_job_id}/items/{item['id']}/add-to-map/{map_job['id']}/{slide_id}")
    assert added.status_code == 200, added.text
    doc = added.json()["result"]
    slide = next(s for s in doc["slides"] if s["id"] == slide_id)
    church = slide["churches"][-1]
    assert church["size"] == _default_landmark_size(church["assetWidth"])
    assert church["size"] != 180
    import re
    assert re.fullmatch(r"w[0-9a-f]{8}", church["id"])


def test_studio_add_clears_only_that_slides_still_png():
    map_job = _seed()
    doc = _doc(map_job)
    slide = dict(doc["slides"][0])
    other = dict(slide)
    other["id"] = "s2"
    other["title"] = "Second"
    doc["slides"] = [slide, other]
    doc["links"] = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    saved = _save(map_job, doc)
    assert saved.status_code == 200, saved.text
    map_job = {**map_job, "result": saved.json()["result"]}
    slide_id, other_slide_id = "s1", "s2"

    for sid in (slide_id, other_slide_id):
        thumb = client.post(f"/api/maps/{map_job['id']}/png?slideId={sid}&kind=thumb", content=_landmark_png())
        assert thumb.status_code == 200, thumb.text

    wash_response = client.post(
        "/api/watercolour",
        files=[("files", ("landmark.png", _landmark_png(), "image/png"))],
        data={"masks": json.dumps({"0": {"transparent": True, "rect": [4, 2, 30, 14]}})},
    )
    assert wash_response.status_code == 200, wash_response.text
    wash_job = _wait(wash_response.json()["id"])
    item = wash_job["result"]["items"][0]

    added = client.post(f"/api/watercolour/{wash_job['id']}/items/{item['id']}/add-to-map/{map_job['id']}/{slide_id}")
    assert added.status_code == 200, added.text
    doc = added.json()["result"]
    touched = next(s for s in doc["slides"] if s["id"] == slide_id)
    untouched = next(s for s in doc["slides"] if s["id"] == other_slide_id)
    assert touched.get("stillPng") is None
    assert untouched.get("stillPng") is not None


def test_add_landmark_endpoint_appends_asset_and_church_in_one_revision():
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]
    before_revision = int(map_job["result"].get("stateRevision") or 0)

    response = client.post(
        f"/api/maps/{map_job['id']}/slides/{slide_id}/landmark",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    church_id = body["churchId"]
    result = body["result"]
    assert result["stateRevision"] == before_revision + 1
    slide = next(s for s in result["slides"] if s["id"] == slide_id)
    church = next(c for c in slide["churches"] if c["id"] == church_id)
    assert church["kind"] == "landmark"
    assert church["assetId"] in {row["id"] for row in result["assets"]}

    asset_response = client.get(f"/api/maps/{map_job['id']}/assets/{church['assetId']}.png")
    assert asset_response.status_code == 200
    assert asset_response.headers["content-type"] == "image/png"


def test_add_landmark_unknown_slide_404s_and_writes_no_asset():
    map_job = _seed()
    before_assets = list(map_job["result"].get("assets") or [])

    response = client.post(
        f"/api/maps/{map_job['id']}/slides/nope/landmark",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert response.status_code == 404

    latest = client.get(f"/api/jobs/{map_job['id']}").json()
    assert latest["result"]["assets"] == before_assets
    asset_dir = Path(latest["result"]["outputDir"]) / "assets"
    pngs_after = set(asset_dir.glob("*.png")) if asset_dir.is_dir() else set()
    assert not pngs_after


def test_add_landmark_persist_failure_leaves_no_asset_and_no_document_change(monkeypatch):
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]
    before_revision = int(map_job["result"].get("stateRevision") or 0)

    def boom(_job_id, _result):
        raise RuntimeError("disk full")

    monkeypatch.setattr(RUNNER, "update_result", boom)
    with pytest.raises(RuntimeError):
        client.post(
            f"/api/maps/{map_job['id']}/slides/{slide_id}/landmark",
            files={"file": ("st-marks.png", _landmark_png(), "image/png")},
        )

    monkeypatch.undo()
    latest = client.get(f"/api/jobs/{map_job['id']}").json()
    assert int(latest["result"].get("stateRevision") or 0) == before_revision
    asset_dir = Path(latest["result"]["outputDir"]) / "assets"
    pngs_after = set(asset_dir.glob("*.png")) if asset_dir.is_dir() else set()
    tmp_after = set(asset_dir.glob("*.tmp")) if asset_dir.is_dir() else set()
    assert not pngs_after
    assert not tmp_after


def test_add_landmark_promotes_asset_before_publishing_document(monkeypatch):
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]

    real_update_result = RUNNER.update_result
    seen: dict[str, bool] = {}

    def spy(job_id, result):
        assets = result.get("assets") or []
        if assets:
            asset_id = assets[-1]["id"]
            asset_dir = Path(result["outputDir"]) / "assets"
            seen["asset_on_disk"] = (asset_dir / f"{asset_id}.png").is_file()
        return real_update_result(job_id, result)

    monkeypatch.setattr(RUNNER, "update_result", spy)
    response = client.post(
        f"/api/maps/{map_job['id']}/slides/{slide_id}/landmark",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert seen.get("asset_on_disk") is True


def test_add_landmark_rolls_back_document_and_leaves_no_asset_on_persistence_failure(monkeypatch):
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]
    before_assets = list(map_job["result"].get("assets") or [])
    before_churches = list(map_job["result"]["slides"][0]["churches"])

    calls = {"n": 0}
    real_save = RUNNER.save

    def flaky_save(job):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk full")
        return real_save(job)

    monkeypatch.setattr(RUNNER, "save", flaky_save)
    with pytest.raises(RuntimeError):
        client.post(
            f"/api/maps/{map_job['id']}/slides/{slide_id}/landmark",
            files={"file": ("st-marks.png", _landmark_png(), "image/png")},
        )

    latest = client.get(f"/api/jobs/{map_job['id']}").json()
    assert latest["result"]["assets"] == before_assets
    slide = next(s for s in latest["result"]["slides"] if s["id"] == slide_id)
    assert slide["churches"] == before_churches
    asset_dir = Path(latest["result"]["outputDir"]) / "assets"
    leftover = set(asset_dir.glob("*")) if asset_dir.is_dir() else set()
    assert not leftover


def test_append_landmark_church_id_collision_loops_until_a_free_id(monkeypatch):
    from obed_edom.web import maps

    result = {
        "slides": [
            {
                "id": "s1",
                "camera": {"lat": 1.0, "lon": 2.0},
                "churches": [{"id": "wdeadbeef"}, {"id": "waaaaaaaa"}],
            }
        ],
    }
    sequence = iter(["aaaaaaaa", "cccccccc"])

    class FakeUuid:
        def __init__(self, hex_value):
            self.hex = hex_value

    monkeypatch.setattr(maps.uuid, "uuid4", lambda: FakeUuid(next(sequence)))
    updated = maps.append_landmark(result, "s1", "lw", "Landmark", 10, 10, "a" * 40, "deadbeef")
    church = updated["slides"][0]["churches"][-1]
    assert church["id"] == "wcccccccc"


def test_add_landmark_places_on_the_cg_view_and_invalidates_only_its_still_png():
    map_job = _seed()
    doc = _doc(map_job)
    slide = dict(doc["slides"][0])
    slide["cg"] = {
        "camera": slide["camera"],
        "style": slide["style"],
        "highlights": [],
        "churches": [],
    }
    doc["slides"] = [slide]
    saved = _save(map_job, doc)
    assert saved.status_code == 200, saved.text
    map_job = {**map_job, "result": saved.json()["result"]}
    slide_id = slide["id"]

    lw_thumb = client.post(f"/api/maps/{map_job['id']}/png?slideId={slide_id}&kind=thumb", content=_landmark_png())
    assert lw_thumb.status_code == 200, lw_thumb.text
    cg_thumb = client.post(f"/api/maps/{map_job['id']}/png?slideId={slide_id}&audience=cg&kind=thumb", content=_landmark_png())
    assert cg_thumb.status_code == 200, cg_thumb.text

    response = client.post(
        f"/api/maps/{map_job['id']}/slides/{slide_id}/landmark?audience=cg",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    result = body["result"]
    updated_slide = next(s for s in result["slides"] if s["id"] == slide_id)
    assert updated_slide["churches"] == []
    cg_view = updated_slide["cg"]
    church = next(c for c in cg_view["churches"] if c["id"] == body["churchId"])
    assert church["kind"] == "landmark"
    assert cg_view.get("stillPng") is None
    assert updated_slide.get("stillPng") is not None


# --- Concurrent-race tests ---------------------------------------------------
# These exercise real thread interleavings around the per-job mutation lock
# (_mutation_lock in obed_edom.web.maps) and the job store (obed_edom.web.jobs).


def test_two_concurrent_appends_both_land_with_distinct_ids_and_assets(monkeypatch):
    job = _seed()
    slide_id = job["result"]["slides"][0]["id"]
    before_revision = int(job["result"].get("stateRevision") or 0)

    from obed_edom.web import maps

    barrier = threading.Barrier(2)
    real_decode = maps._decode_png

    def gated_decode(raw):
        payload = real_decode(raw)
        barrier.wait(5)
        return payload

    monkeypatch.setattr(maps, "_decode_png", gated_decode)

    def upload(name):
        return client.post(
            f"/api/maps/{job['id']}/slides/{slide_id}/landmark",
            files={"file": (name, _landmark_png(), "image/png")},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(upload, "a.png"), pool.submit(upload, "b.png")]
        responses = [future.result(timeout=5) for future in futures]

    for response in responses:
        assert response.status_code == 200, response.text
    bodies = [response.json() for response in responses]
    church_ids = {body["churchId"] for body in bodies}
    assert len(church_ids) == 2
    revisions = sorted(body["result"]["stateRevision"] for body in bodies)
    assert revisions == [before_revision + 1, before_revision + 2]

    latest = client.get(f"/api/jobs/{job['id']}").json()
    slide = next(s for s in latest["result"]["slides"] if s["id"] == slide_id)
    assert {c["id"] for c in slide["churches"]} == church_ids
    asset_ids = {c["assetId"] for c in slide["churches"]}
    assert len(asset_ids) == 2
    for asset_id in asset_ids:
        asset_response = client.get(f"/api/maps/{job['id']}/assets/{asset_id}.png")
        assert asset_response.status_code == 200


def test_asset_upload_hands_the_new_revision_to_the_next_save():
    # The per-job mutation lock fully serializes writes, so an upload that lands
    # between a client's read and its save is a sequencing race, not a lock race:
    # client 1 reads stale_revision, client 2's upload commits first, then client
    # 1's save (still carrying stale_revision) must 409 with the new revision.
    job = _seed()
    doc = _doc(job)
    stale_revision = int(job["result"].get("stateRevision") or 0)

    uploaded = client.post(
        f"/api/maps/{job['id']}/assets",
        files={"file": ("church.png", _landmark_png(), "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    asset = uploaded.json()["asset"]
    new_revision = uploaded.json()["stateRevision"]

    stale_save = client.post(
        f"/api/maps/{job['id']}/state",
        json={"expectedRevision": stale_revision, "document": doc},
    )
    assert stale_save.status_code == 409, stale_save.text
    stale_detail = stale_save.json()["detail"]
    assert stale_detail["stateRevision"] == new_revision
    assert stale_detail["document"]["assets"] == [asset]

    doc["slides"][0]["churches"] = [
        {
            "id": "p1", "name": "Church", "lat": 3, "lon": 101, "kind": "landmark", "color": "#c44a42",
            "assetId": asset["id"], "size": 180,
        }
    ]
    retry = client.post(
        f"/api/maps/{job['id']}/state",
        json={"expectedRevision": new_revision, "document": doc},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["result"]["assets"] == [asset]


def test_studio_append_during_a_stale_state_save_yields_409_and_keeps_the_landmark():
    map_job = _seed()
    slide_id = map_job["result"]["slides"][0]["id"]
    stale_doc = _doc(map_job)
    before_revision = int(map_job["result"].get("stateRevision") or 0)

    wash_response = client.post(
        "/api/watercolour",
        files=[("files", ("landmark.png", _landmark_png(), "image/png"))],
        data={"masks": json.dumps({"0": {"transparent": True, "rect": [4, 2, 30, 14]}})},
    )
    assert wash_response.status_code == 200, wash_response.text
    wash_job = _wait(wash_response.json()["id"])
    item = wash_job["result"]["items"][0]

    append_response = client.post(
        f"/api/watercolour/{wash_job['id']}/items/{item['id']}/add-to-map/{map_job['id']}/{slide_id}"
    )
    assert append_response.status_code == 200, append_response.text
    church_id = append_response.json()["churchId"]

    stale_save = client.post(
        f"/api/maps/{map_job['id']}/state",
        json={"expectedRevision": before_revision, "document": stale_doc},
    )
    assert stale_save.status_code == 409, stale_save.text
    detail = stale_save.json()["detail"]
    assert detail["stateRevision"] == before_revision + 1
    slide_in_conflict = next(s for s in detail["document"]["slides"] if s["id"] == slide_id)
    assert any(c["id"] == church_id for c in slide_in_conflict["churches"])

    latest = client.get(f"/api/jobs/{map_job['id']}").json()
    live_slide = next(s for s in latest["result"]["slides"] if s["id"] == slide_id)
    assert any(c["id"] == church_id for c in live_slide["churches"])
    asset_id = next(c["assetId"] for c in live_slide["churches"] if c["id"] == church_id)
    asset_response = client.get(f"/api/maps/{map_job['id']}/assets/{asset_id}.png")
    assert asset_response.status_code == 200
    asset_dir = Path(latest["result"]["outputDir"]) / "assets"
    assert not list(asset_dir.glob("*.tmp"))


def test_stale_thumbnail_after_an_append_is_dropped(monkeypatch):
    job = _seed()
    slide_id = job["result"]["slides"][0]["id"]

    from obed_edom.web import maps

    seed_revision = int(job["result"].get("stateRevision") or 0)
    seed_bytes = _landmark_png()
    seeded = client.post(
        f"/api/maps/{job['id']}/png?slideId={slide_id}&kind=thumb&revision={seed_revision}",
        content=seed_bytes,
    )
    assert seeded.status_code == 200, seeded.text
    seeded_result = seeded.json()["result"]
    before_revision = int(seeded_result["stateRevision"] or 0)
    preview_dir = Path(seeded_result["previewDir"])
    thumb_path = next(p for p in preview_dir.glob("*.png") if p.name.startswith(slide_id))
    on_disk_before = thumb_path.read_bytes()
    assert on_disk_before == seed_bytes

    thumb_started = threading.Event()
    release_thumb = threading.Event()
    real_validate_raster = maps._validate_raster

    def gated_validate_raster(raw, **kwargs):
        dims = real_validate_raster(raw, **kwargs)
        thumb_started.set()
        release_thumb.wait(5)
        return dims

    monkeypatch.setattr(maps, "_validate_raster", gated_validate_raster)

    write_calls = []
    real_write_atomic = maps._write_atomic

    def spy_write_atomic(path, data):
        write_calls.append(Path(path))
        return real_write_atomic(path, data)

    monkeypatch.setattr(maps, "_write_atomic", spy_write_atomic)

    stale_image = Image.new("RGBA", (40, 20), (10, 200, 10, 255))
    stale_buffer = BytesIO()
    stale_image.save(stale_buffer, "PNG")
    stale_bytes = stale_buffer.getvalue()
    assert stale_bytes != seed_bytes

    outcome = {}

    def post_thumb():
        outcome["response"] = client.post(
            f"/api/maps/{job['id']}/png?slideId={slide_id}&kind=thumb&revision={before_revision}",
            content=stale_bytes,
        )

    thread = threading.Thread(target=post_thumb)
    thread.start()
    assert thumb_started.wait(5)

    landmark = client.post(
        f"/api/maps/{job['id']}/slides/{slide_id}/landmark",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert landmark.status_code == 200, landmark.text

    release_thumb.set()
    thread.join(5)
    assert outcome["response"].status_code == 409, outcome["response"].text
    detail = outcome["response"].json()["detail"]
    assert detail["staleThumbnail"] is True
    assert detail["stateRevision"] == before_revision + 1

    latest = client.get(f"/api/jobs/{job['id']}").json()
    slide = next(s for s in latest["result"]["slides"] if s["id"] == slide_id)
    assert slide.get("stillPng") is None
    on_disk_after = thumb_path.read_bytes()
    assert on_disk_after == on_disk_before
    assert thumb_path not in write_calls
    leftover_pngs = [p for p in preview_dir.glob("*.png") if p.name.startswith(slide_id)]
    assert leftover_pngs == [thumb_path]
    assert not list(preview_dir.glob("*.tmp"))
    assert int(latest["result"]["stateRevision"] or 0) == before_revision + 1


def test_thumb_post_with_stale_revision_conflicts_then_succeeds():
    job = _seed()
    slide_id = job["result"]["slides"][0]["id"]
    revision = int(job["result"].get("stateRevision") or 0)

    stale = client.post(
        f"/api/maps/{job['id']}/png?slideId={slide_id}&kind=thumb&revision={revision + 1}",
        content=_landmark_png(),
    )
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["staleThumbnail"] is True
    assert detail["stateRevision"] == revision

    fresh = client.post(
        f"/api/maps/{job['id']}/png?slideId={slide_id}&kind=thumb&revision={revision}",
        content=_landmark_png(),
    )
    assert fresh.status_code == 200, fresh.text
    assert int(fresh.json()["result"]["stateRevision"] or 0) == revision + 1


def test_session_import_and_a_concurrent_append_do_not_lose_each_other(monkeypatch):
    from obed_edom.web import maps

    # Part (a): an append landing while the archive is still being read must
    # see the job "running" and 409, leaving no asset behind.
    job_a = _seed()
    slide_a = job_a["result"]["slides"][0]["id"]
    session_a = client.get(f"/api/maps/{job_a['id']}/session")
    assert session_a.status_code == 200, session_a.text

    mid_import = threading.Event()
    release_import = threading.Event()
    real_read_archive = maps._read_session_archive

    def gated_read_archive(job, source):
        if job.id == job_a["id"]:
            mid_import.set()
            release_import.wait(5)
        return real_read_archive(job, source)

    monkeypatch.setattr(maps, "_read_session_archive", gated_read_archive)

    import_outcome_a = {}

    def import_session_a():
        import_outcome_a["response"] = client.post(
            f"/api/maps/{job_a['id']}/session",
            files={"file": ("saved.obedmaps", session_a.content, "application/zip")},
        )

    import_thread_a = threading.Thread(target=import_session_a)
    import_thread_a.start()
    assert mid_import.wait(5)

    mid_append = client.post(
        f"/api/maps/{job_a['id']}/slides/{slide_a}/landmark",
        files={"file": ("st-marks.png", _landmark_png(), "image/png")},
    )
    assert mid_append.status_code == 409, mid_append.text
    assert mid_append.json()["detail"] == "Maps job is not ready"

    release_import.set()
    import_thread_a.join(5)
    assert not import_thread_a.is_alive()
    assert import_outcome_a["response"].status_code == 200, import_outcome_a["response"].text
    monkeypatch.undo()

    latest_a = client.get(f"/api/jobs/{job_a['id']}").json()
    slide_after_a = next(s for s in latest_a["result"]["slides"] if s["id"] == slide_a)
    assert not any(c.get("assetId") for c in slide_after_a.get("churches", []))

    # Part (b): the status-flip-to-publish tail must run under the same job
    # lock an append needs, so the append cannot land in the gap between them.
    job_b = _seed()
    slide_b = job_b["result"]["slides"][0]["id"]
    session_b = client.get(f"/api/maps/{job_b['id']}/session")
    assert session_b.status_code == 200, session_b.text

    tail_reached = threading.Event()
    release_tail = threading.Event()
    real_mutate_document = maps._mutate_document
    tail_lock_state = {}

    def spy_mutate_document(job_id, expected_revision, mutate):
        if job_id == job_b["id"] and "owned" not in tail_lock_state:
            tail_lock_state["owned"] = maps._mutation_lock(job_id)._is_owned()
            tail_reached.set()
            release_tail.wait(5)
        return real_mutate_document(job_id, expected_revision, mutate)

    monkeypatch.setattr(maps, "_mutate_document", spy_mutate_document)

    append_lock_reached = threading.Event()
    landmark_bytes = _landmark_png()

    import_outcome_b = {}

    def import_session_b():
        import_outcome_b["response"] = client.post(
            f"/api/maps/{job_b['id']}/session",
            files={"file": ("saved.obedmaps", session_b.content, "application/zip")},
        )

    import_thread_b = threading.Thread(target=import_session_b)
    import_thread_b.start()
    assert tail_reached.wait(5)
    # The status flip and the publish call must already be running under the
    # job's own mutation lock, held by the import thread.
    assert tail_lock_state.get("owned") is True

    real_mutate_document_with_asset = maps._mutate_document_with_asset

    def spy_mutate_document_with_asset(job_id, expected_revision, asset_id, payload, mutate):
        if job_id == job_b["id"] and not append_lock_reached.is_set():
            append_lock_reached.set()
        return real_mutate_document_with_asset(job_id, expected_revision, asset_id, payload, mutate)

    monkeypatch.setattr(maps, "_mutate_document_with_asset", spy_mutate_document_with_asset)

    append_outcome = {}

    def append_during_tail():
        append_outcome["response"] = client.post(
            f"/api/maps/{job_b['id']}/slides/{slide_b}/landmark",
            files={"file": ("st-marks.png", landmark_bytes, "image/png")},
        )

    append_thread = threading.Thread(target=append_during_tail, name="append_during_tail")
    append_thread.start()
    # Deterministic signal: the append thread has reached the point right
    # before it tries to acquire the job's mutation lock, which the import
    # tail is still holding.
    assert append_lock_reached.wait(5), "append never reached the lock-acquisition point"

    release_tail.set()
    import_thread_b.join(5)
    append_thread.join(5)
    assert not import_thread_b.is_alive()
    assert not append_thread.is_alive()

    assert import_outcome_b["response"].status_code == 200, import_outcome_b["response"].text
    append_response = append_outcome["response"]
    assert append_response.status_code == 200, append_response.text
    monkeypatch.undo()

    latest_b = client.get(f"/api/jobs/{job_b['id']}").json()
    slide_after_b = next(s for s in latest_b["result"]["slides"] if s["id"] == slide_b)
    church_id = append_response.json()["churchId"]
    assert any(c["id"] == church_id for c in slide_after_b["churches"])
    asset_id = next(c["assetId"] for c in slide_after_b["churches"] if c["id"] == church_id)
    asset_response = client.get(f"/api/maps/{job_b['id']}/assets/{asset_id}.png")
    assert asset_response.status_code == 200
    assert append_response.json()["result"] == latest_b["result"]


def test_load_session_locks_idle_check_and_status_flip_together(monkeypatch):
    from obed_edom.web import maps

    job = _seed()
    slide_id = job["result"]["slides"][0]["id"]
    session = client.get(f"/api/maps/{job['id']}/session")
    assert session.status_code == 200, session.text

    reached = threading.Event()
    release = threading.Event()
    real_require_idle = maps._require_idle
    state = {"gated": False}

    def gated_require_idle(j):
        real_require_idle(j)
        if j.id == job["id"] and not state["gated"]:
            state["gated"] = True
            reached.set()
            release.wait(5)

    monkeypatch.setattr(maps, "_require_idle", gated_require_idle)

    import_outcome = {}

    def do_import():
        import_outcome["response"] = client.post(
            f"/api/maps/{job['id']}/session",
            files={"file": ("saved.obedmaps", session.content, "application/zip")},
        )

    import_thread = threading.Thread(target=do_import)
    import_thread.start()
    assert reached.wait(5)

    append_outcome = {}

    def do_append():
        append_outcome["response"] = client.post(
            f"/api/maps/{job['id']}/slides/{slide_id}/landmark",
            files={"file": ("st-marks.png", _landmark_png(), "image/png")},
        )

    append_lock_reached = threading.Event()
    real_mutate_document_with_asset = maps._mutate_document_with_asset

    def spy_mutate_document_with_asset(job_id, expected_revision, asset_id, payload, mutate):
        if job_id == job["id"] and not append_lock_reached.is_set():
            append_lock_reached.set()
        return real_mutate_document_with_asset(job_id, expected_revision, asset_id, payload, mutate)

    monkeypatch.setattr(maps, "_mutate_document_with_asset", spy_mutate_document_with_asset)

    append_thread = threading.Thread(target=do_append)
    append_thread.start()
    assert append_lock_reached.wait(5), "append never reached the lock-acquisition point"

    release.set()
    import_thread.join(5)
    append_thread.join(5)
    monkeypatch.undo()

    assert not import_thread.is_alive()
    assert not append_thread.is_alive()
    assert import_outcome["response"].status_code == 200, import_outcome["response"].text

    latest = client.get(f"/api/jobs/{job['id']}").json()
    slide_after = next(s for s in latest["result"]["slides"] if s["id"] == slide_id)
    append_response = append_outcome["response"]
    assert append_response.status_code == 409, append_response.text
    assert not any(c.get("assetId") for c in slide_after.get("churches", []))


def test_delete_and_edit_conflict_leaves_exactly_one_winner():
    job = _seed()
    doc = _doc(job)
    slide_id = doc["slides"][0]["id"]
    revision = int(job["result"].get("stateRevision") or 0)

    delete_doc = {**doc, "slides": [s for s in doc["slides"] if s["id"] != slide_id]}
    edit_doc = json.loads(json.dumps(doc))
    edit_doc["slides"][0]["title"] = "Edited under race"

    def post(document):
        return client.post(
            f"/api/maps/{job['id']}/state",
            json={"expectedRevision": revision, "document": document},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post, delete_doc), pool.submit(post, edit_doc)]
        responses = [future.result(timeout=5) for future in futures]

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 409]
    winner = next(r for r in responses if r.status_code == 200)
    loser = next(r for r in responses if r.status_code == 409)
    assert winner.json()["result"]["stateRevision"] == revision + 1
    assert loser.json()["detail"]["stateRevision"] == revision + 1

    document_keys = (
        "defaultStyle",
        "crop",
        "exportLw",
        "exportCg",
        "exportDsk",
        "hiddenLayers",
        "cachedCountries",
        "assets",
        "slides",
        "links",
        "retiredLinks",
    )
    latest = client.get(f"/api/jobs/{job['id']}").json()
    winner_doc = {key: latest["result"].get(key) for key in document_keys}
    assert loser.json()["detail"]["document"] == winner_doc
    assert int(latest["result"]["stateRevision"]) == revision + 1


def test_append_to_a_job_deleted_mid_flight_404s_and_leaves_no_asset(monkeypatch):
    job = _seed()
    slide_id = job["result"]["slides"][0]["id"]
    output_dir = Path(job["result"]["outputDir"])

    save_entered = threading.Event()
    release_save = threading.Event()
    gated_once = threading.Event()
    real_job_lock = RUNNER._job_lock

    def gated_job_lock(job_id):
        if job_id == job["id"] and not gated_once.is_set():
            gated_once.set()
            save_entered.set()
            release_save.wait(5)
        return real_job_lock(job_id)

    monkeypatch.setattr(RUNNER, "_job_lock", gated_job_lock)

    outcome = {}

    def append():
        outcome["response"] = client.post(
            f"/api/maps/{job['id']}/slides/{slide_id}/landmark",
            files={"file": ("st-marks.png", _landmark_png(), "image/png")},
        )

    thread = threading.Thread(target=append)
    thread.start()
    assert save_entered.wait(5)
    assert RUNNER.delete(job["id"], purge=False) is True
    release_save.set()
    thread.join(5)

    assert outcome["response"].status_code == 404, outcome["response"].text
    monkeypatch.undo()
    assert RUNNER.get(job["id"]) is None
    asset_dir = output_dir / "assets"
    pngs = set(asset_dir.glob("*.png")) if asset_dir.is_dir() else set()
    tmps = set(asset_dir.glob("*.tmp")) if asset_dir.is_dir() else set()
    assert not pngs
    assert not tmps


def test_bootstrap_csv_headerless_paste_zooms_via_ladder(monkeypatch):
    job = _seed()

    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": 'China\nUdaipur,"24.58, 73.68"\n', "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    new_slides = [s for s in done["result"]["slides"] if s["id"] != "s1"]
    assert len(new_slides) == 2
    china_slide = next(s for s in new_slides if s["title"] == "China")
    udaipur_slide = next(s for s in new_slides if s["title"] == "Udaipur")
    assert china_slide["camera"]["zoom"] == pytest.approx(4.3)
    assert udaipur_slide["camera"]["zoom"] == pytest.approx(13.0)


def test_bootstrap_csv_row_error_returns_400_with_line_detail():
    job = _seed()
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "China\n,24.5 N, 73.6 E\n", "replace": "false"},
    )
    assert started.status_code == 400
    detail = started.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0].startswith("Line 2:")


def test_bootstrap_csv_headerless_paste_into_pins(monkeypatch):
    job = _seed()

    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "China\n", "targetSlideId": "s1", "audience": "lw"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    pins = done["result"]["slides"][0]["churches"]
    assert [pin["name"] for pin in pins] == ["China"]


def test_bootstrap_csv_headerless_explicit_zoom_wins_over_ladder(monkeypatch):
    job = _seed()

    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "China,z=6.8\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    china_slide = next(s for s in done["result"]["slides"] if s["id"] != "s1")
    assert china_slide["camera"]["zoom"] == pytest.approx(6.8)


def test_bootstrap_csv_headerless_leftover_words_qualify_the_geocode_query(monkeypatch):
    job = _seed()
    seen_queries: list[str] = []

    def fake_geocode(query, *, wait=False):
        seen_queries.append(query)
        return {"camera": camera_dict(1.0, 2.0, 10.5), "placeType": "city", "label": query}

    monkeypatch.setattr("obed_edom.web.maps.geocode", fake_geocode)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "Paris,France\nUdaipur,India,z=6.8\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    assert seen_queries == ["Paris, France", "Udaipur, India"]
    new_slides = [s for s in done["result"]["slides"] if s["id"] != "s1"]
    udaipur_slide = next(s for s in new_slides if s["title"] == "Udaipur")
    assert udaipur_slide["camera"]["zoom"] == pytest.approx(6.8)


def test_bootstrap_csv_header_form_place_column_is_full_query_override(monkeypatch):
    job = _seed()
    seen_queries: list[str] = []

    def fake_geocode(query, *, wait=False):
        seen_queries.append(query)
        return {"camera": camera_dict(1.0, 2.0, 10.5), "placeType": "city", "label": query}

    monkeypatch.setattr("obed_edom.web.maps.geocode", fake_geocode)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": 'name,place\nMy Church,"Paris, France"\n', "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    assert seen_queries == ["Paris, France"]


def test_bootstrap_csv_header_form_bad_zoom_reports_error_not_crash():
    job = _seed()
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name,zoom\nParis,notazoom\n", "replace": "false"},
    )
    assert started.status_code == 400
    detail = started.json()["detail"]
    assert "Line 2" in detail[0]
    assert "bad zoom" in detail[0]


def test_bootstrap_csv_header_form_unknown_kind_reports_error_not_crash():
    job = _seed()
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name,kind\nParis,spaceport\n", "replace": "false"},
    )
    assert started.status_code == 400
    detail = started.json()["detail"]
    assert "Line 2" in detail[0]
    assert "unknown kind" in detail[0]


def test_bootstrap_csv_place_only_header_with_extra_comma_is_joined_not_a_500(monkeypatch):
    job = _seed()
    seen_queries: list[str] = []

    def fake_geocode(query, *, wait=False):
        seen_queries.append(query)
        return {"camera": camera_dict(1.0, 2.0, 10.5), "placeType": "city", "label": query}

    monkeypatch.setattr("obed_edom.web.maps.geocode", fake_geocode)
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "place\nParis, France\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    assert seen_queries == ["Paris, France"]
    new_slides = [s for s in done["result"]["slides"] if s["id"] != "s1"]
    assert len(new_slides) == 1


def test_bootstrap_csv_multi_column_header_extra_columns_is_400_not_500():
    job = _seed()
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "name,lat,lon\nX,1,2,3\n", "replace": "false"},
    )
    assert started.status_code == 400
    detail = started.json()["detail"]
    assert "Line 2" in detail[0]
    assert "too many columns" in detail[0]


def test_bootstrap_csv_place_header_naming_country_adopts_country_name_as_title():
    job = _seed()
    started = client.post(
        f"/api/maps/{job['id']}/bootstrap-csv",
        data={"csv_text": "place\nFrance\n", "replace": "false"},
    )
    assert started.status_code == 200
    done = _wait(job["id"])
    assert done["status"] == "done", done.get("error")
    new_slides = [s for s in done["result"]["slides"] if s["id"] != "s1"]
    assert len(new_slides) == 1
    assert new_slides[0]["title"] == "France"
