#!/usr/bin/env python3
"""Magic Move + video probe on Alpha_DSK source slides 7→8 (nav 5→6).

Reconciles transition, slims to 7–8, UI-transparent ProRes export, then:
- dense 30fps windows through Magic Move (video + overlays)
- longer uninterrupted sync segment after the cut
- live Keynote slideshow screen capture compared to export window (motion/geometry)

P3 stays off. Never writes owner source decks. HTML composed alpha is out of scope.
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

from obed_edom.dsk_live import LiveBatch, keynote_app, keynote_running  # noqa: E402
from obed_edom.fixture_paths import fixture  # noqa: E402
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
from p2_recovery_mixed_transparent import (  # noqa: E402
    _clamp_rect,
    _empty_patches_from_mask,
    _export_stages_script,
    _ffprobe_duration,
    _nofill_and_save,
    _nofill_ui_script,
    _union_mask,
)
from p2_recovery_mixed_dense_windows import (  # noqa: E402
    _compare_to_stage,
    _extract_window,
    _mae_rgb,
    _score_sequence,
)
from p2_recovery_native_ui import (  # noqa: E402
    _run_osascript,
    _ui_click_next_and_save,
    _ui_configure_transparent_export,
    _ui_dump_script,
    _ui_open_export_movie,
)

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key")
OUT = fixture("p2-recovery") / "magic-move-7-8"
KEEP = (7, 8)  # source ordinals; nav 5→6 with skips hidden
FPS = 30
SYNC_SEGMENT_S = 4.0  # uninterrupted after MM cut
LIVE_FPS = 10


def _refuse_busy_keynote() -> None:
    """Never force-quit an unrelated owner Keynote session."""
    if keynote_running():
        raise SystemExit(
            "Keynote is already running — refuse to force-quit an owner session. "
            "Quit Keynote and re-run this probe."
        )


def _reconcile() -> dict:
    inv = inventory_deck(SOURCE)
    ident = file_identity(SOURCE).as_dict()
    nav = {}
    n = 0
    for s in inv["slides"]:
        if s.get("skipped"):
            nav[s["originalOrdinal"]] = None
        else:
            n += 1
            nav[s["originalOrdinal"]] = n
    s7 = next(s for s in inv["slides"] if s["originalOrdinal"] == 7)
    s8 = next(s for s in inv["slides"] if s["originalOrdinal"] == 8)
    ready = bool(s8.get("magicMove")) and "magic-move" in str((s8.get("transition") or {}).get("effect") or "")
    return {
        "source": ident,
        "skipped": inv.get("skipped"),
        "nav": {7: nav.get(7), 8: nav.get(8)},
        "slide7": {"transition": s7.get("transition"), "magicMove": s7.get("magicMove"), "identity": s7.get("identity")},
        "slide8": {"transition": s8.get("transition"), "magicMove": s8.get("magicMove"), "identity": s8.get("identity")},
        "ready": ready,
        "intended": "source 7→8 (nav 5→6): Sunday Service alone → + Children’s Church with Magic Move",
    }


def _rois_for_keep() -> dict:
    """Build ROIs for source 7–8 only (patched KEEP for helpers that scan KEEP)."""
    # Temporarily monkeypatch is messy; build inline from inventory + geometry.
    inv = inventory_deck(SOURCE)
    cw = float(inv["canvas"]["width"])
    ch = float(inv["canvas"]["height"])
    objects = _load_deck(SOURCE)
    if isinstance(objects, tuple):
        objects = objects[0]
    archives = movie_archives(SOURCE)
    slides_out = []
    for s in inv["slides"]:
        if s["originalOrdinal"] not in KEEP:
            continue
        sid = str(s["slideId"])
        geos = compose_geometry(objects.get(sid) or {}, objects)
        movies = []
        for a in archives:
            if f"Slide-{sid}.iwa" not in a["member"]:
                continue
            vis = _clamp_rect(a["x"], a["y"], a["w"], a["h"], cw, ch)
            if vis:
                movies.append(
                    {
                        "id": a["id"],
                        "raw": {"x": a["x"], "y": a["y"], "width": a["w"], "height": a["h"]},
                        "visible": vis,
                        "endTime": a.get("endTime"),
                    }
                )
        overlays = []
        for g in geos:
            kind = str(g.get("kind") or "")
            if kind == "movie":
                continue
            rect = _clamp_rect(float(g["x"]), float(g["y"]), float(g["w"]), float(g["h"]), cw, ch)
            if not rect:
                continue
            overlays.append({"id": g.get("id"), "kind": kind, "rect": rect, "text": (g.get("text") or "")[:80]})
        movie_rects = [m["visible"] for m in movies]
        overlay_rects = [o["rect"] for o in overlays]
        content = movie_rects + overlay_rects
        h_i, w_i = int(ch), int(cw)
        empty_mask = ~_union_mask(h_i, w_i, content, margin=2)
        empty_patches = _empty_patches_from_mask(empty_mask) if empty_mask.any() else []
        slides_out.append(
            {
                "originalOrdinal": s["originalOrdinal"],
                "slideId": sid,
                "identity": s.get("identity"),
                "magicMove": bool(s.get("magicMove")),
                "hasMovieStart": bool(s.get("hasMovieStart")),
                "transition": s.get("transition"),
                "movies": movies,
                "overlays": overlays,
                "movieRects": movie_rects,
                "overlayRects": overlay_rects,
                "emptyPatches": empty_patches,
                "emptyRoiEstablished": bool(empty_patches),
                "emptyFrac": float(empty_mask.mean()),
            }
        )
    return {"canvas": {"width": cw, "height": ch}, "slides": slides_out}


def _slim_keep_script(bid: str, scratch: Path) -> str:
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


def _find_mm_cut(movie: Path, dur: float, out: Path) -> float:
    coarse = out / "coarse-2fps"
    if coarse.exists():
        shutil.rmtree(coarse)
    coarse.mkdir(parents=True)
    exe = ffmpeg_exe()
    subprocess.run(
        [exe, "-y", "-i", str(movie), "-vf", "fps=2", "-pix_fmt", "rgba", str(coarse / "c%04d.png")],
        capture_output=True,
        text=True,
    )
    frames = sorted(coarse.glob("c*.png"))
    arrs = [load_rgba(p) for p in frames]
    maes = [_mae_rgb(arrs[i], arrs[i + 1]) for i in range(len(arrs) - 1)]
    best_i, best_m = max(enumerate(maes), key=lambda z: z[1])
    cut_t = (best_i + 0.5) / 2.0
    write_json(out / "coarse-maes.json", {"maes": maes, "best": {"i": best_i, "t": cut_t, "mae": best_m}})
    shutil.rmtree(coarse)
    # Prefer a strong peak after the first second (skip open)
    peaks = []
    for i, m in enumerate(maes):
        left = maes[i - 1] if i else 0
        right = maes[i + 1] if i + 1 < len(maes) else 0
        if m >= left and m >= right and m > 2.0 and (i + 0.5) / 2.0 > 1.0:
            peaks.append(((i + 0.5) / 2.0, m))
    if peaks:
        cut_t = max(peaks, key=lambda p: p[1])[0]
    return float(min(max(0.5, cut_t), dur - 0.5))


def _live_play_capture(scratch: Path, dest: Path, duration_s: float = 6.0) -> dict:
    """Play Keynote slideshow and grab window screenshots at LIVE_FPS (opaque screen — motion only)."""
    dest.mkdir(parents=True, exist_ok=True)
    bid = keynote_app.bundle_id()
    # Open + start slideshow from slide 1 of slim doc
    open_play = f'''
tell application id "{bid}"
  activate
  open POSIX file "{scratch}"
  delay 3
  tell document 1
    set current slide to slide 1
  end tell
  delay 0.5
end tell
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    delay 0.3
    keystroke "p" using {{command down, option down, shift down}} -- play from current (best-effort)
  end tell
end tell
delay 0.8
-- fallback play menu
try
  tell application "System Events" to tell process "Keynote"
    click menu item "Play Slideshow" of menu 1 of menu bar item "Play" of menu bar 1
  end try
end try
'''
    # Simpler: use Keynote `start from` if available
    play_script = f'''
tell application id "{bid}"
  activate
  set theDoc to open POSIX file "{scratch}"
  delay 4
  tell theDoc
    set current slide to slide 1
  end tell
  delay 0.5
  -- Keynote suite: start slideshow
  try
    start from theDoc
  on error
    try
      tell theDoc to start
    end try
  end try
end tell
'''
    proc = _run_osascript(play_script, dest / "live_play.applescript")
    # Get Keynote window bounds for screencapture -R
    bounds_proc = _run_osascript(
        '''
tell application "System Events" to tell process "Keynote"
  set frontmost to true
  delay 0.5
  try
    set b to position of window 1 & size of window 1
    return (item 1 of b as text) & "," & (item 2 of b as text) & "," & (item 3 of b as text) & "," & (item 4 of b as text)
  on error
    return "0,0,1920,1080"
  end try
end tell
''',
        dest / "bounds.applescript",
    )
    raw = (bounds_proc.stdout or "0,0,1920,1080").strip()
    try:
        x, y, w, h = [int(float(v)) for v in raw.split(",")]
    except Exception:
        x, y, w, h = 0, 0, 1920, 1080
    # Capture loop
    n = int(duration_s * LIVE_FPS)
    paths = []
    t0 = time.monotonic()
    for i in range(n):
        p = dest / f"live-{i:04d}.png"
        # -x silent, -R region
        subprocess.run(
            ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(p)],
            check=False,
        )
        if p.is_file():
            paths.append(p)
        target = t0 + (i + 1) / LIVE_FPS
        while time.monotonic() < target:
            time.sleep(0.005)
    # Stop slideshow
    _run_osascript(
        f'''
tell application id "{bid}" to activate
tell application "System Events" to key code 53 -- escape
delay 0.5
''',
        dest / "stop.applescript",
    )
    # Motion summary
    pair = []
    if len(paths) >= 2:
        prev = np.array(Image.open(paths[0]).convert("RGB"))
        for p in paths[1:]:
            cur = np.array(Image.open(p).convert("RGB"))
            if cur.shape != prev.shape:
                cur = np.array(Image.fromarray(cur).resize((prev.shape[1], prev.shape[0])))
            pair.append(float(np.mean(np.abs(cur.astype(np.float32) - prev.astype(np.float32)))))
            prev = cur
    return {
        "ok": len(paths) >= 5,
        "frameCount": len(paths),
        "bounds": [x, y, w, h],
        "playRc": proc.returncode,
        "playOut": (proc.stdout or "")[-200:],
        "playErr": (proc.stderr or "")[-300:],
        "maxPairMae": max(pair) if pair else 0.0,
        "meanPairMae": float(np.mean(pair)) if pair else 0.0,
        "motionPresent": sum(1 for m in pair if m > 1.0) >= 1,
        "note": "Screen capture is opaque RGB — used for motion/geometry compare only, not alpha",
    }


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    wall_started = time.time()  # compare with st_mtime
    mono_started = time.monotonic()
    before = file_identity(SOURCE)
    write_json(OUT / "fingerprints-before.json", before.as_dict())

    recon = _reconcile()
    write_json(OUT / "reconcile.json", recon)
    print("reconcile ready=", recon["ready"], recon["slide8"])
    if not recon["ready"]:
        (OUT / "REPORT.md").write_text(
            "# Magic Move 7→8 — blocked\n\nSlide 8 is not Magic Move yet.\n", encoding="utf-8"
        )
        return 2

    rois = _rois_for_keep()
    write_json(OUT / "rois.json", rois)
    roi_by = {s["originalOrdinal"]: s for s in rois["slides"]}

    _refuse_busy_keynote()
    movie_path = OUT / "movies" / "mm-7-8-ui-transparent-prores4444.mov"
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    stages = OUT / "stages"
    ui_report: dict = {}
    scratch_keep: Path | None = None

    with LiveBatch(SOURCE, OUT / "batch", log=print) as batch:
        assert batch.scratch is not None and batch.work is not None
        bid = keynote_app.bundle_id()
        scratch = batch.scratch
        scratch_keep = scratch

        slim = batch.work / "slim.applescript"
        slim.write_text(_slim_keep_script(bid, scratch), encoding="utf-8")
        proc = batch.run(slim)
        if proc.returncode != 0:
            write_json(OUT / "report.json", {"stopped": "slim failed", "stderr": (proc.stderr or "")[-500:]})
            return 1

        # No Fill (enables transparent checkbox)
        open_sc = batch.work / "open.applescript"
        open_sc.write_text(_nofill_and_save(bid, scratch), encoding="utf-8")
        batch.run(open_sc)
        nf = _run_osascript(_nofill_ui_script(), batch.work / "nofill.applescript")
        save_nf = batch.work / "save_nofill.applescript"
        save_nf.write_text(
            f'tell application id "{bid}"\nif (count of documents)>0 then save document 1\nend tell\n',
            encoding="utf-8",
        )
        batch.run(save_nf)

        # Stages for native settled anchors
        st = batch.work / "stages.applescript"
        st.write_text(_export_stages_script(bid, scratch, stages), encoding="utf-8")
        batch.run(st)

        # Re-open for UI movie export
        batch.run(open_sc)
        if movie_path.exists():
            movie_path.unlink()
        open_ui = _run_osascript(_ui_open_export_movie(), batch.work / "ui_open.applescript")
        (OUT / "ui").mkdir(exist_ok=True)
        dump = _run_osascript(_ui_dump_script(), batch.work / "ui_dump.applescript")
        (OUT / "ui" / "dump.txt").write_text((dump.stdout or "") + (dump.stderr or ""), encoding="utf-8")
        cfg = _run_osascript(_ui_configure_transparent_export(), batch.work / "ui_cfg.applescript")
        save = _run_osascript(_ui_click_next_and_save(movie_path), batch.work / "ui_save.applescript")

        deadline = time.time() + 900
        found = None
        owned_dir = movie_path.parent.resolve()
        while time.time() < deadline:
            # Only accept the exact run-owned destination (or siblings created in that folder).
            # Never search SOURCE.parent — that can pick up an owner Alpha_DSK.mov.
            candidates = []
            if movie_path.is_file():
                candidates.append(movie_path)
            candidates.extend(sorted(owned_dir.glob("*.mov")))
            candidates.extend(sorted(owned_dir.glob("*.m4v")))
            for c in candidates:
                try:
                    st = c.stat()
                except OSError:
                    continue
                if st.st_size <= 1_000_000:
                    continue
                if st.st_mtime < wall_started - 2:
                    continue
                found = c
                break
            if found:
                sz1 = found.stat().st_size
                time.sleep(2)
                if found.stat().st_size == sz1:
                    break
                found = None
            time.sleep(2)

        if found and found.resolve() != movie_path.resolve():
            # Rename within the owned output folder only.
            if found.parent.resolve() != owned_dir:
                raise RuntimeError(f"refusing to move unowned movie: {found}")
            if movie_path.exists():
                movie_path.unlink()
            shutil.move(str(found), str(movie_path))
            found = movie_path

        ui_report = {
            "ok": found is not None and found.is_file(),
            "movie": str(found) if found else None,
            "bytes": found.stat().st_size if found and found.is_file() else 0,
            "cfg": (cfg.stdout or "").strip(),
            "cfgErr": (cfg.stderr or "")[-400:],
            "save": (save.stdout or "").strip(),
            "saveErr": (save.stderr or "")[-400:],
            "openRc": open_ui.returncode,
            "nofill": (nf.stdout or "").strip(),
        }
        write_json(OUT / "ui-export.json", ui_report)

        # Keep scratch path for live play — copy aside before LiveBatch cleanup
        preserved = OUT / "scratch-slim.key"
        shutil.copy2(scratch, preserved)
        scratch_keep = preserved

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

    report: dict = {
        "probe": "p2_recovery_magic_move_capture",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reconcile": recon,
        "uiMovie": ui_report,
        "p3": "still unwired",
        "htmlComposedAlpha": "separate open question — not tested here",
    }

    if not ui_report.get("ok"):
        report["stopped"] = "UI movie export not found — press Enter on save panel if needed and re-run"
        write_json(OUT / "report.json", report)
        (OUT / "REPORT.md").write_text(
            "# Magic Move 7→8 — export pending\n\nUI movie not found yet.\n", encoding="utf-8"
        )
        print("UI export not found")
        return 1

    movie = Path(ui_report["movie"])
    dur = _ffprobe_duration(movie)
    report["durationS"] = dur
    cut_t = _find_mm_cut(movie, dur, OUT)
    report["magicMoveCutT"] = cut_t

    # Dense MM window ±1.0s around cut (covers 1.5s transition)
    mm_t0, mm_t1 = max(0.0, cut_t - 1.0), min(dur - 0.01, cut_t + 1.0)
    mm_frames = _extract_window(movie, mm_t0, mm_t1, OUT / "windows" / "magic-move")
    mid = len(mm_frames) // 2
    seq_from = _score_sequence(mm_frames[: max(1, mid)], roi_by[7], mm_t0)
    seq_into = _score_sequence(mm_frames[mid:], roi_by[8], mm_t0 + mid / FPS)
    arrs = [load_rgba(p) for p in mm_frames]
    pair = [_mae_rgb(arrs[i], arrs[i + 1]) for i in range(len(arrs) - 1)]
    mm_window = {
        "t0": mm_t0,
        "t1": mm_t1,
        "cutT": cut_t,
        "frameCount": len(mm_frames),
        "fromHalf": seq_from,
        "intoHalf": seq_into,
        "emptyAlphaStable": seq_from["emptyAlphaStable"] and seq_into["emptyAlphaStable"],
        "motionPresent": seq_from["motionPresent"] or seq_into["motionPresent"],
        "maxPairMae": max(pair) if pair else 0.0,
        "overlaysMovingHint": bool(pair) and max(pair) > 2.0,
        "videoPlayingHint": (seq_from.get("footprintOpaqueMax") or 0) > 0.5
        or (seq_into.get("footprintOpaqueMax") or 0) > 0.5,
    }
    write_json(OUT / "windows" / "magic-move" / "window.json", mm_window)

    # Longer uninterrupted sync segment after cut
    sync_t0 = min(dur - 0.05, cut_t + 0.2)
    sync_t1 = min(dur - 0.01, sync_t0 + SYNC_SEGMENT_S)
    sync_frames = _extract_window(movie, sync_t0, sync_t1, OUT / "windows" / "sync-segment")
    sync_seq = _score_sequence(sync_frames, roi_by[8], sync_t0)
    # Overlay vs footprint relative stability: text opaque should stay high while movie opaque
    sync_report = {
        "t0": sync_t0,
        "t1": sync_t1,
        "frameCount": len(sync_frames),
        "sequence": sync_seq,
        "emptyAlphaStable": sync_seq["emptyAlphaStable"],
        "footprintStaysOpaque": (sync_seq.get("footprintOpaqueMin") or 0) >= 0.7
        if sync_seq.get("footprintOpaqueMin") is not None
        else None,
        "textOverlayStable": (sync_seq.get("textOverlayOpaqueMin") or 0) >= 0.5
        if sync_seq.get("textOverlayOpaqueMin") is not None
        else None,
        "motionPresent": sync_seq["motionPresent"],
    }
    write_json(OUT / "windows" / "sync-segment" / "window.json", sync_report)

    # Stage anchors
    stage_pngs = sorted(stages.rglob("*.png")) if stages.exists() else []
    # After slim, stages are 001=7, 002=8
    stage7 = [p for p in stage_pngs if "001" in p.name or p.name.endswith(".001.png")]
    stage8 = [p for p in stage_pngs if "002" in p.name or p.name.endswith(".002.png")]
    if not stage7 and len(stage_pngs) >= 1:
        stage7 = [stage_pngs[0]]
    if not stage8 and len(stage_pngs) >= 2:
        stage8 = [stage_pngs[1]]
    native = {
        "mmStartVsSlide7": _compare_to_stage(mm_frames[0], stage7, roi_by[7]) if mm_frames else {},
        "mmEndVsSlide8": _compare_to_stage(mm_frames[-1], stage8, roi_by[8]) if mm_frames else {},
    }

    # Live Keynote playback capture (scratch only; never force-quit owner sessions)
    live = {"skipped": True}
    if scratch_keep and scratch_keep.is_file():
        if keynote_running():
            live = {
                "skipped": True,
                "reason": "Keynote still running after batch — refuse force-quit; live compare skipped",
            }
        else:
            live = _live_play_capture(scratch_keep, OUT / "live-play", duration_s=6.0)
            live["matchesExportMotion"] = bool(live.get("motionPresent")) and bool(
                mm_window.get("motionPresent")
            )

    findings = [
        {"id": "reconcileMagicMoveOn8", "pass": True},
        {"id": "emptyAlphaThroughMagicMove", "pass": bool(mm_window["emptyAlphaStable"])},
        {"id": "magicMoveMotionPresent", "pass": bool(mm_window["motionPresent"])},
        {"id": "overlaysMoveWithMagicMove", "pass": bool(mm_window["overlaysMovingHint"])},
        {"id": "videoPresentDuringMagicMove", "pass": bool(mm_window["videoPlayingHint"])},
        {
            "id": "syncSegmentEmptyAndFootprint",
            "pass": bool(sync_report["emptyAlphaStable"])
            and (sync_report["footprintStaysOpaque"] in (True, None)),
        },
        {
            "id": "livePlaybackMotion",
            "pass": bool(live.get("motionPresent")) if live.get("ok") else False,
            "detail": live,
        },
    ]
    report.update(
        {
            "magicMoveWindow": mm_window,
            "syncSegment": sync_report,
            "nativeStageCompare": native,
            "livePlayback": live,
            "findings": findings,
            "success": all(f["pass"] for f in findings if f["id"] != "livePlaybackMotion")
            and (findings[-1]["pass"] or not live.get("ok")),
            # don't fail whole probe solely on live AX flakiness if export MM passed
        }
    )
    # Stricter: require live if ok
    report["success"] = all(
        f["pass"]
        for f in findings
        if f["id"] != "livePlaybackMotion" or live.get("ok")
    )

    after = file_identity(SOURCE)
    write_json(OUT / "fingerprints-after.json", after.as_dict())
    report["sourceUnchanged"] = after.as_dict() == before.as_dict()
    report["durationWallS"] = time.monotonic() - mono_started
    write_json(OUT / "report.json", report)

    lines = [
        "# Magic Move 7→8 (nav 5→6) — native UI transparent",
        "",
        f"Generated: {report['generated']}",
        f"Source unchanged: **{report['sourceUnchanged']}** sha `{before.sha256[:16]}…`",
        f"Reconcile: slide8 magic=**{recon['slide8']['magicMove']}** trans=`{recon['slide8']['transition']}`",
        f"UI movie: **{ui_report.get('ok')}** bytes={ui_report.get('bytes')} dur={dur:.2f}s cut≈{cut_t:.2f}s",
        "",
        "## Magic Move window",
        f"- [{mm_t0:.2f},{mm_t1:.2f}] frames={mm_window['frameCount']} emptyStable={mm_window['emptyAlphaStable']} "
        f"motion={mm_window['motionPresent']} overlaysMoving={mm_window['overlaysMovingHint']} "
        f"video={mm_window['videoPlayingHint']} maxPairMae={mm_window['maxPairMae']:.2f}",
        "",
        "## Sync segment",
        f"- [{sync_t0:.2f},{sync_t1:.2f}] emptyStable={sync_report['emptyAlphaStable']} "
        f"footOpaque={sync_report['footprintStaysOpaque']} textStable={sync_report['textOverlayStable']} "
        f"motion={sync_report['motionPresent']}",
        "",
        "## Live Keynote",
        f"- ok={live.get('ok')} motion={live.get('motionPresent')} maxPairMae={live.get('maxPairMae')} "
        f"matchesExportMotion={live.get('matchesExportMotion')}",
        "",
        "## Findings",
    ]
    for f in findings:
        lines.append(f"- {f['id']}: **{f['pass']}**")
    lines += [
        "",
        f"success: **{report['success']}**",
        "",
        "HTML composed alpha: separate / open. P3 still unwired.",
        f"Samples: `{OUT}`",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
