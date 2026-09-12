from __future__ import annotations

from pathlib import Path

from PIL import Image

from obed_edom.maps_keynote import parse_color
from obed_edom.maps_pins import (
    PIN_ASPECT,
    RENDER_VERSION,
    ensure_pin_png,
    pin_png_path,
    render_dot,
    render_drop_pin,
)

ORANGE = parse_color("#ff8a00")
RED = parse_color("#c44a42")


def test_dot_is_rgba_with_transparent_corners_and_an_opaque_centre():
    image = render_dot(RED)
    assert image.mode == "RGBA"
    assert image.size == (512, 512)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((511, 0))[3] == 0
    red, green, blue, alpha = image.getpixel((256, 256))
    assert alpha == 255
    assert (red, green, blue) == (0xC4, 0x4A, 0x42)


def test_dot_alpha_bbox_fills_the_canvas():
    image = render_dot(ORANGE)
    left, top, right, bottom = image.getchannel("A").getbbox()
    assert left <= 1 and top <= 1
    assert right >= image.width - 1 and bottom >= image.height - 1


def test_drop_pin_has_the_keynote_aspect_and_a_tip_at_the_bottom_centre():
    image = render_drop_pin(ORANGE)
    assert image.mode == "RGBA"
    assert image.size == (512, round(512 * PIN_ASPECT))
    alpha = image.getchannel("A")
    left, top, right, bottom = alpha.getbbox()
    assert left <= 1 and top <= 1
    assert right >= image.width - 1 and bottom >= image.height - 1
    # The last opaque row is the tail tip: a couple of pixels wide, centred.
    row = image.height - 2
    opaque = [x for x in range(image.width) if alpha.getpixel((x, row)) > 128]
    assert opaque
    assert abs(sum(opaque) / len(opaque) - image.width / 2) <= 2
    assert len(opaque) <= 8


def test_drop_pin_hole_is_opaque_white_and_the_head_is_the_requested_colour():
    image = render_drop_pin(ORANGE)
    centre = (image.width // 2, image.width // 2)
    assert image.getpixel(centre) == (255, 255, 255, 255)
    red, green, blue, alpha = image.getpixel((image.width // 2, 8))
    assert alpha == 255
    assert (red, green, blue) == (0xFF, 0x8A, 0x00)


def test_dot_has_no_stroke_ring_around_the_edge():
    image = render_dot(RED)
    rim = image.getpixel((image.width // 2, 3))
    assert rim[3] == 255
    assert rim[:3] == (0xC4, 0x4A, 0x42)


def test_filename_is_content_addressed_and_stable(tmp_path: Path):
    assert pin_png_path(tmp_path, "dot", RED).name == f"dot-c44a42-v{RENDER_VERSION}.png"
    assert pin_png_path(tmp_path, "droppin", ORANGE).name == f"droppin-ff8a00-v{RENDER_VERSION}.png"
    assert pin_png_path(tmp_path, "dot", RED) != pin_png_path(tmp_path, "dot", ORANGE)


def test_ensure_pin_png_writes_once_and_reuses_the_file(tmp_path: Path):
    root = tmp_path / "pins"
    first = ensure_pin_png(root, "droppin", ORANGE)
    assert first.is_file()
    assert first == pin_png_path(root, "droppin", ORANGE)
    marker = b"untouched"
    first.write_bytes(marker)

    again = ensure_pin_png(root, "droppin", ORANGE)

    assert again == first
    assert first.read_bytes() == marker


def test_ensure_pin_png_renders_each_kind_at_its_own_aspect(tmp_path: Path):
    with Image.open(ensure_pin_png(tmp_path, "dot", RED)) as dot:
        assert dot.size == (512, 512)
    with Image.open(ensure_pin_png(tmp_path, "droppin", RED)) as pin:
        assert pin.size == (512, round(512 * PIN_ASPECT))
