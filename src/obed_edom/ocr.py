"""On-device OCR of exported slide previews via the macOS Vision framework.

Keynote cannot read groups or baked-in image text. Local only; no writes to .key.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CACHE_VERSION = 3
MIN_CONFIDENCE = 0.4

_VISION_ERROR: str | None = None
_VISION_READY = False


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)


def _load_vision():
    """macOS-only; slow to import."""
    global _VISION_READY, _VISION_ERROR
    try:
        import Quartz  # noqa: PLC0415
        import Vision  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _VISION_ERROR = f"macOS Vision is unavailable ({exc})."
        return None
    _VISION_READY = True
    return Quartz, Vision, NSURL


def vision_error() -> str | None:
    if _VISION_READY:
        return None
    return _VISION_ERROR


def _cache_path(png: Path) -> Path:
    return png.with_suffix(png.suffix + ".ocr.json")


def _cache_key(png: Path, box: tuple[float, float, float, float] | None) -> dict:
    try:
        stat = png.stat()
    except OSError:
        return {}
    return {
        "version": CACHE_VERSION,
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
        "box": [round(v, 4) for v in box] if box else None,
    }


def _read_cache(png: Path, key: dict) -> list[OcrLine] | None:
    path = _cache_path(png)
    if not key or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("key") != key:
        return None
    return [OcrLine(**line) for line in data.get("lines") or []]


def _write_cache(png: Path, key: dict, lines: list[OcrLine]) -> None:
    if not key:
        return
    payload = {"key": key, "lines": [line.__dict__ for line in lines]}
    try:
        _cache_path(png).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def ocr_lines(
    png: Path | str,
    *,
    box: tuple[float, float, float, float] | None = None,
) -> list[OcrLine]:
    """Top to bottom. Empty when Vision cannot run. `box` is a pixel rect (center wall)."""
    global _VISION_ERROR
    png = Path(png)
    if not png.is_file():
        return []
    key = _cache_key(png, box)
    cached = _read_cache(png, key)
    if cached is not None:
        return cached
    loaded = _load_vision()
    if loaded is None:
        return []
    Quartz, Vision, NSURL = loaded

    url = NSURL.fileURLWithPath_(str(png))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return []
    if box:
        image = _crop(Quartz, image, box)
        if image is None:
            return []

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    try:
        ok, _err = handler.performRequests_error_([request], None)
    except Exception as exc:  # noqa: BLE001
        _VISION_ERROR = f"Vision text recognition failed ({exc})."
        return []
    if not ok:
        _VISION_ERROR = "Vision text recognition returned no result."
        return []

    lines: list[OcrLine] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        best = candidates[0]
        text = str(best.string() or "").strip()
        confidence = float(best.confidence())
        if not text or confidence < MIN_CONFIDENCE:
            continue
        rect = observation.boundingBox()
        # Vision origin is bottom-left; flip to top-left for Keynote coords.
        x0 = float(rect.origin.x)
        width = float(rect.size.width)
        height = float(rect.size.height)
        y0 = 1.0 - float(rect.origin.y) - height
        lines.append(
            OcrLine(
                text=text,
                confidence=round(confidence, 3),
                x0=round(x0, 4),
                y0=round(y0, 4),
                x1=round(x0 + width, 4),
                y1=round(y0 + height, 4),
            )
        )
    lines.sort(key=lambda line: (round(line.y0 / 0.04), line.x0))
    _write_cache(png, key, lines)
    return lines


def _crop(Quartz, image, box: tuple[float, float, float, float]):
    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)
    x0 = max(0, int(box[0]))
    y0 = max(0, int(box[1]))
    x1 = min(width, int(box[2]))
    y1 = min(height, int(box[3]))
    if x1 <= x0 or y1 <= y0:
        return image
    if x0 == 0 and y0 == 0 and x1 == width and y1 == height:
        return image
    rect = Quartz.CGRectMake(x0, y0, x1 - x0, y1 - y0)
    return Quartz.CGImageCreateWithImageInRect(image, rect)


def ocr_text(png: Path | str, *, box: tuple[float, float, float, float] | None = None) -> str:
    return "\n".join(line.text for line in ocr_lines(png, box=box))


# Small-capped LORD OCRs as "Lord". Ascender drop vs cap-line "d" is the tell.
SMALL_CAPS_RATIO = 0.05
_INK_THRESHOLD = 60


@dataclass(frozen=True)
class WordShape:
    text: str
    small_caps: bool
    drop: float
    context: str = ""


def word_shapes(
    png: Path | str,
    word: str,
    *,
    box: tuple[float, float, float, float] | None = None,
) -> list[WordShape]:
    png = Path(png)
    if not png.is_file() or len(word) < 3:
        return []
    key = _cache_key(png, box) | {"word": word}
    cached = _read_shape_cache(png, key)
    if cached is not None:
        return cached
    loaded = _load_vision()
    if loaded is None:
        return []
    Quartz, Vision, NSURL = loaded
    try:
        from Foundation import NSRange  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []

    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(png)), None)
    if source is None:
        return []
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        return []
    offset_x, offset_y = 0, 0
    full_w, full_h = Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)
    if box:
        offset_x, offset_y = max(0, int(box[0])), max(0, int(box[1]))
        image = _crop(Quartz, image, box)
        if image is None:
            return []
    width = Quartz.CGImageGetWidth(image)
    height = Quartz.CGImageGetHeight(image)

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    try:
        ok, _ = handler.performRequests_error_([request], None)
    except Exception:  # noqa: BLE001
        return []
    if not ok:
        return []

    with Image.open(png) as raw:
        grey = raw.convert("L")
        if box:
            grey = grey.crop((offset_x, offset_y, offset_x + width, offset_y + height))
        elif (grey.width, grey.height) != (full_w, full_h):
            grey = grey.resize((full_w, full_h))

    shapes: list[WordShape] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        best = candidates[0]
        text = str(best.string() or "")
        start = 0
        while True:
            found = text.find(word, start)
            if found < 0:
                break
            start = found + 1
            try:
                region, _ = best.boundingBoxForRange_error_(NSRange(found, len(word)), None)
            except Exception:  # noqa: BLE001
                region = None
            if region is None:
                continue
            drop = _ascender_drop(grey, region.boundingBox())
            if drop is None:
                continue
            shapes.append(
                WordShape(
                    text=word,
                    small_caps=drop >= SMALL_CAPS_RATIO,
                    drop=round(drop, 3),
                    context=text[max(0, found - 12) : found + len(word) + 12],
                )
            )
    _write_shape_cache(png, key, shapes)
    return shapes


def _ascender_drop(grey, rect) -> float | None:
    """Near zero = normal case; clearly positive = remaining letters are small caps."""
    try:
        import numpy as np  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    width, height = grey.size
    x0 = int(rect.origin.x * width)
    x1 = int((rect.origin.x + rect.size.width) * width)
    y0 = int((1 - rect.origin.y - rect.size.height) * height)
    y1 = int((1 - rect.origin.y) * height)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    patch = np.asarray(grey.crop((x0, y0, x1, y1))).astype(float)
    if patch.size == 0:
        return None
    ink = np.abs(patch - np.median(patch)) > _INK_THRESHOLD
    if not ink.any():
        return None
    tops = np.full(ink.shape[1], -1)
    for column in range(ink.shape[1]):
        rows = np.where(ink[:, column])[0]
        if len(rows):
            tops[column] = rows[0]
    filled = np.where(tops >= 0)[0]
    if len(filled) < 4:
        return None
    gaps = np.where(np.diff(filled) > 2)[0]
    first_end = filled[gaps[0]] if len(gaps) else filled[len(filled) // 4]
    head = filled[filled <= first_end]
    tail = filled[filled > first_end]
    if len(head) == 0 or len(tail) == 0:
        return None
    return float((tops[tail].min() - tops[head].min()) / ink.shape[0])


def _shape_cache_path(png: Path) -> Path:
    return png.with_suffix(png.suffix + ".caps.json")


def _read_shape_cache(png: Path, key: dict) -> list[WordShape] | None:
    path = _shape_cache_path(png)
    if not key or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("key") != key:
        return None
    return [WordShape(**shape) for shape in data.get("shapes") or []]


def _write_shape_cache(png: Path, key: dict, shapes: list[WordShape]) -> None:
    if not key:
        return
    payload = {"key": key, "shapes": [shape.__dict__ for shape in shapes]}
    try:
        _shape_cache_path(png).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def clear_cache(folder: Path | str) -> int:
    removed = 0
    for pattern in ("*.ocr.json", "*.caps.json"):
        for path in Path(folder).rglob(pattern):
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed
