#!/usr/bin/env python3
"""HTML adversarial gate on owner-edited Minimal Alpha_DSK (4 slides).

Proves, with --preserve + PDF bg-strip:
  - empty canvas stays transparent
  - authored opaque black (white-bordered) survives strip
  - green panel keeps partial alpha (~75/255 authored opacity, not colour-keyed)
  - 1→2 Magic Move: across-slides movie CONTINUES
  - 2→3: movies deliberately RESTART (must not be stitched by preserve)

P3 stays off. Never writes owner source decks.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from p2_alpha_spike import CHROME, ChromeCdp, _wait_ready  # noqa: E402
from p2_recovery_html_dissolve_live import (  # noqa: E402
    MOVIE1_TOKEN,
    MOVIE2_TOKEN,
    _ensure_videos_playing,
    _media_snapshot,
    _movie_key,
    _norm_hash,
    _replace_hevc_movies,
    _wait_hash_clean,
    inject_preserve,
)
from obed_edom.dsk_live import keynote_running  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    analyze_rgba,
    file_identity,
    inventory_deck,
    score_motion_across_flip,
    score_playback_continuity,
    score_restart_at_slide_boundary,
    score_restart_movie_from_observations,
    score_visible_movie_motion,
    strip_export_pdf_bg_fills,
    write_json,
    write_patched_export,
)
from obed_edom.html_preview import export_html  # noqa: E402

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
OUT = REPO / "output" / "p2-recovery" / "html-adversarial"
CLICK_DELAY_S = 1.5
TRANS_S = 1.5
DENSE_FPS = 20
POST_SETTLE_S = 0.6

# Slide shape ROIs from inventory (1920×1080). Inset past white border.
BLACK_ROI_S1 = (401 + 20, 578 + 20, 174 - 40, 154 - 40)
BLACK_ROI_S2 = (545 + 20, 724 + 20, 174 - 40, 154 - 40)
GREEN_ROI_S1 = (790 + 10, 675 + 10, 174 - 20, 154 - 20)
EMPTY_CORNERS = ((1864, 8, 48, 48), (1864, 1024, 48, 48))  # right side stays emptier after MM
# Large continuing movie footprint on slide 1 (inventory). Center is unobscured.
MOVIE_ROI = (109, 795, 952, 268)
# HTML event index where slide 3 begins (2 + 4 events before it → scene #6).
SLIDE3_MIN_HASH = 6
# Fixed expected movie keys for restart evidence (not derived from observations).
# untitled.mov (movie1, Shibuya crossing) is the restart target; after the
# case-insensitive _movie_key fix, both its DOM src and pooled assetKey
# observations collapse under "movie1".
EXPECTED_MOVIE_KEYS = ("movie1",)
# Wall-clock gap required between slide-3 samples to claim progression.
PROGRESSION_WALL_S = 0.25
PROGRESSION_MEDIA_S = 0.20
# Operator-wait acceptance profiles: click delay, pre-advance straddle capture,
# and post-MM settle before draining slide-2 builds. "fast" is prior behaviour.
WAIT_PROFILES = {
    "fast": {"clickDelayS": CLICK_DELAY_S, "preAdvanceFrames": 4, "preAdvanceGapS": 0.05, "postMmSettleS": 0.4},
    "slow": {"clickDelayS": 3.5, "preAdvanceFrames": 10, "preAdvanceGapS": 0.2, "postMmSettleS": 1.5},
}


def _arg_value(name: str, default: str) -> str:
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _crop(arr: np.ndarray, xywh: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = xywh
    H, W = arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return arr[y0:y1, x0:x1]


def _score_black(arr: np.ndarray, roi: tuple[int, int, int, int]) -> dict:
    patch = _crop(arr, roi)
    if patch.size == 0:
        return {"ok": False, "reason": "empty crop", "roi": list(roi)}
    a = patch[:, :, 3].astype(np.float64)
    rgb = patch[:, :, :3].astype(np.float64)
    return {
        "ok": bool(a.mean() >= 240 and rgb.mean() <= 40),
        "alphaMean": float(a.mean()),
        "rgbMean": float(rgb.mean()),
        "shape": list(patch.shape[:2]),
        "roi": list(roi),
    }


def _score_green(arr: np.ndarray, roi: tuple[int, int, int, int] = GREEN_ROI_S1) -> dict:
    patch = _crop(arr, roi)
    if patch.size == 0:
        return {"ok": False, "reason": "empty crop"}
    a = patch[:, :, 3].astype(np.float64)
    g = patch[:, :, 1].astype(np.float64)
    partial = bool((a.mean() > 30) and (a.mean() < 230))
    greenish = bool(g.mean() > patch[:, :, 0].mean() + 15)
    return {
        "ok": partial and greenish,
        "alphaMean": float(a.mean()),
        "greenMean": float(g.mean()),
        "partial": partial,
        "greenish": greenish,
        "shape": list(patch.shape[:2]),
    }


def _score_empty(arr: np.ndarray) -> dict:
    fracs = []
    for c in EMPTY_CORNERS:
        patch = _crop(arr, c)
        if patch.size == 0:
            continue
        fracs.append(float((patch[:, :, 3] < 8).mean()))
    a = analyze_rgba(arr)
    return {
        "ok": bool(fracs) and all(f >= 0.9 for f in fracs) and a["transparentFrac"] >= 0.35,
        "cornerTransparentFrac": fracs,
        "transparentFrac": a["transparentFrac"],
        "alphaMin": a["alphaMin"],
    }


def _times(samples: list[dict], key: str = "primary") -> list[float | None]:
    """Track the continuing primary movie (max currentTime among playing videos)."""
    out: list[float | None] = []
    for s in samples:
        vids = s.get("videos") or []
        times = [
            float(v["currentTime"])
            for v in vids
            if v.get("currentTime") is not None and (v.get("readyState") or 0) >= 2
        ]
        if key == "primary":
            out.append(max(times) if times else None)
        elif key == "min":
            out.append(min(times) if times else None)
        else:
            hit = None
            for v in vids:
                if _movie_key(v.get("src") or "") == key:
                    hit = v.get("currentTime")
                    break
            out.append(hit)
    return out


def _score_black_auto(arr: np.ndarray) -> dict:
    """Find authored opaque black via near-pure opaque black pixels."""
    a = arr[:, :, 3]
    rgb = arr[:, :, :3]
    mask = (a > 250) & (rgb.max(axis=2) < 12)
    count = int(mask.sum())
    if count < 200:
        return {"ok": False, "reason": "no opaque black blob", "count": count}
    ys, xs = np.where(mask)
    vals = rgb[mask].astype(np.float64)
    return {
        "ok": bool(vals.mean() <= 12 and count >= 200),
        "count": count,
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "alphaMean": 255.0,
        "rgbMean": float(vals.mean()),
    }


def _hash_num(h: str | None) -> int | None:
    m = __import__("re").match(r"#(\d+)", _norm_hash(h))
    return int(m.group(1)) if m else None


def _mae_rgb(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.mean(np.abs(a[:, :, :3].astype(np.float64) - b[:, :, :3].astype(np.float64))))


def _score_visible_movie_motion(frame_paths: list[Path], roi: tuple[int, int, int, int] = MOVIE_ROI) -> dict:
    """Require sustained composed movie ROI motion — clock-only / one cut is not enough."""
    if len(frame_paths) < 3:
        return {"ok": False, "reason": "need >=3 frames", "n": len(frame_paths)}
    x, y, w, h = roi
    # Inset a few pixels to avoid borders, but keep the full movie face — a tiny
    # center crop can sit on a static overlay / testsrc bullseye and false-fail.
    inset = 8
    patches = []
    for p in frame_paths:
        arr = np.array(Image.open(p))
        patch = arr[y + inset : y + h - inset, x + inset : x + w - inset]
        if patch.size == 0:
            continue
        patches.append(patch)
    scored = score_visible_movie_motion(patches)
    scored["roi"] = list(roi)
    return scored


def _per_movie_obs(snap: dict) -> list[dict]:
    """Per-decoder observations; prefer entries with videoWidth>0 over null-width dupes."""
    by_id: dict[object, dict] = {}
    order: list[object] = []

    def _ingest(row: dict) -> None:
        did = row.get("decoderId")
        key = (did if did is not None else id(row), row.get("key"), row.get("fromPreservePool"))
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = row
            order.append(key)
            return
        # Prefer the observation that has real decoded dimensions.
        pw = prev.get("videoWidth") or 0
        rw = row.get("videoWidth") or 0
        if rw > 0 and pw <= 0:
            by_id[key] = row
        elif rw > 0 and pw > 0:
            # Same width family — keep the one with a clock if the other lacks it.
            if prev.get("currentTime") is None and row.get("currentTime") is not None:
                by_id[key] = row

    for v in snap.get("videos") or []:
        src = v.get("src") or ""
        _ingest(
            {
                "key": _movie_key(src),
                "srcTail": str(src)[-80:],
                "currentTime": v.get("currentTime"),
                "presentedMediaTime": v.get("presentedMediaTime"),
                "videoWidth": v.get("w") if v.get("w") is not None else v.get("videoWidth"),
                "videoHeight": v.get("h") if v.get("h") is not None else v.get("videoHeight"),
                "paused": v.get("paused"),
                "readyState": v.get("readyState"),
                "decoderId": v.get("decoderId"),
                "fromPreservePool": bool(v.get("fromPreservePool")),
            }
        )
    for p in snap.get("preservePool") or []:
        _ingest(
            {
                "key": _movie_key(p.get("key") or ""),
                "srcTail": p.get("key"),
                "currentTime": p.get("currentTime"),
                "presentedMediaTime": None,
                "videoWidth": p.get("videoWidth"),
                "videoHeight": p.get("videoHeight"),
                "paused": p.get("paused"),
                "readyState": p.get("readyState"),
                "decoderId": p.get("elId"),
                "fromPreservePool": True,
                "inDocument": p.get("inDocument"),
            }
        )
    return [by_id[k] for k in order]


def _annotate_sample(snap: dict, *, phase: str, capture_offset_s: float, scene_hash: str) -> dict:
    return {
        **snap,
        "phase": phase,
        "captureOffsetS": capture_offset_s,
        "sceneHash": scene_hash,
        "movies": _per_movie_obs(snap),
    }


def _score_neighbours_retained_clocks(
    samples: list[dict], restart_keys: list[str], min_hash: int
) -> dict:
    """Neighbour (non-restart-target) movies must not be disrupted by the restart.

    movie2 (WA0125) plays alongside the untitled.mov (movie1) restart on slide 3
    but may itself start fresh there — a near-zero first observation is not a
    disruption. Only a backward clock jump (a reset caused by our own
    retirement leaking onto the wrong key) fails this check. Informational —
    does not gate deliberateRestart2to3.
    """
    neighbour_keys = sorted(
        {
            m.get("key")
            for s in samples
            for m in (s.get("movies") or [])
            if m.get("key") and m.get("key") not in restart_keys
        }
    )
    per_key: dict[str, dict] = {}
    for key in neighbour_keys:
        obs = []
        for s in samples:
            hn = _hash_num(s.get("sceneHash"))
            if hn is None or hn < min_hash:
                continue
            for m in s.get("movies") or []:
                if m.get("key") == key and m.get("currentTime") is not None:
                    obs.append(float(m["currentTime"]))
        if len(obs) < 2:
            per_key[key] = {"ok": False, "reason": "insufficient obs", "n": len(obs)}
            continue
        max_backward_jump = max(
            (obs[i] - obs[i + 1] for i in range(len(obs) - 1)), default=0.0
        )
        not_reset = max_backward_jump <= 0.35
        per_key[key] = {
            "ok": bool(not_reset),
            "n": len(obs),
            "first": obs[0],
            "last": obs[-1],
            "min": min(obs),
            "max": max(obs),
            "maxBackwardJump": max_backward_jump,
        }
    ok = bool(per_key) and all(v["ok"] for v in per_key.values())
    return {"ok": ok, "keys": neighbour_keys, "perKey": per_key}


def _score_canvas_identical(frame_paths: list[Path]) -> dict:
    if len(frame_paths) < 2:
        return {"ok": False, "n": len(frame_paths)}
    arrs = [np.array(Image.open(p)) for p in frame_paths]
    identical = all(np.array_equal(arrs[0], a) for a in arrs[1:])
    return {
        "allFramesIdentical": identical,
        "n": len(arrs),
        "firstLastMae": _mae_rgb(arrs[0], arrs[-1]),
    }


async def _advance_until_hash_changes(chrome: ChromeCdp, max_steps: int = 8) -> list[str]:
    """Drain builds until hash changes at least once (legacy helper)."""
    return await _advance_until_hash_at_least(chrome, min_hash=None, max_steps=max_steps)


async def _advance_until_hash_at_least(
    chrome: ChromeCdp, *, min_hash: int | None, max_steps: int = 16
) -> list[str]:
    """Keep advancing until hash number >= min_hash (or any change if min_hash is None)."""
    log, _ = await _advance_until_hash_at_least_sampling(
        chrome, min_hash=min_hash, max_steps=max_steps, sample=False
    )
    return log


async def _advance_until_hash_at_least_sampling(
    chrome: ChromeCdp,
    *,
    min_hash: int | None,
    max_steps: int = 16,
    click_wall: float | None = None,
    sample_hz: float = 10.0,
    sample: bool = True,
) -> tuple[list[str], list[dict]]:
    """Advance builds while densely sampling media (scene + per-movie).

    Sampling continues *through* each advance wait so a near-zero Start Movie
    clock is not missed between drain steps.
    """
    log: list[str] = []
    samples: list[dict] = []
    if click_wall is None:
        click_wall = time.monotonic()
    dt = 1.0 / max(1.0, sample_hz)

    async def _snap(phase: str) -> dict:
        h = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        media = await _media_snapshot_with_pool(chrome) if sample else {"videos": [], "preservePool": []}
        row = _annotate_sample(
            media,
            phase=phase,
            capture_offset_s=time.monotonic() - click_wall,
            scene_hash=h,
        )
        if sample:
            samples.append(row)
        return row

    for step in range(max_steps):
        row = await _snap(f"drain-pre-{step}")
        n = _hash_num(row["sceneHash"])
        if min_hash is not None and n is not None and n >= min_hash:
            log.append(f"already:{row['sceneHash']}")
            return log, samples

        hash0 = row["sceneHash"]
        prefer = "arrow" if step % 2 == 0 else "space"
        # Try arrow/space/click in turn while sampling continuously during the wait.
        order = ["arrow", "space", "click"] if prefer == "arrow" else ["space", "arrow", "click"]
        changed = None
        for name in order:
            if name == "arrow":
                await chrome.key("ArrowRight", "ArrowRight", 39)
            elif name == "space":
                await chrome.key(" ", "Space", 32)
            else:
                await chrome.click_center()
            deadline = time.monotonic() + 4.0
            next_sample = time.monotonic()
            while time.monotonic() < deadline:
                now = time.monotonic()
                if sample and now >= next_sample:
                    await _snap(f"drain-wait-{step}-{name}")
                    next_sample = now + dt
                h = _norm_hash(
                    await chrome.evaluate(
                        "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                    )
                )
                if h != hash0:
                    changed = f"{name}:{hash0}->{h}"
                    break
                await asyncio.sleep(0.02)
            if changed:
                break
        if changed is None:
            changed = f"none:{hash0}->{hash0}"
        log.append(changed)
        await _snap(f"drain-post-{step}")
        nn = _hash_num(changed.split("->")[-1] if "->" in changed else "")
        if changed.startswith("none:"):
            # One stuck step is inconclusive; try alternate input next loop.
            continue
        if min_hash is None:
            if nn is not None and n is not None and nn != n:
                return log, samples
        elif nn is not None and nn >= min_hash:
            return log, samples
    return log, samples


def _caps(samples: list[dict]) -> list[float | None]:
    return [s.get("captureOffsetS") for s in samples]


async def _media_snapshot_with_pool(chrome: ChromeCdp) -> dict:
    snap = await _media_snapshot(chrome) or {}
    pool = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.snapshot "
        "? window.__OBED_P2_PRESERVE__.snapshot() : []"
    )
    snap = dict(snap)
    snap["preservePool"] = pool or []
    # Prefer live DOM videos; fall back to pooled detached decoders for MM gaps.
    # Also merge pool clocks when DOM videos are frozen/missing.
    dom = list(snap.get("videos") or [])
    if pool:
        pool_vids = [
            {
                "src": p.get("key") or "",
                "currentTime": p.get("currentTime"),
                "paused": p.get("paused"),
                "readyState": p.get("readyState"),
                "decoderId": p.get("elId"),
                "fromPreservePool": True,
            }
            for p in pool
        ]
        if not dom:
            snap["videos"] = pool_vids
        else:
            # Keep DOM entries but ensure we can see advancing pool clocks too.
            snap["videos"] = dom + pool_vids
        snap["videoCount"] = len(snap["videos"])
    return snap


def _pick_decoded_video(media: dict) -> dict | None:
    """First video with a decoder id or decoded width — used to tag flip-scorer frames."""
    return next(
        (
            v
            for v in (media.get("videos") or [])
            if v.get("decoderId") is not None or (v.get("w") or 0) > 0
        ),
        None,
    )


async def _pre_advance_frames(
    chrome: ChromeCdp, run_dir: Path, prefix: str, click_wall: float, n: int, gap_s: float
) -> list[dict]:
    """Capture composed frames BEFORE firing the advance.

    score_motion_across_flip needs a genuine before-flip segment; without this,
    dense capture starting only after the hash has already changed makes
    flipIndex==0 with no pre-flip pairs to score.
    """
    frames: list[dict] = []
    for i in range(n):
        media = await _media_snapshot_with_pool(chrome)
        capture_wall = time.monotonic()
        arr = await chrome.screenshot()
        name = f"{prefix}-pre{i:02d}.png"
        Image.fromarray(arr).save(run_dir / name)
        scene_hash = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        vid = _pick_decoded_video(media)
        frames.append(
            {
                "name": name,
                "i": -(n - i),
                "empty": _score_empty(arr),
                "sceneHash": scene_hash,
                "captureOffsetS": capture_wall - click_wall,
                "decoderId": vid.get("decoderId") if vid else None,
                "w": vid.get("w") if vid else None,
            }
        )
        if gap_s > 0:
            await asyncio.sleep(gap_s)
    return frames


async def _dense_after_click(
    chrome: ChromeCdp, run_dir: Path, prefix: str, click_wall: float | None = None,
    *, sample_decoder: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    samples: list[dict] = []
    frames: list[dict] = []
    decoder_frames: list[dict] = []
    # Anchor dense window to *now* so a prior wait cannot collapse all frames.
    start = time.monotonic()
    if click_wall is None:
        click_wall = start
    n = int((TRANS_S + POST_SETTLE_S) * DENSE_FPS)
    dt = 1.0 / DENSE_FPS
    for i in range(n):
        target = start + (i + 1) * dt
        while time.monotonic() < target:
            await asyncio.sleep(0.001)
        capture_wall = time.monotonic()
        media = await _media_snapshot_with_pool(chrome)
        do_shot = i % 2 == 0 or i == n - 1
        if do_shot:
            arr = await chrome.screenshot()
            name = f"{prefix}-t{i:03d}.png"
            Image.fromarray(arr).save(run_dir / name)
            scene_hash = _norm_hash(
                await chrome.evaluate(
                    "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                )
            )
            vid = _pick_decoded_video(media)
            frames.append(
                {
                    "name": name,
                    "i": i,
                    "empty": _score_empty(arr),
                    "sceneHash": scene_hash,
                    "captureOffsetS": capture_wall - click_wall,
                    "decoderId": vid.get("decoderId") if vid else None,
                    "w": vid.get("w") if vid else None,
                }
            )
        if sample_decoder and (i % 8 == 0 or i == n - 1) and len(decoder_frames) < 6:
            el_id = None
            pool = media.get("preservePool") or []
            if pool:
                el_id = pool[0].get("elId")
            else:
                for v in media.get("videos") or []:
                    if v.get("decoderId") is not None:
                        el_id = v.get("decoderId")
                        break
            fr = None
            if el_id is not None:
                fr = await chrome.evaluate(
                    f"window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.sampleFrame"
                    f" ? window.__OBED_P2_PRESERVE__.sampleFrame({int(el_id)}) : null"
                )
            if not (fr and fr.get("ok") and fr.get("dataURL")):
                fr = await chrome.evaluate(
                    """(() => {
                      const p = window.__OBED_P2_PRESERVE__;
                      const vids = Array.from(document.querySelectorAll('video'));
                      if (p && p.sampleFrame) {
                        for (const v of vids) {
                          if (v.__obedElId == null) continue;
                          const out = p.sampleFrame(v.__obedElId);
                          if (out && out.ok && out.dataURL) return out;
                        }
                      }
                      for (const v of vids) {
                        const real = v.__obedFacadeFor || v;
                        if (!(real && real.videoWidth > 0)) continue;
                        try {
                          const c = document.createElement('canvas');
                          const w = Math.min(320, real.videoWidth);
                          const h = Math.round(w * real.videoHeight / real.videoWidth);
                          c.width = w; c.height = h;
                          c.getContext('2d').drawImage(real, 0, 0, w, h);
                          return {
                            ok: true,
                            elId: real.__obedElId || null,
                            currentTime: real.currentTime,
                            width: w,
                            height: h,
                            dataURL: c.toDataURL('image/jpeg', 0.7),
                            via: 'direct-draw',
                            videoCount: vids.length
                          };
                        } catch (e) {
                          return {
                            ok: false,
                            reason: 'direct-draw-failed',
                            message: String(e && e.message || e)
                          };
                        }
                      }
                      return {
                        ok: false,
                        reason: 'no-video-pixels',
                        videoCount: vids.length,
                        preserve: !!p,
                        snap: p && p.snapshot ? p.snapshot() : [],
                        firstFail: (function(){
                          const snap = p && p.snapshot ? p.snapshot() : [];
                          if (!snap.length || !p || !p.sampleFrame) return null;
                          return p.sampleFrame(snap[0].elId);
                        })()
                      };
                    })()"""
                )
            if fr and fr.get("ok") and fr.get("dataURL"):
                raw = fr["dataURL"].split(",", 1)[-1]
                img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
                path = run_dir / f"decoder-t{len([d for d in decoder_frames if d.get('path')]):02d}.jpg"
                img.save(path)
                decoder_frames.append(
                    {
                        "path": str(path),
                        "currentTime": fr.get("currentTime"),
                        "elId": fr.get("elId", el_id),
                        "i": i,
                        "via": fr.get("via"),
                    }
                )
            elif fr is not None and sum(1 for d in decoder_frames if not d.get("path")) < 2:
                decoder_frames.append({"ok": False, "i": i, "detail": fr, "triedElId": el_id})
        samples.append(
            {
                **media,
                "i": i,
                "captureOffsetS": capture_wall - click_wall,
            }
        )
    return samples, frames, decoder_frames


async def _boot(chrome: ChromeCdp, base: str) -> dict:
    await chrome.goto("about:blank")
    await asyncio.sleep(0.05)
    await chrome.goto(f"{base}?currentSlide=1")
    ready = await _wait_ready(chrome)
    live_hash = await _wait_hash_clean(chrome)
    await _ensure_videos_playing(chrome)
    media = {}
    for _ in range(60):
        media = await _media_snapshot(chrome)
        vids = media.get("videos") or []
        playing = [
            v
            for v in vids
            if (v.get("readyState") or 0) >= 2 and not v.get("paused") and (v.get("currentTime") or 0) > 0.05
        ]
        if playing:
            break
        await _ensure_videos_playing(chrome)
        await asyncio.sleep(0.1)
    return {"ready": ready, "liveHash": live_hash, "media": media}


async def _run(player: Path) -> dict:
    reuse = "--reuse-export" in sys.argv
    disposable_mode = "--disposable" in sys.argv
    wait_profile_name = _arg_value("--wait-profile", "fast")
    wait_profile = WAIT_PROFILES[wait_profile_name]
    if OUT.exists() and not reuse:
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    runs = OUT / "runs"
    if runs.exists():
        shutil.rmtree(runs)
    runs.mkdir()

    before = file_identity(SOURCE)
    write_json(OUT / "fingerprints-before.json", before.as_dict())
    inv = inventory_deck(SOURCE)
    write_json(
        OUT / "inventory.json",
        {
            "source": before.as_dict(),
            "canvas": inv["canvas"],
            "slideCount": inv["slideCount"],
            "slides": [
                {
                    "originalOrdinal": s["originalOrdinal"],
                    "transition": s.get("transition"),
                    "magicMove": s.get("magicMove"),
                    "hasMovieStart": s.get("hasMovieStart"),
                    "builds": s.get("builds"),
                }
                for s in inv["slides"]
            ],
        },
    )

    unmodified = OUT / "html-unmodified"
    disposable_dir = OUT / "html-disposable"
    player_dir = OUT / "html-player"
    if reuse and (unmodified / "index.html").is_file():
        print("reusing HTML export at", unmodified)
    else:
        print("HTML export…")
        if unmodified.exists():
            shutil.rmtree(unmodified)
        export_html(SOURCE, unmodified, log=print)

    asset_replace_info: dict | None = None
    if disposable_mode:
        # Clone from the on-disk unmodified export — no Keynote required.
        if disposable_dir.exists():
            shutil.rmtree(disposable_dir)
        shutil.copytree(unmodified, disposable_dir)
        asset_replace_info = _replace_hevc_movies(disposable_dir)
        write_json(OUT / "asset-replace.json", asset_replace_info)
        source_dir = disposable_dir
    else:
        source_dir = unmodified

    strip_info = strip_export_pdf_bg_fills(source_dir)
    write_json(OUT / "pdf-strip.json", strip_info)
    print("stripped", [r["pdf"] for r in (strip_info.get("rewritten") or [])])
    if player_dir.exists():
        shutil.rmtree(player_dir)
    write_patched_export(source_dir, player_dir)
    preserve = inject_preserve(player_dir)
    write_json(OUT / "preserve-inject.json", preserve)

    # HTTP serve
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(player_dir), **k)

        def log_message(self, fmt, *args):  # noqa: A003
            return

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/index.html"

    run_dir = runs / "primary"
    run_dir.mkdir()
    chrome = ChromeCdp(CHROME, run_dir / "chrome-profile")
    await chrome.start()
    try:
        boot = await _boot(chrome, base)
        await chrome.evaluate(f"window.__OBED_P2_RESTART_MIN_HASH__ = {SLIDE3_MIN_HASH}")
        await asyncio.sleep(wait_profile["clickDelayS"])
        media_pre = await _media_snapshot_with_pool(chrome)
        pre = await chrome.screenshot()
        Image.fromarray(pre).save(run_dir / "pre.png")
        pre_scores = {
            "empty": _score_empty(pre),
            "black": _score_black(pre, BLACK_ROI_S1),
            "green": _score_green(pre, GREEN_ROI_S1),
        }

        hash1 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        # --- Transition A: 1→2 Magic Move + continue ---
        samples_a = [{"phase": "pre", "captureOffsetS": 0.0, **media_pre}]
        click_wall_a = time.monotonic()
        # Capture a few frames BEFORE firing the advance so the dense window
        # straddles the flip (movie already playing from boot at hash1).
        pre_frames_a = await _pre_advance_frames(
            chrome,
            run_dir,
            "mm12",
            click_wall_a,
            wait_profile["preAdvanceFrames"],
            wait_profile["preAdvanceGapS"],
        )
        # Fire the advance WITHOUT blocking on hash-settle — ChromeCdp has no
        # concurrent recv, so a blocking poll here would push dense capture
        # past the flip instant. Confirm the flip afterward instead.
        await chrome.key("ArrowRight", "ArrowRight", 39)
        immediate = await _media_snapshot_with_pool(chrome)
        samples_a.append(
            {
                **immediate,
                "phase": "hash-changed",
                "captureOffsetS": time.monotonic() - click_wall_a,
            }
        )
        dense_a, frames_a, decoder_frames = await _dense_after_click(
            chrome, run_dir, "mm12", click_wall_a, sample_decoder=True
        )
        samples_a.extend(dense_a)
        hash2 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        if hash2 == hash1:
            # MM may still be settling past the dense window; short grace poll.
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and hash2 == hash1:
                await asyncio.sleep(0.05)
                hash2 = _norm_hash(
                    await chrome.evaluate(
                        "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                    )
                )
        method_a = f"arrow-nonblocking:{hash1}->{hash2}"
        mid = await chrome.screenshot()
        Image.fromarray(mid).save(run_dir / "after-1to2.png")
        mid_scores = {
            "empty": _score_empty(mid),
            "black": _score_black_auto(mid),
            "blackFixedRoi": _score_black(mid, BLACK_ROI_S2),
            "green": _score_green(mid, GREEN_ROI_S1),
        }

        cont = score_playback_continuity(
            _times(samples_a, "primary"),
            click_i=0,
            capture_offsets=_caps(samples_a),
            dissolve_s=TRANS_S,
            position_eps=1.25,  # MM can take >0.75s before first pooled sample
        )
        mm_paths = sorted(run_dir.glob("mm12-t*.png"))
        visible_motion = _score_visible_movie_motion(mm_paths, MOVIE_ROI)
        flip_samples = []
        for f in [*pre_frames_a, *frames_a]:
            if f.get("sceneHash") is None:
                continue
            farr = np.array(Image.open(run_dir / f["name"]))
            flip_samples.append(
                {
                    "roi": _crop(farr, MOVIE_ROI),
                    "sceneHash": f["sceneHash"],
                    "captureOffsetS": f.get("captureOffsetS"),
                    "decoderId": f.get("decoderId"),
                    "w": f.get("w"),
                }
            )
        motion_across_flip = score_motion_across_flip(flip_samples, start_hash=hash1)
        decoder_motion: dict = {"ok": False, "n": 0, "attempts": len(decoder_frames)}
        ok_frames = [d for d in decoder_frames if d.get("path")]
        if len(ok_frames) >= 2:
            d0 = np.array(Image.open(ok_frames[0]["path"]))
            d1 = np.array(Image.open(ok_frames[-1]["path"]))
            decoder_motion = {
                "ok": _mae_rgb(d0, d1) >= 2.0,
                "n": len(ok_frames),
                "firstLastMae": _mae_rgb(d0, d1),
                "t0": ok_frames[0].get("currentTime"),
                "t1": ok_frames[-1].get("currentTime"),
            }
        elif decoder_frames:
            decoder_motion = {
                "ok": False,
                "n": len(ok_frames),
                "attempts": len(decoder_frames),
                "firstFailure": next((d for d in decoder_frames if not d.get("path")), None),
            }

        # 2→3 restart must come from the authored Start Movie (PRESERVE_SCRIPT's
        # boundary guard), not a manual pool clear.
        await asyncio.sleep(wait_profile["postMmSettleS"])
        await _ensure_videos_playing(chrome)
        media_mid = await _media_snapshot_with_pool(chrome)
        h_mid = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        click_wall_b = time.monotonic()
        samples_b = [
            _annotate_sample(
                media_mid, phase="pre", capture_offset_s=0.0, scene_hash=h_mid
            )
        ]
        # Drain slide-2 builds while sampling continuously through the #6 boundary.
        methods_b, drain_samples = await _advance_until_hash_at_least_sampling(
            chrome,
            min_hash=SLIDE3_MIN_HASH,
            max_steps=16,
            click_wall=click_wall_b,
            sample_hz=12.0,
        )
        samples_b.extend(drain_samples)
        dense_b, frames_b, _ = await _dense_after_click(
            chrome, run_dir, "restart23", click_wall_b
        )
        # Annotate dense samples with scene hash snapshots (best-effort).
        for s in dense_b:
            s.setdefault("phase", "dense-post")
            s["movies"] = _per_movie_obs(s)
            if "sceneHash" not in s:
                s["sceneHash"] = None
        samples_b.extend(dense_b)
        hash3 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        for s in samples_b:
            if s.get("sceneHash") is None:
                s["sceneHash"] = hash3
        post = await chrome.screenshot()
        Image.fromarray(post).save(run_dir / "after-2to3.png")
        preserved_on_slide3 = await chrome.evaluate(
            """(() => {
              const vids = Array.prototype.slice.call(
                document.querySelectorAll('video[data-obed-preserved="1"]')
              );
              const visible = vids.filter((v) => {
                if (!document.contains(v)) return false;
                const st = getComputedStyle(v);
                if (st.visibility === 'hidden' || st.display === 'none') return false;
                const r = v.getBoundingClientRect();
                return r.width > 1 && r.height > 1;
              });
              return {total: vids.length, visible: visible.length};
            })()"""
        ) or {"total": 0, "visible": 0}
        lingering_movie_overlays = await chrome.evaluate(
            """(() => {
              const footprints = [
                {x: 109, y: 795, w: 952, h: 268},
                {x: 109, y: 500, w: 663, h: 186}
              ];
              function overlaps(r, fp) {
                const ix = Math.max(0, Math.min(r.left + r.width, fp.x + fp.w) - Math.max(r.left, fp.x));
                const iy = Math.max(0, Math.min(r.top + r.height, fp.y + fp.h) - Math.max(r.top, fp.y));
                const inter = ix * iy;
                const minArea = Math.min(r.width * r.height, fp.w * fp.h);
                return minArea > 0 && inter > 0.25 * minArea;
              }
              // Only OUR remount overlays (data-obed-remounted) can be a leftover here —
              // a fresh authored movie that legitimately (re)starts on slide 3 in the same
              // footprint is not marked and must not be flagged.
              const vids = Array.prototype.slice.call(
                document.querySelectorAll('video[data-obed-remounted="1"]')
              );
              const lingering = vids.filter((v) => {
                if (!document.contains(v)) return false;
                const st = getComputedStyle(v);
                if (st.visibility === 'hidden' || st.display === 'none') return false;
                const r = v.getBoundingClientRect();
                if (!(r.width > 1 && r.height > 1)) return false;
                return footprints.some((fp) => overlaps(r, fp));
              });
              return {
                count: lingering.length,
                elIds: lingering.map((v) => v.__obedElId || null),
                preservedCount: lingering.filter(
                  (v) => v.dataset && v.dataset.obedPreserved === '1'
                ).length
              };
            })()"""
        ) or {"count": 0, "elIds": [], "preservedCount": 0}
        post_black = _score_black_auto(post)
        post_green = _score_green(post, GREEN_ROI_S1)
        overlay_gone_by_roi = (not post_black.get("ok")) and (not post_green.get("ok"))
        restart_paths = sorted(run_dir.glob("restart23-t*.png"))
        restart_canvas = _score_canvas_identical(restart_paths)

        # Per-movie timeline across the drain→slide3 boundary.
        movie_keys = sorted(
            {
                m.get("key")
                for s in samples_b
                for m in (s.get("movies") or [])
                if m.get("key")
            }
        )
        restart_scores: dict = {}
        for key in ["primary", "min", *movie_keys]:
            times = _times(samples_b, key)
            scored = score_playback_continuity(
                times, click_i=0, capture_offsets=_caps(samples_b), dissolve_s=TRANS_S
            )
            first = scored.get("firstAfterClick")
            pre_t = scored.get("preTime")
            restarted = bool(
                scored.get("remountRestart")
                or scored.get("hardRestartVsPre")
                or (first is not None and float(first) < 0.35)
                or (
                    pre_t is not None
                    and first is not None
                    and float(first) + 0.35 < float(pre_t)
                )
            )
            # Observations on/after slide-3 scenes only.
            slide3_obs = []
            for s in samples_b:
                hn = _hash_num(s.get("sceneHash"))
                if hn is None or hn < SLIDE3_MIN_HASH:
                    continue
                for m in s.get("movies") or []:
                    if key in ("primary", "min") or m.get("key") == key:
                        slide3_obs.append(
                            {
                                "t": m.get("currentTime"),
                                "w": m.get("videoWidth"),
                                "captureOffsetS": s.get("captureOffsetS"),
                                "sceneHash": s.get("sceneHash"),
                                "phase": s.get("phase"),
                                "key": m.get("key"),
                            }
                        )
            earliest_slide3 = next(
                (o for o in slide3_obs if o.get("t") is not None), None
            )
            restart_scores[key] = {
                **{k: scored.get(k) for k in (
                    "preTime", "firstAfterClick", "postTime", "remountRestart",
                    "hardRestartVsPre", "continuesThroughDissolve",
                )},
                "restarted": restarted,
                "earliestSlide3Obs": earliest_slide3,
                "slide3ObsN": len(slide3_obs),
            }

        # Fetch by kind server-side — a flat last-120 slice lets ~100+ routine
        # remount-done events crowd out the few guard/retire/clear events that
        # findings actually depend on.
        preserve_events = await chrome.evaluate(
            """(() => {
              const p = window.__OBED_P2_PRESERVE__;
              if (!p) return [];
              const keep = [
                'reuse-skip-boundary', 'retire-on-start-movie', 'pool-cleared',
                'reuse-decoder', 'createElement-video'
              ];
              const important = p.events.filter((e) => keep.indexOf(e.kind) >= 0);
              const remounts = p.events.filter((e) => e.kind === 'remount-done').slice(-20);
              return important.concat(remounts);
            })()"""
        ) or []
        clear_i = next(
            (i for i, e in enumerate(preserve_events) if e.get("kind") == "pool-cleared"),
            None,
        )
        reuse_after_clear = [
            e
            for i, e in enumerate(preserve_events)
            if e.get("kind") == "reuse-decoder" and (clear_i is None or i > clear_i)
        ]
        reuse_skip_boundary_events = [
            e for e in preserve_events if e.get("kind") == "reuse-skip-boundary"
        ]
        retire_events = [e for e in preserve_events if e.get("kind") == "retire-on-start-movie"]
        target_key = EXPECTED_MOVIE_KEYS[0]
        reuse_skip_boundary_for_target = [
            e
            for e in reuse_skip_boundary_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
        ]
        retire_events_for_target = [
            e
            for e in retire_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
        ]
        # Reuse of a preserved decoder is the LEGITIMATE 1→2 continue mechanism; only a
        # reuse on/after the restart boundary would stitch a fake restart. Scope the ban there.
        reuse_after_boundary = [
            e
            for e in preserve_events
            if e.get("kind") == "reuse-decoder"
            and (_hash_num((e.get("detail") or {}).get("sceneHash")) or -1) >= SLIDE3_MIN_HASH
        ]
        reached_slide3 = (_hash_num(hash3) or -1) >= SLIDE3_MIN_HASH
        # Fixed expected keys — never derive solely from what happened to be observed.
        intended_keys = list(EXPECTED_MOVIE_KEYS)
        per_movie_boundary: dict[str, dict] = {}
        for key in intended_keys:
            obs = []
            for s in samples_b:
                for m in s.get("movies") or []:
                    if m.get("key") != key or m.get("currentTime") is None:
                        continue
                    obs.append(
                        {
                            "t": float(m["currentTime"]),
                            "w": m.get("videoWidth"),
                            "captureOffsetS": float(s.get("captureOffsetS") or 0.0),
                            "sceneHash": s.get("sceneHash"),
                            "phase": s.get("phase"),
                            "decoderId": m.get("decoderId"),
                        }
                    )
            per_movie_boundary[key] = score_restart_movie_from_observations(
                obs,
                slide_min_hash=SLIDE3_MIN_HASH,
                progression_wall_s=PROGRESSION_WALL_S,
                progression_media_s=PROGRESSION_MEDIA_S,
            )
        boundary = score_restart_at_slide_boundary(
            reached_slide=reached_slide3,
            per_movie=per_movie_boundary,
            expected_keys=intended_keys,
            canvas_all_identical=bool(restart_canvas.get("allFramesIdentical")),
        )
        restart_playback_ok = bool(boundary["ok"])
        restart_inconclusive = bool(boundary["inconclusive"])
        restart_verdict = str(boundary["verdict"])
        missing_slide3 = list(boundary["missingSlide3Media"])
        # Stash for report detail.
        near_zero_on_slide3 = any(v["nearZeroAtBoundary"] for v in per_movie_boundary.values())
        earliest_any = None
        for v in per_movie_boundary.values():
            e = v.get("earliest")
            if e and (earliest_any is None or float(e["t"]) < float(earliest_any["t"])):
                earliest_any = e
        restart_observed = bool(boundary["allMoviesOk"])
        drain_samples_n = len(drain_samples)
        neighbours_retained = _score_neighbours_retained_clocks(
            samples_b, intended_keys, SLIDE3_MIN_HASH
        )
    finally:
        await chrome.close()
        httpd.shutdown()

    after = file_identity(SOURCE)
    write_json(OUT / "fingerprints-after.json", after.as_dict())

    findings = [
        {"id": "sourceUnchanged", "pass": after.as_dict() == before.as_dict()},
        {"id": "emptyCanvasPre", "pass": pre_scores["empty"]["ok"], "detail": pre_scores["empty"]},
        {"id": "blackSentinelOpaquePre", "pass": pre_scores["black"]["ok"], "detail": pre_scores["black"]},
        {"id": "greenTranslucentPre", "pass": pre_scores["green"]["ok"], "detail": pre_scores["green"]},
        {
            "id": "continueThroughMagicMove1to2",
            "pass": (
                bool(cont.get("continuesThroughDissolve"))
                and hash1 != hash2
                and visible_motion.get("ok", False)
                and motion_across_flip.get("ok", False)
            ),
            "detail": {
                "continues": cont.get("continuesThroughDissolve"),
                "noJump": cont.get("noJump"),
                "remountRestart": cont.get("remountRestart"),
                "pre": cont.get("preTime"),
                "firstAfter": cont.get("firstAfterClick"),
                "post": cont.get("postTime"),
                "hash": f"{hash1}->{hash2}",
                "method": method_a,
                "visibleMovieMotion": visible_motion,
                "motionAcrossFlip": motion_across_flip,
                "decoderMotion": decoder_motion,
                "reuseEvents": [
                    e for e in preserve_events if e.get("kind") == "reuse-decoder"
                ][:8],
                "note": (
                    "Clock continuity alone is insufficient; composed movie ROI must move "
                    "before, across, and after the scene-hash flip. "
                    "Decoder sampleFrame motion without visible motion = detached clock."
                ),
            },
        },
        {
            "id": "blackSurvivesAfter1to2",
            "pass": mid_scores["black"]["ok"],
            "detail": mid_scores["black"],
        },
        {
            "id": "emptyCanvasAfter1to2",
            "pass": mid_scores["empty"]["ok"],
            "detail": mid_scores["empty"],
        },
        {
            "id": "overlappingArtworkComposedAfter1to2",
            "pass": bool(mid_scores["blackFixedRoi"]["ok"] and mid_scores["green"]["ok"]),
            "detail": {
                "blackFixedRoi": mid_scores["blackFixedRoi"],
                "blackAuto": mid_scores["black"],
                "green": mid_scores["green"],
            },
            "note": (
                "Must hold at the FIXED authored ROIs (BLACK_ROI_S2, GREEN_ROI_S1) — "
                "black-anywhere (_score_black_auto) is satisfied by the movie's own "
                "test pattern and does not prove the overlay is unoccluding artwork."
            ),
        },
        {
            "id": "reachedSlide3",
            "pass": reached_slide3,
            "detail": {
                "hash": f"{hash2}->{hash3}",
                "minHash": SLIDE3_MIN_HASH,
                "methods": methods_b,
            },
        },
        {
            "id": "overlayRemovedOnLeave",
            "pass": bool(
                preserved_on_slide3.get("visible", 1) == 0
                and lingering_movie_overlays.get("count", 1) == 0
            ),
            "detail": {
                "preservedVideosOnSlide3": preserved_on_slide3,
                "lingeringMovieOverlays": lingering_movie_overlays,
                "roiCheck": {"black": post_black, "green": post_green},
                "roiOverlayGone": overlay_gone_by_roi,
                "hash": hash3,
            },
            "note": (
                "Requires zero visible preserved videos AND zero visible <video> "
                "elements overlapping the slide-1/2 movie footprints on slide 3 "
                "(catches a lingering overlay even if it lost its preserved marker). "
                "The ROI check is informational only, not gating."
            ),
        },
        {
            "id": "deliberateRestart2to3",
            "pass": restart_playback_ok,
            "verdict": restart_verdict,
            "detail": {
                "movies": restart_scores,
                "perMovieBoundary": per_movie_boundary,
                "missingSlide3Media": missing_slide3,
                "hash": f"{hash2}->{hash3}",
                "methods": methods_b,
                "reachedSlide3": reached_slide3,
                "restartObservedNearZero": restart_observed or near_zero_on_slide3,
                "nearZeroOnSlide3": near_zero_on_slide3,
                "earliestSlide3Obs": earliest_any,
                "restartInconclusive": restart_inconclusive,
                "restartCanvas": restart_canvas,
                "poolCleared": clear_i is not None,
                "reuseAfterClear": reuse_after_clear[:6],
                "reuseSkipBoundaryEvents": reuse_skip_boundary_events[:6],
                "retireEvents": retire_events[:6],
                "neighboursRetainedClocks": bool(neighbours_retained.get("ok")),
                "neighboursRetainedClocksDetail": neighbours_retained,
                "drainSampleN": drain_samples_n,
                "note": (
                    "Pass only when each intended movie has slide-3 observations "
                    "with near-zero at the boundary and later progression. "
                    "Pre-boundary restart_observed alone is not a pass. "
                    "Missing slide-3 media → inconclusive/fail. "
                    "Restart now comes from the authored Start Movie via the "
                    "boundary-guarded reuse skip, not a manual pool clear."
                ),
            },
        },
        {
            "id": "preserveDidNotBlockRestart",
            "pass": bool(
                restart_playback_ok
                and clear_i is None
                and len(reuse_skip_boundary_for_target) >= 1
                and len(retire_events_for_target) >= 1
                and len(reuse_after_boundary) == 0
            ),
            "verdict": restart_verdict if restart_playback_ok or restart_inconclusive else "fail",
            "note": (
                "decoder-preserve must not stitch a deliberate Start Movie restart. "
                "Requires: no manual pool-cleared event at all, at least one "
                "reuse-skip-boundary AND one retire-on-start-movie event for the "
                "target key, and zero reuse-decoder events ON/AFTER the boundary "
                "(pre-boundary 1→2 reuse is the legitimate continue) — the boundary "
                "guard + retirement, not a manual clear, keeps the restart fresh."
            ),
            "detail": {
                "targetKey": target_key,
                "poolCleared": clear_i is not None,
                "reuseSkipBoundaryForTargetN": len(reuse_skip_boundary_for_target),
                "retireEventsForTargetN": len(retire_events_for_target),
                "reuseAfterBoundary": reuse_after_boundary[:6],
                "reuseAfterBoundaryScenes": [
                    (e.get("detail") or {}).get("sceneHash") for e in reuse_after_boundary[:6]
                ],
                "reuseSkipBoundaryEvents": reuse_skip_boundary_events[:6],
                "retireEvents": retire_events[:6],
            },
        },
    ]
    # Restart inconclusive must not count as overall success.
    success = all(f["pass"] for f in findings) and not restart_inconclusive
    report = {
        "probe": "p2_recovery_html_adversarial",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": before.as_dict(),
        "sourceUnchanged": after.as_dict() == before.as_dict(),
        "deckFixture": "Minimal Alpha_DSK.key (owner adversarial 4-slide)",
        "fixture": "disposable-h264" if disposable_mode else "hevc-original",
        "assetReplace": asset_replace_info,
        "waitProfile": wait_profile_name,
        "waitProfileValues": wait_profile,
        "clickDelayS": wait_profile["clickDelayS"],
        "reusedExport": reuse,
        "stripPdf": strip_info,
        "preserve": preserve,
        "boot": boot,
        "preScores": pre_scores,
        "midScores": mid_scores,
        "continue1to2": cont,
        "visibleMovieMotion": visible_motion,
        "motionAcrossFlip": motion_across_flip,
        "decoderMotion": decoder_motion,
        "restart2to3": restart_scores,
        "perMovieBoundary": per_movie_boundary,
        "restartCanvas": restart_canvas,
        "restartVerdict": restart_verdict,
        "hashes": {"h1": hash1, "h2": hash2, "h3": hash3},
        "preserveEvents": preserve_events,
        "findings": findings,
        "success": success,
        "p3": "still unwired",
        "rois": {
            "blackS1": BLACK_ROI_S1,
            "blackS2": BLACK_ROI_S2,
            "greenS1": GREEN_ROI_S1,
            "emptyCorners": EMPTY_CORNERS,
            "movie": list(MOVIE_ROI),
        },
        "tokens": {"movie1": MOVIE1_TOKEN, "movie2": MOVIE2_TOKEN},
        "note": (
            "Disposable H.264 fixture: Untitled.mov replaced with a browser-decodable "
            "yuv420p test pattern under the same filenames."
            if disposable_mode
            else (
                "Untitled.mov in this export is HEVC Main 10 — Chrome often advances "
                "currentTime (AAC) with videoWidth=0 (audio-only clock); decode/motion/"
                "restart findings cannot pass on this fixture. Pass --disposable to gate "
                "on the browser-decodable H.264 clone instead."
            )
        ),
    }
    write_json(OUT / "report.json", report)

    lines = [
        "# HTML adversarial gate — Minimal Alpha_DSK",
        "",
        f"Generated: {report['generated']}",
        f"Source unchanged: **{report['sourceUnchanged']}**",
        f"success: **{success}**",
        "",
        "## Findings",
        "",
    ]
    for f in findings:
        extra = f" — {f['note']}" if f.get("note") else ""
        verdict = f" ({f['verdict']})" if f.get("verdict") and f["verdict"] != ("pass" if f["pass"] else "fail") else ""
        lines.append(f"- {f['id']}: **{f['pass']}**{verdict}{extra}")
    lines += ["", f"Samples: `{OUT}`", "", "P3 still unwired."]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return report


def main() -> int:
    reuse = "--reuse-export" in sys.argv
    if keynote_running() and not reuse:
        raise SystemExit(
            "Keynote is already running — refuse to force-quit an owner session. "
            "Quit Keynote and re-run, or pass --reuse-export."
        )
    report = asyncio.run(_run(OUT / "html-player"))
    return 0 if report.get("sourceUnchanged") and report.get("success") else (2 if not report.get("sourceUnchanged") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
