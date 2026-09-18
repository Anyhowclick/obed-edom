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
# F5 — steady folding by object identity, not by size.
# --------------------------------------------------------------------------- #
def test_f5_steady_folding_picks_same_object_not_same_size(tmp_path):
    """Fold only the steady textures owned by the boundary crossfade's OWN
    object; a second, same-sized movie's steadys must not be folded in.

    Slide 1: object `obj-movie1` owns steadys {A, A2}; a same-sized OTHER movie
    `obj-movie2` owns steady {X}. Slide 2: `obj-movie1` owns {B}, `obj-movie2`
    owns {Y}. The unique boundary A->B belongs to obj-movie1, so outgoing folds
    {A, A2} (not X) and incoming folds {B} (not Y).
    """
    slides = [
        (
            "slide1",
            [
                _video_layer("obj-movie1", "A"),
                # A second footprint-sized steady on the SAME object id.
                _video_layer("obj-movie1", "A2"),
                _video_layer("obj-movie2", "X"),
            ],
        ),
        (
            "slide2",
            [
                _video_layer("obj-movie1", "B"),
                _video_layer("obj-movie2", "Y"),
                _magic_move([_crossfade("A", "B")]),
            ],
        ),
    ]
    result = p2._derive_movie_texids(_write_player(tmp_path, slides))

    assert result["decoderKey"] == "movie1"
    assert result["outgoing"] == ["A", "A2"]  # same-object fold, X excluded
    assert result["incoming"] == ["B"]  # Y (other movie) excluded
    assert "X" not in result["outgoing"]
    assert "Y" not in result["incoming"]


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
# F1b — fail-closed engagement gate `feedEngagedAt1to2`.
# --------------------------------------------------------------------------- #
def _valid_texids() -> dict:
    return {"decoderKey": "movie1", "outgoing": ["out1"], "incoming": ["in1"]}


def _post_flip_samples(decoder_id="dec-1", context_type="2d") -> list[dict]:
    """Two post-flip samples (`sceneHash != hash1`) with a stable decoder."""
    return [
        {"sceneHash": "#2", "decoderId": decoder_id, "contextType": context_type},
        {"sceneHash": "#3", "decoderId": decoder_id, "contextType": context_type},
    ]


def _incoming_draw(decoder_id="dec-1", canvas_id="in1", hash_num=6) -> dict:
    return {
        "kind": "texture-feed-draw",
        "detail": {
            "slot": "incoming",
            "decoderId": decoder_id,
            "canvasId": canvas_id,
            "hashNum": hash_num,
            "authoredBy": "player-draw",
        },
    }


def test_feed_engaged_passes_only_when_every_condition_holds():
    """Positive control: all five sub-conditions satisfied => ok, no failures.
    Proves the gate is not wired to always-fail."""
    verdict = p2._score_feed_engaged(
        _valid_texids(),
        {"ok": True},
        _post_flip_samples(),
        [_incoming_draw()],
        "#1",
        "#2",
    )
    assert verdict["ok"] is True
    assert verdict["failed"] == []
    assert verdict["boundDecoderId"] == "dec-1"


def test_feed_engaged_fails_closed_when_incoming_draw_absent():
    """No incoming texture-feed-draw/mo-prepaint-draw => the finding cannot pass.

    This is the empirical round-1 reality: only outgoing prepaint draws fired,
    zero incoming, so the gate stays RED for a proven reason.
    """
    verdict = p2._score_feed_engaged(
        _valid_texids(),
        {"ok": True},
        _post_flip_samples(),
        [],  # no engagement events at all
        "#1",
        "#2",
    )
    assert verdict["ok"] is False
    assert verdict["failed"] == ["incomingFeedDraw"]


def test_feed_engaged_fails_when_only_outgoing_draws_exist():
    """An outgoing-slot draw is not engagement of the incoming canvas."""
    outgoing_only = {
        "kind": "mo-prepaint-draw",
        "detail": {"slot": "outgoing", "decoderId": "dec-1", "canvasId": "out1", "hashNum": 4},
    }
    verdict = p2._score_feed_engaged(
        _valid_texids(), {"ok": True}, _post_flip_samples(), [outgoing_only], "#1", "#2"
    )
    assert verdict["ok"] is False
    assert "incomingFeedDraw" in verdict["failed"]


def test_feed_engaged_fails_closed_when_decoder_id_unstable():
    """Two different decoderIds across the after window => no single bound
    decoder => fail. Cascades to context/draw checks (which need that id)."""
    unstable = [
        {"sceneHash": "#2", "decoderId": "dec-1", "contextType": "2d"},
        {"sceneHash": "#3", "decoderId": "dec-2", "contextType": "2d"},
    ]
    verdict = p2._score_feed_engaged(
        _valid_texids(), {"ok": True}, unstable, [_incoming_draw()], "#1", "#2"
    )
    assert verdict["ok"] is False
    assert "stableDecoder" in verdict["failed"]
    assert verdict["boundDecoderId"] is None


def test_feed_engaged_fails_closed_when_context_type_not_2d():
    """A webgl (non-2D) fed canvas fails the passive-context condition in
    isolation — decoder is stable, draw present, only contextType is wrong."""
    verdict = p2._score_feed_engaged(
        _valid_texids(),
        {"ok": True},
        _post_flip_samples(context_type="webgl"),
        [_incoming_draw()],
        "#1",
        "#2",
    )
    assert verdict["ok"] is False
    assert "contextType2d" in verdict["failed"]
    # Isolation: the other conditions still held.
    assert "stableDecoder" not in verdict["failed"]
    assert "incomingFeedDraw" not in verdict["failed"]


def test_feed_engaged_fails_closed_on_one_sided_or_null_texids():
    """Never pass by absence of texid data: a one-sided (or null) texid object
    fails the both-sided condition."""
    one_sided = {"decoderKey": "movie1", "outgoing": [], "incoming": ["in1"]}
    verdict = p2._score_feed_engaged(
        one_sided, {"ok": True}, _post_flip_samples(), [_incoming_draw()], "#1", "#2"
    )
    assert verdict["ok"] is False
    assert "bothSidedTexids" in verdict["failed"]


def test_feed_engaged_fails_when_motion_across_flip_not_ok():
    """`motionAcrossFlip.ok` is a necessary condition."""
    verdict = p2._score_feed_engaged(
        _valid_texids(),
        {"ok": False},
        _post_flip_samples(),
        [_incoming_draw()],
        "#1",
        "#2",
    )
    assert verdict["ok"] is False
    assert "motionAcrossFlipOk" in verdict["failed"]


def test_feed_engaged_draw_before_boundary_window_does_not_count():
    """A draw at a hashNum before the boundary (warmup) is not 1->2 engagement."""
    early_draw = _incoming_draw(hash_num=0)
    verdict = p2._score_feed_engaged(
        _valid_texids(), {"ok": True}, _post_flip_samples(), [early_draw], "#1", "#2"
    )
    # hash1 == "#1" (num 1); a draw at #0 is filtered out of the window.
    assert verdict["ok"] is False
    assert "incomingFeedDraw" in verdict["failed"]


def test_feed_engaged_fails_closed_on_empty_after_window():
    """No post-flip samples at all => stable decoder cannot be proven => fail
    (never pass by absence of data)."""
    verdict = p2._score_feed_engaged(_valid_texids(), {"ok": True}, [], [_incoming_draw()], "#1", "#2")
    assert verdict["ok"] is False
    assert "stableDecoder" in verdict["failed"]
