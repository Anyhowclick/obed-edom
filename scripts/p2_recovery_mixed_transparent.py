#!/usr/bin/env python3
"""Evidence-first Alpha_DSK mixed-clip transparency probe (recovery follow-up).

Keeps Alpha_DSK slides 6–8 (multi-slide movie clips + overlays) together on a
LiveBatch scratch. Does **not** use DSK_Gen_Export_Input / FW 11–13 — that wall
deck has no transparency by construction.

Verifies empty ROIs from movie/overlay geometry, isolates slide fill (No Fill),
exports via UI ProRes 4444 + transparent backgrounds, and scores sparse frames
around movie-start / transitions — without refuse-by-construction.

Does not implement P3. Never writes owner source decks.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom.dsk_live import LiveBatch, keynote_app, keynote_running, run_osascript  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    file_identity,
    inventory_deck,
    load_rgba,
    write_json,
)
from obed_edom.iwa_geometry import compose_geometry  # noqa: E402
from obed_edom.iwa_movies import movie_archives  # noqa: E402
from obed_edom.iwa_runs import _load_deck  # noqa: E402
from obed_edom.maps_movie import ffmpeg_exe  # noqa: E402
from p2_recovery_native_ui import (  # noqa: E402
    _run_osascript,
    _ui_click_next_and_save,
    _ui_configure_transparent_export,
    _ui_dump_script,
    _ui_open_export_movie,
)

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key")
OUT = REPO / "output" / "p2-recovery" / "mixed-11-13-transparent"
# Alpha_DSK multi-slide movie clips (not FW DSK_Gen_Export_Input 11–13 — that deck is opaque wall).
KEEP = (6, 7, 8)
EMPTY_ALPHA_MAX = 2
OPAQUE_ALPHA_MIN = 250
EMPTY_FRAC_PASS = 0.50
FOOTPRINT_OPAQUE_PASS = 0.80
OVERLAY_ALPHA_PASS = 0.50
MAX_SPARSE_FRAMES = 24


def _quit_if_idle() -> None:
    if not keynote_running():
        return
    bid = keynote_app.bundle_id()
    run_osascript(
        f'''
tell application id "{bid}"
  if (count of documents) is 0 then quit
end tell
'''
    )


def _clamp_rect(x: float, y: float, w: float, h: float, cw: float, ch: float) -> dict | None:
    x0 = max(0.0, x)
    y0 = max(0.0, y)
    x1 = min(cw, x + w)
    y1 = min(ch, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def _union_mask(h: int, w: int, rects: list[dict], margin: int = 0) -> np.ndarray:
    mask = np.zeros((h, w), dtype=bool)
    for r in rects:
        x0 = max(0, int(r["x"]) - margin)
        y0 = max(0, int(r["y"]) - margin)
        x1 = min(w, int(r["x"] + r["width"]) + margin)
        y1 = min(h, int(r["y"] + r["height"]) + margin)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _empty_patches_from_mask(empty: np.ndarray, patch: int = 48, max_patches: int = 12) -> list[dict]:
    """Sample non-overlapping empty patches from a boolean empty mask."""
    h, w = empty.shape
    patches: list[dict] = []
    step = max(patch, 64)
    for y in range(0, h - patch + 1, step):
        for x in range(0, w - patch + 1, step):
            block = empty[y : y + patch, x : x + patch]
            if block.mean() >= 0.95:
                patches.append({"x": x, "y": y, "width": patch, "height": patch})
                if len(patches) >= max_patches:
                    return patches
    # Fallback: any high-empty locations via coarse grid
    if not patches:
        ys, xs = np.where(empty)
        if len(ys):
            for i in np.linspace(0, len(ys) - 1, num=min(max_patches, 8), dtype=int):
                y = int(max(0, min(h - patch, ys[i] - patch // 2)))
                x = int(max(0, min(w - patch, xs[i] - patch // 2)))
                patches.append({"x": x, "y": y, "width": min(patch, w - x), "height": min(patch, h - y)})
    return patches


def _build_rois(source: Path) -> dict:
    inv = inventory_deck(source)
    cw = float(inv["canvas"]["width"])
    ch = float(inv["canvas"]["height"])
    objects = _load_deck(source)
    if isinstance(objects, tuple):
        objects = objects[0]
    archives = movie_archives(source)
    slides_out = []
    for s in inv["slides"]:
        if s["originalOrdinal"] not in KEEP:
            continue
        sid = str(s["slideId"])
        slide_obj = objects.get(sid) or {}
        geos = compose_geometry(slide_obj, objects) if slide_obj else []
        movies = []
        for a in archives:
            if f"Slide-{sid}.iwa" not in a["member"]:
                continue
            vis = _clamp_rect(a["x"], a["y"], a["w"], a["h"], cw, ch)
            if not vis:
                continue
            movies.append(
                {
                    "id": a["id"],
                    "raw": {"x": a["x"], "y": a["y"], "width": a["w"], "height": a["h"]},
                    "visible": vis,
                    "endTime": a.get("endTime"),
                    "playsAcrossSlides": a.get("playsAcrossSlides"),
                }
            )
        overlays = []
        side_panels = []
        fills = []
        for g in geos:
            kind = str(g.get("kind") or "")
            rect = _clamp_rect(float(g["x"]), float(g["y"]), float(g["w"]), float(g["h"]), cw, ch)
            if not rect:
                continue
            entry = {
                "id": g.get("id"),
                "kind": kind,
                "rect": rect,
                "text": (g.get("text") or "")[:80],
            }
            area = rect["width"] * rect["height"]
            if kind == "movie":
                continue
            # Wall side plates are ~1920×1080 on a 7680 canvas (left/right thirds).
            if kind == "image" and rect["width"] >= 1800 and rect["height"] >= 0.9 * ch:
                side_panels.append(entry)
            elif kind == "shape" and area >= 0.5 * (cw / 3) * ch:
                fills.append(entry)
            else:
                overlays.append(entry)

        movie_rects = [m["visible"] for m in movies]
        overlay_rects = [o["rect"] for o in overlays]
        side_rects = [p["rect"] for p in side_panels]
        fill_rects = [f["rect"] for f in fills]
        content = movie_rects + overlay_rects + side_rects + fill_rects
        h_i, w_i = int(ch), int(cw)
        content_mask = _union_mask(h_i, w_i, content, margin=2)
        empty_mask = ~content_mask
        empty_area = int(empty_mask.sum())
        empty_patches = _empty_patches_from_mask(empty_mask) if empty_area else []
        slides_out.append(
            {
                "originalOrdinal": s["originalOrdinal"],
                "slideId": sid,
                "identity": s.get("identity"),
                "magicMove": bool(s.get("magicMove")),
                "hasMovieStart": bool(s.get("hasMovieStart")),
                "transition": s.get("transition"),
                "builds": s.get("builds"),
                "movies": movies,
                "overlays": overlays,
                "sidePanels": side_panels,
                "fills": fills,
                "movieRects": movie_rects,
                "overlayRects": overlay_rects,
                "sideRects": side_rects,
                "emptyAreaPx": empty_area,
                "emptyFrac": float(empty_area) / float(h_i * w_i),
                "emptyPatches": empty_patches,
                "emptyRoiEstablished": bool(empty_patches) and empty_area >= patch_area_min(empty_patches),
            }
        )
    return {
        "canvas": {"width": cw, "height": ch},
        "shippingContractNote": (
            "Alpha_DSK 1920×1080 — alpha-capable DSK fixture. "
            "FW DSK_Gen_Export_Input slides 11–13 are opaque wall and are not used here."
        ),
        "slides": slides_out,
    }


def patch_area_min(patches: list[dict]) -> int:
    return 32 * 32


def _score_regions(arr: np.ndarray, movie_rects: list[dict], overlay_rects: list[dict], empty_patches: list[dict]) -> dict:
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]

    def region_stats(rects: list[dict]) -> dict | None:
        if not rects:
            return None
        mask = _union_mask(h, w, rects, margin=0)
        if not mask.any():
            return None
        vals = alpha[mask]
        return {
            "alphaMin": int(vals.min()),
            "alphaMean": float(vals.mean()),
            "transparentFrac": float((vals <= EMPTY_ALPHA_MAX).mean()),
            "opaqueFrac": float((vals >= OPAQUE_ALPHA_MIN).mean()),
            "px": int(mask.sum()),
        }

    empty_stats = None
    if empty_patches:
        empty_stats = region_stats(empty_patches)

    return {
        "global": {
            "alphaMin": int(alpha.min()),
            "transparentFrac": float((alpha <= EMPTY_ALPHA_MAX).mean()),
            "opaqueFrac": float((alpha >= OPAQUE_ALPHA_MIN).mean()),
        },
        "movieFootprint": region_stats(movie_rects),
        "overlays": region_stats(overlay_rects),
        "empty": empty_stats,
    }


def _analyze_png(path: Path, slide_roi: dict) -> dict:
    arr = load_rgba(path)
    scores = _score_regions(
        arr,
        slide_roi.get("movieRects") or [],
        slide_roi.get("overlayRects") or [],
        slide_roi.get("emptyPatches") or [],
    )
    per_movie = []
    for m in slide_roi.get("movies") or []:
        st = _score_regions(arr, [m["visible"]], [], [])
        per_movie.append({"id": m["id"], **(st["movieFootprint"] or {})})
    # Text/label overlays only — decorative shapes often have partial alpha by design.
    text_rects = [o["rect"] for o in (slide_roi.get("overlays") or []) if o.get("kind") == "text"]
    text_overlay = _score_regions(arr, [], text_rects, [])["overlays"] if text_rects else None
    return {
        "path": str(path),
        "name": path.name,
        "shape": list(arr.shape[:2]),
        **scores,
        "perMovie": per_movie,
        "textOverlays": text_overlay,
    }


def _slim_script(bid: str, scratch: Path) -> str:
    keep = ", ".join(str(i) for i in KEEP)
    return f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 1800 seconds
    activate
    set theDoc to open POSIX file "{scratch}"
    delay 8
    tell theDoc
      set n to count of slides
      repeat with i from n to 1 by -1
        if {{{keep}}} does not contain i then delete slide i
      end repeat
    end tell
    delay 2
    save theDoc
    delay 1
  end timeout
end tell
end using terms from
'''


def _export_stages_script(bid: str, scratch: Path, dest_dir: Path) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    return f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 1800 seconds
    activate
    set theDoc to open POSIX file "{scratch}"
    delay 5
    export theDoc to POSIX file "{dest_dir}" as slide images with properties {{image format:PNG, skipped slides:false, all stages:true}}
    delay 2
    close theDoc saving no
  end timeout
end tell
end using terms from
'''


def _nofill_ui_script() -> str:
    return '''
tell application id "com.apple.Keynote" to activate
delay 0.4
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    delay 0.3
    set report to ""
    -- Select each slide and apply Format > Background > No Fill
    repeat with i from 1 to 3
      try
        keystroke "1" using {command down, option down} -- navigator focus best-effort
      end try
      delay 0.2
      -- Click slide i in slide list is unreliable; use AppleScript selection via Keynote
    end repeat
  end tell
end tell
tell application id "com.apple.Keynote"
  tell document 1
    repeat with i from 1 to (count of slides)
      set current slide to slide i
    end repeat
  end tell
end tell
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    set errs to ""
    repeat with i from 1 to 3
      tell application id "com.apple.Keynote"
        tell document 1 to set current slide to slide i
      end tell
      delay 0.5
      try
        click menu item "No Fill" of menu 1 of menu item "Background" of menu 1 of menu bar item "Format" of menu bar 1
        set report to report & "slide" & i & ":nofill;"
        delay 0.3
      on error errMsg
        set errs to errs & "slide" & i & ":" & errMsg & ";"
      end try
    end repeat
    if errs is not "" then set report to report & "errs:" & errs
    if report is "" then set report to "nofill-no-action"
    return report
  end tell
end tell
'''


def _nofill_and_save(bid: str, scratch: Path) -> str:
    return f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 600 seconds
    activate
    set theDoc to open POSIX file "{scratch}"
    delay 4
  end timeout
end tell
end using terms from
'''


def _assign_stage_pngs(pngs: list[Path], rois: dict) -> dict[int, list[Path]]:
    """Map exported stage PNGs onto original ordinals 11–13 by name or emission order."""
    buckets: dict[int, list[Path]] = {6: [], 7: [], 8: []}
    named = False
    for p in pngs:
        n = p.name.lower()
        for token, ord_ in (("001", 6), ("01.", 6), ("002", 7), ("02.", 7), ("003", 8), ("03.", 8)):
            if token in n:
                buckets[ord_].append(p)
                named = True
                break
    if named and any(buckets.values()):
        return buckets
    ordered = sorted(pngs)
    if len(ordered) >= 6:
        buckets[6] = ordered[0:2]
        buckets[7] = ordered[2:4]
        buckets[8] = ordered[4:6]
    elif len(ordered) == 3:
        buckets[6] = [ordered[0]]
        buckets[7] = [ordered[1]]
        buckets[8] = [ordered[2]]
    else:
        n = len(ordered)
        for i, ord_ in enumerate(KEEP):
            a = (i * n) // 3
            b = ((i + 1) * n) // 3
            buckets[ord_] = ordered[a:b]
    return buckets


def _event_times_s(rois: dict, duration_s: float) -> list[dict]:
    """Build sparse sample times from transition + movie durations (best-effort timeline)."""
    slides = rois["slides"]
    events: list[dict] = []
    t = 0.0
    for i, s in enumerate(slides):
        trans = (s.get("transition") or {}).get("duration") or 0.0
        magic = bool(s.get("magicMove"))
        movie_ends = [float(m["endTime"]) for m in s.get("movies") or [] if m.get("endTime")]
        clip = max(movie_ends) if movie_ends else 8.0
        # transition into slide
        if i > 0:
            mid = t + trans / 2.0
            events.append(
                {
                    "t": mid,
                    "label": f"transition-mid-{s['originalOrdinal']}",
                    "kind": "magicMove" if magic else "transition",
                    "slide": s["originalOrdinal"],
                }
            )
            t += trans
        events.append({"t": t + 0.15, "label": f"slide-{s['originalOrdinal']}-start", "kind": "movie-start", "slide": s["originalOrdinal"]})
        events.append({"t": t + min(1.0, clip * 0.15), "label": f"slide-{s['originalOrdinal']}-early", "kind": "movie-start", "slide": s["originalOrdinal"]})
        events.append({"t": t + clip * 0.5, "label": f"slide-{s['originalOrdinal']}-mid", "kind": "movie-mid", "slide": s["originalOrdinal"]})
        t += clip
    # Clamp / densify to duration
    if duration_s > 0:
        for e in events:
            e["t"] = float(min(max(0.0, e["t"]), max(0.0, duration_s - 0.05)))
        # Add evenly spaced backups if too few unique times
        uniq = sorted({round(e["t"], 3) for e in events})
        if len(uniq) < 8:
            for x in np.linspace(0.1, max(0.1, duration_s - 0.1), num=8):
                events.append({"t": float(x), "label": f"grid-{x:.2f}", "kind": "grid", "slide": None})
    # Dedupe by rounded t, keep first label, cap
    seen = set()
    out = []
    for e in sorted(events, key=lambda z: z["t"]):
        key = round(e["t"], 2)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
        if len(out) >= MAX_SPARSE_FRAMES:
            break
    return out


def _ffprobe_duration(movie: Path) -> float:
    exe = ffmpeg_exe()
    if not exe:
        return 0.0
    # imageio-ffmpeg ships ffmpeg only; parse duration from ffmpeg -i stderr.
    proc = subprocess.run([exe, "-i", str(movie)], capture_output=True, text=True)
    import re

    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
    if not m:
        return 0.0
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def _extract_sparse_frames(movie: Path, events: list[dict], dest: Path) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    exe = ffmpeg_exe()
    if not exe:
        return [{"error": "ffmpeg missing"}]
    frames = []
    for i, e in enumerate(events):
        out = dest / f"t{e['t']:07.2f}_{e['label']}.png".replace(" ", "_")
        proc = subprocess.run(
            [exe, "-y", "-ss", f"{e['t']:.3f}", "-i", str(movie), "-frames:v", "1", "-pix_fmt", "rgba", str(out)],
            capture_output=True,
            text=True,
        )
        frames.append(
            {
                **e,
                "path": str(out) if out.is_file() else None,
                "ok": out.is_file() and out.stat().st_size > 0,
                "ffmpegRc": proc.returncode,
                "stderr": (proc.stderr or "")[-300:],
            }
        )
    return frames


def _gate_from_evidence(rois: dict, stage_scores: dict, movie_frame_scores: list[dict], shipping_note: str) -> dict:
    """Derive pass only from measurements — movie-start / Magic Move are labels, not refusals."""
    per_slide = []
    for s in rois["slides"]:
        ord_ = s["originalOrdinal"]
        empty_est = bool(s.get("emptyRoiEstablished"))
        stage = stage_scores.get(ord_) or []
        frames = [f for f in movie_frame_scores if f.get("slide") == ord_]

        def empty_ok(rows: list[dict]) -> bool | None:
            if not empty_est:
                return None
            ok_rows = []
            for r in rows:
                e = r.get("empty")
                if not e:
                    continue
                ok_rows.append(e["transparentFrac"] >= EMPTY_FRAC_PASS and e["alphaMin"] <= EMPTY_ALPHA_MAX)
            if not ok_rows:
                return None
            return all(ok_rows)

        def footprint_ok(rows: list[dict]) -> bool | None:
            movie_ids = [m["id"] for m in s.get("movies") or []]
            if not movie_ids:
                return None
            # Each movie must be opaque in at least one sampled frame ( staggered starts OK).
            seen_ok = {mid: False for mid in movie_ids}
            for r in rows:
                for pm in r.get("perMovie") or []:
                    mid = pm.get("id")
                    if mid in seen_ok and pm.get("opaqueFrac", 0) >= FOOTPRINT_OPAQUE_PASS:
                        seen_ok[mid] = True
            if not any(r.get("perMovie") for r in rows):
                # Fallback: union footprint on any frame
                vals = [
                    (r.get("movieFootprint") or {}).get("opaqueFrac", 0) >= FOOTPRINT_OPAQUE_PASS
                    for r in rows
                    if r.get("movieFootprint")
                ]
                return any(vals) if vals else None
            return all(seen_ok.values())

        def overlay_ok(rows: list[dict]) -> bool | None:
            text_rects = [o for o in (s.get("overlays") or []) if o.get("kind") == "text"]
            if not text_rects:
                return None
            vals = []
            for r in rows:
                o = r.get("textOverlays") or r.get("overlays")
                if o:
                    vals.append(
                        o.get("opaqueFrac", 0) >= OVERLAY_ALPHA_PASS or o.get("alphaMean", 0) >= 128
                    )
            if not vals:
                return None
            return any(vals)  # overlays visible in at least one event window

        rows = stage + frames
        e_ok = empty_ok(rows)
        f_ok = footprint_ok(frames if frames else stage)
        o_ok = overlay_ok(rows)
        # Pass when every established measure is True
        checks = [c for c in (e_ok, f_ok, o_ok) if c is not None]
        slide_pass = bool(checks) and all(checks)
        per_slide.append(
            {
                "originalOrdinal": ord_,
                "fixture": {
                    "magicMove": s["magicMove"],
                    "hasMovieStart": s["hasMovieStart"],
                    "transition": s.get("transition"),
                },
                "emptyRoiEstablished": empty_est,
                "emptyAreaPx": s.get("emptyAreaPx"),
                "emptyFrac": s.get("emptyFrac"),
                "measures": {
                    "emptyCanvas": e_ok,
                    "movieFootprintOpaque": f_ok,
                    "overlaysPreserved": o_ok,
                },
                "pass": slide_pass,
                "notes": []
                if empty_est
                else ["no independent empty ROI after content union — empty gate not applicable"],
            }
        )

    any_pass = any(s["pass"] for s in per_slide)
    all_pass = all(s["pass"] for s in per_slide) and bool(per_slide)
    # supportedTransparentMixed: all slides pass AND empty established on each that claims empty
    supported = all_pass and all(
        (s["emptyRoiEstablished"] and s["measures"]["emptyCanvas"] is True) for s in per_slide
    )
    return {
        "shippingContractNote": shipping_note,
        "slides": per_slide,
        "anySlidePass": any_pass,
        "allSlidesPass": all_pass,
        "supportedTransparentMixed": supported,
        "pass": supported,
    }


def main() -> int:
    out = OUT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    started = time.monotonic()
    before = file_identity(SOURCE)
    write_json(out / "fingerprints-before.json", before.as_dict())

    rois = _build_rois(SOURCE)
    write_json(out / "rois.json", rois)
    roi_by_ord = {s["originalOrdinal"]: s for s in rois["slides"]}
    print(f"ROIs: canvas={rois['canvas']} slides={len(rois['slides'])}")
    for s in rois["slides"]:
        print(
            f"  slide {s['originalOrdinal']}: movies={len(s['movies'])} overlays={len(s['overlays'])} "
            f"emptyFrac={s['emptyFrac']:.4f} emptyPatches={len(s['emptyPatches'])} established={s['emptyRoiEstablished']}"
        )

    report: dict = {
        "probe": "p2_recovery_mixed_transparent",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": before.as_dict(),
        "canvas": rois["canvas"],
        "shippingContractNote": rois["shippingContractNote"],
        "p3": "still unwired",
    }

    _quit_if_idle()
    stages_before = out / "stages-before-nofill"
    stages_after = out / "stages-after-nofill"
    movie_path = out / "movies" / "mixed-11-13-ui-transparent-prores4444.mov"
    movie_path.parent.mkdir(parents=True, exist_ok=True)

    stage_scores_before: dict[int, list[dict]] = {6: [], 7: [], 8: []}
    stage_scores_after: dict[int, list[dict]] = {6: [], 7: [], 8: []}
    nofill_report: dict = {"skipped": True}
    ui_report: dict = {}
    sparse: list[dict] = []
    frame_scores: list[dict] = []

    with LiveBatch(SOURCE, out / "batch", log=print) as batch:
        assert batch.scratch is not None and batch.work is not None
        bid = keynote_app.bundle_id()
        scratch = batch.scratch

        slim = batch.work / "slim.applescript"
        slim.write_text(_slim_script(bid, scratch), encoding="utf-8")
        proc = batch.run(slim)
        report["slim"] = {"ok": proc.returncode == 0, "stderr": (proc.stderr or "")[-500:]}
        if proc.returncode != 0:
            report["stopped"] = "slim failed"
            write_json(out / "report.json", report)
            return 1

        # Rebuild ROIs from slim scratch (ordinals become 1..3 but geometry same)
        # Keep original-ordinal ROI map from source inventory — geometry unchanged by slim.

        st = batch.work / "stages_before.applescript"
        st.write_text(_export_stages_script(bid, scratch, stages_before), encoding="utf-8")
        proc = batch.run(st)
        pngs = sorted(stages_before.rglob("*.png")) if stages_before.exists() else []
        report["stageExportBefore"] = {"ok": proc.returncode == 0, "pngCount": len(pngs), "stderr": (proc.stderr or "")[-400:]}
        buckets = _assign_stage_pngs(pngs, rois)
        for ord_, paths in buckets.items():
            for p in paths:
                stage_scores_before[ord_].append(_analyze_png(p, roi_by_ord[ord_]))
        write_json(out / "stage-scores-before-nofill.json", stage_scores_before)

        empty_opaque = False
        for ord_, rows in stage_scores_before.items():
            s = roi_by_ord[ord_]
            if not s["emptyRoiEstablished"]:
                # If no empty ROI, treat full-canvas opaque as fill/layout candidate
                for r in rows:
                    if r["global"]["transparentFrac"] < 0.01:
                        empty_opaque = True
            else:
                for r in rows:
                    e = r.get("empty") or {}
                    if e.get("transparentFrac", 1.0) < 0.05:
                        empty_opaque = True

        # Always attempt No Fill — UI transparent checkbox often requires it
        open_sc = batch.work / "open_for_nofill.applescript"
        open_sc.write_text(_nofill_and_save(bid, scratch), encoding="utf-8")
        batch.run(open_sc)
        nf = _run_osascript(_nofill_ui_script(), batch.work / "nofill_ui.applescript")
        # Save scratch after nofill
        save_sc = batch.work / "save_nofill.applescript"
        save_sc.write_text(
            f'''
tell application id "{bid}"
  if (count of documents) > 0 then
    save document 1
    delay 1
  end if
end tell
''',
            encoding="utf-8",
        )
        batch.run(save_sc)
        nofill_report = {
            "attempted": True,
            "emptyOpaqueBefore": empty_opaque,
            "returncode": nf.returncode,
            "stdout": (nf.stdout or "").strip(),
            "stderr": (nf.stderr or "")[-500:],
        }
        report["noFill"] = nofill_report

        st2 = batch.work / "stages_after.applescript"
        st2.write_text(_export_stages_script(bid, scratch, stages_after), encoding="utf-8")
        proc = batch.run(st2)
        pngs2 = sorted(stages_after.rglob("*.png")) if stages_after.exists() else []
        report["stageExportAfter"] = {"ok": proc.returncode == 0, "pngCount": len(pngs2), "stderr": (proc.stderr or "")[-400:]}
        buckets2 = _assign_stage_pngs(pngs2, rois)
        for ord_, paths in buckets2.items():
            for p in paths:
                stage_scores_after[ord_].append(_analyze_png(p, roi_by_ord[ord_]))
        write_json(out / "stage-scores-after-nofill.json", stage_scores_after)

        # Classify fill isolation from before/after empty (or global) alpha
        fill_class = "unchanged_opaque"
        for ord_ in KEEP:
            before_rows = stage_scores_before.get(ord_) or []
            after_rows = stage_scores_after.get(ord_) or []
            if not before_rows or not after_rows:
                continue
            b = before_rows[0]["global"]["transparentFrac"]
            a = after_rows[0]["global"]["transparentFrac"]
            if a - b > 0.05:
                fill_class = "nofill_increased_transparency"
                break
            be = (before_rows[0].get("empty") or {}).get("transparentFrac")
            ae = (after_rows[0].get("empty") or {}).get("transparentFrac")
            if be is not None and ae is not None and ae - be > 0.05:
                fill_class = "nofill_increased_empty_roi_transparency"
                break
        if empty_opaque and fill_class == "unchanged_opaque":
            fill_class = "slide_fill_or_opaque_layout"
        report["fillIsolation"] = {"class": fill_class, "emptyOpaqueBefore": empty_opaque}

        # --- UI transparent Movie export ---
        # Ensure doc open
        open2 = batch.work / "open_for_ui.applescript"
        open2.write_text(_nofill_and_save(bid, scratch), encoding="utf-8")
        batch.run(open2)

        if movie_path.exists():
            movie_path.unlink()
        open_ui = _run_osascript(_ui_open_export_movie(), batch.work / "ui_open.applescript")
        dump = _run_osascript(_ui_dump_script(), batch.work / "ui_dump.applescript")
        (out / "ui").mkdir(exist_ok=True)
        (out / "ui" / "export-sheet-dump.txt").write_text((dump.stdout or "") + (dump.stderr or ""), encoding="utf-8")
        cfg = _run_osascript(_ui_configure_transparent_export(), batch.work / "ui_cfg.applescript")
        save = _run_osascript(_ui_click_next_and_save(movie_path), batch.work / "ui_save.applescript")

        # Wait for export file (may land in scratch dir)
        deadline = time.monotonic() + 900
        found = None
        candidates = [
            movie_path,
            scratch.parent / movie_path.name,
            Path(scratch).parent / movie_path.name,
            SOURCE.parent / movie_path.name,
        ]
        # Also watch movies dir for any new .mov/.m4v
        while time.monotonic() < deadline:
            for c in list(candidates) + list(movie_path.parent.glob("*.mov")) + list(movie_path.parent.glob("*.m4v")):
                if c.is_file() and c.stat().st_size > 1_000_000:
                    found = c
                    break
            if found:
                # wait until size stable
                sz1 = found.stat().st_size
                time.sleep(3)
                sz2 = found.stat().st_size
                if sz1 == sz2 and sz1 > 1_000_000:
                    break
                found = None
            time.sleep(2)

        if found and found.resolve() != movie_path.resolve():
            if movie_path.exists():
                movie_path.unlink()
            shutil.move(str(found), str(movie_path))
            found = movie_path

        ui_report = {
            "openRc": open_ui.returncode,
            "openOut": (open_ui.stdout or "")[-200:],
            "cfgRc": cfg.returncode,
            "cfgOut": (cfg.stdout or "").strip(),
            "cfgErr": (cfg.stderr or "")[-400:],
            "saveRc": save.returncode,
            "saveOut": (save.stdout or "").strip(),
            "saveErr": (save.stderr or "")[-400:],
            "ok": found is not None and found.is_file(),
            "movie": str(found) if found else None,
            "bytes": found.stat().st_size if found and found.is_file() else 0,
            "note": "UI Export with transparent backgrounds — operator Enter may be required if save panel AX fails",
        }
        report["uiMovie"] = ui_report

        # Close without saving further
        close = batch.work / "close.applescript"
        close.write_text(
            f'''
tell application id "{bid}"
  repeat while (count of documents) > 0
    close document 1 saving no
  end repeat
end tell
''',
            encoding="utf-8",
        )
        batch.run(close)

    # Sparse decode + score
    if ui_report.get("ok"):
        dur = _ffprobe_duration(Path(ui_report["movie"]))
        report["movieDurationS"] = dur
        events = _event_times_s(rois, dur if dur > 0 else 120.0)
        # If estimated timeline >> actual duration, rebuild on duration grids
        if dur > 0 and events and events[-1]["t"] > dur * 1.2:
            events = []
            # Map thirds of timeline to slides 11–13
            for i, ord_ in enumerate(KEEP):
                base = dur * (i / 3.0)
                span = dur / 3.0
                for frac, kind in ((0.05, "movie-start"), (0.15, "movie-start"), (0.5, "movie-mid"), (0.85, "movie-late")):
                    events.append(
                        {
                            "t": min(dur - 0.05, base + span * frac),
                            "label": f"slide-{ord_}-{kind}-{frac}",
                            "kind": kind,
                            "slide": ord_,
                        }
                    )
                if i > 0:
                    events.append(
                        {
                            "t": min(dur - 0.05, base + 0.4),
                            "label": f"transition-into-{ord_}",
                            "kind": "magicMove",
                            "slide": ord_,
                        }
                    )
            events = sorted(events, key=lambda e: e["t"])[:MAX_SPARSE_FRAMES]
        write_json(out / "sparse-events.json", events)
        sparse = _extract_sparse_frames(Path(ui_report["movie"]), events, out / "frames")
        for fr in sparse:
            if not fr.get("ok") or not fr.get("path"):
                continue
            slide = fr.get("slide")
            if slide not in roi_by_ord:
                # assign by timeline third
                if dur > 0:
                    slide = KEEP[min(2, int(3 * fr["t"] / dur))]
                else:
                    slide = 11
            scored = _analyze_png(Path(fr["path"]), roi_by_ord[slide])
            scored.update({"t": fr["t"], "label": fr["label"], "kind": fr["kind"], "slide": slide})
            frame_scores.append(scored)
        write_json(out / "frame-scores.json", frame_scores)
        report["sparseFrameCount"] = len(frame_scores)
    else:
        report["sparseFrameCount"] = 0

    # Prefer after-nofill stages for gating when present
    stage_for_gate = stage_scores_after if any(stage_scores_after.values()) else stage_scores_before
    gates = _gate_from_evidence(rois, stage_for_gate, frame_scores, rois["shippingContractNote"])
    report["gates"] = gates
    report["success"] = bool(gates.get("supportedTransparentMixed"))

    after = file_identity(SOURCE)
    write_json(out / "fingerprints-after.json", after.as_dict())
    report["sourceUnchanged"] = after.as_dict() == before.as_dict()
    report["durationS"] = time.monotonic() - started
    write_json(out / "report.json", report)

    lines = [
        "# Mixed Alpha_DSK slides 6–8 transparency probe (evidence-first)",
        "",
        f"Generated: {report['generated']}",
        "",
        f"Fixture: **Alpha_DSK.key** slides {list(KEEP)} (not FW 11–13)",
        f"Source unchanged: **{report['sourceUnchanged']}**",
        f"Canvas: `{rois['canvas']}` — {rois['shippingContractNote']}",
        f"Fill isolation: **{report.get('fillIsolation', {}).get('class')}** (No Fill: `{nofill_report.get('stdout')}`)",
        f"UI transparent movie: **{ui_report.get('ok')}** bytes={ui_report.get('bytes')} cfg=`{ui_report.get('cfgOut')}`",
        f"Sparse frames scored: **{report.get('sparseFrameCount')}**",
        "",
        "## ROI establishment",
        "",
    ]
    for s in rois["slides"]:
        lines.append(
            f"- Slide {s['originalOrdinal']}: emptyRoiEstablished=**{s['emptyRoiEstablished']}** "
            f"emptyFrac={s['emptyFrac']:.4f} movies={len(s['movies'])} magic={s['magicMove']} movieStart={s['hasMovieStart']}"
        )
    lines += ["", "## Evidence gates (can pass)", ""]
    for g in gates["slides"]:
        lines.append(
            f"- Slide {g['originalOrdinal']}: pass=**{g['pass']}** measures=`{g['measures']}` "
            f"fixture=`{g['fixture']}` notes={g['notes']}"
        )
    lines += [
        "",
        f"supportedTransparentMixed: **{gates['supportedTransparentMixed']}**",
        "",
        "P3 still unwired. Movie-start / Magic Move are fixture labels, not automatic refusals.",
        f"Samples: `{out}`",
    ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if report.get("sourceUnchanged") else 2


if __name__ == "__main__":
    raise SystemExit(main())
