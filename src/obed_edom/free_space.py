"""Pixel occupancy of a slide, then pack loose text boxes into empty cells.

Rect occupancy cannot help: the map image covers the whole CG frame while most
of it is ocean. Background-coloured pixels are free; inked ones are not.
Integral image over an 8px grid, no numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

# 8px cells at 1920×1080 → 240×135: fine enough for coastlines, cheap enough.
DEFAULT_CELL = 8
# RGB distance at which a pixel stops counting as background (PNG noise / vignette).
DEFAULT_TOLERANCE = 38.0
# Occupied when this fraction of the cell is non-background (keep low for antialiased edges).
DEFAULT_INK_FRACTION = 0.12


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float
    h: float

    def moved_to(self, x: float, y: float) -> Box:
        return Box(x, y, self.w, self.h)


@dataclass(frozen=True)
class Placement:
    """Placed box. ``overlap`` > 0 means it sat on artwork (operator should look)."""

    box: Box
    overlap: float

    @property
    def clean(self) -> bool:
        return self.overlap <= 0.0


def background_colour(im: Image.Image, *, sample: int = 160) -> tuple[int, int, int]:
    """Dominant flat colour. Quantise first so JPEG noise cannot split one navy into hundreds of votes."""
    small = im.convert("RGB")
    if max(small.size) > sample:
        small.thumbnail((sample, sample))
    quantised = small.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
    palette = quantised.getpalette() or []
    counts = quantised.getcolors() or []
    if not counts or not palette:
        return (0, 0, 0)
    _, index = max(counts, key=lambda pair: pair[0])
    base = index * 3
    return (palette[base], palette[base + 1], palette[base + 2])


class FreeSpace:
    """Occupancy grid with O(1) region sums."""

    def __init__(self, cols: int, rows: int, occupied: list[bool], cell: int) -> None:
        self.cols = cols
        self.rows = rows
        self.cell = cell
        self._occupied = occupied
        self._rebuild()

    def _rebuild(self) -> None:
        # Integral occupancy with a zero pad so a region sum never needs a bounds check.
        cols, rows = self.cols, self.rows
        total = [0] * ((cols + 1) * (rows + 1))
        for r in range(rows):
            row_base = (r + 1) * (cols + 1)
            prev_base = r * (cols + 1)
            for c in range(cols):
                total[row_base + c + 1] = (
                    total[row_base + c]
                    + total[prev_base + c + 1]
                    - total[prev_base + c]
                    + (1 if self._occupied[r * cols + c] else 0)
                )
        self._sums = total

    def occupied_cells(self, c0: int, r0: int, c1: int, r1: int) -> int:
        """Occupied cells in half-open [c0,c1) × [r0,r1)."""
        c0 = max(0, min(self.cols, c0))
        c1 = max(0, min(self.cols, c1))
        r0 = max(0, min(self.rows, r0))
        r1 = max(0, min(self.rows, r1))
        if c1 <= c0 or r1 <= r0:
            return 0
        stride = self.cols + 1
        return (
            self._sums[r1 * stride + c1]
            - self._sums[r0 * stride + c1]
            - self._sums[r1 * stride + c0]
            + self._sums[r0 * stride + c0]
        )

    def is_free(self, box: Box) -> bool:
        c0 = int(box.x // self.cell)
        r0 = int(box.y // self.cell)
        c1 = int((box.x + box.w + self.cell - 1) // self.cell)
        r1 = int((box.y + box.h + self.cell - 1) // self.cell)
        if c0 < 0 or r0 < 0 or c1 > self.cols or r1 > self.rows:
            return False
        return self.occupied_cells(c0, r0, c1, r1) == 0

    def mark(self, box: Box) -> None:
        c0 = max(0, int(box.x // self.cell))
        r0 = max(0, int(box.y // self.cell))
        c1 = min(self.cols, int((box.x + box.w + self.cell - 1) // self.cell))
        r1 = min(self.rows, int((box.y + box.h + self.cell - 1) // self.cell))
        for r in range(r0, r1):
            for c in range(c0, c1):
                self._occupied[r * self.cols + c] = True
        self._rebuild()

    @property
    def free_fraction(self) -> float:
        n = self.cols * self.rows
        if not n:
            return 0.0
        return 1.0 - (sum(1 for v in self._occupied if v) / n)


def predict_cg_raster(
    preview: Image.Image,
    *,
    wall_w: float,
    wall_h: float,
    scale: float,
    tx: float,
    ty: float,
    dest_w: float,
    dest_h: float,
    bg: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, tuple[int, int, int]]:
    """Wall through the affine onto the CG frame. Cropping a scaled map runs off-canvas and pads black."""
    if bg is None:
        # Sample only the on-canvas part of the wall that lands in the frame (side panels would skew).
        x0 = max(0.0, (0.0 - tx) / scale) if scale else 0.0
        y0 = max(0.0, (0.0 - ty) / scale) if scale else 0.0
        x1 = min(wall_w, (dest_w - tx) / scale) if scale else wall_w
        y1 = min(wall_h, (dest_h - ty) / scale) if scale else wall_h
        px = preview.width / wall_w if wall_w else 1.0
        py = preview.height / wall_h if wall_h else 1.0
        box = (int(x0 * px), int(y0 * py), max(int(x1 * px), int(x0 * px) + 1), max(int(y1 * py), int(y0 * py) + 1))
        bg = background_colour(preview.crop(box))

    canvas = Image.new("RGB", (max(1, int(dest_w)), max(1, int(dest_h))), bg)
    scaled_w = max(1, int(round(wall_w * scale)))
    scaled_h = max(1, int(round(wall_h * scale)))
    scaled = preview.convert("RGB").resize((scaled_w, scaled_h), Image.Resampling.BILINEAR)
    canvas.paste(scaled, (int(round(tx)), int(round(ty))))
    return canvas, bg


def occupancy_from_image(
    im: Image.Image,
    *,
    slide_w: float,
    slide_h: float,
    cell: int = DEFAULT_CELL,
    bg: tuple[int, int, int] | None = None,
    tolerance: float = DEFAULT_TOLERANCE,
    ink_fraction: float = DEFAULT_INK_FRACTION,
) -> FreeSpace:
    rgb = im.convert("RGB")
    cols = max(1, int(slide_w // cell))
    rows = max(1, int(slide_h // cell))
    if bg is None:
        bg = background_colour(rgb)
    # One pixel per cell aliases thin coastlines away; sample a 2×2 block.
    probe = rgb.resize((cols * 2, rows * 2), Image.Resampling.BILINEAR)
    pixels = probe.load()
    br, bgr, bb = bg
    limit = tolerance * tolerance
    occupied = [False] * (cols * rows)
    for r in range(rows):
        for c in range(cols):
            ink = 0
            for dy in range(2):
                for dx in range(2):
                    pr, pg, pb = pixels[c * 2 + dx, r * 2 + dy]
                    dr, dg, db = pr - br, pg - bgr, pb - bb
                    if dr * dr + dg * dg + db * db > limit:
                        ink += 1
            if ink / 4.0 > ink_fraction:
                occupied[r * cols + c] = True
    return FreeSpace(cols, rows, occupied, cell)


def background_fraction(
    im: Image.Image,
    box: Box,
    *,
    bg: tuple[int, int, int],
    tolerance: float = DEFAULT_TOLERANCE,
    samples: int = 24,
) -> float:
    """Fraction of ``box`` that is bare background. Oversized PDF map art covers the frame in rects, not pixels."""
    w, h = im.size
    if box.w <= 0 or box.h <= 0 or w <= 0 or h <= 0:
        return 0.0
    br, bgr, bb = bg
    limit = tolerance * tolerance
    hits = 0
    total = 0
    pixels = im.convert("RGB").load()
    for sy in range(samples):
        y = int(box.y + (sy + 0.5) * box.h / samples)
        if y < 0 or y >= h:
            continue
        for sx in range(samples):
            x = int(box.x + (sx + 0.5) * box.w / samples)
            if x < 0 or x >= w:
                continue
            pr, pg, pb = pixels[x, y]
            dr, dg, db = pr - br, pg - bgr, pb - bb
            total += 1
            if dr * dr + dg * dg + db * db <= limit:
                hits += 1
    if not total:
        return 0.0
    return hits / total


def place_boxes(
    space: FreeSpace,
    boxes: list[Box],
    *,
    gap: float = 10.0,
    margin: float = 16.0,
) -> list[Placement]:
    """Place each box in order (reading order). Always place: overlap is better than dropping a name."""
    out: list[Placement] = []
    slide_w = space.cols * space.cell
    slide_h = space.rows * space.cell
    last: Box | None = None
    for box in boxes:
        if box.w <= 0 or box.h <= 0:
            out.append(Placement(box, 0.0))
            continue
        chosen: Box | None = None
        if last is not None:
            below = last.moved_to(last.x, last.y + last.h + gap)
            if _within(below, slide_w, slide_h, margin) and space.is_free(below):
                chosen = below
        if chosen is None:
            chosen = _best_position(
                space, box, slide_w, slide_h, margin, prefer_y=last.y if last else None
            )
        overlap = _overlap_fraction(space, chosen)
        space.mark(Box(chosen.x - gap, chosen.y - gap, chosen.w + 2 * gap, chosen.h + 2 * gap))
        out.append(Placement(chosen, overlap))
        last = chosen
    return out


def _overlap_fraction(space: FreeSpace, box: Box) -> float:
    c0 = int(box.x // space.cell)
    r0 = int(box.y // space.cell)
    c1 = int((box.x + box.w + space.cell - 1) // space.cell)
    r1 = int((box.y + box.h + space.cell - 1) // space.cell)
    cells = max(1, (c1 - c0) * (r1 - r0))
    return space.occupied_cells(c0, r0, c1, r1) / cells


def _within(box: Box, slide_w: float, slide_h: float, margin: float) -> bool:
    return (
        box.x >= margin
        and box.y >= margin
        and box.x + box.w <= slide_w - margin
        and box.y + box.h <= slide_h - margin
    )


def _best_position(
    space: FreeSpace,
    box: Box,
    slide_w: float,
    slide_h: float,
    margin: float,
    *,
    prefer_y: float | None = None,
) -> Box:
    """New column: right-first, then high. ``prefer_y`` stops columns from stepping down a coastline."""
    step = space.cell
    best: Box | None = None
    best_cost: tuple[int, float] | None = None
    x = slide_w - margin - box.w
    while x >= margin:
        ys: list[float] = []
        if prefer_y is not None:
            ys.append(prefer_y)
        y = margin
        while y + box.h <= slide_h - margin:
            ys.append(y)
            y += step
        for candidate_y in ys:
            candidate = box.moved_to(x, candidate_y)
            if not _within(candidate, slide_w, slide_h, margin):
                continue
            taken = space.occupied_cells(
                int(candidate.x // step),
                int(candidate.y // step),
                int((candidate.x + candidate.w + step - 1) // step),
                int((candidate.y + candidate.h + step - 1) // step),
            )
            if taken == 0:
                return candidate
            cost = (taken, candidate_y)
            if best_cost is None or cost < best_cost:
                best, best_cost = candidate, cost
        x -= step
    if best is not None:
        return best
    return box.moved_to(margin, margin)
