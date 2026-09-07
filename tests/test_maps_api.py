import json
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from obed_edom.maps_geo import CG_MIN_ZOOM, WORLD_MIN_ZOOM
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


def test_post_maps_seeds_under_output_root_without_dest():
    job = _seed()
    result = job["result"]
    assert "destPath" not in result
    assert result["exportLw"] is True
    assert result["exportCg"] is True
    assert result["hiddenLayers"] == ["roadnames"]
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
    res = client.post(f"/api/maps/{job['id']}/state", json=_doc(job))
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=_doc(job))
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
    assert saved.status_code == 200, saved.text
    route = saved.json()["result"]["links"][0]["route"]
    assert route == {"points": [{"lat": 1.3, "lon": 103.8}, {"lat": 3.1, "lon": 101.7}]}
    doc["links"][0]["route"] = {"points": [{"lat": 1.3, "lon": 103.8}, {"lat": 3.1, "lon": 101.7}], "extra": True}
    bad = client.post(f"/api/maps/{job['id']}/state", json=doc)
    assert bad.status_code == 400
    doc["links"][0]["route"] = {"points": [{"lat": 1.3, "lon": 103.8}]}
    short = client.post(f"/api/maps/{job['id']}/state", json=doc)
    assert short.status_code == 400


def test_hidden_layers_roundtrip():
    job = _seed()
    doc = _doc(job)
    doc["hiddenLayers"] = ["pois", "shields"]
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["hiddenLayers"] == ["pois", "shields"]


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
    assert client.post(f"/api/maps/{job['id']}/state", json=doc).status_code == 200
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
    client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    assert client.post(f"/api/maps/{job['id']}/state", json=saved_doc).status_code == 200
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
    assert saved.status_code == 200, saved.text
    assert saved.json()["result"]["exportDsk"] is True


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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
    saved = client.post(f"/api/maps/{job['id']}/state", json=doc)
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
