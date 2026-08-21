"""Shared PIL decode cache. A 7680×1080 PNG was being opened 3–5 times per run."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PIL import Image

_MAX = 48
_CACHE: OrderedDict[tuple[str, int, int], Image.Image] = OrderedDict()


def _key(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path.resolve()), int(stat.st_size), int(stat.st_mtime))


def open_rgb(path: Path | str) -> Image.Image:
    """Decoded RGB image. Callers must not close or mutate the returned object."""
    png = Path(path)
    key = _key(png)
    if key and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    image = Image.open(png).convert("RGB")
    if key:
        _CACHE[key] = image
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX:
            _CACHE.popitem(last=False)
    return image


def image_size(path: Path | str) -> tuple[int, int] | None:
    try:
        im = open_rgb(path)
    except OSError:
        return None
    return im.size


def clear_cache() -> None:
    _CACHE.clear()
