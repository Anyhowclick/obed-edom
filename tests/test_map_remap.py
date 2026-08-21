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
    score = score_against_gold(transforms, gold)
    assert score["pinPairs"] == 1
    assert score["pinRmse"] < 5

    with_lists = plan_payload_transforms(wall, recipe, include_lists=True)
    assert summarize_plan(with_lists)["list"] == 1
    name = next(t for t in with_lists if t.role == "list")
    # Same map affine as the image (identity scale + crop offset), not a squash.
    assert abs(name.x - 3120) < 1
    assert abs(name.y - 80) < 1
    assert abs(name.w - 400) < 1
    assert abs(name.h - 40) < 1


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


def test_resolve_slide_range_single_and_span():
    from obed_edom.map_remap import MVP_MAP_SLIDE, resolve_slide_range

    assert resolve_slide_range(2, None) == (2, 2)
    assert resolve_slide_range(None, 2) == (2, 2)
    assert resolve_slide_range(1, 9) == (1, 9)
    assert resolve_slide_range(None, None) is None
    assert resolve_slide_range(None, None, default=(MVP_MAP_SLIDE, MVP_MAP_SLIDE)) == (2, 2)


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
