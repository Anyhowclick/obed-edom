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
)
from obed_edom.map_remap import ItemTransform, frame_affine

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
        report = kwargs.get("framing_report")
        if report is not None:
            report.extend(
                {
                    "slide": slide["number"],
                    "templateSlide": 1,
                    "fitted": False,
                }
                for slide in payload["slides"]
            )
        return []

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
    monkeypatch.setattr(remap_mod, "plan_payload_transforms", fake_plan)
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
                {"templateSlide": 1, "wouldFallBack": False, "transform": None, "rects": []}
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
    captured: dict = {}

    def fake_plan(payload, _recipe, **kwargs):
        report = kwargs.get("framing_report")
        if report is not None:
            report.append({"slide": 1, "templateSlide": 1, "fitted": True})
        return []

    def fake_planned_rects(_slide, recipe, **_kwargs):
        captured["recipe"] = recipe
        return []

    monkeypatch.setattr(baseline_mod, "deck_digest", lambda _path: "deck")
    monkeypatch.setattr(baseline_mod, "deck_slide_digests", lambda _payload: ["d1"])
    monkeypatch.setattr(baseline_mod, "wall_thumb_dir", lambda _digest: tmp_path / "thumbs")
    monkeypatch.setattr(framing_mod, "build_preview_thumbs", lambda *_a, **_k: {})
    monkeypatch.setattr(framing_mod, "planned_rects", fake_planned_rects)
    monkeypatch.setattr(remap_mod, "learn_recipe", lambda *_a, **_k: dict(trial_recipe))
    monkeypatch.setattr(remap_mod, "plan_payload_transforms", fake_plan)
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

    assert captured["recipe"].get("listFontSize") == 42
    assert captured["recipe"].get("cardSamples") == [{"w": 1}]


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
    monkeypatch.setattr(map_remap_mod, "plan_payload_transforms", lambda *a, **k: [spec])

    rects = planned_rects(
        {"index": 0, "number": 1, "items": []}, {}, wall_size=(1920, 1080)
    )
    assert rects[0]["x"] == round(spec.as_dict()["x"]) == 82
