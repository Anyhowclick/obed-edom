import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from obed_edom.maps_geo import WORLD_MIN_ZOOM
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
    assert result["slides"][0]["camera"]["zoom"] >= WORLD_MIN_ZOOM


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


def test_export_requires_one_deck():
    job = _seed()
    res = client.post(
        f"/api/maps/{job['id']}/export",
        json={"exportLw": False, "exportCg": False},
    )
    assert res.status_code == 400


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
    assert plate["plateW"] >= 7680
    assert plate["plateH"] >= 1080
    assert plate["camera"]["bearing"] == 0
    assert plate["camera"]["pitch"] == 0
    assert set(plate["camera"]) >= {"lat", "lon", "zoom", "bearing", "pitch"}
