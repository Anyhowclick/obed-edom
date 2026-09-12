"""Raster dot and drop-pin markers.

In Keynote 15.3 `make new shape with properties {shape type:...}` fails to
compile (AppleScript error -2741), so markers are rendered to PNG and placed as
images. The rasters are scale-invariant: Keynote stretches them, so size and
zoom stay out of the cache key.

Label pills are the exception: a rounded rectangle is NOT scale-invariant
(stretching one ovals its corners), so `render_label_pill` renders at the
requested aspect and the cache key carries a quantised aspect bucket.

Changing `_TAIL_W`, `_TAIL_TOP`, `_HOLE`, `PIN_ASPECT`, `DOT_PX`,
`PILL_PX`, `LABEL_RADIUS_FRAC` or `LABEL_ASPECT_STEP` changes the pixels
behind a cached filename and requires bumping `RENDER_VERSION`.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RENDER_VERSION = 2

DOT_PX = 512
PIN_ASPECT = 1.08
SUPERSAMPLE = 4

# Gold_Wall_Input.key slide 8: corner scalar 9.57 at h~46 -> radius ~= 0.21*h.
LABEL_PILL_RGB = (0xEE * 257, 0x22 * 257, 0x0C * 257)
LABEL_RADIUS_FRAC = 0.21
LABEL_ASPECT_STEP = 0.25
PILL_PX = 128

_TAIL_W = 0.46
_TAIL_TOP = 0.68
_HOLE = 0.36


def _rgb8(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(channel / 257))) for channel in color)  # type: ignore[return-value]


def _hex6(color: tuple[int, int, int]) -> str:
    return "%02x%02x%02x" % _rgb8(color)


def pin_png_path(root: Path, kind: str, color: tuple[int, int, int]) -> Path:
    return Path(root) / f"{kind}-{_hex6(color)}-v{RENDER_VERSION}.png"


def _downscale(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.resize((width, height), Image.LANCZOS)


def render_dot(color: tuple[int, int, int]) -> Image.Image:
    size = DOT_PX * SUPERSAMPLE
    rgb = _rgb8(color)
    image = Image.new("RGBA", (size, size), (*rgb, 0))
    ImageDraw.Draw(image).ellipse((0, 0, size - 1, size - 1), fill=(*rgb, 255))
    return _downscale(image, DOT_PX, DOT_PX)


def render_drop_pin(color: tuple[int, int, int]) -> Image.Image:
    width, height = DOT_PX, round(DOT_PX * PIN_ASPECT)
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    rgb = _rgb8(color)
    image = Image.new("RGBA", (w, h), (*rgb, 0))
    draw = ImageDraw.Draw(image)
    fill = (*rgb, 255)
    tail_w = w * _TAIL_W
    draw.polygon(
        [((w - tail_w) / 2, w * _TAIL_TOP), ((w + tail_w) / 2, w * _TAIL_TOP), (w / 2, h)],
        fill=fill,
    )
    draw.ellipse((0, 0, w - 1, w - 1), fill=fill)
    hole = w * _HOLE
    draw.ellipse(
        ((w - hole) / 2, (w - hole) / 2, (w + hole) / 2, (w + hole) / 2),
        fill=(255, 255, 255, 255),
    )
    return _downscale(image, width, height)


def label_aspect_bucket(aspect: float) -> float:
    steps = max(1, round(float(aspect) / LABEL_ASPECT_STEP))
    return round(steps * LABEL_ASPECT_STEP, 2)


def label_pill_png_path(root: Path, color: tuple[int, int, int], aspect: float) -> Path:
    bucket = f"{label_aspect_bucket(aspect):.2f}".replace(".", "_")
    return Path(root) / f"labelpill-{_hex6(color)}-a{bucket}-v{RENDER_VERSION}.png"


def render_label_pill(color: tuple[int, int, int], aspect: float) -> Image.Image:
    height = PILL_PX
    width = max(1, round(height * label_aspect_bucket(aspect)))
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    rgb = _rgb8(color)
    image = Image.new("RGBA", (w, h), (*rgb, 0))
    ImageDraw.Draw(image).rounded_rectangle(
        (0, 0, w - 1, h - 1),
        radius=LABEL_RADIUS_FRAC * h,
        fill=(*rgb, 255),
    )
    return _downscale(image, width, height)


def ensure_label_pill_png(root: Path, color: tuple[int, int, int], aspect: float) -> Path:
    path = label_pill_png_path(root, color, aspect)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    render_label_pill(color, aspect).save(path, "PNG")
    return path


def ensure_pin_png(root: Path, kind: str, color: tuple[int, int, int]) -> Path:
    path = pin_png_path(root, kind, color)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    image = render_drop_pin(color) if kind == "droppin" else render_dot(color)
    image.save(path, "PNG")
    return path
