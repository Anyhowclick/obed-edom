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
from typing import Any, Callable

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
    inherit_hidden_layers,
    inverse_mercator_y,
    mercator_y,
    slide_hidden_layers,
    world_width,
)
from obed_edom.maps_movie import movie_path
from obed_edom.maps_pins import LABEL_PILL_RGB, PIN_ASPECT, ensure_label_pill_png, ensure_pin_png
from obed_edom.paths import ensure_export_dir, find_repo_root

# P2: HEVC fly/route movies, is_backdrop Map BG, score_resize — deferred.

CG_WIDTH = 1920
CG_HEIGHT = 1080
DSK_WIDTH = 1920
DSK_HEIGHT = 1080
DSK_SCALE = 0.5
DSK_Y = 540
CG_ORIGIN_X = (WALL_WIDTH - CG_WIDTH) / 2.0  # 2880
MAX_TEXTURE_SIZE = 8192
TIMEOUT_SECONDS = 3600
PANEL_EDGES = (1920.0, 5760.0)
PIN_MAX_PT = 180
DOT_SIZE = 28
DROP_SIZE = 64
PHOTO_SIZE = 96
NAME_HEIGHT = 32
LABEL_BOLD_FONT = "Amplitude-Bold"
LABEL_BOLD_FALLBACK = "HelveticaNeue-Bold"
LABEL_CHAR_W = 13
PILL_PAD_X = 6
PILL_PAD_Y = 2
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
    if slide.get("_splitCg"):
        return int(CG_WIDTH), int(CG_HEIGHT)
    if slide_includes_side_panels(slide):
        return int(WALL_WIDTH), int(WALL_HEIGHT)
    return int(CENTRE_WIDTH), int(WALL_HEIGHT)


def slide_map_origin_x(slide: dict[str, Any]) -> int:
    if slide.get("_splitCg"):
        return 0
    return 0 if slide_includes_side_panels(slide) else int(CENTRE_ORIGIN_X)


def hop_capture_size(from_slide: dict[str, Any], to_slide: dict[str, Any] | None = None) -> tuple[int, int]:
    fw, fh = slide_capture_size(from_slide)
    if not to_slide:
        return fw, fh
    tw, th = slide_capture_size(to_slide)
    return max(fw, tw), max(fh, th)


def hop_map_origin_x(width: int) -> int:
    return 0 if int(width) >= int(WALL_WIDTH) else int(CENTRE_ORIGIN_X)


def normalized_viewport(
    camera: dict[str, Any],
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
    bearing: float = 0.0,
) -> tuple[float, float, float, float]:
    zoom = float(camera.get("zoom") or 0)
    world = world_width(zoom)
    cx = (clamp_lon(float(camera.get("lon") or 0)) + 180.0) / 360.0
    cy = mercator_y(float(camera.get("lat") or 0))
    cx, cy = rotated_mercator(cx, cy, bearing)
    nw = float(width) / world
    nh = float(height) / world
    return (cx - nw / 2.0, cy - nh / 2.0, cx + nw / 2.0, cy + nh / 2.0)


def rotated_mercator(x: float, y: float, bearing: float) -> tuple[float, float]:
    theta = math.radians(float(bearing) or 0.0)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return cos_t * x + sin_t * y, -sin_t * x + cos_t * y


def nearest_world_x(x: float, reference: float) -> float:
    return x + round(reference - x)


def unrotated_mercator(x: float, y: float, bearing: float) -> tuple[float, float]:
    theta = math.radians(float(bearing) or 0.0)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return cos_t * x - sin_t * y, sin_t * x + cos_t * y


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
    bearing = float(cameras[0].get("bearing") or 0)
    boxes = [normalized_viewport(cam, w, height, bearing) for cam, w in zip(cameras, canvas)]
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
    nx, ny = unrotated_mercator(nx, ny, bearing)
    capture = camera_dict(inverse_mercator_y(ny), nx * 360.0 - 180.0, z_plate, bearing, 0.0)
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
    bearing = float((plate.get("captureCamera") or {}).get("bearing") or 0)
    cam = normalized_viewport(camera, width, height, bearing)
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
    capture_lon = float((plate.get("captureCamera") or {}).get("lon") or 0)
    reference_x = (clamp_lon(capture_lon) + 180.0) / 360.0
    nx = nearest_world_x(nx, reference_x)
    ny = mercator_y(lat)
    bearing = float((plate.get("captureCamera") or {}).get("bearing") or 0)
    nx, ny = rotated_mercator(nx, ny, bearing)
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
    nx = (clamp_lon(lon) + 180.0) / 360.0
    camera_x = (clamp_lon(float(camera.get("lon") or 0)) + 180.0) / 360.0
    px = nearest_world_x(nx, camera_x) * world
    py = mercator_y(lat) * world
    cx = camera_x * world
    cy = mercator_y(float(camera.get("lat") or 0)) * world
    bearing = float(camera.get("bearing") or 0)
    px, py = rotated_mercator(px, py, bearing)
    cx, cy = rotated_mercator(cx, cy, bearing)
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


def _cg_view(slide: dict[str, Any]) -> dict[str, Any]:
    """Merge a slide with its CG override, letting unset override fields (e.g. hiddenLayers) inherit."""
    cg = slide.get("cg")
    if not isinstance(cg, dict):
        return slide
    return {**slide, **{key: value for key, value in cg.items() if value is not None}}


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
    """Invalid Magic Move falls back; explicit Movie, Dissolve, and Cut are preserved."""
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    next_links: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        start, end = _link_ends(item)
        from_slide, to_slide = by_id.get(start), by_id.get(end)
        if from_slide is not None and to_slide is not None:
            suggested = infer_hop_kind(from_slide, to_slide)
            if isinstance(from_slide.get("cg"), dict) or isinstance(to_slide.get("cg"), dict):
                cg_suggested = infer_hop_kind(_cg_view(from_slide), _cg_view(to_slide))
                rank = {"morph": 0, "movie": 1, "cut": 2}
                if rank[cg_suggested] > rank[suggested]:
                    suggested = cg_suggested
            kind = str(item.get("kind") or "")
            if kind == "morph" and suggested != "morph":
                item["kind"] = suggested
                item.pop("plateId", None)
        if str(item.get("kind") or "") != "movie":
            item.pop("easing", None)
            item.pop("route", None)
            item.pop("easeIn", None)
            item.pop("easeOut", None)
            item.pop("flyZoom", None)
            item.pop("flight", None)
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
    audience: str = "lw",
) -> dict[str, Any]:
    """Coerced links plus still/plate capture jobs for Keynote export."""
    if audience == "cg":
        slides = [
            {**_cg_view(slide), "cgShiftX": 0, "cgShiftY": 0, "includeSidePanels": False, "_splitCg": True}
            if isinstance(slide.get("cg"), dict)
            else slide
            for slide in slides
        ]
        width = CG_WIDTH
        height = CG_HEIGHT
    links = coerce_link_kinds(slides, links)
    plates, links = assign_morph_plates(slides, links, width=width, height=height)
    covered: set[str] = set()
    for geom in plates.values():
        covered.update(str(sid) for sid in (geom.get("slideIds") or []))
    landing_targets = {str(to_slide.get("id") or "") for _link, _from_slide, to_slide in _qualifying_movie_landing_links(slides, links)}
    stills: list[dict[str, Any]] = []
    for slide in slides:
        sid = str(slide.get("id") or "")
        if not sid or sid in covered:
            continue
        cap_w, cap_h = slide_capture_size(slide)
        highlights = list(slide.get("highlights") or [])
        row = {
            "slideId": sid,
            "style": slide.get("style") or "positron",
            "camera": slide.get("camera") or {},
            "highlights": highlights,
            "hiddenLayers": slide_hidden_layers(slide),
            "hillshade": bool(slide.get("hillshade")),
            "isolate": slide.get("isolate"),
            "width": cap_w,
            "height": cap_h,
            "revealMovie": bool(slide.get("revealMovie")),
        }
        if slide.get("isolate") and highlights:
            row["stillPngCountry"] = f"{sid}{'_CG' if audience == 'cg' else ''}-country.png"
        stills.append(row)
        if sid in landing_targets:
            stills.append(
                {
                    "slideId": f"{sid}__landing",
                    "style": slide.get("style") or "positron",
                    "camera": slide.get("camera") or {},
                    "highlights": [],
                    "hiddenLayers": slide_hidden_layers(slide),
                    "hillshade": bool(slide.get("hillshade")),
                    "isolate": None,
                    "width": cap_w,
                    "height": cap_h,
                    "synthetic": True,
                    "_landingFor": sid,
                }
            )
    plate_list: list[dict[str, Any]] = []
    for plate_id, geom in plates.items():
        first = next((slide for slide in slides if str(slide.get("id") or "") in (geom.get("slideIds") or [])), None)
        output_id = f"{plate_id}-cg" if audience == "cg" else plate_id
        if audience == "cg":
            for link in links:
                if link.get("plateId") == plate_id:
                    link["plateId"] = output_id
        plate_list.append(
            {
                "plateId": output_id,
                "plateW": int(math.ceil(float(geom["plateW"]))),
                "plateH": int(math.ceil(float(geom["plateH"]))),
                "slideIds": [str(sid) for sid in (geom.get("slideIds") or [])],
                "camera": geom["captureCamera"],
                "style": (first or {}).get("style") or "positron",
                "highlights": list((first or {}).get("highlights") or []),
                "hiddenLayers": slide_hidden_layers(first or {}),
                "hillshade": bool((first or {}).get("hillshade")),
                "isolate": (first or {}).get("isolate"),
            }
        )
    if audience == "cg":
        plates = {f"{plate_id}-cg": geom for plate_id, geom in plates.items()}
    return {"links": links, "stills": stills, "plates": plate_list, "plateGeoms": plates, "audience": audience}


def cg_affected_slide_ids(slides: list[dict[str, Any]], links: list[dict[str, Any]]) -> set[str]:
    affected = {str(slide.get("id") or "") for slide in slides if isinstance(slide.get("cg"), dict)}
    morph_edges: dict[str, set[str]] = {}
    for link in links:
        if str(link.get("kind") or "") != "morph":
            continue
        start, end = _link_ends(link)
        morph_edges.setdefault(start, set()).add(end)
        morph_edges.setdefault(end, set()).add(start)
    pending = list(affected)
    while pending:
        slide_id = pending.pop()
        for neighbor in morph_edges.get(slide_id, set()):
            if neighbor not in affected:
                affected.add(neighbor)
                pending.append(neighbor)
    for link in links:
        if str(link.get("kind") or "") != "movie":
            continue
        start, end = _link_ends(link)
        if start in affected or end in affected:
            affected.update((start, end))
    return affected


def split_cg_export_plan(slides: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    affected = cg_affected_slide_ids(slides, links)
    plan = maps_export_plan(slides, links, audience="cg")
    plan["stills"] = [
        row for row in plan["stills"] if str(row.get("_landingFor") or row.get("slideId") or "") in affected
    ]
    plan["plates"] = [
        row for row in plan["plates"]
        if any(str(sid) in affected for sid in (plan["plateGeoms"].get(str(row["plateId"])) or {}).get("slideIds") or [])
    ]
    keep = {str(row["plateId"]) for row in plan["plates"]}
    plan["plateGeoms"] = {plate_id: geom for plate_id, geom in plan["plateGeoms"].items() if plate_id in keep}
    plan["affectedSlideIds"] = sorted(affected)
    return plan


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


def _qualifying_movie_landing_links(
    slides: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Movie links whose isolated+highlighted destination immediately follows its source."""
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    index_of = {str(slide.get("id") or ""): index for index, slide in enumerate(slides)}
    out: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for link in links:
        if str(link.get("kind") or "") != "movie":
            continue
        start, end = _link_ends(link)
        from_slide, to_slide = by_id.get(start), by_id.get(end)
        if not from_slide or not to_slide:
            continue
        if not to_slide.get("isolate") or not to_slide.get("highlights"):
            continue
        if index_of.get(end) != index_of.get(start, -2) + 1:
            continue
        out.append((link, from_slide, to_slide))
    return out


def isolate_landing_slides(
    slides: list[dict[str, Any]], links: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Insert a synthetic plain-view landing slide before each isolated movie destination."""
    landing_after: dict[str, tuple[dict[str, Any], dict[str, Any], str]] = {}
    for link, from_slide, to_slide in _qualifying_movie_landing_links(slides, links):
        to_id = str(to_slide.get("id") or "")
        landing_slide = {**to_slide, "id": f"{to_id}__landing", "highlights": [], "isolate": None, "_landingFor": to_id}
        landing_after[str(from_slide.get("id") or "")] = (landing_slide, link, to_id)
    if not landing_after:
        return slides, links
    next_slides: list[dict[str, Any]] = []
    next_links = list(links)
    for slide in slides:
        next_slides.append(slide)
        landing = landing_after.get(str(slide.get("id") or ""))
        if landing is None:
            continue
        landing_slide, link, to_id = landing
        next_slides.append(landing_slide)
        for index, existing in enumerate(next_links):
            if existing is link:
                next_links[index] = {**link, "to": landing_slide["id"]}
                break
        duration = float(link.get("duration") or 0) or 1.0
        next_links.append(
            {
                "from": landing_slide["id"],
                "to": to_id,
                "kind": "dissolve",
                "duration": duration,
                "playWithoutClick": bool(link.get("playWithoutClick")),
            }
        )
    return next_slides, next_links


def _outgoing(slide_id: str, links: list[dict[str, Any]]) -> dict[str, Any] | None:
    for link in links:
        start, _end = _link_ends(link)
        if start == slide_id:
            return link
    return None


def _still_path(slide: dict[str, Any], output_dir: Path, preview_dir: Path | None = None, audience: str = "lw") -> Path:
    del preview_dir
    sid = str(slide.get("id") or "slide")
    name = Path(f"{sid}{'_CG' if audience == 'cg' else ''}.png").name
    path = Path(output_dir) / "stills" / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing export still {path}")
    return path


def _country_still_path(slide: dict[str, Any], output_dir: Path, audience: str = "lw") -> Path | None:
    sid = str(slide.get("id") or "slide")
    name = Path(f"{sid}{'_CG' if audience == 'cg' else ''}-country.png").name
    path = Path(output_dir) / "stills" / name
    return path if path.is_file() else None


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


def dsk_item(item: dict[str, Any]) -> dict[str, Any]:
    row = dict(item)
    for key in ("w", "h"):
        row[key] = whole(float(row[key]) * DSK_SCALE)
    row["x"] = whole((float(row["x"]) - CENTRE_ORIGIN_X) * DSK_SCALE)
    row["y"] = whole(float(row["y"]) * DSK_SCALE + DSK_Y)
    if row.get("kind") == "text":
        row["fontSize"] = float(row.get("fontSize") or 24) * DSK_SCALE
    return row


def dsk_ops(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**op, "items": [dsk_item(item) for item in op["items"]]} for op in ops]


def _pin_size(church: dict[str, Any], movie: Path | None) -> int:
    kind = str(church.get("kind") or "dot")
    if kind == "dropPin" and movie is not None:
        return DROP_SIZE
    if kind == "dropPin":
        return min(PIN_MAX_PT, DROP_SIZE)
    return min(PIN_MAX_PT, DOT_SIZE)


EFFECTIVE_SIZE_MAX = 20000


def _effective_size(church: dict[str, Any], zoom: float, movie: Path | None) -> float:
    size = float(church.get("size") or _pin_size(church, movie))
    size_zoom = church.get("sizeZoom")
    if church.get("scaleWithMap") and size_zoom is not None:
        size = size * 2 ** (zoom - float(size_zoom))
    return min(EFFECTIVE_SIZE_MAX, size)


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
    pin_root: Path,
    asset_root: Path | None = None,
    allow_reveal: bool = True,
    reveals: dict[tuple[str, str, str], str] | None = None,
    reveal_audience: str = "lw",
    sid: str = "",
    skip_landmarks: bool = False,
) -> list[dict[str, Any]]:
    """`pin_root` is required on purpose: dot and drop-pin rasters are written
    there, so a caller that forgets it must fail rather than emit a markerless
    deck. Production callers pass `output_dir / "pins"`."""
    items: list[dict[str, Any]] = []
    for church in churches:
        if skip_landmarks and str(church.get("kind") or "") == "landmark":
            continue
        lat = float(church.get("lat") or 0)
        lon = float(church.get("lon") or 0)
        if plate is not None and placement is not None:
            base_x, base_y = project_into_plate(lat, lon, plate, placement)
            copy_world = world_width(float(plate["zPlate"]))
            scale_x = placement["w"] / float(plate["plateW"]) if plate["plateW"] else 1.0
            scale_y = placement["h"] / float(plate["plateH"]) if plate["plateH"] else 1.0
            bearing = float((plate.get("captureCamera") or {}).get("bearing") or 0)
            theta = math.radians(bearing)
            copy_dx = math.cos(theta) * copy_world * scale_x
            copy_dy = -math.sin(theta) * copy_world * scale_y
        else:
            base_x, base_y = project_into_camera(lat, lon, camera, width=capture_w)
            copy_world = world_width(float(camera.get("zoom") or 0))
            theta = math.radians(float(camera.get("bearing") or 0))
            copy_dx = math.cos(theta) * copy_world
            copy_dy = -math.sin(theta) * copy_world
        zoom = float((camera or {}).get("zoom") or 0)
        size = _effective_size(church, zoom, movie)
        if size < 1:
            continue
        size = int(size)
        color = parse_color(str(church.get("color") or "#c44a42"))
        kind = str(church.get("kind") or "dot")
        asset_id = str(church.get("assetId") or "")
        landmark = asset_root / f"{asset_id}.png" if asset_root and asset_id else None
        if kind == "landmark" and (movie is not None or landmark is None or not landmark.is_file()):
            continue
        static_drop = kind == "dropPin" and movie is None
        name = str(church.get("name") or "").strip()
        photo = None
        copy_span = max(1.0, math.hypot(copy_dx, copy_dy))
        copy_count = math.ceil((capture_w + WALL_HEIGHT) / copy_span) + 2
        for copy_index in range(-copy_count, copy_count + 1):
            cx = base_x + copy_index * copy_dx
            cy = base_y + copy_index * copy_dy
            if not (-size <= cx <= capture_w + size and -size <= cy <= WALL_HEIGHT + size):
                continue
            x = cx + origin_x - size / 2.0
            drop_h = whole(size * PIN_ASPECT)
            if kind == "landmark":
                y = cy - size
            elif static_drop:
                y = whole(cy) - drop_h
            else:
                y = cy - size / 2.0
            if wall:
                x = avoid_straddle(x, size)
            if kind == "landmark":
                with Image.open(landmark) as image:
                    height = size * image.height / max(1, image.width)
                    opacity = float(church.get("opacity") if church.get("opacity") is not None else 1)
                    church_id = str(church.get("id") or "")
                    reveal_mov = reveals.get((reveal_audience, sid, church_id)) if allow_reveal and reveals else None
                    if opacity < 1:
                        faded = asset_root / f"{asset_id}-{int(opacity * 1000)}.png"
                        if not faded.exists():
                            rgba = image.convert("RGBA")
                            rgba.putalpha(rgba.getchannel("A").point(lambda value: round(value * opacity)))
                            rgba.save(faded, "PNG")
                        landmark = faded
                    if reveal_mov:
                        items.append(
                            _item(
                                "movie",
                                x,
                                cy - height,
                                size,
                                height,
                                path=str(reveal_mov),
                                fallback=str(landmark),
                                landmark=True,
                                revealKey=(reveal_audience, sid, church_id),
                            )
                        )
                    else:
                        item = _item("image", x, cy - height, size, height, path=str(landmark), landmark=True)
                        item["opacity"] = opacity
                        items.append(item)
            elif kind == "dropPin" and movie is not None:
                items.append(_item("movie", x, y, size, size, path=str(movie), color=color))
            else:
                pin_kind = "droppin" if static_drop else "dot"
                height = drop_h if static_drop else size
                items.append(
                    _item(
                        "image",
                        x,
                        y,
                        size,
                        height,
                        path=str(ensure_pin_png(pin_root, pin_kind, color)),
                        color=color,
                    )
                )
            if name and church.get("showLabel", True):
                nw = max(48, min(420, LABEL_CHAR_W * len(name)))
                nw += nw % 2
                nx = x + size + 8
                ny = y + (size - NAME_HEIGHT) / 2.0
                pw = nw + 2 * PILL_PAD_X
                ph = NAME_HEIGHT + 2 * PILL_PAD_Y
                if wall:
                    px = nx - PILL_PAD_X
                    nx += avoid_straddle(px, pw) - px
                items.append(
                    _item(
                        "image",
                        nx - PILL_PAD_X,
                        ny - PILL_PAD_Y,
                        pw,
                        ph,
                        path=str(ensure_label_pill_png(pin_root, LABEL_PILL_RGB, pw, ph)),
                        labelPill=True,
                    )
                )
                items.append(_item("text", nx, ny, nw, NAME_HEIGHT, text=name, bold=True))
    return items


def _map_item(
    slide: dict[str, Any],
    *,
    plate: dict[str, Any] | None,
    plate_path: Path | None,
    still: Path | None,
    bg_movie: Path | None = None,
    dest_slide: dict[str, Any] | None = None,
    asset_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, int] | None]:
    camera = slide.get("camera") or {}
    if bg_movie is not None:
        cap_w, cap_h = hop_capture_size(slide, dest_slide)
        ox = 0 if slide.get("_splitCg") and cap_w == CG_WIDTH else hop_map_origin_x(cap_w)
        return _item("movie", ox, 0, cap_w, cap_h, path=str(bg_movie), map=True), None
    cap_w, cap_h = slide_capture_size(slide)
    ox = slide_map_origin_x(slide)
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
    dest_slide: dict[str, Any] | None = None,
    pin_root: Path,
    asset_root: Path | None = None,
    country_still: Path | None = None,
    allow_reveal: bool = True,
    reveals: dict[tuple[str, str, str], str] | None = None,
    reveal_audience: str = "lw",
    sid: str = "",
    skip_landmarks: bool = False,
) -> list[dict[str, Any]]:
    """`pin_root` is required (see `_place_churches`); pass `output_dir / "pins"`."""
    mapped, placement = _map_item(
        slide, plate=plate, plate_path=plate_path, still=still, bg_movie=bg_movie, dest_slide=dest_slide
    )
    items = [mapped]
    if country_still is not None and still is not None and slide.get("isolate") and slide.get("highlights"):
        items.append(_item("image", mapped["x"], mapped["y"], mapped["w"], mapped["h"], path=str(country_still), map=True))
    cap_w, _cap_h = slide_capture_size(slide)
    origin_x = slide_map_origin_x(slide)
    if bg_movie is None or skip_landmarks:
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
                asset_root=asset_root,
                pin_root=pin_root,
                allow_reveal=allow_reveal,
                reveals=reveals,
                reveal_audience=reveal_audience,
                sid=sid,
                skip_landmarks=skip_landmarks,
            )
        )
    oversized_cg_movie = bg_movie is not None and float(mapped["w"]) > CG_WIDTH
    if not wall and (not slide.get("_splitCg") or oversized_cg_movie):
        origin = cg_crop_origin(slide) if not slide.get("_splitCg") else (CG_ORIGIN_X, 0.0)
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
        return {"effect": "dissolve", "duration": 1.0, "automatic": True, "delay": delay}
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
    audience: str = "lw",
    cg_affected: set[str] | None = None,
    reveals: dict[tuple[str, str, str], str] | None = None,
    reveal_movies: dict[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    slides, links = isolate_landing_slides(slides, links)
    slide_plate: dict[str, str] = {}
    for plate_id, geom in plates.items():
        for sid in geom.get("slideIds") or []:
            slide_plate[str(sid)] = plate_id
    ops: list[dict[str, Any]] = []
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    for index, slide in enumerate(slides):
        sid = str(slide.get("id") or "")
        cg_key = str(slide.get("_landingFor") or sid)
        asset_audience = "cg" if audience == "cg" and (cg_affected is None or cg_key in cg_affected) else "lw"
        plate_id = slide_plate.get(sid)
        plate = plates.get(plate_id) if plate_id else None
        plate_path = _plate_path(plate_id, output_dir) if plate_id else None
        outgoing = _outgoing(sid, links)
        dest_slide = by_id.get(str(outgoing.get("to") or "")) if outgoing else None
        bg_movie = None
        if outgoing and str(outgoing.get("kind") or "") == "movie":
            candidate = movie_path(output_dir, sid, asset_audience)
            if candidate.exists():
                bg_movie = candidate
                plate_id = None
                plate = None
                plate_path = None
        reveal_bg = False
        if bg_movie is None and reveal_movies:
            reveal_candidate = reveal_movies.get((asset_audience, cg_key))
            if reveal_candidate:
                bg_movie = Path(reveal_candidate)
                reveal_bg = True
                plate_id = None
                plate = None
                plate_path = None
        still = None if plate_id or bg_movie else _still_path(slide, output_dir, preview_dir, asset_audience)
        item_slide = slide
        item_dest = dest_slide
        if audience == "cg" and asset_audience == "cg" and bg_movie is not None:
            item_slide = {**slide, "_splitCg": True, "cgShiftX": 0, "includeSidePanels": False}
            item_dest = (
                {**dest_slide, "_splitCg": True, "cgShiftX": 0, "includeSidePanels": False}
                if dest_slide
                else None
            )
        if reveal_bg:
            item_dest = None
            reveal_view = item_slide if item_slide.get("_splitCg") else slide
            durations = [
                float((church.get("reveal") or {}).get("duration") or 1.2)
                for church in (reveal_view.get("churches") or [])
                if str(church.get("kind") or "") == "landmark" and church.get("reveal")
            ]
            item_slide = {**item_slide, "movieDuration": (max(durations) if durations else 1.2) + 0.3}
        prev_link = _outgoing(str(slides[index - 1].get("id") or ""), links) if index else None
        duplicate = bool(
            index
            and bg_movie is None
            and prev_link
            and str(prev_link.get("kind") or "") == "morph"
            and prev_link.get("plateId")
            and prev_link.get("plateId") == plate_id
        )
        country_still = (
            _country_still_path(slide, output_dir, asset_audience)
            if not duplicate and bg_movie is None and plate_id is None
            else None
        )
        items = build_slide_items(
            item_slide,
            plate=plate,
            plate_path=plate_path,
            still=still,
            movie=movie,
            wall=wall,
            bg_movie=bg_movie,
            dest_slide=item_dest,
            asset_root=output_dir / "assets",
            pin_root=output_dir / "pins",
            country_still=country_still,
            allow_reveal=not duplicate,
            reveals=reveals,
            reveal_audience="cg" if item_slide.get("_splitCg") else "lw",
            sid=cg_key,
            skip_landmarks=reveal_bg,
        )
        ops.append(
            {
                "id": sid,
                "duplicate": duplicate,
                "items": items,
                "transition": _transition_for(outgoing, item_slide, bg_movie=bg_movie is not None),
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
        # Keynote 15 honours the {file:…} initializer; {file name:…} silently no-ops.
        return [
            f'        set imgFile to (POSIX file "{path}") as alias',
            "        set img to make new image with properties {file:imgFile}",
            f"        set position of img to {{{x}, {y}}}",
            f"        set width of img to {w}",
            f"        set height of img to {h}",
        ]
    if kind == "movie":
        path = _as_escape(item["path"])
        # `make new image with properties {file:<mov>}` yields a movie object in Keynote 15;
        # `make new movie` no longer imports the file. Autoplay-on-appear still needs a manual check.
        if item.get("map"):
            return [
                f'        set movFile to (POSIX file "{path}") as alias',
                "        set mv to make new image with properties {file:movFile}",
                f"        set position of mv to {{{x}, {y}}}",
                f"        set width of mv to {w}",
                f"        set height of mv to {h}",
            ]
        fallback = item.get("fallback")
        lines = [
            "        try",
            f'          set movFile to (POSIX file "{path}") as alias',
            "          set mv to make new image with properties {file:movFile}",
            f"          set position of mv to {{{x}, {y}}}",
            f"          set width of mv to {w}",
            f"          set height of mv to {h}",
            "        on error",
        ]
        if fallback:
            fb_path = _as_escape(fallback)
            lines += [
                f'          set fbFile to (POSIX file "{fb_path}") as alias',
                "          set img to make new image with properties {file:fbFile}",
                f"          set position of img to {{{x}, {y}}}",
                f"          set width of img to {w}",
                f"          set height of img to {h}",
            ]
        lines.append("        end try")
        return lines
    text = _as_escape(str(item.get("text") or ""))
    font_size = float(item.get("fontSize") or 24)
    lines = [
        "        set txt to make new text item with properties "
        f'{{object text:"{text}", position:{{{x}, {y}}}, width:{w}, height:{h}}}',
        "        try",
        f"          set size of object text of txt to {font_size}",
        "        end try",
        "        try",
        "          set color of object text of txt to {65535, 65535, 65535}",
        "        end try",
    ]
    if item.get("bold"):
        lines += [
            "        try",
            f'          set font of object text of txt to "{LABEL_BOLD_FONT}"',
            "        on error",
            "          try",
            f'            set font of object text of txt to "{LABEL_BOLD_FALLBACK}"',
            "          end try",
            "        end try",
        ]
    return lines


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
            new_no = slide_no + 1
            body += [
                f"      make new slide at after slide {slide_no}",
                "      try",
                f'        set base slide of slide {new_no} of theDoc to master slide "Blank" of theDoc',
                "      on error",
                '        set masterStatus to "default"',
                "      end try",
            ]
            slide_no = new_no
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
            '    set themeStatus to "default"',
            '    set masterStatus to "blank"',
            "    set theDoc to make new document",
            "    try",
            '      set document theme of theDoc to theme "Basic Black"',
            '      set themeStatus to "basicblack"',
            "    end try",
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
            "    try",
            '      set base slide of slide 1 of theDoc to master slide "Blank" of theDoc',
            "    on error",
            '      set masterStatus to "default"',
            "    end try",
            "    tell theDoc",
            *body,
            "    end tell",
            "    save theDoc",
            '    log "theme=" & themeStatus & " master=" & masterStatus',
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
            "      set img to make new image with properties {file:imgFile}",
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


def _raise_if_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled and is_cancelled():
        raise RuntimeError("Export cancelled.")


def run_osascript(
    script: str, *, script_path: Path | None = None, is_cancelled: Callable[[], bool] | None = None
) -> subprocess.CompletedProcess[str]:
    """Execute AppleScript from a file (not stdin). Mock this in tests."""
    _raise_if_cancelled(is_cancelled)
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    _raise_if_cancelled(is_cancelled)
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
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc = subprocess.Popen(["osascript", str(script_path)], stdout=stdout, stderr=stderr)
            while proc.poll() is None:
                if is_cancelled and is_cancelled():
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    raise RuntimeError("Export cancelled.")
                time.sleep(0.05)
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(
                proc.args,
                proc.returncode,
                stdout.read().decode("utf-8", "replace"),
                stderr.read().decode("utf-8", "replace"),
            )
    finally:
        if owned:
            script_path.unlink(missing_ok=True)


def inspect_and_validate(path: Path, *, is_cancelled: Callable[[], bool] | None = None) -> list[Any]:
    from obed_edom.inspect import inspect_keynote
    from obed_edom.validate import validate_inspect

    _raise_if_cancelled(is_cancelled)
    payload = inspect_keynote(path, use_cache=False, is_cancelled=is_cancelled)
    _raise_if_cancelled(is_cancelled)
    flags = validate_inspect(payload, location_prefix=path.name, use_ocr=False, check_passages=False)
    _raise_if_cancelled(is_cancelled)
    return flags


def _inspect_dest(path: Path, job: Any, *, is_cancelled: Callable[[], bool] | None = None) -> list[Any]:
    if not path.exists():
        return []
    try:
        return inspect_and_validate(path, is_cancelled=is_cancelled)
    except RuntimeError as exc:
        if str(exc) == "Export cancelled.":
            raise
        _log(job, f"validate {path.name} failed: {exc}")
        return []
    except Exception as exc:
        _log(job, f"validate {path.name} failed: {exc}")
        return []


def _log(job: Any, message: str) -> None:
    log = getattr(job, "log", None)
    if callable(log):
        log(message)


_OFF_ALIASES = {"off", "0", "false", "no"}


def maps_poster_frame_mode(explicit: str | None = None) -> str:
    """`off` (default), `on` (surgical offline posterTime patch), or `verify` (patch +
    read-back log). Env `OBED_MAPS_POSTER_FRAME`."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_MAPS_POSTER_FRAME", "")).strip().lower()
    if raw in _OFF_ALIASES:
        return "off"
    return raw if raw in {"on", "verify"} else "off"


def maps_movie_autoplay_mode(explicit: str | None = None) -> str:
    """`on` (default; surgical offline autoplay-after-transition patch), `off`, or
    `verify` (patch + read-back log). Env `OBED_MAPS_MOVIE_AUTOPLAY`."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_MAPS_MOVIE_AUTOPLAY", "")).strip().lower()
    if raw in _OFF_ALIASES:
        return "off"
    return raw if raw == "verify" else "on"


def _poster_targets(ops: list[dict[str, Any]], reveal_poster_times: dict[tuple[str, str, str], float]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for op in ops:
        for item in op.get("items") or []:
            if not (item.get("landmark") and item.get("kind") == "movie"):
                continue
            key = item.get("revealKey")
            if key is None or tuple(key) not in reveal_poster_times:
                continue
            targets.append(
                {
                    "x": float(item["x"]),
                    "y": float(item["y"]),
                    "w": float(item["w"]),
                    "h": float(item["h"]),
                    "posterTime": reveal_poster_times[tuple(key)],
                    "name": item.get("path"),
                }
            )
    return targets


def _autoplay_targets(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for op in ops:
        for item in op.get("items") or []:
            if item.get("landmark") and item.get("kind") == "movie":
                targets.append(
                    {"x": float(item["x"]), "y": float(item["y"]), "w": float(item["w"]), "h": float(item["h"]),
                     "name": item.get("path")}
                )
    return targets


def _apply_movie_autoplay(
    dest: Path,
    ops: list[dict[str, Any]],
    job: Any,
    deck_label: str,
    *,
    width: int,
    height: int,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any] | None:
    """Patch reveal movies in ``dest`` to start right after their slide's build-in
    transition, no click needed (owner 2026-09-12 probe: Keynote's AppleScript movie
    class exposes no autoplay-style property -- only file name/volume/reflection/
    repetition method/rotation, see Keynote.sdef -- so this is patched offline the
    same way Keynote itself saves "Start = After Transition"). Gated behind
    `OBED_MAPS_MOVIE_AUTOPLAY` (default on); a refusal is never fatal to export, same
    containment as `_apply_poster_frames`."""
    mode = maps_movie_autoplay_mode()
    from obed_edom.offline_write import probe_iwa_extra

    mode = probe_iwa_extra(mode, lambda m: _log(job, m))
    if mode == "off":
        return None
    targets = _autoplay_targets(ops)
    if not targets:
        return {"deck": deck_label, "mode": mode, "applied": 0, "refused": False, "reason": None, "regenerated": False}

    from obed_edom.iwa_movies import movie_autoplay_state, patch_movie_autoplay, plan_movie_autoplay
    from obed_edom.iwa_write import OfflineWriteCorrupted

    try:
        plan = plan_movie_autoplay(dest, targets)
        if plan["refused"]:
            _log(job, f"movieAutoplay {deck_label}: refused ({plan['reason']})")
            return {
                "deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": plan["reason"],
                "regenerated": False,
            }

        patched = patch_movie_autoplay(dest, plan["ids"])
        if patched["refused"]:
            _log(job, f"movieAutoplay {deck_label}: refused ({patched['reason']})")
            return {
                "deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": patched["reason"],
                "regenerated": False,
            }

        _log(job, f"movieAutoplay {deck_label}: patched {patched['applied']} reveal movie(s)")
        if mode == "verify":
            state = movie_autoplay_state(dest, patched["touched"])
            bad: list[str] = []
            for oid in patched["touched"]:
                read = state.get(oid, {})
                _log(
                    job,
                    f"movieAutoplay {deck_label}: {oid} playsAcrossSlides={read.get('playsAcrossSlides')} "
                    f"automatic={read.get('automatic')}",
                )
                if read.get("playsAcrossSlides") is not False or read.get("automatic") is not True:
                    bad.append(
                        f"{oid} playsAcrossSlides={read.get('playsAcrossSlides')} automatic={read.get('automatic')}"
                    )
            if bad:
                reason = "verify read-back mismatch: " + "; ".join(bad)
                _log(job, f"movieAutoplay {deck_label}: refused ({reason})")
                return {
                    "deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": reason,
                    "regenerated": False,
                }
        return {
            "deck": deck_label, "mode": mode, "applied": patched["applied"], "refused": False, "reason": None,
            "regenerated": False,
        }
    except OfflineWriteCorrupted as exc:
        _log(job, f"movieAutoplay {deck_label}: deck truncated during patch ({exc}); regenerating unpatched…")
        _run_one_deck(
            ops, dest, width=width, height=height, is_cancelled=is_cancelled, log=lambda m: _log(job, m)
        )
        from obed_edom.iwa_write import recovery_tmp_path

        recovery_tmp_path(dest).unlink(missing_ok=True)
        return {
            "deck": deck_label,
            "mode": mode,
            "applied": 0,
            "refused": True,
            "reason": f"deck truncated during patch, regenerated unpatched: {exc}",
            "regenerated": True,
        }
    except Exception as exc:  # noqa: BLE001 — every optional-patch failure refuses, never fatal
        _log(job, f"movieAutoplay {deck_label}: refused (unexpected error: {exc})")
        return {
            "deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": f"unexpected error: {exc}",
            "regenerated": False,
        }


def _invalidate_poster_on_regeneration(
    poster_record: dict[str, Any] | None, autoplay_record: dict[str, Any] | None
) -> None:
    """If autoplay patching left the deck truncated, `_apply_movie_autoplay` regenerates
    it unpatched -- which also wipes any poster-frame patch already applied to that same
    deck. Mark the stale poster record refused so it doesn't survive into `result`."""
    if autoplay_record is None or not autoplay_record.get("regenerated"):
        return
    if poster_record is not None and not poster_record["refused"]:
        poster_record["applied"] = 0
        poster_record["refused"] = True
        poster_record["reason"] = "discarded by autoplay regeneration"


def _apply_poster_frames(
    dest: Path,
    ops: list[dict[str, Any]],
    reveal_poster_times: dict[tuple[str, str, str], float],
    job: Any,
    deck_label: str,
    *,
    width: int,
    height: int,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any] | None:
    """Patch reveal-movie ``posterTime`` in ``dest`` to last-frame. Gated behind
    `OBED_MAPS_POSTER_FRAME` (default off); a refusal is never fatal to export --
    the deck simply keeps today's first-frame posters. Every failure mode of the
    optional patch (decode, planning, patch, verify reread) is contained here and
    turned into a refusal; if the deck may have been left truncated (an
    ``OfflineWriteCorrupted`` raised once ``_rewrite_members`` began truncating the
    real inode), the deck is regenerated unpatched before returning."""
    mode = maps_poster_frame_mode()
    from obed_edom.offline_write import probe_iwa_extra

    mode = probe_iwa_extra(mode, lambda m: _log(job, m))
    if mode == "off":
        return None
    targets = _poster_targets(ops, reveal_poster_times)
    if not targets:
        return {"deck": deck_label, "mode": mode, "applied": 0, "refused": False, "reason": None}

    from obed_edom.iwa_movies import movie_archives, patch_movie_posters, plan_movie_posters
    from obed_edom.iwa_write import OfflineWriteCorrupted

    try:
        plan = plan_movie_posters(dest, targets)
        if plan["refused"]:
            _log(job, f"posterFrame {deck_label}: refused ({plan['reason']})")
            return {"deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": plan["reason"]}

        patched = patch_movie_posters(dest, plan["posters"])
        if patched["refused"]:
            _log(job, f"posterFrame {deck_label}: refused ({patched['reason']})")
            return {"deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": patched["reason"]}

        _log(job, f"posterFrame {deck_label}: patched {patched['applied']} reveal movie(s)")
        if mode == "verify":
            by_id = {a["id"]: a["posterTime"] for a in movie_archives(dest)}
            for oid in patched["touched"]:
                _log(job, f"posterFrame {deck_label}: {oid} posterTime={by_id.get(oid)}")
        return {"deck": deck_label, "mode": mode, "applied": patched["applied"], "refused": False, "reason": None}
    except OfflineWriteCorrupted as exc:
        _log(job, f"posterFrame {deck_label}: deck truncated during patch ({exc}); regenerating unpatched…")
        _run_one_deck(
            ops, dest, width=width, height=height, is_cancelled=is_cancelled, log=lambda m: _log(job, m)
        )
        from obed_edom.iwa_write import recovery_tmp_path

        recovery_tmp_path(dest).unlink(missing_ok=True)
        return {
            "deck": deck_label,
            "mode": mode,
            "applied": 0,
            "refused": True,
            "reason": f"deck truncated during patch, regenerated unpatched: {exc}",
        }
    except Exception as exc:  # noqa: BLE001 — every optional-patch failure refuses, never fatal
        _log(job, f"posterFrame {deck_label}: refused (unexpected error: {exc})")
        return {"deck": deck_label, "mode": mode, "applied": 0, "refused": True, "reason": f"unexpected error: {exc}"}


def _run_one_deck(
    ops: list[dict[str, Any]],
    dest: Path,
    *,
    width: int,
    height: int,
    is_cancelled: Callable[[], bool] | None = None,
    log: Callable[[str], None] | None = None,
) -> str:
    _raise_if_cancelled(is_cancelled)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _remove_key(dest)
    script = build_deck_script(ops, dest, width=width, height=height)
    proc = run_osascript(script, is_cancelled=is_cancelled)
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
    if log is not None:
        for line in (proc.stdout or "").splitlines() + (proc.stderr or "").splitlines():
            line = line.strip()
            if line.startswith("theme=") or line.startswith("master="):
                log(line)
    return script


def _render_reveals(
    output_dir: Path,
    slides: list[dict[str, Any]],
    links: list[dict[str, Any]],
    log: Callable[[str], None],
    is_cancelled: Callable[[], bool] | None,
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str], str], dict[tuple[str, str, str], float]]:
    """Render paint-on reveal movies without mutating the job's stored slides/churches.

    Returns (reveals, reveal_movies, reveal_poster_times): reveals is keyed (audience,
    slideId, churchId) -> movie path, used for per-landmark reveal items; reveal_movies is
    keyed (audience, slideId) -> movie path, used for the "Reveal as slide movie" bg movie;
    reveal_poster_times mirrors reveals' keys with each movie's last-frame start time
    (seconds), for the OBED_MAPS_POSTER_FRAME offline patch.
    """
    from obed_edom.maps_reveal import (
        REVEAL_FPS,
        render_reveal,
        render_slide_reveal_movie,
        reveal_fingerprint,
        reveal_movie_fingerprint,
        reveal_movie_path,
        reveal_path,
        reveal_seed,
        reveal_stale,
    )

    asset_root = output_dir / "assets"
    reveals: dict[tuple[str, str, str], str] = {}
    reveal_movies: dict[tuple[str, str], str] = {}
    reveal_poster_times: dict[tuple[str, str, str], float] = {}
    for slide in slides:
        sid = str(slide.get("id") or "")
        outgoing = _outgoing(sid, links)
        is_fly_source = bool(outgoing and str(outgoing.get("kind") or "") == "movie")
        if is_fly_source:
            continue
        for audience, view in (("lw", slide), ("cg", slide.get("cg"))):
            if not isinstance(view, dict):
                continue
            for church in view.get("churches") or []:
                reveal = church.get("reveal")
                if str(church.get("kind") or "") != "landmark" or not reveal:
                    continue
                asset_id = str(church.get("assetId") or "")
                asset = asset_root / f"{asset_id}.png"
                if not asset_id or not asset.is_file():
                    continue
                church_id = str(church.get("id") or "")
                dest = reveal_path(output_dir, sid, church_id, audience)
                duration = float(reveal.get("duration") or 1.2)
                seed = reveal_seed(church_id)
                opacity = float(church.get("opacity") if church.get("opacity") is not None else 1)
                strokes = int(reveal.get("strokes") or 4)
                fingerprint = reveal_fingerprint(
                    asset,
                    duration=duration,
                    opacity=opacity,
                    seed=seed,
                    width=int(church.get("assetWidth") or 0),
                    height=int(church.get("assetHeight") or 0),
                    strokes=strokes,
                )
                if reveal_stale(dest, fingerprint):
                    _raise_if_cancelled(is_cancelled)
                    log(f"Rendering paint-on reveal for {church.get('name') or asset_id}…")
                    render_reveal(
                        asset,
                        dest,
                        duration=duration,
                        seed=seed,
                        opacity=opacity,
                        strokes=strokes,
                        fingerprint=fingerprint,
                        is_cancelled=is_cancelled,
                    )
                reveals[(audience, sid, church_id)] = str(dest)
                reveal_poster_times[(audience, sid, church_id)] = (max(2, round(duration * REVEAL_FPS)) - 1) / float(REVEAL_FPS)
            if not view.get("revealMovie"):
                continue
            landmark_churches = [
                church
                for church in (view.get("churches") or [])
                if str(church.get("kind") or "") == "landmark" and church.get("reveal")
            ]
            if not landmark_churches:
                continue
            item_slide = {**_cg_view(slide), "_splitCg": True} if audience == "cg" else slide
            try:
                still = _still_path(item_slide, output_dir, audience=audience)
            except FileNotFoundError:
                continue
            country_still = _country_still_path(item_slide, output_dir, audience)
            cap_w, cap_h = slide_capture_size(item_slide)
            origin_x = slide_map_origin_x(item_slide)
            slide_zoom = float((item_slide.get("camera") or {}).get("zoom") or 0)
            landmark_churches = [
                church for church in landmark_churches if _effective_size(church, slide_zoom, None) >= 1
            ]
            if not landmark_churches:
                continue
            geometry_items = _place_churches(
                landmark_churches,
                plate=None,
                placement=None,
                camera=item_slide.get("camera") or {},
                wall=(audience == "lw"),
                movie=None,
                origin_x=origin_x,
                capture_w=cap_w,
                asset_root=asset_root,
                pin_root=output_dir / "pins",
                allow_reveal=False,
                sid=sid,
            )
            landmark_items = [item for item in geometry_items if item.get("landmark")]
            if len(landmark_items) != len(landmark_churches):
                continue
            landmarks: list[dict[str, Any]] = []
            for church, item in zip(landmark_churches, landmark_items):
                asset_path = item.get("fallback") or item.get("path")
                if not asset_path:
                    continue
                reveal = church.get("reveal") or {}
                landmarks.append(
                    dict(
                        asset=Path(str(asset_path)),
                        x=item["x"] - origin_x,
                        y=item["y"],
                        w=item["w"],
                        h=item["h"],
                        duration=float(reveal.get("duration") or 1.2),
                        seed=reveal_seed(str(church.get("id") or "")),
                        opacity=float(church.get("opacity") if church.get("opacity") is not None else 1),
                        strokes=int(reveal.get("strokes") or 4),
                    )
                )
            if not landmarks:
                continue
            movie_dest = reveal_movie_path(output_dir, sid, audience)
            fingerprint = reveal_movie_fingerprint(still, landmarks)
            if reveal_stale(movie_dest, fingerprint):
                _raise_if_cancelled(is_cancelled)
                log(f"Rendering reveal slide movie for {sid}…")
                render_slide_reveal_movie(
                    still,
                    country_still,
                    landmarks,
                    movie_dest,
                    output_dir=output_dir,
                    slide_id=sid,
                    audience=audience,
                    size=(cap_w, cap_h),
                    fingerprint=fingerprint,
                    is_cancelled=is_cancelled,
                )
            reveal_movies[(audience, sid)] = str(movie_dest)
    return reveals, reveal_movies, reveal_poster_times


def export_maps_job(
    job: Any,
    *,
    export_lw: bool = True,
    export_cg: bool = True,
    export_dsk: bool = False,
    export_dir: Path | None = None,
) -> dict[str, Any]:
    if not export_lw and not export_cg and not export_dsk:
        raise ValueError("At least one export target must be on")
    is_cancelled = getattr(job, "cancelled", lambda: False)
    _raise_if_cancelled(is_cancelled)
    result = inherit_hidden_layers(dict(getattr(job, "result", None) or {}))
    output_dir = Path(
        str(
            result.get("outputDir")
            or find_repo_root() / "output" / ".maps" / str(getattr(job, "name", None) or getattr(job, "id", "maps"))
        )
    )
    preview_dir = Path(str(result.get("previewDir") or (output_dir / "previews")))
    output_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    slides = [dict(slide) for slide in (result.get("slides") or [])]
    links = [dict(link) for link in (result.get("links") or [])]
    if not slides:
        raise ValueError("Maps document has no slides")
    try:
        from obed_edom.maps_movie import encode_pending

        slides = encode_pending(
            output_dir, slides, log=lambda m: _log(job, m), links=links, is_cancelled=is_cancelled
        )
    except (ImportError, AttributeError):
        pass
    else:
        result["slides"] = slides
    _raise_if_cancelled(is_cancelled)
    reveals: dict[tuple[str, str, str], str] = {}
    reveal_movies: dict[tuple[str, str], str] = {}
    reveal_poster_times: dict[tuple[str, str, str], float] = {}
    try:
        reveals, reveal_movies, reveal_poster_times = _render_reveals(
            output_dir, slides, links, lambda m: _log(job, m), is_cancelled
        )
    except ImportError:
        pass
    _raise_if_cancelled(is_cancelled)
    plan = maps_export_plan(slides, links)
    plates = plan["plateGeoms"]
    links = plan["links"]
    result["links"] = links
    movie = find_pin_drop_wave()
    stem = str(result.get("stem") or getattr(job, "name", "") or f"maps-{getattr(job, 'id', 'maps')}")
    flags: list[Any] = []
    flags_cg: list[Any] = []
    poster_frame: list[dict[str, Any]] = []
    movie_autoplay: list[dict[str, Any]] = []
    if export_dir is not None:
        export_dir = ensure_export_dir(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
    if export_lw:
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
        dest = (export_dir or output_dir) / f"{stem}.key"
        _log(job, f"Exporting wall deck {dest.name} (7680×1080)…")
        ops = plan_deck(
            slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=True,
            reveals=reveals, reveal_movies=reveal_movies,
        )
        _run_one_deck(
            ops, dest, width=WALL_WIDTH, height=WALL_HEIGHT, is_cancelled=is_cancelled, log=lambda m: _log(job, m)
        )
        result["destPath"] = str(dest)
        _raise_if_cancelled(is_cancelled)
        record_lw = _apply_poster_frames(
            dest, ops, reveal_poster_times, job, "lw",
            width=WALL_WIDTH, height=WALL_HEIGHT, is_cancelled=is_cancelled,
        )
        if record_lw is not None:
            poster_frame.append(record_lw)
        autoplay_record = _apply_movie_autoplay(
            dest, ops, job, "lw", width=WALL_WIDTH, height=WALL_HEIGHT, is_cancelled=is_cancelled
        )
        if autoplay_record is not None:
            movie_autoplay.append(autoplay_record)
        _invalidate_poster_on_regeneration(record_lw, autoplay_record)
        flags = _inspect_dest(dest, job, is_cancelled=is_cancelled)
    if export_dsk:
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
        dest_dsk = (export_dir or output_dir) / f"{stem}_DSK.key"
        _log(job, f"Exporting DSK deck {dest_dsk.name} (1920×1080)…")
        ops_dsk = dsk_ops(
            plan_deck(
                slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=True,
                reveals=reveals, reveal_movies=reveal_movies,
            )
        )
        _run_one_deck(
            ops_dsk, dest_dsk, width=DSK_WIDTH, height=DSK_HEIGHT, is_cancelled=is_cancelled, log=lambda m: _log(job, m)
        )
        result["destPathDsk"] = str(dest_dsk)
        record_dsk = _apply_poster_frames(
            dest_dsk, ops_dsk, reveal_poster_times, job, "dsk",
            width=DSK_WIDTH, height=DSK_HEIGHT, is_cancelled=is_cancelled,
        )
        if record_dsk is not None:
            poster_frame.append(record_dsk)
        autoplay_record = _apply_movie_autoplay(
            dest_dsk, ops_dsk, job, "dsk", width=DSK_WIDTH, height=DSK_HEIGHT, is_cancelled=is_cancelled
        )
        if autoplay_record is not None:
            movie_autoplay.append(autoplay_record)
        _invalidate_poster_on_regeneration(record_dsk, autoplay_record)
    if export_cg:
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
        dest_cg = (export_dir or output_dir) / f"{stem}_CG.key"
        _log(job, f"Exporting CG deck {dest_cg.name} (1920×1080)…")
        split_cg = any(isinstance(slide.get("cg"), dict) for slide in slides)
        if split_cg:
            cg_plan = split_cg_export_plan(slides, links)
            cg_slides = [
                {**_cg_view(slide), "_splitCg": True} if isinstance(slide.get("cg"), dict) else slide
                for slide in slides
            ]
            affected = set(cg_plan["affectedSlideIds"])
            cg_links = [
                cg_link if _link_ends(cg_link)[0] in affected or _link_ends(cg_link)[1] in affected else lw_link
                for lw_link, cg_link in zip(links, cg_plan["links"])
            ]
            cg_plates = {**plates, **cg_plan["plateGeoms"]}
            try:
                encode_pending(
                    output_dir, cg_slides, log=lambda m: _log(job, m), links=cg_links,
                    is_cancelled=is_cancelled, audience="cg"
                )
            except (ImportError, AttributeError):
                pass
            ops_cg = plan_deck(
                cg_slides, cg_links, cg_plates, output_dir=output_dir, preview_dir=preview_dir,
                movie=movie, wall=False, audience="cg", cg_affected=affected, reveals=reveals,
                reveal_movies=reveal_movies,
            )
        else:
            ops_cg = plan_deck(
                slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=False,
                reveals=reveals, reveal_movies=reveal_movies,
            )
        _run_one_deck(
            ops_cg, dest_cg, width=CG_WIDTH, height=CG_HEIGHT, is_cancelled=is_cancelled, log=lambda m: _log(job, m)
        )
        result["destPathCg"] = str(dest_cg)
        _raise_if_cancelled(is_cancelled)
        record_cg = _apply_poster_frames(
            dest_cg, ops_cg, reveal_poster_times, job, "cg",
            width=CG_WIDTH, height=CG_HEIGHT, is_cancelled=is_cancelled,
        )
        if record_cg is not None:
            poster_frame.append(record_cg)
        autoplay_record = _apply_movie_autoplay(
            dest_cg, ops_cg, job, "cg", width=CG_WIDTH, height=CG_HEIGHT, is_cancelled=is_cancelled
        )
        if autoplay_record is not None:
            movie_autoplay.append(autoplay_record)
        _invalidate_poster_on_regeneration(record_cg, autoplay_record)

        flags_cg = _inspect_dest(dest_cg, job, is_cancelled=is_cancelled)
    if not export_lw:
        result.pop("destPath", None)
    if not export_cg:
        result.pop("destPathCg", None)
    if not export_dsk:
        result.pop("destPathDsk", None)
    result["exportLw"] = bool(export_lw)
    result["exportCg"] = bool(export_cg)
    result["exportDsk"] = bool(export_dsk)
    if poster_frame:
        result["posterFrame"] = poster_frame
    else:
        # Gate off (or no reveal movies to patch): never let a stale record from a
        # prior on/verify run survive in `result`, which starts as a copy of it.
        result.pop("posterFrame", None)
    if movie_autoplay:
        result["movieAutoplay"] = movie_autoplay
    else:
        result.pop("movieAutoplay", None)
    from obed_edom.validate import flag_dict

    if export_lw:
        result["flags"] = [flag_dict(flag) for flag in flags]
    if export_cg:
        result["flagsCg"] = [flag_dict(flag) for flag in flags_cg]
    _raise_if_cancelled(is_cancelled)
    return result
