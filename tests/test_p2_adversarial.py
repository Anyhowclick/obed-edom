"""Load-bearing tests for the Round-2 ownership/engagement fixes in
`scripts/p2_recovery_html_adversarial.py` (Codex r1 findings F3, F5, F6, and the
F1b fail-closed engagement gate).

These are pure-logic tests: they never launch Keynote, a browser, or the live
harness. The verdict logic they exercise lives in `obed_edom.p2_verdict`, an
installed module; driver-boundary tests (Chrome/CDP, injected JS) live in
`tests/test_p2_adversarial_driver.py`, which still loads the script by path.

Each test is deliberately explicit about the adversarial input it guards
against, so a regression that reopens a Codex defect fails a NAMED test.
"""

from __future__ import annotations

import base64
import concurrent.futures
import contextlib
import copy
import io
import json
import os
import zlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from obed_edom import p2_verdict as p2

REPO = Path(__file__).resolve().parent.parent

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


def test_live_continuity_fails_closed_on_a_split_cumulative_rewind():
    """A rewind split into small steps (10.00 -> 9.96 -> 9.92 -> 10.10) has a net
    advance of +0.10 (passes the `> 0.05` gate) and every ADJACENT delta is only
    -0.04 (inside the 0.05 tolerance) -- an adjacent-delta check would wrongly
    pass this. `_presented_time_advances` instead compares each sample to the
    RUNNING MAX seen so far, so it catches the -0.08 dip below the prior peak
    (10.00) and fails closed."""
    split_rewind = [
        {"sceneHash": "#2", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.00}]},
        {"sceneHash": "#2", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 9.96}]},
        {"sceneHash": "#3", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 9.92}]},
        {"sceneHash": "#3", "videos": [{"decoderId": "dec-1", "presentedMediaTime": 10.10}]},
    ]
    verdict = p2.liveContinuity1to2(
        _motion_healthy(), _flip_samples(), split_rewind, "#1", "#2", restart_min_hash=RESTART
    )
    assert verdict["ok"] is False
    assert "rvfcAdvance" in verdict["failed"]
    assert verdict["rvfcAdvance"]["worstRegression"] == pytest.approx(-0.08)


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


_FP_34 = [327.0, 709.0, 1266.0, 356.0]


def _owner_samples_34(decoder_id=4, ambiguous=False):
    """Owner samples in the slide-4 after-window (hn #8,#9 >= num(hash4)=8)."""
    return [
        {"sceneHash": "#8", "decoderId": decoder_id, "ownerAmbiguous": ambiguous,
         "footprint": list(_FP_34)},
        {"sceneHash": "#9", "decoderId": decoder_id, "ownerAmbiguous": ambiguous,
         "footprint": list(_FP_34)},
    ]


def _video_entry_34(decoder_id, t, **over):
    """One `videos` entry carrying the geometry AND the raw readings the paint
    decision is re-derived from."""
    box = dict(zip(("x", "y", "w", "h"), _FP_34))
    entry = {
        "decoderId": decoder_id, "presentedMediaTime": t, "visible": True,
        "hiddenBy": None, "suppressed34": False, "rect": dict(box),
        "inDocument": True, "display": "block", "visibility": "visible",
        "opacityProduct": 1.0, "checkVisibility": True,
        "clientRect": dict(box), "viewport": {"w": 1920.0, "h": 1080.0},
    }
    entry.update(over)
    return entry


def _presented_34(decoder_id=4):
    """Media snapshots whose slide-4 owner's presentedMediaTime advances >0.05."""
    return [
        {"sceneHash": "#8", "videos": [_video_entry_34(decoder_id, 1.6)]},
        {"sceneHash": "#9", "videos": [_video_entry_34(decoder_id, 2.4)]},
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
# The clean bracket below is the REAL A1/B/A2 snapshot triple of ONE live run
# (round 13, `output/scratch-r13/run1300`), committed verbatim under
# `tests/fixtures/p2_freeze_3to4/` with nothing the scorer reads stripped, so the
# absence sweep walks the PRODUCTION shape instead of a hand-built model of it
# (review r10 MAJOR 5). Its geometry is read off the fixture, never declared.
# --------------------------------------------------------------------------- #
_FIXTURE_34 = json.loads(
    (REPO / "tests" / "fixtures" / "p2_freeze_3to4" / "clean_bracket.json").read_text()
)
FREEZE_SPLIT_INDEX_34 = _FIXTURE_34["b"]["releaseSplitIndex"]
FREEZE_FLIP_INDEX_34 = next(
    i for i, s in enumerate(_FIXTURE_34["b"]["indexSamples"])
    if (p2._hash_num(s.get("sceneHash")) or -1) >= p2.SLIDE4_MIN_HASH
)
# Capture 0 is the badge's one re-handoff frame (null rect, exempt), so the
# scored in-hold window opens at 1.
FIRST_IN_HOLD_34 = 1
ADVANCE_KEY_AT_34 = _FIXTURE_34["b"]["advanceKeyPerfMs"]
HOLD_STARTED_AT_34 = _FIXTURE_34["b"]["nullControl"]["holdStartedAt"]
COVER_PAINTED_AT_34 = _FIXTURE_34["b"]["nullControl"]["coverPaintedAt"]
REHANDOFF_SEQ0_34 = _FIXTURE_34["b"]["badge"]["stats"]["rehandoffSeqs"][0]


_MISSING = object()


def _score_34(a1: dict, b: dict, a2: dict, manifest=_MISSING) -> dict:
    """The A-B-A scorer, handed the bracket MANIFEST the fixture was captured
    under. The manifest is minted before any arm runs and lives outside the
    snapshots, so it is an argument here exactly as it is in production."""
    return p2._score_freeze_control(
        a1, b, a2,
        _FIXTURE_34["manifest"] if manifest is _MISSING else manifest,
    )


def _positive_snap_34(**overrides) -> dict:
    snap = copy.deepcopy(_FIXTURE_34["a1"])
    snap.update(overrides)
    return snap


def _freeze_b_snap_34(**overrides) -> dict:
    snap = copy.deepcopy(_FIXTURE_34["b"])
    snap.update(overrides)
    return snap


def _a2_snap_34(**overrides) -> dict:
    """The run's OWN second positive, never a copy of A1: value-dependent
    positions in the real A2 are otherwise never scored (review r11 MINOR 1)."""
    snap = copy.deepcopy(_FIXTURE_34["a2"])
    snap.update(overrides)
    return snap


def _reconcile_34(snap: dict) -> dict:
    """Recompute every cached view from this snapshot's (edited) capture samples,
    through the same helpers the capture side uses."""
    samples = snap["indexSamples"]
    split = snap["releaseSplitIndex"]
    run, decodable = p2._moving_index_run_at_cut(samples, covered_until=split, covered_from=0)
    boundary = p2._at_cut_boundary(samples, snap["advanceKeyPerfMs"])
    settled = p2._slide4_settled_window(samples[split + 1:])
    snap["movingIndexRunAtCut"] = run
    snap["flipWindowDecodable"] = decodable
    snap["settledIndexProgression"] = p2.score_index_progression(
        [s.get("index") for s in settled]
    )
    snap["atCutBoundary"] = boundary
    snap["atCutFrom"] = boundary["from"]
    snap["indexSequence"] = [s.get("index") for s in samples]
    snap["footprintSources"] = [s.get("footprintSource") for s in samples]
    snap["captureOffsets"] = [s.get("captureOffsetS") for s in samples]
    snap["lastAtCutPerfMs"] = samples[split].get("perfNowMs")
    snap["firstSettledPerfMs"] = min(
        (s["perfNowMs"] for s in settled if s.get("perfNowMs") is not None), default=None
    )
    snap["badge"]["decoded"] = len(samples)
    snap["collector"]["samples"] = len(samples)
    snap["collector"]["ok"] = p2._collector_ok(snap["collector"])
    return snap


def _authored_b_34(covered, *, prepend=None) -> dict:
    """The real B arm with an AUTHORED counter series over its covered window:
    `covered` supplies the last values of `indexSamples[FIRST_IN_HOLD_34 ..
    FREEZE_SPLIT_INDEX_34]` and its first value is repeated backwards to fill the
    rest. `prepend` adds ONE capture before the re-handoff, on the page clock it
    names -- the live pre-cover frame whose exclusion the window is scored for."""
    snap = _freeze_b_snap_34()
    samples = snap["indexSamples"]
    lo, hi = FIRST_IN_HOLD_34, snap["releaseSplitIndex"]
    span = hi - lo + 1
    values = [covered[0]] * (span - len(covered)) + list(covered)
    for k, v in enumerate(values):
        samples[lo + k]["index"] = v
    if prepend is not None:
        head = copy.deepcopy(samples[FREEZE_FLIP_INDEX_34])
        head.update(prepend)
        head["badgeSeq"] = samples[0]["badgeSeq"] - 1
        head["sceneHash"] = samples[0]["sceneHash"]
        head["progress"] = samples[0]["progress"]
        samples.insert(0, head)
        snap["releaseSplitIndex"] += 1
    return _reconcile_34(snap)


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
         "badgeRect": (dict(rect) if rect is not None else None), "measuredRect": None}
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


def test_fill_badge_coupling_null_rect_badges_still_take_the_sequence_checks():
    """Review r5 MAJOR 1. A decoded badge that painted a NULL rect (the
    re-handoff pair) used to be marked `unstable` on the capture side and so
    BYPASSED these checks -- a duplicate or reversed exempt sequence went
    unnoticed. It now walks the same path: `unstable` either way, but a
    non-increasing sequence is counted as a violation."""
    good = [_badge_sample(20, None), _badge_sample(21, None)]
    counts = p2._fill_badge_coupling(
        good, {"20": {"t": 10.0, "rect": None}, "21": {"t": 26.0, "rect": None}}
    )
    assert [s["footprintSource"] for s in good] == ["unstable", "unstable"]
    assert [s["perfNowMs"] for s in good] == [10.0, 26.0]
    assert counts["seqViolation"] == 0

    dup = [_badge_sample(20, None), _badge_sample(20, None)]
    counts = p2._fill_badge_coupling(dup, {"20": {"t": 10.0, "rect": None}})
    assert counts["seqViolation"] == 1

    rev = [_badge_sample(21, None), _badge_sample(20, None)]
    counts = p2._fill_badge_coupling(
        rev, {"20": {"t": 10.0, "rect": None}, "21": {"t": 26.0, "rect": None}}
    )
    assert counts["seqViolation"] == 1


# --- `_at_cut_boundary` (review r5 MAJOR 3, r6 MAJOR 2) --------------------- #
def _press_window_samples(press_index_value):
    """Thirteen samples on one page clock. The advance keydown lands at 1000 ms and
    the sample at index 2 is captured 5 ms AFTER it -- its screenshot follows the
    dispatch -- which `advancePressIndex + 1` used to drop. The counter is a
    healthy positive arm (no cover): monotonically increasing through the flip."""
    idx = [10, 11, press_index_value, 13, 14] + list(range(15, 23))
    hashes = ["#7"] * 5 + ["#8"] * 8
    return [
        {"index": v, "sceneHash": h, "perfNowMs": 900.0 + 50.0 * i,
         "footprintSource": "measured", "badgeSeq": 700 + i}
        for i, (v, h) in enumerate(zip(idx, hashes))
    ]


def test_at_cut_boundary_starts_at_the_first_frame_after_the_keydown():
    samples = _press_window_samples(12)
    assert p2._at_cut_boundary(samples, 1000.0) == {
        "from": 2, "ok": True, "reason": None
    }, "the press-index sample itself"


def test_at_cut_boundary_fails_closed_without_a_usable_keydown_clock():
    """Review r6 MAJOR 2. A missing timestamp, and a timestamp later than every
    badge frame, are INVALID boundaries -- distinguishable from a legitimate 0."""
    samples = _press_window_samples(12)
    missing = p2._at_cut_boundary(samples, None)
    assert missing["from"] is None and missing["ok"] is False

    late = p2._at_cut_boundary(samples, 10_000.0)
    assert late["from"] is None and late["ok"] is False

    nonfinite = p2._at_cut_boundary(samples, float("nan"))
    assert nonfinite["ok"] is False


def test_at_cut_boundary_admits_the_frame_painted_during_the_key_round_trip():
    """Review r7 MAJOR 2. The keydown lands at 1000 ms; the post-dispatch
    `performance.now()` evaluation used to return ~1012 ms because keyDown and
    keyUp are each an awaited CDP round trip. A badge painted at 1004 ms -- after
    the cut, during that round trip -- was EXCLUDED from the at-cut window, so a
    reset confined to that first frame was discarded. The page-side listener's own
    `timeStamp` puts it back INSIDE."""
    samples = [
        {"index": 10, "sceneHash": "#7", "perfNowMs": 950.0,
         "footprintSource": "measured", "badgeSeq": 700},
        {"index": 255, "sceneHash": "#7", "perfNowMs": 1004.0,
         "footprintSource": "measured", "badgeSeq": 701},
        {"index": 12, "sceneHash": "#8", "perfNowMs": 1060.0,
         "footprintSource": "measured", "badgeSeq": 702},
    ]
    keydown_ms, post_dispatch_ms = 1000.0, 1012.0
    assert p2._at_cut_boundary(samples, keydown_ms) == {"from": 1, "ok": True, "reason": None}
    assert p2._at_cut_boundary(samples, post_dispatch_ms)["from"] == 2, "the r7 blind spot"


def test_advance_key_clock_requires_exactly_one_observed_keydown():
    """The cut instant comes from the page's own listener, and only when it saw
    exactly one ACCEPTED ArrowRight keydown and rejected none. Anything else is
    `None`, which fails the arm closed rather than dating the cut from a replay,
    from a synthetic press, or from nothing."""
    assert p2._advance_key_clock({"n": 1, "rejected": 0, "t": 1000.0}) == 1000.0
    assert p2._advance_key_clock({"n": 0, "rejected": 0, "t": None}) is None, "never landed"
    assert p2._advance_key_clock({"n": 2, "rejected": 0, "t": 1000.0}) is None, "a replay"
    assert p2._advance_key_clock({"n": 1, "rejected": 0, "t": None}) is None
    assert p2._advance_key_clock({"n": 1, "rejected": 0, "t": float("inf")}) is None
    assert p2._advance_key_clock({"n": True, "rejected": 0, "t": 1000.0}) is None
    assert p2._advance_key_clock(None) is None
    # A rejected event is an untrusted or auto-repeat ArrowRight the listener
    # refused to count: the accepted one alone is no longer a sound cut.
    assert p2._advance_key_clock({"n": 1, "rejected": 1, "t": 1000.0}) is None
    assert p2._advance_key_clock({"n": 1, "t": 1000.0}) is None, "counter absent"
    assert p2._advance_key_clock({"n": 1, "rejected": True, "t": 1000.0}) is None

    samples = _press_window_samples(12)
    assert p2._at_cut_boundary(
        samples, p2._advance_key_clock({"n": 2, "rejected": 0, "t": 900.0})
    ) == {"from": None, "ok": False, "reason": "no advance keydown page clock"}


def test_advance_key_observed_once_refuses_absence_and_contamination():
    assert p2._advance_key_observed_once(
        {"advanceKeyEvents": 1, "advanceKeyRejected": 0}
    ) is True
    for snap in (
        {},                                                        # both absent
        {"advanceKeyRejected": 0},                                 # count absent
        {"advanceKeyEvents": 1},                                   # rejects absent
        {"advanceKeyEvents": 0, "advanceKeyRejected": 0},          # never landed
        {"advanceKeyEvents": 2, "advanceKeyRejected": 0},          # a replay
        {"advanceKeyEvents": 1, "advanceKeyRejected": 1},          # synthetic/repeat
        {"advanceKeyEvents": True, "advanceKeyRejected": 0},       # bool is not 1
        {"advanceKeyEvents": None, "advanceKeyRejected": None},
    ):
        assert p2._advance_key_observed_once(snap) is False, snap


def test_at_cut_boundary_zero_is_legitimate_and_not_an_error():
    """A keydown at or before the first badge frame really does put the whole
    capture at the cut -- `from == 0` with `ok` True, which the scorer must not
    confuse with the None above (this is the live schedule: atCutFrom == 0)."""
    samples = _press_window_samples(12)
    boundary = p2._at_cut_boundary(samples, samples[0]["perfNowMs"])
    assert boundary == {"from": 0, "ok": True, "reason": None}
    assert p2._at_cut_boundary(samples, 0.0)["from"] == 0


# --- page-side collector series (review r6 MAJOR 1) ------------------------- #
def _collector_row(t: float, **overrides) -> dict:
    row = {
        "t": t, "hash": "#8", "progress": 0.5, "fp": [1.0, 2.0, 3.0, 4.0],
        "owner": {"elId": 4, "key": "movie1", "via": "keyed"},
        "media": {"currentTime": 1.2}, "pool": [],
    }
    row.update(overrides)
    return row


def _collector_dump(times, **overrides) -> dict:
    dump = {"rows": [_collector_row(t) for t in times], "dropped": 0, "errors": 0,
            "started": 0.0, "running": True}
    dump.update(overrides)
    return dump


def _collector_meta_for(dump: dict, sample_times) -> dict:
    """The capture side's own arithmetic: series metadata, then one bracket
    lookup per capture sample."""
    meta = p2._collector_series_meta(dump)
    rows = dump.get("rows") or []
    unbracketed = sum(
        1 for t in sample_times
        if any(r is None for r in p2._collector_rows_for(rows, t))
    )
    meta["samples"] = len(list(sample_times))
    meta["unbracketed"] = unbracketed
    meta["ok"] = p2._collector_ok(meta)
    return meta


def test_collector_series_is_sound_when_every_sample_is_bracketed():
    dump = _collector_dump([0.0, 16.0, 32.0, 48.0, 64.0])
    meta = _collector_meta_for(dump, [20.0, 40.0])
    assert meta["ok"] is True
    assert (meta["rowCount"], meta["firstT"], meta["lastT"]) == (5, 0.0, 64.0)
    assert meta["unbracketed"] == 0


def test_collector_truncated_dump_fails_closed():
    """A dump that stops before the last capture: the trailing samples have no
    row AFTER them, so they are unbracketed -- no endpoint extrapolation."""
    dump = _collector_dump([0.0, 16.0, 32.0])
    meta = _collector_meta_for(dump, [8.0, 100.0])
    assert meta["unbracketed"] == 1
    assert meta["ok"] is False
    assert p2._collector_rows_for(dump["rows"], 100.0) == (None, None)
    assert p2._collector_rows_for(dump["rows"], -5.0) == (None, None)


def test_collector_gap_containing_a_sample_fails_closed():
    """The exact r6 counter-example: a dropped interval that happens to contain a
    decoder handoff must not hand its captures the neighbouring healthy rows."""
    dump = _collector_dump([0.0, 16.0, 500.0, 516.0], dropped=12)
    meta = _collector_meta_for(dump, [8.0, 250.0])
    assert meta["dropped"] == 12
    assert meta["ok"] is False, "the ring dropped rows"

    # ...and even with `dropped` unreported, the sample inside the gap IS
    # bracketed by rows 16.0 and 500.0, so the drop counter is what catches it.
    honest = _collector_meta_for(_collector_dump([0.0, 16.0, 500.0, 516.0]), [8.0, 250.0])
    assert honest["unbracketed"] == 0 and honest["ok"] is True


def test_collector_non_monotonic_rows_fail_closed():
    dump = _collector_dump([0.0, 32.0, 16.0, 48.0])
    meta = _collector_meta_for(dump, [8.0])
    assert meta["monotonicOk"] is False
    assert meta["ok"] is False


def test_collector_missing_field_fails_closed():
    for field in p2.COLLECTOR_ROW_FIELDS:
        dump = _collector_dump([0.0, 16.0, 32.0])
        dump["rows"][1][field] = None
        meta = _collector_meta_for(dump, [8.0])
        assert meta["schemaOk"] is False, field
        assert meta["ok"] is False, field


def test_collector_page_side_error_and_empty_series_fail_closed():
    assert _collector_meta_for(_collector_dump([0.0, 16.0], errors=1), [8.0])["ok"] is False
    assert _collector_meta_for(_collector_dump([]), [8.0])["ok"] is False
    assert _collector_meta_for(_collector_dump([0.0, 16.0]), [])["ok"] is False, "no captures"
    assert p2._collector_series_meta(None)["schemaOk"] is False


def test_collector_undecoded_sample_time_is_unbracketed():
    """A capture with no page clock at all (`None`) cannot be bracketed."""
    dump = _collector_dump([0.0, 16.0, 32.0])
    assert p2._collector_rows_for(dump["rows"], None) == (None, None)
    assert _collector_meta_for(dump, [None, 8.0])["ok"] is False


# --- raw capture clocks only (review r7 MAJOR 1) ---------------------------- #
def test_collector_sample_times_never_substitutes_a_neighbours_clock():
    """The production seam hands the bracketer each capture's OWN clock. The
    neighbour fill still exists for diagnostics, and this is the divergence it
    used to hide: the same series calls the gap sound when a neighbour's clock is
    borrowed, and unbracketed when it is not."""
    samples = [
        {"perfNowMs": 900.0}, {"perfNowMs": 950.0},
        {"perfNowMs": None},  # post-cover, pre-flip: the badge did not decode
        {"perfNowMs": 1050.0}, {"perfNowMs": 1100.0},
    ]
    raw = p2._collector_sample_times(samples)
    assert raw == [900.0, 950.0, None, 1050.0, 1100.0]

    dump = _collector_dump([880.0, 920.0, 960.0, 1000.0, 1040.0, 1080.0, 1120.0])
    assert _collector_meta_for(dump, raw)["unbracketed"] == 1
    assert _collector_meta_for(dump, raw)["ok"] is False
    borrowed = p2._nearest_sample_times(raw)
    assert _collector_meta_for(dump, borrowed)["unbracketed"] == 0
    assert _collector_meta_for(dump, borrowed)["ok"] is True, "the r7 counter-example"


def test_collector_truncated_endpoint_with_no_badge_clock_fails_closed():
    """A collector that started late or ended early AND an endpoint capture whose
    badge never decoded: the neighbour fill used to lend that endpoint an interior
    clock and keep the series sound. On raw clocks both endpoints are unbracketed,
    which is what reds MAIN's `advanceOk`."""
    raw = p2._collector_sample_times(
        [{"perfNowMs": None}, {"perfNowMs": 950.0}, {"perfNowMs": 1000.0},
         {"perfNowMs": None}]
    )
    late_start = _collector_dump([940.0, 960.0, 1010.0, 1060.0])
    early_end = _collector_dump([900.0, 940.0, 960.0, 1010.0])
    for dump in (late_start, early_end):
        assert _collector_meta_for(dump, raw)["unbracketed"] == 2
        assert _collector_meta_for(dump, raw)["ok"] is False
        assert _collector_meta_for(dump, p2._nearest_sample_times(raw))["ok"] is True


def _sound_badge_snap(n: int = 3) -> dict:
    rect = {"x": 1.0, "y": 2.0, "w": 30.0, "h": 40.0}
    samples = [
        {"index": 40 + i, "badgeSeq": 900 + i, "perfNowMs": 100.0 + i,
         "badgeRect": dict(rect), "measuredRect": dict(rect),
         "footprintSource": "measured"}
        for i in range(n)
    ]
    return {
        "indexSamples": samples,
        "badge": {"install": {"ok": True}, "decoded": n, "missing": 0, "crcBad": 0,
                  "unlogged": 0, "counts": {"seqViolation": 0}},
    }


def test_badge_samples_sound_requires_every_capture_to_carry_its_own_frame():
    sound = _sound_badge_snap()
    assert p2._badge_samples_sound(sound) is True
    for key in ("missing", "crcBad", "unlogged"):
        bad = {**sound, "badge": {**sound["badge"], key: 1}}
        assert p2._badge_samples_sound(bad) is False, key
    torn = {**sound, "badge": {**sound["badge"], "counts": {"seqViolation": 1}}}
    assert p2._badge_samples_sound(torn) is False
    assert p2._badge_samples_sound(
        {**sound, "badge": {**sound["badge"], "install": None}}
    ) is False
    assert p2._badge_samples_sound({}) is False


def test_badge_samples_sound_requires_a_usable_geometry_not_just_transport():
    """r8 MAJOR 1: a CRC-valid, logged, in-order badge whose painted rect
    disagrees with the page log is `unstable` -- transport-sound, geometry-junk.
    It must not leave the arm sound."""
    sound = _sound_badge_snap()
    for source in ("unstable", "modelled", "none", None):
        bad = {**sound, "indexSamples": [
            {**sound["indexSamples"][0], "footprintSource": source},
            *sound["indexSamples"][1:],
        ]}
        assert p2._badge_samples_sound(bad) is False, source
    # `install` present but not OK, and a short decode count, are both refused.
    assert p2._badge_samples_sound(
        {**sound, "badge": {**sound["badge"], "install": {"ok": False}}}
    ) is False
    assert p2._badge_samples_sound(
        {**sound, "badge": {**sound["badge"], "install": {}}}
    ) is False
    assert p2._badge_samples_sound(
        {**sound, "badge": {**sound["badge"], "decoded": 2}}
    ) is False, "one capture decoded nothing"
    assert p2._badge_samples_sound(
        {**sound, "indexSamples": []}
    ) is False, "no samples is not soundness"


def test_badge_samples_sound_exempts_only_the_validated_rehandoff_pair():
    """The ONLY admissible non-`measured` sample is one of the re-handoff pair's
    deliberate null-rect frames, and only when the scorer passes that validated
    pair in. Absent the exemption the same sample fails the arm closed."""
    sound = _sound_badge_snap()
    null_sample = {"index": None, "badgeSeq": 900, "badgeRect": None,
                   "perfNowMs": 100.0, "footprintSource": "unstable"}
    snap = {**sound, "indexSamples": [null_sample, *sound["indexSamples"][1:]]}
    assert p2._badge_samples_sound(snap, {900, 901}) is True
    assert p2._badge_samples_sound(snap) is False, "no exemption passed in"
    assert p2._badge_samples_sound(snap, set()) is False
    assert p2._badge_samples_sound(snap, {777, 778}) is False, "some other pair"
    # A sample that DID decode a rect is a real observation: never exempt.
    decoded = {**null_sample, "index": 41, "badgeRect": {"x": 1.0}}
    assert p2._badge_samples_sound(
        {**sound, "indexSamples": [decoded, *sound["indexSamples"][1:]]}, {900, 901}
    ) is False


def test_moving_index_run_at_cut_refuses_an_invalid_boundary():
    """`covered_from=None` means "no valid boundary", never index 0 -- the run is
    not scored and the window is not decodable, so the arm fails closed."""
    result, decodable = p2._moving_index_run_at_cut(_cut_samples(), covered_from=None)
    assert decodable is False
    assert result["ok"] is False and result["reason"] == "no valid at-cut boundary"


def test_at_cut_segment_keeps_an_anomalous_press_index_sample():
    """Review r5 MAJOR 3. An anomaly confined to the first post-keydown frame --
    a transient reset, a wrong ROI -- must reach the scorer. Under
    `advancePressIndex + 1` it was discarded and the arm greened for the wrong
    reason."""
    start = 2
    clean, _ = p2._moving_index_run_at_cut(_press_window_samples(12), covered_from=start)
    assert clean["ok"] is True, clean

    # 11 -> 140 is a mod-256 jump of 129, i.e. a backward step past half the
    # modulo: `negativeAnomaly`, the transient-reset signature.
    anomalous = _press_window_samples(140)
    assert p2._at_cut_boundary(anomalous, 1000.0)["from"] == start
    run, decodable = p2._moving_index_run_at_cut(anomalous, covered_from=start)
    assert decodable is True
    assert run["ok"] is False, run

    # ...while the OLD rule's segment, one sample later, is green.
    old_run, _ = p2._moving_index_run_at_cut(anomalous, covered_from=start + 1)
    assert old_run["ok"] is True, old_run


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
    result, decodable = p2._moving_index_run_at_cut(samples, covered_from=0)
    assert result["flipIndexFull"] == 3
    assert decodable is True


def test_moving_index_run_at_cut_measured_but_undecoded_is_not_decodable():
    """A `measured` sample whose patch did NOT decode (`index is None`) must not
    count as a decodable flip window (review BLOCKER 3: the old predicate checked
    only the source tag, so an all-None window scored a freeze run)."""
    samples = _cut_samples()
    samples[4]["index"] = None
    result, decodable = p2._moving_index_run_at_cut(samples, covered_from=0)
    assert decodable is False
    assert result["ok"] is False and result["reason"] == "flip window not decodable"


def test_moving_index_run_at_cut_all_none_window_never_scores_a_freeze_run():
    """The exact r2 counter-example: flip + FREEZE_MIN_AFTER samples all
    `measured` with `index=None` must NOT produce `freeze run at cut`."""
    samples = _cut_samples()
    for s in samples[3:]:
        s["index"] = None
    result, decodable = p2._moving_index_run_at_cut(samples, covered_from=0)
    assert decodable is False
    assert result.get("freezeRunAtCut") is None


def test_moving_index_run_at_cut_needs_strictly_after_flip_samples():
    """FREEZE_MIN_AFTER samples STRICTLY after the flip -- the flip sample itself
    does not count towards them (the release off-by-one)."""
    short = _cut_samples(n_after=p2.FREEZE_MIN_AFTER - 1)
    assert p2._moving_index_run_at_cut(short, covered_from=0)[1] is False
    assert p2._moving_index_run_at_cut(_cut_samples(), covered_from=0)[1] is True


def test_moving_index_run_at_cut_ignores_post_release_samples():
    """Samples after the covered segment cannot contribute to the run or to
    `n - flipIndex` (review BLOCKER 3: post-release contamination)."""
    samples = _cut_samples()
    samples += [{"index": 100 + i, "sceneHash": "#8", "footprintSource": "measured"} for i in range(8)]
    covered = 3 + p2.FREEZE_MIN_AFTER
    result, decodable = p2._moving_index_run_at_cut(samples, covered_until=covered, covered_from=0)
    assert decodable is True
    assert result["n"] == covered + 1
    assert result["n"] - result["flipIndex"] == p2.FREEZE_MIN_AFTER + 1


def test_moving_index_run_at_cut_truncated_window_is_not_decodable():
    """A covered segment that stops before flip + FREEZE_MIN_AFTER cannot judge
    the cut."""
    samples = _cut_samples()
    result, decodable = p2._moving_index_run_at_cut(samples, covered_until=3 + 2, covered_from=0)
    assert decodable is False
    assert result["ok"] is False


def test_moving_index_run_at_cut_no_slide4_sample():
    samples = [{"index": 30 + i, "sceneHash": "#7", "footprintSource": "measured"} for i in range(5)]
    result, decodable = p2._moving_index_run_at_cut(samples, covered_from=0)
    assert decodable is False
    assert result["reason"] == "no sample reached slide 4"


def test_moving_index_run_at_cut_positive_arm_is_green():
    """The live positive arm's shape: an advancing counter through the cut scores
    `ok` with no freeze run -- the negative control's counterpart."""
    result, decodable = p2._moving_index_run_at_cut(_cut_samples(frozen=False), covered_from=0)
    assert decodable is True
    assert result["ok"] is True and result["freezeRunAtCut"] == 0


def test_freeze_control_passes_on_clean_bracket():
    """Positive control for the instrument: a correctly-fired freeze turns the
    at-cut counter RED for the right reason while the bridged decoder stays live,
    both bracketing positives are green, and every invariant sub-verdict is equal
    (and GREEN) across A1/B/A2 -- including `settledIndexProgressionOk`, which is
    genuinely green in B too because the cover is released before the settled
    window (review Blocker 3)."""
    verdict = _score_34(_positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["ok"] is True, verdict["failed"]
    assert verdict["verdict"] == "pass"
    assert verdict["isolationDiffs"] == {}


def test_freeze_control_unsound_collector_is_inconclusive_in_every_arm():
    """Review r6 MAJOR 1. The page-side evidence series is gated in ALL THREE
    arms: a gapped or truncated dump anywhere makes the bracket INCONCLUSIVE, not
    a verdict about the counter."""
    for arm in ("a1", "b", "a2"):
        snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
        snaps[arm]["collector"] = {**snaps[arm]["collector"], "unbracketed": 1, "ok": False}
        verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
        assert verdict["verdict"] == "inconclusive", arm
        assert "collectorSeriesSound" in verdict["integrityFailed"], arm

    missing = _freeze_b_snap_34()
    missing.pop("collector")
    verdict = _score_34(_positive_snap_34(), missing, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "collectorSeriesSound" in verdict["integrityFailed"]


def test_freeze_control_post_cover_missing_badge_is_inconclusive_in_every_arm():
    """Review r7 MAJOR 1, end to end. A post-cover/pre-flip capture whose badge
    went missing has no clock of its own, so the production bracketer (raw clocks,
    no neighbour fill) counts it unbracketed AND the arm's badge counters are
    dirty. Either route alone makes the bracket INCONCLUSIVE -- it must never be
    able to drop out of the in-hold lists and leave the later frozen frames to
    carry a PASS."""
    first_covered = FIRST_IN_HOLD_34
    for arm in ("a1", "b", "a2"):
        snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
        snap = snaps[arm]
        _with_sample(snap, first_covered, footprintSource="none", index=None,
                     perfNowMs=None, badgeSeq=None, badgeRect=None)
        raw = p2._collector_sample_times(snap["indexSamples"])
        dump = _collector_dump(
            [t - 10.0 for t in raw if t is not None] + [max(t for t in raw if t) + 10.0]
        )
        snap["collector"] = _collector_meta_for(dump, raw)
        snap["badge"] = {**snap["badge"], "missing": 1,
                         "counts": {**snap["badge"]["counts"], "none": 1}}
        assert snap["collector"]["unbracketed"] == 1, arm
        verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
        assert verdict["verdict"] == "inconclusive", (arm, verdict["failed"])
        assert "collectorSeriesSound" in verdict["integrityFailed"], arm
        assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], arm


def test_freeze_control_torn_or_unlogged_badges_are_inconclusive_in_every_arm():
    """...and so is a CRC-torn, unlogged or out-of-sequence badge, even when the
    surviving captures happen to bracket cleanly."""
    for arm in ("a1", "b", "a2"):
        for field, value in (("crcBad", 1), ("unlogged", 1), ("counts", None)):
            snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(),
                     "a2": _a2_snap_34()}
            badge = snaps[arm]["badge"]
            if field == "counts":
                badge = {**badge, "counts": {**badge["counts"], "seqViolation": 1}}
            else:
                badge = {**badge, field: value}
            snaps[arm]["badge"] = badge
            verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
            assert verdict["verdict"] == "inconclusive", (arm, field)
            assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], (arm, field)


def test_freeze_control_invalid_at_cut_boundary_is_inconclusive_in_every_arm():
    """Review r6 MAJOR 2. No keydown page clock, or one later than every badge
    frame, is an invalid cut boundary in any arm -- the positives must not stay
    green off a boundary that was silently index 0."""
    for arm in ("a1", "b", "a2"):
        snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
        snaps[arm]["advanceKeyPerfMs"] = None
        snaps[arm]["atCutBoundary"] = p2._at_cut_boundary(snaps[arm]["indexSamples"], None)
        snaps[arm]["atCutFrom"] = None
        verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
        assert verdict["verdict"] == "inconclusive", arm
        assert "atCutBoundaryValidAllArms" in verdict["integrityFailed"], arm

    late = _positive_snap_34()
    late["atCutBoundary"] = p2._at_cut_boundary(late["indexSamples"], 1e9)
    late["advanceKeyPerfMs"] = 1e9
    verdict = _score_34(late, _freeze_b_snap_34(), _a2_snap_34())
    assert "atCutBoundaryValidAllArms" in verdict["integrityFailed"]


def test_freeze_control_at_cut_boundary_zero_still_passes():
    """...while a LEGITIMATE `from == 0` -- the live schedule -- is admissible
    and the clean bracket still passes (no fail-closed overreach)."""
    a1, b, a2 = _positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()
    # A keydown at or before the first capture: the whole series is at-cut. B's
    # control listener saw the SAME event, so both clocks move together.
    for snap in (a1, b, a2):
        first_perf = min(s["perfNowMs"] for s in snap["indexSamples"])
        snap["advanceKeyPerfMs"] = first_perf
        snap["atCutBoundary"] = p2._at_cut_boundary(snap["indexSamples"], first_perf)
        assert snap["atCutBoundary"]["from"] == 0 and snap["atCutBoundary"]["ok"] is True
    b["nullControl"]["advanceKeyAt"] = b["advanceKeyPerfMs"]
    verdict = _score_34(a1, b, a2)
    assert verdict["verdict"] == "pass", verdict["failed"]


def test_freeze_control_arm_failure_is_inconclusive():
    """Review BLOCKER 1: a control that never armed cannot judge anything -- the
    recorded arm error must surface as INCONCLUSIVE, never as a verdict."""
    b = _freeze_b_snap_34()
    b["armResult"] = {"ok": False, "error": "owner-unresolved-at-arm"}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "drainPressesAllLanded" in verdict["integrityFailed"]


def test_freeze_control_missing_drain_block_fails_closed():
    """No drain record at all (an older snapshot, a capture that died early) is
    NOT evidence of a clean drain -- it must fail closed to INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b.pop("drain")
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_contaminated_positive_drain_is_inconclusive(arm):
    """Round-3 review nit: `drainPressesAllLanded` read only arm B's drain, so a
    POSITIVE whose 3->4 move was started by a replayed queued press still counted
    towards `positivesGreen`. A1 and A2 are held to the SAME condition -- a
    contaminated positive is a different stimulus, so the bracket is
    INCONCLUSIVE, never a verdict."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    snaps[arm]["drain"] = {
        **snaps[arm]["drain"], "pressesSent": 5, "pressesLanded": 4,
        "unlandedFromHash": [5], "allPressesLanded": False, "ok": False,
    }
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False
    assert "drainPressesAllLanded" in verdict["integrityFailed"]
    assert verdict["verdictFailed"] == []


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_positive_drain_overshoot_is_inconclusive(arm):
    """A positive that overshot the arm boundary drained past `#7` too."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    snaps[arm]["drain"] = {**snaps[arm]["drain"], "hashAtArm": "#8", "hashAtArmExact": False}
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "drainPressesAllLanded" in verdict["integrityFailed"]


@pytest.mark.parametrize("arm", ["a1", "a2"])
def test_freeze_control_missing_positive_drain_block_fails_closed(arm):
    """Fail CLOSED on a missing block in a positive arm, exactly as for B."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    snaps[arm].pop("drain")
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert verdict["checks"]["drainPressesAllLanded"] is False
    assert verdict["drains"][arm] is None


def test_freeze_control_never_fired_hold_is_inconclusive_not_pass():
    """A hold that silently never fired (holdStartedAt null) leaves the counter
    GREEN in B, which looks exactly like a passing positive. It MUST be
    INCONCLUSIVE, not PASS and not a plain FAIL."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "status": "armed", "holdStartedAt": None}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "maxRafGapOk" in verdict["integrityFailed"]


def test_freeze_control_trigger_to_first_frame_gap_is_disqualifying():
    """`maxRafGapOk` also bounds the gap between the move-start TRIGGER and the
    first hold frame (review MAJOR 5) -- not just gaps between logged frames."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    raf[0] = {**raf[0], "t": raf[0]["t"] + 500.0}  # first frame lags the trigger by 500ms
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert {"staleFrameFromPlayback", "noControlError"} & set(verdict["integrityFailed"])


def test_freeze_control_valid_dark_counter_not_rejected():
    """Regression: a valid counter near the DARK end of its cycle decodes to RGB
    ~0 (tv-range luma 16 -> full-range RGB ~0). It must NOT be rejected as
    'black' — a genuinely frozen dark frame from live playback still PASSES."""
    b = _authored_b_34([2])
    b["nullControl"] = {**b["nullControl"], "staleCurrentTime": 7.33, "coverPatchMean": 2.0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "pass", verdict["failed"]


def test_freeze_control_owner_not_ready_is_inconclusive():
    """If the footprint owner was not a decoded video at trigger (readyState < 2),
    the stale frame was not captured from a real frame => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "ownerReadyState": 0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "ownerReadyAtTrigger" in verdict["integrityFailed"]


def test_freeze_control_fired_before_advance_is_inconclusive():
    """A trigger that fired BEFORE the in-page advance keydown held a pre-cut
    frame, not the cut => INCONCLUSIVE (review BLOCKER 2, one clock)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "holdStartedAt": ADVANCE_KEY_AT_34 - 30.0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAfterAdvance" in verdict["integrityFailed"]


def test_freeze_control_no_advance_timestamp_is_inconclusive():
    """No in-page advance timestamp at all means there is no causality evidence
    -- INCONCLUSIVE, never a verdict."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "advanceKeyAt": None}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAfterAdvance" in verdict["integrityFailed"]


def test_freeze_control_pre_advance_departure_is_inconclusive():
    """A rect departure seen BEFORE the advance keydown means the move was
    already running (or the stage jittered): the hold cannot be attributed to the
    cut => INCONCLUSIVE with the departure recorded."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "preAdvanceDepartureAt": ADVANCE_KEY_AT_34 - 100.0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    for i in range(FIRST_IN_HOLD_34, FREEZE_SPLIT_INDEX_34 + 1):
        b = _with_sample(b, i, index=40 + i)  # advancing again -> no freeze to catch
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["ok"] is False
    assert "freezeRunMargin" in verdict["failed"] or "everyInHoldStale" in verdict["integrityFailed"]


def test_freeze_control_fails_when_freeze_leaked_into_liveness():
    """The RED must be ISOLATED to the counter: if a sub-verdict that should be
    invariant (here movingContinuity3to4) differs in B, the freeze was not clean
    => fail on isolation (or its own key), never a spurious pass."""
    b = _freeze_b_snap_34()
    b["movingContinuity3to4"] = {**b["movingContinuity3to4"], "ok": False, "failed": ["rvfcMonotonic"]}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["ok"] is False
    assert "isolationEqual" in verdict["failed"] or "movingContinuityOk" in verdict["failed"]


def test_freeze_control_fails_when_bound_decoder_is_not_slide3_decoder():
    """The cover must have bound the SAME decoder that played slide 3; otherwise
    the freeze proved nothing about the decoder under test."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "boundDecoderId": 99}  # cover bound a different el
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(a_bad, _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["ok"] is False
    assert "positivesGreen" in verdict["failed"]


def test_freeze_control_hash_only_trigger_is_inconclusive():
    """`firedVia == 'hash'` means the move is already OVER and the cover tracked
    nothing during the move: `firedAtMoveStart` requires `firedVia == 'moved'` (a
    MEASURED departure of the bound owner's rect from its armed rect), never a
    hash-only fallback fire — INCONCLUSIVE (owner decision 8c)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "firedVia": "hash"}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverTracksFootprint" in verdict["integrityFailed"]


def test_freeze_control_release_after_burst_started_is_inconclusive():
    """A release that slips past the settled-slide-4 visible-content burst start
    leaves the cover in place for part of the burst — it would red
    `footprintFullyLive` for the WRONG reason. `releaseStrictlyBeforeSettleAndBurst`
    is bounded on both sides: INCONCLUSIVE, not a verdict."""
    b = _freeze_b_snap_34()
    b["burstStartPerfMs"] = b["nullControl"]["releaseAt"] - 10.0
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_release_not_strictly_after_last_capture_is_inconclusive():
    """The check is STRICT (`<`, not `<=`): a release that lands exactly ON the
    last at-cut capture must not pass — that capture's cover state at the instant
    of the screenshot is ambiguous."""
    b = _freeze_b_snap_34()
    b["lastAtCutPerfMs"] = b["nullControl"]["releaseAt"]
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_release_not_strictly_before_settled_is_inconclusive():
    """The other bound: release must land STRICTLY before the first post-split
    settled sample, not merely before the burst (review Blocker 3)."""
    b = _freeze_b_snap_34()
    b["firstSettledPerfMs"] = b["nullControl"]["releaseAt"]
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]


def test_freeze_control_modelled_in_hold_sample_is_inconclusive():
    """A `modelled` (not measured) footprint sample inside the hold window means
    the ROI mapping for that decode is unproven — `allInHoldMeasured` fails
    closed rather than trusting a decode off an unverified ROI."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 1, footprintSource="modelled")
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_unstable_in_hold_sample_is_inconclusive():
    """An `unstable` sample (before/after screenshot rect reads disagreed,
    review Blocker 2b) inside the hold window is just as untrustworthy as a
    `modelled` one — `allInHoldMeasured` fails closed."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 1, footprintSource="unstable")
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_isolation_mismatch_fails():
    """`footprintFullyLive` differing between A1 and B (a sub-verdict that must be
    invariant, since the burst is captured AFTER release) fails the bracket on
    isolation, never a spurious pass."""
    a1 = _positive_snap_34()
    a1["footprintFullyLive"] = {"ok": False}
    verdict = _score_34(a1, _freeze_b_snap_34(), _a2_snap_34())
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
    a2 = _all_false(_a2_snap_34())
    b = _all_false(_freeze_b_snap_34())
    verdict = _score_34(a1, b, a2)
    assert verdict["ok"] is False
    assert "isolationEqual" in verdict["failed"]


def test_freeze_control_stage_origin_nonzero_is_inconclusive():
    """The partial cover is `position:fixed` (viewport px) while the moving
    <video> is stage-absolute px — they only coincide while the stage origin is
    (0,0). A nonzero origin at arm invalidates the geometry => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "stageOrigin": {"x": 12.0, "y": 0.0}}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "stageOriginZero" in verdict["integrityFailed"]


def test_freeze_control_flip_window_undecodable_is_inconclusive():
    """`flipWindowDecodable` is RECOMPUTED by the scorer from the raw samples
    (review BLOCKER 3) -- a capture-side boolean claiming otherwise cannot green
    it, and an undecodable flip window is INCONCLUSIVE."""
    b = _with_sample(_freeze_b_snap_34(), FREEZE_FLIP_INDEX_34 + 2, index=None)
    b["flipWindowDecodable"] = True  # the capture-side claim is ignored
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "flipWindowDecodable" in verdict["integrityFailed"]


def test_freeze_control_post_release_samples_do_not_pad_after_flip():
    """`enoughAfterFlip` counts only samples inside the covered at-cut segment:
    a short segment cannot be padded by post-release settled samples."""
    b = _freeze_b_snap_34()
    b["releaseSplitIndex"] = FREEZE_FLIP_INDEX_34 + 2
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert {"enoughAfterFlip", "flipWindowDecodable"} & set(verdict["integrityFailed"])


def test_freeze_control_owner_disconnected_mid_hold_is_inconclusive():
    """Once bound by element id, the SAME element must stay connected/keyed for
    the whole hold (review MAJOR 4's de-vacuumed `noOwnerAmbiguousInWindow`) — a
    disconnect fails it closed even with `ownerAmbiguousInWindow` itself False."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "ownerDisconnectedInWindow": True}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["ok"] is False
    assert "noOwnerAmbiguousInWindow" in verdict["failed"]


def test_freeze_control_bound_decoder_id_changes_mid_hold_fails_ambiguity():
    """`noOwnerAmbiguousInWindow` also requires the LOGGED `boundDecoderId` to
    stay the SAME element for every rAF frame, not just at the end."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    raf[10] = {**raf[10], "boundDecoderId": 99}
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    b = _authored_b_34([28] * 10, prepend={"index": 29, "perfNowMs": HOLD_STARTED_AT_34 + 1.0})
    b["nullControl"] = {**b["nullControl"], "coverPatchMean": 28.0}
    # Capture 0 is the pre-cover one: live at 29, timestamped between the trigger
    # and the cover actually being painted; 1 is the badge's re-handoff frame.
    raw = [s["index"] for s in b["indexSamples"][: b["releaseSplitIndex"] + 1]]
    assert raw[0] == 29 and raw[2:5] == [28, 28, 28], "the live shape, before trimming"

    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "pass", verdict["failed"]
    assert verdict["movingIndexRunAtCut"]["negativeAnomaly"] is False
    assert verdict["movingIndexRunAtCut"]["reason"] == "freeze run at cut"
    assert 29 in [s["index"] for s in b["indexSamples"]], "kept for diagnostics"


def test_freeze_control_missing_cover_painted_at_fails_closed():
    """No `coverPaintedAt`, no window: the scorer must not silently fall back to
    `holdStartedAt` (which is the defect) nor to "everything"."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "coverPaintedAt": None}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverPaintedAtPresent" in verdict["integrityFailed"]


def _with_rehandoff(b: dict, n: int, seq0: int = REHANDOFF_SEQ0_34) -> dict:
    """Turn the first `n` COVERED samples into the badge's own re-handoff frames:
    null rect, nothing decoded, sequences the badge logged as a contiguous pair.
    """
    first = FIRST_IN_HOLD_34
    for k in range(n):
        b = _with_sample(b, first + k, footprintSource="unstable", index=None,
                         badgeRect=None, badgeSeq=seq0 + k)
    # The pair's frames DECODE and ARE logged -- they just paint a null rect --
    # so the arm's badge counters stay clean and only `unstable` moves.
    counts = dict(b["badge"]["counts"])
    counts["measured"] -= n
    counts["unstable"] += n
    b["badge"] = {**b["badge"], "counts": counts,
                  "stats": {**b["badge"]["stats"], "rehandoffs": 1,
                            "rehandoffSeqs": [seq0, seq0 + 1]}}
    return b


def test_freeze_control_window_opens_after_the_badges_own_rehandoff():
    """LIVE (bracket run0): the badge's re-handoff onto the fresh 3->4 pin lands
    ONE frame before the cover is painted and paints a NULL rect for the
    contiguous pair of frames it spans, so the first covered capture is often one
    of them. Those -- and only those -- are excused: they decoded nothing, so they
    are no evidence either way."""
    for n in (1, 2):
        b = _with_rehandoff(_freeze_b_snap_34(), n)
        verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
        assert verdict["verdict"] == "pass", (n, verdict["failed"])
        assert verdict["freeze"]["rehandoffExemptSamples"] == n
        assert verdict["freeze"]["firstCoveredPosition"] == FIRST_IN_HOLD_34 + n


def test_freeze_control_leading_unstable_with_a_live_decode_is_inconclusive():
    """Review r4 BLOCKER 1. An unguarded leading skip let a CRC/sequence/coupling
    failure that still DECODED a live counter open the window past itself, and
    later frozen frames then carried the verdict. A leading `unstable` sample that
    decoded something is a real observation on an uncoupled frame: INCONCLUSIVE."""
    first = FIRST_IN_HOLD_34
    b = _with_sample(_freeze_b_snap_34(), first, footprintSource="unstable", index=255)
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]

    # ...and a null-rect leading sample the badge did NOT log as a re-handoff
    # buys no exemption either.
    b2 = _with_sample(_freeze_b_snap_34(), first, footprintSource="unstable",
                      index=None, badgeRect=None, badgeSeq=999)
    v2 = _score_34(_positive_snap_34(), b2, _a2_snap_34())
    assert v2["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v2["integrityFailed"]

    # ...nor does a LONE logged sequence that is not part of a contiguous pair.
    b3 = _with_rehandoff(_freeze_b_snap_34(), 1)
    b3["badge"] = {"stats": {"rehandoffs": 1, "rehandoffSeqs": [4100, 4150],
                             "motionStartedAt": HOLD_STARTED_AT_34}}
    v3 = _score_34(_positive_snap_34(), b3, _a2_snap_34())
    assert v3["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v3["integrityFailed"]

    # ...and an unstable sample in the MIDDLE of the hold still reds it.
    b4 = _with_sample(_freeze_b_snap_34(), first + 2, footprintSource="unstable")
    v4 = _score_34(_positive_snap_34(), b4, _a2_snap_34())
    assert v4["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in v4["integrityFailed"]


def test_freeze_control_more_rehandoff_frames_than_the_badge_paints_is_inconclusive():
    """The re-handoff spans exactly two frames; a third excused sample means the
    badge was not doing what its own contract says."""
    b = _with_rehandoff(_freeze_b_snap_34(), 3)
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_rejects_a_malformed_or_foreign_rehandoff():
    """Review r5 MAJOR 1. Two captures of the SAME exempt sequence, a reversed
    pair, or one sample from each of several re-handoffs could all consume the
    two-sample allowance and PASS, because `badge.stats.rehandoffs` was never
    gated and the pair was never tied to the trigger's own marker."""
    p0 = REHANDOFF_SEQ0_34

    def stats(**over):
        base = {"rehandoffs": 1, "rehandoffSeqs": [p0, p0 + 1],
                "motionStartedAt": HOLD_STARTED_AT_34}
        base.update(over)
        return {"stats": base}

    cases = {
        "duplicate": stats(rehandoffSeqs=[p0, p0]),
        "reversed": stats(rehandoffSeqs=[p0 + 1, p0]),
        "multi": {"stats": {"rehandoffs": 2,
                            "rehandoffSeqs": [p0, p0 + 1, p0 + 40, p0 + 41],
                            "motionStartedAt": HOLD_STARTED_AT_34}},
        "foreign-generation": stats(motionStartedAt=HOLD_STARTED_AT_34 - 900.0),
        "missing-stats": {},
    }
    for name, badge in cases.items():
        b = _with_rehandoff(_freeze_b_snap_34(), 2)
        b["badge"] = badge
        verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
        assert verdict["verdict"] == "inconclusive", name
        assert "rehandoffPairSound" in verdict["integrityFailed"], name


def test_freeze_control_rejects_two_captures_of_one_exempt_sequence():
    """The two excused captures must be DISTINCT, increasing frames of the pair;
    the same sequence read twice is an aliased read, not two re-handoff frames."""
    first = FIRST_IN_HOLD_34
    b = _with_rehandoff(_freeze_b_snap_34(), 2)
    b = _with_sample(b, first + 1, badgeSeq=REHANDOFF_SEQ0_34)
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "rehandoffPairSound" in verdict["integrityFailed"]


def test_freeze_control_rejects_a_covered_badge_measured_before_the_pair():
    """Nothing previously proved the first MEASURED covered badge came after the
    re-handoff, so the argued pin-start residual was an assumption. A covered
    measured sample whose sequence predates the pair now reds it."""
    first = FIRST_IN_HOLD_34
    b = _with_sample(_freeze_b_snap_34(), first, badgeSeq=REHANDOFF_SEQ0_34 - 5)
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "rehandoffPairSound" in verdict["integrityFailed"]


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
@pytest.mark.parametrize("settle", [{"settled": False, "stableReadings": 1}, None, "absent"])
def test_freeze_control_requires_a_settled_owner_rect_in_every_arm(arm, settle):
    """Review r5 MAJOR 2. A timed-out or still-moving `#7` owner is a different
    stimulus; the bracket recorded `ownerSettle` but never gated it, so a green
    downstream could carry a failed prerequisite to PASS."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    if settle == "absent":
        snaps[arm].pop("ownerSettle")
    else:
        snaps[arm]["ownerSettle"] = settle
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "ownerSettledAllArms" in verdict["integrityFailed"]


def test_freeze_control_no_coupled_frame_in_the_hold_fails_closed():
    """A covered span with NOTHING coupled in it is not a measured hold."""
    b = _freeze_b_snap_34()
    for i in range(FIRST_IN_HOLD_34, len(b["indexSamples"])):
        b = _with_sample(b, i, footprintSource="unstable")
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "allInHoldMeasured" in verdict["integrityFailed"]


def test_freeze_control_cover_painted_before_trigger_is_not_assumed():
    """`coverPaintedAt` is a distinct, LATER instant than `holdStartedAt`; the
    window must follow it, not the trigger."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "coverPaintedAt": 10_000.0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_pre_trigger_raf_gap_counts_towards_the_max_gap():
    """Gaps BEFORE the trigger are measured in the page from the keydown and fold
    into the same max-gap budget -- previously they were invisible."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "pollMaxGapMs": p2.MAX_RAF_GAP_MS + 1.0}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]


def test_freeze_control_missing_runtime_motion_marker_is_inconclusive():
    """Fail CLOSED: no fresh marker means nothing ties the departure to the
    runtime's move at all."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "motionStartedFrame": None}
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
        verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in verdict["integrityFailed"]

    replaced_start = {**nc["obedMotionAtTrigger"], "started": HOLD_STARTED_AT_34 + 40.0}
    b2 = _freeze_b_snap_34()
    b2["nullControl"] = {**b2["nullControl"], "obedMotionAtTrigger": replaced_start}
    v2 = _score_34(_positive_snap_34(), b2, _a2_snap_34())
    assert v2["verdict"] == "inconclusive"
    assert "firedAtRuntimeMotionStart" in v2["integrityFailed"]

    # ...and no marker at the trigger at all fails closed too.
    b3 = _freeze_b_snap_34()
    b3["nullControl"] = {**b3["nullControl"], "obedMotionAtTrigger": None}
    v3 = _score_34(_positive_snap_34(), b3, _a2_snap_34())
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
        verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
        assert verdict["verdict"] == "pass", (frames, marker, verdict["failed"])


# --- review r3 MAJOR 1: exactly one advance press, in every arm -------------- #
@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_multi_press_advance_is_inconclusive(arm):
    """A second queued press is replayed by the player and starts the move by
    itself, so the arms are no longer the same stimulus -- in ANY arm."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    snaps[arm] = {**snaps[arm], "advance": {**snaps[arm]["advance"], "pressesSent": 2, "ok": False}}
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "advanceSinglePressAllArms" in verdict["integrityFailed"]


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_missing_advance_block_fails_closed(arm):
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    snaps[arm] = {k: v for k, v in snaps[arm].items() if k != "advance"}
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive"
    assert "advanceSinglePressAllArms" in verdict["integrityFailed"]


def _pin_presented_media_time(snaps: dict) -> None:
    """The bound decoder's rVFC clock stops advancing through the hold."""
    for sample in snaps["b"]["mediaSamples"]:
        for video in sample.get("videos") or []:
            video["presentedMediaTime"] = 1.0


# --- review r3 BLOCKER 4: integrity problems are INCONCLUSIVE, not FAIL ------ #
@pytest.mark.parametrize(
    "key,mutate",
    [
        ("positivesGreen",
         lambda s: s["a1"].update(continueThroughMovingMagicMove3to4Pass=False)),
        ("rvfcRanThroughHold", _pin_presented_media_time),
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
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    mutate(snaps)
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", verdict["failed"]
    assert key in verdict["integrityFailed"]
    assert p2._freeze_control_blocks_success("inconclusive", bridge34_disabled=False) is True


def test_freeze_control_negative_anomaly_is_integrity_not_a_verdict():
    """`noNegativeAnomaly` is measurement integrity (the live failure is exactly
    that), so it must not be able to produce a FAIL against the counter."""
    b = _freeze_b_snap_34()
    b = _with_sample(b, FREEZE_FLIP_INDEX_34 + 1, index=250)  # backward past modulo/2
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
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
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "fail"
    assert verdict["integrityFailed"] == []
    assert verdict["verdictFailed"] == ["freezeRunMargin"]
    assert p2._freeze_control_blocks_success("fail", bridge34_disabled=False) is True


def test_freeze_control_a_counter_that_never_froze_is_inconclusive_not_fail():
    """...and the common "no freeze at all" shape is NOT a claim about the
    counter: the harness's own stale check reds first, so the bracket says
    INCONCLUSIVE rather than accusing the gate."""
    b = _authored_b_34([37, 38, 39, 40, 41, 42, 43, 44, 45, 46])
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["integrityFailed"] == ["everyInHoldStale"]


def test_freeze_control_verdict_tier_is_only_the_counter_response():
    """Guard the tier split itself: the verdict tier says nothing except whether
    the counter went red at the cut for the injected freeze."""
    verdict = _score_34(_positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["verdict"] == "pass"
    keys = set(verdict["checks"])
    assert keys - set(verdict["integrityFailed"]) - set(verdict["verdictFailed"])
    # The three counter-response keys, and nothing else, can produce a FAIL.
    b = _freeze_b_snap_34()
    for i in range(FIRST_IN_HOLD_34, FREEZE_SPLIT_INDEX_34 + 1):
        b = _with_sample(b, i, index=40 + i)
    v2 = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert set(v2["verdictFailed"]) <= {
        "indexRunRed", "reasonFreezeRunAtCut", "freezeRunMargin"
    }


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
    verdict = p2.footprintFullyLive(capture_id="cap-test", frames=_burst(p2.SLIDE4_MOVIE_RECT))
    assert verdict["ok"] is True
    assert verdict["verdict"] is True
    assert verdict["perRect"][0]["label"] == "slide4Movie"


def test_footprint_fully_live_red_on_a_half_dead_footprint():
    """Half the destination rect frozen => the carry is not visibly correct."""
    verdict = p2.footprintFullyLive(capture_id="cap-test", frames=_burst(p2.SLIDE4_MOVIE_RECT, live_frac=0.5))
    assert verdict["ok"] is False
    assert verdict["verdict"] is False


def test_footprint_fully_live_inconclusive_is_a_failure():
    """A noise floor above threshold yields verdict None — anything but True fails."""
    verdict = p2.footprintFullyLive(capture_id="cap-test", frames=_burst(p2.SLIDE4_MOVIE_RECT, control_noise=True))
    assert verdict["verdict"] is None
    assert verdict["status"] == "inconclusive"
    assert verdict["ok"] is False


def test_footprint_fully_live_fails_closed_on_a_truncated_burst():
    verdict = p2.footprintFullyLive(capture_id="cap-test", frames=_burst(p2.SLIDE4_MOVIE_RECT, n=1))
    assert verdict["ok"] is False
    assert verdict["status"] == "inconclusive"


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


# --------------------------------------------------------------------------- #
# `_score_visible_movie_motion` — the restored fail-closed "empty crop" branch
# (gate-verdict-seam): the caller-side `if patch.size == 0: continue` used to
# swallow every empty patch before `score_visible_movie_motion` ever saw one, so
# an out-of-bounds ROI was misreported as "need >=3 frames" (a shrunken `n`)
# instead of the hard-rejecting "empty crop". Proven here through the src entry
# point, `obed_edom.p2_verdict._score_visible_movie_motion`.
# --------------------------------------------------------------------------- #
def test_visible_movie_motion_out_of_bounds_roi_is_empty_crop_not_short_window(tmp_path):
    """An ROI entirely outside the frames must fail closed as "empty crop" with
    `emptyIndices`/`shapes`, never "need >=3 frames" — that reason belongs only
    to a genuinely short `frame_paths` list, not one shrunk by a caller-side filter."""
    frame_paths = []
    for i in range(5):
        arr = np.zeros((50, 50, 3), dtype=np.uint8)
        p = tmp_path / f"frame{i}.png"
        Image.fromarray(arr).save(p)
        frame_paths.append(p)

    out_of_bounds_roi = (1000, 1000, 100, 100)
    scored = p2._score_visible_movie_motion(frame_paths, roi=out_of_bounds_roi)

    assert scored["reason"] == "empty crop"
    assert scored["ok"] is False
    assert scored["n"] == len(frame_paths)
    assert scored["emptyIndices"] == list(range(len(frame_paths)))
    assert len(scored["shapes"]) == len(frame_paths)


# --------------------------------------------------------------------------- #
# r8 MAJOR 1 — geometry soundness. Badge TRANSPORT (installed, decoded, CRC-ok,
# logged, in order) is not badge GEOMETRY: a sample whose painted rect disagrees
# with the page's own log for that frame is `unstable`, and scoring it is
# scoring a wrong ROI. Every SCORED sample must be `measured`; the only
# exception is the scorer's already-validated re-handoff pair.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_unstable_but_crc_valid_sample_is_inconclusive(arm):
    """The exact r8 hole: CRC-valid, logged, ordered, decoded -- and geometrically
    junk. The old transport-only gate left `badgeSamplesSoundAllArms` green."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    _with_sample(snaps[arm], 1, footprintSource="unstable")
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", arm
    assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], arm


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
@pytest.mark.parametrize("source", ["modelled", "none", None])
def test_freeze_control_any_non_measured_source_is_inconclusive(arm, source):
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    _with_sample(snaps[arm], 0, footprintSource=source)
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", (arm, source)
    assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], (arm, source)


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_badge_install_not_ok_is_inconclusive(arm):
    """`install` merely PRESENT was enough before; it must be `ok is True`."""
    for install in ({"ok": False}, {}, None):
        snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
        snaps[arm]["badge"] = {**snaps[arm]["badge"], "install": install}
        verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
        assert verdict["verdict"] == "inconclusive", (arm, install)
        assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], (arm, install)


@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
def test_freeze_control_short_decode_count_is_inconclusive(arm):
    """`decoded` short of the capture count means some frame produced no badge at
    all -- a sample with no geometry of its own."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    n = len(snaps[arm]["indexSamples"])
    snaps[arm]["badge"] = {**snaps[arm]["badge"], "decoded": n - 1}
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", arm
    assert "badgeSamplesSoundAllArms" in verdict["integrityFailed"], arm


# --------------------------------------------------------------------------- #
# r8 MAJOR 2 — the page's own keydown count gates the verdict, in every arm.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
@pytest.mark.parametrize(
    "events,rejected,label",
    [
        (None, None, "counters missing entirely"),
        (0, 0, "the dispatch never reached the page"),
        (2, 0, "a replayed or drain press in flight"),
        (1, 1, "one accepted plus one SYNTHETIC (untrusted) ArrowRight"),
        (0, 1, "only a synthetic ArrowRight"),
        (1, 3, "an auto-REPEAT burst alongside the real press"),
    ],
)
def test_freeze_control_advance_key_count_is_gated_in_every_arm(
    arm, events, rejected, label
):
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    if events is None:
        snaps[arm].pop("advanceKeyEvents", None)
        snaps[arm].pop("advanceKeyRejected", None)
    else:
        snaps[arm]["advanceKeyEvents"] = events
        snaps[arm]["advanceKeyRejected"] = rejected
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    assert verdict["verdict"] == "inconclusive", (arm, label)
    assert "atCutBoundaryValidAllArms" in verdict["integrityFailed"], (arm, label)


def test_freeze_control_clean_bracket_still_passes_with_the_new_gates():
    """The positive control for both r8 majors: nothing above weakened the
    pass-capable fixture."""
    verdict = _score_34(
        _positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()
    )
    assert verdict["verdict"] == "pass", verdict["reason"]
    assert verdict["integrityFailed"] == []


# --------------------------------------------------------------------------- #
# r12 MAJOR 1 — the retained burst raster is bound to its ARM and to the fixed
# capture contract. Codex's four pure-scorer probes each reached PASS before
# this; every one of them must now come back INCONCLUSIVE.
# --------------------------------------------------------------------------- #
def _reencode_raster(arr, **over) -> dict:
    """An `evidence` block for `arr`, contract-shaped except where overridden."""
    ev = {
        "captureId": _FIXTURE_34["b"]["captureId"],
        "n": p2.FOOTPRINT_BURST_FRAMES,
        "rects": p2._footprint_rects(),
        "controlRect": dict(p2.SLIDE4_CONTROL_RECT),
        "params": dict(p2.FOOTPRINT_SCORE_PARAMS),
        "frameSha256": ["0" * 64] * p2.FOOTPRINT_BURST_FRAMES,
        **p2._encode_delta_raster(arr),
    }
    ev.update(over)
    return ev


def _b_with_evidence(**over) -> dict:
    snap = _freeze_b_snap_34()
    live = copy.deepcopy(snap["footprintFullyLive"])
    live["evidence"] = {**live["evidence"], **over}
    snap["footprintFullyLive"] = live
    return snap


def test_footprint_raster_from_another_arm_is_inconclusive():
    """Probe 1: B's evidence replaced with A1's raster. The raster re-scores
    green -- it is a real passing burst -- but it is not B's, and the captureId
    retained in B's snapshot header says so."""
    a1_ev = _FIXTURE_34["a1"]["footprintFullyLive"]["evidence"]
    snap = _b_with_evidence(**{k: a1_ev[k] for k in ("data", "bytes", "h", "w",
                                                     "encoding", "frameSha256")})
    assert p2._footprint_fully_live_ok(snap) is False
    verdict = _score_34(_positive_snap_34(), snap, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "isolationEqual" in verdict["integrityFailed"]


def test_footprint_raster_with_a_swapped_capture_id_is_inconclusive():
    """The same binding from the other side: the evidence keeps B's pixels but
    names another capture."""
    snap = _b_with_evidence(captureId=_FIXTURE_34["a1"]["captureId"])
    assert p2._footprint_fully_live_ok(snap) is False


@pytest.mark.parametrize("n", [2, 11, 13, 0, None, "12"])
def test_footprint_frame_count_off_contract_is_inconclusive(n):
    """Probe 2: the burst length is the CONTRACT's, not the evidence's. A raster
    reduced from 2 frames says far less than one reduced from 12, and a cached
    count that agrees with a forged one proves nothing."""
    snap = _b_with_evidence(n=n)
    assert p2._footprint_fully_live_ok(snap) is False


def test_footprint_frame_sha_list_must_match_the_burst_length():
    """The per-frame provenance is retained at the contract's length; a short or
    malformed list is not the burst's provenance."""
    assert p2._footprint_fully_live_ok(_b_with_evidence(frameSha256=["0" * 64])) is False
    assert p2._footprint_fully_live_ok(
        _b_with_evidence(frameSha256=["zz" + "0" * 62] * p2.FOOTPRINT_BURST_FRAMES)
    ) is False
    assert p2._footprint_fully_live_ok(_b_with_evidence(frameSha256=None)) is False


def test_footprint_padded_raster_is_inconclusive():
    """Probe 3: the raster padded and re-encoded at 1921x1081. It decodes, and it
    is self-consistent, but it is not the capture viewport."""
    delta = p2._decode_delta_raster(
        _FIXTURE_34["b"]["footprintFullyLive"]["evidence"], p2.FOOTPRINT_BURST_SHAPE
    )
    padded = np.zeros((delta.shape[0] + 1, delta.shape[1] + 1), dtype=np.uint8)
    padded[: delta.shape[0], : delta.shape[1]] = delta
    snap = _b_with_evidence(**p2._encode_delta_raster(padded))
    assert p2._footprint_fully_live_ok(snap) is False


def test_footprint_all_zero_raster_with_weakened_params_is_inconclusive():
    """Probe 4: a dead (all-zero) raster carrying parameters slack enough to call
    itself live. The re-score uses the CONSTANTS, so the weakened parameters are
    refused outright -- and the dead raster would fail them anyway."""
    dead = np.zeros(p2.FOOTPRINT_BURST_SHAPE, dtype=np.uint8)
    slack = {**p2.FOOTPRINT_SCORE_PARAMS, "deltaMin": 0, "minLiveFrac": 0.0,
             "bandLiveFrac": 0.0}
    snap = _b_with_evidence(params=slack, **p2._encode_delta_raster(dead))
    assert p2._footprint_fully_live_ok(snap) is False
    snap = _b_with_evidence(**p2._encode_delta_raster(dead))
    assert p2._footprint_fully_live_ok(snap) is False


@pytest.mark.parametrize("field", ["rects", "controlRect"])
def test_footprint_rects_must_equal_the_contract(field):
    """A blob cannot move the rectangles it is scored over."""
    moved = ({"x": 0, "y": 0, "w": 40, "h": 40, "label": "slide4Movie"}
             if field == "rects" else {"x": 0, "y": 0, "w": 40, "h": 40})
    snap = _b_with_evidence(**{field: [moved] if field == "rects" else moved})
    assert p2._footprint_fully_live_ok(snap) is False


def test_footprint_cached_numbers_must_equal_the_re_derived_ones():
    """The comparison is over the COMPLETE result, at tolerance 0: a single
    per-rect `liveFrac` or `maxDelta` edited away from what the raster yields is
    a cached summary that no longer describes its own evidence."""
    for path in (("perRect", 0, "liveFrac"), ("perRect", 0, "maxDelta"),
                 ("noiseFloor", "p99"), ("stray", "strays")):
        snap = _freeze_b_snap_34()
        live = copy.deepcopy(snap["footprintFullyLive"])
        node = live
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = 0 if node[path[-1]] != 0 else 1
        snap["footprintFullyLive"] = live
        assert p2._footprint_fully_live_ok(snap) is False, path


def test_footprint_decode_is_fail_closed(tmp_path):
    """r12 MINOR 1: a non-PNG L-mode container, a declared-shape mismatch and a
    decompression-bomb header all decode to `None`, never to pixels."""
    buf = io.BytesIO()
    Image.fromarray(
        np.zeros(p2.FOOTPRINT_BURST_SHAPE, dtype=np.uint8), mode="L"
    ).save(buf, format="TIFF")
    blob = buf.getvalue()
    ev = {"encoding": "png-gray", "bytes": len(blob), "h": 1080, "w": 1920,
          "data": base64.b64encode(blob).decode("ascii")}
    assert p2._decode_delta_raster(ev, p2.FOOTPRINT_BURST_SHAPE) is None
    good = _FIXTURE_34["b"]["footprintFullyLive"]["evidence"]
    assert p2._decode_delta_raster(good, (1081, 1921)) is None
    assert p2._decode_delta_raster({**good, "h": 1081}, p2.FOOTPRINT_BURST_SHAPE) is None
    old_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 16
    try:
        assert p2._decode_delta_raster(good, p2.FOOTPRINT_BURST_SHAPE) is None
    finally:
        Image.MAX_IMAGE_PIXELS = old_limit


# --------------------------------------------------------------------------- #
# r12 MAJOR 2 — `None` counter reads in a scored window.
# --------------------------------------------------------------------------- #
def _positive_with_at_cut_nulls(positions) -> dict:
    """A1 with `index` nulled at the given positions of its at-cut segment."""
    snap = _positive_snap_34()
    lo = snap["atCutBoundary"]["from"]
    hi = snap["releaseSplitIndex"]
    seg = [i for i in range(lo, hi + 1)
           if snap["indexSamples"][i].get("footprintSource") == "measured"]
    samples = [dict(s) for s in snap["indexSamples"]]
    for pos in positions:
        samples[seg[pos]]["index"] = None
    snap["indexSamples"] = samples
    return snap


def test_positive_at_cut_null_run_is_inconclusive():
    """Codex's probe: positions 1-13 of the 24-sample at-cut segment nulled. The
    bracket reached PASS before -- the null-adjacent deltas simply vanished from
    the progress and freeze-run totals, so the interval was unobserved."""
    a1 = _positive_with_at_cut_nulls(range(1, 14))
    verdict = _score_34(a1, _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "positivesGreen" in verdict["integrityFailed"]


def test_positive_at_cut_two_consecutive_nulls_are_inconclusive():
    """The bound is on the RUN, not only on the total: two in a row is an
    unobserved interval however short."""
    a1 = _positive_with_at_cut_nulls((5, 6))
    verdict = _score_34(a1, _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "positivesGreen" in verdict["integrityFailed"]


def test_the_clean_at_cut_leading_null_is_still_scorable():
    """The other half of the rule: every clean arm carries exactly one null, the
    unsettled first read after the advance, and it must stay admissible."""
    a1 = _positive_snap_34()
    lo, hi = a1["atCutBoundary"]["from"], a1["releaseSplitIndex"]
    seg = [s.get("index") for s in a1["indexSamples"][lo:hi + 1]
           if s.get("footprintSource") == "measured"]
    assert seg.count(None) == 1 and seg[0] is None
    assert _score_34(
        a1, _freeze_b_snap_34(), _a2_snap_34()
    )["verdict"] == "pass"


def test_main_settled_window_admits_no_nulls():
    """MAIN's settled window measured ZERO nulls in every clean arm, so one is
    already evidence the window is missing a read."""
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, settle, owner) is True
    window = [i for i, s in enumerate(samples)
              if s in p2._slide4_settled_window(samples)
              and s.get("footprintSource") == "measured"]
    meta = _with_sample(dict(meta), window[3], index=None)
    assert p2._advance_c_ok(meta, meta["indexSamples"], settle, owner) is False


def test_settled_progression_null_is_not_green_in_the_bracket():
    """The same rule on the bracket's settled window, which is an isolation key."""
    snap = _freeze_b_snap_34()
    split = snap["releaseSplitIndex"]
    window = [i for i, s in enumerate(snap["indexSamples"])
              if i > split and s in p2._slide4_settled_window(
                  snap["indexSamples"][split + 1:])]
    snap = _with_sample(snap, window[2], index=None)
    assert p2._settled_progression_ok(snap) is False


# --------------------------------------------------------------------------- #
# r12 MAJOR 3 — null-`decoderId` gaps in the after-window.
# --------------------------------------------------------------------------- #
def _b_with_owner_nulls(n: int, *, start: int = 0, decoder=None) -> dict:
    """B with the first `n` after-window owner readings from `start` nulled (or
    re-attributed to `decoder`)."""
    snap = _freeze_b_snap_34()
    n4 = p2._strict_hash_num(snap["hash4"])
    samples = [dict(s) for s in snap["ownerSamples"]]
    after = [i for i, s in enumerate(samples)
             if (p2._strict_hash_num(s.get("sceneHash")) or -1) >= n4]
    for i in after[start:start + n]:
        samples[i]["decoderId"] = decoder
    snap["ownerSamples"] = samples
    return snap


def test_owner_null_gap_of_24_of_80_is_inconclusive():
    """Codex's probe: the first 24 of 80 after-window `decoderId` readings nulled
    consecutively. `nonNullFrac == 0.70` satisfies the majority gate, so the
    bracket passed -- while a replacement decoder could own the footprint for
    that whole interval."""
    b = _b_with_owner_nulls(24)
    mc = p2._moving_continuity_derived(b)
    assert mc["stableSlide4Owner"]["nonNullFrac"] >= 0.7
    assert "stableSlide4Owner" in mc["failed"]
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"


def test_owner_null_gap_just_over_the_bound_is_inconclusive():
    """The bound bites well before the aggregate does."""
    b = _b_with_owner_nulls(p2.OWNER_NULL_MAX_RUN + 1)
    mc = p2._moving_continuity_derived(b)
    assert mc["stableSlide4Owner"]["nonNullFrac"] > 0.7
    assert "stableSlide4Owner" in mc["failed"]


def test_the_clean_leading_owner_gap_is_still_admissible():
    """The measured clean gap -- the box mid-flight, `elementFromPoint`
    resolving nothing -- stays admissible, and is bracketed by the bound decoder
    on both sides, its left bracket read from BEFORE the window."""
    gaps = p2._moving_continuity_derived(
        _freeze_b_snap_34()
    )["stableSlide4Owner"]["nullGaps"]
    assert gaps["ok"] is True
    assert len(gaps["gaps"]) == 1 and gaps["gaps"][0]["from"] == 0
    assert gaps["maxRun"] <= p2.OWNER_NULL_MAX_RUN
    assert gaps["gaps"][0]["bracketed"] is True


def test_owner_gap_bracketed_by_a_different_decoder_is_refused():
    """A gap the owner ENTERS as one decoder and LEAVES as another is exactly
    the handoff the gate exists to catch, however short it is."""
    snap = _freeze_b_snap_34()
    n4 = p2._strict_hash_num(snap["hash4"])
    samples = [dict(s) for s in snap["ownerSamples"]]
    after = [i for i, s in enumerate(samples)
             if (p2._strict_hash_num(s.get("sceneHash")) or -1) >= n4]
    for i in after[10:12]:
        samples[i]["decoderId"] = None
    for i in after[12:]:
        samples[i]["decoderId"] = 99
    snap["ownerSamples"] = samples
    gaps = p2._owner_null_gaps(samples, [samples[i] for i in after])
    assert gaps["ok"] is False
    assert any(g["bracketed"] is False for g in gaps["gaps"])


def test_owner_gap_with_nothing_resolved_after_it_is_refused():
    """A trailing gap has no right-hand bracket and cannot earn one."""
    after_n = p2._moving_continuity_derived(
        _freeze_b_snap_34()
    )["stableSlide4Owner"]["afterN"]
    snap = _b_with_owner_nulls(3, start=after_n - 3)
    gaps = p2._moving_continuity_derived(snap)["stableSlide4Owner"]["nullGaps"]
    assert gaps["ok"] is False
    assert gaps["gaps"][-1]["after"] is None


# --------------------------------------------------------------------------- #
# r12 MAJOR 3, second half — the competing-decoder attestation is GEOMETRIC.
# --------------------------------------------------------------------------- #
def _after_positions(snap: dict) -> list[int]:
    n4 = p2._strict_hash_num(snap["hash4"])
    return [i for i, s in enumerate(snap["ownerSamples"])
            if (p2._strict_hash_num(s.get("sceneHash")) or -1) >= n4]


def _competitor_entry(rect, visible, decoder) -> dict:
    """An extra `videos` entry whose raw readings AGREE with its paint flag, so
    the attestation is exercised on the overlap rather than on a contradiction."""
    return {
        "index": 99, "decoderId": decoder, "presentedMediaTime": None,
        "visible": visible,
        "hiddenBy": None if visible else "hidden",
        "suppressed34": False,
        "rect": dict(rect), "clientRect": dict(rect),
        "inDocument": True, "display": "block",
        "visibility": "visible" if visible else "hidden",
        "opacityProduct": 1.0, "checkVisibility": True,
        "viewport": {"w": 1920.0, "h": 1080.0},
    }


def _b_with_competitor(at, rect, *, visible=True, decoder=9999) -> dict:
    """B with a synthetic extra `<video>` entry at the given after-window
    positions, sitting on the bound decoder's own footprint."""
    snap = _freeze_b_snap_34()
    media = [copy.deepcopy(m) for m in snap["mediaSamples"]]
    after = _after_positions(snap)
    for k in at:
        media[after[k]]["videos"].append(_competitor_entry(rect, visible, decoder))
    snap["mediaSamples"] = media
    return snap


def test_visible_competitor_on_the_footprint_during_the_gap_is_inconclusive():
    """The finding r12 MAJOR 3 named and round 15 could not close: a replacement
    decoder owning the footprint through the blind interval, while the bound
    decoder's offscreen rVFC clock keeps ticking. It is now SEEN."""
    b = _freeze_b_snap_34()
    gap = p2._moving_continuity_derived(b)["stableSlide4Owner"]["nullGaps"]["gaps"][0]
    fp = b["ownerSamples"][_after_positions(b)[gap["from"]]]["footprint"]
    competitor = dict(zip(("x", "y", "w", "h"), fp))
    b = _b_with_competitor(range(gap["from"], gap["to"] + 1), competitor)
    mc = p2._moving_continuity_derived(b)
    comp = mc["stableSlide4Owner"]["visibleCompetitors"]
    assert comp["ok"] is False and comp["hits"]
    assert comp["hits"][0]["iou"] > 0
    assert "stableSlide4Owner" in mc["failed"]
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"


def test_a_competitor_that_does_not_paint_is_not_a_competitor():
    """The same overlapping box, not painting: a decoder that does not composite
    cannot own the footprint however well its rect fits."""
    b = _freeze_b_snap_34()
    gap = p2._moving_continuity_derived(b)["stableSlide4Owner"]["nullGaps"]["gaps"][0]
    fp = b["ownerSamples"][_after_positions(b)[gap["from"]]]["footprint"]
    b = _b_with_competitor(
        range(gap["from"], gap["to"] + 1),
        dict(zip(("x", "y", "w", "h"), fp)),
        visible=False,
    )
    assert p2._moving_continuity_derived(b)["failed"] == []


def test_a_visible_competitor_clear_of_the_footprint_is_not_a_competitor():
    """Overlap is the test, not presence: the deck legitimately paints other
    movies elsewhere on slide 4."""
    b = _b_with_competitor(range(0, 6), {"x": 0.0, "y": 0.0, "w": 40.0, "h": 40.0})
    comp = p2._moving_continuity_derived(b)["stableSlide4Owner"]["visibleCompetitors"]
    assert comp["ok"] is True and comp["hits"] == []


def test_a_visible_competitor_anywhere_in_the_after_window_is_caught():
    """Not only inside the gap: a handoff at a position whose owner reading
    happens to resolve is still a handoff."""
    b = _freeze_b_snap_34()
    after = _after_positions(b)
    late = len(after) - 5
    fp = b["ownerSamples"][after[late]]["footprint"]
    b = _b_with_competitor([late], dict(zip(("x", "y", "w", "h"), fp)))
    assert "stableSlide4Owner" in p2._moving_continuity_derived(b)["failed"]


def test_the_export_suppressed_restart_element_is_classified_never_ignored():
    """The clean run really does carry a SECOND decoder on the same asset -- the
    export's fresh autoplay-from-0 element, which PRESERVE suppresses so the
    bridged decoder keeps painting. It must be visible in the snapshot as a
    classified non-painter, not quietly absent: `suppressed34` says PRESERVE is
    holding it, `hiddenBy` says how it reads."""
    b = _freeze_b_snap_34()
    bound = str(b["ownerDecoderId"])
    n4 = p2._strict_hash_num(b["hash4"])
    after_media = [m for m in b["mediaSamples"]
                   if (p2._strict_hash_num(m.get("sceneHash")) or -1) >= n4]
    others = [v for m in after_media for v in m["videos"]
              if str(v.get("decoderId")) != bound]
    assert others, "the clean fixture must carry the suppressed restart element"
    suppressed = [v for v in others if v.get("suppressed34")]
    assert suppressed, "PRESERVE's suppression marker must be retained"
    assert all(v["visible"] is False for v in others)
    assert {v["hiddenBy"] for v in suppressed} <= {
        "detached", "display-none", "zero-size", "hidden", "engine-hidden", "offscreen"
    }
    comp = p2._moving_continuity_derived(b)["stableSlide4Owner"]["visibleCompetitors"]
    assert comp["ok"] is True and comp["hits"] == []
    assert sum(comp["hiddenBy"].values()) == len(others)


@pytest.mark.parametrize("field", ["visible", "rect", "hiddenBy", "suppressed34"])
def test_competitor_geometry_is_required_per_entry(field):
    """Absence is not an attestation: a `videos` entry without its geometry or
    its paint flag fails the arm closed rather than being skipped."""
    b = _freeze_b_snap_34()
    media = [copy.deepcopy(m) for m in b["mediaSamples"]]
    n4 = p2._strict_hash_num(b["hash4"])
    target = next(m for m in media
                  if (p2._strict_hash_num(m.get("sceneHash")) or -1) >= n4)
    del target["videos"][0][field]
    b["mediaSamples"] = media
    assert p2._media_samples_schema_ok(media, b["ownerDecoderId"]) is False
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "sampleSchemaSoundAllArms" in verdict["integrityFailed"]


def test_a_competitor_without_a_stage_mapped_rect_fails_closed():
    """`rect` is null exactly when the page could not state the geometry in
    authored px. For a NON-painting entry that is immaterial; for a painting one
    there is nothing to compare against the footprint, so the arm fails."""
    b = _b_with_competitor(range(0, 4), {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0})
    n4 = p2._strict_hash_num(b["hash4"])
    for m in b["mediaSamples"]:
        if (p2._strict_hash_num(m.get("sceneHash")) or -1) >= n4:
            for v in m["videos"]:
                if v.get("index") == 99:
                    v["rect"] = None
    comp = p2._moving_continuity_derived(b)["stableSlide4Owner"]["visibleCompetitors"]
    assert comp["ok"] is False


@pytest.mark.parametrize("a,b_,expected", [
    ({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 0, "y": 0, "w": 10, "h": 10}, 1.0),
    ({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 10, "y": 0, "w": 10, "h": 10}, 0.0),
    ({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 5, "y": 0, "w": 10, "h": 10}, 1 / 3),
])
def test_iou_is_the_ordinary_one(a, b_, expected):
    assert p2._iou(a, b_) == pytest.approx(expected)
    assert p2._iou(a, {"x": 0, "y": 0, "w": None, "h": 10}) is None


# --------------------------------------------------------------------------- #
# r13 MAJOR 1 — the arm identity comes from OUTSIDE the arm.
# --------------------------------------------------------------------------- #
def test_whole_arm_substitution_is_inconclusive():
    """The probe r13 named: move A1's COMPLETE `footprintFullyLive` block and its
    header id into B. Everything inside B then agrees with itself -- raster,
    numbers, hashes, ids -- because both copies went stale together. The
    manifest, minted before any arm ran and held outside the snapshots, is what
    still disagrees."""
    a1, b, a2 = _positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()
    b["footprintFullyLive"] = copy.deepcopy(a1["footprintFullyLive"])
    b["captureId"] = a1["captureId"]
    assert p2._footprint_fully_live_ok(b) is True, "the swap is self-consistent"
    verdict = _score_34(a1, b, a2)
    assert verdict["verdict"] == "inconclusive"
    assert "armIdentitiesMatchManifest" in verdict["integrityFailed"]


def test_manifest_must_be_present_and_well_formed():
    """No manifest, a foreign manifest, or one of the wrong kind is no arm
    provenance at all."""
    args = (_positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34())
    for manifest in (None, {}, {"arms": {}}, p2._new_bracket_manifest(),
                     {**_FIXTURE_34["manifest"], "kind": "something-else"}):
        verdict = _score_34(*args, manifest=manifest)
        assert verdict["verdict"] == "inconclusive", manifest
        assert "armIdentitiesMatchManifest" in verdict["integrityFailed"]


def test_manifest_requires_three_distinct_arm_ids():
    """One id shared by two arms would make "another arm's evidence" meaningless
    -- the substitution above would agree."""
    one = _FIXTURE_34["manifest"]["arms"]["a1"]
    manifest = {"kind": p2.BRACKET_MANIFEST_KIND,
                "arms": {label: one for label in p2.BRACKET_ARMS}}
    snaps = [_positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()]
    for s in snaps:
        s["captureId"] = one
    verdict = _score_34(*snaps, manifest=manifest)
    assert verdict["verdict"] == "inconclusive"
    assert "armIdentitiesMatchManifest" in verdict["integrityFailed"]


def test_the_real_bracket_matches_its_own_manifest():
    """The other half: the committed bracket's three arms carry exactly the three
    identities its manifest handed them."""
    manifest = _FIXTURE_34["manifest"]
    assert manifest["kind"] == p2.BRACKET_MANIFEST_KIND
    ids = [manifest["arms"][label] for label in p2.BRACKET_ARMS]
    assert len(set(ids)) == 3
    assert [_FIXTURE_34[label]["captureId"] for label in p2.BRACKET_ARMS] == ids
    assert _score_34(_positive_snap_34(), _freeze_b_snap_34(),
                     _a2_snap_34())["verdict"] == "pass"


# --------------------------------------------------------------------------- #
# r13 MAJOR 2 — the paint decision is RE-DERIVED, not trusted.
# --------------------------------------------------------------------------- #
def _raw_visible(**over) -> dict:
    """The raw readings of an attached, opaque, on-screen entry."""
    entry = {
        "decoderId": 4242, "inDocument": True, "display": "block",
        "visibility": "visible", "opacityProduct": 1.0, "checkVisibility": True,
        "clientRect": {"x": 327.0, "y": 709.0, "w": 1266.0, "h": 356.0},
        "viewport": {"w": 1920.0, "h": 1080.0},
        "rect": {"x": 327.0, "y": 709.0, "w": 1266.0, "h": 356.0},
        "visible": True, "hiddenBy": None, "suppressed34": False,
    }
    entry.update(over)
    return entry


def test_a_stale_not_visible_flag_over_a_painting_entry_is_inconclusive():
    """r13's probe: an overlapping entry that is attached, opacity 1,
    `checkVisibility` true and on-screen, but whose derived flag says
    `visible=false`. Trusting the flag SKIPPED it and the bracket passed."""
    stale = _raw_visible(visible=False, hiddenBy="hidden")
    assert p2._derived_paint(stale) == (True, None)
    assert p2._paint_agrees(stale, set()) is False
    b = _freeze_b_snap_34()
    n4 = p2._strict_hash_num(b["hash4"])
    media = [copy.deepcopy(m) for m in b["mediaSamples"]]
    for m in media:
        if (p2._strict_hash_num(m.get("sceneHash")) or -1) >= n4:
            m["videos"].append(stale)
    b["mediaSamples"] = media
    comp = p2._moving_continuity_derived(b)["stableSlide4Owner"]["visibleCompetitors"]
    assert comp["ok"] is False
    assert _score_34(_positive_snap_34(), b, _a2_snap_34())["verdict"] == "inconclusive"


@pytest.mark.parametrize("over,expected", [
    ({}, (True, None)),
    ({"inDocument": False}, (False, "detached")),
    ({"display": "none"}, (False, "display-none")),
    ({"clientRect": {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}}, (False, "zero-size")),
    ({"visibility": "hidden"}, (False, "hidden")),
    ({"opacityProduct": 0.0}, (False, "hidden")),
    ({"checkVisibility": False}, (False, "engine-hidden")),
    ({"clientRect": {"x": 4000.0, "y": 10.0, "w": 100.0, "h": 100.0}},
     (False, "offscreen")),
])
def test_paint_is_rederived_from_the_raw_readings(over, expected):
    """The page's rules, restated on the retained readings, in the same order."""
    assert p2._derived_paint(_raw_visible(**over)) == expected


@pytest.mark.parametrize(
    "missing", ["inDocument", "display", "visibility", "opacityProduct", "clientRect",
                "viewport"])
def test_paint_cannot_be_rederived_without_its_readings(missing):
    entry = _raw_visible()
    del entry[missing]
    assert p2._derived_paint(entry) is None
    assert p2._paint_agrees(entry, set()) is False


def test_pool_detached_is_admitted_only_on_the_retained_reading():
    """`hiddenBy: "detached"` on a pool entry is a CLAIM. It is admitted only
    when the page's own `inDocument` reading says so."""
    pooled = {"decoderId": 4, "fromPreservePool": True, "visible": False,
              "hiddenBy": "detached", "suppressed34": False, "rect": None,
              "inDocument": False}
    assert p2._paint_agrees(pooled, set()) is True
    assert p2._paint_agrees({**pooled, "inDocument": True}, set()) is False
    assert p2._paint_agrees({**pooled, "inDocument": None}, set()) is False


def test_an_attached_pool_entry_needs_its_dom_census_entry():
    """A pool entry that says it is still attached asserts nothing by itself; it
    is admitted only when that sample's DOM census carries the same decoder."""
    attached = {"decoderId": 4, "fromPreservePool": True, "visible": False,
                "hiddenBy": "pool-duplicate", "suppressed34": False, "rect": None,
                "inDocument": True}
    assert p2._paint_agrees(attached, {"4"}) is True
    assert p2._paint_agrees(attached, {"6"}) is False
    assert p2._paint_agrees({**attached, "hiddenBy": "detached"}, {"4"}) is False


def test_the_clean_fixtures_pool_entries_are_classified_from_their_readings():
    """What the clean run actually carries, asserted rather than assumed."""
    b = _freeze_b_snap_34()
    pooled = [v for m in b["mediaSamples"] for v in m["videos"]
              if v.get("fromPreservePool")]
    assert pooled
    for v in pooled:
        assert isinstance(v["inDocument"], bool)
        assert v["hiddenBy"] == ("pool-duplicate" if v["inDocument"] else "detached")


# --------------------------------------------------------------------------- #
# r13 MAJOR 3 — the null is admissible only where it was measured.
# --------------------------------------------------------------------------- #
def test_a_null_moved_off_position_zero_is_inconclusive():
    """r13's probe: the SOLE null moved from position 0 into the middle of the
    at-cut segment. The count bound still passes and the bridge across it still
    reads as plausible forward progress, yet both sides of a restart would be
    erased there."""
    a1 = _positive_snap_34()
    lo, hi = a1["atCutBoundary"]["from"], a1["releaseSplitIndex"]
    seg = [i for i in range(lo, hi + 1)
           if a1["indexSamples"][i].get("footprintSource") == "measured"]
    samples = [dict(s) for s in a1["indexSamples"]]
    samples[seg[0]]["index"] = samples[seg[1]]["index"]   # fill the leading miss
    samples[seg[10]]["index"] = None                      # and move it inward
    a1["indexSamples"] = samples
    verdict = _score_34(a1, _freeze_b_snap_34(), _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "positivesGreen" in verdict["integrityFailed"]


def test_a_trailing_null_is_inconclusive():
    a1 = _positive_snap_34()
    lo, hi = a1["atCutBoundary"]["from"], a1["releaseSplitIndex"]
    seg = [i for i in range(lo, hi + 1)
           if a1["indexSamples"][i].get("footprintSource") == "measured"]
    samples = [dict(s) for s in a1["indexSamples"]]
    samples[seg[0]]["index"] = samples[seg[1]]["index"]
    samples[seg[-1]]["index"] = None
    a1["indexSamples"] = samples
    assert _score_34(a1, _freeze_b_snap_34(), _a2_snap_34())["verdict"] == "inconclusive"


def test_the_leading_null_is_bounded_against_the_pre_key_reading():
    """The clean arm's one null is admitted only because a DECODED reading taken
    before the advance brackets it. Remove that reading, or make it disagree with
    the first decoded sample, and the window fails closed."""
    a1 = _positive_snap_34()
    assert a1["preKeySample"]["index"] is not None
    lo, hi = a1["atCutBoundary"]["from"], a1["releaseSplitIndex"]
    seg = [x.get("index") for x in a1["indexSamples"][lo:hi + 1]
           if x.get("footprintSource") == "measured"]
    assert seg[0] is None and seg.count(None) == 1, "the arm must carry the miss"
    for bad in (None, {"index": None}, {"index": seg[1]}, {"index": 200}):
        arm = _positive_snap_34()
        arm["preKeySample"] = bad
        verdict = _score_34(arm, _freeze_b_snap_34(), _a2_snap_34())
        assert verdict["verdict"] == "inconclusive", bad
        assert "positivesGreen" in verdict["integrityFailed"], bad


@pytest.mark.parametrize("indices,pre,ok", [
    ([None, 5, 6, 7], 4, True),          # the measured shape, properly bracketed
    ([None, 5, 6, 7], None, False),      # no pre-key reading at all
    ([None, 5, 6, 7], 5, False),         # a ZERO step across the miss: a freeze
    ([None, 5, 6, 7], 200, False),       # an implausible step: a reset
    ([4, None, 6, 7], 3, False),         # interior
    ([4, 5, 6, None], 3, False),         # trailing
    ([4, 5, 6, 7], None, True),          # no nulls needs no bracket
])
def test_null_admissibility_is_positional(indices, pre, ok):
    assert p2._null_reads_admissible(
        indices, max_total=1, pre_key_index=pre
    ) is ok


def test_null_bridge_step_ceiling_is_the_progression_rules_own():
    """No semantic headroom over the scorer that owns the rule."""
    assert p2.NULL_BRIDGE_MAX_STEP == 30
    assert p2._plausible_step(0, p2.NULL_BRIDGE_MAX_STEP) is True
    assert p2._plausible_step(0, p2.NULL_BRIDGE_MAX_STEP + 1) is False


# --------------------------------------------------------------------------- #
# r13 MINOR 2 — the zlib path is bounded.
# --------------------------------------------------------------------------- #
def test_zlib_raster_decode_is_bounded():
    """A stream that inflates past the contract's pixel count, one with a tail,
    and a truncated one each return `None` rather than inflating."""
    shape = (16, 16)
    delta = np.zeros(shape, dtype=np.int16)
    raw = zlib.compress(np.zeros(shape, dtype=np.uint8).tobytes(), 9)
    good = {"encoding": "zlib-u8", "bytes": len(raw), "h": 16, "w": 16,
            "data": base64.b64encode(raw).decode("ascii")}
    assert p2._decode_delta_raster(good, shape) is not None
    bomb = zlib.compress(np.zeros((16, 64), dtype=np.uint8).tobytes(), 9)
    assert p2._decode_delta_raster(
        {**good, "bytes": len(bomb), "data": base64.b64encode(bomb).decode("ascii")},
        shape,
    ) is None
    tailed = raw + b"\x00\x01\x02"
    assert p2._decode_delta_raster(
        {**good, "bytes": len(tailed),
         "data": base64.b64encode(tailed).decode("ascii")},
        shape,
    ) is None
    cut = raw[: len(raw) // 2]
    assert p2._decode_delta_raster(
        {**good, "bytes": len(cut), "data": base64.b64encode(cut).decode("ascii")},
        shape,
    ) is None
    assert delta.shape == shape


# --------------------------------------------------------------------------- #
# r12 MINOR 2 — "exactly one" bound-decoder rVFC clock.
# --------------------------------------------------------------------------- #
def test_duplicate_bound_decoder_clocks_fail_the_schema():
    """Two entries for the bound decoder used to collapse into one through a
    set, agreeing or not. Two readings for one decoder is not one reading."""
    snap = _freeze_b_snap_34()
    n4 = p2._strict_hash_num(snap["hash4"])
    media = [copy.deepcopy(m) for m in snap["mediaSamples"]]
    target = next(
        m for m in media
        if (p2._strict_hash_num(m.get("sceneHash")) or -1) >= n4
    )
    bound = next(v for v in target["videos"]
                 if str(v.get("decoderId")) == str(snap["ownerDecoderId"]))
    target["videos"].append(copy.deepcopy(bound))
    snap["mediaSamples"] = media
    assert p2._media_samples_schema_ok(media, snap["ownerDecoderId"]) is False
    verdict = _score_34(_positive_snap_34(), snap, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "sampleSchemaSoundAllArms" in verdict["integrityFailed"]


# --------------------------------------------------------------------------- #
# MAIN's finding-13 gate (`_advance_c_ok`) — the same two majors on the path
# that is NOT the A-B-A bracket.
# --------------------------------------------------------------------------- #
def _main_inputs(**snap_overrides):
    """MAIN's four real arguments, every one of them CAPTURED. The arm takes the
    same `_settle_at_advance_hash` reading MAIN does and persists it as
    `advanceSettle`, so the sweep walks a captured block instead of one the
    harness rebuilt from `drain.hashAtArm` (review r12 MINOR 3)."""
    snap = _positive_snap_34(**snap_overrides)
    return snap, snap["indexSamples"], snap["advanceSettle"], snap["ownerSettle"]


def test_main_advance_c_ok_is_green_on_a_clean_capture():
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, settle, owner) is True
    seq = [
        s.get("index") for s in p2._slide4_settled_window(samples)
        if s.get("footprintSource") == "measured"
    ]
    assert seq and p2.score_index_progression(seq)["ok"] is True


@pytest.mark.parametrize("source", ["unstable", "modelled", "none", None])
def test_main_wrong_roi_sample_in_the_scored_window_is_not_green(source):
    """r8 MAJOR 1 on MAIN: a wrong-ROI (or undecoded) sample inside the SETTLED
    slide-4 window is filtered out of `slide4IndexSequence` AND fails the gate
    closed -- there is no re-handoff on this path to exempt it."""
    meta, samples, settle, owner = _main_inputs()
    window_pos = [
        i for i, s in enumerate(samples) if s in p2._slide4_settled_window(samples)
    ]
    assert window_pos, "fixture must have a settled slide-4 window"
    meta = _with_sample(dict(meta), window_pos[0], footprintSource=source)
    samples = meta["indexSamples"]
    assert p2._advance_c_ok(meta, samples, settle, owner) is False, source
    scored = [
        s for s in p2._slide4_settled_window(samples)
        if s.get("footprintSource") == "measured"
    ]
    assert len(scored) == len(window_pos) - 1, "the bad sample was scored anyway"


def test_main_wrong_roi_sample_with_a_none_index_is_not_green():
    """A `None` decode: the r8 wording's other half."""
    meta, samples, settle, owner = _main_inputs()
    window_pos = [
        i for i, s in enumerate(samples) if s in p2._slide4_settled_window(samples)
    ]
    meta = _with_sample(dict(meta), window_pos[0], footprintSource="unstable", index=None)
    assert p2._advance_c_ok(meta, meta["indexSamples"], settle, owner) is False


@pytest.mark.parametrize(
    "events,rejected",
    [(None, None), (0, 0), (2, 0), (1, 1), (0, 1), (1, 3)],
)
def test_main_advance_key_count_is_gated(events, rejected):
    meta, samples, settle, owner = _main_inputs()
    meta = dict(meta)
    if events is None:
        meta.pop("advanceKeyEvents", None)
        meta.pop("advanceKeyRejected", None)
    else:
        meta["advanceKeyEvents"], meta["advanceKeyRejected"] = events, rejected
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


@pytest.mark.parametrize("install", [{"ok": False}, {}, None])
def test_main_badge_install_not_ok_is_not_green(install):
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "badge": {**meta["badge"], "install": install}}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


def test_main_short_decode_count_is_not_green():
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "badge": {**meta["badge"], "decoded": len(samples) - 1}}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


# The full absence sweep over MAIN's inputs: no input may be satisfied by being
# missing (the pre-emptive round-11 instruction).
MAIN_ABSENCE_FIELDS = [
    "advance", "collector", "atCutBoundary", "advanceKeyEvents",
    "advanceKeyRejected", "advanceKeyPerfMs", "badge",
]


def test_main_advance_c_ok_refuses_an_absent_at_cut_boundary_from():
    """r9 MAJOR 1: MAIN read the cached `atCutBoundary.ok` and never the
    boundary's own `from`, so a boundary with no placeable first sample passed."""
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "atCutBoundary": {k: v for k, v in meta["atCutBoundary"].items()
                                      if k != "from"}}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


@pytest.mark.parametrize("i", [-1, 10**6, True, None, 1.5])
def test_main_advance_c_ok_refuses_an_out_of_range_boundary_from(i):
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "atCutBoundary": {**meta["atCutBoundary"], "from": i}}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


@pytest.mark.parametrize("key_ms", [None, True, float("nan"), float("inf"), "700"])
def test_main_advance_c_ok_refuses_a_bad_advance_key_clock(key_ms):
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "advanceKeyPerfMs": key_ms}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False


@pytest.mark.parametrize("field", MAIN_ABSENCE_FIELDS)
def test_main_advance_c_ok_refuses_every_absent_input(field):
    meta, samples, settle, owner = _main_inputs()
    meta = {k: v for k, v in meta.items() if k != field}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False, field


@pytest.mark.parametrize("sub", ["install", "decoded", "missing", "crcBad", "unlogged", "counts"])
def test_main_advance_c_ok_refuses_an_absent_badge_subfield(sub):
    meta, samples, settle, owner = _main_inputs()
    meta = {**meta, "badge": {k: v for k, v in meta["badge"].items() if k != sub}}
    assert p2._advance_c_ok(meta, samples, settle, owner) is False, sub


def test_main_advance_c_ok_refuses_absent_settle_and_absent_samples():
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, {}, owner) is False
    assert p2._advance_c_ok(meta, samples, None, owner) is False
    assert p2._advance_c_ok(meta, samples, settle, {}) is False
    assert p2._advance_c_ok(meta, samples, settle, None) is False
    assert p2._advance_c_ok(meta, [], settle, owner) is False


@pytest.mark.parametrize(
    "override",
    [{"exact": False}, {"hashAtAdvance": "#6"}, {"hashAtAdvance": None},
     {"expected": "#6"}, {"expected": None}],
)
def test_main_advance_settle_is_derived_not_a_cached_boolean(override):
    """r11 MAJOR 4: a cached `exact` retained from a read during the `#7` build's
    residual motion used to carry MAIN; the hash reading itself now has to say so."""
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, {**settle, **override}, owner) is False, override
    assert p2._advance_c_ok(
        meta, samples, {k: v for k, v in settle.items() if k not in override}, owner
    ) is False, override


def test_main_owner_settle_walks_the_real_readings():
    """r11 MAJOR 4: `{"settled": True}` with no readings is two derived values,
    not the rect series they came from."""
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, settle, {**owner, "readings": []}) is False
    assert p2._advance_c_ok(
        meta, samples, settle,
        {"settled": True, "stableReadings": owner["stableReadings"],
         "required": owner["required"]},
    ) is False


def test_main_advance_c_ok_refuses_a_sample_with_no_footprint_source():
    meta, samples, settle, owner = _main_inputs()
    window_pos = [
        i for i, s in enumerate(samples) if s in p2._slide4_settled_window(samples)
    ]
    stripped = [dict(s) for s in samples]
    stripped[window_pos[0]].pop("footprintSource")
    meta = {**meta, "indexSamples": stripped}
    assert p2._advance_c_ok(meta, stripped, settle, owner) is False


# --------------------------------------------------------------------------- #
# Pre-emptive absence sweep (round 11). The recurring review class has been
# "the pass-capable fixture never carried the field the new key reads, so the
# key was satisfied by ABSENCE". This takes the CLEAN, pass-capable bracket and,
# for every integrity key the scorer reads, deletes the snapshot field(s) that
# key is argued from, then asserts the verdict falls to INCONCLUSIVE.
#
# Two keys are NEGATIVE assertions ("no pre-advance departure", "no control
# error"): their green state IS the absence of a value, so deleting that one
# field cannot and must not flip them. They are probed instead by deleting the
# whole `nullControl` block they live in, which short-circuits to "hold never
# fired" -- inconclusive, and the two keys are never reached at all.
# The sweep already caught one real hole this way: `maxRafGapOk` was a `max()`
# over an empty series, green with no series to measure.
# --------------------------------------------------------------------------- #
def _drop(snap: dict, *path):
    """Delete a nested field, mutating a deep copy's parents only."""
    node = snap
    for step in path[:-1]:
        node = node[step]
    if isinstance(path[-1], int):
        del node[path[-1]]
    else:
        node.pop(path[-1], None)
    return snap


# (integrity key, arm, path to delete, does THAT key have to go red?)
_ABSENCE_CASES = [
    ("firedAtMoveStart", "b", ("nullControl", "firedVia"), True),
    ("firedAtMoveStart", "b", ("nullControl", "triggerFramesAfterAdvance"), True),
    ("firedAtRuntimeMotionStart", "b", ("nullControl", "motionStartedFrame"), True),
    ("firedAtRuntimeMotionStart", "b", ("nullControl", "motionStartedMarker"), True),
    ("firedAtRuntimeMotionStart", "b", ("nullControl", "obedMotionAtTrigger"), True),
    ("firedAfterAdvance", "b", ("nullControl", "advanceKeyAt"), True),
    ("noPreAdvanceDeparture", "b", ("nullControl",), False),
    ("noControlError", "b", ("nullControl",), False),
    ("drainPressesAllLanded", "a1", ("drain",), True),
    ("drainPressesAllLanded", "b", ("drain",), True),
    ("drainPressesAllLanded", "a2", ("drain",), True),
    ("advanceSinglePressAllArms", "a1", ("advance",), True),
    ("advanceSinglePressAllArms", "b", ("advance",), True),
    ("advanceSinglePressAllArms", "a2", ("advance",), True),
    ("coverPaintedAtPresent", "b", ("nullControl", "coverPaintedAt"), True),
    ("stageGeometryStable", "b", ("nullControl", "stageRectAtTrigger"), True),
    ("stageGeometryStable", "b", ("nullControl", "stageRectAtArm"), True),
    ("stageOriginZero", "b", ("nullControl", "stageOrigin"), True),
    ("ownerReadyAtTrigger", "b", ("nullControl", "ownerReadyState"), True),
    ("staleFrameFromPlayback", "b", ("nullControl", "staleCurrentTime"), True),
    ("paintedOnce", "b", ("nullControl", "paintCount"), True),
    ("coverPatchStable", "b", ("nullControl", "coverPatchStart"), True),
    ("coverPatchStable", "b", ("nullControl", "coverPatchEnd"), True),
    ("coverHitTest100", "b", ("nullControl", "rafLog"), True),
    ("coverTracksFootprint", "b", ("nullControl", "rafLog", 0, "measuredRect"), True),
    ("coverTracksFootprint", "b", ("nullControl", "rafLog", 0, "coverRect"), True),
    ("loopLive", "b", ("nullControl", "rafLog"), True),
    ("maxRafGapOk", "b", ("nullControl", "rafLog"), True),
    ("maxRafGapOk", "b", ("nullControl", "pollMaxGapMs"), True),
    ("advanceKeySameEventInControl", "b", ("nullControl", "advanceKeyAt"), True),
    ("advanceKeySameEventInControl", "b", ("nullControl", "advanceKeyRejected"), True),
    ("advanceKeySameEventInControl", "b", ("advanceKeyPerfMs",), True),
    ("everyInHoldStale", "b", ("nullControl", "coverPatchMean"), True),
    ("rehandoffPairSound", "b", ("badge", "stats"), True),
    ("ownerSettledAllArms", "a1", ("ownerSettle",), True),
    ("ownerSettledAllArms", "b", ("ownerSettle",), True),
    ("ownerSettledAllArms", "a2", ("ownerSettle",), True),
    ("releaseStrictlyBeforeSettleAndBurst", "b", ("nullControl", "releaseAt"), True),
    ("releaseStrictlyBeforeSettleAndBurst", "b", ("lastAtCutPerfMs",), True),
    ("releaseStrictlyBeforeSettleAndBurst", "b", ("burstStartPerfMs",), True),
    ("releaseStrictlyBeforeSettleAndBurst", "b", ("releaseSplitIndex",), True),
    ("releaseStrictlyBeforeSettleAndBurst", "b", ("firstSettledPerfMs",), True),
    ("collectorSeriesSound", "a1", ("collector",), True),
    ("collectorSeriesSound", "b", ("collector",), True),
    ("collectorSeriesSound", "a2", ("collector",), True),
    ("atCutBoundaryValidAllArms", "a1", ("advanceKeyPerfMs",), True),
    ("atCutBoundaryValidAllArms", "b", ("advanceKeyPerfMs",), True),
    ("atCutBoundaryValidAllArms", "a2", ("advanceKeyPerfMs",), True),
    ("atCutBoundaryValidAllArms", "b", ("atCutBoundary",), True),
    ("atCutBoundaryValidAllArms", "a1", ("advanceKeyEvents",), True),
    ("atCutBoundaryValidAllArms", "b", ("advanceKeyEvents",), True),
    ("atCutBoundaryValidAllArms", "a2", ("advanceKeyEvents",), True),
    ("atCutBoundaryValidAllArms", "a1", ("advanceKeyRejected",), True),
    ("atCutBoundaryValidAllArms", "b", ("advanceKeyRejected",), True),
    ("atCutBoundaryValidAllArms", "a2", ("advanceKeyRejected",), True),
    ("badgeSamplesSoundAllArms", "a1", ("badge",), True),
    ("badgeSamplesSoundAllArms", "b", ("badge",), True),
    ("badgeSamplesSoundAllArms", "a2", ("badge",), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "install"), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "decoded"), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "missing"), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "crcBad"), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "unlogged"), True),
    ("badgeSamplesSoundAllArms", "b", ("badge", "counts"), True),
    ("noNegativeAnomaly", "b", ("indexSamples",), True),
    ("flipIndexPresent", "b", ("indexSamples",), True),
    ("flipWindowDecodable", "b", ("indexSamples",), True),
    ("enoughAfterFlip", "b", ("indexSamples",), True),
    ("allInHoldMeasured", "b", ("indexSamples",), True),
    ("movingContinuityOk", "b", ("movingContinuity3to4",), True),
    ("boundDecoderIsSlide3Decoder", "b", ("nullControl", "boundDecoderId"), True),
    ("boundDecoderIsSlide3Decoder", "b", ("ownerDecoderId",), True),
    ("noOwnerAmbiguousInWindow", "b", ("nullControl", "ownerAmbiguousInWindow"), True),
    ("noOwnerAmbiguousInWindow", "b", ("nullControl", "ownerDisconnectedInWindow"), True),
    ("rvfcRanThroughHold", "b", ("mediaSamples",), True),
    ("playerBuildErrorsEmpty", "b", ("playerBuildErrors",), True),
    ("bridgeEngaged", "b", ("bridgeEngaged",), True),
    ("positivesGreen", "a1", ("continueThroughMovingMagicMove3to4Pass",), True),
    ("positivesGreen", "a2", ("continueThroughMovingMagicMove3to4Pass",), True),
    ("positivesGreen", "a1", ("movingIndexRunAtCut",), True),
    ("sampleSchemaSoundAllArms", "a1", ("indexSamples", 0, "sceneHash"), True),
    ("sampleSchemaSoundAllArms", "b", ("ownerSamples", 0, "ownerAmbiguous"), True),
    ("sampleSchemaSoundAllArms", "a2", ("mediaSamples", 0, "videos"), True),
    ("isolationEqual", "a1", ("footprintFullyLive", "evidence", "data"), True),
    ("isolationEqual", "b", ("settledIndexProgression",), True),
    ("armIdentitiesMatchManifest", "a1", ("captureId",), True),
    ("armIdentitiesMatchManifest", "b", ("captureId",), True),
    ("armIdentitiesMatchManifest", "a2", ("captureId",), True),
]


@pytest.mark.parametrize("key,arm,path,key_must_fail", _ABSENCE_CASES)
def test_no_integrity_key_can_be_satisfied_by_absence(key, arm, path, key_must_fail):
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    _drop(snaps[arm], *path)
    verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
    where = (key, arm, path)
    assert verdict["verdict"] == "inconclusive", where
    if key_must_fail:
        assert key in verdict["integrityFailed"], where


# --------------------------------------------------------------------------- #
# Round 12 (review r9 MAJOR 2/3/4): the values, not only the absences.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("gap", [None, True, False, -1.0, float("nan"), float("inf"), "17"])
def test_freeze_control_poll_gap_must_be_a_real_measurement(gap):
    """r9 MAJOR 2: a missing/degenerate pre-trigger gap used to read as 0.0, so a
    short, clean hold series carried `maxRafGapOk` with no pre-trigger evidence."""
    b = _freeze_b_snap_34()
    b["nullControl"]["pollMaxGapMs"] = gap
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "maxRafGapOk" in verdict["integrityFailed"], gap


@pytest.mark.parametrize("split", [None, True, -1, 10**6, 1.5, "6"])
def test_freeze_control_release_split_index_must_be_in_range(split):
    """r9 MAJOR 3: without a valid split there is no at-cut upper bound at all."""
    b = _freeze_b_snap_34()
    b["releaseSplitIndex"] = split
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"], split


def test_freeze_control_first_settled_is_derived_not_trusted():
    """r9 MAJOR 3: the reported `firstSettledPerfMs` must agree with the instant
    re-derived from the post-split settled samples, and a post-split sample with
    no page clock leaves nothing to derive."""
    b = _freeze_b_snap_34()
    b["firstSettledPerfMs"] = b["firstSettledPerfMs"] - 500.0
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict["integrityFailed"]

    b2 = _freeze_b_snap_34()
    settled = p2._slide4_settled_window(b2["indexSamples"][b2["releaseSplitIndex"] + 1:])
    post = b2["indexSamples"].index(settled[0])
    b2 = _with_sample(b2, post, perfNowMs=None)
    verdict2 = _score_34(_positive_snap_34(), b2, _a2_snap_34())
    assert verdict2["verdict"] == "inconclusive"
    assert "releaseStrictlyBeforeSettleAndBurst" in verdict2["integrityFailed"]


def test_freeze_control_null_controller_clock_must_be_the_watched_event():
    """r9 MAJOR 4, the three shapes. A SYNTHETIC ArrowRight landing shortly
    BEFORE the real one used to seed the controller's clock while the capture
    watch (which filters) timed the trusted event; a REPEAT did the same; and
    nothing tied the two clocks together at all."""
    pre = _freeze_b_snap_34()
    pre["nullControl"]["advanceKeyAt"] = ADVANCE_KEY_AT_34 - 5.0
    v_pre = _score_34(_positive_snap_34(), pre, _a2_snap_34())
    assert v_pre["verdict"] == "inconclusive"
    assert "advanceKeySameEventInControl" in v_pre["integrityFailed"]

    rep = _freeze_b_snap_34()
    rep["nullControl"]["advanceKeyRejected"] = 1
    v_rep = _score_34(_positive_snap_34(), rep, _a2_snap_34())
    assert v_rep["verdict"] == "inconclusive"
    assert "advanceKeySameEventInControl" in v_rep["integrityFailed"]

    mism = _freeze_b_snap_34()
    mism["advanceKeyPerfMs"] = ADVANCE_KEY_AT_34 + 0.4
    v_mis = _score_34(_positive_snap_34(), mism, _a2_snap_34())
    assert v_mis["verdict"] == "inconclusive"
    assert "advanceKeySameEventInControl" in v_mis["integrityFailed"]


# --------------------------------------------------------------------------- #
# Round 14 (review r11): schema before windowing, the bridge kind, and the
# footprint verdict re-scored from pixels.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("arm", ["a1", "b", "a2"])
@pytest.mark.parametrize(
    "series,key",
    [("indexSamples", "index"), ("indexSamples", "sceneHash"),
     ("indexSamples", "progress"), ("indexSamples", "perfNowMs"),
     ("ownerSamples", "sceneHash"), ("ownerSamples", "decoderId"),
     ("ownerSamples", "ownerAmbiguous"),
     ("mediaSamples", "sceneHash"), ("mediaSamples", "videos")],
)
def test_freeze_control_absent_sample_key_is_inconclusive_at_every_position(series, key, arm):
    """r11 MAJOR 1/2: the windows are cut by `sceneHash`/`progress` and scored on
    `index`/`decoderId`/`videos`, so deleting one of those keys used to move the
    window off the sample that carried the bad evidence. Presence is now checked
    per sample BEFORE any window is selected -- at EVERY position, not only the
    scored ones."""
    snaps = {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(), "a2": _a2_snap_34()}
    rows = snaps[arm][series]
    for pos in (0, len(rows) // 2, len(rows) - 1):
        kept = rows[pos].pop(key)
        verdict = _score_34(snaps["a1"], snaps["b"], snaps["a2"])
        rows[pos][key] = kept
        assert verdict["verdict"] == "inconclusive", (series, key, arm, pos)
        assert "sampleSchemaSoundAllArms" in verdict["integrityFailed"]


@pytest.mark.parametrize("key", ["index", "decoderId"])
def test_freeze_control_admits_the_explicit_nulls_the_model_permits(key):
    """An undecodable badge patch and a transient unresolved owner are real
    readings; only ABSENCE fails the schema."""
    series = "indexSamples" if key == "index" else "ownerSamples"
    b = _freeze_b_snap_34()
    assert any(s[key] is None for s in b[series]), (key, "fixture carries no explicit null")
    assert p2._samples_schema_ok(
        b[series],
        p2._INDEX_SAMPLE_KEYS if key == "index" else p2._OWNER_SAMPLE_KEYS,
    ) is True


def test_freeze_control_bound_decoder_needs_one_finite_rvfc_reading_per_sample():
    """r11 MAJOR 2: an after-window media sample with no bound-decoder
    `presentedMediaTime` -- or two that disagree -- is no rVFC reading at all."""
    b = _freeze_b_snap_34()
    after = next(
        m for m in b["mediaSamples"]
        if (p2._strict_hash_num(m["sceneHash"]) or -1) >= p2.SLIDE4_MIN_HASH
    )
    bound = next(v for v in after["videos"] if str(v["decoderId"]) == str(b["ownerDecoderId"])
                 and "presentedMediaTime" in v)
    kept = bound.pop("presentedMediaTime")
    assert _score_34(_positive_snap_34(), b, _a2_snap_34())["verdict"] \
        == "inconclusive"
    bound["presentedMediaTime"] = kept
    after["videos"].append({**bound, "presentedMediaTime": kept + 1.0})
    assert _score_34(_positive_snap_34(), b, _a2_snap_34())["verdict"] \
        == "inconclusive"


def test_freeze_control_bridge_event_of_another_kind_is_inconclusive():
    """r11 MAJOR 3: `reuse-decoder` carries the same detail shape; only the
    `bridge-3to4` event is this bridge."""
    b = _freeze_b_snap_34()
    b["bridgeEvents"][0]["kind"] = "reuse-decoder"
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "bridgeEngaged" in verdict["integrityFailed"]

    b2 = _freeze_b_snap_34()
    b2["bridgeEvents"][0].pop("kind")
    assert _score_34(_positive_snap_34(), b2, _a2_snap_34())["verdict"] \
        == "inconclusive"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.update(verdict=False),
        lambda f: f.update(status="fail"),
        lambda f: f["perRect"][0].update(verdict=False),
        lambda f: f["noiseFloor"].update(verdict=False),
        lambda f: f["stray"].update(verdict=False),
        lambda f: f.update(n=f["n"] + 1),
    ],
)
def test_freeze_control_cached_footprint_verdict_must_agree_with_the_raster(mutate):
    """r11 MAJOR 5: `ok=True` over a summary that says the footprint was NOT live
    was a material fail-open. The verdict is recomputed from the retained
    max-delta raster and every cached sub-verdict has to match it."""
    b = _freeze_b_snap_34()
    mutate(b["footprintFullyLive"])
    verdict = _score_34(_positive_snap_34(), b, _a2_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "isolationEqual" in verdict["integrityFailed"]


@pytest.mark.parametrize(
    "path",
    [("evidence",), ("evidence", "data"), ("evidence", "encoding"),
     ("evidence", "bytes"), ("evidence", "h"), ("evidence", "w"),
     ("evidence", "n"), ("evidence", "rects"), ("evidence", "controlRect"),
     ("evidence", "params")],
)
def test_freeze_control_footprint_without_its_raster_is_inconclusive(path):
    """No raster, no re-derivation: a cached verdict alone cannot show pixels."""
    b = _drop(_freeze_b_snap_34(), "footprintFullyLive", *path)
    assert _score_34(_positive_snap_34(), b, _a2_snap_34())["verdict"] \
        == "inconclusive"


def test_footprint_raster_round_trips_losslessly():
    """The retained encoding must reproduce the scored raster EXACTLY -- a lossy
    one would re-score a different image than the burst was judged on."""
    delta = np.zeros((64, 96), dtype=np.int16)
    delta[10:50, 20:80] = np.arange(40 * 60, dtype=np.int16).reshape(40, 60) % 256
    encoded = p2._encode_delta_raster(delta)
    assert np.array_equal(
        p2._decode_delta_raster(encoded, delta.shape), delta.astype(np.uint8)
    )
    assert encoded["encoding"] in ("png-gray", "zlib-u8")
    assert encoded["bytes"] == len(base64.b64decode(encoded["data"]))


def test_footprint_raster_rejects_a_tampered_blob():
    delta = np.zeros((32, 32), dtype=np.int16)
    encoded = p2._encode_delta_raster(delta)
    shape = delta.shape
    assert p2._decode_delta_raster({**encoded, "bytes": encoded["bytes"] + 1}, shape) is None
    assert p2._decode_delta_raster({**encoded, "encoding": "raw"}, shape) is None
    assert p2._decode_delta_raster({**encoded, "h": encoded["h"] + 1}, shape) is None
    assert p2._decode_delta_raster({**encoded, "data": "not base64!"}, shape) is None


# --------------------------------------------------------------------------- #
# EXHAUSTIVE absence sweep (round 12, replacing the hand-picked round-11 one).
# Every LEAF of the clean pass-capable bracket -- all three arms, nested dicts,
# every dict inside every list -- is deleted in turn and the verdict must fall
# to INCONCLUSIVE. Anything that may survive its own deletion is named below
# with a reason; that allowlist IS the argument, so every entry is one line and
# `test_bracket_sweep_allowlist_has_no_dead_entries` refuses a stale one.
#
# Reason classes:
#  * report-only  -- carried into the report/forensics, scored by nothing.
#  * redundant    -- a duplicate view of a field gated elsewhere in the snapshot.
#  * provenance   -- an input the PAGE used to compute a sub-verdict the scorer
#                    either re-derives itself or reads only as `ok`.
#  * negative     -- the key ASSERTS absence (`is None` / `is False`), so
#                    deleting that field cannot flip it; its PRESENCE is what
#                    the key tests, and those cases live in `_ABSENCE_CASES`.
# --------------------------------------------------------------------------- #
# A positive arm's survivors are a property of the ARM CLASS, not of which run
# filled it: A1 and A2 are two captures of the same thing, walked independently.
# Defined ONCE and keyed per class below, so the two can no longer drift apart
# and classify identical evidence differently (review r12 MINOR 5).
_POSITIVE_SWEEP_ALLOW: dict[tuple, str] = {
    ('advanceKeyEvalMs',): 'report-only: the post-dispatch read, kept to measure its lag against the page-side keydown clock',
    ('advanceKeySeen',): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('advanceKeySeen', 'isTrusted'): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('advanceKeySeen', 'repeat'): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('advanceKeySeen', 't'): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('advanceKeySeen', 'type'): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('advanceSettle', 'exact'): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('advanceSettle', 'expected'): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('advanceSettle', 'hashAtAdvance'): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('armResult',): 'report-only in a positive arm: only B arms the freeze control',
    ('atCutBoundary', 'reason'): "report-only: the boundary's reason string",
    ('atCutFrom',): 'redundant: a view of atCutBoundary.from, gated there',
    ('badge', 'counts', 'measured'): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('badge', 'counts', 'modelled'): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('badge', 'counts', 'none'): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('badge', 'counts', 'unlogged'): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('badge', 'counts', 'unstable'): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('badge', 'install', 'cell'): 'report-only badge install geometry; install.ok is gated',
    ('badge', 'install', 'cells'): 'report-only badge install geometry; install.ok is gated',
    ('badge', 'install', 'dpr'): 'report-only badge install geometry; install.ok is gated',
    ('badge', 'install', 'elId'): 'report-only badge install geometry; install.ok is gated',
    ('badge', 'install', 'innerWidth'): 'report-only badge install geometry; install.ok is gated',
    ('badge', 'scale'): 'report-only: badge geometry diagnostic',
    ('badge', 'stats', 'installedAt'): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('badge', 'stats', 'logged'): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('badge', 'stats', 'motionStartedAt'): "report-only in a positive arm: only B's re-handoff pair is scored",
    ('badge', 'stats', 'painted'): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('badge', 'stats', 'rehandoffSeqs'): "report-only in a positive arm: only B's re-handoff pair is scored",
    ('badge', 'stats', 'rehandoffs'): "report-only in a positive arm: only B's re-handoff pair is scored",
    ('badge', 'stats', 'running'): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('badge', 'stats', 'seq'): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('bridgeEvents', 'detail', 'newElId'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('bridgeEvents', 'detail', 'paused'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('bridgeEvents', 'detail', 'preservedT'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('bridgeEvents', 'detail', 'queueLeft'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('bridgeEvents', 'detail', 'readyState'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('bridgeEvents', 't'): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('burstStartOffsetS',): 'report-only: the perfMs form is what is ordered',
    ('burstStartPerfMs',): "report-only in a positive arm: only B's release is ordered",
    ('captureOffsets',): 'report-only: wall offsets; the perfMs clock is what is ordered',
    ('collector', 'firstT'): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('collector', 'lastT'): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('collector', 'neighbourFillable'): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('collectorRows',): 'report-only row count; collector.rowCount is the gated one',
    ('firstSettledOffsetS',): 'report-only: the perfMs form is what is ordered',
    ('firstSettledPerfMs',): "report-only in a positive arm: only B's release is ordered",
    ('flipWindowDecodable',): 'redundant: the scorer RE-DERIVES it from the samples',
    ('footprintSources',): 'redundant: a view of indexSamples[*].footprintSource',
    ('indexSamples', 'captureOffsetS'): "report-only in a positive arm: the positives' run is re-derived from index/hash/progress only",
    ('indexSequence',): 'redundant: a view of indexSamples[*].index',
    ('lastAtCutHoldOffsetS',): 'report-only: the perfMs form is what is ordered',
    ('lastAtCutPerfMs',): "report-only in a positive arm: only B's release is ordered",
    ('mediaSamples', 'canvasCount'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'captureOffsetS'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'hash'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'currentTime'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'elId'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'ended'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'fromDom'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'inDocument'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'key'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'movieKey'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'paused'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'readyState'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'videoHeight'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'preservePool', 'videoWidth'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'search'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'stageMap', 'authoredHeight'): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('mediaSamples', 'stageMap', 'authoredWidth'): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('mediaSamples', 'stageMap', 'ox'): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('mediaSamples', 'stageMap', 'oy'): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('mediaSamples', 'stageMap', 's'): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('mediaSamples', 'videoCount'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'checkVisibility'): 'provenance of the paint decision; `visible` and `hiddenBy` are what the attestation reads',
    ('mediaSamples', 'videos', 'clientRect', 'h'): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('mediaSamples', 'videos', 'clientRect', 'w'): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('mediaSamples', 'videos', 'clientRect', 'x'): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('mediaSamples', 'videos', 'clientRect', 'y'): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('mediaSamples', 'videos', 'currentTime'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'display'): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('mediaSamples', 'videos', 'duration'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'ended'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'fromPreservePool'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'h'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'index'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'loop'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'muted'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'networkState'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'opacityProduct'): 'provenance of the paint decision; `visible` and `hiddenBy` are what the attestation reads',
    ('mediaSamples', 'videos', 'paused'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'playbackRate'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'presentedMediaTime'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'readyState'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'rect', 'h'): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('mediaSamples', 'videos', 'rect', 'w'): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('mediaSamples', 'videos', 'rect', 'x'): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('mediaSamples', 'videos', 'rect', 'y'): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('mediaSamples', 'videos', 'src'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'videos', 'viewport', 'h'): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('mediaSamples', 'videos', 'viewport', 'w'): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('mediaSamples', 'videos', 'visibility'): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('mediaSamples', 'videos', 'w'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('mediaSamples', 'wallMs'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('movingContinuity3to4', 'boundaryValid', 'n3'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'boundaryValid', 'n4'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'boundaryValid', 'ok'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'boundaryValid', 'slide4Min'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'crossingIdentity', 'ok'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'rvfcMonotonic', 'advance'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'rvfcMonotonic', 'n'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'rvfcMonotonic', 'ok'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'rvfcMonotonic', 'worstRegression'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'slide3MovieDecoder'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'slide4Owner'): 'provenance of movingContinuity3to4.ok, the gated key',
    ('movingContinuity3to4', 'stableSlide4Owner', 'afterN'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'stableSlide4Owner', 'distinctNonNull'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nonNullFrac'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'after'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'before'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'bracketed'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'from'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'run'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'to'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'maxRun'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'ok'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'reason'): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('movingContinuity3to4', 'stableSlide4Owner', 'ok'): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hiddenBy', 'hidden'): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hits'): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'n'): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'ok'): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'reason'): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('movingIndexRunAtCut', 'firstIndex'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'flipIndex'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'flipIndexFull'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'freezeRunAtCut'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'freezeRunBaseline'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'lastIndex'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'n'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'negativeAnomaly'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'reason'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'totalProgressAfter'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('movingIndexRunAtCut', 'totalProgressBefore'): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('nullControl',): 'expected: a positive arm carries no null control',
    ('ownerSamples', 'captureOffsetS'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('ownerSamples', 'footprint'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('ownerSamples', 'progress'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('ownerSamples', 'via'): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('ownerSettle', 'rect', 'h'): 'provenance; `settled` is the gated key',
    ('ownerSettle', 'rect', 'w'): 'provenance; `settled` is the gated key',
    ('ownerSettle', 'rect', 'x'): 'provenance; `settled` is the gated key',
    ('ownerSettle', 'rect', 'y'): 'provenance; `settled` is the gated key',
    ('preKeySample', 'badgeSeq'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('preKeySample', 'rect', 'h'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('preKeySample', 'rect', 'w'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('preKeySample', 'rect', 'x'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('preKeySample', 'rect', 'y'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('preKeySample', 'sceneHash'): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('releaseOffsetS',): 'report-only: the perfMs form is what is ordered',
    ('releasePerfMs',): 'redundant: nullControl.releaseAt is the gated release clock',
    ('settledIndexProgression', 'decodableFrac'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'firstIndex'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'implausibleStep'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'lastIndex'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'longestStallRun'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'n'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'nDecodable'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'nDistinct'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'reason'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('settledIndexProgression', 'totalForward'): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
}

_SWEEP_ALLOW: dict[tuple[str, tuple], str] = {
    ('b', ('advanceKeyEvalMs',)): 'report-only: the post-dispatch read, kept to measure its lag against the page-side keydown clock',
    ('b', ('advanceKeySeen',)): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('b', ('advanceKeySeen', 'isTrusted')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('b', ('advanceKeySeen', 'repeat')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('b', ('advanceKeySeen', 't')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('b', ('advanceKeySeen', 'type')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected and advanceKeyPerfMs',
    ('b', ('advanceSettle', 'exact')): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('b', ('advanceSettle', 'expected')): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('b', ('advanceSettle', 'hashAtAdvance')): "provenance: the bracket persists MAIN's own settled-`#7` reading; the bracket's own arm boundary is gated through drain.hashAtArmExact",
    ('b', ('armResult', 'armedElId')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'armedHash')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'armedOwnerRect', 'h')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'armedOwnerRect', 'w')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'armedOwnerRect', 'x')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'armedOwnerRect', 'y')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageOrigin', 'x')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageOrigin', 'y')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageRectAtArm', 'h')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageRectAtArm', 'w')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageRectAtArm', 'x')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('armResult', 'stageRectAtArm', 'y')): 'report-only: nullControl carries the gated copies of the arm geometry',
    ('b', ('atCutBoundary', 'reason')): "report-only: the boundary's reason string",
    ('b', ('atCutFrom',)): 'redundant: a view of atCutBoundary.from, gated there',
    ('b', ('badge', 'counts', 'measured')): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('b', ('badge', 'counts', 'modelled')): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('b', ('badge', 'counts', 'none')): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('b', ('badge', 'counts', 'unlogged')): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('b', ('badge', 'counts', 'unstable')): 'report-only count: seqViolation is gated, per-sample truth by footprintSource',
    ('b', ('badge', 'install', 'cell')): 'report-only badge install geometry; install.ok is gated',
    ('b', ('badge', 'install', 'cells')): 'report-only badge install geometry; install.ok is gated',
    ('b', ('badge', 'install', 'dpr')): 'report-only badge install geometry; install.ok is gated',
    ('b', ('badge', 'install', 'elId')): 'report-only badge install geometry; install.ok is gated',
    ('b', ('badge', 'install', 'innerWidth')): 'report-only badge install geometry; install.ok is gated',
    ('b', ('badge', 'scale')): 'report-only: badge geometry diagnostic',
    ('b', ('badge', 'stats', 'installedAt')): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('b', ('badge', 'stats', 'logged')): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('b', ('badge', 'stats', 'painted')): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('b', ('badge', 'stats', 'running')): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('b', ('badge', 'stats', 'seq')): 'report-only badge counter; the re-handoff pair evidence (rehandoffs/rehandoffSeqs/motionStartedAt) is gated',
    ('b', ('bridgeEvents', 'detail', 'newElId')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('bridgeEvents', 'detail', 'paused')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('bridgeEvents', 'detail', 'preservedT')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('bridgeEvents', 'detail', 'queueLeft')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('bridgeEvents', 'detail', 'readyState')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('bridgeEvents', 't')): 'report-only: bridge engagement is DERIVED from key/scene/oldElId/oldGen/generation',
    ('b', ('burstStartOffsetS',)): 'report-only: the perfMs form is what is ordered',
    ('b', ('captureOffsets',)): 'report-only: wall offsets; the perfMs clock is what is ordered',
    ('b', ('collector', 'firstT')): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('b', ('collector', 'lastT')): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('b', ('collector', 'neighbourFillable')): 'provenance of the collector series; the scorer RE-DERIVES _collector_ok',
    ('b', ('collectorRows',)): 'report-only row count; collector.rowCount is the gated one',
    ('b', ('continueThroughMovingMagicMove3to4Pass',)): 'negative in B: the freeze is what turns it red',
    ('b', ('firstSettledOffsetS',)): 'report-only: the perfMs form is what is ordered',
    ('b', ('flipWindowDecodable',)): 'redundant: the scorer RE-DERIVES it from the samples',
    ('b', ('footprintSources',)): 'redundant: a view of indexSamples[*].footprintSource',
    ('b', ('indexSamples', 'captureOffsetS')): "report-only in a positive arm: the positives' run is re-derived from index/hash/progress only",
    ('b', ('indexSequence',)): 'redundant: a view of indexSamples[*].index',
    ('b', ('lastAtCutHoldOffsetS',)): 'report-only: the perfMs form is what is ordered',
    ('b', ('mediaSamples', 'canvasCount')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'captureOffsetS')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'hash')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'currentTime')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'elId')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'ended')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'fromDom')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'inDocument')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'key')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'movieKey')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'paused')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'readyState')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'videoHeight')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'preservePool', 'videoWidth')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'search')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'stageMap', 'authoredHeight')): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('b', ('mediaSamples', 'stageMap', 'authoredWidth')): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('b', ('mediaSamples', 'stageMap', 'ox')): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('b', ('mediaSamples', 'stageMap', 'oy')): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('b', ('mediaSamples', 'stageMap', 's')): 'provenance: the PAGE applies this map to state videos[].rect in authored px; the scorer compares the mapped rects, never the map',
    ('b', ('mediaSamples', 'videoCount')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'checkVisibility')): 'provenance of the paint decision; `visible` and `hiddenBy` are what the attestation reads',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'h')): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'w')): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'x')): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'y')): 'report-only: the raw viewport rect kept beside the authored-px `rect` that is scored',
    ('b', ('mediaSamples', 'videos', 'currentTime')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'display')): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('b', ('mediaSamples', 'videos', 'duration')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'ended')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'fromPreservePool')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'h')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'index')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'loop')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'muted')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'networkState')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'opacityProduct')): 'provenance of the paint decision; `visible` and `hiddenBy` are what the attestation reads',
    ('b', ('mediaSamples', 'videos', 'paused')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'playbackRate')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'presentedMediaTime')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'readyState')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'rect', 'h')): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('b', ('mediaSamples', 'videos', 'rect', 'w')): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('b', ('mediaSamples', 'videos', 'rect', 'x')): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('b', ('mediaSamples', 'videos', 'rect', 'y')): "not read for a NON-painting entry: a rect is compared to the footprint only when `visible` is true, and a visible entry's missing component fails closed",
    ('b', ('mediaSamples', 'videos', 'src')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'videos', 'viewport', 'h')): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('b', ('mediaSamples', 'videos', 'viewport', 'w')): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('b', ('mediaSamples', 'videos', 'visibility')): 'not read for a POOL entry, which is classified by its retained `inDocument` alone; gated at every DOM entry, where the paint decision is re-derived from it',
    ('b', ('mediaSamples', 'videos', 'w')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('mediaSamples', 'wallMs')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash plus videos[].decoderId/presentedMediaTime',
    ('b', ('movingContinuity3to4', 'boundaryValid', 'n3')): 'provenance of movingContinuity3to4.ok, the gated key',
    ('b', ('movingContinuity3to4', 'boundaryValid', 'n4')): 'provenance of movingContinuity3to4.ok, the gated key',
    ('b', ('movingContinuity3to4', 'boundaryValid', 'ok')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'boundaryValid', 'slide4Min')): 'provenance of movingContinuity3to4.ok, the gated key',
    ('b', ('movingContinuity3to4', 'crossingIdentity', 'ok')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'rvfcMonotonic', 'advance')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'rvfcMonotonic', 'n')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'rvfcMonotonic', 'ok')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'rvfcMonotonic', 'worstRegression')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'slide3MovieDecoder')): 'provenance of movingContinuity3to4.ok, the gated key',
    ('b', ('movingContinuity3to4', 'slide4Owner')): 'provenance of movingContinuity3to4.ok, the gated key',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'afterN')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'distinctNonNull')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nonNullFrac')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'after')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'before')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'bracketed')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'from')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'run')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'to')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'maxRun')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'ok')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'reason')): 'redundant: the scorer RE-DERIVES movingContinuity3to4, null gaps and all; the cached ok/failed are what the isolation keys read',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'ok')): 'provenance: the scorer RE-RUNS movingContinuity3to4 from ownerSamples/mediaSamples and holds only `ok`/`failed` to the cache',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hiddenBy', 'hidden')): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hits')): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'n')): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'ok')): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('b', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'reason')): 'redundant: the scorer RE-DERIVES the competitor attestation from videos[].visible/rect',
    ('b', ('movingIndexRunAtCut', 'firstIndex')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'flipIndex')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'flipIndexFull')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'freezeRunAtCut')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'freezeRunBaseline')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'lastIndex')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'n')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'negativeAnomaly')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'ok')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'reason')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'totalProgressAfter')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('movingIndexRunAtCut', 'totalProgressBefore')): 'redundant: the scorer RE-DERIVES the at-cut run from the samples',
    ('b', ('nullControl', 'arm')): 'report-only: the arm ack; armResult.ok and the gated arm geometry carry it',
    ('b', ('nullControl', 'armedAt')): 'report-only: the arm instant; the trigger is timed from the advance keydown',
    ('b', ('nullControl', 'armedElId')): 'report-only: boundDecoderId is the gated identity',
    ('b', ('nullControl', 'armedHash')): 'report-only: drain.hashAtArmExact is the gated arm-hash evidence',
    ('b', ('nullControl', 'armedOwnerRect', 'h')): 'report-only: the MEASURED departure, not the armed rect, is gated',
    ('b', ('nullControl', 'armedOwnerRect', 'w')): 'report-only: the MEASURED departure, not the armed rect, is gated',
    ('b', ('nullControl', 'armedOwnerRect', 'x')): 'report-only: the MEASURED departure, not the armed rect, is gated',
    ('b', ('nullControl', 'armedOwnerRect', 'y')): 'report-only: the MEASURED departure, not the armed rect, is gated',
    ('b', ('nullControl', 'error')): 'negative: green IS absence (noControlError)',
    ('b', ('nullControl', 'fellBackToArmOwner')): 'report-only: noOwnerAmbiguousInWindow gates the binding',
    ('b', ('nullControl', 'holdFrames')): 'report-only: the rAF series itself is what loopLive and maxRafGapOk are measured on',
    ('b', ('nullControl', 'loopHandedOff')): 'report-only: the hand-off is proved by the rafLog itself',
    ('b', ('nullControl', 'motionStartedAt')): 'redundant: motionStartedMarker.started is the gated instant',
    ('b', ('nullControl', 'movedFromRect', 'h')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedFromRect', 'w')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedFromRect', 'x')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedFromRect', 'y')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedToRect', 'h')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedToRect', 'w')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedToRect', 'x')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'movedToRect', 'y')): 'report-only: firedVia is the gated form of the departure',
    ('b', ('nullControl', 'preAdvanceDepartureAt')): 'negative: green IS absence (noPreAdvanceDeparture)',
    ('b', ('nullControl', 'preAdvanceDepartureRect')): 'negative: forensics for noPreAdvanceDeparture',
    ('b', ('nullControl', 'rafLog', 't')): 'one frame with no clock widens the gap it sits in; the bound still applies',
    ('b', ('nullControl', 'staleIndexExpected')): 'report-only: superseded by coverPatchMean',
    ('b', ('ownerSamples', 'captureOffsetS')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('b', ('ownerSamples', 'footprint')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('b', ('ownerSamples', 'progress')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('b', ('ownerSamples', 'via')): 'not read by the re-derived movingContinuity3to4: it scores sceneHash/decoderId/ownerAmbiguous',
    ('b', ('ownerSettle', 'rect', 'h')): 'provenance; `settled` is the gated key',
    ('b', ('ownerSettle', 'rect', 'w')): 'provenance; `settled` is the gated key',
    ('b', ('ownerSettle', 'rect', 'x')): 'provenance; `settled` is the gated key',
    ('b', ('ownerSettle', 'rect', 'y')): 'provenance; `settled` is the gated key',
    ('b', ('preKeySample', 'badgeSeq')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('preKeySample', 'index')): 'not scored in the FREEZE arm: its at-cut segment opens after the validated re-handoff pair, so it carries no leading miss to bracket; gated in both positives, whose segments do',
    ('b', ('preKeySample', 'rect', 'h')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('preKeySample', 'rect', 'w')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('preKeySample', 'rect', 'x')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('preKeySample', 'rect', 'y')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('preKeySample', 'sceneHash')): 'provenance of the pre-key reading; its decoded `index` is what brackets the leading miss',
    ('b', ('releaseOffsetS',)): 'report-only: the perfMs form is what is ordered',
    ('b', ('releasePerfMs',)): 'redundant: nullControl.releaseAt is the gated release clock',
    ('b', ('settledIndexProgression', 'decodableFrac')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'firstIndex')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'implausibleStep')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'lastIndex')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'longestStallRun')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'n')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'nDecodable')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'nDistinct')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'reason')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    ('b', ('settledIndexProgression', 'totalForward')): 'provenance of a pre-scored sub-verdict; its `ok` is the isolation key',
    **{(cls, path): reason
       for cls in ("positive", "positiveA2")
       for path, reason in _POSITIVE_SWEEP_ALLOW.items()},
}

# The same accounting for MAIN's `_advance_c_ok` input.
_MAIN_SWEEP_ALLOW: dict[tuple[str, tuple], str] = {
    ('main', ('advanceKeyEvalMs',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('advanceKeySeen',)): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected',
    ('main', ('advanceKeySeen', 'isTrusted')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected',
    ('main', ('advanceKeySeen', 'repeat')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected',
    ('main', ('advanceKeySeen', 't')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected',
    ('main', ('advanceKeySeen', 'type')): 'report-only: the counted, filtered keydown is gated via advanceKeyEvents/advanceKeyRejected',
    ('main', ('armHash',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('armResult',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('atCutBoundary', 'reason')): "report-only: the boundary's reason string",
    ('main', ('atCutFrom',)): 'redundant: a view of atCutBoundary.from, gated there',
    ('main', ('badge', 'counts', 'measured')): 'report-only count: seqViolation is gated, per-sample truth by the recomputed coupling',
    ('main', ('badge', 'counts', 'modelled')): 'report-only count: seqViolation is gated, per-sample truth by the recomputed coupling',
    ('main', ('badge', 'counts', 'none')): 'report-only count: seqViolation is gated, per-sample truth by the recomputed coupling',
    ('main', ('badge', 'counts', 'unlogged')): 'report-only count: seqViolation is gated, per-sample truth by the recomputed coupling',
    ('main', ('badge', 'counts', 'unstable')): 'report-only count: seqViolation is gated, per-sample truth by the recomputed coupling',
    ('main', ('badge', 'install', 'cell')): 'report-only badge install geometry; install.ok is gated',
    ('main', ('badge', 'install', 'cells')): 'report-only badge install geometry; install.ok is gated',
    ('main', ('badge', 'install', 'dpr')): 'report-only badge install geometry; install.ok is gated',
    ('main', ('badge', 'install', 'elId')): 'report-only badge install geometry; install.ok is gated',
    ('main', ('badge', 'install', 'innerWidth')): 'report-only badge install geometry; install.ok is gated',
    ('main', ('badge', 'scale')): 'report-only: badge geometry diagnostic',
    ('main', ('badge', 'stats', 'installedAt')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'logged')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'motionStartedAt')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'painted')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'rehandoffSeqs')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'rehandoffs')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'running')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('badge', 'stats', 'seq')): 'report-only: MAIN has no re-handoff to exempt',
    ('main', ('bridgeEngaged',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'generation')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'key')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'newElId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'oldElId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'oldGen')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'paused')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'preservedT')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'queueLeft')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'readyState')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'detail', 'sceneHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 'kind')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('bridgeEvents', 't')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('burstStartOffsetS',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('burstStartPerfMs',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('captureId',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('captureOffsets',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('collector', 'firstT')): 'provenance of the collector series; MAIN RE-DERIVES `_collector_ok` and holds the cached `ok` to it',
    ('main', ('collector', 'lastT')): 'provenance of the collector series; MAIN RE-DERIVES `_collector_ok` and holds the cached `ok` to it',
    ('main', ('collector', 'neighbourFillable')): 'provenance of the collector series; MAIN RE-DERIVES `_collector_ok` and holds the cached `ok` to it',
    ('main', ('collectorRows',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('continueThroughMovingMagicMove3to4Pass',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'allPressesLanded')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'hashAtArm')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'hashAtArmExact')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'pressesLanded')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'pressesSent')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'selfAdvanceHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('drain', 'unlandedFromHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('firstSettledOffsetS',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('firstSettledPerfMs',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('flipWindowDecodable',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'bytes')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'captureId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'controlRect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'controlRect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'controlRect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'controlRect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'data')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'encoding')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'frameSha256')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'bandLiveFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'cols')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'deadMaxLiveFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'deltaMin')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'dilatePx')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'insetPx')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'maxP99')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'minAreaPx')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'minLiveFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'params', 'rows')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects', 'label')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'rects', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'evidence', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'p99')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'rect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'rect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'rect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'rect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'noiseFloor', 'verdict')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'deadColumnBands')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'deadRowBands')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'expect')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'label')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'liveFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'maxDelta')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'rect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'rect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'rect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'rect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'perRect', 'verdict')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'status')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'stray', 'strays')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'stray', 'verdict')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintFullyLive', 'verdict')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('footprintSources',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('hash3',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('hash4',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('indexSamples', 'captureOffsetS')): 'outside the scored settled window in every sample: MAIN gates that window only',
    ('main', ('indexSequence',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('lastAtCutHoldOffsetS',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('lastAtCutPerfMs',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'canvasCount')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'captureOffsetS')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'hash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'currentTime')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'elId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'ended')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'fromDom')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'inDocument')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'key')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'movieKey')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'paused')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'readyState')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'videoHeight')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'preservePool', 'videoWidth')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'sceneHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'search')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'stageMap', 'authoredHeight')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'stageMap', 'authoredWidth')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'stageMap', 'ox')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'stageMap', 'oy')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'stageMap', 's')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videoCount')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'checkVisibility')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'clientRect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'clientRect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'clientRect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'clientRect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'currentTime')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'decoderId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'display')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'duration')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'ended')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'fromPreservePool')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'hiddenBy')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'inDocument')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'index')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'loop')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'muted')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'networkState')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'opacityProduct')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'paused')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'playbackRate')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'presentedMediaTime')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'readyState')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'rect')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'rect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'rect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'rect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'rect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'src')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'suppressed34')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'viewport', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'viewport', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'visibility')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'visible')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'videos', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('mediaSamples', 'wallMs')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'boundaryValid', 'n3')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'boundaryValid', 'n4')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'boundaryValid', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'boundaryValid', 'slide4Min')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'crossingIdentity', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'failed')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'rvfcMonotonic', 'advance')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'rvfcMonotonic', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'rvfcMonotonic', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'rvfcMonotonic', 'worstRegression')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'slide3MovieDecoder')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'slide4Owner')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'afterN')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'distinctNonNull')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nonNullFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'after')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'before')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'bracketed')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'from')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'run')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'gaps', 'to')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'maxRun')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'nullGaps', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hiddenBy', 'hidden')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'hits')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingContinuity3to4', 'stableSlide4Owner', 'visibleCompetitors', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'firstIndex')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'flipIndex')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'flipIndexFull')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'freezeRunAtCut')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'freezeRunBaseline')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'lastIndex')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'negativeAnomaly')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'totalProgressAfter')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('movingIndexRunAtCut', 'totalProgressBefore')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('nullControl',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerDecoderId',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'captureOffsetS')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'decoderId')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'footprint')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'ownerAmbiguous')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'progress')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'sceneHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSamples', 'via')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('ownerSettle', 'rect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only (the settle dict is passed in separately)',
    ('main', ('ownerSettle', 'rect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only (the settle dict is passed in separately)',
    ('main', ('ownerSettle', 'rect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only (the settle dict is passed in separately)',
    ('main', ('ownerSettle', 'rect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only (the settle dict is passed in separately)',
    ('main', ('playerBuildErrors',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'badgeSeq')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'index')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'rect', 'h')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'rect', 'w')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'rect', 'x')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'rect', 'y')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('preKeySample', 'sceneHash')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('releaseOffsetS',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('releasePerfMs',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('releaseSplitIndex',)): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'decodableFrac')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'firstIndex')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'implausibleStep')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'lastIndex')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'longestStallRun')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'n')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'nDecodable')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'nDistinct')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'ok')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'reason')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
    ('main', ('settledIndexProgression', 'totalForward')): 'not read by `_advance_c_ok`: MAIN scores advance/settle/collector/boundary/badge/window only',
}


def _leaf_paths(node, prefix=()):
    """Every leaf of a snapshot: scalars, empty containers, and the leaves of
    every dict inside every list. A non-empty list is itself a leaf too (its
    deletion must be refused)."""
    if isinstance(node, dict):
        if not node:
            yield prefix
            return
        for k, v in node.items():
            yield from _leaf_paths(v, prefix + (k,))
    elif isinstance(node, list):
        yield prefix
        for i, v in enumerate(node):
            if isinstance(v, dict):
                yield from _leaf_paths(v, prefix + (i,))
    else:
        yield prefix


def _sweep_key(path: tuple) -> tuple:
    """The COLLAPSED question a concrete indexed path belongs to: `rafLog[0].t`
    and `rafLog[40].t` are two positions of one field."""
    return tuple(x for x in path if not isinstance(x, int))


@contextlib.contextmanager
def _without(snap: dict, path: tuple):
    """Delete ONE concrete leaf for the duration of the block, then put it back.
    Restoring beats rebuilding the bracket: the real fixture is large enough that
    a deep copy per deletion dominates the walk."""
    node = snap
    for step in path[:-1]:
        node = node[step]
    key = path[-1]
    missing = object()
    after = []
    if not isinstance(key, int) and key in node:
        keys = list(node)
        after = keys[keys.index(key) + 1:]
    value = node.pop(key) if isinstance(key, int) else node.pop(key, missing)
    try:
        yield
    finally:
        if isinstance(key, int):
            node.insert(key, value)
        elif value is not missing:
            # Back in its ORIGINAL position: a plain assignment would append the
            # key, so serial and sharded walks would leave different key orders
            # behind them (Codex test-speed r1 #3).
            node[key] = value
            for later in after:
                node[later] = node.pop(later)


def _walk(snap: dict, score) -> dict:
    out: dict = {}
    for path in list(_leaf_paths(snap)):
        if not path:
            continue
        with _without(snap, path):
            out[path] = score()
    return out


# Fields whose deletion is refused in SOME positions and tolerated in others --
# the shape the round-12 OR-aggregation hid. Each must say which positions are
# merely diagnostic.
_SWEEP_PARTIAL_ALLOW: dict[tuple[str, tuple], str] = {
    ('b', ('mediaSamples', 'videos', 'clientRect', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'x')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'clientRect', 'y')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'display')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'fromPreservePool')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'opacityProduct')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'viewport', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'viewport', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('mediaSamples', 'videos', 'visibility')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'clientRect', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'clientRect', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'clientRect', 'x')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'clientRect', 'y')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'display')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'fromPreservePool')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'opacityProduct')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'viewport', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'viewport', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positive', ('mediaSamples', 'videos', 'visibility')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'clientRect', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'clientRect', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'clientRect', 'x')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'clientRect', 'y')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'display')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'fromPreservePool')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'opacityProduct')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'viewport', 'h')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'viewport', 'w')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('positiveA2', ('mediaSamples', 'videos', 'visibility')): 'gated at every AFTER-WINDOW position, where the paint decision is re-derived; the pre-boundary samples are outside the scored window',
    ('b', ('ownerSamples', 'footprint')): "gated at every AFTER-WINDOW position, where the competitor attestation compares each painting decoder's rect to this footprint; the pre-boundary positions are outside the scored window",
    ('positive', ('ownerSamples', 'footprint')): "gated at every AFTER-WINDOW position, where the competitor attestation compares each painting decoder's rect to this footprint; the pre-boundary positions are outside the scored window",
    ('positiveA2', ('ownerSamples', 'footprint')): "gated at every AFTER-WINDOW position, where the competitor attestation compares each painting decoder's rect to this footprint; the pre-boundary positions are outside the scored window",
    ('b', ('mediaSamples', 'videos', 'presentedMediaTime')): "gated at the bound decoder's own entries in every after-window media sample; the other entries are other decoders' clocks, which movingContinuity3to4 does not read",
    ('positive', ('mediaSamples', 'videos', 'presentedMediaTime')): "gated at the bound decoder's own entries in every after-window media sample; the other entries are other decoders' clocks, which movingContinuity3to4 does not read",
    ('positiveA2', ('mediaSamples', 'videos', 'presentedMediaTime')): "gated at the bound decoder's own entries in every after-window media sample; the other entries are other decoders' clocks, which movingContinuity3to4 does not read",
}
_MAIN_SWEEP_PARTIAL_ALLOW: dict[tuple[str, tuple], str] = {}

_BRACKET_SWEEP_CACHE: dict = {}

_BRACKET_SWEEP_ARMS = (("a1", "positive"), ("b", "b"), ("a2", "positiveA2"))


def _bracket_snapshots() -> dict:
    return {"a1": _positive_snap_34(), "b": _freeze_b_snap_34(),
            "a2": _a2_snap_34()}


def _bracket_closed(snaps: dict) -> bool:
    return _score_34(
        snaps["a1"], snaps["b"], snaps["a2"]
    )["verdict"] == "inconclusive"


def _bracket_sweep_worker(arm: str, shard: int, n_shards: int) -> list:
    """Picklable, module-level worker for `_bracket_sweep`'s process pool.

    Builds its OWN fresh snapshots (a `_without` deletion mutates one in
    place, so snapshots can never be shared across processes or shards), then
    scores this shard's slice of `arm`'s leaf paths -- `paths[shard::n_shards]`
    of the SAME ordered list `_walk` would produce -- exactly as `_walk` does:
    same `_without`, same "inconclusive" predicate, empty path skipped.
    Returns a list of (path, closed) pairs rather than a dict so the parent
    can detect duplicate/missing paths across shards itself.
    """
    snaps = _bracket_snapshots()
    paths = [p for p in _leaf_paths(snaps[arm]) if p][shard::n_shards]
    out = []
    for path in paths:
        with _without(snaps[arm], path):
            out.append((path, _bracket_closed(snaps)))
    return out


def _bracket_sweep_worker_count() -> int:
    """`OBED_TEST_SWEEP_WORKERS` overrides; `1` forces the original serial
    walk (useful under nested xdist or for debugging). Capped at the
    machine's core count either way."""
    cap = os.cpu_count() or 1
    override = os.environ.get("OBED_TEST_SWEEP_WORKERS")
    if override is None:
        return cap
    if not override.isdigit() or int(override) < 1:
        raise pytest.UsageError(
            f"OBED_TEST_SWEEP_WORKERS must be an integer >= 1, got {override!r}"
        )
    return min(int(override), cap)


def _bracket_sweep() -> dict:
    """{(arm class, CONCRETE indexed path) -> did that one deletion fail closed?}

    Positions are kept apart and aggregated with AND by the callers (review r10
    MAJOR 5): the round-12 walk ORed them, so one gated position marked the whole
    collapsed field gated and hid every other position's hole.

    The deletions are independent pure-scorer calls, so they are fanned out over
    a `ProcessPoolExecutor`; every path is still visited exactly once and scored
    exactly as `_walk` would score it."""
    if not _BRACKET_SWEEP_CACHE:
        n_workers = _bracket_sweep_worker_count()

        snaps = _bracket_snapshots()
        if n_workers <= 1:
            for arm, cls in _BRACKET_SWEEP_ARMS:
                walked = _walk(snaps[arm], lambda: _bracket_closed(snaps))
                for path, closed in walked.items():
                    _BRACKET_SWEEP_CACHE[(cls, path)] = closed
            return _BRACKET_SWEEP_CACHE

        expected = {
            cls: len([p for p in _leaf_paths(snaps[arm]) if p])
            for arm, cls in _BRACKET_SWEEP_ARMS
        }

        seen: dict = {}
        with concurrent.futures.ProcessPoolExecutor(max_workers=n_workers) as ex:
            futures = {
                ex.submit(_bracket_sweep_worker, arm, shard, n_workers): cls
                for arm, cls in _BRACKET_SWEEP_ARMS
                for shard in range(n_workers)
            }
            for fut in concurrent.futures.as_completed(futures):
                cls = futures[fut]
                # .result() re-raises any worker exception loudly -- a failed
                # shard must fail the sweep, never silently shrink the cache.
                for path, closed in fut.result():
                    key = (cls, path)
                    if key in seen:
                        raise AssertionError(f"bracket sweep path scored twice: {key}")
                    seen[key] = closed

        for cls, count in expected.items():
            actual = sum(1 for (c, _p) in seen if c == cls)
            assert actual == count, (
                f"bracket sweep for {cls!r}: expected {count} paths, "
                f"covered {actual} -- shards left a gap"
            )
        # Published only once whole: a failed shard must not leave a partial
        # cache for the next caller to mistake for a finished sweep.
        _BRACKET_SWEEP_CACHE.update(seen)
    return _BRACKET_SWEEP_CACHE


def _collapse(swept: dict) -> tuple[dict, dict]:
    """(fully gated keys, keys with at least one surviving position). A key is
    GATED only when EVERY scored position of it fails closed."""
    positions: dict = {}
    for (cls, path), closed in swept.items():
        positions.setdefault((cls, _sweep_key(path)), []).append(closed)
    gated = {k: v for k, v in positions.items() if all(v)}
    survived = {k: v for k, v in positions.items() if not all(v)}
    return gated, survived


def test_bracket_absence_sweep_is_exhaustive():
    """Walk EVERY leaf of the clean pass-capable bracket -- the REAL one, loaded
    from `tests/fixtures/p2_freeze_3to4/` -- delete it, and require INCONCLUSIVE.
    A field counts as gated only when EVERY one of its positions fails closed;
    anything else must be named in `_SWEEP_ALLOW` with a reason, and a field that
    is gated in SOME positions only must additionally be classified in
    `_SWEEP_PARTIAL_ALLOW`. A1 and A2 are the run's two REAL positives and are
    walked independently (review r11 MINOR 1)."""
    assert _score_34(
        _positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()
    )["verdict"] == "pass"
    swept = _bracket_sweep()
    assert len(swept) > 3000, f"the walk collapsed to {len(swept)} paths"
    _, survived = _collapse(swept)
    assert [k for k in sorted(survived) if k not in _SWEEP_ALLOW] == [], (
        f"leaves whose deletion kept a verdict: "
        f"{[k for k in sorted(survived) if k not in _SWEEP_ALLOW]}"
    )
    partial = sorted(k for k, v in survived.items() if any(v))
    assert [k for k in partial if k not in _SWEEP_PARTIAL_ALLOW] == [], (
        f"fields gated in some positions and not others, unclassified: "
        f"{[k for k in partial if k not in _SWEEP_PARTIAL_ALLOW]}"
    )
    # ...and the one remaining partial is MEASURED, not merely excused: the rVFC
    # clock is refused at exactly the bound decoder's entries in the after-window
    # media samples, which is every position `movingContinuity3to4` reads.
    b = _freeze_b_snap_34()
    expected = sorted(
        (i, j)
        for i, m in enumerate(b["mediaSamples"])
        if (p2._strict_hash_num(m["sceneHash"]) or -1) >= p2.SLIDE4_MIN_HASH
        for j, v in enumerate(m["videos"])
        if str(v.get("decoderId")) == str(b["ownerDecoderId"])
        and "presentedMediaTime" in v
    )
    closed_at = sorted(
        (path[1], path[3]) for (cls, path), closed in swept.items()
        if cls == "b"
        and _sweep_key(path) == ("mediaSamples", "videos", "presentedMediaTime")
        and closed
    )
    assert closed_at == expected


def test_without_restores_the_original_key_and_list_order():
    """A sharded walk and the serial walk delete different sequences of leaves
    from one long-lived snapshot. They can only be equivalent if every deletion
    leaves the snapshot EXACTLY as it found it -- including dict key order,
    which a plain `node[key] = value` restore would silently rotate."""
    snap = {"a": 1, "b": {"x": 1, "y": 2, "z": 3}, "c": [10, 20, 30]}
    before = json.dumps(snap)
    for path in [p for p in _leaf_paths(snap) if p]:
        with _without(snap, path):
            assert json.dumps(snap) != before
        assert json.dumps(snap) == before, path


@pytest.mark.parametrize("raw", ["", "0", "-2", "two", "1.5"])
def test_sweep_worker_override_refuses_a_malformed_value(monkeypatch, raw):
    monkeypatch.setenv("OBED_TEST_SWEEP_WORKERS", raw)
    with pytest.raises(pytest.UsageError, match="OBED_TEST_SWEEP_WORKERS"):
        _bracket_sweep_worker_count()


def test_sweep_worker_count_is_capped_and_survives_an_unknown_core_count(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    monkeypatch.delenv("OBED_TEST_SWEEP_WORKERS", raising=False)
    assert _bracket_sweep_worker_count() == 1
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    assert _bracket_sweep_worker_count() == 4
    monkeypatch.setenv("OBED_TEST_SWEEP_WORKERS", "64")
    assert _bracket_sweep_worker_count() == 4
    monkeypatch.setenv("OBED_TEST_SWEEP_WORKERS", "1")
    assert _bracket_sweep_worker_count() == 1


def test_bracket_sweep_allowlist_has_no_dead_entries():
    """A stale excuse is worse than none: every allowlist entry must still be
    survivable, or a reader trusts a reason for a field that is now gated."""
    _, survived = _collapse(_bracket_sweep())
    assert set(_SWEEP_ALLOW) - set(survived) == set(), (
        f"allowlist entries that are already gated: {set(_SWEEP_ALLOW) - set(survived)}"
    )
    assert all(v.strip() for v in _SWEEP_ALLOW.values()), "an allowlist entry has no reason"
    partial = {k for k, v in survived.items() if any(v)}
    assert set(_SWEEP_PARTIAL_ALLOW) - partial == set(), (
        f"partial-allowlist entries that are not partial: {set(_SWEEP_PARTIAL_ALLOW) - partial}"
    )
    assert all(v.strip() for v in _SWEEP_PARTIAL_ALLOW.values())


_MAIN_SWEEP_CACHE: dict = {}


def _main_sweep() -> dict:
    """The walk over MAIN's real arguments. Both settles ARE members of the
    captured snapshot, exactly as MAIN passes them, so the one snapshot walk
    covers every leaf of both (review r11 MAJOR 4, r12 MINOR 3)."""
    if not _MAIN_SWEEP_CACHE:
        snap, _, settle, owner = _main_inputs()
        assert owner is snap["ownerSettle"] and settle is snap["advanceSettle"]

        def score() -> bool:
            return p2._advance_c_ok(
                snap, snap.get("indexSamples") or [], settle, owner
            ) is False

        _MAIN_SWEEP_CACHE.update(
            {("main", path): closed for path, closed in _walk(snap, score).items()}
        )
    return _MAIN_SWEEP_CACHE


def test_main_absence_sweep_is_exhaustive():
    """The same exhaustive walk over MAIN's `_advance_c_ok` input."""
    meta, samples, settle, owner = _main_inputs()
    assert p2._advance_c_ok(meta, samples, settle, owner) is True
    swept = _main_sweep()
    assert len(swept) > 1000, f"the walk collapsed to {len(swept)} paths"
    _, survived = _collapse(swept)
    assert [k for k in sorted(survived) if k not in _MAIN_SWEEP_ALLOW] == [], (
        f"MAIN leaves whose deletion kept the gate green: "
        f"{[k for k in sorted(survived) if k not in _MAIN_SWEEP_ALLOW]}"
    )
    partial = sorted(k for k, v in survived.items() if any(v))
    assert [k for k in partial if k not in _MAIN_SWEEP_PARTIAL_ALLOW] == [], (
        f"MAIN fields gated in some positions and not others, unclassified: "
        f"{[k for k in partial if k not in _MAIN_SWEEP_PARTIAL_ALLOW]}"
    )


def test_main_sweep_allowlist_has_no_dead_entries():
    _, survived = _collapse(_main_sweep())
    assert set(_MAIN_SWEEP_ALLOW) - set(survived) == set(), (
        f"allowlist entries that are already gated: "
        f"{set(_MAIN_SWEEP_ALLOW) - set(survived)}"
    )
    partial = {k for k, v in survived.items() if any(v)}
    assert set(_MAIN_SWEEP_PARTIAL_ALLOW) - partial == set(), (
        f"partial-allowlist entries that are not partial: "
        f"{set(_MAIN_SWEEP_PARTIAL_ALLOW) - partial}"
    )


def test_absence_sweep_covers_every_integrity_key():
    """The sweep is only worth what it covers: assert it names EVERY integrity
    key the scorer scores, so a future key cannot be added without a case."""
    verdict = _score_34(
        _positive_snap_34(), _freeze_b_snap_34(), _a2_snap_34()
    )
    assert verdict["verdict"] == "pass"
    scored = set(verdict["integrityKeys"])
    covered = {case[0] for case in _ABSENCE_CASES}
    assert scored - covered == set(), f"integrity keys with no absence case: {scored - covered}"
    assert covered - scored == set(), f"absence cases for non-keys: {covered - scored}"
