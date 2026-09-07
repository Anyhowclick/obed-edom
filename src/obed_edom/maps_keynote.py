"""P1 Maps Keynote export: greenfield LW/CG stills and shared-plate morph.

P2: HEVC fly/route movies, is_backdrop Map BG, score_resize — deferred.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image

from obed_edom import keynote_app
from obed_edom.maps_geo import (
    CENTRE_ORIGIN_X,
    CENTRE_WIDTH,
    WALL_HEIGHT,
    WALL_WIDTH,
    camera_dict,
    clamp_cg_shift,
    clamp_lon,
    infer_hop_kind,
    inverse_mercator_y,
    mercator_y,
    world_width,
)
from obed_edom.maps_movie import movie_path
from obed_edom.paths import find_repo_root

# P2: HEVC fly/route movies, is_backdrop Map BG, score_resize — deferred.

CG_WIDTH = 1920
CG_HEIGHT = 1080
CG_ORIGIN_X = (WALL_WIDTH - CG_WIDTH) / 2.0  # 2880
MAX_TEXTURE_SIZE = 8192
TIMEOUT_SECONDS = 3600
PANEL_EDGES = (1920.0, 5760.0)
PIN_MAX_PT = 180
DOT_SIZE = 28
DROP_SIZE = 64
PHOTO_SIZE = 96
NAME_HEIGHT = 32
MAP_BG_RE = re.compile(r"map\s*bg", re.I)
PIN_WAVE_RE = re.compile(r"PIN\s*DROP\s*WAVE.*\.mov$", re.I)
_SKIP_WALK = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dashboard",
    "output",
}


def _as_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def whole(value: float) -> int:
    return int(round(float(value)))


def plate_filename(plate_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "", plate_id) or "plate"
    return f"map BG_{safe}.png"


def plate_id_for(slide_ids: list[str]) -> str:
    parts = [re.sub(r"[^A-Za-z0-9._-]+", "", str(sid)) or "s" for sid in slide_ids]
    return "p-" + "-".join(parts)


def keynote_is_available() -> bool:
    return keynote_app.app_path(keynote_app.bundle_id()) is not None


def parse_color(value: str) -> tuple[int, int, int]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raw = "c44a42"
    try:
        red, green, blue = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        red, green, blue = 0xC4, 0x4A, 0x42
    return red * 257, green * 257, blue * 257


def cg_crop_origin(slide: dict[str, Any]) -> tuple[float, float]:
    dx, _dy = clamp_cg_shift(slide.get("cgShiftX") or 0, 0)
    return (CG_ORIGIN_X + dx, 0.0)


def slide_includes_side_panels(slide: dict[str, Any]) -> bool:
    return bool(slide.get("includeSidePanels"))


def slide_capture_size(slide: dict[str, Any]) -> tuple[int, int]:
    """Raster size for this slide. Off (default) is the 3840×1080 LED centre."""
    if slide_includes_side_panels(slide):
        return int(WALL_WIDTH), int(WALL_HEIGHT)
    return int(CENTRE_WIDTH), int(WALL_HEIGHT)


def slide_map_origin_x(slide: dict[str, Any]) -> int:
    return 0 if slide_includes_side_panels(slide) else int(CENTRE_ORIGIN_X)


def normalized_viewport(
    camera: dict[str, Any],
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
) -> tuple[float, float, float, float]:
    zoom = float(camera.get("zoom") or 0)
    world = world_width(zoom)
    cx = (clamp_lon(float(camera.get("lon") or 0)) + 180.0) / 360.0
    cy = mercator_y(float(camera.get("lat") or 0))
    nw = float(width) / world
    nh = float(height) / world
    return (cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0)


def union_viewports(
    cameras: list[dict[str, Any]],
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
) -> tuple[float, float, float, float]:
    boxes = [normalized_viewport(cam, width, height) for cam in cameras]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def morph_plate_geom(
    cameras: list[dict[str, Any]],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
    widths: list[float] | None = None,
) -> dict[str, Any] | None:
    """Union mercator viewports; one raster at the deeper zoom. None if too large."""
    if not cameras:
        return None
    canvas = list(widths) if widths is not None else [width] * len(cameras)
    if len(canvas) != len(cameras):
        canvas = [width] * len(cameras)
    boxes = [normalized_viewport(cam, w, height) for cam, w in zip(cameras, canvas)]
    union = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    z_plate = max(float(cam.get("zoom") or 0) for cam in cameras)
    world = world_width(z_plate)
    plate_w = (union[2] - union[0]) * world
    plate_h = (union[3] - union[1]) * world
    if plate_w <= 1 or plate_h <= 1:
        return None
    nx = (union[0] + union[2]) / 2.0
    ny = (union[1] + union[3]) / 2.0
    capture = camera_dict(inverse_mercator_y(ny), nx * 360.0 - 180.0, z_plate, 0.0, 0.0)
    return {
        "union": union,
        "zPlate": z_plate,
        "plateW": plate_w,
        "plateH": plate_h,
        "width": float(max(canvas) if canvas else width),
        "height": float(height),
        "captureCamera": capture,
    }


def plate_placement(
    camera: dict[str, Any],
    plate: dict[str, Any],
    *,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, int]:
    """Place the shared plate so this camera is full-bleed on its capture canvas."""
    width = float(width if width is not None else plate.get("width") or WALL_WIDTH)
    height = float(height if height is not None else plate.get("height") or WALL_HEIGHT)
    union = plate["union"]
    z_plate = float(plate["zPlate"])
    world = world_width(z_plate)
    cam = normalized_viewport(camera, width, height)
    cam_w_plate = (cam[2] - cam[0]) * world
    scale = width / cam_w_plate if cam_w_plate else 1.0
    disp_w = float(plate["plateW"]) * scale
    disp_h = float(plate["plateH"]) * scale
    img_x = -((cam[0] - union[0]) * world) * scale
    img_y = -((cam[1] - union[1]) * world) * scale
    return {"x": whole(img_x), "y": whole(img_y), "w": whole(disp_w), "h": whole(disp_h)}


def project_into_plate(
    lat: float,
    lon: float,
    plate: dict[str, Any],
    placement: dict[str, int],
) -> tuple[float, float]:
    union = plate["union"]
    world = world_width(float(plate["zPlate"]))
    nx = (clamp_lon(lon) + 180.0) / 360.0
    ny = mercator_y(lat)
    scale_x = placement["w"] / float(plate["plateW"]) if plate["plateW"] else 1.0
    scale_y = placement["h"] / float(plate["plateH"]) if plate["plateH"] else 1.0
    px = placement["x"] + (nx - union[0]) * world * scale_x
    py = placement["y"] + (ny - union[1]) * world * scale_y
    return px, py


def project_into_camera(
    lat: float,
    lon: float,
    camera: dict[str, Any],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
) -> tuple[float, float]:
    zoom = float(camera.get("zoom") or 0)
    world = world_width(zoom)
    px = (clamp_lon(lon) + 180.0) / 360.0 * world
    py = mercator_y(lat) * world
    cx = (clamp_lon(float(camera.get("lon") or 0)) + 180.0) / 360.0 * world
    cy = mercator_y(float(camera.get("lat") or 0)) * world
    return width / 2.0 + (px - cx), height / 2.0 + (py - cy)


def avoid_straddle(
    x: float,
    w: float,
    *,
    edges: tuple[float, ...] = PANEL_EDGES,
    gap: float = 1.0,
) -> int:
    """Keep the box off x=1920 and x=5760 on the wall deck (no panel straddle)."""
    x = float(x)
    w = max(1.0, float(w))
    for edge in edges:
        right = x + w
        on_edge = abs(x - edge) < 0.5 or abs(right - edge) < 0.5
        straddles = x < edge < right
        if not on_edge and not straddles:
            continue
        if x + w / 2.0 <= edge:
            x = edge - w - gap
        else:
            x = edge + gap
    return whole(x)


def _link_ends(link: dict[str, Any]) -> tuple[str, str]:
    return str(link.get("from") or link.get("from_") or ""), str(link.get("to") or "")


def morph_runs(slides: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[list[str]]:
    """Consecutive morph hops share one plate (pairwise union would dissolve on a chain)."""
    by_pair = {_link_ends(link): link for link in links}
    ids = [str(slide.get("id") or "") for slide in slides]
    runs: list[list[str]] = []
    current: list[str] = []
    for index in range(len(ids) - 1):
        start, end = ids[index], ids[index + 1]
        link = by_pair.get((start, end))
        if link and str(link.get("kind") or "") == "morph":
            if not current:
                current = [start, end]
            else:
                current.append(end)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def coerce_link_kinds(slides: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Disabled-but-checked morph must not stay morph when hop rules say otherwise."""
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    next_links: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        start, end = _link_ends(item)
        from_slide, to_slide = by_id.get(start), by_id.get(end)
        if from_slide is not None and to_slide is not None:
            suggested = infer_hop_kind(from_slide, to_slide)
            kind = str(item.get("kind") or "")
            if kind == "morph" and suggested != "morph":
                item["kind"] = suggested
                item.pop("plateId", None)
            elif kind == "movie" and suggested == "cut":
                item["kind"] = "cut"
                item.pop("plateId", None)
        if str(item.get("kind") or "") != "movie":
            item.pop("easing", None)
            item.pop("route", None)
            item.pop("easeIn", None)
            item.pop("easeOut", None)
            item.pop("flyZoom", None)
        next_links.append(item)
    return next_links


def assign_morph_plates(
    slides: list[dict[str, Any]],
    links: list[dict[str, Any]],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return {plateId: geom} and links with plateId, or coerce oversized morph to movie."""
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    plates: dict[str, dict[str, Any]] = {}
    pair_plate: dict[tuple[str, str], str] = {}
    movie_pairs: set[tuple[str, str]] = set()
    for run in morph_runs(slides, links):
        cameras = [(by_id[sid].get("camera") or {}) for sid in run if sid in by_id]
        widths = [float(slide_capture_size(by_id[sid])[0]) for sid in run if sid in by_id]
        geom = morph_plate_geom(cameras, width=width, height=height, widths=widths)
        hops = [(run[index], run[index + 1]) for index in range(len(run) - 1)]
        too_big = geom is None or max(float(geom["plateW"]), float(geom["plateH"])) > MAX_TEXTURE_SIZE
        if too_big:
            movie_pairs.update(hops)
            continue
        plate_id = plate_id_for(run)
        plates[plate_id] = {**geom, "slideIds": run, "plateId": plate_id}
        for hop in hops:
            pair_plate[hop] = plate_id
    next_links: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        ends = _link_ends(item)
        plate_id = pair_plate.get(ends)
        if plate_id:
            item["plateId"] = plate_id
        elif ends in movie_pairs and str(item.get("kind") or "") == "morph":
            item["kind"] = "movie"
            item.pop("plateId", None)
        else:
            item.pop("plateId", None)
        next_links.append(item)
    return plates, next_links


def maps_export_plan(
    slides: list[dict[str, Any]],
    links: list[dict[str, Any]],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
) -> dict[str, Any]:
    """Coerced links plus still/plate capture jobs for Keynote export."""
    links = coerce_link_kinds(slides, links)
    plates, links = assign_morph_plates(slides, links, width=width, height=height)
    covered: set[str] = set()
    for geom in plates.values():
        covered.update(str(sid) for sid in (geom.get("slideIds") or []))
    stills: list[dict[str, Any]] = []
    for slide in slides:
        sid = str(slide.get("id") or "")
        if not sid or sid in covered:
            continue
        cap_w, cap_h = slide_capture_size(slide)
        stills.append(
            {
                "slideId": sid,
                "style": slide.get("style") or "positron",
                "camera": slide.get("camera") or {},
                "highlights": list(slide.get("highlights") or []),
                "width": cap_w,
                "height": cap_h,
            }
        )
    plate_list: list[dict[str, Any]] = []
    for plate_id, geom in plates.items():
        first = next((slide for slide in slides if str(slide.get("id") or "") in (geom.get("slideIds") or [])), None)
        plate_list.append(
            {
                "plateId": plate_id,
                "plateW": int(math.ceil(float(geom["plateW"]))),
                "plateH": int(math.ceil(float(geom["plateH"]))),
                "camera": geom["captureCamera"],
                "style": (first or {}).get("style") or "positron",
                "highlights": list((first or {}).get("highlights") or []),
            }
        )
    return {"links": links, "stills": stills, "plates": plate_list, "plateGeoms": plates}


def find_pin_drop_wave(root: Path | None = None) -> Path | None:
    root = Path(root) if root else find_repo_root()
    if not root.is_dir():
        return None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_WALK and not name.startswith(".")]
        for name in filenames:
            if PIN_WAVE_RE.search(name):
                return Path(dirpath) / name
    return None


def ensure_png(path: Path, w: int = 8, h: int = 8) -> Path:
    path = Path(path)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (max(1, int(w)), max(1, int(h))), (32, 48, 64)).save(path, "PNG")
    return path


def _remove_key(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _outgoing(slide_id: str, links: list[dict[str, Any]]) -> dict[str, Any] | None:
    for link in links:
        start, _end = _link_ends(link)
        if start == slide_id:
            return link
    return None


def _still_path(slide: dict[str, Any], output_dir: Path, preview_dir: Path | None = None) -> Path:
    del preview_dir
    sid = str(slide.get("id") or "slide")
    name = Path(f"{sid}.png").name
    path = Path(output_dir) / "stills" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing export still {path}")
    return path


def _plate_path(plate_id: str, output_dir: Path) -> Path:
    name = plate_filename(plate_id)
    path = Path(output_dir) / "plates" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing export plate {path}")
    return path


def _item(
    kind: str,
    x: float,
    y: float,
    w: float,
    h: float,
    **extra: Any,
) -> dict[str, Any]:
    row = {"kind": kind, "x": whole(x), "y": whole(y), "w": whole(w), "h": whole(h)}
    row.update(extra)
    return row


def _pin_size(church: dict[str, Any], movie: Path | None) -> int:
    kind = str(church.get("kind") or "dot")
    if kind == "dropPin" and movie is not None:
        return DROP_SIZE
    if kind == "dropPin":
        return min(PIN_MAX_PT, DROP_SIZE)
    return min(PIN_MAX_PT, DOT_SIZE)


def _place_churches(
    churches: list[dict[str, Any]],
    *,
    plate: dict[str, Any] | None,
    placement: dict[str, int] | None,
    camera: dict[str, Any],
    wall: bool,
    movie: Path | None,
    origin_x: float = 0,
    capture_w: float = WALL_WIDTH,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for church in churches:
        lat = float(church.get("lat") or 0)
        lon = float(church.get("lon") or 0)
        if plate is not None and placement is not None:
            cx, cy = project_into_plate(lat, lon, plate, placement)
        else:
            cx, cy = project_into_camera(lat, lon, camera, width=capture_w)
        cx += origin_x
        size = _pin_size(church, movie)
        x = cx - size / 2.0
        y = cy - size / 2.0
        if wall:
            x = avoid_straddle(x, size)
        color = parse_color(str(church.get("color") or "#c44a42"))
        kind = str(church.get("kind") or "dot")
        if kind == "dropPin" and movie is not None:
            items.append(_item("movie", x, y, size, size, path=str(movie), color=color))
        else:
            items.append(_item("shape", x, y, size, size, color=color, shape="oval"))
        name = str(church.get("name") or "").strip()
        if name:
            nw = max(48, min(420, 11 * len(name)))
            nx = x + size + 8
            ny = y + (size - NAME_HEIGHT) / 2.0
            if wall:
                nx = avoid_straddle(nx, nw)
            items.append(_item("text", nx, ny, nw, NAME_HEIGHT, text=name))
        photo = church.get("photoPath")
        if photo and Path(str(photo)).is_file():
            px = x - PHOTO_SIZE - 8
            py = y
            if wall:
                px = avoid_straddle(px, PHOTO_SIZE)
            items.append(_item("image", px, py, PHOTO_SIZE, PHOTO_SIZE, path=str(Path(photo)), photo=True))
    return items


def _map_item(
    slide: dict[str, Any],
    *,
    plate: dict[str, Any] | None,
    plate_path: Path | None,
    still: Path | None,
    bg_movie: Path | None = None,
) -> tuple[dict[str, Any], dict[str, int] | None]:
    camera = slide.get("camera") or {}
    cap_w, cap_h = slide_capture_size(slide)
    ox = slide_map_origin_x(slide)
    if bg_movie is not None:
        return _item("movie", ox, 0, cap_w, cap_h, path=str(bg_movie), map=True), None
    if plate is not None and plate_path is not None:
        geom = plate_placement(camera, plate, width=cap_w, height=cap_h)
        return _item("image", geom["x"] + ox, geom["y"], geom["w"], geom["h"], path=str(plate_path), map=True), geom
    if still is None:
        raise FileNotFoundError("Missing export still for a non-morph slide")
    return _item("image", ox, 0, cap_w, cap_h, path=str(still), map=True), None


def _to_cg(items: list[dict[str, Any]], origin: tuple[float, float]) -> list[dict[str, Any]]:
    ox, oy = origin
    out: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        row["x"] = whole(item["x"] - ox)
        row["y"] = whole(item["y"] - oy)
        out.append(row)
    return out


def build_slide_items(
    slide: dict[str, Any],
    *,
    plate: dict[str, Any] | None,
    plate_path: Path | None,
    still: Path | None,
    movie: Path | None,
    wall: bool,
    bg_movie: Path | None = None,
) -> list[dict[str, Any]]:
    mapped, placement = _map_item(slide, plate=plate, plate_path=plate_path, still=still, bg_movie=bg_movie)
    items = [mapped]
    cap_w, _cap_h = slide_capture_size(slide)
    origin_x = slide_map_origin_x(slide)
    if bg_movie is None:
        items.extend(
            _place_churches(
                list(slide.get("churches") or []),
                plate=plate,
                placement=placement,
                camera=slide.get("camera") or {},
                wall=wall,
                movie=movie,
                origin_x=origin_x,
                capture_w=cap_w,
            )
        )
    if not wall:
        origin = cg_crop_origin(slide)
        items = _to_cg(items, origin)
    return items


def _transition_for(
    link: dict[str, Any] | None,
    slide: dict[str, Any] | None = None,
    *,
    bg_movie: bool = False,
) -> dict[str, Any] | None:
    if not link:
        return None
    kind = str(link.get("kind") or "cut")
    duration = float(link.get("duration") or 1.0)
    automatic = bool(link.get("playWithoutClick"))
    if kind == "morph" and link.get("plateId"):
        return {"effect": "magic_move", "duration": duration, "automatic": automatic}
    if bg_movie:
        delay = float((slide or {}).get("movieDuration") or duration)
        return {"effect": None, "duration": duration, "automatic": True, "delay": delay}
    if kind == "dissolve":
        return {"effect": "dissolve", "duration": duration, "automatic": automatic}
    if automatic:
        return {"effect": None, "duration": duration, "automatic": True}
    return None


def plan_deck(
    slides: list[dict[str, Any]],
    links: list[dict[str, Any]],
    plates: dict[str, dict[str, Any]],
    *,
    output_dir: Path,
    preview_dir: Path,
    movie: Path | None,
    wall: bool,
) -> list[dict[str, Any]]:
    slide_plate: dict[str, str] = {}
    for plate_id, geom in plates.items():
        for sid in geom.get("slideIds") or []:
            slide_plate[str(sid)] = plate_id
    ops: list[dict[str, Any]] = []
    for index, slide in enumerate(slides):
        sid = str(slide.get("id") or "")
        plate_id = slide_plate.get(sid)
        plate = plates.get(plate_id) if plate_id else None
        plate_path = _plate_path(plate_id, output_dir) if plate_id else None
        outgoing = _outgoing(sid, links)
        bg_movie = None
        if outgoing and str(outgoing.get("kind") or "") == "movie":
            candidate = movie_path(output_dir, sid)
            if candidate.exists():
                bg_movie = candidate
                plate_id = None
                plate = None
                plate_path = None
        still = None if plate_id or bg_movie else _still_path(slide, output_dir, preview_dir)
        items = build_slide_items(
            slide,
            plate=plate,
            plate_path=plate_path,
            still=still,
            movie=movie,
            wall=wall,
            bg_movie=bg_movie,
        )
        prev_link = _outgoing(str(slides[index - 1].get("id") or ""), links) if index else None
        duplicate = bool(
            index
            and bg_movie is None
            and prev_link
            and str(prev_link.get("kind") or "") == "morph"
            and prev_link.get("plateId")
            and prev_link.get("plateId") == plate_id
        )
        ops.append(
            {
                "id": sid,
                "duplicate": duplicate,
                "items": items,
                "transition": _transition_for(outgoing, slide, bg_movie=bg_movie is not None),
            }
        )
    return ops


def _emit_clear() -> list[str]:
    return [
        "        try",
        "          delete every text item",
        "        end try",
        "        try",
        "          delete every shape",
        "        end try",
        "        try",
        "          delete every image",
        "        end try",
        "        try",
        "          delete every movie",
        "        end try",
    ]


def _emit_adjust_map(item: dict[str, Any]) -> list[str]:
    return [
        "        try",
        f"          set position of image 1 to {{{item['x']}, {item['y']}}}",
        f"          set width of image 1 to {item['w']}",
        f"          set height of image 1 to {item['h']}",
        "        end try",
        "        try",
        "          repeat with i from (count of images) to 2 by -1",
        "            delete image i",
        "          end repeat",
        "        end try",
        "        try",
        "          delete every shape",
        "        end try",
        "        try",
        "          delete every movie",
        "        end try",
        "        try",
        "          delete every text item",
        "        end try",
    ]


def _emit_item(item: dict[str, Any]) -> list[str]:
    kind = item["kind"]
    x, y, w, h = item["x"], item["y"], item["w"], item["h"]
    if kind == "image":
        path = _as_escape(item["path"])
        return [
            f'        set imgFile to (POSIX file "{path}") as alias',
            "        set img to make new image with properties {file name:imgFile}",
            f"        set position of img to {{{x}, {y}}}",
            f"        set width of img to {w}",
            f"        set height of img to {h}",
        ]
    if kind == "movie":
        path = _as_escape(item["path"])
        if item.get("map"):
            return [
                f'        set movFile to (POSIX file "{path}") as alias',
                "        set mv to make new movie with properties {file name:movFile}",
                f"        set position of mv to {{{x}, {y}}}",
                f"        set width of mv to {w}",
                f"        set height of mv to {h}",
            ]
        return [
            "        try",
            f'          set movFile to (POSIX file "{path}") as alias',
            "          set mv to make new movie with properties {file name:movFile}",
            f"          set position of mv to {{{x}, {y}}}",
            f"          set width of mv to {w}",
            f"          set height of mv to {h}",
            "        on error",
            "          set shp to make new shape with properties {shape type:oval, "
            f"position:{{{x}, {y}}}, width:{w}, height:{h}}}",
            "        end try",
        ]
    if kind == "shape":
        color = item.get("color") or (0xC4 * 257, 0x4A * 257, 0x42 * 257)
        shape = item.get("shape") or "oval"
        return [
            "        set shp to make new shape with properties "
            f"{{shape type:{shape}, position:{{{x}, {y}}}, width:{w}, height:{h}}}",
            "        try",
            "          set fill type of shp to color fill",
            "        end try",
            "        try",
            f"          set fill color of shp to {{{color[0]}, {color[1]}, {color[2]}}}",
            "        end try",
        ]
    text = _as_escape(str(item.get("text") or ""))
    return [
        "        set txt to make new text item with properties "
        f'{{object text:"{text}", position:{{{x}, {y}}}, width:{w}, height:{h}}}',
        "        try",
        "          set size of object text of txt to 24",
        "        end try",
        "        try",
        "          set color of object text of txt to {65535, 65535, 65535}",
        "        end try",
    ]


def _emit_transition(slide_no: int, trans: dict[str, Any] | None) -> list[str]:
    """Always write a transition. Duplicate inherits Magic Move; None must clear it."""
    trans = trans or {}
    props: list[str] = []
    effect = trans.get("effect")
    if effect == "magic_move":
        props.append("transition effect:magic move")
    elif effect == "dissolve":
        props.append("transition effect:dissolve")
    else:
        props.append("transition effect:none")
    if trans.get("duration") is not None:
        props.append(f"transition duration:{float(trans['duration'])}")
    if trans.get("automatic"):
        props.append("automatic transition:true")
    else:
        props.append("automatic transition:false")
    if trans.get("delay") is not None:
        props.append(f"transition delay:{float(trans['delay'])}")
    joined = ", ".join(props)
    return [
        "      try",
        f"        set transition properties of slide {slide_no} to {{{joined}}}",
        "      end try",
    ]


def _emit_slide_body(op: dict[str, Any], slide_no: int) -> list[str]:
    items = list(op.get("items") or [])
    lines = [f"      tell slide {slide_no}"]
    if op.get("duplicate"):
        mapped = next((item for item in items if item.get("map")), items[0] if items else None)
        if mapped:
            lines += _emit_adjust_map(mapped)
        overlays = [item for item in items if not item.get("map")]
        for item in overlays:
            lines += _emit_item(item)
    else:
        lines += _emit_clear()
        for item in items:
            lines += _emit_item(item)
    lines.append("      end tell")
    lines += _emit_transition(slide_no, op.get("transition"))
    return lines


def build_deck_script(ops: list[dict[str, Any]], dest: Path, *, width: int, height: int) -> str:
    dest = Path(dest)
    bid = keynote_app.bundle_id()
    dest_s = _as_escape(str(dest.resolve()))
    name = _as_escape(dest.name)
    stem = _as_escape(dest.stem)
    body: list[str] = []
    slide_no = 0
    for index, op in enumerate(ops):
        if index == 0:
            slide_no = 1
        elif op.get("duplicate"):
            body += [
                f"      duplicate slide {slide_no} to after slide {slide_no}",
            ]
            slide_no += 1
        else:
            body += [
                f"      make new slide at after slide {slide_no}",
            ]
            slide_no += 1
        body += _emit_slide_body(op, slide_no)
    return "\n".join(
        [
            f'using terms from application id "{bid}"',
            f'tell application id "{bid}"',
            "  activate",
            f"  with timeout of {TIMEOUT_SECONDS} seconds",
            "    try",
            f'      close (every document whose name is "{name}" or name is "{stem}") saving no',
            "      delay 0.3",
            "    end try",
            "    set theDoc to make new document",
            f"    set width of theDoc to {int(width)}",
            f"    set height of theDoc to {int(height)}",
            f'    save theDoc in POSIX file "{dest_s}"',
            "    try",
            "      close theDoc saving yes",
            "    end try",
            "    delay 0.3",
            "    try",
            f'      close (every document whose name is "{name}" or name is "{stem}") saving no',
            "      delay 0.3",
            "    end try",
            f'    set theFile to POSIX file "{dest_s}"',
            "    open theFile",
            "    delay 0.4",
            "    activate",
            "    set theDoc to document 1",
            f'    if name of theDoc does not start with "{stem}" then error '
            '"maps export bound the wrong document: " & (name of theDoc)',
            "    tell theDoc",
            *body,
            "    end tell",
            "    save theDoc",
            "    try",
            "      close theDoc saving yes",
            "    end try",
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def build_shared_plate_probe_script(
    dest: Path,
    image_path: Path,
    *,
    width: int = 800,
    height: int = 200,
) -> str:
    """New doc, place image, duplicate, move/scale the copy, Magic Move on slide 1."""
    dest = Path(dest)
    image_path = Path(image_path)
    bid = keynote_app.bundle_id()
    dest_s = _as_escape(str(dest.resolve()))
    img_s = _as_escape(str(image_path.resolve()))
    name = _as_escape(dest.name)
    stem = _as_escape(dest.stem)
    shifted_x = whole(-width / 4)
    shifted_y = whole(-height / 4)
    scaled_w = whole(width * 1.5)
    scaled_h = whole(height * 1.5)
    return "\n".join(
        [
            f'using terms from application id "{bid}"',
            f'tell application id "{bid}"',
            "  activate",
            f"  with timeout of {TIMEOUT_SECONDS} seconds",
            "    try",
            f'      close (every document whose name is "{name}" or name is "{stem}") saving no',
            "      delay 0.3",
            "    end try",
            "    set theDoc to make new document",
            f"    set width of theDoc to {int(width)}",
            f"    set height of theDoc to {int(height)}",
            f'    save theDoc in POSIX file "{dest_s}"',
            "    try",
            "      close theDoc saving yes",
            "    end try",
            "    delay 0.3",
            "    try",
            f'      close (every document whose name is "{name}" or name is "{stem}") saving no',
            "      delay 0.3",
            "    end try",
            f'    set theFile to POSIX file "{dest_s}"',
            "    open theFile",
            "    delay 0.4",
            "    activate",
            "    set theDoc to document 1",
            f'    if name of theDoc does not start with "{stem}" then error '
            '"maps probe bound the wrong document: " & (name of theDoc)',
            "    tell slide 1 of theDoc",
            "      try",
            "        delete every text item",
            "      end try",
            f'      set imgFile to (POSIX file "{img_s}") as alias',
            "      set img to make new image with properties {file name:imgFile}",
            "      set position of img to {0, 0}",
            f"      set width of img to {int(width)}",
            f"      set height of img to {int(height)}",
            "    end tell",
            "    duplicate slide 1 of theDoc to after slide 1 of theDoc",
            "    tell slide 2 of theDoc",
            f"      set position of image 1 to {{{shifted_x}, {shifted_y}}}",
            f"      set width of image 1 to {scaled_w}",
            f"      set height of image 1 to {scaled_h}",
            "    end tell",
            "    try",
            "      set transition properties of slide 1 of theDoc to "
            "{transition effect:magic move, transition duration:1.2, automatic transition:true}",
            "    end try",
            f'    save theDoc in POSIX file "{dest_s}"',
            "    try",
            "      close theDoc saving yes",
            "    end try",
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def run_osascript(script: str, *, script_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Execute AppleScript from a file (not stdin). Mock this in tests."""
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    owned = script_path is None
    if script_path is None:
        handle = tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False)
        handle.write(script)
        script_path = Path(handle.name)
        handle.close()
    else:
        script_path = Path(script_path)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script, encoding="utf-8")
    try:
        return subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        if owned:
            script_path.unlink(missing_ok=True)


def inspect_and_validate(path: Path) -> list[Any]:
    from obed_edom.inspect import inspect_keynote
    from obed_edom.validate import validate_inspect

    payload = inspect_keynote(path, use_cache=False)
    return validate_inspect(payload, location_prefix=path.name, use_ocr=False, check_passages=False)


def _inspect_dest(path: Path, job: Any) -> list[Any]:
    if not path.exists():
        return []
    try:
        return inspect_and_validate(path)
    except Exception as exc:
        _log(job, f"validate {path.name} failed: {exc}")
        return []


def _log(job: Any, message: str) -> None:
    log = getattr(job, "log", None)
    if callable(log):
        log(message)


def _run_one_deck(
    ops: list[dict[str, Any]],
    dest: Path,
    *,
    width: int,
    height: int,
) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _remove_key(dest)
    script = build_deck_script(ops, dest, width=width, height=height)
    proc = run_osascript(script)
    if proc.returncode != 0:
        debug = dest.with_suffix(".applescript")
        debug.write_text(script, encoding="utf-8")
        raise RuntimeError(
            "Maps Keynote AppleScript failed:\n"
            + (proc.stderr or "")
            + "\n"
            + (proc.stdout or "")
            + f"\nScript saved to {debug}"
        )
    return script


def export_maps_job(job: Any, *, export_lw: bool = True, export_cg: bool = True) -> dict[str, Any]:
    if not export_lw and not export_cg:
        raise ValueError("At least one of exportLw or exportCg must be on")
    result = dict(getattr(job, "result", None) or {})
    output_dir = Path(str(result.get("outputDir") or find_repo_root() / "output" / ".maps" / str(getattr(job, "id", "maps"))))
    preview_dir = Path(str(result.get("previewDir") or (output_dir / "previews")))
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    slides = [dict(slide) for slide in (result.get("slides") or [])]
    links = [dict(link) for link in (result.get("links") or [])]
    if not slides:
        raise ValueError("Maps document has no slides")
    try:
        from obed_edom.maps_movie import encode_pending

        slides = encode_pending(output_dir, slides, log=lambda m: _log(job, m))
    except (ImportError, AttributeError):
        pass
    else:
        result["slides"] = slides
    plan = maps_export_plan(slides, links)
    plates = plan["plateGeoms"]
    links = plan["links"]
    result["links"] = links
    movie = find_pin_drop_wave()
    stem = str(result.get("stem") or f"maps-{getattr(job, 'id', 'maps')}")
    flags: list[Any] = []
    flags_cg: list[Any] = []
    if export_lw:
        dest = output_dir / f"{stem}.key"
        _log(job, f"Exporting wall deck {dest.name} (7680×1080)…")
        ops = plan_deck(
            slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=True
        )
        _run_one_deck(ops, dest, width=WALL_WIDTH, height=WALL_HEIGHT)
        result["destPath"] = str(dest)
        flags = _inspect_dest(dest, job)
    if export_cg:
        dest_cg = output_dir / f"{stem}_CG.key"
        _log(job, f"Exporting CG deck {dest_cg.name} (1920×1080)…")
        ops_cg = plan_deck(
            slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=False
        )
        _run_one_deck(ops_cg, dest_cg, width=CG_WIDTH, height=CG_HEIGHT)
        result["destPathCg"] = str(dest_cg)
        flags_cg = _inspect_dest(dest_cg, job)
    result["exportLw"] = bool(export_lw)
    result["exportCg"] = bool(export_cg)
    from obed_edom.validate import flag_dict

    if export_lw:
        result["flags"] = [flag_dict(flag) for flag in flags]
    if export_cg:
        result["flagsCg"] = [flag_dict(flag) for flag in flags_cg]
    return result
