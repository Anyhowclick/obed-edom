#!/usr/bin/env python3
"""Recovery plan step 1–2: native Movie UI transparent-background ProRes control.

Scratch-only Alpha_DSK Genesis (slide 3) with an opaque black sentinel image.
Exports via:
  A) scripted QuickTime to .m4v (classifies P2.4 .mov error 6)
  B) actual File > Export To > Movie UI with Custom + ProRes 4444 +
     Export with Transparent Backgrounds (the option AppleScript cannot set)

Decodes frames; requires empty alpha, intact black sentinel, genuine motion.
Never writes the owner's source deck. Does not implement P3.
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

from obed_edom.fixture_paths import fixture
from obed_edom import keynote_app
from obed_edom.dsk_live import LiveBatch, keynote_running
from obed_edom.dsk_stage_export import StageCountAmbiguous, export_stage_pngs, stage_counts, validate_alpha
from obed_edom.html_alpha_probe import (
    analyze_rgba,
    decode_prores_rgba,
    file_identity,
    identities_match,
    load_rgba,
    write_json,
)

DEFAULT_SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key")
OUT = fixture("p2-recovery")
SENTINEL = OUT / "sentinel-black-opaque.png"
SLIDE = 3  # Genesis
SENTINEL_XY = (40, 40)
SENTINEL_WH = (80, 80)


def _ffmpeg_codec_report(movie: Path) -> dict:
    """Confirm container codec is Apple ProRes 4444 (not HEVC/H.264)."""
    from obed_edom.maps_movie import ffmpeg_exe
    ff = ffmpeg_exe()
    proc = subprocess.run([ff, "-i", str(movie)], capture_output=True, text=True)
    err = proc.stderr or ""
    line = next((ln for ln in err.splitlines() if "Video:" in ln), "")
    is_4444 = ("prores (4444)" in line.lower()) or ("ap4h" in line.lower()) or ("Apple ProRes 4444" in err)
    is_hevc = "hevc" in line.lower() or "hvc1" in line.lower()
    is_h264 = "h264" in line.lower() or "avc1" in line.lower()
    return {
        "videoLine": line.strip(),
        "isProRes4444": is_4444,
        "isHEVC": is_hevc,
        "isH264": is_h264,
        "hasYuva": "yuva" in line.lower(),
    }


def _quit_if_idle() -> None:
    if not keynote_running():
        return
    bid = keynote_app.bundle_id()
    n = int(subprocess.check_output(
        ["osascript", "-e", f'tell application id "{bid}" to count documents'], text=True
    ).strip())
    if n != 0:
        raise RuntimeError(f"Keynote has {n} documents; refuse")
    subprocess.check_call(["osascript", "-e", f'tell application id "{bid}" to quit'])
    for _ in range(40):
        if not keynote_running():
            return
        time.sleep(0.25)
    raise RuntimeError("Keynote did not quit")


def _ensure_sentinel() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    if not SENTINEL.is_file():
        Image.new("RGBA", SENTINEL_WH, (0, 0, 0, 255)).save(SENTINEL)
    return SENTINEL


def _slim_prepare_script(bid: str, scratch: Path, sentinel: Path) -> str:
    sx, sy = SENTINEL_XY
    sw, sh = SENTINEL_WH
    return f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 900 seconds
    activate
    set theDoc to open POSIX file "{scratch}"
    delay 5
    tell theDoc
      set n to count of slides
      repeat with i from n to 1 by -1
        if i is not {SLIDE} then delete slide i
      end repeat
      delay 1
      -- after slim, Genesis is slide 1; place opaque black sentinel
      set imgFile to (POSIX file "{sentinel}") as alias
      tell slide 1
        set img to make new image with properties {{file:imgFile}}
        set position of img to {{{sx}, {sy}}}
        set width of img to {sw}
        set height of img to {sh}
        try
          set opacity of img to 100
        end try
      end tell
    end tell
    save theDoc
    delay 1
  end timeout
end tell
end using terms from
'''


def _scripted_m4v_export(bid: str, scratch: Path, dest: Path) -> str:
    return f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 900 seconds
    activate
    set theDoc to document 1
    export theDoc to POSIX file "{dest}" as QuickTime movie with properties {{movie format:native size, movie codec:AppleProRes4444, movie framerate:FPS30, skipped slides:false}}
  end timeout
end tell
end using terms from
'''


def _ui_dump_script() -> str:
    return '''
tell application "System Events"
  tell process "Keynote"
    set out to ""
    try
      set wins to windows
      set out to out & "windows=" & (count of wins) & linefeed
      repeat with w in wins
        set out to out & "WIN:" & (name of w as text) & linefeed
        try
          set out to out & "  role=" & (role of w as text) & linefeed
        end try
        try
          set ui to entire contents of w
          set lim to 80
          if (count of ui) < lim then set lim to count of ui
          repeat with i from 1 to lim
            set el to item i of ui
            try
              set out to out & "  [" & i & "] " & (class of el as text) & " name=" & (name of el as text) & " desc=" & (description of el as text) & " value=" & (value of el as text) & linefeed
            on error
              try
                set out to out & "  [" & i & "] " & (class of el as text) & linefeed
              end try
            end try
          end repeat
        end try
      end repeat
    on error errMsg
      set out to out & "ERR:" & errMsg & linefeed
    end try
    return out
  end tell
end tell
'''


def _ui_open_export_movie() -> str:
    # File > Export To > Movie… — options appear as a *sheet* on the doc window
    return '''
tell application id "com.apple.Keynote" to activate
delay 0.5
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    delay 0.3
    click menu item "Movie…" of menu 1 of menu item "Export To" of menu 1 of menu bar item "File" of menu bar 1
    delay 1.5
    if not (exists sheet 1 of window 1) then error "export sheet did not open"
    return "sheet-open"
  end tell
end tell
'''


def _ui_configure_transparent_export() -> str:
    """Sheet-aware: Advanced Options + Format=Apple ProRes 4444 + transparent on.

    Measured Keynote 15.3.1 sheet: Format pop-up often defaults to HEVC; transparent
    checkbox exists only when background is No Fill. Must target sheet 1 of window 1.
    """
    return '''
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    set sh to sheet 1 of window 1
    set report to ""
    -- Expand Advanced Options only if disclosure is closed (button toggles/collapses)
    try
      set discs to UI elements of sh whose description is "disclosure triangle"
      if (count of discs) > 0 then
        set d to item 1 of discs
        set report to report & "disc=" & (value of d as text) & ";"
        if (value of d as integer) is 0 then
          click d
          delay 0.4
          set report to report & "expanded;"
        end if
      end if
    end try
    -- Set Format pop-up to Apple ProRes 4444 (do NOT leave HEVC)
    set formatSet to false
    set pops to pop up buttons of sh
    repeat with p in pops
      try
        set cur to (value of p as text)
        -- Format control shows codec names (HEVC / H.264 / Apple ProRes …)
        if cur is "HEVC" or cur is "H.264" or cur contains "ProRes" or cur is "Apple ProRes 422" or cur is "Apple ProRes 4444" then
          click p
          delay 0.25
          click menu item "Apple ProRes 4444" of menu 1 of p
          delay 0.3
          set cur2 to (value of p as text)
          set report to report & "formatWas:" & cur & ">now:" & cur2 & ";"
          if cur2 is "Apple ProRes 4444" then set formatSet to true
        end if
      end try
    end repeat
    if not formatSet then
      -- Fallback: try every pop-up
      repeat with p in pops
        try
          click p
          delay 0.2
          try
            click menu item "Apple ProRes 4444" of menu 1 of p
            delay 0.2
            if (value of p as text) is "Apple ProRes 4444" then
              set formatSet to true
              set report to report & "formatFallback:Apple ProRes 4444;"
            end if
          end try
          key code 53 -- escape leftover menus
        end try
      end repeat
    end if
    if not formatSet then error "failed to set Format to Apple ProRes 4444"
    -- Transparent checkbox must be on
    set boxes to checkboxes of sh
    repeat with c in boxes
      try
        set nm to (name of c as text)
        if nm contains "transparent" or nm contains "Transparent" then
          if (value of c as integer) is 0 then click c
          set report to report & "transparent:" & nm & "=val" & (value of c as text) & ";"
        end if
      end try
    end repeat
    -- Record final pop-up values for the report
    repeat with p in pops
      try
        set report to report & "popup:" & (value of p as text) & ";"
      end try
    end repeat
    return report
  end tell
end tell
'''


def _ui_click_next_and_save(dest: Path) -> str:
    """Save sheet: set Save As name, click Export. No Shift-Cmd-G / Go to Folder."""
    dest_name = dest.name
    return f'''
tell application id "com.apple.Keynote" to activate
delay 0.3
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    delay 0.2
    set report to ""
    -- Movie options sheet still on the doc window
    click button "Save…" of sheet 1 of window 1
    set report to report & "save;"
    delay 1.5
    -- Save panel: AX often titles this window "Open"
    set saveWin to missing value
    repeat with w in windows
      try
        if exists text field "Save As:" of sheet 1 of w then
          set saveWin to w
          exit repeat
        end if
      end try
      try
        if exists text field "Save As:" of w then
          set saveWin to w
          exit repeat
        end if
      end try
    end repeat
    if saveWin is missing value then error "save panel not found"
    try
      set whereVal to (value of pop up button "Where:" of sheet 1 of saveWin as text)
      set report to report & "where:" & whereVal & ";"
    end try
    try
      set value of text field "Save As:" of sheet 1 of saveWin to "{dest_name}"
    on error
      set value of text field "Save As:" of saveWin to "{dest_name}"
    end try
    set report to report & "named:{dest_name};"
    delay 0.4
    -- Click Export (blue default). Prefer button; fall back to Return.
    set clicked to false
    try
      click button "Export" of sheet 1 of saveWin
      set clicked to true
      set report to report & "export-sheet;"
    end try
    if not clicked then
      try
        click button "Export" of saveWin
        set clicked to true
        set report to report & "export-win;"
      end try
    end if
    if not clicked then
      keystroke return
      set report to report & "export-return;"
    end if
    return report
  end tell
end tell
'''



def _run_osascript(text: str, path: Path) -> subprocess.CompletedProcess:
    path.write_text(text, encoding="utf-8")
    return subprocess.run(["osascript", str(path)], capture_output=True, text=True, timeout=960)


def _frame_stats(path: Path, sentinel_box: tuple[int, int, int, int]) -> dict:
    arr = load_rgba(path)
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = sentinel_box
    x1 = min(x1, w)
    y1 = min(y1, h)
    box = arr[y0:y1, x0:x1]
    corners = [
        arr[0:8, 0:8],
        arr[0:8, w - 8 : w],
        arr[h - 8 : h, 0:8],
        arr[h - 8 : h, w - 8 : w],
    ]
    # Prefer far corners away from sentinel (top-left has sentinel) — use bottom-right
    empty = arr[h - 40 : h - 10, w - 40 : w - 10]
    a = analyze_rgba(arr)
    return {
        "path": str(path),
        "shape": [h, w],
        "alphaMin": int(arr[:, :, 3].min()),
        "alphaMax": int(arr[:, :, 3].max()),
        "transparentFrac": float((arr[:, :, 3] <= 2).mean()),
        "emptyPatchAlphaMean": float(empty[:, :, 3].mean()),
        "emptyPatchAlphaMax": int(empty[:, :, 3].max()),
        "sentinelRgbMean": [float(x) for x in box[:, :, :3].mean(axis=(0, 1))],
        "sentinelAlphaMean": float(box[:, :, 3].mean()),
        "sentinelAlphaMin": int(box[:, :, 3].min()),
        "analyzePass": a["pass"],
        "emptyBackgroundOk": a["samples"]["emptyBackgroundOk"],
    }


def _genuine_motion(frames: list[Path]) -> dict:
    if len(frames) < 3:
        return {"ok": False, "reason": "too-few-frames", "count": len(frames)}
    idxs = [0, len(frames) // 4, len(frames) // 2, (3 * len(frames)) // 4, len(frames) - 1]
    idxs = sorted(set(min(i, len(frames) - 1) for i in idxs))
    arrs = [load_rgba(frames[i])[:, :, :3].astype(np.float32) for i in idxs]
    maes = []
    for i in range(len(arrs) - 1):
        maes.append(float(np.mean(np.abs(arrs[i + 1] - arrs[i]))))
    changing = sum(1 for m in maes if m > 0.5)
    return {
        "ok": changing >= 1 and max(maes) > 1.0,
        "sampleIndexes": idxs,
        "pairwiseMae": maes,
        "changingPairs": changing,
        "frameCount": len(frames),
    }


def _classify_native_failure(movie: dict, samples: list[dict], motion: dict) -> dict:
    if not movie.get("ok"):
        err = (movie.get("stderr") or "") + (movie.get("uiReport") or "")
        if '".mov"' in err or "(6)" in err:
            return {"class": "encoder_container_failure", "detail": "destination/container rejected"}
        if "no-controls-matched" in err or "transparent" in err.lower() and movie.get("uiConfig") == "no-controls-matched":
            return {"class": "unavailable_control", "detail": "UI transparent checkbox not found/set"}
        if movie.get("bytes", 0) == 0:
            return {"class": "encoder_container_failure", "detail": "no movie bytes"}
        return {"class": "export_failed", "detail": err[-500:]}
    if not samples:
        return {"class": "decode_failed", "detail": "no decoded frames"}
    # Successful file but opaque?
    any_empty = any(s["emptyPatchAlphaMax"] <= 5 and s["transparentFrac"] > 0.05 for s in samples)
    sentinel_ok = any(
        s["sentinelAlphaMean"] > 250 and s["sentinelRgbMean"][0] < 40 for s in samples
    )
    if any_empty and sentinel_ok and motion.get("ok"):
        return {"class": "success", "detail": "genuine alpha + sentinel + motion"}
    if any_empty and not sentinel_ok:
        return {"class": "opaque_or_lost_artwork", "detail": "empty alpha but sentinel not intact"}
    if not any_empty and sentinel_ok:
        return {
            "class": "opaque_output_after_successful_export",
            "detail": "movie wrote; sentinel present; empty regions still opaque — setting ignored or slide fill opaque",
        }
    if not any_empty and not sentinel_ok:
        return {"class": "opaque_source_or_layout_artwork", "detail": "no empty alpha and sentinel missing"}
    if any_empty and sentinel_ok and not motion.get("ok"):
        return {"class": "no_motion", "detail": "alpha+sentinel but no genuine motion"}
    return {"class": "inconclusive", "detail": "see samples"}


def main() -> int:
    source = DEFAULT_SOURCE
    out = OUT
    movies = out / "movies"
    ui_dir = out / "ui"
    scripted_dir = out / "scripted"
    for d in (movies, ui_dir, scripted_dir):
        d.mkdir(parents=True, exist_ok=True)
    sentinel = _ensure_sentinel()
    started = time.monotonic()
    before = file_identity(source)
    write_json(out / "fingerprints-before.json", before.as_dict())

    _quit_if_idle()

    # Reference settled stage PNGs (no sentinel) for later compare
    counts = {SLIDE: 2}
    stages_dir = out / "stages-ref"
    existing = sorted(stages_dir.glob("*.png")) if stages_dir.is_dir() else []
    if len(existing) >= 2:
        stage_ref = [{"slide": SLIDE, "stage": i + 1, "path": str(p), "alphaOk": None, "reused": True} for i, p in enumerate(existing)]
        print(f"reusing {len(existing)} stage PNGs from {stages_dir}")
    else:
        try:
            stage_assets = export_stage_pngs(source, [SLIDE], stages_dir, expected_stage_counts=counts, log=print)
            stage_ref = [{"slide": a.slide, "stage": a.stage_index, "path": a.path, "alphaOk": a.alpha_ok} for a in stage_assets]
        except Exception as e:  # noqa: BLE001
            stage_ref = {"error": str(e)}

    _quit_if_idle()

    bid = keynote_app.bundle_id()
    scripted_movie = scripted_dir / "genesis-prores4444.m4v"
    ui_movie = movies / "genesis-ui-transparent-prores4444.mov"
    report: dict = {
        "generated": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "probe": "p2_recovery_native_ui",
        "settingsAttempted": {
            "resolution": "Custom / native size",
            "codec": "Apple ProRes 4444",
            "framerate": "FPS30",
            "transparentBackgrounds": "UI checkbox Export with Transparent Backgrounds",
            "slideBackground": "unchanged initially; No Fill attempted via Format if UI allows",
            "sentinel": {"path": str(sentinel), "xy": SENTINEL_XY, "wh": SENTINEL_WH, "rgb": [0, 0, 0], "alpha": 255},
            "destination": ".m4v (Keynote QuickTime exporter rejects .mov)",
        },
        "stageRef": stage_ref,
    }

    with LiveBatch(source, out / "batch", log=print) as batch:
        assert batch.scratch is not None and batch.work is not None
        # Copy sentinel into work so path stays local
        local_sentinel = batch.work / "sentinel-black-opaque.png"
        shutil.copy2(sentinel, local_sentinel)

        prep = batch.work / "prep.applescript"
        prep.write_text(_slim_prepare_script(bid, batch.scratch, local_sentinel), encoding="utf-8")
        # Do not retry-on-1712: a recopy would wipe the sentinel/slim edits.
        proc = batch.run(prep, retry_on_1712=False)
        report["prep"] = {
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-800:],
            "stdout": (proc.stdout or "")[-400:],
        }
        if proc.returncode != 0:
            raise RuntimeError(f"prep failed: {proc.stderr}")

        # --- A) scripted .m4v (no UI transparency) ---
        if scripted_movie.exists():
            scripted_movie.unlink()
        sc = batch.work / "scripted_export.applescript"
        sc.write_text(_scripted_m4v_export(bid, batch.scratch, scripted_movie), encoding="utf-8")
        proc = batch.run(sc, retry_on_1712=False)
        scripted = {
            "ok": scripted_movie.is_file() and scripted_movie.stat().st_size > 0,
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-1000:],
            "movie": str(scripted_movie) if scripted_movie.is_file() else None,
            "bytes": scripted_movie.stat().st_size if scripted_movie.is_file() else 0,
            "pathNote": "scripted AppleScript has no transparent-backgrounds property",
        }
        report["scriptedM4v"] = scripted

        # --- B) UI export ---
        # Attempt Format > Background > No Fill first (enables transparent option per Apple docs)
        nofill = _run_osascript(
            '''
tell application id "com.apple.Keynote" to activate
delay 0.4
tell application "System Events"
  tell process "Keynote"
    set frontmost to true
    -- select all (one slide)
    keystroke "a" using {command down}
    delay 0.3
  end tell
end tell
-- Try Format inspector via menu; if unavailable record and continue
try
  tell application "System Events"
    tell process "Keynote"
      click menu item "No Fill" of menu 1 of menu item "Background" of menu 1 of menu bar item "Format" of menu bar 1
      return "nofill-menu"
    end tell
  end tell
on error errMsg
  return "nofill-failed:" & errMsg
end try
''',
            batch.work / "nofill.applescript",
        )
        report["noFillAttempt"] = {
            "returncode": nofill.returncode,
            "stdout": (nofill.stdout or "").strip(),
            "stderr": (nofill.stderr or "")[-400:],
        }

        open_ui = _run_osascript(_ui_open_export_movie(), batch.work / "ui_open.applescript")
        report["uiOpen"] = {
            "returncode": open_ui.returncode,
            "stderr": (open_ui.stderr or "")[-500:],
        }
        dump = _run_osascript(_ui_dump_script(), batch.work / "ui_dump.applescript")
        (ui_dir / "export-sheet-dump.txt").write_text(
            (dump.stdout or "") + "\nSTDERR\n" + (dump.stderr or ""), encoding="utf-8"
        )
        cfg = _run_osascript(_ui_configure_transparent_export(), batch.work / "ui_cfg.applescript")
        report["uiConfig"] = (cfg.stdout or "").strip()
        dump2 = _run_osascript(_ui_dump_script(), batch.work / "ui_dump2.applescript")
        (ui_dir / "export-sheet-after-config.txt").write_text(
            (dump2.stdout or "") + "\nSTDERR\n" + (dump2.stderr or ""), encoding="utf-8"
        )

        if ui_movie.exists():
            ui_movie.unlink()
        save = _run_osascript(_ui_click_next_and_save(ui_movie), batch.work / "ui_save.applescript")
        report["uiSave"] = {
            "returncode": save.returncode,
            "stdout": (save.stdout or "").strip(),
            "stderr": (save.stderr or "")[-500:],
        }

        # Wait for export in movies/ or Keynote Where: (deck folder); then move
        deck_dir = source.parent
        candidates = [ui_movie, deck_dir / ui_movie.name]
        found = None
        deadline = time.time() + 300
        while time.time() < deadline:
            for c in candidates:
                if c.is_file() and c.stat().st_size > 10000:
                    s1 = c.stat().st_size
                    time.sleep(2)
                    if c.is_file() and c.stat().st_size == s1:
                        found = c
                        break
            if found is not None:
                break
            time.sleep(1.5)
        if found is not None and found.resolve() != ui_movie.resolve():
            if ui_movie.exists():
                ui_movie.unlink()
            shutil.move(str(found), str(ui_movie))
            report["uiMovieMovedFrom"] = str(found)
        ui = {
            "ok": ui_movie.is_file() and ui_movie.stat().st_size > 0,
            "movie": str(ui_movie) if ui_movie.is_file() else None,
            "bytes": ui_movie.stat().st_size if ui_movie.is_file() else 0,
            "uiReport": report.get("uiConfig"),
            "uiSave": report.get("uiSave"),
            "stderr": (open_ui.stderr or "") + (cfg.stderr or "") + (save.stderr or ""),
        }
        report["uiMovie"] = ui

        # Close doc without saving further changes to source (scratch only)
        _run_osascript(
            f'''
tell application id "{bid}"
  try
    close every document saving no
  end try
end tell
''',
            batch.work / "close.applescript",
        )

    # Decode + analyze
    sx, sy = SENTINEL_XY
    sw, sh = SENTINEL_WH
    box = (sx, sy, sx + sw, sy + sh)

    def analyze_movie(label: str, movie_path: Path | None, dest: Path) -> dict:
        if not movie_path or not movie_path.is_file():
            return {"ok": False, "label": label}
        frames = decode_prores_rgba(movie_path, dest)
        picks = [0, len(frames) // 2, len(frames) - 1] if frames else []
        samples = [_frame_stats(frames[i], box) for i in picks] if picks else []
        motion = _genuine_motion(frames)
        # Compare last frame RGB to settled stage PNG if available
        settled_cmp = None
        if isinstance(stage_ref, list) and stage_ref and frames:
            ref = Path(stage_ref[-1]["path"])
            if ref.is_file():
                a = load_rgba(frames[-1])[:, :, :3].astype(np.float32)
                b = load_rgba(ref)[:, :, :3].astype(np.float32)
                # Ignore sentinel region for compare
                a[sy : sy + sh, sx : sx + sw] = b[sy : sy + sh, sx : sx + sw]
                settled_cmp = {
                    "ref": str(ref),
                    "mae": float(np.mean(np.abs(a - b))),
                }
        classification = _classify_native_failure(
            {"ok": True, "bytes": movie_path.stat().st_size, "uiReport": report.get("uiConfig")},
            samples,
            motion,
        )
        codec = _ffmpeg_codec_report(movie_path)
        return {
            "ok": True,
            "label": label,
            "frameCount": len(frames),
            "samples": samples,
            "motion": motion,
            "settledCompare": settled_cmp,
            "classification": classification,
            "codec": codec,
            "genuineAlpha": any(
                s["emptyPatchAlphaMax"] <= 5 and s["transparentFrac"] > 0.05 and s["sentinelAlphaMean"] > 250
                for s in samples
            ),
        }

    if report["scriptedM4v"].get("ok"):
        report["scriptedAnalysis"] = analyze_movie(
            "scripted-m4v-no-ui-transparent", Path(report["scriptedM4v"]["movie"]), scripted_dir / "decoded"
        )
    else:
        report["scriptedAnalysis"] = {
            "ok": False,
            "classification": _classify_native_failure(report["scriptedM4v"], [], {"ok": False}),
        }

    if report["uiMovie"].get("ok"):
        report["uiAnalysis"] = analyze_movie(
            "ui-transparent-prores", Path(report["uiMovie"]["movie"]), movies / "decoded"
        )
    else:
        report["uiAnalysis"] = {
            "ok": False,
            "classification": _classify_native_failure(report["uiMovie"], [], {"ok": False}),
        }

    after = file_identity(source)
    write_json(out / "fingerprints-after.json", after.as_dict())
    report["fingerprints"] = {
        "before": before.as_dict(),
        "after": after.as_dict(),
        "unchanged": identities_match(before, after),
    }
    report["elapsedS"] = time.monotonic() - started
    write_json(out / "report.json", report)

    lines = [
        "# Recovery step 1–2 — native UI transparent ProRes control",
        "",
        f"Generated: {report['generated']}",
        "",
        "## Settings attempted",
        "",
        "```json",
        json.dumps(report["settingsAttempted"], indent=2),
        "```",
        "",
        f"No Fill attempt: `{report.get('noFillAttempt')}`",
        f"UI config: `{report.get('uiConfig')}`",
        f"UI save: `{report.get('uiSave')}`",
        "",
        "## A) Scripted `.m4v` ProRes 4444 (no transparency property)",
        "",
        f"ok={report['scriptedM4v'].get('ok')} bytes={report['scriptedM4v'].get('bytes')} "
        f"class={report['scriptedAnalysis'].get('classification')}",
        f"codec={report['scriptedAnalysis'].get('codec')}",
        f"genuineAlpha={report['scriptedAnalysis'].get('genuineAlpha')} "
        f"motion={report['scriptedAnalysis'].get('motion')}",
        "",
        "## B) Movie UI + Transparent Backgrounds",
        "",
        f"ok={report['uiMovie'].get('ok')} bytes={report['uiMovie'].get('bytes')} "
        f"class={report['uiAnalysis'].get('classification')}",
        f"codec={report['uiAnalysis'].get('codec')}",
        f"uiConfig={report.get('uiConfig')}",
        f"genuineAlpha={report['uiAnalysis'].get('genuineAlpha')} "
        f"motion={report['uiAnalysis'].get('motion')}",
        f"settledCompare={report['uiAnalysis'].get('settledCompare')}",
        "",
        f"Source unchanged: **{identities_match(before, after)}**",
        "",
        f"Samples: `{out}`",
        "",
        "UI dumps: `ui/export-sheet-dump.txt`",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if identities_match(before, after) else 3


if __name__ == "__main__":
    raise SystemExit(main())
