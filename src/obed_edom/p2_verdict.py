"""Pure gate-verdict logic for the P2 HTML adversarial gate.

Moved verbatim from `scripts/p2_recovery_html_adversarial.py` (the driver
boundary -- Chrome/CDP and injected JS -- stays in the script). The one
intentional behaviour change from the move: `_score_visible_movie_motion`'s
caller-side `if patch.size == 0: continue` filter is dropped, so its
documented "empty crop" fail-closed branch is reachable again.
"""
from __future__ import annotations

import base64
import copy
import functools
import hashlib
import io
import json
import math
import time
import uuid
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from obed_edom.html_alpha_probe import (
    DEAD_RECT_MAX_LIVE_FRAC,
    LIVE_BAND_COLS,
    LIVE_BAND_MIN_FRAC,
    LIVE_BAND_ROWS,
    LIVE_DELTA_MIN,
    LIVE_RECT_INSET_PX,
    LIVE_RECT_MIN_FRAC,
    NOISE_FLOOR_P99_MAX,
    STRAY_DILATE_PX,
    STRAY_MIN_AREA_PX,
    _max_delta_map,
    score_composited_index_run,
    score_index_progression,
    score_visible_movie_motion,
    score_visible_slide_from_delta,
)

MOVIE1_TOKEN = "Untitled.mov"
MOVIE2_TOKEN = "WA0125"


def _movie_key(src: str) -> str:
    s = str(src or "").lower()
    if MOVIE1_TOKEN.lower() in s:
        return "movie1"
    if MOVIE2_TOKEN.lower() in s:
        return "movie2"
    # fallback: basename stem
    return s.rsplit("/", 1)[-1][:40] or "unknown"


def _norm_hash(h: str | None) -> str:
    s = str(h or "")
    if "?" in s:
        s = s.split("?", 1)[0]
    # keep only leading #digits
    import re

    m = re.match(r"(#\d+)", s)
    return m.group(1) if m else s


# 12 shots at >=360 ms gaps, alternating 360/370 (paint-oracle plan SS14; research
# doc "Paint-oracle E0"): keeps the 12-shot aliasing bound (2*0.5**12 ~ 0.05%)
# and fixes the WebGL stale-surface misread the earlier, tighter burst can hit.
BURST_OFFSETS_MS = (0, 360, 730, 1090, 1460, 1820, 2190, 2550, 2920, 3280, 3650, 4010)
CONTROL_PATCH_PX = 40
CONTROL_INSET_PX = 4

TRANS_S = 1.5

# Owner-authored z-order (front->back): green square -> larger movie -> black square
# -> smaller movie. So relative to the LARGER movie the green square is IN FRONT and
# the black sentinel is BEHIND. Black sentinel canvas ~[542,721,181,161], larger movie
# ~[105,791,960,276], green square ~[789,673,353,313] (measured on the exported deck).
# The script's one "this ROI is opaque black" level: `_score_black` calls a patch
# black at rgbMean <= this, and blackBehind calls the movie visible above it.
BLACK_RGB_MEAN_MAX = 40.0

EMPTY_CORNERS = ((1864, 8, 48, 48), (1864, 1024, 48, 48))  # right side stays emptier after MM
# Large continuing movie footprint on slide 1 (inventory). Center is unobscured.
MOVIE_ROI = (109, 795, 952, 268)

# HTML event index where slide 2 begins (the 1→2 Magic Move destination, whose
# carry the derived plan REFUSES: slide 2 draws the green square over the movie).
SLIDE2_MIN_HASH = 2
# The player holds `#1` for the WHOLE 1->2 Magic Move and only flips to `#2`
# after the move, yet it detaches the slide-1 videos at `#1` — so the retire zone
# starts one scene early (same convention as the bridge's move scene) and a
# remount during the transition is exactly the defect this gate must catch.
RETIRE_ZONE_MIN_HASH = SLIDE2_MIN_HASH - 1
# HTML event index where slide 3 begins (2 + 4 events before it → scene #6).
SLIDE3_MIN_HASH = 6
# ---- 3->4 moving Magic Move constants (positive control; measured Phase 0) ----
# Slide 4's first scene (the 3->4 magic-move destination). Scene map:
# s1=#1, s2≈#2-5, s3=#6-7, 3->4 MM lands slide 4 at #8, settles #8/#9.
SLIDE4_MIN_HASH = 8

SLIDE4_MOVIE_RECT = (327, 709, 1266, 356)
# Noise-floor control patch for the settled-slide-4 visible-content burst: a
# CONTROL_PATCH_PX square inset into the first empty corner, sized/inset by the
# probe's own constants so both instruments read the same floor.
SLIDE4_CONTROL_RECT = {
    "x": EMPTY_CORNERS[0][0] + CONTROL_INSET_PX,
    "y": EMPTY_CORNERS[0][1] + CONTROL_INSET_PX,
    "w": CONTROL_PATCH_PX,
    "h": CONTROL_PATCH_PX,
}
# PRESERVE assetKey for untitled.mov (movie1) — used to key the 3->4 footprint
# owner query so the retiring right-side WA0125 the grown box overlaps is excluded.
MOVIE1_KEY = "movie1"
# Fixed expected movie keys for restart evidence (not derived from observations).
# untitled.mov (movie1, Shibuya crossing) is the restart target; after the
# case-insensitive _movie_key fix, both its DOM src and pooled assetKey
# observations collapse under "movie1".
EXPECTED_MOVIE_KEYS = ("movie1",)
BRIDGE_EVENT_KIND = "bridge-3to4"

# Preserve notes that mean a movie was actually carried (pooled decoder reused,
# placed or swapped back in) — the notes a retire zone must never produce.
# Event kinds the P2 script fetches from the page (every other kind is dropped before
# the verdicts see it): the refusal notes, the pool-consuming and engagement notes the
# 1->2 gates key off, and the glReplay zone/live notes `refusedCarry1to2` reads.
PRESERVE_EVENT_KEEP_KINDS = (
    "createElement-video",
    "dom-swap",
    "facade-block-clear",
    "glreplay-live",
    "glreplay-zone",
    "mo-no-stage",
    "mo-prepaint-draw",
    "mo-prepaint-skip",
    "player-build-error",
    "pool-cleared",
    "preserve-refused",
    "remount-error",
    "retire-boundary",
    "retire-on-start-movie",
    "reuse-decoder",
    "reuse-skip-boundary",
    "texture-feed-draw",
    "texture-feed-skip",
    "texture-feed-skip-canvas",
    "texture-feed-start",
    "texture-feed-stop",
)

# Added to the fetch filter under `--gl-replay auto` only: the zone, seam and module
# notes `glReplayCarry1to2` reads.
GL_REPLAY_KEEP_KINDS = (
    "glreplay-arm",
    "glreplay-carried",
    "glreplay-handoff",
    "glreplay-hold",
    "glreplay-live",
    "glreplay-opacity-unproven",
    "glreplay-release",
    "glreplay-retained-frame",
    "glreplay-standdown",
    "glreplay-zone",
)

CARRY_EVENT_KINDS = frozenset({
    "remount-scheduled",
    "remount-done",
    "remount-authored-parent",
    "remount-into-authored-layer",
    "remount-footprint-rect",
    "reuse-decoder",
    "dom-swap",
    "facade-block-clear",
})

# --- Phase 2: composited-freeze negative control (Arm A) thresholds ---------- #
# The freeze control proves the COUNTER gate (`score_composited_index_run`) is not
# vacuous: it injects a persistent VISIBLE stale cover over the burnt-in counter so
# `index_run` goes RED ("freeze run at cut") while the live-<video> decoder + rVFC
# stay green. A strong margin (not just >max_freeze_run==2) is required so the RED is
# unmistakably the injected freeze, not coarse-capture jitter.
FREEZE_MIN_RUN = 6            # freezeRunAtCut must reach this (margin over the gate's 2)
FREEZE_MIN_AFTER = 6         # samples after the flip (n - flip_index) needed to form the run
RVFC_MIN_ADVANCE_S = 0.5    # the decoder must run >=0.5s through the hold (0.05 is too weak)
MAX_RAF_GAP_MS = 100.0      # a per-rAF hold-log gap beyond this => INCONCLUSIVE, not a verdict
STALE_INDEX_TOL = 2         # +/- yuv rounding on the decoded frozen counter
COVER_MATCH_TOL = 6.0       # frozen decode mean must match the cover's painted patch mean
MIN_STALE_TIME_S = 0.3      # the stale frame must be from genuine playback (not a t=0 unrendered black)

COVER_LEFT_FRAC = 0.4       # mirrors NULL_CONTROL_JS's LEFT_FRAC (subRect) -- keep in sync
COVER_TRACK_TOL_PX = 0.5    # cover rect vs measured*COVER_LEFT_FRAC; tight enough that a
                            # ONE-FRAME lag cannot hide in it (plan §10)
STAGE_ORIGIN_TOL_PX = 0.5   # stageOrigin must read (0,0) at arm (plan §2, cover geometry)
# --- Admissible ABSENCE in the scored series (plan §10.17, §10.19) ----------- #
# A `None` counter read and a null footprint owner are real readings, but both
# DELETE the interval across them from what the scorers total, so they are
# bounded in COUNT, RUN and POSITION, not merely tolerated. Derivations and the
# measured distributions behind each value: plan §10.17 and §10.19.
INDEX_PATCH_MODULO = 256    # the burnt-in counter's wrap, as both index scorers read it
SCORED_NULL_MAX_RUN = 1     # consecutive `None` counter reads
AT_CUT_MAX_NULLS = 1        # `None` reads in an at-cut scored segment, position 0 only
SETTLED_MAX_NULLS = 0       # `None` reads in a settled window
NULL_BRIDGE_MAX_STEP = 30   # plausible forward counter step ACROSS one missed read
OWNER_NULL_MAX_RUN = 5      # consecutive null footprint owners INSIDE the after-window

FOOTPRINT_COUPLE_TOL_PX = 1.5  # before/after owner-rect agreement for a screenshot to count
                                # "measured" rather than "unstable" (review Blocker 2b)
# Trigger bounds, all three calibrated in plan §10 and all tracking the harness's
# per-frame cost, not the player alone -- re-measure when the capture loop changes.
FREEZE_TRIGGER_MAX_RAFS = 9        # delivered poll frames, keydown -> rect departure
FREEZE_TRIGGER_MAX_DELAY_MS = 190.0  # page-clock ceiling: a frame count cannot see a stall
FREEZE_TRIGGER_MOTION_SLACK_FRAMES = 2  # poll callbacks between the runtime's fresh
                                        # motion marker and the measured departure

# Drain to the freeze-control arm boundary (`_capture_3to4_snapshot`). MEASURED on
# this fixture 2026-09-21: the drain needs presses from #1..#5 only. `#6` is the
# 2->3 dissolve IN FLIGHT and the player SELF-ADVANCES #6 -> #7 (settled slide 3)
# with no key press. A press sent at #6 cannot be honoured, is QUEUED by the player
# and replayed on arrival at #7 -- which starts the real 3->4 move immediately "on
# arrival" and reds `noPreAdvanceDeparture`. So: press only while the hash is BELOW
# the self-advancing scene, then WAIT for the self-advance.
DRAIN_SELF_ADVANCE_HASH = SLIDE4_MIN_HASH - 2  # == #6, the self-advancing dissolve
DRAIN_PRESS_LAND_S = 10.0   # per-press landing wait. Measured: at 2.0 s presses went
                            # UNLANDED at #1 and #5 on several boots (an unlanded press
                            # is queued and replayed later -- the same defect); at 10.0 s
                            # with a `Page.captureScreenshot` per poll iteration every
                            # press landed exactly once.


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
    (`_derive_movie_texids`) resolves the single footprint motion-path Magic Move
    `contents` crossfade (a poster swap on the 1->2 or 3->4 motion-path MM — NOT
    the 2->3 boundary, which is an `apple:dissolve`, not a Magic Move) from these
    per-slide pieces and preserves each occurrence's provenance.
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

    CORRECTED MODEL (2026-09-19): Keynote stores a transition under its OUTGOING
    slide (a transition authored on slide N applies N->N+1). The deck's footprint
    Magic Moves are the motion-path MMs at 1->2 and 3->4; the 2->3 boundary is an
    `apple:dissolve` (a movie RESTART, NOT a Magic Move) and owns no `contents`
    poster crossfade. So the single footprint magic-move `contents` poster swap
    this resolves is a MOTION-PATH Magic Move (1->2 or 3->4) — tagged
    `"boundary": "motion-path-mm"`, NOT the earlier (wrong) "2to3". It is
    provenance-only: no gate consumes it. The 1->2 movie is a live `<video>`
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
        "boundary": "motion-path-mm",
        "outgoing": [frm],
        "incoming": [to],
        "boundaryCrossfade": {"from": frm, "to": to},
        "boundaryOccurrences": [{"slide": o["slide"], "owner": o["owner"]} for o in occs],
        "scannedSlideUuids": scanned,
        "slideList": slide_list,
    }


GL_REPLAY_BOUNDARY_1TO2 = {
    "atScene": SLIDE2_MIN_HASH, "action": "glReplay", "movieKey": MOVIE1_KEY, "fallback": "retire",
    "slotSizes": [[1920, 1080], [671, 195], [266, 236], [960, 276], [178, 157]],
    "slotRects": [
        [0.0, 0.0, 1920.0, 1080.0],
        [1071.6833801269531, 871.9523239135742, 671.0, 195.0],
        [541.858301475681, 721.0772309801108, 181.0, 161.0],
        [105.1231918334961, 790.846923828125, 960.0, 276.0],
        [788.725538103768, 672.9158876261134, 353.0, 313.0],
    ],
    "opacityOverrides": [{"slot": 4, "opacity": 0.29468628764152527, "texW": 178, "texH": 157}],
    "instanceId": "untitled.mov#1",
    "instanceRect": {
        "x": 109.3517074584961, "y": 795.0361938476562,
        "w": 951.54296875, "h": 267.6214599609375,
    },
    "movieSlot": 3,
}


def build_continuity_plan(bridge34: bool) -> dict:
    """The runtime plan injected into the player — equal to
    `derive_plan(..., gl_replay=True).to_runtime()` for this fixture, plus the
    transparent background the P2 export needs. P2 loads no GL module, so the
    `glReplay` 1->2 boundary takes its `retire` fallback in the page.

    `movies` names movie1 ONLY: naming the slide-3-only WA0125 clip admits it to
    the runtime's `stash()` plan-name filter, which pools it at the 3->4 detach
    and remounts it at the fallback footprint (the stray 62e1ab7 fixed for the
    product by not naming it). `MOVIE2_ROI` stays a probe-side constant.

    `bridge34=False` removes the 3->4 bridge ONLY; the 1->2 glReplay and the 2->3
    restart stay, so `--disable-bridge34` turns exactly one finding red.
    """
    plan: dict = {
        "movies": {
            "movie1": {
                "assetKeys": [MOVIE1_TOKEN.lower()],
                "footprint": dict(zip(("x", "y", "w", "h"), MOVIE_ROI)),
            },
        },
        "boundaries": [
            copy.deepcopy(GL_REPLAY_BOUNDARY_1TO2),
            {"atScene": SLIDE3_MIN_HASH, "action": "restart"},
        ],
        "transparentBackground": True,
    }
    if bridge34:
        plan["boundaries"].append({
            "atScene": SLIDE4_MIN_HASH,
            "action": "bridge",
            "movieKey": MOVIE1_KEY,
            "srcRect": {"x": 198, "y": 797, "w": 952, "h": 268},
            "durationSeconds": TRANS_S,
            "rect": dict(zip(("x", "y", "w", "h"), SLIDE4_MOVIE_RECT)),
        })
    return plan


def _event_scene(event: dict) -> int | None:
    detail = event.get("detail")
    if not isinstance(detail, dict):
        return None
    for key in ("scene", "atScene", "hashNum"):
        value = detail.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return _hash_num(detail.get("sceneHash"))


def _target_elids(events: list[dict], target_key: str) -> set:
    """Element ids the runtime has ever attributed to `target_key`."""
    ids: set = set()
    for e in events:
        detail = e.get("detail")
        if not isinstance(detail, dict):
            continue
        if _movie_key(detail.get("key") or "") != target_key:
            continue
        for field in ("elId", "newElId"):
            if detail.get(field) is not None:
                ids.add(detail[field])
        for el in detail.get("elIds") or []:
            ids.add(el)
    return ids


def refusalEvents(events: list[dict], target_key: str, min_scene: int) -> list[dict]:
    """`preserve-refused` / `retire-boundary` notes for `target_key` at/after `min_scene`."""
    out = []
    for e in events:
        if e.get("kind") not in ("preserve-refused", "retire-boundary"):
            continue
        detail = e.get("detail") if isinstance(e.get("detail"), dict) else {}
        if _movie_key(detail.get("key") or "") != target_key:
            continue
        scene = _event_scene(e)
        if scene is None or scene < min_scene:
            continue
        out.append(e)
    return out


def carryEvents(events: list[dict], target_key: str, lo_scene: int, hi_scene: int) -> list[dict]:
    """Preservation notes that would mean the movie WAS carried in `[lo, hi)`.

    Only notes that mean a carry actually happened — `remount-suppressed`,
    `remount-stale`, `remount-no-stage` and the `*-error` notes all mean the
    opposite and must not turn the refusal red.
    """
    el_ids = _target_elids(events, target_key)
    out = []
    for e in events:
        kind = str(e.get("kind") or "")
        if kind not in CARRY_EVENT_KINDS:
            continue
        detail = e.get("detail") if isinstance(e.get("detail"), dict) else {}
        keyed = _movie_key(detail.get("key") or "") == target_key
        el_match = any(detail.get(f) in el_ids for f in ("elId", "newElId") if detail.get(f) is not None)
        if not (keyed or el_match):
            continue
        scene = _event_scene(e)
        if scene is None or not (lo_scene <= scene < hi_scene):
            continue
        out.append(e)
    return out


def carryCensusVerdict(
    census: object, events: list[dict], target_key: str, lo_scene: int, hi_scene: int
) -> dict:
    """Clause (c)'s count. The in-page census is authoritative (`total` is taken
    before any slicing); the fetched notes are a belt. A missing or malformed
    census fails closed — absence cannot be proven from a bounded sample."""
    local = carryEvents(events, target_key, lo_scene, hi_scene)
    if not isinstance(census, dict) or not isinstance(census.get("total"), int):
        return {
            "ok": False,
            "total": None,
            "reason": "carry census missing or malformed",
            "census": census,
            "localMatches": local[:6],
            "localMatchesN": len(local),
        }
    total = int(census["total"])
    return {
        "ok": total == 0 and not local,
        "total": total,
        "reason": None if (total == 0 and not local) else "carry notes inside the retire zone",
        "census": {k: v for k, v in census.items() if k != "sample"},
        "sample": (census.get("sample") or [])[:6],
        "localMatches": local[:6],
        "localMatchesN": len(local),
    }


def poolCensusVerdict(
    census: object, target_key: str, lo_scene: int, hi_scene: int
) -> dict:
    """The real pool on settled slide 2: zero pooled AND zero `fromDom`
    preserved entries for the target's asset. A census that is missing,
    malformed or taken outside the retire zone is NOT evidence.

    Entries are attributed by the stamped `movieKey` first, then by `key`. A
    preserved decoder whose src was really cleared reports an EMPTY key, so an
    entry with neither is unattributable and invalidates the whole census — a
    non-empty key that maps to no plan movie is provably another asset and is
    tolerated."""
    if not isinstance(census, dict) or not isinstance(census.get("entries"), list):
        return {"ok": False, "reason": "pool census missing or malformed", "census": census}
    scene = _hash_num(census.get("sceneHash"))
    if scene is None or not (lo_scene <= scene < hi_scene):
        return {
            "ok": False,
            "reason": "pool census taken outside the retire zone",
            "sceneHash": census.get("sceneHash"),
        }
    mine = []
    unattributable = []
    for e in census["entries"]:
        if not isinstance(e, dict):
            unattributable.append(e)
            continue
        stamped = e.get("movieKey")
        raw = str(e.get("key") or "")
        if isinstance(stamped, str) and stamped:
            attributed = _movie_key(stamped)
        elif raw:
            attributed = _movie_key(raw)
        else:
            unattributable.append(e)
            continue
        if attributed == target_key:
            mine.append(e)
    if unattributable:
        return {
            "ok": False,
            "reason": "pool census holds an unattributable entry",
            "sceneHash": census.get("sceneHash"),
            "entriesN": len(census["entries"]),
            "unattributable": unattributable[:6],
            "unattributableN": len(unattributable),
        }
    return {
        "ok": not mine,
        "reason": None if not mine else "the target movie is still pooled on slide 2",
        "sceneHash": census.get("sceneHash"),
        "entriesN": len(census["entries"]),
        "entriesForTarget": mine[:6],
        "entriesForTargetN": len(mine),
        "fromDomForTargetN": sum(1 for e in mine if e.get("fromDom")),
    }


def frozenCompositeAfterFlip(
    motion_across_flip: object,
    flip_rois: object = None,
    settled_roi: object = None,
    *,
    min_after_pairs: int = 4,
    min_rgb_mean: float = BLACK_RGB_MEAN_MAX,
) -> dict:
    """Clause (e): the movie ROI must be PIXEL-FROZEN for the whole post-flip
    window and have been LIVE before it — the raw export's own behaviour once
    the carry is refused (a carried movie shows after-pair MAE >> eps).

    Stillness alone is not enough: an ROI that went dead/all-black after the cut
    and recovered later is also "still". The post-flip frames must therefore also
    be CONTENT-VALID — not blank (rgbMean above the script's own opaque-black
    level) and equal, within the same `pairEps`, to the composite the slide-2
    settle point actually rests on.

    The burnt-in counter cannot serve here: on the refused slide the patch ROI
    shows the export's poster photo, so it never decodes. Fails closed when the
    scored window, the post-flip ROIs or the settled ROI are absent, short or
    malformed.
    """
    m = motion_across_flip if isinstance(motion_across_flip, dict) else {}
    after = m.get("afterPairMae")
    eps = m.get("pairEps")
    if not isinstance(after, list) or not isinstance(eps, (int, float)):
        return {"frozen": False, "reason": "no scored flip window", "n": 0}
    if any(not isinstance(v, (int, float)) for v in after):
        return {"frozen": False, "reason": "non-numeric pair mae", "n": len(after)}
    if len(after) < min_after_pairs:
        return {
            "frozen": False,
            "reason": "insufficient after-pairs to judge a freeze",
            "n": len(after),
            "afterPairMae": after,
        }
    still = all(float(v) <= float(eps) for v in after)
    live_before = bool(m.get("beforeOk"))
    flip_index = m.get("flipIndex")
    rois = list(flip_rois or [])
    content = {"ok": False, "reason": "no post-flip ROI frames"}
    if isinstance(flip_index, int) and 0 <= flip_index < len(rois) and settled_roi is not None:
        after_rois = rois[flip_index:]
        means = [float(np.asarray(r)[..., :3].mean()) for r in after_rois]
        settled_maes = [_mae_rgb(np.asarray(r), np.asarray(settled_roi)) for r in after_rois]
        blank = [v for v in means if v <= float(min_rgb_mean)]
        off = [v for v in settled_maes if v > float(eps)]
        content = {
            "ok": bool(after_rois and not blank and not off),
            "reason": (
                "post-flip ROI is blank/black" if blank
                else "post-flip ROI does not match the settled slide-2 composite" if off
                else None
            ),
            "n": len(after_rois),
            "rgbMeans": means,
            "settledMae": settled_maes,
            "minRgbMean": float(min_rgb_mean),
        }
    elif settled_roi is None:
        content = {"ok": False, "reason": "no settled slide-2 ROI"}
    reason = None
    if not still:
        reason = "composite kept moving on the refused slide"
    elif not live_before:
        reason = "no motion before the flip — the instrument is blind"
    elif not content["ok"]:
        reason = content["reason"]
    return {
        "frozen": bool(still and live_before and content["ok"]),
        "reason": reason,
        "content": content,
        "n": len(after),
        "afterPairMae": after,
        "beforePairMae": m.get("beforePairMae"),
        "pairEps": eps,
        "liveBeforeFlip": live_before,
        "flipIndex": m.get("flipIndex"),
    }


def frozenIndexAfterFlip(
    index_samples: list[dict], flip_index: int | None, *, min_samples: int = 4
) -> dict:
    """The composited counter must NOT advance after the 1->2 flip (the raw
    export's own behaviour once the carry is refused). Fails closed when the
    patch is not decodable often enough to judge."""
    if flip_index is None:
        return {"frozen": False, "reason": "no scene-hash flip observed", "n": 0}
    decoded = [
        s.get("index")
        for s in index_samples[flip_index:]
        if s.get("index") is not None
    ]
    if len(decoded) < min_samples:
        return {
            "frozen": False,
            "reason": "insufficient decodable samples after the flip",
            "n": len(decoded),
            "indices": decoded,
        }
    frozen = len(set(decoded)) == 1
    return {
        "frozen": frozen,
        "reason": None if frozen else "counter advanced on the refused slide",
        "n": len(decoded),
        "indices": decoded,
        "distinct": sorted(set(decoded)),
    }


def refusedCarry1to2(
    injected_plan: dict,
    preserve_events: list[dict],
    lingering: dict,
    motion_across_flip: object,
    flip_rois: object,
    settled_slide2_roi: object,
    index_samples: list[dict],
    flip_index: int | None,
    hash1: object,
    hash2: object,
    player_build_errors: list,
    carry_census: object = None,
    *,
    target_key: str = MOVIE1_KEY,
    retire_scene: int = SLIDE2_MIN_HASH,
    zone_scene: int = RETIRE_ZONE_MIN_HASH,
    restart_scene: int = SLIDE3_MIN_HASH,
    expected_gl_fallback: str = "moduleAbsent",
) -> dict:
    """Fail-CLOSED verdict that the 1->2 carry was REFUSED and slide 2 therefore
    looks exactly like the raw export (plan §4).

    All of: (a) the injected plan retires `target_key` at `retire_scene`, as a
    literal `retire` or a `glReplay` with `fallback == "retire"` — the latter must
    also show exactly one `glreplay-zone` note to `retired`, with reason
    `expected_gl_fallback`, none to `armed`/`released` and no `glreplay-live`;
    (b) a positive refusal event at scene >= `zone_scene` (the runtime declines
    to preserve during the transition scene, which the player still hashes as
    `retire_scene - 1`); (c) zero carry notes for that movie anywhere in the
    retire zone `[zone_scene, restart_scene)`, the transition scene included;
    (d) no lingering preserved/remounted overlay and nothing painting over the
    slide-1/2 footprints on settled slide 2; (e) the composite in the movie ROI
    pixel-FROZEN across the post-flip window (live before it) with a real 1->2
    hash change; (f) no player build error.
    """
    boundaries = (injected_plan or {}).get("boundaries") or []
    plan_retire = next(
        (
            b
            for b in boundaries
            if (
                b.get("action") == "retire"
                or (b.get("action") == "glReplay" and b.get("fallback") == "retire")
            )
            and b.get("atScene") == retire_scene
            and b.get("movieKey") == target_key
        ),
        None,
    )
    gl_replay = bool(plan_retire and plan_retire.get("action") == "glReplay")
    zone_notes = _gl_zone_notes(preserve_events)
    zone_retired = [d.get("reason") for d in zone_notes if d.get("to") == "retired"]
    zone_clean = bool(zone_retired) and not _gl_zone_armed(zone_notes)
    fallback_expected = zone_retired == [expected_gl_fallback]
    zone_fell_back = zone_clean and fallback_expected
    went_live = any(e.get("kind") == "glreplay-live" for e in preserve_events)
    gl_replay_ok = not gl_replay or (zone_fell_back and not went_live)
    refusals = refusalEvents(preserve_events, target_key, zone_scene)
    carried = carryCensusVerdict(
        carry_census, preserve_events, target_key, zone_scene, restart_scene
    )
    lingering = lingering or {}
    no_lingering = bool(
        lingering.get("count", 1) == 0
        and lingering.get("preservedCount", 1) == 0
        and lingering.get("paintingCount", 1) == 0
    )
    frozen = frozenCompositeAfterFlip(motion_across_flip, flip_rois, settled_slide2_roi)
    index_diagnostic = frozenIndexAfterFlip(index_samples, flip_index)
    from_n = _strict_hash_num(hash1)
    to_n = _strict_hash_num(hash2)
    hash_changed = bool(
        from_n is not None and to_n is not None and to_n > from_n and to_n >= retire_scene
    )
    ok = bool(
        plan_retire
        and gl_replay_ok
        and refusals
        and carried["ok"]
        and no_lingering
        and frozen["frozen"]
        and hash_changed
        and not player_build_errors
    )
    reasons = []
    if not plan_retire:
        reasons.append("injected plan has no retire boundary for the target key")
    if gl_replay and not zone_clean:
        reasons.append("glReplay zone never fell back to retire")
    if gl_replay and zone_retired and not fallback_expected:
        reasons.append(f"glReplay fell back for {zone_retired!r}, expected [{expected_gl_fallback!r}]")
    if gl_replay and went_live:
        reasons.append("glReplay went live")
    if not refusals:
        reasons.append("no preserve-refused/retire-boundary event in the retire zone")
    if not carried["ok"]:
        reasons.append(carried["reason"] or "the movie was carried inside the retire zone")
    if not no_lingering:
        reasons.append("a preserved/remounted/painting <video> lingers on slide 2")
    if not frozen["frozen"]:
        reasons.append(frozen.get("reason") or "composite not frozen")
    if not hash_changed:
        reasons.append("no valid forward 1->2 boundary")
    if player_build_errors:
        reasons.append("player build error")
    return {
        "ok": ok,
        "planRetire": plan_retire,
        "glReplayFallback": zone_retired[0] if gl_replay and zone_retired else None,
        "refusalEvents": refusals[:6],
        "refusalEventsN": len(refusals),
        "carryInRetireZone": carried,
        "carryEventsInRetireZoneN": carried["total"],
        "lingering": lingering,
        "frozenComposite": frozen,
        "frozenIndexNonGating": index_diagnostic,
        "hash": f"{hash1}->{hash2}",
        "hashChanged": hash_changed,
        "playerBuildErrors": player_build_errors,
        "reasons": reasons,
    }


def _gl_zone_notes(preserve_events: list[dict]) -> list[dict]:
    return [
        e["detail"]
        for e in preserve_events
        if e.get("kind") == "glreplay-zone" and isinstance(e.get("detail"), dict)
    ]


def _gl_zone_armed(zone_notes: list[dict]) -> bool:
    return any(d.get("to") in ("armed", "released") for d in zone_notes)


def neverPooledEvidence(
    preserve_events: list[dict],
    carry_census: object = None,
    pool_census: object = None,
    *,
    target_key: str = MOVIE1_KEY,
    zone_scene: int = RETIRE_ZONE_MIN_HASH,
    restart_scene: int = SLIDE3_MIN_HASH,
) -> dict:
    """"Nothing was ever pooled" — the stronger substitute for the
    reuse-skip/retire pair once the target key is retired before the restart.

    Requires a positive refusal note, zero carry notes in the retire zone, AND a
    well-formed pool census taken on settled slide 2 that holds no pooled or
    `fromDom` preserved entry for the key — a detached decoder can sit in the
    pool through slide 2 without ever being reused, so silence is not evidence.
    An invalid census invalidates the route (the original positive pair is then
    required). A glReplay zone that ever armed or released pooled the carried
    decoder, so it also fails the route.
    """
    refusals = refusalEvents(preserve_events, target_key, zone_scene)
    carried = carryCensusVerdict(
        carry_census, preserve_events, target_key, zone_scene, restart_scene
    )
    pooled = poolCensusVerdict(pool_census, target_key, zone_scene, restart_scene)
    gl_armed = _gl_zone_armed(_gl_zone_notes(preserve_events))
    return {
        "ok": bool(refusals and carried["ok"] and pooled["ok"] and not gl_armed),
        "refusalEventsN": len(refusals),
        "glReplayArmed": gl_armed,
        "carryInRetireZone": carried,
        "carryEventsInRetireZoneN": carried["total"],
        "poolCensus": pooled,
    }


GL_CARRIED_MAX_DELTA = 0.02
GL_POOL_MIN_READS = 3
GL_POOL_MIN_GAP_MS = 300.0
GL_CLOCK_RATE_MIN = 0.75
GL_CLOCK_RATE_MAX = 1.25
GL_INDEX_MAX_STEP = 64
GL_INDEX_MIN_AFTER_FLIP = 4
GL_SAMPLE_FRAME_MIN_READS = 3
GL_HANDOFF_STAND_DOWN = "canvasRemoved"


def _same_id(a: object, b: object) -> bool:
    return a is not None and b is not None and str(a) == str(b)


def _id_set(values: object) -> set[str] | None:
    if not isinstance(values, list) or any(v is None for v in values):
        return None
    return {str(v) for v in values}


def _kind_details(preserve_events: list[dict], kind: str) -> list[dict]:
    return [
        e["detail"]
        for e in preserve_events
        if e.get("kind") == kind and isinstance(e.get("detail"), dict)
    ]


def _entry_movie_key(entry: dict) -> str | None:
    stamped = entry.get("movieKey")
    if isinstance(stamped, str) and stamped:
        return _movie_key(stamped)
    raw = str(entry.get("key") or "")
    return _movie_key(raw) if raw else None


def _index_series_progress(values: list, *, min_decoded: int, max_step: int = GL_INDEX_MAX_STEP) -> dict:
    decoded = [int(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    deltas = [(b - a) % INDEX_PATCH_MODULO for a, b in zip(decoded, decoded[1:])]
    base = {"nDecoded": len(decoded), "nNull": len(values) - len(decoded), "indices": decoded, "deltas": deltas}
    if len(decoded) < min_decoded:
        return {"ok": False, "reason": "insufficient decoded reads", **base}
    if any(d >= max_step for d in deltas):
        return {"ok": False, "reason": "implausible counter step", **base}
    if sum(deltas) <= 0:
        return {"ok": False, "reason": "counter never advanced", **base}
    return {"ok": True, "reason": None, **base}


def progressingIndexAfterFlip(
    index_samples: list[dict],
    flip_index: int | None,
    sample_frame_indices: list,
    *,
    min_after: int = GL_INDEX_MIN_AFTER_FLIP,
    min_sample_frames: int = GL_SAMPLE_FRAME_MIN_READS,
) -> dict:
    """Clause (f) (plan §4.2 f): composite and `sampleFrame` counters advance after the flip."""
    if not isinstance(flip_index, int) or not isinstance(index_samples, list) or not 0 <= flip_index <= len(index_samples):
        composite = {"ok": False, "reason": "no scene-hash flip observed", "nDecoded": 0}
    else:
        composite = _index_series_progress(
            [s.get("index") if isinstance(s, dict) else None for s in index_samples[flip_index:]],
            min_decoded=min_after,
        )
    source = _index_series_progress(list(sample_frame_indices or []), min_decoded=min_sample_frames)
    return {
        "ok": bool(composite["ok"] and source["ok"]),
        "composite": composite,
        "sourceSampleFrame": source,
        "agreementNonGating": {
            "compositeForward": sum(composite.get("deltas") or []),
            "sourceForward": sum(source.get("deltas") or []),
        },
    }


def glPoolReadsVerdict(
    pool_reads: object,
    carried_el_id: object,
    *,
    target_key: str = MOVIE1_KEY,
    lo_scene: int = SLIDE2_MIN_HASH,
    hi_scene: int = SLIDE2_MIN_HASH + 1,
    min_reads: int = GL_POOL_MIN_READS,
    min_gap_ms: float = GL_POOL_MIN_GAP_MS,
) -> dict:
    """Clause (d) (plan §4.2 d): every slide-2 pool read holds movie1 as {carried} ∪ detached siblings."""
    reads = pool_reads if isinstance(pool_reads, list) else []
    problems: list[str] = []
    pooled: set[str] = set()
    per_read = []
    if carried_el_id is None:
        problems.append("no carried decoder")
    if len(reads) < min_reads:
        problems.append(f"{len(reads)} pool reads, need {min_reads}")
    last_t = None
    for i, r in enumerate(reads):
        if not isinstance(r, dict) or not isinstance(r.get("pool"), list):
            problems.append(f"read {i} malformed")
            continue
        scene = _strict_hash_num(r.get("sceneHash"))
        if scene is None or not lo_scene <= scene < hi_scene:
            problems.append(f"read {i} outside [{lo_scene},{hi_scene})")
        t = _finite(r.get("t"))
        if t is None:
            problems.append(f"read {i} has no page clock")
        elif last_t is not None and t - last_t < min_gap_ms:
            problems.append(f"read {i} only {t - last_t:.0f} ms after the previous")
        last_t = t if t is not None else last_t
        mine = []
        for e in r["pool"]:
            if not isinstance(e, dict) or _entry_movie_key(e) is None:
                problems.append(f"read {i} holds an unattributable entry")
                continue
            if _entry_movie_key(e) == target_key:
                mine.append(e)
        ids = [e.get("elId") for e in mine]
        pooled |= {str(x) for x in ids if x is not None}
        carried = [e for e in mine if _same_id(e.get("elId"), carried_el_id)]
        if len(carried) != 1:
            problems.append(f"read {i} holds {len(carried)} carried entries")
        if any(e.get("elId") is None for e in mine):
            problems.append(f"read {i} holds a movie1 entry without an elId")
        if any(e.get("inDocument") is not False for e in mine):
            problems.append(f"read {i} holds a movie1 entry in the document")
        if any(e.get("fromDom") for e in mine):
            problems.append(f"read {i} holds a fromDom movie1 entry")
        for e in carried:
            if e.get("paused") is not False:
                problems.append(f"read {i} carried decoder paused")
            ready = e.get("readyState")
            if not isinstance(ready, (int, float)) or ready < 2:
                problems.append(f"read {i} carried decoder readyState {ready!r}")
        per_read.append({"t": t, "sceneHash": r.get("sceneHash"), "movie1ElIds": ids})
    return {
        "ok": not problems,
        "problems": problems[:12],
        "readsN": len(reads),
        "pooledElIds": sorted(pooled),
        "reads": per_read,
    }


def carriedClock1to2(
    pre_flip_owner_ids: list,
    pool_reads: object,
    carried_el_id: object,
    *,
    rate_min: float = GL_CLOCK_RATE_MIN,
    rate_max: float = GL_CLOCK_RATE_MAX,
    min_reads: int = GL_POOL_MIN_READS,
) -> dict:
    """Clause (g) (plan §4.2 g): the pre-flip owner is the carried decoder and its own clock runs at wall rate."""
    owners = [o for o in (pre_flip_owner_ids or []) if o is not None]
    owner_ok = bool(owners) and all(_same_id(o, carried_el_id) for o in owners)
    samples = []
    for r in pool_reads if isinstance(pool_reads, list) else []:
        if not isinstance(r, dict):
            continue
        entry = next(
            (e for e in r.get("pool") or [] if isinstance(e, dict) and _same_id(e.get("elId"), carried_el_id)),
            None,
        )
        t = _finite(r.get("t"))
        ct = _finite(entry.get("currentTime")) if entry else None
        samples.append({"t": t, "currentTime": ct})
    clean = [s for s in samples if s["t"] is not None and s["currentTime"] is not None]
    rising = len(clean) == len(samples) and all(
        b["currentTime"] > a["currentTime"] and b["t"] > a["t"] for a, b in zip(clean, clean[1:])
    )
    rate = None
    if len(clean) >= 2 and clean[-1]["t"] > clean[0]["t"]:
        rate = (clean[-1]["currentTime"] - clean[0]["currentTime"]) / ((clean[-1]["t"] - clean[0]["t"]) / 1000.0)
    ok = bool(
        carried_el_id is not None
        and owner_ok
        and len(clean) >= min_reads
        and rising
        and rate is not None
        and rate_min <= rate <= rate_max
    )
    reason = None
    if carried_el_id is None:
        reason = "no carried decoder"
    elif not owner_ok:
        reason = "pre-flip footprint owner is not the carried decoder"
    elif len(clean) < min_reads or len(clean) != len(samples):
        reason = "carried clock missing from a pool read"
    elif not rising:
        reason = "carried clock not strictly increasing"
    elif rate is None or not rate_min <= rate <= rate_max:
        reason = "carried clock off wall rate"
    return {
        "ok": ok,
        "reason": reason,
        "preFlipOwnerIds": owners[:12],
        "samples": samples,
        "rate": rate,
    }


def glCarryCensusVerdict(census: object, carried_el_id: object) -> dict:
    """Clause (c) (plan §4.2 c): the in-page carry census split at the hand-off."""
    if not isinstance(census, dict):
        return {"ok": False, "reason": "gl carry census missing", "census": census}
    before = census.get("before") if isinstance(census.get("before"), dict) else {}
    gated = census.get("gated")
    gated_total = census.get("gatedTotal")
    facades = _id_set(census.get("facadeElIds"))
    handoff_scene = census.get("handoffScene")
    if (
        not isinstance(before.get("total"), int)
        or not isinstance(gated, list)
        or not isinstance(gated_total, int)
        or facades is None
        or not all(isinstance(e, dict) for e in gated)
    ):
        return {"ok": False, "reason": "gl carry census malformed", "census": census}
    if census.get("malformedTotal") != 0:
        return {"ok": False, "reason": "movie1 carry notes with an unparseable scene hash", "census": census}
    if _finite(census.get("handoffT")) is None or not isinstance(handoff_scene, int) or handoff_scene < 0:
        return {"ok": False, "reason": "no hand-off in the census", "census": census}
    if gated_total != len(gated):
        return {"ok": False, "reason": "gl carry census truncated after the hand-off", "census": census}
    into = [
        e for e in gated
        if e.get("kind") == "remount-into-authored-layer"
        and _strict_hash_num(e.get("sceneHash")) == handoff_scene
        and _same_id(e.get("elId"), carried_el_id)
    ]
    owned = facades | ({str(carried_el_id)} if carried_el_id is not None else set())
    forbidden = [
        e for e in gated
        if e.get("kind") in ("remount-done", "remount-footprint-rect") and str(e.get("elId")) in owned
    ]
    problems = []
    if carried_el_id is None:
        problems.append("no carried decoder")
    if not _same_id(census.get("carriedElId"), carried_el_id):
        problems.append("census carried decoder differs from the carried note")
    if before["total"] != 0:
        problems.append(f"{before['total']} carry notes before the hand-off")
    if len(into) != 1:
        problems.append(f"{len(into)} remount-into-authored-layer for the carried decoder at the hand-off scene")
    if forbidden:
        problems.append(f"{len(forbidden)} remount-done/-footprint-rect for the carried decoder or its facade")
    return {
        "ok": not problems,
        "reason": problems[0] if problems else None,
        "problems": problems,
        "beforeTotal": before["total"],
        "beforeSample": (before.get("sample") or [])[:6],
        "gated": gated[:12],
        "handoffT": census.get("handoffT"),
        "handoffScene": handoff_scene,
        "afterTotalNonGating": census.get("afterTotal"),
    }


def glLiveOnSlide2(states: object, at_scene: int, *, min_reads: int = 2) -> dict:
    """Clause (b)'s live half (plan §4.2 b): the module LIVE and advancing across the slide-2 state reads."""
    reads = states if isinstance(states, list) else []
    problems = []
    if len(reads) < min_reads:
        problems.append(f"{len(reads)} slide-2 state reads, need {min_reads}")
    stats = []
    times: list[float | None] = []
    for i, r in enumerate(reads):
        st = r.get("stats") if isinstance(r, dict) and isinstance(r.get("stats"), dict) else None
        if st is None:
            problems.append(f"state read {i} missing")
            continue
        if r.get("state") != "LIVE":
            problems.append(f"state read {i} is {r.get('state')!r}")
        if r.get("standDowns") != []:
            problems.append(f"state read {i} stand-downs {r.get('standDowns')!r}")
        if st.get("glErrors") != 0:
            problems.append(f"state read {i} glErrors {st.get('glErrors')!r}")
        if _strict_hash_num(r.get("sceneHash")) != at_scene:
            problems.append(f"state read {i} at {r.get('sceneHash')!r}, expected #{at_scene}")
        epoch = st.get("epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool):
            problems.append(f"state read {i} epoch {epoch!r}")
        stats.append(st)
        times.append(_finite(r.get("t")))
    if len(stats) == len(reads) and len(stats) >= 2:
        if len({s.get("epoch") for s in stats}) != 1:
            problems.append("epoch changed across slide-2 reads")
        if any(x is None for x in times) or not all(b > a for a, b in zip(times, times[1:])):
            problems.append(f"state read clocks not strictly increasing: {times!r}")
        for field in ("iter", "uploads"):
            vals = [_finite(s.get(field)) for s in stats]
            if any(x is None for x in vals) or not all(b > a for a, b in zip(vals, vals[1:])):
                problems.append(f"{field} not strictly increasing: {vals!r}")
    return {
        "ok": not problems,
        "problems": problems,
        "reads": [
            {k: s.get(k) for k in ("epoch", "iter", "uploads", "glErrors", "loopMode")} for s in stats
        ],
    }


def _gl_zone_handoff_verdict(
    preserve_events: list[dict],
    carried_el_id: object,
    pooled_el_ids: list[str],
    *,
    target_key: str,
    at_scene: int,
    max_delta: float,
) -> dict:
    zone = [(d.get("from"), d.get("to"), d.get("reason")) for d in _gl_zone_notes(preserve_events)]
    arms = _kind_details(preserve_events, "glreplay-arm")
    lives = _kind_details(preserve_events, "glreplay-live")
    carried = _kind_details(preserve_events, "glreplay-carried")
    releases = _kind_details(preserve_events, "glreplay-release")
    refusals = [
        e for e in refusalEvents(preserve_events, target_key, at_scene)
        if (_event_scene(e) or 0) < at_scene + 1
    ]
    expected_retired = sorted(set(pooled_el_ids) - {str(carried_el_id)})
    release = releases[0] if len(releases) == 1 else {}
    retired = _id_set(release.get("retired"))
    delta = _finite(carried[0].get("delta")) if len(carried) == 1 else None
    problems = []
    if zone != [("pending", "armed", "moduleReady"), ("armed", "released", "handoff")]:
        problems.append(f"zone {zone!r}")
    if len(arms) != 1 or _strict_hash_num(arms[0].get("sceneHash")) != at_scene - 1:
        problems.append(f"{len(arms)} glreplay-arm, expected one at #{at_scene - 1}")
    if len(lives) != 1:
        problems.append(f"{len(lives)} glreplay-live")
    if len(carried) != 1 or delta is None or delta > max_delta:
        problems.append(f"{len(carried)} glreplay-carried, delta {delta!r}")
    if len(releases) != 1:
        problems.append(f"{len(releases)} glreplay-release")
    elif release.get("mode") != "handoff" or release.get("ok") is not True:
        problems.append(f"release mode {release.get('mode')!r}")
    elif not _same_id(release.get("elId"), carried_el_id):
        problems.append("release handed off another decoder")
    elif retired is None or sorted(retired) != expected_retired or len(release["retired"]) != len(retired):
        problems.append(f"release retired {release.get('retired')!r}, expected {expected_retired!r}")
    if refusals:
        problems.append(f"{len(refusals)} refusal notes for {target_key} at #{at_scene}")
    return {
        "ok": not problems,
        "problems": problems,
        "zone": zone,
        "carriedDelta": delta,
        "release": release or None,
        "expectedRetired": expected_retired,
        "refusals": refusals[:6],
    }


def glReplayCarry1to2(
    injected_plan: dict,
    preserve_events: list[dict],
    gl_carry_census: object,
    pool_reads: object,
    lingering: object,
    index_samples: list[dict],
    flip_index: int | None,
    sample_frame_indices: list,
    pre_flip_owner_ids: list,
    gl_states_s2: object,
    gl_state_after: object,
    hash1: object,
    hash2: object,
    player_build_errors: list,
    *,
    target_key: str = MOVIE1_KEY,
    at_scene: int = SLIDE2_MIN_HASH,
    max_delta: float = GL_CARRIED_MAX_DELTA,
) -> dict:
    """Fail-closed 1->2 GL-replay carry verdict, clauses (a)-(h) of plan §4.2."""
    boundaries = (injected_plan or {}).get("boundaries") or []
    entry = next(
        (
            b for b in boundaries
            if isinstance(b, dict)
            and b.get("action") == "glReplay"
            and b.get("atScene") == at_scene
            and b.get("movieKey") == target_key
            and b.get("fallback") == "retire"
        ),
        None,
    )
    carried_notes = _kind_details(preserve_events, "glreplay-carried")
    carried_el_id = carried_notes[0].get("elId") if len(carried_notes) == 1 else None
    pool = glPoolReadsVerdict(pool_reads, carried_el_id, target_key=target_key, lo_scene=at_scene, hi_scene=at_scene + 1)
    zone = _gl_zone_handoff_verdict(
        preserve_events, carried_el_id, pool["pooledElIds"],
        target_key=target_key, at_scene=at_scene, max_delta=max_delta,
    )
    census = glCarryCensusVerdict(gl_carry_census, carried_el_id)
    painting = lingering.get("paintingCount") if isinstance(lingering, dict) else None
    no_painting = isinstance(painting, int) and not isinstance(painting, bool) and painting == 0
    progress = progressingIndexAfterFlip(index_samples, flip_index, sample_frame_indices)
    clock = carriedClock1to2(pre_flip_owner_ids, pool_reads, carried_el_id)
    state = gl_state_after if isinstance(gl_state_after, dict) else {}
    from_n = _strict_hash_num(hash1)
    to_n = _strict_hash_num(hash2)
    hash_ok = from_n == at_scene - 1 and to_n == at_scene
    live = glLiveOnSlide2(gl_states_s2, at_scene)
    retired_ok = state.get("standDowns") == [GL_HANDOFF_STAND_DOWN] and state.get("state") == "RETIRED"
    clauses = {
        "a": entry is not None,
        "b": bool(zone["ok"] and live["ok"]),
        "c": census["ok"],
        "d": pool["ok"],
        "e": no_painting,
        "f": progress["ok"],
        "g": clock["ok"],
        "h": bool(retired_ok and hash_ok and not player_build_errors),
    }
    reasons = []
    if not clauses["a"]:
        reasons.append("(a) no glReplay retire-fallback entry for the target key")
    if not clauses["b"]:
        reasons.append("(b) " + "; ".join(zone["problems"] + live["problems"]))
    if not clauses["c"]:
        reasons.append("(c) " + str(census.get("reason")))
    if not clauses["d"]:
        reasons.append("(d) " + "; ".join(pool["problems"]))
    if not clauses["e"]:
        reasons.append(f"(e) paintingCount {painting!r} on settled slide 2")
    if not clauses["f"]:
        reasons.append(
            f"(f) composite {progress['composite'].get('reason')!r}, "
            f"sampleFrame {progress['sourceSampleFrame'].get('reason')!r}"
        )
    if not clauses["g"]:
        reasons.append("(g) " + str(clock["reason"]))
    if not retired_ok:
        reasons.append(f"(h) module {state.get('state')!r} with standDowns {state.get('standDowns')!r}")
    if not hash_ok:
        reasons.append("(h) no valid forward 1->2 boundary")
    if player_build_errors:
        reasons.append("(h) player build error")
    return {
        "ok": all(clauses.values()),
        "clauses": clauses,
        "reasons": reasons,
        "planEntry": entry,
        "carriedElId": carried_el_id,
        "zone": zone,
        "liveOnSlide2": live,
        "carryCensus": census,
        "poolReads": pool,
        "paintingCount": painting,
        "progressingIndexAfterFlip": progress,
        "carriedClock1to2": clock,
        "glStateAfterBuild1": {k: state.get(k) for k in ("state", "standDowns")},
        "hash": f"{hash1}->{hash2}",
        "playerBuildErrors": player_build_errors,
    }


# The CAPTURE CONTRACT for the settled-slide-4 visible-content burst: the shape,
# frame count, rects and thresholds the re-score uses, taken from HERE and never
# from the retained blob (plan §10.17).
FOOTPRINT_BURST_SHAPE = (1080, 1920)
FOOTPRINT_BURST_FRAMES = len(BURST_OFFSETS_MS)
FOOTPRINT_SCORE_PARAMS = {
    "deltaMin": LIVE_DELTA_MIN,
    "cols": LIVE_BAND_COLS,
    "rows": LIVE_BAND_ROWS,
    "bandLiveFrac": LIVE_BAND_MIN_FRAC,
    "minLiveFrac": LIVE_RECT_MIN_FRAC,
    "insetPx": LIVE_RECT_INSET_PX,
    "dilatePx": STRAY_DILATE_PX,
    "minAreaPx": STRAY_MIN_AREA_PX,
    "deadMaxLiveFrac": DEAD_RECT_MAX_LIVE_FRAC,
    "maxP99": NOISE_FLOOR_P99_MAX,
}
_FOOTPRINT_PARAM_ARGS = {
    "deltaMin": "delta_min", "cols": "cols", "rows": "rows",
    "bandLiveFrac": "band_live_frac", "minLiveFrac": "min_live_frac",
    "insetPx": "inset_px", "dilatePx": "dilate_px", "minAreaPx": "min_area_px",
    "deadMaxLiveFrac": "dead_max_live_frac", "maxP99": "max_p99",
}


def _encode_delta_raster(delta: np.ndarray) -> dict:
    """The scored max-delta raster, LOSSLESSLY, in whichever of the two encodings
    is smaller for this burst. `_max_delta_map` is a max-minus-min of uint8
    channels, so uint8 holds every value exactly."""
    u8 = np.ascontiguousarray(delta.astype(np.uint8))
    raw = zlib.compress(u8.tobytes(), 9)
    buf = io.BytesIO()
    Image.fromarray(u8, mode="L").save(buf, format="PNG", optimize=True)
    png = buf.getvalue()
    encoding, blob = ("png-gray", png) if len(png) <= len(raw) else ("zlib-u8", raw)
    return {
        "encoding": encoding,
        "bytes": len(blob),
        "h": int(u8.shape[0]),
        "w": int(u8.shape[1]),
        "data": base64.b64encode(blob).decode("ascii"),
    }


def _decode_delta_raster(evidence: dict, shape: tuple[int, int]) -> np.ndarray | None:
    """The retained raster at the CONTRACT's `shape`, or `None`.

    Fails closed on anything that is not exactly the recorded bytes decoded at
    exactly that shape: a self-described size other than the contract's, an
    unknown encoding, a truncated blob, a byte count that disagrees with the
    payload, a container that is not really a PNG, or a decoder error. The
    dimensions are checked BEFORE any pixel is decoded, so an oversized or
    decompression-bomb header is refused rather than expanded."""
    h_want, w_want = shape
    data, encoding = evidence.get("data"), evidence.get("encoding")
    h, w, n_bytes = evidence.get("h"), evidence.get("w"), evidence.get("bytes")
    if not isinstance(data, str) or not all(
        isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (h, w, n_bytes)
    ):
        return None
    if (h, w) != (h_want, w_want):
        return None
    try:
        blob = base64.b64decode(data, validate=True)
    except (ValueError, TypeError):
        return None
    if len(blob) != n_bytes:
        return None
    try:
        if encoding == "zlib-u8":
            # BOUNDED: never inflate more than one pixel past the contract's
            # size, so a corrupt stream returns `None` instead of exhausting
            # memory. Excess output, an unconsumed tail and a stream that never
            # terminates are each a refusal.
            dec = zlib.decompressobj()
            raw = dec.decompress(blob, h * w + 1)
            if len(raw) != h * w or dec.unconsumed_tail or dec.unused_data or not dec.eof:
                return None
            arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, w)
        elif encoding == "png-gray":
            with Image.open(io.BytesIO(blob)) as img:
                if img.format != "PNG" or img.mode != "L" or img.size != (w, h):
                    return None
                arr = np.asarray(img, dtype=np.uint8)
        else:
            return None
    except (ValueError, OSError, zlib.error, Image.DecompressionBombError,
            Image.UnidentifiedImageError):
        return None
    return arr if arr.shape == (h, w) else None


def _footprint_rects(
    expected_rect: tuple[int, int, int, int] = SLIDE4_MOVIE_RECT,
) -> list[dict]:
    """The contract's scored rectangles for the settled slide-4 burst."""
    return [{**dict(zip(("x", "y", "w", "h"), expected_rect)), "label": "slide4Movie"}]


def footprintFullyLive(frames: list, *, capture_id: str) -> dict:
    """Settled slide 4 must PAINT the carried movie: `score_visible_slide` over
    the bridged footprint, with imported thresholds. Anything but
    `verdict is True` (including `inconclusive`) fails.

    The scored max-delta raster is RETAINED under `evidence` with the arm's own
    `capture_id` and a per-frame sha256 of the burst: the verdict is a pure
    function of the raster, so the scorer recomputes coverage, bands, noise and
    strays instead of trusting the cached summary, and the `captureId` (retained
    again in the snapshot header) says WHOSE burst it recomputed them from. The
    rects and parameters travel for the report; the re-score reads the contract's
    constants (plan §10.17)."""
    if len(frames) < 2:
        return {"ok": False, "verdict": None, "status": "inconclusive",
                "reason": "insufficient burst frames", "n": len(frames)}
    rects = _footprint_rects()
    ctrl = dict(SLIDE4_CONTROL_RECT)
    delta = _max_delta_map(frames)
    scored = score_visible_slide_from_delta(
        delta, rects, ctrl,
        **{arg: FOOTPRINT_SCORE_PARAMS[key] for key, arg in _FOOTPRINT_PARAM_ARGS.items()},
    )
    return {
        "ok": scored.get("verdict") is True,
        "n": len(frames),
        "evidence": {
            "captureId": capture_id,
            "n": len(frames),
            "rects": rects,
            "controlRect": ctrl,
            "params": dict(FOOTPRINT_SCORE_PARAMS),
            "burstOffsetsMs": list(BURST_OFFSETS_MS),
            "frameSha256": [
                hashlib.sha256(np.ascontiguousarray(f).tobytes()).hexdigest()
                for f in frames
            ],
            **_encode_delta_raster(delta),
        },
        **scored,
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
    texids they keyed off are the provenance-only motion-path Magic Move poster
    swap (a 1->2 or 3->4 crossfade, never a fed surface in-window here). A live
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


def _iou(a: object, b: object) -> float | None:
    """Intersection-over-union of two authored-px rects, or `None` when either is
    not four real measurements."""
    ra, rb = _rect_or_none(a), _rect_or_none(b)
    if ra is None or rb is None:
        return None
    ix = max(0.0, min(ra["x"] + ra["w"], rb["x"] + rb["w"]) - max(ra["x"], rb["x"]))
    iy = max(0.0, min(ra["y"] + ra["h"], rb["y"] + rb["h"]) - max(ra["y"], rb["y"]))
    inter = ix * iy
    union = ra["w"] * ra["h"] + rb["w"] * rb["h"] - inter
    return (inter / union) if union > 0 else None


def _derived_paint(entry: dict) -> tuple[bool, str | None] | None:
    """`(visible, hiddenBy)` RECOMPUTED from the raw readings, or `None` when the
    entry does not carry them.

    The page's own `visible` is a derived Boolean like any other, and a stale one
    reading `false` over an attached, opaque, on-screen element would be SKIPPED
    by the attestation. The rules are the page's, restated on the
    retained `inDocument` / `documentHidden` / `display` / `visibility` / ancestor-opacity product /
    `checkVisibility` / client rect / viewport, in the same order, so the two
    must agree exactly. `documentHidden` is absent only from records that predate
    it (captured under screenshot-driven hidden-page scheduling)."""
    attached = entry.get("inDocument")
    page_hidden = entry.get("documentHidden", False)
    display, visibility = entry.get("display"), entry.get("visibility")
    op = _finite(entry.get("opacityProduct"))
    engine = entry.get("checkVisibility")
    rect = _rect_or_none(entry.get("clientRect"))
    view = entry.get("viewport") if isinstance(entry.get("viewport"), dict) else {}
    vw, vh = _finite(view.get("w")), _finite(view.get("h"))
    if not (
        isinstance(attached, bool)
        and isinstance(page_hidden, bool)
        and (engine is None or isinstance(engine, bool))
        and rect is not None
        and vw is not None and vh is not None
    ):
        return None
    if not attached:
        return False, "detached"
    if page_hidden:
        return False, "page-hidden"
    if not (isinstance(display, str) and isinstance(visibility, str) and op is not None):
        return None
    if display == "none":
        return False, "display-none"
    if not (rect["w"] > 0 and rect["h"] > 0):
        return False, "zero-size"
    if visibility == "hidden" or not op > 0:
        return False, "hidden"
    if engine is False:
        return False, "engine-hidden"
    if not (
        rect["x"] + rect["w"] > 0 and rect["y"] + rect["h"] > 0
        and rect["x"] < vw and rect["y"] < vh
    ):
        return False, "offscreen"
    return True, None


def _paint_agrees(entry: dict, dom_ids: set[str]) -> bool:
    """Is this entry's paint decision RE-DERIVABLE and equal to the page's?

    A preserve-pool entry is a CLOCK record, not a paint claim, and carries no
    CSS of its own. It is admitted as `detached` only on a retained
    `inDocument == false`; one that says it is still attached asserts nothing by
    itself and is admitted only when that sample's DOM census carries the same
    decoder -- whose own entry is re-derived by this same rule (plan §10.19)."""
    if entry.get("fromPreservePool"):
        if entry.get("inDocument") is False:
            return entry.get("visible") is False and entry.get("hiddenBy") == "detached"
        if entry.get("inDocument") is not True:
            return False
        return (
            entry.get("visible") is False
            and entry.get("hiddenBy") == "pool-duplicate"
            and str(entry.get("decoderId")) in dom_ids
        )
    derived = _derived_paint(entry)
    return derived is not None and (entry.get("visible"), entry.get("hiddenBy")) == derived


def _visible_competitors(
    media: list[dict], owner: list[dict], bound_decoder: object, positions: list[int]
) -> dict:
    """Which decoders OTHER than the bound one were VISIBLY sitting on the
    footprint, at the given positions of the after-window?

    A null owner reading says the footprint query resolved nothing; it does not
    say nothing was there. This reads the retained per-video geometry instead:
    every `videos` entry carries its authored-px rect and whether it PAINTS
    (`visible`), so a replacement decoder overlapping the bound decoder's own
    footprint while the owner is unresolved is DETECTABLE rather than assumed
    away (plan §10.18).

    Overlap is `IoU > 0` against that sample's own footprint. A sample whose
    geometry cannot be stated in authored px -- no stage map, a malformed rect,
    a missing `visible` flag -- is not an attestation and fails closed. The
    export's own suppressed restart element paints nothing and so does not
    compete; `hiddenBy` records which of detached / page-hidden / display-none /
    zero-size / hidden / engine-hidden / offscreen it was, and `suppressed34` records that
    PRESERVE is what is holding it that way.
    """
    hits: list[dict] = []
    classified: dict[str, int] = {}
    ok = True
    bound = str(bound_decoder)
    for i in positions:
        if not (0 <= i < len(media) and 0 <= i < len(owner)):
            ok = False
            continue
        fp = _rect_or_none(dict(zip(("x", "y", "w", "h"), owner[i].get("footprint") or [])))
        videos = media[i].get("videos")
        if fp is None or not isinstance(videos, list) or not videos:
            ok = False
            continue
        dom_ids = {
            str(e.get("decoderId")) for e in videos
            if isinstance(e, dict) and not e.get("fromPreservePool")
        }
        for v in videos:
            if not isinstance(v, dict) or "visible" not in v or not _paint_agrees(v, dom_ids):
                ok = False
                continue
            if str(v.get("decoderId")) == bound:
                continue
            if not v.get("visible"):
                why = str(v.get("hiddenBy"))
                classified[why] = classified.get(why, 0) + 1
                continue
            iou = _iou(v.get("rect"), fp)
            if iou is None:
                ok = False
                continue
            if iou > 0:
                ok = False
                hits.append({"at": i, "decoderId": v.get("decoderId"),
                             "iou": round(iou, 4), "rect": v.get("rect")})
    return {
        "ok": ok,
        "reason": None if ok else "a visible competing decoder overlapped the footprint",
        "hits": hits[:8],
        "n": len(positions),
        "hiddenBy": classified,
    }


def _owner_null_gaps(all_owner: list[dict], after: list[dict]) -> dict:
    """Are the after-window's null-`decoderId` intervals BOUNDED and BRACKETED?

    `nonNullFrac >= 0.7` is an aggregate: it admits a single blind interval of
    nearly a third of the window, during which a replacement decoder could own
    the footprint while the bound decoder's offscreen rVFC clock keeps ticking
    (plan §10.17). Each gap is therefore bounded on its own:

      - no run of nulls longer than `OWNER_NULL_MAX_RUN` INSIDE the window --
        that run is the blind interval, and it is what is bounded;
      - the nearest RESOLVED readings on either side of it, searched in the FULL
        owner series, must both exist and name the SAME decoder. The clean run's
        one gap straddles the boundary (the box is mid-flight and
        `elementFromPoint` resolves nothing while it moves), so its left bracket
        lies before the window; taking it from the full series is what makes the
        check non-vacuous instead of skipped;
      - a gap with nothing resolved after it is unbracketed and fails closed.

    Every admitted gap is reported with its span and its bracketing identity, so
    an arm that comes back INCONCLUSIVE says which interval was not observed.
    """
    if not after:
        return {"ok": False, "reason": "empty after-window", "gaps": [], "maxRun": 0}
    start = next((i for i, s in enumerate(all_owner) if s is after[0]), None)
    if start is None or all_owner[start:start + len(after)] != after:
        return {"ok": False, "reason": "after-window is not a slice of the series",
                "gaps": [], "maxRun": 0}

    def _resolved(i: int, step: int) -> object | None:
        """The nearest resolved `decoderId` from `i`, walking by `step`."""
        while 0 <= i < len(all_owner):
            did = all_owner[i].get("decoderId")
            if did is not None:
                return did
            i += step
        return None

    gaps: list[dict] = []
    ok = True
    i = 0
    while i < len(after):
        if after[i].get("decoderId") is not None:
            i += 1
            continue
        j = i
        while j + 1 < len(after) and after[j + 1].get("decoderId") is None:
            j += 1
        before = _resolved(start + i - 1, -1)
        after_id = _resolved(start + j + 1, 1)
        run = j - i + 1
        bracketed = (
            before is not None
            and after_id is not None
            and str(before) == str(after_id)
        )
        if run > OWNER_NULL_MAX_RUN or not bracketed:
            ok = False
        gaps.append({
            "from": i, "to": j, "run": run,
            "before": before, "after": after_id, "bracketed": bracketed,
        })
        i = j + 1
    return {
        "ok": ok,
        "reason": None if ok else "unbounded or unbracketed null-owner gap",
        "gaps": gaps,
        "maxRun": max((g["run"] for g in gaps), default=0),
    }


def movingContinuity3to4(
    owner_samples: list[dict],
    presented_samples: list[dict],
    slide3_movie_decoder: object,
    hash3: object,
    hash4: object,
    slide4_min_hash: int,
) -> dict:
    """Fail-CLOSED sub-verdict for playback continuity through the 3->4 moving
    Magic Move (positive control). The owner authored "Play movie across slides"
    but the HTML export RESTARTS movie1 on a fresh decoder at the grown slide-4
    footprint (see the Phase-0 diagnosis); the PRESERVE 3->4 bridge repairs it by
    keeping the SAME decoder playing while its box translates+scales. This gate
    proves the repair engaged — a raw (unbridged) export restarts and fails it.

    `ok` iff ALL hold (absence of any ⇒ fail closed; the failing name recorded):
      - `boundaryValid` — `hash3`/`hash4` parse, `num(hash4) > num(hash3)`, and
        `num(hash4) >= slide4_min_hash`: a genuine forward entry into slide 4.
      - `stableSlide4Owner` — exactly ONE distinct non-null footprint decoderId
        across the after-window (`hn >= num(hash4)`), covering a strong majority
        (>=70%); no `ownerAmbiguous` frame (two decoders at the slot). Owner is
        resolved by the caller at the MOVING interpolated footprint, keyed to
        movie1 (so the retiring right-side WA0125 the grown box overlaps is
        excluded).
      - `crossingIdentity` — that single slide-4 owner IS the SAME decoder that
        played slide 3 (`slide3_movie_decoder`, the 2->3 restart decoder). This is
        the ANTI-RESTART check: the export's fresh autoplay-from-0 element is a
        DIFFERENT decoder and fails here; only the bridged continuing decoder
        passes.
      - `rvfcMonotonic` — that decoder's rVFC `presentedMediaTime` ADVANCES
        (> 0.05) across the after-window and never rewinds (a reset-to-~0 restart
        would rewind), proving the live clock continues rather than restarting.
    """
    n3 = _strict_hash_num(hash3)
    n4 = _strict_hash_num(hash4)
    boundary_valid = (
        n3 is not None and n4 is not None and n4 > n3
        and isinstance(slide4_min_hash, int) and n4 >= slide4_min_hash
    )

    def _after(s: dict) -> bool:
        hn = _strict_hash_num(s.get("sceneHash"))
        return hn is not None and n4 is not None and hn >= n4

    all_owner = owner_samples or []
    after = [s for s in all_owner if _after(s)] if boundary_valid else []
    non_null_ids = [s.get("decoderId") for s in after if s.get("decoderId") is not None]
    distinct_non_null = sorted({str(x) for x in non_null_ids})
    non_null_frac = (len(non_null_ids) / len(after)) if after else 0.0
    has_ambiguous = any(s.get("ownerAmbiguous") for s in after)
    gaps = _owner_null_gaps(all_owner, after)
    # The owner and media series are built one per capture sample, so the
    # after-window's media rows are the SAME positions. Every position is
    # attested -- the gaps are where the owner reading is missing, but a visible
    # competitor anywhere in the window is a handoff either way -- and a series
    # that does not line up is no attestation at all.
    after_media = (
        [s for s in (presented_samples or []) if _after(s)] if boundary_valid else []
    )
    if len(after_media) == len(after):
        competitors = _visible_competitors(
            after_media, after, slide3_movie_decoder, list(range(len(after)))
        )
    else:
        competitors = {"ok": False, "reason": "owner and media series do not align",
                       "hits": [], "n": 0, "hiddenBy": {}}
    stable = (
        bool(after)
        and len(distinct_non_null) == 1
        and non_null_frac >= 0.7
        and gaps["ok"]
        and competitors["ok"]
        and not has_ambiguous
    )
    slide4_owner = non_null_ids[0] if stable else None

    crossing_identity = bool(
        slide4_owner is not None
        and slide3_movie_decoder is not None
        and str(slide4_owner) == str(slide3_movie_decoder)
    )

    if not boundary_valid:
        rvfc = {"ok": False, "reason": "invalid 3->4 boundary", "n": 0}
    elif slide4_owner is None:
        rvfc = {"ok": False, "reason": "no stable slide-4 owner", "n": 0}
    else:
        bounded = [s for s in (presented_samples or []) if _after(s)]
        rvfc = _presented_time_advances(bounded, slide4_owner, n4)
    rvfc_ok = bool(rvfc.get("ok"))

    checks = {
        "boundaryValid": boundary_valid,
        "stableSlide4Owner": stable,
        "crossingIdentity": crossing_identity,
        "rvfcMonotonic": rvfc_ok,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failed,
        "failed": failed,
        "slide4Owner": slide4_owner,
        "slide3MovieDecoder": slide3_movie_decoder,
        "boundaryValid": {"ok": boundary_valid, "n3": n3, "n4": n4, "slide4Min": slide4_min_hash},
        "stableSlide4Owner": {
            "ok": stable,
            "distinctNonNull": distinct_non_null,
            "nonNullFrac": round(non_null_frac, 3),
            "afterN": len(after),
            "nullGaps": gaps,
            "visibleCompetitors": competitors,
        },
        "crossingIdentity": {"ok": crossing_identity},
        "rvfcMonotonic": rvfc,
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
        patches.append(patch)
    scored = score_visible_movie_motion(patches)
    scored["roi"] = list(roi)
    return scored


# --- Footprint badge: the rect the CAPTURED FRAME actually shows ---------------
# The page paints the rect it is pinning, in the SAME animation frame it reads it,
# into a small binary badge at the viewport origin, with that frame's sequence
# number and a CRC. A screenshot therefore carries the movie pixels and the rect
# that produced them in ONE composited frame -- coupled by construction, not by
# timing luck -- and the page's own log of that frame can be matched against the
# decoded pixels afterwards. Round-trip measurements: plan §10.
FOOTPRINT_BADGE_CELL_PX = 6   # cell width (plan §10: 100% decode at dpr 1)
FOOTPRINT_BADGE_MAGIC = 0xB2  # 8-bit prefix; a frame without it is not a badge
FOOTPRINT_BADGE_FIELDS = ("seq", "x", "y", "w", "h")  # 16 bits each, after the magic
# ...then an 8-bit CRC over those five words, MSB-first: without it a torn frame
# can present a corrupted SEQUENCE that names another logged frame and borrows its
# timestamp, moving a sample across the hold or release boundary.
FOOTPRINT_BADGE_CRC_BITS = 8
# The re-handoff paints a null rect for exactly two consecutive frames, so at most
# two captures can land in it.
FREEZE_REHANDOFF_MAX_EXEMPT = 2
FOOTPRINT_BADGE_CELLS = 8 + 16 * len(FOOTPRINT_BADGE_FIELDS) + FOOTPRINT_BADGE_CRC_BITS
FOOTPRINT_BADGE_Q = 4         # quarter-px quantisation of the encoded rect
                              # (<=0.125 px error, far inside the couple tolerance)


def _nearest_sample_times(times: list[float | None]) -> list[float | None]:
    """DIAGNOSTICS ONLY. Fill each missing capture time from its nearest
    neighbour in SAMPLE ORDER; nothing scored may use it (plan §10.12)."""
    out = list(times)
    last: float | None = None
    for i, t in enumerate(out):
        if t is None:
            out[i] = last
        else:
            last = t
    nxt: float | None = None
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            out[i] = nxt
        else:
            nxt = out[i]
    return out


def _collector_sample_times(index_samples: list[dict]) -> list[float | None]:
    """The clock each capture is bracketed against: its OWN badge frame's, or
    `None`. The one seam the capture loop uses, so a neighbour substitution can
    never be reintroduced without a test seeing it (review r7 MAJOR 1)."""
    return [s.get("perfNowMs") for s in index_samples]


COLLECTOR_ROW_FIELDS = ("t", "hash", "progress", "fp", "owner", "media", "pool")


def _collector_rows_for(
    rows: list[dict], t: float | None
) -> tuple[dict | None, dict | None]:
    """The collector rows genuinely BRACKETING one capture sample's own badge-frame
    time: the last row at or before it (what the pre-screenshot read used to see)
    and the first row strictly after it (the post-screenshot read). `(None, None)`
    when the series does not bracket the sample -- never an extrapolated endpoint,
    which would lend a gap its neighbours' evidence (plan §10.10)."""
    if t is None:
        return None, None
    before: dict | None = None
    for r in rows:
        rt = r.get("t") if isinstance(r, dict) else None
        if not isinstance(rt, (int, float)):
            continue
        if rt <= t:
            before = r
        else:
            return (before, r) if before is not None else (None, None)
    return None, None


def _collector_series_meta(dump: object) -> dict:
    """Fail-closed integrity metadata for the ONE page-side collector dump: row
    count, first/last page clock, rows the ring dropped, page-side errors, and
    whether every row carries `COLLECTOR_ROW_FIELDS` in non-decreasing time
    order. `ok` is completed by the caller once every sample is bracketed."""
    d = dump if isinstance(dump, dict) else {}
    rows = d.get("rows")
    rows = rows if isinstance(rows, list) else []
    schema_ok = bool(rows)
    monotonic_ok = bool(rows)
    times: list[float] = []
    for r in rows:
        if not isinstance(r, dict) or any(r.get(k) is None for k in COLLECTOR_ROW_FIELDS):
            schema_ok = False
            break
        t = r.get("t")
        if not isinstance(t, (int, float)) or isinstance(t, bool):
            schema_ok = False
            break
        if times and t < times[-1]:
            monotonic_ok = False
        times.append(float(t))
    return {
        "rowCount": len(rows),
        "firstT": times[0] if times else None,
        "lastT": times[-1] if times else None,
        "dropped": int(d.get("dropped") or 0),
        "errors": int(d.get("errors") or 0),
        "schemaOk": schema_ok,
        "monotonicOk": monotonic_ok,
        "flipVia": d.get("flipVia"),
    }


def _collector_ok(meta: dict) -> bool:
    """The collector series is admissible evidence: rows present, schema intact,
    time non-decreasing, nothing dropped by the ring, no page-side error, and
    every capture sample bracketed by real rows."""
    return bool(
        meta.get("rowCount")
        and meta.get("schemaOk")
        and meta.get("monotonicOk")
        and meta.get("dropped") == 0
        and meta.get("errors") == 0
        and meta.get("samples")
        and meta.get("unbracketed") == 0
    )


def _rehandoff_pair(badge_stats: object, motion_marker: object) -> tuple[int, int] | None:
    """The ONE contiguous null-rect pair `(p, p+1)` the badge logged for the ONE
    re-handoff onto the trigger's own fresh pin, or None. Requires
    `rehandoffs == 1`, exactly that pair in `rehandoffSeqs`, and the badge's
    `motionStartedAt` to be the trigger marker's `started` -- a pair from any
    other generation is not the one the hold's pin-start residual is argued from
    (plan §10.6)."""
    st = badge_stats if isinstance(badge_stats, dict) else {}
    marker = motion_marker if isinstance(motion_marker, dict) else {}
    seqs = st.get("rehandoffSeqs")
    if st.get("rehandoffs") != 1 or not isinstance(seqs, list) or len(seqs) != 2:
        return None
    a, b = seqs
    if not (isinstance(a, int) and isinstance(b, int) and b == a + 1):
        return None
    started = marker.get("started")
    if started is None or st.get("motionStartedAt") != started:
        return None
    return (a, b)


def _is_rehandoff_sample(sample: dict, exempt_seqs: set[int]) -> bool:
    """A capture that landed on one of those null-rect re-handoff frames: no
    rect was painted, so nothing was decoded and the sample carries no evidence
    either way. Anything that DID decode is a real observation and must be
    `measured` instead."""
    return bool(
        sample.get("footprintSource") != "measured"
        and sample.get("index") is None
        and sample.get("badgeRect") is None
        and isinstance(sample.get("badgeSeq"), int)
        and sample["badgeSeq"] in exempt_seqs
    )


def _footprint_badge_crc8(words: list[int]) -> int:
    """CRC-8/ATM (poly 0x07, init 0x00) over 16-bit words, high byte first.
    Mirrors `crc8()` in FOOTPRINT_BADGE_JS."""
    crc = 0
    for w in words:
        for byte in ((w >> 8) & 0xFF, w & 0xFF):
            crc ^= byte
            for _ in range(8):
                crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _decode_footprint_badge(arr: np.ndarray, scale: float = 1.0) -> dict | None:
    """Decode the footprint badge out of ONE captured frame. Returns
    `{"seq", "x", "y", "w", "h", "crcOk"}` (CSS px) or `None` when the magic
    prefix is absent -- i.e. the badge was not installed, not yet painted, or
    torn across the prefix.

    `crcOk` False means the cells carried the magic but the payload does not
    check out (review r3 MAJOR 3): a torn or aliased frame. The caller must NOT
    use such a rect -- the sample is `unstable`, never `measured`."""
    cell = FOOTPRINT_BADGE_CELL_PX * scale
    if arr.ndim != 3 or arr.shape[1] < int(round(FOOTPRINT_BADGE_CELLS * cell)):
        return None
    y = int(cell // 2)
    if y >= arr.shape[0]:
        return None
    vals: list[int] = []
    for c in range(FOOTPRINT_BADGE_CELLS):
        x = int(round(c * cell + cell / 2.0))
        if x >= arr.shape[1]:
            return None
        vals.append(1 if float(arr[y, x, :3].mean()) >= 128.0 else 0)
    magic = 0
    for b in vals[:8]:
        magic = (magic << 1) | b
    if magic != FOOTPRINT_BADGE_MAGIC:
        return None
    out: dict = {}
    words: list[int] = []
    for i, name in enumerate(FOOTPRINT_BADGE_FIELDS):
        n = 0
        for b in vals[8 + 16 * i: 8 + 16 * (i + 1)]:
            n = (n << 1) | b
        words.append(n)
        out[name] = n if name == "seq" else n / float(FOOTPRINT_BADGE_Q)
    crc = 0
    for b in vals[8 + 16 * len(FOOTPRINT_BADGE_FIELDS):]:
        crc = (crc << 1) | b
    out["crcOk"] = crc == _footprint_badge_crc8(words)
    return out


ADVANCE_PRESS_HASH = SLIDE4_MIN_HASH - 1  # == #7, the settled pre-move boundary


def _new_advance_press_state() -> dict:
    return {"atHash": None, "wall": None, "sent": 0, "landed": 0,
            "unlanded": [], "stopped": False}


def _advance_press_decision(hn: int | None, st: dict, now: float) -> tuple[dict, bool]:
    """ONE step of the single-press advance discipline. This player QUEUES a key
    it cannot honour yet and replays it later, and the hash sits at
    `ADVANCE_PRESS_HASH` for the WHOLE 3->4 move -- so a timer-based re-press
    sends presses DURING the move that the player then replays on arrival.

    EXACTLY ONE key leaves, and only from the exact settled `#7` (review r3 MAJOR
    1). Draining from below is NOT this helper's job any more: entering at the
    self-advancing `#6` sent a press the player could not honour, and when the
    player's own `#6 -> #7` self-advance arrived the helper counted it as that
    press landing and immediately sent another -- two presses before `#8`, a
    contaminated multi-advance stimulus that finding 13 could still green on. The
    caller settles at `#7` first.

    The press is OUTSTANDING (`atHash`) until the hash rises above the hash it
    was sent at. An outstanding press that has not landed within
    `DRAIN_PRESS_LAND_S` is recorded unlanded and pressing STOPS for good --
    recorded and reported, never re-pressed, because a press that has not landed
    is a press the player may still be holding.

    Returns the new state and whether to press now."""
    if st["atHash"] is not None and hn is not None and hn > st["atHash"]:
        st = {**st, "atHash": None, "wall": None, "landed": st["landed"] + 1}
    elif (
        st["atHash"] is not None
        and st["wall"] is not None
        and (now - st["wall"]) > DRAIN_PRESS_LAND_S
    ):
        st = {**st, "atHash": None, "wall": None, "stopped": True,
              "unlanded": st["unlanded"] + [st["atHash"]]}
    press = bool(
        hn == ADVANCE_PRESS_HASH
        and st["sent"] == 0
        and st["atHash"] is None
        and not st["stopped"]
    )
    if press:
        st = {**st, "atHash": hn, "wall": now, "sent": st["sent"] + 1}
    return st, press


def _advance_gate(press_state: dict, final_hash: object) -> dict:
    """Fail-CLOSED summary of the advance (review r3 MAJOR 1): the 3->4 stimulus
    is valid only if exactly one key was sent from `#7`, it landed, nothing is
    outstanding or unlanded, pressing never had to stop, and the run ended at or
    beyond the intended boundary."""
    n = _hash_num(_norm_hash(final_hash))
    return {
        "pressesSent": press_state["sent"],
        "pressesLanded": press_state["landed"],
        "unlandedFromHash": press_state["unlanded"],
        "outstandingAtEnd": press_state["atHash"],
        "pressingStopped": press_state["stopped"],
        "finalHash": _norm_hash(final_hash),
        "pressHash": f"#{ADVANCE_PRESS_HASH}",
        "ok": bool(
            press_state["sent"] == 1
            and press_state["landed"] == 1
            and press_state["atHash"] is None
            and not press_state["unlanded"]
            and not press_state["stopped"]
            and n is not None
            and n >= SLIDE4_MIN_HASH
        ),
    }


OWNER_SETTLE_READINGS = 3   # consecutive agreeing keyed-owner rect reads


def _advance_key_clock(read: object) -> float | None:
    """The cut instant: the watch's recorded `timeStamp` iff the page accepted
    EXACTLY ONE trusted non-repeat ArrowRight keydown and rejected none. Anything
    else is `None`, which `_at_cut_boundary` fails closed (plan §10.13)."""
    r = read if isinstance(read, dict) else {}
    n, rej, t = r.get("n"), r.get("rejected"), r.get("t")
    if not isinstance(n, int) or isinstance(n, bool) or n != 1:
        return None
    if not isinstance(rej, int) or isinstance(rej, bool) or rej != 0:
        return None
    if not isinstance(t, (int, float)) or isinstance(t, bool):
        return None
    return float(t) if math.isfinite(float(t)) else None


def _advance_key_observed_once(snap: dict) -> bool:
    """The page itself counted exactly one accepted ArrowRight keydown and
    rejected none. A missing counter is absence, not evidence (plan §10.13)."""
    n, rej = snap.get("advanceKeyEvents"), snap.get("advanceKeyRejected")
    return bool(
        isinstance(n, int) and not isinstance(n, bool) and n == 1
        and isinstance(rej, int) and not isinstance(rej, bool) and rej == 0
    )


def _fill_badge_coupling(samples: list[dict], frame_log: dict | None) -> dict:
    """Settle each sample's `footprintSource` against the page's OWN record of
    the frame its badge names. `measured` requires BOTH readings of that one
    frame -- the page's logged rect and the rect decoded from that frame's
    painted pixels -- to agree within `FOOTPRINT_COUPLE_TOL_PX`. A badge naming a
    frame the page never logged has a single reading, so it stays `unstable` and
    fails `allInHoldMeasured`: fail closed, exactly as a missing read did.

    Sequence integrity (review r3 MAJOR 3): the capture samples strictly slower
    than the badge paints, so the badge sequences it reads must be STRICTLY
    INCREASING, and the page's log times must increase with them. A duplicate,
    a non-monotonic sequence or a non-monotonic log time means a torn or aliased
    read -- the substituted `perfNowMs` could move a sample across the hold or
    release boundary -- so the sample is `unstable` and its timestamp is left
    alone.

    Mutates `samples` in place and returns counts for the report."""
    log = frame_log or {}
    counts = {"measured": 0, "unstable": 0, "unlogged": 0, "modelled": 0,
              "none": 0, "seqViolation": 0}
    prev_seq: int | None = None
    prev_t: float | None = None
    for s in samples:
        if s.get("footprintSource") != "badge":
            counts[s.get("footprintSource", "none")] = (
                counts.get(s.get("footprintSource", "none"), 0) + 1
            )
            continue
        seq = s.get("badgeSeq")
        entry = log.get(str(seq)) or log.get(seq)
        frame_rect = (entry or {}).get("rect")
        t = (entry or {}).get("t")
        violated = not isinstance(seq, int) or (prev_seq is not None and seq <= prev_seq)
        if entry is not None and t is not None and prev_t is not None and t <= prev_t:
            violated = True
        if isinstance(seq, int):
            prev_seq = seq if prev_seq is None else max(prev_seq, seq)
        if t is not None:
            prev_t = t if prev_t is None else max(prev_t, t)
        if entry is None:
            counts["unlogged"] += 1
        if violated:
            counts["seqViolation"] += 1
            s["footprintSource"] = "unstable"
            counts["unstable"] += 1
            continue
        if t is not None:
            s["perfNowMs"] = t
        if s.get("badgeRect") is None:
            # A decoded badge that painted a NULL rect (owner unresolved, or the
            # re-handoff's deliberate pair): one reading at most, so `unstable`.
            # It still passes through the sequence checks above -- bypassing them
            # let a duplicate or reversed exempt sequence through (review r5
            # MAJOR 1).
            s["footprintSource"] = "unstable"
            counts["unstable"] += 1
            continue
        coupled = _couple_owner_rect(frame_rect, s.get("badgeRect"))
        source = coupled.get("source")
        s["footprintSource"] = source
        if source == "measured":
            s["measuredRect"] = {k: coupled[k] for k in ("x", "y", "w", "h")}
        counts[source] = counts.get(source, 0) + 1
    return counts


def _couple_owner_rect(before: dict | None, after: dict | None) -> dict:
    """Couple rect + pixels (review Blocker 2b): a sample is `measured` only when
    two rect readings of the SAME frame both exist and agree within
    `FOOTPRINT_COUPLE_TOL_PX` -- otherwise `unstable` (still decoded, off
    whichever reading exists, for forensics, but never counted in an at-cut run
    and counted as a failure by `allInHoldMeasured`).

    The two readings are the page's OWN log of the animation frame it painted
    (`before`) and the rect decoded from that frame's painted badge pixels
    (`after`) -- one frame, one read, so a MOVING rect can still be `measured`
    (round 3, item B). `before` supplies the ROI: it is the unquantised value the
    runtime actually pinned, of which the badge is a quarter-px encoding.

    Still used pairwise on two successive reads by the pre-arm settle loop, where
    "the rect stopped moving" is exactly the question being asked."""
    if before is None and after is None:
        return {"source": "none"}
    if before is None or after is None:
        return {"source": "unstable", "before": before, "after": after}
    if (
        abs(before["x"] - after["x"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["y"] - after["y"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["w"] - after["w"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["h"] - after["h"]) <= FOOTPRINT_COUPLE_TOL_PX
    ):
        return {**before, "source": "measured"}
    return {"source": "unstable", "before": before, "after": after}


def _at_cut_boundary(
    index_samples: list[dict], advance_key_perf_ms: float | None
) -> dict:
    """The at-cut segment's first sample AND whether that boundary is valid: the
    first badge frame whose own page clock is at or after the advance keydown's
    (plan §10.8). Index `0` is a legitimate boundary and must not be confused
    with an invalid one, so the verdict travels as `ok`: a missing or
    non-finite keydown clock, or a keydown later than every badge frame, is
    `{"from": None, "ok": False}` and fails its arm closed."""
    if not isinstance(advance_key_perf_ms, (int, float)) or isinstance(advance_key_perf_ms, bool):
        return {"from": None, "ok": False, "reason": "no advance keydown page clock"}
    if not math.isfinite(float(advance_key_perf_ms)):
        return {"from": None, "ok": False, "reason": "non-finite advance keydown page clock"}
    for i, s in enumerate(index_samples):
        t = s.get("perfNowMs")
        if isinstance(t, (int, float)) and not isinstance(t, bool) and t >= advance_key_perf_ms:
            return {"from": i, "ok": True, "reason": None}
    return {"from": None, "ok": False, "reason": "no badge frame at or after the advance keydown"}


def _moving_index_run_at_cut(
    index_samples: list[dict],
    covered_until: int | None = None,
    covered_from: int | None = None,
    pre_key_index: object = None,
) -> tuple[dict, bool]:
    """Score the at-cut counter run over `index_samples[covered_from:covered_until]`.

    `covered_from` is the at-cut boundary and is REQUIRED: `None` means the
    boundary is invalid, never index 0 (plan §10.8), and the run is not scored.

    `flip_index` is the first sample in that segment whose hash reaches slide 4,
    found on the FULL ordered list, never on the measured-only subsequence. The
    flip sample and the FREEZE_MIN_AFTER samples strictly after it must all be
    `measured` and actually decoded and must all fit inside the segment, else
    `flipWindowDecodable=False` (the caller treats that as INCONCLUSIVE). Samples
    outside the segment stay in `indexSamples` for diagnostics only. Rationale and
    measurements: plan §10."""
    if covered_from is None:
        return (
            {"ok": False, "reason": "no valid at-cut boundary", "flipIndex": None,
             "flipIndexFull": None},
            False,
        )
    hi_bound = len(index_samples) - 1
    if covered_until is not None:
        hi_bound = min(hi_bound, int(covered_until))
    lo_bound = max(0, int(covered_from))
    samples = index_samples[lo_bound: hi_bound + 1] if hi_bound >= lo_bound else []
    flip_index_full = next(
        (
            i for i, s in enumerate(samples)
            if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
        ),
        None,
    )
    if flip_index_full is None:
        return (
            {"ok": False, "reason": "no sample reached slide 4", "flipIndex": None,
             "flipIndexFull": None},
            False,
        )
    window = range(flip_index_full, flip_index_full + FREEZE_MIN_AFTER + 1)
    window_decodable = window.stop - 1 <= len(samples) - 1 and all(
        samples[i].get("footprintSource") == "measured" and samples[i].get("index") is not None
        for i in window
    )
    if not window_decodable:
        return (
            {"ok": False, "reason": "flip window not decodable", "flipIndex": None,
             "flipIndexFull": flip_index_full},
            False,
        )
    measured = [s for s in samples if s.get("footprintSource") == "measured"]
    # A `None` read deletes the step across it from the freeze-run and progress
    # totals, so an unbounded run of them can conceal exactly the reset or freeze
    # this segment is scored for. Inadmissible absence is an
    # INCONCLUSIVE segment, never a verdict about the counter.
    if not _null_reads_admissible(
        [s.get("index") for s in measured], max_total=AT_CUT_MAX_NULLS,
        pre_key_index=pre_key_index,
    ):
        return (
            {"ok": False, "reason": "inadmissible null reads at cut",
             "flipIndex": None, "flipIndexFull": flip_index_full},
            False,
        )
    flip_index_measured = next(
        i for i, s in enumerate(measured) if s is samples[flip_index_full]
    )
    result = score_composited_index_run(measured, flip_index=flip_index_measured)
    return {**result, "flipIndexFull": flip_index_full}, True


# Sub-verdicts that MUST be invariant across A1/B/A2 (the freeze must change ONLY
# the counter): decoder liveness/identity + boundary/composition on the 3->4
# moving Magic Move, none of which the partial left-cover touches.
# `movingIndexRunAtCut` and `continueThroughMovingMagicMove3to4Pass` are
# DELIBERATELY excluded — they are what the freeze flips RED in B (plan
# p2_freeze_control_3to4.plan.md §4, "the slide-1/2 composition keys go").
_ISOLATION_KEYS = (
    "movingContinuityOk",
    "movingContinuityFailedEmpty",
    "rvfcMonotonicOk",
    "crossingIdentityOk",
    "stableSlide4OwnerOk",
    "boundaryValidOk",
    "footprintFullyLiveOk",
    "settledIndexProgressionOk",
    "playerBuildErrorsEmpty",
    "bridgeEngaged",
)


def _isolation_view(
    snap: dict, *,
    evidence_cadence: tuple[int, ...] = BURST_OFFSETS_MS,
    legacy_unrecorded_cadence: tuple[int, ...] | None = None,
) -> dict:
    """The invariant booleans extracted from a 3->4 snapshot for A1==B==A2 checks.
    Every one is RE-DERIVED from the arm's raw evidence -- samples, bridge events,
    and the retained burst raster -- and held to the cached values."""
    mc = _moving_continuity_derived(snap) or {}
    cached_mc = snap.get("movingContinuity3to4") or {}
    return {
        "movingContinuityOk": _moving_continuity_ok(snap),
        "movingContinuityFailedEmpty": (
            mc.get("failed") == [] and cached_mc.get("failed") == []
        ),
        "rvfcMonotonicOk": bool((mc.get("rvfcMonotonic") or {}).get("ok")),
        "crossingIdentityOk": bool((mc.get("crossingIdentity") or {}).get("ok")),
        "stableSlide4OwnerOk": bool((mc.get("stableSlide4Owner") or {}).get("ok")),
        "boundaryValidOk": bool((mc.get("boundaryValid") or {}).get("ok")),
        "footprintFullyLiveOk": _footprint_fully_live_ok(
            snap, evidence_cadence=evidence_cadence, legacy_unrecorded_cadence=legacy_unrecorded_cadence,
        ),
        "settledIndexProgressionOk": _settled_progression_ok(snap),
        "playerBuildErrorsEmpty": (snap.get("playerBuildErrors") == []),
        "bridgeEngaged": _bridge_engaged(snap),
    }


@functools.lru_cache(maxsize=8)
def _rescore_footprint_raster(data: str, meta_json: str) -> dict | None:
    """One re-score of a retained burst raster, memoised on the blob itself: the
    sweep scores the same three arms thousands of times. The scoring inputs are
    the CONTRACT's; `meta_json` carries only the blob's self-described container
    fields, which `_decode_delta_raster` checks against the contract's shape."""
    meta = json.loads(meta_json)
    delta = _decode_delta_raster({**meta, "data": data}, FOOTPRINT_BURST_SHAPE)
    if delta is None:
        return None
    return score_visible_slide_from_delta(
        delta, _footprint_rects(), dict(SLIDE4_CONTROL_RECT),
        **{arg: FOOTPRINT_SCORE_PARAMS[key] for key, arg in _FOOTPRINT_PARAM_ARGS.items()},
    )


def _footprint_evidence_bound(
    evidence: object, capture_id: object, *,
    evidence_cadence: tuple[int, ...] = BURST_OFFSETS_MS,
    legacy_unrecorded_cadence: tuple[int, ...] | None = None,
) -> dict | None:
    """The retained evidence, once it is BOUND to this arm, to the capture
    contract, AND to the named capture cadence, or `None`. Cadence is part of
    the instrument: evidence binds only to the profile `evidence_cadence`
    names, and a capture retained under an earlier profile (no recorded
    `burstOffsetsMs`) is scored only when the caller names that legacy
    profile explicitly via `legacy_unrecorded_cadence` -- the live driver
    path never does, so unrecorded evidence is unbound there by default.

    Also requires: the arm's own `captureId` (retained independently in the
    snapshot header, so a raster lifted from another arm names the wrong
    capture); the contract's frame count; a per-frame sha256 list of that
    same length, as provenance for the burst the raster was reduced from;
    and the rects, control rect and the ten parameters EQUAL to the constants
    the re-score will use, so a blob cannot weaken its own thresholds. The
    shape is enforced at decode."""
    ev = evidence if isinstance(evidence, dict) else {}
    ev_id = ev.get("captureId")
    shas = ev.get("frameSha256")
    recorded = ev.get("burstOffsetsMs")
    cadence_bound = (
        evidence_cadence == legacy_unrecorded_cadence
        if recorded is None
        else recorded == list(evidence_cadence)
    )
    if not (
        cadence_bound
        and isinstance(capture_id, str) and capture_id
        and isinstance(ev_id, str) and ev_id == capture_id
        and ev.get("n") == FOOTPRINT_BURST_FRAMES
        and isinstance(shas, list) and len(shas) == FOOTPRINT_BURST_FRAMES
        and all(
            isinstance(s, str) and len(s) == 64 and not set(s) - set("0123456789abcdef")
            for s in shas
        )
        and ev.get("rects") == _footprint_rects()
        and ev.get("controlRect") == dict(SLIDE4_CONTROL_RECT)
        and ev.get("params") == dict(FOOTPRINT_SCORE_PARAMS)
    ):
        return None
    meta = {k: ev.get(k) for k in ("encoding", "bytes", "h", "w")}
    return _rescore_footprint_raster(ev.get("data"), json.dumps(meta, sort_keys=True))


def _footprint_fully_live_ok(
    snap: dict, *,
    evidence_cadence: tuple[int, ...] = BURST_OFFSETS_MS,
    legacy_unrecorded_cadence: tuple[int, ...] | None = None,
) -> bool:
    """`footprintFullyLive.ok` RE-SCORED from the retained max-delta raster, bound
    to this arm's `captureId`, to the capture contract, and to the named capture
    cadence, and required to equal the cached result in EVERY field it derives --
    `liveFrac`, `maxDelta`, the clipped rects, the noise floor's p99, the strays --
    not merely in its booleans. Exact equality, no tolerance: the re-score runs
    the same code on the same raster, and it reproduces the committed numbers
    exactly on all three arms (plan §10.17). A summary alone authenticates
    nothing: it can claim a live footprint over a raster that shows a frozen
    one, or over another arm's."""
    cached = snap.get("footprintFullyLive")
    if not isinstance(cached, dict):
        return False
    derived = _footprint_evidence_bound(
        cached.get("evidence"), snap.get("captureId"),
        evidence_cadence=evidence_cadence, legacy_unrecorded_cadence=legacy_unrecorded_cadence,
    )
    if derived is None or derived.get("verdict") is not True:
        return False
    return bool(
        cached.get("ok") is True
        and cached.get("n") == FOOTPRINT_BURST_FRAMES
        and all(k in cached and cached[k] == v for k, v in derived.items())
    )


def _cover_tracks_footprint(raf_log: list[dict]) -> bool:
    """100% of hold frames: the logged cover rect must equal `subRect(measuredRect)`
    (NULL_CONTROL_JS's own derivation -- left-fraction of the ACTUALLY MEASURED
    owner rect read at the START of that rAF, never the modelled one, and never
    the value this frame itself just set -- review MAJOR 4) within
    `COVER_TRACK_TOL_PX`. Fails closed on a missing log or a missing rect on any
    frame."""
    if not raf_log:
        return False
    for r in raf_log:
        cover = r.get("coverRect")
        measured = r.get("measuredRect")
        if not cover or not measured:
            return False
        expected_w = float(measured.get("w") or 0.0) * COVER_LEFT_FRAC
        if (
            abs(float(cover.get("x") or 0.0) - float(measured.get("x") or 0.0)) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("y") or 0.0) - float(measured.get("y") or 0.0)) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("w") or 0.0) - expected_w) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("h") or 0.0) - float(measured.get("h") or 0.0)) > COVER_TRACK_TOL_PX
        ):
            return False
    return True


def _finite(v: object) -> float | None:
    """A real measurement, or `None`. Booleans and non-finite values are not
    numbers here, and a missing one is absence, never a zero."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _rect_or_none(rect: object) -> dict | None:
    """A rect with four real measurements, or `None`. A partial rect is absence."""
    if not isinstance(rect, dict):
        return None
    out = {k: _finite(rect.get(k)) for k in ("x", "y", "w", "h")}
    return out if all(v is not None for v in out.values()) else None


# Per-sample REQUIRED keys, validated before any window is selected or scored.
# The windows are cut by `sceneHash`/`progress` and scored on `index`/`decoderId`/
# `videos`, so an ABSENT key silently moves a window instead of failing one --
# deleting the sample that carries the evidence is not the same as that sample
# reading clean. `True` marks the keys the model admits as an explicit `None`.
# `badgeSeq` and the two rects are NOT here: `_badge_samples_sound` already holds
# every sample to them, with the argued re-handoff exemption a blanket presence
# rule would break (the one re-handoff capture legitimately reads null rects).
_INDEX_SAMPLE_KEYS = {
    "index": True,           # an undecodable badge patch is a real reading
    "sceneHash": False,
    "progress": False,
    "perfNowMs": False,
    "footprintSource": False,
}
_OWNER_SAMPLE_KEYS = {
    "sceneHash": False,
    "decoderId": True,       # a transient unresolved footprint owner is tolerated
    "ownerAmbiguous": False,
}
_MEDIA_SAMPLE_KEYS = {"sceneHash": False, "videos": False}
# `rect` is admitted as an explicit `None` -- that is what the probe records when
# the stage map is unavailable -- and `_visible_competitors` then fails the arm
# closed at the position that needs it, rather than the whole series here.
_VIDEO_ENTRY_KEYS = {
    "decoderId": False, "visible": False, "hiddenBy": True, "rect": True,
    "suppressed34": False, "inDocument": False,
}


def _samples_schema_ok(samples: object, required: dict[str, bool]) -> bool:
    """A non-empty series of dicts, each carrying every required key. An explicit
    `None` is admissible only where the model permits it; an absent key never is."""
    if not isinstance(samples, list) or not samples:
        return False
    return all(
        isinstance(s, dict)
        and all(k in s and (s[k] is not None or none_ok) for k, none_ok in required.items())
        for s in samples
    )


def _media_samples_schema_ok(samples: object, bound_decoder: object) -> bool:
    """`mediaSamples` carry their required keys, every `videos` entry is
    attributable to a decoder, and every after-window sample holds exactly ONE
    finite `presentedMediaTime` for the bound decoder: no observation, two that
    disagree, or two that AGREE is no rVFC reading at all."""
    if not _samples_schema_ok(samples, _MEDIA_SAMPLE_KEYS):
        return False
    for s in samples:
        videos = s.get("videos")
        if not isinstance(videos, list) or not _samples_schema_ok(videos, _VIDEO_ENTRY_KEYS):
            return False
        hn = _strict_hash_num(s.get("sceneHash"))
        if bound_decoder is None or hn is None or hn < SLIDE4_MIN_HASH:
            continue
        matches = [
            _finite(v.get("presentedMediaTime"))
            for v in videos
            if str(v.get("decoderId")) == str(bound_decoder) and "presentedMediaTime" in v
        ]
        if len(matches) != 1 or matches[0] is None:
            return False
    return True


def _sample_schema_failures(snap: dict) -> list[str]:
    """The sample series of one arm that are not schema-sound, by name."""
    return [
        name for name, ok in (
            ("indexSamples",
             _samples_schema_ok(snap.get("indexSamples"), _INDEX_SAMPLE_KEYS)),
            ("ownerSamples",
             _samples_schema_ok(snap.get("ownerSamples"), _OWNER_SAMPLE_KEYS)),
            ("mediaSamples",
             _media_samples_schema_ok(snap.get("mediaSamples"), snap.get("ownerDecoderId"))),
        ) if not ok
    ]


def _at_cut_boundary_valid(snap: dict) -> bool:
    """One arm's at-cut boundary is admissible: exactly one accepted advance
    keydown, a finite page clock for it, and a boundary RE-DERIVED here from that
    clock and the arm's own samples that agrees exactly with the cached one. A
    cached boundary that is merely in range can name a later sample and discard
    the first post-keydown reset the control exists to see."""
    key_ms = snap.get("advanceKeyPerfMs")
    derived = _at_cut_boundary(snap.get("indexSamples") or [], key_ms)
    cached = snap.get("atCutBoundary") or {}
    return bool(
        _advance_key_observed_once(snap)
        and _finite(key_ms) is not None
        and derived.get("ok") is True
        and isinstance(derived.get("from"), int)
        and cached.get("ok") is True
        and cached.get("from") == derived.get("from")
    )


def _advance_ok_derived(advance: object) -> bool:
    """`advance.ok` RE-DERIVED from the recorded press primitives through the same
    `_advance_gate`, and required to agree with the cached verdict."""
    a = advance if isinstance(advance, dict) else {}
    sent, landed = a.get("pressesSent"), a.get("pressesLanded")
    unlanded, stopped = a.get("unlandedFromHash"), a.get("pressingStopped")
    if not (
        isinstance(sent, int) and not isinstance(sent, bool)
        and isinstance(landed, int) and not isinstance(landed, bool)
        and isinstance(unlanded, list)
        and isinstance(stopped, bool)
        and "outstandingAtEnd" in a
        and a.get("pressHash") == f"#{ADVANCE_PRESS_HASH}"
    ):
        return False
    derived = _advance_gate(
        {"atHash": a.get("outstandingAtEnd"), "wall": None, "sent": sent,
         "landed": landed, "unlanded": unlanded, "stopped": stopped},
        a.get("finalHash"),
    )
    return bool(derived["ok"]) and a.get("ok") is True


def _drain_clean(snap: dict) -> bool:
    """Drain cleanliness RE-DERIVED from the recorded counts, unlanded list and
    `hashAtArm`, and required to agree with the cached booleans. `hashAtArm` must
    be the exact arm boundary this arm claims AND the exact `#7` the single
    advance press is sent from."""
    d = snap.get("drain") if isinstance(snap.get("drain"), dict) else {}
    sent, landed = d.get("pressesSent"), d.get("pressesLanded")
    unlanded = d.get("unlandedFromHash")
    if not (
        isinstance(sent, int) and not isinstance(sent, bool)
        and isinstance(landed, int) and not isinstance(landed, bool)
        and isinstance(unlanded, list)
    ):
        return False
    at_arm = d.get("hashAtArm")
    return bool(
        sent == landed
        and not unlanded
        and _norm_hash(at_arm) == _norm_hash(snap.get("armHash"))
        and _strict_hash_num(at_arm) == ADVANCE_PRESS_HASH
        and d.get("allPressesLanded") is True
        and d.get("hashAtArmExact") is True
        and d.get("ok") is True
        and d.get("selfAdvanceHash") == f"#{DRAIN_SELF_ADVANCE_HASH}"
    )


def _settled_progression_ok(snap: dict) -> bool:
    """`settledIndexProgression.ok` RE-DERIVED from the POST-SPLIT settled samples
    and required to agree with the cached verdict: a stalled settled counter can
    otherwise sit under a stale green."""
    split = snap.get("releaseSplitIndex")
    samples = snap.get("indexSamples") or []
    if not (
        isinstance(split, int) and not isinstance(split, bool)
        and 0 <= split < len(samples)
    ):
        return False
    seq = [s.get("index") for s in _slide4_settled_window(samples[split + 1:])]
    derived = score_index_progression(seq)
    return bool(
        _null_reads_admissible(seq, max_total=SETTLED_MAX_NULLS)
        and derived.get("ok")
        and (snap.get("settledIndexProgression") or {}).get("ok") is True
    )


def _owner_settle_ok(owner_settle: object) -> bool:
    """The pre-advance settle RE-DERIVED by replaying the ordered rect readings
    through the same `_couple_owner_rect` run the capture loop used, and required
    to agree with the recorded counters. A count and a Boolean alone are two more
    derived values, not the readings they came from."""
    st = owner_settle if isinstance(owner_settle, dict) else {}
    readings = st.get("readings")
    if not isinstance(readings, list):
        return False
    prev, stable = None, 0
    for raw in readings:
        rect = _rect_or_none(raw)
        stable = (
            stable + 1
            if _couple_owner_rect(prev, rect).get("source") == "measured"
            else 0
        )
        prev = rect
    return bool(
        stable >= OWNER_SETTLE_READINGS
        and st.get("stableReadings") == stable
        and st.get("required") == OWNER_SETTLE_READINGS
        and st.get("settled") is True
    )


def _advance_settle_exact(settle: object) -> bool:
    """The advance press left from the exact settled `#7`, RE-DERIVED from the
    recorded hash reading and its expectation. A cached `exact` can be stale from
    a read taken during the `#7` build's residual motion."""
    st = settle if isinstance(settle, dict) else {}
    return bool(
        _strict_hash_num(st.get("hashAtAdvance")) == ADVANCE_PRESS_HASH
        and st.get("expected") == f"#{ADVANCE_PRESS_HASH}"
        and st.get("exact") is True
    )


def _moving_continuity_derived(snap: dict) -> dict | None:
    """`movingContinuity3to4` RE-RUN from the retained owner and media samples, or
    `None` when either series is absent. Without the media samples a stale green
    continuity field hides a handoff or an rVFC rewind."""
    owner, media = snap.get("ownerSamples"), snap.get("mediaSamples")
    if not isinstance(owner, list) or not isinstance(media, list):
        return None
    return movingContinuity3to4(
        owner, media, snap.get("ownerDecoderId"),
        snap.get("hash3"), snap.get("hash4"), SLIDE4_MIN_HASH,
    )


def _moving_continuity_ok(snap: dict) -> bool:
    derived = _moving_continuity_derived(snap)
    cached = snap.get("movingContinuity3to4") or {}
    return bool(
        derived is not None and derived.get("ok")
        and cached.get("ok") is True and cached.get("failed") == []
    )


def _bridge_engaged(snap: dict) -> bool:
    """3->4 bridge engagement DERIVED from the retained `bridge-3to4` events: one
    must BE of that kind, and name the expected movie key, a scene at or beyond
    slide 4, the bound slide-3 decoder as the OLD element, and a preserve
    generation matching the one current when it fired. A `reuse-decoder` event
    carries the same detail shape and is not this bridge. The cached Boolean must
    agree."""
    events = snap.get("bridgeEvents")
    owner = snap.get("ownerDecoderId")
    if not isinstance(events, list) or owner is None:
        return False
    for e in events:
        if not isinstance(e, dict) or e.get("kind") != BRIDGE_EVENT_KIND:
            continue
        detail = e.get("detail")
        if not isinstance(detail, dict):
            continue
        gen, old_gen = detail.get("generation"), detail.get("oldGen")
        if (
            _movie_key(detail.get("key") or "") in EXPECTED_MOVIE_KEYS
            and (_event_scene(e) if isinstance(e, dict) else None) is not None
            and _event_scene(e) >= SLIDE4_MIN_HASH
            and detail.get("oldElId") is not None
            and str(detail.get("oldElId")) == str(owner)
            and isinstance(gen, int) and not isinstance(gen, bool)
            and isinstance(old_gen, int) and not isinstance(old_gen, bool)
            and old_gen == gen
        ):
            return snap.get("bridgeEngaged") is True
    return False


def _badge_samples_sound(snap: dict, exempt_seqs: set[int] | None = None) -> bool:
    """Every capture in this arm carries its own badge frame AND a USABLE
    GEOMETRY: the badge installed, every capture decoded, none went missing, tore
    its CRC, named an unlogged frame or read a sequence out of order, and every
    sample's painted rect agreed with the page's log (`measured`). The only
    non-`measured` samples admitted are the scorer's already-validated re-handoff
    pair, passed in as `exempt_seqs`; absent that, transport soundness alone is
    not geometry soundness (plan §10.12).

    Every sample is held to its OWN evidence, never to the aggregate counters or
    to its derived `footprintSource` label: a finite page clock, a strictly
    increasing typed badge sequence, both rect readings, and a coupling
    RECOMPUTED from them (plan §10.15)."""
    badge = snap.get("badge") or {}
    counts = badge.get("counts") or {}
    install = badge.get("install") or {}
    samples = snap.get("indexSamples") or []
    exempt = exempt_seqs or set()
    if not (
        samples
        and install.get("ok") is True
        and badge.get("decoded") == len(samples)
        and badge.get("missing") == 0
        and badge.get("crcBad") == 0
        and badge.get("unlogged") == 0
        and counts.get("seqViolation") == 0
    ):
        return False
    prev_seq: int | None = None
    for s in samples:
        if not isinstance(s, dict):
            return False
        seq = s.get("badgeSeq")
        if not (isinstance(seq, int) and not isinstance(seq, bool)):
            return False
        if prev_seq is not None and seq <= prev_seq:
            return False
        prev_seq = seq
        if _finite(s.get("perfNowMs")) is None:
            return False
        if _is_rehandoff_sample(s, exempt):
            continue
        coupled = _couple_owner_rect(
            _rect_or_none(s.get("measuredRect")), _rect_or_none(s.get("badgeRect"))
        )
        if coupled.get("source") != "measured" or s.get("footprintSource") != "measured":
            return False
    return True


def _longest_run(positions: list[int]) -> int:
    """The longest run of CONSECUTIVE positions in a sorted index list."""
    longest = run = 0
    prev: int | None = None
    for p in positions:
        run = run + 1 if prev is not None and p == prev + 1 else 1
        longest = max(longest, run)
        prev = p
    return longest


def _plausible_step(before: object, after: object) -> bool:
    """Did the counter march FORWARD by a plausible amount across one missed
    read? A zero step is the freeze the gate exists to catch; a large one is a
    reset."""
    if before is None or after is None:
        return False
    return 1 <= (int(after) - int(before)) % INDEX_PATCH_MODULO <= NULL_BRIDGE_MAX_STEP


def _null_reads_admissible(
    indices: list, *, max_total: int, pre_key_index: object = None
) -> bool:
    """Are this scored window's `None` counter reads the ONE identified
    acquisition miss, or evidence the window is missing?

    Both index scorers drop null-adjacent deltas, so a `None` is not a neutral
    sample: it deletes the step across it from the progress and freeze-run
    totals, and a reset or a freeze can hide in what it deleted. Only the
    measured shape is admitted:

      - at most `max_total` of them, and no run longer than
        `SCORED_NULL_MAX_RUN`;
      - a null is admissible only at POSITION 0. A count bound alone left the
        POSITION free: a sole null in the middle of the window erases both sides
        of a restart while the bridge across it still reads as plausible forward
        progress. Interior and trailing nulls are refused outright;
      - and the position-0 miss is bounded against the DECODED PRE-KEY reading
        taken before the advance, exactly as an interior null would be bounded
        against its own neighbours. Without that reading the leading miss has no
        near-side neighbour at all and the window fails closed.
    """
    if not isinstance(indices, list):
        return False
    nulls = [i for i, v in enumerate(indices) if v is None]
    if not nulls:
        return True
    if len(nulls) > max_total or _longest_run(nulls) > SCORED_NULL_MAX_RUN:
        return False
    if nulls != [0]:
        return False
    return _plausible_step(pre_key_index, indices[1] if len(indices) > 1 else None)


def _slide4_settled_window(index_samples: list[dict]) -> list[dict]:
    """Finding 13's scored window: samples whose hash has reached slide 4 and
    whose footprint has settled on the destination rect. Mid-transition frames
    sample an animating box and decode garbage (plan §10.12)."""
    return [
        s for s in index_samples
        if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
        and float(s.get("progress") or 0.0) >= 0.98
    ]


def _advance_c_ok(
    capture_meta: dict, index_samples: list[dict], settle: dict, owner_settle: dict
) -> bool:
    """Finding 13's stimulus-and-evidence gate, failing CLOSED: exactly one
    accepted keydown, one press sent from a SETTLED exact `#7` that landed, a
    whole bracketing collector series, a valid cut boundary, every capture
    badge- and geometry-sound, and a scored window that loses nothing to the
    measured-only filter -- there is no re-handoff here to exempt (plan §10.12).

    The sample schema is validated BEFORE the window is cut; the advance gate,
    both settles and the collector series are RE-DERIVED here and required to
    agree with the page's cached `ok` (plan §10.15)."""
    if not _samples_schema_ok(index_samples, _INDEX_SAMPLE_KEYS):
        return False
    collector = capture_meta.get("collector") or {}
    window = _slide4_settled_window(index_samples)
    measured = [s for s in window if s.get("footprintSource") == "measured"]
    return bool(
        _null_reads_admissible(
            [s.get("index") for s in measured], max_total=SETTLED_MAX_NULLS
        )
        and _advance_ok_derived(capture_meta.get("advance"))
        and _advance_settle_exact(settle)
        and _owner_settle_ok(owner_settle)
        and collector.get("ok") is True
        and _collector_ok(collector)
        and _at_cut_boundary_valid({**capture_meta, "indexSamples": index_samples})
        and _badge_samples_sound({**capture_meta, "indexSamples": index_samples})
        and len(measured) == len(window)
    )


BRACKET_MANIFEST_KIND = "p2-freeze-bracket-3to4"
BRACKET_ARMS = ("a1", "b", "a2")


def _new_bracket_manifest() -> dict:
    """One arm identity per arm, minted before any arm is captured."""
    return {
        "kind": BRACKET_MANIFEST_KIND,
        "arms": {label: uuid.uuid4().hex for label in BRACKET_ARMS},
    }


def _manifest_arms_ok(manifest: object, snaps: dict[str, dict]) -> bool:
    """Does every arm carry the identity the manifest HANDED it, and are the three
    distinct?

    The manifest is written before the first capture and lives outside the
    snapshots, so substituting a whole arm -- header id, raster evidence and all
    -- no longer agrees with anything: the moved block names another arm's
    identity, and the arm it replaced no longer names its own. Three distinct ids
    is what makes "another arm's" meaningful at all."""
    m = manifest if isinstance(manifest, dict) else {}
    arms = m.get("arms")
    if not (m.get("kind") == BRACKET_MANIFEST_KIND and isinstance(arms, dict)):
        return False
    expected = [arms.get(label) for label in BRACKET_ARMS]
    if not all(isinstance(v, str) and v for v in expected):
        return False
    if len(set(expected)) != len(BRACKET_ARMS):
        return False
    return all(
        snaps[label].get("captureId") == arms[label] for label in BRACKET_ARMS
    )


def _score_freeze_control(
    a1: dict, b: dict, a2: dict, manifest: object = None, *,
    evidence_cadence: tuple[int, ...] = BURST_OFFSETS_MS,
    legacy_unrecorded_cadence: tuple[int, ...] | None = None,
) -> dict:
    """Pure A-B-A verdict for `freezeControlCaughtByCounter`, re-bracketed at the
    3->4 moving Magic Move (plan p2_freeze_control_3to4.plan.md §4; the 1->2 carry
    is refused, so there is no carried movie to freeze there).

    Passes IFF the injected freeze turns the at-cut counter RED for the right
    reason while every other sub-verdict stays green (and equal) in ALL three
    runs. Returns `{"ok", "verdict", "reason", "checks", ...}` where `verdict` is
    one of "pass" / "fail" / "inconclusive".

    A hold that never fired is INCONCLUSIVE, never PASS/FAIL: a silently-unfired
    hold makes B look exactly like a passing positive (index_run green), which
    must NOT be read as "the gate is vacuous". So holdStartedAt is checked BEFORE
    the two-tier integrity/verdict split below.
    """
    checks: dict[str, object] = {}
    # --- Schema BEFORE any window is selected or scored -------------------------
    schema_failed = {
        name: _sample_schema_failures(snap)
        for name, snap in (("a1", a1), ("b", b), ("a2", a2))
    }
    checks["sampleSchemaSoundAllArms"] = not any(schema_failed.values())
    checks["armIdentitiesMatchManifest"] = _manifest_arms_ok(
        manifest, {"a1": a1, "b": b, "a2": a2}
    )

    nc = b.get("nullControl") or {}

    # --- Guard: the control must have ARMED (review BLOCKER 1) ------------------
    arm_result = b.get("armResult") or {}
    if not arm_result.get("ok"):
        return {
            "ok": False,
            "verdict": "inconclusive",
            "reason": f"freeze control never armed: {arm_result.get('error')}",
            "armResult": arm_result,
            "checks": checks,
        }

    # --- Guard: the hold must have fired, and continuously (else INCONCLUSIVE) ---
    hold_started = nc.get("holdStartedAt")
    if hold_started is None or nc.get("status") not in ("holding", "released"):
        return {
            "ok": False,
            "verdict": "inconclusive",
            "reason": "freeze hold never fired (holdStartedAt is null) — cannot judge the counter",
            "nullControlStatus": nc.get("status"),
            "checks": checks,
        }
    raf_log = nc.get("rafLog") or []
    raf_ts = [r.get("t") for r in raf_log if isinstance(r.get("t"), (int, float))]
    # The gap from the move-start TRIGGER to the first hold frame is bounded too
    # (review MAJOR 5): a slow first rAF after trigger leaves the cover behind
    # the movie for that whole span, same as an inter-frame stall.
    raf_ts_from_trigger = ([hold_started] + raf_ts) if hold_started is not None else raf_ts
    max_gap_ms = max(
        (raf_ts_from_trigger[i + 1] - raf_ts_from_trigger[i] for i in range(len(raf_ts_from_trigger) - 1)),
        default=0.0,
    )
    # ...and the PRE-trigger poll gaps, measured in the page from the advance
    # keydown (review r3 BLOCKER 3): a stall there is unobserved by everything
    # else, yet it is exactly when the runtime's interpolation runs away.
    # ...and a MISSING pre-trigger measurement is absence, not a zero gap: without
    # it a low-gap hold series would carry `maxRafGapOk` on its own (review r9
    # MAJOR 2).
    poll_gap = _finite(nc.get("pollMaxGapMs"))
    poll_gap_present = poll_gap is not None and poll_gap >= 0.0
    poll_max_gap_ms = poll_gap if poll_gap_present else None
    max_gap_ms = max(max_gap_ms, poll_max_gap_ms or 0.0)
    # Unlike the retired static 1->2 footprint, the 3->4 cover TRACKS a moving
    # target every rAF (re-derived from the measured owner rect); a rAF stall
    # here leaves the cover behind the movie, not merely unobserved, so the gap
    # is DISQUALIFYING (owner decision, plan §4) rather than diagnostic-only.

    # ONE clock (review BLOCKER 2): the advance keydown, the hold, the release and
    # every capture sample are all browser `performance.now()` readings. Python's
    # `time.monotonic()` offsets are retained for the report only.
    advance_key_at = nc.get("advanceKeyAt")
    release_at = nc.get("releaseAt")
    trigger_delay_ms = (
        (hold_started - advance_key_at) if advance_key_at is not None else None
    )
    trigger_frames = nc.get("triggerFramesAfterAdvance")
    hold_offset_s = trigger_delay_ms / 1000.0 if trigger_delay_ms is not None else None
    release_offset_s_nc = (
        (release_at - advance_key_at) / 1000.0
        if (advance_key_at is not None and release_at is not None)
        else None
    )
    index_samples = b.get("indexSamples") or []
    perfs = [s.get("perfNowMs") for s in index_samples]
    seq = [s.get("index") for s in index_samples]
    sources = [s.get("footprintSource") for s in index_samples]

    # The scored window opens when the cover was actually PAINTED, not at the
    # trigger, and fails CLOSED without a `coverPaintedAt` (plan §10).
    cover_painted_at = nc.get("coverPaintedAt")
    release_split_index = b.get("releaseSplitIndex")
    covered_positions = [
        i for i, t in enumerate(perfs)
        if cover_painted_at is not None and t is not None and t >= cover_painted_at
        and (release_at is None or t <= release_at)
        and (not isinstance(release_split_index, int) or i <= release_split_index)
    ]
    # ...and it opens after the badge's OWN single identified re-handoff, and
    # nothing else (review r4 BLOCKER 1, r5 MAJOR 1): exactly one re-handoff,
    # exactly one contiguous null-rect pair tied to the trigger marker, the
    # captured exempt sequences unique and increasing, and EVERY non-exempt
    # covered badge sequence strictly later than that pair -- so the argued
    # pin-start residual is proved, not assumed (plan §10.6).
    motion_marker = nc.get("motionStartedMarker") or {}
    motion_at_trigger = nc.get("obedMotionAtTrigger") or {}
    badge_stats = (b.get("badge") or {}).get("stats")
    pair = _rehandoff_pair(badge_stats, motion_marker)
    exempt_seqs = set(pair) if pair else set()
    exempt_prefix = 0
    for i in covered_positions:
        if not _is_rehandoff_sample(index_samples[i], exempt_seqs):
            break
        exempt_prefix += 1
    exempt_seen = [index_samples[i].get("badgeSeq") for i in covered_positions[:exempt_prefix]]
    rest = covered_positions[exempt_prefix:]
    rest_seqs = [index_samples[i].get("badgeSeq") for i in rest]
    rehandoff_exempt_ok = bool(
        pair is not None
        and exempt_prefix <= FREEZE_REHANDOFF_MAX_EXEMPT
        and all(y > x for x, y in zip(exempt_seen, exempt_seen[1:]))
        and rest
        and all(isinstance(s, int) and s > pair[1] for s in rest_seqs)
    )
    in_hold_positions = rest if rehandoff_exempt_ok else []
    first_covered_position = in_hold_positions[0] if in_hold_positions else None
    # RECOMPUTED here from the raw samples, never trusted from the capture side
    # (review BLOCKER 3), and bounded to the covered at-cut segment at BOTH ends.
    idx, flip_window_decodable = _moving_index_run_at_cut(
        index_samples,
        covered_until=b.get("releaseSplitIndex"),
        covered_from=first_covered_position,
        pre_key_index=(b.get("preKeySample") or {}).get("index"),
    )
    flip_index = idx.get("flipIndex")

    first_in_hold = min(in_hold_positions) if in_hold_positions else None
    in_hold_decodes = [seq[i] for i in in_hold_positions if i < len(seq)]
    _decoded = [v for v in in_hold_decodes if v is not None]
    # "Frozen" = the in-hold composite decodes are CONSTANT and match the cover's ACTUAL
    # painted content (coverPatchMean) — NOT the currentTime-derived staleIndexExpected,
    # which runs ahead of the presented frame by the video's presentation lag. Tying the
    # frozen composite to the cover's own pixels is lag-immune and stronger (it proves
    # the composite shows the cover); the decoder staying live (rvfcRanThroughHold)
    # proves the counter WOULD advance if it were not covered.
    cover_mean = nc.get("coverPatchMean")
    stale_ok = bool(
        in_hold_decodes
        and len(_decoded) == len(in_hold_decodes)
        and (max(_decoded) - min(_decoded)) <= STALE_INDEX_TOL
        and cover_mean is not None
        and abs(sum(_decoded) / len(_decoded) - cover_mean) <= COVER_MATCH_TOL
    )
    all_in_hold_measured = (
        bool(covered_positions)
        and bool(in_hold_positions)
        and rehandoff_exempt_ok
        and all(
            (sources[i] if i < len(sources) else None) == "measured"
            for i in in_hold_positions
        )
    )

    flip_index_present = isinstance(flip_index, int)
    n_total = idx.get("n")
    n_after = (n_total - flip_index) if (flip_index_present and isinstance(n_total, int)) else 0

    mc = _moving_continuity_derived(b) or {}
    stage_at_arm = nc.get("stageRectAtArm")
    stage_at_trigger = nc.get("stageRectAtTrigger")
    stage_geometry_stable = bool(
        stage_at_arm and stage_at_trigger
        and all(
            _finite(stage_at_arm.get(k)) is not None
            and _finite(stage_at_trigger.get(k)) is not None
            and abs(_finite(stage_at_arm.get(k)) - _finite(stage_at_trigger.get(k)))
            <= STAGE_ORIGIN_TOL_PX
            for k in ("x", "y", "w", "h")
        )
    )
    stage_origin = nc.get("stageOrigin") or {}
    stage_origin_zero = bool(
        _finite(stage_origin.get("x")) is not None
        and _finite(stage_origin.get("y")) is not None
        and abs(_finite(stage_origin["x"])) <= STAGE_ORIGIN_TOL_PX
        and abs(_finite(stage_origin["y"])) <= STAGE_ORIGIN_TOL_PX
    )
    all_cover = bool(raf_log) and all(r.get("elementFromPointIsCover") for r in raf_log)

    # Release ordering: the release happens MID-CAPTURE, so it must fall strictly
    # after the last covered instant and strictly before BOTH the first settled
    # sample and the burst (plan §10).
    burst_start = b.get("burstStartPerfMs")
    # The split is the at-cut segment's upper bound, so an absent or out-of-range
    # `releaseSplitIndex` is no bound at all; and the first post-split settled
    # instant is RE-DERIVED here from the samples, never accepted as absent
    # (review r9 MAJOR 3). The reported field must agree with the derivation.
    split_valid = (
        isinstance(release_split_index, int)
        and not isinstance(release_split_index, bool)
        and 0 <= release_split_index < len(index_samples)
    )
    # The last covered instant is the SPLIT SAMPLE's own clock, never the
    # capture's cached copy of it.
    last_at_cut = (
        _finite(index_samples[release_split_index].get("perfNowMs"))
        if split_valid else None
    )
    settled_after_split = (
        _slide4_settled_window(index_samples[release_split_index + 1:])
        if split_valid else []
    )
    settled_perfs = [s.get("perfNowMs") for s in settled_after_split]
    first_settled = (
        min(settled_perfs)
        if settled_perfs and all(
            isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(float(t))
            for t in settled_perfs
        )
        else None
    )
    release_ordered = bool(
        split_valid
        and release_at is not None
        and last_at_cut is not None
        and burst_start is not None
        and first_settled is not None
        and b.get("firstSettledPerfMs") == first_settled
        and b.get("lastAtCutPerfMs") == last_at_cut
        and last_at_cut < release_at
        and release_at < first_settled
        and release_at < burst_start
    )

    # --- The counter went RED for exactly the injected freeze -------------------
    checks["indexRunRed"] = idx.get("ok") is False
    checks["reasonFreezeRunAtCut"] = idx.get("reason") == "freeze run at cut"
    checks["freezeRunMargin"] = bool((idx.get("freezeRunAtCut") or 0) >= FREEZE_MIN_RUN)
    checks["noNegativeAnomaly"] = idx.get("negativeAnomaly") is False
    checks["flipIndexPresent"] = flip_index_present
    checks["flipWindowDecodable"] = flip_window_decodable
    checks["enoughAfterFlip"] = n_after >= FREEZE_MIN_AFTER

    # --- The decoder stayed LIVE through the freeze (RED isolated to counter) ----
    checks["movingContinuityOk"] = _moving_continuity_ok(b)
    checks["boundDecoderIsSlide3Decoder"] = (
        nc.get("boundDecoderId") is not None
        and nc.get("boundDecoderId") == b.get("ownerDecoderId")
    )
    # De-vacuumed (review MAJOR 4): once bound-by-id, ambiguity resolution never
    # re-runs, so "no ambiguous resolution" alone is vacuous. Require ALSO that
    # the bound element (a) never reported disconnected, (b) resolved on every
    # logged rAF, and (c) stayed the SAME element id for the whole hold.
    raf_bound_ids = [r.get("boundDecoderId") for r in raf_log]
    checks["noOwnerAmbiguousInWindow"] = bool(
        nc.get("ownerAmbiguousInWindow") is False
        and nc.get("ownerDisconnectedInWindow") is False
        and bool(raf_log)
        and all(r.get("ownerResolved") for r in raf_log)
        and nc.get("boundDecoderId") is not None
        and all(bid == nc.get("boundDecoderId") for bid in raf_bound_ids)
    )
    checks["rvfcRanThroughHold"] = bool(
        (mc.get("rvfcMonotonic") or {}).get("advance") is not None
        and (mc.get("rvfcMonotonic") or {}).get("advance") >= RVFC_MIN_ADVANCE_S
    )
    checks["playerBuildErrorsEmpty"] = (b.get("playerBuildErrors") == [])
    checks["bridgeEngaged"] = _bridge_engaged(b)

    # --- The freeze fired correctly, at the right moment, over the right target -
    # `firedVia == "moved"` is a MEASURED departure of the bound owner's rect from
    # its armed rect, and the poll only starts counting at the in-page advance
    # keydown -- so the trigger is bounded in DELIVERED FRAMES after the advance
    # (FREEZE_TRIGGER_MAX_RAFS), not by a wall-clock window the linear
    # interpolation would make meaningless.
    # ...and, because a delivered-frame count alone can hide unbounded elapsed
    # time (review r3 BLOCKER 3), a page-clock ceiling on the keydown->trigger
    # delay, plus agreement with the runtime's OWN fresh motion-start marker to
    # within a couple of callbacks. The frame count stays as secondary evidence.
    motion_started_frame = nc.get("motionStartedFrame")
    checks["firedAtMoveStart"] = bool(
        nc.get("firedVia") == "moved"
        and isinstance(trigger_frames, int)
        and 1 <= trigger_frames <= FREEZE_TRIGGER_MAX_RAFS
        and trigger_delay_ms is not None
        and trigger_delay_ms <= FREEZE_TRIGGER_MAX_DELAY_MS
    )
    # Frame proximity alone is not identity (review r4 MAJOR 1): a marker for
    # another boundary, or a replacement generation on the bound video, can also
    # produce a timely departure. The trigger's marker must be the SAME fresh
    # marker the poll first retained, and must name the 3->4 boundary.
    checks["firedAtRuntimeMotionStart"] = bool(
        isinstance(motion_started_frame, int)
        and isinstance(trigger_frames, int)
        and abs(trigger_frames - motion_started_frame) <= FREEZE_TRIGGER_MOTION_SLACK_FRAMES
        and motion_marker.get("atScene") == SLIDE4_MIN_HASH
        and motion_marker.get("started") is not None
        and motion_at_trigger.get("started") == motion_marker.get("started")
        and motion_marker.get("generation") is not None
        and motion_at_trigger.get("generation") == motion_marker.get("generation")
        and motion_at_trigger.get("atScene") == SLIDE4_MIN_HASH
    )
    checks["firedAfterAdvance"] = bool(
        advance_key_at is not None and trigger_delay_ms is not None and trigger_delay_ms >= 0.0
    )
    # The control's clock and the capture watch's must be the SAME EVENT, not two
    # ArrowRights: the control now filters as the watch does, so a shared
    # `timeStamp` identifies one trusted, non-repeat keydown, and anything the
    # control rejected means another ArrowRight reached the page (review r9
    # MAJOR 4). `atCutBoundaryValidAllArms` holds A1/A2 to the watch's own count.
    nc_rejected = nc.get("advanceKeyRejected")
    checks["advanceKeySameEventInControl"] = bool(
        _finite(advance_key_at) is not None
        and advance_key_at == b.get("advanceKeyPerfMs")
        and isinstance(nc_rejected, int)
        and not isinstance(nc_rejected, bool)
        and nc_rejected == 0
    )
    checks["noPreAdvanceDeparture"] = nc.get("preAdvanceDepartureAt") is None
    # A queued press -- one sent at the self-advancing scene, or one that never
    # landed -- is replayed by the player later and starts the 3->4 move by
    # itself, so a drain that was not clean makes the stimulus a different one in
    # ANY arm. RE-DERIVED from the counts, unlanded list and `hashAtArm`, held to
    # the cached booleans, and required of all three arms; fails closed on a
    # missing block (plan §10).
    drain = b.get("drain") or {}
    drains = {"a1": a1.get("drain"), "b": b.get("drain"), "a2": a2.get("drain")}
    checks["drainPressesAllLanded"] = all(_drain_clean(s) for s in (a1, b, a2))
    # Exactly one key, from the exact settled `#7`, landed, in ALL THREE arms
    # (review r3 MAJOR 1): a second queued press is replayed by the player and
    # makes the stimulus a different one, so the arms are no longer comparable.
    checks["advanceSinglePressAllArms"] = all(
        _advance_ok_derived(s.get("advance")) for s in (a1, b, a2)
    )
    checks["coverPaintedAtPresent"] = cover_painted_at is not None
    checks["stageGeometryStable"] = stage_geometry_stable
    checks["stageOriginZero"] = stage_origin_zero
    checks["noControlError"] = nc.get("error") is None
    checks["ownerReadyAtTrigger"] = bool(
        nc.get("ownerReadyState") is not None and nc.get("ownerReadyState") >= 2
    )
    # The stale frame must come from genuine playback (currentTime >= MIN_STALE_TIME_S),
    # NOT a t~0 unrendered black frame. NB: do NOT range-check cover_mean against [16,235]
    # — that is tv-range LUMA, while cover_mean is decoded RGB (a valid dark/bright counter
    # is not "out of alphabet"). everyInHoldStale ties the composite to cover_mean (both RGB).
    checks["staleFrameFromPlayback"] = bool(
        nc.get("staleCurrentTime") is not None and nc.get("staleCurrentTime") >= MIN_STALE_TIME_S
    )
    checks["paintedOnce"] = nc.get("paintCount") == 1
    checks["coverPatchStable"] = bool(
        nc.get("coverPatchStart") is not None
        and nc.get("coverPatchStart") == nc.get("coverPatchEnd")
    )
    checks["coverHitTest100"] = all_cover
    checks["coverTracksFootprint"] = _cover_tracks_footprint(raf_log)
    checks["loopLive"] = len(raf_ts) >= 10
    checks["everyInHoldStale"] = stale_ok
    checks["allInHoldMeasured"] = all_in_hold_measured
    checks["rehandoffPairSound"] = rehandoff_exempt_ok
    # The `#7` build's own animation outlasts the hash (plan §10.9), so a press
    # sent before the owner rect settles is a different stimulus. MAIN gates this
    # already; all three bracket arms are held to it too (review r5 MAJOR 2).
    settles = {k: s.get("ownerSettle") for k, s in (("a1", a1), ("b", b), ("a2", a2))}
    checks["ownerSettledAllArms"] = all(_owner_settle_ok(s) for s in settles.values())
    checks["releaseStrictlyBeforeSettleAndBurst"] = release_ordered
    # The page-side evidence series must be whole in EVERY arm: a truncated dump,
    # a ring drop, a non-monotonic or malformed row, or a sample the series does
    # not bracket would hand a capture its neighbours' owner/media rows (review r6
    # MAJOR 1). Same condition on all three arms -- a positive scored off a gapped
    # series is not comparable either -- and RE-DERIVED, then held to the cached `ok`.
    checks["collectorSeriesSound"] = all(
        bool((s.get("collector") or {}).get("ok")) and _collector_ok(s.get("collector") or {})
        for s in (a1, b, a2)
    )
    # ...and the press-relative cut must exist before anything is scored against
    # it: no keydown page clock, or a keydown later than every badge frame, is an
    # INVALID boundary, not index 0 (review r6 MAJOR 2).
    checks["atCutBoundaryValidAllArms"] = all(
        _at_cut_boundary_valid(s) for s in (a1, b, a2)
    )
    # ...and every capture must carry its own badge frame AND a measured geometry.
    # Only B's validated re-handoff pair may be non-measured (plan §10.12).
    checks["badgeSamplesSoundAllArms"] = (
        _badge_samples_sound(a1)
        and _badge_samples_sound(b, exempt_seqs if rehandoff_exempt_ok else None)
        and _badge_samples_sound(a2)
    )
    # An EMPTY rAF series has no gap to exceed the ceiling, so the bound must not
    # be satisfiable by absence: a series with nothing to bracket is not a gap
    # measurement at all (plan §10.12).
    checks["maxRafGapOk"] = (
        bool(raf_ts) and poll_gap_present and max_gap_ms <= MAX_RAF_GAP_MS
    )

    # --- Bracketing positives are GREEN ----------------------------------------
    # B's at-cut run is re-derived from B's own samples above; the positives' was
    # taken from the capture side's cached dict, so every sample field it rests on
    # could be deleted and the bracket still passed (round 12 sweep). Re-derived
    # here the same way, and required to AGREE with what the capture reported.
    def _positive_run_ok(s: dict) -> bool:
        run, _ = _moving_index_run_at_cut(
            s.get("indexSamples") or [],
            covered_until=s.get("releaseSplitIndex"),
            covered_from=(s.get("atCutBoundary") or {}).get("from"),
            pre_key_index=(s.get("preKeySample") or {}).get("index"),
        )
        return bool(run.get("ok")) and (s.get("movingIndexRunAtCut") or {}).get("ok") is True

    checks["positivesGreen"] = bool(
        a1.get("continueThroughMovingMagicMove3to4Pass")
        and a2.get("continueThroughMovingMagicMove3to4Pass")
        and _positive_run_ok(a1)
        and _positive_run_ok(a2)
    )

    # --- Isolation: every invariant sub-verdict GREEN and equal across A1/B/A2 --
    # (review MAJOR 4: equality alone let all-False-but-equal pass.)
    isolation_kwargs = {"evidence_cadence": evidence_cadence, "legacy_unrecorded_cadence": legacy_unrecorded_cadence}
    iv_a1, iv_b, iv_a2 = (
        _isolation_view(a1, **isolation_kwargs),
        _isolation_view(b, **isolation_kwargs),
        _isolation_view(a2, **isolation_kwargs),
    )
    isolation_diffs = {
        k: {"a1": iv_a1[k], "b": iv_b[k], "a2": iv_a2[k]}
        for k in _ISOLATION_KEYS
        if not (iv_a1[k] == iv_b[k] == iv_a2[k])
    }
    isolation_all_green = all(iv_a1[k] and iv_b[k] and iv_a2[k] for k in _ISOLATION_KEYS)
    checks["isolationEqual"] = (isolation_diffs == {}) and isolation_all_green

    # Two tiers. A FAIL is a claim about the COUNTER -- "a fully valid isolated
    # freeze was delivered and the counter did not catch it" -- so anything that
    # instead says "the stimulus or the measurement was not sound" is INCONCLUSIVE
    # (tier 1). Nothing is easier to PASS: every tier-1 key must still be True,
    # and `_freeze_control_blocks_success` blocks `success` on "inconclusive"
    # exactly as it does on "fail".
    integrity_keys = (
        "sampleSchemaSoundAllArms", "armIdentitiesMatchManifest",
        "firedAtMoveStart", "firedAtRuntimeMotionStart", "firedAfterAdvance",
        "advanceKeySameEventInControl", "noPreAdvanceDeparture", "drainPressesAllLanded", "advanceSinglePressAllArms",
        "coverPaintedAtPresent",
        "stageGeometryStable", "stageOriginZero", "noControlError",
        "ownerReadyAtTrigger", "staleFrameFromPlayback", "paintedOnce", "coverPatchStable",
        "coverHitTest100", "coverTracksFootprint", "loopLive", "everyInHoldStale",
        "flipIndexPresent", "flipWindowDecodable", "enoughAfterFlip",
        "releaseStrictlyBeforeSettleAndBurst", "allInHoldMeasured", "rehandoffPairSound",
        "ownerSettledAllArms", "bridgeEngaged",
        "collectorSeriesSound", "atCutBoundaryValidAllArms", "badgeSamplesSoundAllArms",
        "maxRafGapOk",
        "noNegativeAnomaly", "movingContinuityOk", "boundDecoderIsSlide3Decoder",
        "noOwnerAmbiguousInWindow", "rvfcRanThroughHold", "playerBuildErrorsEmpty",
        "positivesGreen", "isolationEqual",
    )
    verdict_keys = ("indexRunRed", "reasonFreezeRunAtCut", "freezeRunMargin")
    integrity_failed = [k for k in integrity_keys if not checks.get(k)]
    verdict_failed = [k for k in verdict_keys if not checks.get(k)]
    if integrity_failed:
        ok, verdict, reason = False, "inconclusive", f"hold integrity failed: {integrity_failed}"
    elif not verdict_failed:
        ok, verdict, reason = True, "pass", None
    else:
        ok, verdict, reason = False, "fail", f"gate checks failed: {verdict_failed}"
    failed = integrity_failed + verdict_failed
    return {
        "ok": ok,
        "verdict": verdict,
        "reason": reason,
        "checks": checks,
        "integrityKeys": list(integrity_keys),
        "integrityFailed": integrity_failed,
        "schemaFailed": {k: v for k, v in schema_failed.items() if v},
        "verdictFailed": verdict_failed,
        "failed": failed,
        "maxRafGapMs": max_gap_ms,
        "drain": drain,
        "drains": drains,
        "ownerSettles": settles,
        "collectors": {k: (s.get("collector") or {}) for k, s in (("a1", a1), ("b", b), ("a2", a2))},
        "atCutBoundaries": {
            k: (s.get("atCutBoundary") or {}) for k, s in (("a1", a1), ("b", b), ("a2", a2))
        },
        "isolationDiffs": isolation_diffs,
        "movingIndexRunAtCut": idx,
        "advances": {k: (s.get("advance") or {}) for k, s in (("a1", a1), ("b", b), ("a2", a2))},
        "freeze": {
            "holdStartedAt": hold_started,
            "coverPaintedAt": cover_painted_at,
            "firstCoveredPosition": first_covered_position,
            "rehandoffExemptSamples": exempt_prefix,
            "rehandoffPair": list(pair) if pair else None,
            "coveredPositions": covered_positions,
            "advanceKeyAt": advance_key_at,
            "advanceKeyRejected": nc_rejected,
            "triggerDelayMs": trigger_delay_ms,
            "triggerFramesAfterAdvance": trigger_frames,
            "motionStartedFrame": motion_started_frame,
            "motionStartedAt": nc.get("motionStartedAt"),
            "pollMaxGapMs": poll_max_gap_ms,
            "preAdvanceDepartureAt": nc.get("preAdvanceDepartureAt"),
            "loopHandedOff": nc.get("loopHandedOff"),
            "holdOffsetS": hold_offset_s,
            "releaseOffsetS": release_offset_s_nc,
            "inHoldPositions": in_hold_positions,
            "inHoldDecodes": in_hold_decodes,
            "firstInHold": first_in_hold,
            "flipIndex": flip_index,
            "nAfterFlip": n_after,
            "maxRafGapMs": max_gap_ms,
            "rafFrames": len(raf_ts),
            "coverHitTestAll": all_cover,
            "coverTracksFootprint": checks["coverTracksFootprint"],
            "paintCount": nc.get("paintCount"),
            "firedVia": nc.get("firedVia"),
            "fellBackToArmOwner": nc.get("fellBackToArmOwner"),
            "boundDecoderId": nc.get("boundDecoderId"),
            "armedElId": nc.get("armedElId"),
            "armedOwnerRect": nc.get("armedOwnerRect"),
            "movedFromRect": nc.get("movedFromRect"),
            "movedToRect": nc.get("movedToRect"),
            "obedMotionAtTrigger": nc.get("obedMotionAtTrigger"),
            "coverPatchMean": cover_mean,
            "ownerReadyState": nc.get("ownerReadyState"),
            "stageOrigin": stage_origin,
            "error": nc.get("error"),
        },
        "isolationViews": {"a1": iv_a1, "b": iv_b, "a2": iv_a2},
    }


def _freeze_control_blocks_success(verdict: str | None, bridge34_disabled: bool) -> bool:
    """Owner decision 8b: does this `freeze_control` verdict block overall
    `success`? "pass" never blocks; "skipped" blocks EXCEPT under
    `--disable-bridge34` (the only arm with nothing to freeze); every other
    verdict ("inconclusive", "fail", or anything unrecognised) blocks, same as
    today — never weaken this to a pass on an unrecognised verdict."""
    if verdict == "pass":
        return False
    if verdict == "skipped":
        return not bridge34_disabled
    return True
