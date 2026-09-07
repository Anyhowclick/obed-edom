"""Maps Keynote export: plate math and mocked osascript. No live Keynote, no real .key."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from PIL import Image
import pytest

from obed_edom.maps_geo import CENTRE_ORIGIN_X, CENTRE_WIDTH, clamp_cg_shift, world_width
from obed_edom.maps_keynote import (
    MAP_BG_RE,
    PANEL_EDGES,
    WALL_HEIGHT,
    WALL_WIDTH,
    assign_morph_plates,
    avoid_straddle,
    build_deck_script,
    build_shared_plate_probe_script,
    build_slide_items,
    cg_crop_origin,
    coerce_link_kinds,
    dsk_item,
    export_maps_job,
    hop_capture_size,
    maps_export_plan,
    morph_plate_geom,
    plate_filename,
    plate_id_for,
    plate_placement,
    plan_deck,
    project_into_camera,
    project_into_plate,
    split_cg_export_plan,
)
from obed_edom.maps_movie import movie_path
from obed_edom.web.jobs import Job

from scripts.probe_maps_shared_plate import build_probe, main as probe_main


def _camera(lat: float, lon: float, zoom: float = 8.0) -> dict:
    return {"lat": lat, "lon": lon, "zoom": zoom, "bearing": 0.0, "pitch": 0.0}


def _slide(sid: str, camera: dict, **extra) -> dict:
    row = {
        "id": sid,
        "title": sid,
        "style": "positron",
        "camera": camera,
        "highlights": [],
        "churches": [],
        "cgShiftX": 0,
        "cgShiftY": 0,
    }
    row.update(extra)
    return row


def _job(tmp_path: Path, slides: list[dict], links: list[dict]) -> Job:
    out = tmp_path / "out"
    preview = out / "previews"
    out.mkdir()
    preview.mkdir()
    return Job(
        id="t1",
        kind="maps",
        feature="maps",
        status="done",
        result={
            "stem": "maps-t1",
            "outputDir": str(out),
            "previewDir": str(preview),
            "slides": slides,
            "links": links,
            "exportLw": True,
            "exportCg": True,
        },
    )


def _ok_osascript(script: str, **_k):
    return subprocess.CompletedProcess(["osascript"], 0, stdout="ok", stderr="")


def _dummy_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (20, 30, 40)).save(path, "PNG")
    return path


def _write_plan_rasters(output_dir: Path, slides: list[dict], links: list[dict]):
    plan = maps_export_plan(slides, links)
    for still in plan["stills"]:
        _dummy_png(output_dir / "stills" / f"{still['slideId']}.png")
    for plate in plan["plates"]:
        _dummy_png(output_dir / "plates" / plate_filename(plate["plateId"]))
    return plan


def test_dsk_item_scales_centre_wall_into_bottom_half():
    assert dsk_item({"kind": "image", "x": 1920, "y": 0, "w": 3840, "h": 1080}) == {
        "kind": "image",
        "x": 0,
        "y": 540,
        "w": 1920,
        "h": 540,
    }


def test_dsk_item_clips_full_wall_and_scales_pin_text():
    assert dsk_item({"kind": "image", "x": 0, "y": 0, "w": 7680, "h": 1080})["x"] == -960
    text = dsk_item({"kind": "text", "x": 2880, "y": 100, "w": 300, "h": 32})
    assert text == {"kind": "text", "x": 480, "y": 590, "w": 150, "h": 16, "fontSize": 12}


def _pan_camera(zoom: float, pixels_east: float, lat: float = 3.0, lon: float = 101.0) -> tuple[dict, dict]:
    dlon = pixels_east * 360.0 / world_width(zoom)
    return _camera(lat, lon, zoom), _camera(lat, lon + dlon, zoom)


def test_morph_path_computes_plate_id():
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": True}]
    plates, next_links = assign_morph_plates([a, b], links)
    assert next_links[0].get("plateId")
    plate_id = next_links[0]["plateId"]
    assert plate_id in plates
    assert plate_id == plate_id_for(["s1", "s2"])
    assert MAP_BG_RE.search(plate_filename(plate_id))
    geom = morph_plate_geom([a["camera"], b["camera"]])
    assert geom is not None
    assert geom["captureCamera"]["zoom"] == geom["zPlate"]
    assert geom["captureCamera"]["bearing"] == 0
    assert geom["captureCamera"]["pitch"] == 0
    place_a = plate_placement(a["camera"], geom)
    place_b = plate_placement(b["camera"], geom)
    assert place_a["w"] == place_b["w"]
    assert place_a["x"] != place_b["x"] or place_a["y"] != place_b["y"]


def test_same_zoom_pan_offsets_shared_plate():
    zoom = 8.0
    dlon = 1000.0 * 360.0 / world_width(zoom)
    a = _camera(3.0, 101.0, zoom)
    b = _camera(3.0, 101.0 + dlon, zoom)
    geom = morph_plate_geom([a, b])
    assert geom is not None
    place_a = plate_placement(a, geom)
    place_b = plate_placement(b, geom)
    assert place_a["x"] == 0
    assert place_b["x"] == -1000


def test_matching_rotation_uses_one_rotated_plate():
    a, b = _pan_camera(8, 400)
    a["bearing"] = 22
    b["bearing"] = 22
    geom = morph_plate_geom([a, b])
    assert geom is not None
    assert geom["captureCamera"]["bearing"] == 22
    place_a = plate_placement(a, geom)
    place_b = plate_placement(b, geom)
    assert place_a["x"] != place_b["x"] or place_a["y"] != place_b["y"]
    assert project_into_plate(a["lat"], a["lon"], geom, place_a) == pytest.approx(
        (WALL_WIDTH / 2, WALL_HEIGHT / 2), abs=0.1
    )


def test_cg_shift_clamp_used():
    slide = _slide("s1", _camera(3.0, 101.0), cgShiftX=2000, cgShiftY=10)
    dx, dy = clamp_cg_shift(2000, 0)
    origin = cg_crop_origin(slide)
    assert dy == 0
    assert origin == (2880 + dx, 0)
    assert origin == (2880 + 960, 0)
    items = build_slide_items(
        slide,
        plate=None,
        plate_path=None,
        still=Path("/tmp/missing-still.png"),
        movie=None,
        wall=False,
    )
    mapped = next(item for item in items if item.get("map"))
    assert mapped["x"] == whole_wall_to_cg(CENTRE_ORIGIN_X, origin[0])
    assert mapped["w"] == CENTRE_WIDTH


def whole_wall_to_cg(wall_x: float, origin_x: float) -> int:
    return int(round(wall_x - origin_x))


def test_both_dest_keys_when_both_flags_on(monkeypatch, tmp_path: Path):
    scripts: list[str] = []

    def capture(script: str, **_k):
        scripts.append(script)
        return _ok_osascript(script)

    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", capture)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": True}]
    job = _job(tmp_path, [a, b], links)
    _write_plan_rasters(Path(job.result["outputDir"]), [a, b], links)
    result = export_maps_job(job, export_lw=True, export_cg=True)
    assert result.get("destPath")
    assert result.get("destPathCg")
    assert result["destPath"].endswith(".key")
    assert result["destPathCg"].endswith("_CG.key")
    assert result["links"][0].get("plateId")
    assert len(scripts) == 2
    wall, cg = scripts
    assert 'tell application id "' in wall
    assert 'tell application "Keynote"' not in wall
    assert "with timeout of 3600 seconds" in wall
    assert "duplicate slide" in wall
    assert "magic move" in wall
    assert "transition effect:none" in wall
    assert "automatic transition:true" in wall
    assert "magicDonor" not in wall
    assert "delete slide 1" not in wall
    assert MAP_BG_RE.search(wall)
    assert "set width of theDoc to 7680" in wall
    assert "set width of theDoc to 1920" in cg
    assert "set position of image 1 to" in wall
    assert "set width of image 1 to" in wall


def test_pin_x_not_1920_or_5760(tmp_path: Path):
    zoom = 8.0
    cam = _camera(3.0, 101.0, zoom)
    # Left edge of a 28pt pin would land on the 1920 panel join without the nudge.
    dlon = (1920.0 + 14.0 - 3840.0) * 360.0 / world_width(zoom)
    church = {
        "id": "c1",
        "name": "Edge",
        "lat": 3.0,
        "lon": 101.0 + dlon,
        "kind": "dot",
        "color": "#c44a42",
    }
    slide = _slide("s1", cam, churches=[church])
    still = tmp_path / "s1.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True)
    pins = [item for item in items if item["kind"] == "shape"]
    assert pins
    xs = [item["x"] for item in pins]
    assert 1920 not in xs
    assert 5760 not in xs
    for item in pins:
        assert item["w"] <= 180
        right = item["x"] + item["w"]
        for edge in PANEL_EDGES:
            assert item["x"] != edge
            assert not (item["x"] < edge < right)


def test_avoid_straddle_moves_off_joins():
    assert avoid_straddle(1920, 28) != 1920
    assert avoid_straddle(5760, 40) != 5760
    nudged = avoid_straddle(1900, 80)
    assert not (nudged < 1920 < nudged + 80)


def test_hidden_pin_label_stays_in_state_but_is_not_exported(tmp_path: Path):
    slide = _slide(
        "s1",
        _camera(3.0, 101.0, 8),
        churches=[{"id": "c", "name": "Private label", "lat": 3.0, "lon": 101.0, "kind": "dropPin", "color": "#c44a42", "showLabel": False}],
    )
    items = build_slide_items(slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True)
    shapes = [item for item in items if item["kind"] == "shape"]
    assert len(shapes) == 3
    assert any(item.get("shape") == "triangle" for item in shapes)
    assert not [item for item in items if item["kind"] == "text" and item.get("text") == "Private label"]


def test_static_drop_pin_tip_is_anchored_to_the_projected_location(tmp_path: Path):
    camera = _camera(3.0, 101.0, 8)
    slide = _slide(
        "s1",
        camera,
        churches=[{"id": "c", "name": "Anchor", "lat": 3.0, "lon": 101.0, "kind": "dropPin", "color": "#ff8a00"}],
    )
    items = build_slide_items(slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True)
    triangle = next(item for item in items if item.get("shape") == "triangle")
    projected_x, projected_y = project_into_camera(3.0, 101.0, camera)
    assert abs((triangle["x"] + triangle["w"] / 2) - projected_x) <= 1
    assert abs((triangle["y"] + triangle["h"]) - projected_y) <= 1


def test_dot_pin_is_solid_without_white_centre(tmp_path: Path):
    slide = _slide(
        "s1",
        _camera(3.0, 101.0, 8),
        churches=[{"id": "c", "name": "Dot", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42"}],
    )
    items = build_slide_items(slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True)
    assert len([item for item in items if item["kind"] == "shape"]) == 1


def test_static_pin_wraps_across_dateline_and_low_zoom_world_copies(tmp_path: Path):
    near_dateline = _slide(
        "s1",
        _camera(0.0, 179.0, 8),
        churches=[{"id": "c", "name": "Dateline", "lat": 0.0, "lon": 181.0, "kind": "dot", "color": "#c44a42"}],
    )
    items = build_slide_items(near_dateline, plate=None, plate_path=None, still=_dummy_png(tmp_path / "dateline.png"), movie=None, wall=True)
    pin = next(item for item in items if item["kind"] == "shape")
    assert abs((pin["x"] + pin["w"] / 2) - WALL_WIDTH / 2) < 1000

    overview = _slide(
        "s2",
        _camera(0.0, 0.0, 0),
        includeSidePanels=True,
        churches=[{"id": "c", "name": "World", "lat": 0.0, "lon": 0.0, "kind": "dot", "color": "#c44a42"}],
    )
    copies = build_slide_items(overview, plate=None, plate_path=None, still=_dummy_png(tmp_path / "world.png"), movie=None, wall=True)
    assert len([item for item in copies if item["kind"] == "shape"]) >= 14


def test_movie_without_video_is_still(monkeypatch, tmp_path: Path):
    scripts: list[str] = []
    monkeypatch.setattr(
        "obed_edom.maps_keynote.run_osascript",
        lambda script, **_k: scripts.append(script) or _ok_osascript(script),
    )
    monkeypatch.setattr("obed_edom.maps_keynote.find_pin_drop_wave", lambda: None)
    a = _slide("s1", _camera(3.0, 101.0, 8), churches=[{"id": "c", "name": "KL", "lat": 3.0, "lon": 101.0, "kind": "dropPin", "color": "#c44a42"}])
    b = _slide("s2", _camera(3.0, 102.0, 8))
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 2.0, "playWithoutClick": False}]
    job = _job(tmp_path, [a, b], links)
    _write_plan_rasters(Path(job.result["outputDir"]), [a, b], links)
    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "destPath" in result
    assert "destPathCg" not in result
    assert "plateId" not in (result["links"][0] or {})
    wall = scripts[0]
    assert "magic move" not in wall
    assert "duplicate slide" not in wall
    assert "make new movie" not in wall
    assert "shape type:oval" in wall


def test_export_importable_and_osascript_is_mockable():
    import obed_edom.maps_keynote as mod

    assert callable(mod.export_maps_job)
    assert callable(mod.run_osascript)


def test_split_cg_plan_limits_assets_to_adjacent_transition_run():
    slides = [_slide(f"s{i}", _camera(3.0, 100.0 + i, 8)) for i in range(1, 6)]
    slides[1]["cg"] = {
        "camera": _camera(3.0, 102.0, 8), "style": "positron", "highlights": [], "churches": []
    }
    links = [
        {"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0},
        {"from": "s2", "to": "s3", "kind": "movie", "duration": 1.0},
        {"from": "s3", "to": "s4", "kind": "cut", "duration": 1.0},
        {"from": "s4", "to": "s5", "kind": "cut", "duration": 1.0},
    ]
    plan = split_cg_export_plan(slides, links)
    assert plan["affectedSlideIds"] == ["s1", "s2", "s3"]
    assert {row["slideId"] for row in plan["stills"]} <= {"s1", "s2", "s3"}


def test_run_osascript_terminates_when_cancelled(monkeypatch):
    import obed_edom.maps_keynote as mod

    class Proc:
        args = ["osascript", "script.applescript"]
        returncode = -15

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.returncode

    proc = Proc()
    checks = iter((False, False, True))
    monkeypatch.setattr(mod.subprocess, "run", lambda *_a, **_k: None)
    popen_args = {}
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *_a, **kwargs: popen_args.update(kwargs) or proc)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="Export cancelled"):
        mod.run_osascript("return 1", is_cancelled=lambda: next(checks))
    assert proc.terminated
    assert popen_args["stdout"] is not subprocess.PIPE
    assert popen_args["stderr"] is not subprocess.PIPE


def test_inspect_and_validate_checks_cancellation_between_phases(monkeypatch, tmp_path: Path):
    import obed_edom.maps_keynote as mod

    monkeypatch.setattr("obed_edom.inspect.inspect_keynote", lambda *_a, **_k: {"slides": []})
    monkeypatch.setattr("obed_edom.validate.validate_inspect", lambda *_a, **_k: [])
    checks = iter((False, False, True))
    with pytest.raises(RuntimeError, match="Export cancelled"):
        mod.inspect_and_validate(tmp_path / "deck.key", is_cancelled=lambda: next(checks))


def test_inspect_keynote_terminates_blocked_jxa_when_cancelled(monkeypatch, tmp_path: Path):
    import obed_edom.inspect as inspect_mod

    class Proc:
        args = ["osascript", "-l", "JavaScript"]
        returncode = -15

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.returncode

    key = tmp_path / "deck.key"
    key.write_text("stub")
    proc = Proc()
    started = threading.Event()
    cancelled = threading.Event()
    monkeypatch.setattr(inspect_mod.subprocess, "Popen", lambda *_a, **_k: started.set() or proc)
    result = []

    def inspect():
        try:
            inspect_mod.inspect_keynote(key, use_cache=False, is_cancelled=cancelled.is_set)
        except RuntimeError as exc:
            result.append(str(exc))

    thread = threading.Thread(target=inspect)
    thread.start()
    assert started.wait(1)
    cancelled.set()
    thread.join(1)
    assert not thread.is_alive()
    assert proc.terminated
    assert result == ["Export cancelled."]


def test_probe_dry_run_prints_script(tmp_path: Path, capsys):
    code = probe_main(["--dry-run", "--out", str(tmp_path / "probe")])
    assert code == 0
    printed = capsys.readouterr().out
    assert 'tell application id "' in printed
    assert 'tell application "Keynote"' not in printed
    assert "with timeout of 3600 seconds" in printed
    assert "duplicate slide" in printed
    assert "set theDoc to document 1" in printed
    assert "set position of image 1 to" in printed
    assert "set width of image 1 to" in printed
    assert "magic move" in printed
    dest, script_path, script = build_probe(tmp_path / "probe")
    assert script_path.is_file()
    assert MAP_BG_RE.search(script)
    built = build_shared_plate_probe_script(dest, tmp_path / "probe" / "map BG_probe.png")
    assert "file:imgFile" in built
    assert "set position of image 1 to" in built
    assert "set width of image 1 to" in built


def test_plan_deck_morph_duplicates(tmp_path: Path):
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.0, "playWithoutClick": False}]
    plates, links = assign_morph_plates([a, b], links)
    _write_plan_rasters(tmp_path, [a, b], links)
    ops = plan_deck(
        [a, b],
        links,
        plates,
        output_dir=tmp_path,
        preview_dir=tmp_path,
        movie=None,
        wall=True,
    )
    assert ops[0]["duplicate"] is False
    assert ops[1]["duplicate"] is True
    assert ops[0]["transition"]["effect"] == "magic_move"
    assert ops[1].get("transition") is None
    assert MAP_BG_RE.search(Path(ops[0]["items"][0]["path"]).name)
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "transition effect:magic move" in script
    assert "transition effect:none" in script


def test_stale_plate_id_stripped_on_cut():
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0))
    links = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "cut",
            "duration": 1.0,
            "playWithoutClick": False,
            "plateId": "p-stale",
        }
    ]
    _plates, next_links = assign_morph_plates([a, b], links)
    assert next_links[0]["kind"] == "cut"
    assert "plateId" not in next_links[0]


def test_plan_deck_dissolve_writes_keynote_duration(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0, 8), style="positron")
    b = _slide("s2", _camera(3.0, 102.0, 8), style="dark")
    links = [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 0.8, "playWithoutClick": True}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    assert ops[0]["transition"] == {"effect": "dissolve", "duration": 0.8, "automatic": True}
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "transition effect:dissolve" in script
    assert "transition duration:0.8" in script
    assert "automatic transition:true" in script


def test_coerce_keeps_dissolve_on_style_mismatch():
    a = _slide("s1", _camera(3.0, 101.0, 8), style="positron")
    b = _slide("s2", _camera(3.0, 102.0, 8), style="dark")
    links = [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 0.8, "playWithoutClick": False}]
    next_links = coerce_link_kinds([a, b], links)
    assert next_links[0]["kind"] == "dissolve"


def test_coerce_uses_strictest_cg_transition_requirement():
    a = _slide("s1", _camera(3.0, 101.0, 8))
    b = _slide("s2", _camera(3.0, 102.0, 8))
    b["cg"] = {"camera": _camera(3.0, 102.0, 10.1), "style": "positron", "highlights": [], "churches": []}
    movie = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}])[0]
    assert movie["kind"] == "movie"
    assert movie["duration"] == 1.7
    b["cg"]["style"] = "dark"
    cut = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}])[0]
    assert cut["kind"] == "cut"
    dissolve = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 1.7}])[0]
    assert dissolve["kind"] == "dissolve"
    assert dissolve["duration"] == 1.7


def test_split_cg_plan_uses_direct_1920_still_capture():
    slide = _slide("s1", _camera(3.0, 101.0, 8))
    slide["cg"] = {"camera": _camera(3.0, 102.0, 8), "style": "positron", "highlights": [], "churches": []}
    plan = split_cg_export_plan([slide], [])
    assert plan["stills"][0]["width"] == 1920
    assert plan["stills"][0]["height"] == 1080


def test_plan_deck_mixed_cg_uses_namespaced_and_legacy_stills(tmp_path: Path):
    s1 = _slide("s1", _camera(3.0, 101.0, 8))
    s2 = _slide("s2", _camera(3.0, 102.0, 8))
    s2["cg"] = {"camera": _camera(3.0, 103.0, 8), "style": "positron", "highlights": [], "churches": []}
    s3 = _slide("s3", _camera(3.0, 104.0, 8))
    for name in ("s1.png", "s2.png", "s3.png", "s2_CG.png"):
        _dummy_png(tmp_path / "stills" / name)
    cg_slides = [s1, {**s2, **s2["cg"], "_splitCg": True}, s3]
    ops = plan_deck(cg_slides, [], {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=False, audience="cg", cg_affected={"s2"})
    assert Path(ops[0]["items"][0]["path"]).name == "s1.png"
    assert Path(ops[1]["items"][0]["path"]).name == "s2_CG.png"
    assert (ops[1]["items"][0]["x"], ops[1]["items"][0]["w"]) == (0, 1920)
    assert Path(ops[2]["items"][0]["path"]).name == "s3.png"


def test_plan_deck_uses_cg_movie_for_affected_hop(tmp_path: Path):
    s1 = _slide("s1", _camera(3.0, 101.0, 8))
    s2 = _slide("s2", _camera(3.0, 102.0, 8))
    s2["cg"] = {"camera": _camera(3.0, 103.0, 8), "style": "positron", "highlights": [], "churches": []}
    for name in ("s1.png", "s2.png", "s2_CG.png"):
        _dummy_png(tmp_path / "stills" / name)
    movie_path(tmp_path, "s2").parent.mkdir(parents=True, exist_ok=True)
    movie_path(tmp_path, "s2").write_bytes(b"lw")
    movie_path(tmp_path, "s2", "cg").write_bytes(b"cg")
    cg_s2 = {**s2, **s2["cg"], "_splitCg": True}
    ops = plan_deck(
        [s1, cg_s2], [{"from": "s2", "to": "s1", "kind": "movie", "duration": 1.0}], {},
        output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=False, audience="cg", cg_affected={"s2"}
    )
    assert Path(ops[1]["items"][0]["path"]).name.endswith("_CG.mov")


def test_split_cg_movie_is_direct_1920_in_both_directions(tmp_path: Path):
    split = _slide("split", _camera(3.0, 101.0, 8), _splitCg=True, includeSidePanels=False)
    legacy = _slide("legacy", _camera(3.0, 102.0, 8), cgShiftX=300, includeSidePanels=False)
    for sid in ("split", "legacy"):
        _dummy_png(tmp_path / "stills" / f"{sid}_CG.png")
        movie_path(tmp_path, sid, "cg").parent.mkdir(parents=True, exist_ok=True)
        movie_path(tmp_path, sid, "cg").write_bytes(b"cg")
    link = lambda start, end: [{"from": start, "to": end, "kind": "movie", "duration": 1.0}]

    split_to_legacy = plan_deck(
        [split, legacy], link("split", "legacy"), {}, output_dir=tmp_path, preview_dir=tmp_path,
        movie=None, wall=False, audience="cg", cg_affected={"split", "legacy"}
    )[0]["items"][0]
    legacy_to_split = plan_deck(
        [legacy, split], link("legacy", "split"), {}, output_dir=tmp_path, preview_dir=tmp_path,
        movie=None, wall=False, audience="cg", cg_affected={"split", "legacy"}
    )[0]["items"][0]

    assert (split_to_legacy["x"], split_to_legacy["w"]) == (0, 1920)
    assert (legacy_to_split["x"], legacy_to_split["w"]) == (0, 1920)


def test_oversized_morph_becomes_movie():
    cam_a, cam_b = _pan_camera(8, 800)
    a = _slide("s1", cam_a, includeSidePanels=True)
    b = _slide("s2", cam_b, includeSidePanels=True)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    geom = morph_plate_geom([a["camera"], b["camera"]])
    assert geom is not None
    assert max(geom["plateW"], geom["plateH"]) > 8192
    plates, next_links = assign_morph_plates([a, b], links)
    assert plates == {}
    assert next_links[0]["kind"] == "movie"
    assert "plateId" not in next_links[0]
    plan = maps_export_plan([a, b], links)
    assert plan["links"][0]["kind"] == "movie"
    assert {row["slideId"] for row in plan["stills"]} == {"s1", "s2"}
    assert plan["plates"] == []


def test_missing_export_rasters_raise(tmp_path: Path):
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    morph_root = tmp_path / "morph"
    morph_root.mkdir()
    job = _job(
        morph_root,
        [a, b],
        [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}],
    )
    with pytest.raises(FileNotFoundError, match="Missing export plate"):
        export_maps_job(job, export_lw=True, export_cg=False)
    movie_root = tmp_path / "movie"
    movie_root.mkdir()
    movie_job = _job(
        movie_root,
        [a, b],
        [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0, "playWithoutClick": False}],
    )
    with pytest.raises(FileNotFoundError, match="Missing export still"):
        export_maps_job(movie_job, export_lw=True, export_cg=False)


def _backdrop_movie_slides_links():
    a = _slide("s1", _camera(3.0, 101.0, 8), movieDuration=2.5)
    b = _slide("s2", _camera(3.0, 102.0, 8))
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0, "playWithoutClick": False}]
    return a, b, links


def test_plan_deck_uses_backdrop_movie_when_present(tmp_path: Path):
    a, b, links = _backdrop_movie_slides_links()
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    item = ops[0]["items"][0]
    assert item["kind"] == "movie"
    assert (item["x"], item["y"], item["w"], item["h"]) == (CENTRE_ORIGIN_X, 0, CENTRE_WIDTH, WALL_HEIGHT)
    assert item["map"] is True
    assert ops[0]["transition"] == {"effect": None, "duration": 1.0, "automatic": True, "delay": 2.5}


def test_plan_deck_backdrop_movie_cg_shift(tmp_path: Path):
    a, b, links = _backdrop_movie_slides_links()
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=False)
    item = ops[0]["items"][0]
    origin = cg_crop_origin(a)
    assert item["x"] == whole_wall_to_cg(CENTRE_ORIGIN_X, origin[0])
    assert item["w"] == CENTRE_WIDTH


def test_plan_deck_backdrop_movie_missing_file_falls_back_to_still(tmp_path: Path):
    a, b, links = _backdrop_movie_slides_links()
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    item = ops[0]["items"][0]
    assert item["kind"] == "image"


def test_plan_deck_movie_wins_over_ending_plate(tmp_path: Path):
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b, movieDuration=2.0)
    c = _slide("s3", {**cam_b, "pitch": 40.0})
    links = [
        {"from": "s1", "to": "s2", "kind": "morph", "duration": 1.0, "playWithoutClick": False},
        {"from": "s2", "to": "s3", "kind": "movie", "duration": 2.0, "playWithoutClick": False},
    ]
    plates, links = assign_morph_plates([a, b, c], links)
    _write_plan_rasters(tmp_path, [a, b, c], links)
    mov = movie_path(tmp_path, "s2")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    ops = plan_deck(
        [a, b, c],
        links,
        plates,
        output_dir=tmp_path,
        preview_dir=tmp_path,
        movie=None,
        wall=True,
    )
    assert ops[0]["items"][0]["kind"] == "image"
    assert MAP_BG_RE.search(Path(ops[0]["items"][0]["path"]).name)
    assert ops[1]["items"][0]["kind"] == "movie"
    assert ops[1]["duplicate"] is False
    assert ops[1]["transition"]["delay"] == 2.0


def test_coerce_preserves_explicit_movie_on_style_mismatch():
    a = _slide("s1", _camera(3.0, 101.0, 8), style="positron")
    b = _slide("s2", _camera(3.0, 102.0, 8), style="dark")
    links = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "movie",
            "duration": 1.2,
            "playWithoutClick": False,
            "easing": "ease-in-out",
            "easeIn": 0.4,
            "easeOut": 0.3,
            "flyZoom": 5.0,
        }
    ]
    next_links = coerce_link_kinds([a, b], links)
    assert next_links[0]["kind"] == "movie"
    assert next_links[0]["easing"] == "ease-in-out"
    assert next_links[0]["easeIn"] == 0.4
    assert next_links[0]["easeOut"] == 0.3
    assert next_links[0]["flyZoom"] == 5.0


def test_plan_deck_movie_slide_omits_churches(tmp_path: Path):
    a, b, links = _backdrop_movie_slides_links()
    a["churches"] = [
        {
            "id": "p1",
            "name": "CHC",
            "lat": 1.3,
            "lon": 103.8,
            "kind": "dropPin",
            "color": "#c44a42",
        }
    ]
    b["churches"] = [
        {
            "id": "p2",
            "name": "Arrival",
            "lat": 3.1,
            "lon": 101.7,
            "kind": "dropPin",
            "color": "#c44a42",
        }
    ]
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    assert len(ops[0]["items"]) == 1
    assert ops[0]["items"][0]["kind"] == "movie"
    assert ops[0]["items"][0]["map"] is True
    assert len(ops[1]["items"]) > 1


def test_coerce_clears_route_when_not_movie():
    a = _slide("s1", _camera(3.0, 101.0, 8), style="positron")
    b = _slide("s2", _camera(3.0, 102.0, 8), style="dark")
    links = [
        {
            "from": "s1",
            "to": "s2",
            "kind": "morph",
            "duration": 1.2,
            "playWithoutClick": False,
            "easing": "ease-in-out",
            "route": {"points": [{"lat": 1.0, "lon": 103.0}, {"lat": 2.0, "lon": 104.0}]},
        }
    ]
    next_links = coerce_link_kinds([a, b], links)
    assert next_links[0]["kind"] == "cut"
    assert "route" not in next_links[0]
    assert "easing" not in next_links[0]


def test_build_deck_script_movie_backdrop_has_delay(tmp_path: Path):
    a, b, links = _backdrop_movie_slides_links()
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "set mv to make new image with properties {file:movFile}" in script
    assert "transition delay:2.5" in script


def test_lw_still_sits_on_centre_wall(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0))
    still = tmp_path / "s1.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True)
    mapped = next(item for item in items if item.get("map"))
    assert mapped["x"] == CENTRE_ORIGIN_X
    assert mapped["w"] == CENTRE_WIDTH
    assert mapped["h"] == WALL_HEIGHT


def test_fw_still_fills_wall(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), includeSidePanels=True)
    still = tmp_path / "s1.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True)
    mapped = next(item for item in items if item.get("map"))
    assert mapped["x"] == 0
    assert mapped["w"] == WALL_WIDTH
    assert mapped["h"] == WALL_HEIGHT


def test_hop_capture_size_is_max_from_to():
    a = _slide("s1", _camera(3.0, 101.0, 8))
    b = _slide("s2", _camera(3.0, 102.0, 8), includeSidePanels=True)
    assert hop_capture_size(a, b) == (WALL_WIDTH, WALL_HEIGHT)
    assert hop_capture_size(b, a) == (WALL_WIDTH, WALL_HEIGHT)
    assert hop_capture_size(a, a) == (CENTRE_WIDTH, WALL_HEIGHT)


def test_plan_deck_movie_uses_max_capture_width(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0, 8), movieDuration=2.0)
    b = _slide("s2", _camera(3.0, 102.0, 8), includeSidePanels=True)
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0, "playWithoutClick": False}]
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    item = ops[0]["items"][0]
    assert item["kind"] == "movie"
    assert (item["x"], item["y"], item["w"], item["h"]) == (0, 0, WALL_WIDTH, WALL_HEIGHT)
