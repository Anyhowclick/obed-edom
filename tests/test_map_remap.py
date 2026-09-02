"""CG resizer planner (obed_edom.map_remap).

Keynote traps this suite locks (kept out of the production file):
- Setting size yanks the object to (0,0); apply size before position.
- Keynote does not take line endpoints; a line's width is its length and height
  is 0 whichever way it runs. Send size as length×0, not the bounding box.
- Keynote 15.3.1 exposes no arrange/z-order; moving an object does not restack.
  Apply order is stacking only on generate, which creates objects.
- Reuse pastes with select-all: everything the donor copy already carries must
  leave the original first, not merely the objects the planner looked at.
- A badge plate colour mismatch is an in-map label, not the badge; snapping onto
  it drags the cyan badge into the map.
- Church-name lists are ≥6 short boxes; map labels come 1–5 at a time. An
  unticked include-lists must drop the whole list even where it sits over the map.
- Centre-panel panoramas (~2 CG frames wide) frame 1:1; thumbnails on them ride
  the panel affine and must not vote on the crop.
- Judge a framing on the artwork it is about, not whole-slide extent (side-panel
  lists punish a true-size map). Rank on agreement count, not raw pair total.
- Cover the centre panel when no template framing pairs, not the whole wall.
- Never drop text; least-overlapping placement + report the overlap.
- Off-slide leftovers must never teach an affine.
"""
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
    on_canvas_fraction,
    _recipe_reusing_affine,
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
                    # A framing this page can actually take, so the pin is honoured
                    # rather than overridden as a collapse — the degenerate case has
                    # its own test below.
                    _item(index=0, kind="image", fileName="map BG-1.png", x=10, y=400, w=1900, h=267),
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
    assert row["pinOverridden"] is False
    assert "fitted" in row


def test_a_degenerate_pin_reuses_an_adjacent_same_pin_siblings_affine():
    """Magic-move siblings pinned to one framing keep the map 1:1 across the morph.

    Slide 1's own art pairs cleanly; slides 2 and 3 are full-bleed photos that pair
    to a sliver on their own. All three carry the same pin, so 2 reuses 1's affine
    and 3 reuses 2's — the same transform down the sequence, not each page's own
    shifted cover."""
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [_item(index=0, kind="image", fileName="m.pdf", x=-2880, y=0, w=7680, h=1080)]},
            # A plain map slot the first slide pairs cleanly.
            {"number": 2, "items": [_item(index=0, kind="image", fileName="m.pdf", x=200, y=0, w=480, h=135)]},
        ],
    }
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [_item(index=0, kind="image", fileName="m.pdf", x=3000, y=0, w=480, h=135)]},
            {"number": 2, "items": [_item(index=0, kind="image", fileName="China.png", x=1920, y=0, w=3840, h=1080)]},
            {"number": 3, "items": [_item(index=0, kind="image", fileName="China.png", x=1920, y=0, w=3840, h=1080)]},
        ],
    }
    rows: list[dict] = []
    plan_payload_transforms(
        wall, learn_recipe(wall, template), template=template,
        framing_overrides={1: 2, 2: 2, 3: 2}, framing_report=rows,
    )
    assert rows[0]["reusedSibling"] is False  # slide 1 pairs on its own
    assert rows[1]["source"] == "sibling-affine" and rows[1]["reusedSibling"] is True
    assert rows[2]["source"] == "sibling-affine" and rows[2]["reusedSibling"] is True

    from obed_edom.map_remap import frame_affine
    a1 = frame_affine(learn_recipe({"slideWidth": 7680, "slideHeight": 1080, "slides": [wall["slides"][0]]}, template, template_slide=2))
    a2 = frame_affine(_recipe_reusing_affine(wall["slides"][1], learn_recipe({"slideWidth": 7680, "slideHeight": 1080, "slides": [wall["slides"][1]]}, template, template_slide=2), a1, 7680, 1080))
    assert abs(a2.s - a1.s) < 1e-6 and abs(a2.tx - a1.tx) < 1e-6  # identical transform


def test_a_non_adjacent_or_differently_pinned_slide_does_not_reuse():
    """Reuse is only for adjacent slides carrying the same pin — never inferred."""
    template = {
        "slideWidth": 1920, "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [_item(index=0, kind="image", fileName="m.pdf", x=-2880, y=0, w=7680, h=1080)]},
            {"number": 2, "items": [_item(index=0, kind="image", fileName="m.pdf", x=200, y=100, w=1000, h=600)]},
        ],
    }
    wall = {
        "slideWidth": 7680, "slideHeight": 1080,
        "slides": [
            {"number": 1, "items": [_item(index=0, kind="image", fileName="m.pdf", x=2000, y=100, w=1000, h=600)]},
            {"number": 2, "skipped": True, "items": []},  # a gap breaks adjacency
            {"number": 3, "items": [_item(index=0, kind="image", fileName="China.png", x=1920, y=0, w=3840, h=1080)]},
        ],
    }
    rows: list[dict] = []
    plan_payload_transforms(
        wall, learn_recipe(wall, template), template=template,
        framing_overrides={1: 2, 3: 2}, framing_report=rows, skipped_slides=[],
    )
    slide3 = next(r for r in rows if r["slide"] == 3)
    assert slide3["reusedSibling"] is False  # slide 1 is not adjacent to slide 3


def test_a_degenerate_pin_falls_back_to_the_pages_own_framing():
    """A pin that collapses the page to a sliver is overridden by its own framing.

    A small-map layout dropped onto a full-bleed page shrinks it below any useful
    scale. Rather than honour that and letterbox, the page's automatic framing —
    the cover it was reaching for — is used, and the override is reported so it is
    visible rather than silent."""
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
                    # 1280 wide against a 7680 wall is s≈0.17 — a degenerate collapse.
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=100, w=1280, h=720),
                ],
            },
        ],
    }
    auto = learn_recipe(wall, template)
    report: list[dict] = []
    fitted: list[int] = []
    plan_payload_transforms(
        wall,
        learn_recipe(wall, template),
        template=template,
        framing_overrides={1: 2},
        framing_report=report,
        fitted_slides=fitted,
    )
    row = report[0]
    assert row["requested"] == 2  # the pin is still recorded as tried
    assert row["templateSlide"] == auto["templateSlide"]  # but the page's own framing was used
    assert row["pinOverridden"] is True
    assert row["confirmed"] is False
    assert row["fitted"] is False  # covered, not letterboxed
    assert fitted == []


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
    # Sending no size at all used to be the guard against the bounding box zeroing
    # the length. It also left Keynote's slide-size scale in place, so the rule
    # came out 164px — the wall's 658 at 0.25. Send the length, in Keynote's own
    # convention of width-is-length.
    sent = planned.as_dict()
    assert sent["w"] == round(abs(planned.end[1] - planned.start[1]), 2)
    assert sent["h"] == 0.0


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


def test_reuse_strips_hidden_side_panel_delta_before_the_paste():
    # A reuse TARGET whose delta includes a side-panel church-name list the planner
    # marked role="hide". It must NOT ride the select-all paste back onto the finished
    # slide: it is filtered out of `add` (never repositioned) AND it must land in `strip`
    # so it is deleted from the original before the paste. Regression for the church list
    # reappearing on slide 125 despite "keep side panel content" being off.
    from obed_edom.map_remap import ItemTransform, plan_slide_reuses

    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    title = _item(kind="text", kindIndex=0, text="Global Missions", x=2147, y=52, w=537, h=124, size=100)
    # Slide 3's delta over the donor: a GENUINE new photo (kept) AND a side-panel church
    # list the planner hid. Both are in `add`; only the hidden one must be stripped.
    photo = _item(kind="image", kindIndex=1, fileName="CHC-New.png", x=3200, y=300, w=278, h=88)
    church = _item(kind="text", kindIndex=1, text="CHC Foo\nCHC Bar", x=6946, y=9, w=474, h=954, size=42)
    wall = {
        "slides": [
            {"number": 2, "items": [map_img, *pins, dict(title)]},
            {"number": 3, "items": [dict(map_img), *[dict(p) for p in pins], dict(title), photo, church]},
        ]
    }
    # The planner hid the church list (side panel, side content off); the photo has no
    # hide transform, so it stays a real delta.
    hide = ItemTransform(
        slide_number=3, item_index=42, kind="text", kind_index=1,
        x=6946, y=9, w=474, h=954, role="hide",
    )
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [hide])}
    job = jobs[3]
    assert job["from"] == 2
    # The genuine photo IS a real add and must NOT be stripped (over-strip guard)…
    assert any(a.get("kind") == "image" and a.get("kindIndex") == 1 for a in job["add"])
    assert not any(r.get("kind") == "image" and r.get("kindIndex") == 1 for r in job["strip"])
    # …the hidden church list is never re-added (filtered from add_specs)…
    assert not any(a.get("kind") == "text" and a.get("kindIndex") == 1 for a in job["add"])
    # …and it IS stripped from the original, so the select-all paste can't carry it back.
    assert any(r.get("kind") == "text" and r.get("kindIndex") == 1 for r in job["strip"])


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


def test_unpaired_text_keeps_source_colour_takes_only_template_size():
    """Rule: unpaired LW text keeps its source font family and colour. A matched
    template swatch lends its size only — never its colour. A white verse on the
    wall must stay white even when its face matches a cyan template swatch."""
    white = [1.0, 1.0, 1.0]
    cyan = [0.125, 0.996, 0.996]
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=-8400, y=-4070, w=20000, h=14934),
                    _item(kind="image", fileName="scene.JPG", x=3121, y=-78, w=2720, h=1240),
                    _item(
                        kind="text",
                        text="Then Moses said to Aaron",
                        x=2458,
                        y=51,
                        w=248,
                        h=124,
                        size=100,
                        font="Helvetica",
                        color=white,
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
                    _item(kind="image", fileName="scene.JPG", x=-153, y=-11, w=787, h=1154),
                ],
            },
            {
                "number": 2,
                "items": [
                    _item(
                        kind="text",
                        text="NUMBERS 16",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="Helvetica",
                        color=cyan,
                    ),
                ],
            },
        ],
    }
    recipe = learn_recipe(wall, template)
    styles = recipe.get("characterStyles") or []
    assert any(abs(s["size"] - 50) < 0.1 and "helvetica" in (s["font"] or "").lower() for s in styles)
    transforms = plan_payload_transforms(wall, recipe, include_lists=True, template=template)
    verse = next(t for t in transforms if t.role == "other" and t.kind == "text")
    # Size comes from the swatch...
    assert verse.font_size is not None and abs(verse.font_size - 50) < 0.1
    # ...face stays the source's (equal to the swatch by construction)...
    assert verse.font == "Helvetica"
    # ...and the colour is never repainted: None means Keynote leaves the source
    # white in place rather than writing the swatch's cyan.
    assert verse.color is None


def test_title_keeps_source_font_and_colour_takes_template_position_and_size():
    """The rule reaches the title too. It keeps its source face and colour and
    takes only the template's position (titleDst) and size (titleFontSize). The
    template's own title font/colour are recorded on the recipe but never applied
    — a white title must not turn the template's cyan."""
    white = [1.0, 1.0, 1.0]
    cyan = [0.125, 0.996, 0.996]
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=2147,
                        y=52,
                        w=537,
                        h=124,
                        size=100,
                        font="AzoSans-Bold",
                        color=white,
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
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1248, h=771),
                    _item(
                        kind="text",
                        text="Global Missions",
                        x=135,
                        y=67,
                        w=271,
                        h=64,
                        size=50,
                        font="Helvetica",
                        color=cyan,
                    ),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    # The template's title styling is recorded on the recipe...
    assert recipe["titleFont"] == "Helvetica"
    assert recipe.get("titleColor") is not None
    assert recipe["titleFontSize"] == 50
    transforms = plan_payload_transforms(wall, recipe, include_lists=True)
    title = next(t for t in transforms if t.role == "title")
    # ...position and size come from the template...
    assert abs(title.x - 135) < 1
    assert title.font_size == 50
    # ...but the face stays the source's and the colour is never repainted.
    assert title.font == "AzoSans-Bold"
    assert title.color is None


def test_centre_panel_panorama_frames_one_to_one_over_overlaid_thumbnails():
    """A map spanning the centre panel is shown 1:1. A grid of thumbnails laid on
    top must not drag the frame down to their scale, the way one slide of a
    transition (map alone) should match the next (map plus a photo grid). The
    overlays are only held out of the framing choice; they still ride the affine."""
    from obed_edom.map_remap import centre_panel_image, frame_affine

    panel = _item(kind="image", fileName="China.png", x=1920, y=0, w=3840, h=1080)
    thumbs = [
        _item(
            kind="image",
            fileName=f"upg{i}.png",
            x=2044 + (i % 5) * 314,
            y=166 + (i // 5) * 346,
            w=279,
            h=315,
        )
        for i in range(10)
    ]
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [panel, *thumbs]}],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            # A cover slide: its own centre panel, which the wall panel frames against.
            {"number": 1, "items": [_item(kind="image", fileName="China.png", x=-338, y=0, w=3840, h=1080)]},
            # A thumbnail-grid slide the raw agreement count would otherwise prefer.
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName=f"t{i}.png", x=100 + i * 150, y=200, w=150, h=169)
                    for i in range(6)
                ],
            },
        ],
    }
    assert centre_panel_image(wall["slides"][0]["items"], 7680, 1080, 1920, 1080) is not None
    recipe = learn_recipe(wall, template)
    # 1:1, not the thumbnail scale it would take if the grid drove the framing.
    assert abs(frame_affine(recipe).s - 1.0) < 0.05
    transforms = plan_payload_transforms(wall, recipe, include_lists=True, template=template)
    placed = [t for t in transforms if t.kind == "image" and t.role != "hide"]
    # Every overlay is still placed — held out of the crop choice, not dropped.
    assert len(placed) >= 10


def test_badge_ignores_a_differently_coloured_template_label_and_borrows_the_real_slot():
    """A plain-map layout's in-map label must not capture the source badge.

    Template slide 1 is a map whose only text is a white label sitting in the
    middle of it. The source's cyan badge (a plate, a logo and its word) must not
    snap onto that white label mid-map; it borrows the deck's real badge slot from
    slide 2, whose plate is the badge's own colour, and lands top-left."""
    cyan = [0.13, 1.0, 1.0]
    white = [1.0, 1.0, 1.0]
    # Source: a top-left cyan badge (plate + logo + word) over a wide map.
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="China.pdf", x=2200, y=-100, w=3600, h=1280),
                    _item(kind="shape", x=1953, y=28, w=740, h=173, color=cyan),
                    _item(kind="image", fileName="globe.pdf", x=1992, y=52, w=124, h=124),
                    _item(kind="text", text="China", x=2458, y=51, w=198, h=124, size=60, color=cyan),
                ],
            }
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            # A plain map with a white in-map province label, like template 10.
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="China.pdf", x=226, y=61, w=1364, h=947),
                    _item(kind="shape", x=628, y=537, w=212, h=46, color=white),
                    _item(kind="text", text="Province", x=638, y=537, w=192, h=46, size=20, color=white),
                ],
            },
            # The deck's real badge slot: a cyan plate with a logo, top-left.
            {
                "number": 2,
                "items": [
                    _item(kind="image", fileName="China.pdf", x=226, y=61, w=1364, h=947),
                    _item(kind="shape", x=17, y=37, w=411, h=123, color=cyan),
                    _item(kind="image", fileName="globe.pdf", x=31, y=59, w=80, h=80),
                    _item(kind="text", text="China", x=135, y=67, w=271, h=64, size=40, color=cyan),
                ],
            },
        ],
    }
    recipe = learn_recipe(wall, template, template_slide=1)  # pin the plain-map layout
    # The badge home is slide 2's cyan plate, not slide 1's white label mid-map.
    assert recipe.get("badgePlateDst") == {"x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0}
    plate = next(t for t in plan_slide_transforms(wall["slides"][0], recipe, wall_size=(7680, 1080))
                 if t.kind == "shape" and t.w > 300)
    assert 0 <= plate.x + plate.w / 2 <= 1920 and plate.y + plate.h / 2 <= 300  # top-left, on-frame


def test_scripture_body_text_snaps_to_template_box_keeping_source_style():
    """A verse paragraph lands in the template's body box at the template's size,
    rather than keeping its wall width at the scene's 1:1 scale. Source font and
    colour are kept, like the title."""
    verse = (
        "46 Then Moses said to Aaron, Take your censer and put incense in it, "
        "along with burning coals from the altar, and hurry to the assembly."
    )
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
                    _item(kind="shape", x=3395, y=21, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=3395, y=21, w=662, h=92, size=60, font="AzoSans-Bold"),
                    _item(kind="text", text=verse, x=3395, y=89, w=2328, h=351, size=46.67, font="AzoSans-Regular"),
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
                    _item(kind="image", fileName="Wilderness.png", x=-544, y=0, w=3840, h=1080),
                    _item(kind="shape", x=702, y=49, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=702, y=49, w=662, h=92, size=60, font="AzoSans-Bold"),
                    _item(kind="text", text=verse, x=698, y=119, w=1140, h=675, size=46.67, font="AzoSans-Regular"),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe.get("bodyTextDst") == {"x": 698.0, "y": 119.0, "w": 1140.0, "h": 675.0}
    transforms = plan_payload_transforms(wall, recipe, include_lists=True, template=template)
    body = next(t for t in transforms if t.kind == "text" and t.role == "other")
    assert (round(body.x), round(body.y), round(body.w), round(body.h)) == (698, 119, 1140, 675)
    assert abs((body.font_size or 0) - 46.67) < 0.1
    # Font is left unset so the box keeps its own runs (bold, coloured emphasis
    # the inspect cannot see); setting the single face would flatten them.
    assert body.font is None
    assert body.color is None  # source colour kept


def test_full_bleed_cover_is_not_vetoed_by_reflowed_body_and_cropped_side_content():
    """A correct centre-panel cover must not fall back to fit-to-frame just because
    its verse body, emphasis copies and a side-panel graphic sit off the raw frame.

    The body reflows into the template box and the side graphic is cropped by the
    16:9 crop on purpose, so where the affine would drop them is no evidence the
    framing fails. `on_canvas_fraction` judged them anyway and letterboxed a page
    that covers fine — this pins that it does not."""
    verse = (
        "47 So Aaron did as Moses said, and ran into the midst of the assembly. "
        "The plague had already started among the people, but Aaron offered the "
        "incense and made atonement for them."
    )
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
                    _item(kind="shape", x=3395, y=21, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=3395, y=21, w=662, h=92, size=60, font="AzoSans-Bold"),
                    # Body set for the 3840-wide wall panel: its raw centre is off
                    # the 1920 frame until it reflows into bodyTextDst.
                    _item(kind="text", text=verse, x=3395, y=89, w=2328, h=351, size=46.67, font="AzoSans-Regular"),
                    # A sparkle emphasis copy of a body phrase, sitting over the body.
                    _item(kind="text", text="the plague", x=4378, y=337, w=676, h=98, size=46.67, font="AzoSans-Regular"),
                    # A side-panel graphic outside the centre crop — cropped by design.
                    _item(kind="image", fileName="Sidebar.png", x=6200, y=100, w=1200, h=880),
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
                    _item(kind="image", fileName="Wilderness.png", x=-544, y=0, w=3840, h=1080),
                    _item(kind="shape", x=702, y=49, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=702, y=49, w=662, h=92, size=60, font="AzoSans-Bold"),
                    _item(kind="text", text=verse, x=698, y=119, w=1140, h=675, size=46.67, font="AzoSans-Regular"),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe.get("source") == "template-cover"
    # Only the cover image is the affine's own artwork; it is on-frame, so the
    # page is not vetoed.
    assert on_canvas_fraction(wall["slides"][0], recipe, 7680, 1080) >= 0.5
    fitted: list[int] = []
    plan_payload_transforms(wall, recipe, include_lists=True, template=template, fitted_slides=fitted)
    assert fitted == []  # covered, not scaled to fit


def test_church_name_column_is_not_taken_for_a_body_paragraph():
    """A tall stack of church names is long like a verse but is a list, not a
    body — it keeps its own placement path and is never snapped to a body box."""
    from obed_edom.map_remap import slide_body_text_item

    slide = {
        "number": 1,
        "items": [
            _item(kind="text", text="Global Missions", x=2147, y=52, w=537, h=124, size=100),
            _item(
                kind="text",
                text="CHC Zui Si\nCHC Zwechipen\nCHC Sitiawan\nCHC Ipoh\nCHC Prai\nCHC Klang",
                x=6946,
                y=9,
                w=474,
                h=954,
                size=42,
            ),
        ],
    }
    assert slide_body_text_item(slide, (7680, 1080)) is None


def test_sparkle_overlay_takes_body_size_not_its_own_clamp():
    """An emphasis copy of body words (substring of the body, sitting over it)
    takes the body's final size so it stays on the words, rather than being
    clamped small on its own and drifting off them. A phrase that is a substring
    but does not overlap the body is left alone."""
    from obed_edom.map_remap import sparkle_overlays, slide_body_text_item

    verse = (
        "47 So Aaron did as Moses said and ran into the midst of the assembly. "
        "He stood between the living and the dead, and the plague stopped."
    )
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
                    _item(kind="shape", x=3395, y=21, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=3395, y=21, w=662, h=92, size=60, font="AzoSans-Bold"),
                    _item(kind="text", text=verse, x=3395, y=89, w=2328, h=351, size=46.67, font="AzoSans-Regular"),
                    # Emphasis copy: substring of the verse, sitting over the body box.
                    _item(kind="text", text="the living and the dead", x=3395, y=336, w=817, h=98, size=75, font="AzoSans-Bold"),
                    # Substring, but far off the body box — not an overlay.
                    _item(kind="text", text="the plague stopped", x=200, y=980, w=676, h=98, size=75, font="AzoSans-Bold"),
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
                    _item(kind="image", fileName="Wilderness.png", x=-544, y=0, w=3840, h=1080),
                    _item(kind="text", text="body sample text of a reasonable length here", x=698, y=119, w=1140, h=675, size=40, font="AzoSans-Regular"),
                ],
            }
        ],
    }
    s = wall["slides"][0]
    body = slide_body_text_item(s, (7680, 1080))
    overlays = sparkle_overlays(s, body)
    assert len(overlays) == 1  # only the overlapping substring, not the far one
    recipe = learn_recipe(wall, template)
    transforms = plan_payload_transforms(wall, recipe, include_lists=True, template=template)
    others = [t for t in transforms if t.role == "other" and t.kind == "text"]
    body_tf = max(others, key=lambda t: t.w * t.h)
    overlay_tf = next(t for t in others if t is not body_tf and 300 < t.w < 600)
    # The overlay takes the body's final size, not the 0.42 down-scale of its own 75.
    assert abs((overlay_tf.font_size or 0) - (body_tf.font_size or 0)) < 0.5
    assert overlay_tf.font_size and overlay_tf.font_size > 75 * 0.42 + 1


def test_coincident_group_deduped_but_images_kept():
    """A magic-move build's leftover second copy of a group is placed once. Two
    coincident images are both kept — stacked map layers are coincident on
    purpose and dropping one tears the map apart."""
    from obed_edom.map_remap import coincident_duplicate_ids

    items = [
        _item(kind="group", x=5770, y=-174, w=1923, h=1317, childCount=5),
        _item(kind="group", x=5771, y=-174, w=1923, h=1317, childCount=5),  # dup
        _item(kind="image", fileName="a.png", x=0, y=0, w=1364, h=947),
        _item(kind="image", fileName="b.png", x=0, y=0, w=1364, h=947),  # coincident layer
        _item(kind="group", x=100, y=100, w=200, h=200, childCount=2),  # different spot
    ]
    dup = coincident_duplicate_ids(items)
    assert len(dup) == 1  # one group dropped
    assert id(items[1]) in dup  # the second coincident group
    assert id(items[3]) not in dup  # the coincident image is kept


def test_coincident_dup_is_hidden_not_dropped_from_plan():
    """The leftover magic-move copy is pinned to zero opacity, not left un-planned.
    On the LW wall the canvas change scales every un-planned object into the frame,
    so a dropped duplicate reappears as a ghost beside the copy that was placed."""
    slide = {
        "number": 1,
        "items": [
            _item(kind="image", fileName="Building.png", x=1920, y=-126, w=3840, h=1250),
            _item(kind="group", x=5770, y=-174, w=1923, h=1317, childCount=5),  # side panel
            _item(kind="group", x=5771, y=-174, w=1923, h=1317, childCount=5),  # coincident dup
        ],
    }
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    template = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    recipe = learn_recipe(wall, template)
    out = plan_slide_transforms(slide, recipe, wall_size=(7680, 1080))
    groups = [t for t in out if t.kind == "group"]
    # Both the side-panel copy and its coincident duplicate are hidden; neither is
    # left un-planned to be scaled back on-frame.
    assert len(groups) == 2 and all(t.role == "hide" and t.opacity == 0.0 for t in groups)


def test_side_panel_content_is_dropped_when_side_content_is_not_kept():
    """On the LW wall, content wholly on a side panel is dropped unless side
    content is being kept; centre and boundary-straddling content stay."""
    from obed_edom.map_remap import is_side_panel_item

    left = _item(kind="text", text="CHC Left", x=200, y=100, w=300, h=60)  # side
    right = _item(kind="image", fileName="badge.png", x=6200, y=100, w=800, h=400)  # side
    straddle = _item(kind="image", fileName="panorama.png", x=1700, y=0, w=900, h=1080)  # crosses in
    centre = _item(kind="image", fileName="worldmap.png", x=2600, y=0, w=2400, h=1080)  # centre
    assert is_side_panel_item(left, 7680, 1080)
    assert is_side_panel_item(right, 7680, 1080)
    assert not is_side_panel_item(straddle, 7680, 1080)  # deemed inside
    assert not is_side_panel_item(centre, 7680, 1080)
    assert not is_side_panel_item(left, 1920, 1080)  # not the LW wall

    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [centre, left, right, straddle]}],
    }
    recipe = learn_recipe(wall, {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]})
    dropped = plan_slide_transforms(wall["slides"][0], recipe, wall_size=(7680, 1080))
    assert not any(t.kind == "text" and t.role != "hide" for t in dropped)  # side text dropped
    kept = plan_slide_transforms(wall["slides"][0], recipe, wall_size=(7680, 1080), include_lists=True)
    assert any(t.kind == "text" and t.role != "hide" for t in kept)  # kept when side content is kept


def test_side_content_whitelist_keeps_only_the_named_slide():
    """plan_payload_transforms drops side content by default and keeps it on the
    slides named in side_content_slides — the per-slide form of include_lists."""
    def slide(n):
        return {
            "number": n,
            "items": [
                _item(kind="image", fileName="worldmap.png", x=2600, y=0, w=2400, h=1080),  # centre
                _item(kind="text", text="CHC Left", x=200, y=100, w=300, h=60),  # side panel
            ],
        }

    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide(1), slide(2)]}
    template = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    recipe = learn_recipe(wall, template)

    def side_text_visible(transforms, number):
        return any(
            t.slide_number == number and t.kind == "text" and t.role != "hide"
            for t in transforms
        )

    # No whitelist: the side text is dropped on both slides.
    none = plan_payload_transforms(wall, recipe, template=template)
    assert not side_text_visible(none, 1) and not side_text_visible(none, 2)

    # Whitelist slide 2 only: it keeps its side text, slide 1 still drops it.
    picked = plan_payload_transforms(wall, recipe, template=template, side_content_slides={2})
    assert not side_text_visible(picked, 1)
    assert side_text_visible(picked, 2)


def test_church_summary_list_over_map_is_hidden_when_flag_off():
    """A church-name list is dropped when 'include lists' is off even where it
    sits over the map. The background test marks names over land as non-free, and
    they used to be left remapped in place; a slide of many names is a list, not a
    set of map labels. A slide with only a couple of labels keeps the old
    protection."""
    def church_slide(n_names):
        # Names over the centre map (x within 1920..5760) so this exercises the
        # summary-list rule, not the side-panel drop that has its own test.
        items = [_item(kind="image", fileName="worldmap.png", x=0, y=0, w=7680, h=1080)]
        for i in range(n_names):
            items.append(_item(kind="text", text=f"CHC Place{i}", x=3000, y=6 + i * 52, w=215, h=58, size=42))
        return {"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": items}]}

    from obed_edom.map_remap import is_list_item

    # Sanity: the names read as list items.
    many = church_slide(20)
    assert sum(1 for it in many["slides"][0]["items"] if is_list_item(it)) >= 6

    recipe = learn_recipe(many, {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]})
    # free_text_keys empty simulates a real run where every name sits over artwork.
    off = plan_slide_transforms(
        many["slides"][0], recipe, include_lists=False, wall_size=(7680, 1080), free_text_keys=set()
    )
    placed_names = [t for t in off if t.kind == "text" and t.role != "hide"]
    assert not placed_names  # the whole list is hidden, not remapped over the map

    # A couple of labels over artwork keep their protection (not a summary list).
    few = church_slide(2)
    recipe2 = learn_recipe(few, {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]})
    off2 = plan_slide_transforms(
        few["slides"][0], recipe2, include_lists=False, wall_size=(7680, 1080), free_text_keys=set()
    )
    kept = [t for t in off2 if t.kind == "text" and t.role != "hide"]
    assert kept  # few labels over artwork are not dropped


def test_off_screen_objects_are_hidden_not_left_alone():
    """An object wholly off the wall is pinned to zero opacity, not dropped from the
    plan. Changing the canvas to 16:9 scales every object Keynote still owns into
    the frame, so an off-slide leftover left un-planned is dragged back on-frame; a
    hide is what actually removes it. A partly-visible object is kept and placed."""
    slide = {
        "number": 1,
        "items": [
            _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
            _item(kind="text", text="CHC Kuching", x=4681, y=1678, w=235, h=52, size=40),  # y>1080, off
            _item(kind="text", text="on the wall", x=3000, y=200, w=300, h=60, size=40),  # visible
        ],
    }
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    template = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    recipe = learn_recipe(wall, template)
    out = plan_slide_transforms(slide, recipe, wall_size=(7680, 1080), include_lists=True)
    # The off-slide "CHC Kuching" (the only text parked at y=1678) is present but
    # hidden, so the canvas change cannot scale it back on-frame.
    off = [t for t in out if t.kind == "text" and t.y >= 1080]
    assert off and all(t.role == "hide" and t.opacity == 0.0 for t in off)
    visible = [t for t in out if t.kind == "text" and t.role != "hide"]
    assert visible  # the on-wall label is kept and placed


def test_fit_body_to_frame_narrows_the_body_only():
    """The overflowing body verse is nudged and narrowed to fit; a bleeding panel
    and an already-on-screen box are left exactly as they were."""
    from obed_edom.map_remap import _fit_body_to_frame, ItemTransform

    verse = ItemTransform(slide_number=1, item_index=1, kind="text", x=1137, y=89, w=1995, h=301, role="other")
    _fit_body_to_frame(verse, 1920, 1080)
    assert verse.x >= 0 and verse.x + verse.w <= 1920 + 0.5
    assert verse.w < 1995

    onframe = ItemTransform(slide_number=1, item_index=2, kind="text", x=100, y=100, w=400, h=80, role="other")
    _fit_body_to_frame(onframe, 1920, 1080)
    assert (onframe.x, onframe.y, onframe.w) == (100, 100, 400)  # already on-frame — untouched


def test_fit_pass_leaves_a_corner_label_and_its_width_alone():
    """A short corner label that bleeds off an edge is not the body, so the fit
    pass does not narrow it (which would wrap it) or move it off its plate. Only
    the verse is fitted."""
    verse = (
        "47 So Aaron did as Moses said and ran into the midst of the assembly. "
        "He stood between the living and the dead, and the plague stopped."
    )
    slide = {
        "number": 1,
        "items": [
            _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
            _item(kind="shape", x=3395, y=21, w=662, h=92),  # title plate
            _item(kind="text", text="Numbers 16", x=3395, y=21, w=662, h=92, size=60, font="AzoSans-Bold"),
            _item(kind="text", text=verse, x=3395, y=89, w=2328, h=351, size=46.67, font="AzoSans-Regular"),
            # A short corner label riding the affine to the right edge — must keep its width.
            _item(kind="text", text="Main Sanctuary", x=5400, y=40, w=333, h=64, size=40),
        ],
    }
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    template = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": [
        _item(kind="image", fileName="Wilderness.png", x=-544, y=0, w=3840, h=1080),
    ]}]}
    recipe = learn_recipe(wall, template)
    out = plan_slide_transforms(slide, recipe, wall_size=(7680, 1080), include_lists=True)
    others = sorted(
        (t for t in out if t.kind == "text" and t.role == "other"), key=lambda t: t.w * t.h
    )
    label, body = others[0], others[-1]
    # The body verse is fitted onto the frame and narrowed.
    assert body.x >= 0 and body.x + body.w <= 1920 + 0.5
    # The label rides the affine off the right edge and is left there — the fit
    # pass does not pull it on and narrow it (which would wrap it onto the plate).
    assert label.x + label.w > 1920


def test_sparkle_overlays_follow_the_body_after_the_fit_pass():
    """An emphasis copy is re-seated on the body once the body has been placed and
    the fit pass has moved and narrowed it, so it lands on the body's words on the
    frame instead of being left off-screen where its own affine put it."""
    verse = (
        "47 So Aaron did as Moses said and ran into the midst of the assembly. "
        "He stood between the living and the dead, and the plague stopped."
    )
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="Wilderness.png", x=1920, y=0, w=3840, h=1080),
                    _item(kind="shape", x=3395, y=21, w=662, h=92),
                    _item(kind="text", text="Numbers 16", x=3395, y=21, w=662, h=92, size=60, font="AzoSans-Bold"),
                    _item(kind="text", text=verse, x=3395, y=89, w=2328, h=351, size=46.67, font="AzoSans-Regular"),
                    # An emphasis copy far to the right — off-frame at 1:1 on its own.
                    _item(kind="text", text="the plague stopped", x=4378, y=337, w=676, h=98, size=75, font="AzoSans-Bold"),
                ],
            }
        ],
    }
    template = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": [
        _item(kind="image", fileName="Wilderness.png", x=-544, y=0, w=3840, h=1080),
    ]}]}
    recipe = learn_recipe(wall, template)
    tfs = plan_slide_transforms(wall["slides"][0], recipe, wall_size=(7680, 1080), include_lists=True)
    others = [t for t in tfs if t.role == "other" and t.kind == "text"]
    body = max(others, key=lambda t: t.w * t.h)
    overlay = next(t for t in others if t is not body)
    # The overlay lands on-frame, within the body's final vertical span, at the
    # body's size — following it rather than sitting off to the right.
    assert 0 <= overlay.x and overlay.x + overlay.w <= 1920 + 0.5
    assert body.y - 1 <= overlay.y <= body.y + body.h + 1
    assert abs((overlay.font_size or 0) - (body.font_size or 0)) < 0.5


def test_corner_label_keeps_its_plate_size_not_the_template_slot():
    """A corner label — a plate with one word and no logo, bleeding off a corner —
    is moved to the template's corner keeping its own size, so the rounded plate is
    not squared off by a resize and a longer word is not squeezed into a shorter
    word's slot. A logo makes it a missions badge, which keeps the slot."""
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "items": [
                    _item(kind="image", fileName="photo.png", x=1920, y=0, w=3840, h=1080),
                    _item(kind="shape", x=1942, y=-77, w=362, h=160),  # rounded plate, bleeds off top
                    _item(kind="text", text="Main Sanctuary", x=1957, y=11, w=333, h=64, size=50),
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
                    _item(kind="image", fileName="photo.png", x=-830, y=1, w=3840, h=1080),
                    _item(kind="shape", x=20, y=-77, w=227, h=160),  # narrower slot (shorter word)
                    _item(kind="text", text="Sunday", x=20, y=-1, w=227, h=88, size=50),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, template)
    assert recipe.get("badgePlateDst") == {"x": 20.0, "y": -77.0, "w": 227.0, "h": 160.0}
    out = plan_slide_transforms(wall["slides"][0], recipe, wall_size=(7680, 1080), include_lists=True)
    plate = next(t for t in out if t.kind == "shape")
    label = next(t for t in out if t.kind == "text" and t.role != "hide")
    # Plate moved to the corner but kept its own 362 width (rounding survives), not
    # squeezed to the template's 227 slot.
    assert (round(plate.x), round(plate.y), round(plate.w), round(plate.h)) == (20, -77, 362, 160)
    # Label moved with it, keeping its width so the word still fits.
    assert round(label.w) == 333
    assert 20 <= label.x <= 382  # sits on the plate


def test_full_bleed_image_is_not_mistaken_for_a_centre_panel():
    """A full-bleed image that runs off the top and bottom is not a centre panel:
    height is capped near one frame, so its framing is left to the usual path."""
    from obed_edom.map_remap import centre_panel_image

    items = [_item(kind="image", fileName="bleed.png", x=2189, y=-96, w=3686, h=2752)]
    assert centre_panel_image(items, 7680, 1080, 1920, 1080) is None


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


def test_thumbs_export_previews_the_template_never_had(tmp_path, monkeypatch):
    """A template is inspected without an export dir, so it reaches the framing
    list with no previews and the operator gets bare slide numbers."""
    from pathlib import Path

    from PIL import Image

    from obed_edom import inspect as inspect_mod
    from obed_edom.baseline import CACHE_DIR_ENV, deck_digest, preview_cache_dir
    from obed_edom.framing import build_preview_thumbs

    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    monkeypatch.setattr("obed_edom.keynote_app.app_version", lambda: "15.3.1")
    deck = tmp_path / "Base_CG_Assets.key"
    deck.write_text("placeholder")

    exported: list[Path] = []

    def fake_export(key_path, export_dir):
        exported.append(Path(key_path))
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), "navy").save(Path(export_dir) / "slide.001.png")
        return None

    monkeypatch.setattr(inspect_mod, "export_slide_images", fake_export)
    payload = {"slides": [{"number": 12, "items": []}]}
    thumbs = build_preview_thumbs(deck, payload)

    assert exported == [deck]
    assert thumbs == {12: "0012.jpg"}
    assert preview_cache_dir(deck_digest(deck)).is_dir()


def test_planned_rects_cover_every_role_the_page_uses():
    """The crop shows one affine, so the boxes are the only thing that can show
    the badge slot, the divider and the objects the run hides."""
    from obed_edom.framing import planned_rects

    slide = {
        "number": 4,
        "items": [
            _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
            _item(kind="image", fileName="pasted-image.pdf", x=1992, y=52, w=124, h=124),
            _item(kind="shape", x=1953, y=28, w=767, h=173),
            _item(kind="shape", x=3563, y=255, w=11, h=11),
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
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 12,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf", x=11, y=18, w=1067, h=659),
                    _item(kind="image", fileName="pasted-image.pdf", x=31, y=59, w=80, h=80),
                    _item(kind="shape", x=17, y=37, w=411, h=123),
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
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    recipe = learn_recipe(wall, template)
    rects = planned_rects(slide, recipe, wall_size=(7680, 1080))

    assert {r["role"] for r in rects} >= {"map", "pin", "title", "line"}
    # Every box is in destination coordinates, so the browser scales by one factor.
    assert all(isinstance(r["x"], int) and isinstance(r["w"], int) for r in rects)
    logo = next(r for r in rects if r["kind"] == "image" and r["w"] == 80)
    assert (logo["x"], logo["y"], logo["h"]) == (31, 59, 80)
    rule = next(r for r in rects if r["kind"] == "line")
    assert (rule["x"], rule["y"], rule["h"]) == (480, 621, 383)


def test_planned_rects_mark_dropped_side_content_and_a_whitelist_keeps_it():
    """A side-panel name list is dropped by default, so every one of its objects is
    marked willBeInOutput False and the composite omits it — the box view used to
    draw ~200 of them as landing. Whitelisting the slide (`side_content_slides`)
    plans that content placed instead, so the same objects come back kept."""
    from obed_edom.framing import planned_rects

    slide = {
        "number": 4,
        "items": [
            # Centre-panel map, kept either way — it overlaps [1920..5760].
            _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                  x=3052, y=-12, w=1248, h=771),
            # Wholly on the left panel, so side-panel content that is dropped
            # unless the slide is whitelisted.
            _item(kind="text", kindIndex=0, text="First Baptist Church",
                  x=120, y=200, w=520, h=90, size=40, font="AmplitudeCond-Medium"),
        ],
    }
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 12,
                "items": [
                    _item(kind="image", fileName="pasted-image.pdf",
                          x=11, y=18, w=1067, h=659),
                ],
            }
        ],
    }
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    recipe = learn_recipe(wall, template)

    dropped = planned_rects(slide, recipe, wall_size=(7680, 1080))
    assert all("willBeInOutput" in r for r in dropped)
    gone = [r for r in dropped if r["willBeInOutput"] is False]
    # The side panel leaves the output, and everything that leaves is a hide.
    assert gone and all(r["role"] == "hide" for r in gone)
    # The map is not among the casualties.
    assert all(r["willBeInOutput"] for r in dropped if r["role"] == "map")

    kept = planned_rects(
        slide, recipe, wall_size=(7680, 1080), side_content_slides={4}
    )
    kept_gone = [r for r in kept if r["willBeInOutput"] is False]
    # Whitelisting slide 4 flips its side content from dropped to kept: fewer
    # objects leave, and the page now plans a placed (in-output) box it did not.
    assert len(kept_gone) < len(gone)
    assert any(r["willBeInOutput"] for r in kept if r["role"] != "map")


def test_validation_off_exports_previews_without_reading_the_deck_back(tmp_path, monkeypatch):
    """The read-back dumps every object on every slide, and that dump exists only
    to build the validation flags. A run that does not want them should not pay
    for it — but it still wants the pictures."""
    from pathlib import Path

    from obed_edom import remap_keynote as remap_mod

    dest = tmp_path / "Wall_CG.key"
    dest.write_text("placeholder")
    previews = tmp_path / "previews"
    calls: list[str] = []

    monkeypatch.setattr(
        remap_mod, "remap_keynote", lambda *a, **k: {"applied": 3, "missed": 0}
    )
    monkeypatch.setattr(
        remap_mod,
        "inspect_keynote",
        lambda *a, **k: calls.append("inspect") or {"slides": []},
    )

    def fake_export(key_path, export_dir):
        calls.append("export")
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        (Path(export_dir) / "slide.001.png").write_bytes(b"")
        return None

    monkeypatch.setattr(remap_mod, "export_slide_images", fake_export)
    monkeypatch.setattr(remap_mod, "preview_pngs", lambda folder: sorted(Path(folder).glob("*.png")))

    info = remap_mod.remap_and_inspect(
        tmp_path / "Wall.key", dest, template=tmp_path / "T.key",
        export_dir=previews, validate=False,
    )
    assert calls == ["export"]
    assert info["previewFiles"] == ["slide.001.png"]
    assert "payload" not in info

    calls.clear()
    remap_mod.remap_and_inspect(
        tmp_path / "Wall.key", dest, template=tmp_path / "T.key",
        export_dir=previews, validate=True,
    )
    assert calls == ["inspect"]


def test_planned_rects_carry_the_wall_source_to_cut_from():
    """A composite preview draws each object by cutting it out of the wall
    thumbnail, so the destination rect alone is not enough — it needs to know
    which part of the wall the object occupied."""
    from obed_edom.framing import planned_rects

    map_img = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    slide = {
        "number": 4,
        "items": [
            map_img,
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
    template = {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 12,
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
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [slide]}
    recipe = learn_recipe(wall, template)
    rects = planned_rects(slide, recipe, wall_size=(7680, 1080))

    art = next(r for r in rects if r["role"] == "map" and r["w"] == 1067)
    assert (art["sx"], art["sy"], art["sw"], art["sh"]) == (3052, -12, 1248, 771)
    # The badge logo moves to its template slot, so its source is the only thing
    # that says which pixels to draw there.
    logo = next(r for r in rects if r["kind"] == "image" and r["w"] == 80)
    assert (logo["sx"], logo["sy"], logo["sw"], logo["sh"]) == (1992, 52, 124, 124)


def test_a_rule_sends_its_length_the_way_keynote_reports_it():
    """A divider came out 164px long — the wall's 658 through the 0.25 slide-size
    scale — because endpoints alone were sent and Keynote did not take them. It
    reports a line's width as its length whichever way the line runs, so the
    bounding box a vertical rule carries would set that length to zero."""
    from obed_edom.map_remap import ItemTransform

    spec = ItemTransform(
        slide_number=4,
        item_index=171,
        kind="line",
        x=480.0,
        y=621.0,
        w=0.0,
        h=383.0,
        role="line",
        start=(480.0, 1004.0),
        end=(480.0, 621.0),
    ).as_dict()
    assert spec["w"] == 383.0
    assert spec["h"] == 0.0
    assert spec["start"] == [480.0, 1004.0]
    assert spec["end"] == [480.0, 621.0]

    across = ItemTransform(
        slide_number=4,
        item_index=1,
        kind="line",
        x=100.0,
        y=50.0,
        w=300.0,
        h=0.0,
        role="line",
        start=(100.0, 50.0),
        end=(400.0, 50.0),
    ).as_dict()
    assert across["w"] == 300.0
    assert across["h"] == 0.0


def test_reuse_strips_the_objects_the_planner_never_looked_at():
    """The delta is pasted with a select-all, so anything left on the original
    rides across. `_live_items` skips placeholder text and objects inspect marked
    as duplicates, so those were never stripped and the donor's own copies were
    joined by a second set."""
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [
        _item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)
    ]

    def page(number, extra):
        return {
            "number": number,
            "items": [
                dict(map_img, kindIndex=0),
                *[dict(p) for p in pins],
                # Every wall slide carries these, and neither reaches the planner.
                _item(kind="text", kindIndex=8, text="", x=0, y=0, w=0, h=0),
                _item(
                    kind="text",
                    kindIndex=9,
                    text="183 CHC Churches",
                    x=262,
                    y=9,
                    w=215,
                    h=58,
                    duplicateOf=1,
                ),
                *extra,
            ],
        }

    wall = {
        "slides": [
            page(2, []),
            page(
                3,
                [_item(kind="text", kindIndex=10, text="26 Total", x=300, y=500, w=200, h=60)],
            ),
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert [a.get("matchText") for a in job["add"]] == ["26 Total"]

    stripped = {(r["kind"], r["kindIndex"]) for r in job["strip"]}
    assert ("text", 9) in stripped, "the duplicate would be pasted a second time"
    assert ("text", 8) in stripped, "the placeholder would be pasted a second time"
    # Everything except the delta goes; the original slide is deleted right after.
    assert ("text", 10) not in stripped
    assert ("image", 0) in stripped
    assert len(stripped) == 43


def _kuching_wall_slide():
    """Extracted_Wall_3rd slide 2, to scale: a badge, a bigger empty side panel,
    and a full-bleed photo."""
    return {
        "number": 2,
        "items": [
            _item(kind="text", kindIndex=0, text="CHC Kuching", x=1993, y=18, w=423, h=100, size=80),
            _item(kind="image", kindIndex=0, fileName="CHC Kuching Building.png",
                  x=1920, y=-1, w=3840, h=1080),
            _item(kind="shape", kindIndex=0, x=1961, y=-65, w=485, h=197),
            # Larger than the plate, and carries no words.
            _item(kind="shape", kindIndex=1, x=4261, y=205, w=398, h=710),
        ],
    }


def test_title_found_from_the_plate_when_no_phrase_matches():
    """`is_title_item` matches masters.yaml wording, so a deck titled per church
    had no title at all — and with it no titleDst and no badge slots."""
    from obed_edom.map_remap import is_title_item, slide_title_item, title_plate

    slide = _kuching_wall_slide()
    assert not any(is_title_item(it) for it in slide["items"])

    plate = title_plate(slide, (7680, 1080))
    # The side panel is the larger shape; the plate is the one with words on it.
    assert (plate["x"], plate["y"], plate["w"], plate["h"]) == (1961, -65, 485, 197)

    title = slide_title_item(slide, (7680, 1080))
    assert title is not None and title["text"] == "CHC Kuching"


def test_phrase_still_wins_where_masters_knows_the_wording():
    from obed_edom.map_remap import slide_title_item

    slide = {
        "number": 4,
        "items": [
            _item(kind="text", kindIndex=0, text="Global Missions", x=2147, y=52, w=537, h=124, size=100),
            _item(kind="shape", kindIndex=0, x=1953, y=28, w=767, h=173),
            # Bigger, lettered, and not the badge — structure alone might take it.
            _item(kind="shape", kindIndex=1, x=3000, y=300, w=900, h=600),
            _item(kind="text", kindIndex=1, text="a caption", x=3100, y=400, w=400, h=120, size=40),
        ],
    }
    title = slide_title_item(slide, (7680, 1080))
    assert title["text"] == "Global Missions"


def test_a_plate_with_several_words_is_left_alone():
    """Map_Extracted_Wall_2nd's badge is MISSIONS + UPDATE + China. Picking the
    largest would collapse one of three onto the template's single title box, so
    the deck keeps the behaviour it had: no structural title."""
    from obed_edom.map_remap import slide_title_item

    slide = {
        "number": 1,
        "items": [
            _item(kind="text", kindIndex=0, text="MISSIONS", x=2139, y=34, w=270, h=82, size=65),
            _item(kind="text", kindIndex=1, text="UPDATE", x=2138, y=90, w=273, h=104, size=83),
            _item(kind="text", kindIndex=2, text="China", x=2458, y=51, w=198, h=124, size=100),
            _item(kind="shape", kindIndex=0, x=1953, y=28, w=740, h=173),
        ],
    }
    assert slide_title_item(slide, (7680, 1080)) is None


def test_a_church_named_title_is_not_a_list_sample():
    """CHURCH_LIST_RE matches "CHC Kuching", so a 60pt heading became the seed
    that church-name columns were sized against."""
    from obed_edom.map_remap import classify_item, slide_title_item, template_list_sample

    slide = _kuching_wall_slide()
    size, _rect = template_list_sample([slide], (7680, 1080))
    assert size is None

    title = slide_title_item(slide, (7680, 1080))
    assert classify_item(title, None, title) == "title"
    # Without the resolved title it falls through to the church-name pattern.
    assert classify_item(title, None, None) == "list"


def test_a_deck_with_skipped_slides_says_how_its_numbers_read():
    """Slide numbers here are document positions and count every slide. Keynote
    numbers only the ones that will play, so a range typed off the navigator
    quietly selects the wrong pages."""
    from obed_edom.map_remap import navigator_numbering, skipped_positions

    deck = {"slides": [{"number": n, "skipped": n in (3, 7)} for n in range(1, 12)]}
    assert skipped_positions(deck) == [3, 7]
    note = navigator_numbering(deck)
    assert "position 3, 7" in note
    # Position 4 is the navigator's 3 once one slide before it is skipped.
    assert "4→3" in note
    assert "8→6" in note

    # Nothing to say about a deck that plays every slide.
    assert navigator_numbering({"slides": [{"number": n} for n in range(1, 5)]}) == ""


def test_a_range_is_read_in_the_numbers_keynote_shows():
    """The dashboard takes a range in navigator numbering; the CLI keeps document
    positions and says so in --help. Splitting them silently would be worse than
    either, so the translation is explicit and one-way."""
    from obed_edom.map_remap import to_document_range

    deck = {"slides": [{"number": n, "skipped": n in (3, 7)} for n in range(1, 12)]}
    # Keynote shows the 4th playable slide as 3, and it is document position 4.
    assert sorted(to_document_range(deck, frozenset({3, 4}))) == [4, 5]
    assert sorted(to_document_range(deck, frozenset({1, 2}))) == [1, 2]
    # A deck that plays everything is untouched.
    plain = {"slides": [{"number": n} for n in range(1, 6)]}
    assert sorted(to_document_range(plain, frozenset({2, 3}))) == [2, 3]
    # Past the end is kept rather than dropped: losing a page silently is worse
    # than planning one that turns out not to exist.
    assert sorted(to_document_range(deck, frozenset({99}))) == [99]
    assert to_document_range(deck, None) is None


def _two_layout_template():
    """Two template slides with different badges, so "which slide" is visible in
    the recipe rather than only in the map."""
    return {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 4,
                "items": [
                    _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                          x=0, y=-53, w=1920, h=1186),
                    _item(kind="shape", kindIndex=0, x=10, y=0, w=300, h=90),
                    _item(kind="text", kindIndex=0, text="Global Missions",
                          x=25, y=6, w=181, h=74, size=40, font="AmplitudeCond-Medium"),
                ],
            },
            {
                "number": 12,
                "items": [
                    _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                          x=11, y=18, w=1067, h=659),
                    _item(kind="image", kindIndex=1, fileName="pasted-image.pdf",
                          x=31, y=59, w=80, h=80),
                    _item(kind="shape", kindIndex=0, x=17, y=37, w=411, h=123),
                    _item(kind="text", kindIndex=0, text="Global Missions",
                          x=135, y=67, w=271, h=64, size=50, font="AmplitudeCond-Medium"),
                ],
            },
        ],
    }


def test_a_framing_takes_its_own_slide_s_badge_not_the_deck_s_first():
    """"Template slide 12" has to mean slide 12's layout. Scanning the deck in
    order returned whichever slide held the first title, so every framing
    produced the same title box and choosing another moved the map alone."""
    wall = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 4,
                "items": [
                    _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                          x=3052, y=-12, w=1248, h=771),
                    _item(kind="image", kindIndex=1, fileName="pasted-image.pdf",
                          x=1992, y=52, w=124, h=124),
                    _item(kind="shape", kindIndex=0, x=1953, y=28, w=767, h=173),
                    _item(kind="text", kindIndex=0, text="Global Missions",
                          x=2147, y=52, w=537, h=124, size=100,
                          font="AmplitudeCond-Medium"),
                ],
            }
        ],
    }
    template = _two_layout_template()

    twelve = learn_recipe(wall, template, template_slide=12)
    assert twelve["titleDst"] == {"x": 135.0, "y": 67.0, "w": 271.0, "h": 64.0}
    assert twelve["badgeSlots"]["shape:0"]["w"] == 411.0
    assert twelve["badgeSlots"]["image:0"] == {"x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0}

    four = learn_recipe(wall, template, template_slide=4)
    assert four["titleDst"] == {"x": 25.0, "y": 6.0, "w": 181.0, "h": 74.0}
    assert four["badgeSlots"]["shape:0"]["w"] == 300.0
    # Slide 4 has no logo of its own, so nothing claims that slot.
    assert "image:0" not in four["badgeSlots"]


def test_two_framings_of_one_page_do_not_preview_the_same():
    """planned_rects was handed the template as well as the recipe, and
    plan_payload_transforms re-learns per slide when given one — so every
    candidate drew the automatic framing and the picker showed one picture."""
    from obed_edom.framing import planned_rects

    wall_slide = {
        "number": 4,
        "items": [
            _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                  x=3052, y=-12, w=1248, h=771),
            _item(kind="text", kindIndex=0, text="Global Missions",
                  x=2147, y=52, w=537, h=124, size=100, font="AmplitudeCond-Medium"),
            _item(kind="shape", kindIndex=0, x=1953, y=28, w=767, h=173),
        ],
    }
    wall = {"slideWidth": 7680, "slideHeight": 1080, "slides": [wall_slide]}
    template = _two_layout_template()

    def title_of(n):
        recipe = learn_recipe(wall, template, template_slide=n)
        rects = planned_rects(wall_slide, recipe, wall_size=(7680, 1080))
        return next(r for r in rects if r["role"] == "title")

    assert title_of(12) != title_of(4)
    assert (title_of(12)["x"], title_of(12)["w"]) == (135, 271)
    assert (title_of(4)["x"], title_of(4)["w"]) == (25, 181)


def test_bleed_art_is_judged_on_the_part_that_is_on_the_wall():
    """A 2752px-tall image on a 1080px wall has its centre off the source deck
    before any framing is applied. Judging the framing by where that centre lands
    called a correct 1:1 placement a failure and scaled the page instead."""
    from obed_edom.map_remap import on_canvas_fraction

    recipe = {
        "destWidth": 1920,
        "destHeight": 1080,
        "mapSrc": {"x": 3158.0, "y": -69.0, "w": 1364.0, "h": 947.0},
        "mapDst": {"x": 226.0, "y": 61.0, "w": 1364.0, "h": 947.0},
        "groups": [
            {
                "s": 1.0,
                "tx": -2932.0,
                "ty": 130.0,
                "src": {"x": 3158.0, "y": -69.0, "w": 1364.0, "h": 947.0},
                "dst": {"x": 226.0, "y": 61.0, "w": 1364.0, "h": 947.0},
                "members": 1,
            }
        ],
    }
    slide = {
        "number": 94,
        "items": [
            # Full-bleed art, far taller than the wall it sits on.
            _item(kind="image", kindIndex=0, fileName="pasted-image.pdf",
                  x=2189, y=-96, w=3686, h=2752),
            _item(kind="image", kindIndex=1, fileName="pasted-image.pdf",
                  x=2231, y=-123, w=3686, h=2752),
            # The map itself, which the framing places 1:1.
            _item(kind="image", kindIndex=2, fileName="pasted-image.pdf",
                  x=3158, y=-69, w=1364, h=947),
        ],
    }
    # All three are on frame once each is judged by its visible part.
    assert on_canvas_fraction(slide, recipe, 7680, 1080) == 1.0


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return not (
        a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y
    )


def test_pack_columns_from_left_wraps_right_by_column_max_width():
    from obed_edom.map_remap import pack_columns_from_left

    # Non-uniform widths (the real number-block sizes); heights fill the 1080
    # frame after three boxes so the fourth must wrap into a second column.
    boxes = [
        Rect(0, 0, 537, 300),
        Rect(0, 0, 496, 300),
        Rect(0, 0, 199, 300),
        Rect(0, 0, 237, 300),
    ]
    placed = pack_columns_from_left(boxes, 1920, 1080)
    assert len(placed) == 4
    # Sizes are untouched — only position moves.
    for src, dst in zip(boxes, placed, strict=True):
        assert dst.w == src.w
        assert dst.h == src.h
    # First box anchors the left margin.
    assert placed[0].x == 16
    # The first three boxes stayed in column one.
    first_col = placed[:3]
    assert all(r.x == 16 for r in first_col)
    col1_max_w = max(r.w for r in first_col)
    # The wrapped (fourth) box stepped by the widest box in column one (537),
    # not by the previous box's width (199) — a naive prev_w step would overlap.
    assert placed[3].x >= 16 + col1_max_w
    # No two placed boxes overlap.
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            assert not _rects_overlap(placed[i], placed[j])


def test_pack_left_groups_moves_wall_size_groups_without_overlap():
    from obed_edom.map_remap import ItemTransform, _pack_left_groups

    # Four left-column number-block groups, all parked at x=16 by the affine,
    # given in a shuffled order but each with a distinct src.y that defines the
    # wall's reading order (100 < 400 < 700 < 1000).
    groups = [
        ItemTransform(
            slide_number=1, item_index=0, kind="group", x=16, y=50, w=199, h=200,
            role="other", src=Rect(0, 700, 199, 200),
        ),
        ItemTransform(
            slide_number=1, item_index=1, kind="group", x=16, y=150, w=537, h=200,
            role="other", src=Rect(0, 100, 537, 200),
        ),
        ItemTransform(
            slide_number=1, item_index=2, kind="group", x=16, y=250, w=237, h=200,
            role="other", src=Rect(0, 1000, 237, 200),
        ),
        ItemTransform(
            slide_number=1, item_index=3, kind="group", x=16, y=350, w=496, h=200,
            role="other", src=Rect(0, 400, 496, 200),
        ),
    ]
    original_sizes = {id(g): (g.w, g.h) for g in groups}
    _pack_left_groups(groups, {"destWidth": 1920.0, "destHeight": 1080.0})
    # Wall size is preserved — only x/y moved.
    for g in groups:
        assert (g.w, g.h) == original_sizes[id(g)]
    # No two groups overlap after packing.
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            ri = Rect(groups[i].x, groups[i].y, groups[i].w, groups[i].h)
            rj = Rect(groups[j].x, groups[j].y, groups[j].w, groups[j].h)
            assert not _rects_overlap(ri, rj)
    # Placement follows ascending src.y (wall reading order): the group with the
    # smallest src.y lands first — leftmost margin, topmost y.
    by_src_y = sorted(groups, key=lambda g: g.src.y)
    ys = [g.y for g in by_src_y]
    assert ys == sorted(ys)
    assert by_src_y[0].x == 16


# --- Part A: per-slide occurrence-ordinal partition key (co-located dedup) ---


def test_reuse_colocated_group_pair_yields_two_partition_entries():
    """Two co-located identical GROUPS (same content_key, like real slide 3's
    stat pairs) must each get their own partition slot. Pre-fix the dict keyed by
    bare content_key collapsed them to one, so only ONE of the twins was ever
    addressed; with the occurrence-ordinal both land in `add`."""
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    # A co-located twin: identical geometry, so the same content_key twice.
    twin_a = _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50)
    twin_b = _item(kind="group", kindIndex=1, x=100, y=100, w=50, h=50)
    wall = {
        "slides": [
            {"number": 2, "items": [dict(map_img), *[dict(p) for p in pins]]},
            {"number": 3, "items": [dict(map_img), *[dict(p) for p in pins], dict(twin_a), dict(twin_b)]},
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert job["from"] == 2
    # Both physical twins are distinct partition entries -> both added (was 1 pre-fix).
    assert len([a for a in job["add"] if a.get("kind") == "group"]) == 2


def test_reuse_duplicated_map_images_stay_ordinal_paired_and_persist():
    """The map image is legitimately duplicated across wall panels (per SKILL).
    Both copies key to ordinals 0/1 on donor and target, pair 0<->0 / 1<->1, and
    both persist unchanged — never dropped, never re-added. Pre-fix the second
    copy was collapsed away (only one map persisted)."""
    from obed_edom.map_remap import plan_slide_reuses

    map0 = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    map1 = _item(kind="image", kindIndex=1, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    wall = {
        "slides": [
            {"number": 2, "items": [dict(map0), dict(map1), *[dict(p) for p in pins]]},
            {"number": 3, "items": [dict(map0), dict(map1), *[dict(p) for p in pins]]},
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert job["from"] == 2
    # 40 pins + BOTH map copies persist (== 42); pre-fix a collapsed map gave 41.
    assert job["persist"] == 42
    assert not any(r.get("kind") == "image" for r in job["remove"])
    assert not any(a.get("kind") == "image" for a in job["add"])


def test_reuse_persisting_collided_pair_aligns_by_ordinal_across_slides():
    """A PERSISTING collided pair (the Map deck never exercises this) proves the
    donor pair aligns to the current pair BY ORDINAL, not cross-matched/collapsed:
    the donor's ordinal-0 member carries a build the target lost, the ordinal-1
    member does not. `stripBuilds` must name exactly the ordinal-0 donor. Pre-fix
    the dict kept only the last (ordinal-1, build-free) copy, so the lost build was
    invisible and `stripBuilds` was empty."""
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    # Donor: co-located pair, ordinal-0 (ki 0) animates, ordinal-1 (ki 1) is static.
    donor_pair = [
        _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50, buildCount=1),
        _item(kind="group", kindIndex=1, x=100, y=100, w=50, h=50, buildCount=0),
    ]
    # Target: same co-located pair, both static (the ordinal-0 build was dropped).
    curr_pair = [
        _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50, buildCount=0),
        _item(kind="group", kindIndex=1, x=100, y=100, w=50, h=50, buildCount=0),
    ]
    wall = {
        "slides": [
            {"number": 2, "items": [dict(map_img), *[dict(p) for p in pins], *donor_pair]},
            {"number": 3, "items": [dict(map_img), *[dict(p) for p in pins], *curr_pair]},
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert job["from"] == 2
    # 40 pins + 1 map + both twins persist.
    assert job["persist"] == 43
    build_refs = [r for r in job["stripBuilds"] if r.get("kind") == "group"]
    # Exactly the ordinal-0 donor (ki 0) — proves per-ordinal pairing, not collapse.
    assert build_refs == [{"kind": "group", "kindIndex": 0, "itemIndex": 0}]


def test_reuse_collision_free_wall_all_ordinals_zero():
    """On a collision-free wall (single map, distinct pins) every content_key
    occurs once, so all ordinals are 0 and behaviour is identical to the pre-fix
    partition: exactly 40 pins + 1 map persist, no phantom ordinal-1 entry."""
    from obed_edom.map_remap import plan_slide_reuses

    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    wall = {
        "slides": [
            {"number": 2, "items": [dict(map_img), *[dict(p) for p in pins],
                                     _item(kind="text", kindIndex=0, text="CHC Zui", x=6946, y=9, w=474, h=954, size=42)]},
            {"number": 3, "items": [dict(map_img), *[dict(p) for p in pins],
                                    _item(kind="text", kindIndex=0, text="CHC Aaliana", x=262, y=9, w=215, h=58, size=42)]},
        ]
    }
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[3]
    assert job["from"] == 2
    # 40 pins + 1 map; the differing text is not in persist. No duplication.
    assert job["persist"] == 41


def _reuse_gold_cache_payload(name):
    """Return the CACHED inspect payload for a wall deck, or None if the cache is
    cold. Never opens Keynote: it hashes the file offline and only reads the cache
    if the digest-keyed JSON already exists on disk."""
    from pathlib import Path

    from obed_edom.baseline import deck_digest, inspect_cache_path

    deck = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs") / name
    if not deck.exists():
        return None
    try:
        if not inspect_cache_path(deck_digest(deck)).is_file():
            return None
    except (OSError, ValueError):
        return None
    from obed_edom.inspect import inspect_keynote

    payload = inspect_keynote(deck, use_cache=True)
    return payload if payload.get("_cached") else None


def test_gold_map_deck_donor_selection_unchanged():
    """Offline gold gate (no Keynote): the ordinal key must not disturb donor
    SELECTION or the REUSE_MIN_PERSIST gate on the real Map wall deck. The chain
    and per-slide persist counts below are the live values AFTER the ordinal fix;
    each persist is exactly the pre-fix value + 1 (the second map copy that used to
    be collapsed now counts), and the donor chain is byte-identical to pre-fix."""
    import pytest

    from obed_edom.map_remap import REUSE_MIN_PERSIST, plan_slide_reuses

    payload = _reuse_gold_cache_payload("Map_Extracted_Wall_1st.key")
    if payload is None:
        pytest.skip("Map wall deck cache is cold; refuse to open Keynote")
    jobs = {j["slide"]: j for j in plan_slide_reuses(payload, [])}
    # Donor chain unchanged vs pre-fix (verified by A/B run on the cached payload).
    assert {s: j["from"] for s, j in sorted(jobs.items())} == {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6}
    # Gating not tripped, and persist == pre-fix + 1 (the recovered second map).
    prefix_persist = {2: 160, 3: 160, 4: 166, 5: 169, 6: 169, 7: 168}
    for s, j in jobs.items():
        assert j["persist"] >= REUSE_MIN_PERSIST
        assert j["persist"] == prefix_persist[s] + 1


def test_gold_full_report_card_deck_if_warm():
    """Full_Report_Card_Wall gold gate — runs ONLY if its cache is already warm
    (never opens Keynote). If cold it skips, leaving Full unverified as flagged."""
    import pytest

    from obed_edom.map_remap import REUSE_MIN_PERSIST, plan_slide_reuses

    payload = _reuse_gold_cache_payload("Full_Report_Card_Wall.key")
    if payload is None:
        pytest.skip("Full_Report_Card_Wall cache is cold; refuse to open Keynote")
    jobs = plan_slide_reuses(payload, [])
    # Whatever donor selection this deck makes, gating must never trip.
    for j in jobs:
        assert j["persist"] >= REUSE_MIN_PERSIST


def test_gold_map_deck_stripbuilds_empty():
    """A5: stripBuildRefs is left wall-index addressed on the drifted copy
    (deferred (f) build work) and guarded to fail loud only if it is ever
    non-empty. Assert it stays empty on the Map gold deck so the guard never
    fires today; also assert every remove ref carries a plausible output rect."""
    import math

    import pytest

    from obed_edom.map_remap import plan_slide_reuses

    payload = _reuse_gold_cache_payload("Map_Extracted_Wall_1st.key")
    if payload is None:
        pytest.skip("Map wall deck cache is cold; refuse to open Keynote")
    # Empty transforms (as the sibling donor-selection gold test): stripBuilds
    # emptiness depends only on the wall buildCounts, and remove refs still carry
    # finite wall-fallback output rects with no spec present.
    jobs = plan_slide_reuses(payload, [])
    for j in jobs:
        assert j["stripBuilds"] == []
        # Every remove ref carries a finite output rect (Part B1 / Part C tiles).
        for r in j["remove"]:
            for f in ("x", "y", "w", "h"):
                assert f in r and math.isfinite(float(r[f]))


# --- Part B1: per-object OUTPUT-rect map threaded onto `remove` refs -----------
# These prove the three load-bearing rules of the donor-copy geometry map: a base
# slide object's rect is its transform spec; a no-spec object's rect is its wall
# geometry; a persisting object inherits its donor's rect through >=2 donors; and
# every emitted remove ref carries a finite x/y/w/h for the JS geometry matcher.


def _reuse_wall_base(*extra_slide1_items, extra_slide2_items=()):
    """A synthetic wall: 1 map + 40 pins (>= REUSE_MIN_PERSIST) shared on two
    slides, plus caller-supplied extras. Slide 1 is the base; slide 2 reuses it."""
    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    return {
        "slides": [
            {"number": 1, "items": [dict(map_img), *[dict(p) for p in pins], *extra_slide1_items]},
            {"number": 2, "items": [dict(map_img), *[dict(p) for p in pins], *extra_slide2_items]},
        ]
    }


def test_reuse_remove_ref_carries_base_slide_spec_rect():
    """B1(a)+(d): a base-slide object removed on a later reuse target carries its
    OUTPUT rect = the base slide's transform spec (CG space, NOT the wall geom),
    and every remove ref carries a finite x/y/w/h."""
    from obed_edom.map_remap import ItemTransform, plan_slide_reuses

    # `extra` lives on the base slide only, at wall (5000,5000,99,99); its base
    # transform spec repositions it to a CG rect far away.
    extra = _item(kind="shape", kindIndex=40, x=5000, y=5000, w=99, h=99)
    wall = _reuse_wall_base(dict(extra))
    spec = ItemTransform(
        slide_number=1, item_index=41, kind="shape", x=123, y=456, w=78, h=90, kind_index=40, role="other"
    )
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [spec])}[2]
    removed = [r for r in job["remove"] if r.get("kind") == "shape"]
    assert len(removed) == 1
    r = removed[0]
    assert (r["x"], r["y"], r["w"], r["h"]) == (123, 456, 78, 90)  # spec rect, not wall
    # (d) every remove ref carries finite geometry.
    for rr in job["remove"]:
        assert all(isinstance(rr.get(f), (int, float)) for f in ("x", "y", "w", "h"))


def test_reuse_remove_ref_no_spec_falls_back_to_wall_rect():
    """B1(b): a removed donor object with NO transform spec is left at its WALL
    geometry by applyReuse (applySpec is skipped when spec.x is null), so its
    remove ref carries the wall x/y/w/h."""
    from obed_edom.map_remap import plan_slide_reuses

    extra = _item(kind="shape", kindIndex=40, x=5000, y=5000, w=99, h=99)
    wall = _reuse_wall_base(dict(extra))
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]  # no transforms at all
    removed = [r for r in job["remove"] if r.get("kind") == "shape"]
    assert len(removed) == 1
    r = removed[0]
    assert (r["x"], r["y"], r["w"], r["h"]) == (5000, 5000, 99, 99)  # wall fallback


def test_reuse_remove_ref_inherits_persisted_rect_through_two_donors():
    """B1(c): an object placed by the BASE spec, persisted (with no spec of its
    own) through slide 2 and slide 3, then removed on slide 4, carries the base
    spec rect — inherited across >= 2 donors, never recomputed from a later wall.

    Slides grow monotonically so the donor chain is forced to 2<-1, 3<-2, 4<-3
    (each slide shares most with its immediate predecessor); on slides 2 & 3
    `extra` has NO spec, so a wall-geom rect there would prove inheritance broke."""
    from obed_edom.map_remap import ItemTransform, plan_slide_reuses

    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    extra = _item(kind="shape", kindIndex=40, x=5000, y=5000, w=99, h=99)
    a1 = _item(kind="shape", kindIndex=41, x=6000, y=100, w=20, h=20)
    a2 = _item(kind="shape", kindIndex=42, x=6000, y=200, w=20, h=20)
    a3 = _item(kind="shape", kindIndex=43, x=6000, y=300, w=20, h=20)
    base = [dict(map_img), *[dict(p) for p in pins]]
    wall = {
        "slides": [
            {"number": 1, "items": [*[dict(b) for b in base], dict(extra), dict(a1)]},
            {"number": 2, "items": [*[dict(b) for b in base], dict(extra), dict(a1), dict(a2)]},
            {"number": 3, "items": [*[dict(b) for b in base], dict(extra), dict(a1), dict(a2), dict(a3)]},
            {"number": 4, "items": [*[dict(b) for b in base], dict(a1), dict(a2), dict(a3)]},  # extra removed
        ]
    }
    spec = ItemTransform(
        slide_number=1, item_index=41, kind="shape", x=123, y=456, w=78, h=90, kind_index=40, role="other"
    )
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [spec])}
    assert {s: j["from"] for s, j in jobs.items()} == {2: 1, 3: 2, 4: 3}
    removed = [r for r in jobs[4]["remove"] if r.get("kind") == "shape"]
    assert len(removed) == 1
    r = removed[0]
    # Inherited base spec rect (would be (5000,5000,99,99) if the 2-hop inherit failed).
    assert (r["x"], r["y"], r["w"], r["h"]) == (123, 456, 78, 90)


# --- R1/R2: group removes route to `groupRemove` (content-addressed, no geometry) ---


def _reuse_wall_with_group(donor_groups, target_groups, donor_gct, target_gct):
    """A synthetic wall: 1 map + 40 shared pins (>= REUSE_MIN_PERSIST) so slide 2
    reuses slide 1, plus caller-supplied donor/target groups and their groupChildText
    (``{kindIndex: childSig}``) as the resizer flow attaches it."""
    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    base = [dict(map_img), *[dict(p) for p in pins]]
    return {
        "slides": [
            {"number": 1, "items": [*[dict(b) for b in base], *donor_groups], "groupChildText": donor_gct},
            {"number": 2, "items": [*[dict(b) for b in base], *target_groups], "groupChildText": target_gct},
        ]
    }


def test_reuse_group_remove_routes_out_of_remove_with_sig_and_keep():
    """A donor group absent from the target is routed OUT of `remove` into
    `groupRemove`, carrying the DONOR slide's childSig and `expectedKeep` from the
    TARGET's own groupChildText — and it carries NO geometry (R1)."""
    from obed_edom.map_remap import plan_slide_reuses

    ga = _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50)  # removed
    gb = _item(kind="group", kindIndex=1, x=200, y=200, w=50, h=50)  # persists
    gb_t = _item(kind="group", kindIndex=0, x=200, y=200, w=50, h=50)
    wall = _reuse_wall_with_group(
        donor_groups=[dict(ga), dict(gb)],
        target_groups=[dict(gb_t)],
        donor_gct={0: "27\nSchools", 1: "110\nWorkers"},
        target_gct={0: "110\nWorkers"},
    )
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    # No GROUP ever survives in `remove` (so JXA deleteRefs never index-deletes it).
    assert all(r.get("kind") != "group" for r in job["remove"])
    grs = job["groupRemove"]
    assert len(grs) == 1
    gr = grs[0]
    assert gr["kind"] == "group" and gr["kindIndex"] == 0
    assert gr["childSig"] == "27\nSchools"  # DONOR slide's signature for kindIndex 0
    assert gr["expectedKeep"] == 0  # target retains zero groups of that signature
    # R1: a group remove carries no output rect (a re-derived frame is undecidable).
    assert not any(k in gr for k in ("x", "y", "w", "h"))


def test_reuse_group_remove_expected_keep_counts_target_signatures():
    """The stranded-twin case: donor has two groups of the SAME signature, only one
    persists (target keeps one), so `expectedKeep == 1` — the count-scoped dedup keeps
    exactly that many and deletes the one donor-copy leftover."""
    from obed_edom.map_remap import plan_slide_reuses

    ga = _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50)  # removed twin
    gb = _item(kind="group", kindIndex=1, x=200, y=200, w=50, h=50)  # persists
    gb_t = _item(kind="group", kindIndex=0, x=200, y=200, w=50, h=50)
    wall = _reuse_wall_with_group(
        donor_groups=[dict(ga), dict(gb)],
        target_groups=[dict(gb_t)],
        donor_gct={0: "27\nSchools", 1: "27\nSchools"},
        target_gct={0: "27\nSchools"},
    )
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    grs = job["groupRemove"]
    assert len(grs) == 1
    assert grs[0]["childSig"] == "27\nSchools"
    assert grs[0]["expectedKeep"] == 1  # target keeps one group of that signature


def test_reuse_group_remove_without_groupchildtext_has_no_sig():
    """When groupChildText is absent (no `iwa` extra), a group remove still routes to
    `groupRemove` (never `remove`) but carries no childSig — the dedup then reports a
    shortfall rather than deleting the wrong object."""
    from obed_edom.map_remap import plan_slide_reuses

    ga = _item(kind="group", kindIndex=0, x=100, y=100, w=50, h=50)
    wall = _reuse_wall_with_group(
        donor_groups=[dict(ga)], target_groups=[], donor_gct=None, target_gct=None
    )
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    grs = job.get("groupRemove")
    assert grs and len(grs) == 1
    assert "childSig" not in grs[0]
    assert all(r.get("kind") != "group" for r in job["remove"])


def test_reuse_no_groupremove_key_when_no_group_removes():
    """A reuse job with only tile removes carries no `groupRemove` key at all."""
    from obed_edom.map_remap import plan_slide_reuses

    extra = _item(kind="shape", kindIndex=40, x=5000, y=5000, w=99, h=99)
    wall = _reuse_wall_with_group(
        donor_groups=[dict(extra)], target_groups=[], donor_gct={}, target_gct={}
    )
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    assert "groupRemove" not in job
    # The shape tile still carries its (wall-fallback) output rect for the geom path.
    tile = [r for r in job["remove"] if r.get("kind") == "shape"][0]
    assert (tile["x"], tile["y"], tile["w"], tile["h"]) == (5000, 5000, 99, 99)


# --- R2 amendments (v2): donor OUTPUT-state model, cross-chain stray accumulation ---


def _reuse_chain(per_slide):
    """N-slide wall forcing the reuse chain n<-(n-1): 1 map + 40 shared pins, plus an
    accumulating anchor per slide (slide n carries anchors 0..n-2) so each slide shares
    strictly more with its immediate predecessor than any earlier slide. `per_slide` is
    a list of (groups, groupChildText) — the caller-supplied groups for slides 1..N."""
    map_img = _item(kind="image", kindIndex=0, fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    pins = [_item(kind="shape", kindIndex=i, x=3563 + i * 13, y=255, w=11, h=11) for i in range(40)]
    base = [dict(map_img), *[dict(p) for p in pins]]
    slides = []
    for idx, (groups, gct) in enumerate(per_slide):
        anchors = [_item(kind="shape", kindIndex=100 + j, x=9000 + j * 7, y=900, w=5, h=5) for j in range(idx)]
        slides.append(
            {"number": idx + 1, "items": [*[dict(b) for b in base], *anchors, *groups], "groupChildText": gct}
        )
    return {"slides": slides}


def _grp(ki, x, sig):
    return _item(kind="group", kindIndex=ki, x=x, y=100, w=50, h=50), sig


def test_reuse_group_moved_then_absent_schedules_both_stray_copies():
    """A stat group at pos A on slide 1 MOVES to pos B on slide 2 (remove+add), then is
    absent on slide 3. Because the whole JXA reuse chain runs before the single dedup
    pass, slide 3 inherits BOTH pre-dedup copies (the slide-1 donor copy + the slide-2
    paste), neither addressed by the wall-vs-wall partition. Slide 2 removes one (keep 1);
    slide 3 must schedule TWO removes for that sig — one real (the partitioned donor group)
    plus one synthetic for the inherited stray the partition never saw."""
    from obed_edom.map_remap import plan_slide_reuses

    wall = _reuse_chain([
        ([_grp(50, 4600, "27\nSchools")[0]], {50: "27\nSchools"}),
        ([_grp(50, 4739, "27\nSchools")[0]], {50: "27\nSchools"}),
        ([], {}),
    ])
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [])}
    assert {s: j["from"] for s, j in jobs.items()} == {2: 1, 3: 2}

    g2 = jobs[2]["groupRemove"]
    assert len(g2) == 1
    assert g2[0]["childSig"] == "27\nSchools" and g2[0]["expectedKeep"] == 1
    assert g2[0]["kindIndex"] == 50  # the real (partitioned) donor copy

    g3 = jobs[3]["groupRemove"]
    assert len(g3) == 2
    assert all(r["childSig"] == "27\nSchools" and r["expectedKeep"] == 0 for r in g3)
    assert sorted(r["kindIndex"] for r in g3) == [-1, 50]  # one real + one synthetic stray


def test_reuse_inherited_strays_are_all_synthetic_down_the_chain():
    """A group present on slides 1+2 (moved) but absent on 3 AND 4: by slide 4 the
    partition sees no copy at all, so every scheduled remove is a synthetic stray."""
    from obed_edom.map_remap import plan_slide_reuses

    wall = _reuse_chain([
        ([_grp(50, 4600, "110\nWorkers")[0]], {50: "110\nWorkers"}),
        ([_grp(50, 4739, "110\nWorkers")[0]], {50: "110\nWorkers"}),
        ([], {}),
        ([], {}),
    ])
    jobs = {j["slide"]: j for j in plan_slide_reuses(wall, [])}
    assert {s: j["from"] for s, j in jobs.items()} == {2: 1, 3: 2, 4: 3}
    g4 = jobs[4]["groupRemove"]
    assert len(g4) == 2
    assert all(r["kindIndex"] == -1 and r["childSig"] == "110\nWorkers" and r["expectedKeep"] == 0 for r in g4)


def test_reuse_hidden_persisted_group_becomes_dedup_surplus():
    """A group that PERSISTS onto a reuse target but is marked role='hide' is not a keeper
    (deleteHides never runs on a reuse slide, so it survives live) — keep excludes it and
    it is scheduled for dedup removal as a synthetic surplus."""
    from obed_edom.map_remap import ItemTransform, plan_slide_reuses

    g = _grp(50, 4600, "side\nlist")[0]
    wall = _reuse_chain([
        ([dict(g)], {50: "side\nlist"}),
        ([dict(g)], {50: "side\nlist"}),  # same geometry => persists
    ])
    hide = ItemTransform(slide_number=2, item_index=50, kind="group", kind_index=50, role="hide", x=1, y=1, w=1, h=1)
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [hide])}[2]
    grs = job["groupRemove"]
    assert len(grs) == 1
    assert grs[0]["kindIndex"] == -1 and grs[0]["childSig"] == "side\nlist" and grs[0]["expectedKeep"] == 0


def test_reuse_nonreuse_donor_hide_seeds_no_phantom_surplus():
    """A group hidden on a NON-reuse donor (slide 1) is deleted there by deleteHides, so it
    never enters the donor's output; when it is absent on the target its partition remove is
    capped to zero — no phantom surplus, no synthetic."""
    from obed_edom.map_remap import ItemTransform, plan_slide_reuses

    wall = _reuse_chain([
        ([_grp(50, 4600, "hidden\ngroup")[0]], {50: "hidden\ngroup"}),
        ([], {}),
    ])
    hide = ItemTransform(slide_number=1, item_index=50, kind="group", kind_index=50, role="hide", x=1, y=1, w=1, h=1)
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [hide])}[2]
    assert "groupRemove" not in job  # capped away, no fake surplus


def test_reuse_group_without_gct_entry_stays_sig_less_amid_signed_peers():
    """Rule D: a removed donor group with no groupChildText entry is EXCLUDED from the
    output/keep counts and emits a sig-less passthrough ref — never a synthetic carrying a
    fabricated signature — even alongside a peer group that does have a signature."""
    from obed_edom.map_remap import plan_slide_reuses

    signed = _grp(50, 4600, "27\nSchools")[0]
    unsigned = _grp(51, 4739, None)[0]  # no gct entry for kindIndex 51
    wall = _reuse_chain([
        ([dict(signed), dict(unsigned)], {50: "27\nSchools"}),
        ([], {}),
    ])
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    grs = job["groupRemove"]
    sigless = [r for r in grs if "childSig" not in r]
    signed_refs = [r for r in grs if r.get("childSig") == "27\nSchools"]
    assert len(sigless) == 1 and sigless[0]["kindIndex"] == 51
    assert len(signed_refs) == 1 and signed_refs[0]["kindIndex"] == 50
    assert not any(r.get("kindIndex") == -1 for r in grs)  # no fabricated-sig synthetic


def test_reuse_stray_outliving_keeper_downgrades_to_sig_less():
    """Wrong-survivor guard (amendment C): two same-sig twins on slide 1 (kindIndex 50/51);
    only the ki-50 copy persists to slide 2, the ki-51 copy is partition-removed. In the live
    output the persisted keeper sits BELOW the inherited stray, but the dedup keeps the
    highest index — so count-scoping would delete the keeper. The planner detects the stray
    as the predicted survivor and downgrades that signature to a sig-less (fail-loud) ref."""
    from obed_edom.map_remap import plan_slide_reuses

    keeper = _grp(50, 4600, "twin")[0]
    twin = _grp(51, 4739, "twin")[0]
    wall = _reuse_chain([
        ([dict(keeper), dict(twin)], {50: "twin", 51: "twin"}),
        ([dict(keeper)], {50: "twin"}),  # only ki-50 twin persists
    ])
    job = {j["slide"]: j for j in plan_slide_reuses(wall, [])}[2]
    grs = job["groupRemove"]
    assert len(grs) == 1
    assert "childSig" not in grs[0] and "expectedKeep" not in grs[0]
    assert grs[0]["kindIndex"] == 51  # the partitioned twin, emitted sig-less
