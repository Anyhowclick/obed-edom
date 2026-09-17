"""P1 Maps Keynote export: greenfield LW/CG stills and shared-plate morph.

P2: HEVC fly/route movies, is_backdrop Map BG, score_resize — deferred.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import warnings
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
    default_landmark_size,
    infer_hop_kind,
    inherit_hidden_layers,
    inverse_mercator_y,
    mercator_y,
    signed_bearing_delta,
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
# Keynote object size after placement. Capture still fits to MAX_TEXTURE_SIZE; this
# is how big the PNG is drawn on the slide. 16384 is 2× the old unfitted-8192 gate.
MAX_MORPH_DISPLAY_PX = 16384
TIMEOUT_SECONDS = 3600
PANEL_EDGES = (1920.0, 5760.0)
PIN_MAX_PT = 180
DOT_SIZE = 28
DROP_SIZE = 64
PHOTO_SIZE = 96
NAME_HEIGHT = 32
LABEL_BOLD_FONT = "Amplitude-Bold"
LABEL_BOLD_FALLBACK = "HelveticaNeue-Bold"
LABEL_FONT_PT = 23
LABEL_GAP = 8
LABEL_CHAR_W = 13
PILL_PAD_X = 6
PILL_PAD_Y = 2
LABEL_SCALE_MIN = 0.5
LABEL_SCALE_MAX = 8
CREDITS_TITLE = "Map data"
CREDITS_FONT = 28
CREDITS_TITLE_FONT = 40
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


_EXPORT_NAME_SUFFIXES = ("_CG", "_DSK", "_LW")


def maps_export_stem(name: str) -> str:
    """Strip a trailing `_CG` / `_DSK` / `_LW` so a save-panel name can be the stem."""
    stem = Path(name).stem
    for suffix in _EXPORT_NAME_SUFFIXES:
        if stem.endswith(suffix):
            stripped = stem[: -len(suffix)]
            return stripped or stem
    return stem


def maps_export_dests(
    *,
    export_lw: bool,
    export_cg: bool,
    export_dsk: bool,
    output_dir: Path,
    stem: str,
    export_dir: Path | None = None,
    export_path: Path | None = None,
) -> tuple[Path | None, Path | None, Path | None]:
    """Return `(dest_lw, dest_cg, dest_dsk)` for the selected targets.

    With one target, `export_path` is that file. With several, it is the stem:
    `Sunday.key`, `Sunday_CG.key`, `Sunday_DSK.key`.
    """
    if export_path is not None:
        chosen = Path(export_path)
        if chosen.suffix.lower() != ".key":
            chosen = chosen.with_name(f"{chosen.name}.key")
        parent = chosen.parent
        n = int(export_lw) + int(export_cg) + int(export_dsk)
        if n == 1:
            return (
                chosen if export_lw else None,
                chosen if export_cg else None,
                chosen if export_dsk else None,
            )
        base = maps_export_stem(chosen.name)
        return (
            parent / f"{base}.key" if export_lw else None,
            parent / f"{base}_CG.key" if export_cg else None,
            parent / f"{base}_DSK.key" if export_dsk else None,
        )
    root = export_dir or output_dir
    return (
        root / f"{stem}.key" if export_lw else None,
        root / f"{stem}_CG.key" if export_cg else None,
        root / f"{stem}_DSK.key" if export_dsk else None,
    )


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


def _label_pill_rgb(church: dict[str, Any]) -> tuple[int, int, int]:
    raw = church.get("labelColor")
    return parse_color(str(raw)) if raw else LABEL_PILL_RGB


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


EXPORT_REF_WIDTH = 1920


def export_scale(surface_width: float) -> float:
    """Mirrors `dashboard` `exportScale`: 1920→1, 3840→2, 7680→4."""
    return 2 ** max(0, round(math.log2(max(float(surface_width), 1.0) / EXPORT_REF_WIDTH)))


def export_zoom_delta(surface_width: float) -> float:
    """Mirrors `dashboard` `exportZoomDelta`. Style/tile zoom offset for a capture surface."""
    scale = export_scale(surface_width)
    return -math.log2(scale) if scale else 0.0


def movie_endpoint_surface(
    slide: dict[str, Any],
    plates: list[dict[str, Any]] | dict[str, dict[str, Any]],
    slides: list[dict[str, Any]],
) -> int:
    """Style/tile surface at one movie end: that slide's plate, else its own capture."""
    own = slide_capture_size(slide)[0]
    sid = str(slide.get("id") or "")
    by_id = {str(row.get("id") or ""): row for row in slides}
    plate_rows = plates.values() if isinstance(plates, dict) else plates
    for plate in plate_rows:
        ids = [str(item) for item in (plate.get("slideIds") or [])]
        if sid not in ids:
            continue
        widest = own
        for member_id in ids:
            member = by_id.get(member_id)
            if member is not None:
                widest = max(widest, slide_capture_size(member)[0])
        return widest
    return own


def movie_render_surface(
    from_slide: dict[str, Any],
    to_slide: dict[str, Any],
    plates: list[dict[str, Any]] | dict[str, dict[str, Any]],
    slides: list[dict[str, Any]],
) -> int:
    """Style/tile surface for movie frame 0: the *source* plate, else the source slide.

    Hop output size stays `hop_capture_size`. Do not `max` with the dest/hop — a
    3840 plate followed by a 7680 movie must take off at 3840.
    """
    return movie_endpoint_surface(from_slide, plates, slides)


def movie_viewport_width(from_width: float, to_width: float, t: float) -> int:
    """Visible authored width at hop progress `t` (0 = source plate, 1 = dest)."""
    u = max(0.0, min(1.0, float(t)))
    return int(round_half_away(float(from_width) + (float(to_width) - float(from_width)) * u))


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


def _rotate_offset(dx: float, dy: float, bearing: float) -> tuple[float, float]:
    theta = math.radians(float(bearing) or 0.0)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return cos_t * dx + sin_t * dy, -sin_t * dx + cos_t * dy


def viewport_aabb(
    camera: dict[str, Any],
    width: float,
    height: float,
    plate_bearing: float,
) -> tuple[float, float, float, float]:
    """Camera viewport as an AABB in the plate's bearing frame."""
    axis = normalized_viewport(camera, width, height, plate_bearing)
    delta = signed_bearing_delta(plate_bearing, float(camera.get("bearing") or 0))
    if abs(delta) < 1e-9:
        return axis
    cx = (axis[0] + axis[2]) / 2.0
    cy = (axis[1] + axis[3]) / 2.0
    hw = (axis[2] - axis[0]) / 2.0
    hh = (axis[3] - axis[1]) / 2.0
    xs: list[float] = []
    ys: list[float] = []
    for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        rx, ry = _rotate_offset(dx, dy, delta)
        xs.append(cx + rx)
        ys.append(cy + ry)
    return (min(xs), min(ys), max(xs), max(ys))


def _camera_cover_box(
    camera: dict[str, Any],
    width: float,
    height: float,
    plate_bearing: float,
) -> tuple[float, float, float, float]:
    """Mercator AABB of the LW circumcircle, so any rotation about the camera still covers the frame."""
    axis = normalized_viewport(camera, width, height, plate_bearing)
    cx = (axis[0] + axis[2]) / 2.0
    cy = (axis[1] + axis[3]) / 2.0
    world = world_width(float(camera.get("zoom") or 0))
    radius = math.hypot(float(width) / 2.0, float(height) / 2.0) / world if world else 0.0
    return (cx - radius, cy - radius, cx + radius, cy + radius)


def _geom_from_union(
    union: tuple[float, float, float, float],
    cameras: list[dict[str, Any]],
    canvas: list[float],
    height: float,
    bearing: float,
) -> dict[str, Any] | None:
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
        "width": float(max(canvas) if canvas else WALL_WIDTH),
        "height": float(height),
        "captureCamera": capture,
    }


def _slide_xy_to_mercator(
    sx: float,
    sy: float,
    plate: dict[str, Any],
    placement: dict[str, Any],
) -> tuple[float, float]:
    """Inverse of `project_into_plate`: slide pixels back to the plate's bearing-frame mercator."""
    rot = quantized_rotation(placement.get("rotation") or 0)
    ux, uy = sx, sy
    if rot:
        cx = float(placement["x"]) + float(placement["w"]) / 2.0
        cy = float(placement["y"]) + float(placement["h"]) / 2.0
        ux, uy = _rotate_about(sx, sy, cx, cy, -rot)
    scale_x = float(placement["w"]) / float(plate["plateW"]) if plate["plateW"] else 1.0
    scale_y = float(placement["h"]) / float(plate["plateH"]) if plate["plateH"] else 1.0
    world = world_width(float(plate["zPlate"]))
    union = plate["union"]
    nx = union[0] + (ux - float(placement["x"])) / (world * scale_x) if world and scale_x else union[0]
    ny = union[1] + (uy - float(placement["y"])) / (world * scale_y) if world and scale_y else union[1]
    return nx, ny


def _grow_union_for_rotated_lw(
    cameras: list[dict[str, Any]],
    canvas: list[float],
    height: float,
    bearing: float,
    union: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Expand the union until each camera's placed+rotated plate covers its LW rectangle.

    Keynote rotates about the plate centre, not the camera, so the AABB of a rotated
    viewport is not always enough — zoom/pan leaves the plate centre off the LW
    centre and the corners swing out.
    """
    next_union = union
    for _ in range(8):
        geom = _geom_from_union(next_union, cameras, canvas, height, bearing)
        if geom is None:
            return next_union
        grew = False
        x0, y0, x1, y1 = next_union
        for cam, width in zip(cameras, canvas):
            place = _place_plate_float(cam, geom, width=width, height=height)
            for sx, sy in ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height)):
                nx, ny = _slide_xy_to_mercator(sx, sy, geom, place)
                if nx < x0 - 1e-12 or ny < y0 - 1e-12 or nx > x1 + 1e-12 or ny > y1 + 1e-12:
                    grew = True
                x0, y0, x1, y1 = min(x0, nx), min(y0, ny), max(x1, nx), max(y1, ny)
        next_union = (x0, y0, x1, y1)
        if not grew:
            break
    return next_union


def morph_plate_geom(
    cameras: list[dict[str, Any]],
    *,
    width: float = WALL_WIDTH,
    height: float = WALL_HEIGHT,
    widths: list[float] | None = None,
) -> dict[str, Any] | None:
    """Union mercator viewports; one raster at the deeper zoom. None if the union is degenerate.

    Each camera contributes its bearing-frame AABB. A hop that actually rotates also
    adds the LW circumcircle and grows until a Keynote rotate-about-centre still
    covers the frame. Zoom/pan hops stay on the AABB so the fitted 8192 raster
    matches the live preview instead of a padded square.
    """
    if not cameras:
        return None
    canvas = list(widths) if widths is not None else [width] * len(cameras)
    if len(canvas) != len(cameras):
        canvas = [width] * len(cameras)
    bearing = float(cameras[0].get("bearing") or 0)
    boxes = [viewport_aabb(cam, w, height, bearing) for cam, w in zip(cameras, canvas)]
    # Circumcircle + grow are only for Keynote rotate-about-centre. A zoom/pan hop
    # must stay the AABB of the cameras or the fitted 8192 raster spends most of
    # its pixels on empty padding and Magic Move no longer matches the preview.
    needs_rotation_pad = any(
        quantized_rotation(signed_bearing_delta(bearing, float(cam.get("bearing") or 0))) for cam in cameras
    )
    if needs_rotation_pad:
        boxes += [_camera_cover_box(cam, w, height, bearing) for cam, w in zip(cameras, canvas)]
    union = (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )
    if needs_rotation_pad:
        union = _grow_union_for_rotated_lw(cameras, canvas, height, bearing, union)
    return _geom_from_union(union, cameras, canvas, height, bearing)


def fit_morph_plate(geom: dict[str, Any], max_side: float = MAX_TEXTURE_SIZE) -> dict[str, Any]:
    """Lower capture zoom so the union raster fits in `max_side`.

    Keynote still places that PNG larger than the slide when zooming in — overflow is the
    Magic Move, not a reason to fall back to Movie.
    """
    plate_w = float(geom["plateW"])
    plate_h = float(geom["plateH"])
    longest = max(plate_w, plate_h)
    if longest <= max_side:
        return geom
    z_plate = float(geom["zPlate"]) + math.log2(max_side / longest)
    union = geom["union"]
    world = world_width(z_plate)
    plate_w = (union[2] - union[0]) * world
    plate_h = (union[3] - union[1]) * world
    snap = max(plate_w, plate_h)
    if snap > max_side:
        scale = max_side / snap
        plate_w *= scale
        plate_h *= scale
    bearing = float((geom.get("captureCamera") or {}).get("bearing") or 0)
    nx = (union[0] + union[2]) / 2.0
    ny = (union[1] + union[3]) / 2.0
    nx, ny = unrotated_mercator(nx, ny, bearing)
    capture = camera_dict(inverse_mercator_y(ny), nx * 360.0 - 180.0, z_plate, bearing, 0.0)
    return {**geom, "zPlate": z_plate, "plateW": plate_w, "plateH": plate_h, "captureCamera": capture}


def _place_plate_float(
    camera: dict[str, Any],
    plate: dict[str, Any],
    *,
    width: float,
    height: float,
) -> dict[str, Any]:
    """Unrounded placement. Rotation is about the plate centre, so a zoom/pan
    hop shifts `(x, y)` until that centre-rotation keeps the camera on the LW
    midpoint — Keynote cannot rotate about an off-centre viewport.
    """
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
    rotation = quantized_rotation(signed_bearing_delta(bearing, float(camera.get("bearing") or 0)))
    if rotation:
        cx = img_x + disp_w / 2.0
        cy = img_y + disp_h / 2.0
        vx, vy = width / 2.0, height / 2.0
        dx, dy = vx - cx, vy - cy
        rdx, rdy = _rotate_about(dx, dy, 0.0, 0.0, rotation)
        img_x = vx - rdx - disp_w / 2.0
        img_y = vy - rdy - disp_h / 2.0
    row: dict[str, Any] = {"x": img_x, "y": img_y, "w": disp_w, "h": disp_h}
    if rotation:
        row["rotation"] = rotation
    return row


def plate_placement(
    camera: dict[str, Any],
    plate: dict[str, Any],
    *,
    width: float | None = None,
    height: float | None = None,
) -> dict[str, Any]:
    """Place the shared plate so this camera is full-bleed on its capture canvas.

    `x`/`y` are the unrotated top-left. A non-zero `rotation` is Keynote's CCW
    iWork angle (degrees) so Magic Move can spin the same PNG to a new bearing.
    """
    width = float(width if width is not None else plate.get("width") or WALL_WIDTH)
    height = float(height if height is not None else plate.get("height") or WALL_HEIGHT)
    row = _place_plate_float(camera, plate, width=width, height=height)
    snapped: dict[str, Any] = {
        "x": whole(row["x"]),
        "y": whole(row["y"]),
        "w": whole(row["w"]),
        "h": whole(row["h"]),
    }
    if row.get("rotation"):
        snapped["rotation"] = row["rotation"]
    return snapped


def _rotate_about(px: float, py: float, cx: float, cy: float, degrees: float) -> tuple[float, float]:
    """Rotate (px, py) about (cx, cy) by Keynote's CCW-positive angle."""
    theta = math.radians(float(degrees) or 0.0)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    dx, dy = px - cx, py - cy
    return cx + cos_t * dx - sin_t * dy, cy + sin_t * dx + cos_t * dy


def round_half_away(value: float) -> int:
    """Half away from zero. Shared with dashboard `roundHalfAway`.

    Python `round` is half-to-even and `Math.round` is half-toward-+∞, so 10.5
    and −11.5 would otherwise put the Keynote plate one degree off the movie.
    """
    number = float(value)
    if number >= 0:
        return int(math.floor(number + 0.5))
    return int(math.ceil(number - 0.5))


def quantized_rotation(degrees: float) -> float:
    """Signed integer degrees, or 0. The one angle Keynote can honour.

    Placement, region orbit, visual-origin, and the emitted iWork property must
    all spin by this value — a leftover 0.4° on an 8k plate is tens of pixels.
    """
    snapped = round_half_away(float(degrees) or 0.0)
    return float(snapped) if snapped else 0.0


def effective_plate_bearing(plate_bearing: float, camera_bearing: float) -> float:
    """The bearing Keynote actually shows after integer plate rotation.

    The plate PNG is captured at `plate_bearing`. Placement then rotates by
    `quantized_rotation(signed_bearing_delta(...))`. A movie that takes off
    from (or lands on) that plate must use this snapped bearing — interpolating
    from the authored 10.4° while Keynote holds 10° is a visible jump.
    The result stays on the authored wrap so hop interpolation does not spin.
    """
    delta = signed_bearing_delta(plate_bearing, camera_bearing)
    next_bearing = float(camera_bearing) + quantized_rotation(delta) - delta
    nearest = float(round_half_away(next_bearing))
    return nearest if abs(next_bearing - nearest) < 1e-6 else next_bearing


def _plate_capture_bearing(plate: dict[str, Any]) -> float:
    cam = plate.get("captureCamera") or plate.get("camera") or {}
    return float(cam.get("bearing") or 0)


def movie_endpoint_camera(camera: dict[str, Any], plate: dict[str, Any] | None) -> dict[str, Any]:
    """Copy of `camera` with bearing snapped to the plate Keynote will show."""
    if not plate:
        return dict(camera)
    next_cam = dict(camera)
    next_cam["bearing"] = effective_plate_bearing(
        _plate_capture_bearing(plate),
        float(camera.get("bearing") or 0),
    )
    return next_cam


def keynote_rotation(degrees: float) -> int:
    """iWork `rotation` is an integer in 0–359."""
    return int(quantized_rotation(degrees)) % 360


def visual_origin(x: float, y: float, w: float, h: float, rotation: float) -> tuple[int, int]:
    """AABB top-left after CCW rotation about the unrotated frame centre."""
    rotation = quantized_rotation(rotation)
    if not rotation:
        return whole(x), whole(y)
    cx, cy = x + w / 2.0, y + h / 2.0
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    rot = [_rotate_about(px, py, cx, cy, rotation) for px, py in corners]
    return whole(min(p[0] for p in rot)), whole(min(p[1] for p in rot))


def orbit_item(item: dict[str, Any], origin: dict[str, Any], rotation: float) -> dict[str, Any]:
    """Move `item` so rotating both objects about their own centres keeps them glued."""
    rotation = quantized_rotation(rotation)
    if not rotation:
        return item
    ocx = float(origin["x"]) + float(origin["w"]) / 2.0
    ocy = float(origin["y"]) + float(origin["h"]) / 2.0
    icx = float(item["x"]) + float(item["w"]) / 2.0
    icy = float(item["y"]) + float(item["h"]) / 2.0
    ncx, ncy = _rotate_about(icx, icy, ocx, ocy, rotation)
    next_item = dict(item)
    next_item["x"] = ncx - float(item["w"]) / 2.0
    next_item["y"] = ncy - float(item["h"]) / 2.0
    next_item["rotation"] = rotation
    return next_item


def project_into_plate(
    lat: float,
    lon: float,
    plate: dict[str, Any],
    placement: dict[str, Any],
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
    rotation = quantized_rotation(placement.get("rotation") or 0)
    if rotation:
        cx = float(placement["x"]) + float(placement["w"]) / 2.0
        cy = float(placement["y"]) + float(placement["h"]) / 2.0
        px, py = _rotate_about(px, py, cx, cy, rotation)
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
    """Return {plateId: geom} and links with plateId. Degenerate unions fall back to movie."""
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    plates: dict[str, dict[str, Any]] = {}
    pair_plate: dict[tuple[str, str], str] = {}
    movie_pairs: set[tuple[str, str]] = set()
    for run in morph_runs(slides, links):
        cameras = [(by_id[sid].get("camera") or {}) for sid in run if sid in by_id]
        widths = [float(slide_capture_size(by_id[sid])[0]) for sid in run if sid in by_id]
        geom = morph_plate_geom(cameras, width=width, height=height, widths=widths)
        hops = [(run[index], run[index + 1]) for index in range(len(run) - 1)]
        if geom is None:
            movie_pairs.update(hops)
            continue
        display = 0.0
        for cam, canvas_w in zip(cameras, widths):
            place = _place_plate_float(cam, geom, width=canvas_w, height=height)
            display = max(display, float(place["w"]), float(place["h"]))
        if display > MAX_MORPH_DISPLAY_PX:
            movie_pairs.update(hops)
            continue
        geom = fit_morph_plate(geom)
        # Capture uses ceil(plateW/H); keep placement on those same integer pixels.
        geom = {
            **geom,
            "plateW": float(math.ceil(float(geom["plateW"]))),
            "plateH": float(math.ceil(float(geom["plateH"]))),
        }
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


def _first_plate_slide(slides: list[dict[str, Any]], slide_ids: list[str]) -> dict[str, Any] | None:
    """The plate's own slide, in document order — the baked plate raster must
    agree on which slide's highlights/style/isolate represent the whole group."""
    wanted = set(slide_ids)
    return next((slide for slide in slides if str(slide.get("id") or "") in wanted), None)


def _plate_group_highlights(slides: list[dict[str, Any]], slide_ids: list[str]) -> list[str]:
    """Union of highlight ids on the plate run, document order, first-seen.

    Morph hops already refuse a highlight mismatch, so this matches the first
    slide today. Collecting the group keeps the baked plate's wash list complete
    even if a later slide is the one that authored it.
    """
    wanted = {str(sid) for sid in slide_ids}
    seen: list[str] = []
    for slide in slides:
        if str(slide.get("id") or "") not in wanted:
            continue
        for raw in slide.get("highlights") or []:
            code = str(raw)
            if code and code not in seen:
                seen.append(code)
    return seen


def _plate_group_isolate(slides: list[dict[str, Any]], slide_ids: list[str]) -> Any:
    """First isolate-on in the plate run.

    A morph hop with isolate only on a later slide used to capture the first
    slide's off-state, so the shared PNG (and every Magic Move frame) lost the
    darken mask the preview still shows.
    """
    wanted = {str(sid) for sid in slide_ids}
    for slide in slides:
        if str(slide.get("id") or "") not in wanted:
            continue
        isolate = slide.get("isolate")
        if isolate:
            return isolate
    return None


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
        if not sid:
            continue
        cap_w, cap_h = slide_capture_size(slide)
        if sid not in covered:
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
            if highlights:
                row["stillPngRegions"] = f"{sid}{'_CG' if audience == 'cg' else ''}-regions.json"
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
        first = _first_plate_slide(slides, geom.get("slideIds") or [])
        highlights = _plate_group_highlights(slides, geom.get("slideIds") or [])
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
                "highlights": highlights,
                "hiddenLayers": slide_hidden_layers(first or {}),
                "hillshade": bool((first or {}).get("hillshade")),
                "isolate": _plate_group_isolate(slides, geom.get("slideIds") or []),
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
    """Movie links that land on isolate+highlights from a non-isolated source (plain still, then dissolve)."""
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
        if from_slide.get("isolate"):
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


def _qualifying_movie_takeoff_links(
    slides: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """Movie hops whose source just landed a Magic Move on a shared plate.

    That slide must keep the plate objects (duplicate + adjust) so Keynote can
    interpolate. The fly is moved onto a follow-up takeoff slide.
    """
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    index_of = {str(slide.get("id") or ""): index for index, slide in enumerate(slides)}
    morph_dests: set[str] = set()
    for link in links:
        if str(link.get("kind") or "") != "morph" or not link.get("plateId"):
            continue
        _start, end = _link_ends(link)
        if end:
            morph_dests.add(end)
    out: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for link in links:
        if str(link.get("kind") or "") != "movie":
            continue
        start, end = _link_ends(link)
        from_slide, to_slide = by_id.get(start), by_id.get(end)
        if not from_slide or not to_slide:
            continue
        if start not in morph_dests:
            continue
        if index_of.get(end) != index_of.get(start, -2) + 1:
            continue
        out.append((link, from_slide, to_slide))
    return out


def movie_takeoff_slides(
    slides: list[dict[str, Any]], links: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """After a Magic Move landing, play the outgoing fly on a synthetic takeoff slide."""
    takeoff_after: dict[str, tuple[dict[str, Any], dict[str, Any], str]] = {}
    for link, from_slide, to_slide in _qualifying_movie_takeoff_links(slides, links):
        from_id = str(from_slide.get("id") or "")
        duration = float(link.get("duration") or 0) or 1.0
        takeoff_slide = {
            **from_slide,
            "id": f"{from_id}__takeoff",
            "_takeoffFor": from_id,
            "movieDuration": float(from_slide.get("movieDuration") or duration),
        }
        takeoff_after[from_id] = (takeoff_slide, link, str(to_slide.get("id") or ""))
    if not takeoff_after:
        return slides, links
    next_slides: list[dict[str, Any]] = []
    next_links = list(links)
    for slide in slides:
        next_slides.append(slide)
        takeoff = takeoff_after.get(str(slide.get("id") or ""))
        if takeoff is None:
            continue
        takeoff_slide, link, to_id = takeoff
        next_slides.append(takeoff_slide)
        for index, existing in enumerate(next_links):
            if existing is link:
                next_links[index] = {**link, "from": takeoff_slide["id"]}
                break
        next_links.append(
            {
                "from": str(slide.get("id") or ""),
                "to": takeoff_slide["id"],
                "kind": "cut",
                "duration": 0.0,
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


def _region_manifest_scale(
    mapped_w: float, mapped_h: float, manifest: dict[str, Any]
) -> tuple[float, float]:
    """Per-axis scale from manifest pixels onto the placed map (`mapped_w`×`mapped_h`).

    A width-only scale leaves Y drifting when Keynote's placed aspect is not the PNG's —
    region washes then sit off the plate land they were captured against.
    """
    manifest_w = float(manifest["width"])
    manifest_h = float(manifest["height"])
    scale_x = mapped_w / manifest_w if manifest_w else 1.0
    scale_y = mapped_h / manifest_h if manifest_h else 1.0
    if manifest_w > 0 and manifest_h > 0 and mapped_h > 0 and abs(scale_x - scale_y) > max(1e-6, abs(scale_x) * 0.02):
        warnings.warn(
            f"region manifest aspect ratio mismatch: mapped {mapped_w:g}x{mapped_h:g} vs manifest {manifest_w:g}x{manifest_h:g}"
        )
    return scale_x, scale_y


REGION_MANIFEST_MAX_SIDE = 8192
REGION_MANIFEST_MAX_PIECES = 512


def region_manifest_dims_valid(width: Any, height: Any, *, max_side: int = REGION_MANIFEST_MAX_SIDE) -> bool:
    return (
        isinstance(width, int)
        and not isinstance(width, bool)
        and isinstance(height, int)
        and not isinstance(height, bool)
        and 1 <= width <= max_side
        and 1 <= height <= max_side
    )


def region_piece_is_valid(piece: Any, width: int, height: int) -> bool:
    if not isinstance(piece, dict):
        return False
    x, y, w, h = piece.get("x"), piece.get("y"), piece.get("w"), piece.get("h")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (x, y, w, h)):
        return False
    return w >= 1 and h >= 1 and x >= 0 and y >= 0 and x + w <= width and y + h <= height


def _read_region_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    width, height = data.get("width"), data.get("height")
    if not region_manifest_dims_valid(width, height):
        return None
    pieces = data.get("pieces")
    if not isinstance(pieces, list) or len(pieces) > REGION_MANIFEST_MAX_PIECES:
        pieces = []
    return {
        **data,
        "pieces": [
            {**piece, "index": k}
            for k, piece in enumerate(pieces)
            if region_piece_is_valid(piece, width, height)
        ],
    }


def _still_region_manifest_path(slide: dict[str, Any], output_dir: Path, audience: str = "lw") -> Path:
    sid = str(slide.get("id") or "slide")
    name = Path(f"{sid}{'_CG' if audience == 'cg' else ''}-regions.json").name
    return Path(output_dir) / "stills" / name


def _still_region_manifest(slide: dict[str, Any], output_dir: Path, audience: str = "lw") -> dict[str, Any] | None:
    return _read_region_manifest(_still_region_manifest_path(slide, output_dir, audience))


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


def normalise_credit_line(line: str) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(line)).strip()


CREDITS_WIDTH_FRAC = 0.6
CREDITS_CHAR_WIDTH_FRAC = 0.55
CREDITS_LINE_HEIGHT_FRAC = 1.6


def _wrapped_row_count(text: str, box_w: float, font_size: float) -> int:
    char_w = font_size * CREDITS_CHAR_WIDTH_FRAC
    chars_per_line = max(1, int(box_w / char_w))
    return max(1, math.ceil(len(text) / chars_per_line))


def _centred_box(text: str, max_w: float, font_size: float, centre_x: float) -> tuple[float, float]:
    line_w = min(max_w, len(text) * font_size * CREDITS_CHAR_WIDTH_FRAC)
    return centre_x - line_w / 2.0, line_w


def credits_op(lines: list[str], *, width: int, height: int) -> dict[str, Any]:
    """One text item per line (no `\\n`): `_as_escape` doesn't handle literal newlines,
    which would otherwise break `osacompile`. Keynote's `rich text`/`text item` classes
    have no `alignment` property, so each line's own box is centred by its estimated
    width instead of relying on AppleScript alignment. Box width is deck-relative so it
    fits LW, DSK, and CG canvases alike; each item's height is estimated from wrapped
    row count so the block centres correctly even when a line wraps."""
    clean_lines = [normalise_credit_line(line) for line in lines]
    clean_lines = [line for line in clean_lines if line]
    max_w = width * CREDITS_WIDTH_FRAC
    centre_x = width / 2.0
    line_height = CREDITS_FONT * CREDITS_LINE_HEIGHT_FRAC
    title_line_height = CREDITS_TITLE_FONT * CREDITS_LINE_HEIGHT_FRAC
    title_h = _wrapped_row_count(CREDITS_TITLE, max_w, CREDITS_TITLE_FONT) * title_line_height
    row_heights = [title_h]
    for line in clean_lines:
        row_heights.append(_wrapped_row_count(line, max_w, CREDITS_FONT) * line_height)
    block_h = sum(row_heights)
    y0 = (height - block_h) / 2.0
    title_x, title_w = _centred_box(CREDITS_TITLE, max_w, CREDITS_TITLE_FONT, centre_x)
    items = [
        _item(
            "text", title_x, y0, title_w, row_heights[0],
            text=CREDITS_TITLE, fontSize=CREDITS_TITLE_FONT, bold=True,
        )
    ]
    y = y0 + row_heights[0]
    for line, h in zip(clean_lines, row_heights[1:]):
        line_x, line_w = _centred_box(line, max_w, CREDITS_FONT, centre_x)
        items.append(_item("text", line_x, y, line_w, h, text=line, fontSize=CREDITS_FONT))
        y += h
    return {"id": "_credits", "duplicate": False, "transition": None, "items": items}


def _pin_size(church: dict[str, Any], movie: Path | None) -> int:
    kind = str(church.get("kind") or "dot")
    if kind == "dropPin" and movie is not None:
        return DROP_SIZE
    if kind == "dropPin":
        return min(PIN_MAX_PT, DROP_SIZE)
    if kind == "landmark":
        return _default_object_size(kind, church)
    return min(PIN_MAX_PT, DOT_SIZE)


def _default_object_size(kind: str, church: dict[str, Any] | None = None) -> int:
    """Mirrors `defaultObjectSize` in dashboard/src/maps/objects.ts; landmarks are
    authored at `default_landmark_size(assetWidth)`, so that is their label baseline."""
    if kind == "dropPin":
        return DROP_SIZE
    if kind == "landmark":
        return default_landmark_size(int((church or {}).get("assetWidth") or 0))
    return DOT_SIZE


def _label_scale(church: dict[str, Any], size: float) -> float:
    """`size` is the zoom-scaled marker size, so the clamp bounds the total scale."""
    base = _default_object_size(str(church.get("kind") or "dot"), church)
    scale = size / base if base else 1.0
    return min(LABEL_SCALE_MAX, max(LABEL_SCALE_MIN, scale))


EFFECTIVE_SIZE_MAX = 20000


def _effective_size(church: dict[str, Any], zoom: float, movie: Path | None) -> float:
    size = float(church.get("size") or _pin_size(church, movie))
    size_zoom = church.get("sizeZoom")
    if church.get("scaleWithMap") and size_zoom is not None:
        size = size * 2 ** (zoom - float(size_zoom))
    return min(EFFECTIVE_SIZE_MAX, size)


def _marker_on_canvas_or_plate(
    cx: float,
    cy: float,
    size: float,
    capture_w: float,
    *,
    plate: dict[str, Any] | None,
    placement: dict[str, Any] | None,
) -> bool:
    """Keep markers that sit on the LW frame *or* on the overflowing plate.

    Magic Move needs the same pin on every slide of a run — a zoomed-in landing
    still has to carry the overview pins so they can fly off-canvas. The tight
    LW cull dropped those, and a rotate-about-centre used to orbit in-view pins
    off the frame entirely.
    """
    margin = max(float(size), 64.0)
    xs = [0.0, float(capture_w)]
    ys = [0.0, float(WALL_HEIGHT)]
    if plate is not None and placement is not None:
        px, py = float(placement["x"]), float(placement["y"])
        pw, ph = float(placement["w"]), float(placement["h"])
        rot = quantized_rotation(placement.get("rotation") or 0)
        if rot:
            vx, vy = visual_origin(px, py, pw, ph, rot)
            theta = math.radians(rot)
            aw = abs(pw * math.cos(theta)) + abs(ph * math.sin(theta))
            ah = abs(pw * math.sin(theta)) + abs(ph * math.cos(theta))
            xs += [vx, vx + aw]
            ys += [vy, vy + ah]
        else:
            xs += [px, px + pw]
            ys += [py, py + ph]
    return min(xs) - margin <= cx <= max(xs) + margin and min(ys) - margin <= cy <= max(ys) + margin


def _place_churches(
    churches: list[dict[str, Any]],
    *,
    plate: dict[str, Any] | None,
    placement: dict[str, Any] | None,
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
            rotation = quantized_rotation(placement.get("rotation") or 0)
            if rotation:
                copy_dx, copy_dy = _rotate_about(copy_dx, copy_dy, 0.0, 0.0, rotation)
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
        if kind == "landmark":
            with Image.open(landmark) as probe:
                landmark_h = size * probe.height / max(1, probe.width)
        copy_span = max(1.0, math.hypot(copy_dx, copy_dy))
        copy_count = math.ceil((capture_w + WALL_HEIGHT) / copy_span) + 2
        for copy_index in range(-copy_count, copy_count + 1):
            cx = base_x + copy_index * copy_dx
            cy = base_y + copy_index * copy_dy
            if not _marker_on_canvas_or_plate(
                cx, cy, size, capture_w, plate=plate, placement=placement
            ):
                continue
            x = cx + origin_x - size / 2.0
            drop_h = whole(size * PIN_ASPECT)
            if kind == "landmark":
                y = cy - landmark_h
            elif static_drop:
                y = whole(cy) - drop_h
            else:
                y = cy - size / 2.0
            if wall:
                x = avoid_straddle(x, size)
            if kind == "landmark":
                height = landmark_h
                opacity = float(church.get("opacity") if church.get("opacity") is not None else 1)
                church_id = str(church.get("id") or "")
                reveal_mov = reveals.get((reveal_audience, sid, church_id)) if allow_reveal and reveals else None
                if opacity < 1:
                    faded = asset_root / f"{asset_id}-{int(opacity * 1000)}.png"
                    if not faded.exists():
                        with Image.open(landmark) as image:
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
            if name and church.get("showLabel", True) is True:
                scale = _label_scale(church, size)
                font = whole(LABEL_FONT_PT * scale)
                nh = whole(NAME_HEIGHT * scale)
                nh += nh % 2
                nw = whole(max(48 * scale, min(420 * scale, LABEL_CHAR_W * scale * len(name))))
                nw += nw % 2
                # Even pads keep pill and text sharing one centre after `dsk_item` halves both.
                pad_x = whole(PILL_PAD_X * scale)
                pad_x += pad_x % 2
                pad_y = whole(PILL_PAD_Y * scale)
                pad_y += pad_y % 2
                pw = nw + 2 * pad_x
                ph = nh + 2 * pad_y
                top = y if kind in ("dropPin", "landmark") else cy - size / 2.0
                # Even origins as well as even extents: `dsk_item` halves each box on its own,
                # and an odd coordinate would round the pill and its text apart.
                nx = whole(x + size / 2.0 - nw / 2.0)
                nx -= nx % 2
                ny = whole(top - LABEL_GAP * scale) - nh - pad_y
                ny -= ny % 2
                if wall:
                    px = nx - pad_x
                    nx += avoid_straddle(px, pw) - px
                items.append(
                    _item(
                        "image",
                        nx - pad_x,
                        ny - pad_y,
                        pw,
                        ph,
                        path=str(ensure_label_pill_png(pin_root, _label_pill_rgb(church), pw, ph)),
                        labelPill=True,
                    )
                )
                items.append(_item("text", nx, ny, nw, nh, text=name, bold=True, fontSize=font))
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
        extra = {"rotation": geom["rotation"]} if geom.get("rotation") else {}
        return _item("image", geom["x"] + ox, geom["y"], geom["w"], geom["h"], path=str(plate_path), map=True, **extra), geom
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
    region_manifest: dict[str, Any] | None = None,
    allow_reveal: bool = True,
    reveals: dict[tuple[str, str, str], str] | None = None,
    reveal_audience: str = "lw",
    sid: str = "",
    skip_landmarks: bool = False,
    cutout_highlights: list[str] | None = None,
) -> list[dict[str, Any]]:
    """`pin_root` is required (see `_place_churches`); pass `output_dir / "pins"`.

    `cutout_highlights` gates the country-cutout item when set: for a morph plate
    member it should be the plate's own highlights (the group's first slide), so
    every member of the group shows what the plate raster was rendered with. Falls
    back to `slide`'s own highlights when omitted.
    """
    mapped, placement = _map_item(
        slide, plate=plate, plate_path=plate_path, still=still, bg_movie=bg_movie, dest_slide=dest_slide
    )
    items = [mapped]
    cutout_gate = slide.get("highlights") if cutout_highlights is None else cutout_highlights
    # Morph plates already bake country/admin-1 washes into the shared PNG.
    # Stacking translucent cutouts here lets Keynote recomposite ~55% alpha and
    # orbit each piece independently of the plate — both of which miss the live map.
    if plate is None and region_manifest is not None and mapped.get("kind") == "image" and cutout_gate:
        base_path = Path(mapped["path"])
        scale_x, scale_y = _region_manifest_scale(float(mapped["w"]), float(mapped["h"]), region_manifest)
        for piece in region_manifest.get("pieces") or []:
            k = piece["index"]
            png = base_path.with_name(f"{base_path.stem}-region-{k}{base_path.suffix}")
            if not png.is_file():
                warnings.warn(f"missing region cutout {png}")
                continue
            items.append(
                _item(
                    "image",
                    mapped["x"] + piece["x"] * scale_x,
                    mapped["y"] + piece["y"] * scale_y,
                    piece["w"] * scale_x,
                    piece["h"] * scale_y,
                    path=str(png),
                    country=True,
                )
            )
        rot = quantized_rotation(mapped.get("rotation") or 0)
        if rot:
            items[:] = [orbit_item(item, mapped, rot) if item.get("country") else item for item in items]
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
    slides, links = movie_takeoff_slides(slides, links)
    by_id = {str(slide.get("id") or ""): slide for slide in slides}
    slide_plate: dict[str, str] = {}
    plate_highlights: dict[str, list[str]] = {}
    for plate_id, geom in plates.items():
        ids = [str(sid) for sid in (geom.get("slideIds") or [])]
        for sid in ids:
            slide_plate[sid] = plate_id
        plate_highlights[plate_id] = _plate_group_highlights(slides, ids)
    ops: list[dict[str, Any]] = []
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
            movie_sid = str(slide.get("_takeoffFor") or sid)
            candidate = movie_path(output_dir, movie_sid, asset_audience)
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
        region_manifest = None
        if bg_movie is None and plate_id is None:
            region_manifest = _still_region_manifest(slide, output_dir, asset_audience)
            if slide.get("highlights") and region_manifest is None:
                warnings.warn(f"missing region manifest for slide {sid} (expected -regions.json)")
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
            region_manifest=region_manifest,
            allow_reveal=not duplicate,
            reveals=reveals,
            reveal_audience="cg" if item_slide.get("_splitCg") else "lw",
            sid=cg_key,
            skip_landmarks=reveal_bg,
            cutout_highlights=plate_highlights.get(plate_id) if plate_id else None,
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


def _emit_image_layout(item: dict[str, Any], target: str) -> list[str]:
    """Width/height/position, plus rotation when Magic Move must spin the plate."""
    x, y, w, h = item["x"], item["y"], item["w"], item["h"]
    rot = quantized_rotation(item.get("rotation") or 0)
    kn = keynote_rotation(rot) if rot else 0
    if kn:
        x, y = visual_origin(x, y, w, h, rot)
        return [
            f"        set width of {target} to {w}",
            f"        set height of {target} to {h}",
            f"        set rotation of {target} to {kn}",
            f"        set position of {target} to {{{x}, {y}}}",
        ]
    # Size first. Keynote scales about the centre when width/height change, so a
    # position set against the PNG's intrinsic 8192px would slide off the LW
    # frame once the plate is displayed at Magic Move overflow size.
    return [
        f"        set width of {target} to {w}",
        f"        set height of {target} to {h}",
        f"        set position of {target} to {{{x}, {y}}}",
    ]


def _emit_adjust_map(item: dict[str, Any], cutouts: list[dict[str, Any]] | None = None) -> list[str]:
    lines = ["        try", *("          " + line.strip() for line in _emit_image_layout(item, "image 1")), "        end try"]
    for i, cutout in enumerate(cutouts or [], start=2):
        layout = _emit_image_layout(cutout, f"image {i}")
        lines += ["        try", *("          " + line.strip() for line in layout), "        end try"]
    last = len(cutouts or []) + 2
    lines += [
        "        try",
        f"          repeat with i from (count of images) to {last} by -1",
        "            delete image i",
        "          end repeat",
        "        end try",
    ]
    lines += [
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
    return lines


def _emit_item(item: dict[str, Any]) -> list[str]:
    kind = item["kind"]
    x, y, w, h = item["x"], item["y"], item["w"], item["h"]
    if kind == "image":
        path = _as_escape(item["path"])
        # Keynote 15 honours the {file:…} initializer; {file name:…} silently no-ops.
        return [
            f'        set imgFile to (POSIX file "{path}") as alias',
            "        set img to make new image with properties {file:imgFile}",
            *_emit_image_layout(item, "img"),
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
    font_size = whole(item.get("fontSize") or 24)
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
        cutouts = [item for item in items if item.get("country")]
        if mapped:
            lines += _emit_adjust_map(mapped, cutouts)
        overlays = [item for item in items if item is not mapped and item not in cutouts]
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
            region_manifest = _still_region_manifest(item_slide, output_dir, audience)
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
            manifest_path = _still_region_manifest_path(item_slide, output_dir, audience)
            pieces = []
            if region_manifest is not None:
                pscale_x, pscale_y = _region_manifest_scale(float(cap_w), float(cap_h), region_manifest)
                for piece in region_manifest.get("pieces") or []:
                    k = piece["index"]
                    piece_png = still.with_name(f"{still.stem}-region-{k}{still.suffix}")
                    pieces.append(
                        (
                            piece_png,
                            round(piece["x"] * pscale_x),
                            round(piece["y"] * pscale_y),
                            round(piece["w"] * pscale_x),
                            round(piece["h"] * pscale_y),
                        )
                    )
            piece_paths = [piece_path for piece_path, *_ in pieces]
            fingerprint = reveal_movie_fingerprint(still, landmarks, manifest_path, piece_paths)
            if reveal_stale(movie_dest, fingerprint):
                _raise_if_cancelled(is_cancelled)
                log(f"Rendering reveal slide movie for {sid}…")
                render_slide_reveal_movie(
                    still,
                    pieces,
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
    export_path: Path | None = None,
    credits: list[str] | None = None,
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
    credit_lines = (
        [cleaned for x in (credits or []) if (cleaned := normalise_credit_line(x))]
        if str(result.get("attribution") or "credits") != "stamp"
        else []
    )
    movie = find_pin_drop_wave()
    stem = str(result.get("stem") or getattr(job, "name", "") or f"maps-{getattr(job, 'id', 'maps')}")
    flags: list[Any] = []
    flags_cg: list[Any] = []
    poster_frame: list[dict[str, Any]] = []
    movie_autoplay: list[dict[str, Any]] = []
    if export_path is not None:
        export_dir = Path(export_path).parent
    if export_dir is not None:
        export_dir = ensure_export_dir(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
    dest_lw, dest_cg, dest_dsk = maps_export_dests(
        export_lw=export_lw,
        export_cg=export_cg,
        export_dsk=export_dsk,
        output_dir=output_dir,
        stem=stem,
        export_dir=export_dir,
        export_path=export_path,
    )
    if export_lw:
        dest = dest_lw
        if dest is None:
            raise ValueError("LED wall export path is missing")
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
        _log(job, f"Exporting wall deck {dest.name} (7680×1080)…")
        ops = plan_deck(
            slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=True,
            reveals=reveals, reveal_movies=reveal_movies,
        )
        if credit_lines:
            ops.append(credits_op(credit_lines, width=WALL_WIDTH, height=WALL_HEIGHT))
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
        if dest_dsk is None:
            raise ValueError("DSK export path is missing")
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
        _log(job, f"Exporting DSK deck {dest_dsk.name} (1920×1080)…")
        ops_dsk = dsk_ops(
            plan_deck(
                slides, links, plates, output_dir=output_dir, preview_dir=preview_dir, movie=movie, wall=True,
                reveals=reveals, reveal_movies=reveal_movies,
            )
        )
        if credit_lines:
            ops_dsk.append(credits_op(credit_lines, width=DSK_WIDTH, height=DSK_HEIGHT))
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
        if dest_cg is None:
            raise ValueError("CG export path is missing")
        if export_dir is not None:
            export_dir = ensure_export_dir(export_dir)
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
        if credit_lines:
            ops_cg.append(credits_op(credit_lines, width=CG_WIDTH, height=CG_HEIGHT))
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
