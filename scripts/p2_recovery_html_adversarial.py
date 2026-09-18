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
    score_composited_index_run,
    score_index_progression,
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
# Slide-1 (pre) positions on the owner-revised deck (measured): black sentinel canvas
# ~[975,722,266,236], green square ~[636,723,178,157]; both sampled ABOVE the movie top
# (~791) so black reads opaque and green reads its authored partial alpha (translucent).
BLACK_ROI_S1 = (1010, 740, 180, 45)
BLACK_ROI_S2 = (545 + 20, 724 + 20, 174 - 40, 154 - 40)
GREEN_ROI_S1 = (660, 735, 150, 45)
# Owner-authored z-order (front->back): green square -> larger movie -> black square
# -> smaller movie. So relative to the LARGER movie the green square is IN FRONT and
# the black sentinel is BEHIND. Black sentinel canvas ~[542,721,181,161], larger movie
# ~[105,791,960,276], green square ~[789,673,353,313] (measured on the exported deck).
BLACK_ABOVE_ROI = (560, 730, 140, 50)    # black sentinel above the movie -> opaque black present
BLACK_BEHIND_ROI = (560, 800, 140, 70)   # black sentinel ∩ movie -> the MOVIE must show (black behind)
GREEN_FRONT_ROI = (820, 810, 160, 120)   # green square ∩ movie -> translucent green IN FRONT
EMPTY_CORNERS = ((1864, 8, 48, 48), (1864, 1024, 48, 48))  # right side stays emptier after MM
# Large continuing movie footprint on slide 1 (inventory). Center is unobscured.
MOVIE_ROI = (109, 795, 952, 268)
# The disposable movie's frame-index stimulus patch occupies the top-left
# 120x48 of its 1920x540 source; map it to screen space via the movie's own
# footprint fraction (see _write_h264_pattern in p2_recovery_html_dissolve_live.py).
# Inset well inside the ~60x24 on-screen patch: the full mapped size spills past
# the patch's bottom-right edge into the high-contrast grating (std explodes ->
# the neutrality gate rejects it). A shrunk inner ROI stays flat (std ~0).
INDEX_PATCH_ROI = (
    MOVIE_ROI[0] + 2,
    MOVIE_ROI[1],
    max(1, round(MOVIE_ROI[2] * 120 / 1920) - 18),
    max(1, round(MOVIE_ROI[3] * 48 / 540) - 10),
)
# On slide 3 the restarted movie renders at a DIFFERENT screen rect (~x232,
# shifted right of the slide-2 footprint) and slightly smaller, so INDEX_PATCH_ROI
# above reads the black margin. This is the slide-3 movie's index patch, measured
# empirically from the restart frames (largest flat-neutral region that decodes
# the counter across the window). A wrong ROI decodes to non-flat pixels -> None
# -> score_index_progression fails closed on min_decodable, never a false pass.
INDEX_PATCH_ROI_SLIDE3 = (233, 800, 24, 12)
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


def _decode_index_patch(arr: np.ndarray, roi: tuple[int, int, int, int] = INDEX_PATCH_ROI) -> int | None:
    """Decode the frame-index stimulus patch off a composite screenshot.

    None if the mapped ROI isn't a flat neutral patch (composite not settled,
    ROI mislocated, or occluded) — never guess a value from noisy pixels.
    """
    patch = _crop(arr, roi)
    if patch.size == 0:
        return None
    rgb = patch[:, :, :3].astype(np.float64)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    if max(float(r.std()), float(g.std()), float(b.std())) > 8:
        return None
    if max(float(np.abs(r - g).max()), float(np.abs(g - b).max())) > 12:
        return None
    return int(round(float(rgb.mean())))


def _layer_identity(node: dict) -> str | None:
    """Stable identity for an authored layer/object node, used to fold a steady
    texture only into the SAME object that owns the resolved crossfade (Codex
    F5). Size equality is NOT identity: two same-sized movies each own a
    footprint-sized steady, so folding by size would feed movie1 into movie2's
    canvases. Magic Move persists an object's id across the 1->2 pair, so the id
    is the join key. Returns None when the node carries no id — the caller then
    folds no steady rather than guessing.
    """
    for k in ("id", "objectID", "uuid", "layerUUID"):
        v = node.get(k)
        if isinstance(v, (str, int)) and str(v):
            return f"{k}:{v}"
    return None


def _extract_movie_layers(
    events: object,
    footprint_wh: tuple[float, float] | None = None,
    tol: float = 30.0,
) -> tuple[dict[str | None, set[str]], list[dict]]:
    """Walk ONE slide-UUID JSON's `events` tree for the footprint movie's textures.

    Returns `(steady_by_owner, crossfades)` for the layer(s) whose enclosing
    `initialState` w/h matches `footprint_wh` (so a differently-sized OTHER
    movie's layer is excluded; `footprint_wh=None` disables the gate):

      - `steady_by_owner` — `{ownerId | None: {texture, ...}}`: each footprint
        video layer's steady-state `isVideoLayer` texture(s), keyed by the
        owning object's identity (`_layer_identity`). Keeping the owner (not a
        flat set) is what lets `_derive_movie_texids` fold a steady into ONLY the
        object that owns the boundary crossfade (Codex F5). An id-less layer's
        steady lands under `None` and is never folded.
      - `crossfades` — `[{"from", "to", "owner", "withinMagicMove"}, ...]` from
        `property == "contents"` animations with `from != to`: the poster swap's
        outgoing (`from`) and incoming (`to`) textures, tagged with the enclosing
        video layer's identity (`owner`, may be None) and whether an ancestor is
        an `apple:magic-move-*` transition (`withinMagicMove`). A same-texture
        (`from == to`) tween is a background/opacity animation, not a crossfade.

    This function never unions across slides. The caller
    (`_derive_movie_texids`) resolves the single footprint magic-move crossfade
    (the 2->3 restart boundary under the corrected model) from these per-slide
    pieces and preserves each occurrence's provenance.
    """
    steady_by_owner: dict[str | None, set[str]] = {}
    crossfades: list[dict] = []

    def size_matches(size: tuple[float, float] | None) -> bool:
        if footprint_wh is None:
            return True
        if size is None:
            return False
        return abs(size[0] - footprint_wh[0]) <= tol and abs(size[1] - footprint_wh[1]) <= tol

    def walk(
        o: object,
        layer_size: tuple[float, float] | None,
        owner: str | None,
        in_mm: bool,
    ) -> None:
        if isinstance(o, dict):
            size = layer_size
            init = o.get("initialState")
            if isinstance(init, dict) and isinstance(init.get("width"), (int, float)) and isinstance(
                init.get("height"), (int, float)
            ):
                size = (init["width"], init["height"])
            # A `contents` crossfade is the movie's OWN poster swap only when it
            # sits inside a Magic Move transition (Keynote authors the enclosing
            # layer name `apple:magic-move-*`). The crossfade lives in a separate
            # event subtree from the steady `isVideoLayer`, and this deck's layers
            # carry no id on the video node itself, so this authored transition
            # marker — not layer identity or texture-set membership — is what
            # distinguishes a real poster swap from a same-sized background tween.
            name = o.get("name")
            # Require an AUTHORED Magic Move TRANSITION node: `type == "transition"`
            # AND an `apple:magic-move-*` name — not a loose "magic-move" substring
            # (Codex r2 F2: "not-a-magic-move-caption" must not match) and not a
            # non-transition group that merely bears the name (Codex r3 F2).
            if (
                o.get("type") == "transition"
                and isinstance(name, str)
                and name.lower().startswith("apple:magic-move")
            ):
                in_mm = True
            if o.get("isVideoLayer"):
                owner = _layer_identity(o)
            if o.get("isVideoLayer") and o.get("texture") and size_matches(size):
                steady_by_owner.setdefault(owner, set()).add(o["texture"])
            if o.get("property") == "contents" and size_matches(size):
                frm = (o.get("from") or {}).get("texture")
                to = (o.get("to") or {}).get("texture")
                if frm and to and frm != to:
                    crossfades.append(
                        {"from": frm, "to": to, "owner": owner, "withinMagicMove": in_mm}
                    )
            for v in o.values():
                walk(v, size, owner, in_mm)
        elif isinstance(o, list):
            for v in o:
                walk(v, layer_size, owner, in_mm)

    walk(events, None, None, False)
    return steady_by_owner, crossfades


def _derive_movie_texids(
    player_dir: Path,
    footprint_wh: tuple[float, float] = (MOVIE_ROI[2], MOVIE_ROI[3]),
    decoder_key: str = EXPECTED_MOVIE_KEYS[0],
) -> dict:
    """Resolve the single footprint-movie Magic Move `contents` crossfade and
    emit Contract-1's `{decoderKey, outgoing, incoming}` (see
    `.agents/plans/step1-ownership-contracts.md`).

    CORRECTED MODEL (handover CORRECTION 2026-09-18): this crossfade is the
    **2->3** restart-side boundary, NOT 1->2. Keynote stores a Magic Move
    transition under its INCOMING slide (#3), so the only footprint magic-move
    `contents` crossfade in the deck is the 2->3 restart crossfade — its posters
    (`0885 -> A223`) surface only at scene #6, OUTSIDE the 1->2 gate window. The
    output is tagged `"boundary": "2to3"`. The 1->2 movie is a live `<video>`
    (no canvas feed), so this crossfade is NOT injected for a 1->2 feed anymore;
    `movie-texids.json` is kept for provenance only.

    NOT a whole-deck union (Codex defect #5): the boundary is the ONE
    footprint-sized `contents` crossfade under a Magic Move transition
    (`withinMagicMove`) — the movie's own poster swap; `from` -> `outgoing`,
    `to` -> `incoming`. The crossfade's `from`/`to` are transition posters that
    never appear as slide-1/2 steady textures (empirically true on this deck), so
    steady-texture anchoring cannot match them; the authored `apple:magic-move-*`
    transition marker is what ties the poster swap to the movie when no object
    identity is on the video node. The animation may be stored under any slide's
    JSON, so crossfades are gathered across the deck.

    "Unambiguous" = EXACTLY ONE distinct magic-move footprint crossfade exists
    (Codex F3). There is NO whole-deck "sole footprint-sized crossfade" fallback:
    a same-sized nonmovie `contents` tween on slide 4 is rejected because it is
    NOT inside a Magic Move (and a different-sized movie's crossfade by the size
    gate). Zero such candidates, or more than one, returns
    `{"decoderKey": null, "outgoing": [], "incoming": [], "warning": ...}` —
    NEVER a whole-deck union. Occurrence provenance (slide uuid + count) is
    preserved and EXPOSES a repeat; note the documented residual (contract doc):
    the SAME `(from, to)` pair genuinely occurring at two distinct boundaries is
    still accepted as one (the authored JSON carries no per-boundary tag to tell
    it apart from redundant storage of one boundary). Not present on this deck.

    `outgoing`/`incoming` are exactly the crossfade `from`/`to` posters. No steady
    texture is folded in (Codex r2 F5): a footprint-sized steady cannot be proven
    to belong to THIS movie by size alone, and the magic-move crossfade carries no
    object identity to tie one to it; the runtime player-draw wrapper discovers the
    true canvas<->decoder binding instead.
    """
    header_path = player_dir / "assets" / "header.json"
    try:
        header = json.loads(header_path.read_text())
    except Exception as e:  # noqa: BLE001
        return {"decoderKey": None, "outgoing": [], "incoming": [], "warning": f"header read failed: {e}"}
    slide_list = header.get("slideList") or []
    if len(slide_list) < 2:
        return {
            "decoderKey": None,
            "outgoing": [],
            "incoming": [],
            "warning": f"need >=2 slides to resolve the 1->2 boundary, got {len(slide_list)}",
            "slideList": slide_list,
        }

    occurrences: list[dict] = []  # {from, to, owner, slide} — provenance kept per hit
    scanned: list[str] = []
    for uuid in slide_list:
        path = player_dir / "assets" / uuid / f"{uuid}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue
        scanned.append(uuid)
        _steady_by_owner, cfs = _extract_movie_layers(
            data.get("events") or [], footprint_wh=footprint_wh
        )
        for cf in cfs:
            occurrences.append({**cf, "slide": uuid})

    # Select the boundary crossfade STRUCTURALLY: a footprint-sized `contents`
    # crossfade under a Magic Move transition (`withinMagicMove`) — the movie's
    # own poster swap. Its `from`/`to` are transition-only poster textures that
    # never appear as slide-1/2 steady state, so steady-texture anchoring cannot
    # match them (and the whole-deck "sole crossfade" fallback that Codex F3
    # flagged was the only thing that used to resolve this). A spurious same-sized
    # *background* `contents` tween is rejected because it is not inside a Magic
    # Move; a differently-sized movie's crossfade is rejected by the footprint
    # size gate. DISTINCT by (from, to); provenance retained.
    movie_cfs: dict[tuple[str, str], list[dict]] = {}
    for occ in occurrences:
        if occ.get("withinMagicMove"):
            movie_cfs.setdefault((occ["from"], occ["to"]), []).append(occ)

    if len(movie_cfs) != 1:
        crossfade_summary = [
            {"from": f, "to": t, "count": len(occs), "slides": sorted({o["slide"] for o in occs})}
            for (f, t), occs in sorted(movie_cfs.items())
        ]
        return {
            "decoderKey": None,
            "outgoing": [],
            "incoming": [],
            "warning": (
                f"1->2 boundary not uniquely resolvable: {len(movie_cfs)} distinct "
                f"magic-move footprint crossfade(s) among {len(occurrences)} occurrence(s)"
            ),
            "scannedSlideUuids": scanned,
            "slideList": slide_list,
            "movieCrossfadeCandidates": crossfade_summary,
        }

    (frm, to), occs = next(iter(movie_cfs.items()))

    # outgoing = the crossfade `from` (pre-cut poster), incoming = `to` (post-cut
    # poster). No steady folding (Codex r2 F5): a footprint-sized steady texture
    # cannot be proven to belong to THIS movie by size, and on the real deck the
    # magic-move crossfade carries no object identity to tie a steady to it. The
    # provable, honest hint is exactly the two poster textures; at runtime the
    # player-draw wrapper (dissolve_live.py) discovers the true canvas<->decoder
    # binding, so the static hint need not (and must not) guess the steady canvas.
    return {
        "decoderKey": decoder_key,
        "boundary": "2to3",
        "outgoing": [frm],
        "incoming": [to],
        "boundaryCrossfade": {"from": frm, "to": to},
        "boundaryOccurrences": [{"slide": o["slide"], "owner": o["owner"]} for o in occs],
        "scannedSlideUuids": scanned,
        "slideList": slide_list,
    }


def liveContinuity1to2(
    motion_across_flip: dict,
    flip_samples: list[dict],
    presented_samples: list[dict],
    hash1: object,
    hash2: object,
    restart_min_hash: object = None,
) -> dict:
    """Fail-CLOSED sub-verdict for live-`<video>` continuity through the 1->2
    Magic Move (corrected model — see the handover CORRECTION 2026-09-18 and the
    Step-2 contract, Stream B). The 1->2 movie is a live `<video>` at the
    footprint, NOT a fed 2D canvas, so the old deck-texid / canvas-feed checks
    (`bothSidedTexids`, `contextType2d`, `incomingFeedDraw`) are DROPPED entirely:
    they assumed a 2D-canvas surface that does not exist for 1->2, and the deck
    texids they keyed off are the 2->3 crossfade (never in-window here). A live
    `<video>` owner reports `contextType=null`, so this gate requires NO 2D
    context and NO texid membership.

    `ok` iff ALL hold (absence of any ⇒ fail closed; the failing name is
    recorded):
      - `boundaryValid` — `hash1` and `hash2` both parse AND `num(hash2) >
        num(hash1)`: a genuine FORWARD entry into the 1->2 window. A regressive
        (`#1->#0`), equal, or unparseable hash pair cannot place the after-window.
      - `stableFootprintDecoder` — exactly ONE distinct non-null `decoderId`
        covering a strong majority (>=70%) of the after-window, defined as samples
        strictly inside `[num(hash2), restart_min_hash)` (NOT merely
        `sceneHash != hash1`, which would admit a pre-advance or a 2->3 restart
        frame). A same-key handoff (>=2 distinct non-null ids) or a mostly-
        unresolved window fails; a few transient null frames (the <video> briefly
        mid-remount during the fast MM animation) are tolerated.
      - `crossingIdentity` — the PRE-flip footprint owner (flip_samples with
        hn <= num(hash1)) is resolved AND is exactly the same single decoder as the
        after-window owner. This rejects a same-key HANDOFF (D1 owns before, sibling
        D2 slides into the footprint after): post-flip stability + rVFC advance alone
        cannot see it because D2's own clock is already advancing. Derived from
        flip_samples (jitter-tolerant), not the two exact crossing frames, and NOT
        the aliased pixel crossing-MAE.
      - `rvfcAdvance` — the bound footprint decoder's rVFC `presentedMediaTime`
        advances (> 0.05) within `[num(hash2), restart_min_hash)`, proving the
        live `<video>` is actually presenting new frames across the cut. Fails
        closed on an invalid boundary, a null bound decoder, or <2 samples.

    `motionAcrossFlip.ok` (the pixel crossing-MAE verdict) is NOT gated here — it
    aliases to ~0 ("frozen crossing") on the disposable two-state grating, the
    exact parity-aliasing that `score_index_progression` defeats; gating it would
    reintroduce that flake. Composited motion is proven by the top-level
    `visible_motion.ok` + `index_run.ok` (the aliasing-immune burnt-in counter);
    this sub-verdict adds decoder IDENTITY + crossing continuity + LIVENESS.

    `flip_samples` supply the after-window decoder identity (roi/sceneHash/
    decoderId). `presented_samples` (media snapshots carrying `videos`) supply the
    bound decoder's own rVFC clock. `restart_min_hash` upper-bounds both windows.
    """
    motion_ok = bool((motion_across_flip or {}).get("ok"))

    n1 = _strict_hash_num(hash1)
    n2 = _strict_hash_num(hash2)
    n_restart = restart_min_hash if isinstance(restart_min_hash, int) else _strict_hash_num(restart_min_hash)
    # A missing/malformed restart bound leaves the after-window unbounded above (a
    # #99 sample would count) — so the bound is REQUIRED for a valid boundary (the
    # function itself stays fail-closed, not only the production caller).
    boundary_valid = n1 is not None and n2 is not None and n2 > n1 and n_restart is not None

    def _in_window(s: dict) -> bool:
        hn = _strict_hash_num(s.get("sceneHash"))
        if hn is None or n2 is None or hn < n2:
            return False
        if n_restart is not None and hn >= n_restart:
            return False
        return True

    post = [s for s in (flip_samples or []) if _in_window(s)] if boundary_valid else []
    distinct_ids = sorted({s.get("decoderId") for s in post}, key=lambda x: (x is None, str(x)))
    # ONE dominant footprint owner: exactly one DISTINCT non-null decoderId across
    # the after-window, covering a strong majority of it. A same-key HANDOFF is >=2
    # distinct non-null ids -> fail. A mostly-unresolved window -> fail. A few
    # transient unresolved (null) frames are tolerated: the footprint <video> is
    # briefly mid-remount during the fast MM animation, so ~1 capture per run can
    # land in that gap even though the movie is continuously present otherwise
    # (measured: when placed its footprint IoU is ~0.998, never marginal) — a
    # zero-null rule turned that instrument jitter into a spurious RED. Rejecting
    # the real failure modes while tolerating jitter keeps this fail-closed.
    non_null_ids = [s.get("decoderId") for s in post if s.get("decoderId") is not None]
    distinct_non_null = sorted(set(non_null_ids))
    non_null_frac = (len(non_null_ids) / len(post)) if post else 0.0
    # A tolerated null must be a genuine ABSENCE gap, never a masked handoff: a null
    # from `footprintOwnerDecoderId` returning `via=='ambiguous'` means TWO decoders
    # both cover the footprint (D1 leaving + D2 arriving) — a handoff in progress —
    # so ANY ambiguous after-frame fails closed rather than being tolerated as jitter.
    # (A frame where a single OTHER decoder owns the footprint is not null; it makes
    # distinct_non_null == 2 and fails anyway.)
    has_ambiguous_owner = any(s.get("ownerAmbiguous") for s in post)
    stable = (
        bool(post)
        and len(distinct_non_null) == 1
        and non_null_frac >= 0.7
        and not has_ambiguous_owner
    )
    bound_decoder_id = distinct_non_null[0] if stable else None

    # Handoff defense, derived from flip_samples (jitter-tolerant): the PRE-flip
    # footprint owner (frames with hn <= n1) must be resolved and be EXACTLY the same
    # single decoder as the after-window owner. A different pre-flip owner (D1 before,
    # D2 after) is a same-key HANDOFF -> fail. Deriving this from flip_samples rather
    # than the two exact crossing frames score_motion_across_flip picks tolerates a
    # transient unresolved frame at the flip instant (which flaked crossingDecoder
    # Stable on the slow profile) while still requiring before-evidence (empty pre
    # owners -> fail closed). Movie-key correctness is already guaranteed by
    # footprintOwnerDecoderId (it owns a footprint only when assetKey matches it).
    pre = (
        [s for s in (flip_samples or [])
         if (lambda h: h is not None and h <= n1)(_strict_hash_num(s.get("sceneHash")))]
        if boundary_valid else []
    )
    pre_owner_ids = sorted({s.get("decoderId") for s in pre if s.get("decoderId") is not None},
                           key=str)
    pre_ambiguous = any(s.get("ownerAmbiguous") for s in pre)
    crossing_identity = bool(
        bound_decoder_id is not None
        and pre_owner_ids == [bound_decoder_id]
        and not pre_ambiguous
    )

    # rVFC advance of the bound footprint <video>, bounded to the SAME window.
    if not boundary_valid:
        rvfc = {"ok": False, "reason": "invalid 1->2 boundary", "n": 0}
    elif bound_decoder_id is None:
        rvfc = {"ok": False, "reason": "no bound decoder", "n": 0}
    else:
        bounded = [s for s in (presented_samples or []) if _in_window(s)]
        rvfc = _presented_time_advances(bounded, bound_decoder_id, n2)
    rvfc_ok = bool(rvfc.get("ok"))

    checks = {
        "boundaryValid": boundary_valid,
        "stableFootprintDecoder": stable,
        "crossingIdentity": crossing_identity,
        "rvfcAdvance": rvfc_ok,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failed,
        "failed": failed,
        "boundDecoderId": bound_decoder_id,
        "boundaryValid": {"ok": boundary_valid, "n1": n1, "n2": n2, "restart": n_restart},
        "stableFootprintDecoder": {
            "ok": stable,
            "distinctDecoderIds": distinct_ids,
            "distinctNonNull": distinct_non_null,
            "nonNullFrac": round(non_null_frac, 3),
            "afterN": len(post),
        },
        "crossingIdentity": {
            "ok": crossing_identity,
            "preOwnerIds": pre_owner_ids,
            "afterOwner": bound_decoder_id,
        },
        "rvfcAdvance": rvfc,
        # Reported for provenance only — NOT a gating sub-condition (aliased pixel
        # crossing-MAE; the crossing IDENTITY fields above ARE gated).
        "motionAcrossFlipOk": motion_ok,
    }


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


def _score_green_front_composite(
    composite: np.ndarray,
    roi: tuple[int, int, int, int],
    footprint: tuple[int, int, int, int],
    source: np.ndarray | None,
) -> dict:
    """Prove the green square is IN FRONT of the movie by diffing the composite
    against the movie1 decoder's OWN source pixels for the same mapped region.

    A standalone "is this ROI greenish" test is satisfied by the movie's own
    green content even with the square BEHIND it. If the translucent green
    square (~75/255 alpha) is genuinely in front, compositing green-over-movie
    must shift the region toward green and away from red relative to the raw
    source; if it's behind, composite == source and the deltas are ~0.
    Fails closed (ok=False) if the decoder source can't be sampled — no
    fallback to the standalone greenish test.
    """
    comp_patch = _crop(composite, roi)
    if comp_patch.size == 0:
        return {"ok": False, "reason": "empty composite crop"}
    comp_rgb = comp_patch[:, :, :3].astype(np.float64).reshape(-1, 3).mean(axis=0)
    if source is None or source.size == 0:
        return {
            "ok": False,
            "reason": "no decoder source sample",
            "compositeRGB": comp_rgb.tolist(),
            "sourceRGB": None,
            "dG": None,
            "dR": None,
        }
    fx, fy, fw, fh = footprint
    gx, gy, gw, gh = roi
    nx0, ny0 = (gx - fx) / fw, (gy - fy) / fh
    nw, nh = gw / fw, gh / fh
    sh, sw = source.shape[:2]
    x0, y0 = max(0, int(round(nx0 * sw))), max(0, int(round(ny0 * sh)))
    x1, y1 = min(sw, int(round((nx0 + nw) * sw))), min(sh, int(round((ny0 + nh) * sh)))
    source_patch = source[y0:y1, x0:x1]
    if source_patch.size == 0:
        return {
            "ok": False,
            "reason": "empty mapped source crop",
            "compositeRGB": comp_rgb.tolist(),
            "sourceRGB": None,
            "dG": None,
            "dR": None,
            "mappedRect": [x0, y0, x1, y1],
        }
    source_rgb = source_patch[:, :, :3].astype(np.float64).reshape(-1, 3).mean(axis=0)
    dG = float(comp_rgb[1] - source_rgb[1])
    dR = float(comp_rgb[0] - source_rgb[0])
    greenish = bool(comp_rgb[1] > comp_rgb[0] + 15)
    ok = bool(dG >= 20 and dR < 0 and greenish)
    return {
        "ok": ok,
        "compositeRGB": comp_rgb.tolist(),
        "sourceRGB": source_rgb.tolist(),
        "dG": dG,
        "dR": dR,
        "greenish": greenish,
        "mappedRect": [x0, y0, x1, y1],
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


def _times(
    samples: list[dict], key: str = "primary", decoder_id: object | None = None
) -> list[float | None]:
    """Track a movie's clock across samples.

    `key="primary"`/`"min"` give the max/min currentTime across ALL playing
    videos (informational only). Any other `key` gives that asset key's clock;
    when `decoder_id` is given it is BOUND to that one decoder — only videos
    whose `decoderId == decoder_id` (a DOM/pool mirror of the same element)
    contribute, never a max across sibling same-key decoders. A stall on the
    bound decoder then surfaces as a non-advancing (or None) clock instead of
    being masked by a fresh/pooled same-key instance sitting at a higher time.
    """
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
            hits = [
                float(v["currentTime"])
                for v in vids
                if _movie_key(v.get("src") or "") == key
                and v.get("currentTime") is not None
                and (decoder_id is None or v.get("decoderId") == decoder_id)
            ]
            out.append(max(hits) if hits else None)
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


def _strict_hash_num(h: object) -> int | None:
    """Strict scene-hash parse for boundary validation: FULL-match `#<digits>`
    after stripping only a `?query` suffix. Unlike `_hash_num`'s prefix match, a
    malformed value like `#1junk` returns None (fail closed) rather than 1."""
    s = str(h if h is not None else "")
    if "?" in s:
        s = s.split("?", 1)[0]
    m = __import__("re").fullmatch(r"#(\d+)", s)
    return int(m.group(1)) if m else None


def _mae_rgb(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.mean(np.abs(a[:, :, :3].astype(np.float64) - b[:, :, :3].astype(np.float64))))


def _presented_time_advances(samples: list[dict], decoder_id: object, min_hash: int) -> dict:
    """rVFC-presented mediaTime advancement for a decoder, on/after min_hash.

    An alternate, pixel-independent signal for presentedMotionOk: the decoder
    is genuinely presenting new frames even if the composed-ROI pixel check
    is inconclusive (e.g. a still moment in the source pattern).
    """
    if decoder_id is None:
        return {"ok": False, "reason": "no decoderId", "n": 0}
    vals: list[float] = []
    for s in samples:
        hn = _hash_num(s.get("sceneHash"))
        if hn is None or hn < min_hash:
            continue
        for v in s.get("videos") or []:
            if v.get("decoderId") == decoder_id and v.get("presentedMediaTime") is not None:
                vals.append(float(v["presentedMediaTime"]))
    if len(vals) < 2:
        return {"ok": False, "reason": "insufficient presented-time samples", "n": len(vals)}
    # ORDERED forward progression: net advance > 0.05 AND never regress more than
    # 0.05 below ANY previously-presented time (compare to the running max, not just
    # the adjacent step — a cumulative rewind split into small steps like
    # 10.00->9.96->9.92->10.10 would slip past an adjacent-delta check). `max-min`
    # accepted a plain rewind (10.0->1.0 reads as +9.0); a genuinely playing
    # decoder's rVFC media time is monotonic, so any material regression is a
    # restart/seek, not continuity — reject it (fail closed).
    advance = vals[-1] - vals[0]
    running_max = vals[0]
    worst_regression = 0.0
    for v in vals[1:]:
        worst_regression = min(worst_regression, v - running_max)
        running_max = max(running_max, v)
    ok = advance > 0.05 and worst_regression >= -0.05
    return {"ok": bool(ok), "n": len(vals), "advance": advance, "worstRegression": worst_regression}


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


def _resolve_target_media(media: dict, decoder_id: object) -> dict | None:
    """Decoded width / currentTime for a decoderId, across native videos + pool."""
    if decoder_id is None:
        return None
    for v in media.get("videos") or []:
        if v.get("decoderId") == decoder_id:
            w = v.get("w") if v.get("w") is not None else v.get("videoWidth")
            return {"w": w, "currentTime": v.get("currentTime")}
    for p in media.get("preservePool") or []:
        if p.get("elId") == decoder_id:
            return {"w": p.get("videoWidth"), "currentTime": p.get("currentTime")}
    return None


async def _footprint_target(chrome: ChromeCdp, media: dict, roi: tuple[int, int, int, int]) -> dict:
    """Decoder that currently owns the movie footprint (active texture-feed
    canvas first, else the positioned <video> overlapping it most) — stable
    across the Magic Move cut so score_motion_across_flip's crossing-decoder
    check reflects the actual target movie, not whichever video happened
    to be first in the DOM.
    """
    x, y, w, h = roi
    owner = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId "
        f"? window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId({{x:{x}, y:{y}, w:{w}, h:{h}}}) "
        ": {elId: null, key: null, via: 'unavailable'}"
    ) or {"elId": None, "key": None, "via": "unavailable"}
    decoder_id = owner.get("elId")
    context_type = owner.get("contextType")  # passively recorded by PRESERVE_SCRIPT (Stream A)
    resolved = _resolve_target_media(media, decoder_id)
    if resolved is not None:
        return {
            "decoderId": decoder_id,
            "w": resolved.get("w"),
            "movieKey": owner.get("key"),
            "contextType": context_type,
            "via": owner.get("via"),
        }
    # Footprint owner unresolved: fail the gate, never a ready-video fallback
    # (Contract 2 — a first-decoded fallback would bind some OTHER movie).
    return {
        "decoderId": None,
        "w": None,
        "movieKey": None,
        "contextType": context_type,
        "via": owner.get("via", "none"),
    }


def _owner_ambiguous(before: dict, after: dict) -> bool:
    """A footprint frame is handoff/ambiguous when EITHER screenshot-bracket endpoint
    resolved ownership as `ambiguous` (two decoders both cover the footprint), OR the
    two endpoints resolved to DIFFERENT non-null owners (the owner changed mid-capture
    — a handoff in flight). Such a frame must never be tolerated as a mere absence gap
    by the after-window null tolerance."""
    if before.get("via") == "ambiguous" or after.get("via") == "ambiguous":
        return True
    b, a = before.get("decoderId"), after.get("decoderId")
    return bool(b is not None and a is not None and b != a)


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
        # Bracket the screenshot: read sceneHash + footprint owner both before AND
        # after so a flip mid-capture can be detected instead of silently mislabeling
        # a post-flip frame with pre-flip (or vice versa) identity metadata.
        scene_hash_before = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        target_before = await _footprint_target(chrome, media, MOVIE_ROI)
        capture_wall = time.monotonic()
        arr = await chrome.screenshot()
        name = f"{prefix}-pre{i:02d}.png"
        Image.fromarray(arr).save(run_dir / name)
        scene_hash_after = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        target_after = await _footprint_target(chrome, media, MOVIE_ROI)
        bracket_consistent = bool(
            scene_hash_before == scene_hash_after
            and target_before.get("decoderId") == target_after.get("decoderId")
            and target_before.get("movieKey") == target_after.get("movieKey")
        )
        frames.append(
            {
                "name": name,
                "i": -(n - i),
                "empty": _score_empty(arr),
                "sceneHash": scene_hash_after,
                "captureOffsetS": capture_wall - click_wall,
                "decoderId": target_after.get("decoderId") if bracket_consistent else None,
                "w": target_after.get("w") if bracket_consistent else None,
                "movieKey": target_after.get("movieKey") if bracket_consistent else None,
                "contextType": target_after.get("contextType") if bracket_consistent else None,
                "targetVia": target_after.get("via"),
                "ownerAmbiguous": _owner_ambiguous(target_before, target_after),
                "bracketConsistent": bracket_consistent,
                "index": _decode_index_patch(arr),
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
            # Bracket the screenshot (see _pre_advance_frames) so a flip mid-capture
            # is detected rather than silently mislabeling the frame.
            scene_hash_before = _norm_hash(
                await chrome.evaluate(
                    "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                )
            )
            target_before = await _footprint_target(chrome, media, MOVIE_ROI)
            arr = await chrome.screenshot()
            name = f"{prefix}-t{i:03d}.png"
            Image.fromarray(arr).save(run_dir / name)
            scene_hash_after = _norm_hash(
                await chrome.evaluate(
                    "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                )
            )
            target_after = await _footprint_target(chrome, media, MOVIE_ROI)
            bracket_consistent = bool(
                scene_hash_before == scene_hash_after
                and target_before.get("decoderId") == target_after.get("decoderId")
                and target_before.get("movieKey") == target_after.get("movieKey")
            )
            frames.append(
                {
                    "name": name,
                    "i": i,
                    "empty": _score_empty(arr),
                    "sceneHash": scene_hash_after,
                    "captureOffsetS": capture_wall - click_wall,
                    "decoderId": target_after.get("decoderId") if bracket_consistent else None,
                    "w": target_after.get("w") if bracket_consistent else None,
                    "movieKey": target_after.get("movieKey") if bracket_consistent else None,
                    "contextType": target_after.get("contextType") if bracket_consistent else None,
                    "targetVia": target_after.get("via"),
                    "ownerAmbiguous": _owner_ambiguous(target_before, target_after),
                    "bracketConsistent": bracket_consistent,
                    "index": _decode_index_patch(arr),
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
                # Normalise the media snapshot's location hash to `sceneHash` so a
                # dense sample is a valid presented-time sample (it carries `videos`
                # with rVFC presentedMediaTime; _presented_time_advances keys the
                # window off `sceneHash`).
                "sceneHash": _norm_hash(media.get("hash")),
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
        # Derive the footprint movie's Magic Move crossfade texture ids. Under
        # the corrected model this is the 2->3 restart-side crossfade (see
        # `_derive_movie_texids`), so it is written for provenance only and is
        # NO LONGER injected as `window.__OBED_MOVIE_TEXIDS__`: the 1->2 movie is
        # a live `<video>`, not a fed 2D canvas, so that canvas-feed is gone.
        texids_info = _derive_movie_texids(player_dir)
        write_json(OUT / "movie-texids.json", texids_info)
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
        # Sample the movie1 decoder's OWN frame (not the composite) as close to the
        # mid screenshot as possible, to prove the green square composites IN FRONT
        # of it rather than just "this ROI looks greenish" (which the movie's own
        # green content can satisfy on its own).
        media_for_green = await _media_snapshot_with_pool(chrome)
        green_target = await _footprint_target(chrome, media_for_green, MOVIE_ROI)
        green_decoder_id = green_target.get("decoderId")
        green_source_arr: np.ndarray | None = None
        if green_decoder_id is not None:
            green_sample = await chrome.evaluate(
                "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.sampleFrame "
                f"? window.__OBED_P2_PRESERVE__.sampleFrame({int(green_decoder_id)}) : {{ok: false}}"
            )
            if green_sample and green_sample.get("ok") and green_sample.get("dataURL"):
                raw = green_sample["dataURL"].split(",", 1)[-1]
                green_source_arr = np.array(
                    Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
                )
                Image.fromarray(green_source_arr).save(run_dir / "green-front-source.jpg")
        mid_scores = {
            "empty": _score_empty(mid),
            "black": _score_black_auto(mid),
            "blackFixedRoi": _score_black(mid, BLACK_ROI_S2),
            "green": _score_green(mid, GREEN_ROI_S1),
            # New z-order composition (green front, movie, black behind).
            "blackAbove": _score_black(mid, BLACK_ABOVE_ROI),
            "blackBehind": _score_black(mid, BLACK_BEHIND_ROI),
            "greenFront": _score_green(mid, GREEN_FRONT_ROI),
            "greenFrontComposite": _score_green_front_composite(
                mid, GREEN_FRONT_ROI, MOVIE_ROI, green_source_arr
            ),
        }

        # Bind continuity to the ONE footprint-owner decoder's own clock, not
        # "primary" (max across ALL videos) nor max-of-same-key (a fresh/pooled
        # movie1 instance sitting higher must not mask the bound decoder's stall).
        # If the footprint owner is unresolved, emit all-None (the gate fails) —
        # never a same-key fallback.
        primary_times_a = _times(samples_a, "primary")
        min_times_a = _times(samples_a, "min")
        target_times_a = (
            _times(samples_a, EXPECTED_MOVIE_KEYS[0], decoder_id=green_decoder_id)
            if green_decoder_id is not None
            else [None] * len(samples_a)
        )
        cont = score_playback_continuity(
            target_times_a,
            click_i=0,
            capture_offsets=_caps(samples_a),
            dissolve_s=TRANS_S,
            position_eps=1.25,  # MM can take >0.75s before first pooled sample
        )
        mm_paths = sorted(run_dir.glob("mm12-t*.png"))
        visible_motion = _score_visible_movie_motion(mm_paths, MOVIE_ROI)
        capture_race_frames_a = sum(
            1 for f in [*pre_frames_a, *frames_a] if f.get("bracketConsistent") is False
        )
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
                    "movieKey": f.get("movieKey"),
                    "contextType": f.get("contextType"),
                    "ownerAmbiguous": f.get("ownerAmbiguous"),
                }
            )
        motion_across_flip = score_motion_across_flip(
            flip_samples, start_hash=hash1, expected_key=EXPECTED_MOVIE_KEYS[0]
        )
        # Composited-freeze check: decode the frame-index patch off every dense
        # capture and confirm it keeps progressing across the MM cut, rather than
        # sticking on the newborn canvas's stale poster frame for 1-2 frames.
        index_samples = [
            {
                "index": f.get("index"),
                "sceneHash": f.get("sceneHash"),
                "captureOffsetS": f.get("captureOffsetS"),
            }
            for f in [*pre_frames_a, *frames_a]
        ]
        flip_index = next(
            (
                i
                for i, s in enumerate(index_samples)
                if s["sceneHash"] is not None and s["sceneHash"] != hash1
            ),
            None,
        )
        if flip_index is None:
            index_run = {"ok": False, "reason": "no scene-hash flip observed in dense window"}
        else:
            index_run = score_composited_index_run(index_samples, flip_index=flip_index)
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
                'reuse-decoder', 'createElement-video',
                'texture-feed-start', 'texture-feed-stop',
                // F1a: engagement events the fail-closed 1->2 gate keys off — a
                // texture-feed-draw / mo-prepaint-draw into an incoming canvas is
                // the ONLY positive proof the feed drew; the skip notes explain a
                // non-engagement so the gate fails for a named reason, not silently.
                'texture-feed-draw', 'texture-feed-skip', 'texture-feed-skip-canvas',
                'mo-prepaint-skip',
                'player-build-error', 'mo-prepaint-draw', 'mo-no-stage'
              ];
              const important = p.events.filter((e) => keep.indexOf(e.kind) >= 0);
              const remounts = p.events.filter((e) => e.kind === 'remount-done').slice(-20);
              const moNoTexids = p.events.filter((e) => e.kind === 'mo-no-texids').slice(-5);
              return important.concat(remounts).concat(moNoTexids);
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
        # Composed-ROI corroboration on slide 3. The burnt-in frame-index counter
        # (parity-immune) is the gating signal; pixel-MAE is kept as a diagnostic
        # only. The slide-2 grating aliases to a ~50/50 per-pair change under the
        # work-bound capture cadence, which made MAE-based motion a ~1/3 coin flip
        # (2->3 restart flake, Fable root-cause 2026-09-18); the counter marches
        # forward every presented frame regardless of grating phase.
        restart_pixel_motion = _score_visible_movie_motion(restart_paths, MOVIE_ROI)
        restart_index_seq = [
            _decode_index_patch(np.asarray(Image.open(p).convert("RGBA")), INDEX_PATCH_ROI_SLIDE3)
            for p in restart_paths
        ]
        restart_index_progression = score_index_progression(restart_index_seq)
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
            # presentedMotionOk: the TARGET decoder's own rVFC mediaTime progression
            # is mandatory (a frozen restart decoder must not pass just because some
            # OTHER movie/animation moves the shared ROI); on-screen progression is
            # required too as corroboration, via the parity-immune burnt-in index
            # counter (pixelMotion stays as a diagnostic only — see above).
            restart_decoder_id = per_movie_boundary[key].get("restartDecoderId")
            presented_rvfc = _presented_time_advances(samples_b, restart_decoder_id, SLIDE3_MIN_HASH)
            per_movie_boundary[key]["presentedMotionOk"] = bool(
                presented_rvfc.get("ok") and restart_index_progression.get("ok")
            )
            per_movie_boundary[key]["presentedMotionDetail"] = {
                "indexProgression": restart_index_progression,
                "pixelMotion": restart_pixel_motion,
                "rvfcAdvance": presented_rvfc,
            }
        # Tie the guard/retire evidence to the SPECIFIC decoder that earned the
        # restart score — a reuse-skip-boundary/retire for the target key that
        # happened to some OTHER decoder does not prove this decoder is genuine.
        target_restart_decoder_id = per_movie_boundary.get(target_key, {}).get("restartDecoderId")
        reuse_skip_boundary_matching_restart = [
            e
            for e in reuse_skip_boundary_for_target
            if (e.get("detail") or {}).get("newElId") == target_restart_decoder_id
        ]
        # Belt-and-suspenders on top of reuse_after_boundary's blanket ban: explicitly
        # forbid a reuse-decoder for the target key at/after the boundary that either
        # supplies the exact element we scored as the restart, or looks like a
        # near-zero decoder being handed off (not a genuine fresh createElement).
        reuse_decoder_events = [e for e in preserve_events if e.get("kind") == "reuse-decoder"]
        reuse_stitched_restart = [
            e
            for e in reuse_decoder_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
            and (_hash_num((e.get("detail") or {}).get("sceneHash")) or -1) >= SLIDE3_MIN_HASH
            and (
                (e.get("detail") or {}).get("newElId") == target_restart_decoder_id
                or abs(float((e.get("detail") or {}).get("preservedT") or 0.0)) < 0.35
            )
        ]
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

    player_build_errors = [e for e in preserve_events if e.get("kind") == "player-build-error"]

    # Fail-closed live-<video> continuity sub-verdict — a necessary condition for
    # the 1->2 finding under the corrected model. It proves the ONE footprint
    # decoder is stable across the cut, its rVFC presentedMediaTime advances, and
    # composited ROI motion crosses the flip. Absence of any sub-condition fails
    # the gate closed. samples_a carries the `videos` rVFC clocks.
    live_continuity = liveContinuity1to2(
        motion_across_flip, flip_samples, samples_a, hash1, hash2,
        restart_min_hash=SLIDE3_MIN_HASH,
    )

    findings = [
        {"id": "sourceUnchanged", "pass": after.as_dict() == before.as_dict()},
        {"id": "emptyCanvasPre", "pass": pre_scores["empty"]["ok"], "detail": pre_scores["empty"]},
        {"id": "blackSentinelOpaquePre", "pass": pre_scores["black"]["ok"], "detail": pre_scores["black"]},
        {"id": "greenTranslucentPre", "pass": pre_scores["green"]["ok"], "detail": pre_scores["green"]},
        {
            "id": "continueThroughMagicMove1to2",
            # Composited motion is proven by index_run (the burnt-in counter marching
            # forward — aliasing-immune). visible_motion (pixel-MAE) is NOT gated: it
            # aliases to a false "still" on the two-state grating (the same parity
            # aliasing index_run was built to defeat, and the reason motionAcrossFlip
            # was de-gated), so gating it re-introduced a flake on runs where the
            # decoder + counter + rVFC all advance. It is reported for provenance.
            # Remaining gated checks are all counter/clock/identity based (immune):
            # continuity clock, index_run, and liveContinuity (owner + rVFC + crossing).
            "pass": bool(
                cont.get("continuesThroughDissolve")
                and hash1 != hash2
                and index_run.get("ok", False)
                and live_continuity.get("ok", False)
                and not player_build_errors
            ),
            "status": "failed-by-player" if player_build_errors else None,
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
                "indexRun": index_run,
                "flipIndex": flip_index,
                "indexSequence": [s.get("index") for s in index_samples],
                "movieTexids": {
                    "decoderKey": texids_info.get("decoderKey"),
                    "boundary": texids_info.get("boundary"),
                    "outgoing": texids_info.get("outgoing"),
                    "incoming": texids_info.get("incoming"),
                },
                "movieTexidsWarning": texids_info.get("warning"),
                "liveContinuity1to2": live_continuity,
                "motionAcrossFlip": motion_across_flip,
                "decoderMotion": decoder_motion,
                "targetKey": EXPECTED_MOVIE_KEYS[0],
                "primaryTimes": primary_times_a,
                "minTimes": min_times_a,
                "captureRaceFramesN": capture_race_frames_a,
                "playerBuildErrors": player_build_errors,
                "reuseEvents": [
                    e for e in preserve_events if e.get("kind") == "reuse-decoder"
                ][:8],
                "note": (
                    "Pass gate is target-decoder continuity + visibleMovieMotion + "
                    "indexRun + liveContinuity1to2 (the fail-closed live-<video> sub-verdict: "
                    "a valid forward 1->2 boundary (num(hash2)>num(hash1)); one stable non-null "
                    "footprint decoderId across the after window [num(hash2), restart); the SAME "
                    "decoded footprint owner immediately before AND after the flip (crossing "
                    "identity — rejects a same-key handoff); AND that decoder's rVFC "
                    "presentedMediaTime advancing >0.05 in-window — absence of any sub-condition "
                    "fails the finding closed. motionAcrossFlip's pixel crossing-MAE is NOT "
                    "gated (it aliases on the grating); its crossing IDENTITY fields ARE. "
                    "The 1->2 movie is a live <video> at the footprint (not a fed 2D "
                    "canvas), so the old deck-texid/canvas-feed checks are dropped; the deck "
                    "crossfade texids are the 2->3 restart boundary, kept as provenance only. "
                    "indexRun means the composited frame-index patch keeps progressing across "
                    "the MM cut, i.e. the canvas is not stuck on the newborn poster frame. "
                    "motionAcrossFlip is kept as corroboration, not gating: it scores "
                    "ROI pixel motion, which the neutral scrolling grating provides even "
                    "while frozen on a single stale poster frame's own motion blur, so it "
                    "cannot by itself distinguish a live feed from a freeze. Any "
                    "player-build-error (an uncaught exception/rejection during the MM "
                    "rebuild, e.g. getTextureObject returning null) fails this finding "
                    "outright as failed-by-player, never masked as a pass. "
                    "Continuity is bound to the ONE footprint-owner decoder's own clock "
                    "(not max-of-same-key) — primary/min (max/min across ALL videos) are "
                    "informational only, since neither movie2 nor a fresh/pooled movie1 "
                    "instance may supply continuity for the bound decoder's handoff/stall."
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
            "pass": bool(
                mid_scores["blackAbove"]["ok"]
                and mid_scores["blackBehind"]["rgbMean"] > 40
                and not mid_scores["blackBehind"]["ok"]
                and mid_scores["greenFront"]["greenish"]
            ),
            "detail": {
                "blackAbove": mid_scores["blackAbove"],
                "blackBehind": mid_scores["blackBehind"],
                "greenFrontComposite": mid_scores["greenFrontComposite"],
                "greenFront": mid_scores["greenFront"],
                "blackAuto": mid_scores["black"],
            },
            "note": (
                "Authored z-order front->back: green square, larger movie, black sentinel, "
                "smaller movie. Verifies the composition against the LARGER movie: the black "
                "sentinel is opaque above the movie (blackAbove ok), is OCCLUDED by the movie "
                "where they overlap (blackBehind shows the movie, rgbMean>40, not opaque black), "
                "and the green square is IN FRONT (greenFront greenish). The disposable movie is a "
                "NEUTRAL grayscale grating (r==g==b), so greenish uniquely means the green square "
                "composites in front — it is NOT satisfiable by the movie's own colour (Codex's "
                "content-dependence concern). greenFrontComposite (composite vs decoder source) is "
                "kept as extra evidence but not gating, since a fast movie races the source sample. "
                "Green's translucency is proven separately by greenTranslucentPre on slide 1. A "
                "root-level overlay on top would fail blackBehind (black would show); green behind "
                "would fail greenFront (the neutral grating, not green, would show)."
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
                and target_restart_decoder_id is not None
                and len(reuse_skip_boundary_matching_restart) >= 1
                and len(retire_events_for_target) >= 1
                and len(reuse_after_boundary) == 0
                and len(reuse_stitched_restart) == 0
            ),
            "verdict": restart_verdict if restart_playback_ok or restart_inconclusive else "fail",
            "note": (
                "decoder-preserve must not stitch a deliberate Start Movie restart. "
                "Requires: no manual pool-cleared event at all, a reuse-skip-boundary "
                "whose newElId IS the decoder that earned deliberateRestart2to3 "
                "(not just any target-key event), a retire-on-start-movie for the "
                "target key, zero reuse-decoder events ON/AFTER the boundary "
                "(pre-boundary 1→2 reuse is the legitimate continue), and no "
                "reuse-decoder for the target key that supplies the same restart "
                "element or a near-zero-then-reset preservedT — the fresh restart "
                "element must be a genuine createElement, not a reused decoder."
            ),
            "detail": {
                "targetKey": target_key,
                "targetRestartDecoderId": target_restart_decoder_id,
                "poolCleared": clear_i is not None,
                "reuseSkipBoundaryForTargetN": len(reuse_skip_boundary_for_target),
                "reuseSkipBoundaryMatchingRestartN": len(reuse_skip_boundary_matching_restart),
                "retireEventsForTargetN": len(retire_events_for_target),
                "reuseAfterBoundary": reuse_after_boundary[:6],
                "reuseAfterBoundaryScenes": [
                    (e.get("detail") or {}).get("sceneHash") for e in reuse_after_boundary[:6]
                ],
                "reuseStitchedRestart": reuse_stitched_restart[:6],
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
