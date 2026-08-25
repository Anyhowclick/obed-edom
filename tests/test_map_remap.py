from obed_edom.map_remap import (
    Affine,
    Rect,
    affine_of,
    cover_rect,
    effective_wall_map_src,
    is_map_item,
    is_pin_item,
    item_center,
    learn_recipe,
    map_dst_for_cg,
    map_point,
    merge_affine_groups,
    pair_by_size,
    plan_payload_transforms,
    plan_slide_transforms,
    recipe_from_cover,
    score_against_gold,
    summarize_plan,
)


def _item(**kwargs):
    rec = {"index": 0, "kind": "shape", "x": 0, "y": 0, "w": 10, "h": 10, "text": "", "fileName": "", "locked": False}
    rec.update(kwargs)
    return rec


def test_wall_canvas_used_when_map_image_inspects_as_cg():
    wide = Rect(0, 0, 1920, 1080)
    src = effective_wall_map_src({"slideWidth": 7680, "slideHeight": 1080}, wide)
    assert src.w == 7680
    assert src.h == 1080
    already_cg = effective_wall_map_src({"slideWidth": 1920, "slideHeight": 1080}, wide)
    assert already_cg.w == 1920


def _one_map_wall() -> dict:
    return {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080),
                ],
            }
        ],
    }


def test_a_pinned_framing_is_used_instead_of_the_best_match():
    wall = _one_map_wall()
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=-2880, y=0, w=7680, h=1080),
                ],
            },
            {
                "number": 2,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=100, w=1280, h=720),
                ],
            },
        ],
    }
    auto = learn_recipe(wall, template)
    pinned = learn_recipe(wall, template, template_slide=2)
    assert pinned["templateSlide"] == 2
    assert pinned["framingPinned"] is True
    assert pinned["mapDst"] != auto["mapDst"]
    # An unknown pin must not fail the run; it falls back to choosing.
    stale = learn_recipe(wall, template, template_slide=99)
    assert stale["framingPinned"] is False
    assert stale["templateSlide"] == auto["templateSlide"]


def test_an_unbuildable_pin_still_reports_which_slide_was_tried():
    """A pin applied and found unusable is not the same answer as a pin ignored.

    Only the first tells the operator that this template slide cannot frame this
    page, and the cover-fallback path used to report neither.
    """
    wall = _one_map_wall()
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=-2880, y=0, w=7680, h=1080),
                ],
            },
            {"number": 2, "items": []},
        ],
    }
    recipe = learn_recipe(wall, template, template_slide=2)
    assert recipe["source"] == "cover-fallback"
    assert recipe["templateSlide"] == 2
    assert recipe["framingPinned"] is True
    assert recipe["pairQuality"] == 0


def test_framing_report_says_what_each_slide_used():
    wall = _one_map_wall()
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=-2880, y=0, w=7680, h=1080),
                ],
            },
            {
                "number": 2,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=100, w=1280, h=720),
                ],
            },
        ],
    }
    recipe = learn_recipe(wall, template)
    report: list[dict] = []
    plan_payload_transforms(
        wall,
        recipe,
        template=template,
        framing_overrides={1: 2},
        framing_report=report,
    )
    assert len(report) == 1
    row = report[0]
    assert row["slide"] == 1
    assert row["requested"] == 2
    assert row["templateSlide"] == 2
    assert row["confirmed"] is True
    assert "fitted" in row


def test_cover_keeps_center_pin_on_canvas():
    map_src = Rect(0, 0, 7680, 1080)
    recipe = recipe_from_cover(map_src)
    dst = Rect(**recipe["mapDst"])
    assert dst.w == 7680
    assert dst.h == 1080
    assert dst.x == -2880
    cx, cy = map_point(3840, 540, map_src, dst)
    assert abs(cx - 960) < 0.5
    assert abs(cy - 540) < 0.5


def test_gold_recipe_pairs_pins_and_list():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kindIndex=0, kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080),
                    _item(index=1, kindIndex=0, kind="movie", fileName="PIN DROP WAVE-1.mov", x=3815, y=515, w=50, h=50),
                    _item(index=2, kindIndex=0, kind="text", text="CHC Prai", x=6000, y=80, w=400, h=40, size=36),
                ],
            }
        ],
    }
    gold = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(index=0, kind="image", fileName="map BG-1.png", x=-2880, y=0, w=7680, h=1080),
                    _item(index=1, kind="movie", fileName="PIN DROP WAVE-1.mov", x=935, y=515, w=50, h=50),
                    _item(index=2, kind="text", text="CHC Prai", x=1400, y=40, w=480, h=48, size=28),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, gold)
    assert recipe["source"] == "template-cover"
    assert recipe["mapDst"]["x"] == -2880
    assert recipe["mapDst"]["w"] == 7680
    assert recipe["pinPairs"] == 1
    assert recipe["pinRmse"] is not None
    assert recipe["pinRmse"] < 5
    assert "listSrc" in recipe
    transforms = plan_payload_transforms(wall, recipe)
    counts = summarize_plan(transforms)
    assert counts["map"] == 1
    assert counts["pin"] == 1
    assert counts["list"] == 0
    assert counts.get("hide") == 1
    pin = next(t for t in transforms if t.role == "pin")
    assert abs((pin.x + pin.w / 2) - 960) < 1
    assert abs((pin.y + pin.h / 2) - 540) < 1
    assert abs(pin.w - 50) < 1
    assert pin.as_dict()["w"] == 50
    assert pin.as_dict()["kindIndex"] == 0
    score = score_against_gold(transforms, gold, wall=wall)
    assert score["pinPairs"] == 1
    assert score["pinRmse"] < 5

    with_lists = plan_payload_transforms(wall, recipe, include_lists=True)
    assert summarize_plan(with_lists)["list"] == 1
    name = next(t for t in with_lists if t.role == "list")
    assert name.font_size == 28
    assert abs(name.w - 400 * (28 / 36)) < 2
    assert name.x + name.w <= 1920 + 2
    assert name.y >= 0


def test_full_frame_template_cover_crops_wall_map():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080),
                    _item(kind="movie", fileName="PIN DROP WAVE-1.mov", x=3815, y=515, w=50, h=50),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="map BG-1.png", x=0, y=0, w=1920, h=1080),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["mapSrc"]["w"] == 7680
    assert recipe["mapDst"]["w"] == 7680
    assert recipe["mapDst"]["h"] == 1080
    assert recipe["mapDst"]["x"] == -2880
    pin = next(t for t in plan_payload_transforms(wall, recipe) if t.role == "pin")
    assert abs((pin.x + pin.w / 2) - 960) < 1
    assert abs((pin.y + pin.h / 2) - 540) < 1


def test_letterbox_template_is_treated_as_cover():
    dst = map_dst_for_cg(Rect(0, 0, 7680, 1080), Rect(0, 200, 1920, 270), 1920, 1080)
    assert dst.w == 7680
    assert dst.h == 1080
    assert dst.x == -2880


def test_template_wide_crop_is_kept():
    crop = Rect(-3200, 0, 7680, 1080)
    dst = map_dst_for_cg(Rect(0, 0, 7680, 1080), crop, 1920, 1080)
    assert dst.x == -3200
    assert dst.w == 7680


def test_layout_map_is_not_expanded_to_wall_canvas():
    layout = Rect(3052, -12, 1248, 771)
    src = effective_wall_map_src({"slideWidth": 7680, "slideHeight": 1080}, layout)
    assert src.w == 1248
    assert src.x == 3052


def test_template_layout_translates_map_cluster_and_pins():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 2,
                "items": [
                    _item(kindIndex=0, kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kindIndex=1, kind="image", fileName="pasted-image.pdf", x=3061, y=-6, w=1232, h=761),
                    _item(kindIndex=5, kind="image", fileName="pasted-image.pdf", x=4073, y=748, w=306, h=295),
                    _item(kindIndex=0, kind="shape", x=3563, y=255, w=11, h=11),
                    _item(kindIndex=0, kind="text", text="Global Missions", x=2147, y=52, w=537, h=124, size=36),
                    _item(kindIndex=1, kind="text", text="CHC Prai\nCHC Aliwal", x=262, y=9, w=423, h=954, size=18),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=20, y=24, w=1232, h=761),
                    _item(kind="text", text="全球使命", x=128, y=50, w=282, h=99, size=36),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["source"] == "template-layout"
    assert abs(recipe["mapDst"]["x"] - 11) < 1
    assert abs(recipe["mapDst"]["w"] - 1248) < 1
    transforms = plan_payload_transforms(wall, recipe)
    counts = summarize_plan(transforms)
    assert counts["map"] == 3
    assert counts["pin"] == 1
    assert counts.get("hide") == 1
    assert counts.get("list", 0) == 0
    pin = next(t for t in transforms if t.role == "pin")
    assert abs(pin.x - (3563 - 3041)) < 1
    assert abs(pin.y - (255 + 30)) < 1
    assert abs(pin.w - 11) < 1
    layer = next(t for t in transforms if t.role == "map" and abs(t.w - 1248) < 1)
    assert abs(layer.x - 11) < 1
    assert abs(layer.y - 18) < 1
    assert abs(layer.w - 1248) < 1
    assert abs(layer.h - 771) < 1
    orange = next(t for t in transforms if t.role == "map" and abs(t.w - 306) < 1)
    assert abs(orange.x - (4073 - 3041)) < 1
    assert abs(orange.y - (748 + 30)) < 1
    maps = [t for t in transforms if t.role == "map"]
    assert maps[0].w >= maps[-1].w
    hides = [t for t in transforms if t.role == "hide"]
    assert len(hides) == 1
    assert abs(hides[0].x - 262) < 1


def test_gold_map_layers_share_one_affine():
    """Wall s2 vs gold CG s3: every country overlay is translate (-3041, 30), scale 1."""
    pairs = [
        ((3052, -12, 1248, 771), (11, 18, 1248, 771)),
        ((3740, 328, 554, 426), (699, 358, 554, 426)),
        ((4073, 748, 306, 295), (1032, 778, 306, 295)),
        ((3858, 615, 5, 3), (817, 645, 5, 3)),
    ]
    affines = [Affine(*affine_of(Rect(*src), Rect(*dst))) for src, dst in pairs]
    assert {round(a.s, 4) for a in affines} == {1.0}
    assert {round(a.tx, 0) for a in affines} == {-3041}
    assert {round(a.ty, 0) for a in affines} == {30}
    grouped = merge_affine_groups(
        [
            (_item(kind="image", x=s[0], y=s[1], w=s[2], h=s[3]), _item(kind="image", x=d[0], y=d[1], w=d[2], h=d[3]))
            for s, d in pairs
        ]
    )
    assert len(grouped) == 1
    assert grouped[0]["affine"].similar(Affine(1.0, -3041.0, 30.0))


def test_two_layout_groups_do_not_share_an_affine():
    """Generic path: a left photo and a right box can have different affines."""
    wall = [
        _item(kind="image", x=0, y=0, w=2000, h=1000),
        _item(kind="image", x=4200, y=100, w=800, h=400),
    ]
    dest = [
        _item(kind="image", x=0, y=0, w=2000, h=1000),
        _item(kind="image", x=50, y=80, w=800, h=400),
    ]
    pairs = pair_by_size(wall, dest)
    assert len(pairs) == 2
    grouped = merge_affine_groups(pairs)
    assert len(grouped) == 2


def test_led_panel_tiles_are_not_the_base_map():
    """`map BG.png` passes is_map_item, but a 1920x1080 panel tile is a backdrop.

    It outweighs real map art on area, so taking it as the affine origin put a
    whole deck's pins about 2500px from where the finished CG has them.
    """
    from obed_edom.map_remap import primary_map_rect

    items = [
        _item(kind="image", fileName="Data/map BG-39230.png", x=0, y=0, w=1920, h=1080),
        _item(kind="image", fileName="Data/map BG-39231.png", x=5760, y=0, w=1920, h=1080),
        _item(kind="image", fileName="pasted-image.pdf", x=3258, y=-69, w=1364, h=947),
    ]
    assert primary_map_rect(items) == Rect(3258, -69, 1364, 947)


def test_full_wall_map_art_is_still_eligible():
    """A wall-spanning map named `map BG` is art, not a panel tile."""
    from obed_edom.map_remap import primary_map_rect

    items = [_item(kind="image", fileName="Data/map BG-1.png", x=0, y=0, w=7680, h=1080)]
    assert primary_map_rect(items) == Rect(0, 0, 7680, 1080)


def test_classifies_pasted_map_art():
    assert is_map_item(_item(kind="image", fileName="pasted-image.pdf", w=1248, h=771))
    assert not is_map_item(_item(kind="image", fileName="pasted-image.pdf", w=20000, h=14934))
    assert not is_map_item(_item(kind="image", fileName="pasted-image.pdf", w=124, h=124))
    cluster = Rect(3052, -12, 1248, 771)
    assert is_map_item(_item(kind="image", fileName="pasted-image.pdf", x=3305, y=344, w=13, h=13), cluster)
    assert is_map_item(_item(kind="image", fileName="pasted-image.pdf", x=4073, y=748, w=306, h=295), cluster)
    assert not is_map_item(_item(kind="image", fileName="pasted-image.pdf", x=1992, y=52, w=124, h=124), cluster)
    assert is_map_item(_item(kind="image", fileName="Data/map BG-39230.png", w=7680, h=1080))
    assert is_pin_item(_item(kind="movie", fileName="PIN DROP WAVE-71712.mov", w=500, h=500))
    assert not is_pin_item(_item(kind="image", fileName="34. CHC Kotagiri-76091.JPG", w=800, h=600))
    assert not is_map_item(_item(kind="image", fileName="LED blank-1.png", w=7680, h=1080))


def _identity_recipe():
    """A 1:1 recipe, so planning order can be asserted without geometry noise."""
    frame = {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}
    return {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": dict(frame),
        "mapDst": dict(frame),
        "groups": [{"s": 1.0, "tx": 0.0, "ty": 0.0, "src": dict(frame), "dst": dict(frame)}],
        # Without a titleDst the planner drops title text entirely.
        "titleDst": {"x": 135.0, "y": 67.0, "w": 271.0, "h": 64.0},
    }


def test_base_map_is_applied_before_the_overlays_that_sit_on_it():
    """Apply order is stacking order, so the biggest map plate has to go first."""
    asia = _item(index=0, kindIndex=0, kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771)
    australia = _item(index=1, kindIndex=1, kind="image", fileName="pasted-image.pdf", x=1032, y=778, w=306, h=295)
    pin = _item(index=2, kindIndex=0, kind="movie", fileName="PIN DROP WAVE-1.mov", x=1100, y=900, w=50, h=50)
    title = _item(index=3, kindIndex=0, kind="text", text="Global Missions", x=135, y=67, w=271, h=64)
    slide = {"number": 1, "items": [pin, title, australia, asia]}
    roles = [
        (t.role, t.w * t.h)
        for t in plan_slide_transforms(slide, _identity_recipe(), include_lists=True)
    ]
    assert [r for r, _ in roles] == ["map", "map", "pin", "title"]
    # Largest map first: Australia must land on top of the Asia plate.
    assert roles[0][1] > roles[1][1]


def test_title_cluster_does_not_swallow_stats_groups():
    """The stats infographic sits 4px under the badge on the wall. A padded
    bbox test used to give it the title affine, landing it on the badge."""
    recipe = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
        "mapDst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
        "groups": [
            {
                "s": 0.8547,
                "tx": -2597.5,
                "ty": 28.3,
                "src": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
                "dst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
            }
        ],
        "titleDst": {"x": 135.0, "y": 67.0, "w": 271.0, "h": 64.0},
        "titleFontSize": 50.0,
    }
    slide = {
        "number": 4,
        "items": [
            _item(
                index=0,
                kindIndex=0,
                kind="text",
                text="Global Missions",
                x=2147,
                y=52,
                w=537,
                h=124,
                size=100,
            ),
            _item(
                index=3,
                kindIndex=0,
                kind="image",
                fileName="pasted-image.pdf",
                x=1992,
                y=52,
                w=124,
                h=124,
            ),
            _item(index=24, kindIndex=0, kind="shape", x=1953, y=28, w=767, h=173),
            _item(
                index=4,
                kindIndex=1,
                kind="image",
                fileName="pasted-image.pdf",
                x=3052,
                y=-12,
                w=1248,
                h=771,
            ),
            _item(index=163, kindIndex=0, kind="group", x=1993, y=172, w=537, h=271),
        ],
    }
    out = plan_slide_transforms(slide, recipe)
    title = next(t for t in out if t.role == "title")
    assert abs(title.x - 135) < 1
    globe = next(t for t in out if t.kind == "image" and t.item_index == 3)
    assert 0 < globe.x < 200
    stats = next(t for t in out if t.kind == "group")
    # Map affine for position, wall size so grouped children (logo, rules, type)
    # still fit. Affine-scaled w/h clips them.
    assert abs(stats.w - 537) < 1
    assert abs(stats.h - 271) < 1
    assert stats.y > title.y + title.h + 20
    assert stats.x >= 0
    plate = next(t for t in out if t.kind == "shape")
    assert 0 < plate.x < 200


def _missions_map_recipe() -> dict:
    return {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
        "mapDst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
        "groups": [
            {
                "s": 0.8547,
                "tx": -2597.5,
                "ty": 28.3,
                "src": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
                "dst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
            }
        ],
        "titleDst": {"x": 135.0, "y": 67.0, "w": 271.0, "h": 64.0},
        "titleFontSize": 50.0,
    }


def test_zero_thickness_line_is_visible_and_planned():
    """Inspect reports a 90° meridian as h=0 / w=length. Skipping those left
    the 7680→1920 leftover (~164px) on the map."""
    from obed_edom.map_remap import is_visible

    line = _item(
        index=171,
        kindIndex=0,
        kind="line",
        x=2587,
        y=223,
        w=658,
        h=0,
        start=[2587, 881],
        end=[2587, 223],
    )
    assert is_visible(line, 7680, 1080)
    slide = {
        "number": 4,
        "items": [
            _item(
                index=4,
                kindIndex=1,
                kind="image",
                fileName="pasted-image.pdf",
                x=3052,
                y=-12,
                w=1248,
                h=771,
            ),
            line,
        ],
    }
    out = plan_slide_transforms(slide, _missions_map_recipe(), wall_size=(7680, 1080))
    planned = next(t for t in out if t.kind == "line")
    assert planned.start is not None and planned.end is not None
    assert planned.x >= 0
    assert abs(planned.end[1] - planned.start[1]) > 400
    assert "w" not in planned.as_dict()


def test_date_group_keeps_wall_width():
    recipe = _missions_map_recipe()
    slide = {
        "number": 4,
        "items": [
            _item(
                index=4,
                kindIndex=1,
                kind="image",
                fileName="pasted-image.pdf",
                x=3052,
                y=-12,
                w=1248,
                h=771,
            ),
            _item(index=166, kindIndex=3, kind="group", x=4438, y=21, w=575, h=76),
        ],
    }
    out = plan_slide_transforms(slide, recipe, wall_size=(7680, 1080))
    date = next(t for t in out if t.kind == "group")
    assert abs(date.w - 575) < 1
    assert abs(date.h - 76) < 1


def test_same_size_overlays_keep_deck_order_because_z_is_unreadable():
    """Keynote reports no stacking (slide.iWorkItems() is empty), so equal-area
    map layers can only fall back to the order Keynote listed them in. Getting
    these two the right way round needs a human, and that is a known limit."""
    india = _item(index=0, kindIndex=0, kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771)
    white = _item(index=1, kindIndex=1, kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771)
    slide = {"number": 1, "items": [india, white]}
    out = plan_slide_transforms(slide, _identity_recipe(), include_lists=True)
    assert [t.kind_index for t in out] == [0, 1]


def test_resolve_slide_range_single_and_span():
    from obed_edom.map_remap import resolve_slide_range

    assert resolve_slide_range(2, None) == (2, 2)
    assert resolve_slide_range(None, 2) == (2, 2)
    assert resolve_slide_range(1, 9) == (1, 9)
    # Nothing asked for means the whole deck, not a default slide.
    assert resolve_slide_range(None, None) is None
    assert resolve_slide_range(None, None, default=(2, 2)) == (2, 2)


def test_no_slide_selection_plans_every_slide():
    """The resizer used to default to slide 2, where the map lived by convention."""
    from obed_edom.map_remap import resolve_slides, wants_slide

    assert resolve_slides(spec=None, range_from=None, range_to=None) is None
    for number in (1, 2, 7, 158):
        assert wants_slide(number, None)


def test_parse_slide_spec_lists_and_gaps():
    from obed_edom.map_remap import format_slide_range, parse_slide_spec, resolve_slides, wants_slide

    assert parse_slide_spec("2") == frozenset({2})
    assert parse_slide_spec("2, 4-6") == frozenset({2, 4, 5, 6})
    assert parse_slide_spec("1–3, 8") == frozenset({1, 2, 3, 8})
    assert format_slide_range({2, 4, 5, 6}) == "2, 4–6"
    # No selection means the whole deck, and must not raise.
    assert format_slide_range(None) == ""
    assert format_slide_range(frozenset()) == ""
    assert resolve_slides(spec="2,4-6") == frozenset({2, 4, 5, 6})
    assert wants_slide(3, frozenset({2, 4, 5, 6})) is False
    assert wants_slide(4, frozenset({2, 4, 5, 6})) is True


def test_plan_only_the_requested_slide():
    recipe = recipe_from_cover(Rect(0, 0, 7680, 1080))
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [_item(kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080)],
            },
            {
                "number": 2,
                "items": [
                    _item(kindIndex=0, kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080),
                    _item(kindIndex=0, kind="movie", fileName="PIN DROP WAVE-1.mov", x=3815, y=515, w=50, h=50),
                ],
            },
        ],
    }
    only_two = plan_payload_transforms(wall, recipe, slide_range=(2, 2))
    assert {t.slide_number for t in only_two} == {2}
    assert summarize_plan(only_two)["pin"] == 1


def test_cover_rect_fills_16x9():
    dst = cover_rect(Rect(0, 0, 7680, 1080), 1920, 1080)
    assert dst.h == 1080
    assert dst.w == 7680
    assert item_center({"x": dst.x, "y": dst.y, "w": dst.w, "h": dst.h})[0] == 960


def test_cg_layout_name_adds_16x9_suffix():
    from obed_edom.map_remap import cg_layout_name

    assert cg_layout_name("MAP BLANK") == "MAP BLANK (16:9)"
    assert cg_layout_name("BLANK") == "BLANK (16:9)"
    assert cg_layout_name("MAP BLANK (16:9)") == "MAP BLANK (16:9)"
    assert cg_layout_name("") == ""


def test_learn_recipe_uses_template_slide_with_matching_map_layers():
    """Empty_Map slide 1 is a photo; the 21-layer map is later. Pair that one."""
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=4073, y=748, w=306, h=295),
                    _item(kind="shape", x=3563, y=255, w=11, h=11),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=-126, y=-14, w=787, h=1154),
                ],
            },
            {
                "number": 2,
                "items": [],
            },
            {
                "number": 3,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=1032, y=778, w=306, h=295),
                ],
            },
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["source"] == "template-layout"
    assert abs(recipe["mapDst"]["x"] - 11) < 1
    assert abs(recipe["mapDst"]["w"] - 1248) < 1
    assert abs(recipe["mapDst"]["h"] - 771) < 1
    pin = next(t for t in plan_payload_transforms(wall, recipe) if t.role == "pin")
    assert abs(pin.x - (3563 - 3041)) < 1


def test_list_sample_uses_one_line_church_name_font():
    from obed_edom.map_remap import template_list_sample

    slides = [
        {
            "items": [
                _item(kind="text", text="CHC Aaliana", x=39, y=527, w=101, h=26, size=20),
                _item(kind="text", text="CHC Prai\nCHC Aliwal\nCHC Bohol", x=1400, y=40, w=400, h=200, size=42),
            ]
        }
    ]
    font, sample = template_list_sample(slides)
    assert font == 20
    assert sample is not None
    assert abs(sample.x - 39) < 1


def test_church_lists_use_sample_font_and_pack_in_gutter():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="text", text="Global Missions", x=2147, y=52, w=537, h=124, size=100),
                    _item(kind="text", text="CHC Zui Si\nCHC Zwechipen", x=6946, y=9, w=474, h=954, size=42),
                    _item(kind="text", text="CHC Aaliana\nCHC Aliwal", x=262, y=9, w=423, h=954, size=42),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(kind="text", text="Global Missions", x=135, y=67, w=271, h=64, size=50),
                    _item(kind="text", text="CHC Aaliana", x=39, y=527, w=101, h=26, size=20),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["listFontSize"] == 20
    assert recipe["titleFontSize"] == 50
    assert abs(recipe["titleDst"]["x"] - 135) < 1
    transforms = plan_payload_transforms(wall, recipe, include_lists=True)
    lists = [t for t in transforms if t.role == "list"]
    assert len(lists) == 2
    assert all(t.font_size == 20 for t in lists)
    assert all(abs(t.h - 954 * (20 / 42)) < 2 for t in lists)
    title = next(t for t in transforms if t.role == "title")
    assert abs(title.x - 135) < 1
    assert title.font_size == 50
    # Rightmost wall column is placed first, against the right edge.
    rightmost = max(lists, key=lambda t: t.x)
    assert rightmost.x + rightmost.w <= 1920 + 1
    assert rightmost.x >= 1920 - 16 - rightmost.w - 1
    # Both columns fit in the ~640px gutter to the right of the map.
    map_right = 11 + 1248
    assert all(t.x + 1 >= map_right for t in lists)


def test_pack_columns_steps_left_when_taller_than_frame():
    from obed_edom.map_remap import pack_columns_from_right

    boxes = [Rect(0, 0, 200, 500), Rect(0, 0, 200, 500), Rect(0, 0, 180, 400)]
    placed = pack_columns_from_right(boxes, 1920, 1080, Rect(11, 18, 1248, 771))
    assert len(placed) == 3
    assert placed[0].x > placed[2].x
    assert placed[0].y < placed[1].y


def test_match_character_style_prefers_font_family_then_size():
    from obed_edom.map_remap import match_character_style

    styles = [
        {"font": "Amplitude-Regular", "size": 20, "text": "CHC Aaliana"},
        {"font": "AmplitudeCond-Medium", "size": 50, "text": "Global Missions"},
    ]
    taiwan = match_character_style(
        _item(kind="text", text="Taiwan", size=100, font="AmplitudeCond-Medium"),
        styles,
    )
    assert taiwan is not None
    assert taiwan["size"] == 50
    assert taiwan["font"] == "AmplitudeCond-Medium"
    chc = match_character_style(
        _item(kind="text", text="CHC Tai Chung", size=40, font="Amplitude-Bold"),
        styles,
    )
    assert chc is None


def test_match_character_style_uses_colour_when_face_matches():
    from obed_edom.map_remap import match_character_style

    red = [0.987, 0.222, 0.201]
    white = [1.0, 1.0, 1.0]
    styles = [
        {"font": "Amplitude-Regular", "size": 20, "color": red, "text": "CHC Aaliana"},
        {"font": "Amplitude-Regular", "size": 32, "color": white, "text": "UPDATE"},
    ]
    picked = match_character_style(
        _item(kind="text", text="UPDATE", size=83, font="Amplitude-Regular", color=white),
        styles,
    )
    assert picked is not None
    assert picked["size"] == 32
    assert picked["color"] == white


def test_reuse_duplicates_donor_then_only_text_delta():
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    wall = {
        "slides": [
            {
                "number": 2,
                "items": [
                    map_img,
                    *pins,
                    _item(kind="text", text="CHC Zui Si\nCHC Zwechipen", x=6946, y=9, w=474, h=954, size=42),
                ],
            },
            {
                "number": 3,
                "items": [
                    dict(map_img),
                    *[dict(p) for p in pins],
                    _item(kind="text", text="CHC Aaliana", x=262, y=9, w=215, h=58, size=42),
                ],
            },
            {
                "number": 4,
                "items": [
                    dict(map_img),
                    *[dict(p) for p in pins],
                    _item(kind="text", text="CHC Aaliana", x=262, y=9, w=180, h=40, size=30),
                ],
            },
            {
                "number": 8,
                "items": [
                    dict(map_img),
                    *[dict(p) for p in pins],
                    _item(kind="text", text="Global Missions", x=2147, y=52, w=537, h=124, size=100),
                ],
            },
            {
                "number": 9,
                "items": [
                    dict(map_img),
                    *[dict(p) for p in pins],
                    _item(kind="text", text="Global Missions", x=2147, y=52, w=537, h=124, size=100),
                ],
            },
        ]
    }
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [])}
    assert jobs[3]["from"] == 2
    assert jobs[3]["persist"] >= 40
    assert any(r["kind"] == "text" for r in jobs[3]["remove"])
    assert any(a.get("matchText") == "CHC Aaliana" for a in jobs[3]["add"])
    assert jobs[3]["mutate"] == []
    assert jobs[4]["from"] == 3
    assert jobs[4]["add"] == []
    assert jobs[4]["mutate"][0]["matchText"] == "CHC Aaliana"
    assert jobs[9]["from"] == 8
    assert jobs[9]["add"] == []
    assert jobs[9]["remove"] == []


def test_unpaired_text_resizes_when_swatch_face_differs():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=-8400, y=-4070, w=20000, h=14934),
                    _item(kind="image", fileName="pasted-image.pdf", x=2695, y=-15, w=787, h=1154),
                    _item(kind="image", fileName="IMG_7198.JPG", x=3121, y=-78, w=2720, h=1240),
                    _item(
                        kind="text",
                        text="Taiwan",
                        x=2458,
                        y=51,
                        w=248,
                        h=124,
                        size=100,
                        font="AmplitudeCond-Medium",
                    ),
                    _item(
                        kind="text",
                        text="CHC Tai Chung",
                        x=2751,
                        y=280,
                        w=257,
                        h=52,
                        size=40,
                        font="Amplitude-Bold",
                    ),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=-11221, y=-4069, w=20000, h=14934),
                    _item(kind="image", fileName="pasted-image.pdf", x=-153, y=-11, w=787, h=1154),
                ],
            },
            {
                "number": 2,
                "items": [
                    _item(kind="text", text="CHC Aaliana", x=39, y=527, w=101, h=26, size=20, font="Amplitude-Regular"),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            },
        ],
    }
    recipe = learn_recipe(wall, template)
    styles = recipe.get("characterStyles") or []
    assert any(s["size"] == 50 and "AmplitudeCond" in s["font"] for s in styles)
    transforms = plan_payload_transforms(wall, recipe, include_lists=True, template=template)
    taiwan = next(t for t in transforms if t.role == "other" and abs((t.font_size or 0) - 50) < 0.1)
    assert taiwan.font == "AmplitudeCond-Medium"
    # Photo crop translate is ~-2848; Taiwan stays with the photo, not packed as a list.
    assert taiwan.x < 2458
    chc = next(t for t in transforms if t.kind == "text" and t.font != "AmplitudeCond-Medium")
    assert chc.font is None
    assert chc.color is None
    assert chc.font_size != 20
    assert chc.font_size is not None and chc.font_size < 25
    photo = next(t for t in transforms if 2000 < t.w < 4000)
    assert abs(photo.x - (3121 - 2848)) < 40


def test_resized_leftover_image_gets_its_own_affine():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 5,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=1992, y=52, w=124, h=124),
                    _item(kind="shape", x=3563, y=255, w=11, h=11),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 3,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=31, y=59, w=80, h=80),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    transforms = plan_payload_transforms(wall, recipe, template=template)
    globe = next(t for t in transforms if abs(t.w - 80) < 2 and abs(t.h - 80) < 2)
    # 124→80 at (31, 59)
    assert abs(globe.w - 80) < 2
    assert abs(globe.x - 31) < 2
    pin = next(t for t in transforms if t.role == "pin")
    assert abs(pin.x - (3563 - 3041)) < 2


def test_title_badge_follows_globe_not_map():
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 5,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=1992, y=52, w=124, h=124),
                    _item(kind="shape", x=1960, y=30, w=520, h=160),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=2147,
                        y=52,
                        w=537,
                        h=124,
                        size=100,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 3,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=31, y=59, w=80, h=80),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    transforms = plan_payload_transforms(wall, recipe, template=template)
    badge = next(t for t in transforms if t.kind == "shape" and t.w > 50)
    assert badge.x > -40
    assert badge.x < 500
    title = next(t for t in transforms if t.role == "title")
    assert abs(title.x - 135) < 1


def test_reuse_strips_builds_missing_on_dest():
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [
        _item(kind="shape", x=3563 + i * 13, y=255, w=11, h=11, buildCount=1 if i == 0 else 0)
        for i in range(40)
    ]
    dest_pins = [
        _item(kind="shape", x=3563 + i * 13, y=255, w=11, h=11, buildCount=0) for i in range(40)
    ]
    wall = {
        "slides": [
            {"number": 2, "items": [map_img, *pins]},
            {"number": 5, "items": [dict(map_img), *dest_pins]},
        ]
    }
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [])}
    assert jobs[5]["from"] == 2
    assert any(r["kind"] == "shape" for r in jobs[5]["stripBuilds"])


def test_reuse_strips_mutated_text_before_pasting_the_delta():
    """A slide with both an add and a mutate pastes with select-all, so the
    mutated text has to be stripped from the original or the donor copy ends up
    carrying two of it."""
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    wall = {
        "slides": [
            {
                "number": 2,
                "items": [
                    map_img,
                    *pins,
                    _item(kind="text", text="183 CHC Churches", x=262, y=9, w=215, h=58, size=42),
                ],
            },
            {
                "number": 3,
                "items": [
                    dict(map_img),
                    *[dict(p) for p in pins],
                    # Same words, new geometry -> mutate the donor's copy.
                    _item(kind="text", text="183 CHC Churches", x=800, y=400, w=180, h=40, size=30),
                    # Brand new words -> pasted across as the delta.
                    _item(kind="text", text="26 Total", x=300, y=500, w=200, h=60, size=42),
                ],
            },
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert [a.get("matchText") for a in job["add"]] == ["26 Total"]
    assert [m.get("matchText") for m in job["mutate"]] == ["183 CHC Churches"]
    # The mutated text is the slide's first text item, and the donor copy
    # already supplies it, so the select-all must not pick it up again.
    stripped = {(r["kind"], r["kindIndex"]) for r in job["strip"]}
    assert ("text", 0) in stripped


def test_badge_logo_and_plate_land_on_their_template_slots():
    """The template's badge is not a uniform shrink of the wall's — plate, logo
    and title each moved by their own ratio — so scaling by the title text box
    lands the logo and plate short. Place them on the template's rects."""
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 5,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="image", fileName="pasted-image.pdf", x=1992, y=52, w=124, h=124),
                    _item(kind="shape", x=1953, y=28, w=767, h=173),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=2147,
                        y=52,
                        w=537,
                        h=124,
                        size=100,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 3,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1067, h=659),
                    _item(kind="image", fileName="pasted-image.pdf", x=31, y=59, w=80, h=80),
                    _item(kind="shape", x=17, y=37, w=411, h=123),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["badgeSlots"]["image:0"] == {"x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0}
    assert recipe["badgeSlots"]["shape:0"] == {"x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0}

    transforms = plan_payload_transforms(wall, recipe, template=template)
    # The title text box shrinks 537 -> 271, so the affine alone would give the
    # 124px logo 63px and the 767px plate 387px.
    logo = next(t for t in transforms if t.kind == "image" and t.w < 200)
    assert (round(logo.x), round(logo.y), round(logo.w), round(logo.h)) == (31, 59, 80, 80)
    plate = next(t for t in transforms if t.kind == "shape" and t.w > 50)
    assert (round(plate.x), round(plate.y), round(plate.w), round(plate.h)) == (17, 37, 411, 123)


def test_rank_pairing_drops_scales_nothing_else_agrees_with():
    """Rank pairing walks both sides by area, so once the wall runs past the end
    of the template it pairs whatever is left. Those tail pairs have to go, or a
    map inset ends up wearing the badge logo's affine."""
    from obed_edom.map_remap import drop_outlier_pairs, item_rect, pair_by_area_rank

    wall = [
        _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
        _item(kind="image", fileName="pasted-image.pdf", x=3061, y=-6, w=1232, h=761),
        _item(kind="image", fileName="pasted-image.pdf", x=3547, y=15, w=634, h=425),
        _item(kind="image", fileName="pasted-image.pdf", x=3489, y=245, w=306, h=316),
        _item(kind="image", fileName="pasted-image.pdf", x=4073, y=748, w=306, h=295),
    ]
    template = [
        _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1067, h=659),
        _item(kind="image", fileName="pasted-image.pdf", x=19, y=23, w=1053, h=651),
        _item(kind="image", fileName="pasted-image.pdf", x=599, y=309, w=473, h=364),
        _item(kind="image", fileName="pasted-image.pdf", x=31, y=59, w=80, h=80),
        _item(kind="image", fileName="pasted-image.pdf", x=227, y=322, w=11, h=11),
    ]
    ranked = pair_by_area_rank(wall, template)
    assert len(ranked) == 5
    kept = drop_outlier_pairs(ranked)
    scales = [round(item_rect(d).w / item_rect(s).w, 3) for s, d in kept]
    # 0.855 x2 and 0.746 survive; the 80x80 (0.261) and 11x11 (0.036) do not.
    assert scales == [0.855, 0.855, 0.746]


def test_outlier_pairs_left_alone_when_there_is_no_consensus():
    from obed_edom.map_remap import drop_outlier_pairs

    pairs = [
        (_item(kind="image", w=1000, h=600), _item(kind="image", w=500, h=300)),
        (_item(kind="image", w=200, h=200), _item(kind="image", w=20, h=20)),
    ]
    assert drop_outlier_pairs(pairs) == pairs


def test_divider_lands_on_the_template_rule():
    """The wall's rule sits in a gutter the CG crop excludes, so the affine puts
    it off-canvas and the meridian rescue re-places it on the document scale —
    near enough in x to look deliberate, wrong length. The template says where."""
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 4,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(kind="line", x=2587, y=223, w=658, h=0, start=[2587, 881], end=[2587, 223]),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=2147,
                        y=52,
                        w=537,
                        h=124,
                        size=100,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 12,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1067, h=659),
                    _item(kind="line", x=480, y=621, w=383, h=0, start=[480, 1004], end=[480, 621]),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="AmplitudeCond-Medium",
                    ),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe["lineSlots"][0]["start"] == [480.0, 1004.0]
    rule = next(t for t in plan_payload_transforms(wall, recipe, template=template) if t.kind == "line")
    assert rule.start == (480.0, 1004.0)
    assert rule.end == (480.0, 621.0)
    assert (round(rule.x), round(rule.y), round(rule.h)) == (480, 621, 383)
