from obed_edom.map_remap import (
    Rect,
    cover_rect,
    is_map_item,
    is_pin_item,
    item_center,
    learn_recipe,
    map_point,
    plan_payload_transforms,
    recipe_from_cover,
    score_against_gold,
    summarize_plan,
)


def _item(**kwargs):
    rec = {"index": 0, "kind": "shape", "x": 0, "y": 0, "w": 10, "h": 10, "text": "", "fileName": "", "locked": False}
    rec.update(kwargs)
    return rec


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
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=0, w=7680, h=1080),
                    _item(index=1, kind="movie", fileName="PIN DROP WAVE-1.mov", x=3815, y=515, w=50, h=50),
                    _item(index=2, kind="text", text="CHC Prai", x=6000, y=80, w=400, h=40, size=36),
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
                    _item(index=0, kind="image", fileName="map BG-1.png", x=0, y=200, w=1920, h=270),
                    _item(index=1, kind="movie", fileName="PIN DROP WAVE-1.mov", x=935, y=310, w=50, h=50),
                    _item(index=2, kind="text", text="CHC Prai", x=1400, y=40, w=480, h=48, size=28),
                ],
            }
        ],
    }
    recipe = learn_recipe(wall, gold)
    assert recipe["source"] == "gold"
    assert recipe["mapDst"]["y"] == 200
    assert recipe["pinPairs"] == 1
    assert recipe["pinRmse"] is not None
    assert recipe["pinRmse"] < 5
    assert "listSrc" in recipe
    transforms = plan_payload_transforms(wall, recipe)
    counts = summarize_plan(transforms)
    assert counts["map"] == 1
    assert counts["pin"] == 1
    assert counts["list"] == 1
    pin = next(t for t in transforms if t.role == "pin")
    assert abs((pin.x + pin.w / 2) - 960) < 1
    assert abs((pin.y + pin.h / 2) - 335) < 1
    assert abs(pin.w - 50) < 1
    score = score_against_gold(transforms, gold)
    assert score["pinPairs"] == 1
    assert score["pinRmse"] < 5


def test_classifies_map_and_pin_by_filename():
    assert is_map_item(_item(kind="image", fileName="Data/map BG-39230.png", w=7680, h=1080))
    assert is_pin_item(_item(kind="movie", fileName="PIN DROP WAVE-71712.mov", w=500, h=500))
    assert not is_pin_item(_item(kind="image", fileName="34. CHC Kotagiri-76091.JPG", w=800, h=600))


def test_cover_rect_fills_16x9():
    dst = cover_rect(Rect(0, 0, 7680, 1080), 1920, 1080)
    assert dst.h == 1080
    assert dst.w == 7680
    assert item_center({"x": dst.x, "y": dst.y, "w": dst.w, "h": dst.h})[0] == 960
