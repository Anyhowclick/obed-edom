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


def test_content_pushed_out_of_frame_is_reported():
    """Nothing else catches this. bounds.offcanvas measures vertical cuts only
    and bounds.straddles looks for LED panel seams, so an object shoved off the
    left or right edge is invisible to both and simply vanishes."""
    from obed_edom.map_remap import offframe_rows, plan_slide_transforms

    keeper = _map(3000, 100, 1200, 700, kindIndex=0)
    off_left = _item(kind="image", fileName="badge.png", x=100, y=40, w=300, h=120, kindIndex=1)
    off_right = _item(kind="text", text="Not Actual Names", x=5385, y=100, w=300, h=60, kindIndex=0)
    slide = {"number": 1, "items": [keeper, off_left, off_right]}
    # A pure crop: wall x 3000 lands at 0.
    frame = {"x": 3000.0, "y": 100.0, "w": 1200.0, "h": 700.0}
    dst = {"x": 0.0, "y": 100.0, "w": 1200.0, "h": 700.0}
    recipe = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(frame),
        "mapDst": dict(dst),
        "groups": [{"s": 1.0, "tx": -3000.0, "ty": 0.0, "src": frame, "dst": dst}],
    }
    out = plan_slide_transforms(slide, recipe, include_lists=True, wall_size=(7680.0, 1080.0))
    rows = offframe_rows(out, slide, recipe, 7680.0, 1080.0)
    reported = {(r["kind"], r["kindIndex"]) for r in rows}
    assert ("image", 1) in reported, "badge pushed off the left edge went unreported"
    assert ("text", 0) in reported, "text pushed off the right edge went unreported"
    # The map itself is fine and must not be reported.
    assert ("image", 0) not in reported


def test_offscreen_wall_content_is_not_reported_as_pushed_out():
    """It was already invisible, so it is not news — and it is never planned."""
    from obed_edom.map_remap import offframe_rows, plan_slide_transforms

    slide = {
        "number": 1,
        "items": [_map(3000, 100, 1200, 700, kindIndex=0), _pin(1892, -510, kindIndex=0)],
    }
    frame = {"x": 3000.0, "y": 100.0, "w": 1200.0, "h": 700.0}
    dst = {"x": 0.0, "y": 100.0, "w": 1200.0, "h": 700.0}
    crop = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(frame),
        "mapDst": dict(dst),
        "groups": [{"s": 1.0, "tx": -3000.0, "ty": 0.0, "src": frame, "dst": dst}],
    }
    out = plan_slide_transforms(slide, crop, wall_size=(7680.0, 1080.0))
    # The parked pin is never planned, so it cannot be reported either.
    assert offframe_rows(out, slide, crop, 7680.0, 1080.0) == []


def test_many_labels_do_not_all_snap_to_one_template_position():
    """listDst pins where a single column belongs. Applied to fifteen map
    labels it stacked all fifteen on one point; the old blind packing spread
    them again afterwards, so the collapse only showed once that was deferred."""
    from obed_edom.map_remap import plan_slide_transforms

    labels = [
        _item(kind="text", text=f"CHC Name {i}", x=3300 + i * 40, y=200 + i * 30, w=200, h=44, kindIndex=i, size=20)
        for i in range(5)
    ]
    slide = {"number": 1, "items": [_map(3000, 100, 1200, 700, kindIndex=0), *labels]}
    recipe = dict(_identity_recipe())
    recipe["listFontSize"] = 20.0
    recipe["listPaired"] = True
    recipe["listDst"] = {"x": 638.0, "y": 537.0, "w": 192.0, "h": 46.0}

    out = plan_slide_transforms(slide, recipe, include_lists=True, defer_list_packing=True)
    spots = {(round(t.x), round(t.y)) for t in out if t.role == "list"}
    assert len(spots) == 5, "labels collapsed onto one another"

    # A lone column still honours the template's destination.
    single = {"number": 1, "items": [_map(3000, 100, 1200, 700, kindIndex=0), labels[0]]}
    out = plan_slide_transforms(single, recipe, include_lists=True, defer_list_packing=True)
    only = next(t for t in out if t.role == "list")
    assert (round(only.x), round(only.y)) == (638, 537)


def test_map_labels_are_not_dragged_off_the_map():
    """A label belongs to its plate. Blind packing moved the words to the frame
    edge and left the red plate behind on the map, which reads as a broken deck.
    Deferring the decision keeps labels at their mapped position."""
    from obed_edom.map_remap import plan_slide_transforms

    # Two labels sitting on plates, plus a genuine free-floating name column.
    label_a = _item(kind="text", text="CHC Bian Lan", x=500, y=300, w=220, h=44, kindIndex=0, size=20)
    label_b = _item(kind="text", text="CHC Zui Si", x=700, y=500, w=200, h=44, kindIndex=1, size=20)
    column = _item(
        kind="text",
        text="CHC Aaliana\nCHC Bais\nCHC Cavinte\nCHC Dahunan",
        x=1500,
        y=100,
        w=300,
        h=400,
        kindIndex=2,
        size=20,
    )
    slide = {
        "number": 1,
        "items": [_map(0, 0, 1000, 600, kindIndex=0), label_a, label_b, column],
    }
    recipe = dict(_identity_recipe())
    recipe["listFontSize"] = 20.0

    packed = plan_slide_transforms(slide, recipe, include_lists=True, defer_list_packing=False)
    deferred = plan_slide_transforms(slide, recipe, include_lists=True, defer_list_packing=True)

    # Blind packing walks them to the right edge; deferring leaves them put.
    packed_xs = sorted(t.x for t in packed if t.role == "list")
    deferred_xs = sorted(t.x for t in deferred if t.role == "list")
    assert packed_xs != deferred_xs
    assert deferred_xs == [500.0, 700.0, 1500.0]


def test_a_framing_that_keeps_the_map_whole_wins_a_tie():
    """The same map often appears at several framings; one crops it."""
    from obed_edom.map_remap import _best_matching_slide

    wall_slide = {
        "number": 1,
        "items": [_map(3000, 100, 1200, 700, kindIndex=0), _pin(3500, 400, kindIndex=0)],
    }
    # Both hold the same art, so they pair equally well. The first crops it off
    # the left edge; the second keeps it inside the frame.
    crops = {"number": 1, "items": [_map(-700, 100, 1200, 700, kindIndex=0)]}
    whole = {"number": 2, "items": [_map(300, 100, 1200, 700, kindIndex=0)]}

    picked = _best_matching_slide(
        wall_slide, [crops, whole], wall_size=(7680.0, 1080.0), dest_size=(1920.0, 1080.0)
    )
    assert picked is whole

    # Order must not decide it.
    picked = _best_matching_slide(
        wall_slide, [whole, crops], wall_size=(7680.0, 1080.0), dest_size=(1920.0, 1080.0)
    )
    assert picked is whole


def test_a_framing_that_shrinks_into_a_corner_does_not_win():
    """Keeping content inside the frame is trivially maximised by shrinking.

    Scoring only that made a tiny framing beat every rival with a perfect 1.0,
    so slides came out squeezed into the top-left with the frame left empty.
    """
    from obed_edom.map_remap import _best_matching_slide

    wall_slide = {
        "number": 1,
        "items": [_map(3000, 100, 1200, 700, kindIndex=0), _pin(3500, 400, kindIndex=0)],
    }
    tiny = {"number": 3, "items": [_map(20, 20, 300, 175, kindIndex=0)]}
    sized = {"number": 2, "items": [_map(300, 100, 1200, 700, kindIndex=0)]}

    for order in ([tiny, sized], [sized, tiny]):
        picked = _best_matching_slide(
            wall_slide, order, wall_size=(7680.0, 1080.0), dest_size=(1920.0, 1080.0)
        )
        assert picked is sized


def test_a_better_fit_beats_one_extra_paired_object():
    """Score is agreement*100 + pair count, so a single extra pair used to
    outrank a fit two and a half times better and pick the wrong framing."""
    from obed_edom.map_remap import _best_matching_slide

    wall_slide = {
        "number": 1,
        "items": [
            _map(3000, 100, 1364, 947, kindIndex=0),
            _item(kind="image", fileName="pasted-image.pdf", x=3100, y=200, w=200, h=140, kindIndex=1),
        ],
    }
    # Same agreement level; this one frames the map properly.
    good_fit = {"number": 1, "items": [_map(226, 61, 1364, 947, kindIndex=0)]}
    # One extra paired object, but a framing that barely uses the frame.
    extra_pair = {
        "number": 3,
        "items": [
            _map(11, 18, 400, 278, kindIndex=0),
            _item(kind="image", fileName="pasted-image.pdf", x=20, y=30, w=59, h=41, kindIndex=1),
        ],
    }
    for order in ([extra_pair, good_fit], [good_fit, extra_pair]):
        picked = _best_matching_slide(
            wall_slide, order, wall_size=(7680.0, 1080.0), dest_size=(1920.0, 1080.0)
        )
        assert picked is good_fit


def test_a_collapsed_scale_is_rejected_even_though_it_is_all_on_canvas():
    """Content squeezed into a corner is entirely on canvas, so the off-frame
    check blesses it. Nothing sensible shrinks below "the whole wall fits"."""
    from obed_edom.map_remap import is_degenerate_scale, on_canvas_fraction

    slide = {
        "number": 1,
        "items": [_map(3000, 100, 1200, 700, kindIndex=0), _pin(3500, 400, kindIndex=0)],
    }
    tiny_src = {"x": 3000.0, "y": 100.0, "w": 1200.0, "h": 700.0}
    tiny_dst = {"x": 10.0, "y": 10.0, "w": 76.0, "h": 44.0}
    collapsed = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(tiny_src),
        "mapDst": dict(tiny_dst),
        "groups": [{"s": 0.0634, "tx": -180.0, "ty": 3.7, "src": tiny_src, "dst": tiny_dst}],
    }
    # Everything lands on canvas, so the off-frame test cannot see the problem.
    assert on_canvas_fraction(slide, collapsed, 7680.0, 1080.0) == 1.0
    # The scale floor can: 1920/7680 * 0.9 = 0.225.
    assert is_degenerate_scale(collapsed, 7680.0, 1080.0)
    # A crop at full size is fine.
    assert not is_degenerate_scale(_identity_recipe(), 7680.0, 1080.0)


def test_a_framing_that_overflows_the_frame_does_not_win_either():
    """The mirror failure: filling the frame is maximised by going too big."""
    from obed_edom.map_remap import _best_matching_slide

    wall_slide = {
        "number": 1,
        "items": [_map(3000, 100, 1200, 700, kindIndex=0), _pin(3500, 400, kindIndex=0)],
    }
    huge = {"number": 4, "items": [_map(-1500, -900, 4800, 2800, kindIndex=0)]}
    sized = {"number": 2, "items": [_map(300, 100, 1200, 700, kindIndex=0)]}

    for order in ([huge, sized], [sized, huge]):
        picked = _best_matching_slide(
            wall_slide, order, wall_size=(7680.0, 1080.0), dest_size=(1920.0, 1080.0)
        )
        assert picked is sized


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
