"""Find the empty part of a slide and drop loose text boxes into it.

The CG resizer's problem with church-name lists is not scale, it is real estate.
On the wall those lists live on side panels outside the centre 1920x1080, so the
crop to 16:9 leaves them nowhere to go, and `pack_columns_from_right` stacks
them inward across the map until they cover the landmass.

Rect-level occupancy cannot help: the map *image* covers the whole CG frame
while most of it is ocean, so every candidate position looks taken. So the
emptiness test is done on pixels — background-coloured pixels are free, inked
ones are not — against a raster of the slide with the lists left out.

Only PIL is used, matching the rest of `src/`. The grid is a few tens of
thousands of cells, so an integral image in plain Python answers a fit test in
constant time without pulling in numpy.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

# 8px cells at 1920x1080 give a 240x135 grid: fine enough to thread a text
# column between coastlines, coarse enough to stay cheap.
DEFAULT_CELL = 8
# Distance in RGB (0-255) at which a pixel stops counting as background. Slide
# backgrounds here are flat brand navy, so this only has to survive PNG noise
# and the faint vignette Keynote renders at the edges.
DEFAULT_TOLERANCE = 38.0
# A cell is occupied when this fraction of its pixels are non-background. Kept
# low so antialiased coastlines and pin edges still read as content.
DEFAULT_INK_FRACTION = 0.12


@dataclass(frozen=True)
class Box:
    """A rectangle in slide coordinates."""

    x: float
    y: float
    w: float
    h: float

    def moved_to(self, x: float, y: float) -> Box:
        return Box(x, y, self.w, self.h)


@dataclass(frozen=True)
class Placement:
    """Where a box ended up, and how much artwork it had to sit on to get there.

    `overlap` is the fraction of the box's cells that were already taken. Zero
    means it found clean background. Anything above zero is a slide the operator
    should look at: the content is all present and readable-ish, but the list
    wants breaking up by hand.
    """

    box: Box
    overlap: float

    @property
    def clean(self) -> bool:
        return self.overlap <= 0.0


def background_colour(im: Image.Image, *, sample: int = 160) -> tuple[int, int, int]:
    """The slide's dominant flat colour.

    Quantising first stops JPEG-ish noise splitting one navy into hundreds of
    near-identical colours, which would let a gradient in the artwork outvote
    the real background.
    """
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
    """Which cells of a slide are empty, with O(1) "does a box fit here" tests."""

    def __init__(self, cols: int, rows: int, occupied: list[bool], cell: int) -> None:
        self.cols = cols
        self.rows = rows
        self.cell = cell
        self._occupied = occupied
        self._rebuild()

    def _rebuild(self) -> None:
        # Integral image over the occupancy grid, with one row/column of zero
        # padding so a region sum never needs a bounds check.
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
        """Count occupied cells in the half-open cell range [c0,c1) x [r0,r1)."""
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
        """Claim a box's cells so later boxes cannot land on top of it."""
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
    """Render what the CG will look like, by putting the wall through the affine.

    Cropping the wall preview to the CG frame only works when the map is not
    being scaled. Once the template shrinks the map, the CG frame maps back to a
    region taller than the 1080px wall, the crop runs off the canvas, and the
    padding PIL adds is black — which then wins the background vote and makes the
    real background read as content. Scaling and offsetting the whole wall
    instead is correct for any scale, and the uncovered part of the frame is
    genuinely empty, so filling it with the background colour is accurate.

    Returns the predicted frame and the background colour used, since callers
    need the same colour to erase relocatable text.
    """
    if bg is None:
        # Sample only the part of the wall that lands inside the frame, and only
        # where that is actually on-canvas. The side panels are busy with the
        # lists being moved and would skew the estimate.
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
    """Grid a rendered slide into background (free) and inked (occupied) cells.

    `im` may be any resolution; it is mapped onto the slide's coordinate space so
    placements come back in slide units.
    """
    rgb = im.convert("RGB")
    cols = max(1, int(slide_w // cell))
    rows = max(1, int(slide_h // cell))
    if bg is None:
        bg = background_colour(rgb)
    # One pixel per cell would alias thin coastlines away, so sample a small
    # block per cell and let ink_fraction decide.
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
    """How much of what is under `box` is bare background.

    Rectangles lie about this. Map art arrives as oversized mostly-transparent
    PDFs — on one deck two layers of 3686x2752 covered the whole centre wall —
    so every text box overlaps one and nothing looks free to move. Pixels tell
    the truth about what is actually visible underneath.

    The box's own text is inside the sample, so this never reaches 1.0. That is
    fine: glyphs cover a small fraction of a text box, while landmass covers
    nearly all of it, so the two cases are far apart.
    """
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
    """Drop each box into empty space, in order, preferring tidy columns.

    Boxes are placed in the order given, because these are alphabetical name
    columns and reordering them would scramble the reading order.

    Every box gets placed. When the artwork leaves no clean gap — a full-frame
    map with 12 columns of names to house is the normal case, not the exception —
    the box goes where it covers the least, and the returned `overlap` says so.
    Dropping content instead would leave a church off the slide, which is worse
    than a crowded slide the operator breaks up by hand.
    """
    out: list[Placement] = []
    slide_w = space.cols * space.cell
    slide_h = space.rows * space.cell
    last: Box | None = None
    for box in boxes:
        if box.w <= 0 or box.h <= 0:
            out.append(Placement(box, 0.0))
            continue
        # Continuing the current column keeps a list reading as one list.
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
    """Start a new column as far right and as high as the artwork allows.

    Right-first matches the wall layout, where these lists sit in the right-hand
    panels, so the CG keeps the operator's sense of where a name should be.
    `prefer_y` lines a new column up with the previous one, because without it
    columns drift down following a sloping coastline and read as a staircase.

    A clean position always wins. Failing that this returns the position
    covering the least artwork, so the caller can place it and flag it.
    """
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
            # Prefer less coverage, then higher up, so crowded columns still
            # start at the top of the frame rather than scattering.
            cost = (taken, candidate_y)
            if best_cost is None or cost < best_cost:
                best, best_cost = candidate, cost
        x -= step
    if best is not None:
        return best
    # Narrower than the margins allow: clamp inside the frame and let the flag
    # tell the operator.
    return box.moved_to(margin, margin)
