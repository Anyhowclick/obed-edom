"""Framing decisions survive a re-run, and only re-ask what changed.

The point of remembering a crop is not having to pick it twice. These tests pin
the three behaviours that make that true: a decision follows its page by content
rather than by position, a page whose content changed loses its answer, and a
deferred page is re-offered exactly when the template gains new framings.
"""

from pathlib import Path

from obed_edom.framing import (
    AUTO,
    DEFERRED,
    PINNED,
    Decision,
    load_framings,
    normalize_decision,
    reuse_framings,
    save_framings,
)

WALL = "/tmp/Wall.key"
TEMPLATE = "/tmp/Base_CG_Assets.key"


def test_round_trip(tmp_path: Path):
    save_framings(
        WALL,
        TEMPLATE,
        ["a", "b", "c"],
        "tmpl-1",
        [Decision(0, PINNED, 7), Decision(2, DEFERRED)],
        root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    assert record is not None
    assert record["templateDigest"] == "tmpl-1"
    assert [row["wallIndex"] for row in record["decisions"]] == [0, 2]


def test_auto_is_not_stored(tmp_path: Path):
    """Auto means unanswered. Storing it would make 'already answered' a lie."""
    save_framings(
        WALL, TEMPLATE, ["a", "b"], "t", [Decision(0, AUTO), Decision(1, PINNED, 3)], root=tmp_path
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    assert record is not None
    assert [row["wallIndex"] for row in record["decisions"]] == [1]


def test_decision_follows_its_page_when_slides_are_inserted(tmp_path: Path):
    save_framings(WALL, TEMPLATE, ["a", "b", "c"], "t", [Decision(2, PINNED, 5)], root=tmp_path)
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    # A new slide lands at the front, so the answered page is now index 3.
    reuse = reuse_framings(record, ["new", "a", "b", "c"], "t")
    assert reuse.carried == 1
    assert reuse.dropped == 0
    assert reuse.decisions[3].template_slide == 5
    assert reuse.overrides() == {4: 5}


def test_a_changed_page_loses_its_answer(tmp_path: Path):
    """The crop was chosen for the old content, so it should not be assumed."""
    save_framings(WALL, TEMPLATE, ["a", "b"], "t", [Decision(1, PINNED, 5)], root=tmp_path)
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a", "edited"], "t")
    assert reuse.carried == 0
    assert reuse.dropped == 1
    assert reuse.overrides() == {}


def test_deferred_pages_resurface_only_when_the_template_changes(tmp_path: Path):
    save_framings(
        WALL,
        TEMPLATE,
        ["a", "b"],
        "tmpl-1",
        [Decision(0, DEFERRED), Decision(1, PINNED, 2)],
        root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)

    same = reuse_framings(record, ["a", "b"], "tmpl-1")
    assert same.template_changed is False
    assert same.resurfaced == []

    changed = reuse_framings(record, ["a", "b"], "tmpl-2")
    assert changed.template_changed is True
    # Only the deferred page: the pinned one was answered and stays answered.
    assert changed.resurfaced == [0]
    assert changed.decisions[0].state == DEFERRED


def test_deferred_and_auto_do_not_pin_anything(tmp_path: Path):
    """Both mean 'let the planner choose', so neither becomes an override."""
    save_framings(
        WALL, TEMPLATE, ["a", "b"], "t", [Decision(0, DEFERRED), Decision(1, PINNED, 4)], root=tmp_path
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a", "b"], "t")
    assert reuse.overrides() == {2: 4}


def test_a_pin_with_no_slide_is_rejected(tmp_path: Path):
    assert normalize_decision({"wallIndex": 1, "state": PINNED}) is None
    assert normalize_decision({"wallIndex": 1, "state": "nonsense"}) is None
    assert normalize_decision({"state": PINNED, "templateSlide": 2}) is None


def test_no_record_is_not_an_error(tmp_path: Path):
    assert load_framings(WALL, TEMPLATE, root=tmp_path) is None
    reuse = reuse_framings(None, ["a"], "t")
    assert reuse.overrides() == {}
    assert reuse.carried == 0
