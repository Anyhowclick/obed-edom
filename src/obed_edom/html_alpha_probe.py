"""P2 alpha/timing feasibility helpers (offline except documented live hooks).

Inventory, click grouping, opacity-source tracing, index.html patches, alpha
statistics, composites, and ProRes encode/decode. Browser capture lives in
``scripts/p2_alpha_spike.py``. Must not import ``web.*``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from obed_edom import keynote_app
from obed_edom.dsk_live import keynote_running, layout_alpha_safe
from obed_edom.dsk_stage_export import StageCountAmbiguous, stage_counts, validate_alpha
from obed_edom.html_preview import (
    EXPORT_CONTRACT_MAJOR,
    EXPORT_CONTRACT_MINOR,
    PLAYER_JS,
    PreviewStructureError,
    export_payload_identity,
    file_sha256,
    header_slide_list,
    load_header,
    player_hash,
    read_jsonish,
    source_slides,
    tree_bytes,
    validate_export_contract,
)
from obed_edom.iwa_builds import _build_effect_animtype, _ref_id, _transition_effect_duration, deck_builds
from obed_edom.iwa_runs import _load_deck
from obed_edom.maps_movie import ffmpeg_exe

PROBE_VERSION = 4
FPS = 30
# Numeric comparison tolerances — declared before any fixture is compared (plan §5 / P2.1).
CLOCK_WINDOW_S = 0.5
CLOCK_MIN_RAF = 10  # historical idle-request bar; not a freeze proof
HEARTBEAT_MIN_EXECUTED = 1
REPEAT_PROGRESS_MAE_MAX = 0.02
REPEAT_TIMESTAMP_ERR_MAX_S = 1 / FPS
EMPTY_ALPHA_MAX = 2
OPAQUE_ALPHA_MIN = 250
MIN_TRANSPARENT_FRAC = 0.05
HALO_RGB_ON_ZERO_ALPHA_MAX = 8
DECODED_ALPHA_MAE_MAX = 3.0
BLACK_CONTENT_ALPHA_MIN = 250
# Painted identity: leftover plates are near-duplicates; own raster must win.
IDENTITY_NEAR_DUP_MAE_MAX = 3.0
IDENTITY_OWN_CLOSER_MARGIN = 2.0
IDENTITY_CONTENT_MIN = 0.02
IDENTITY_RASTER_USEFUL_MAX = 20.0
# Visible-content gate: a pixel is live when it moves across a settle burst (plan §1.3).
LIVE_DELTA_MIN = 12
LIVE_BAND_COLS = 16
LIVE_BAND_ROWS = 8
LIVE_BAND_MIN_FRAC = 0.05
LIVE_RECT_MIN_FRAC = 0.35
LIVE_RECT_INSET_PX = 2
# A rect the plan expects to be FROZEN (a boundary the plan refuses to carry, or a
# geometry-static Magic Move under the raw player) may keep only this much live.
DEAD_RECT_MAX_LIVE_FRAC = 0.05
STRAY_DILATE_PX = 6
STRAY_MIN_AREA_PX = 2000
NOISE_FLOOR_P99_MAX = 6
# In-page GL liveness oracle: thresholds frozen from the research harness (plan §4.2).
INPAGE_BAND_MARGIN = 1.0
INPAGE_CONTROL_RANGE_MAX = 1.0
INPAGE_GREEN_STATIC_MAX = 1.0
INPAGE_GREEN_CHANNEL_MARGIN = 30
INPAGE_MIN_SAMPLES = 24
INPAGE_BAND_COUNT = LIVE_BAND_COLS * LIVE_BAND_ROWS
INPAGE_OCCLUDED_BANDS_MAX_FRAC = 0.5
INPAGE_MARKER_DELTA_MAX = 0.5
PLAYER_RAF_ASSIGN = "window.requestAnimFrame=window.requestAnimationFrame"
LINEDRAW = "com.apple.iWork.Keynote.LineDraw"
LINEDRAW_FOR_LINE = "com.apple.iWork.Keynote.LineDrawForLine"


def current_slide_query_url(page_url: str, exported_1based: int) -> str:
    """Player query: 1-based exported slide index → starting scene. Do not add #scene."""
    base = page_url.split("#")[0]
    base = base.split("?")[0]
    return f"{base}?currentSlide={int(exported_1based)}"


def scene_from_hash(live_hash: str) -> int | None:
    token = str(live_hash or "").lstrip("#")
    if token.isdigit():
        return int(token)
    return None


def assign_starting_scenes(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scene = 0
    for slide in slides:
        n_events = int(slide.get("eventCount") or 0)
        slide["startingScene"] = scene
        slide["currentSlide"] = int(slide["playerIndex"]) + 1
        scene += max(n_events, 1)
    return slides



_INDEX_MAIN_JS = re.compile(
    r'<script\s+src="assets/player/main\.js"\s*>\s*</script>',
    re.IGNORECASE,
)
_BODY_BG = re.compile(r'(<body\b[^>]*\s)bgcolor="black"', re.IGNORECASE)

# Synthetic black-content fixture: a colour-key of near-black must fail this region.
BLACK_SQUARE = (slice(500, 700), slice(500, 700))
WHITE_BAR = (slice(200, 400), slice(200, 800))


class ProbeStructureError(PreviewStructureError):
    """Exported HTML/player structure is not the measured P2 contract."""


@dataclass(frozen=True)
class FileIdentity:
    path: str
    sha256: str
    mtime: float
    mtime_iso: str
    inode: int
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "mtime": self.mtime,
            "mtimeIso": self.mtime_iso,
            "inode": self.inode,
            "size": self.size,
        }


def file_identity(path: Path) -> FileIdentity:
    path = Path(path)
    st = path.stat()
    return FileIdentity(
        path=str(path),
        sha256=file_sha256(path) if path.is_file() else _tree_sha256(path),
        mtime=st.st_mtime,
        mtime_iso=datetime.fromtimestamp(st.st_mtime).isoformat(sep=" ", timespec="seconds"),
        inode=st.st_ino,
        size=st.st_size if path.is_file() else _dir_size(path),
    )


def _dir_size(path: Path) -> int:
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file() and not child.is_symlink())


def _tree_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink()):
        hasher.update(child.relative_to(path).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(file_sha256(child).encode())
        hasher.update(b"\n")
    return hasher.hexdigest()


def identities_match(before: FileIdentity, after: FileIdentity) -> bool:
    return (
        before.sha256 == after.sha256
        and before.mtime == after.mtime
        and before.inode == after.inode
        and before.size == after.size
    )


def keynote_document_count() -> int | None:
    """Document count for an already-running Keynote. Does not launch Keynote.

    ``tell application id`` would launch the app if it is not running, so this
    returns ``None`` unless ``keynote_running()`` is already true.
    """
    if not keynote_running():
        return None
    bundle = keynote_app.bundle_id()
    script = "\n".join(
        [
            f'using terms from application id "{bundle}"',
            f'tell application id "{bundle}"',
            "  return count of documents",
            "end tell",
            "end using terms from",
        ]
    )
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text.isdigit():
        raise RuntimeError(f"could not read Keynote document count: {(proc.stderr or text).strip()}")
    return int(text)


def flatten_effect_names(node: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        name = node.get("name")
        kind = node.get("type")
        if name or kind:
            out.append(
                {
                    "type": kind,
                    "name": name,
                    "duration": node.get("duration"),
                    "beginTime": node.get("beginTime"),
                    "objectID": node.get("objectID"),
                }
            )
        for child in node.get("effects") or []:
            out.extend(flatten_effect_names(child))
    elif isinstance(node, list):
        for child in node:
            out.extend(flatten_effect_names(child))
    return out


def kpf_operator_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Click-sized KPF events: skip trailing/pure transition events.

    LineDraw + nested LineDrawForLine + dissolve live in one event on Alpha_DSK
    slide 3 — one operator click, not three.
    """
    clicks: list[dict[str, Any]] = []
    for index, event in enumerate(payload.get("events") or []):
        if not isinstance(event, dict):
            continue
        effects = event.get("effects") or []
        names = flatten_effect_names(effects)
        if names and all(item.get("type") == "transition" for item in names):
            continue
        if not names:
            continue
        clicks.append(
            {
                "eventIndex": index,
                "automaticPlay": bool(event.get("automaticPlay")),
                "effects": names,
            }
        )
    return clicks


def merge_linedraw_companions(groups: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """LineDraw + LineDrawForLine is one operator click even if split across chunks."""
    merged: list[list[dict[str, Any]]] = []
    for group in groups:
        if (
            merged
            and merged[-1]
            and group
            and merged[-1][0].get("effect") == LINEDRAW
            and group[0].get("effect") == LINEDRAW_FOR_LINE
        ):
            merged[-1].extend(group)
            continue
        merged.append(list(group))
    return merged


def iwa_click_groups(objects: dict[str, Any], slide: dict[str, Any]) -> dict[str, Any]:
    """Referent/automatic buildChunks → operator click groups.

    A referent chunk with ``automatic=False`` starts a click. Subsequent chunks
    (including referent+automatic companions such as LineDrawForLine) attach to
    that click. A referent+automatic chunk with no current click is on-show
    (after transition), not an operator click.
    """
    clicks: list[list[dict[str, Any]]] = []
    automatic_on_show: list[dict[str, Any]] = []
    current: list[dict[str, Any]] | None = None
    unresolved = 0
    for ref in slide.get("buildChunks") or []:
        chunk = objects.get(_ref_id(ref) or "")
        if chunk is None or chunk.get("_pbtype") != "KN.BuildChunkArchive":
            unresolved += 1
            continue
        build = objects.get(_ref_id(chunk.get("build")) or "")
        effect, animation_type = _build_effect_animtype(build) if build else (None, None)
        item = {
            "effect": effect,
            "animationType": animation_type,
            "referent": bool(chunk.get("referent")),
            "automatic": bool(chunk.get("automatic")),
            "delay": chunk.get("delay"),
        }
        if item["referent"] and not item["automatic"]:
            current = [item]
            clicks.append(current)
            continue
        if current is not None:
            current.append(item)
            continue
        if item["referent"] and item["automatic"]:
            automatic_on_show.append(item)
    clicks = merge_linedraw_companions(clicks)
    return {
        "operatorClicks": clicks,
        "automaticOnShow": automatic_on_show,
        "unresolvedChunks": unresolved,
        "operatorClickCount": len(clicks),
        "settledStateCount": 1 + len(clicks),
    }


def is_magic_move(transition: tuple[Any, Any] | None) -> bool:
    if not transition:
        return False
    effect = str(transition[0] or "")
    return "magic-move" in effect.lower()


def is_character_effect(name: str | None) -> bool:
    return bool(name) and "character" in str(name).lower()


def is_build_out(animation_type: Any) -> bool:
    return str(animation_type or "").lower() in {"out", "buildout", "build-out"}


def pdf_page_inventory(pdf_path: Path) -> list[dict[str, Any]]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(reader.pages):
        box = page.mediabox
        resources = page.get("/Resources")
        xobjects = 0
        smask = 0
        if resources is not None:
            xobj = resources.get("/XObject")
            if xobj is not None:
                xobj = xobj.get_object()
                for _name, ref in xobj.items():
                    obj = ref.get_object()
                    xobjects += 1
                    if obj.get("/SMask"):
                        smask += 1
        pages.append(
            {
                "index": index,
                "width": float(box.width),
                "height": float(box.height),
                "hasTransparencyGroup": page.get("/Group") is not None,
                "xobjects": xobjects,
                "smaskCount": smask,
            }
        )
    return pages


def render_pdf_page_rgba(pdf_path: Path, page_index: int) -> np.ndarray | None:
    """Rasterise one PDF page with a transparent Quartz context. ``None`` if Quartz fails."""
    try:
        from Foundation import NSURL
        from Quartz import (
            CGBitmapContextCreate,
            CGBitmapContextCreateImage,
            CGColorSpaceCreateDeviceRGB,
            CGContextConcatCTM,
            CGContextDrawPDFPage,
            CGPDFDocumentCreateWithURL,
            CGPDFDocumentGetPage,
            CGPDFPageGetBoxRect,
            CGPDFPageGetDrawingTransform,
            kCGBitmapByteOrder32Big,
            kCGImageAlphaPremultipliedLast,
            kCGPDFCropBox,
        )
    except Exception:
        return None
    url = NSURL.fileURLWithPath_(str(Path(pdf_path).resolve()))
    doc = CGPDFDocumentCreateWithURL(url)
    if doc is None:
        return None
    page = CGPDFDocumentGetPage(doc, page_index + 1)
    if page is None:
        return None
    box = CGPDFPageGetBoxRect(page, kCGPDFCropBox)
    width = max(1, int(round(box.size.width)))
    height = max(1, int(round(box.size.height)))
    colorspace = CGColorSpaceCreateDeviceRGB()
    ctx = CGBitmapContextCreate(
        None,
        width,
        height,
        8,
        width * 4,
        colorspace,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big,
    )
    if ctx is None:
        return None
    transform = CGPDFPageGetDrawingTransform(page, kCGPDFCropBox, box, 0, True)
    CGContextConcatCTM(ctx, transform)
    CGContextDrawPDFPage(ctx, page)
    image = CGBitmapContextCreateImage(ctx)
    if image is None:
        return None
    try:
        from Quartz import CGDataProviderCopyData, CGImageGetDataProvider

        data = bytes(CGDataProviderCopyData(CGImageGetDataProvider(image)))
    except Exception:
        return None
    expected = height * width * 4
    if len(data) < expected:
        return None
    arr = np.frombuffer(data[:expected], dtype=np.uint8).reshape((height, width, 4)).copy()
    # Quartz bitmaps are bottom-up.
    return np.ascontiguousarray(arr[::-1])


def _css_background_sources(index_html: str, player_js: str) -> list[dict[str, Any]]:
    sources = []
    if "bgcolor=\"black\"" in index_html.lower() or "bgcolor='black'" in index_html.lower():
        sources.append(
            {
                "origin": "html",
                "detail": "index.html body bgcolor=black",
                "safeToClear": True,
                "reason": "player chrome, not authored artwork",
            }
        )
    compact = player_js.replace(" ", "")
    if "body{background-color:black}" in compact:
        sources.append(
            {
                "origin": "css",
                "detail": "main.js body{background-color:black} (max-device-width media query)",
                "safeToClear": True,
                "reason": "player chrome",
            }
        )
    if PLAYER_RAF_ASSIGN not in player_js:
        sources.append(
            {
                "origin": "player",
                "detail": "requestAnimFrame assignment missing",
                "safeToClear": False,
                "reason": "player structure does not match the 2026-09-12 contract",
            }
        )
    return sources


def opacity_trace(
    export_root: Path,
    *,
    uuid: str,
    payload: dict[str, Any],
    index_html: str,
    player_js: str,
) -> dict[str, Any]:
    """Where opaque pixels can come from. Never recommends colour-keying."""
    sources = _css_background_sources(index_html, player_js)
    sources.append(
        {
            "origin": "webgl",
            "detail": "main.js clearColor(0,0,0,0) on measured shader paths",
            "safeToClear": True,
            "reason": "already a transparent clear; not a black fill",
        }
    )
    full_page_textures = 0
    pdf_pages: list[dict[str, Any]] = []
    slide_dir = export_root / "assets" / uuid
    for asset in (payload.get("assets") or {}).values():
        if not isinstance(asset, dict):
            continue
        if asset.get("type") == "texture" and float(asset.get("width") or 0) >= 1920 and float(asset.get("height") or 0) >= 1080:
            full_page_textures += 1
        url = ((asset.get("url") or {}) if isinstance(asset.get("url"), dict) else {}).get("native")
        if isinstance(url, str) and url.endswith(".pdf"):
            pdf = slide_dir / url
            if pdf.is_file() and not pdf_pages:
                pdf_pages = pdf_page_inventory(pdf)
    empty_full_pages = [
        page
        for page in pdf_pages
        if page["width"] >= 1920 and page["height"] >= 1080 and page["xobjects"] == 0
    ]
    if empty_full_pages:
        sources.append(
            {
                "origin": "pdf",
                "detail": f"{len(empty_full_pages)} full-canvas PDF page(s) with no XObjects",
                "safeToClear": False,
                "reason": "may be an empty plate or a flattened fill; distinguish by raster alpha, do not colour-key",
            }
        )
    if any(page["smaskCount"] > 0 for page in pdf_pages):
        sources.append(
            {
                "origin": "pdf",
                "detail": "PDF image XObjects carry /SMask (soft-mask alpha)",
                "safeToClear": True,
                "reason": "authored artwork already has a real alpha channel in the texture PDF",
            }
        )
    return {
        "sources": sources,
        "fullPageTextures": full_page_textures,
        "pdfPages": pdf_pages,
        "safeBackgroundDistinction": bool(pdf_pages) and (not empty_full_pages or any(page["smaskCount"] > 0 for page in pdf_pages)),
    }


def make_black_content_fixture(size: tuple[int, int] = (1920, 1080)) -> np.ndarray:
    """Transparent plate + white bar + opaque black square + semitransparent grey.

    A 'remove black' colour-key must destroy the square and fail ``black_content_ok``.
    """
    width, height = size
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[WHITE_BAR] = (255, 255, 255, 255)
    arr[BLACK_SQUARE] = (0, 0, 0, 255)
    arr[800:900, 200:400] = (128, 128, 128, 128)
    return arr


def color_key_near_black(arr: np.ndarray, thresh: int = 8) -> np.ndarray:
    """Blanket near-black removal — the default we must not use."""
    out = arr.copy()
    luma = out[:, :, :3].max(axis=2)
    out[luma <= thresh, 3] = 0
    return out


def black_content_ok(arr: np.ndarray, region: tuple[slice, slice] = BLACK_SQUARE) -> bool:
    patch = arr[region]
    if patch.size == 0:
        return False
    return bool(patch[:, :, 3].min() >= BLACK_CONTENT_ALPHA_MIN and patch[:, :, :3].max() <= 5)


def premultiply_halo(arr: np.ndarray) -> dict[str, float | bool]:
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]
    zero = alpha == 0
    leftover = int(rgb[zero].max()) if zero.any() else 0
    near = (alpha > 0) & (alpha <= 16)
    edge_rgb = float(rgb[near].mean()) if near.any() else 0.0
    return {
        "rgbMaxOnZeroAlpha": leftover,
        "meanRgbOnNearTransparent": edge_rgb,
        "haloOk": leftover <= HALO_RGB_ON_ZERO_ALPHA_MAX,
    }


def empty_and_opaque_samples(arr: np.ndarray, content_rects: Sequence[dict[str, float]]) -> dict[str, Any]:
    height, width = arr.shape[:2]
    corners = [(0, 0), (0, width - 1), (height - 1, 0), (height - 1, width - 1)]
    mid_edges = [(0, width // 2), (height - 1, width // 2), (height // 2, 0), (height // 2, width - 1)]
    empty_pts = corners + mid_edges
    empty_ok = all(int(arr[y, x, 3]) <= EMPTY_ALPHA_MAX for y, x in empty_pts)
    opaque_pts: list[tuple[int, int]] = []
    for rect in content_rects:
        x = int(rect.get("x", 0) + rect.get("width", 0) / 2)
        y = int(rect.get("y", 0) + rect.get("height", 0) / 2)
        if 0 <= x < width and 0 <= y < height:
            opaque_pts.append((y, x))
    if not opaque_pts:
        ys, xs = np.where(arr[:, :, 3] >= OPAQUE_ALPHA_MIN)
        if len(ys):
            opaque_pts.append((int(ys[len(ys) // 2]), int(xs[len(xs) // 2])))
    opaque_ok = bool(opaque_pts) and all(int(arr[y, x, 3]) >= OPAQUE_ALPHA_MIN for y, x in opaque_pts)
    return {
        "emptyPoints": empty_pts,
        "opaquePoints": opaque_pts,
        "emptyBackgroundOk": empty_ok,
        "opaqueContentOk": opaque_ok,
        "emptyAlphas": [int(arr[y, x, 3]) for y, x in empty_pts],
        "opaqueAlphas": [int(arr[y, x, 3]) for y, x in opaque_pts],
    }


def accessibility_rects(payload: dict[str, Any]) -> list[dict[str, float]]:
    rects: list[dict[str, float]] = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        for item in event.get("accessibility") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            if text.lower().endswith((".tiff", ".jpg", ".jpeg", ".png", ".mov", ".mp4")):
                continue
            rect = item.get("targetRectangle") or {}
            if rect:
                rects.append({k: float(rect[k]) for k in ("x", "y", "width", "height") if k in rect})
    return rects


def analyze_rgba(arr: np.ndarray, *, content_rects: Sequence[dict[str, float]] | None = None) -> dict[str, Any]:
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"expected HxWx4 RGBA, got {arr.shape}")
    alpha = arr[:, :, 3]
    transparent_frac = float((alpha <= EMPTY_ALPHA_MAX).mean())
    content_frac = float((alpha > EMPTY_ALPHA_MAX).mean())
    samples = empty_and_opaque_samples(arr, content_rects or [])
    halo = premultiply_halo(arr)
    near_black = (arr[:, :, :3].max(axis=2) <= 8) & (alpha >= OPAQUE_ALPHA_MIN)
    black_content_frac = float(near_black.mean())
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    try:
        Image.fromarray(arr, "RGBA").save(tmp.name)
        try:
            stage_ok, bg_alpha_max, content_alpha_frac, stage_transparent = validate_alpha(
                Path(tmp.name), expected_size=(arr.shape[1], arr.shape[0])
            )
        except ValueError as exc:
            stage_ok, bg_alpha_max, content_alpha_frac, stage_transparent = False, -1, 0.0, 0.0
            stage_error = str(exc)
        else:
            stage_error = None
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    alpha_min = int(alpha.min())
    verdict = (
        samples["emptyBackgroundOk"]
        and samples["opaqueContentOk"]
        and transparent_frac >= MIN_TRANSPARENT_FRAC
        and content_frac > 0
        and bool(halo["haloOk"])
        and not (alpha_min == 0 and transparent_frac < MIN_TRANSPARENT_FRAC)
    )
    return {
        "width": int(arr.shape[1]),
        "height": int(arr.shape[0]),
        "alphaMin": alpha_min,
        "alphaMax": int(alpha.max()),
        "transparentFrac": transparent_frac,
        "contentFrac": content_frac,
        "blackContentFrac": black_content_frac,
        "blackContentPresent": black_content_frac > 0,
        "stageValidateAlpha": {
            "alphaOk": stage_ok,
            "bgAlphaMax": bg_alpha_max,
            "contentAlphaFrac": content_alpha_frac,
            "transparentFrac": stage_transparent,
            "error": stage_error,
        },
        "halo": halo,
        "samples": samples,
        "pass": verdict,
        "failReasons": _fail_reasons(samples, transparent_frac, content_frac, halo, alpha_min),
    }


def _fail_reasons(
    samples: dict[str, Any],
    transparent_frac: float,
    content_frac: float,
    halo: dict[str, Any],
    alpha_min: int,
) -> list[str]:
    reasons: list[str] = []
    if not samples["emptyBackgroundOk"]:
        reasons.append("empty-background samples are not transparent")
    if not samples["opaqueContentOk"]:
        reasons.append("known content samples are not opaque")
    if transparent_frac < MIN_TRANSPARENT_FRAC:
        reasons.append(f"transparent_frac {transparent_frac:.4f} < {MIN_TRANSPARENT_FRAC}")
    if content_frac <= 0:
        reasons.append("no opaque content")
    if not halo["haloOk"]:
        reasons.append(f"premultiplication halo rgbMaxOnZeroAlpha={halo['rgbMaxOnZeroAlpha']}")
    if alpha_min == 0 and transparent_frac < MIN_TRANSPARENT_FRAC:
        reasons.append("alpha_min==0 only (one transparent pixel is not evidence)")
    return reasons


def save_png(arr: np.ndarray, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA").save(path)
    return path


def load_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.array(img.convert("RGBA"))


def checkerboard(height: int, width: int, cell: int = 32) -> np.ndarray:
    yy, xx = np.indices((height, width))
    mask = ((yy // cell) + (xx // cell)) % 2
    out = np.empty((height, width, 3), dtype=np.uint8)
    out[mask == 0] = (255, 0, 64)
    out[mask == 1] = (0, 220, 180)
    return out


def composite_over(arr: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Straight-alpha composite. ``background`` is HxWx3."""
    alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
    rgb = arr[:, :, :3].astype(np.float32)
    bg = background.astype(np.float32)
    blended = rgb * alpha + bg * (1.0 - alpha)
    out = np.empty_like(arr)
    out[:, :, :3] = blended.clip(0, 255).astype(np.uint8)
    out[:, :, 3] = 255
    return out


def write_composites(arr: np.ndarray, dest_dir: Path, stem: str) -> dict[str, str]:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    height, width = arr.shape[:2]
    return {
        "raw": str(save_png(arr, dest_dir / f"{stem}.raw.png")),
        "overBlack": str(save_png(composite_over(arr, np.zeros((height, width, 3), np.uint8)), dest_dir / f"{stem}.over-black.png")),
        "overWhite": str(save_png(composite_over(arr, np.full((height, width, 3), 255, np.uint8)), dest_dir / f"{stem}.over-white.png")),
        "overChecker": str(save_png(composite_over(arr, checkerboard(height, width)), dest_dir / f"{stem}.over-checker.png")),
    }


def encode_prores_4444(frames: Sequence[np.ndarray], dest: Path, *, fps: int = FPS) -> Path:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    if not frames:
        raise ValueError("no frames to encode")
    height, width = frames[0].shape[:2]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    cmd = [
        exe, "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "prores_ks",
        "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le",
        "-vendor", "apl0",
        "-movflags", "+faststart",
        "-an", str(tmp),
    ]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        assert proc.stdin is not None
        try:
            for frame in frames:
                if frame.shape != (height, width, 4):
                    raise ValueError(f"frame shape {frame.shape} != {(height, width, 4)}")
                proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            proc.stdin.close()
            proc.wait()
        finally:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        if proc.returncode != 0:
            stderr.seek(0)
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"ProRes encode failed: {stderr.read().decode('utf-8', 'replace')[-2000:]}")
    tmp.rename(dest)
    return dest


def decode_prores_rgba(movie: Path, dest_dir: Path) -> list[Path]:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    dest_dir = Path(dest_dir)
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True)
    proc = subprocess.run(
        [exe, "-y", "-i", str(movie), "-pix_fmt", "rgba", str(dest_dir / "frame-%04d.png")],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ProRes decode failed: {(proc.stderr or '')[-2000:]}")
    return sorted(dest_dir.glob("frame-*.png"))


def source_has_genuine_alpha(frames: Sequence[np.ndarray]) -> bool:
    """Opaque (alpha 255 everywhere) frames cannot prove transparent video."""
    if not frames:
        return False
    mixed = False
    any_transparent = False
    any_opaque_content = False
    for frame in frames:
        alpha = frame[:, :, 3]
        amin = int(alpha.min())
        amax = int(alpha.max())
        if amin < OPAQUE_ALPHA_MIN:
            any_transparent = True
        if amax >= OPAQUE_ALPHA_MIN:
            any_opaque_content = True
        if amin < OPAQUE_ALPHA_MIN < amax or (amin <= EMPTY_ALPHA_MAX and amax >= OPAQUE_ALPHA_MIN):
            mixed = True
    return mixed or (any_transparent and any_opaque_content)


def decoded_alpha_report(src_frames: Sequence[np.ndarray], decoded: Sequence[Path]) -> dict[str, Any]:
    genuine = source_has_genuine_alpha(src_frames)
    if len(src_frames) != len(decoded):
        return {
            "pass": False,
            "reason": f"frame count {len(decoded)} != source {len(src_frames)}",
            "declaredMaeMax": DECODED_ALPHA_MAE_MAX,
            "sourceHasGenuineAlpha": genuine,
        }
    maes: list[float] = []
    frame_reports: list[dict[str, Any]] = []
    for index, (src, path) in enumerate(zip(src_frames, decoded, strict=True)):
        dec = load_rgba(path)
        if dec.shape != src.shape:
            return {
                "pass": False,
                "reason": f"decoded shape {dec.shape} != {src.shape}",
                "declaredMaeMax": DECODED_ALPHA_MAE_MAX,
                "sourceHasGenuineAlpha": genuine,
            }
        mae = float(np.mean(np.abs(dec[:, :, 3].astype(np.int16) - src[:, :, 3].astype(np.int16))))
        maes.append(mae)
        frame_reports.append({"index": index, "alphaMae": mae, "analysis": analyze_rgba(dec)})
    max_mae = max(maes) if maes else 999.0
    return {
        "pass": genuine and max_mae <= DECODED_ALPHA_MAE_MAX,
        "reason": None if genuine else "source frames are opaque; MAE against opaque plates is not a transparent-video pass",
        "sourceHasGenuineAlpha": genuine,
        "maxAlphaMae": max_mae,
        "meanAlphaMae": float(sum(maes) / len(maes)) if maes else None,
        "declaredMaeMax": DECODED_ALPHA_MAE_MAX,
        "frames": frame_reports,
    }



def page_websocket_url(targets: Sequence[dict[str, Any]]) -> str | None:
    """Pick a page-target debugger URL. The browser target from /json/version has no Runtime/Page."""
    pages = [
        item
        for item in targets
        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
        and "devtools://" not in str(item.get("url") or "")
    ]
    if not pages:
        return None
    for item in pages:
        url = str(item.get("url") or "")
        if url.startswith("http://") or url.startswith("https://") or url == "about:blank":
            return str(item["webSocketDebuggerUrl"])
    return str(pages[0]["webSocketDebuggerUrl"])


def progress_metric(arr: np.ndarray) -> float:
    """Non-black coverage. Alpha-only progress is vacuous on a flattened opaque plate."""
    rgb = arr[:, :, :3].astype(np.int16)
    return float((rgb.max(axis=2) > 8).mean())


def score_playback_continuity(
    times: Sequence[float | None],
    *,
    click_i: int = 0,
    capture_offsets: Sequence[float | None] | None = None,
    presented_times: Sequence[float | None] | None = None,
    dissolve_s: float = 1.5,
    playback_rate: float = 1.0,
    min_advance_ratio: float = 0.35,
    position_eps: float = 0.75,
    restart_eps: float = 0.35,
    jump_eps: float = 0.85,
    freeze_eps: float = 0.02,
    min_advancing_pairs: int = 3,
    rate_slack_s: float = 0.35,
) -> dict[str, Any]:
    """Score across-transition media continuity.

    A frozen clock (identical timestamps) must fail even when the first
    post-click position matches the pre-click position. Prefer presented-frame
    media times when provided; otherwise fall back to ``currentTime`` samples.
    Capture offsets are wall/capture clock and must not be treated as media time.

    ``continuesThroughDissolve`` requires position continuity, media progress
    consistent with elapsed capture time, no restart, and no jump — a later
    seek discontinuity must fail even if overall advance looks healthy.
    """
    clock_source = list(times)
    if presented_times is not None and any(t is not None for t in presented_times):
        clock_source = list(presented_times)
    clock = clock_source
    if len(clock) != len(times):
        clock = list(times)

    caps: list[float | None] | None = None
    if capture_offsets is not None and len(capture_offsets) == len(clock):
        caps = [None if c is None else float(c) for c in capture_offsets]

    advancing = 0
    freeze_runs = 0
    restarts = 0
    jumps = 0
    gaps = 0
    rate_inconsistent = 0
    last: float | None = None
    last_cap: float | None = None
    for i, t in enumerate(clock):
        if t is None:
            if i >= click_i:
                gaps += 1
            continue
        cap_i = caps[i] if caps is not None else None
        if last is not None:
            dt = float(t) - float(last)
            if dt > freeze_eps:
                advancing += 1
            elif abs(dt) <= freeze_eps:
                freeze_runs += 1
            if i >= click_i:
                if dt < -restart_eps:
                    restarts += 1
                if (
                    cap_i is not None
                    and last_cap is not None
                    and (cap_i - last_cap) > 0.02
                ):
                    expected = (cap_i - last_cap) * float(playback_rate)
                    # Media ran far ahead of (or behind) elapsed capture between samples.
                    if dt - expected > max(jump_eps, rate_slack_s):
                        rate_inconsistent += 1
                    if expected - dt > max(dissolve_s, 1.0) and dt < -restart_eps:
                        rate_inconsistent += 1
                elif dt > jump_eps:
                    # No usable capture delta — treat large media steps as jumps.
                    jumps += 1
        last = float(t)
        last_cap = cap_i

    pre = next((t for t in clock[: click_i + 1] if t is not None), None)
    post = next((t for t in reversed(clock) if t is not None), None)
    first_after = next((t for t in clock[click_i + 1 :] if t is not None), None)
    remount = (
        pre is not None
        and first_after is not None
        and (float(first_after) < restart_eps or float(first_after) + restart_eps < float(pre))
    )
    n_through = max(1, int(round(dissolve_s * 20)))
    through = clock[click_i : click_i + n_through]
    present = [float(t) for t in through if t is not None]
    dissolve_advance = float(present[-1] - present[0]) if len(present) >= 2 else 0.0

    elapsed_capture = None
    if caps is not None:
        through_caps = [c for c in caps[click_i : click_i + n_through] if c is not None]
        if len(through_caps) >= 2:
            elapsed_capture = float(through_caps[-1] - through_caps[0])
        else:
            all_caps = [c for c in caps[click_i:] if c is not None]
            if len(all_caps) >= 2:
                elapsed_capture = float(all_caps[-1] - all_caps[0])

    min_advance = float(min_advance_ratio) * float(dissolve_s) * float(playback_rate)
    media_progressing = dissolve_advance >= min_advance and advancing >= min_advancing_pairs
    frozen_clock = (
        len(present) >= 2
        and abs(dissolve_advance) <= freeze_eps
        and advancing == 0
    )
    position_continuous = (
        pre is not None
        and first_after is not None
        and not remount
    )
    if position_continuous:
        media_dt = abs(float(first_after) - float(pre))
        # When capture offsets exist, allow media to advance with wall time during a
        # slow transition (Magic Move) instead of requiring a <0.75s media step.
        first_after_i = next(
            (i for i, t in enumerate(clock) if i > click_i and t is not None),
            None,
        )
        cap_pre = caps[click_i] if caps is not None and click_i < len(caps) else None
        cap_after = (
            caps[first_after_i]
            if caps is not None and first_after_i is not None and first_after_i < len(caps)
            else None
        )
        if cap_pre is not None and cap_after is not None:
            wall_dt = abs(float(cap_after) - float(cap_pre))
            position_continuous = abs(media_dt - wall_dt) <= max(position_eps, rate_slack_s) or media_dt < position_eps
        else:
            position_continuous = media_dt < position_eps

    # Whole-window media advance must not exceed capture elapsed by a jump margin.
    elapsed_consistent = True
    if elapsed_capture is not None and elapsed_capture > 0.2 and len(present) >= 2:
        expected_window = elapsed_capture * float(playback_rate)
        if dissolve_advance > expected_window + max(jump_eps, rate_slack_s):
            elapsed_consistent = False
        if dissolve_advance < expected_window * min_advance_ratio - rate_slack_s:
            elapsed_consistent = False

    no_restart = restarts == 0 and not remount
    no_jump = jumps == 0 and rate_inconsistent == 0
    # Sustained presence: majority of dissolve samples must have a media clock.
    presence_ok = len(present) >= max(3, n_through // 3)

    continues = bool(
        position_continuous
        and media_progressing
        and not frozen_clock
        and no_restart
        and no_jump
        and elapsed_consistent
        and presence_ok
    )
    return {
        "times": list(times),
        "presentedTimes": list(presented_times) if presented_times is not None else None,
        "captureOffsets": list(capture_offsets) if capture_offsets is not None else None,
        "advancingPairs": advancing,
        "nearFreezePairs": freeze_runs,
        "restartsAfterClick": restarts,
        "jumpsAfterClick": jumps,
        "rateInconsistentPairs": rate_inconsistent,
        "gapSamplesAfterClick": gaps,
        "preTime": pre,
        "firstAfterClick": first_after,
        "postTime": post,
        "remountRestart": remount,
        "hardRestartVsPre": remount
        or (pre is not None and post is not None and float(post) + restart_eps < float(pre)),
        "positionContinuous": position_continuous,
        "dissolveAdvanceS": dissolve_advance,
        "elapsedCaptureS": elapsed_capture,
        "minAdvanceS": min_advance,
        "mediaProgressing": media_progressing,
        "elapsedConsistent": elapsed_consistent,
        "presenceOk": presence_ok,
        "frozenClock": frozen_clock,
        "presentDuringDissolve": len(present),
        "continuesThroughDissolve": continues,
        "noRestart": no_restart,
        "noJump": no_jump,
    }


def _longest_still_run(pairs: Sequence[float], identical_eps: float) -> int:
    longest = 0
    current = 0
    for m in pairs:
        current = current + 1 if m < identical_eps else 0
        longest = max(longest, current)
    return longest


def score_visible_movie_motion(
    frames: Sequence[np.ndarray],
    *,
    pair_eps: float = 2.0,
    identical_eps: float = 0.01,
    min_changing_frac: float = 0.45,
    max_still_run: int | None = None,
) -> dict[str, Any]:
    """Require sustained composed-frame motion — one mid-window cut is not enough.

    ``frames`` are already-cropped movie ROI patches (RGB or RGBA). A sequence
    that is still except for a single change halfway through must fail even when
    first→last MAE is large. Empty or mismatched crops are hard rejects — they
    must not count as motion via infinite MAE. ``max_still_run``, when given,
    additionally rejects a mid-window stall longer than that many still pairs.
    """
    if len(frames) < 3:
        return {"ok": False, "reason": "need >=3 frames", "n": len(frames)}

    shapes = [tuple(getattr(f, "shape", ())) for f in frames]
    empty_i = [
        i
        for i, (f, s) in enumerate(zip(frames, shapes, strict=True))
        if f.size == 0 or len(s) < 2 or s[0] == 0 or s[1] == 0
    ]
    if empty_i:
        return {
            "ok": False,
            "reason": "empty crop",
            "n": len(frames),
            "emptyIndices": empty_i[:8],
            "shapes": list(shapes)[:8],
        }
    if len(set(shapes)) != 1:
        return {
            "ok": False,
            "reason": "mismatched crop shapes",
            "n": len(frames),
            "shapes": list(shapes)[:8],
        }

    def _mae(a: np.ndarray, b: np.ndarray) -> float:
        return float(
            np.mean(np.abs(a[:, :, :3].astype(np.float64) - b[:, :, :3].astype(np.float64)))
        )

    pair = [_mae(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    if any(not np.isfinite(m) for m in pair):
        return {
            "ok": False,
            "reason": "non-finite pair mae",
            "n": len(frames),
            "pairMae": pair[:12],
        }
    first_last = _mae(frames[0], frames[-1])
    identical_pairs = sum(1 for m in pair if m < identical_eps)
    changing_pairs = sum(1 for m in pair if m >= pair_eps)
    n_pair = len(pair)
    changing_frac = changing_pairs / max(1, n_pair)
    half = max(1, n_pair // 2)
    early_max = max(pair[:half]) if pair else 0.0
    late_max = max(pair[half:]) if pair else 0.0
    max_still_run_actual = _longest_still_run(pair, identical_eps)
    ok = bool(
        changing_frac >= min_changing_frac
        and early_max >= pair_eps
        and late_max >= pair_eps
        and first_last >= pair_eps
        and np.isfinite(first_last)
        and (max_still_run is None or max_still_run_actual <= max_still_run)
    )
    return {
        "ok": ok,
        "n": len(frames),
        "firstLastMae": first_last,
        "maxPairMae": max(pair) if pair else 0.0,
        "identicalPairs": identical_pairs,
        "identicalPairFrac": identical_pairs / max(1, n_pair),
        "changingPairs": changing_pairs,
        "changingPairFrac": changing_frac,
        "earlyMaxPairMae": early_max,
        "lateMaxPairMae": late_max,
        "minChangingFrac": min_changing_frac,
        "pairEps": pair_eps,
        "maxStillRun": max_still_run_actual,
        "shape": list(shapes[0]),
    }


def score_motion_across_flip(
    samples: Sequence[dict[str, Any]],
    *,
    start_hash: object,
    pair_eps: float = 2.0,
    identical_eps: float = 0.01,
    max_still_run: int = 4,
    expected_key: object | None = None,
) -> dict[str, Any]:
    """Tie visible movie motion to the actual scene-hash flip instant.

    ``samples`` are ``{roi, sceneHash, captureOffsetS, decoderId?, w?, movieKey?}``
    in capture order. A continuously-playing movie that satisfies pre-navigation
    motion plus a late navigation must not pass: motion is required before,
    across, and after ``flipIndex`` (the first sample whose scene hash differs
    from ``start_hash``), with no mid-window stall longer than ``max_still_run``
    and a decoded movie present in the flip neighbourhood. The crossing frames
    must also share one stable ``decoderId`` — a switch to a different decoder
    at the flip is not the target movie progressing. When ``expected_key`` is
    given, identity is bound across the whole window the gate relies on, not
    just the crossing: every sampled frame's ``movieKey`` must match it, and
    every post-flip frame must share one non-null ``decoderId`` — a same-key
    handoff or restart later in the after-window must not pass either.
    """
    n = len(samples)
    if n < 3:
        return {"ok": False, "reason": "need >=3 samples", "n": n}

    rois = [s["roi"] for s in samples]
    shapes = [tuple(getattr(r, "shape", ())) for r in rois]
    empty_i = [
        i
        for i, (r, s) in enumerate(zip(rois, shapes, strict=True))
        if r.size == 0 or len(s) < 2 or s[0] == 0 or s[1] == 0
    ]
    if empty_i:
        return {
            "ok": False,
            "reason": "empty crop",
            "n": n,
            "emptyIndices": empty_i[:8],
            "shapes": list(shapes)[:8],
        }
    if len(set(shapes)) != 1:
        return {
            "ok": False,
            "reason": "mismatched crop shapes",
            "n": n,
            "shapes": list(shapes)[:8],
        }

    def _mae(a: np.ndarray, b: np.ndarray) -> float:
        return float(
            np.mean(np.abs(a[:, :, :3].astype(np.float64) - b[:, :, :3].astype(np.float64)))
        )

    pair = [_mae(rois[i], rois[i + 1]) for i in range(n - 1)]
    if any(not np.isfinite(m) for m in pair):
        return {"ok": False, "reason": "non-finite pair mae", "n": n, "pairMae": pair[:12]}

    def _hash_num(h: object) -> int | None:
        token = str(h or "").lstrip("#").split("?")[0]
        return int(token) if token.isdigit() else None

    start_norm = _hash_num(start_hash)
    normalized = [_hash_num(s.get("sceneHash")) for s in samples]
    flip_index = next((i for i, h in enumerate(normalized) if h != start_norm), None)
    if flip_index is None:
        return {"ok": False, "reason": "no flip observed", "n": n}
    if flip_index < 1:
        return {"ok": False, "reason": "flip at first sample", "n": n, "flipIndex": flip_index}
    if flip_index > n - 2:
        return {"ok": False, "reason": "no post-flip frame", "n": n, "flipIndex": flip_index}

    f = flip_index
    n_pair = len(pair)
    before = pair[: max(0, f - 1)]
    crossing = pair[f - 1]
    after = pair[f:n_pair]
    before_ok = any(m >= pair_eps for m in before)
    across_ok = crossing >= pair_eps
    after_ok = any(m >= pair_eps for m in after)
    max_still_run_actual = _longest_still_run(pair, identical_eps)
    still_ok = max_still_run_actual <= max_still_run

    crossing_decoded = bool(
        (samples[f - 1].get("w") or 0) > 0 and (samples[f].get("w") or 0) > 0
    )
    crossing_decoder_ids = [samples[f - 1].get("decoderId"), samples[f].get("decoderId")]
    crossing_decoder_stable = bool(
        crossing_decoder_ids[0] is not None
        and crossing_decoder_ids[1] is not None
        and crossing_decoder_ids[0] == crossing_decoder_ids[1]
    )
    flip_neighbourhood = [i for i in (f - 1, f, f + 1) if 0 <= i < n]
    decoder_ids_across_flip = [samples[i].get("decoderId") for i in flip_neighbourhood]

    crossing_movie_keys = [samples[f - 1].get("movieKey"), samples[f].get("movieKey")]
    crossing_key_ok = bool(
        expected_key is None
        or (crossing_movie_keys[0] == expected_key and crossing_movie_keys[1] == expected_key)
    )

    after_frame_indices = list(range(f, n))
    after_decoder_ids = [samples[i].get("decoderId") for i in after_frame_indices]
    after_decoder_stable = bool(
        after_decoder_ids
        and after_decoder_ids[0] is not None
        and all(d == after_decoder_ids[0] for d in after_decoder_ids)
    )
    window_key_ok = bool(
        expected_key is None or all(s.get("movieKey") == expected_key for s in samples)
    )
    identity_ok = expected_key is None or (window_key_ok and after_decoder_stable)

    ok = bool(
        before_ok
        and across_ok
        and after_ok
        and crossing_decoded
        and crossing_decoder_stable
        and crossing_key_ok
        and identity_ok
        and still_ok
    )
    reason = None
    if not ok:
        if not before_ok:
            reason = "no motion before flip"
        elif not across_ok:
            reason = "frozen crossing"
        elif not after_ok:
            reason = "no motion after flip"
        elif not crossing_decoded:
            reason = "crossing frame not decoded"
        elif not crossing_decoder_stable:
            reason = "crossing decoder switched"
        elif not crossing_key_ok:
            reason = "crossing movie key mismatch"
        elif not window_key_ok:
            reason = "movie key mismatch in window"
        elif not after_decoder_stable:
            reason = "after-flip decoder switched"
        else:
            reason = "still run exceeds max across flip"

    first_last = _mae(rois[0], rois[-1])
    return {
        "ok": ok,
        "reason": reason,
        "n": n,
        "flipIndex": flip_index,
        "beforeOk": before_ok,
        "acrossOk": across_ok,
        "afterOk": after_ok,
        "maxStillRun": max_still_run_actual,
        "crossingPairMae": crossing,
        "crossingDecoded": crossing_decoded,
        "crossingDecoderStable": crossing_decoder_stable,
        "crossingDecoderIds": crossing_decoder_ids,
        "crossingKeyOk": crossing_key_ok,
        "crossingMovieKeys": crossing_movie_keys,
        "afterDecoderStable": after_decoder_stable,
        "afterDecoderIds": after_decoder_ids,
        "windowKeyOk": window_key_ok,
        "decoderIdsAcrossFlip": decoder_ids_across_flip,
        "firstLastMae": first_last,
        "maxPairMae": max(pair) if pair else 0.0,
        "pairEps": pair_eps,
        "beforePairMae": before,
        "afterPairMae": after,
    }


def _index_run_gaps(indices: Sequence[int | None], modulo: int) -> list[int | None]:
    return [
        None if a is None or b is None else (b - a) % modulo
        for a, b in zip(indices, indices[1:])
    ]


def _frozen_runs(frozen: Sequence[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, still in enumerate(frozen):
        if still:
            start = i if start is None else start
        elif start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(frozen) - 1))
    return runs


def footprint_at(
    progress: float,
    src_rect: Sequence[float],
    dst_rect: Sequence[float],
) -> tuple[float, float, float, float]:
    """Linearly interpolate a movie footprint (x, y, w, h) across a moving cut.

    ``progress`` is clamped to [0, 1]. When ``src_rect == dst_rect`` (a static
    boundary) it returns that constant rect, so a caller can wire this uniformly
    for both static (1->2) and translating+scaling (3->4) magic moves.
    """
    p = max(0.0, min(1.0, float(progress)))
    s = tuple(float(v) for v in src_rect)
    d = tuple(float(v) for v in dst_rect)
    return (
        s[0] + (d[0] - s[0]) * p,
        s[1] + (d[1] - s[1]) * p,
        s[2] + (d[2] - s[2]) * p,
        s[3] + (d[3] - s[3]) * p,
    )


# Top-edge guard (screen px) for a MEASURED footprint's index-patch ROI: the y
# mapping carries no inset, so a fractional rect can put the ROI's first row on
# the movie's antialiased top edge and the patch decodes None. Calibration in
# the freeze-control 3->4 plan §10 (PR #187).
INDEX_PATCH_TOP_GUARD_PX = 2


def index_patch_roi_for(
    footprint: Sequence[float] | dict[str, Any],
    *,
    top_guard: int = 0,
) -> tuple[int, int, int, int]:
    """Map a movie footprint (x, y, w, h) to its burnt-in frame-index patch ROI.

    Generalises the fixed slide-1/2 mapping (the disposable movie's counter patch
    is the top-left 120x48 of its 1920x540 source) to an arbitrary footprint, with
    the same insets that keep the ROI inside the flat-neutral patch and off the
    high-contrast grating. ``index_patch_roi_for((109, 795, 952, 268))`` reproduces
    the adversarial probe's ``INDEX_PATCH_ROI`` exactly (back-compat). Also accepts
    a measured footprint dict (``{x, y, w, h, ...}``, e.g. a live
    ``getBoundingClientRect()`` reading); extra keys are ignored.

    ``top_guard`` drops that many rows off the TOP without moving the bottom edge,
    so the result is ALWAYS a subset of the unguarded ROI: the guard is clamped to
    ``height - 1``, so even a tiny footprint keeps at least one row and never grows
    downwards. Callers decoding a measured (fractional, badge-quantised) rect pass
    ``INDEX_PATCH_TOP_GUARD_PX``; the default 0 leaves every static caller's ROI
    byte-identical.
    """
    if isinstance(footprint, dict):
        x, y, w, h = (float(footprint[k]) for k in ("x", "y", "w", "h"))
    else:
        x, y, w, h = (float(v) for v in footprint)
    height = max(1, round(h * 48 / 540) - 10)
    guard = min(max(0, int(top_guard)), height - 1)
    return (
        int(round(x)) + 2,
        int(round(y)) + guard,
        max(1, round(w * 120 / 1920) - 18),
        height - guard,
    )


def score_index_progression(
    indices: Sequence[int | None],
    *,
    modulo: int = 256,
    min_decodable: int = 6,
    min_decodable_frac: float = 0.5,
    min_distinct: int = 6,
    max_stall_run: int = 2,
    max_forward_step: int = 30,
) -> dict[str, Any]:
    """Parity-immune "the composited output kept advancing" corroboration.

    ``indices`` are the burnt-in frame-index patch decodes (a flat gray counter,
    ``None`` when the patch is occluded/unsettled/mislocated) in capture order.
    Unlike a pixel-MAE motion check, this cannot be fooled by a two-state grating
    whose inter-capture parity aliases visible motion to ~0 (the 2->3 restart
    flake's root cause): the burnt-in counter increments every presented frame
    regardless of grating phase. PASSES only when the counter genuinely marches
    forward — enough decodable samples both in count (``min_decodable``) and as a
    fraction of the window (``min_decodable_frac``, so a run that advances briefly
    then loses its ROI for the rest of the window fails, Codex flake-review F1),
    enough distinct values, no stall run longer than ``max_stall_run`` consecutive
    equal decodes, some net forward progress, and every step a PLAUSIBLE forward
    increment ``0 < d <= max_forward_step`` (a larger modular delta is a reset /
    occlusion / wraparound-misread, not real single-capture progress — Codex F3;
    genuine mod wraparound stays a small positive step and passes).

    Fail-closed on a non-flat/occluded ROI (decodes to None -> coverage fails).
    NOT source-bound: it trusts that ``indices`` were decoded at the target
    movie's own patch ROI. For a fixed fixture whose ROI lies on the target movie
    that holds; binding the counter to the decoder's own media time is a Step-2
    concern (Codex flake-review F2).
    """
    n = len(indices)
    decodable = [v for v in indices if v is not None]
    base = {
        "n": n,
        "nDecodable": len(decodable),
        "nDistinct": len(set(decodable)),
        "decodableFrac": (len(decodable) / n) if n else 0.0,
        "firstIndex": decodable[0] if decodable else None,
        "lastIndex": decodable[-1] if decodable else None,
    }
    if len(decodable) < min_decodable:
        return {"ok": False, "reason": "insufficient decodable samples", **base}
    if base["decodableFrac"] < min_decodable_frac:
        return {"ok": False, "reason": "sparse decodable coverage", **base}

    deltas = [(b - a) % modulo for a, b in zip(decodable, decodable[1:])]
    implausible = any(d > max_forward_step for d in deltas)
    longest_stall = 0
    run = 0
    for d in deltas:
        run = run + 1 if d == 0 else 0
        longest_stall = max(longest_stall, run)
    total_forward = sum(d for d in deltas if 0 < d <= max_forward_step)

    ok = bool(
        not implausible
        and base["nDistinct"] >= min_distinct
        and longest_stall <= max_stall_run
        and total_forward > 0
    )
    reason = None
    if not ok:
        if implausible:
            reason = "implausible index jump (reset/occlusion)"
        elif base["nDistinct"] < min_distinct:
            reason = "too few distinct indices"
        elif longest_stall > max_stall_run:
            reason = "stall run too long"
        else:
            reason = "no forward progress"
    return {
        "ok": ok,
        "reason": reason,
        "longestStallRun": longest_stall,
        "totalForward": total_forward,
        "implausibleStep": implausible,
        **base,
    }


def score_composited_index_run(
    samples: Sequence[dict[str, Any]],
    *,
    flip_index: int,
    max_freeze_run: int = 2,
    modulo: int = 256,
) -> dict[str, Any]:
    """Score a decoded burnt-in frame-index run for a freeze/restart at the cut.

    ``samples`` are composited-frame decodes in capture order, each
    ``{index: int|None, sceneHash: str|None, captureOffsetS: float}``.
    A poster freeze at the cut shows as decoded index not advancing even
    though the decoder's own clock keeps ticking; wraparound (mod
    ``modulo``) is normal forward progress, a drop beyond half the modulo is
    a restart/poster-swap and fails closed.
    """
    n = len(samples)
    indices = [s.get("index") for s in samples]
    decodable = sum(1 for v in indices if v is not None)
    empty = {
        "flipIndex": flip_index,
        "n": n,
        "freezeRunAtCut": None,
        "freezeRunBaseline": None,
        "totalProgressBefore": None,
        "totalProgressAfter": None,
        "firstIndex": indices[0] if indices else None,
        "lastIndex": indices[-1] if indices else None,
        "negativeAnomaly": False,
    }
    if decodable < 4:
        return {"ok": False, "reason": "insufficient decodable samples", **empty}

    window = range(max(0, flip_index - 1), min(n - 1, flip_index + 3) + 1)
    if any(indices[i] is None for i in window):
        return {"ok": False, "reason": "undecodable in flip window", **empty}

    deltas = _index_run_gaps(indices, modulo)
    negative_anomaly = any(d is not None and d > modulo / 2 for d in deltas)

    frozen = [d == 0 for d in deltas]
    runs = _frozen_runs(frozen)
    at_cut = [
        end - start + 1
        for start, end in runs
        if not (end + 1 < window.start or start > window.stop - 1)
    ]
    baseline = [
        end - start + 1
        for start, end in runs
        if end + 1 < window.start or start > window.stop - 1
    ]
    freeze_run_at_cut = max(at_cut, default=0)
    freeze_run_baseline = max(baseline, default=0)

    before_pairs = deltas[: max(0, flip_index - 1)]
    after_pairs = deltas[flip_index:]
    total_before = sum(d for d in before_pairs if d is not None)
    total_after = sum(d for d in after_pairs if d is not None)

    ok = bool(
        not negative_anomaly
        and freeze_run_at_cut <= max_freeze_run
        and total_before > 0
        and total_after > 0
    )
    reason = None
    if not ok:
        if negative_anomaly:
            reason = "negative delta anomaly"
        elif freeze_run_at_cut > max_freeze_run:
            reason = "freeze run at cut"
        elif total_before <= 0:
            reason = "no forward progress before flip"
        else:
            reason = "no forward progress after flip"

    return {
        "ok": ok,
        "reason": reason,
        "flipIndex": flip_index,
        "n": n,
        "freezeRunAtCut": freeze_run_at_cut,
        "freezeRunBaseline": freeze_run_baseline,
        "totalProgressBefore": total_before,
        "totalProgressAfter": total_after,
        "firstIndex": indices[0],
        "lastIndex": indices[-1],
        "negativeAnomaly": negative_anomaly,
    }


def _max_delta_map(frames: Sequence[np.ndarray]) -> np.ndarray:
    """Per-pixel max-minus-min across a burst, maximised over RGB. HxW int16."""
    if len(frames) < 2:
        raise ValueError(f"need >=2 frames, got {len(frames)}")
    shapes = {tuple(getattr(f, "shape", ())) for f in frames}
    if len(shapes) != 1:
        raise ValueError(f"mismatched frame shapes: {sorted(shapes)}")
    shape = next(iter(shapes))
    if len(shape) != 3 or shape[2] not in (3, 4) or shape[0] == 0 or shape[1] == 0:
        raise ValueError(f"expected HxWx3|4 frames, got {shape}")
    stack = np.stack([np.asarray(f)[:, :, :3] for f in frames]).astype(np.int16)
    return (stack.max(axis=0) - stack.min(axis=0)).max(axis=2)


def _clip_rect(
    rect: dict[str, float],
    height: int,
    width: int,
    *,
    inset_px: int = 0,
) -> tuple[int, int, int, int] | None:
    """Inset a {x,y,w,h} screen rect and clip it to the image; None when empty."""
    x0 = int(round(float(rect.get("x", 0)) + inset_px))
    y0 = int(round(float(rect.get("y", 0)) + inset_px))
    x1 = int(round(float(rect.get("x", 0)) + float(rect.get("w", 0)) - inset_px))
    y1 = int(round(float(rect.get("y", 0)) + float(rect.get("h", 0)) - inset_px))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def liveness_mask(frames: Sequence[np.ndarray], delta_min: int = LIVE_DELTA_MIN) -> np.ndarray:
    """Pixels that moved across a settle burst: max-min over RGB >= ``delta_min``.

    ``frames`` are >=2 same-shape HxWx3|4 uint8 screenshots (alpha ignored);
    posters, frozen video and opaque occluders are not live. Returns HxW bool.
    """
    return _max_delta_map(frames) >= int(delta_min)


def score_live_coverage(
    mask: np.ndarray,
    rect: dict[str, float],
    *,
    cols: int = LIVE_BAND_COLS,
    rows: int = LIVE_BAND_ROWS,
    band_live_frac: float = LIVE_BAND_MIN_FRAC,
    min_live_frac: float = LIVE_RECT_MIN_FRAC,
    inset_px: int = LIVE_RECT_INSET_PX,
    occluded_cells: Iterable[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Require every column AND row band of a movie rect to be live (plan §1.2.1).

    Bands beat a whole-rect fraction: an interior opaque occluder never blanks a
    full band, while a sub-rect live patch blanks the bands it does not reach.

    ``occluded_cells`` (screen ``(row, col)``, row 0 = top) are excluded: band means
    and ``liveFrac`` run over the remaining cells, and a fully occluded band is
    reported as excluded, never dead. ``None`` is the unmasked score.
    """
    if occluded_cells is not None:
        return _score_live_coverage_occluded(
            mask, rect, occluded_cells, cols=cols, rows=rows, band_live_frac=band_live_frac,
            min_live_frac=min_live_frac, inset_px=inset_px,
        )
    height, width = mask.shape[:2]
    clipped = _clip_rect(rect, height, width, inset_px=inset_px)
    if clipped is None or clipped[2] < cols or clipped[3] < rows:
        out_rect = (
            {"x": clipped[0], "y": clipped[1], "w": clipped[2], "h": clipped[3]}
            if clipped
            else None
        )
        return {
            "verdict": False,
            "liveFrac": 0.0,
            "deadColumnBands": [],
            "deadRowBands": [],
            "rect": out_rect,
            "reason": "rect outside image or too small",
        }

    x, y, w, h = clipped
    sub = mask[y : y + h, x : x + w]
    live_frac = float(sub.mean())
    col_edges = [round(i * w / cols) for i in range(cols + 1)]
    row_edges = [round(i * h / rows) for i in range(rows + 1)]
    dead_cols = [
        i
        for i in range(cols)
        if float(sub[:, col_edges[i] : col_edges[i + 1]].mean()) < band_live_frac
    ]
    dead_rows = [
        i
        for i in range(rows)
        if float(sub[row_edges[i] : row_edges[i + 1], :].mean()) < band_live_frac
    ]
    verdict = not dead_cols and not dead_rows and live_frac >= min_live_frac
    reason = None
    if not verdict:
        if dead_cols or dead_rows:
            reason = "dead bands"
        else:
            reason = "live fraction below threshold"
    return {
        "verdict": bool(verdict),
        "liveFrac": live_frac,
        "deadColumnBands": dead_cols,
        "deadRowBands": dead_rows,
        "rect": {"x": x, "y": y, "w": w, "h": h},
        "reason": reason,
    }


def _score_live_coverage_occluded(
    mask: np.ndarray,
    rect: dict[str, float],
    occluded_cells: Iterable[tuple[int, int]],
    *,
    cols: int,
    rows: int,
    band_live_frac: float,
    min_live_frac: float,
    inset_px: int,
) -> dict[str, Any]:
    cells: set[tuple[int, int]] = set()
    for cell in occluded_cells:
        if (
            not isinstance(cell, (tuple, list)) or len(cell) != 2
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in cell)
            or not (0 <= cell[0] < rows and 0 <= cell[1] < cols)
        ):
            raise ValueError(f"occluded cell {cell!r} is not on the {rows}x{cols} band grid")
        cells.add((int(cell[0]), int(cell[1])))
    height, width = mask.shape[:2]
    clipped = _clip_rect(rect, height, width, inset_px=inset_px)
    base = {"occludedCells": sorted(cells), "excludedColumnBands": [], "excludedRowBands": []}
    if clipped is None or clipped[2] < cols or clipped[3] < rows:
        out_rect = {"x": clipped[0], "y": clipped[1], "w": clipped[2], "h": clipped[3]} if clipped else None
        return {
            "verdict": False, "liveFrac": 0.0, "deadColumnBands": [], "deadRowBands": [],
            "rect": out_rect, "reason": "rect outside image or too small", **base,
        }
    x, y, w, h = clipped
    sub = mask[y : y + h, x : x + w]
    col_edges = [round(i * w / cols) for i in range(cols + 1)]
    row_edges = [round(i * h / rows) for i in range(rows + 1)]
    visible = np.ones((h, w), dtype=bool)
    for row, col in cells:
        visible[row_edges[row] : row_edges[row + 1], col_edges[col] : col_edges[col + 1]] = False
    rect_out = {"x": x, "y": y, "w": w, "h": h}
    if not visible.any():
        return {
            "verdict": False, "liveFrac": 0.0, "deadColumnBands": [], "deadRowBands": [],
            "rect": rect_out, "reason": "every cell occluded", **base,
        }

    def band_mean(region: np.ndarray, seen: np.ndarray) -> float | None:
        return float(region[seen].mean()) if seen.any() else None

    col_means = [
        band_mean(sub[:, col_edges[i] : col_edges[i + 1]], visible[:, col_edges[i] : col_edges[i + 1]])
        for i in range(cols)
    ]
    row_means = [
        band_mean(sub[row_edges[i] : row_edges[i + 1], :], visible[row_edges[i] : row_edges[i + 1], :])
        for i in range(rows)
    ]
    live_frac = float(sub[visible].mean())
    dead_cols = [i for i, m in enumerate(col_means) if m is not None and m < band_live_frac]
    dead_rows = [i for i, m in enumerate(row_means) if m is not None and m < band_live_frac]
    verdict = not dead_cols and not dead_rows and live_frac >= min_live_frac
    reason = None
    if not verdict:
        reason = "dead bands" if dead_cols or dead_rows else "live fraction below threshold"
    return {
        "verdict": bool(verdict),
        "liveFrac": live_frac,
        "deadColumnBands": dead_cols,
        "deadRowBands": dead_rows,
        "rect": rect_out,
        "reason": reason,
        "occludedCells": base["occludedCells"],
        "excludedColumnBands": [i for i, m in enumerate(col_means) if m is None],
        "excludedRowBands": [i for i, m in enumerate(row_means) if m is None],
    }


def score_dead_rect(
    mask: np.ndarray,
    rect: dict[str, float],
    *,
    max_live_frac: float = DEAD_RECT_MAX_LIVE_FRAC,
    inset_px: int = LIVE_RECT_INSET_PX,
) -> dict[str, Any]:
    """The inverted verdict: a rect the plan expects to be frozen must read dead.

    A rect that cannot be measured (outside the image, or emptied by the inset) is
    not evidence of deadness and fails.
    """
    height, width = mask.shape[:2]
    clipped = _clip_rect(rect, height, width, inset_px=inset_px)
    if clipped is None:
        return {
            "verdict": False,
            "liveFrac": None,
            "rect": None,
            "reason": "rect outside image or too small",
        }
    x, y, w, h = clipped
    live_frac = float(mask[y : y + h, x : x + w].mean())
    verdict = live_frac <= float(max_live_frac)
    return {
        "verdict": bool(verdict),
        "liveFrac": live_frac,
        "rect": {"x": x, "y": y, "w": w, "h": h},
        "reason": None if verdict else "live pixels in a rect the plan expects to be frozen",
    }


def score_no_stray_movie(
    mask: np.ndarray,
    expected_rects: Sequence[dict[str, float]],
    *,
    dilate_px: int = STRAY_DILATE_PX,
    min_area_px: int = STRAY_MIN_AREA_PX,
    ignore_rects: Sequence[dict[str, float]] = (),
) -> dict[str, Any]:
    """Live pixels outside every expected movie rect: a stray second instance.

    Expected rects are dilated by ``dilate_px`` before subtraction; any remaining
    8-connected component of at least ``min_area_px`` fails the slide.

    Limitation: pixels inside an expected rect cannot reveal a second movie there
    (the probe's DOM instance check covers that case).
    """
    height, width = mask.shape[:2]
    work = np.asarray(mask).astype(np.uint8).copy()
    for rect, inset in [(r, -dilate_px) for r in expected_rects] + [(r, 0) for r in ignore_rects]:
        clipped = _clip_rect(rect, height, width, inset_px=inset)
        if clipped is None:
            continue
        x, y, w, h = clipped
        work[y : y + h, x : x + w] = 0

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(work, 8)
    strays = [
        {
            "bbox": {
                "x": int(stats[i, cv2.CC_STAT_LEFT]),
                "y": int(stats[i, cv2.CC_STAT_TOP]),
                "w": int(stats[i, cv2.CC_STAT_WIDTH]),
                "h": int(stats[i, cv2.CC_STAT_HEIGHT]),
            },
            "area": int(stats[i, cv2.CC_STAT_AREA]),
        }
        for i in range(1, count)
        if int(stats[i, cv2.CC_STAT_AREA]) >= min_area_px
    ]
    strays.sort(key=lambda s: s["area"], reverse=True)
    return {"verdict": not strays, "strays": strays}


def score_noise_floor(
    frames: Sequence[np.ndarray],
    control_rect: dict[str, float],
    *,
    max_p99: int = NOISE_FLOOR_P99_MAX,
) -> dict[str, Any]:
    """99th-percentile burst delta over a known-static control region (plan §1.2.3)."""
    return score_noise_floor_from_delta(
        _max_delta_map(frames), control_rect, max_p99=max_p99
    )


def score_noise_floor_from_delta(
    delta: np.ndarray,
    control_rect: dict[str, float],
    *,
    max_p99: int = NOISE_FLOOR_P99_MAX,
) -> dict[str, Any]:
    """``score_noise_floor`` over an already-computed max-delta map."""
    clipped = _clip_rect(control_rect, delta.shape[0], delta.shape[1])
    if clipped is None:
        return {"verdict": False, "p99": None, "rect": None, "reason": "control rect outside image"}
    x, y, w, h = clipped
    p99 = float(np.percentile(delta[y : y + h, x : x + w], 99))
    return {
        "verdict": bool(p99 < max_p99),
        "p99": p99,
        "rect": {"x": x, "y": y, "w": w, "h": h},
        "reason": None if p99 < max_p99 else "noise floor above threshold",
    }


def score_visible_slide(
    frames: Sequence[np.ndarray],
    expected_rects: Sequence[dict[str, Any]],
    control_rect: dict[str, float],
    *,
    delta_min: int = LIVE_DELTA_MIN,
    cols: int = LIVE_BAND_COLS,
    rows: int = LIVE_BAND_ROWS,
    band_live_frac: float = LIVE_BAND_MIN_FRAC,
    min_live_frac: float = LIVE_RECT_MIN_FRAC,
    inset_px: int = LIVE_RECT_INSET_PX,
    dilate_px: int = STRAY_DILATE_PX,
    min_area_px: int = STRAY_MIN_AREA_PX,
    dead_max_live_frac: float = DEAD_RECT_MAX_LIVE_FRAC,
    ignore_rects: Sequence[dict[str, float]] = (),
    max_p99: int = NOISE_FLOOR_P99_MAX,
) -> dict[str, Any]:
    """One settled slide's visible-content verdict: every rect meets its stated
    expectation (``expect: "live" | "dead"``, live when unstated) + no strays.

    A dead-expected rect is scored by ``score_dead_rect`` and joins ``ignore_rects``
    for the stray check, which cannot judge whatever the player paints there.
    A failed noise floor yields ``verdict None`` / ``status "inconclusive"``;
    callers must treat anything but ``verdict is True`` as a failure.
    """
    return score_visible_slide_from_delta(
        _max_delta_map(frames),
        expected_rects,
        control_rect,
        delta_min=delta_min,
        cols=cols,
        rows=rows,
        band_live_frac=band_live_frac,
        min_live_frac=min_live_frac,
        inset_px=inset_px,
        dilate_px=dilate_px,
        min_area_px=min_area_px,
        dead_max_live_frac=dead_max_live_frac,
        ignore_rects=ignore_rects,
        max_p99=max_p99,
    )


def score_visible_slide_from_delta(
    delta: np.ndarray,
    expected_rects: Sequence[dict[str, Any]],
    control_rect: dict[str, float],
    *,
    delta_min: int = LIVE_DELTA_MIN,
    cols: int = LIVE_BAND_COLS,
    rows: int = LIVE_BAND_ROWS,
    band_live_frac: float = LIVE_BAND_MIN_FRAC,
    min_live_frac: float = LIVE_RECT_MIN_FRAC,
    inset_px: int = LIVE_RECT_INSET_PX,
    dilate_px: int = STRAY_DILATE_PX,
    min_area_px: int = STRAY_MIN_AREA_PX,
    dead_max_live_frac: float = DEAD_RECT_MAX_LIVE_FRAC,
    ignore_rects: Sequence[dict[str, float]] = (),
    max_p99: int = NOISE_FLOOR_P99_MAX,
) -> dict[str, Any]:
    """``score_visible_slide`` over an already-computed max-delta map — the whole
    verdict is a function of that raster, so retaining it is enough to recompute
    the slide's visible-content result later."""
    noise = score_noise_floor_from_delta(delta, control_rect, max_p99=max_p99)
    if not noise["verdict"]:
        return {
            "verdict": None,
            "status": "inconclusive",
            "perRect": [],
            "stray": None,
            "noiseFloor": noise,
            "reason": noise.get("reason") or "noise floor above threshold",
        }

    mask = delta >= int(delta_min)
    per_rect: list[dict[str, Any]] = []
    for rect in expected_rects:
        expect = "dead" if rect.get("expect") == "dead" else "live"
        if expect == "dead":
            scored = score_dead_rect(
                mask, rect, max_live_frac=dead_max_live_frac, inset_px=inset_px
            )
        else:
            scored = score_live_coverage(
                mask,
                rect,
                cols=cols,
                rows=rows,
                band_live_frac=band_live_frac,
                min_live_frac=min_live_frac,
                inset_px=inset_px,
            )
        clipped = scored["rect"]
        max_delta = 0
        if clipped:
            patch = delta[
                clipped["y"] : clipped["y"] + clipped["h"],
                clipped["x"] : clipped["x"] + clipped["w"],
            ]
            max_delta = int(patch.max()) if patch.size else 0
        entry = {**scored, "maxDelta": max_delta, "expect": expect}
        if "label" in rect:
            entry["label"] = rect["label"]
        per_rect.append(entry)

    stray = score_no_stray_movie(
        mask,
        [rect for rect in expected_rects if rect.get("expect") != "dead"],
        dilate_px=dilate_px,
        min_area_px=min_area_px,
        ignore_rects=[*ignore_rects, *(r for r in expected_rects if r.get("expect") == "dead")],
    )
    verdict = bool(all(r["verdict"] for r in per_rect) and stray["verdict"])
    return {
        "verdict": verdict,
        "status": "pass" if verdict else "fail",
        "perRect": per_rect,
        "stray": stray,
        "noiseFloor": noise,
        "reason": None,
    }


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if np.isfinite(result) else None


def _valid_inpage_sample(sample: Any, n_bands: int) -> bool:
    """Every field `score_inpage_liveness` reads or converts, checked up front so a
    malformed sample fails closed to INCONCLUSIVE instead of raising."""
    if not isinstance(sample, dict):
        return False
    bands = sample.get("bands")
    if not isinstance(bands, (list, tuple)) or len(bands) != n_bands:
        return False
    if any(_finite_float(v) is None for v in bands):
        return False
    if _finite_float(sample.get("control")) is None or _finite_float(sample.get("green")) is None:
        return False
    rgb = sample.get("greenRGB")
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3 or any(_finite_float(v) is None for v in rgb):
        return False
    if _finite_float(sample.get("ms")) is None or _finite_float(sample.get("t")) is None:
        return False
    return _finite_float(sample.get("glErr")) is not None


def _distinct_monotonic(values: Sequence[float]) -> bool:
    """Strictly increasing, no repeats: a duplicated or replayed callback cannot
    "prove" a window by repeating one frozen sample."""
    return all(a < b for a, b in zip(values, values[1:]))


def _valid_occluder_mask(mask: Any, n_bands: int) -> bool:
    return (
        isinstance(mask, (list, tuple))
        and len(mask) == n_bands
        and all(v in (0, 1) for v in mask)
    )


def score_inpage_liveness(
    samples: Sequence[dict[str, Any]],
    *,
    occluder_mask: Sequence[int],
    min_samples: int = INPAGE_MIN_SAMPLES,
) -> dict[str, Any]:
    """WebGL-settled-slide oracle: LIVE iff every non-occluded band moves more than
    the static control patch, the green patch stays green and static, and there is
    no GL error. Fails closed to INCONCLUSIVE on anything that makes the read itself
    untrustworthy (too few/malformed samples, an unmeasured or malformed occluder
    mask, a moving control, mostly-occluded bands) rather than ever manufacturing a
    pass. ``mediaTime``/``vt`` are recorded only and never influence the verdict.
    """
    if not isinstance(samples, (list, tuple)):
        return {"verdict": None, "status": "inconclusive", "reason": "malformed samples", "n": 0}
    if not samples:
        return {"verdict": None, "status": "inconclusive", "reason": "no samples", "n": 0}

    n_bands = INPAGE_BAND_COUNT
    if not all(_valid_inpage_sample(s, n_bands) for s in samples):
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "malformed samples",
            "n": len(samples),
        }
    t_values = [float(s["t"]) for s in samples]
    if not _distinct_monotonic(t_values):
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "duplicate or non-monotonic sample callbacks",
            "n": len(samples),
        }
    if not _valid_occluder_mask(occluder_mask, n_bands):
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "missing or malformed occluder mask",
            "n": len(samples),
            "nBands": n_bands,
        }

    bands = np.array([s["bands"] for s in samples], dtype=float)
    control = np.array([s["control"] for s in samples], dtype=float)
    green = np.array([s["green"] for s in samples], dtype=float)
    rgb = np.array([s["greenRGB"] for s in samples], dtype=float)
    vt_values = [_finite_float(s.get("vt")) for s in samples]
    media_time_values = [_finite_float(s.get("mediaTime")) for s in samples]

    occ = np.asarray(occluder_mask, dtype=bool)
    n_occluded = int(occ.sum())
    if n_bands == 0 or (n_occluded / n_bands) > INPAGE_OCCLUDED_BANDS_MAX_FRAC:
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "more than half the bands are occluded",
            "n": len(samples),
            "nBands": n_bands,
            "occludedBands": n_occluded,
        }

    judged = ~occ
    n_judged = int(judged.sum())
    if n_judged == 0:
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "no judged bands",
            "n": len(samples),
            "nBands": n_bands,
            "occludedBands": n_occluded,
            "judgedBands": n_judged,
        }

    band_range = bands.max(axis=0) - bands.min(axis=0)
    control_range = float(control.max() - control.min())
    green_range = float(green.max() - green.min())
    threshold = control_range + INPAGE_BAND_MARGIN
    live_bands = int((band_range > threshold).sum())
    mean_rgb = rgb.mean(axis=0)
    green_is_green = bool(
        mean_rgb[1] > mean_rgb[0] + INPAGE_GREEN_CHANNEL_MARGIN
        and mean_rgb[1] > mean_rgb[2] + INPAGE_GREEN_CHANNEL_MARGIN
    )
    gl_err_values = [float(s["glErr"]) for s in samples]
    gl_err_any = max((abs(v) for v in gl_err_values), default=0.0)
    sample_ms = [float(s["ms"]) for s in samples]

    common = {
        "n": len(samples),
        "enoughSamples": len(samples) >= min_samples,
        "nBands": n_bands,
        "liveBands": live_bands,
        "occludedBands": n_occluded,
        "judgedBands": n_judged,
        "judgedBandRangeMin": float(band_range[judged].min()) if judged.any() else None,
        "bandRangeMin": float(band_range.min()),
        "bandRangeMed": float(np.median(band_range)),
        "bandRangeMax": float(band_range.max()),
        "threshold": float(threshold),
        "controlRange": control_range,
        "greenRange": green_range,
        "greenMeanRGB": [float(v) for v in mean_rgb],
        "greenIsGreen": green_is_green,
        "vtSpan": (max(vt_values) - min(vt_values)) if all(v is not None for v in vt_values) else None,
        "mediaTimeSpan": (
            (max(media_time_values) - min(media_time_values))
            if all(v is not None for v in media_time_values)
            else None
        ),
        "sampleMsP50": float(np.percentile(sample_ms, 50)),
        "sampleMsP95": float(np.percentile(sample_ms, 95)),
        "glErrAny": gl_err_any,
    }

    if control_range > INPAGE_CONTROL_RANGE_MAX:
        return {"verdict": None, "status": "inconclusive", "reason": "control patch moved", **common}
    if len(samples) < min_samples:
        return {"verdict": None, "status": "inconclusive", "reason": "too few samples", **common}

    all_judged_live = bool((band_range[judged] > threshold).all())
    reasons = []
    if not all_judged_live:
        reasons.append("a judged band did not move")
    if green_range > INPAGE_GREEN_STATIC_MAX:
        reasons.append("green patch moved")
    if not green_is_green:
        reasons.append("green patch is not green")
    if gl_err_any != 0:
        reasons.append("gl error")

    verdict = not reasons
    return {
        "verdict": verdict,
        "status": "live" if verdict else "dead",
        "reason": None if verdict else reasons[0],
        **common,
    }


def occluder_mask_from_markers(
    dark_bands: Sequence[float],
    light_bands: Sequence[float],
    *,
    max_delta: float = INPAGE_MARKER_DELTA_MAX,
) -> dict[str, Any]:
    """Marker-swap occluder mask: a band whose mean does not move between a black and
    a white marker frame is covered by later-authored artwork. Markers must differ in
    RGB sum (black vs white) because the band metric is the RGB mean."""
    if not isinstance(dark_bands, (list, tuple)) or not isinstance(light_bands, (list, tuple)):
        return {"verdict": False, "mask": None, "reason": "mismatched marker lengths"}
    n = len(dark_bands)
    if n != INPAGE_BAND_COUNT or len(light_bands) != n:
        return {"verdict": False, "mask": None, "reason": "mismatched marker lengths"}
    dark = [_finite_float(v) for v in dark_bands]
    light = [_finite_float(v) for v in light_bands]
    if any(v is None for v in dark) or any(v is None for v in light):
        return {"verdict": False, "mask": None, "reason": "non-finite marker delta"}
    delta = [light[i] - dark[i] for i in range(n)]
    mask = [1 if abs(d) <= max_delta else 0 for d in delta]
    return {
        "verdict": True,
        "mask": mask,
        "occluded": int(sum(mask)),
        "nBands": n,
        "markerDelta": delta,
        "reason": None,
    }


def inpage_mask_is_usable(mask_result: dict[str, Any]) -> bool:
    """A measured occluder mask is usable when it exists and covers no more than
    half the bands (plan §4.3)."""
    if not mask_result.get("verdict") or not mask_result.get("mask"):
        return False
    n_bands = mask_result["nBands"]
    if n_bands == 0:
        return False
    return (mask_result["occluded"] / n_bands) <= INPAGE_OCCLUDED_BANDS_MAX_FRAC


def combine_oracle_verdicts(
    screenshot: dict[str, Any], inpage: dict[str, Any] | None
) -> dict[str, Any]:
    """Two-oracle verdict: agreement wins, disagreement is always inconclusive, and
    an inconclusive or absent in-page read never upgrades a screenshot verdict of
    False or None (plan §4.4). A screenshot verdict of None is never overridden."""
    oracles = {"screenshot": screenshot, "inpage": inpage}
    if inpage is None or inpage.get("status") == "n/a":
        return {
            "verdict": screenshot["verdict"],
            "status": screenshot["status"],
            "reason": screenshot.get("reason"),
            "oracles": oracles,
        }

    screenshot_verdict = screenshot["verdict"]
    inpage_verdict = inpage["verdict"]

    if screenshot_verdict is None:
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": screenshot.get("reason"),
            "oracles": oracles,
        }

    if inpage_verdict is None:
        if screenshot_verdict is True:
            return {
                "verdict": None,
                "status": "inconclusive",
                "reason": f"in-page oracle inconclusive: {inpage.get('reason')}",
                "oracles": oracles,
            }
        return {
            "verdict": False,
            "status": "fail",
            "reason": screenshot.get("reason"),
            "oracles": oracles,
        }

    if screenshot_verdict != inpage_verdict:
        return {
            "verdict": None,
            "status": "inconclusive",
            "reason": "oracle disagreement",
            "oracles": oracles,
        }

    return {
        "verdict": screenshot_verdict,
        "status": "pass" if screenshot_verdict else "fail",
        "reason": screenshot.get("reason"),
        "oracles": oracles,
    }


def score_restart_movie_from_observations(
    observations: Sequence[dict[str, Any]],
    *,
    slide_min_hash: int,
    near_zero_max_s: float = 0.35,
    progression_wall_s: float = 0.25,
    progression_media_s: float = 0.20,
    backward_reset_min_s: float = 1.0,
) -> dict[str, Any]:
    """Build one expected-movie restart row from continuous samples.

    Observations are ``{t|currentTime, w|videoWidth, captureOffsetS, sceneHash,
    decoderId?}``. Continued remount clocks for the same asset key must not hide
    a fresh decoder: we pick the decoder whose near-zero clock is itself observed
    on ``sceneHash >= slide_min_hash`` (a decoder merely continuing onto the
    target slide from an earlier one does not count), then require spaced
    progression and at least one sample on ``sceneHash >= slide_min_hash`` with
    decoded width. The near-zero decoder must also be a genuine restart — it
    either first appears at/after the boundary, or was observed pre-boundary
    with a clock clearly above ``near_zero_max_s`` and never near-zero before
    resetting — so a decoder that merely happened to be near-zero while
    continuing across the boundary does not pass, even if it was also seen
    far from zero at some earlier point.
    """
    rows: list[dict[str, Any]] = []
    for raw in observations:
        if raw.get("t") is None and raw.get("currentTime") is None:
            continue
        t = float(raw["t"] if raw.get("t") is not None else raw["currentTime"])
        w_raw = raw.get("w")
        if w_raw is None:
            w_raw = raw.get("videoWidth")
        rows.append(
            {
                "t": t,
                "w": w_raw,
                "captureOffsetS": float(raw.get("captureOffsetS") or 0.0),
                "sceneHash": raw.get("sceneHash"),
                "decoderId": raw.get("decoderId"),
                "phase": raw.get("phase"),
            }
        )

    def _hash_num(h: object) -> int | None:
        token = str(h or "").lstrip("#").split("?")[0]
        return int(token) if token.isdigit() else None

    slide3 = [r for r in rows if (_hash_num(r.get("sceneHash")) or -1) >= slide_min_hash]
    by_dec: dict[object, list[dict[str, Any]]] = {}
    for r in rows:
        by_dec.setdefault(r.get("decoderId"), []).append(r)

    def _first_progression(series: list[dict[str, Any]], ref: dict[str, Any]) -> bool:
        for row in series:
            wall_dt = float(row["captureOffsetS"]) - float(ref["captureOffsetS"])
            media_dt = float(row["t"]) - float(ref["t"])
            if wall_dt >= progression_wall_s and media_dt >= progression_media_s:
                return True
        return False

    # One boundary near-zero candidate per decoder — its own earliest near-zero on-slide sample.
    candidates: list[tuple[object, dict[str, Any], list[dict[str, Any]]]] = []
    for dec_id, series in by_dec.items():
        series_sorted = sorted(series, key=lambda r: float(r["captureOffsetS"]))
        hit = next(
            (
                r
                for r in series_sorted
                if float(r["t"]) < near_zero_max_s
                and (r.get("w") or 0) > 0
                and (_hash_num(r.get("sceneHash")) or -1) >= slide_min_hash
            ),
            None,
        )
        if hit is not None:
            candidates.append((dec_id, hit, series))

    def _pre_boundary_rows(dec_id: object) -> list[dict[str, Any]]:
        return [
            r
            for r in by_dec.get(dec_id, [])
            if (_hash_num(r.get("sceneHash")) or -1) < slide_min_hash
        ]

    def _first_seen_at_boundary(dec_id: object) -> bool:
        return dec_id is not None and len(_pre_boundary_rows(dec_id)) == 0

    def _has_pre_boundary_near_zero(dec_id: object) -> bool:
        return any(float(r["t"]) < near_zero_max_s for r in _pre_boundary_rows(dec_id))

    def _backward_reset(dec_id: object) -> bool:
        return (
            dec_id is not None
            and any(float(r["t"]) > backward_reset_min_s for r in _pre_boundary_rows(dec_id))
            and not _has_pre_boundary_near_zero(dec_id)
        )

    def _genuine(dec_id: object) -> bool:
        return _first_seen_at_boundary(dec_id) or _backward_reset(dec_id)

    # Prefer an identified, genuinely-restarting decoder that both near-zeros and
    # progresses; a stalled candidate appearing first must not mask a genuine
    # restart in another decoder, and a decoder that merely continued across the
    # boundary near-zero (never reset) must not masquerade as one either.
    chosen = (
        next(
            (
                (d, h, s)
                for d, h, s in candidates
                if d is not None and _genuine(d) and _first_progression(s, h)
            ),
            None,
        )
        or next(((d, h, s) for d, h, s in candidates if d is not None and _genuine(d)), None)
        or next(iter(candidates), None)
    )
    chosen_id: object | None = chosen[0] if chosen else None
    near_zero_row: dict[str, Any] | None = chosen[1] if chosen else None
    series = list(chosen[2]) if chosen else []
    slide3_series = [
        r for r in series if (_hash_num(r.get("sceneHash")) or -1) >= slide_min_hash
    ]
    # Fallback: no boundary near-zero decoder — surface slide-3 evidence for reporting only.
    if near_zero_row is None and slide3:
        with_w = [r for r in slide3 if (r.get("w") or 0) > 0]
        pool = with_w or slide3
        near_zero_row = min(pool, key=lambda r: float(r["t"])) if pool else None
        slide3_series = slide3
        series = slide3

    # Progression must be attributable to one identified decoder — id-less rows can mix a
    # stalled decoder with a different continued one, which is not a restart.
    progressed = bool(
        near_zero_row is not None
        and chosen_id is not None
        and _first_progression(series, near_zero_row)
    )

    decoded = bool(slide3_series) and any((r.get("w") or 0) > 0 for r in slide3_series)
    near_zero = bool(near_zero_row and float(near_zero_row["t"]) < near_zero_max_s)
    earliest_slide3 = None
    if slide3_series:
        with_w = [r for r in slide3_series if (r.get("w") or 0) > 0]
        earliest_slide3 = min(with_w or slide3_series, key=lambda r: float(r["t"]))

    first_seen_at_boundary = _first_seen_at_boundary(chosen_id)
    backward_reset = _backward_reset(chosen_id)

    ok = bool(
        len(slide3_series) >= 1
        and near_zero
        and progressed
        and decoded
        and near_zero_row is not None
        and (near_zero_row.get("w") or 0) > 0
        and (first_seen_at_boundary or backward_reset)
    )
    return {
        "slide3ObsN": len(slide3_series),
        "earliest": earliest_slide3,
        "firstSeenAtBoundary": first_seen_at_boundary,
        "backwardReset": backward_reset,
        "nearZeroObs": near_zero_row,
        "restartDecoderId": chosen_id,
        "nearZeroAtBoundary": near_zero,
        "progressedAfterRestart": progressed,
        "decodedWidthAtBoundary": decoded,
        "ok": ok,
    }


def score_restart_at_slide_boundary(
    *,
    reached_slide: bool,
    per_movie: dict[str, dict[str, Any]],
    expected_keys: Sequence[str],
    canvas_all_identical: bool = False,
) -> dict[str, Any]:
    """Verdict for deliberate restart — evidence must be on the target slide.

    ``per_movie`` maps asset key → {
      slide3ObsN, earliest: {t, w, ...}|None, nearZeroAtBoundary,
      progressedAfterRestart, decodedWidthAtBoundary, presentedMotionOk, ok
    }.

    ``expected_keys`` is required (never derived from observed keys) — missing
    movies must not silently pass. Decoded width is always required so
    audio-only clocks cannot pass. Pre-boundary restart signals alone must
    never pass. ``currentTime``/width progression alone does not prove the
    presented frame progresses — a caller must additionally attest
    ``presentedMotionOk`` (target-footprint composed-ROI motion or rVFC
    progression on the target slide), or that movie fails.
    """
    expected = [k for k in expected_keys if k]
    missing = [
        k
        for k in expected
        if int((per_movie.get(k) or {}).get("slide3ObsN") or 0) == 0
    ]
    width_fail = [
        k
        for k in expected
        if k not in missing and not bool((per_movie.get(k) or {}).get("decodedWidthAtBoundary"))
    ]
    presented_motion_fail = [
        k
        for k in expected
        if k not in missing and not bool((per_movie.get(k) or {}).get("presentedMotionOk"))
    ]
    all_ok = bool(expected) and all(
        bool((per_movie.get(k) or {}).get("ok"))
        and bool((per_movie.get(k) or {}).get("presentedMotionOk"))
        for k in expected
    )
    late = any(
        int((per_movie.get(k) or {}).get("slide3ObsN") or 0) > 0
        and (per_movie.get(k) or {}).get("earliest")
        and float(((per_movie.get(k) or {}).get("earliest") or {}).get("t") or 0) >= 0.35
        for k in expected
    )
    inconclusive = bool(
        reached_slide and (missing or width_fail or presented_motion_fail or (not all_ok and late))
    )
    ok = bool(
        reached_slide
        and expected
        and not missing
        and not width_fail
        and not presented_motion_fail
        and all_ok
        and not canvas_all_identical
    )
    verdict = "pass" if ok else ("inconclusive" if inconclusive else "fail")
    return {
        "ok": ok,
        "verdict": verdict,
        "expectedKeys": list(expected),
        "missingSlide3Media": missing,
        "missingDecodedWidth": width_fail,
        "missingPresentedMotion": presented_motion_fail,
        "allMoviesOk": all_ok,
        "inconclusive": inconclusive,
    }


def contentful_plate(arr: np.ndarray) -> bool:
    """Skip empty/black PDF pages that match every DSK plate equally."""
    return progress_metric(arr) >= IDENTITY_CONTENT_MIN


def rgb_over_black(arr: np.ndarray) -> np.ndarray:
    rgb = arr[:, :, :3].astype(np.float32)
    alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
    return np.clip(rgb * alpha, 0, 255).astype(np.uint8)


def plate_rgb_mae(left: np.ndarray, right: np.ndarray) -> float:
    a = rgb_over_black(left)
    b = rgb_over_black(right)
    if a.shape != b.shape:
        from PIL import Image

        b_img = Image.fromarray(b, "RGB").resize((a.shape[1], a.shape[0]), Image.Resampling.BILINEAR)
        b = np.array(b_img)
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))


def layer_signature(layers: Sequence[dict[str, Any]]) -> tuple[tuple[int, int, float, float], ...]:
    sig = []
    for layer in layers:
        if not layer.get("used"):
            continue
        sig.append(
            (
                int(layer.get("w") or 0),
                int(layer.get("h") or 0),
                round(float(layer.get("x") or 0), 1),
                round(float(layer.get("y") or 0), 1),
            )
        )
    return tuple(sorted(sig))


def leftover_object_layers(
    current: Sequence[dict[str, Any]],
    previous_by_ordinal: dict[int, Sequence[dict[str, Any]]],
) -> str | None:
    sig = layer_signature(current)
    if not sig:
        return None
    for ordinal, prev in previous_by_ordinal.items():
        if layer_signature(prev) == sig:
            return f"object layers match leftover slide {ordinal}"
    return None


def painted_identity(
    plate: np.ndarray,
    *,
    ordinal: int,
    expected_hash: str | None = None,
    live_hash: str = "",
    rasters_by_ordinal: dict[int, Sequence[np.ndarray]],
    previous_plates: dict[int, np.ndarray],
    layers: Sequence[dict[str, Any]] | None = None,
    previous_layers: dict[int, Sequence[dict[str, Any]]] | None = None,
    expected_starting_scene: int | None = None,
    require_starting_scene: bool = False,
) -> dict[str, Any]:
    """Painted composed-plate identity. Hash is a scene index, not a slide."""
    reasons: list[str] = []
    live_scene = scene_from_hash(live_hash)
    if expected_starting_scene is None and expected_hash:
        expected_starting_scene = scene_from_hash(expected_hash)
    if require_starting_scene and expected_starting_scene is not None and live_scene != expected_starting_scene:
        reasons.append(
            f"landed on scene {live_scene} expected starting scene {expected_starting_scene}"
        )
    leftover: dict[str, float] = {}
    other_best: float | None = None
    other_label = None

    def _consider_other(mae: float, label: str) -> None:
        nonlocal other_best, other_label
        leftover[label] = mae if label not in leftover else min(leftover[label], mae)
        if other_best is None or mae < other_best:
            other_best = mae
            other_label = label

    for other, prev in previous_plates.items():
        mae = plate_rgb_mae(plate, prev)
        _consider_other(mae, f"prev-{other}")
        if mae <= IDENTITY_NEAR_DUP_MAE_MAX:
            reasons.append(f"near-duplicate of slide {other} settled plate (mae {mae:.3f})")
    own_maes = [
        plate_rgb_mae(plate, raster)
        for raster in rasters_by_ordinal.get(ordinal) or []
        if contentful_plate(raster)
    ]
    own_best = min(own_maes) if own_maes else None
    for other, rasters in rasters_by_ordinal.items():
        if other == ordinal:
            continue
        for raster in rasters:
            if not contentful_plate(raster):
                continue
            mae = plate_rgb_mae(plate, raster)
            _consider_other(mae, f"raster-{other}")
    raster_useful = own_best is not None and own_best <= IDENTITY_RASTER_USEFUL_MAX
    own_rasters_declared = bool(rasters_by_ordinal.get(ordinal))
    # When own rasters are contentful but the plate is a weak match, fail closed.
    # (Do not fail merely because rasters were non-contentful / near-black.)
    if own_rasters_declared and own_best is not None and not raster_useful:
        # Weak own match must not silently skip the near-dup / closer-than-other checks.
        reasons.append(
            f"own raster mae {own_best:.3f} exceeds useful max {IDENTITY_RASTER_USEFUL_MAX} — identity evidence insufficient"
        )
        if other_best is not None and other_best <= IDENTITY_NEAR_DUP_MAE_MAX:
            reasons.append(
                f"also near-duplicate of {other_label} (mae {other_best:.3f}) while own evidence is weak"
            )
    elif raster_useful and other_best is not None and own_best + IDENTITY_OWN_CLOSER_MARGIN >= other_best:
        reasons.append(
            f"plate closer to {other_label} (mae {other_best:.3f}) than own raster (mae {own_best:.3f})"
        )
    if require_starting_scene and expected_starting_scene is not None and live_scene is None:
        reasons.append("live scene hash unparseable while starting scene is required")
    leftover_layers = leftover_object_layers(layers or [], previous_layers or {})
    if leftover_layers:
        reasons.append(leftover_layers)
    return {
        "pass": not reasons,
        "reasons": reasons,
        "expectedHash": expected_hash,
        "liveHash": live_hash,
        "liveScene": live_scene,
        "expectedStartingScene": expected_starting_scene,
        "ownRasterMae": own_best,
        "otherRasterMae": other_best,
        "otherRasterOrdinal": other_label,
        "previousPlateMae": leftover,
        "declaredNearDupMaeMax": IDENTITY_NEAR_DUP_MAE_MAX,
        "declaredOwnCloserMargin": IDENTITY_OWN_CLOSER_MARGIN,
        "declaredRasterUsefulMax": IDENTITY_RASTER_USEFUL_MAX,
    }


def _progress_at(run: Sequence[tuple[float, np.ndarray]], t: float) -> float:
    if not run:
        return 0.0
    nearest = min(run, key=lambda item: abs(item[0] - t))
    return progress_metric(nearest[1])


def timing_repeatability(
    run_a: Sequence[tuple[float, np.ndarray]],
    run_b: Sequence[tuple[float, np.ndarray]],
    *,
    fps: int = FPS,
) -> dict[str, Any]:
    """Compare progress at the same timestamps (declared fps grid), not screenshot index.

    Screenshot duration may skip slots; identical hold frames are allowed. Consecutive
    identical frames *during* changing progress are counted as duplicates.
    """
    if len(run_a) < 2 or len(run_b) < 2:
        return {"pass": False, "reason": "need at least 2 frames per run", "declaredMaeMax": REPEAT_PROGRESS_MAE_MAX}
    duration = min(run_a[-1][0], run_b[-1][0])
    if duration <= 0:
        return {"pass": False, "reason": "non-positive duration", "declaredMaeMax": REPEAT_PROGRESS_MAE_MAX}
    steps = max(2, int(round(duration * fps)) + 1)
    grid = [i / fps for i in range(steps) if i / fps <= duration + 1e-9]
    progress_err = [abs(_progress_at(run_a, t) - _progress_at(run_b, t)) for t in grid]
    mae = float(sum(progress_err) / len(progress_err))

    def _dup_during_motion(run: Sequence[tuple[float, np.ndarray]]) -> int:
        """Count identical frames that are not a terminal hold."""
        last_change = 0
        for i in range(1, len(run)):
            if not np.array_equal(run[i][1], run[i - 1][1]):
                last_change = i
        dups = 0
        for i in range(1, last_change):
            if np.array_equal(run[i][1], run[i - 1][1]):
                dups += 1
        return dups

    dups = max(_dup_during_motion(run_a), _dup_during_motion(run_b))

    def _motion_sampled(run: Sequence[tuple[float, np.ndarray]]) -> bool:
        if len(run) < 2:
            return False
        distinct = 1
        for i in range(1, len(run)):
            if not np.array_equal(run[i][1], run[i - 1][1]):
                distinct += 1
        progress = [progress_metric(frame) for _ts, frame in run]
        return distinct >= 2 and (max(progress) - min(progress)) > 1e-6

    motion_a = _motion_sampled(run_a)
    motion_b = _motion_sampled(run_b)
    motion_sampled = motion_a and motion_b
    return {
        "pass": motion_sampled and mae <= REPEAT_PROGRESS_MAE_MAX and dups == 0,
        "progressMae": mae,
        "duplicateMotionFrames": dups,
        "motionSampled": motion_sampled,
        "reason": None if motion_sampled else "identical holds only; LineDraw intermediates were not captured",
        "declaredMaeMax": REPEAT_PROGRESS_MAE_MAX,
        "declaredTimestampErrMaxS": REPEAT_TIMESTAMP_ERR_MAX_S,
        "framesCompared": len(grid),
        "runAFrames": len(run_a),
        "runBFrames": len(run_b),
        "durationS": duration,
    }


PROBE_STYLE = """
html,body,#body,#stageArea,#stage,div.stage{
  background:transparent !important;
  background-color:transparent !important;
}
#slideshowNavigator,#slideNumberControl,#slideNumberDisplay,#helpPlacard,#waitingIndicator{
  display:none !important;
}
""".strip()

PROBE_SCRIPT = r"""
(function(){
  if (window.__OBED_P2_PROBE__) return;
  var rafTimes = [];
  var rafRequested = 0;
  var rafExecuted = 0;
  var origRAF = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function(cb){
    rafRequested += 1;
    return origRAF(function(ts){
      rafExecuted += 1;
      rafTimes.push(ts);
      return cb(ts);
    });
  };
  window.__OBED_P2_PROBE__ = {
    version: 4,
    playerFnNames: ["jumpToSlide","advanceToNextBuild","goBackToPreviousBuild"],
    rafTimes: rafTimes,
    rafRequested: function(){ return rafRequested; },
    rafExecuted: function(){ return rafExecuted; },
    console: [],
    clock: function(ms){
      var startReq = rafRequested, startExec = rafExecuted;
      var t0 = performance.now();
      return new Promise(function(resolve){
        setTimeout(function(){
          resolve({
            windowMs: performance.now() - t0,
            requested: rafRequested - startReq,
            executed: rafExecuted - startExec,
            rafCount: rafTimes.length,
            hidden: !!(document.hidden),
            now: performance.now(),
            note: "idle: zero requests is not a freeze"
          });
        }, ms);
      });
    },
    heartbeat: function(ms){
      var startReq = rafRequested, startExec = rafExecuted;
      var t0 = performance.now();
      var stop = false;
      function beat(){
        if (stop) return;
        window.requestAnimationFrame(beat);
      }
      beat();
      return new Promise(function(resolve){
        setTimeout(function(){
          stop = true;
          resolve({
            windowMs: performance.now() - t0,
            requested: rafRequested - startReq,
            executed: rafExecuted - startExec,
            hidden: !!(document.hidden),
            now: performance.now()
          });
        }, ms);
      });
    },
    textureInventory: function(){
      var canvases = [];
      document.querySelectorAll("canvas").forEach(function(c, i){
        canvases.push({index:i, id:c.id||"", w:c.width, h:c.height, className:c.className||""});
      });
      var images = [];
      document.querySelectorAll("img").forEach(function(im){
        images.push({src: String(im.currentSrc || im.src || ""), w: im.naturalWidth, h: im.naturalHeight});
      });
      var pdfs = [];
      document.querySelectorAll("embed,object,iframe").forEach(function(n){
        var src = String(n.getAttribute("src") || n.getAttribute("data") || "");
        if (src.toLowerCase().indexOf(".pdf") >= 0) pdfs.push(src);
      });
      return {hash: String(location.hash||""), search: String(location.search||""), canvases: canvases, images: images, pdfs: pdfs};
    },
    hash: function(){ return String(location.hash || ""); },
    ready: function(){
      var area = document.getElementById("stageArea");
      var canvases = document.querySelectorAll("canvas");
      var vis = area ? getComputedStyle(area).visibility : "missing";
      return {
        stageVisibility: vis,
        canvasCount: canvases.length,
        fonts: (document.fonts && document.fonts.status) || "unknown",
        hash: String(location.hash || ""),
        search: String(location.search || "")
      };
    },
    layerSignature: function(){
      var nodes = document.querySelectorAll("canvas");
      var out = [];
      nodes.forEach(function(c){
        var r = c.getBoundingClientRect();
        out.push({
          id: c.id || "",
          w: c.width,
          h: c.height,
          x: r.left,
          y: r.top,
          full: c.width >= 1920 && c.height >= 1080,
          used: c.width < 1920 || c.height < 1080
        });
      });
      return out;
    },
    objectComposite: function(){
      var w = 1920, h = 1080;
      var out = document.createElement("canvas");
      out.width = w; out.height = h;
      var ctx = out.getContext("2d", {alpha:true});
      var nodes = document.querySelectorAll("canvas");
      var layers = [];
      nodes.forEach(function(c){
        var full = c.width >= 1920 && c.height >= 1080;
        var r = c.getBoundingClientRect();
        if (full) {
          layers.push({id:c.id||"", w:c.width, h:c.height, skipped:"full-slide-opaque"});
          return;
        }
        try {
          ctx.drawImage(c, r.left, r.top, r.width, r.height);
          layers.push({id:c.id||"", w:c.width, h:c.height, x:r.left, y:r.top, used:true});
        } catch (err) {
          layers.push({id:c.id||"", w:c.width, h:c.height, error:String(err && err.message || err)});
        }
      });
      return {png: out.toDataURL("image/png"), layers: layers};
    },
    canvasAlpha: function(){
      var nodes = document.querySelectorAll("#stageArea canvas, #stage canvas, canvas");
      var out = [];
      nodes.forEach(function(c, i){
        var item = {index:i, width:c.width, height:c.height, id:c.id||"", className:c.className||""};
        try {
          var ctx = c.getContext("2d");
          if (ctx) {
            var img = ctx.getImageData(0, 0, Math.min(c.width, 8), Math.min(c.height, 8));
            var a = 255, z = 0, n = img.data.length/4;
            for (var p=0;p<n;p++){
              var v = img.data[p*4+3];
              if (v < a) a = v;
              if (v <= 2) z++;
            }
            item.readable = "2d";
            item.sampleAlphaMin = a;
            item.sampleTransparent = z;
          } else {
            item.readable = "not-2d";
          }
        } catch (err) {
          item.readable = "blocked";
          item.error = String(err && err.message || err);
        }
        out.push(item);
      });
      return out;
    }
  };
  function note(kind, detail){
    window.__OBED_P2_PROBE__.console.push({kind:kind, detail:String(detail||"")});
  }
  window.addEventListener("error", function(ev){ if (ev.message) note("error", ev.message); }, true);
  window.addEventListener("unhandledrejection", function(ev){ note("error", ev.reason || "unhandledrejection"); });
  var cons = console;
  var oe = cons.error.bind(cons), ow = cons.warn.bind(cons);
  cons.error = function(){ note("console", Array.prototype.join.call(arguments, " ")); oe.apply(cons, arguments); };
  cons.warn = function(){ note("console", Array.prototype.join.call(arguments, " ")); ow.apply(cons, arguments); };
})();
""".strip()


def required_player_markers(player_js: str) -> dict[str, bool]:
    return {
        "requestAnimFrameAssign": PLAYER_RAF_ASSIGN in player_js,
        "jumpToSlidePresent": "jumpToSlide" in player_js,
        "advanceToNextBuildPresent": "advanceToNextBuild" in player_js,
        "webglGetContext": 'getContext("webgl")' in player_js,
        "clearColorTransparent": "clearColor(0,0,0,0)" in player_js,
    }


def patch_index_html(html: str, player_js: str) -> str:
    """Patch only index.html. Refuse if the measured structure is absent.

    Does not edit main.js. Wraps ``requestAnimationFrame`` before the player
    assigns ``requestAnimFrame``, so instrumentation is version-checked against
    the measured assignment string without calling private player functions.
    """
    markers = required_player_markers(player_js)
    if not markers["requestAnimFrameAssign"]:
        raise ProbeStructureError(
            "player main.js is missing the measured requestAnimFrame assignment; refusing to instrument"
        )
    if not _INDEX_MAIN_JS.search(html):
        raise ProbeStructureError("index.html is missing assets/player/main.js")
    if 'id="body"' not in html and "id='body'" not in html:
        raise ProbeStructureError("index.html is missing body#body")
    if 'id="stageArea"' not in html or 'id="stage"' not in html:
        raise ProbeStructureError("index.html is missing #stageArea/#stage")
    patched = _BODY_BG.sub(r"\1", html, count=1)
    snippet = (
        f'<style data-obed-p2-alpha="{PROBE_VERSION}">{PROBE_STYLE}</style>'
        f'<script data-obed-p2-probe="{PROBE_VERSION}">{PROBE_SCRIPT}</script>'
    )
    patched = _INDEX_MAIN_JS.sub(snippet + r'<script src="assets/player/main.js"></script>', patched, count=1)
    if f'data-obed-p2-probe="{PROBE_VERSION}"' not in patched:
        raise ProbeStructureError("failed to inject the version-checked P2 probe")
    return patched


def copy_unmodified_export(src: Path, dest: Path) -> dict[str, Any]:
    src = Path(src)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=False)
    header, header_path = load_header(dest)
    validate_export_contract(header)
    player = dest / PLAYER_JS
    if not player.is_file():
        raise ProbeStructureError(f"unmodified export is missing {PLAYER_JS}")
    return {
        "root": str(dest),
        "bytes": tree_bytes(dest),
        "playerDigest": file_sha256(player),
        "headerPath": header_path,
        "header": {
            "creator": header.get("creator"),
            "major": header.get("majorVersion", header.get("major")),
            "minor": header.get("minorVersion", header.get("minor")),
            "slideList": header_slide_list(header),
            "slideWidth": header.get("slideWidth"),
            "slideHeight": header.get("slideHeight"),
        },
        "playerMarkers": required_player_markers(player.read_text(encoding="utf-8", errors="replace")),
    }


def write_patched_export(unmodified: Path, dest: Path) -> dict[str, Any]:
    unmodified = Path(unmodified)
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(unmodified, dest, symlinks=False)
    index = dest / "index.html"
    player = dest / PLAYER_JS
    html = index.read_text(encoding="utf-8")
    js = player.read_text(encoding="utf-8", errors="replace")
    index.write_text(patch_index_html(html, js), encoding="utf-8")
    if file_sha256(player) != file_sha256(unmodified / PLAYER_JS):
        raise ProbeStructureError("patched export changed main.js — refuse")
    return {
        "root": str(dest),
        "playerDigest": file_sha256(player),
        "indexSha256": file_sha256(index),
        "patches": [
            "remove body bgcolor=black",
            "inject transparent CSS for html/body/#stageArea/#stage",
            "hide player chrome (navigator/help/waiting)",
            f"inject version-checked probe script v{PROBE_VERSION} before main.js",
            "main.js unmodified",
        ],
    }


def inventory_deck(deck: Path) -> dict[str, Any]:
    deck = Path(deck)
    source, canvas = source_slides(deck)
    objects, id_to_file, file_ids = _load_deck(deck)
    builds = deck_builds(deck, deck=(objects, id_to_file, file_ids))
    slides: list[dict[str, Any]] = []
    for src in source:
        slide = objects.get(src.slide_id) or {}
        rec = builds.get(src.ordinal) or {}
        transition = _transition_effect_duration(rec.get("transition"))
        groups = iwa_click_groups(objects, slide)
        try:
            counts = {
                "stageCounts": stage_counts(deck, [src.ordinal], deck_obj=(objects, id_to_file, file_ids))[src.ordinal],
                "refusedAutomatic": False,
            }
        except StageCountAmbiguous as exc:
            try:
                auto = stage_counts(
                    deck, [src.ordinal], deck_obj=(objects, id_to_file, file_ids), allow_automatic=True
                )[src.ordinal]
            except StageCountAmbiguous:
                auto = None
            counts = {
                "stageCounts": None,
                "refusedAutomatic": True,
                "stageCountsIfAllowAutomatic": auto,
                "reason": str(exc),
            }
        effect_names = [str(b.get("effect") or "") for b in rec.get("builds") or []]
        slides.append(
            {
                "originalOrdinal": src.ordinal,
                "slideId": src.slide_id,
                "skipped": src.skipped,
                "identity": list(src.identity),
                "transition": {
                    "effect": transition[0] if transition else None,
                    "duration": transition[1] if transition else None,
                },
                "magicMove": is_magic_move(transition),
                "layoutAlphaSafe": layout_alpha_safe(slide, objects, canvas),
                "iwa": groups,
                "stageCounts": counts,
                "builds": [
                    {
                        "effect": b.get("effect"),
                        "animationType": b.get("animationType"),
                        "kind": b.get("kind"),
                        "characterEffect": is_character_effect(b.get("effect")),
                        "buildOut": is_build_out(b.get("animationType")),
                        "movieStart": "movie-start" in str(b.get("effect") or "").lower(),
                    }
                    for b in rec.get("builds") or []
                ],
                "hasCharacterEffect": any(is_character_effect(name) for name in effect_names),
                "hasBuildOut": any(is_build_out(b.get("animationType")) for b in rec.get("builds") or []),
                "hasMovieStart": any("movie-start" in str(b.get("effect") or "").lower() for b in rec.get("builds") or []),
                "hasLineDraw": any(name in {LINEDRAW, LINEDRAW_FOR_LINE} for name in effect_names)
                or any(
                    item.get("effect") in {LINEDRAW, LINEDRAW_FOR_LINE}
                    for group in groups["operatorClicks"]
                    for item in group
                ),
            }
        )
    return {
        "path": str(deck),
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "slideCount": len(source),
        "skipped": [s.ordinal for s in source if s.skipped],
        "slides": slides,
    }


def inventory_export(export_root: Path, source_inventory: dict[str, Any]) -> dict[str, Any]:
    export_root = Path(export_root)
    header, _header_path = load_header(export_root)
    uuids = header_slide_list(header)
    live = [slide for slide in source_inventory["slides"] if not slide["skipped"]]
    if len(live) != len(uuids):
        raise ProbeStructureError(
            f"export has {len(uuids)} slides but source has {len(live)} non-skipped"
        )
    index_html = (export_root / "index.html").read_text(encoding="utf-8")
    player_js = (export_root / PLAYER_JS).read_text(encoding="utf-8", errors="replace")
    slides: list[dict[str, Any]] = []
    for player_index, (src, uuid) in enumerate(zip(live, uuids, strict=True)):
        payload = read_jsonish(export_root / "assets" / uuid / f"{uuid}.json")
        clicks = kpf_operator_events(payload)
        events = payload.get("events") if isinstance(payload, dict) else None
        slides.append(
            {
                "originalOrdinal": src["originalOrdinal"],
                "playerIndex": player_index,
                "playerHash": player_hash(player_index),
                "eventCount": len(events) if isinstance(events, list) else 0,
                "exportedUuid": uuid,
                "identity": list(export_payload_identity(payload)),
                "kpfOperatorClicks": clicks,
                "kpfClickCount": len(clicks),
                "iwaClickCount": src["iwa"]["operatorClickCount"],
                "clickCountsAgree": len(clicks) == src["iwa"]["operatorClickCount"],
                "opacity": opacity_trace(
                    export_root, uuid=uuid, payload=payload, index_html=index_html, player_js=player_js
                ),
                "accessibilityRects": accessibility_rects(payload),
                "assetTypes": sorted(
                    {
                        str(asset.get("type"))
                        for asset in (payload.get("assets") or {}).values()
                        if isinstance(asset, dict)
                    }
                ),
            }
        )
    assign_starting_scenes(slides)
    return {
        "canvas": {"width": header.get("slideWidth"), "height": header.get("slideHeight")},
        "creator": header.get("creator"),
        "exportContract": {"major": EXPORT_CONTRACT_MAJOR, "minor": EXPORT_CONTRACT_MINOR},
        "slides": slides,
        "playerMarkers": required_player_markers(player_js),
    }


def capability_row(
    *,
    ordinal: int,
    skipped: bool,
    magic_move: bool,
    has_character: bool,
    has_build_out: bool,
    has_movie: bool,
    has_line_draw: bool,
    iwa_clicks: int,
    kpf_clicks: int | None,
    capture: dict[str, Any] | None,
    alpha: dict[str, Any] | None,
    canvas: tuple[float, float] | None = None,
) -> dict[str, Any]:
    refusals: list[str] = []
    if skipped:
        refusals.append("skipped in source; HTML export omits this slide")
    if magic_move:
        refusals.append("Magic Move — unproven for isolated-slide alpha export")
    if has_character:
        refusals.append("character effect — not demonstrated on Alpha_DSK")
    if has_build_out:
        refusals.append("build-out — not demonstrated on Alpha_DSK")
    if canvas and canvas[0] > 1920:
        refusals.append(f"canvas {int(canvas[0])}×{int(canvas[1])} is not the DSK 1920×1080 contract")
    if has_movie:
        refusals.append("movie-start / mixed video — retain opaque clip behaviour until separately proven")
    identity = (capture or {}).get("identity") if capture else None
    identity_pass = bool(identity and identity.get("pass"))
    if not skipped and capture is not None:
        if identity is None:
            refusals.append("identity not recorded")
        elif not identity_pass:
            detail = "; ".join(identity.get("reasons") or [identity.get("reason") or "fail"])
            refusals.append(f"identity: {detail}")
        click = capture.get("click") or {}
        if click.get("stillIdentifiable") is False:
            refusals.append("click settled plate is no longer this slide")
    if alpha and alpha.get("source") == "object-canvases":
        refusals.append("object-composite cannot prove composed alpha")
    if alpha and not alpha.get("pass") and not skipped and not has_movie:
        refusals.append("alpha statistics did not pass")
    timing = (capture or {}).get("timing") if capture else None
    timing_pass = bool(timing and timing.get("pass"))
    page_alpha = bool(alpha and alpha.get("source") != "object-canvases" and alpha.get("pass"))
    if capture and capture.get("error"):
        refusals.append(f"capture: {capture['error']}")
    has_click = (iwa_clicks > 0 or (kpf_clicks or 0) > 0) and not has_movie
    if has_click and capture is not None and not timing_pass:
        refusals.append("timing not proven on changing progress")
    static = (
        not skipped
        and not has_movie
        and identity_pass
        and page_alpha
        and not any(
            item.startswith("identity:")
            or item.startswith("capture:")
            or "object-composite" in item
            or "alpha statistics" in item
            or "Magic Move" in item
            or "character effect" in item
            or "build-out" in item
            or item.startswith("canvas ")
            or item.startswith("identity not")
            for item in refusals
        )
    )
    animated = static and has_click and timing_pass
    return {
        "originalOrdinal": ordinal,
        "skipped": skipped,
        "iwaOperatorClicks": iwa_clicks,
        "kpfOperatorClicks": kpf_clicks,
        "lineDraw": has_line_draw,
        "movieStart": has_movie,
        "magicMove": magic_move,
        "characterEffect": has_character,
        "buildOut": has_build_out,
        "identity": bool(identity_pass) if not skipped else False,
        "supportedAnimatedAlpha": animated,
        "supportedStaticAlpha": static,
        "refusals": refusals,
    }


def write_json(path: Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# Exact full-canvas black fill measured on Keynote HTML PDF textures (Genesis + Minimal Alpha_DSK).
_BG_FILL_SOLO = re.compile(
    rb"^q Q q /Cs1 cs 0 0 0 sc 0 1080 m 1920 1080 l 1920 0 l 0 0 l h f Q\s*"
)
# Same fill when the trailing Q is deferred (content continues in the same q-block).
_BG_FILL_INLINE = re.compile(
    rb"^(q Q q) /Cs1 cs 0 0 0 sc 0 1080 m 1920 1080 l 1920 0 l 0 0 l h f "
)


def _pdf_page_raw(page: Any) -> bytes:
    contents = page.get_contents()
    if contents is None:
        return b""
    if isinstance(contents, list):
        return b"".join(c.get_data() for c in contents)
    return contents.get_data()


def strip_pdf_page_bg_fill(page: Any) -> dict[str, Any]:
    """Remove only the identified full-slide black fill. Refuses ambiguous prefixes."""
    from pypdf.generic import DecodedStreamObject, NameObject

    raw = _pdf_page_raw(page)
    solo = _BG_FILL_SOLO.match(raw)
    if solo:
        rest = raw[solo.end() :]
        new_stream = DecodedStreamObject()
        new_stream.set_data(rest if rest else b"q Q\n")
        page[NameObject("/Contents")] = new_stream
        return {
            "stripped": True,
            "kind": "solo",
            "removedBytes": solo.end(),
            "remainingBytes": len(rest),
        }
    inline = _BG_FILL_INLINE.match(raw)
    if inline:
        rest = inline.group(1) + b" " + raw[inline.end() :]
        new_stream = DecodedStreamObject()
        new_stream.set_data(rest)
        page[NameObject("/Contents")] = new_stream
        return {
            "stripped": True,
            "kind": "inline",
            "removedBytes": inline.end() - len(inline.group(1)),
            "remainingBytes": len(rest),
        }
    return {
        "stripped": False,
        "reason": "leading ops do not match identified bg fill",
        "prefix": raw[:90].decode("latin1", "replace"),
    }


def rewrite_pdfp_from_pdf(pdf_path: Path, pdfp_path: Path) -> dict[str, Any]:
    """Embed current PDF bytes into the file:// local_pdf companion."""
    import base64

    pdf_path = Path(pdf_path)
    pdfp_path = Path(pdfp_path)
    if not pdfp_path.is_file():
        return {"rewrote": False, "reason": "pdfp missing"}
    pdf = pdf_path.read_bytes()
    text = pdfp_path.read_text(encoding="utf-8")
    m = re.match(r"local_pdf\(\s*(\{.*\})\s*\);?\s*$", text, re.S)
    if not m:
        return {"rewrote": False, "reason": "unexpected pdfp format", "head": text[:80]}
    obj = json.loads(m.group(1))
    before = base64.b64decode(obj["pdf"])
    obj["pdf"] = base64.b64encode(pdf).decode("ascii")
    pdfp_path.write_text("local_pdf( " + json.dumps(obj, indent=2) + " );\n", encoding="utf-8")
    after = base64.b64decode(
        json.loads(re.match(r"local_pdf\(\s*(\{.*\})\s*\);?\s*$", pdfp_path.read_text(), re.S).group(1))["pdf"]
    )
    return {
        "rewrote": True,
        "beforeSha256": hashlib.sha256(before).hexdigest(),
        "afterSha256": hashlib.sha256(after).hexdigest(),
        "matchesPdf": after == pdf,
        "bytes": len(after),
    }


def strip_export_pdf_bg_fills(export_root: Path) -> dict[str, Any]:
    """Strip identified full-slide black fills from every PDF under an HTML export."""
    from pypdf import PdfReader, PdfWriter

    export_root = Path(export_root)
    reports = []
    for pdf_path in sorted(export_root.rglob("*.pdf")):
        if pdf_path.is_symlink():
            continue
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter()
        page_reports = []
        any_stripped = False
        for i, page in enumerate(reader.pages):
            info = {"pageIndex": i, **strip_pdf_page_bg_fill(page)}
            if info.get("stripped"):
                any_stripped = True
            page_reports.append(info)
            writer.add_page(page)
        if any_stripped:
            with pdf_path.open("wb") as fh:
                writer.write(fh)
            pdfp = pdf_path.with_suffix(".pdfp")
            pdfp_info = rewrite_pdfp_from_pdf(pdf_path, pdfp) if pdfp.is_file() else {"rewrote": False}
            reports.append(
                {
                    "pdf": str(pdf_path.relative_to(export_root)),
                    "strippedPages": [p["pageIndex"] for p in page_reports if p.get("stripped")],
                    "pages": page_reports,
                    "pdfp": pdfp_info,
                    "sha256": file_sha256(pdf_path),
                }
            )
        else:
            reports.append(
                {
                    "pdf": str(pdf_path.relative_to(export_root)),
                    "strippedPages": [],
                    "pages": page_reports,
                    "skipped": True,
                }
            )
    return {
        "exportRoot": str(export_root),
        "pdfCount": sum(1 for _ in export_root.rglob("*.pdf")),
        "rewritten": [r for r in reports if r.get("strippedPages")],
        "reports": reports,
    }
