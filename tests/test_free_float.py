"""Which wall text is free to be re-placed when the slide is cropped to 16:9."""

from obed_edom.map_remap import (
    Rect,
    is_backdrop,
    occluder_rects,
    sits_on_background,
)

WALL_W, WALL_H = 7680.0, 1080.0


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


def test_full_canvas_art_is_a_backdrop_not_an_occluder():
    backdrop = _item(kind="image", fileName="LED blank-1.png", x=0, y=0, w=7680, h=1080)
    assert is_backdrop(backdrop, WALL_W, WALL_H)
    plate = _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771)
    assert not is_backdrop(plate, WALL_W, WALL_H)


def test_side_panel_list_counts_as_free_to_move():
    slide = {
        "items": [
            _item(kind="image", fileName="LED blank-1.png", x=0, y=0, w=7680, h=1080),
            _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
            _item(kind="text", text="CHC Aaliana\nCHC Bais", x=6200, y=80, w=400, h=500),
        ]
    }
    occluders = occluder_rects(slide, WALL_W, WALL_H)
    # The backdrop must not appear, or nothing would ever look free.
    assert occluders == [Rect(3052, -12, 1248, 771)]
    assert sits_on_background(slide["items"][2], occluders)


def test_label_on_the_map_is_pinned_to_it():
    slide = {
        "items": [
            _item(kind="image", fileName="pasted-image.pdf", x=3052, y=-12, w=1248, h=771),
            _item(kind="text", text="Indonesia", x=3600, y=400, w=200, h=40),
        ]
    }
    occluders = occluder_rects(slide, WALL_W, WALL_H)
    assert not sits_on_background(slide["items"][1], occluders)


def test_text_touching_a_pin_is_pinned():
    pin = _item(kind="movie", fileName="PIN DROP WAVE-1.mov", x=3800, y=500, w=60, h=60)
    label = _item(kind="text", text="CHC Prai", x=3840, y=520, w=180, h=30)
    occluders = occluder_rects({"items": [pin]}, WALL_W, WALL_H)
    assert not sits_on_background(label, occluders)


def test_chrome_tiles_are_ignored():
    """The 1920x1080 LED panel tiles are chrome; text over them is still free."""
    slide = {
        "items": [
            _item(kind="image", fileName="Data/map BG-39230.png", x=0, y=0, w=1920, h=1080),
            _item(kind="text", text="CHC Aaliana", x=200, y=200, w=300, h=400),
        ]
    }
    occluders = occluder_rects(slide, WALL_W, WALL_H)
    assert occluders == []
    assert sits_on_background(slide["items"][1], occluders)


def test_duplicate_shape_twin_is_not_its_own_occluder():
    """A text-bearing shape Keynote listed twice must not occlude its own text."""
    slide = {
        "items": [
            _item(kind="text", text="Genesis 1", x=2304, y=21, w=626, h=92, kindIndex=0),
            _item(
                kind="shape",
                text="Genesis 1",
                x=2304,
                y=21,
                w=626,
                h=92,
                kindIndex=0,
                duplicateOf={"kind": "text", "kindIndex": 0},
            ),
        ]
    }
    occluders = occluder_rects(slide, WALL_W, WALL_H)
    assert occluders == []
    assert sits_on_background(slide["items"][0], occluders)


def test_non_text_is_never_free_to_move():
    assert not sits_on_background(_item(kind="image", w=100, h=100), [])
