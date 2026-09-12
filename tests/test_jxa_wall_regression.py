"""Real-payload regression for the Gold slide 2 badge collapse.

Unlike the synthetic `test_map_remap.py` cases (which hand-set `groupAutosize`
and `groupChildrenUnavailable` on a literal slide dict), this drives the real
`remap_keynote()` entry point over a real cached jxa payload -- the two links
that actually broke in production were `attach_group_autosize` composed with
`prepare_wall_payload`'s reader gate, and the writer's tolerance of a spec with
no `w`/`h`, neither of which a hand-built dict exercises.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from scripts import golden_plan  # noqa: E402

from obed_edom import baseline, remap_keynote  # noqa: E402
from obed_edom.offline_inspect import offline_wall_payload  # noqa: E402

DECKS = golden_plan.DECKS
SOURCE_DECK = DECKS / "Gold_Wall_Input.key"
TEMPLATE_DECK = DECKS / "Base_CG_Assets.key"
FIXTURE = Path(__file__).parent / "fixtures" / "jxa-wall" / "gold_slide2_badges.json"
GOLDEN_GOLD_WALL = golden_plan.golden_path("Gold_Wall_Input.key")


def _skip_unless_gold_deck_matches() -> None:
    if not SOURCE_DECK.exists():
        pytest.skip(f"deck missing: {SOURCE_DECK}")
    if not TEMPLATE_DECK.exists():
        pytest.skip(f"template missing: {TEMPLATE_DECK}")
    if not GOLDEN_GOLD_WALL.exists():
        pytest.skip(f"golden fixture missing: {GOLDEN_GOLD_WALL}")
    golden = json.loads(GOLDEN_GOLD_WALL.read_text())
    source_digest = baseline.deck_digest(SOURCE_DECK)
    template_digest = baseline.deck_digest(TEMPLATE_DECK)
    if source_digest != golden.get("sourceDigest") or template_digest != golden.get("templateDigest"):
        pytest.skip(
            f"deck/template digest drift (source {source_digest} vs {golden.get('sourceDigest')}, "
            f"template {template_digest} vs {golden.get('templateDigest')}); attach_group_autosize "
            "needs the real Gold archive to match this fixture's kindIndex layout"
        )


def test_jxa_wall_slide2_badges_refuse_size_end_to_end():
    """b390466's planner wrote w=278, h=88 on both slide-2 badge groups; the fix
    must refuse both, deck-wide, with statJobs faithfully reporting s=1.0."""
    _skip_unless_gold_deck_matches()

    fixture = json.loads(FIXTURE.read_text())
    tmpl = offline_wall_payload(TEMPLATE_DECK)
    out: dict = {}
    dest = SOURCE_DECK.parent / "never-written.key"

    with golden_plan._pinned_env(), golden_plan._keynote_free():
        try:
            remap_keynote.remap_keynote(
                SOURCE_DECK,
                dest,
                template=TEMPLATE_DECK,
                wall_payload=fixture,
                template_payload=tmpl,
                plan_out=out,
                log=lambda _m: None,
            )
        except golden_plan._PlanCaptured:
            pass
        else:
            pytest.fail("plan capture did not reach _run_jxa")

    transforms = [
        t for t in out["transforms"] if t.get("slide") == 2 and t.get("kind") == "group"
    ]
    assert len(transforms) == 2
    for t in transforms:
        assert "w" not in t and "h" not in t
        assert t["sizeRefused"] == "group-children-unavailable"
        assert "children" not in t

    stat_rows = [r for r in out["statJobs"] if r.get("slide") == 2]
    assert len(stat_rows) == 2
    for row in stat_rows:
        assert row["s"] == 1.0
