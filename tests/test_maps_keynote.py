"""Maps Keynote export: plate math and mocked osascript. No live Keynote, no real .key."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

from PIL import Image
import pytest

from obed_edom.maps_geo import CENTRE_ORIGIN_X, CENTRE_WIDTH, DEFAULT_HIDDEN_LAYERS, clamp_cg_shift, default_landmark_size, world_width
from obed_edom.maps_keynote import (
    CG_HEIGHT,
    CG_WIDTH,
    CREDITS_FONT,
    DOT_SIZE,
    DROP_SIZE,
    DSK_HEIGHT,
    DSK_SCALE,
    DSK_WIDTH,
    LABEL_BOLD_FALLBACK,
    LABEL_BOLD_FONT,
    LABEL_CHAR_W,
    LABEL_FONT_PT,
    LABEL_SCALE_MAX,
    LABEL_SCALE_MIN,
    MAP_BG_RE,
    NAME_HEIGHT,
    PANEL_EDGES,
    PILL_PAD_X,
    PILL_PAD_Y,
    WALL_HEIGHT,
    WALL_WIDTH,
    _default_object_size,
    _place_churches,
    _read_region_manifest,
    _render_reveals,
    assign_morph_plates,
    avoid_straddle,
    build_deck_script,
    build_shared_plate_probe_script,
    build_slide_items,
    cg_crop_origin,
    coerce_link_kinds,
    credits_op,
    dsk_item,
    dsk_ops,
    export_maps_job,
    fit_morph_plate,
    maps_export_dests,
    maps_export_stem,
    hop_capture_size,
    maps_export_plan,
    maps_movie_autoplay_mode,
    maps_poster_frame_mode,
    morph_plate_geom,
    plate_filename,
    plate_id_for,
    plate_placement,
    plan_deck,
    project_into_camera,
    project_into_plate,
    slide_capture_size,
    split_cg_export_plan,
    whole,
    _emit_adjust_map,
    _emit_item,
)
from obed_edom.maps_pins import LABEL_PILL_RGB, PIN_ASPECT, label_pill_png_path
from obed_edom.maps_reveal import REVEAL_FPS, reveal_movie_fingerprint
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


def _region_manifest(pieces: list[dict] | None = None, width: int = 16, height: int = 16) -> dict:
    pieces = pieces if pieces is not None else [{"id": "USA", "x": 0, "y": 0, "w": width, "h": height}]
    pieces = [{**piece, "index": k} for k, piece in enumerate(pieces)]
    return {"width": width, "height": height, "pieces": pieces}


def _dummy_region(base_path: Path, pieces: list[dict] | None = None, width: int = 16, height: int = 16) -> Path:
    """Writes a `-regions.json` manifest plus one `-region-<k>.png` per piece next to `base_path`."""
    stem, suffix = base_path.stem, base_path.suffix
    manifest = _region_manifest(pieces, width, height)
    for k in range(len(manifest["pieces"])):
        _dummy_png(base_path.with_name(f"{stem}-region-{k}{suffix}"))
    manifest_path = base_path.with_name(f"{stem}-regions.json")
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path


def _pin_items(items: list[dict]) -> list[dict]:
    """Dots and static drop pins are plain images: not the map, not a landmark,
    not a label pill."""
    return [
        item for item in items
        if item["kind"] == "image"
        and not item.get("map")
        and not item.get("landmark")
        and not item.get("labelPill")
    ]


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
    assert "rotation" not in place_a
    assert "rotation" not in place_b


def test_bearing_change_rotates_the_shared_plate():
    a, b = _pan_camera(8, 400)
    a["bearing"] = 0
    b["bearing"] = 30
    same = morph_plate_geom([a, {**b, "bearing": 0}])
    turned = morph_plate_geom([a, b])
    assert same is not None and turned is not None
    assert turned["plateW"] * turned["plateH"] > same["plateW"] * same["plateH"]
    place_a = plate_placement(a, turned)
    place_b = plate_placement(b, turned)
    assert "rotation" not in place_a
    assert place_b["rotation"] == pytest.approx(30)
    assert project_into_plate(a["lat"], a["lon"], turned, place_a) == pytest.approx(
        (WALL_WIDTH / 2, WALL_HEIGHT / 2), abs=1.0
    )


def test_emit_sets_keynote_rotation_on_bearing_change():
    item = {
        "kind": "image",
        "x": -200,
        "y": -50,
        "w": 8000,
        "h": 2000,
        "path": "/tmp/plate.png",
        "map": True,
        "rotation": 30,
    }
    script = "\n".join(_emit_item(item))
    assert "set rotation of img to 30" in script
    assert "set width of img to 8000" in script
    adjust = "\n".join(_emit_adjust_map(item))
    assert "set rotation of image 1 to 30" in adjust


def test_cg_shift_clamp_used(tmp_path: Path):
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
        pin_root=tmp_path / "pins",
    )
    mapped = next(item for item in items if item.get("map"))
    assert mapped["x"] == whole_wall_to_cg(CENTRE_ORIGIN_X, origin[0])
    assert mapped["w"] == CENTRE_WIDTH


def whole_wall_to_cg(wall_x: float, origin_x: float) -> int:
    return int(round(wall_x - origin_x))


def test_credits_op_emits_one_text_item_per_line():
    op = credits_op(["a", "b"], width=int(WALL_WIDTH), height=int(WALL_HEIGHT))
    assert len(op["items"]) == 3
    assert all(item["kind"] == "text" for item in op["items"])
    assert all("\n" not in item["text"] for item in op["items"])
    assert "alignment" not in op["items"][0]
    centre_x = WALL_WIDTH / 2.0
    for item in op["items"]:
        assert abs((item["x"] + item["w"] / 2.0) - centre_x) <= 1


def test_credits_op_script_has_no_alignment_verb(tmp_path: Path):
    op = credits_op(["short", "a"], width=int(WALL_WIDTH), height=int(WALL_HEIGHT))
    script = build_deck_script([op], tmp_path / "deck.key", width=int(WALL_WIDTH), height=int(WALL_HEIGHT))
    assert "set alignment" not in script


@pytest.mark.parametrize(
    "width,height",
    [(int(WALL_WIDTH), int(WALL_HEIGHT)), (int(DSK_WIDTH), int(DSK_HEIGHT)), (int(CG_WIDTH), int(CG_HEIGHT))],
)
def test_credits_op_layout_stays_in_bounds_and_centred(width: int, height: int):
    short_line = "© OSM"
    long_line = "© MapTiler, terrain data from a very long attribution string that needs to wrap across multiple lines"
    op = credits_op([short_line, long_line], width=width, height=height)
    centre_x = width / 2.0
    items = op["items"]
    for item in items:
        assert item["x"] >= 0
        assert item["x"] + item["w"] <= width
        assert item["y"] >= 0
        assert item["y"] + item["h"] <= height
        assert abs((item["x"] + item["w"] / 2.0) - centre_x) <= 1
    short_item, long_item = items[1], items[2]
    assert short_item["w"] < long_item["w"]
    top = items[0]["y"]
    bottom = items[-1]["y"] + items[-1]["h"]
    block_h = bottom - top
    assert abs((height - block_h) / 2.0 - top) <= 2


def _export_scripts(monkeypatch, tmp_path: Path, *, attribution: str | None, credits: list[str] | None) -> list[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    if attribution is not None:
        job.result["attribution"] = attribution
    _write_plan_rasters(Path(job.result["outputDir"]), [a, b], links)
    result = export_maps_job(job, export_lw=True, export_cg=True, export_dsk=True, credits=credits)
    assert result.get("destPath") and result.get("destPathCg") and result.get("destPathDsk")
    return scripts


def test_export_maps_job_appends_credits_slide_when_attribution_credits(monkeypatch, tmp_path: Path):
    credits = ["© OpenStreetMap contributors", "© MapTiler"]
    with_credits = _export_scripts(monkeypatch, tmp_path / "with", attribution="credits", credits=credits)
    without_credits = _export_scripts(monkeypatch, tmp_path / "without", attribution="stamp", credits=credits)
    for script in with_credits:
        assert "© MapTiler" in script
    for script_with, script_without in zip(with_credits, without_credits):
        assert script_with.count("make new slide") - script_without.count("make new slide") == 1


def test_export_maps_job_omits_credits_slide_when_attribution_stamp(monkeypatch, tmp_path: Path):
    scripts = _export_scripts(monkeypatch, tmp_path, attribution="stamp", credits=["© OpenStreetMap contributors"])
    for script in scripts:
        assert "© OpenStreetMap" not in script


def test_export_maps_job_appends_credits_slide_when_attribution_missing(monkeypatch, tmp_path: Path):
    scripts = _export_scripts(monkeypatch, tmp_path, attribution=None, credits=["© OpenStreetMap contributors"])
    for script in scripts:
        assert "© OpenStreetMap" in script


def test_credits_slide_not_rescaled_in_dsk_script(monkeypatch, tmp_path: Path):
    scripts = _export_scripts(monkeypatch, tmp_path, attribution="credits", credits=["© OpenStreetMap contributors"])
    lw_script, dsk_script, _cg_script = scripts
    assert f"to {CREDITS_FONT}\n" in dsk_script
    assert f"to {CREDITS_FONT}\n" in lw_script
    assert f"to {whole(CREDITS_FONT * DSK_SCALE)}\n" not in dsk_script


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


def test_maps_export_stem_strips_audience_suffix():
    assert maps_export_stem("Sunday.key") == "Sunday"
    assert maps_export_stem("Sunday_CG.key") == "Sunday"
    assert maps_export_stem("Sunday_DSK.key") == "Sunday"
    assert maps_export_stem("Sunday_LW.key") == "Sunday"


def test_maps_export_dests_single_target_uses_chosen_path(tmp_path: Path):
    chosen = tmp_path / "Desktop" / "My Maps.key"
    dest_lw, dest_cg, dest_dsk = maps_export_dests(
        export_lw=False,
        export_cg=True,
        export_dsk=False,
        output_dir=tmp_path / "out",
        stem="maps-t1",
        export_path=chosen,
    )
    assert dest_lw is None and dest_dsk is None
    assert dest_cg == chosen


def test_maps_export_dests_multiple_targets_use_stem_suffixes(tmp_path: Path):
    dest_lw, dest_cg, dest_dsk = maps_export_dests(
        export_lw=True,
        export_cg=True,
        export_dsk=True,
        output_dir=tmp_path / "out",
        stem="maps-t1",
        export_path=tmp_path / "Desktop" / "Sunday_CG.key",
    )
    assert dest_lw == tmp_path / "Desktop" / "Sunday.key"
    assert dest_cg == tmp_path / "Desktop" / "Sunday_CG.key"
    assert dest_dsk == tmp_path / "Desktop" / "Sunday_DSK.key"


def test_export_maps_job_uses_export_path_for_dest(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": True}]
    job = _job(tmp_path, [a, b], links)
    _write_plan_rasters(Path(job.result["outputDir"]), [a, b], links)
    dest = tmp_path / "exports" / "Sunday.key"
    dest.parent.mkdir()
    result = export_maps_job(job, export_lw=True, export_cg=False, export_path=dest)
    assert result["destPath"] == str(dest)
    assert "destPathCg" not in result


def test_stale_dest_path_dropped_when_target_not_reexported(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": True}]
    job = _job(tmp_path, [a, b], links)
    _write_plan_rasters(Path(job.result["outputDir"]), [a, b], links)
    first = export_maps_job(job, export_lw=True, export_cg=True)
    assert first.get("destPathCg")

    job.result = first
    second = export_maps_job(job, export_lw=True, export_cg=False)
    assert second.get("destPath")
    assert "destPathCg" not in second


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
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    pins = _pin_items(items)
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
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True,
        pin_root=tmp_path / "pins",
    )
    pins = _pin_items(items)
    assert len(pins) == 1
    assert Path(pins[0]["path"]).name.startswith("droppin-")
    assert not [item for item in items if item["kind"] == "text" and item.get("text") == "Private label"]


def test_static_drop_pin_tip_is_anchored_to_the_projected_location(tmp_path: Path):
    camera = _camera(3.0, 101.0, 8)
    # lat 3.1 projects to y = 503.539..., i.e. a NON-integral tip: the height must
    # still be the canonical raster height, not a projection-fraction artefact.
    slide = _slide(
        "s1",
        camera,
        churches=[{"id": "c", "name": "Anchor", "lat": 3.1, "lon": 101.0, "kind": "dropPin", "color": "#ff8a00"}],
    )
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True,
        pin_root=tmp_path / "pins",
    )
    pins = _pin_items(items)
    assert len(pins) == 1
    pin = pins[0]
    projected_x, projected_y = project_into_camera(3.1, 101.0, camera)
    assert projected_y != whole(projected_y)
    assert abs((pin["x"] + pin["w"] / 2) - projected_x) <= 1
    assert pin["h"] == whole(pin["w"] * PIN_ASPECT)
    assert pin["y"] + pin["h"] == whole(projected_y)


def test_dot_pin_is_solid_without_white_centre(tmp_path: Path):
    slide = _slide(
        "s1",
        _camera(3.0, 101.0, 8),
        churches=[{"id": "c", "name": "Dot", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42"}],
    )
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True,
        pin_root=tmp_path / "pins",
    )
    pins = _pin_items(items)
    assert len(pins) == 1
    dot = pins[0]
    assert dot["w"] == dot["h"] == whole(DOT_SIZE)
    projected_x, projected_y = project_into_camera(3.0, 101.0, _camera(3.0, 101.0, 8))
    assert abs((dot["x"] + dot["w"] / 2) - projected_x) <= 1
    assert abs((dot["y"] + dot["h"] / 2) - projected_y) <= 1
    assert Path(dot["path"]).name.startswith("dot-")


def _landmark_church(**extra) -> dict:
    row = {
        "id": "lm",
        "name": "Landmark",
        "lat": 3.0,
        "lon": 101.0,
        "kind": "landmark",
        "color": "#c44a42",
        "assetId": "asset1",
        "size": 100,
    }
    row.update(extra)
    return row


def test_landmark_scale_with_map_zoom_in_doubles_width(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_landmark_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins")
    landmark = next(item for item in items if item.get("landmark"))
    assert landmark["w"] == 200


def test_landmark_scale_with_map_zoom_out_halves_width(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    camera = _camera(3.0, 101.0, 4)
    slide = _slide("s1", camera, churches=[_landmark_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins")
    landmark = next(item for item in items if item.get("landmark"))
    assert landmark["w"] == 50


def test_landmark_scale_with_map_zoom_in_doubles_width_on_morph_plate(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    cam_a, cam_b = _pan_camera(6, 400)
    slide = _slide("s1", cam_a, churches=[_landmark_church(scaleWithMap=True, sizeZoom=5)])
    geom = morph_plate_geom([cam_a, cam_b])
    plate_path = _dummy_png(tmp_path / "plate.png")
    items = build_slide_items(
        slide, plate=geom, plate_path=plate_path, still=None, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins",
    )
    landmark = next(item for item in items if item.get("landmark"))
    assert landmark["w"] == 200


def test_landmark_scale_with_map_off_is_unchanged(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_landmark_church(sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins")
    landmark = next(item for item in items if item.get("landmark"))
    assert landmark["w"] == 100


def test_landmark_scale_with_map_clamps_at_effective_size_max(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    camera = _camera(3.0, 101.0, 40)
    slide = _slide("s1", camera, churches=[_landmark_church(scaleWithMap=True, sizeZoom=5, size=100)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins")
    landmark = next(item for item in items if item.get("landmark"))
    assert landmark["w"] == 20000


def _dot_church(**extra) -> dict:
    row = {"id": "dot", "name": "Dot", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42", "size": 100}
    row.update(extra)
    return row


def _drop_pin_church(**extra) -> dict:
    row = {"id": "drop", "name": "Drop", "lat": 3.0, "lon": 101.0, "kind": "dropPin", "color": "#c44a42", "size": 100}
    row.update(extra)
    return row


def test_dot_scale_with_map_zoom_in_doubles_width(tmp_path: Path):
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_dot_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    oval = _pin_items(items)[0]
    assert oval["w"] == 200


def test_dot_scale_with_map_zoom_out_halves_width(tmp_path: Path):
    camera = _camera(3.0, 101.0, 4)
    slide = _slide("s1", camera, churches=[_dot_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    oval = _pin_items(items)[0]
    assert oval["w"] == 50


def test_dot_scale_with_map_off_is_unchanged(tmp_path: Path):
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_dot_church(sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    oval = _pin_items(items)[0]
    assert oval["w"] == 100


def test_drop_pin_scale_with_map_zoom_in_doubles_width(tmp_path: Path):
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_drop_pin_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    head = _pin_items(items)[0]
    assert head["w"] == 200


def test_drop_pin_scale_with_map_zoom_out_halves_width(tmp_path: Path):
    camera = _camera(3.0, 101.0, 4)
    slide = _slide("s1", camera, churches=[_drop_pin_church(scaleWithMap=True, sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    head = _pin_items(items)[0]
    assert head["w"] == 50


def test_drop_pin_scale_with_map_off_is_unchanged(tmp_path: Path):
    camera = _camera(3.0, 101.0, 6)
    slide = _slide("s1", camera, churches=[_drop_pin_church(sizeZoom=5)])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    head = _pin_items(items)[0]
    assert head["w"] == 100


def test_landmark_sub_one_px_is_dropped_but_others_remain(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    _dummy_png(asset_root / "asset2.png")
    camera = _camera(3.0, 101.0, 8)
    tiny = _landmark_church(id="tiny", assetId="asset1", size=0.5)
    visible = {**_landmark_church(id="visible", assetId="asset2", size=100), "lon": 101.01}
    slide = _slide("s1", camera, churches=[tiny, visible])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins")
    landmarks = [item for item in items if item.get("landmark")]
    assert len(landmarks) == 1


def test_landmark_with_reveal_mov_yields_movie_item_at_image_geometry(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    camera = _camera(3.0, 101.0, 8)
    reveal_mov = tmp_path / "reveal" / "s1-lm.mov"
    reveal_mov.parent.mkdir(parents=True, exist_ok=True)
    reveal_mov.write_bytes(b"mov")

    without_reveal = _slide("s1", camera, churches=[_landmark_church()])
    still = _dummy_png(tmp_path / "s1.png")
    baseline = build_slide_items(
        without_reveal, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins",
    )
    image_item = next(item for item in baseline if item.get("landmark"))
    assert image_item["kind"] == "image"

    with_reveal = _slide("s1", camera, churches=[_landmark_church()])
    revealed = build_slide_items(
        with_reveal, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins",
        reveals={("lw", "s1", "lm"): str(reveal_mov)}, reveal_audience="lw", sid="s1",
    )
    movie_item = next(item for item in revealed if item.get("landmark"))
    assert movie_item["kind"] == "movie"
    assert movie_item["path"] == str(reveal_mov)
    assert movie_item["fallback"]
    for key in ("x", "y", "w", "h"):
        assert movie_item[key] == image_item[key]


def test_emit_item_landmark_movie_fallback_uses_image_not_shape():
    import obed_edom.maps_keynote as mod

    item = mod._item(
        "movie", 0, 0, 100, 100, path="/tmp/reveal.mov", fallback="/tmp/still.png", landmark=True
    )
    script = "\n".join(mod._emit_item(item))
    assert "make new image with properties {file:" in script
    assert "shape type:" not in script


def test_emit_item_droppin_movie_no_fallback_omits_shape():
    import obed_edom.maps_keynote as mod

    item = mod._item("movie", 0, 0, 40, 40, path="/tmp/wave.mov")
    script = "\n".join(mod._emit_item(item))
    assert "shape type:" not in script
    assert "make new image with properties {file:" in script


def test_landmark_reveal_suppressed_on_duplicate_slide(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    reveal_mov = tmp_path / "reveal" / "s1-lm.mov"
    reveal_mov.parent.mkdir(parents=True, exist_ok=True)
    reveal_mov.write_bytes(b"mov")
    camera = _camera(3.0, 101.0, 8)
    slide = _slide("s1", camera, churches=[_landmark_church()])
    still = _dummy_png(tmp_path / "s1.png")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, asset_root=asset_root,
        pin_root=tmp_path / "pins", allow_reveal=False,
        reveals={("lw", "s1", "lm"): str(reveal_mov)}, reveal_audience="lw", sid="s1",
    )
    landmark_item = next(item for item in items if item.get("landmark"))
    assert landmark_item["kind"] == "image"


def test_render_reveals_returns_mapping_without_mutating_church(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    reveals, _, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert reveals[("lw", "s1", "lm")].endswith(".mov")
    assert "revealMov" not in church
    assert "revealMov" not in slide["churches"][0]


def test_render_reveals_regenerates_when_duration_or_opacity_changes(tmp_path: Path, monkeypatch):
    calls: list[float] = []

    def fake_render(asset, dest, *, duration, seed, opacity, strokes=4, fingerprint=None, is_cancelled=None):
        calls.append(duration)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"mov-{duration}-{opacity}".encode())
        if fingerprint is not None:
            dest.with_suffix(dest.suffix + ".fp").write_text(fingerprint)
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.render_reveal", fake_render)
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])

    reveals, _, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert len(calls) == 1
    dest = Path(reveals[("lw", "s1", "lm")])
    first_bytes = dest.read_bytes()

    # Unchanged inputs must reuse the cached movie.
    reveals_again, _, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert len(calls) == 1
    assert reveals_again[("lw", "s1", "lm")] == reveals[("lw", "s1", "lm")]
    assert dest.read_bytes() == first_bytes

    # A duration change must invalidate the cache and re-render.
    church["reveal"]["duration"] = 2.4
    _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert len(calls) == 2
    assert dest.read_bytes() != first_bytes

    # An opacity change (not covered by mtime) must also invalidate the cache.
    church["opacity"] = 0.5
    _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert len(calls) == 3


def test_render_reveals_uses_separate_lw_and_cg_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    lw_church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    cg_church = _landmark_church(reveal={"kind": "brush", "duration": 1.2}, opacity=0.4)
    slide = _slide(
        "s1", _camera(3.0, 101.0, 8), churches=[lw_church],
        cg={"camera": _camera(3.0, 101.0, 8), "style": "positron", "churches": [cg_church]},
    )
    reveals, _, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert reveals[("lw", "s1", "lm")] != reveals[("cg", "s1", "lm")]


def test_reveal_movie_composite_drops_sub_one_px_landmark_but_keeps_others(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    captured: dict[str, list] = {}

    def fake_render_slide(base_png, country_png, landmarks, dest, **_kw):
        captured["landmarks"] = landmarks
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mov")
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.render_slide_reveal_movie", fake_render_slide)
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    _dummy_png(output_dir / "assets" / "asset2.png")
    _dummy_png(output_dir / "stills" / "s1.png")
    tiny = _landmark_church(id="tiny", assetId="asset1", size=0.5, reveal={"kind": "brush", "duration": 1.2})
    visible = {
        **_landmark_church(id="visible", assetId="asset2", size=100, reveal={"kind": "brush", "duration": 1.2}),
        "lon": 101.01,
    }
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[tiny, visible], revealMovie=True)
    reveals, reveal_movies, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert reveals[("lw", "s1", "tiny")].endswith(".mov")
    assert reveals[("lw", "s1", "visible")].endswith(".mov")
    assert ("lw", "s1") in reveal_movies
    assert len(captured["landmarks"]) == 1


def test_reveal_movie_composite_uses_cg_view_camera_zoom(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    captured: dict[str, list] = {}

    def fake_render_slide(base_png, country_png, landmarks, dest, **_kw):
        captured["landmarks"] = landmarks
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mov")
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.render_slide_reveal_movie", fake_render_slide)
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    _dummy_png(output_dir / "stills" / "s1_CG.png")
    # scaleWithMap sized so it's visible at the lw camera's zoom (8) but shrinks below
    # 1px at the CG override camera's zoom (-40) — the composite must filter using the
    # cg view's own camera, not the top-level slide's.
    church = _landmark_church(id="lm", assetId="asset1", size=100, scaleWithMap=True, sizeZoom=8,
                               reveal={"kind": "brush", "duration": 1.2})
    slide = _slide(
        "s1", _camera(3.0, 101.0, 8), churches=[], revealMovie=True,
        cg={"camera": _camera(3.0, 101.0, -40), "style": "positron", "churches": [church]},
    )
    reveals, reveal_movies, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
    assert reveals[("cg", "s1", "lm")].endswith(".mov")
    assert ("cg", "s1") not in reveal_movies
    assert "landmarks" not in captured


def test_reveal_movie_slide_emits_bg_movie_and_no_still(tmp_path: Path):
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    camera = _camera(3.0, 101.0, 8)
    landmark = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    dot = {"id": "d1", "name": "Dot", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42", "showLabel": True}
    slide = _slide("s1", camera, churches=[landmark, dot], revealMovie=True)
    slide2 = _slide("s2", camera)
    _dummy_png(output_dir / "stills" / "s2.png")
    link = {"from": "s1", "to": "s2", "kind": "cut"}
    reveal_movie = output_dir / "movies" / "Map BG_s1-reveal.mov"
    reveal_movie.parent.mkdir(parents=True, exist_ok=True)
    reveal_movie.write_bytes(b"mov")
    ops = plan_deck(
        [slide, slide2], [link], {}, output_dir=output_dir, preview_dir=output_dir / "previews", movie=None,
        wall=True, reveals={}, reveal_movies={("lw", "s1"): str(reveal_movie)},
    )
    items = ops[0]["items"]
    assert items[0] == {
        "kind": "movie", "x": int(CENTRE_ORIGIN_X), "y": 0, "w": CENTRE_WIDTH, "h": WALL_HEIGHT,
        "path": str(reveal_movie), "map": True,
    }
    assert not any(item.get("kind") == "image" and item.get("map") for item in items)
    assert not any(item.get("landmark") for item in items)
    assert _pin_items(items)
    assert any(item.get("kind") == "text" for item in items)


def test_reveal_movie_skipped_when_slide_is_a_fly_source(tmp_path: Path):
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    camera = _camera(3.0, 101.0, 8)
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", camera, churches=[church], revealMovie=True)
    slide2 = _slide("s2", camera)
    link = {"from": "s1", "to": "s2", "kind": "movie"}
    reveals, reveal_movies, _ = _render_reveals(output_dir, [slide, slide2], [link], lambda _m: None, None)
    assert reveal_movies == {}
    assert reveals == {}


def test_reveal_movie_transition_is_automatic_dissolve_after_duration(tmp_path: Path):
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    camera = _camera(3.0, 101.0, 8)
    landmark = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", camera, churches=[landmark], revealMovie=True)
    slide2 = _slide("s2", camera)
    _dummy_png(output_dir / "stills" / "s2.png")
    link = {"from": "s1", "to": "s2", "kind": "cut"}
    reveal_movie = output_dir / "movies" / "Map BG_s1-reveal.mov"
    reveal_movie.parent.mkdir(parents=True, exist_ok=True)
    reveal_movie.write_bytes(b"mov")
    ops = plan_deck(
        [slide, slide2], [link], {}, output_dir=output_dir, preview_dir=output_dir / "previews", movie=None,
        wall=True, reveals={}, reveal_movies={("lw", "s1"): str(reveal_movie)},
    )
    assert ops[0]["transition"] == {"effect": "dissolve", "duration": 1.0, "automatic": True, "delay": 1.5}


def test_export_maps_job_does_not_leak_reveal_mov_into_stored_document(tmp_path: Path, monkeypatch):
    from obed_edom.web.maps import MapsDocument

    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)

    for stored_slide in result["slides"]:
        for stored_church in stored_slide.get("churches") or []:
            assert "revealMov" not in stored_church

    doc = MapsDocument.model_validate(
        {
            "defaultStyle": "positron",
            "crop": "wall",
            "exportLw": True,
            "exportCg": True,
            "slides": result["slides"],
            "links": result["links"],
        }
    )
    assert doc.slides[0].churches[0].reveal.duration == 1.2


def test_full_deck_landmark_reveal_script_has_no_shape_type(tmp_path: Path, monkeypatch):
    scripts: list[str] = []
    monkeypatch.setattr(
        "obed_edom.maps_keynote.run_osascript",
        lambda script, **_k: scripts.append(script) or _ok_osascript(script),
    )
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    export_maps_job(job, export_lw=True, export_cg=False)

    assert scripts
    for script in scripts:
        assert "shape type" not in script


def test_static_pin_wraps_across_dateline_and_low_zoom_world_copies(tmp_path: Path):
    near_dateline = _slide(
        "s1",
        _camera(0.0, 179.0, 8),
        churches=[{"id": "c", "name": "Dateline", "lat": 0.0, "lon": 181.0, "kind": "dot", "color": "#c44a42"}],
    )
    items = build_slide_items(
        near_dateline, plate=None, plate_path=None, still=_dummy_png(tmp_path / "dateline.png"), movie=None,
        wall=True, pin_root=tmp_path / "pins",
    )
    pin = _pin_items(items)[0]
    assert abs((pin["x"] + pin["w"] / 2) - WALL_WIDTH / 2) < 1000

    overview = _slide(
        "s2",
        _camera(0.0, 0.0, 0),
        includeSidePanels=True,
        churches=[{"id": "c", "name": "World", "lat": 0.0, "lon": 0.0, "kind": "dot", "color": "#c44a42"}],
    )
    copies = build_slide_items(
        overview, plate=None, plate_path=None, still=_dummy_png(tmp_path / "world.png"), movie=None,
        wall=True, pin_root=tmp_path / "pins",
    )
    assert len(_pin_items(copies)) >= 14


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
    assert "shape type" not in wall
    assert "droppin-c44a42" in wall


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


def test_inspect_keynote_terminates_blocked_jxa_when_cancelled(monkeypatch, tmp_path: Path, live_osascript):
    import obed_edom.inspect as inspect_mod
    from obed_edom import osascript_runner

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
    monkeypatch.setattr(osascript_runner.subprocess, "Popen", lambda *_a, **_k: started.set() or proc)
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
    pitched = {**_camera(3.0, 102.0, 8), "pitch": 20.0}
    b["cg"] = {"camera": pitched, "style": "positron", "highlights": [], "churches": []}
    movie = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}])[0]
    assert movie["kind"] == "movie"
    assert movie["duration"] == 1.7
    b["cg"]["style"] = "dark"
    cut = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}])[0]
    assert cut["kind"] == "cut"
    dissolve = coerce_link_kinds([a, b], [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 1.7}])[0]
    assert dissolve["kind"] == "dissolve"
    assert dissolve["duration"] == 1.7


def test_coerce_strips_flight_when_kind_stays_morph():
    a = _slide("s1", _camera(3.0, 101.0, 8))
    b = _slide("s2", _camera(3.0, 101.01, 8))
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7, "flight": "phases"}]
    next_links = coerce_link_kinds([a, b], links)
    assert next_links[0]["kind"] == "morph"
    assert "flight" not in next_links[0]


def test_coerce_demotes_morph_on_hidden_layers_mismatch():
    a = _slide("s1", _camera(3.0, 101.0, 8), hiddenLayers=["roadnames"])
    b = _slide("s2", _camera(3.0, 102.0, 8), hiddenLayers=["roadnames", "pois"])
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}]
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "cut"
    b["hiddenLayers"] = ["roadnames"]
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "morph"


def test_coerce_cg_layer_override_can_demote_while_lw_stays_morph():
    a = _slide("s1", _camera(3.0, 101.0, 8), hiddenLayers=["roadnames"])
    b = _slide("s2", _camera(3.0, 102.0, 8), hiddenLayers=["roadnames"])
    b["cg"] = {"camera": _camera(3.0, 102.0, 8), "style": "positron", "highlights": [], "churches": []}
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}]
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "morph"
    b["cg"]["hiddenLayers"] = ["roadnames", "pois"]
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "cut"
    b["cg"]["hiddenLayers"] = None
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "morph"


def test_export_plan_stills_and_plates_carry_hidden_layers():
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, hiddenLayers=["pois"])
    b = _slide("s2", cam_b, hiddenLayers=["pois"])
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2}])
    assert plan["stills"] == []
    assert plan["plates"][0]["hiddenLayers"] == ["pois"]
    plan_cut = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.2}])
    assert {row["slideId"]: row["hiddenLayers"] for row in plan_cut["stills"]} == {"s1": ["pois"], "s2": ["pois"]}


def test_export_plan_plate_rows_carry_slide_ids_full_wall():
    """FW slides (includeSidePanels) capture at WALL_WIDTH; the dashboard picks export scale 4
    (exportScale(7680) === 4, dashboard/src/maps/types.ts) from the plate's slideIds."""
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, includeSidePanels=True)
    b = _slide("s2", cam_b, includeSidePanels=True)
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2}])
    assert len(plan["plates"]) == 1
    assert plan["plates"][0]["slideIds"] == ["s1", "s2"]


def test_export_plan_plate_rows_carry_slide_ids_centre_only():
    """Centre-only slides capture at CENTRE_WIDTH; the dashboard picks export scale 2
    (exportScale(3840) === 2) from the same slideIds field."""
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, includeSidePanels=False)
    b = _slide("s2", cam_b, includeSidePanels=False)
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2}])
    assert len(plan["plates"]) == 1
    assert plan["plates"][0]["slideIds"] == ["s1", "s2"]


def test_export_plan_hidden_layers_default_when_unset():
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a)
    b = _slide("s2", cam_b)
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2}])
    assert plan["stills"] == []
    assert plan["plates"][0]["hiddenLayers"] == list(DEFAULT_HIDDEN_LAYERS)
    plan_cut = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.2}])
    assert {row["slideId"]: row["hiddenLayers"] for row in plan_cut["stills"]} == {
        "s1": list(DEFAULT_HIDDEN_LAYERS),
        "s2": list(DEFAULT_HIDDEN_LAYERS),
    }


def test_coerce_cg_hillshade_override_demotes_morph():
    a = _slide("s1", _camera(3.0, 101.0, 8), hillshade=True)
    b = _slide("s2", _camera(3.0, 102.0, 8), hillshade=True)
    b["cg"] = {"camera": _camera(3.0, 102.0, 8), "style": "positron", "highlights": [], "churches": []}
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}]
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "morph"
    b["cg"]["hillshade"] = False
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "cut"
    b["cg"]["hillshade"] = None
    assert coerce_link_kinds([a, b], links)[0]["kind"] == "morph"


def test_export_plan_stills_and_plates_carry_hillshade():
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, hillshade=True)
    b = _slide("s2", cam_b, hillshade=True)
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2}])
    assert plan["stills"] == []
    assert plan["plates"][0]["hillshade"] is True
    plan_cut = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.2}])
    assert {row["slideId"]: row["hillshade"] for row in plan_cut["stills"]} == {"s1": True, "s2": True}


def test_export_plan_still_defaults_hidden_layers_when_missing():
    a = _slide("s1", _camera(3.0, 101.0, 8))
    plan = maps_export_plan([a], [])
    assert plan["stills"][0]["hiddenLayers"] == list(DEFAULT_HIDDEN_LAYERS)


def test_export_plan_still_preserves_explicit_empty_hidden_layers():
    a = _slide("s1", _camera(3.0, 101.0, 8), hiddenLayers=[])
    plan = maps_export_plan([a], [])
    assert plan["stills"][0]["hiddenLayers"] == []


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


def test_oversized_morph_is_fitted_not_movie():
    cam_a, cam_b = _pan_camera(8, 800)
    a = _slide("s1", cam_a, includeSidePanels=True)
    b = _slide("s2", cam_b, includeSidePanels=True)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]
    native = morph_plate_geom([a["camera"], b["camera"]])
    assert native is not None
    assert max(native["plateW"], native["plateH"]) > 8192
    fitted = fit_morph_plate(native)
    assert max(fitted["plateW"], fitted["plateH"]) <= 8192
    plates, next_links = assign_morph_plates([a, b], links)
    assert next_links[0]["kind"] == "morph"
    plate_id = next_links[0]["plateId"]
    assert plate_id in plates
    assert max(float(plates[plate_id]["plateW"]), float(plates[plate_id]["plateH"])) <= 8192
    place_a = plate_placement(a["camera"], plates[plate_id], width=WALL_WIDTH)
    place_b = plate_placement(b["camera"], plates[plate_id], width=WALL_WIDTH)
    assert place_a["w"] == place_b["w"]
    assert place_a["w"] > WALL_WIDTH
    plan = maps_export_plan([a, b], links)
    assert plan["links"][0]["kind"] == "morph"
    assert plan["stills"] == []
    assert len(plan["plates"]) == 1
    assert max(plan["plates"][0]["plateW"], plan["plates"][0]["plateH"]) <= 8192


def test_zoom_in_morph_plate_overflows_the_frame():
    a = _slide("s1", _camera(3.0, 101.0, 10), includeSidePanels=False)
    b = _slide("s2", _camera(3.0, 101.0, 12), includeSidePanels=False)
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.0, "playWithoutClick": False}]
    native = morph_plate_geom([a["camera"], b["camera"]], widths=[3840.0, 3840.0])
    assert native is not None
    assert max(native["plateW"], native["plateH"]) > 8192
    plates, next_links = assign_morph_plates([a, b], links)
    assert next_links[0]["kind"] == "morph"
    geom = plates[next_links[0]["plateId"]]
    assert max(float(geom["plateW"]), float(geom["plateH"])) <= 8192
    place_close = plate_placement(b["camera"], geom, width=3840)
    assert place_close["w"] > 3840


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
    assert ops[0]["transition"] == {"effect": "dissolve", "duration": 1.0, "automatic": True, "delay": 2.5}


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


def test_coerce_keeps_manual_movie_on_appearance_mismatch():
    movie_link = {"from": "s1", "to": "s2", "kind": "movie", "duration": 1.2, "playWithoutClick": False}

    a = _slide("s1", _camera(3.0, 101.0, 8), highlights=["MYS"])
    b = _slide("s2", _camera(3.0, 102.0, 8), highlights=["SGP"])
    assert coerce_link_kinds([a, b], [movie_link])[0]["kind"] == "movie"

    a = _slide("s1", _camera(3.0, 101.0, 8), hiddenLayers=["roadnames"])
    b = _slide("s2", _camera(3.0, 102.0, 8), hiddenLayers=["roadnames", "pois"])
    assert coerce_link_kinds([a, b], [movie_link])[0]["kind"] == "movie"

    a = _slide("s1", _camera(3.0, 101.0, 8), hillshade=True)
    b = _slide("s2", _camera(3.0, 102.0, 8), hillshade=False)
    assert coerce_link_kinds([a, b], [movie_link])[0]["kind"] == "movie"


def test_coerce_keeps_manual_movie_on_cg_appearance_mismatch():
    a = _slide("s1", _camera(3.0, 101.0, 8))
    b = _slide("s2", _camera(3.0, 102.0, 8))
    b["cg"] = {"camera": _camera(3.0, 102.0, 8), "style": "positron", "highlights": [], "churches": [], "hillshade": True}

    morph_link = {"from": "s1", "to": "s2", "kind": "morph", "duration": 1.7}
    assert coerce_link_kinds([a, b], [morph_link])[0]["kind"] == "cut"

    movie_link = {"from": "s1", "to": "s2", "kind": "movie", "duration": 1.2, "playWithoutClick": False}
    assert coerce_link_kinds([a, b], [movie_link])[0]["kind"] == "movie"


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
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
    mapped = next(item for item in items if item.get("map"))
    assert mapped["x"] == CENTRE_ORIGIN_X
    assert mapped["w"] == CENTRE_WIDTH
    assert mapped["h"] == WALL_HEIGHT


def test_fw_still_fills_wall(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), includeSidePanels=True)
    still = tmp_path / "s1.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n")
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still, movie=None, wall=True, pin_root=tmp_path / "pins"
    )
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


def test_export_plan_still_carries_country_cutout_when_isolated():
    a = _slide("s1", _camera(3.0, 101.0), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    b = _slide("s2", _camera(3.0, 102.0))
    plan = maps_export_plan([a, b], [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0}])
    stills = {row["slideId"]: row for row in plan["stills"]}
    assert stills["s1"]["stillPngRegions"] == "s1-regions.json"
    assert "stillPngRegions" not in stills["s2"]


def test_plan_deck_emits_country_cutout_image_above_base(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    b = _slide("s2", _camera(3.0, 102.0))
    links = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    cap_w, cap_h = slide_capture_size(a)
    _dummy_region(tmp_path / "stills" / "s1.png", width=cap_w, height=cap_h)
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    items = ops[0]["items"]
    map_items = [item for item in items if item.get("map")]
    country_items = [item for item in items if item.get("country")]
    assert len(map_items) == 1
    assert len(country_items) == 1
    assert Path(map_items[0]["path"]).name == "s1.png"
    assert Path(country_items[0]["path"]).name == "s1-region-0.png"
    assert (map_items[0]["x"], map_items[0]["y"], map_items[0]["w"], map_items[0]["h"]) == (
        country_items[0]["x"],
        country_items[0]["y"],
        country_items[0]["w"],
        country_items[0]["h"],
    )
    assert len([item for item in ops[1]["items"] if item.get("map")]) == 1


def test_plan_deck_magic_move_duplicate_keeps_country_cutout(tmp_path: Path):
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    b = _slide("s2", cam_b, isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.0, "playWithoutClick": False}]
    plates, links = assign_morph_plates([a, b], links)
    plan = _write_plan_rasters(tmp_path, [a, b], links)
    for plate in plan["plates"]:
        name = plate_filename(plate["plateId"])
        _dummy_region(tmp_path / "plates" / name)
    ops = plan_deck([a, b], links, plates, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    assert ops[1]["duplicate"] is True
    country_items = [item for item in ops[1]["items"] if item.get("country")]
    assert len(country_items) == 1
    assert Path(country_items[0]["path"]).name.endswith("-region-0.png")

    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    tell_start = script.index("tell slide 2")
    tell_end = script.index("end tell", tell_start)
    body = script[tell_start:tell_end]
    assert "-country.png" not in body
    assert "make new image" not in body
    assert "set width of image 2 to" in body
    assert "set height of image 2 to" in body
    assert re.search(r"repeat with i from \(count of images\) to 3 by -1", body) is not None


def test_plan_deck_morph_member_with_no_own_highlights_still_gets_plate_cutout(tmp_path: Path):
    cam_a, cam_b = _pan_camera(8, 400)
    a = _slide("s1", cam_a, isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    b = _slide("s2", cam_b, isolate={"mode": "darken", "strength": 0.6}, highlights=[])
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.0, "playWithoutClick": False}]
    plates, links = assign_morph_plates([a, b], links)
    for plate_id in plates:
        name = plate_filename(plate_id)
        _dummy_png(tmp_path / "plates" / name)
        _dummy_region(tmp_path / "plates" / name)
    ops = plan_deck([a, b], links, plates, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    country_items = [item for item in ops[1]["items"] if item.get("country")]
    assert len(country_items) == 1
    assert Path(country_items[0]["path"]).name.endswith("-region-0.png")


def test_export_plan_inserts_landing_row_for_isolated_movie_destination():
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.5, "playWithoutClick": False}]
    plan = maps_export_plan([a, b], links)
    stills = {row["slideId"]: row for row in plan["stills"]}
    assert set(stills) == {"s1", "s2", "s2__landing"}
    landing = stills["s2__landing"]
    assert landing["camera"] == b["camera"]
    assert landing["highlights"] == []
    assert landing["isolate"] is None
    assert "stillPngRegions" not in landing
    assert landing["_landingFor"] == "s2"


def test_export_plan_no_landing_row_for_dissolve_or_no_highlights():
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    links = [{"from": "s1", "to": "s2", "kind": "dissolve", "duration": 1.0}]
    plan = maps_export_plan([a, b], links)
    assert {row["slideId"] for row in plan["stills"]} == {"s1", "s2"}

    c = _slide("s3", _camera(3.0, 102.0), isolate={"mode": "darken", "strength": 0.6}, highlights=[])
    plan2 = maps_export_plan([a, c], [{"from": "s1", "to": "s3", "kind": "movie", "duration": 1.0}])
    assert {row["slideId"] for row in plan2["stills"]} == {"s1", "s3"}


def test_plan_deck_inserts_landing_slide_between_movie_and_isolated_destination(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0, 8), movieDuration=2.0)
    b = _slide("s2", _camera(3.0, 102.0, 8), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"])
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.5, "playWithoutClick": False}]
    mov = movie_path(tmp_path, "s1")
    mov.parent.mkdir(parents=True, exist_ok=True)
    mov.write_bytes(b"fake-mov")
    _dummy_png(tmp_path / "stills" / "s2__landing.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    _dummy_region(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    assert [op["id"] for op in ops] == ["s1", "s2__landing", "s2"]
    assert ops[0]["transition"] == {"effect": "dissolve", "duration": 1.0, "automatic": True, "delay": 2.0}
    assert ops[1]["transition"] == {"effect": "dissolve", "duration": 1.5, "automatic": False}
    assert len([item for item in ops[2]["items"] if item.get("map")]) == 1
    assert len([item for item in ops[2]["items"] if item.get("country")]) == 1


def test_plan_deck_no_isolate_deck_ops_unchanged(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0))
    links = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    assert [op["id"] for op in ops] == ["s1", "s2"]


def test_split_cg_export_plan_keeps_landing_still_for_affected_slide():
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide(
        "s2", _camera(3.0, 102.0), isolate={"mode": "darken", "strength": 0.6}, highlights=["USA"],
        cg={"style": "toner"},
    )
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 1.0}]
    plan = split_cg_export_plan([a, b], links)
    assert "s2__landing" in {row["slideId"] for row in plan["stills"]}


def test_render_reveals_returns_poster_times_matching_shared_formula(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    for duration in (0.5, 1.2, 3.0):
        church = _landmark_church(reveal={"kind": "brush", "duration": duration})
        slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
        _, _, poster_times = _render_reveals(output_dir, [slide], [], lambda _m: None, None)
        expected = (max(2, round(duration * REVEAL_FPS)) - 1) / float(REVEAL_FPS)
        assert poster_times[("lw", "s1", "lm")] == pytest.approx(expected)


def test_place_churches_stamps_reveal_key_only_on_reveal_movie_items(tmp_path: Path):
    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    reveal_mov = tmp_path / "reveal" / "s1-lm.mov"
    reveal_mov.parent.mkdir(parents=True, exist_ok=True)
    reveal_mov.write_bytes(b"mov")
    camera = _camera(3.0, 101.0, 8)
    dot = {"id": "d1", "name": "Dot", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42"}
    churches = [_landmark_church(), dot]

    with_reveal = _place_churches(
        churches, plate=None, placement=None, camera=camera, wall=True, movie=None,
        asset_root=asset_root, pin_root=tmp_path / "pins",
        reveals={("lw", "s1", "lm"): str(reveal_mov)}, reveal_audience="lw", sid="s1",
    )
    revealed_item = next(item for item in with_reveal if item.get("landmark"))
    assert revealed_item["revealKey"] == ("lw", "s1", "lm")
    assert not any(item.get("revealKey") for item in with_reveal if item is not revealed_item)

    without_reveal = _place_churches(
        churches, plate=None, placement=None, camera=camera, wall=True, movie=None, asset_root=asset_root,
        pin_root=tmp_path / "pins",
    )
    assert not any("revealKey" in item for item in without_reveal)


def test_maps_poster_frame_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("OBED_MAPS_POSTER_FRAME", raising=False)
    assert maps_poster_frame_mode() == "off"
    assert maps_poster_frame_mode("on") == "on"
    assert maps_poster_frame_mode("verify") == "verify"
    assert maps_poster_frame_mode("bogus") == "off"


def test_export_maps_job_never_calls_patcher_when_gate_unset(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OBED_MAPS_POSTER_FRAME", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )

    def _boom(*_a, **_k):
        raise AssertionError("patch_movie_posters must not be called with the gate off")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_posters", _boom)
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "posterFrame" not in result


def test_export_maps_job_records_movie_autoplay_refusal_reason(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OBED_MAPS_POSTER_FRAME", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": True, "reason": "x", "ids": []},
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "posterFrame" not in result
    assert result["movieAutoplay"]
    assert result["movieAutoplay"][0]["refused"] is True
    assert result["movieAutoplay"][0]["reason"] == "x"
    # never fatal to export
    assert result["destPath"]


def test_export_maps_job_records_refusal_reason_when_gated_on(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "on")
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": True, "reason": "x", "posters": {}},
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"]
    assert result["posterFrame"][0]["refused"] is True
    assert result["posterFrame"][0]["reason"] == "x"


def _gated_export(tmp_path, monkeypatch):
    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "on")
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])
    return job


def test_export_maps_job_contains_planning_exception_as_refusal(tmp_path: Path, monkeypatch):
    job = _gated_export(tmp_path, monkeypatch)

    def _boom(*_a, **_k):
        raise RuntimeError("planning blew up")

    monkeypatch.setattr("obed_edom.iwa_movies.plan_movie_posters", _boom)
    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is True
    assert "planning blew up" in result["posterFrame"][0]["reason"]
    # export itself must not have raised/aborted -- destPath was recorded regardless
    assert result["destPath"]


def test_export_maps_job_contains_patch_exception_as_refusal(tmp_path: Path, monkeypatch):
    job = _gated_export(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )

    def _boom(*_a, **_k):
        raise RuntimeError("patch blew up")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_posters", _boom)
    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is True
    assert "patch blew up" in result["posterFrame"][0]["reason"]


def test_export_maps_job_contains_verify_reread_exception_as_refusal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "verify")
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_posters",
        lambda deck, posters: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )

    def _boom(*_a, **_k):
        raise RuntimeError("reread blew up")

    monkeypatch.setattr("obed_edom.iwa_movies.movie_archives", _boom)
    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is True
    assert "reread blew up" in result["posterFrame"][0]["reason"]


def test_export_maps_job_regenerates_deck_after_offline_write_corrupted(tmp_path: Path, monkeypatch):
    from obed_edom.iwa_write import OfflineWriteCorrupted, recovery_tmp_path

    job = _gated_export(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )

    def _boom(deck, posters):
        Path(deck).write_bytes(b"truncated")
        recovery_tmp_path(Path(deck)).write_bytes(b"recovery")
        raise OfflineWriteCorrupted("simulated truncation")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_posters", _boom)

    run_calls: list[str] = []
    real_ok = _ok_osascript
    tmp_paths: list[Path] = []

    def _counting_osascript(script: str, **_k):
        run_calls.append(script)
        return real_ok(script)

    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _counting_osascript)

    import obed_edom.maps_keynote as mod

    real_run_one_deck = mod._run_one_deck

    def _capturing_run_one_deck(ops, dest, **kw):
        tmp_paths.append(recovery_tmp_path(Path(dest)))
        return real_run_one_deck(ops, dest, **kw)

    monkeypatch.setattr("obed_edom.maps_keynote._run_one_deck", _capturing_run_one_deck)

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is True
    assert "truncated" in result["posterFrame"][0]["reason"]
    # _run_one_deck was invoked a second time to regenerate the (truncated) deck:
    # once for the initial export, once more after OfflineWriteCorrupted.
    assert len(run_calls) == 2
    # the recovery tmp file left behind by the (simulated) truncated rewrite is
    # cleaned up once regeneration succeeds.
    assert tmp_paths and not tmp_paths[-1].exists()


def test_export_maps_job_keeps_recovery_tmp_when_regeneration_fails(tmp_path: Path, monkeypatch):
    from obed_edom.iwa_write import OfflineWriteCorrupted, recovery_tmp_path

    job = _gated_export(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )

    recovery_holder: dict[str, Path] = {}

    def _boom(deck, posters):
        Path(deck).write_bytes(b"truncated")
        tmp = recovery_tmp_path(Path(deck))
        tmp.write_bytes(b"recovery")
        recovery_holder["path"] = tmp
        raise OfflineWriteCorrupted("simulated truncation")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_posters", _boom)

    import obed_edom.maps_keynote as mod

    real_run_one_deck = mod._run_one_deck
    calls = {"n": 0}

    def _run_one_deck_boom(*a, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("regeneration blew up")
        return real_run_one_deck(*a, **kw)

    monkeypatch.setattr("obed_edom.maps_keynote._run_one_deck", _run_one_deck_boom)

    with pytest.raises(RuntimeError, match="regeneration blew up"):
        export_maps_job(job, export_lw=True, export_cg=False)

    assert recovery_holder["path"].exists()


def test_export_maps_job_removes_stale_poster_frame_when_gate_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OBED_MAPS_POSTER_FRAME", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    job.result["posterFrame"] = [{"deck": "lw", "mode": "on", "applied": 1, "refused": False, "reason": None}]
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "posterFrame" not in result


def test_build_deck_script_creates_document_on_basic_black_theme(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0))
    links = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "set theDoc to make new document\n" in script
    assert 'set document theme of theDoc to theme "Basic Black"' in script
    assert 'set themeStatus to "basicblack"' in script
    assert 'set base slide of slide 1 of theDoc to master slide "Blank" of theDoc' in script
    # exactly one combined status line, emitted once at the end of the script.
    assert script.count('log "theme=" & themeStatus & " master=" & masterStatus') == 1


def test_build_deck_script_new_slides_use_blank_master_with_fallback(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0))
    links = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "make new slide at after slide 1\n" in script
    assert 'set base slide of slide 2 of theDoc to master slide "Blank" of theDoc' in script
    # every base-slide assignment (slide 1 included) degrades the single master status.
    assert script.count('set masterStatus to "default"') == 2
    assert 'set masterStatus to "blank"' in script


def test_build_deck_script_single_slide_deck_still_reports_master(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0))
    _dummy_png(tmp_path / "stills" / "s1.png")
    ops = plan_deck([a], [], {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert 'set masterStatus to "blank"' in script
    assert script.count('log "theme=" & themeStatus & " master=" & masterStatus') == 1


def test_run_one_deck_forwards_the_combined_status_line(tmp_path: Path, monkeypatch):
    import subprocess as _sp

    import obed_edom.maps_keynote as mod

    a = _slide("s1", _camera(3.0, 101.0))
    _dummy_png(tmp_path / "stills" / "s1.png")
    ops = plan_deck([a], [], {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)

    def _fake_run(script, **_k):
        return _sp.CompletedProcess(
            args=["osascript"], returncode=0, stdout="theme=basicblack master=blank\n", stderr=""
        )

    monkeypatch.setattr(mod, "run_osascript", _fake_run)
    job = _job(tmp_path, [a], [])
    mod._run_one_deck(
        ops, tmp_path / "Deck.key", width=7680, height=1080, log=lambda message: mod._log(job, message)
    )
    assert job.logs == ["theme=basicblack master=blank"]


def test_build_deck_script_theme_and_master_scripts_compile(tmp_path: Path):
    """A `try` block rescues only runtime errors, never a COMPILE error (627cd66) -- verify
    the theme-create and blank-master AppleScript this PR emits actually osacompiles."""
    import shutil
    import subprocess
    import tempfile

    if shutil.which("osacompile") is None:
        pytest.skip("osacompile unavailable (non-macOS)")

    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.0, 102.0))
    links = [{"from": "s1", "to": "s2", "kind": "cut", "duration": 1.0, "playWithoutClick": False}]
    _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s2.png")
    ops = plan_deck([a, b], links, {}, output_dir=tmp_path, preview_dir=tmp_path, movie=None, wall=True)
    # broaden past image-only ops: a movie with an image fallback, a text item, a
    # duplicated slide and a transition all have to compile too.
    movie = tmp_path / "clip.m4v"
    movie.write_bytes(b"x")
    ops[0]["items"] += [
        {
            "kind": "movie",
            "x": 10,
            "y": 10,
            "w": 50,
            "h": 50,
            "path": str(movie),
            "fallback": str(tmp_path / "stills" / "s1.png"),
        },
        {"kind": "text", "x": 30, "y": 30, "w": 100, "h": 40, "text": "Hope Church"},
    ]
    ops.append(
        {
            "duplicate": True,
            "transition": {"effect": "magic_move", "duration": 1.0, "automatic": True},
            "items": list(ops[0]["items"][:1]),
        }
    )
    script = build_deck_script(ops, tmp_path / "Deck.key", width=7680, height=1080)
    assert "duplicate slide" in script
    assert "make new text item" in script
    assert "transition effect:magic move" in script

    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osacompile", "-o", "/dev/null", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    assert "-2707" not in proc.stderr
    assert "-2741" not in proc.stderr


def test_maps_movie_autoplay_mode_defaults_on(monkeypatch):
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    assert maps_movie_autoplay_mode() == "on"
    assert maps_movie_autoplay_mode("off") == "off"
    assert maps_movie_autoplay_mode("verify") == "verify"
    assert maps_movie_autoplay_mode("bogus") == "on"


def test_export_maps_job_movie_autoplay_happy_path(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": False, "reason": None, "ids": ["300"]},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_autoplay",
        lambda deck, ids: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["movieAutoplay"][0]["applied"] == 1
    assert result["movieAutoplay"][0]["refused"] is False


def test_export_maps_job_movie_autoplay_verify_mismatch_refuses(tmp_path: Path, monkeypatch):
    """Verify mode must not report success when the read-back still shows the
    pre-patch values."""
    monkeypatch.setenv("OBED_MAPS_MOVIE_AUTOPLAY", "verify")
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": False, "reason": None, "ids": ["300"]},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_autoplay",
        lambda deck, ids: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.movie_autoplay_state",
        lambda deck, ids: {"300": {"playsAcrossSlides": True, "automatic": None}},
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    record = result["movieAutoplay"][0]
    assert record["refused"] is True
    assert record["applied"] == 0
    assert "verify read-back mismatch" in record["reason"]


def test_export_maps_job_movie_autoplay_off_records_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBED_MAPS_MOVIE_AUTOPLAY", "off")
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )

    def _boom(*_a, **_k):
        raise AssertionError("patch_movie_autoplay must not be called with the gate off")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_autoplay", _boom)
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "movieAutoplay" not in result


def test_export_maps_job_movie_autoplay_missing_extra_degrades_cleanly(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )

    def _missing_extra(mode, say=None):
        if say:
            say("Offline-write needs the `iwa` extra; forcing offline write off.")
        return "off"

    monkeypatch.setattr("obed_edom.offline_write.probe_iwa_extra", _missing_extra)

    def _boom(*_a, **_k):
        raise AssertionError("patch_movie_autoplay must not run when the iwa extra is missing")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_autoplay", _boom)
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert "movieAutoplay" not in result


def test_export_maps_job_invalidates_poster_record_on_autoplay_regeneration(tmp_path: Path, monkeypatch):
    from obed_edom.iwa_write import OfflineWriteCorrupted, recovery_tmp_path

    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "on")
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_posters",
        lambda deck, posters: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": False, "reason": None, "ids": ["300"]},
    )

    def _boom(deck, ids):
        Path(deck).write_bytes(b"truncated")
        recovery_tmp_path(Path(deck)).write_bytes(b"recovery")
        raise OfflineWriteCorrupted("simulated truncation")

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_autoplay", _boom)

    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is True
    assert result["posterFrame"][0]["reason"] == "discarded by autoplay regeneration"
    assert result["movieAutoplay"][0]["refused"] is True
    assert "truncated" in result["movieAutoplay"][0]["reason"]


def test_export_maps_job_plain_autoplay_refusal_leaves_poster_record_intact(tmp_path: Path, monkeypatch):
    """A plain (non-truncating) autoplay refusal must not invalidate a successful
    poster-frame record for the same deck -- only regeneration does that."""
    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "on")
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_posters",
        lambda deck, posters: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": True, "reason": "x", "ids": []},
    )
    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=False)
    assert result["posterFrame"][0]["refused"] is False
    assert result["posterFrame"][0]["applied"] == 1
    assert result["movieAutoplay"][0]["refused"] is True
    assert result["movieAutoplay"][0]["reason"] == "x"


def test_export_maps_job_cg_autoplay_regeneration_invalidates_cg_poster_record(tmp_path: Path, monkeypatch):
    """Export-level case for the cg call site: regeneration must only touch the cg
    poster record, and leave the lw record (a separate deck) untouched."""
    from obed_edom.iwa_write import OfflineWriteCorrupted, recovery_tmp_path

    monkeypatch.setenv("OBED_MAPS_POSTER_FRAME", "on")
    monkeypatch.delenv("OBED_MAPS_MOVIE_AUTOPLAY", raising=False)
    monkeypatch.setattr("obed_edom.maps_keynote.run_osascript", _ok_osascript)
    monkeypatch.setattr("obed_edom.maps_keynote.inspect_and_validate", lambda _p: [])
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_posters",
        lambda deck, targets: {"refused": False, "reason": None, "posters": {"300": 1.0}},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.patch_movie_posters",
        lambda deck, posters: {"refused": False, "reason": None, "touched": ["300"], "applied": 1},
    )
    monkeypatch.setattr(
        "obed_edom.iwa_movies.plan_movie_autoplay",
        lambda deck, targets: {"refused": False, "reason": None, "ids": ["300"]},
    )

    def _autoplay_patch(deck: Path, ids: list[str]):
        if "_CG" in deck.name:
            Path(deck).write_bytes(b"truncated")
            recovery_tmp_path(Path(deck)).write_bytes(b"recovery")
            raise OfflineWriteCorrupted("simulated truncation")
        return {"refused": False, "reason": None, "touched": ["300"], "applied": 1}

    monkeypatch.setattr("obed_edom.iwa_movies.patch_movie_autoplay", _autoplay_patch)

    church = _landmark_church(reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church])
    job = _job(tmp_path, [slide], [])
    _dummy_png(Path(job.result["outputDir"]) / "assets" / "asset1.png")
    _write_plan_rasters(Path(job.result["outputDir"]), [slide], [])

    result = export_maps_job(job, export_lw=True, export_cg=True)
    lw_poster = next(r for r in result["posterFrame"] if r["deck"] == "lw")
    cg_poster = next(r for r in result["posterFrame"] if r["deck"] == "cg")
    assert lw_poster["refused"] is False
    assert lw_poster["applied"] == 1
    assert cg_poster["refused"] is True
    assert cg_poster["reason"] == "discarded by autoplay regeneration"
    cg_autoplay = next(r for r in result["movieAutoplay"] if r["deck"] == "cg")
    assert cg_autoplay["refused"] is True
    assert "truncated" in cg_autoplay["reason"]


def _kitchen_sink_ops(tmp_path: Path, *, wall: bool = True) -> list[dict]:
    """One deck plan touching every `_emit_item` branch and every transition shape.

    Map still, country cutout, landmark movie with a still fallback, a dot, a
    movie-less drop pin and its label, then a duplicate slide (magic move), a
    movie backdrop (dissolve) and a fresh slide with an automatic no-effect
    transition.
    """
    import obed_edom.maps_keynote as mod

    asset_root = tmp_path / "assets"
    _dummy_png(asset_root / "asset1.png")
    reveal_mov = tmp_path / "reveal" / "s1-lm.mov"
    reveal_mov.parent.mkdir(parents=True, exist_ok=True)
    reveal_mov.write_bytes(b"mov")
    slide = _slide(
        "s1",
        _camera(3.0, 101.0, 8),
        isolate=True,
        highlights=["MYS"],
        churches=[
            {"id": "c1", "name": "Dot City", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42"},
            {"id": "c2", "name": "Pin City", "lat": 3.1, "lon": 101.1, "kind": "dropPin", "color": "#ff8a00"},
            _landmark_church(id="lm", lat=3.2, lon=101.2),
        ],
    )
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s1-region-0.png")
    items = build_slide_items(
        slide,
        plate=None,
        plate_path=None,
        still=still_path,
        movie=None,
        wall=wall,
        asset_root=asset_root,
        pin_root=tmp_path / "pins",
        region_manifest=_region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": 16, "h": 16}]),
        reveals={("lw", "s1", "lm"): str(reveal_mov)},
        sid="s1",
    )
    deck_width = WALL_WIDTH if wall else CENTRE_WIDTH
    bg_movie = tmp_path / "movies" / "s3.mov"
    bg_movie.parent.mkdir(parents=True, exist_ok=True)
    bg_movie.write_bytes(b"mov")
    return [
        {"id": "s1", "duplicate": False, "items": items,
         "transition": {"effect": "magic_move", "duration": 1.2, "automatic": False}},
        {"id": "s2", "duplicate": True, "items": items,
         "transition": {"effect": "dissolve", "duration": 0.8, "automatic": True}},
        {"id": "s3", "duplicate": False,
         "items": [mod._item("movie", 0, 0, deck_width, WALL_HEIGHT, path=str(bg_movie), map=True)],
         "transition": {"effect": None, "duration": 2.0, "automatic": True}},
        {"id": "s4", "duplicate": False,
         "items": [mod._item("text", 10, 20, 200, 40, text='Quote "x" & tail')],
         "transition": None},
        mod.credits_op(
            [
                "© OpenStreetMap contributors",
                "Elevation: Mapzen Terrain Tiles · SRTM & GMTED2010 data courtesy of the U.S. Geological Survey",
                'Data by "Acme\\Maps" Ltd.',
            ],
            width=deck_width,
            height=WALL_HEIGHT,
        ),
    ]


def test_deck_script_never_emits_shape_properties(tmp_path: Path):
    """All three real export paths: the 7680 wall plan, the 1920 CG plan built
    from wall=False items, and the 1920 DSK plan built by `dsk_ops`."""
    wall_ops = _kitchen_sink_ops(tmp_path)
    cg_ops = _kitchen_sink_ops(tmp_path, wall=False)
    matrix = (
        (int(WALL_WIDTH), wall_ops),
        (CG_WIDTH, cg_ops),
        (DSK_WIDTH, dsk_ops(wall_ops)),
    )
    for width, plan in matrix:
        script = build_deck_script(plan, tmp_path / "deck.key", width=width, height=int(WALL_HEIGHT))
        for banned in ("shape type", "fill type", "fill color", "color fill", "make new shape"):
            assert banned not in script, banned


def test_deck_script_and_plate_probe_compile_under_osacompile(tmp_path: Path):
    """`osascript <file>` compiles the whole file before running a line, so one
    unsupported term anywhere aborts the entire export (-2741). This is the
    offline guard: compile a deck plan covering every emitter branch."""
    if shutil.which("osacompile") is None:
        pytest.skip("osacompile unavailable (non-macOS)")

    deck = build_deck_script(
        _kitchen_sink_ops(tmp_path), tmp_path / "deck.key", width=int(WALL_WIDTH), height=int(WALL_HEIGHT)
    )
    probe = build_shared_plate_probe_script(tmp_path / "probe.key", _dummy_png(tmp_path / "probe.png"))
    for label, script in (("deck", deck), ("probe", probe)):
        source = tmp_path / f"{label}.applescript"
        source.write_text(script, encoding="utf-8")
        proc = subprocess.run(
            ["osacompile", "-o", str(tmp_path / f"{label}.scpt"), str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{label}: {proc.stderr}"


def test_credits_op_normalises_control_characters():
    op = credits_op(
        ["Line one\r\nwith CRLF", "Line two\nwith LF", "Tabbed\tvalue", "   ", ""],
        width=int(WALL_WIDTH), height=int(WALL_HEIGHT),
    )
    texts = [item["text"] for item in op["items"]]
    assert texts[1:] == ["Line one with CRLF", "Line two with LF", "Tabbed value"]
    for text in texts:
        assert "\r" not in text and "\n" not in text and "\t" not in text


def test_credits_op_with_crlf_compiles_under_osacompile(tmp_path: Path):
    if shutil.which("osacompile") is None:
        pytest.skip("osacompile unavailable (non-macOS)")
    op = credits_op(
        ["© OpenStreetMap contributors\r\nMulti-line credit", 'Quoted "value"\\with\\backslash'],
        width=int(WALL_WIDTH), height=int(WALL_HEIGHT),
    )
    script = build_deck_script([op], tmp_path / "deck.key", width=int(WALL_WIDTH), height=int(WALL_HEIGHT))
    source = tmp_path / "credits.applescript"
    source.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        ["osacompile", "-o", str(tmp_path / "credits.scpt"), str(source)],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_static_drop_pin_geometry_survives_the_dsk_scale(tmp_path: Path):
    slide = _slide(
        "s1",
        _camera(3.0, 101.0, 8),
        churches=[{"id": "c", "name": "Anchor", "lat": 3.0, "lon": 101.0, "kind": "dropPin", "color": "#ff8a00"}],
    )
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=_dummy_png(tmp_path / "s1.png"), movie=None, wall=True,
        pin_root=tmp_path / "pins",
    )
    pin = _pin_items(items)[0]
    scaled = dsk_item(pin)
    assert scaled["w"] == round(pin["w"] * DSK_SCALE)
    assert scaled["h"] == round(pin["h"] * DSK_SCALE)
    assert abs(scaled["h"] / scaled["w"] - pin["h"] / pin["w"]) < 0.02


def _label_churches() -> list[dict]:
    return [
        {"id": "c1", "name": "Dot City", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42", "showLabel": True},
        {"id": "c2", "name": "Pin City", "lat": 3.05, "lon": 101.05, "kind": "dropPin", "color": "#ff8a00", "showLabel": True},
    ]


def _place_labels(tmp_path: Path, churches: list[dict], **kwargs) -> list[dict]:
    params = {
        "plate": None,
        "placement": None,
        "camera": _camera(3.0, 101.0, 8),
        "wall": True,
        "movie": None,
        "pin_root": tmp_path / "pins",
    }
    params.update(kwargs)
    return _place_churches(churches, **params)


def test_label_pill_is_emitted_before_its_text_and_inflated_by_the_pad_constants(tmp_path: Path):
    items = _place_labels(tmp_path, _label_churches())
    texts = [index for index, item in enumerate(items) if item.get("kind") == "text"]
    pills = [index for index, item in enumerate(items) if item.get("labelPill")]
    assert len(texts) == 2
    assert len(pills) == 2
    for pill_index, text_index in zip(pills, texts):
        # Creation order is stacking order: the pill must precede its text.
        assert pill_index == text_index - 1
        pill, text = items[pill_index], items[text_index]
        assert pill["kind"] == "image"
        assert pill["x"] == text["x"] - PILL_PAD_X
        assert pill["y"] == text["y"] - PILL_PAD_Y
        assert pill["w"] == text["w"] + 2 * PILL_PAD_X
        assert pill["h"] == text["h"] + 2 * PILL_PAD_Y
        assert text["h"] == NAME_HEIGHT


def test_label_text_is_flagged_bold_and_sized_by_the_bold_char_width(tmp_path: Path):
    items = _place_labels(tmp_path, _label_churches())
    texts = [item for item in items if item.get("kind") == "text"]
    assert len(texts) == 2
    for text, church in zip(texts, _label_churches()):
        assert text["bold"] is True
        assert text["w"] == max(48, min(420, LABEL_CHAR_W * len(church["name"])))


def test_emitted_script_sets_the_bold_label_font_with_a_system_fallback(tmp_path: Path):
    """1x bold white (owner decision L3): the Gold reference face, falling back
    to a guaranteed system bold so a missing Amplitude never aborts the export."""
    script = build_deck_script(
        _kitchen_sink_ops(tmp_path), tmp_path / "deck.key", width=int(WALL_WIDTH), height=int(WALL_HEIGHT)
    )
    assert f'set font of object text of txt to "{LABEL_BOLD_FONT}"' in script
    assert f'set font of object text of txt to "{LABEL_BOLD_FALLBACK}"' in script
    assert f"set size of object text of txt to {LABEL_FONT_PT}\n" in script


def test_unflagged_text_items_keep_the_theme_font(tmp_path: Path):
    import obed_edom.maps_keynote as mod

    plain = "\n".join(mod._emit_item({"kind": "text", "x": 0, "y": 0, "w": 10, "h": 10, "text": "Plain"}))
    assert "set font of object text" not in plain


def test_label_pill_uses_the_fixed_gold_red_regardless_of_marker_colour(tmp_path: Path):
    items = _place_labels(tmp_path, _label_churches())
    pills = [item for item in items if item.get("labelPill")]
    assert len(pills) == 2
    for pill in pills:
        path = Path(pill["path"])
        assert path.is_file()
        assert path.name.startswith("labelpill-ee220c-")
        expected = label_pill_png_path(tmp_path / "pins", LABEL_PILL_RGB, pill["w"], pill["h"])
        assert path == expected


def test_show_label_false_emits_neither_pill_nor_text(tmp_path: Path):
    churches = [dict(church, showLabel=False) for church in _label_churches()]
    items = _place_labels(tmp_path, churches)
    assert not any(item.get("kind") == "text" for item in items)
    assert not any(item.get("labelPill") for item in items)


def test_show_label_defaults_to_on_for_a_legacy_export_with_no_key(tmp_path: Path):
    # A deck persisted before showLabel existed reaches export as a raw dict with no
    # showLabel key at all (export_maps_job works off job.result raw, no MapsChurch
    # validation). It must label, matching the UI's migration, or exporting without a
    # prior re-save would silently drop every label.
    church = {"id": "c1", "name": "No Flag", "lat": 3.0, "lon": 101.0, "kind": "dot", "color": "#c44a42"}
    items = _place_labels(tmp_path, [church])
    assert any(item.get("kind") == "text" for item in items)
    assert any(item.get("labelPill") for item in items)


def test_label_geometry_scales_with_the_marker(tmp_path: Path):
    plain = _place_labels(tmp_path, _label_churches())
    zoom = 8
    size_zoom = 7
    factor = 2 ** (zoom - size_zoom)
    scaled = _place_labels(
        tmp_path,
        [dict(church, scaleWithMap=True, sizeZoom=size_zoom) for church in _label_churches()],
    )

    def labels(items):
        return [item for item in items if item.get("kind") == "text" or item.get("labelPill")]

    for plain_item, scaled_item in zip(labels(plain), labels(scaled)):
        assert scaled_item["w"] == pytest.approx(plain_item["w"] * factor, abs=2)
        assert scaled_item["h"] == pytest.approx(plain_item["h"] * factor, abs=2)
        if "fontSize" in plain_item:
            assert scaled_item["fontSize"] == pytest.approx(plain_item["fontSize"] * factor, rel=1e-6)


def test_label_sits_above_its_marker(tmp_path: Path):
    for church in _label_churches():
        items = _place_labels(tmp_path, [church])
        pin = _pin_items(items)[0]
        pill = next(item for item in items if item.get("labelPill"))
        assert pill["y"] + pill["h"] <= pin["y"]
        pin_cx = pin["x"] + pin["w"] / 2.0
        pill_cx = pill["x"] + pill["w"] / 2.0
        assert abs(pin_cx - pill_cx) <= 1


def test_label_sits_above_a_non_square_landmark(tmp_path: Path):
    """A square asset makes the landmark's `y` (top-left of a `size` x `size` box)
    coincide with the rendered top-left, hiding a mismatch between the two. This
    landmark asset is 100x300 (portrait), so the rendered top is `cy - height`
    with `height = size * 3`, not `cy - size`."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (100, 300), (20, 30, 40, 255)).save(asset_root / "asset1.png", "PNG")
    church = _landmark_church(size=100, showLabel=True, name="Tall Landmark")
    items = _place_labels(tmp_path, [church], asset_root=asset_root)
    landmark = next(item for item in items if item.get("landmark"))
    pill = next(item for item in items if item.get("labelPill"))
    assert pill["y"] + pill["h"] <= landmark["y"]
    landmark_cx = landmark["x"] + landmark["w"] / 2.0
    pill_cx = pill["x"] + pill["w"] / 2.0
    assert abs(landmark_cx - pill_cx) <= 1


@pytest.mark.parametrize("label_scale", [1, 2], ids=["scale-1", "scaleWithMap-sizeZoom-2x"])
def test_dsk_and_cg_keep_the_pill_registered_with_its_text(tmp_path: Path, label_scale: float):
    import obed_edom.maps_keynote as mod

    churches = _label_churches()
    if label_scale != 1:
        # zoom=8 (the _place_labels default camera) over sizeZoom=7 scales the marker,
        # and with it the label, by 2**(8-7) == label_scale.
        churches = [dict(church, scaleWithMap=True, sizeZoom=7) for church in churches]
    items = _place_labels(tmp_path, churches)
    pairs = [
        (items[index], items[index + 1])
        for index, item in enumerate(items)
        if item.get("labelPill")
    ]
    assert pairs
    for pill, text in pairs:
        for mapped_pill, mapped_text, pad_scale in (
            (dsk_item(pill), dsk_item(text), DSK_SCALE),
            (*mod._to_cg([pill, text], (CENTRE_ORIGIN_X, 0.0)), 1),
        ):
            assert mapped_pill["x"] == mapped_text["x"] - round(PILL_PAD_X * label_scale * pad_scale)
            assert mapped_pill["w"] - mapped_text["w"] == round(2 * PILL_PAD_X * label_scale * pad_scale)
            assert mapped_pill["h"] - mapped_text["h"] == round(2 * PILL_PAD_Y * label_scale * pad_scale)


def test_a_zoom_scaled_drop_pin_label_follows_the_dynamic_font(tmp_path: Path):
    """A scaleWithMap drop pin's Keynote size is LABEL_FONT_PT × (effective px / DROP_SIZE)."""
    church = {
        "id": "p1",
        "name": "CHC Medan",
        "lat": 3.555,
        "lon": 98.644,
        "kind": "dropPin",
        "color": "#c44a42",
        "showLabel": True,
        "size": 224,
        "scaleWithMap": True,
        "sizeZoom": 17.6,
    }
    items = _place_labels(tmp_path, [church], camera=_camera(3.555, 98.644, 17.9))
    text = next(item for item in items if item.get("kind") == "text")
    size = int(min(20000, 224 * 2 ** (17.9 - 17.6)))
    assert text["fontSize"] == whole(LABEL_FONT_PT * (size / DROP_SIZE))


@pytest.mark.parametrize(
    ("size_zoom", "expected"),
    [(10, LABEL_SCALE_MIN), (4, LABEL_SCALE_MAX)],
    ids=["quarter-clamps-to-half", "sixteen-clamps-to-eight"],
)
def test_label_scale_clamps_the_total_scale(tmp_path: Path, size_zoom: float, expected: float):
    """The camera zoom is 8, so sizeZoom 10 is 0.25x and sizeZoom 4 is 16x."""
    churches = [dict(church, scaleWithMap=True, sizeZoom=size_zoom) for church in _label_churches()]
    items = _place_labels(tmp_path, churches)
    texts = [item for item in items if item.get("kind") == "text"]
    assert texts
    for text in texts:
        assert text["fontSize"] == whole(LABEL_FONT_PT * expected)
        assert text["h"] == NAME_HEIGHT * expected


def test_landmark_label_scale_follows_its_authored_size(tmp_path: Path):
    """A landmark is created at `default_landmark_size(assetWidth)`, so that size — not
    some other default — is the 1x label baseline."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (600, 600), (20, 30, 40, 255)).save(asset_root / "asset1.png", "PNG")
    baseline = default_landmark_size(600)
    fonts = {}
    for size in (baseline, baseline * 2):
        items = _place_labels(
            tmp_path,
            [_landmark_church(size=size, assetWidth=600, showLabel=True)],
            asset_root=asset_root,
        )
        fonts[size] = next(item for item in items if item.get("kind") == "text")["fontSize"]
    assert fonts[baseline] == pytest.approx(LABEL_FONT_PT)
    assert fonts[baseline * 2] == pytest.approx(LABEL_FONT_PT * 2)


def test_a_size_less_landmark_labels_at_1x(tmp_path: Path):
    """`_pin_size` and `_default_object_size` must agree, or a landmark the schema lets
    through without a `size` would label at the clamp instead of 1x."""
    asset_root = tmp_path / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (600, 600), (20, 30, 40, 255)).save(asset_root / "asset1.png", "PNG")
    church = _landmark_church(assetWidth=600, showLabel=True)
    church.pop("size")
    items = _place_labels(tmp_path, [church], asset_root=asset_root)
    assert next(item for item in items if item.get("kind") == "text")["fontSize"] == pytest.approx(LABEL_FONT_PT)


def test_emitted_script_sets_an_integer_font_size_for_a_scaled_label(tmp_path: Path):
    """Keynote's `size` property takes a whole number and the setter runs inside a bare
    `try`, so a fractional scale must be rounded before it reaches the script."""
    import obed_edom.maps_keynote as mod

    churches = [dict(_label_churches()[1], size=round(DROP_SIZE * 2.7))]
    items = _place_labels(tmp_path, churches)
    font = next(item for item in items if item.get("kind") == "text")["fontSize"]
    assert isinstance(font, int)
    script = build_deck_script(
        [{"id": "s1", "duplicate": False, "items": items, "transition": None}],
        tmp_path / "deck.key",
        width=int(WALL_WIDTH),
        height=int(WALL_HEIGHT),
    )
    sizes = re.findall(r"set size of object text of txt to (\S+)", script)
    assert sizes
    assert all(re.fullmatch(r"\d+", value) for value in sizes), sizes
    assert str(font) in sizes


@pytest.mark.parametrize("scale", [1.3, 2.7], ids=["scale-1.3", "scale-2.7"])
def test_fractional_label_scales_keep_the_pill_centred_on_its_text(tmp_path: Path, scale: float):
    """Fractional lat/lon put the marker on a fractional projected centre too."""
    churches = [
        dict(church, size=round(_default_object_size(church["kind"]) * scale), lat=3.0137, lon=101.0219)
        for church in _label_churches()
    ]
    items = _place_labels(tmp_path, churches)
    pairs = [(items[index], items[index + 1]) for index, item in enumerate(items) if item.get("labelPill")]
    assert pairs
    for pill, text in pairs:
        for mapped_pill, mapped_text in ((dsk_item(pill), dsk_item(text)), (pill, text)):
            pill_cx = mapped_pill["x"] + mapped_pill["w"] / 2.0
            text_cx = mapped_text["x"] + mapped_text["w"] / 2.0
            assert pill_cx == pytest.approx(text_cx)
            pill_cy = mapped_pill["y"] + mapped_pill["h"] / 2.0
            text_cy = mapped_text["y"] + mapped_text["h"] / 2.0
            assert pill_cy == pytest.approx(text_cy)
            left = mapped_text["x"] - mapped_pill["x"]
            right = (mapped_pill["x"] + mapped_pill["w"]) - (mapped_text["x"] + mapped_text["w"])
            assert left == right
            top = mapped_text["y"] - mapped_pill["y"]
            bottom = (mapped_pill["y"] + mapped_pill["h"]) - (mapped_text["y"] + mapped_text["h"])
            assert top == bottom


def test_movie_backdrop_slides_emit_no_label_pills(tmp_path: Path):
    bg_movie = tmp_path / "movies" / "s1.mov"
    bg_movie.parent.mkdir(parents=True, exist_ok=True)
    bg_movie.write_bytes(b"mov")
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=_label_churches())
    items = build_slide_items(
        slide,
        plate=None,
        plate_path=None,
        still=None,
        movie=None,
        wall=True,
        bg_movie=bg_movie,
        pin_root=tmp_path / "pins",
        sid="s1",
    )
    assert not any(item.get("labelPill") for item in items)
    assert not any(item.get("kind") == "text" for item in items)


def test_reveal_backdrop_slides_still_label_their_non_landmark_churches(tmp_path: Path):
    """The reveal backdrop is `render_slide_reveal_movie(still, ...)`, and the dashboard
    exports stills with no `churches` in its opts (MapsTab.tsx ~1550), so `addOverlays` —
    and with it the `churches-labels` symbol layer — never runs. The movie bakes only the
    painted landmark artwork, so pins and labels must still be placed over it."""
    movie = tmp_path / "reveal.mov"
    movie.write_bytes(b"mov")
    churches = [
        *_label_churches(),
        {"id": "lm", "name": "Landmark", "lat": 3.1, "lon": 101.1, "kind": "landmark", "reveal": {"duration": 1.2}},
    ]
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=churches, revealMovie=True)
    ops = plan_deck(
        [slide],
        [],
        {},
        output_dir=tmp_path,
        preview_dir=tmp_path,
        movie=None,
        wall=True,
        reveal_movies={("lw", "s1"): str(movie)},
    )
    items = ops[0]["items"]
    assert any(item.get("map") and item["kind"] == "movie" for item in items)
    labelled = [church for church in churches if church["kind"] != "landmark"]
    assert len([item for item in items if item.get("labelPill")]) == len(labelled)
    assert len([item for item in items if item.get("kind") == "text"]) == len(labelled)


def test_odd_length_names_scale_to_dsk_without_distorting_the_pill(tmp_path: Path):
    church = dict(_label_churches()[0], name="Odd Name")
    items = _place_labels(tmp_path, [church])
    pill = next(item for item in items if item.get("labelPill"))
    text = next(item for item in items if item.get("kind") == "text")
    for item in (pill, text):
        assert item["w"] % 2 == 0
        assert item["h"] % 2 == 0
        scaled = dsk_item(item)
        assert scaled["w"] / item["w"] == DSK_SCALE
        assert scaled["h"] / item["h"] == DSK_SCALE


def test_label_pill_outer_bounds_clear_the_wall_seam(tmp_path: Path):
    church = {"id": "c1", "name": "Seam Church", "lat": 3.0, "lon": 95.673, "kind": "dot", "color": "#c44a42", "showLabel": True}
    unguarded = _place_labels(tmp_path, [church], wall=False)
    straddler = next(item for item in unguarded if item.get("labelPill"))
    assert straddler["x"] < 1920 < straddler["x"] + straddler["w"]

    items = _place_labels(tmp_path, [church])
    pill = next(item for item in items if item.get("labelPill"))
    text = next(item for item in items if item.get("kind") == "text")
    for item in (pill, text):
        assert not (item["x"] < 1920 < item["x"] + item["w"])
    assert pill["x"] <= text["x"]
    assert text["x"] + text["w"] <= pill["x"] + pill["w"]
    assert pill["x"] == text["x"] - PILL_PAD_X


def test_still_plans_a_cutout_without_isolate():
    """A highlighted slide gets its cutout raster whether or not it is isolated."""
    plain = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    isolated = _slide("s2", _camera(3.0, 101.0), highlights=["MYS"], isolate={"mode": "darken", "strength": 0.6})
    bare = _slide("s3", _camera(3.0, 101.0))

    plan = maps_export_plan([plain, isolated, bare], [])
    rows = {row["slideId"]: row for row in plan["stills"]}

    assert rows["s1"]["stillPngRegions"] == "s1-regions.json"
    assert rows["s2"]["stillPngRegions"] == "s2-regions.json"
    assert "stillPngRegions" not in rows["s3"]


def test_landing_slide_plans_no_cutout():
    """`isolate_landing_slides` forces `highlights: []`, so the gate can never fire for one."""
    a = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"], isolate={"mode": "darken", "strength": 0.6})
    b = _slide("s2", _camera(20.0, 130.0, 4), highlights=["MYS"], isolate={"mode": "darken", "strength": 0.6})
    links = [{"from": "s1", "to": "s2", "kind": "movie", "duration": 2.0, "playWithoutClick": True}]

    plan = maps_export_plan([a, b], links)
    landing = [row for row in plan["stills"] if row["slideId"].endswith("__landing")]

    assert landing, "expected a synthetic landing still"
    assert all("stillPngRegions" not in row for row in landing)


def test_plate_plans_a_cutout_when_highlighted():
    a = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    b = _slide("s2", _camera(3.05, 101.05), highlights=["MYS"])
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]

    plan = maps_export_plan([a, b], links)
    plates = plan["plates"]

    assert plates, "expected a morph plate"
    assert plates[0]["platePngRegions"] == f"{plates[0]['plateId']}-regions.json"


def test_plate_plans_no_cutout_without_highlights():
    a = _slide("s1", _camera(3.0, 101.0))
    b = _slide("s2", _camera(3.05, 101.05))
    links = [{"from": "s1", "to": "s2", "kind": "morph", "duration": 1.2, "playWithoutClick": False}]

    plan = maps_export_plan([a, b], links)

    assert plan["plates"]
    assert "platePngRegions" not in plan["plates"][0]


def test_build_slide_items_stacks_the_cutout_without_isolate(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"], isolate=None)
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    piece_path = _dummy_png(tmp_path / "stills" / "s1-region-0.png")
    cap_w, cap_h = slide_capture_size(slide)

    items = build_slide_items(
        slide,
        plate=None,
        plate_path=None,
        still=still_path,
        movie=None,
        wall=True,
        pin_root=tmp_path / "pins",
        region_manifest=_region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": cap_w, "h": cap_h}], width=cap_w, height=cap_h),
    )
    map_items = [item for item in items if item.get("map")]
    country_items = [item for item in items if item.get("country")]

    assert len(map_items) == 1
    assert len(country_items) == 1
    assert country_items[0]["path"] == str(piece_path)
    assert (country_items[0]["x"], country_items[0]["y"]) == (map_items[0]["x"], map_items[0]["y"])
    assert (country_items[0]["w"], country_items[0]["h"]) == (map_items[0]["w"], map_items[0]["h"])


def test_build_slide_items_gives_a_plate_cutout_the_plate_geometry(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    b = _slide("s2", _camera(3.05, 101.05), highlights=["MYS"])
    geom = morph_plate_geom([a, b])
    plate_path = _dummy_png(tmp_path / "plates" / plate_filename("p-s1-s2"))
    piece_path = _dummy_png(tmp_path / "plates" / "map BG_p-s1-s2-region-0.png")

    unmapped = build_slide_items(
        a, plate=geom, plate_path=plate_path, still=None, movie=None, wall=True,
        pin_root=tmp_path / "pins", region_manifest=None,
    )
    plate_w = next(item for item in unmapped if item.get("map"))["w"]
    plate_h = next(item for item in unmapped if item.get("map"))["h"]

    items = build_slide_items(
        a,
        plate=geom,
        plate_path=plate_path,
        still=None,
        movie=None,
        wall=True,
        pin_root=tmp_path / "pins",
        region_manifest=_region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": plate_w, "h": plate_h}], width=plate_w, height=plate_h),
    )
    map_items = [item for item in items if item.get("map")]
    country_items = [item for item in items if item.get("country")]

    assert len(map_items) == 1
    assert len(country_items) == 1
    assert country_items[0]["path"] == str(piece_path)
    assert [country_items[0][key] for key in ("x", "y", "w", "h")] == [map_items[0][key] for key in ("x", "y", "w", "h")]


def test_build_slide_items_emits_n_pieces_in_manifest_order(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), highlights=["MYS", "IDN"])
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s1-region-0.png")
    _dummy_png(tmp_path / "stills" / "s1-region-1.png")
    _dummy_png(tmp_path / "stills" / "s1-region-2.png")
    manifest = _region_manifest(
        [
            {"id": "A", "x": 0, "y": 0, "w": 4, "h": 4},
            {"id": "B", "x": 10, "y": 10, "w": 5, "h": 5},
            {"id": "C", "x": 20, "y": 20, "w": 6, "h": 6},
        ],
        width=32,
        height=9,
    )
    items = build_slide_items(
        slide, plate=None, plate_path=None, still=still_path, movie=None, wall=True,
        pin_root=tmp_path / "pins", region_manifest=manifest,
    )
    map_index = next(i for i, item in enumerate(items) if item.get("map"))
    country_items = [item for item in items if item.get("country")]
    assert len(country_items) == 3
    assert items[map_index + 1 : map_index + 4] == country_items
    assert [Path(item["path"]).name for item in country_items] == [
        "s1-region-0.png", "s1-region-1.png", "s1-region-2.png",
    ]


def test_build_slide_items_scales_pieces_to_plate_placement(tmp_path: Path):
    a = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    b = _slide("s2", _camera(3.05, 101.05), highlights=["MYS"])
    geom = morph_plate_geom([a, b])
    plate_path = _dummy_png(tmp_path / "plates" / plate_filename("p-s1-s2"))
    piece_path = _dummy_png(tmp_path / "plates" / "map BG_p-s1-s2-region-0.png")
    manifest = _region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": 320, "h": 45}], width=640, height=90)

    items = build_slide_items(
        a, plate=geom, plate_path=plate_path, still=None, movie=None, wall=True,
        pin_root=tmp_path / "pins", region_manifest=manifest,
    )
    mapped = next(item for item in items if item.get("map"))
    piece = next(item for item in items if item.get("country"))
    assert piece["path"] == str(piece_path)
    scale = mapped["w"] / 640.0
    assert piece["w"] == pytest.approx(320 * scale)
    assert piece["h"] == pytest.approx(45 * scale)
    assert piece["x"] == pytest.approx(mapped["x"] + 0 * scale)
    assert piece["y"] == pytest.approx(mapped["y"] + 0 * scale)
    assert (mapped["w"], mapped["h"]) != (640, 90), "plate placement should not coincidentally match the manifest size"


def test_build_slide_items_warns_but_does_not_crash_on_aspect_mismatch(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s1-region-0.png")
    manifest = _region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": 16, "h": 16}], width=16, height=16)
    with pytest.warns(UserWarning, match="aspect ratio mismatch"):
        items = build_slide_items(
            slide, plate=None, plate_path=None, still=still_path, movie=None, wall=True,
            pin_root=tmp_path / "pins", region_manifest=manifest,
        )
    country_items = [item for item in items if item.get("country")]
    assert len(country_items) == 1


def test_build_slide_items_warns_and_skips_a_missing_piece(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"])
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    manifest = _region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": 16, "h": 16}])
    with pytest.warns(UserWarning, match="missing region cutout"):
        items = build_slide_items(
            slide, plate=None, plate_path=None, still=still_path, movie=None, wall=True,
            pin_root=tmp_path / "pins", region_manifest=manifest,
        )
    assert not [item for item in items if item.get("country")]


def test_build_slide_items_shifts_pieces_for_cg(tmp_path: Path):
    slide = _slide("s1", _camera(3.0, 101.0), highlights=["MYS"], cgShiftX=300)
    still_path = _dummy_png(tmp_path / "stills" / "s1.png")
    _dummy_png(tmp_path / "stills" / "s1-region-0.png")
    manifest = _region_manifest([{"id": "MYS", "x": 0, "y": 0, "w": 16, "h": 16}])

    items_wall = build_slide_items(
        slide, plate=None, plate_path=None, still=still_path, movie=None, wall=True,
        pin_root=tmp_path / "pins", region_manifest=manifest,
    )
    items_cg = build_slide_items(
        slide, plate=None, plate_path=None, still=still_path, movie=None, wall=False,
        pin_root=tmp_path / "pins", region_manifest=manifest,
    )
    mapped_wall = next(item for item in items_wall if item.get("map"))
    piece_wall = next(item for item in items_wall if item.get("country"))
    mapped_cg = next(item for item in items_cg if item.get("map"))
    piece_cg = next(item for item in items_cg if item.get("country"))

    assert piece_cg["x"] - mapped_cg["x"] == piece_wall["x"] - mapped_wall["x"]
    assert piece_cg["x"] != piece_wall["x"]


def test_emit_adjust_map_emits_one_triple_per_cutout_and_collapses_the_delete_formula():
    mapped = {"x": 0, "y": 0, "w": 100, "h": 50}
    cutouts = [{"x": 1, "y": 2, "w": 3, "h": 4}, {"x": 5, "y": 6, "w": 7, "h": 8}]
    body = "\n".join(_emit_adjust_map(mapped, cutouts))
    assert "set position of image 2 to {1, 2}" in body
    assert "set width of image 2 to 3" in body
    assert "set height of image 2 to 4" in body
    assert "set position of image 3 to {5, 6}" in body
    assert "set width of image 3 to 7" in body
    assert "set height of image 3 to 8" in body
    assert re.search(r"repeat with i from \(count of images\) to 4 by -1", body)

    empty_body = "\n".join(_emit_adjust_map(mapped, []))
    assert re.search(r"repeat with i from \(count of images\) to 2 by -1", empty_body)
    assert "image 2" not in empty_body


def test_render_reveals_composites_region_pieces_in_order(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    captured: dict[str, list] = {}

    def fake_render_slide(base_png, pieces, landmarks, dest, **_kw):
        captured["pieces"] = pieces
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mov")
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.render_slide_reveal_movie", fake_render_slide)
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    _dummy_png(output_dir / "stills" / "s1.png")
    _dummy_png(output_dir / "stills" / "s1-region-0.png")
    _dummy_png(output_dir / "stills" / "s1-region-1.png")
    manifest_path = output_dir / "stills" / "s1-regions.json"
    manifest_path.write_text(json.dumps({
        "width": 3840, "height": 1080,
        "pieces": [
            {"id": "A", "x": 0, "y": 0, "w": 4, "h": 4},
            {"id": "B", "x": 100, "y": 200, "w": 4, "h": 4},
        ],
    }))
    church = _landmark_church(id="lm", assetId="asset1", size=100, reveal={"kind": "brush", "duration": 1.2})
    slide = _slide("s1", _camera(3.0, 101.0, 8), churches=[church], highlights=["A", "B"], revealMovie=True)

    _, reveal_movies, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)

    assert ("lw", "s1") in reveal_movies
    pieces = captured["pieces"]
    assert [Path(p[0]).name for p in pieces] == ["s1-region-0.png", "s1-region-1.png"]
    assert (pieces[0][1], pieces[0][2]) == (0, 0)
    assert (pieces[1][1], pieces[1][2]) == (100, 200)
    assert (pieces[0][3], pieces[0][4]) == (4, 4)
    assert (pieces[1][3], pieces[1][4]) == (4, 4)


def test_read_region_manifest_returns_none_for_shape_missing_dimensions(tmp_path: Path):
    missing_dims = tmp_path / "s1-regions.json"
    missing_dims.write_text(json.dumps({"pieces": []}))
    assert _read_region_manifest(missing_dims) is None

    not_a_dict = tmp_path / "s2-regions.json"
    not_a_dict.write_text(json.dumps([1, 2, 3]))
    assert _read_region_manifest(not_a_dict) is None

    valid = tmp_path / "s3-regions.json"
    valid.write_text(json.dumps({"width": 10, "height": 10, "pieces": []}))
    assert _read_region_manifest(valid) == {"width": 10, "height": 10, "pieces": []}


def test_read_region_manifest_skips_malformed_pieces(tmp_path: Path):
    path = tmp_path / "s1-regions.json"
    path.write_text(
        json.dumps(
            {
                "width": 10,
                "height": 10,
                "pieces": [
                    {"id": "MYS", "x": 0, "y": 0, "w": 1, "h": 1},
                    {"id": "SGP", "x": 0, "y": 0},
                    "not-a-dict",
                ],
            }
        )
    )
    manifest = _read_region_manifest(path)
    assert manifest["pieces"] == [{"id": "MYS", "x": 0, "y": 0, "w": 1, "h": 1, "index": 0}]


def test_read_region_manifest_rejects_bool_and_non_int_dimensions(tmp_path: Path):
    bool_dims = tmp_path / "s1-regions.json"
    bool_dims.write_text(json.dumps({"width": True, "height": 10, "pieces": []}))
    assert _read_region_manifest(bool_dims) is None

    float_dims = tmp_path / "s2-regions.json"
    float_dims.write_text(json.dumps({"width": 10.5, "height": 10, "pieces": []}))
    assert _read_region_manifest(float_dims) is None

    negative_dims = tmp_path / "s3-regions.json"
    negative_dims.write_text(json.dumps({"width": -1, "height": 10, "pieces": []}))
    assert _read_region_manifest(negative_dims) is None


def test_read_region_manifest_skips_pieces_with_invalid_value_types(tmp_path: Path):
    path = tmp_path / "s1-regions.json"
    path.write_text(
        json.dumps(
            {
                "width": 10,
                "height": 10,
                "pieces": [
                    {"id": "MYS", "x": 0, "y": 0, "w": 1, "h": 1},
                    {"id": "STR", "x": "0", "y": 0, "w": 1, "h": 1},
                    {"id": "BOOL", "x": True, "y": 0, "w": 1, "h": 1},
                    {"id": "NEG", "x": -1, "y": 0, "w": 1, "h": 1},
                    {"id": "ZERO_W", "x": 0, "y": 0, "w": 0, "h": 1},
                    {"id": "OOB", "x": 9, "y": 9, "w": 5, "h": 5},
                ],
            }
        )
    )
    manifest = _read_region_manifest(path)
    assert manifest["pieces"] == [{"id": "MYS", "x": 0, "y": 0, "w": 1, "h": 1, "index": 0}]


def test_read_region_manifest_treats_non_list_pieces_as_empty(tmp_path: Path):
    path = tmp_path / "s1-regions.json"
    path.write_text(json.dumps({"width": 10, "height": 10, "pieces": {"id": "MYS"}}))
    assert _read_region_manifest(path) == {"width": 10, "height": 10, "pieces": []}


def test_read_region_manifest_treats_oversized_pieces_list_as_empty(tmp_path: Path):
    path = tmp_path / "s1-regions.json"
    pieces = [{"id": f"p{i}", "x": 0, "y": 0, "w": 1, "h": 1} for i in range(513)]
    path.write_text(json.dumps({"width": 10, "height": 10, "pieces": pieces}))
    assert _read_region_manifest(path) == {"width": 10, "height": 10, "pieces": []}


def test_read_region_manifest_preserves_original_index_across_dropped_pieces(tmp_path: Path):
    path = tmp_path / "s1-regions.json"
    path.write_text(
        json.dumps(
            {
                "width": 10,
                "height": 10,
                "pieces": [
                    {"id": "valid-0", "x": 0, "y": 0, "w": 1, "h": 1},
                    {"id": "invalid-1", "x": 0, "y": 0},
                    {"id": "valid-2", "x": 2, "y": 2, "w": 1, "h": 1},
                ],
            }
        )
    )
    manifest = _read_region_manifest(path)
    assert manifest["pieces"] == [
        {"id": "valid-0", "x": 0, "y": 0, "w": 1, "h": 1, "index": 0},
        {"id": "valid-2", "x": 2, "y": 2, "w": 1, "h": 1, "index": 2},
    ]


def test_build_slide_items_and_render_reveals_use_original_manifest_index(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "obed_edom.maps_reveal.render_reveal",
        lambda asset, dest, **_kw: dest.parent.mkdir(parents=True, exist_ok=True) or dest.write_bytes(b"mov") or dest,
    )
    captured: dict[str, list] = {}

    def fake_render_slide(base_png, pieces, landmarks, dest, **_kw):
        captured["pieces"] = pieces
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mov")
        return dest

    monkeypatch.setattr("obed_edom.maps_reveal.render_slide_reveal_movie", fake_render_slide)
    output_dir = tmp_path / "out"
    _dummy_png(output_dir / "assets" / "asset1.png")
    _dummy_png(output_dir / "stills" / "s1.png")
    _dummy_png(output_dir / "stills" / "s1-region-0.png")
    _dummy_png(output_dir / "stills" / "s1-region-2.png")
    manifest_path = output_dir / "stills" / "s1-regions.json"
    manifest_path.write_text(
        json.dumps(
            {
                "width": 3840,
                "height": 1080,
                "pieces": [
                    {"id": "valid-0", "x": 0, "y": 0, "w": 4, "h": 4},
                    {"id": "invalid-1", "x": 100, "y": 200},
                    {"id": "valid-2", "x": 300, "y": 400, "w": 4, "h": 4},
                ],
            }
        )
    )
    church = _landmark_church(id="lm", assetId="asset1", size=100, reveal={"kind": "brush", "duration": 1.2})
    slide = _slide(
        "s1", _camera(3.0, 101.0, 8), churches=[church], highlights=["valid-0", "valid-2"], revealMovie=True
    )

    _, reveal_movies, _ = _render_reveals(output_dir, [slide], [], lambda _m: None, None)

    assert ("lw", "s1") in reveal_movies
    pieces = captured["pieces"]
    assert [Path(p[0]).name for p in pieces] == ["s1-region-0.png", "s1-region-2.png"]
    assert (pieces[1][1], pieces[1][2]) == (300, 400)

    items = build_slide_items(
        slide,
        plate=None,
        plate_path=None,
        still=output_dir / "stills" / "s1.png",
        movie=None,
        wall=True,
        asset_root=output_dir / "assets",
        pin_root=output_dir / "pins",
        region_manifest=_read_region_manifest(manifest_path),
        sid="s1",
    )
    country_items = [item for item in items if item.get("country")]
    assert [Path(item["path"]).name for item in country_items] == ["s1-region-0.png", "s1-region-2.png"]


def test_reveal_movie_fingerprint_changes_when_manifest_changes(tmp_path: Path):
    still = _dummy_png(tmp_path / "s1.png")
    manifest_path = tmp_path / "s1-regions.json"
    manifest_path.write_text(json.dumps({"width": 16, "height": 16, "pieces": [{"id": "A", "x": 0, "y": 0, "w": 4, "h": 4}]}))
    fp1 = reveal_movie_fingerprint(still, [], manifest_path)
    manifest_path.write_text(json.dumps({"width": 16, "height": 16, "pieces": [{"id": "A", "x": 1, "y": 1, "w": 4, "h": 4}]}))
    fp2 = reveal_movie_fingerprint(still, [], manifest_path)
    assert fp1 != fp2
    assert reveal_movie_fingerprint(still, [], None) != fp1
