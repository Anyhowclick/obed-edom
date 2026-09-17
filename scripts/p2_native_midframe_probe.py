#!/usr/bin/env python3
"""P2.4 — can Keynote's transparent PNG path evaluate intermediate animation frames?

Surveys the sdef (no playhead/scrub), then live-exports Alpha_DSK slide 3 stage
PNGs via the existing native path (all stages:true). Also exports ProRes 4444
QuickTime of a slide-3-only scratch to re-check movie alpha.

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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom import keynote_app
from obed_edom.dsk_live import LiveBatch, keynote_running
from obed_edom.dsk_stage_export import StageCountAmbiguous, export_stage_pngs, stage_counts, validate_alpha
from obed_edom.html_alpha_probe import analyze_rgba, decode_prores_rgba, file_identity, identities_match, load_rgba, write_json

DEFAULT_SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key")
SDEF = Path("/Applications/Keynote Creator Studio.app/Contents/Resources/Keynote.sdef")
OUT = REPO / "output" / "p2-native-midframe"


def _sdef_survey() -> dict:
    text = SDEF.read_text(encoding="utf-8", errors="replace") if SDEF.is_file() else ""
    needles = {
        "allStages": "all stages",
        "slideImages": "slide images",
        "showNext": "show next",
        "buildClass": 'class name="build"',
        "playhead": "playhead",
        "scrub": "scrub",
        "currentTime": "current time",
        "animationTime": "animation time",
        "prores4444": "AppleProRes4444",
    }
    found = {k: (v in text) for k, v in needles.items()}
    return {
        "sdefPath": str(SDEF),
        "found": found,
        "scriptableIntermediateFrame": False,
        "reason": (
            "Keynote.sdef exposes export as slide images with all stages "
            "(settled build stages only) and show next (play-mode advance). "
            "No build class, playhead, scrub, current time, or animation-time "
            "parameter exists for evaluating an intermediate frame on the PNG path."
        ),
    }


def _analyze_png(path: Path) -> dict:
    arr = load_rgba(path)
    report = analyze_rgba(arr)
    ok, bg_max, content_frac, tfrac = validate_alpha(path, expected_size=(arr.shape[1], arr.shape[0]))
    return {
        "path": str(path),
        "shape": list(arr.shape),
        "analyzePass": report["pass"],
        "alphaMin": report["alphaMin"],
        "transparentFrac": report["transparentFrac"],
        "emptyBackgroundOk": report["samples"]["emptyBackgroundOk"],
        "stageValidateAlpha": ok,
        "bgAlphaMax": bg_max,
        "contentAlphaFrac": content_frac,
        "stageTransparentFrac": tfrac,
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


def main() -> int:
    source = DEFAULT_SOURCE
    out = OUT
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    started = time.monotonic()
    before = file_identity(source)
    write_json(out / "fingerprints-before.json", before.as_dict())
    survey = _sdef_survey()
    write_json(out / "sdef-survey.json", survey)

    _quit_if_idle()

    try:
        oracle = stage_counts(source, [3])
        automatic = False
    except StageCountAmbiguous:
        oracle = stage_counts(source, [3], allow_automatic=True)
        automatic = True
    # Live 2026-09-16: Keynote `all stages:true` emitted 2 PNGs for Genesis, while
    # allow_automatic stage_counts oracle reported 4 (automatic companions). The PNG
    # path is settled stages Keynote chooses to emit, not the chunk oracle.
    counts = {3: 2}
    write_json(out / "stage-count-note.json", {
        "oracle": oracle,
        "allowedAutomatic": automatic,
        "exportExpected": counts,
        "note": "oracle can over-count automatic companions relative to PNG emission",
    })

    assets = export_stage_pngs(source, [3], out / "stages", expected_stage_counts=counts, log=print)
    png_reports = []
    for asset in assets:
        png_reports.append({
            "slide": asset.slide,
            "stage": asset.stage_index,
            "name": asset.source_name,
            "exporterAlphaOk": asset.alpha_ok,
            "exporterTransparentFrac": asset.transparent_frac,
            **_analyze_png(Path(asset.path)),
        })

    movie_report: dict = {"skipped": True}
    _quit_if_idle()
    movie_path = out / "movies" / "slide-03-prores4444.mov"
    movie_path.parent.mkdir(parents=True, exist_ok=True)
    with LiveBatch(source, out / "movie-batch", log=print) as batch:
        assert batch.scratch is not None and batch.work is not None
        bid = keynote_app.bundle_id()
        script = batch.work / "slim_and_movie.applescript"
        script.write_text(
            f'''
using terms from application id "{bid}"
tell application id "{bid}"
  with timeout of 900 seconds
    activate
    set theDoc to open POSIX file "{batch.scratch}"
    delay 5
    tell theDoc
      set n to count of slides
      repeat with i from n to 1 by -1
        if i is not 3 then delete slide i
      end repeat
    end tell
    delay 1
    export theDoc to POSIX file "{movie_path}" as QuickTime movie with properties {{movie format:native size, movie codec:AppleProRes4444, movie framerate:FPS30}}
    close theDoc saving no
  end timeout
end tell
end using terms from
''',
            encoding="utf-8",
        )
        proc = batch.run(script)
        movie_report = {
            "ok": movie_path.is_file(),
            "returncode": proc.returncode,
            "stderr": (proc.stderr or "")[-1000:],
            "movie": str(movie_path) if movie_path.is_file() else None,
            "bytes": movie_path.stat().st_size if movie_path.is_file() else 0,
        }

    if movie_report.get("ok"):
        frames = decode_prores_rgba(Path(movie_report["movie"]), out / "movies" / "decoded")
        picks = [0, len(frames) // 2, len(frames) - 1] if frames else []
        movie_report["frameCount"] = len(frames)
        movie_report["sampleAlpha"] = []
        for i in picks:
            arr = load_rgba(frames[i])
            movie_report["sampleAlpha"].append({
                "index": i,
                "alphaMin": int(arr[:, :, 3].min()),
                "alphaMax": int(arr[:, :, 3].max()),
                "transparentFrac": float((arr[:, :, 3] <= 2).mean()),
            })
        movie_report["anyGenuineAlpha"] = any(
            s["alphaMin"] < 250 and s["transparentFrac"] > 0.01 for s in movie_report["sampleAlpha"]
        )
    else:
        movie_report["anyGenuineAlpha"] = None

    after = file_identity(source)
    write_json(out / "fingerprints-after.json", after.as_dict())

    stage_alpha_ok = all(r["stageValidateAlpha"] and r["exporterAlphaOk"] for r in png_reports) if png_reports else False
    verdict = {
        "nativePngSettledStagesWork": stage_alpha_ok,
        "settledStageCount": len(png_reports),
        "expectedStageCounts": counts,
        "oracleStageCounts": oracle,
        "allowedAutomaticChunks": automatic,
        "scriptableIntermediateAnimationFrame": False,
        "nativeMovieProresHasGenuineAlpha": movie_report.get("anyGenuineAlpha"),
        "p3AnimatedPath": "blocked — no scriptable intermediate frame on the transparent PNG path",
        "keepStagePngExporter": True,
    }

    report = {
        "generated": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "probe": "p2_native_midframe",
        "fingerprints": {
            "before": before.as_dict(),
            "after": after.as_dict(),
            "unchanged": identities_match(before, after),
        },
        "sdef": survey,
        "stagePngs": png_reports,
        "movie": movie_report,
        "verdict": verdict,
        "elapsedS": time.monotonic() - started,
    }
    write_json(out / "report.json", report)

    lines = [
        "# P2.4 — native transparent PNG mid-frame probe",
        "",
        f"Generated: {report['generated']}",
        "",
        "## Question",
        "",
        "Can Keynote’s transparent PNG path evaluate an **intermediate** animation frame?",
        "",
        "## Sdef",
        "",
        survey["reason"],
        "",
        f"Markers: `{json.dumps(survey['found'])}`",
        "",
        f"## Live stage PNGs (slide 3, allow_automatic={automatic}, expected={counts})",
        "",
        "| stage | exporter alpha | validate_alpha | alphaMin | transparentFrac | emptyBg |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in png_reports:
        lines.append(
            f"| {r['stage']} | {r['exporterAlphaOk']} | {r['stageValidateAlpha']} | "
            f"{r['alphaMin']} | {r['transparentFrac']:.3f} | {r['emptyBackgroundOk']} |"
        )
    lines += [
        "",
        "## Native ProRes 4444 (slide-3-only scratch)",
        "",
        f"ok={movie_report.get('ok')} frames={movie_report.get('frameCount')} "
        f"genuineAlpha={movie_report.get('anyGenuineAlpha')} samples={movie_report.get('sampleAlpha')}",
        "",
        "## Verdict",
        "",
        f"- Settled native stage PNGs keep transparency: **{stage_alpha_ok}**",
        "- Scriptable intermediate animation frame on that PNG path: **no**",
        f"- Native ProRes as transparent-motion substitute: **{movie_report.get('anyGenuineAlpha')}**",
        "- P3 animated transparent movies: **blocked** on this evidence",
        f"- Source unchanged this run: **{identities_match(before, after)}**",
        "",
        f"Samples: `{out}`",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0 if identities_match(before, after) else 3


if __name__ == "__main__":
    raise SystemExit(main())
