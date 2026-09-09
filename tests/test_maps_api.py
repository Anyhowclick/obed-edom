import json
import shutil
import subprocess
import time
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from obed_edom.maps_geo import camera_dict
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
    assert result["slides"][0]["title"] == "Downtown Singapore"
    assert result["slides"][0]["camera"] == {
        "lat": 1.2894,
        "lon": 103.8596,
        "zoom": 16.7,
        "pitch": 0,
        "bearing": 52,
    }


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
        content=b"jpg-bytes",
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
        }
    ]
    saved = _save(job, doc)
    assert saved.status_code == 200, saved.text
    links = saved.json()["result"]["links"]
    assert "easeIn" not in links[0]
    assert "easeOut" not in links[0]
    assert "flyZoom" not in links[0]


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
    camera = camera_dict(1.3521, 103.8198, 8)
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
    ok = client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=b"png-bytes")
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
    res = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=3&fps=30",
        content=b"jpg-bytes",
        headers={"content-type": "image/jpeg"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "index": 0, "count": 3}
    frame_dir = out / "frames" / "s1"
    assert (frame_dir / "00000.jpg").read_bytes() == b"jpg-bytes"
    meta = json.loads((frame_dir / "meta.json").read_text())
    assert meta == {"fps": 30, "count": 3, "duration": 0.1}
    stale = frame_dir / "stale.jpg"
    stale.write_bytes(b"stale")
    res2 = client.post(
        f"/api/maps/{job['id']}/frame?slideId=s1&index=0&count=2&fps=30",
        content=b"new-bytes",
        headers={"content-type": "image/jpeg"},
    )
    assert res2.status_code == 200
    assert not stale.exists()
    assert (frame_dir / "00000.jpg").read_bytes() == b"new-bytes"


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
    assert client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=b"preview").status_code == 200
    tile = tile_root / "planet" / "0" / "0" / "0.pbf"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")

    response = client.get(f"/api/maps/{job['id']}/session")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        assert json.loads(archive.read("manifest.json"))["document"]["slides"][0]["title"] == "Portable session"
        assert archive.read("previews/s1.png") == b"preview"
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
    assert preview.read_bytes() == b"preview"


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
    assert client.post(f"/api/maps/{job['id']}/png?slideId=s1", content=b"existing").status_code == 200
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
    assert preview.read_bytes() == b"existing"


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
    still = client.post(f"/api/maps/{job['id']}/png?slideId=s1&kind=still", content=b"png-still")
    assert still.status_code == 200
    assert still.json()["result"]["slides"][0].get("stillPng") is None
    out = Path(job["result"]["outputDir"])
    assert (out / "stills" / "s1.png").read_bytes() == b"png-still"
    plate = client.post(f"/api/maps/{job['id']}/png?plateId=p-s1-s2&kind=plate", content=b"png-plate")
    assert plate.status_code == 200
    assert plate.json()["result"]["slides"][0].get("stillPng") is None
    assert (out / "plates" / "map BG_p-s1-s2.png").read_bytes() == b"png-plate"
    missing = client.post(f"/api/maps/{job['id']}/png?kind=plate", content=b"x")
    assert missing.status_code == 400


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
    assert plate["camera"]["bearing"] == cam["bearing"]
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
