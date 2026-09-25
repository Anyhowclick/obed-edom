from __future__ import annotations

import copy
import json
import shutil
from dataclasses import replace
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


NOT_YET_QUALIFIED = "deck shape is not yet qualified for continuity (only gate-measured plans are)"

MINIMAL_UUIDS = _slide_list(MINIMAL_ROOT)
POSITIVE_UUIDS = _slide_list(POSITIVE_ROOT)
LOOP_UUIDS = _slide_list(LOOP_ROOT)


def test_minimal_s4_to_s5_pins_with_no_refusal():
    plan = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[0:2])
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()
    movies = plan.boundaries[0].as_dict()["movies"]
    assert [m["action"] for m in movies] == ["pin"]
    assert plan.to_runtime() == Unsupported(NOT_YET_QUALIFIED)


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
    assert plan.to_runtime() == Unsupported(NOT_YET_QUALIFIED)


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
def test_minimal_geometry_equal_pairings_refuse_only_their_boundary(slice_):
    """Two instances each side, each geometry-equal to both across the move: the best and
    runner-up pairings tie, so that boundary is refused (R1), not the deck."""
    start, end = slice_
    plan = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[start:end])
    assert isinstance(plan, ContinuityPlan)
    ambiguous = plan.boundaries[-2]
    assert [(m.action, m.code, m.dst_object_id) for m in ambiguous.movies] == [("retire", "R1", None)] * 2
    assert "differ by 0.0 px (margin 16 px)" in ambiguous.movies[0].refusal


def test_positive_control_actions_and_to_runtime():
    plan = _plan(POSITIVE_ROOT, POSITIVE_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    actions = [
        boundary.as_dict()["movies"][0]["action"]
        for boundary in plan.boundaries
        if boundary.as_dict()["movies"]
    ]
    assert actions == ["pin", "bridge", "restart", "restart"]
    assert plan.to_runtime() == Unsupported(NOT_YET_QUALIFIED)


@pytest.mark.skipif(not GL_DECKS_ROOT.is_dir(), reason="real gl-deck exports not available")
def test_minimal_fixture_parity_with_real_export():
    real = _plan(MINIMAL_REAL_ROOT, MINIMAL_UUIDS)
    fixture = _plan(MINIMAL_ROOT, MINIMAL_UUIDS)
    assert isinstance(real, ContinuityPlan)
    assert isinstance(fixture, ContinuityPlan)
    assert real.as_dict() == fixture.as_dict()


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

LOOP_S4_TO_S5_REASON = (
    "'untitled.mov' loops on one side of player index 0 -> 1 only; "
    "a carried decoder keeps its source's loop setting"
)


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


def test_loop_s4_to_s5_pins_with_no_refusal_and_a_looping_entry(monkeypatch):
    """L0-a: both sides loop, so the pin carries exactly as the non-looping deck's does, with
    `loop: true` on its entry; the runtime stays unqualified."""
    plan = _plan(LOOP_ROOT, LOOP_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    assert plan.refusals == ()
    movies = plan.boundaries[0].as_dict()["movies"]
    assert [(m["action"], m["loop"]) for m in movies] == [("pin", True)]
    result, runtime = _signed_runtime(monkeypatch, plan)
    assert result == Unsupported(NOT_YET_QUALIFIED)
    assert [(b["action"], b["loop"]) for b in runtime["boundaries"]] == [("pin", True)]


def test_loop_s4_to_s5_differs_from_the_non_looping_deck_only_in_loop(monkeypatch):
    """Plan F1: the loop is the only difference on these two slides."""
    looping = _plan(LOOP_ROOT, LOOP_UUIDS)
    plain = _plan(MINIMAL_ROOT, MINIMAL_UUIDS[0:2])
    assert isinstance(looping, ContinuityPlan)
    assert isinstance(plain, ContinuityPlan)
    assert looping.boundaries[0] == replace(
        plain.boundaries[0], movies=tuple(replace(m, loop=True) for m in plain.boundaries[0].movies)
    )
    assert plain.loop_instances == {}
    _, looping_runtime = _signed_runtime(monkeypatch, looping)
    _, plain_runtime = _signed_runtime(monkeypatch, plain)
    assert "loops" not in looping_runtime
    assert looping_runtime == {
        **plain_runtime, "boundaries": [{**b, "loop": True} for b in plain_runtime["boundaries"]],
    }


@pytest.mark.parametrize("dropped", [0, 1], ids=["S4-plain", "S5-plain"])
def test_loop_removed_on_one_side_refuses_the_pin(tmp_path, monkeypatch, dropped):
    """L0-b / R4: a loop difference across the carried pair refuses that boundary, which
    becomes a `retire` of the source instance."""
    root = _drop_loop_mode(tmp_path, LOOP_UUIDS[dropped])
    plan = _plan(root, LOOP_UUIDS)
    assert isinstance(plan, ContinuityPlan)
    [refusal] = plan.refusals
    assert (refusal["reason"], refusal["code"]) == (LOOP_S4_TO_S5_REASON, "R4")
    assert set(refusal) == {"fromPlayer", "toPlayer", "atScene", "asset", "movieKey", "reason", "code", "objectId"}
    result, runtime = _signed_runtime(monkeypatch, plan)
    assert result == Unsupported(NOT_YET_QUALIFIED)
    assert [(b["atScene"], b["action"], b["reason"]) for b in runtime["boundaries"]] == [(2, "retire", "refused")]
    assert runtime["boundaries"][0]["src"]["objectId"] == refusal["objectId"]


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
def test_the_whole_owner_loop_export_refuses_only_its_ambiguous_boundary():
    """L0-e / plan F4: the 9-slide deck's 8 -> 9 move pairs two geometry-equal instances each
    side, so that boundary alone is refused (R1); the deck still derives."""
    plan = _plan(SOAK_LOOP_REAL_ROOT, _slide_list(SOAK_LOOP_REAL_ROOT))
    assert isinstance(plan, ContinuityPlan)
    assert [(r["fromPlayer"], r["code"]) for r in plan.refusals if r["code"] == "R1"] == [(7, "R1"), (7, "R1")]


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


# --- S0 decks D1-D6 (generalisation plan section 5) ----------------------------------------
#
# `qual_decks/Dn/` holds each S0 export's header and slide JSONs verbatim (main checkout
# `output/fixtures/qual-decks/Dn/html-unmodified`); no movie files. D2-across derives exactly as
# D2 (the export does not encode play-across), so it has no committed copy. D1, D3 and D5 must
# derive the frozen schema-2 contract examples the core and injection streams test against.

QUAL_ROOT = Path(__file__).parent / "fixtures" / "live_continuity" / "qual_decks"
QUAL_REAL_ROOT = fixture("qual-decks")
RUNTIME_V2_EXAMPLES = json.loads((FIXTURE_ROOT / "runtime_v2_examples.json").read_text())
QUAL_PLAN_SHA256 = {
    "D1": "4d466b2f0ee035928486dc3e61f23a5d92e3cc4e76d5d02f367e115331cc0b00",
    "D2": "029a4c427d2f7ebe2cf7410e2010fdc03834f370f5c6d25aeea9e05c2fbc20f7",
    "D3": "01b74c88f4622e5a0650d334d7721a247a2039a1767f232d792e823405a21b1b",
    "D4": "e166c385753364cdc159307b8f7d9092979533b71aee93ea4b8ebbea7a366076",
    "D5": "73d1153f086381996b5490d6f66eae2ee6996eb05b4a1dcd0af0fce70a018f5e",
    "D6": "149e813cfe68b6bac7c5c4ea0b5829f20e017ee1d0ce742ece3444fd1f60eed1",
}


def _qual_plan(deck: str, *, gl_replay: bool = False, root: Path = QUAL_ROOT) -> ContinuityPlan:
    deck_root = root / deck if root is QUAL_ROOT else root / deck / "html-unmodified"
    plan = derive_plan(deck_root, _slides(_slide_list(deck_root)), resolver=_resolver, gl_replay=gl_replay)
    assert isinstance(plan, ContinuityPlan), plan
    return plan


def _qual_runtime(deck: str, **kwargs) -> dict:
    runtime = _qual_plan(deck, **kwargs).to_runtime()
    assert isinstance(runtime, dict), runtime
    return runtime


def _summary(runtime: dict) -> list[tuple]:
    return [
        (b["atScene"], b["action"], b["movieKey"], b["src"]["objectId"][:4], (b.get("dst") or {}).get("objectId", "")[:4])
        for b in runtime["boundaries"]
    ]


@pytest.mark.parametrize("deck", ["D1", "D3", "D5"])
@pytest.mark.parametrize("gl_replay", [False, True])
def test_s0_deck_derives_the_contract_example(deck, gl_replay):
    assert _qual_runtime(deck, gl_replay=gl_replay) == RUNTIME_V2_EXAMPLES[deck.lower()]


@pytest.mark.parametrize("deck", sorted(QUAL_PLAN_SHA256))
@pytest.mark.parametrize("gl_replay", [False, True])
def test_s0_deck_runtime_is_pinned_and_allowlisted(deck, gl_replay):
    runtime = _qual_runtime(deck, gl_replay=gl_replay)
    assert live_continuity.plan_signature(runtime) == QUAL_PLAN_SHA256[deck]
    assert QUAL_PLAN_SHA256[deck] in live_continuity.QUALIFIED_PLAN_SHA256


def test_d2_restarts_after_a_bridge_and_starts_a_new_chain():
    assert _summary(_qual_runtime("D2")) == [
        (2, "bridge", "movie1", "D4E3", "2935"),
        (4, "restart", "movie1", "2935", "DE43"),
        (6, "pin", "movie1", "DE43", "1D37"),
        (8, "bridge", "movie1", "1D37", "0815"),
    ]


def test_d4_the_far_instance_bridges_and_the_near_one_gets_no_entry():
    """A-far (centre distance ~266 px) pairs, not A-near (~994 px); A-near is uncarried, so the
    runtime never names it and plays it raw."""
    runtime = _qual_runtime("D4")
    assert _summary(runtime) == [
        (3, "bridge", "movie1", "254E", "9E04"),
        (5, "pin", "movie1", "9E04", "E839"),
    ]
    assert "072763EA-8E68-4E62-9855-2BAEF215572B" not in json.dumps(runtime)


def test_d6_loops_through_the_chain_and_retires_the_loop_mismatch():
    plan = _qual_plan("D6")
    runtime = plan.to_runtime()
    assert isinstance(runtime, dict)
    assert _summary(runtime) == [
        (2, "bridge", "movie1", "41D0", "8A80"),
        (4, "bridge", "movie1", "8A80", "B275"),
        (6, "pin", "movie1", "B275", "4478"),
        (8, "retire", "movie1", "4478", ""),
    ]
    assert [b.get("loop") for b in runtime["boundaries"]] == [True, True, True, None]
    assert runtime["boundaries"][-1]["reason"] == "refused"
    assert [(r["atScene"], r["code"]) for r in plan.refusals] == [(8, "R4")]
    assert "70E3E894-8770-4892-B203-870BDB4E665C" not in json.dumps(runtime)


def test_d3_ends_the_movie_that_does_not_continue():
    plan = _qual_plan("D3")
    ends = [m for b in plan.boundaries for m in b.movies if m.action == "retire"]
    assert [(m.asset, m.refusal, m.dst_rect) for m in ends] == [("counter-a.mov", None, None)]
    assert plan.refusals == ()


@pytest.mark.skipif(not QUAL_REAL_ROOT.is_dir(), reason="S0 deck exports not available")
@pytest.mark.parametrize("deck", sorted(QUAL_PLAN_SHA256))
def test_s0_deck_fixture_is_the_exports_bytes(deck):
    real = QUAL_REAL_ROOT / deck / "html-unmodified" / "assets"
    committed = QUAL_ROOT / deck / "assets"
    assert (committed / "header.json").read_bytes() == (real / "header.json").read_bytes()
    uuids = _slide_list(QUAL_ROOT / deck)
    assert sorted(p.name for p in committed.iterdir() if p.is_dir()) == sorted(uuids)
    for uuid in uuids:
        assert (committed / uuid / f"{uuid}.json").read_bytes() == (real / uuid / f"{uuid}.json").read_bytes()


@pytest.mark.skipif(not QUAL_REAL_ROOT.is_dir(), reason="S0 deck exports not available")
def test_d2_across_derives_exactly_as_d2():
    """The HTML export does not encode play-across-slides (plan section 5, S0 investigation)."""
    assert _qual_plan("D2-across", root=QUAL_REAL_ROOT).as_dict() == _qual_plan("D2").as_dict()


def test_d2_with_its_dissolve_exported_as_none_signs_the_same_plan(tmp_path):
    """A mid-deck `none` cut derives exactly as the Dissolve it replaces, so D2's allowlisted sha
    is unchanged (no S0 deck has a mid-deck `none`)."""
    root = tmp_path / "D2"
    shutil.copytree(QUAL_ROOT / "D2", root)
    slide2 = _slide_list(root)[1]
    path = root / "assets" / slide2 / f"{slide2}.json"
    raw = path.read_text()
    assert raw.count('"apple:dissolve"') == 1
    path.write_text(raw.replace('"apple:dissolve"', '"none"'))
    runtime = derive_plan(root, _slides(_slide_list(root)), resolver=_resolver).to_runtime()
    assert isinstance(runtime, dict)
    assert live_continuity.plan_signature(runtime) == QUAL_PLAN_SHA256["D2"]
