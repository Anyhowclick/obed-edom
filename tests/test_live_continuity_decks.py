from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_continuity"
MINIMAL_ROOT = FIXTURE_ROOT / "minimal_alpha_dsk"
POSITIVE_ROOT = FIXTURE_ROOT / "positive_control"

GL_DECKS_ROOT = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/gl-decks")
MINIMAL_REAL_ROOT = GL_DECKS_ROOT / "Minimal Alpha_DSK" / "html"
POSITIVE_REAL_ROOT = GL_DECKS_ROOT / "Positive Control" / "html"


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
    # (arming plan §11: only a refused pin is considered for glReplay).
    plan = derive_plan(MINIMAL_ROOT, _slides(MINIMAL_UUIDS[0:2]), resolver=_resolver, gl_replay=True)
    assert isinstance(plan, ContinuityPlan)
    movie = plan.boundaries[0].as_dict()["movies"][0]
    assert movie["glReplay"] is False
    assert movie["glReplayReason"] is None


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
