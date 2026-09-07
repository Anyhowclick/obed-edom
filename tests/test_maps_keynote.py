"""Maps Keynote export: plate math and mocked osascript. No live Keynote, no real .key."""

from __future__ import annotations

import subprocess
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
    export_maps_job,
    maps_export_plan,
    morph_plate_geom,
    plate_filename,
    plate_id_for,
    plate_placement,
    plan_deck,
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
    assert "file name:imgFile" in built
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


def test_coerce_movie_to_cut_on_style_mismatch():
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
    assert next_links[0]["kind"] == "cut"
    assert "easing" not in next_links[0]
    assert "easeIn" not in next_links[0]
    assert "easeOut" not in next_links[0]
    assert "flyZoom" not in next_links[0]


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
            "kind": "movie",
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
    assert "make new movie" in script
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
