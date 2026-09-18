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

import importlib.util
import json
import sys
from pathlib import Path

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
# `_derive_movie_texids` — corrected model relabels the crossfade as 2->3.
# --------------------------------------------------------------------------- #
def test_derive_movie_texids_labels_boundary_as_2to3(tmp_path):
    """The resolved footprint magic-move `contents` crossfade is the 2->3
    restart-side boundary (Keynote stores the transition under incoming slide #3),
    not 1->2, so a successful resolve is tagged `boundary == "2to3"` (handover
    CORRECTION 2026-09-18)."""
    slides = [
        ("slide1", [_video_layer("obj-m1", "S")]),
        ("slide2", [_video_layer("obj-m1", "S"), _magic_move([_crossfade("P", "R")])]),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))
    assert result["decoderKey"] == "movie1"
    assert result["boundary"] == "2to3"
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
