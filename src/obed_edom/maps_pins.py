"""Raster dot and drop-pin markers.

Keynote 15.3's `shape` class exposes no writable fill, so markers are rendered
to PNG and placed as images. The rasters are scale-invariant: Keynote stretches
them, so size and zoom stay out of the cache key.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

RENDER_VERSION = 1

DOT_PX = 512
PIN_ASPECT = 1.08
SUPERSAMPLE = 4

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
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((0, 0, size - 1, size - 1), fill=(*_rgb8(color), 255))
    return _downscale(image, DOT_PX, DOT_PX)


def render_drop_pin(color: tuple[int, int, int]) -> Image.Image:
    width, height = DOT_PX, round(DOT_PX * PIN_ASPECT)
    w, h = width * SUPERSAMPLE, height * SUPERSAMPLE
    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    fill = (*_rgb8(color), 255)
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


def ensure_pin_png(root: Path, kind: str, color: tuple[int, int, int]) -> Path:
    path = pin_png_path(root, kind, color)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    image = render_drop_pin(color) if kind == "droppin" else render_dot(color)
    image.save(path, "PNG")
    return path
