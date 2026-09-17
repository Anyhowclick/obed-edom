#!/usr/bin/env python3
"""Disposable HTML decode probe — browser-decodable movies + unchanged preserve.

Clones the adversarial HTML export (no Keynote), replaces HEVC Untitled.mov
assets with H.264 test patterns Chrome can decode, injects the same preserve
script, and measures:

  1. actual video decode (videoWidth>0, changing sampleFrame pixels)
  2. *visible* colour-pattern motion through Magic Move 1→2 (composed ROI must
     show testsrc bars and match decoder — not a frozen street poster)
  3. each movie's restart + progression on slide-3 (#6+) samples

Does not write owner source decks. P3 stays off.
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
from p2_recovery_html_adversarial import (  # noqa: E402
    EXPECTED_MOVIE_KEYS,
    MOVIE_ROI,
    PROGRESSION_MEDIA_S,
    PROGRESSION_WALL_S,
    SLIDE3_MIN_HASH,
    _advance_hash,
    _advance_until_hash_at_least_sampling,
    _annotate_sample,
    _dense_after_click,
    _hash_num,
    _media_snapshot_with_pool,
    _norm_hash,
    _score_visible_movie_motion,
)
from p2_recovery_html_dissolve_live import (  # noqa: E402
    _ensure_videos_playing,
    _wait_hash_clean,
    inject_preserve,
)
from obed_edom.html_alpha_probe import (  # noqa: E402
    file_identity,
    score_restart_at_slide_boundary,
    score_restart_movie_from_observations,
    score_visible_movie_motion,
    strip_export_pdf_bg_fills,
    write_json,
    write_patched_export,
)

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
ADV_UNMOD = REPO / "output" / "p2-recovery" / "html-adversarial" / "html-unmodified"
OUT = REPO / "output" / "p2-recovery" / "html-decode-probe"


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"imageio-ffmpeg required for disposable H.264 encode: {e}") from e


def _write_h264_pattern(dest: Path, *, seconds: float = 46.0333, fps: int = 30) -> dict:
    """Write a browser-decodable H.264 MP4 (yuv420p) with a moving bar.

    Duration matches Keynote export filenames/metadata so the player timeline
    stays coherent.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp4")
    cmd = [
        _ffmpeg(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=1920x540:rate={fps}:duration={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=44100:duration={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    import subprocess

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not tmp.is_file():
        raise RuntimeError(f"ffmpeg encode failed: {proc.stderr[-800:]}")
    dest.write_bytes(tmp.read_bytes())
    tmp.unlink(missing_ok=True)
    return {"path": str(dest), "bytes": dest.stat().st_size, "seconds": seconds, "fps": fps}


def _replace_hevc_movies(root: Path) -> dict:
    """Replace Untitled.mov* HEVC assets with H.264 test patterns (same filenames)."""
    replaced = []
    for mov in sorted(root.rglob("Untitled.mov-*.mov")):
        # Parse duration from Keynote export name: …-0.0000-46.0333.mov
        seconds = 46.0333
        try:
            tail = mov.name.rsplit("-", 1)[-1]
            seconds = float(tail.replace(".mov", ""))
        except ValueError:
            pass
        info = _write_h264_pattern(mov, seconds=seconds)
        info["replaced"] = str(mov.relative_to(root))
        replaced.append(info)
    return {"replacedN": len(replaced), "files": replaced}


async def _sample_decoder_frames(chrome: ChromeCdp, run_dir: Path, n: int = 6, gap_s: float = 0.25) -> list[dict]:
    frames: list[dict] = []
    for i in range(n):
        fr = await chrome.evaluate(
            """(() => {
              const p = window.__OBED_P2_PRESERVE__;
              const vids = Array.from(document.querySelectorAll('video'));
              const tryIds = [];
              if (p && p.snapshot) {
                for (const s of p.snapshot()) if (s.elId != null) tryIds.push(s.elId);
              }
              for (const v of vids) if (v.__obedElId != null) tryIds.push(v.__obedElId);
              if (p && p.sampleFrame) {
                for (const id of tryIds) {
                  const out = p.sampleFrame(id);
                  if (out && out.ok && out.dataURL) return out;
                }
              }
              for (const v of vids) {
                const real = v.__obedFacadeFor || v;
                if (!(real && real.videoWidth > 0)) continue;
                const c = document.createElement('canvas');
                const w = Math.min(320, real.videoWidth);
                const h = Math.round(w * real.videoHeight / real.videoWidth);
                c.width = w; c.height = h;
                c.getContext('2d').drawImage(real, 0, 0, w, h);
                return {
                  ok: true,
                  elId: real.__obedElId || null,
                  currentTime: real.currentTime,
                  videoWidth: real.videoWidth,
                  videoHeight: real.videoHeight,
                  dataURL: c.toDataURL('image/jpeg', 0.7),
                  via: 'direct-draw'
                };
              }
              return {
                ok: false,
                reason: 'no-pixels',
                videoCount: vids.length,
                snap: p && p.snapshot ? p.snapshot() : []
              };
            })()"""
        )
        if fr and fr.get("ok") and fr.get("dataURL"):
            raw = fr["dataURL"].split(",", 1)[-1]
            img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
            path = run_dir / f"decoder-t{len(frames):02d}.jpg"
            img.save(path)
            frames.append(
                {
                    "path": str(path),
                    "currentTime": fr.get("currentTime"),
                    "videoWidth": fr.get("videoWidth") or fr.get("width"),
                    "elId": fr.get("elId"),
                    "via": fr.get("via") or fr.get("where"),
                }
            )
        else:
            frames.append({"ok": False, "detail": fr})
        await asyncio.sleep(gap_s)
    return frames


def _crop_movie_roi(arr: np.ndarray, roi: tuple[int, int, int, int] = MOVIE_ROI) -> np.ndarray:
    x, y, w, h = roi
    H, W = arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return arr[y0:y1, x0:x1]


def _looks_like_colour_bars(patch: np.ndarray) -> dict:
    """ffmpeg testsrc is vivid striped colour; street posters are flatter chroma."""
    if patch.size == 0 or patch.shape[0] < 8 or patch.shape[1] < 8:
        return {"ok": False, "reason": "empty/small crop"}
    rgb = patch[:, :, :3].astype(np.float64)
    std = rgb.reshape(-1, 3).std(axis=0)
    sat = float(((rgb.max(axis=2) - rgb.min(axis=2)) > 60).mean())
    # Horizontal stripe energy: row-mean variance is high for testsrc.
    row_mean = rgb.mean(axis=1)
    row_var = float(row_mean.var())
    ok = bool(
        (float(std.mean()) > 35 and sat > 0.12 and row_var > 200)
        or (sat > 0.45 and float(std.mean()) > 70)
    )
    return {
        "ok": ok,
        "channelStdMean": float(std.mean()),
        "satFrac": sat,
        "rowMeanVar": row_var,
        "shape": list(patch.shape[:2]),
    }


def _composed_vs_decoder_mae(composed: np.ndarray, decoder_rgb: np.ndarray) -> dict:
    if composed.size == 0 or decoder_rgb.size == 0:
        return {"ok": False, "reason": "empty", "mae": None}
    target = Image.fromarray(composed[:, :, :3].astype(np.uint8)).resize(
        (decoder_rgb.shape[1], decoder_rgb.shape[0]), Image.Resampling.BILINEAR
    )
    a = np.array(target).astype(np.float64)
    b = decoder_rgb[:, :, :3].astype(np.float64)
    mae = float(np.mean(np.abs(a - b)))
    # Colour bars should be recognizably closer than a street poster (~80–120 MAE).
    return {"ok": mae < 55.0, "mae": mae}


def _decode_health(snap: dict, decoder_frames: list[dict]) -> dict:
    vids = snap.get("videos") or []
    pool = snap.get("preservePool") or []
    widths = [
        int(v.get("w") or v.get("videoWidth") or 0)
        for v in vids + [{"videoWidth": p.get("videoWidth")} for p in pool]
    ]
    ok_frames = [d for d in decoder_frames if d.get("path")]
    motion = {"ok": False, "n": len(ok_frames)}
    if len(ok_frames) >= 3:
        arrs = [np.array(Image.open(d["path"])) for d in ok_frames]
        motion = score_visible_movie_motion(arrs, min_changing_frac=0.45)
    return {
        "anyVideoWidth": any(w > 0 for w in widths),
        "maxVideoWidth": max(widths) if widths else 0,
        "domVideoCount": len(vids),
        "poolN": len(pool),
        "sampleFrameOkN": len(ok_frames),
        "decoderMotion": motion,
        "ok": bool(
            any(w > 0 for w in widths)
            and len(ok_frames) >= 2
            and motion.get("ok")
        ),
    }


async def _run() -> dict:
    if not (ADV_UNMOD / "index.html").is_file():
        raise SystemExit(
            f"Missing reused export at {ADV_UNMOD}. Run adversarial gate once first "
            "(or pass a prior html-unmodified tree)."
        )
    OUT.mkdir(parents=True, exist_ok=True)
    before = file_identity(SOURCE) if SOURCE.is_file() else None
    if before:
        write_json(OUT / "fingerprints-before.json", before.as_dict())

    disposable = OUT / "html-disposable"
    player = OUT / "html-player"
    if disposable.exists():
        shutil.rmtree(disposable)
    shutil.copytree(ADV_UNMOD, disposable)
    replace_info = _replace_hevc_movies(disposable)
    write_json(OUT / "asset-replace.json", replace_info)
    strip_info = strip_export_pdf_bg_fills(disposable)
    write_json(OUT / "pdf-strip.json", strip_info)
    if player.exists():
        shutil.rmtree(player)
    write_patched_export(disposable, player)
    preserve = inject_preserve(player)
    write_json(OUT / "preserve-inject.json", preserve)

    run_dir = OUT / "runs" / "primary"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(player), **k)

        def log_message(self, fmt, *args):  # noqa: A003
            return

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/index.html"

    chrome = ChromeCdp(CHROME, run_dir / "chrome-profile", width=1920, height=1080)
    try:
        await chrome.start()
        await chrome.goto("about:blank")
        await asyncio.sleep(0.05)
        await chrome.goto(f"{base}?currentSlide=1")
        ready = await _wait_ready(chrome)
        live_hash = await _wait_hash_clean(chrome)
        await _ensure_videos_playing(chrome)
        # Give H.264 a moment to present frames.
        for _ in range(40):
            snap0 = await _media_snapshot_with_pool(chrome)
            vids = snap0.get("videos") or []
            if any((v.get("w") or v.get("videoWidth") or 0) > 0 for v in vids):
                break
            if any((v.get("currentTime") or 0) > 0.05 for v in vids):
                break
            await _ensure_videos_playing(chrome)
            await asyncio.sleep(0.1)

        snap_pre = await _media_snapshot_with_pool(chrome)
        pre_shot = await chrome.screenshot()
        Image.fromarray(pre_shot).save(run_dir / "pre.png")
        pre_roi = _crop_movie_roi(pre_shot)
        Image.fromarray(pre_roi[:, :, :3] if pre_roi.ndim == 3 else pre_roi).save(run_dir / "pre-movie-roi.png")
        pre_bars = _looks_like_colour_bars(pre_roi)
        (run_dir / "decoder-pre").mkdir(exist_ok=True)
        decoder_pre = await _sample_decoder_frames(chrome, run_dir / "decoder-pre", n=6, gap_s=0.3)
        health_pre = _decode_health(snap_pre, decoder_pre)
        # Match first decoder frame to pre composed ROI (baseline).
        pre_match = {"ok": False, "mae": None}
        if decoder_pre and decoder_pre[0].get("path"):
            d0 = np.array(Image.open(decoder_pre[0]["path"]))
            pre_match = _composed_vs_decoder_mae(pre_roi, d0)

        # Dense capture through Magic Move 1→2 — composed frames, not just decoder clocks.
        await asyncio.sleep(1.5)
        click_wall_a = time.monotonic()
        method_a = await _advance_hash(chrome, prefer="arrow", wait_s=3.0)
        # Keep remounting through the dense window — scene changes can cover/detach again.
        await chrome.evaluate(
            "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.remountAll && "
            "window.__OBED_P2_PRESERVE__.remountAll()"
        )
        await asyncio.sleep(0.35)
        dense_a, _frames_a, decoder_during = await _dense_after_click(
            chrome, run_dir, "mm12", click_wall_a, sample_decoder=True
        )
        hash2 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        mid_shot = await chrome.screenshot()
        Image.fromarray(mid_shot).save(run_dir / "after-1to2.png")
        mid_roi = _crop_movie_roi(mid_shot)
        Image.fromarray(mid_roi[:, :, :3]).save(run_dir / "after-1to2-movie-roi.png")
        mid_bars = _looks_like_colour_bars(mid_roi)
        mm_paths = sorted(run_dir.glob("mm12-t*.png"))
        visible_mm = _score_visible_movie_motion(mm_paths, MOVIE_ROI)
        # Decoder samples during/after MM vs composed mid ROI.
        mid_match = {"ok": False, "mae": None}
        ok_dec = [d for d in decoder_during if d.get("path")]
        if not ok_dec:
            ok_dec = [d for d in decoder_pre if d.get("path")]
        if ok_dec:
            d_mid = np.array(Image.open(ok_dec[-1]["path"]))
            mid_match = _composed_vs_decoder_mae(mid_roi, d_mid)
        visible_colour_through_mm = bool(
            hash2 != _norm_hash(live_hash)
            and mid_bars.get("ok")
            and visible_mm.get("ok")
            and mid_match.get("ok")
        )

        # After Magic Move, settle then drain slide-2 builds to #6.
        await asyncio.sleep(2.0)
        click_wall = time.monotonic()
        samples = [
            _annotate_sample(
                await _media_snapshot_with_pool(chrome),
                phase="after-1to2",
                capture_offset_s=0.0,
                scene_hash=hash2,
            )
        ]
        await chrome.evaluate(
            "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.clear && "
            "window.__OBED_P2_PRESERVE__.clear()"
        )
        await asyncio.sleep(0.3)
        methods, drain = await _advance_until_hash_at_least_sampling(
            chrome,
            min_hash=SLIDE3_MIN_HASH,
            max_steps=16,
            click_wall=click_wall,
            sample_hz=12.0,
        )
        methods = [method_a, *methods]
        samples.extend(drain)
        # Extra nav diagnostics when stalled.
        nav_diag = {
            "methods": methods,
            "drainPhases": [s.get("phase") for s in drain[:20]],
            "drainHashes": sorted({s.get("sceneHash") for s in drain}),
            "drainVideoCounts": [
                {
                    "phase": s.get("phase"),
                    "hash": s.get("sceneHash"),
                    "dom": len(s.get("videos") or []),
                    "pool": len(s.get("preservePool") or []),
                    "movies": [
                        {
                            "key": m.get("key"),
                            "t": m.get("currentTime"),
                            "w": m.get("videoWidth"),
                        }
                        for m in (s.get("movies") or [])[:4]
                    ],
                }
                for s in drain[:: max(1, len(drain) // 8 or 1)][:12]
            ],
        }
        hash_final = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        snap_post = await _media_snapshot_with_pool(chrome)
        samples.append(
            _annotate_sample(
                snap_post,
                phase="post",
                capture_offset_s=time.monotonic() - click_wall,
                scene_hash=hash_final,
            )
        )
        Image.fromarray(await chrome.screenshot()).save(run_dir / "post.png")
        post_dec_dir = run_dir / "post-decoder"
        post_dec_dir.mkdir(exist_ok=True)
        decoder_post = await _sample_decoder_frames(chrome, post_dec_dir, n=4, gap_s=0.25)
        health_post = _decode_health(snap_post, decoder_post)

        preserve_events = await chrome.evaluate(
            "window.__OBED_P2_PRESERVE__ ? window.__OBED_P2_PRESERVE__.events.slice(-120) : []"
        ) or []

        by_key: dict[str, list] = {}
        for s in samples:
            for m in s.get("movies") or []:
                k = m.get("key") or "?"
                by_key.setdefault(k, []).append(
                    {
                        "sceneHash": s.get("sceneHash"),
                        "phase": s.get("phase"),
                        "captureOffsetS": s.get("captureOffsetS"),
                        "currentTime": m.get("currentTime"),
                        "videoWidth": m.get("videoWidth"),
                        "fromPreservePool": m.get("fromPreservePool"),
                        "decoderId": m.get("decoderId"),
                    }
                )

        intended = list(EXPECTED_MOVIE_KEYS)
        per_movie_boundary: dict[str, dict] = {}
        for key in intended:
            per_movie_boundary[key] = score_restart_movie_from_observations(
                by_key.get(key, []),
                slide_min_hash=SLIDE3_MIN_HASH,
                progression_wall_s=PROGRESSION_WALL_S,
                progression_media_s=PROGRESSION_MEDIA_S,
            )
        boundary = score_restart_at_slide_boundary(
            reached_slide=(_hash_num(hash_final) or -1) >= SLIDE3_MIN_HASH,
            per_movie=per_movie_boundary,
            expected_keys=intended,
            canvas_all_identical=False,
        )
    finally:
        await chrome.close()
        httpd.shutdown()

    after = file_identity(SOURCE) if SOURCE.is_file() else None
    if after:
        write_json(OUT / "fingerprints-after.json", after.as_dict())

    findings = [
        {
            "id": "sourceUnchanged",
            "pass": after is None or (before is not None and after.as_dict() == before.as_dict()),
        },
        {
            "id": "replacedHevcWithH264",
            "pass": replace_info.get("replacedN", 0) >= 1,
            "detail": replace_info,
        },
        {
            "id": "browserDecodesVideoPixels",
            "pass": health_pre.get("ok", False),
            "detail": health_pre,
            "note": "videoWidth>0 + sampleFrame pixels that change (may be pre-transition only)",
        },
        {
            "id": "visibleColourPatternThroughMagicMove",
            "pass": visible_colour_through_mm,
            "detail": {
                "hash": f"{_norm_hash(live_hash)}->{hash2}",
                "method": method_a,
                "preBars": pre_bars,
                "midBars": mid_bars,
                "visibleMotion": visible_mm,
                "preMatchDecoder": pre_match,
                "midMatchDecoder": mid_match,
                "note": (
                    "Composed movie ROI must show colour-bar pattern, sustain motion "
                    "through MM, and match decoder sampleFrame — navigation alone is insufficient"
                ),
            },
        },
        {
            "id": "reachedSlide3",
            "pass": (_hash_num(hash_final) or -1) >= SLIDE3_MIN_HASH,
            "detail": {"hash": hash_final, "navDiag": nav_diag},
        },
        {
            "id": "restartBoundaryPerMovie",
            "pass": bool(boundary.get("ok")),
            "verdict": boundary.get("verdict"),
            "detail": {
                "boundary": boundary,
                "perMovie": per_movie_boundary,
            },
            "note": "each intended movie: near-zero + progression on #6+ samples",
        },
    ]
    success = all(f["pass"] for f in findings)
    report = {
        "probe": "p2_recovery_html_decode_probe",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sourceUnchanged": findings[0]["pass"],
        "assetReplace": replace_info,
        "stripPdf": strip_info,
        "preserve": preserve,
        "boot": {"ready": ready, "liveHash": live_hash},
        "decodePre": health_pre,
        "decodePost": health_post,
        "visibleThroughMM": {
            "ok": visible_colour_through_mm,
            "preBars": pre_bars,
            "midBars": mid_bars,
            "visibleMotion": visible_mm,
            "preMatchDecoder": pre_match,
            "midMatchDecoder": mid_match,
        },
        "hashes": {"h1": _norm_hash(live_hash), "h2": hash2, "final": hash_final},
        "methods": methods,
        "navDiag": nav_diag,
        "perMovie": by_key,
        "perMovieBoundary": per_movie_boundary,
        "restartBoundary": boundary,
        "preserveEvents": preserve_events,
        "findings": findings,
        "success": success,
        "p3": "still unwired",
        "note": (
            "Disposable H.264 under Untitled.mov filenames; preserve unchanged. "
            "Decode ≠ visible: require composed colour-bar motion through MM."
        ),
    }
    write_json(OUT / "report.json", report)
    lines = [
        "# HTML decode probe — disposable H.264 under preserve",
        "",
        f"Generated: {report['generated']}",
        f"success: **{success}**",
        "",
        "## Findings",
        "",
    ]
    for f in findings:
        extra = f" — {f['note']}" if f.get("note") else ""
        verd = f" ({f['verdict']})" if f.get("verdict") else ""
        lines.append(f"- {f['id']}: **{f['pass']}**{verd}{extra}")
    lines += ["", f"Samples: `{OUT}`", "", "P3 still unwired."]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return report


def main() -> int:
    report = asyncio.run(_run())
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
