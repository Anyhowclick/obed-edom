#!/usr/bin/env python3
"""Inventory active surfaces through dissolve on the --preserve fixture.

Identifies canvases/videos/DOM styles and the first sample where known-empty
corners become opaque. Does not launch Keynote. Reuses the Minimal Alpha_DSK
HTML export under html-dissolve-preserve (or html-dissolve-live baseline).

P3 stays off. Decoder-preserve stays on as the playback control.
"""
from __future__ import annotations

import asyncio
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
    CLICK_DELAYS_S,
    DISSOLVE_S,
    SOURCE,
    _boot_slide1,
    _trigger_advance,
    inject_preserve,
)
from obed_edom.p2_verdict import _norm_hash  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    analyze_rgba,
    file_identity,
    write_json,
    write_patched_export,
)

OUT = REPO / "output" / "p2-recovery" / "html-alpha-surfaces"
BASELINE = REPO / "output" / "p2-recovery" / "html-dissolve-preserve" / "html-unmodified"
FALLBACK = REPO / "output" / "p2-recovery" / "html-dissolve-live" / "html-unmodified"
# Corners that should be empty on Minimal Alpha_DSK (transparent DSK plate).
EMPTY_PTS = [(8, 8), (8, 1912), (1072, 8), (1072, 1912), (540, 50), (50, 960)]


SURFACE_JS = r"""
() => {
  function sampleCanvas(c) {
    const item = {
      id: c.id || '',
      className: c.className || '',
      w: c.width,
      h: c.height,
      full: c.width >= 1900 && c.height >= 1000,
      rect: (() => { const r = c.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; })(),
      styleBg: getComputedStyle(c).backgroundColor,
      styleOpacity: getComputedStyle(c).opacity,
    };
    // Prefer 2d readback; record if context is webgl-only.
    let ctx2d = null;
    try { ctx2d = c.getContext('2d', {willReadFrequently:true}); } catch (e) {}
    if (!ctx2d) {
      try {
        const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
        item.context = gl ? 'webgl' : 'none';
        if (gl) {
          const w = Math.min(c.width, 4), h = Math.min(c.height, 4);
          const buf = new Uint8Array(w * h * 4);
          gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
          item.glCorner = Array.from(buf.slice(0, 4));
          item.glAlphaMin = Math.min(buf[3], buf[7] || 255, buf[11] || 255, buf[15] || 255);
        }
      } catch (e) {
        item.context = 'blocked';
        item.error = String(e && e.message || e);
      }
      return item;
    }
    item.context = '2d';
    const pts = [[0,0],[c.width-1,0],[0,c.height-1],[c.width-1,c.height-1],
                 [Math.floor(c.width/2), 4], [4, Math.floor(c.height/2)]];
    const samples = [];
    let amin = 255;
    for (const [x,y] of pts) {
      try {
        const d = ctx2d.getImageData(x, y, 1, 1).data;
        const px = [d[0], d[1], d[2], d[3]];
        samples.push({x:x, y:y, rgba: px});
        if (d[3] < amin) amin = d[3];
      } catch (e) {
        samples.push({x:x, y:y, error: String(e && e.message || e)});
      }
    }
    item.cornerSamples = samples;
    item.sampleAlphaMin = amin;
    item.emptyCornersTransparent = samples.every(s => s.rgba && s.rgba[3] <= 2);
    return item;
  }
  const stage = document.getElementById('stageArea');
  const body = document.getElementById('body') || document.body;
  const videos = Array.prototype.slice.call(document.querySelectorAll('video')).map((v,i) => ({
    index: i,
    elId: v.__obedElId || null,
    src: String(v.currentSrc || v.src || '').slice(-80),
    w: v.videoWidth, h: v.videoHeight,
    currentTime: v.currentTime,
    paused: v.paused,
    rect: (() => { const r = v.getBoundingClientRect(); return {x:r.left,y:r.top,w:r.width,h:r.height}; })(),
  }));
  return {
    hash: String(location.hash || ''),
    wallMs: performance.now(),
    dom: {
      htmlBg: getComputedStyle(document.documentElement).backgroundColor,
      bodyBg: body ? getComputedStyle(body).backgroundColor : null,
      stageBg: stage ? getComputedStyle(stage).backgroundColor : null,
      stageVis: stage ? getComputedStyle(stage).visibility : null,
      canvasCount: document.querySelectorAll('canvas').length,
      videoCount: videos.length,
    },
    canvases: Array.prototype.slice.call(document.querySelectorAll('canvas')).map(sampleCanvas),
    videos: videos,
  };
}
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve(root: Path) -> tuple[ThreadingHTTPServer, int]:
    port = _free_port()
    directory = str(root.resolve())

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=directory, **k)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def _empty_report(arr: np.ndarray) -> dict:
    a = analyze_rgba(arr)
    corners = []
    h, w = arr.shape[:2]
    for y, x in EMPTY_PTS:
        yy, xx = min(y, h - 1), min(x, w - 1)
        px = arr[yy, xx]
        corners.append({"y": yy, "x": xx, "rgba": [int(v) for v in px], "transparent": int(px[3]) <= 2})
    return {
        "alphaMin": a["alphaMin"],
        "transparentFrac": a["transparentFrac"],
        "pass": a["pass"],
        "emptyCornersTransparent": all(c["transparent"] for c in corners),
        "corners": corners,
        "blackOpaqueCornerFrac": float(
            ((arr[:, :, 3] >= 250) & (arr[:, :, :3].max(axis=2) <= 8)).mean()
        ),
    }


async def _surface(chrome: ChromeCdp) -> dict:
    raw = await chrome.evaluate(f"({SURFACE_JS})()")
    return raw or {}


async def _run() -> dict:
    src_export = BASELINE if (BASELINE / "index.html").is_file() else FALLBACK
    if not (src_export / "index.html").is_file():
        raise SystemExit(f"missing HTML export at {src_export}")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    player = OUT / "html-player"
    patch = write_patched_export(src_export, player)
    preserve = inject_preserve(player)
    write_json(OUT / "patch.json", {"export": str(src_export), **patch, "preserve": preserve})

    httpd, port = _serve(player)
    base = f"http://127.0.0.1:{port}/index.html"
    chrome = ChromeCdp(CHROME, OUT / f"chrome-{int(time.time())}", width=1920, height=1080)
    await chrome.start()
    samples = []
    try:
        ready, live_hash, video_ready, _ = await _boot_slide1(chrome, base)
        await asyncio.sleep(1.0)  # settle movie
        # Pre-dissolve inventory
        surf = await _surface(chrome)
        shot = await chrome.screenshot()
        Image.fromarray(shot).save(OUT / "pre.png")
        samples.append(
            {
                "phase": "pre",
                "captureOffsetS": 0.0,
                "hash": _norm_hash(surf.get("hash")),
                "surface": surf,
                "page": _empty_report(shot),
            }
        )
        write_json(OUT / "pre-surface.json", surf)

        hash_before = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        method = await _trigger_advance(chrome)
        t0 = time.monotonic()
        # Dense through dissolve
        n = int(DISSOLVE_S * 10) + 3
        for i in range(n):
            target = t0 + (i + 1) * 0.1
            while time.monotonic() < target:
                await asyncio.sleep(0.001)
            surf = await _surface(chrome)
            shot = await chrome.screenshot()
            name = f"t{i:02d}.png"
            Image.fromarray(shot).save(OUT / name)
            samples.append(
                {
                    "phase": "dissolve",
                    "i": i,
                    "captureOffsetS": time.monotonic() - t0,
                    "hash": _norm_hash(surf.get("hash")),
                    "surface": surf,
                    "page": _empty_report(shot),
                }
            )
        await asyncio.sleep(0.4)
        surf = await _surface(chrome)
        shot = await chrome.screenshot()
        Image.fromarray(shot).save(OUT / "post.png")
        samples.append(
            {
                "phase": "post",
                "captureOffsetS": time.monotonic() - t0,
                "hash": _norm_hash(surf.get("hash")),
                "surface": surf,
                "page": _empty_report(shot),
            }
        )
    finally:
        await chrome.close()
        httpd.shutdown()

    # Find first opaque-empty on page and on each full canvas
    first_page = next((s for s in samples if not s["page"]["emptyCornersTransparent"]), None)
    first_canvas = None
    for s in samples:
        for c in s["surface"].get("canvases") or []:
            if c.get("full") and c.get("sampleAlphaMin", 0) >= 250:
                first_canvas = {"sample": s["phase"], "i": s.get("i"), "offset": s["captureOffsetS"], "canvas": c}
                break
        if first_canvas:
            break

    # Was page already opaque before dissolve?
    pre_opaque = not samples[0]["page"]["emptyCornersTransparent"]

    report = {
        "probe": "p2_recovery_html_alpha_surfaces",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": file_identity(SOURCE).as_dict(),
        "export": str(src_export),
        "preserve": True,
        "ready": ready,
        "videoReady": video_ready,
        "liveHash": live_hash,
        "hashBefore": hash_before,
        "advanceMethod": method,
        "httpBase": base,
        "prePageOpaqueEmpty": pre_opaque,
        "firstPageOpaqueEmpty": {
            "phase": first_page["phase"] if first_page else None,
            "i": first_page.get("i") if first_page else None,
            "offsetS": first_page["captureOffsetS"] if first_page else None,
            "page": first_page["page"] if first_page else None,
        },
        "firstFullCanvasOpaque": first_canvas,
        "sampleCount": len(samples),
        "samples": samples,
        "p3": "still unwired",
    }
    write_json(OUT / "report.json", report)

    lines = [
        "# HTML alpha surfaces — preserve fixture",
        "",
        f"Generated: {report['generated']}",
        f"Preserve control: **True**  advance={method} hash {hash_before}→{samples[-1]['hash']}",
        "",
        f"Pre-dissolve page empty-corners opaque: **{pre_opaque}**",
        f"First page opaque-empty: phase={report['firstPageOpaqueEmpty']['phase']} "
        f"i={report['firstPageOpaqueEmpty']['i']} t={report['firstPageOpaqueEmpty']['offsetS']}",
        f"First full-canvas opaque sampleAlphaMin≥250: {first_canvas is not None}",
        "",
        "## Pre canvases",
        "",
    ]
    for c in samples[0]["surface"].get("canvases") or []:
        lines.append(
            f"- id=`{c.get('id')}` {c.get('w')}x{c.get('h')} full={c.get('full')} "
            f"ctx={c.get('context')} alphaMin={c.get('sampleAlphaMin')} "
            f"emptyTransparent={c.get('emptyCornersTransparent')}"
        )
    lines += ["", f"DOM: `{json.dumps(samples[0]['surface'].get('dom'))}`", "", f"Samples: `{OUT}`"]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return report


def main() -> int:
    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
