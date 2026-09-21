"""Load-bearing tests for the Round-2 ownership/engagement fixes in
`scripts/p2_recovery_html_adversarial.py` (Codex r1 findings F3, F5, F6, and the
F1b fail-closed engagement gate).

These are pure-logic tests: they never launch Keynote, a browser, or the live
harness. The script lives under `scripts/` (not an installed package), so it is
loaded by file path; loading it runs its own `sys.path` inserts, which make its
sibling-script and `obed_edom` imports resolve.

Each test is deliberately explicit about the adversarial input it guards
against, so a regression that reopens a Codex defect fails a NAMED test.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_adversarial_module():
    """Import `p2_recovery_html_adversarial` by file path.

    scripts/ and src/ are placed on `sys.path` first so the module's top-level
    `from p2_alpha_spike import ...` / `from obed_edom... import ...` resolve
    during exec (the module also inserts these itself, but doing it here keeps
    the very first import lookup working under a bare pytest invocation).
    """
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "p2_recovery_html_adversarial", REPO / "scripts" / "p2_recovery_html_adversarial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p2 = _load_adversarial_module()

FOOTPRINT_W, FOOTPRINT_H = p2.MOVIE_ROI[2], p2.MOVIE_ROI[3]


# --------------------------------------------------------------------------- #
# Fixture builders — a minimal player_dir the texid deriver can walk.
# --------------------------------------------------------------------------- #
def _video_layer(
    object_id: str,
    texture: str,
    *,
    width: float = FOOTPRINT_W,
    height: float = FOOTPRINT_H,
    animations: list | None = None,
) -> dict:
    """One authored `isVideoLayer` node with a footprint-sized initialState.

    `object_id` is the Magic-Move-persistent identity used to fold steady
    textures by object (Codex F5); animations nest inside so their crossfade
    inherits this owner.
    """
    node: dict = {
        "id": object_id,
        "isVideoLayer": True,
        "texture": texture,
        "initialState": {"width": width, "height": height},
    }
    if animations:
        node["animations"] = animations
    return node


def _crossfade(frm: str, to: str, *, width: float = FOOTPRINT_W, height: float = FOOTPRINT_H) -> dict:
    """A `property=='contents'` poster-swap tween (the movie crossfade shape)."""
    return {
        "property": "contents",
        "initialState": {"width": width, "height": height},
        "from": {"texture": frm},
        "to": {"texture": to},
    }


def _magic_move(children: list) -> dict:
    """Wrap crossfade(s) in an `apple:magic-move-*` transition node — the authored
    marker that makes an enclosed `contents` crossfade a real poster swap (as
    opposed to a same-sized background tween). Keynote stores the boundary
    crossfade in a separate transition subtree from the steady `isVideoLayer`.
    """
    return {"type": "transition", "name": "apple:magic-move-implied-motion-path", "layers": children}


def _write_player(tmp_path: Path, slides: list[tuple[str, list]]) -> Path:
    """Write `assets/header.json` + per-slide `assets/<uuid>/<uuid>.json`.

    `slides` is ordered `[(uuid, events_list), ...]`; the first two entries are
    slide 1 and slide 2 (the 1->2 boundary the deriver resolves).
    """
    assets = tmp_path / "assets"
    assets.mkdir(parents=True)
    assets.joinpath("header.json").write_text(json.dumps({"slideList": [u for u, _ in slides]}))
    for uuid, events in slides:
        slide_dir = assets / uuid
        slide_dir.mkdir()
        slide_dir.joinpath(f"{uuid}.json").write_text(json.dumps({"events": events}))
    return tmp_path


# --------------------------------------------------------------------------- #
# F3 — texid provenance: no whole-deck spurious-tween fallback.
# --------------------------------------------------------------------------- #
def test_f3_spurious_same_sized_contents_tween_is_rejected(tmp_path):
    """A same-sized `contents` tween on slide 4 must NEVER become the 1->2
    boundary when no steady-anchored crossfade exists.

    Slides 1/2 carry the movie's steady textures A and B but NO Magic Move;
    slide 4 has the deck's only footprint-sized crossfade P->Q, but it is a plain
    (non-magic-move) `contents` tween. The deleted fallback used to promote that
    sole crossfade; the fix rejects it (not inside a Magic Move) => null + warning.
    """
    slides = [
        ("slide1", [_video_layer("obj-movie1", "A")]),
        ("slide2", [_video_layer("obj-movie1", "B")]),
        ("slide4", [_crossfade("P", "Q")]),  # NOT wrapped in _magic_move => rejected
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] is None
    assert result["outgoing"] == []
    assert result["incoming"] == []
    assert result.get("warning")
    # The spurious tween's textures must not have leaked into either slot.
    assert "P" not in result["outgoing"] and "Q" not in result["incoming"]


def test_f3_two_candidate_boundary_is_ambiguous_null_and_warning(tmp_path):
    """Two distinct magic-move footprint crossfades => unresolved boundary.

    Both A->B and C->D are footprint-sized poster swaps under a Magic Move.
    Neither can be named THE boundary, so the deriver fails closed with a warning
    and reports both candidates.
    """
    slides = [
        ("slide1", [_video_layer("obj-1", "A"), _video_layer("obj-2", "C")]),
        (
            "slide2",
            [
                _video_layer("obj-1", "B"),
                _video_layer("obj-2", "D"),
                _magic_move([_crossfade("A", "B"), _crossfade("C", "D")]),
            ],
        ),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] is None
    assert result["outgoing"] == [] and result["incoming"] == []
    assert result.get("warning")
    assert len(result.get("movieCrossfadeCandidates", [])) == 2


def test_f3_repeated_pair_provenance_is_preserved(tmp_path):
    """The SAME boundary pair repeated across slide JSONs stays one boundary,
    and every occurrence's provenance (slide uuid) is preserved — `set()` used
    to discard this, hiding that a pair repeated at multiple boundaries.
    """
    slides = [
        ("slide1", [_video_layer("obj-1", "A"), _magic_move([_crossfade("A", "B")])]),
        ("slide2", [_video_layer("obj-1", "B"), _magic_move([_crossfade("A", "B")])]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] == "movie1"
    slides_seen = sorted(o["slide"] for o in result["boundaryOccurrences"])
    assert slides_seen == ["slide1", "slide2"]


# --------------------------------------------------------------------------- #
# F5 — no steady folding; posters only. F2 — authored magic-move marker.
# --------------------------------------------------------------------------- #
def test_f5_no_steady_folding_only_posters(tmp_path):
    """No steady texture is folded (Codex r2 F5): outgoing/incoming are exactly
    the crossfade's `from`/`to` posters. A footprint-sized steady cannot be
    proven to belong to THIS movie by size, so a second same-sized movie's steady
    (and even this movie's own steady) is never included.

    The unique magic-move boundary is P->R; the deck also has same-sized steadys
    {A, X, B, Y}. Result must be exactly outgoing==[P], incoming==[R].
    """
    slides = [
        (
            "slide1",
            [_video_layer("obj-movie1", "A"), _video_layer("obj-movie2", "X")],
        ),
        (
            "slide2",
            [
                _video_layer("obj-movie1", "B"),
                _video_layer("obj-movie2", "Y"),
                _magic_move([_crossfade("P", "R")]),
            ],
        ),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] == "movie1"
    assert result["outgoing"] == ["P"]
    assert result["incoming"] == ["R"]
    for leaked in ("A", "X", "B", "Y"):
        assert leaked not in result["outgoing"] and leaked not in result["incoming"]


def test_f2_loose_magic_move_substring_name_is_not_a_transition(tmp_path):
    """Only the authored `apple:magic-move-*` transition marks a real poster swap
    (Codex r2 F2). A layer merely NAMED to contain 'magic-move' (e.g. a caption
    'not-a-magic-move-caption') must NOT make its footprint contents tween the
    boundary — it is not an apple:magic-move transition.
    """
    fake = {"type": "group", "name": "not-a-magic-move-caption", "layers": [_crossfade("P", "Q")]}
    slides = [
        ("slide1", [_video_layer("obj-m1", "A")]),
        ("slide2", [_video_layer("obj-m1", "B"), fake]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] is None
    assert result["outgoing"] == [] and result["incoming"] == []
    assert result.get("warning")


def test_f2_magic_move_name_on_non_transition_node_is_rejected(tmp_path):
    """A non-transition node bearing the accepted `apple:magic-move-*` name must
    NOT mark its crossfade as a Magic Move (Codex r3 F2). Only `type=='transition'`
    plus the name prefix qualifies.
    """
    group_with_mm_name = {
        "type": "group",  # NOT a transition
        "name": "apple:magic-move-implied-motion-path",
        "layers": [_crossfade("P", "Q")],
    }
    slides = [
        ("slide1", [_video_layer("obj-m1", "A")]),
        ("slide2", [_video_layer("obj-m1", "B"), group_with_mm_name]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] is None
    assert result["outgoing"] == [] and result["incoming"] == []
    assert result.get("warning")


def test_f5_unidentified_owner_folds_no_steady(tmp_path):
    """If the boundary endpoint's owner cannot be identified (id-less layer),
    fold no steady — keep just the crossfade from/to.
    """
    # No `id` on the video layers => owner is None => not foldable.
    slide1 = [{"isVideoLayer": True, "texture": "A", "initialState": {"width": FOOTPRINT_W, "height": FOOTPRINT_H}}]
    slide2 = [
        {"isVideoLayer": True, "texture": "B", "initialState": {"width": FOOTPRINT_W, "height": FOOTPRINT_H}},
        _magic_move([_crossfade("A", "B")]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, [("slide1", slide1), ("slide2", slide2)]))

    assert result["decoderKey"] == "movie1"
    assert result["outgoing"] == ["A"]
    assert result["incoming"] == ["B"]


def test_boundary_resolves_when_posters_absent_from_steady_state(tmp_path):
    """Regression (round-2): the REAL Keynote shape. The Magic Move poster swap's
    `from`/`to` textures (P->R) are transition-only — they never appear as the
    slide-1/2 steady `isVideoLayer` texture (S). Steady-texture anchoring would
    (and did) return null here; the magic-move structural marker must resolve it.
    `from`/`to` are the poster canvases; the steady S is not folded (P/R are not
    in any owner's steady set), so outgoing/incoming are exactly [P]/[R].
    """
    slides = [
        ("slide1", [_video_layer("obj-m1", "S")]),
        ("slide2", [_video_layer("obj-m1", "S"), _magic_move([_crossfade("P", "R")])]),
        ("slide3", [_video_layer("obj-m1", "S")]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] == "movie1"
    assert result["outgoing"] == ["P"]
    assert result["incoming"] == ["R"]
    assert result.get("warning") in (None, "")


# --------------------------------------------------------------------------- #
# F6(iv) — `_times` bound to ONE decoder, never max-of-sibling.
# --------------------------------------------------------------------------- #
def test_times_returns_bound_decoder_clock_not_max_of_siblings():
    """`_times(key='movie1', decoder_id=...)` must return the BOUND decoder's
    own clock, even when a sibling same-key decoder sits at a higher time.

    This test actually calls `_times`: reverting the `decoder_id` filter would
    make the bound call return the sibling's 9.0 and fail here.
    """
    samples = [
        {
            "videos": [
                {"src": "a/Untitled.mov", "currentTime": 1.0, "readyState": 2, "decoderId": "dec-A"},
                {"src": "b/Untitled.mov", "currentTime": 9.0, "readyState": 2, "decoderId": "dec-B"},
            ]
        }
    ]

    # Bound to the stalled decoder A: its own low clock, not the sibling max.
    assert p2._times(samples, "movie1", decoder_id="dec-A") == [1.0]
    # Bound to the advancing decoder B: its own clock.
    assert p2._times(samples, "movie1", decoder_id="dec-B") == [9.0]
    # Unbound same-key and 'primary' both take the max across siblings — the
    # very masking behavior the bound path must avoid.
    assert p2._times(samples, "movie1") == [9.0]
    assert p2._times(samples, "primary") == [9.0]


def test_times_bound_decoder_absent_is_none_not_sibling_clock():
    """When the bound decoder is not present in a sample, its clock is None —
    a sibling's higher clock must not stand in for it.
    """
    samples = [
        {"videos": [{"src": "b/Untitled.mov", "currentTime": 9.0, "readyState": 2, "decoderId": "dec-B"}]}
    ]
    assert p2._times(samples, "movie1", decoder_id="dec-A") == [None]


# --------------------------------------------------------------------------- #
# `_derive_movie_texids` — corrected model (2026-09-19): the resolved footprint
# magic-move `contents` poster swap is a MOTION-PATH Magic Move (1->2 or 3->4
# under outgoing-slide storage), NOT the 2->3 boundary (which is an apple:dissolve,
# not a Magic Move). A successful resolve is tagged `boundary == "motion-path-mm"`.
# --------------------------------------------------------------------------- #
def test_derive_movie_texids_labels_boundary_as_motion_path_mm(tmp_path):
    """Keynote stores a transition under its OUTGOING slide, so the only footprint
    magic-move `contents` poster swap is a motion-path Magic Move (1->2 or 3->4),
    not the 2->3 dissolve. A successful resolve is tagged
    `boundary == "motion-path-mm"` (provenance-only; no gate consumes it)."""
    slides = [
        ("slide1", [_video_layer("obj-m1", "S")]),
        ("slide2", [_video_layer("obj-m1", "S"), _magic_move([_crossfade("P", "R")])]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))
    assert result["decoderKey"] == "movie1"
    assert result["boundary"] == "motion-path-mm"
    assert result["outgoing"] == ["P"]
    assert result["incoming"] == ["R"]


# --------------------------------------------------------------------------- #
# `liveContinuity1to2` — fail-closed live-<video> continuity sub-verdict.
#
# Corrected model (handover CORRECTION 2026-09-18): the 1->2 movie is a live
# `<video>` at the footprint, NOT a fed 2D canvas. The gate passes iff ALL of:
#   - stableFootprintDecoder: exactly one non-null decoderId across the after
#     window (sceneHash != hash1);
#   - rvfcAdvance: the bound decoder's presentedMediaTime advances >0.05 on/after
#     the flip (min_hash == num(hash2)).
# motionAcrossFlip.ok is reported for provenance but is NOT gated: its crossing-
# pair pixel-MAE aliases to ~0 ("frozen crossing") on the disposable grating, so
# gating on it would reintroduce the parity-aliasing flake; the composited-motion
# proof is the top-level visible_motion.ok + index_run.ok (aliasing-immune burnt-in
# counter). The old deck-texid / 2d-context / incoming-feed-draw checks are DROPPED.
# --------------------------------------------------------------------------- #
RESTART = 6  # SLIDE3_MIN_HASH — upper-bounds the 1->2 window [num(hash2), RESTART)


def _flip_samples(decoder_id="dec-1", pre_decoder_id=None) -> list[dict]:
    """flip_samples spanning the PRE-flip footprint owner (#1) + the after-window
    (#2,#3, in [num(hash2)=2, RESTART=6)). `pre_decoder_id` defaults to `decoder_id`
    (continuity); set it to a different id to model a same-key HANDOFF (D1 before,
    D2 after)."""
    pre = pre_decoder_id if pre_decoder_id is not None else decoder_id
    return [
        {"sceneHash": "#1", "decoderId": pre},        # pre-flip footprint owner
        {"sceneHash": "#2", "decoderId": decoder_id},
        {"sceneHash": "#3", "decoderId": decoder_id},
    ]


def _advancing_presented(decoder_id="dec-1") -> list[dict]:
    """Media snapshots whose bound decoder's presentedMediaTime advances >0.05
    on/after the flip (`#2`, `#3` are both in-window for hash2 == "#2")."""
    return [
        {"sceneHash": "#2", "videos": [{"decoderId": decoder_id, "presentedMediaTime": 10.0}]},
        {"sceneHash": "#3", "videos": [{"decoderId": decoder_id, "presentedMediaTime": 10.5}]},
    ]


def _motion_healthy(decoder_id="dec-1", *, pixel_ok=True) -> dict:
    """A score_motion_across_flip result whose CROSSING IDENTITY fields hold (same
    decoded decoder + expected key immediately before and after the flip). `pixel_ok`
    is the (non-gated) crossing-MAE verdict `ok`."""
    return {
        "ok": pixel_ok,
        "crossingDecoded": True,
        "crossingDecoderStable": True,
        "crossingKeyOk": True,
        "crossingDecoderIds": [decoder_id, decoder_id],
    }


def test_live_continuity_passes_when_every_condition_holds():
    """Positive control: valid forward boundary + one stable footprint decoder +
    crossing identity + advancing presented time => ok, no failures. Proves the
    gate is not wired to always-fail."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), _advancing_presented(), "#1", "#2",
        restart_min_hash=RESTART,
    )
    assert verdict["ok"] is True
    assert verdict["failed"] == []
    assert verdict["boundDecoderId"] == "dec-1"
    assert verdict["rvfcAdvance"]["ok"] is True


def test_live_continuity_fails_closed_when_decoder_unstable():
    """Two different decoderIds across the after window => no single bound
    decoder => stableFootprintDecoder fails, and rvfcAdvance cascades closed
    (no decoder to bind the clock to)."""
    unstable = [
        {"sceneHash": "#2", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": "dec-2"},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), unstable, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]
    assert "rvfcAdvance" in verdict["failed"]
    assert verdict["boundDecoderId"] is None


def test_live_continuity_fails_closed_on_handoff():
    """A same-key HANDOFF (D1 owns the footprint before the flip, sibling D2 slides
    in after) must fail: post-flip stability + D2's already-advancing rVFC alone
    cannot see it, but crossingIdentity (pre-flip owner D1 != after-window owner D2)
    does. This is the fail-open hole the pixel-MAE de-gating would otherwise open."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples("dec-2", pre_decoder_id="dec-1"),
        _advancing_presented("dec-2"), "#1", "#2", restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "crossingIdentity" in verdict["failed"]
    # Post-flip stability + rVFC still individually hold — only crossing identity fails.
    assert "stableFootprintDecoder" not in verdict["failed"]
    assert "rvfcAdvance" not in verdict["failed"]
    assert verdict["boundDecoderId"] == "dec-2"


def test_live_continuity_fails_closed_on_prefix_parseable_boundary():
    """Boundary parsing is STRICT full-match: a malformed numeric-prefix hash like
    '#1junk' -> '#2junk' must NOT be accepted as a valid 1->2 boundary (the old
    prefix match read them as 1,2)."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), _advancing_presented(),
        "#1junk", "#2junk", restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "boundaryValid" in verdict["failed"]


def test_live_continuity_fails_closed_on_missing_pre_flip_owner():
    """No resolved PRE-flip footprint owner (flip_samples carry only after-window
    frames) cannot prove the owner is unchanged across the cut => crossingIdentity
    fails closed (never pass by absence of before-evidence)."""
    post_only = [
        {"sceneHash": "#2", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": "dec-1"},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), post_only, _advancing_presented(), "#1", "#2",
        restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "crossingIdentity" in verdict["failed"]


def test_live_continuity_tolerates_a_transient_null_owner():
    """A few transient unresolved (null) owner frames — the <video> briefly
    mid-remount during the fast MM animation — do NOT fail stability, as long as one
    distinct non-null owner covers a strong majority (>=70%) of the after-window."""
    jittery = [
        {"sceneHash": "#1", "decoderId": "dec-1"},  # pre-flip owner
        {"sceneHash": "#2", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": None},   # one transient jitter frame
        {"sceneHash": "#4", "decoderId": "dec-1"},
        {"sceneHash": "#4", "decoderId": "dec-1"},
    ]  # after-window 4/5 non-null = 0.8 >= 0.7, one distinct non-null owner
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), jittery, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is True
    assert "stableFootprintDecoder" not in verdict["failed"]
    assert verdict["boundDecoderId"] == "dec-1"


def test_live_continuity_rejects_ambiguous_null_masked_handoff():
    """A tolerated null must be a genuine ABSENCE gap, not a masked handoff. When a
    frame is flagged `ownerAmbiguous` (two decoders both cover the footprint — D1
    leaving + D2 arriving — or the bracket endpoints disagree), that after-frame must
    fail closed even at >=70% D1 coverage, rather than being tolerated as jitter."""
    masked = [
        {"sceneHash": "#1", "decoderId": "dec-1"},                          # pre-flip owner
        {"sceneHash": "#2", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": None, "ownerAmbiguous": True},     # D1+D2 both present
        {"sceneHash": "#4", "decoderId": "dec-1"},
        {"sceneHash": "#4", "decoderId": "dec-1"},
    ]  # 4/5 after non-null = 0.8, but one ambiguous (handoff-in-progress) frame
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), masked, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]


def test_live_continuity_fails_closed_on_mostly_unresolved_window():
    """A window that is mostly null (owner unresolved for the majority) fails: a
    single resolved frame cannot prove continuity (never pass by absence)."""
    mostly_null = [
        {"sceneHash": "#2", "decoderId": "dec-1"},
        {"sceneHash": "#3", "decoderId": None},
        {"sceneHash": "#3", "decoderId": None},
        {"sceneHash": "#4", "decoderId": None},
    ]  # 1/4 non-null = 0.25 < 0.7
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), mostly_null, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]


def test_live_continuity_fails_closed_on_null_decoder_id():
    """An unresolved footprint owner (null decoderId across the window) fails
    closed — never pass by absence of ownership."""
    nulls = [
        {"sceneHash": "#2", "decoderId": None},
        {"sceneHash": "#3", "decoderId": None},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), nulls, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]
    assert verdict["boundDecoderId"] is None


def test_live_continuity_fails_closed_on_empty_after_window():
    """No post-flip samples at all => stable decoder cannot be proven => fail
    (never pass by absence of data)."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), [], _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]


def test_live_continuity_excludes_restart_window_samples():
    """Samples at/after the 2->3 restart boundary (hn >= restart_min_hash) are NOT
    part of the 1->2 after-window: a decoder that only appears at #6 cannot earn
    the 1->2 finding (Codex boundary hole — the old restart upper-bound restored)."""
    at_restart = [
        {"sceneHash": "#6", "decoderId": "dec-1"},
        {"sceneHash": "#7", "decoderId": "dec-1"},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), at_restart, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "stableFootprintDecoder" in verdict["failed"]  # empty in-window after set


def test_live_continuity_fails_closed_when_presented_time_flat():
    """A stable bound decoder whose presentedMediaTime does NOT advance across
    the cut fails rvfcAdvance in isolation (the freeze this whole probe hunts)."""
    flat = [
        {"sceneHash": "#2", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.0}]},
        {"sceneHash": "#3", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.0}]},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), flat, "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]
    # Isolation: identity + crossing still held.
    assert "stableFootprintDecoder" not in verdict["failed"]
    assert "crossingIdentity" not in verdict["failed"]


def test_live_continuity_fails_closed_when_presented_time_absent():
    """No presented-time samples for the bound decoder => insufficient data =>
    rvfcAdvance fails closed (never pass by absence)."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), [], "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]


def test_live_continuity_fails_closed_on_rvfc_regression():
    """A bound decoder whose presentedMediaTime REGRESSES across the window (e.g.
    10.0 -> 1.0, a restart/seek) must NOT count as advance: ordered progression is
    required, not max-min (which read the rewind as +9.0)."""
    regress = [
        {"sceneHash": "#2", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.0}]},
        {"sceneHash": "#3", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 1.0}]},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), regress, "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]


def test_live_continuity_rvfc_bound_to_footprint_decoder_not_sibling():
    """A sibling same-key decoder advancing must NOT satisfy rvfcAdvance for a
    stalled bound decoder — only the bound decoder's OWN clock counts (no
    max-of-same-key masking)."""
    presented = [
        {
            "sceneHash": "#2",
            "videos": [
                {"decoderId": "dec-1", "presentedMediaTime": 10.0},  # bound
                {"decoderId": "dec-2", "presentedMediaTime": 20.0},  # sibling
            ],
        },
        {
            "sceneHash": "#3",
            "videos": [
                {"decoderId": "dec-1", "presentedMediaTime": 10.0},  # bound STALLED
                {"decoderId": "dec-2", "presentedMediaTime": 29.0},  # sibling advances
            ],
        },
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples("dec-1"), presented, "#1", "#2",
        restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]


def test_live_continuity_ignores_presented_advance_before_flip():
    """An advance seen only BEFORE the flip (hn < num(hash2)) is out of window;
    with a single in-window presented-time sample the advance is unprovable =>
    rvfcAdvance fails closed."""
    presented = [
        {"sceneHash": "#1", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 5.0}]},
        {"sceneHash": "#2", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.0}]},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), presented, "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]


def test_live_continuity_does_not_gate_on_motion_across_flip_pixel_ok():
    """The pixel crossing-MAE verdict `motionAcrossFlip.ok` is provenance-only, NOT
    gated: it aliases to ~0 on the grating fixture, so gating it would reintroduce
    the parity flake. With crossing IDENTITY + the real conditions holding, the
    verdict passes even when the pixel `ok` is False; it is still reported."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(pixel_ok=False), _flip_samples(), _advancing_presented(),
        "#1", "#2", restart_min_hash=RESTART,
    )
    assert verdict["ok"] is True
    assert verdict["failed"] == []
    assert "motionAcrossFlipOk" not in verdict["failed"]
    assert verdict["motionAcrossFlipOk"] is False  # reported, non-gating


def test_live_continuity_fails_closed_on_unparseable_hash2():
    """If hash2 cannot be parsed the 1->2 boundary cannot be placed => boundaryValid
    fails closed and rvfc cascades (never accepted by absence of a boundary)."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), _advancing_presented(), "#1", "bad",
        restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "boundaryValid" in verdict["failed"]
    assert "rvfcAdvance" in verdict["failed"]


def test_live_continuity_fails_closed_on_regressive_boundary():
    """A regressive advance (num(hash2) <= num(hash1), e.g. #1 -> #0) is NOT a
    forward entry into the 1->2 window => boundaryValid fails closed, even with
    moving pixels/decoder present at the regressed hash."""
    regressed_post = [
        {"sceneHash": "#0", "decoderId": "dec-1"},
    ]
    regressed_presented = [
        {"sceneHash": "#0", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.0}]},
        {"sceneHash": "#0", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.9}]},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), regressed_post, regressed_presented, "#1", "#0", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "boundaryValid" in verdict["failed"]


def test_live_continuity_fails_closed_on_unparseable_hash1():
    """An unparseable hash1 means we cannot place the window at all => boundaryValid
    fails closed (never pass by absence of a placeable boundary)."""
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), _advancing_presented(), "bad", "#2",
        restart_min_hash=RESTART,
    )
    assert verdict["ok"] is False
    assert "boundaryValid" in verdict["failed"]


def test_live_continuity_accepts_null_context_type():
    """A live `<video>` owner reports contextType=null; the gate must NOT require
    any 2D context or texid membership (the dropped model). Samples carrying
    contextType=None still pass when the real conditions hold."""
    flip = [
        {"sceneHash": "#1", "decoderId": "dec-1", "contextType": None},  # pre-flip owner
        {"sceneHash": "#2", "decoderId": "dec-1", "contextType": None},
        {"sceneHash": "#3", "decoderId": "dec-1", "contextType": None},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), flip, _advancing_presented(), "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is True
    assert verdict["failed"] == []


# --------------------------------------------------------------------------- #
# `movingContinuity3to4` — fail-closed positive control for the 3->4 moving
# Magic Move (playback continuity the export breaks, the PRESERVE bridge repairs).
#
# The owner authored 3->4 as continuity ("Play movie across slides"); the HTML
# export RESTARTS movie1 on a fresh decoder at the grown slide-4 footprint. The
# gate passes iff ALL of:
#   - boundaryValid: hash3/hash4 parse, num(hash4) > num(hash3), and
#     num(hash4) >= slide4_min_hash;
#   - stableSlide4Owner: exactly one non-null footprint owner across the after
#     window (hn >= num(hash4)), covering >=70%, no ambiguous frame;
#   - crossingIdentity: that owner IS the slide-3 movie decoder (anti-restart);
#   - rvfcMonotonic: that decoder's presentedMediaTime advances >0.05, no rewind.
# The export's fresh restart decoder differs from the slide-3 decoder and fails
# crossingIdentity -> RED, so the gate is honest, never a false pass.
# --------------------------------------------------------------------------- #
S4MIN = 8  # SLIDE4_MIN_HASH


def _owner_samples_34(decoder_id=4, ambiguous=False):
    """Owner samples in the slide-4 after-window (hn #8,#9 >= num(hash4)=8)."""
    return [
        {"sceneHash": "#8", "decoderId": decoder_id, "ownerAmbiguous": ambiguous},
        {"sceneHash": "#9", "decoderId": decoder_id, "ownerAmbiguous": ambiguous},
    ]


def _presented_34(decoder_id=4):
    """Media snapshots whose slide-4 owner's presentedMediaTime advances >0.05."""
    return [
        {"sceneHash": "#8", "videos": [{"decoderId": decoder_id, "presentedMediaTime": 1.6}]},
        {"sceneHash": "#9", "videos": [{"decoderId": decoder_id, "presentedMediaTime": 2.4}]},
    ]


def test_moving_continuity_passes_when_bridged_decoder_continues():
    """Positive control: the slide-3 decoder (4) owns the slide-4 footprint with a
    monotonic clock => ok, no failures. Proves the gate is not wired to always-fail."""
    verdict = p2.movingContinuity3to4(
        _owner_samples_34(4), _presented_34(4), 4, "#7", "#8", S4MIN
    )
    assert verdict["ok"] is True
    assert verdict["failed"] == []
    assert verdict["slide4Owner"] == 4
    assert verdict["rvfcMonotonic"]["ok"] is True


def test_moving_continuity_fails_closed_on_export_restart():
    """The export's fresh autoplay-from-0 element is a DIFFERENT decoder (6) than
    the slide-3 decoder (4): crossingIdentity fails => RED. This is the honest
    RED-without-the-bridge case."""
    verdict = p2.movingContinuity3to4(
        _owner_samples_34(6), _presented_34(6), 4, "#7", "#8", S4MIN
    )
    assert verdict["ok"] is False
    assert "crossingIdentity" in verdict["failed"]


def test_moving_continuity_fails_closed_when_no_slide4_owner():
    """No decoder owns the slide-4 footprint (all null — e.g. the restart element
    drifted off the slot): stableSlide4Owner + crossingIdentity + rvfcMonotonic all
    cascade closed."""
    null_owner = [
        {"sceneHash": "#8", "decoderId": None, "ownerAmbiguous": False},
        {"sceneHash": "#9", "decoderId": None, "ownerAmbiguous": False},
    ]
    verdict = p2.movingContinuity3to4(null_owner, [], 4, "#7", "#8", S4MIN)
    assert verdict["ok"] is False
    assert "stableSlide4Owner" in verdict["failed"]
    assert "crossingIdentity" in verdict["failed"]
    assert "rvfcMonotonic" in verdict["failed"]


def test_moving_continuity_fails_closed_on_ambiguous_owner():
    """An ambiguous frame (two decoders at the slot — a handoff in flight) must not
    be tolerated: stableSlide4Owner fails closed."""
    verdict = p2.movingContinuity3to4(
        _owner_samples_34(4, ambiguous=True), _presented_34(4), 4, "#7", "#8", S4MIN
    )
    assert verdict["ok"] is False
    assert "stableSlide4Owner" in verdict["failed"]


def test_moving_continuity_fails_closed_when_not_reaching_slide4():
    """If the after hash never reaches slide 4 (num(hash4) < slide4_min_hash), the
    boundary is invalid and the gate fails closed (never pass by absence)."""
    verdict = p2.movingContinuity3to4(
        _owner_samples_34(4), _presented_34(4), 4, "#7", "#7", S4MIN
    )
    assert verdict["ok"] is False
    assert "boundaryValid" in verdict["failed"]


def test_moving_continuity_fails_closed_on_rvfc_rewind():
    """The bound decoder is stable and identity matches, but its presentedMediaTime
    RESETS/rewinds (a restart signature even under the same reported id) => the
    rvfcMonotonic check fails closed."""
    rewind = [
        {"sceneHash": "#8", "videos": [{"decoderId": 4, "presentedMediaTime": 2.4}]},
        {"sceneHash": "#9", "videos": [{"decoderId": 4, "presentedMediaTime": 0.05}]},
    ]
    verdict = p2.movingContinuity3to4(_owner_samples_34(4), rewind, 4, "#7", "#8", S4MIN)
    assert verdict["ok"] is False
    assert "rvfcMonotonic" in verdict["failed"]
# `_score_freeze_control` — Phase-2 A-B-A composited-freeze verdict (pure logic),
# re-bracketed at the 3->4 moving Magic Move (the 1->2 carry is refused, so there
# is no carried movie to freeze there — see
# `.agents/plans/p2_freeze_control_3to4.plan.md`).
#
# Arm A holds a partial stale cover, tracking the MOVING measured footprint, over
# the burnt-in counter for the middle run only, so `movingIndexRunAtCut` goes RED
# ("freeze run at cut") while the bridged decoder + rVFC stay live. PASS requires
# the RED to be exactly the injected freeze AND every other sub-verdict identical
# (and GREEN) across the two bracketing positives. A hold that never fired is
# INCONCLUSIVE (never PASS/FAIL): a silently-unfired hold would masquerade as a
# passing positive and be misread as "the counter gate is vacuous".
#
# Fixtures below are built through ONE small builder (`_build_snapshot_34`,
# review MAJOR 6a) that mirrors `_capture_3to4_snapshot`'s POST-SPLIT shape: a
# fixed run of pre-flip (#7) samples, an AT-CUT window (#8, progress<0.98, B's
# frozen values live here), then a SETTLED window (#8, progress>=0.98) that is
# ALWAYS built from the caller's `settled_indices` regardless of arm — for a
# genuine freeze that is a CLEAN, ADVANCING sequence in B too (the cover is
# released before it, review Blocker 3), so `settledIndexProgressionOk` comes
# out green in all three arms, letting `isolationEqual` actually be satisfiable
# by a real freeze. `movingIndexRunAtCut`/`settledIndexProgression` are computed
# by calling the SAME scorer functions the script calls, not hand-typed.
# --------------------------------------------------------------------------- #
# Pre-ADVANCE samples: still `#7`, cover not up, counter live in every arm.
_PRE_ADVANCE_INDICES_34 = (31, 32, 33)
# ...then the COVERED PRE-FLIP samples. The hash sits at `#7` for the WHOLE ~2 s
# 3->4 move, so the cover goes up well BEFORE the flip and these are already
# frozen in B. Modelling them is what makes the fixture the live shape: the
# scored window opens at `coverPaintedAt`, not at the flip.
_COVERED_PRE_FLIP_N_34 = 3
FREEZE_FLIP_INDEX_34 = len(_PRE_ADVANCE_INDICES_34) + _COVERED_PRE_FLIP_N_34
# The at-cut segment is the flip sample plus FREEZE_MIN_AFTER samples STRICTLY
# after it (review BLOCKER 3), so the capture's release split lands here:
FREEZE_SPLIT_INDEX_34 = FREEZE_FLIP_INDEX_34 + p2.FREEZE_MIN_AFTER
# ONE browser clock (review BLOCKER 2). Pre-advance samples precede the advance
# keydown; the trigger fires one delivered frame after it.
ADVANCE_KEY_AT_34 = 850.0
HOLD_STARTED_AT_34 = 870.0
# The cover is painted AFTER the <=150 ms owner-readiness retry, so it is a
# distinct, LATER instant than the trigger (review r3 BLOCKER 2). Samples from
# perf 900 on are at or after it; the pre-advance ones (700..800) are not.
COVER_PAINTED_AT_34 = 880.0


def _capture_samples_34(at_cut_indices, settled_indices, covered_pre_flip):
    samples: list[dict] = []
    perf = 700.0
    offset = -0.35
    for v in _PRE_ADVANCE_INDICES_34:
        samples.append({"index": v, "sceneHash": "#7", "captureOffsetS": round(offset, 2),
                        "perfNowMs": perf, "progress": 0.0, "footprintSource": "measured"})
        perf += 50.0
        offset += 0.05
    perf = 900.0
    offset = -0.15
    for v in covered_pre_flip:
        samples.append({"index": v, "sceneHash": "#7", "captureOffsetS": round(offset, 2),
                        "perfNowMs": perf, "progress": 0.0, "footprintSource": "measured"})
        perf += 50.0
        offset += 0.05
    offset = 0.05
    for v in at_cut_indices:
        samples.append({"index": v, "sceneHash": "#8", "captureOffsetS": round(offset, 2),
                        "perfNowMs": perf, "progress": 0.3, "footprintSource": "measured"})
        perf += 50.0
        offset += 0.05
    release_perf = samples[FREEZE_SPLIT_INDEX_34]["perfNowMs"] + 25.0
    for v in settled_indices:
        samples.append({"index": v, "sceneHash": "#8", "captureOffsetS": round(offset, 2),
                        "perfNowMs": perf, "progress": 0.99, "footprintSource": "measured"})
        perf += 50.0
        offset += 0.05
    return samples, release_perf, perf + 100.0


def _build_snapshot_34(at_cut_indices, settled_indices, *, frozen: bool,
                       covered_pre_flip=None) -> dict:
    if covered_pre_flip is None:
        first = at_cut_indices[0]
        covered_pre_flip = (
            (first,) * _COVERED_PRE_FLIP_N_34 if frozen
            else tuple(first - _COVERED_PRE_FLIP_N_34 + i for i in range(_COVERED_PRE_FLIP_N_34))
        )
    samples, release_perf, burst_perf = _capture_samples_34(
        at_cut_indices, settled_indices, covered_pre_flip
    )
    # Through the REAL helper (review MAJOR 6): no hand-set flip/decodable flags.
    # The capture side does NOT know `coverPaintedAt` (it has no null control in
    # two of the three arms), so it scores the whole covered_until segment; only
    # the SCORER re-runs it with `covered_from`.
    moving_index_run_at_cut, flip_window_decodable = p2._moving_index_run_at_cut(
        samples, covered_until=FREEZE_SPLIT_INDEX_34
    )
    settled_index_progression = p2.score_index_progression(list(settled_indices))
    settled = samples[FREEZE_SPLIT_INDEX_34 + 1:]
    snap = {
        "hash3": "#7", "hash4": "#8",
        "armHash": "#7",
        "armResult": {
            "ok": True, "armedElId": 4, "armedHash": "#7", "stageOrigin": {"x": 0.0, "y": 0.0},
            "armedOwnerRect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
            "stageRectAtArm": {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
        },
        # A clean drain: five presses from #1..#5, all landed, then the player's
        # own #6 -> #7 self-advance left the arm boundary exact.
        "drain": {
            "pressesSent": 5, "pressesLanded": 5, "unlandedFromHash": [],
            "selfAdvanceHash": "#6", "hashAtArm": "#7",
            "allPressesLanded": True, "hashAtArmExact": True, "ok": True,
        },
        # Exactly ONE advance key, sent from the exact settled `#7`, landed.
        "advance": {
            "pressesSent": 1, "pressesLanded": 1, "unlandedFromHash": [],
            "outstandingAtEnd": None, "pressingStopped": False,
            "finalHash": "#9", "pressHash": "#7", "ok": True,
        },
        "movingIndexRunAtCut": moving_index_run_at_cut,
        "flipWindowDecodable": flip_window_decodable,
        "indexSamples": samples,
        "settledIndexProgression": settled_index_progression,
        "movingContinuity3to4": {
            "ok": True, "failed": [], "slide4Owner": 4, "slide3MovieDecoder": 4,
            "boundaryValid": {"ok": True, "n3": 7, "n4": 8, "slide4Min": 8},
            "stableSlide4Owner": {"ok": True},
            "crossingIdentity": {"ok": True},
            "rvfcMonotonic": {"ok": True, "advance": 1.2},
        },
        "footprintFullyLive": {"ok": True},
        "continueThroughMovingMagicMove3to4Pass": not frozen,
        "indexSequence": [s["index"] for s in samples],
        "footprintSources": [s["footprintSource"] for s in samples],
        "captureOffsets": [s["captureOffsetS"] for s in samples],
        "ownerDecoderId": 4,
        "playerBuildErrors": [],
        "bridgeEngaged": True,
        "bridgeEvents": [],
        "nullControl": None,
        "releaseSplitIndex": FREEZE_SPLIT_INDEX_34,
        "lastAtCutHoldOffsetS": samples[FREEZE_SPLIT_INDEX_34]["captureOffsetS"],
        "lastAtCutPerfMs": samples[FREEZE_SPLIT_INDEX_34]["perfNowMs"],
        "releaseOffsetS": samples[FREEZE_SPLIT_INDEX_34]["captureOffsetS"] + 0.02,
        "releasePerfMs": release_perf,
        "firstSettledOffsetS": settled[0]["captureOffsetS"] if settled else None,
        "firstSettledPerfMs": settled[0]["perfNowMs"] if settled else None,
        "burstStartOffsetS": 1.5,
        "burstStartPerfMs": burst_perf,
    }
    snap["_releasePerfForNullControl"] = release_perf  # test-only scratch, popped by callers
    return snap


def _positive_snap_34(**overrides) -> dict:
    snap = _build_snapshot_34(
        [37, 38, 39, 40, 41, 42, 43], [50, 51, 52, 53, 54, 55, 56], frozen=False
    )
    snap.pop("_releasePerfForNullControl", None)
    snap.update(overrides)
    return snap


def _freeze_b_snap_34(at_cut=None, settled=None, covered_pre_flip=None, **overrides) -> dict:
    snap = _build_snapshot_34(
        at_cut or [40] * 7,
        settled or [50, 51, 52, 53, 54, 55, 56],
        frozen=True,
        covered_pre_flip=covered_pre_flip,
    )
    release_perf = snap.pop("_releasePerfForNullControl")
    raf = [
        {
            "t": HOLD_STARTED_AT_34 + 20.0 * i, "elementFromPointIsCover": True,
            "ownerResolved": True,
            "coverRect": {"x": 300.0, "y": 700.0, "w": 200.0, "h": 350.0},
            "measuredRect": {"x": 300.0, "y": 700.0, "w": 500.0, "h": 350.0},
            "boundDecoderId": 4,
        }
        for i in range(45)
    ]
    snap["nullControl"] = {
        "status": "released", "holdStartedAt": HOLD_STARTED_AT_34, "firedVia": "moved",
        "coverPaintedAt": COVER_PAINTED_AT_34,
        "advanceKeyAt": ADVANCE_KEY_AT_34, "triggerFramesAfterAdvance": 1,
        "motionStartedAt": HOLD_STARTED_AT_34, "motionStartedFrame": 1,
        # The COMPLETE first fresh marker the poll retained; the trigger's marker
        # must be the same one, for the 3->4 boundary (review r4 MAJOR 1).
        "motionStartedMarker": {
            "started": HOLD_STARTED_AT_34, "generation": 1, "atScene": 8,
        },
        "pollMaxGapMs": 17.0,
        "preAdvanceDepartureAt": None, "preAdvanceDepartureRect": None,
        "loopHandedOff": True,
        "releaseAt": release_perf,
        "staleIndexExpected": 40, "staleCurrentTime": 1.33,
        "ownerReadyState": 4, "coverPatchMean": 40.0,
        "paintCount": 1, "coverPatchStart": {"sum": 12345, "mean": 40.0},
        "coverPatchEnd": {"sum": 12345, "mean": 40.0},
        "ownerAmbiguousInWindow": False, "ownerDisconnectedInWindow": False,
        "boundDecoderId": 4, "armedElId": 4,
        "armedOwnerRect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
        "movedFromRect": {"x": 100.0, "y": 200.0, "w": 300.0, "h": 200.0},
        "movedToRect": {"x": 110.0, "y": 205.0, "w": 305.0, "h": 205.0},
        "obedMotionAtTrigger": {"started": HOLD_STARTED_AT_34, "generation": 1, "atScene": 8},
        "fellBackToArmOwner": False, "rafLog": raf, "error": None,
        "stageOrigin": {"x": 0.0, "y": 0.0},
        "stageRectAtArm": {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
        "stageRectAtTrigger": {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0},
    }
    snap.update(overrides)
    return snap


def _with_sample(snap: dict, i: int, **fields) -> dict:
    """Replace one capture sample, keeping the derived views consistent."""
    samples = [dict(s) for s in snap["indexSamples"]]
    samples[i].update(fields)
    snap["indexSamples"] = samples
    snap["indexSequence"] = [s["index"] for s in samples]
    snap["footprintSources"] = [s["footprintSource"] for s in samples]
    return snap


# --- `_couple_owner_rect` (pure) ------------------------------------------- #
_R = {"x": 100.0, "y": 200.0, "w": 300.0, "h": 150.0}


def test_couple_owner_rect_none_when_both_reads_missing():
    assert p2._couple_owner_rect(None, None) == {"source": "none"}


@pytest.mark.parametrize("before,after", [(_R, None), (None, _R)])
def test_couple_owner_rect_unstable_when_one_read_missing(before, after):
    """One missing read cannot couple pixels to a rect -- never `measured`."""
    assert p2._couple_owner_rect(before, after)["source"] == "unstable"


def test_couple_owner_rect_measured_exactly_at_tolerance():
    """The boundary is inclusive: a shift of exactly FOOTPRINT_COUPLE_TOL_PX on
    every edge still couples, and the FIRST rect is the one kept (the page's own
    unquantised record of the frame, of which the badge is an encoding)."""
    after = {k: v + p2.FOOTPRINT_COUPLE_TOL_PX for k, v in _R.items()}
    out = p2._couple_owner_rect(_R, after)
    assert out["source"] == "measured"
    assert (out["x"], out["y"], out["w"], out["h"]) == (_R["x"], _R["y"], _R["w"], _R["h"])


def test_couple_owner_rect_unstable_just_past_tolerance():
    after = {**_R, "x": _R["x"] + p2.FOOTPRINT_COUPLE_TOL_PX + 0.01}
    out = p2._couple_owner_rect(_R, after)
    assert out["source"] == "unstable"
    assert out["before"] == _R and out["after"] == after


# --- single-press advance discipline (`_advance_press_decision`) ------------ #
def _drive_presses(hashes, *, dt=0.1):
    """Replay a hash timeline through the decision helper, one capture sample
    per entry, and return (state, the sample indices at which a press was sent)."""
    st = p2._new_advance_press_state()
    pressed = []
    for i, hn in enumerate(hashes):
        st, press = p2._advance_press_decision(hn, st, i * dt)
        if press:
            pressed.append(i)
    return st, pressed


def test_advance_press_sends_exactly_one_press_across_the_whole_move():
    """The measured defect (round 3, item D): the hash sits at `#7` for the WHOLE
    ~2 s 3->4 move, so a timer-based re-press sent 2-3 more, all of which the
    player queued and replayed (snapshots ended at `#10`). Exactly ONE press may
    leave, at the first sample, and none while the move is in flight."""
    move = [7] * 20 + [9] * 30
    st, pressed = _drive_presses(move)
    assert pressed == [0]
    assert st["sent"] == 1 and st["landed"] == 1
    assert st["unlanded"] == [] and st["stopped"] is False
    assert st["atHash"] is None


def test_advance_press_never_drains_from_below_the_advance_boundary():
    """Review r3 MAJOR 1. The OLD behaviour drained from below and could send
    TWO presses before `#8`: entering at the self-advancing `#6` sent a key the
    player cannot honour and QUEUES; when the player's own `#6 -> #7`
    self-advance arrived, the helper counted it as that press landing and
    immediately sent another at `#7`. The player then replayed the queued one --
    a contaminated multi-advance stimulus that finding 13 could still green on.
    Now nothing leaves below the exact `#7`, and the run that entered low is
    visibly a no-advance run rather than a silently doubled one."""
    st, pressed = _drive_presses([5, 5, 6, 6, 6])
    assert pressed == [] and st["sent"] == 0
    assert p2._advance_gate(st, "#6")["ok"] is False

    st, pressed = _drive_presses([5, 5, 6, 6, 7, 7, 7, 9, 9])
    assert pressed == [4], "the ONLY press may be the one sent from the exact #7"
    assert st["sent"] == 1 and st["landed"] == 1
    assert p2._advance_gate(st, "#9")["ok"] is True


def test_advance_gate_fails_closed_on_every_contaminated_shape():
    """The gate is what finding 13 and the bracket hang on, so walk each way a
    stimulus can be wrong."""
    clean = {"atHash": None, "wall": None, "sent": 1, "landed": 1,
             "unlanded": [], "stopped": False}
    assert p2._advance_gate(clean, "#8")["ok"] is True
    assert p2._advance_gate({**clean, "sent": 2, "landed": 2}, "#8")["ok"] is False
    assert p2._advance_gate({**clean, "landed": 0}, "#8")["ok"] is False
    assert p2._advance_gate({**clean, "atHash": 7}, "#8")["ok"] is False
    assert p2._advance_gate({**clean, "unlanded": [7]}, "#8")["ok"] is False
    assert p2._advance_gate({**clean, "stopped": True}, "#8")["ok"] is False
    assert p2._advance_gate({**clean, "sent": 0, "landed": 0}, "#8")["ok"] is False
    assert p2._advance_gate(clean, "#7")["ok"] is False, "never reached slide 4"
    assert p2._advance_gate(clean, None)["ok"] is False


class _RectChrome:
    """Minimal CDP stand-in for `_read_bound_owner_rect`: replays a scripted
    series of owner rects, one per `evaluate()`."""

    def __init__(self, rects, then_moving: bool = False):
        self._rects = list(rects)
        self._then_moving = then_moving
        self.calls = 0

    async def evaluate(self, _script):
        if self.calls < len(self._rects):
            rect = self._rects[self.calls]
        elif self._then_moving:
            rect = _moving_rect(self.calls)
        else:
            rect = self._rects[-1]
        self.calls += 1
        return {"t": 100.0 + 16.7 * self.calls, "rect": rect}


def _moving_rect(i: int, step: float = 4.0):
    return {"x": 198.0 + step * i, "y": 797.0, "w": 952.0, "h": 268.0}


def _moving_rects(n: int):
    return [_moving_rect(i) for i in range(n)]


def _settle(chrome, el_id="el4", monkeypatch=None):
    monkeypatch.setattr(p2, "OWNER_SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(p2, "OWNER_SETTLE_S", 0.5)
    return asyncio.run(p2._settle_bound_owner_rect(chrome, el_id))


def test_owner_rect_settle_rejects_a_still_moving_hash_7_build(monkeypatch):
    """Review r4 MAJOR 2. The hash reaching `#7` proves an instantaneous value,
    not a settled build: the `#7` build's own animation is still running, so a
    press sent there is a press during residual motion. Three CONSECUTIVE
    agreeing rect reads are required, and a moving rect never gets them."""
    chrome = _RectChrome(_moving_rects(4), then_moving=True)
    got = _settle(chrome, monkeypatch=monkeypatch)
    assert got["settled"] is False
    assert got["stableReadings"] < p2.OWNER_SETTLE_READINGS


def test_owner_rect_settle_accepts_a_stopped_build(monkeypatch):
    """...and a stopped rect settles, on exactly the `_couple_owner_rect`
    "measured" agreement the at-cut samples are held to."""
    still = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}
    chrome = _RectChrome(_moving_rects(2) + [still] * 8)
    got = _settle(chrome, monkeypatch=monkeypatch)
    assert got["settled"] is True
    assert got["stableReadings"] == p2.OWNER_SETTLE_READINGS
    assert got["rect"] == still


def test_owner_rect_settle_fails_closed_without_a_bound_owner(monkeypatch):
    """No bind, no settle -- and no round trips either."""
    chrome = _RectChrome([None])
    got = _settle(chrome, el_id=None, monkeypatch=monkeypatch)
    assert got["settled"] is False
    assert chrome.calls == 0


def test_advance_press_never_re_presses_while_one_is_outstanding():
    """A press outstanding for many samples (the move, at 0.1 s per sample) must
    not be joined by a second one before `DRAIN_PRESS_LAND_S`."""
    n = int(p2.DRAIN_PRESS_LAND_S / 0.1)
    st, pressed = _drive_presses([7] * n)
    assert pressed == [0] and st["sent"] == 1
    assert st["atHash"] == 7 and st["landed"] == 0


def test_advance_press_stops_for_good_once_a_press_fails_to_land():
    """An unlanded press is a press the player may still be holding: record it
    and STOP. Re-pressing is precisely the defect being fixed."""
    n = int(p2.DRAIN_PRESS_LAND_S / 0.1) + 5
    st, pressed = _drive_presses([7] * n)
    assert pressed == [0]
    assert st["stopped"] is True and st["unlanded"] == [7]
    assert st["sent"] == 1 and st["landed"] == 0


def test_advance_press_does_not_press_once_slide_four_is_reached():
    st, pressed = _drive_presses([9, 9, 9])
    assert pressed == [] and st["sent"] == 0


def test_advance_press_ignores_an_unreadable_hash():
    """A transient unparseable route hash is not evidence that a press is due."""
    st, pressed = _drive_presses([None, None, 7, 7, 9])
    assert pressed == [2]
    assert st["sent"] == 1 and st["landed"] == 1


# --- footprint badge: the rect the CAPTURED FRAME actually shows ------------ #
def _render_badge(seq: int, rect: dict, *, cell: int | None = None,
                  magic: int | None = None, height: int = 40, width: int = 1920,
                  corrupt_crc: bool = False):
    """Render the badge exactly as FOOTPRINT_BADGE_JS paints it: an 8-bit magic
    prefix, then seq/x/y/w/h as 16 MSB-first bits each, then an 8-bit CRC over
    those five words; one flat black-or-white cell per bit, in a single row at
    the viewport origin."""
    cell = p2.FOOTPRINT_BADGE_CELL_PX if cell is None else cell
    magic = p2.FOOTPRINT_BADGE_MAGIC if magic is None else magic
    bits = [(magic >> i) & 1 for i in range(7, -1, -1)]
    words = []
    for name in p2.FOOTPRINT_BADGE_FIELDS:
        raw = seq if name == "seq" else rect[name]
        n = max(0, min(65535, int(round(raw * (1 if name == "seq" else p2.FOOTPRINT_BADGE_Q)))))
        words.append(n)
        bits += [(n >> i) & 1 for i in range(15, -1, -1)]
    crc = p2._footprint_badge_crc8(words) ^ (0xFF if corrupt_crc else 0x00)
    bits += [(crc >> i) & 1 for i in range(7, -1, -1)]
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    for c, bit in enumerate(bits):
        arr[0:cell, c * cell:(c + 1) * cell, :3] = 255 if bit else 0
    return arr


def test_decode_footprint_badge_round_trips_a_moving_rect():
    """The badge is the whole point of item B: a rect in FAST motion must still
    come back out of the frame it was painted into, to quarter-pixel accuracy."""
    rect = {"x": 327.25, "y": 709.75, "w": 1266.5, "h": 356.0}
    out = p2._decode_footprint_badge(_render_badge(4321, rect))
    assert out is not None
    assert out["seq"] == 4321
    for k, v in rect.items():
        assert out[k] == pytest.approx(v, abs=1.0 / p2.FOOTPRINT_BADGE_Q)


def test_decode_footprint_badge_quantisation_is_far_inside_the_couple_tolerance():
    """The badge encodes quarter-pixels, so page-record vs painted-pixels can
    never be pushed past FOOTPRINT_COUPLE_TOL_PX by the encoding itself -- the
    tolerance stays free to catch a genuinely wrong or stale frame."""
    rect = {"x": 198.123456, "y": 797.987654, "w": 951.531250, "h": 267.609375}
    decoded = p2._decode_footprint_badge(_render_badge(7, rect))
    out = p2._couple_owner_rect(rect, {k: decoded[k] for k in ("x", "y", "w", "h")})
    assert out["source"] == "measured"
    assert max(abs(decoded[k] - rect[k]) for k in rect) <= 0.5 / p2.FOOTPRINT_BADGE_Q


def test_decode_footprint_badge_none_without_the_magic_prefix():
    """No badge, a badge not yet painted, or a torn frame must decode to None --
    never to a plausible-looking rect."""
    rect = {"x": 100.0, "y": 200.0, "w": 300.0, "h": 150.0}
    assert p2._decode_footprint_badge(_render_badge(1, rect, magic=0x4D)) is None
    assert p2._decode_footprint_badge(np.zeros((40, 1920, 4), dtype=np.uint8)) is None


def test_decode_footprint_badge_none_when_the_frame_is_too_small():
    rect = {"x": 100.0, "y": 200.0, "w": 300.0, "h": 150.0}
    narrow = _render_badge(1, rect)[:, : p2.FOOTPRINT_BADGE_CELLS * p2.FOOTPRINT_BADGE_CELL_PX - 1]
    assert p2._decode_footprint_badge(narrow) is None


def test_decode_footprint_badge_honours_a_device_scale():
    """deviceScaleFactor is pinned to 1 today, but the decoder derives the cell
    pitch from the captured width rather than assuming it."""
    rect = {"x": 327.0, "y": 709.0, "w": 1266.0, "h": 356.0}
    arr = _render_badge(9, rect, cell=p2.FOOTPRINT_BADGE_CELL_PX * 2, width=3840, height=80)
    out = p2._decode_footprint_badge(arr, 2.0)
    assert out is not None and out["seq"] == 9 and out["crcOk"] is True
    for k, v in rect.items():
        assert out[k] == pytest.approx(v, abs=1.0 / p2.FOOTPRINT_BADGE_Q)
    # ...and read at the WRONG scale it must not hand back a plausible rect.
    # Definite expected result, not "None or True": at scale 1 the sampler lands
    # on the first half of the doubled cells, which duplicates every bit, so the
    # magic byte 0b10110010 reads as 0b11001111 and the prefix check rejects it.
    assert p2._decode_footprint_badge(arr, 1.0) is None


def test_decode_footprint_badge_crc_catches_a_torn_payload():
    """Review r3 MAJOR 3. Without a checksum, a torn frame can present a
    CORRUPTED SEQUENCE that happens to name another logged frame; once the rect
    has settled the coupling comparison still passes and that frame's timestamp
    is substituted, which can move a sample across the hold or release boundary.
    The magic prefix alone cannot see it -- it is intact in a torn payload."""
    rect = {"x": 327.25, "y": 709.75, "w": 1266.5, "h": 356.0}
    out = p2._decode_footprint_badge(_render_badge(4321, rect, corrupt_crc=True))
    assert out is not None, "the magic prefix is intact -- this is not 'no badge'"
    assert out["crcOk"] is False
    assert p2._decode_footprint_badge(_render_badge(4321, rect))["crcOk"] is True


def test_footprint_badge_crc_is_sensitive_to_every_field():
    """A CRC that ignored a field would let that field tear silently."""
    base = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}
    words = [100] + [int(base[k] * p2.FOOTPRINT_BADGE_Q) for k in ("x", "y", "w", "h")]
    baseline = p2._footprint_badge_crc8(words)
    for i in range(len(words)):
        bumped = list(words)
        bumped[i] += 1
        assert p2._footprint_badge_crc8(bumped) != baseline


def _badge_sample(seq, rect, **over):
    s = {"footprintSource": "badge", "badgeSeq": seq, "perfNowMs": 1.0,
         "badgeRect": dict(rect), "measuredRect": None}
    s.update(over)
    return s


def test_fill_badge_coupling_measures_a_rect_in_fast_motion():
    """The item-B semantics, end to end: three frames of a rect travelling far
    faster than FOOTPRINT_COUPLE_TOL_PX per frame are ALL `measured`, because
    each is coupled to its own frame rather than to two reads around a
    screenshot. The frame's own timestamp replaces the free-running one."""
    rects = [
        {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0},
        {"x": 260.0, "y": 753.0, "w": 1110.0, "h": 312.0},
        {"x": 327.0, "y": 709.0, "w": 1266.0, "h": 356.0},
    ]
    samples = [_badge_sample(10 + i, r) for i, r in enumerate(rects)]
    log = {str(10 + i): {"t": 500.0 + i, "rect": r} for i, r in enumerate(rects)}
    counts = p2._fill_badge_coupling(samples, log)
    assert counts["measured"] == 3 and counts["unstable"] == 0
    assert [s["footprintSource"] for s in samples] == ["measured"] * 3
    assert [s["perfNowMs"] for s in samples] == [500.0, 501.0, 502.0]
    assert samples[1]["measuredRect"] == rects[1]


def test_fill_badge_coupling_unlogged_badge_fails_closed():
    """A badge naming a frame the page never logged has ONE reading -- it must
    stay `unstable`, so `allInHoldMeasured` fails rather than trusting pixels
    nothing corroborates."""
    samples = [_badge_sample(99, {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})]
    counts = p2._fill_badge_coupling(samples, {})
    assert samples[0]["footprintSource"] == "unstable"
    assert samples[0]["measuredRect"] is None
    assert counts["unlogged"] == 1


def test_fill_badge_coupling_disagreement_past_tolerance_is_unstable():
    """A torn or stale badge -- pixels that do not match what the page recorded
    for that very frame -- is exactly what the retained tolerance is for."""
    rect = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}
    samples = [_badge_sample(7, {**rect, "x": rect["x"] + 30.0})]
    p2._fill_badge_coupling(samples, {"7": {"t": 1.0, "rect": rect}})
    assert samples[0]["footprintSource"] == "unstable"


def test_fill_badge_coupling_null_logged_rect_is_unstable():
    """A frame in which the page could not resolve the owner still repaints the
    badge, with a NULL rect logged -- so that frame can never couple. (Skipping
    the paint instead would leave the PREVIOUS frame's badge on screen under a
    logged sequence number and couple as `measured` against a stale rect.)"""
    samples = [_badge_sample(5, {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0})]
    p2._fill_badge_coupling(samples, {"5": {"t": 1.0, "rect": None}})
    assert samples[0]["footprintSource"] == "unstable"
    assert samples[0]["measuredRect"] is None


def test_fill_badge_coupling_leaves_non_badge_samples_alone():
    """Without a bound owner there is no badge; those samples stay `modelled`."""
    samples = [{"footprintSource": "modelled", "badgeSeq": None, "perfNowMs": 3.0}]
    counts = p2._fill_badge_coupling(samples, None)
    assert samples[0]["footprintSource"] == "modelled"
    assert samples[0]["perfNowMs"] == 3.0
    assert counts["modelled"] == 1


def test_decode_footprint_badge_unlogged_frame_is_not_measured():
    """The badge alone is not enough: when the page has no record of that frame
    (`lookup` returns null) the sample has one reading, so it is `unstable` and
    `allInHoldMeasured` fails -- fail closed, exactly as a missing read did."""
    decoded = p2._decode_footprint_badge(
        _render_badge(11, {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})
    )
    out = p2._couple_owner_rect(None, {k: decoded[k] for k in ("x", "y", "w", "h")})
    assert out["source"] == "unstable"


# --- badge sequence integrity (review r3 MAJOR 3) --------------------------- #
_SEQ_RECT = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}


def _seq_case(seqs, times):
    samples = [_badge_sample(s, _SEQ_RECT) for s in seqs]
    log = {str(s): {"t": t, "rect": dict(_SEQ_RECT)} for s, t in zip(seqs, times)}
    counts = p2._fill_badge_coupling(samples, log)
    return samples, counts


def test_fill_badge_coupling_rejects_a_repeated_sequence():
    """The capture samples at DENSE_FPS while the badge paints at ~60 Hz, so the
    sequences it reads must strictly increase. A repeat means a torn or aliased
    read -- and its substituted timestamp could move a sample across the hold or
    release boundary -- so it is `unstable`, never `measured`."""
    samples, counts = _seq_case([10, 11, 11, 12], [100.0, 120.0, 140.0, 160.0])
    assert [s["footprintSource"] for s in samples] == [
        "measured", "measured", "unstable", "measured"
    ]
    assert counts["seqViolation"] == 1


def test_fill_badge_coupling_rejects_a_rewound_sequence():
    samples, counts = _seq_case([10, 11, 9, 12], [100.0, 120.0, 140.0, 160.0])
    assert samples[2]["footprintSource"] == "unstable"
    assert counts["seqViolation"] == 1


def test_fill_badge_coupling_rejects_a_non_monotonic_log_time():
    """A sequence can be well-formed while the page's LOG time for it is not --
    the timestamp is what gets substituted into `perfNowMs`, so it is checked in
    its own right, and the offending sample keeps its original timestamp."""
    samples, counts = _seq_case([10, 11, 12], [100.0, 140.0, 120.0])
    assert samples[2]["footprintSource"] == "unstable"
    assert samples[2]["perfNowMs"] == 1.0, "the bad log time must NOT be adopted"
    assert counts["seqViolation"] == 1


def test_fill_badge_coupling_clean_sequence_is_untouched():
    samples, counts = _seq_case([10, 13, 40], [100.0, 150.0, 600.0])
    assert [s["footprintSource"] for s in samples] == ["measured"] * 3
    assert counts["seqViolation"] == 0
    assert [s["perfNowMs"] for s in samples] == [100.0, 150.0, 600.0]


# --- `_moving_index_run_at_cut` (pure) ------------------------------------- #
def _cut_samples(n_pre=3, n_after=p2.FREEZE_MIN_AFTER, *, frozen=True, source="measured"):
    samples = [
        {"index": 30 + i, "sceneHash": "#7", "footprintSource": source} for i in range(n_pre)
    ]
    for i in range(n_after + 1):
        samples.append(
            {"index": 40 if frozen else 40 + i, "sceneHash": "#8", "footprintSource": source}
        )
    return samples


def test_moving_index_run_at_cut_flip_is_on_the_full_list():
    """`flipIndexFull` is the first sample reaching slide 4 in CAPTURE order, not
    the first resolvable one in the measured-only subsequence."""
    samples = _cut_samples()
    samples[1]["footprintSource"] = "unstable"
    result, decodable = p2._moving_index_run_at_cut(samples)
    assert result["flipIndexFull"] == 3
    assert decodable is True


def test_moving_index_run_at_cut_measured_but_undecoded_is_not_decodable():
    """A `measured` sample whose patch did NOT decode (`index is None`) must not
    count as a decodable flip window (review BLOCKER 3: the old predicate checked
    only the source tag, so an all-None window scored a freeze run)."""
    samples = _cut_samples()
    samples[4]["index"] = None
    result, decodable = p2._moving_index_run_at_cut(samples)
    assert decodable is False
    assert result["ok"] is False and result["reason"] == "flip window not decodable"


def test_moving_index_run_at_cut_all_none_window_never_scores_a_freeze_run():
    """The exact r2 counter-example: flip + FREEZE_MIN_AFTER samples all
    `measured` with `index=None` must NOT produce `freeze run at cut`."""
    samples = _cut_samples()
    for s in samples[3:]:
        s["index"] = None
    result, decodable = p2._moving_index_run_at_cut(samples)
    assert decodable is False
    assert result.get("freezeRunAtCut") is None


def test_moving_index_run_at_cut_needs_strictly_after_flip_samples():
    """FREEZE_MIN_AFTER samples STRICTLY after the flip -- the flip sample itself
    does not count towards them (the release off-by-one)."""
    short = _cut_samples(n_after=p2.FREEZE_MIN_AFTER - 1)
    assert p2._moving_index_run_at_cut(short)[1] is False
    assert p2._moving_index_run_at_cut(_cut_samples())[1] is True


def test_moving_index_run_at_cut_ignores_post_release_samples():
    """Samples after the covered segment cannot contribute to the run or to
    `n - flipIndex` (review BLOCKER 3: post-release contamination)."""
    samples = _cut_samples()
    samples += [{"index": 100 + i, "sceneHash": "#8", "footprintSource": "measured"} for i in range(8)]
    covered = 3 + p2.FREEZE_MIN_AFTER
    result, decodable = p2._moving_index_run_at_cut(samples, covered_until=covered)
    assert decodable is True
    assert result["n"] == covered + 1
    assert result["n"] - result["flipIndex"] == p2.FREEZE_MIN_AFTER + 1


def test_moving_index_run_at_cut_truncated_window_is_not_decodable():
    """A covered segment that stops before flip + FREEZE_MIN_AFTER cannot judge
    the cut."""
    samples = _cut_samples()
    result, decodable = p2._moving_index_run_at_cut(samples, covered_until=3 + 2)
    assert decodable is False
    assert result["ok"] is False


def test_moving_index_run_at_cut_no_slide4_sample():
    samples = [{"index": 30 + i, "sceneHash": "#7", "footprintSource": "measured"} for i in range(5)]
    result, decodable = p2._moving_index_run_at_cut(samples)
    assert decodable is False
    assert result["reason"] == "no sample reached slide 4"


def test_moving_index_run_at_cut_positive_arm_is_green():
    """The live positive arm's shape: an advancing counter through the cut scores
    `ok` with no freeze run -- the negative control's counterpart."""
    result, decodable = p2._moving_index_run_at_cut(_cut_samples(frozen=False))
    assert decodable is True
    assert result["ok"] is True and result["freezeRunAtCut"] == 0


def test_freeze_control_passes_on_clean_bracket():
    """Positive control for the instrument: a correctly-fired freeze turns the
    at-cut counter RED for the right reason while the bridged decoder stays live,
    both bracketing positives are green, and every invariant sub-verdict is equal
    (and GREEN) across A1/B/A2 -- including `settledIndexProgressionOk`, which is
    genuinely green in B too because the cover is released before the settled
    window (review Blocker 3)."""
    verdict = p2._score_freeze_control(_positive_snap_34(), _freeze_b_snap_34(), _positive_snap_34())
    assert verdict["ok"] is True, verdict["failed"]
    assert verdict["verdict"] == "pass"
    assert verdict["isolationDiffs"] == {}


def test_freeze_control_arm_failure_is_inconclusive():
    """Review BLOCKER 1: a control that never armed cannot judge anything -- the
    recorded arm error must surface as INCONCLUSIVE, never as a verdict."""
    b = _freeze_b_snap_34()
    b["armResult"] = {"ok": False, "error": "owner-unresolved-at-arm"}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "owner-unresolved-at-arm" in verdict["reason"]


def test_freeze_control_unlanded_drain_press_is_inconclusive():
    """MEASURED root cause of the 5/5 `noPreAdvanceDeparture` red: this player
    QUEUES a key press it cannot honour and replays it later, so an unlanded
    drain press can start the 3->4 move by itself. The bracket must go
    INCONCLUSIVE at the integrity tier, never PASS and never FAIL."""
    b = _freeze_b_snap_34()
    b["drain"] = {
        **b["drain"], "pressesSent": 5, "pressesLanded": 4,
        "unlandedFromHash": [5], "allPressesLanded": False, "ok": False,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False
    assert "drainPressesAllLanded" in verdict["integrityFailed"]
    assert verdict["verdictFailed"] == []


def test_freeze_control_drain_overshoot_is_inconclusive():
    """The drain must stop EXACTLY at the arm boundary. An overshoot means a press
    was honoured past `#7` (or a queued one replayed), so the arm no longer sits
    on the genuine pre-move boundary."""
    b = _freeze_b_snap_34()
    b["drain"] = {**b["drain"], "hashAtArm": "#8", "hashAtArmExact": False, "ok": False}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "drainPressesAllLanded" in verdict["integrityFailed"]


def test_freeze_control_missing_drain_block_fails_closed():
    """No drain record at all (an older snapshot, a capture that died early) is
    NOT evidence of a clean drain -- it must fail closed to INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b.pop("drain")
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_contaminated_positive_drain_is_inconclusive(arm):
    """Round-3 review nit: `drainPressesAllLanded` read only arm B's drain, so a
    POSITIVE whose 3->4 move was started by a replayed queued press still counted
    towards `positivesGreen`. A1 and A2 are held to the SAME condition -- a
    contaminated positive is a different stimulus, so the bracket is
    INCONCLUSIVE, never a verdict."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    snaps[arm]["drain"] = {
        **snaps[arm]["drain"], "pressesSent": 5, "pressesLanded": 4,
        "unlandedFromHash": [5], "allPressesLanded": False, "ok": False,
    }
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False
    assert "drainPressesAllLanded" in verdict["integrityFailed"]
    assert verdict["verdictFailed"] == []


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_positive_drain_overshoot_is_inconclusive(arm):
    """A positive that overshot the arm boundary drained past `#7` too."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    snaps[arm]["drain"] = {**snaps[arm]["drain"], "hashAtArm": "#8", "hashAtArmExact": False}
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "drainPressesAllLanded" in verdict["integrityFailed"]


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_missing_positive_drain_block_fails_closed(arm):
    """Fail CLOSED on a missing block in a positive arm, exactly as for B."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    snaps[arm].pop("drain")
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False
    assert verdict["drains"][arm] is None


def test_freeze_control_never_fired_hold_is_inconclusive_not_pass():
    """A hold that silently never fired (holdStartedAt null) leaves the counter
    GREEN in B, which looks exactly like a passing positive. It MUST be
    INCONCLUSIVE, not PASS and not a plain FAIL."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "status": "armed", "holdStartedAt": None}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["ok"] is False


def test_freeze_control_max_raf_gap_is_disqualifying():
    """Unlike the retired static 1->2 footprint, the 3->4 cover TRACKS a moving
    target every rAF: a stall of >MAX_RAF_GAP_MS leaves the cover behind the
    moving movie, so it is DISQUALIFYING integrity here, never a diagnostic-only
    field (plan §4)."""
    b = _freeze_b_snap_34()
    raf = b["nullControl"]["rafLog"]
    spiked = raf[:20] + [
        {**r, "t": raf[19]["t"] + 380.0 + 20.0 * i} for i, r in enumerate(raf[20:])
    ]
    b["nullControl"] = {**b["nullControl"], "rafLog": spiked}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "maxRafGapOk" in verdict["integrityFailed"]


def test_freeze_control_trigger_to_first_frame_gap_is_disqualifying():
    """`maxRafGapOk` also bounds the gap between the move-start TRIGGER and the
    first hold frame (review MAJOR 5) -- not just gaps between logged frames."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    raf[0] = {**raf[0], "t": raf[0]["t"] + 500.0}  # first frame lags the trigger by 500ms
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "maxRafGapOk" in verdict["integrityFailed"]


def test_freeze_control_dead_loop_is_inconclusive():
    """A loop that barely ran (too few rAF frames) cannot attest the cover
    tracked the footprint over the hold => INCONCLUSIVE, never a verdict."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"],
        "rafLog": [
            {"t": HOLD_STARTED_AT_34 + 10.0, "elementFromPointIsCover": True, "boundDecoderId": 4,
             "ownerResolved": True,
             "coverRect": {"x": 300.0, "y": 700.0, "w": 200.0, "h": 350.0},
             "measuredRect": {"x": 300.0, "y": 700.0, "w": 500.0, "h": 350.0}},
            {"t": HOLD_STARTED_AT_34 + 30.0, "elementFromPointIsCover": True, "boundDecoderId": 4,
             "ownerResolved": True,
             "coverRect": {"x": 300.0, "y": 700.0, "w": 200.0, "h": 350.0},
             "measuredRect": {"x": 300.0, "y": 700.0, "w": 500.0, "h": 350.0}},
        ],  # 2 frames < loopLive floor
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "loopLive" in verdict["integrityFailed"]


def test_freeze_control_unrendered_frame_is_inconclusive():
    """The bug this control was hardened against: a t~0 unrendered frame draws
    BLACK and would decode as a frozen counter for the WRONG reason. Distinguished
    by playback time (currentTime < MIN_STALE_TIME_S) + the trigger error, it must
    be INCONCLUSIVE, never a verdict."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"], "staleCurrentTime": 0.0, "coverPatchMean": 1.0,
        "error": "owner-video-not-ready-at-trigger:rs=4,t=0.01",
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert {"staleFrameFromPlayback", "noControlError"} & set(verdict["integrityFailed"])


def test_freeze_control_valid_dark_counter_not_rejected():
    """Regression: a valid counter near the DARK end of its cycle decodes to RGB
    ~0 (tv-range luma 16 -> full-range RGB ~0). It must NOT be rejected as
    'black' — a genuinely frozen dark frame from live playback still PASSES."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "staleCurrentTime": 7.33, "coverPatchMean": 40.0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "pass", verdict["failed"]


def test_freeze_control_owner_not_ready_is_inconclusive():
    """If the footprint owner was not a decoded video at trigger (readyState < 2),
    the stale frame was not captured from a real frame => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "ownerReadyState": 0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "ownerReadyAtTrigger" in verdict["integrityFailed"]


def test_freeze_control_fired_before_advance_is_inconclusive():
    """A trigger that fired BEFORE the in-page advance keydown held a pre-cut
    frame, not the cut => INCONCLUSIVE (review BLOCKER 2, one clock)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "holdStartedAt": ADVANCE_KEY_AT_34 - 30.0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAfterAdvance" in verdict["integrityFailed"]


def test_freeze_control_no_advance_timestamp_is_inconclusive():
    """No in-page advance timestamp at all means there is no causality evidence
    -- INCONCLUSIVE, never a verdict."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "advanceKeyAt": None}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAfterAdvance" in verdict["integrityFailed"]


def test_freeze_control_pre_advance_departure_is_inconclusive():
    """A rect departure seen BEFORE the advance keydown means the move was
    already running (or the stage jittered): the hold cannot be attributed to the
    cut => INCONCLUSIVE with the departure recorded."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "preAdvanceDepartureAt": ADVANCE_KEY_AT_34 - 100.0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "noPreAdvanceDeparture" in verdict["integrityFailed"]


def test_freeze_control_fired_too_many_frames_after_advance_is_inconclusive():
    """The runtime interpolates LINEARLY, so the rect departs within milliseconds:
    a departure first seen many delivered frames after the advance is a LATE fire,
    not the move start (review BLOCKER 2 -- frames, not a wall-clock window)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"], "triggerFramesAfterAdvance": p2.FREEZE_TRIGGER_MAX_RAFS + 1
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_stage_resized_between_arm_and_trigger_is_inconclusive():
    """The cover geometry is only valid while the stage is unchanged between arm
    and trigger; a resize in that gap invalidates it => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"],
        "stageRectAtTrigger": {"x": 0.0, "y": 0.0, "w": 1600.0, "h": 900.0},
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "stageGeometryStable" in verdict["integrityFailed"]


def test_freeze_control_counter_that_stayed_green_never_passes():
    """If the composite kept ADVANCING under the cover, the gate caught no freeze.
    Since the scorer now recomputes the at-cut run from the raw samples, that is
    caught twice over -- the at-cut run stays green AND the in-hold decodes are
    not stale -- and can never be a PASS."""
    b = _freeze_b_snap_34()
    # Every sample from the moment the cover went up, not merely from the flip:
    # the scored window opens at `coverPaintedAt` (review r3 BLOCKER 2).
    for i in range(len(_PRE_ADVANCE_INDICES_34), FREEZE_SPLIT_INDEX_34 + 1):
        b = _with_sample(b, i, index=40 + i)  # advancing again -> no freeze to catch
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert verdict["verdict"] != "pass"
    assert "indexRunRed" in verdict["failed"]
    assert "everyInHoldStale" in verdict["integrityFailed"]


def test_freeze_control_fails_on_weak_freeze_margin():
    """A freeze run barely over the gate's tolerance (not >= FREEZE_MIN_RUN) is
    indistinguishable from coarse-capture jitter and must not qualify the
    instrument."""
    b = _freeze_b_snap_34()
    # Break the run in the middle: two short frozen runs instead of one long one.
    b = _with_sample(b, FREEZE_FLIP_INDEX_34 + 3, index=77)
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "freezeRunMargin" in verdict["failed"] or "everyInHoldStale" in verdict["integrityFailed"]


def test_freeze_control_fails_when_freeze_leaked_into_liveness():
    """The RED must be ISOLATED to the counter: if a sub-verdict that should be
    invariant (here movingContinuity3to4) differs in B, the freeze was not clean
    => fail on isolation (or its own key), never a spurious pass."""
    b = _freeze_b_snap_34()
    b["movingContinuity3to4"] = {**b["movingContinuity3to4"], "ok": False, "failed": ["rvfcMonotonic"]}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "isolationEqual" in verdict["failed"] or "movingContinuityOk" in verdict["failed"]


def test_freeze_control_fails_when_bound_decoder_is_not_slide3_decoder():
    """The cover must have bound the SAME decoder that played slide 3; otherwise
    the freeze proved nothing about the decoder under test."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "boundDecoderId": 99}  # cover bound a different el
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "boundDecoderIsSlide3Decoder" in verdict["failed"]


def test_freeze_control_fails_when_positive_bracket_not_green():
    """If a bracketing positive is not green, there is no baseline to isolate the
    RED against => fail (the bracket is not trustworthy)."""
    a_bad = _positive_snap_34()
    a_bad["movingIndexRunAtCut"] = {
        "ok": False, "reason": "freeze run at cut", "flipIndex": 3, "n": 10,
        "freezeRunAtCut": 7, "negativeAnomaly": False,
    }
    a_bad["continueThroughMovingMagicMove3to4Pass"] = False
    verdict = p2._score_freeze_control(a_bad, _freeze_b_snap_34(), _positive_snap_34())
    assert verdict["ok"] is False
    assert "positivesGreen" in verdict["failed"]


def test_freeze_control_hash_only_trigger_is_inconclusive():
    """`firedVia == 'hash'` means the move is already OVER and the cover tracked
    nothing during the move: `firedAtMoveStart` requires `firedVia == 'moved'` (a
    MEASURED departure of the bound owner's rect from its armed rect), never a
    hash-only fallback fire — INCONCLUSIVE (owner decision 8c)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "firedVia": "hash"}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_cover_tracks_footprint_violation_is_inconclusive():
    """`coverTracksFootprint` = 100% of hold frames with the cover rect matching
    the JS's own `subRect(measuredRect)` derivation within COVER_TRACK_TOL_PX. One
    frame off (the cover left behind the moving footprint) => INCONCLUSIVE. Both
    rects come from separate post-update `getBoundingClientRect()` reads in
    production (review MAJOR 5), so this is not a tautology to defeat."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    bad = dict(raf[10])
    bad["coverRect"] = {**bad["coverRect"], "x": bad["coverRect"]["x"] + 25.0}
    raf[10] = bad
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverTracksFootprint" in verdict["integrityFailed"]


def test_freeze_control_one_frame_cover_lag_is_caught():
    """A SYSTEMATIC one-frame lag (the cover trailing the moving footprint by one
    rAF) must fail: at the fixture's per-frame motion it exceeds
    COVER_TRACK_TOL_PX, which was derived from a correctly-ordered loop's
    measured ~0 residual, not chosen to pass."""
    b = _freeze_b_snap_34()
    raf = []
    for i, r in enumerate(b["nullControl"]["rafLog"]):
        moved = {**r["measuredRect"], "x": r["measuredRect"]["x"] + 2.8 * i}
        lagged = {**r["coverRect"], "x": r["coverRect"]["x"] + 2.8 * max(0, i - 1)}
        raf.append({**r, "measuredRect": moved, "coverRect": lagged})
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverTracksFootprint" in verdict["integrityFailed"]


def test_freeze_control_release_after_burst_started_is_inconclusive():
    """A release that slips past the settled-slide-4 visible-content burst start
    leaves the cover in place for part of the burst — it would red
    `footprintFullyLive` for the WRONG reason. `releaseStrictlyBeforeSettleAndBurst`
    is bounded on both sides: INCONCLUSIVE, not a verdict."""
    b = _freeze_b_snap_34()
    b["burstStartPerfMs"] = b["nullControl"]["releaseAt"] - 10.0
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_release_not_strictly_after_last_capture_is_inconclusive():
    """The check is STRICT (`<`, not `<=`): a release that lands exactly ON the
    last at-cut capture must not pass — that capture's cover state at the instant
    of the screenshot is ambiguous."""
    b = _freeze_b_snap_34()
    b["lastAtCutPerfMs"] = b["nullControl"]["releaseAt"]
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_release_not_strictly_before_settled_is_inconclusive():
    """The other bound: release must land STRICTLY before the first post-split
    settled sample, not merely before the burst (review Blocker 3)."""
    b = _freeze_b_snap_34()
    b["firstSettledPerfMs"] = b["nullControl"]["releaseAt"]
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_modelled_in_hold_sample_is_inconclusive():
    """A `modelled` (not measured) footprint sample inside the hold window means
    the ROI mapping for that decode is unproven — `allInHoldMeasured` fails
    closed rather than trusting a decode off an unverified ROI."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 1, footprintSource="modelled")
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_unstable_in_hold_sample_is_inconclusive():
    """An `unstable` sample (before/after screenshot rect reads disagreed,
    review Blocker 2b) inside the hold window is just as untrustworthy as a
    `modelled` one — `allInHoldMeasured` fails closed."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 1, footprintSource="unstable")
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_isolation_mismatch_fails():
    """`footprintFullyLive` differing between A1 and B (a sub-verdict that must be
    invariant, since the burst is captured AFTER release) fails the bracket on
    isolation, never a spurious pass."""
    a1 = _positive_snap_34()
    a1["footprintFullyLive"] = {"ok": False}
    verdict = p2._score_freeze_control(a1, _freeze_b_snap_34(), _positive_snap_34())
    assert verdict["ok"] is False
    assert "isolationEqual" in verdict["failed"]


def test_freeze_control_all_isolation_false_but_equal_does_not_pass():
    """`isolationEqual` must require GREEN, not just equality (review MAJOR 4): if
    every isolation key is False in all three arms, that is EQUAL but is not a
    trustworthy bracket, and must not pass."""
    def _all_false(snap):
        snap = dict(snap)
        snap["movingContinuity3to4"] = {
            "ok": False, "failed": ["rvfcMonotonic"],
            "boundaryValid": {"ok": False}, "stableSlide4Owner": {"ok": False},
            "crossingIdentity": {"ok": False}, "rvfcMonotonic": {"ok": False, "advance": None},
        }
        snap["footprintFullyLive"] = {"ok": False}
        snap["settledIndexProgression"] = {"ok": False}
        snap["playerBuildErrors"] = [{"kind": "player-build-error"}]
        snap["bridgeEngaged"] = False
        return snap

    a1 = _all_false(_positive_snap_34())
    a2 = _all_false(_positive_snap_34())
    b = _all_false(_freeze_b_snap_34())
    verdict = p2._score_freeze_control(a1, b, a2)
    assert verdict["ok"] is False
    assert "isolationEqual" in verdict["failed"]


def test_freeze_control_stage_origin_nonzero_is_inconclusive():
    """The partial cover is `position:fixed` (viewport px) while the moving
    <video> is stage-absolute px — they only coincide while the stage origin is
    (0,0). A nonzero origin at arm invalidates the geometry => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "stageOrigin": {"x": 12.0, "y": 0.0}}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "stageOriginZero" in verdict["integrityFailed"]


def test_freeze_control_flip_window_undecodable_is_inconclusive():
    """`flipWindowDecodable` is RECOMPUTED by the scorer from the raw samples
    (review BLOCKER 3) -- a capture-side boolean claiming otherwise cannot green
    it, and an undecodable flip window is INCONCLUSIVE."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 2, index=None)
    b["flipWindowDecodable"] = True  # the capture-side claim is ignored
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "flipWindowDecodable" in verdict["integrityFailed"]


def test_freeze_control_post_release_samples_do_not_pad_after_flip():
    """`enoughAfterFlip` counts only samples inside the covered at-cut segment:
    a short segment cannot be padded by post-release settled samples."""
    b = _freeze_b_snap_34()
    b["releaseSplitIndex"] = FREEZE_FLIP_INDEX_34 + 2
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert {"enoughAfterFlip", "flipWindowDecodable"} & set(verdict["integrityFailed"])


def test_freeze_control_owner_disconnected_mid_hold_is_inconclusive():
    """Once bound by element id, the SAME element must stay connected/keyed for
    the whole hold (review MAJOR 4's de-vacuumed `noOwnerAmbiguousInWindow`) — a
    disconnect fails it closed even with `ownerAmbiguousInWindow` itself False."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "ownerDisconnectedInWindow": True}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "noOwnerAmbiguousInWindow" in verdict["failed"]


def test_freeze_control_bound_decoder_id_changes_mid_hold_fails_ambiguity():
    """`noOwnerAmbiguousInWindow` also requires the LOGGED `boundDecoderId` to
    stay the SAME element for every rAF frame, not just at the end."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    raf[10] = {**raf[10], "boundDecoderId": 99}
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "noOwnerAmbiguousInWindow" in verdict["failed"]

# --- review r3 BLOCKER 2: the scored window opens when the COVER was PAINTED - #
def test_freeze_control_pre_cover_sample_does_not_fake_a_restart():
    """The EXACT live failure. The trigger fires, then the <=150 ms owner-
    readiness retry runs, and a capture landing in that gap still shows a LIVE
    counter -- one step ahead of the frozen ones. Scored from `holdStartedAt`
    the segment reads `[29, 28, 28, ...]`: a -1 step, which the at-cut scorer
    (correctly, and untouched) calls a modulo-255 REWIND, so the bracket reached
    a wrong-reason FAIL through `reasonFreezeRunAtCut`/`noNegativeAnomaly`
    instead of seeing the freeze it had just injected.

    Scored from `coverPaintedAt` the 29 is outside the window and the freeze is
    exactly what it looks like. The raw sample is KEPT for diagnostics."""
    b = _freeze_b_snap_34(at_cut=[28] * 7, covered_pre_flip=(28, 28, 28))
    b["nullControl"] = {**b["nullControl"], "coverPatchMean": 28.0}
    # The last pre-cover capture: live at 29, timestamped between the trigger and
    # the cover actually being painted.
    b = _with_sample(b, len(_PRE_ADVANCE_INDICES_34) - 1, index=29,
                     perfNowMs=HOLD_STARTED_AT_34 + 5.0)
    scored = [s["index"] for s in b["indexSamples"][len(_PRE_ADVANCE_INDICES_34) - 1:
                                                   FREEZE_SPLIT_INDEX_34 + 1]]
    assert scored[:4] == [29, 28, 28, 28], "the live shape, before trimming"

    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "pass", verdict["failed"]
    assert verdict["movingIndexRunAtCut"]["negativeAnomaly"] is False
    assert verdict["movingIndexRunAtCut"]["reason"] == "freeze run at cut"
    assert 29 in [s["index"] for s in b["indexSamples"]], "kept for diagnostics"


def test_freeze_control_missing_cover_painted_at_fails_closed():
    """No `coverPaintedAt`, no window: the scorer must not silently fall back to
    `holdStartedAt` (which is the defect) nor to "everything"."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "coverPaintedAt": None}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverPaintedAtPresent" in verdict["integrityFailed"]


def _with_rehandoff(b: dict, n: int, seq0: int = 4100) -> dict:
    """Turn the first `n` COVERED samples into the badge's own re-handoff frames:
    null rect, nothing decoded, sequences the badge logged as a contiguous pair.
    """
    first = len(_PRE_ADVANCE_INDICES_34)
    for k in range(n):
        b = _with_sample(b, first + k, footprintSource="unstable", index=None,
                         badgeRect=None, badgeSeq=seq0 + k)
    b["badge"] = {"stats": {"rehandoffSeqs": [seq0, seq0 + 1]}}
    return b


def test_freeze_control_window_opens_after_the_badges_own_rehandoff():
    """LIVE (bracket run0): the badge's re-handoff onto the fresh 3->4 pin lands
    ONE frame before the cover is painted and paints a NULL rect for the
    contiguous pair of frames it spans, so the first covered capture is often one
    of them. Those -- and only those -- are excused: they decoded nothing, so they
    are no evidence either way."""
    for n in (1, 2):
        b = _with_rehandoff(_freeze_b_snap_34(), n)
        verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
        assert verdict["verdict"] == "pass", (n, verdict["failed"])
        assert verdict["freeze"]["rehandoffExemptSamples"] == n
        assert verdict["freeze"]["firstCoveredPosition"] == len(_PRE_ADVANCE_INDICES_34) + n


def test_freeze_control_leading_unstable_with_a_live_decode_is_inconclusive():
    """Review r4 BLOCKER 1. An unguarded leading skip let a CRC/sequence/coupling
    failure that still DECODED a live counter open the window past itself, and
    later frozen frames then carried the verdict. A leading `unstable` sample that
    decoded something is a real observation on an uncoupled frame: INCONCLUSIVE."""
    first = len(_PRE_ADVANCE_INDICES_34)
    b = _with_sample(_freeze_b_snap_34(), first, footprintSource="unstable", index=255)
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]

    # ...and a null-rect leading sample the badge did NOT log as a re-handoff
    # buys no exemption either.
    b2 = _with_sample(_freeze_b_snap_34(), first, footprintSource="unstable",
                      index=None, badgeRect=None, badgeSeq=999)
    v2 = p2._score_freeze_control(_positive_snap_34(), b2, _positive_snap_34())
    assert v2["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v2["integrityFailed"]

    # ...nor does a LONE logged sequence that is not part of a contiguous pair.
    b3 = _with_rehandoff(_freeze_b_snap_34(), 1)
    b3["badge"] = {"stats": {"rehandoffSeqs": [4100, 4200]}}
    v3 = p2._score_freeze_control(_positive_snap_34(), b3, _positive_snap_34())
    assert v3["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v3["integrityFailed"]

    # ...and an unstable sample in the MIDDLE of the hold still reds it.
    b4 = _with_sample(_freeze_b_snap_34(), first + 2, footprintSource="unstable")
    v4 = p2._score_freeze_control(_positive_snap_34(), b4, _positive_snap_34())
    assert v4["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v4["integrityFailed"]


def test_freeze_control_more_rehandoff_frames_than_the_badge_paints_is_inconclusive():
    """The re-handoff spans exactly two frames; a third excused sample means the
    badge was not doing what its own contract says."""
    b = _with_rehandoff(_freeze_b_snap_34(), 3)
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_no_coupled_frame_in_the_hold_fails_closed():
    """A covered span with NOTHING coupled in it is not a measured hold."""
    b = _freeze_b_snap_34()
    for i in range(len(_PRE_ADVANCE_INDICES_34), len(b["indexSamples"])):
        b = _with_sample(b, i, footprintSource="unstable")
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_cover_painted_before_trigger_is_not_assumed():
    """`coverPaintedAt` is a distinct, LATER instant than `holdStartedAt`; the
    window must follow it, not the trigger."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "coverPaintedAt": 10_000.0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["freeze"]["firstCoveredPosition"] is None


# --- review r3 BLOCKER 3: the trigger is bounded in TIME, not only in frames - #
def test_freeze_control_long_pre_trigger_stall_is_inconclusive():
    """A keydown->rAF stall advances the runtime's time-based interpolation deep
    into the move before poll frame 1 is ever delivered. The delivered-frame
    bound cannot see it (it still reads 1), and the hold's own gap check starts
    at the trigger -- so the page-clock ceiling is the only thing that bites."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"],
        "holdStartedAt": ADVANCE_KEY_AT_34 + p2.FREEZE_TRIGGER_MAX_DELAY_MS + 1.0,
        "triggerFramesAfterAdvance": 1,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_pre_trigger_raf_gap_counts_towards_the_max_gap():
    """Gaps BEFORE the trigger are measured in the page from the keydown and fold
    into the same max-gap budget -- previously they were invisible."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "pollMaxGapMs": p2.MAX_RAF_GAP_MS + 1.0}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "maxRafGapOk" in verdict["integrityFailed"]
    assert verdict["maxRafGapMs"] == pytest.approx(p2.MAX_RAF_GAP_MS + 1.0)


def test_freeze_control_trigger_far_from_runtime_motion_start_is_inconclusive():
    """The departure must be the runtime's OWN move, within a callback or two of
    `__obedMotion.started` -- not some other rect change that happened to be
    within the frame budget."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"], "triggerFramesAfterAdvance": 8, "motionStartedFrame": 1,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]


def test_freeze_control_missing_runtime_motion_marker_is_inconclusive():
    """Fail CLOSED: no fresh marker means nothing ties the departure to the
    runtime's move at all."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "motionStartedFrame": None}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]


def test_freeze_control_motion_marker_for_the_wrong_boundary_is_inconclusive():
    """Review r4 MAJOR 1. Frame proximity is not identity: keepThroughBridge
    stamps a marker for whatever boundary it is pinning, and a marker for another
    boundary produces an equally timely departure -- after which the real 3->4
    bridge runs uncovered and the bracket could still reach `#8`/`#9`. The
    marker must name the 3->4 boundary (`atScene == SLIDE4_MIN_HASH`)."""
    for at_scene in (6, 12, None):
        b = _freeze_b_snap_34()
        nc = b["nullControl"]
        b["nullControl"] = {
            **nc,
            "motionStartedMarker": {**nc["motionStartedMarker"], "atScene": at_scene},
            "obedMotionAtTrigger": {**nc["obedMotionAtTrigger"], "atScene": at_scene},
        }
        verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
        assert verdict["verdict"] == "inconclusive", at_scene
        assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]


def test_freeze_control_motion_marker_replaced_before_the_trigger_is_inconclusive():
    """A replacement marker on the bound video between the poll retaining the
    first fresh one and the departure means the departure belongs to a DIFFERENT
    move. The trigger's marker must be identical in `started` AND `generation`."""
    b = _freeze_b_snap_34()
    nc = b["nullControl"]
    replaced_gen = {**nc["obedMotionAtTrigger"], "generation": 2}
    b["nullControl"] = {**nc, "obedMotionAtTrigger": replaced_gen}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]

    replaced_start = {**nc["obedMotionAtTrigger"], "started": HOLD_STARTED_AT_34 + 40.0}
    b2 = _freeze_b_snap_34()
    b2["nullControl"] = {**b2["nullControl"], "obedMotionAtTrigger": replaced_start}
    v2 = p2._score_freeze_control(_positive_snap_34(), b2, _positive_snap_34())
    assert v2["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in v2["integrityFailed"]

    # ...and no marker at the trigger at all fails closed too.
    b3 = _freeze_b_snap_34()
    b3["nullControl"] = {**b3["nullControl"], "obedMotionAtTrigger": None}
    v3 = p2._score_freeze_control(_positive_snap_34(), b3, _positive_snap_34())
    assert v3["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in v3["integrityFailed"]


def test_freeze_control_trigger_within_the_motion_slack_still_passes():
    """...and the slack is real: the marker is stamped inside keepThroughBridge's
    first SYNCHRONOUS frame(), which runs in a task, so the poll can see it a
    callback before or after the rect visibly departs."""
    for frames, marker in ((3, 1), (1, 3), (2, 2)):
        b = _freeze_b_snap_34()
        b["nullControl"] = {
            **b["nullControl"], "triggerFramesAfterAdvance": frames,
            "motionStartedFrame": marker,
        }
        verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
        assert verdict["verdict"] == "pass", (frames, marker, verdict["failed"])


# --- review r3 MAJOR 1: exactly one advance press, in every arm -------------- #
@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_multi_press_advance_is_inconclusive(arm):
    """A second queued press is replayed by the player and starts the move by
    itself, so the arms are no longer the same stimulus -- in ANY arm."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    snaps[arm] = {**snaps[arm], "advance": {**snaps[arm]["advance"], "pressesSent": 2, "ok": False}}
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "advanceSinglePressAllArms" in verdict["integrityFailed"]


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_missing_advance_block_fails_closed(arm):
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    snaps[arm] = {k: v for k, v in snaps[arm].items() if k != "advance"}
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "advanceSinglePressAllArms" in verdict["integrityFailed"]


# --- review r3 BLOCKER 4: integrity problems are INCONCLUSIVE, not FAIL ------ #
@pytest.mark.parametrize(
    "key,mutate",
    [
        ("positivesGreen",
         lambda s: s["a1"].update(continueThroughMovingMagicMove3to4Pass=False)),
        ("rvfcRanThroughHold",
         lambda s: s["b"].update(movingContinuity3to4={
             **s["b"]["movingContinuity3to4"], "rvfcMonotonic": {"ok": True, "advance": 0.01}})),
        ("boundDecoderIsSlide3Decoder", lambda s: s["b"].update(ownerDecoderId=99)),
        ("noOwnerAmbiguousInWindow",
         lambda s: s["b"].update(nullControl={**s["b"]["nullControl"],
                                              "ownerAmbiguousInWindow": True})),
        ("playerBuildErrorsEmpty", lambda s: s["b"].update(playerBuildErrors=[{"e": 1}])),
        ("isolationEqual", lambda s: s["b"].update(footprintFullyLive={"ok": False})),
    ],
)
def test_freeze_control_integrity_problems_are_inconclusive_not_fail(key, mutate):
    """None of these establishes whether the counter caught a valid isolated
    freeze, so none may produce a FAIL verdict against the counter. FAIL is
    reserved for a fully valid stimulus whose counter response misses.

    Nothing gets easier to PASS: each is still required, and
    `_freeze_control_blocks_success` blocks overall `success` on `inconclusive`
    exactly as it does on `fail`."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _positive_snap_34()}
    mutate(snaps)
    verdict = p2._score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", verdict["failed"]
    assert key in verdict["integrityFailed"]
    assert p2._freeze_control_blocks_success("inconclusive", bridge34_disabled=False) is True


def test_freeze_control_negative_anomaly_is_integrity_not_a_verdict():
    """`noNegativeAnomaly` is measurement integrity (the live failure is exactly
    that), so it must not be able to produce a FAIL against the counter."""
    b = _freeze_b_snap_34()
    b = _with_sample(b, FREEZE_FLIP_INDEX_34 + 1, index=250)  # backward past modulo/2
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "noNegativeAnomaly" in verdict["integrityFailed"]
    assert "noNegativeAnomaly" not in verdict["verdictFailed"]


def test_freeze_control_fail_route_is_live_and_is_only_the_counter_response(monkeypatch):
    """FAIL must still be REACHABLE, or the verdict tier is dead code. It is
    reached by exactly one situation: the stimulus is fully valid -- the pixels
    under the cover really were frozen, which the harness establishes for itself
    via `everyInHoldStale` against the cover's own painted mean -- and the
    production counter gate nonetheless does not flag it strongly enough.

    That is the whole point of the negative control, so it is simulated here by
    demanding a run the genuine freeze cannot supply."""
    b = _freeze_b_snap_34()
    monkeypatch.setattr(p2, "FREEZE_MIN_RUN", 99)
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "fail"
    assert verdict["integrityFailed"] == []
    assert verdict["verdictFailed"] == ["freezeRunMargin"]
    assert p2._freeze_control_blocks_success("fail", bridge34_disabled=False) is True


def test_freeze_control_a_counter_that_never_froze_is_inconclusive_not_fail():
    """...and the common "no freeze at all" shape is NOT a claim about the
    counter: the harness's own stale check reds first, so the bracket says
    INCONCLUSIVE rather than accusing the gate."""
    b = _freeze_b_snap_34(at_cut=[40, 41, 42, 43, 44, 45, 46],
                          covered_pre_flip=(37, 38, 39))
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["integrityFailed"] == ["everyInHoldStale"]


def test_freeze_control_verdict_tier_is_only_the_counter_response():
    """Guard the tier split itself: the verdict tier says nothing except whether
    the counter went red at the cut for the injected freeze."""
    verdict = p2._score_freeze_control(_positive_snap_34(), _freeze_b_snap_34(),
                                       _positive_snap_34())
    assert verdict["verdict"] == "pass"
    keys = set(verdict["checks"])
    assert keys - set(verdict["integrityFailed"]) - set(verdict["verdictFailed"])
    # The three counter-response keys, and nothing else, can produce a FAIL.
    b = _freeze_b_snap_34()
    for i in range(len(_PRE_ADVANCE_INDICES_34), FREEZE_SPLIT_INDEX_34 + 1):
        b = _with_sample(b, i, index=40 + i)
    v2 = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert set(v2["verdictFailed"]) <= {
        "indexRunRed", "reasonFreezeRunAtCut", "freezeRunMargin"
    }


# --- review r3 MAJOR 2: one shared in-page split evaluation ----------------- #
def test_split_eval_js_is_one_evaluation_with_the_same_shape_in_both_branches():
    """A1/A2 previously returned LOCALLY at the split while B awaited a CDP
    round trip, so the absolute-target capture loop caught up differently
    afterwards -- settled progression or continuity could differ purely because
    B paused. Both branches are now one evaluation of the SAME source, with the
    same keys out."""
    released = p2.SPLIT_EVAL_JS % {"release": "true"}
    noop = p2.SPLIT_EVAL_JS % {"release": "false"}
    assert released != noop
    assert released.replace("var R = true;", "") == noop.replace("var R = false;", "")
    for key in ("t", "released", "controlPresent", "status", "releaseAt",
                "holdFrames", "paintCount", "coverPatchEnd"):
        assert f"{key}:" in released


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_split_eval_js_returns_the_same_keys_on_both_branches():
    """Executed, not just inspected: with no control present (the positive arms)
    and with one present, the returned object has identical keys."""
    harness = """
      var calls = 0;
      global.performance = {now: function () { return 1234.5; }};
      global.window = {};
      function run(src) { return eval(src); }
      var noop = run(%s);
      window.__OBED_NULL_CTRL__ = {release: function () {
        calls++;
        return {status: 'released', releaseAt: 9, holdFrames: 3, paintCount: 1,
                coverPatchEnd: {sum: 5}};
      }};
      var rel = run(%s);
      console.log(JSON.stringify({noop: Object.keys(noop).sort(),
                                  rel: Object.keys(rel).sort(),
                                  released: [noop.released, rel.released],
                                  calls: calls}));
    """ % (json.dumps(p2.SPLIT_EVAL_JS % {"release": "false"}),
           json.dumps(p2.SPLIT_EVAL_JS % {"release": "true"}))
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["noop"] == got["rel"]
    assert got["released"] == [False, True]
    assert got["calls"] == 1, "the no-op branch must not release anything"


# --- review r3 BLOCKER 1 / MAJOR 3: the badge JS, EXECUTED ------------------ #
_BADGE_HARNESS = r"""
var cells = null, painted = [], rafQ = [], taskQ = [];
var video = {__obedElId: 'el4', rect: {left: 198, top: 797, width: 952, height: 268},
             getBoundingClientRect: function () {
               return {left: this.rect.left, top: this.rect.top,
                       width: this.rect.width, height: this.rect.height};
             }};
global.performance = {now: (function () { var t = 0; return function () { return (t += 16.7); }; })()};
global.requestAnimationFrame = function (fn) { rafQ.push(fn); return rafQ.length; };
global.setTimeout = function (fn) { taskQ.push(fn); };
global.document = {
  querySelectorAll: function () { return [video]; },
  body: {appendChild: function () {}},
  createElement: function () {
    return {style: {}, setAttribute: function () {},
            getContext: function () {
              return {fillStyle: '#000000',
                      fillRect: function (x) { cells[Math.round(x / CELL)] = this.fillStyle === '#ffffff' ? 1 : 0; }};
            }};
  }
};
global.window = {devicePixelRatio: 1, innerWidth: 1920};
var CELL = 6;
EVAL_BADGE
window.__OBED_FP_BADGE__.install('el4');
// Flush the install handoff (rAF -> task -> rAF) and then drive frames.
function frame() {
  var q = rafQ; rafQ = [];
  q.forEach(function (fn) { fn(); });
  var t = taskQ; taskQ = [];
  t.forEach(function (fn) { fn(); });
}
function step(label) {
  cells = new Array(NCELL).fill(0);
  frame();
  if (cells.some(function (c) { return c === 1; })) painted.push({label: label, cells: cells.slice()});
}
for (var i = 0; i < 4; i++) { step('pre' + i); video.rect.left += 1.5; }
video.__obedMotion = {started: 500, generation: 3};
for (var j = 0; j < 6; j++) { step('post' + j); video.rect.left += 1.5; }
console.log(JSON.stringify({painted: painted,
                            stats: window.__OBED_FP_BADGE__.stats(),
                            log: window.__OBED_FP_BADGE__.dump()}));
"""


def _run_badge_js() -> dict:
    src = _BADGE_HARNESS.replace(
        "EVAL_BADGE",
        "var NCELL = %d;\n%s" % (p2.FOOTPRINT_BADGE_CELLS, p2.FOOTPRINT_BADGE_JS),
    )
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# A SIMULATED runtime footprint pin, ordered exactly as `keepThroughBridge` is:
# it starts from a post-frame TASK, applies the rect synchronously there, and
# re-queues from its OWN rAF callback. Registering in the task phase puts it
# BEHIND a badge loop that re-queued from its rAF callback -- which is the
# one-frame lag the re-handoff exists to undo.
_PIN_HARNESS = r"""
var cells = null, rafQ = [], taskQ = [], trace = [], pinTicks = 0;
var video = {__obedElId: 'el4', rect: {left: 200, top: 797, width: 952, height: 268},
             getBoundingClientRect: function () {
               return {left: this.rect.left, top: this.rect.top,
                       width: this.rect.width, height: this.rect.height};
             }};
global.performance = {now: (function () { var t = 0; return function () { return (t += 16.7); }; })()};
global.requestAnimationFrame = function (fn) { rafQ.push(fn); return rafQ.length; };
global.setTimeout = function (fn) { taskQ.push(fn); };
global.document = {
  querySelectorAll: function () { return [video]; },
  body: {appendChild: function () {}},
  createElement: function () {
    return {style: {}, setAttribute: function () {},
            getContext: function () {
              return {fillStyle: '#000000', fillRect: function () {}};
            }};
  }
};
global.window = {devicePixelRatio: 1, innerWidth: 1920};
EVAL_BADGE
var B = window.__OBED_FP_BADGE__;
B.install('el4');
function frame() {
  var q = rafQ; rafQ = [];
  q.forEach(function (fn) { fn(); });
  var t = taskQ; taskQ = [];
  t.forEach(function (fn) { fn(); });
}
function pinTick() {
  pinTicks += 1;
  video.rect.left = 200 + 10 * pinTicks;
  requestAnimationFrame(pinTick);
}
function startPin() {
  taskQ.push(function () {
    if (MARK_ON) video.__obedMotion = {started: 500, generation: 3};
    pinTick();
  });
}
function step(label) {
  var before = B.stats().seq;
  frame();
  var st = B.stats(), log = B.dump(), painted = [];
  for (var s = before + 1; s <= st.seq; s++) painted.push(log[s] ? log[s].rect : null);
  trace.push({label: label, painted: painted, endX: video.rect.left});
}
for (var i = 0; i < 3; i++) step('pre' + i);
startPin();
for (var j = 0; j < 8; j++) step('post' + j);
console.log(JSON.stringify({trace: trace, stats: B.stats()}));
"""


def _run_pin_js(mark_on: bool) -> dict:
    src = (
        _PIN_HARNESS
        .replace("EVAL_BADGE", "var NCELL = %d;\n%s"
                 % (p2.FOOTPRINT_BADGE_CELLS, p2.FOOTPRINT_BADGE_JS))
        .replace("MARK_ON", "true" if mark_on else "false")
    )
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _pin_residuals(trace):
    """Per frame: (badge-painted x) - (rect the pin left on screen for it). 0 is
    the badge reading BEHIND the pin; negative is the one-frame lag."""
    out = []
    for fr in trace:
        rects = [r for r in fr["painted"] if r is not None]
        if len(rects) == 1:
            out.append((fr["label"], rects[0]["x"] - fr["endX"]))
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_lands_behind_a_later_runtime_pin_callback():
    """Review r4 MINOR 2. Deterministic rAF/task ordering, with a simulated
    runtime pin scheduled AFTER the badge callback. Without the re-handoff the
    badge reads the pre-move rect and the composited frame shows the moved one --
    a lag of exactly one pin step, mutually consistent between badge pixels and
    badge log, so the coupling check cannot see it. With the re-handoff the badge
    paints NULL across the transfer and every later frame is residual-0."""
    lagged = _pin_residuals(_run_pin_js(mark_on=False)["trace"])
    after = [r for label, r in lagged if label.startswith("post")]
    assert after and set(after[1:]) == {-10.0}, after

    got = _run_pin_js(mark_on=True)
    assert got["stats"]["rehandoffs"] == 1
    post = [r for label, r in _pin_residuals(got["trace"]) if label.startswith("post")]
    # Exactly ONE lagged frame survives: the frame the pin STARTS on, where the
    # badge has already read before the task that creates the marker runs. It is
    # strictly before the trigger (which is the first poll frame that SEES the
    # departure) and therefore before `coverPaintedAt`, so it can never be in the
    # scored window. The transfer frames then paint a null rect, and every frame
    # that reads at all from there on is exactly on the pin's own rect.
    assert post[0] == -10.0, post
    assert set(post[1:]) == {0.0}, post


def _cells_to_frame(cells) -> np.ndarray:
    cell = p2.FOOTPRINT_BADGE_CELL_PX
    arr = np.zeros((cell * 2, len(cells) * cell, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    for c, bit in enumerate(cells):
        arr[0:cell, c * cell:(c + 1) * cell, :3] = 255 if bit else 0
    return arr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_paints_what_python_decodes():
    """End to end across the language boundary: the badge JS is EXECUTED against
    a stub DOM and the cells it actually paints are fed to the real Python
    decoder. The previous badge tests only proved the Python codec was
    self-consistent -- a JS-side encoding bug would have sailed through."""
    got = _run_badge_js()
    frames = [p for p in got["painted"] if p["label"].startswith("pre")]
    assert frames, "the badge must paint on every frame"
    decoded = [p2._decode_footprint_badge(_cells_to_frame(f["cells"])) for f in frames]
    assert all(d is not None and d["crcOk"] for d in decoded), "JS CRC must match Python's"
    seqs = [d["seq"] for d in decoded]
    assert seqs == sorted(set(seqs)), "strictly increasing sequence numbers"
    # ...and each painted rect matches the page's OWN log of that frame, which is
    # exactly what `_fill_badge_coupling` couples.
    for d in decoded:
        logged = got["log"][str(d["seq"])]
        if logged["rect"] is None:
            continue
        assert p2._couple_owner_rect(
            logged["rect"], {k: d[k] for k in ("x", "y", "w", "h")}
        )["source"] == "measured"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_rehandoffs_behind_a_fresh_runtime_pin():
    """Review r3 BLOCKER 1. The install-time handoff only ordered the loop behind
    whatever pin existed THEN; keepThroughBridge's 3->4 pin starts later, from a
    task, so it registers its rAF AFTER this loop has re-queued from its own
    callback and from then on runs after us -- one frame of lag, mutually
    consistent between badge pixels and badge log, invisible to the coupling
    check. On a fresh `__obedMotion` generation the loop re-handoffs, and the
    frames spanning the handoff name a NULL rect so they can only ever be
    `unstable`."""
    got = _run_badge_js()
    assert got["stats"]["rehandoffs"] == 1
    assert got["stats"]["motionStartedAt"] == 500
    null_seqs = {int(s) for s, e in got["log"].items() if e["rect"] is None}
    assert set(got["stats"]["rehandoffSeqs"]) == null_seqs
    assert len(null_seqs) == 2, "this frame AND the intervening handoff frame"
    # A sample that caught one of those frames has a single reading -> unstable.
    seq = min(null_seqs)
    samples = [_badge_sample(seq, {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})]
    p2._fill_badge_coupling(samples, {str(seq): got["log"][str(seq)]})
    assert samples[0]["footprintSource"] == "unstable"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_parses():
    result = subprocess.run(
        ["node", "--check", "-"], input=p2.FOOTPRINT_BADGE_JS, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_null_control_js_parses():
    """The JS itself cannot run under pytest (no browser/DOM) -- this only
    checks the `NULL_CONTROL_JS` source is syntactically valid, catching a
    typo/syntax error the Python-side tests above cannot see."""
    result = subprocess.run(
        ["node", "--check", "-"], input=p2.NULL_CONTROL_JS, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_norm_hash_regression_guard():
    """Review Blocker 1: `arm()` compared `"7"` against `location.hash` (`"#7"`)
    directly and fired instantly. `_norm_hash` is the shared normaliser used on
    the Python side of the arm-time assert; guard that it actually strips the
    `#` inconsistency the bug relied on."""
    assert p2._norm_hash("7") != p2._norm_hash("#7")
    assert p2._norm_hash("#7") == p2._norm_hash("#7?x=1")
    assert p2._norm_hash("#7") == "#7"

# `_freeze_control_blocks_success` — the pure owner-decision-8b rule wiring
# `freeze_control`'s verdict into the probe's overall `success`.
def test_freeze_blocks_success_pass_never_blocks():
    assert p2._freeze_control_blocks_success("pass", bridge34_disabled=False) is False
    assert p2._freeze_control_blocks_success("pass", bridge34_disabled=True) is False


def test_freeze_blocks_success_skipped_non_blocking_only_under_disable_bridge34():
    assert p2._freeze_control_blocks_success("skipped", bridge34_disabled=True) is False
    assert p2._freeze_control_blocks_success("skipped", bridge34_disabled=False) is True


def test_freeze_blocks_success_inconclusive_and_fail_always_block():
    assert p2._freeze_control_blocks_success("inconclusive", bridge34_disabled=False) is True
    assert p2._freeze_control_blocks_success("inconclusive", bridge34_disabled=True) is True
    assert p2._freeze_control_blocks_success("fail", bridge34_disabled=False) is True
    assert p2._freeze_control_blocks_success("fail", bridge34_disabled=True) is True

# --------------------------------------------------------------------------- #
# I4 — the 1->2 carry is REFUSED: gates under the baseline plan.
# --------------------------------------------------------------------------- #
def _refusal_events() -> list[dict]:
    """The two positive notes the retire zone may emit for movie1.

    The player holds `#1` for the WHOLE 1->2 Magic Move, so the declining hooks
    fire at scene 1; the swept `retire-boundary` still names `atScene` 2.
    """
    return [
        {
            "kind": "retire-boundary",
            "detail": {"key": "movie1", "elIds": [1], "atScene": 2, "sceneHash": "#1"},
        },
        {
            "kind": "preserve-refused",
            "detail": {"key": "movie1", "scene": 1, "via": "stash", "sceneHash": "#1"},
        },
    ]


def _clean_lingering() -> dict:
    return {"count": 0, "elIds": [], "preservedCount": 0, "paintingCount": 0, "paintingElIds": []}


def _frozen_index_samples(index: int = 41, n: int = 8) -> list[dict]:
    """A flip at sample 1, then a counter that never advances (raw-export slide 2)."""
    return [{"index": index - 1, "sceneHash": "#1"}] + [
        {"index": index, "sceneHash": "#2"} for _ in range(n)
    ]


def _carry_census(total: int = 0, sample=None) -> dict:
    """The in-page carry census: `total` is counted over the FULL event log,
    filtered to movie1, before the sample is sliced."""
    return {
        "key": "movie1",
        "total": total,
        "sample": sample if sample is not None else [],
        "loScene": 1,
        "hiScene": 6,
        "eventsSeen": 400,
    }


def _pool_census(entries=None, scene_hash: str = "#2") -> dict:
    return {"entries": entries if entries is not None else [], "sceneHash": scene_hash}


def _motion_across_flip(after=(0.0, 0.0, 0.0, 0.0), before=(218.0, 0.85, 110.0), eps=2.0):
    """`score_motion_across_flip`'s window as the live run reports it on the
    REFUSED slide: live before the cut, pixel-frozen after it."""
    return {
        "ok": False,
        "reason": "no motion after flip",
        "flipIndex": 4,
        "beforeOk": any(m >= eps for m in before),
        "pairEps": eps,
        "beforePairMae": list(before),
        "afterPairMae": list(after),
    }


def _poster_roi(level: int = 120):
    """A settled slide-2 composite: the export's poster, well above the script's
    opaque-black level."""
    import numpy as np

    roi = np.full((20, 40, 4), 255, dtype=np.uint8)
    roi[:, :, :3] = level
    return roi


def _flip_rois(after=None, *, flip_index: int = 4, n: int = 9):
    """ROI crops in capture order: moving before the flip, then the still
    post-flip window (the settled poster unless `after` overrides it)."""
    import numpy as np

    before = [_poster_roi(30 + 40 * (i % 2)) for i in range(flip_index)]
    tail = after if after is not None else _poster_roi()
    return before + [np.array(tail, copy=True) for _ in range(n - flip_index)]


def _refused_args(**overrides):
    args = {
        "injected_plan": p2.build_continuity_plan(True),
        "preserve_events": _refusal_events(),
        "lingering": _clean_lingering(),
        "motion_across_flip": _motion_across_flip(),
        "flip_rois": _flip_rois(),
        "settled_slide2_roi": _poster_roi(),
        "index_samples": _frozen_index_samples(),
        "flip_index": 1,
        "hash1": "#1",
        "hash2": "#2",
        "player_build_errors": [],
        "carry_census": _carry_census(),
    }
    args.update(overrides)
    return args


def _refused(**overrides) -> dict:
    return p2.refusedCarry1to2(**_refused_args(**overrides))


def test_refused_carry_passes_when_every_clause_holds():
    verdict = _refused()
    assert verdict["ok"] is True
    assert verdict["reasons"] == []
    assert verdict["planRetire"]["atScene"] == p2.SLIDE2_MIN_HASH
    assert verdict["frozenComposite"]["frozen"] is True


def test_refused_carry_fails_without_plan_retire_boundary():
    """(a) The plan must actually retire the key — an un-retired plan cannot be
    'honoured' by silence."""
    plan = p2.build_continuity_plan(True)
    plan["boundaries"] = [b for b in plan["boundaries"] if b.get("action") != "retire"]
    verdict = _refused(injected_plan=plan)
    assert verdict["ok"] is False
    assert "injected plan has no retire boundary for the target key" in verdict["reasons"]


def test_refused_carry_fails_without_a_positive_refusal_event():
    """(b) Refusal is asserted by an event, never by silence."""
    verdict = _refused(preserve_events=[])
    assert verdict["ok"] is False
    assert "no preserve-refused/retire-boundary event in the retire zone" in verdict["reasons"]


def test_refused_carry_accepts_a_refusal_on_the_transition_scene_alone():
    """The transition scene (RETIRE_ZONE_MIN_HASH) is inside the zone: a
    `preserve-refused` there satisfies (b) with no `retire-boundary` at all."""
    only_transition = [
        {"kind": "preserve-refused",
         "detail": {"key": "movie1", "scene": 1, "via": "src-clear", "sceneHash": "#1"}},
    ]
    verdict = _refused(preserve_events=only_transition)
    assert verdict["ok"] is True
    assert verdict["refusalEventsN"] == 1


def test_refused_carry_ignores_a_refusal_event_before_the_retire_zone():
    early = [
        {"kind": "preserve-refused", "detail": {"key": "movie1", "scene": 0, "via": "stash"}},
    ]
    verdict = _refused(preserve_events=early)
    assert verdict["ok"] is False
    assert verdict["refusalEventsN"] == 0


def test_refused_carry_fails_on_a_remount_during_the_transition_scene():
    """(c) The zone INCLUDES the transition scene the player still hashes as `#1`:
    the first live run remounted there and left decoders painting on slide 2."""
    events = _refusal_events() + [
        {"kind": "remount-done", "detail": {"elId": 1, "key": "movie1", "sceneHash": "#1"}},
    ]
    verdict = _refused(preserve_events=events, carry_census=_carry_census(1, events[-1:]))
    assert verdict["ok"] is False
    assert verdict["carryEventsInRetireZoneN"] == 1
    assert "carry notes inside the retire zone" in verdict["reasons"]


def test_refused_carry_fails_on_a_remount_inside_the_retire_zone():
    """(c) Any carry note for movie1 in [RETIRE_ZONE_MIN_HASH, 6) means it happened."""
    events = _refusal_events() + [
        {"kind": "remount-done", "detail": {"elId": 1, "key": "movie1", "sceneHash": "#3"}},
    ]
    verdict = _refused(preserve_events=events, carry_census=_carry_census(1, events[-1:]))
    assert verdict["ok"] is False
    assert verdict["carryEventsInRetireZoneN"] == 1
    assert "carry notes inside the retire zone" in verdict["reasons"]


def test_refused_carry_fails_on_a_keyless_dom_swap_of_a_known_movie1_element():
    """dom-swap carries no key — it is matched by the element id the retire
    boundary already attributed to movie1."""
    events = _refusal_events() + [
        {"kind": "dom-swap", "detail": {"elId": 1, "t": 4.0, "sceneHash": "#4"}},
    ]
    verdict = _refused(preserve_events=events, carry_census=_carry_census(1, events[-1:]))
    assert verdict["ok"] is False
    assert verdict["carryEventsInRetireZoneN"] == 1


def test_refused_carry_allows_carry_events_outside_the_retire_zone():
    """The 3->4 bridge remounts at scene 8 — outside [2, 6) and not this gate's business."""
    events = _refusal_events() + [
        {"kind": "remount-done", "detail": {"elId": 1, "key": "movie1", "sceneHash": "#8"}},
        {"kind": "remount-done", "detail": {"elId": 9, "key": "movie2", "sceneHash": "#3"}},
    ]
    verdict = _refused(preserve_events=events)
    assert verdict["ok"] is True
    assert verdict["carryEventsInRetireZoneN"] == 0


def test_refused_carry_fails_on_a_lingering_overlay_on_slide2():
    """(d) A remounted leftover over the slide-1/2 footprints."""
    verdict = _refused(lingering={**_clean_lingering(), "count": 1, "elIds": [1]})
    assert verdict["ok"] is False
    assert "a preserved/remounted/painting <video> lingers on slide 2" in verdict["reasons"]


def test_refused_carry_fails_on_a_painting_video_over_the_footprint():
    """(d) A <video> that actually paints there — the player composites slide 2
    in WebGL, so anything painting is ours."""
    verdict = _refused(lingering={**_clean_lingering(), "paintingCount": 1})
    assert verdict["ok"] is False
    assert "a preserved/remounted/painting <video> lingers on slide 2" in verdict["reasons"]


def test_refused_carry_fails_closed_when_the_slide2_query_did_not_run():
    verdict = _refused(lingering={"error": "evaluate returned nothing"})
    assert verdict["ok"] is False


def test_refused_carry_fails_when_the_composite_keeps_moving_after_the_flip():
    """(e) A moving ROI on slide 2 means the movie was carried after all."""
    verdict = _refused(motion_across_flip=_motion_across_flip(after=(0.0, 31.0, 28.0, 25.0)))
    assert verdict["ok"] is False
    assert "composite kept moving on the refused slide" in verdict["reasons"]


def test_refused_carry_fails_closed_when_nothing_moved_before_the_flip():
    """A dead instrument reads 'frozen' everywhere — that is not evidence."""
    verdict = _refused(motion_across_flip=_motion_across_flip(before=(0.0, 0.1, 0.0)))
    assert verdict["ok"] is False
    assert "no motion before the flip — the instrument is blind" in verdict["reasons"]


def test_refused_carry_fails_closed_on_too_few_after_pairs():
    verdict = _refused(motion_across_flip=_motion_across_flip(after=(0.0, 0.0)))
    assert verdict["ok"] is False
    assert "insufficient after-pairs to judge a freeze" in verdict["reasons"]


def test_refused_carry_fails_closed_without_a_scored_flip_window():
    for bad in (None, {}, {"reason": "no flip observed", "n": 3}):
        verdict = _refused(motion_across_flip=bad)
        assert verdict["ok"] is False
        assert "no scored flip window" in verdict["reasons"]


def test_refused_carry_does_not_gate_on_the_undecodable_counter():
    """On the refused slide the patch ROI shows the export's POSTER, so the
    burnt-in counter never decodes — it stays a labelled diagnostic."""
    samples = [{"index": None, "sceneHash": "#1"}] + [
        {"index": None, "sceneHash": "#2"} for _ in range(4)
    ]
    verdict = _refused(index_samples=samples, flip_index=1)
    assert verdict["ok"] is True
    assert verdict["frozenIndexNonGating"]["frozen"] is False
    assert verdict["frozenComposite"]["frozen"] is True


def test_refused_carry_fails_when_the_scene_hash_did_not_change():
    verdict = _refused(hash2="#1")
    assert verdict["ok"] is False
    assert "no valid forward 1->2 boundary" in verdict["reasons"]


def test_refused_carry_fails_on_a_player_build_error():
    """(f) An uncaught player exception fails the finding outright."""
    verdict = _refused(player_build_errors=[{"kind": "player-build-error"}])
    assert verdict["ok"] is False
    assert "player build error" in verdict["reasons"]


# --------------------------------------------------------------------------- #
# preserveDidNotBlockRestart — the two positive-evidence routes.
# --------------------------------------------------------------------------- #
def test_never_pooled_evidence_is_the_refusal_route():
    """Refused + nothing pooled in the retire zone => the pool was EMPTY at the
    2->3 boundary, which is why the reuse-skip/retire pair cannot fire."""
    evidence = p2.neverPooledEvidence(
        _refusal_events(), _carry_census(), _pool_census()
    )
    assert evidence["ok"] is True
    assert evidence["refusalEventsN"] == 2
    assert evidence["carryEventsInRetireZoneN"] == 0


def test_never_pooled_evidence_requires_a_positive_refusal_event():
    """Silence is not evidence: no refusal note => no substitute route."""
    assert p2.neverPooledEvidence([], _carry_census(), _pool_census())["ok"] is False


def test_never_pooled_evidence_dies_on_a_stash_consumed_in_the_retire_zone():
    events = _refusal_events() + [
        {"kind": "reuse-decoder", "detail": {"key": "movie1", "newElId": 3, "sceneHash": "#4"}},
    ]
    evidence = p2.neverPooledEvidence(
        events, _carry_census(1, events[-1:]), _pool_census()
    )
    assert evidence["ok"] is False
    assert evidence["carryEventsInRetireZoneN"] == 1


def test_never_pooled_evidence_ignores_another_movies_reuse():
    events = _refusal_events() + [
        {"kind": "reuse-decoder", "detail": {"key": "movie2", "newElId": 7, "sceneHash": "#4"}},
    ]
    assert p2.neverPooledEvidence(events, _carry_census(), _pool_census())["ok"] is True


# --------------------------------------------------------------------------- #
# footprintFullyLive — wiring only; thresholds are imported, never re-tuned.
# --------------------------------------------------------------------------- #
def _burst(rect, *, live_frac: float = 1.0, control_noise: bool = False, n: int = 6):
    """A synthetic settled-slide burst: static grey everywhere, except a live
    band inside `rect` (the left `live_frac` of it) that alternates every frame."""
    import numpy as np

    x, y, w, h = rect
    frames = []
    for i in range(n):
        frame = np.full((1080, 1920, 3), 60, dtype=np.uint8)
        lw = max(1, int(w * live_frac))
        frame[y:y + h, x:x + lw] = 30 if i % 2 else 220
        if control_noise:
            c = p2.SLIDE4_CONTROL_RECT
            frame[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]] = 30 if i % 2 else 220
        frames.append(frame)
    return frames


def test_footprint_fully_live_green_on_a_fully_painting_footprint():
    verdict = p2.footprintFullyLive(_burst(p2.SLIDE4_MOVIE_RECT))
    assert verdict["ok"] is True
    assert verdict["verdict"] is True
    assert verdict["perRect"][0]["label"] == "slide4Movie"


def test_footprint_fully_live_red_on_a_half_dead_footprint():
    """Half the destination rect frozen => the carry is not visibly correct."""
    verdict = p2.footprintFullyLive(_burst(p2.SLIDE4_MOVIE_RECT, live_frac=0.5))
    assert verdict["ok"] is False
    assert verdict["verdict"] is False


def test_footprint_fully_live_inconclusive_is_a_failure():
    """A noise floor above threshold yields verdict None — anything but True fails."""
    verdict = p2.footprintFullyLive(_burst(p2.SLIDE4_MOVIE_RECT, control_noise=True))
    assert verdict["verdict"] is None
    assert verdict["status"] == "inconclusive"
    assert verdict["ok"] is False


def test_footprint_fully_live_fails_closed_on_a_truncated_burst():
    verdict = p2.footprintFullyLive(_burst(p2.SLIDE4_MOVIE_RECT, n=1))
    assert verdict["ok"] is False
    assert verdict["status"] == "inconclusive"


def test_burst_offsets_come_from_the_probe():
    """One burst cadence for both instruments — never a re-tuned local copy."""
    import live_continuity_probe

    assert p2.BURST_OFFSETS_MS == live_continuity_probe.BURST_OFFSETS_MS
    assert len(set(p2.BURST_OFFSETS_MS)) == len(p2.BURST_OFFSETS_MS)


# --------------------------------------------------------------------------- #
# Injected plan shape + the findings inventory.
# --------------------------------------------------------------------------- #
def test_injected_plan_retires_movie1_before_the_restart_and_bridges_3to4():
    plan = p2.build_continuity_plan(True)
    boundaries = plan["boundaries"]
    assert [b["action"] for b in boundaries] == ["retire", "restart", "bridge"]
    assert boundaries[0] == {
        "atScene": p2.SLIDE2_MIN_HASH, "action": "retire", "movieKey": p2.MOVIE1_KEY,
    }
    assert boundaries[1]["atScene"] == p2.SLIDE3_MIN_HASH
    assert boundaries[2]["atScene"] == p2.SLIDE4_MIN_HASH
    assert boundaries[0]["atScene"] < boundaries[1]["atScene"] < boundaries[2]["atScene"]


def test_injected_plan_names_movie1_only():
    """Naming the slide-3-only WA0125 clip admits it to the runtime's stash()
    plan-name filter, which pools it at the 3->4 detach and remounts it at the
    fallback footprint — the slide-4 stray."""
    for bridge in (True, False):
        assert list(p2.build_continuity_plan(bridge)["movies"]) == ["movie1"]


def test_disable_bridge34_removes_only_the_bridge():
    plan = p2.build_continuity_plan(False)
    assert [b["action"] for b in plan["boundaries"]] == ["retire", "restart"]
    assert plan["movies"] == p2.build_continuity_plan(True)["movies"]
    assert plan["transparentBackground"] is True


def test_injected_plan_matches_the_derived_runtime_plan_boundaries():
    """The P2 injection must stay equal to `derive_plan(...).to_runtime()` for the
    fixture (tests/test_live_continuity.py pins the other direction)."""
    import re

    expected = re.search(
        r"EXPECTED_RUNTIME_PLAN = (\{.*?\n\})",
        (REPO / "tests" / "test_live_continuity.py").read_text(encoding="utf-8"),
        re.S,
    )
    assert expected, "EXPECTED_RUNTIME_PLAN literal not found"
    derived = eval(expected.group(1))  # noqa: S307 - repo-local literal
    injected = p2.build_continuity_plan(True)
    assert injected["boundaries"] == derived["boundaries"]
    assert injected["movies"] == derived["movies"]
    assert {k: v for k, v in injected.items() if k != "transparentBackground"} == derived


def test_findings_inventory_is_still_fourteen_and_renamed():
    import re

    ids = re.findall(
        r'"id": "(\w+)"',
        (REPO / "scripts" / "p2_recovery_html_adversarial.py").read_text(encoding="utf-8"),
    )
    assert len(ids) == 14
    assert "refusedCarry1to2" in ids
    assert "continueThroughMagicMove1to2" not in ids
    assert "freezeControlCaughtByCounter" in ids


def test_refused_carry_ignores_a_suppressed_or_errored_remount():
    """A remount that was suppressed / went stale / errored is the OPPOSITE of a
    carry and must not turn the refusal red."""
    events = _refusal_events() + [
        {"kind": "remount-suppressed", "detail": {"elId": 1, "why": "mm", "sceneHash": "#3"}},
        {"kind": "remount-stale", "detail": {"elId": 1, "epoch": 2, "sceneHash": "#3"}},
        {"kind": "remount-error", "detail": {"elId": 1, "message": "x", "sceneHash": "#4"}},
    ]
    verdict = _refused(preserve_events=events)
    assert verdict["ok"] is True
    assert verdict["carryEventsInRetireZoneN"] == 0


def test_never_pooled_evidence_covers_the_transition_scene():
    """A carry on the transition scene kills the never-pooled route too."""
    events = _refusal_events() + [
        {"kind": "remount-done", "detail": {"elId": 1, "key": "movie1", "sceneHash": "#1"}},
    ]
    assert p2.neverPooledEvidence(
        events, _carry_census(1, events[-1:]), _pool_census()
    )["ok"] is False


def test_retire_zone_starts_one_scene_before_the_destination():
    assert p2.RETIRE_ZONE_MIN_HASH == p2.SLIDE2_MIN_HASH - 1


# --------------------------------------------------------------------------- #
# Codex r1 — the census routes: counted in the page, and the pool read for real.
# --------------------------------------------------------------------------- #
def test_refused_carry_fails_on_a_census_total_the_sample_cannot_show():
    """The bounded sample is not the evidence: a positive TOTAL is red even when
    the sample that came back is empty."""
    verdict = _refused(carry_census=_carry_census(3, []))
    assert verdict["ok"] is False
    assert verdict["carryEventsInRetireZoneN"] == 3
    assert "carry notes inside the retire zone" in verdict["reasons"]


def test_refused_carry_fails_closed_without_a_carry_census():
    verdict = _refused(carry_census=None)
    assert verdict["ok"] is False
    assert "carry census missing or malformed" in verdict["reasons"]


def test_refused_carry_fails_closed_on_a_malformed_carry_census():
    verdict = _refused(carry_census={"key": "movie1", "sample": []})
    assert verdict["ok"] is False
    assert "carry census missing or malformed" in verdict["reasons"]


def test_carry_census_survives_other_movies_crowding_the_sample():
    """25 routine movie2 notes plus ONE movie1 note: the page filters to movie1
    BEFORE slicing, so the total is 1 and the finding is red even though the
    fetched event list is dominated by the other movie."""
    noise = [
        {"kind": "remount-done", "detail": {"elId": 50 + i, "key": "movie2", "sceneHash": "#3"}}
        for i in range(25)
    ]
    offender = {"kind": "remount-done", "detail": {"elId": 1, "key": "movie1", "sceneHash": "#3"}}
    events = _refusal_events() + noise + [offender]
    verdict = _refused(preserve_events=events, carry_census=_carry_census(1, [offender]))
    assert verdict["ok"] is False
    assert verdict["carryEventsInRetireZoneN"] == 1
    assert verdict["carryInRetireZone"]["localMatchesN"] == 1


def test_never_pooled_route_dies_when_a_decoder_is_still_pooled_on_slide2():
    """A detached movie1 decoder sitting in the pool through slide 2 is never
    reused or remounted — only the census can see it."""
    census = _pool_census([
        {"key": "movie1", "elId": 1, "inDocument": False, "currentTime": 4.0},
    ])
    evidence = p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)
    assert evidence["ok"] is False
    assert evidence["poolCensus"]["entriesForTargetN"] == 1


def test_never_pooled_route_dies_on_a_preserved_from_dom_entry():
    census = _pool_census([
        {"key": "untitled.mov", "elId": 1, "fromDom": True, "inDocument": True},
    ])
    evidence = p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)
    assert evidence["ok"] is False
    assert evidence["poolCensus"]["fromDomForTargetN"] == 1


def test_never_pooled_route_tolerates_another_movie_in_the_pool():
    census = _pool_census([{"key": "movie2", "elId": 9, "inDocument": False}])
    assert p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)["ok"] is True


def test_never_pooled_route_is_invalid_without_a_pool_census():
    for bad in (None, {}, {"entries": "nope", "sceneHash": "#2"}):
        evidence = p2.neverPooledEvidence(_refusal_events(), _carry_census(), bad)
        assert evidence["ok"] is False
        assert evidence["poolCensus"]["reason"] == "pool census missing or malformed"


def test_never_pooled_route_is_invalid_when_the_census_left_the_retire_zone():
    """A census taken on slide 3 says nothing about slide 2."""
    evidence = p2.neverPooledEvidence(
        _refusal_events(), _carry_census(), _pool_census([], scene_hash="#6")
    )
    assert evidence["ok"] is False
    assert evidence["poolCensus"]["reason"] == "pool census taken outside the retire zone"


# --------------------------------------------------------------------------- #
# Codex r2 — a still ROI must also be the RIGHT still ROI, and the hash must
# actually move forward.
# --------------------------------------------------------------------------- #
def test_refused_carry_fails_when_the_post_flip_roi_went_black():
    """Four zero MAEs also describe an ROI that died after the cut."""
    verdict = _refused(flip_rois=_flip_rois(after=_poster_roi(0)),
                       settled_slide2_roi=_poster_roi(0))
    assert verdict["ok"] is False
    assert "post-flip ROI is blank/black" in verdict["reasons"]


def test_refused_carry_fails_when_the_post_flip_roi_is_not_what_slide2_rests_on():
    """Frozen on something the settled slide does not show = a dead/stale surface
    that recovered later, not the refused poster."""
    verdict = _refused(flip_rois=_flip_rois(after=_poster_roi(200)),
                       settled_slide2_roi=_poster_roi(120))
    assert verdict["ok"] is False
    assert "post-flip ROI does not match the settled slide-2 composite" in verdict["reasons"]


def test_refused_carry_fails_closed_without_a_settled_roi():
    verdict = _refused(settled_slide2_roi=None)
    assert verdict["ok"] is False
    assert "no settled slide-2 ROI" in verdict["reasons"]


def test_refused_carry_fails_closed_without_post_flip_roi_frames():
    verdict = _refused(flip_rois=[])
    assert verdict["ok"] is False
    assert "no post-flip ROI frames" in verdict["reasons"]


def test_refused_carry_green_on_the_live_shape():
    """After-pair MAE 0, non-blank, equal to the settled composite, #1 -> #2."""
    verdict = _refused()
    assert verdict["ok"] is True
    assert verdict["frozenComposite"]["content"]["ok"] is True


def test_refused_carry_requires_strictly_forward_hash_movement():
    """`#5 -> #2` is not a forward 1->2 boundary."""
    verdict = _refused(hash1="#5", hash2="#2")
    assert verdict["ok"] is False
    assert "no valid forward 1->2 boundary" in verdict["reasons"]


def test_refused_carry_fails_closed_on_an_unparseable_hash():
    for pair in (("#1", "#2x"), ("boot", "#2"), ("#1", None)):
        verdict = _refused(hash1=pair[0], hash2=pair[1])
        assert verdict["ok"] is False
        assert "no valid forward 1->2 boundary" in verdict["reasons"]


# --------------------------------------------------------------------------- #
# Codex r2 — pool census attribution: a cleared src reports an EMPTY key.
# --------------------------------------------------------------------------- #
def test_pool_census_attributes_by_the_stamped_movie_key():
    """A preserved decoder whose src was really cleared has key "" — the stamped
    identity is what says it is movie1."""
    census = _pool_census([{"key": "", "movieKey": "movie1", "elId": 1}])
    evidence = p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)
    assert evidence["ok"] is False
    assert evidence["poolCensus"]["entriesForTargetN"] == 1


def test_pool_census_is_invalid_on_an_unattributable_entry():
    census = _pool_census([{"key": "", "movieKey": None, "elId": 1}])
    evidence = p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)
    assert evidence["ok"] is False
    assert evidence["poolCensus"]["reason"] == "pool census holds an unattributable entry"


def test_pool_census_tolerates_a_provably_different_asset():
    census = _pool_census([{"key": "vid-2024-01-01-wa0125.mp4", "movieKey": None, "elId": 9}])
    assert p2.neverPooledEvidence(_refusal_events(), _carry_census(), census)["ok"] is True
