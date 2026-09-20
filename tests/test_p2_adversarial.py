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
# across the two bracketing positives. A hold that never fired is INCONCLUSIVE
# (never PASS/FAIL): a silently-unfired hold would masquerade as a passing
# positive and be misread as "the counter gate is vacuous".
# --------------------------------------------------------------------------- #
def _positive_snap_34(**overrides) -> dict:
    snap = {
        "hash3": "#7", "hash4": "#8",
        "armHash": "7",
        "armResult": {"ok": True, "armedElId": 4, "armedHash": "7", "stageOrigin": {"x": 0.0, "y": 0.0}},
        "movingIndexRunAtCut": {
            "ok": True, "reason": None, "flipIndex": 3, "n": 10,
            "freezeRunAtCut": 0, "negativeAnomaly": False,
        },
        "settledIndexProgression": {"ok": True},
        "movingContinuity3to4": {
            "ok": True, "failed": [], "slide4Owner": 4, "slide3MovieDecoder": 4,
            "boundaryValid": {"ok": True, "n3": 7, "n4": 8, "slide4Min": 8},
            "stableSlide4Owner": {"ok": True},
            "crossingIdentity": {"ok": True},
            "rvfcMonotonic": {"ok": True, "advance": 1.2},
        },
        "footprintFullyLive": {"ok": True},
        "continueThroughMovingMagicMove3to4Pass": True,
        "indexSequence": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
        "footprintSources": ["measured"] * 10,
        "captureOffsets": [-0.1, 0.0, 0.05, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
        "ownerDecoderId": 4,
        "playerBuildErrors": [],
        "bridgeEngaged": True,
        "bridgeEvents": [],
        "nullControl": None,
        "perfNowAtClick": None,
        "lastAtCutCaptureOffsetS": 0.7,
        "burstStartOffsetS": 1.5,
    }
    snap.update(overrides)
    return snap


def _freeze_b_snap_34(**overrides) -> dict:
    raf = [
        {
            "t": 1120.0 + 20.0 * i, "elementFromPointIsCover": True, "ownerResolved": True,
            "coverRect": {"x": 300.0, "y": 700.0, "w": 200.0, "h": 350.0},
            "measuredRect": {"x": 300.0, "y": 700.0, "w": 500.0, "h": 350.0},
        }
        for i in range(45)
    ]
    snap = _positive_snap_34(
        movingIndexRunAtCut={
            "ok": False, "reason": "freeze run at cut", "flipIndex": 3, "n": 10,
            "freezeRunAtCut": 8, "negativeAnomaly": False,
        },
        continueThroughMovingMagicMove3to4Pass=False,  # the freeze flips this RED
        indexSequence=[37, 38, 39, 40, 40, 40, 40, 40, 40, 40],
        perfNowAtClick=1000.0,
        nullControl={
            "status": "released", "holdStartedAt": 1120.0, "firedVia": "motion",
            "releaseAt": 2000.0, "staleIndexExpected": 40, "staleCurrentTime": 1.33,
            "ownerReadyState": 4, "coverPatchMean": 40.0,
            "paintCount": 1, "coverPatchStart": {"sum": 12345, "mean": 40.0},
            "coverPatchEnd": {"sum": 12345, "mean": 40.0},
            "ownerAmbiguousInWindow": False, "boundDecoderId": 4, "armedElId": 4,
            "fellBackToArmOwner": False, "rafLog": raf, "error": None,
            "stageOrigin": {"x": 0.0, "y": 0.0},
            "armedMotionMarker": None,
            "firedMotionMarker": {"started": 1120.0, "generation": 1, "atScene": 8},
        },
    )
    snap.update(overrides)
    return snap


def test_freeze_control_passes_on_clean_bracket():
    """Positive control for the instrument: a correctly-fired freeze turns the
    at-cut counter RED for the right reason while the bridged decoder stays live,
    both bracketing positives are green, and every invariant sub-verdict is equal
    across A1/B/A2. (was test_freeze_control_passes_on_clean_bracket, 1->2)"""
    verdict = p2._score_freeze_control(_positive_snap_34(), _freeze_b_snap_34(), _positive_snap_34())
    assert verdict["ok"] is True, verdict["failed"]
    assert verdict["verdict"] == "pass"
    assert verdict["isolationDiffs"] == {}


def test_freeze_control_never_fired_hold_is_inconclusive_not_pass():
    """A hold that silently never fired (holdStartedAt null) leaves the counter
    GREEN in B, which looks exactly like a passing positive. It MUST be
    INCONCLUSIVE, not PASS and not a plain FAIL. (was ..._never_fired_hold_...)"""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "status": "armed", "holdStartedAt": None}
    b["movingIndexRunAtCut"] = {
        "ok": True, "reason": None, "flipIndex": 3, "n": 10,
        "freezeRunAtCut": 0, "negativeAnomaly": False,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert verdict["ok"] is False


def test_freeze_control_max_raf_gap_is_disqualifying():
    """Unlike the retired static 1->2 footprint, the 3->4 cover TRACKS a moving
    target every rAF: a stall of >MAX_RAF_GAP_MS leaves the cover behind the
    moving movie, so it is DISQUALIFYING integrity here, never a diagnostic-only
    field (plan §4). (replaces the 1->2 'raf gap alone is not disqualifying' test
    — the owner decision for 3->4 is the opposite)."""
    b = _freeze_b_snap_34()
    raf = b["nullControl"]["rafLog"]
    spiked = raf[:20] + [
        {**r, "t": raf[19]["t"] + 380.0 + 20.0 * i} for i, r in enumerate(raf[20:])
    ]
    b["nullControl"] = {**b["nullControl"], "rafLog": spiked}
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
            {"t": 1120.0, "elementFromPointIsCover": True,
             "coverRect": {"x": 300.0, "y": 700.0, "w": 200.0, "h": 350.0},
             "measuredRect": {"x": 300.0, "y": 700.0, "w": 500.0, "h": 350.0}},
            {"t": 1140.0, "elementFromPointIsCover": True,
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
    b["indexSequence"] = [37, 38, 39, 0, 0, 0, 0, 0, 0, 0]  # unrendered black -> decodes 0
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
    b["indexSequence"] = [5, 4, 3, 3, 3, 3, 3, 3, 3, 3]  # frozen at a dark counter value
    b["nullControl"] = {
        **b["nullControl"], "staleCurrentTime": 7.33, "coverPatchMean": 3.0,
        "coverPatchStart": {"sum": 1, "mean": 3.0}, "coverPatchEnd": {"sum": 1, "mean": 3.0},
    }
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
    """A trigger that fired BEFORE the advance held a pre-cut frame, not the cut
    => INCONCLUSIVE (arm-integrity guard)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "holdStartedAt": 900.0}  # < perfNowAtClick 1000
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAfterAdvance" in verdict["integrityFailed"]


def test_freeze_control_fails_if_counter_did_not_go_red():
    """If the injected freeze did NOT turn the at-cut counter RED, the control
    fails: the gate did not catch the freeze."""
    b = _freeze_b_snap_34()
    b["movingIndexRunAtCut"] = {
        "ok": True, "reason": None, "flipIndex": 3, "n": 10,
        "freezeRunAtCut": 0, "negativeAnomaly": False,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert verdict["verdict"] == "fail"
    assert "indexRunRed" in verdict["failed"]


def test_freeze_control_fails_on_weak_freeze_margin():
    """A freeze run barely over the gate's tolerance (3, not >= 6) is
    indistinguishable from coarse-capture jitter and must not qualify the
    instrument."""
    b = _freeze_b_snap_34()
    b["movingIndexRunAtCut"] = {**b["movingIndexRunAtCut"], "freezeRunAtCut": 3}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["ok"] is False
    assert "freezeRunMargin" in verdict["failed"]


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
    nothing during the move: `firedAtMoveStart` requires `firedVia == 'motion'`,
    never a hash-only fallback fire — INCONCLUSIVE (owner decision 8c)."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "firedVia": "hash"}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_stale_prearmed_motion_falls_through_to_hash_is_inconclusive():
    """Trigger hardening (plan item 3): a stale `__obedMotion` left by an EARLIER
    bridge engagement on the same element must not fire the hold — the JS only
    triggers 'motion' on a marker that is NEW relative to what was armed
    (different started/generation, and matching boundary.atScene when the
    runtime exposes one). A stale marker therefore falls through to the hash
    fallback, which the scorer treats exactly like any other hash-only fire:
    INCONCLUSIVE, never counted as `firedAtMoveStart`. (The JS trigger logic
    itself cannot be exercised outside a browser; this asserts the SCORER-side
    contract the hardening relies on.)"""
    b = _freeze_b_snap_34()
    b["nullControl"] = {
        **b["nullControl"],
        "firedVia": "hash",
        "armedMotionMarker": {"started": 500.0, "generation": 1, "atScene": 8},
        "firedMotionMarker": None,
    }
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "firedAtMoveStart" in verdict["integrityFailed"]


def test_freeze_control_cover_tracks_footprint_violation_is_inconclusive():
    """`coverTracksFootprint` = 100% of hold frames with the cover rect matching
    the JS's own `subRect(measuredRect)` derivation within COVER_TRACK_TOL_PX. One
    frame off (the cover left behind the moving footprint) => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    raf = list(b["nullControl"]["rafLog"])
    bad = dict(raf[10])
    bad["coverRect"] = {**bad["coverRect"], "x": bad["coverRect"]["x"] + 25.0}
    raf[10] = bad
    b["nullControl"] = {**b["nullControl"], "rafLog": raf}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "coverTracksFootprint" in verdict["integrityFailed"]


def test_freeze_control_release_after_burst_started_is_inconclusive():
    """A release that slips past the settled-slide-4 visible-content burst start
    leaves the cover in place for part of the burst — it would red
    `footprintFullyLive` for the WRONG reason. `releaseBetweenLastCaptureAndBurst`
    is two-sided: INCONCLUSIVE, not a verdict."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "releaseAt": 3000.0}  # offset 2.0s > burstStartOffsetS 1.5
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseBetweenLastCaptureAndBurst" in verdict["integrityFailed"]


def test_freeze_control_release_before_last_capture_is_inconclusive():
    """The other side of the same two-sided check: releasing before the last
    at-cut capture leaves that capture uncovered, undermining the freeze it is
    meant to have observed => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "releaseAt": 1150.0}  # offset 0.15s < lastAtCutCaptureOffsetS 0.7
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "releaseBetweenLastCaptureAndBurst" in verdict["integrityFailed"]


def test_freeze_control_modelled_in_hold_sample_is_inconclusive():
    """A `modelled` (not measured) footprint sample inside the hold window means
    the ROI mapping for that decode is unproven — `allInHoldMeasured` fails
    closed rather than trusting a decode off an unverified ROI."""
    b = _freeze_b_snap_34()
    sources = list(b["footprintSources"])
    sources[5] = "modelled"
    b["footprintSources"] = sources
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


def test_freeze_control_stage_origin_nonzero_is_inconclusive():
    """The partial cover is `position:fixed` (viewport px) while the moving
    <video> is stage-absolute px — they only coincide while the stage origin is
    (0,0). A nonzero origin at arm invalidates the geometry => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    b["nullControl"] = {**b["nullControl"], "stageOrigin": {"x": 12.0, "y": 0.0}}
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "stageOriginZero" in verdict["integrityFailed"]


def test_freeze_control_flip_window_undecodable_on_measured_only_is_inconclusive():
    """The flip window (`[flipIndex-1, flipIndex+3]`, flipIndex=3) is recomputed
    by the scorer over the MEASURED-only subsequence; an undecodable sample
    inside it (index 2, all sources still 'measured' so the alignment is
    untouched) must fail `flipWindowDecodable` closed => INCONCLUSIVE."""
    b = _freeze_b_snap_34()
    seq = list(b["indexSequence"])
    seq[2] = None
    b["indexSequence"] = seq
    verdict = p2._score_freeze_control(_positive_snap_34(), b, _positive_snap_34())
    assert verdict["verdict"] == "inconclusive"
    assert "flipWindowDecodable" in verdict["integrityFailed"]


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
