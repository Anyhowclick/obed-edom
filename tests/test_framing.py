"""Framing decisions survive a re-run, and only re-ask what changed.

The point of remembering a crop is not having to pick it twice. These tests pin
the three behaviours that make that true: a decision follows its page by content
rather than by position, a page whose content changed loses its answer, and a
deferred page is re-offered exactly when the template gains new framings.

States are explicit, not packed into pairing leftIndex/rightIndexes:
- auto: unanswered; the planner picks.
- pinned: the operator chose this template slide's framing.
- deferred: no framing here is right; the page still plans (fit-to-frame) and
  is re-offered when the template digest changes, because that is when new
  framings may have appeared.
"""

from pathlib import Path

from obed_edom.framing import (
    AUTO,
    DEFERRED,
    PINNED,
    Decision,
    _transform_of,
    load_framings,
    normalize_decision,
    planned_rects,
    reuse_framings,
    save_framings,
    template_framing_digests,
)
from obed_edom.map_remap import FramingContext, ItemTransform, Plan, Rect, frame_affine

WALL = "/tmp/Wall.key"
TEMPLATE = "/tmp/Base_CG_Assets.key"


def _plan(**overrides) -> Plan:
    defaults = dict(
        transforms=[], placements=[], skipped_slides=[], fitted_slides=[],
        offframe=[], framing=[], child_resize=[], badge_raises=[], card_grid=[],
        roster={},
    )
    defaults.update(overrides)
    return Plan(**defaults)


def _img_slide(number: int, x: float, y: float, w: float, h: float, name: str = "pic.png") -> dict:
    return {
        "number": number,
        "items": [{"kind": "image", "fileName": name, "x": x, "y": y, "w": w, "h": h}],
    }


def _tmpl_digests(*slides: dict) -> list[str]:
    return template_framing_digests({"slides": list(slides)})


def _image(name: str, x: float, y: float, w: float, h: float) -> dict:
    return {"kind": "image", "fileName": name, "x": x, "y": y, "w": w, "h": h}


def _text(text: str, x: float, y: float, w: float, h: float) -> dict:
    return {"kind": "text", "text": text, "x": x, "y": y, "w": w, "h": h}


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
    assert same.decisions[1].template_slide == 2

    # This record predates templateDigests, so once the template changes the saved
    # pin's number is untrustworthy and is dropped, not carried "stays answered".
    changed = reuse_framings(record, ["a", "b"], "tmpl-2")
    assert changed.template_changed is True
    assert changed.resurfaced == [0]
    assert changed.decisions[0].state == DEFERRED
    assert 1 not in changed.decisions
    assert changed.dropped == 1


def test_deferred_and_auto_do_not_pin_anything(tmp_path: Path):
    """Both mean 'let the planner choose', so neither becomes an override."""
    save_framings(
        WALL, TEMPLATE, ["a", "b"], "t", [Decision(0, DEFERRED), Decision(1, PINNED, 4)], root=tmp_path
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a", "b"], "t")
    assert reuse.overrides() == {2: 4}


def test_template_framing_digest_is_stable_under_sub_bucket_jitter():
    """Sub-pixel float jitter that stays within the same 0.5px bucket must not change
    the digest. (A jitter that straddles a bucket edge is a separate, accepted
    refusal case -- not claimed stable here.)"""
    steady = _tmpl_digests(_img_slide(1, 100.10, 100.10, 400.10, 300.10))
    jittered = _tmpl_digests(_img_slide(1, 100.12, 100.08, 400.11, 300.09))
    assert steady == jittered


def test_template_framing_digest_is_insensitive_to_item_order():
    """Keynote can reorder items within a kind on save with nothing else changed
    (see iwa_zorder.py); the same slide with its items listed in a different order
    must produce the same digest."""
    slide = {
        "number": 1,
        "items": [
            {"kind": "image", "fileName": "a.png", "x": 0, "y": 0, "w": 50, "h": 50},
            {"kind": "image", "fileName": "b.png", "x": 200, "y": 0, "w": 60, "h": 60},
        ],
    }
    reordered = {
        "number": 1,
        "items": list(reversed(slide["items"])),
    }
    assert template_framing_digests({"slides": [slide]}) == template_framing_digests(
        {"slides": [reordered]}
    )


def test_template_framing_digest_is_insensitive_to_text_item_order():
    """Two unchanged top-level text items listed in reversed order must not change
    the digest -- text comes from the item itself, not a payload-ordered traversal."""
    slide = {
        "number": 1,
        "items": [
            _text("Left caption", 0, 0, 50, 50),
            _text("Right caption", 200, 0, 60, 60),
        ],
    }
    reordered = {"number": 1, "items": list(reversed(slide["items"]))}
    assert template_framing_digests({"slides": [slide]}) == template_framing_digests(
        {"slides": [reordered]}
    )


def test_template_framing_digest_ignores_group_children():
    """Group-child inspection is best-effort and can silently come back empty between
    runs with the group itself unchanged; only top-level items count -- with a group
    that has neither, a text, nor an image child."""
    def _group(children: list[dict]) -> dict:
        return {"number": 1, "items": [{"kind": "group", "x": 0, "y": 0, "w": 300, "h": 200, "children": children}]}

    no_children = template_framing_digests({"slides": [_group([])]})
    with_shape_child = template_framing_digests(
        {"slides": [_group([{"kind": "shape", "x": 10, "y": 10, "w": 50, "h": 50}])]}
    )
    with_text_child = template_framing_digests(
        {"slides": [_group([_text("caption", 10, 10, 50, 50)])]}
    )
    with_image_child = template_framing_digests(
        {"slides": [_group([_image("c.png", 10, 10, 50, 50)])]}
    )
    assert no_children == with_shape_child == with_text_child == with_image_child


def test_template_framing_digest_changes_when_two_images_swap_positions(tmp_path: Path):
    """Content identity and position are tokenized together, not as independent
    multisets: a.png-left/b.png-right must differ from the swap, and a saved pin
    for the original arrangement must not be carried onto the swapped one."""
    original = {"number": 1, "items": [_image("a.png", 0, 0, 50, 50), _image("b.png", 200, 0, 60, 60)]}
    swapped = {"number": 1, "items": [_image("a.png", 200, 0, 60, 60), _image("b.png", 0, 0, 50, 50)]}
    original_digest = template_framing_digests({"slides": [original]})
    swapped_digest = template_framing_digests({"slides": [swapped]})
    assert original_digest != swapped_digest

    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 1)],
        template_digests=original_digest, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a"], "t2", swapped_digest)
    assert reuse.dropped == 1
    assert reuse.decisions == {}

    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 1, keep_side_content=True)],
        template_digests=original_digest, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a"], "t2", swapped_digest)
    assert reuse.dropped == 0
    assert reuse.unpinned == 1
    assert reuse.decisions[0].template_slide is None
    assert reuse.decisions[0].keep_side_content is True


def test_template_framing_digest_changes_when_two_movies_swap_positions(tmp_path: Path):
    """Movies are paired into the learned recipe like images, so their filename is
    identity too: a.mov/b.mov swapping frames must change the digest and drop the pin."""
    def movie(name: str, x: float, y: float, w: float, h: float) -> dict:
        return {"kind": "movie", "fileName": name, "x": x, "y": y, "w": w, "h": h}

    original = {"number": 1, "items": [movie("a.mov", 0, 0, 50, 50), movie("b.mov", 200, 0, 60, 60)]}
    swapped = {"number": 1, "items": [movie("a.mov", 200, 0, 60, 60), movie("b.mov", 0, 0, 50, 50)]}
    original_digest = template_framing_digests({"slides": [original]})
    swapped_digest = template_framing_digests({"slides": [swapped]})
    assert original_digest != swapped_digest

    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 1)],
        template_digests=original_digest, root=tmp_path,
    )
    reuse = reuse_framings(load_framings(WALL, TEMPLATE, root=tmp_path), ["a"], "t2", swapped_digest)
    assert reuse.dropped == 1 and reuse.decisions == {}


def test_template_framing_digest_changes_when_two_text_items_swap_positions():
    original = {"number": 1, "items": [_text("Left caption", 0, 0, 50, 50), _text("Right caption", 200, 0, 60, 60)]}
    swapped = {"number": 1, "items": [_text("Left caption", 200, 0, 60, 60), _text("Right caption", 0, 0, 50, 50)]}
    assert template_framing_digests({"slides": [original]}) != template_framing_digests({"slides": [swapped]})


def test_template_framing_digest_is_geometry_sensitive():
    """Same text and image identity, moved -- the digest must differ; this is the
    framing itself, unlike the geometry-blind wall digest."""
    moved = _tmpl_digests(_img_slide(1, 100, 100, 400, 300), _img_slide(2, 0, 0, 500, 500))
    original = _tmpl_digests(_img_slide(1, 100, 100, 400, 300), _img_slide(2, 10, 10, 500, 500))
    assert moved[0] == original[0]
    assert moved[1] != original[1]


def test_pinned_template_slide_follows_an_insertion(tmp_path: Path):
    """A new slide lands before the pinned template page, so its number moves too."""
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 2)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(
        _img_slide(1, 500, 500, 50, 50), _img_slide(2, 0, 0, 100, 100), _img_slide(3, 200, 0, 100, 100)
    )
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.template_changed is True
    assert reuse.dropped == 0
    assert reuse.decisions[0].template_slide == 3


def test_pinned_template_slide_dropped_when_deleted(tmp_path: Path):
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 2)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(_img_slide(1, 0, 0, 100, 100))
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.template_changed is True
    assert reuse.dropped == 1
    assert reuse.decisions == {}


def test_pinned_template_slide_dropped_when_its_content_changed(tmp_path: Path):
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 2)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 250, 0, 100, 100))
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.dropped == 1
    assert reuse.decisions == {}


def test_pinned_template_slide_follows_a_reorder(tmp_path: Path):
    saved = _tmpl_digests(
        _img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100), _img_slide(3, 400, 0, 100, 100)
    )
    save_framings(
        WALL, TEMPLATE, ["a", "b"], "t1",
        [Decision(0, PINNED, 1), Decision(1, PINNED, 3)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(
        _img_slide(1, 400, 0, 100, 100), _img_slide(2, 0, 0, 100, 100), _img_slide(3, 200, 0, 100, 100)
    )
    reuse = reuse_framings(record, ["a", "b"], "t2", current)
    assert reuse.dropped == 0
    assert reuse.decisions[0].template_slide == 2
    assert reuse.decisions[1].template_slide == 1


def test_legacy_record_without_template_digests_drops_pins_on_template_change(tmp_path: Path):
    """No templateDigests means the old numbers are untrustworthy once the template moved."""
    save_framings(WALL, TEMPLATE, ["a", "b"], "t1", [Decision(0, PINNED, 2), Decision(1, DEFERRED)], root=tmp_path)
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    assert "templateDigests" not in record or not record["templateDigests"]
    current = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    reuse = reuse_framings(record, ["a", "b"], "t2", current)
    assert reuse.template_changed is True
    assert reuse.dropped == 1
    assert 0 not in reuse.decisions
    assert reuse.decisions[1].state == DEFERRED


def test_legacy_record_with_kept_side_content_survives_unpinned(tmp_path: Path):
    """A legacy pinned decision that also whitelists side content must not lose that
    answer just because its (untrustworthy) template number cannot be trusted."""
    save_framings(
        WALL, TEMPLATE, ["a"], "t1",
        [Decision(0, PINNED, 2, keep_side_content=True)], root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.dropped == 0
    assert reuse.unpinned == 1
    # Unpinned is not "carried" -- the pinned answer did not survive, only the
    # independent side-content whitelist did.
    assert reuse.carried == 0
    assert reuse.decisions[0].state == AUTO
    assert reuse.decisions[0].template_slide is None
    assert reuse.decisions[0].keep_side_content is True
    assert reuse.side_content_slides() == {1}


def test_legacy_record_without_template_digests_is_unaffected_when_template_unchanged(tmp_path: Path):
    save_framings(WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 2)], root=tmp_path)
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["a"], "t1")
    assert reuse.template_changed is False
    assert reuse.dropped == 0
    assert reuse.decisions[0].template_slide == 2


def test_ambiguous_template_digest_drops_the_pin_never_mispins(tmp_path: Path):
    """Two slides share a digest in the saved record: the pin cannot be trusted
    even though the identical-looking pair is still there in the current template."""
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 0, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 1)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 0, 0, 100, 100))
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.template_changed is True
    assert reuse.dropped == 1
    assert reuse.decisions == {}


def test_ambiguous_template_digest_with_a_front_insertion_never_mispins(tmp_path: Path):
    """Codex's exact case: ["dup", "dup"] -> ["dup", "dup", "dup"] with the insertion at
    the front. A positional (SequenceMatcher) map would silently shift the pin by one;
    identity matching must refuse it instead, because the digest is not unique."""
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 0, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 1)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    current = _tmpl_digests(
        _img_slide(1, 500, 500, 20, 20), _img_slide(2, 0, 0, 100, 100), _img_slide(3, 0, 0, 100, 100)
    )
    reuse = reuse_framings(record, ["a"], "t2", current)
    assert reuse.template_changed is True
    assert reuse.dropped == 1
    assert reuse.decisions == {}


def test_save_load_reuse_round_trip_includes_template_digests(tmp_path: Path):
    saved = _tmpl_digests(_img_slide(1, 0, 0, 100, 100), _img_slide(2, 200, 0, 100, 100))
    save_framings(
        WALL, TEMPLATE, ["a"], "t1", [Decision(0, PINNED, 2)],
        template_digests=saved, root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    assert record is not None
    assert record["templateDigests"] == saved
    reuse = reuse_framings(record, ["a"], "t1", saved)
    assert reuse.template_changed is False
    assert reuse.decisions[0].template_slide == 2


def test_a_pin_with_no_slide_is_rejected(tmp_path: Path):
    assert normalize_decision({"wallIndex": 1, "state": PINNED}) is None
    assert normalize_decision({"wallIndex": 1, "state": "nonsense"}) is None
    assert normalize_decision({"state": PINNED, "templateSlide": 2}) is None


def test_no_record_is_not_an_error(tmp_path: Path):
    assert load_framings(WALL, TEMPLATE, root=tmp_path) is None
    reuse = reuse_framings(None, ["a"], "t")
    assert reuse.overrides() == {}
    assert reuse.carried == 0


def test_an_auto_page_kept_for_side_content_is_stored(tmp_path: Path):
    """Side content is whitelisted independently of framing, so an auto page that
    keeps its side content is a real decision and must not be dropped as unanswered."""
    save_framings(
        WALL,
        TEMPLATE,
        ["a", "b"],
        "t",
        [Decision(0, AUTO), Decision(1, AUTO, keep_side_content=True)],
        root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    assert record is not None
    assert [row["wallIndex"] for row in record["decisions"]] == [1]
    assert record["decisions"][0]["keepSideContent"] is True
    # A plain page emits no keepSideContent key, keeping the record lean.
    assert "keepSideContent" not in Decision(0, PINNED, 7).as_dict()


def test_side_content_whitelist_follows_its_page_and_maps_to_numbers(tmp_path: Path):
    """The whitelist rides a re-run by content digest like a pin, and surfaces as
    wall slide *numbers* (index + 1) for the planner."""
    save_framings(
        WALL,
        TEMPLATE,
        ["a", "b", "c"],
        "t",
        [Decision(2, AUTO, keep_side_content=True)],
        root=tmp_path,
    )
    record = load_framings(WALL, TEMPLATE, root=tmp_path)
    reuse = reuse_framings(record, ["new", "a", "b", "c"], "t")
    # index 2 ("c") shifted to index 3; kept and still whitelisted.
    assert reuse.decisions[3].keep_side_content is True
    assert reuse.side_content_slides() == {4}
    assert normalize_decision({"wallIndex": 5, "state": AUTO, "keepSideContent": True}).keep_side_content is True


def test_proposal_uses_full_wall_context_for_digests_navigator_and_thumbnails(tmp_path, monkeypatch):
    import obed_edom.baseline as baseline_mod
    import obed_edom.framing as framing_mod
    import obed_edom.map_remap as remap_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    full_wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": []},
            {"number": 2, "skipped": True, "items": []},
            {"number": 3, "items": []},
        ],
    }
    subset = {**full_wall, "slides": [full_wall["slides"][2]]}
    seen = {}

    def fake_plan(payload, _recipe, **kwargs):
        numbers = [slide["number"] for slide in payload["slides"]]
        return _plan(
            framing=[{"slide": n, "templateSlide": 1, "fitted": False} for n in numbers],
            framing_recipes={n: {"destWidth": 1920, "destHeight": 1080} for n in numbers},
            framing_context={n: FramingContext() for n in numbers},
        )

    def fake_thumbs(deck, payload, **_kwargs):
        if Path(deck) == wall:
            seen["wall_thumb_payload"] = payload
            return {slide["number"]: f"{slide['number']}.jpg" for slide in payload["slides"]}
        return {}

    monkeypatch.setattr(framing_mod, "build_preview_thumbs", fake_thumbs)
    monkeypatch.setattr(baseline_mod, "deck_digest", lambda _path: "deck")
    monkeypatch.setattr(
        baseline_mod,
        "deck_slide_digests",
        lambda payload: [f"d{slide['number']}" for slide in payload["slides"]],
    )
    monkeypatch.setattr(baseline_mod, "wall_thumb_dir", lambda _digest: tmp_path / "thumbs")
    monkeypatch.setattr(remap_mod, "learn_recipe", lambda *_args, **_kwargs: {"destWidth": 1920, "destHeight": 1080})
    monkeypatch.setattr(remap_mod, "plan_payload", fake_plan)
    monkeypatch.setattr(remap_mod, "rank_framing_candidates", lambda *_args, **_kwargs: [{"templateSlide": 1}])
    monkeypatch.setattr(remap_mod, "on_canvas_fraction", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(remap_mod, "is_degenerate_scale", lambda *_args, **_kwargs: False)

    result = framing_mod.propose_framings(
        wall,
        template,
        slide_range=frozenset({3}),
        wall_payload=subset,
        full_wall_payload=full_wall,
        template_payload={"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1}]},
    )

    assert [slide["number"] for slide in seen["wall_thumb_payload"]["slides"]] == [1, 2, 3]
    assert result["wallDigests"] == ["d1", "d2", "d3"]
    assert result["pages"] == [
        {
            "slide": 3,
            "index": 2,
            "thumb": "3.jpg",
            "autoTransform": None,
            "autoRects": [],
            "autoTemplateSlide": 1,
            "autoFellBack": False,
            "needsAttention": False,
            "noUsableFraming": False,
            "candidates": [
                {
                    "templateSlide": 1,
                    "wouldFallBack": False,
                    "pinOverridden": False,
                    "transform": None,
                    "rects": [],
                }
            ],
        }
    ]
    assert result["skippedSlides"] == [2]
    assert "Skip Slide" in result["numberingNote"]


def test_fallback_candidate_carries_text_and_card_context_onto_the_fit_recipe(tmp_path, monkeypatch):
    import obed_edom.baseline as baseline_mod
    import obed_edom.framing as framing_mod
    import obed_edom.map_remap as remap_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")
    full_wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    trial_recipe = {
        "destWidth": 1920, "destHeight": 1080,
        "listFontSize": 42, "cardSamples": [{"w": 1}],
    }
    captured: list[dict] = []

    def fake_plan(payload, _recipe, **kwargs):
        return _plan(
            framing=[{"slide": 1, "templateSlide": 1, "fitted": True}],
            framing_recipes={1: {"destWidth": 1920, "destHeight": 1080}},
            framing_context={1: FramingContext()},
        )

    def fake_planned_rects(_slide, recipe, **_kwargs):
        captured.append(recipe)
        return []

    monkeypatch.setattr(baseline_mod, "deck_digest", lambda _path: "deck")
    monkeypatch.setattr(baseline_mod, "deck_slide_digests", lambda _payload: ["d1"])
    monkeypatch.setattr(baseline_mod, "wall_thumb_dir", lambda _digest: tmp_path / "thumbs")
    monkeypatch.setattr(framing_mod, "build_preview_thumbs", lambda *_a, **_k: {})
    monkeypatch.setattr(framing_mod, "planned_rects", fake_planned_rects)
    monkeypatch.setattr(remap_mod, "learn_recipe", lambda *_a, **_k: dict(trial_recipe))
    monkeypatch.setattr(remap_mod, "plan_payload", fake_plan)
    monkeypatch.setattr(remap_mod, "rank_framing_candidates", lambda *_a, **_k: [{"templateSlide": 1}])
    monkeypatch.setattr(remap_mod, "on_canvas_fraction", lambda *_a, **_k: 0.0)
    monkeypatch.setattr(remap_mod, "is_degenerate_scale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        remap_mod,
        "fit_to_frame_recipe",
        lambda *_a, **_k: {
            "mapSrc": {"x": 0, "y": 0, "w": 10, "h": 10},
            "mapDst": {"x": 0, "y": 0, "w": 20, "h": 20},
        },
    )

    framing_mod.propose_framings(
        wall,
        template,
        wall_payload=full_wall,
        full_wall_payload=full_wall,
        template_payload={"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1}]},
    )

    # Rects are drawn for the one candidate first, then for the planner's own auto recipe.
    candidate_recipe = captured[0]
    assert candidate_recipe.get("listFontSize") == 42
    assert candidate_recipe.get("cardSamples") == [{"w": 1}]


def test_transform_of_uses_the_planner_frame_affine():
    recipe = {
        "mapSrc": {"x": 0, "y": 0, "w": 100, "h": 50},
        "mapDst": {"x": 10, "y": 20, "w": 200, "h": 100},
        "groups": [
            {
                "s": 5.0, "tx": 999.0, "ty": 999.0,
                "src": {"x": 0, "y": 0, "w": 10, "h": 10},
                "dst": {"x": 0, "y": 0, "w": 20, "h": 20},
                "members": 3,
            }
        ],
    }
    aff = frame_affine(recipe)
    assert aff is not None
    expected = {"s": round(aff.s, 6), "tx": round(aff.tx, 2), "ty": round(aff.ty, 2)}
    assert _transform_of(recipe) == expected
    # The old precedence (groups[0] first) would have returned this instead.
    assert expected != {"s": 5.0, "tx": 999.0, "ty": 999.0}


def test_planned_rects_rounds_the_serialized_apply_coordinate(monkeypatch):
    """82.5049 -> as_dict rounds to 82.5 (matching apply's transform dict) -> round(82.5)
    is 82 under banker's rounding. Rounding the raw float directly would also give 82
    here, but the point is planned_rects must go through as_dict's 2-decimal value,
    not the raw one, to stay in lockstep with apply for every boundary case."""
    spec = ItemTransform(
        slide_number=1, item_index=0, kind="text",
        x=82.5049, y=10.0, w=100.0, h=50.0, role="other",
    )
    assert spec.as_dict()["x"] == 82.5
    assert round(spec.as_dict()["x"]) == 82

    from obed_edom import map_remap as map_remap_mod
    monkeypatch.setattr(map_remap_mod, "plan_payload", lambda *a, **k: _plan(transforms=[spec]))

    rects = planned_rects(
        {"index": 0, "number": 1, "items": []}, {}, wall_size=(1920, 1080)
    )
    assert rects[0]["x"] == round(spec.as_dict()["x"]) == 82


def test_planned_rects_does_not_crash_on_a_refused_group(monkeypatch):
    """Reproduces the Gold slide 2 badge collapse's fallout on framing.planned_rects:
    a size-refused group's as_dict() omits w/h entirely, so has_wh must be derived
    from the payload's actual keys, not from spec.role. Must FAIL on pre-fix code
    with KeyError: 'w'."""
    spec = ItemTransform(
        slide_number=2, item_index=0, kind="group",
        x=1700.0, y=40.0, w=278.0, h=87.6, role="other",
        src=Rect(1700.0, 40.0, 278.0, 87.6),
        size_refused="group-children-unavailable",
    )

    from obed_edom import map_remap as map_remap_mod
    monkeypatch.setattr(map_remap_mod, "plan_payload", lambda *a, **k: _plan(transforms=[spec]))

    rects = planned_rects(
        {"index": 1, "number": 2, "items": []}, {}, wall_size=(7680, 1080)
    )
    assert rects[0]["w"] == 278
    assert rects[0]["h"] == 88
