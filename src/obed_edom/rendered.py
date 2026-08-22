"""What the audience actually reads on a slide.

`inspect_keynote` sees only what Keynote's scripting API exposes: loose text
items. Anything inside a group, or set as part of an image, comes back empty.
This module merges that extraction with OCR of the exported preview so every
text rule compares the rendered slide rather than a partial one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from obed_edom.inspect import PREVIEW_VIDEO_SUFFIXES, slide_plain_text
from obed_edom.ocr import ocr_lines, vision_error, word_shapes

CENTER_WALL = (3840, 1080)
_SOFT_WS = re.compile(r"[\s\u2028\u2029\xa0]+")
_PUNCT = re.compile(r"[^0-9a-z]+")
_STANDALONE_NUMBER = re.compile(r"^\d{1,2}$")


def center_wall_box(slide_w: float, slide_h: float) -> tuple[float, float, float, float]:
    """Slide-space box for the 3840x1080 center wall. Sides outside it are decorative."""
    wall_w, wall_h = CENTER_WALL
    if slide_w <= 0 or slide_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    if slide_w <= wall_w:
        return (0.0, 0.0, slide_w, min(slide_h, wall_h))
    x0 = (slide_w - wall_w) / 2.0
    return (x0, 0.0, x0 + wall_w, min(slide_h, wall_h))


def normal_line(text: str) -> str:
    """Aggressive fold used only to decide whether two lines say the same thing."""
    folded = _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip().lower()
    return _PUNCT.sub(" ", folded).strip()


def _pixel_wall_box(
    png: Path, slide_size: tuple[float, float]
) -> tuple[float, float, float, float] | None:
    """Convert the center wall into preview pixels, or None to read the whole frame."""
    slide_w, slide_h = slide_size
    if slide_w <= CENTER_WALL[0] or slide_h <= 0:
        return None
    size = None
    try:
        from obed_edom.images import image_size  # noqa: PLC0415

        size = image_size(png)
    except Exception:  # noqa: BLE001
        size = None
    if not size:
        return None
    width, height = size
    x0, y0, x1, y1 = center_wall_box(slide_w, slide_h)
    sx = width / slide_w
    sy = height / slide_h
    return (x0 * sx, y0 * sy, x1 * sx, y1 * sy)


NEAR_DUPLICATE = 0.9
NEAR_DUPLICATE_MIN_CHARS = 18


def dedup_lines(lines: list[str]) -> list[str]:
    """Keep the first occurrence of each line.

    An LW wall repeats the same text box on the left and right of the center
    panel; without this every verse would look like it was written twice. The
    mirrored copy is often clipped, so near-duplicates are folded in too, which
    also stops a half-read verse marker from being taken for a second verse.
    """
    from obed_edom.text_diff import text_score  # noqa: PLC0415

    seen: set[str] = set()
    kept: list[tuple[str, str]] = []
    for line in lines:
        key = normal_line(line)
        if not key or key in seen:
            continue
        if len(key) >= NEAR_DUPLICATE_MIN_CHARS and any(
            text_score(key, other) >= NEAR_DUPLICATE for other, _ in kept
        ):
            continue
        seen.add(key)
        kept.append((key, line.strip()))

    # A clipped mirror reads as a fragment of the full line, and OCR drops the
    # space after a verse marker often enough that similarity alone misses it.
    squashed = [(key.replace(" ", ""), text) for key, text in kept]
    out: list[str] = []
    for index, (bare, text) in enumerate(squashed):
        swallowed = any(
            len(bare) >= 12 and len(bare) < len(other) and bare in other
            for position, (other, _) in enumerate(squashed)
            if position != index
        )
        if not swallowed:
            out.append(text)
    return out


def _slide_box_of(
    line, wall: tuple[float, float, float, float], slide_size: tuple[float, float]
) -> tuple[float, float, float, float]:
    """An OCR line's box in slide coordinates.

    Vision normalises to the image it was handed, which is the center-wall crop
    on a wide LW export, so the crop's slide rect is what the fractions span.
    """
    if wall[2] > wall[0]:
        x0, y0, x1, y1 = wall
    else:
        x0, y0, x1, y1 = 0.0, 0.0, slide_size[0], slide_size[1]
    width = x1 - x0
    height = y1 - y0
    return (
        x0 + line.x0 * width,
        y0 + line.y0 * height,
        x0 + line.x1 * width,
        y0 + line.y1 * height,
    )


def _outside_photos(lines, slide: dict, slide_size: tuple[float, float]) -> list[str]:
    """OCR lines that are not sitting inside a pasted graphic.

    Text baked into a screenshot belongs to the `photo.*` rules, which compare
    the picture itself. Reading it as slide copy turns a stylised logo into a
    wording difference every time OCR spells it differently.
    """
    if not lines:
        return []
    from obed_edom.photo_regions import content_regions  # noqa: PLC0415

    try:
        regions = content_regions(slide, slide_size)
    except Exception:  # noqa: BLE001
        regions = []
    if not regions:
        return [line.text for line in lines]
    wall = center_wall_box(*slide_size)
    kept: list[str] = []
    for line in lines:
        bx0, by0, bx1, by1 = _slide_box_of(line, wall, slide_size)
        cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
        inside = any(
            region.x <= cx <= region.x + region.w and region.y <= cy <= region.y + region.h
            for region in regions
        )
        if not inside:
            kept.append(line.text)
    return kept


@dataclass(frozen=True)
class RenderedSlide:
    text: str
    extracted: str
    ocr: str
    ocr_used: bool = False
    lines: tuple[str, ...] = field(default_factory=tuple)
    # `text` minus OCR that lands inside a pasted graphic. Used for the wording
    # diff so a stylised logo does not read as rewritten copy.
    outside_photos: str = ""

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def typed(self) -> str:
        """`extracted` with the wall's mirrored boxes folded, as `text` already is.

        The LW repeats a verse box either side of the center panel, so the raw
        extraction reads as the verse written twice.
        """
        return "\n".join(dedup_lines([ln for ln in self.extracted.split("\n") if ln.strip()]))


def render_slide(
    slide: dict,
    png: Path | str | None,
    slide_size: tuple[float, float] = (0.0, 0.0),
    *,
    use_ocr: bool = True,
) -> RenderedSlide:
    """Merge extracted text with OCR lines the extraction missed."""
    extracted = slide_plain_text(slide)
    extracted_lines = [ln for ln in extracted.split("\n") if ln.strip()]
    ocr_text_lines: list[str] = []
    clean_ocr_lines: list[str] = []
    if use_ocr and png:
        path = Path(png)
        if path.suffix.lower() not in PREVIEW_VIDEO_SUFFIXES:
            box = _pixel_wall_box(path, slide_size)
            found = ocr_lines(path, box=box)
            ocr_text_lines = [line.text for line in found]
            clean_ocr_lines = _outside_photos(found, slide, slide_size)

    lines = dedup_lines(_merge_ocr(extracted_lines, ocr_text_lines))
    clean = dedup_lines(_merge_ocr(extracted_lines, clean_ocr_lines))
    return RenderedSlide(
        text="\n".join(lines),
        extracted=extracted,
        ocr="\n".join(dedup_lines(ocr_text_lines)),
        ocr_used=bool(ocr_text_lines),
        lines=tuple(lines),
        outside_photos="\n".join(clean),
    )


def _merge_ocr(extracted_lines: list[str], ocr_text_lines: list[str]) -> list[str]:
    covered = normal_line(" ".join(extracted_lines))
    merged = list(extracted_lines)
    for line in ocr_text_lines:
        key = normal_line(line)
        if not key or (covered and key in covered):
            continue
        # An OCR line that swallows an extracted one saw more than the scripting
        # API did, e.g. a point number set as part of the title graphic.
        superset = next(
            (
                index
                for index, existing in enumerate(merged)
                if normal_line(existing) and normal_line(existing) in key
            ),
            None,
        )
        if superset is not None:
            merged[superset] = line
            continue
        merged.append(line)
    return merged


def point_number_lines(source: RenderedSlide | str) -> set[str]:
    """Standalone point numbers, e.g. the '3' beside a Faith title on the wall.

    LW carries them; the DSK lower third does not. They are layout, not copy.
    """
    if isinstance(source, RenderedSlide):
        lines = source.lines
    else:
        lines = (source or "").split("\n")
    return {ln.strip() for ln in lines if _STANDALONE_NUMBER.match(ln.strip())}


def ocr_unavailable() -> str | None:
    return vision_error()


def word_is_small_caps(
    png: Path | str | None,
    word: str,
    slide_size: tuple[float, float] = (0.0, 0.0),
) -> bool | None:
    """Is every rendering of `word` on this slide set in small caps?

    None when the shape could not be measured, so callers stay quiet rather
    than guess.
    """
    if not png:
        return None
    box = _pixel_wall_box(Path(png), slide_size)
    shapes = word_shapes(png, word, box=box)
    if not shapes:
        return None
    return all(shape.small_caps for shape in shapes)
