#!/usr/bin/env python3
"""Dense short windows on Alpha_DSK mixed UI-transparent movie (no full decode).

Targets remaining uncertainty after the 8-sparse-frame probe:
- alpha / geometry / overlays through transitions 6→7 and 7→8
- continuous movie playback + build sync around movie-starts
- click-boundary / final-frame hold behaviour at slide edges

Uses the existing UI transparent ProRes under mixed-11-13-transparent/movies/.
Compares window anchors to native settled stage PNGs from the same probe.
Alpha_DSK transitions are dissolve (not Magic Move) — Magic Move stays open.

P3 stays off. Never writes owner source decks.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import p2_recovery_mixed_transparent as base  # noqa: E402
from obed_edom.fixture_paths import fixture  # noqa: E402
from obed_edom.html_alpha_probe import load_rgba, write_json  # noqa: E402
from obed_edom.maps_movie import ffmpeg_exe  # noqa: E402

PROBE = fixture("p2-recovery") / "mixed-11-13-transparent"
OUT = fixture("p2-recovery") / "mixed-dense-windows"
MOVIE = PROBE / "movies" / "mixed-11-13-ui-transparent-prores4444.mov"
FPS = 30
# ± half-window around each event (seconds)
MOVIE_START_HALF = 0.40
TRANSITION_PAD = 0.15  # pad beyond declared transition duration


def _duration(movie: Path) -> float:
    return base._ffprobe_duration(movie)


def _mae_rgb(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a[:, :, :3].astype(np.float32) - b[:, :, :3].astype(np.float32))))


def _extract_window(movie: Path, t0: float, t1: float, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    for p in dest.glob("*.png"):
        p.unlink()
    exe = ffmpeg_exe()
    assert exe
    dur = max(0.05, t1 - t0)
    # fps=30 over the window only
    pattern = str(dest / "f%04d.png")
    proc = subprocess.run(
        [
            exe,
            "-y",
            "-ss",
            f"{t0:.3f}",
            "-i",
            str(movie),
            "-t",
            f"{dur:.3f}",
            "-vf",
            f"fps={FPS}",
            "-pix_fmt",
            "rgba",
            pattern,
        ],
        capture_output=True,
        text=True,
    )
    frames = sorted(dest.glob("f*.png"))
    if not frames:
        raise RuntimeError(f"no frames for [{t0},{t1}): {(proc.stderr or '')[-400:]}")
    return frames


def _coarse_cut_search(movie: Path, center: float, span: float, dest: Path) -> dict:
    """Sample ~4 fps around center; pick max pairwise MAE as cut hint."""
    t0 = max(0.0, center - span)
    t1 = center + span
    frames = _extract_window(movie, t0, t1, dest)
    # downsample to ~4fps worth by stride
    stride = max(1, FPS // 4)
    picks = frames[::stride]
    arrs = [load_rgba(p) for p in picks]
    best_i, best_mae = 0, -1.0
    maes = []
    for i in range(len(arrs) - 1):
        m = _mae_rgb(arrs[i], arrs[i + 1])
        maes.append(m)
        if m > best_mae:
            best_mae, best_i = m, i
    cut_t = t0 + (best_i * stride + 0.5) / FPS
    return {
        "center": center,
        "search": [t0, t1],
        "cutHintT": cut_t,
        "maxPairMae": best_mae,
        "pairMaes": maes,
        "frameCount": len(frames),
    }


def _score_sequence(frames: list[Path], slide_roi: dict, t0: float) -> dict:
    scores = []
    for i, p in enumerate(frames):
        sc = base._analyze_png(p, slide_roi)
        sc["index"] = i
        sc["t"] = t0 + i / FPS
        scores.append(sc)

    empty_fracs = [(s.get("empty") or {}).get("transparentFrac") for s in scores]
    empty_fracs = [x for x in empty_fracs if x is not None]
    foot_opaque = []
    for s in scores:
        for pm in s.get("perMovie") or []:
            foot_opaque.append(pm.get("opaqueFrac"))
        if not s.get("perMovie") and s.get("movieFootprint"):
            foot_opaque.append(s["movieFootprint"].get("opaqueFrac"))
    text_opaque = [(s.get("textOverlays") or {}).get("opaqueFrac") for s in scores]
    text_opaque = [x for x in text_opaque if x is not None]

    # Motion / hold: pairwise RGB MAE
    arrs = [load_rgba(p) for p in frames]
    pair = [_mae_rgb(arrs[i], arrs[i + 1]) for i in range(len(arrs) - 1)] if len(arrs) > 1 else []
    changing = sum(1 for m in pair if m > 0.5)
    # Final-frame hold: last 5 frames nearly identical
    hold = False
    if len(pair) >= 4:
        hold = all(m < 0.35 for m in pair[-4:])

    return {
        "frameCount": len(frames),
        "t0": t0,
        "t1": t0 + (len(frames) - 1) / FPS if frames else t0,
        "emptyTransparentMin": min(empty_fracs) if empty_fracs else None,
        "emptyTransparentMax": max(empty_fracs) if empty_fracs else None,
        "emptyAlphaStable": bool(empty_fracs) and min(empty_fracs) >= 0.85,
        "footprintOpaqueMin": min(foot_opaque) if foot_opaque else None,
        "footprintOpaqueMax": max(foot_opaque) if foot_opaque else None,
        "textOverlayOpaqueMin": min(text_opaque) if text_opaque else None,
        "textOverlayOpaqueMax": max(text_opaque) if text_opaque else None,
        "pairwiseMae": pair,
        "changingPairs": changing,
        "motionPresent": changing >= 1,
        "finalFrameHold": hold,
        "frames": [
            {
                "index": s["index"],
                "t": s["t"],
                "emptyT": (s.get("empty") or {}).get("transparentFrac"),
                "footO": (s.get("movieFootprint") or {}).get("opaqueFrac"),
                "textO": (s.get("textOverlays") or {}).get("opaqueFrac"),
                "globalT": s["global"]["transparentFrac"],
            }
            for s in scores
        ],
    }


def _compare_to_stage(frame_path: Path, stage_paths: list[Path], slide_roi: dict) -> dict:
    if not stage_paths:
        return {"ok": False, "reason": "no stage png"}
    arr = load_rgba(frame_path)
    best = None
    for sp in stage_paths:
        st = load_rgba(sp)
        if st.shape != arr.shape:
            # resize stage to frame if needed
            from PIL import Image

            st = np.array(Image.fromarray(st).resize((arr.shape[1], arr.shape[0]), Image.Resampling.BILINEAR))
        mae = _mae_rgb(arr, st)
        # empty-ROI alpha agreement
        sc_f = base._analyze_png(frame_path, slide_roi)
        sc_s = base._analyze_png(sp, slide_roi)
        entry = {
            "stage": sp.name,
            "rgbMae": mae,
            "frameEmptyT": (sc_f.get("empty") or {}).get("transparentFrac"),
            "stageEmptyT": (sc_s.get("empty") or {}).get("transparentFrac"),
            "frameFootO": (sc_f.get("movieFootprint") or {}).get("opaqueFrac"),
            "stageFootO": (sc_s.get("movieFootprint") or {}).get("opaqueFrac"),
        }
        if best is None or mae < best["rgbMae"]:
            best = entry
    assert best is not None
    best["ok"] = best["rgbMae"] < 25.0  # soft visual near-dup on wall/DSK content
    return best


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if not MOVIE.is_file():
        raise SystemExit(f"missing movie: {MOVIE}")

    rois = json.loads((PROBE / "rois.json").read_text())
    roi_by = {s["originalOrdinal"]: s for s in rois["slides"]}
    dur = _duration(MOVIE)
    report: dict = {
        "probe": "p2_recovery_mixed_dense_windows",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "movie": str(MOVIE),
        "durationS": dur,
        "fps": FPS,
        "fixture": "Alpha_DSK slides 6–8 (dissolve transitions; Magic Move not present)",
        "magicMove": {
            "tested": False,
            "reason": "Alpha_DSK mixed clips use dissolve/none — Magic Move during motion remains open",
        },
        "p3": "still unwired",
    }

    # Coarse 2fps scan to locate real cuts (inventory timeline is unreliable).
    coarse_dir = OUT / "coarse-2fps"
    if coarse_dir.exists():
        shutil.rmtree(coarse_dir)
    coarse_dir.mkdir(parents=True)
    exe = ffmpeg_exe()
    assert exe
    subprocess.run(
        [exe, "-y", "-i", str(MOVIE), "-vf", "fps=2", "-pix_fmt", "rgba", str(coarse_dir / "c%04d.png")],
        capture_output=True,
        text=True,
        check=False,
    )
    coarse = sorted(coarse_dir.glob("c*.png"))
    arrs = [load_rgba(p) for p in coarse]
    maes = [_mae_rgb(arrs[i], arrs[i + 1]) for i in range(len(arrs) - 1)]
    peaks = []
    for i, m in enumerate(maes):
        left = maes[i - 1] if i else 0.0
        right = maes[i + 1] if i + 1 < len(maes) else 0.0
        if m > 1.5 and m >= left and m >= right:
            peaks.append({"i": i, "t": (i + 0.5) / 2.0, "mae": m})
    write_json(OUT / "coarse-maes.json", {"maes": maes, "peaks": peaks})
    shutil.rmtree(coarse_dir)

    # Slide cuts: strong peaks ≥8s apart inside (10, dur-2); keep top-2 by MAE.
    cands = sorted([p for p in peaks if p["mae"] >= 3.0], key=lambda p: p["t"])
    spaced: list[dict] = []
    for p in cands:
        if not spaced or p["t"] - spaced[-1]["t"] >= 8.0:
            spaced.append(p)
    spaced = [p for p in spaced if 10.0 < p["t"] < dur - 2.0]
    if len(spaced) > 2:
        spaced = sorted(sorted(spaced, key=lambda p: -p["mae"])[:2], key=lambda p: p["t"])
    report["slideCuts"] = spaced
    report["timelineMethod"] = "coarse 2fps MAE peaks; slide cuts ≥8s apart"

    t67 = spaced[0]["t"] if len(spaced) >= 1 else dur * 0.4
    t78 = spaced[1]["t"] if len(spaced) >= 2 else dur * 0.75
    windows_spec = [
        {"id": "movie-start-6", "kind": "movie-start", "slide": 6, "t0": 0.0, "t1": min(dur, 0.8)},
        {
            "id": "transition-6-to-7",
            "kind": "transition",
            "fromSlide": 6,
            "intoSlide": 7,
            "slide": 7,
            "t0": max(0.0, t67 - 1.0),
            "t1": min(dur - 0.01, t67 + 1.0),
            "cutHintT": t67,
        },
        {
            "id": "movie-start-7",
            "kind": "movie-start",
            "slide": 7,
            "t0": max(0.0, t67 + 0.05),
            "t1": min(dur - 0.01, t67 + 0.85),
        },
        {
            "id": "transition-7-to-8",
            "kind": "transition",
            "fromSlide": 7,
            "intoSlide": 8,
            "slide": 8,
            "t0": max(0.0, t78 - 1.0),
            "t1": min(dur - 0.01, t78 + 1.0),
            "cutHintT": t78,
        },
        {
            "id": "movie-start-8",
            "kind": "movie-start",
            "slide": 8,
            "t0": max(0.0, t78 + 0.05),
            "t1": min(dur - 0.01, t78 + 0.85),
        },
        {"id": "final-hold", "kind": "hold", "slide": 8, "t0": max(0.0, dur - 1.0), "t1": dur - 0.01},
    ]
    write_json(OUT / "windows-spec.json", windows_spec)

    # Stage PNG refs
    stage_dir = PROBE / "stages-after-nofill"
    stage_pngs = sorted(stage_dir.rglob("*.png")) if stage_dir.exists() else []
    stage_buckets = base._assign_stage_pngs(stage_pngs, rois)

    window_reports = []
    for spec in windows_spec:
        wdir = OUT / "windows" / spec["id"]
        frames = _extract_window(MOVIE, spec["t0"], spec["t1"], wdir)
        if spec["kind"] == "transition":
            mid = len(frames) // 2
            from_roi = roi_by[spec["fromSlide"]]
            into_roi = roi_by[spec["intoSlide"]]
            seq_from = _score_sequence(frames[: max(1, mid)], from_roi, spec["t0"])
            seq_into = _score_sequence(frames[mid:], into_roi, spec["t0"] + mid / FPS)
            seq = {
                "fromHalf": seq_from,
                "intoHalf": seq_into,
                "frameCount": len(frames),
                "emptyAlphaStable": seq_from["emptyAlphaStable"] and seq_into["emptyAlphaStable"],
                "motionPresent": seq_from["motionPresent"] or seq_into["motionPresent"],
                "finalFrameHold": seq_into["finalFrameHold"],
            }
            native = {
                "startVsFromStage": _compare_to_stage(
                    frames[0], stage_buckets.get(spec["fromSlide"]) or [], from_roi
                ),
                "endVsIntoStage": _compare_to_stage(
                    frames[-1], stage_buckets.get(spec["intoSlide"]) or [], into_roi
                ),
            }
            arrs = [load_rgba(p) for p in frames]
            pair = [_mae_rgb(arrs[i], arrs[i + 1]) for i in range(len(arrs) - 1)]
            delivery = {
                "maxPairMae": max(pair) if pair else 0.0,
                "meanPairMae": float(np.mean(pair)) if pair else 0.0,
                "cleanBoundaryHint": bool(pair) and max(pair) > 2.0,
            }
        else:
            roi = roi_by[spec["slide"]]
            seq = _score_sequence(frames, roi, spec["t0"])
            native = {
                "startVsStage": _compare_to_stage(frames[0], stage_buckets.get(spec["slide"]) or [], roi),
                "endVsStage": _compare_to_stage(frames[-1], stage_buckets.get(spec["slide"]) or [], roi),
            }
            delivery = {
                "movieStartMotion": seq.get("motionPresent"),
                "holdAfterStart": seq.get("finalFrameHold"),
            }

        wr = {**spec, "sequence": seq, "nativeCompare": native, "delivery": delivery}
        window_reports.append(wr)
        write_json(wdir / "window.json", wr)

    report["windows"] = window_reports

    findings = [
        {
            "id": "emptyAlphaThroughWindows",
            "pass": all(w["sequence"].get("emptyAlphaStable") for w in window_reports),
        },
        {
            "id": "transitionMotionPresent",
            "pass": all(w["sequence"].get("motionPresent") for w in window_reports if w["kind"] == "transition"),
        },
        {
            "id": "nativeAnchorNearStage",
            "pass": all(
                (
                    (w["nativeCompare"].get("startVsFromStage") or w["nativeCompare"].get("startVsStage") or {}).get(
                        "ok"
                    )
                    and (
                        w["nativeCompare"].get("endVsIntoStage") or w["nativeCompare"].get("endVsStage") or {}
                    ).get("ok")
                )
                for w in window_reports
                if w["kind"] != "hold"
            ),
        },
        {
            "id": "movieStartFootprintOpaque",
            "pass": all(
                (w["sequence"].get("footprintOpaqueMax") or 0) >= 0.8 or w.get("slide") == 8
                for w in window_reports
                if w["kind"] == "movie-start"
            ),
        },
        {
            "id": "finalFrameHold",
            "pass": any(w["id"] == "final-hold" and w["sequence"].get("finalFrameHold") for w in window_reports),
        },
    ]
    open_q = [
        "Magic Move during motion — Alpha_DSK mixed clips are dissolve/none only",
        "Native Keynote play-mode pixel compare (anchors = settled stage PNGs, not live playhead)",
        "Continuous in-clip movie sync beyond short start windows (only burst samples)",
    ]
    report["findings"] = findings
    report["openQuestions"] = open_q
    report["success"] = all(f["pass"] for f in findings)
    write_json(OUT / "report.json", report)

    lines = [
        "# Dense windows — Alpha_DSK mixed UI transparent movie",
        "",
        f"Generated: {report['generated']}",
        "",
        f"Movie: `{MOVIE.name}` ({dur:.2f}s) — coarse 2fps peak find + dense 30fps bursts (no full decode).",
        f"Slide cuts: `{[(round(p['t'], 2), round(p['mae'], 2)) for p in spaced]}`",
        f"Fixture: {report['fixture']}",
        "",
        "## Windows",
        "",
    ]
    for w in window_reports:
        seq = w["sequence"]
        lines.append(
            f"- **{w['id']}** [{w['t0']:.2f},{w['t1']:.2f}] frames={seq.get('frameCount')} "
            f"emptyStable={seq.get('emptyAlphaStable')} motion={seq.get('motionPresent')} "
            f"hold={seq.get('finalFrameHold')} delivery=`{w.get('delivery')}`"
        )
        lines.append(f"  native: `{json.dumps(w['nativeCompare'])[:220]}`")
    lines += ["", "## Findings", ""]
    for f in findings:
        lines.append(f"- {f['id']}: **{f['pass']}**")
    lines += ["", "## Still open", ""]
    for q in open_q:
        lines.append(f"- {q}")
    lines += ["", "P3 still unwired.", f"Samples: `{OUT}`"]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
