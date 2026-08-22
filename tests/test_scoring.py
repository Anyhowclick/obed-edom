"""Scoring a remap against a human-made CG deck, and leaving hidden slides alone."""

from obed_edom.map_remap import (
    plan_payload_transforms,
    score_against_gold,
)


def _item(**kwargs):
    rec = {
        "index": 0,
        "kind": "shape",
        "x": 0,
        "y": 0,
        "w": 10,
        "h": 10,
        "text": "",
        "fileName": "",
        "locked": False,
    }
    rec.update(kwargs)
    return rec


def _pin(x, y, **kwargs):
    return _item(kind="movie", fileName="PIN DROP WAVE-1.mov", x=x, y=y, w=50, h=50, **kwargs)


def _map(x, y, w, h, **kwargs):
    return _item(kind="image", fileName="pasted-image.pdf", x=x, y=y, w=w, h=h, **kwargs)


def _identity_recipe():
    frame = {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}
    return {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(frame),
        "mapDst": dict(frame),
        "groups": [{"s": 1.0, "tx": 0.0, "ty": 0.0, "src": dict(frame), "dst": dict(frame)}],
    }


def _wall(slides):
    return {"slideWidth": 1920.0, "slideHeight": 1080.0, "slides": slides}


def test_matching_the_gold_layout_scores_zero():
    """The wall gives an exact correspondence, so an identical layout scores 0."""
    slide = {
        "number": 1,
        "items": [
            _map(0, 0, 1000, 600, kindIndex=0),
            _pin(100, 100, kindIndex=0),
            _pin(400, 300, kindIndex=1),
        ],
    }
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    # Gold used the same 1:1 transform, so its objects sit where ours do.
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100), _pin(400, 300)]}
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    assert score["slides"][1]["pin"]["goldRmse"] == 0.0
    assert score["slides"][1]["_goldAffine"]["s"] == 1.0


def test_a_different_layout_choice_shows_up_as_error():
    """Our template shrank the map; the gold kept it full size."""
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(500, 300, kindIndex=0)],
    }
    wall = _wall([slide])
    # Recipe scales everything to half size.
    recipe = _identity_recipe()
    half = {"x": 0.0, "y": 0.0, "w": 500.0, "h": 300.0}
    recipe["mapDst"] = dict(half)
    recipe["groups"] = [{"s": 0.5, "tx": 0.0, "ty": 0.0, "src": recipe["mapSrc"], "dst": half}]
    transforms = plan_payload_transforms(wall, recipe)
    gold = {"slides": [{"number": 1, "items": [_map(0, 0, 1000, 600), _pin(500, 300)]}]}
    score = score_against_gold(transforms, gold, wall=wall)
    assert score["slides"][1]["_goldAffine"]["s"] == 1.0
    # The pin centre sits at (525,325) for gold and (262,162) for us.
    assert score["slides"][1]["pin"]["goldRmse"] > 250


def test_dense_pins_are_compared_by_identity_not_proximity():
    """Dense pins plus a systematic offset defeat nearest-neighbour matching.

    On the real deck 138 pins share ~886px, about 6px apart, while the layout
    difference offsets everything by up to 190px — so each pin matches one about
    thirty places away. Identity matching reports the true offset; proximity
    matching reports something else entirely, sometimes smaller and sometimes
    larger depending on how the cloud is shaped, which is why it cannot be used
    to judge a change.
    """
    pins = [_pin(1000 + i * 6, 500, kindIndex=i) for i in range(40)]
    slide = {"number": 1, "items": [_map(0, 0, 1900, 1000, kindIndex=0), *pins]}
    wall = _wall([slide])
    recipe = _identity_recipe()
    shifted = {"x": 150.0, "y": 0.0, "w": 1900.0, "h": 1000.0}
    recipe["groups"] = [{"s": 1.0, "tx": 150.0, "ty": 0.0, "src": recipe["mapSrc"], "dst": shifted}]
    recipe["mapDst"] = dict(shifted)
    transforms = plan_payload_transforms(wall, recipe)
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1900, 1000), *[_pin(1000 + i * 6, 500) for i in range(40)]]}
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    row = score["slides"][1]["pin"]
    # The truth: we shifted every pin 150px right of where gold has it.
    assert abs(row["goldRmse"] - 150.0) < 1.0
    # Proximity matching does not recover that, so it must not be trusted.
    assert abs(row["nearestRmse"] - 150.0) > 20.0


def test_count_mismatch_is_visible():
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(100, 100, kindIndex=0), _pin(400, 300, kindIndex=1)],
    }
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    gold = {"slides": [{"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100)]}]}
    score = score_against_gold(transforms, gold, wall=wall)
    row = score["slides"][1]["pin"]
    assert row["predicted"] == 2
    assert row["gold"] == 1


def test_skipped_gold_slides_are_not_scored():
    """Hidden alternates held 21% of the items on a real gold CG deck."""
    slide = {"number": 1, "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(100, 100, kindIndex=0)]}
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    gold = {
        "slides": [
            {"number": 1, "items": [_map(0, 0, 1000, 600), _pin(100, 100)]},
            {"number": 2, "skipped": True, "items": [_pin(9, 9) for _ in range(50)]},
        ]
    }
    score = score_against_gold(transforms, gold, wall=wall)
    assert set(score["slides"]) == {1}


def test_geometry_alignment_survives_a_translated_deck():
    """The Chinese CG shares no words with the English wall, only shapes."""
    from obed_edom.map_remap import align_by_geometry

    def slide(number, pins, maps=1, skipped=False, text=""):
        items = [_map(0, 0, 1000, 600, kindIndex=0) for _ in range(maps)]
        items += [_pin(100 + i * 20, 100, kindIndex=i) for i in range(pins)]
        if text:
            items.append(_item(kind="text", text=text, x=0, y=800, w=400, h=60))
        return {"number": number, "skipped": skipped, "items": items}

    wall = [
        slide(1, 4, text="Malaysia report"),
        slide(2, 9, text="Japan report"),
        slide(3, 2, text="China report"),
    ]
    gold = [
        slide(5, 4, text="马来西亚报告"),
        slide(6, 0, maps=0),  # a page the CG added
        slide(7, 9, text="日本报告"),
        slide(8, 2, text="中国报告"),
    ]
    assert align_by_geometry(wall, gold) == {1: 5, 2: 7, 3: 8}


def test_geometry_alignment_stays_in_order():
    """Pairings must not cross, or a page matches a look-alike elsewhere."""
    from obed_edom.map_remap import align_by_geometry

    def slide(number, pins):
        return {
            "number": number,
            "items": [
                _map(0, 0, 1000, 600, kindIndex=0),
                *[_pin(100 + i * 20, 100, kindIndex=i) for i in range(pins)],
            ],
        }

    # Two wall pages report 5 churches each; the gold has them in the same order.
    wall = [slide(1, 5), slide(2, 8), slide(3, 5)]
    gold = [slide(1, 5), slide(2, 8), slide(3, 5)]
    assert align_by_geometry(wall, gold) == {1: 1, 2: 2, 3: 3}


def test_geometry_alignment_skips_hidden_slides():
    from obed_edom.map_remap import align_by_geometry

    def slide(number, pins, skipped=False):
        return {
            "number": number,
            "skipped": skipped,
            "items": [
                _map(0, 0, 1000, 600, kindIndex=0),
                *[_pin(100 + i * 20, 100, kindIndex=i) for i in range(pins)],
            ],
        }

    wall = [slide(1, 4), slide(2, 7)]
    gold = [slide(1, 4), slide(2, 7, skipped=True), slide(3, 7)]
    assert align_by_geometry(wall, gold) == {1: 1, 2: 3}


def test_offscreen_leftovers_are_neither_planned_nor_scored():
    """15.6% of one wall deck sits entirely off-canvas.

    Both decks carry the same parked leftovers, so scoring them dominated the
    result — one report page had 10 pins of which only 1 was visible. Worse, the
    affine can drag an off-canvas object into the CG frame, putting it in output
    it was never in.
    """
    slide = {
        "number": 1,
        "items": [
            _map(0, 0, 1000, 600, kindIndex=0),
            _pin(100, 100, kindIndex=0),
            _pin(1892, -510, kindIndex=1),  # parked above the top edge
            _pin(-900, 200, kindIndex=2),  # parked off to the left
        ],
    }
    wall = _wall([slide])
    transforms = plan_payload_transforms(wall, _identity_recipe())
    assert sum(1 for t in transforms if t.role == "pin") == 1

    gold = {
        "slideWidth": 1920.0,
        "slideHeight": 1080.0,
        "slides": [
            {
                "number": 1,
                "items": [_map(0, 0, 1000, 600), _pin(100, 100), _pin(1892, -510)],
            }
        ],
    }
    score = score_against_gold(transforms, gold, wall=wall)
    row = score["slides"][1]["pin"]
    assert row["predicted"] == 1
    assert row["gold"] == 1
    assert row["goldRmse"] == 0.0


def test_partly_visible_content_is_kept():
    """A cropped photo's visible part is real content."""
    slide = {
        "number": 1,
        "items": [
            _map(0, 0, 1000, 600, kindIndex=0),
            _pin(-20, 100, kindIndex=0),  # half off the left edge
        ],
    }
    transforms = plan_payload_transforms(_wall([slide]), _identity_recipe())
    assert sum(1 for t in transforms if t.role == "pin") == 1


def test_a_framing_that_throws_content_off_screen_falls_back_to_fitting():
    """Report pages are framed per country, so next week's will match nothing.

    Applying the closest wrong framing put objects 2000px out. Fitting the
    visible content keeps everything present and roughly placed instead.
    """
    from obed_edom.map_remap import fit_to_frame_recipe, on_canvas_fraction

    slide = {
        "number": 1,
        "items": [
            _map(6000, 200, 1200, 700, kindIndex=0),
            _pin(6400, 400, kindIndex=0),
            _pin(6800, 500, kindIndex=1),
        ],
    }
    wall = {"slideWidth": 7680.0, "slideHeight": 1080.0, "slides": [slide]}
    # A template that describes a different part of the wall entirely.
    wrong = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 0.0, "y": 0.0, "w": 1200.0, "h": 700.0},
        "mapDst": {"x": 0.0, "y": 0.0, "w": 1200.0, "h": 700.0},
        "groups": [
            {
                "s": 1.0,
                "tx": 0.0,
                "ty": 0.0,
                "src": {"x": 0.0, "y": 0.0, "w": 1200.0, "h": 700.0},
                "dst": {"x": 0.0, "y": 0.0, "w": 1200.0, "h": 700.0},
            }
        ],
    }
    assert on_canvas_fraction(slide, wrong, 7680.0, 1080.0) == 0.0

    fitted = fit_to_frame_recipe(slide, 7680.0, 1080.0, 1920.0, 1080.0)
    assert fitted is not None
    assert fitted["source"] == "fit-to-frame"
    assert on_canvas_fraction(slide, fitted, 7680.0, 1080.0) == 1.0

    # Everything the fit places lands inside the frame.
    planned = plan_payload_transforms(wall, fitted)
    assert planned
    for t in planned:
        assert 0 <= t.x <= 1920
        assert 0 <= t.y <= 1080


def test_the_planner_switches_to_fitting_and_says_which_slides():
    """Wiring check. The threshold is forced, since learn_recipe is hard to fool
    with synthetic geometry — the real trigger came from a live report deck."""
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1200, 700, kindIndex=0), _pin(100, 100, kindIndex=0)],
    }
    wall = {"slideWidth": 7680.0, "slideHeight": 1080.0, "slides": [slide]}
    template = {
        "slideWidth": 1920.0,
        "slideHeight": 1080.0,
        "slides": [{"number": 1, "items": [_map(0, 0, 1200, 700, kindIndex=0)]}],
    }
    fitted_slides: list[int] = []
    plan_payload_transforms(
        wall,
        _identity_recipe(),
        template=template,
        fitted_slides=fitted_slides,
        min_on_canvas=1.01,
    )
    assert fitted_slides == [1]

    # Left alone at the real threshold, since this framing does fit.
    untouched: list[int] = []
    plan_payload_transforms(
        wall, _identity_recipe(), template=template, fitted_slides=untouched
    )
    assert untouched == []


def test_a_sparse_template_is_still_believed():
    """One anchor image is the documented advice, so it must not trip the fallback."""
    from obed_edom.map_remap import on_canvas_fraction

    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), _pin(100, 100, kindIndex=0)],
    }
    assert on_canvas_fraction(slide, _identity_recipe(), 1920.0, 1080.0) == 1.0


def test_skipped_wall_slides_are_not_planned():
    slides = [
        {"number": 1, "items": [_pin(100, 100, kindIndex=0)]},
        {"number": 2, "skipped": True, "items": [_pin(200, 200, kindIndex=0)]},
        {"number": 3, "items": [_pin(300, 300, kindIndex=0)]},
    ]
    hidden: list[int] = []
    transforms = plan_payload_transforms(_wall(slides), _identity_recipe(), skipped_slides=hidden)
    assert hidden == [2]
    assert sorted({t.slide_number for t in transforms}) == [1, 3]
