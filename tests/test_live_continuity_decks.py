from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from obed_edom import live_continuity
from obed_edom.fixture_paths import fixture
from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
MINIMAL_ROOT = FIXTURE_ROOT / "minimal_alpha_dsk"
POSITIVE_ROOT = FIXTURE_ROOT / "positive_control"
LOOP_ROOT = FIXTURE_ROOT / "minimal_alpha_dsk_loop"

GL_DECKS_ROOT = fixture("gl-decks")
MINIMAL_REAL_ROOT = GL_DECKS_ROOT / "Minimal Alpha_DSK" / "html"
POSITIVE_REAL_ROOT = GL_DECKS_ROOT / "Positive Control" / "html"
SOAK_LOOP_REAL_ROOT = fixture("p2-soak-loop") / "html-unmodified"


def _resolver(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if resolved_root not in candidate.parents and candidate != resolved_root:
        raise ValueError("outside root")
    if not candidate.is_file():
        raise FileNotFoundError(relative)
    return candidate


def _slides(uuids: list[str]) -> list[dict]:
    return [
        {"playerIndex": index, "originalOrdinal": index + 1, "exportedUuid": uuid, "skipped": False}
        for index, uuid in enumerate(uuids)
    ]


def _slide_list(root: Path) -> list[str]:
    return json.loads((root / "assets" / "header.json").read_text())["slideList"]


def _plan(root: Path, uuids: list[str]) -> ContinuityPlan | Unsupported:
    return derive_plan(root, _slides(uuids), resolver=_resolver)


MINIMAL_UUIDS = _slide_list(MINIMAL_ROOT)
POSITIVE_UUIDS = _slide_list(POSITIVE_ROOT)
LOOP_UUIDS = _slide_list(LOOP_ROOT)


def test_minimal_s4_to_s5_pins_with_no_refusal():
    plan = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[0:2])
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()
    movies = plan.boundaries[0].as_dict()["movies"]
    assert [m["action"] for m in movies] == ["pin"]
    assert plan.to_runtime() == Unsupported(
        "deck shape is not yet qualified for continuity (only P2-measured plans are)"
    )


def test_minimal_s4_to_s5_gl_replay_keyword():
    # Deck (i) has no overlap refusal on its pin, so derivation never applies
    # (arming plan §11: only a refused pin is considered for glReplay) and the
    # glReplay keys stay absent, exactly as with the flag off.
    plan = derive_plan(MINIMAL_ROOT, _slides(MINIMAL_UUIDS[0:2]), resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].as_dict()["movies"][0]
    assert "glReplay" not in movie
    assert "glReplayReason" not in movie


def test_minimal_s6_to_s7_two_pins_one_refusal():
    plan = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[2:4])
    assert isinstance(plan, ContinuityPlan)
    movies = plan.boundaries[0].as_dict()["movies"]
    assert [m["action"] for m in movies] == ["pin", "pin"]
    assert len(plan.refusals) == 1
    assert plan.to_runtime() == Unsupported(
        "deck shape is not yet qualified for continuity (only P2-measured plans are)"
    )


def test_minimal_s6_to_s7_gl_replay_refuses_two_movies():
    plan = derive_plan(MINIMAL_ROOT, _slides(MINIMAL_UUIDS[2:4]), resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    refused = [r for r in plan.refusals if r["reason"]]
    assert len(refused) == 1
    movies = plan.boundaries[0].as_dict()["movies"]
    refused_movie = next(m for m in movies if m["asset"] == refused[0]["asset"])
    assert refused_movie["glReplay"] is False
    assert refused_movie["glReplayReason"] == (
        "2 movies are carried across the boundary, expected exactly 1"
    )


@pytest.mark.parametrize("slice_", [(4, 6), (0, 6)])
def test_minimal_ambiguous_ownership_is_unsupported(slice_):
    start, end = slice_
    plan = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[start:end])
    assert isinstance(plan, Unsupported)
    assert "ambiguous" in plan.reason
    assert "4 geometry-equal pair" in plan.reason


def test_positive_control_actions_and_to_runtime():
    plan = _plan(POSITIVE_ROOT, POSITIVE_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    actions = [
        boundary.as_dict()["movies"][0]["action"]
        for boundary in plan.boundaries
        if boundary.as_dict()["movies"]
    ]
    assert actions == ["pin", "bridge", "restart", "restart"]
    unsupported = plan.to_runtime()
    assert isinstance(unsupported, Unsupported)
    assert "bridge boundary precedes" in unsupported.reason


@pytest.mark.skipif(not GL_DECKS_ROOT.is_dir(), reason="real gl-deck exports not available")
def test_minimal_fixture_parity_with_real_export():
    real = _plan(MINIMAL_REAL_ROOT, MINIMAL_UUIDS)
    fixture = _plan(MINIMAL_ROOT, MINIMAL_UUIDS)
    assert isinstance(real, Unsupported)
    assert isinstance(fixture, Unsupported)
    assert real.reason == fixture.reason


@pytest.mark.skipif(not GL_DECKS_ROOT.is_dir(), reason="real gl-deck exports not available")
@pytest.mark.parametrize("slice_", [(0, 2), (2, 4), (4, 6)])
def test_minimal_sub_deck_parity_with_real_export(slice_):
    start, end = slice_
    real = _plan(MINIMAL_REAL_ROOT, MINIMAL_UUIDS[start:end])
    fixture = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[start:end])

    def dump(plan):
        return plan.reason if isinstance(plan, Unsupported) else plan.as_dict()

    assert dump(real) == dump(fixture)


@pytest.mark.skipif(not GL_DECKS_ROOT.is_dir(), reason="real gl-deck exports not available")
def test_positive_control_fixture_parity_with_real_export():
    real = _plan(POSITIVE_REAL_ROOT, POSITIVE_UUIDS)
    fixture = _plan(POSITIVE_ROOT, POSITIVE_UUIDS)
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.as_dict() == fixture.as_dict()


# --- looping movies (keynote_live_continuity_loopmode plan sections 2 and 4) ---------------
#
# `minimal_alpha_dsk_loop/` is the owner's Repeat -> Loop export of Minimal Alpha_DSK
# (`output/fixtures/p2-soak-loop/html-unmodified`), slides 4 and 5 only: both slide JSONs are Keynote's
# bytes verbatim, and the header is trimmed to the two slides like `minimal_alpha_dsk/`'s.
# Keynote wrote exactly one key for the loop, `movie.loopMode: "looping"`, on each slide's one
# `untitled.mov` instance; S4 -> S5 is the same Magic Move pin as the non-looping deck.

NOT_YET_QUALIFIED = "deck shape is not yet qualified for continuity (only P2-measured plans are)"
LOOP_S4_TO_S5_REASON = (
    "'untitled.mov' does not loop on every instance at player index 0 -> 1; "
    "a carried decoder keeps its source's loop setting"
)
LOOP_S4_TO_S5_LOOPS = [
    {"scene": 0, "asset": "untitled.mov", "rect": {"x": 327, "y": 698, "w": 1266, "h": 356}},
    {"scene": 2, "asset": "untitled.mov", "rect": {"x": 327, "y": 698, "w": 1266, "h": 356}},
]


def _signed_runtime(monkeypatch, plan: ContinuityPlan) -> tuple[dict | Unsupported, dict]:
    """`to_runtime()` and the runtime dict it signed (withheld when unqualified)."""
    signed: list[dict] = []
    real_signature = live_continuity.plan_signature

    def recording(runtime):
        signed.append(copy.deepcopy(runtime))
        return real_signature(runtime)

    monkeypatch.setattr(live_continuity, "plan_signature", recording)
    result = plan.to_runtime()
    monkeypatch.setattr(live_continuity, "plan_signature", real_signature)
    assert len(signed) == 1, signed
    return result, signed[0]


def _drop_loop_mode(tmp_path: Path, uuid: str) -> Path:
    root = tmp_path / "loop"
    shutil.copytree(LOOP_ROOT, root)
    path = root / "assets" / uuid / f"{uuid}.json"
    raw = path.read_text()
    assert raw.count('"loopMode":"looping"') == 1
    path.write_text(raw.replace(',"loopMode":"looping"', "", 1))
    assert "loopMode" not in path.read_text()
    return root


def test_loop_fixture_is_keynotes_one_key_per_slide():
    for uuid in LOOP_UUIDS:
        raw = (LOOP_ROOT / "assets" / uuid / f"{uuid}.json").read_text()
        assert raw.count("loopMode") == 1
        assert raw.count('"loopMode":"looping"') == 1


def test_loop_s4_to_s5_pins_with_no_refusal_and_signs_a_two_entry_annex(monkeypatch):
    """L0-a: both sides loop, so the pin carries exactly as the non-looping deck's does; the
    runtime gains `loops` (one entry per slide) and stays unqualified."""
    plan = _plan(LOOP_ROOT, LOOP_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()
    movies = plan.boundaries[0].as_dict()["movies"]
    assert [m["action"] for m in movies] == ["pin"]
    result, runtime = _signed_runtime(monkeypatch, plan)
    assert result == Unsupported(NOT_YET_QUALIFIED)
    assert runtime["loops"] == LOOP_S4_TO_S5_LOOPS


def test_loop_s4_to_s5_as_dict_matches_the_non_looping_deck(monkeypatch):
    """Everything but the annex is the non-looping export's plan (plan F1: the loop is the only
    difference on these two slides)."""
    looping = _plan(LOOP_ROOT, LOOP_UUIDS)
    plain = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[0:2])
    assert isinstance(looping, ContinuityPlan)
    assert isinstance(plain, ContinuityPlan)
    assert looping.as_dict() == plain.as_dict()
    assert plain.loop_instances == {}
    _, looping_runtime = _signed_runtime(monkeypatch, looping)
    _, plain_runtime = _signed_runtime(monkeypatch, plain)
    assert "loops" not in plain_runtime
    assert {k: v for k, v in looping_runtime.items() if k != "loops"} == plain_runtime


@pytest.mark.parametrize("dropped", [0, 1], ids=["S4-plain", "S5-plain"])
def test_loop_removed_on_one_side_refuses_the_pin(tmp_path, monkeypatch, dropped):
    """L0-b: a loop difference across the Magic Move refuses that boundary (plan section 2.2);
    the refused pin becomes the single `retire`, and the remaining looping slide still signs."""
    root = _drop_loop_mode(tmp_path, LOOP_UUIDS[dropped])
    plan = _plan(root, LOOP_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    [refusal] = plan.refusals
    assert refusal["reason"] == LOOP_S4_TO_S5_REASON
    assert set(refusal) == {"fromPlayer", "toPlayer", "atScene", "asset", "movieKey", "reason"}
    result, runtime = _signed_runtime(monkeypatch, plan)
    assert result == Unsupported(NOT_YET_QUALIFIED)
    assert runtime["boundaries"] == [{"atScene": 2, "action": "retire", "movieKey": "movie1"}]
    assert runtime["loops"] == [LOOP_S4_TO_S5_LOOPS[1 - dropped]]


def test_loop_removed_on_one_side_flag_on_names_the_loop_reason(tmp_path):
    root = _drop_loop_mode(tmp_path, LOOP_UUIDS[1])
    plan = derive_plan(root, _slides(LOOP_UUIDS), resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].as_dict()["movies"][0]
    assert movie["glReplay"] is False
    assert movie["glReplayReason"] == LOOP_S4_TO_S5_REASON
    [refusal] = plan.refusals
    assert refusal["glReplay"] is False
    assert refusal["glReplayReason"] == LOOP_S4_TO_S5_REASON


@pytest.mark.skipif(not SOAK_LOOP_REAL_ROOT.is_dir(), reason="owner loop export not available")
def test_loop_fixture_is_the_owner_exports_bytes():
    for uuid in LOOP_UUIDS:
        relative = Path("assets") / uuid / f"{uuid}.json"
        assert (LOOP_ROOT / relative).read_bytes() == (SOAK_LOOP_REAL_ROOT / relative).read_bytes()
    assert _slide_list(SOAK_LOOP_REAL_ROOT)[3:5] == LOOP_UUIDS


@pytest.mark.skipif(not SOAK_LOOP_REAL_ROOT.is_dir(), reason="owner loop export not available")
def test_loop_fixture_parity_with_the_owner_export_slice(monkeypatch):
    """L0-e: the committed slice derives exactly what the owner's export derives for S4-S5."""
    real = _plan(SOAK_LOOP_REAL_ROOT, LOOP_UUIDS)
    fixture = _plan(LOOP_ROOT, LOOP_UUIDS)
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.as_dict() == fixture.as_dict()
    assert real.loop_instances == fixture.loop_instances
    real_result, real_runtime = _signed_runtime(monkeypatch, real)
    fixture_result, fixture_runtime = _signed_runtime(monkeypatch, fixture)
    assert real_result == fixture_result == Unsupported(NOT_YET_QUALIFIED)
    assert real_runtime == fixture_runtime


@pytest.mark.skipif(not SOAK_LOOP_REAL_ROOT.is_dir(), reason="owner loop export not available")
def test_the_whole_owner_loop_export_is_still_ambiguous():
    """L0-e / plan F4: accepting `loopMode` gets the owner's deck past the vocabulary, but the
    9-slide deck still stops at the same ownership ambiguity as the non-looping gl-decks export,
    so it cannot be a gate fixture."""
    plan = _plan(SOAK_LOOP_REAL_ROOT, _slide_list(SOAK_LOOP_REAL_ROOT))
    assert plan == Unsupported(
        "ambiguous 'untitled.mov' ownership at player index 7 -> 8: "
        "2 instance(s) before, 2 after, 4 geometry-equal pair(s)"
    )


@pytest.mark.skipif(
    not (SOAK_LOOP_REAL_ROOT.is_dir() and GL_DECKS_ROOT.is_dir()),
    reason="owner loop export or gl-deck exports not available",
)
def test_owner_loop_export_differs_from_the_plain_export_only_by_loop_mode():
    """Plan F1 on the committed slides: strip `loopMode` and each is the non-looping export."""

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k != "loopMode"}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    for uuid in LOOP_UUIDS:
        relative = Path("assets") / uuid / f"{uuid}.json"
        looping = json.loads((SOAK_LOOP_REAL_ROOT / relative).read_text())
        plain = json.loads((MINIMAL_REAL_ROOT / relative).read_text())
        assert looping != plain
        assert strip(looping) == plain
