#!/usr/bin/env python3
"""HTML/runtime milestone: operator-triggered dissolve while video continues.

Fixture: Minimal Alpha_DSK.key (2 slides, dissolve on-click into slide 2;
movie 1 autoplays on show; movie 2 after dissolve; across-slides continue).

For each click-delay D in {0.5, 1.5, 3.0, 5.0}s after slide-1 ready:
  1) sample media.currentTime (playback clock) separately from wall/capture clock
  2) click to start dissolve
  3) dense-sample during dissolve (~1.5s) + short settle
  4) score: empty-canvas alpha, video advance through dissolve, no restart/jump,
     second movie starts after dissolve, capture-clock ≠ playback-clock

P3 stays off. Never writes owner source decks. Magic Move extension is later.
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
from obed_edom.dsk_live import keynote_running  # noqa: E402
from obed_edom.live_continuity_js import PRESERVE_CORE_JS  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    analyze_rgba,
    file_identity,
    inventory_deck,
    progress_metric,
    score_playback_continuity,
    strip_export_pdf_bg_fills,
    write_json,
    write_patched_export,
)
from obed_edom.html_preview import export_html  # noqa: E402
from obed_edom.p2_verdict import MOVIE1_TOKEN, MOVIE2_TOKEN, _movie_key, _norm_hash  # noqa: E402

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
OUT = REPO / "output" / "p2-recovery" / "html-dissolve-live"
CLICK_DELAYS_S = (0.5, 1.5, 3.0, 5.0)
DISSOLVE_S = 1.5
DENSE_FPS = 20
POST_SETTLE_S = 0.6
# Jump/restart thresholds on media.currentTime (seconds)
RESTART_EPS = 0.35  # drop toward 0
JUMP_EPS = 0.85  # forward discontinuity larger than capture dt allows


def _time_for(samples: list[dict], key: str) -> list[float | None]:
    out: list[float | None] = []
    for s in samples:
        hit = None
        for v in s.get("videos") or []:
            if _movie_key(v.get("src") or "") == key:
                hit = v.get("currentTime")
                break
        out.append(hit)
    return out


def _continuity(
    times: list[float | None],
    click_i: int,
    *,
    capture_offsets: list[float | None] | None = None,
    presented_times: list[float | None] | None = None,
) -> dict:
    return score_playback_continuity(
        times,
        click_i=click_i,
        capture_offsets=capture_offsets,
        presented_times=presented_times,
        dissolve_s=DISSOLVE_S,
        restart_eps=RESTART_EPS,
        jump_eps=JUMP_EPS,
    )


def _series_field(samples: list[dict], key: str, field: str) -> list[float | None]:
    out: list[float | None] = []
    for s in samples:
        hit = None
        for v in s.get("videos") or []:
            if _movie_key(v.get("src") or "") == key:
                hit = v.get(field)
                break
        out.append(hit)
    return out


def _classify_media_series(samples: list[dict], click_i: int) -> dict:
    """Per-movie continuity: track Untitled (movie1) and WA0125 (movie2) separately."""
    caps = [s.get("captureOffsetS") for s in samples]
    m1 = _continuity(
        _time_for(samples, "movie1"),
        click_i,
        capture_offsets=caps,
        presented_times=_series_field(samples, "movie1", "presentedMediaTime"),
    )
    m2 = _continuity(
        _time_for(samples, "movie2"),
        click_i,
        capture_offsets=caps,
        presented_times=_series_field(samples, "movie2", "presentedMediaTime"),
    )
    # Second movie must actually start playing (advancing), not merely appear.
    second_seen_after = False
    second_playing = False
    m2_times_after: list[float] = []
    for s in samples[click_i:]:
        for v in s.get("videos") or []:
            if _movie_key(v.get("src") or "") != "movie2":
                continue
            second_seen_after = True
            t = v.get("presentedMediaTime")
            if t is None:
                t = v.get("currentTime")
            if t is not None and not v.get("paused"):
                m2_times_after.append(float(t))
    if len(m2_times_after) >= 2 and (m2_times_after[-1] - m2_times_after[0]) >= 0.2:
        second_playing = True
    max_gap = 0
    gap = 0
    for t in m1["times"][click_i:]:
        if t is None:
            gap += 1
            max_gap = max(max_gap, gap)
        else:
            gap = 0
    return {
        "movie1": m1,
        "movie2": m2,
        "secondMovieSeenAfterClick": second_seen_after,
        "secondMoviePlayingAfterClick": second_playing,
        "movie1DomMaxGapAfterClick": max_gap,
        "movie1DomTeardown": max_gap >= 3,
        "videoContinuesThroughDissolve": m1["continuesThroughDissolve"],
        "noRestart": m1["noRestart"],
        "noJump": m1["noJump"],
        "dissolvePrimaryAdvanceS": m1["dissolveAdvanceS"],
        "restartsAfterClick": m1["restartsAfterClick"] + (1 if m1["hardRestartVsPre"] else 0),
        "jumpsAfterClick": m1["jumpsAfterClick"],
    }


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        pass


def _serve(root: Path) -> tuple[ThreadingHTTPServer, int]:
    port = _free_port()
    directory = str(root.resolve())

    def factory(*args, **kwargs):
        return _Handler(*args, directory=directory, **kwargs)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), factory)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


MEDIA_PROBE_JS = r"""
(() => {
  let nextId = window.__OBED_VIDEO_ID__ || 1;
  function watch(v) {
    if (v.__obedWatched) return;
    v.__obedWatched = true;
    v.__obedId = nextId++;
    window.__OBED_VIDEO_ID__ = nextId;
    if (typeof v.requestVideoFrameCallback === 'function') {
      const tick = (_now, meta) => {
        try {
          v.__obedPresented = meta && typeof meta.mediaTime === 'number' ? meta.mediaTime : null;
          v.__obedPresentedWall = performance.now();
          v.requestVideoFrameCallback(tick);
        } catch (e) {}
      };
      try { v.requestVideoFrameCallback(tick); } catch (e) {}
    }
  }
  Array.prototype.slice.call(document.querySelectorAll('video')).forEach(watch);
  // PRESERVE's own map: authored px -> viewport px by one uniform scale about
  // the stage's top-left; null when the stage is missing or the axes disagree.
  function stageMap() {
    const stage = document.getElementById('stage');
    if (!stage) return null;
    const ow = stage.offsetWidth, oh = stage.offsetHeight;
    if (!(ow > 1 && oh > 1)) return null;
    const r = stage.getBoundingClientRect();
    if (!(r.width > 1 && r.height > 1)) return null;
    const sx = r.width / ow, sy = r.height / oh;
    const avg = (sx + sy) / 2;
    if (!(avg > 0) || Math.abs(sx - sy) / avg > 0.001) return null;
    return {s: sx, ox: r.left, oy: r.top, authoredWidth: ow, authoredHeight: oh};
  }
  const SMAP = stageMap();
  function toAuthored(r) {
    if (!SMAP) return null;
    return {x: (r.left - SMAP.ox) / SMAP.s, y: (r.top - SMAP.oy) / SMAP.s,
            w: r.width / SMAP.s, h: r.height / SMAP.s};
  }
  function opacityProduct(el) {
    let p = 1, n = el;
    while (n && n.nodeType === 1) {
      const o = parseFloat(getComputedStyle(n).opacity);
      if (!isNaN(o)) p *= o;
      n = n.parentElement;
    }
    return p;
  }
  // Does this <video> PAINT? A decoder that does not paint cannot own a
  // footprint however well its box overlaps one. `checkVisibility` is the
  // engine's own answer (content-visibility, display and the CSS visibility /
  // opacity chains); the explicit clauses restate the ones this probe must not
  // depend on a flag for, and `hiddenBy` names the FIRST reason found so a
  // suppressed sibling is classified rather than silently dropped.
  function visibility(v) {
    const attached = document.contains(v);
    const r = v.getBoundingClientRect();
    const st = attached ? getComputedStyle(v) : null;
    const op = attached ? opacityProduct(v) : 0;
    let engine = null;
    try {
      engine = typeof v.checkVisibility === 'function'
        ? v.checkVisibility({checkOpacity: true, checkVisibilityCSS: true,
                             opacityProperty: true, visibilityProperty: true,
                             contentVisibilityAuto: true})
        : null;
    } catch (e) { engine = null; }
    const offscreen = !(r.right > 0 && r.bottom > 0
                        && r.left < (window.innerWidth || 0)
                        && r.top < (window.innerHeight || 0));
    let why = null;
    if (!attached) why = 'detached';
    else if (st && st.display === 'none') why = 'display-none';
    else if (!(r.width > 0 && r.height > 0)) why = 'zero-size';
    else if (st && st.visibility === 'hidden') why = 'hidden';
    else if (!(op > 0)) why = 'hidden';
    else if (engine === false) why = 'engine-hidden';
    else if (offscreen) why = 'offscreen';
    return {
      visible: why === null,
      hiddenBy: why,
      suppressed34: !!v.__obedSuppressed34,
      // The RAW readings the two fields above are a function of, so the same
      // decision can be recomputed off-page and required to agree.
      inDocument: attached,
      display: st ? String(st.display) : null,
      visibility: st ? String(st.visibility) : null,
      opacityProduct: op,
      checkVisibility: engine,
      clientRect: {x: r.left, y: r.top, w: r.width, h: r.height},
      viewport: {w: window.innerWidth || 0, h: window.innerHeight || 0},
      rect: toAuthored(r),
    };
  }
  const videos = Array.prototype.slice.call(document.querySelectorAll('video')).map((v, i) => ({
    index: i,
    decoderId: v.__obedElId || v.__obedId || null,
    ...visibility(v),
    src: String(v.currentSrc || v.src || '').slice(-120),
    currentTime: v.currentTime,
    presentedMediaTime: (typeof v.__obedPresented === 'number') ? v.__obedPresented : null,
    duration: Number.isFinite(v.duration) ? v.duration : null,
    paused: v.paused,
    ended: v.ended,
    muted: v.muted,
    playbackRate: v.playbackRate,
    loop: !!v.loop,
    readyState: v.readyState,
    networkState: v.networkState,
    w: v.videoWidth,
    h: v.videoHeight,
  }));
  return {
    wallMs: performance.now(),
    hash: String(location.hash || ''),
    search: String(location.search || ''),
    videoCount: videos.length,
    videos: videos,
    stageMap: SMAP,
    canvasCount: document.querySelectorAll('canvas').length,
  };
})()
"""

# Seek-handoff was inconclusive (elapsed always capped; got:0 without seeked traces).
# --handoff now only records lifecycle. --preserve keeps one decoder across destroy/initVideo.

LIFECYCLE_SCRIPT = r"""
(function(){
  if (window.__OBED_P2_HANDOFF__) return;
  window.__OBED_P2_HANDOFF__ = {version: 2, mode: 'lifecycle-only', events: []};
  let nextId = 1;
  function assetKey(src) {
    const s = String(src || '');
    const tail = (s.split('/').pop() || s).split('?')[0];
    const m = tail.match(/^(.+\.(mov|mp4|m4v))-\d+\.\d+-\d+\.\d+\.\2$/i);
    if (m) return m[1].toLowerCase();
    return tail.toLowerCase();
  }
  function note(kind, detail) {
    window.__OBED_P2_HANDOFF__.events.push({kind: kind, detail: detail, t: performance.now()});
  }
  function tag(v) {
    if (!v || v.__obedElId) return v && v.__obedElId;
    v.__obedElId = nextId++;
    ['seeking','seeked','emptied','loadedmetadata','loadeddata','play','pause','error'].forEach(function(ev){
      v.addEventListener(ev, function(){
        note(ev, {
          elId: v.__obedElId,
          key: assetKey(v.currentSrc || v.src || ''),
          currentTime: v.currentTime,
          readyState: v.readyState,
          networkState: v.networkState,
          paused: v.paused,
          seekable: (function(){
            try {
              if (!v.seekable || !v.seekable.length) return null;
              return {start: v.seekable.start(0), end: v.seekable.end(v.seekable.length-1)};
            } catch (e) { return String(e && e.message || e); }
          })(),
          error: v.error ? (v.error.code + ':' + v.error.message) : null
        });
      });
    });
    return v.__obedElId;
  }
  const desc = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
  if (desc && desc.set) {
    Object.defineProperty(HTMLMediaElement.prototype, 'src', {
      configurable: true, enumerable: desc.enumerable, get: desc.get,
      set: function(val) {
        tag(this);
        note('src-set', {
          elId: this.__obedElId,
          from: assetKey(this.currentSrc || ''),
          to: val === '' || val == null ? '' : assetKey(val),
          currentTime: this.currentTime,
          readyState: this.readyState,
          paused: this.paused
        });
        try { return desc.set.call(this, val); }
        catch (e) {
          note('src-set-exception', {elId: this.__obedElId, message: String(e && e.message || e)});
          throw e;
        }
      }
    });
  }
  const origCreate = Document.prototype.createElement;
  Document.prototype.createElement = function(name, opts) {
    const el = origCreate.call(this, name, opts);
    if (String(name).toLowerCase() === 'video') {
      tag(el);
      note('createElement-video', {elId: el.__obedElId});
    }
    return el;
  };
  new MutationObserver(function(){
    document.querySelectorAll('video').forEach(tag);
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
""".strip()


PRESERVE_SCRIPT = PRESERVE_CORE_JS


def _inject_script(player: Path, *, marker_attr: str, script: str, already: str) -> dict:
    import hashlib

    index = Path(player) / "index.html"
    html = index.read_text(encoding="utf-8")
    if already in html:
        return {"injected": False, "reason": "already present"}
    marker = 'data-obed-p2-probe="'
    idx = html.find(marker)
    if idx < 0:
        raise RuntimeError("patched export missing probe marker; refuse inject")
    close = html.find("</script>", idx)
    if close < 0:
        raise RuntimeError("probe script not closed")
    insert_at = close + len("</script>")
    tag = f'\n<script {marker_attr}>{script}</script>'
    index.write_text(html[:insert_at] + tag + html[insert_at:], encoding="utf-8")
    return {"injected": True, "indexSha256": hashlib.sha256(index.read_bytes()).hexdigest()}


def inject_handoff(player: Path) -> dict:
    """Lifecycle-only instrumentation (no seek retries). Does not edit main.js."""
    return _inject_script(
        player,
        marker_attr='data-obed-p2-handoff="2"',
        script=LIFECYCLE_SCRIPT,
        already="data-obed-p2-handoff=",
    )


def inject_preserve(player: Path) -> dict:
    """Keep across-slide decoder alive across destroy()/initVideo(). Does not edit main.js."""
    return _inject_script(
        player,
        marker_attr='data-obed-p2-preserve="1"',
        script=PRESERVE_SCRIPT,
        already="data-obed-p2-preserve=",
    )


def inject_continuity_plan(player: Path, plan: dict) -> dict:
    """Inject the generic plan `PRESERVE_CORE_JS` reads as `window.__OBED_CONTINUITY__`.

    Must land in the HTML before the preserve script tag (call after
    `inject_preserve`; `_inject_script` always inserts immediately after the
    probe marker, so the later call ends up first). Fixture values are the
    caller's, not this module's.
    """
    script = f"window.__OBED_CONTINUITY__ = {json.dumps(plan)};"
    return _inject_script(
        player,
        marker_attr='data-obed-p2-continuity-plan="1"',
        script=script,
        already="data-obed-p2-continuity-plan=",
    )


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"imageio-ffmpeg required for disposable H.264 encode: {e}") from e


def _write_h264_pattern(dest: Path, *, seconds: float = 46.0333, fps: int = 30) -> dict:
    """Write a browser-decodable H.264 MP4 (yuv420p): a fast scrolling GRAYSCALE grating
    with a top-left frame-index patch.

    Two requirements pull in opposite directions: Finding 1 needs large per-frame
    ROI motion (a plain moving bar gives only ~1.5 ROI MAE, below pair_eps=2.0),
    while the Finding-2 green-in-front check must not be fooled by the movie's own
    colour (a hue-rotating colour pattern makes the composite green content-dependent
    and races the decoder-source sample). A fast-scrolling NEUTRAL grating solves
    both: vertical black/white stripes scrolling at 720 px/s give ~228 ROI-MAE per
    frame (unmistakable motion), and cb=cr=128 keeps every pixel neutral (r==g==b),
    so a translucent green square over it reads greenish IFF it is genuinely in
    front — a neutral movie can never be green on its own. Black behind reads the
    grey grating (rgbMean ~124 > 40). Not a flat poster; decodes as H.264.

    A NEUTRAL frame-index patch (top-left 120x48, cb=cr=128 like the rest of the
    frame) rides on top of the grating. Finding 1's composited-freeze check
    decodes that patch off the composite screenshots: a stuck patch value across
    the MM cut means the composited canvas is still showing the stale poster
    frame, independent of the grating's own motion.

    The patch luma is `16 + (N mod 220)`, NOT a raw `mod(N, 256)` — measured
    empirically (offline decode, no browser): a raw 0-255 luma value spends
    frames 0-16 of every 256-frame cycle below the legal "tv-range" black floor
    (Y=16), which yuv->rgb conversion (the same conversion an H.264 <video>
    decode does) clips flat to RGB 0 for all 17 of those frames — a 17-frame
    false "freeze" recurring every ~8.5s, indistinguishable from a real one.
    Offsetting by 16 keeps every value inside the legal 16-235 luma range, so
    it survives H.264 encode + yuv->rgb decode with no clipping; residual
    rounding in that conversion still occasionally repeats or skips a value,
    but never for more than 1 consecutive frame (measured below).

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
        f"color=c=gray:s=1920x540:rate={fps}:duration={seconds}",
        "-vf",
        r"geq=lum='if(lt(X\,120)*lt(Y\,48)\,16+mod(N\,220)\,if(gt(mod(X+T*720\,48)\,24)\,230\,25))':cb=128:cr=128",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-an",
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


async def _media_snapshot(chrome: ChromeCdp) -> dict:
    return await chrome.evaluate(MEDIA_PROBE_JS) or {}


async def _ensure_videos_playing(chrome: ChromeCdp) -> None:
    await chrome.evaluate(
        """
(() => {
  Array.prototype.slice.call(document.querySelectorAll('video')).forEach((v) => {
    try { v.muted = true; var p = v.play(); if (p && p.catch) p.catch(function(){}); } catch (e) {}
  });
  return document.querySelectorAll('video').length;
})()
"""
    )


async def _trigger_advance(chrome: ChromeCdp) -> str:
    """Advance slide transition. Space first (Keynote HTML), then edge click, then ArrowRight."""
    hash0 = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    await chrome.key(" ", "Space", 32)
    await asyncio.sleep(0.25)
    hash1 = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    if hash1 != hash0:
        return "space"
    # Edge click — center often hits the <video> and is swallowed
    await chrome.call("Input.dispatchMouseEvent", type="mouseMoved", x=20, y=20)
    await chrome.call(
        "Input.dispatchMouseEvent", type="mousePressed", x=20, y=20, button="left", clickCount=1
    )
    await chrome.call(
        "Input.dispatchMouseEvent", type="mouseReleased", x=20, y=20, button="left", clickCount=1
    )
    await asyncio.sleep(0.25)
    hash2 = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    if hash2 != hash0:
        return "edge_click"
    await chrome.key("ArrowRight", "ArrowRight", 39)
    await asyncio.sleep(0.25)
    return "arrow_right_fallback"


async def _wait_hash_clean(chrome: ChromeCdp, timeout_s: float = 8.0) -> str:
    import re

    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = str(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
            or ""
        )
        # Strip accidental query bleed if the player mutates location oddly
        if "?" in last:
            last = last.split("?", 1)[0]
        if re.fullmatch(r"#\d+", last or ""):
            return last
        await asyncio.sleep(0.05)
    return last.split("?", 1)[0] if "?" in (last or "") else last


def _alpha_report(arr: np.ndarray) -> dict:
    a = analyze_rgba(arr)
    return {
        "alphaMin": a["alphaMin"],
        "transparentFrac": a["transparentFrac"],
        "pass": a["pass"],
        "emptyBackgroundOk": a["samples"]["emptyBackgroundOk"],
        "progress": progress_metric(arr),
    }


async def _boot_slide1(chrome: ChromeCdp, base: str) -> tuple[dict, str, bool, dict]:
    """Load slide 1 and wait until movie1 is playing. One reload retry."""
    media_boot: dict = {}
    live_hash = ""
    video_ready = False
    ready: dict = {}
    for attempt in range(2):
        await chrome.goto("about:blank")
        await asyncio.sleep(0.05)
        await chrome.goto(f"{base}?currentSlide=1")
        ready = await _wait_ready(chrome)
        live_hash = await _wait_hash_clean(chrome)
        await _ensure_videos_playing(chrome)
        for _ in range(50):  # ≤5s
            media_boot = await _media_snapshot(chrome)
            m1 = [
                v
                for v in (media_boot.get("videos") or [])
                if _movie_key(v.get("src") or "") == "movie1"
            ]
            if m1 and (m1[0].get("readyState") or 0) >= 2:
                if m1[0].get("paused"):
                    await _ensure_videos_playing(chrome)
                    await asyncio.sleep(0.1)
                    continue
                video_ready = True
                return ready, live_hash, video_ready, media_boot
            await asyncio.sleep(0.1)
        # reload once
    return ready, live_hash, video_ready, media_boot


async def _run_delay(chrome: ChromeCdp, base: str, delay_s: float, run_dir: Path) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    ready, live_hash, video_ready, _media_boot = await _boot_slide1(chrome, base)
    # Wait click delay on wall clock; sample media at start/end of wait
    media_pre = await _media_snapshot(chrome)
    wall0 = time.monotonic()
    await asyncio.sleep(delay_s)
    wall_waited = time.monotonic() - wall0
    media_at_click = await _media_snapshot(chrome)

    samples = []
    frames_meta = []
    # pre-click sample
    shot = await chrome.screenshot()
    samples.append({**media_at_click, "phase": "pre-click", "captureWall": time.monotonic()})
    Image.fromarray(shot).save(run_dir / "pre-click.png")
    frames_meta.append({"name": "pre-click.png", "alpha": _alpha_report(shot), "phase": "pre-click"})

    hash_before = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    advance_method = await _trigger_advance(chrome)
    click_wall = time.monotonic()

    # Dense sample during dissolve + settle
    n = int((DISSOLVE_S + POST_SETTLE_S) * DENSE_FPS)
    dt = 1.0 / DENSE_FPS
    click_i = 1  # index in samples after pre-click
    for i in range(n):
        target = click_wall + (i + 1) * dt
        while time.monotonic() < target:
            await asyncio.sleep(0.001)
        capture_wall = time.monotonic()
        media = await _media_snapshot(chrome)
        # Only screenshot a subset to limit IO (every 2nd + first/last)
        do_shot = i % 2 == 0 or i == n - 1
        alpha = None
        if do_shot:
            arr = await chrome.screenshot()
            name = f"t{i:03d}.png"
            Image.fromarray(arr).save(run_dir / name)
            alpha = _alpha_report(arr)
            frames_meta.append({"name": name, "alpha": alpha, "phase": "dissolve", "i": i})
        samples.append(
            {
                **media,
                "phase": "dissolve",
                "i": i,
                "captureWall": capture_wall,
                "captureOffsetS": capture_wall - click_wall,
            }
        )

    hash_after = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    media_post = await _media_snapshot(chrome)
    handoff_events = await chrome.evaluate(
        """
(() => {
  const h = window.__OBED_P2_HANDOFF__;
  const p = window.__OBED_P2_PRESERVE__;
  return {
    handoff: h ? h.events.slice(-40) : [],
    preserve: p ? p.events.slice(-40) : [],
    poolKeys: p ? p.poolKeys : [],
  };
})()
"""
    )
    post = await chrome.screenshot()
    Image.fromarray(post).save(run_dir / "post.png")
    frames_meta.append({"name": "post.png", "alpha": _alpha_report(post), "phase": "post"})

    media_class = _classify_media_series(samples, click_i=click_i)
    # Alpha through dissolve screenshots
    dissolve_alphas = [f["alpha"] for f in frames_meta if f.get("phase") == "dissolve" and f.get("alpha")]
    empty_ok = bool(dissolve_alphas) and all(
        a["transparentFrac"] >= 0.5 or a["emptyBackgroundOk"] for a in dissolve_alphas
    )
    # Playback vs capture clocks — prefer movie1 token
    def _m1_time(snap: dict) -> float | None:
        for v in snap.get("videos") or []:
            if _movie_key(v.get("src") or "") == "movie1":
                return v.get("currentTime")
        return None

    pre_t = _m1_time(media_pre)
    click_t = _m1_time(media_at_click)
    media_wait_advance = None if pre_t is None or click_t is None else float(click_t - pre_t)

    clocks = {
        "wallWaitS": wall_waited,
        "requestedDelayS": delay_s,
        "mediaAdvanceDuringWaitS": media_wait_advance,
        "captureDtS": dt,
        "note": "media.currentTime is playback clock; captureOffsetS is capture clock",
    }

    result = {
        "delayS": delay_s,
        "ready": ready,
        "videoReady": video_ready,
        "liveHash": live_hash,
        "advanceMethod": advance_method,
        "hashBefore": hash_before,
        "hashAfter": hash_after,
        "hashChanged": hash_before != hash_after,
        "mediaPre": media_pre,
        "mediaAtClick": media_at_click,
        "mediaPost": media_post,
        "handoffEvents": (handoff_events or {}).get("handoff") if isinstance(handoff_events, dict) else handoff_events,
        "preserveEvents": (handoff_events or {}).get("preserve") if isinstance(handoff_events, dict) else [],
        "preservePoolKeys": (handoff_events or {}).get("poolKeys") if isinstance(handoff_events, dict) else [],
        "clocks": clocks,
        "mediaClass": media_class,
        "samples": [
            {
                "phase": s.get("phase"),
                "i": s.get("i"),
                "captureOffsetS": s.get("captureOffsetS"),
                "hash": s.get("hash"),
                "videoCount": s.get("videoCount"),
                "videos": [
                    {
                        "key": _movie_key(v.get("src") or ""),
                        "decoderId": v.get("decoderId"),
                        "currentTime": v.get("currentTime"),
                        "presentedMediaTime": v.get("presentedMediaTime"),
                        "paused": v.get("paused"),
                        "playbackRate": v.get("playbackRate"),
                        "srcTail": (v.get("src") or "")[-50:],
                    }
                    for v in (s.get("videos") or [])
                ],
            }
            for s in samples
        ],
        "emptyCanvasThroughDissolve": empty_ok,
        "frameAlphas": frames_meta,
        "pass": bool(
            video_ready
            and media_class["movie1"].get("continuesThroughDissolve")
            and media_class["movie1"].get("noJump")
            and media_class["movie1"].get("noRestart")
            and media_class.get("secondMoviePlayingAfterClick")
            and hash_before != hash_after
            and not media_class["movie1"].get("frozenClock")
        ),
        "setupFailed": not video_ready,
        # alpha is scored but opaque HTML does not fail the playback/sync gate
        "alphaGate": empty_ok,
    }
    write_json(run_dir / "run.json", result)
    return result


async def _async_main(player: Path, report: dict) -> dict:
    httpd, port = _serve(player)
    base = f"http://127.0.0.1:{port}/index.html"
    report["httpBase"] = base
    runs = []
    try:
        for d in CLICK_DELAYS_S:
            print(f"run delay={d}s")
            profile = OUT / f"chrome-profile-{d:.1f}-{int(time.time())}"
            chrome = ChromeCdp(CHROME, profile, width=1920, height=1080)
            await chrome.start()
            try:
                runs.append(await _run_delay(chrome, base, d, OUT / "runs" / f"delay-{d:.1f}s"))
            finally:
                await chrome.close()
    finally:
        httpd.shutdown()
    report["runs"] = runs
    return report


def main() -> int:
    reuse = "--reuse-export" in sys.argv
    handoff = "--handoff" in sys.argv
    preserve = "--preserve" in sys.argv
    strip_pdf = "--strip-pdf" in sys.argv
    global OUT
    if preserve and strip_pdf:
        OUT = REPO / "output" / "p2-recovery" / "html-dissolve-preserve-alpha"
    elif preserve:
        OUT = REPO / "output" / "p2-recovery" / "html-dissolve-preserve"
    elif handoff:
        OUT = REPO / "output" / "p2-recovery" / "html-dissolve-handoff"
    started = time.monotonic()
    before = file_identity(SOURCE)
    unmodified = OUT / "html-unmodified"
    player = OUT / "html-player"

    baseline_unmodified = REPO / "output" / "p2-recovery" / "html-dissolve-live" / "html-unmodified"
    preserve_unmodified = REPO / "output" / "p2-recovery" / "html-dissolve-preserve" / "html-unmodified"
    if reuse and unmodified.is_dir() and (unmodified / "index.html").is_file() and not (
        preserve and strip_pdf and not (OUT / "pdf-strip.json").is_file()
    ):
        print("reusing HTML export at", unmodified)
        if (OUT / "runs").exists():
            shutil.rmtree(OUT / "runs")
        for p in OUT.glob("chrome-profile*"):
            shutil.rmtree(p, ignore_errors=True)
        (OUT / "runs").mkdir(parents=True, exist_ok=True)
    elif reuse and (handoff or preserve):
        src = (
            preserve_unmodified
            if (preserve and strip_pdf and preserve_unmodified.is_dir())
            else baseline_unmodified
        )
        if not (src / "index.html").is_file():
            raise SystemExit(f"missing reusable export at {src}")
        print("reusing HTML export from", src, "into", OUT.name)
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        shutil.copytree(src, unmodified)
        (OUT / "runs").mkdir(parents=True, exist_ok=True)
    else:
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        write_json(OUT / "fingerprints-before.json", before.as_dict())
        inv = inventory_deck(SOURCE)
        write_json(
            OUT / "inventory.json",
            {
                "source": before.as_dict(),
                "canvas": inv["canvas"],
                "slideCount": inv["slideCount"],
                "skipped": inv.get("skipped"),
                "slides": [
                    {
                        "originalOrdinal": s["originalOrdinal"],
                        "transition": s.get("transition"),
                        "hasMovieStart": s.get("hasMovieStart"),
                        "magicMove": s.get("magicMove"),
                        "builds": s.get("builds"),
                    }
                    for s in inv["slides"]
                ],
            },
        )

        if keynote_running():
            raise SystemExit(
                "Keynote is already running — refuse to force-quit an owner session. "
                "Quit Keynote and re-run."
            )

        print("HTML export…")
        export_html(SOURCE, unmodified, log=print)

    write_json(OUT / "fingerprints-before.json", before.as_dict())
    strip_info = None
    if strip_pdf:
        prior_strip = OUT / "pdf-strip.json"
        if (
            reuse
            and prior_strip.is_file()
            and (unmodified / "index.html").is_file()
        ):
            strip_info = json.loads(prior_strip.read_text(encoding="utf-8"))
            print("reusing prior PDF strip record (", len(strip_info.get("rewritten") or []), "pdfs )")
        else:
            print("stripping identified full-slide PDF black fills…")
            strip_info = strip_export_pdf_bg_fills(unmodified)
            write_json(prior_strip, strip_info)
            print("stripped", [r["pdf"] for r in (strip_info.get("rewritten") or [])])
    patch = write_patched_export(unmodified, player)
    write_json(OUT / "patch.json", patch)
    inject_info: dict = {"handoff": False, "preserve": False, "stripPdf": bool(strip_pdf)}
    if handoff:
        inject_info["handoff"] = inject_handoff(player)
        write_json(OUT / "handoff-inject.json", inject_info["handoff"])
    if preserve:
        inject_info["preserve"] = inject_preserve(player)
        write_json(OUT / "preserve-inject.json", inject_info["preserve"])
        # This fixture is click-triggered dissolve only (no Magic Move boundary),
        # so the movie should simply continue: empty boundaries default the core
        # to "pin" behaviour throughout, matching the pre-plan defaults.
        continuity_plan = {
            "movies": {
                "movie1": {"assetKeys": [MOVIE1_TOKEN.lower()], "footprint": {"x": 109, "y": 795, "w": 952, "h": 268}},
                "movie2": {"assetKeys": [MOVIE2_TOKEN.lower()], "footprint": {"x": 109, "y": 500, "w": 663, "h": 186}},
            },
            "boundaries": [],
            "transparentBackground": True,
        }
        inject_info["continuityPlan"] = inject_continuity_plan(player, continuity_plan)
        write_json(OUT / "continuity-plan-inject.json", inject_info["continuityPlan"])

    report: dict = {
        "probe": "p2_recovery_html_dissolve_live",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": before.as_dict(),
        "fixture": "Minimal Alpha_DSK.key",
        "clickDelaysS": list(CLICK_DELAYS_S),
        "dissolveS": DISSOLVE_S,
        "denseFps": DENSE_FPS,
        "reusedExport": reuse,
        "handoff": bool(handoff),
        "preserve": bool(preserve),
        "stripPdf": strip_info,
        "inject": inject_info,
        "p3": "still unwired",
        "magicMoveExtension": "later — dissolve milestone first",
        "alpha": "with --strip-pdf, success requires playback AND alpha gates",
    }
    report = asyncio.run(_async_main(player, report))

    after = file_identity(SOURCE)
    write_json(OUT / "fingerprints-after.json", after.as_dict())
    report["sourceUnchanged"] = after.as_dict() == before.as_dict()
    report["durationS"] = time.monotonic() - started

    # Aggregate
    playback_passes = [r["pass"] for r in report["runs"]]
    alpha_passes = [r["alphaGate"] for r in report["runs"]]
    report["findings"] = [
        {"id": "allDelaysPlaybackPass", "pass": all(playback_passes)},
        {
            "id": "movie1ContinuesThroughDissolve",
            "pass": all(r["mediaClass"]["movie1"].get("continuesThroughDissolve") for r in report["runs"]),
            "note": "requires position continuity, advancing media, noJump/noRestart, elapsed-time consistency",
        },
        {
            "id": "movie1NoJump",
            "pass": all(r["mediaClass"]["movie1"].get("noJump") for r in report["runs"]),
        },
        {
            "id": "movie1MediaProgressing",
            "pass": all(r["mediaClass"]["movie1"].get("mediaProgressing") for r in report["runs"]),
        },
        {
            "id": "movie1NotFrozenClock",
            "pass": all(not r["mediaClass"]["movie1"].get("frozenClock") for r in report["runs"]),
        },
        {
            "id": "movie1RemountRestartOnDissolve",
            "pass": all(not r["mediaClass"]["movie1"].get("remountRestart") for r in report["runs"]),
            "note": "fail means HTML player recreates across-slides <video> at t≈0 when dissolve starts",
        },
        {
            "id": "secondMoviePlayingAfterDissolve",
            "pass": all(r["mediaClass"].get("secondMoviePlayingAfterClick") for r in report["runs"]),
            "note": "movie2 must advance, not merely appear in the DOM",
        },
        {
            "id": "hashAdvancesOnClick",
            "pass": all(r["hashChanged"] for r in report["runs"]),
        },
        {
            "id": "emptyCanvasAlpha",
            "pass": all(alpha_passes),
            "note": (
                "required for success when --strip-pdf"
                if strip_pdf
                else "HTML composed alpha scored separately; not a playback gate"
            ),
        },
        {
            "id": "mediaClockIndependentOfCapture",
            "pass": all(
                (r["clocks"].get("mediaAdvanceDuringWaitS") or 0) > 0.2
                for r in report["runs"]
            ),
            "note": "media.currentTime advanced during wait roughly with delay",
        },
    ]
    report["successPlayback"] = all(
        f["pass"] for f in report["findings"] if f["id"] != "emptyCanvasAlpha"
    )
    report["successAlpha"] = all(alpha_passes)
    report["success"] = (
        report["successPlayback"] and report["successAlpha"]
        if strip_pdf
        else report["successPlayback"]
    )
    write_json(OUT / "report.json", report)

    lines = [
        "# HTML live dissolve — Minimal Alpha_DSK",
        "",
        f"Generated: {report['generated']}",
        f"Source unchanged: **{report['sourceUnchanged']}**",
        f"Delays tested: `{list(CLICK_DELAYS_S)}`s  dissolve≈{DISSOLVE_S}s  dense={DENSE_FPS}fps",
        f"Reuse export: {reuse}  handoff: {handoff}  preserve: {preserve}  stripPdf: {strip_pdf}",
        "",
        "## Per-delay",
        "",
    ]
    for r in report["runs"]:
        mc = r["mediaClass"]
        m1 = mc["movie1"]
        lines.append(
            f"- delay **{r['delayS']}s**: pass={r['pass']} hash {r['hashBefore']}→{r['hashAfter']} "
            f"method={r.get('advanceMethod')} mediaWaitΔ={r['clocks'].get('mediaAdvanceDuringWaitS')} "
            f"m1 pre→firstAfter→post {m1.get('preTime')}→{m1.get('firstAfterClick')}→{m1.get('postTime')} "
            f"remount={m1.get('remountRestart')} progressing={m1.get('mediaProgressing')} "
            f"frozen={m1.get('frozenClock')} continues={m1.get('continuesThroughDissolve')} "
            f"2ndPlaying={mc.get('secondMoviePlayingAfterClick')} "
            f"handoffs={len(r.get('handoffEvents') or [])} "
            f"preserves={len(r.get('preserveEvents') or [])} alphaGate={r['alphaGate']}"
        )
    lines += ["", "## Findings", ""]
    for f in report["findings"]:
        lines.append(f"- {f['id']}: **{f['pass']}**" + (f" — {f['note']}" if f.get("note") else ""))
    lines += [
        "",
        f"**successPlayback: {report['successPlayback']}**  "
        f"**successAlpha: {report['successAlpha']}**  "
        f"**success: {report['success']}**",
        "",
        "P3 still unwired."
        + (" Alpha is a dual gate with --strip-pdf." if strip_pdf else " Alpha remains a separate gate."),
        f"Samples: `{OUT}`",
    ]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if report["sourceUnchanged"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
