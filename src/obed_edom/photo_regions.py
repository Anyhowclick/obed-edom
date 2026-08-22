"""Compare pasted graphics as regions, not as whole slides.

Keynote reports a group of screenshots as one empty box, and the wall
duplicates that box on the right. Hashing the whole center wall against the
whole DSK frame only ever measures layout. This module clusters the actual
content, drops the mirror, and then looks inside the crop for a blur patch or
a highlight box that an 8×8 average hash will not see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from obed_edom.images import open_rgb
from obed_edom.rendered import center_wall_box

GAP_FRAC = 0.02
ASPECT_TOLERANCE = 0.10
GRID = 12
NORM_WIDTH = 384
OFFSETS = (-8, -4, 0, 4, 8)
SCALES = (0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15)
RGB_BLOCK = 18
EDGE_BLOCK = 12
VIVID_BLOCK = 0.08
VIVID_BLOCK_STRONG = 0.20
MIN_REGION = 8
SCALE_FRAMING = 0.03


@dataclass(frozen=True)
class Region:
    x: float
    y: float
    w: float
    h: float

    @property
    def aspect(self) -> float:
        return self.w / max(self.h, 1.0)


@dataclass
class RegionDelta:
    rgb_mean: float
    edge_mean: float
    scale: float
    differing: list[tuple[int, int]] = field(default_factory=list)
    marker_blocks: list[tuple[int, int]] = field(default_factory=list)
    location: str = ""
    flipped: bool = False
    framing: bool = False


@dataclass(frozen=True)
class RegionFinding:
    rule: str
    message: str
    default: str = "warning"
    evidence: str = ""


def _iter_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        yield item
        yield from _iter_items(item)


def _box_of(item: dict) -> tuple[float, float, float, float] | None:
    x = float(item.get("x") or 0)
    y = float(item.get("y") or 0)
    w = float(item.get("w") or 0)
    h = float(item.get("h") or 0)
    if w < MIN_REGION or h < MIN_REGION:
        return None
    return (x, y, w, h)


def _eligible(item: dict, slide_size: tuple[float, float]) -> bool:
    from obed_edom.diff_keynotes import _is_chrome  # noqa: PLC0415

    kind = item.get("kind") or ""
    if kind == "image":
        return not _is_chrome(item, slide_size)
    if kind == "group":
        return not _is_chrome(item, slide_size)
    if kind == "shape":
        if str(item.get("text") or "").strip():
            return False
        return not _is_chrome(item, slide_size)
    return False


def _intersect_wall(
    box: tuple[float, float, float, float], wall: tuple[float, float, float, float]
) -> tuple[float, float, float, float] | None:
    x, y, w, h = box
    x0, y0, x1, y1 = wall
    nx0 = max(x, x0)
    ny0 = max(y, y0)
    nx1 = min(x + w, x1)
    ny1 = min(y + h, y1)
    if nx1 - nx0 < MIN_REGION or ny1 - ny0 < MIN_REGION:
        return None
    return (nx0, ny0, nx1 - nx0, ny1 - ny0)


def _gap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    hgap = max(0.0, max(a[0] - bx2, b[0] - ax2))
    vgap = max(0.0, max(a[1] - by2, b[1] - ay2))
    if hgap == 0 and vgap == 0:
        return 0.0
    if hgap == 0:
        return vgap
    if vgap == 0:
        return hgap
    return (hgap * hgap + vgap * vgap) ** 0.5


def _cluster(boxes: list[tuple[float, float, float, float]], gap: float) -> list[Region]:
    n = len(boxes)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _gap(boxes[i], boxes[j]) <= gap:
                parent[find(i)] = find(j)
    groups: dict[int, list[tuple[float, float, float, float]]] = {}
    for i, box in enumerate(boxes):
        groups.setdefault(find(i), []).append(box)
    out: list[Region] = []
    for cluster in groups.values():
        x0 = min(b[0] for b in cluster)
        y0 = min(b[1] for b in cluster)
        x1 = max(b[0] + b[2] for b in cluster)
        y1 = max(b[1] + b[3] for b in cluster)
        out.append(Region(x0, y0, x1 - x0, y1 - y0))
    out.sort(key=lambda r: (r.x, r.y))
    return out


def content_regions(slide: dict, slide_size: tuple[float, float]) -> list[Region]:
    """Content boxes clustered together, clipped to the center wall."""
    slide_w, slide_h = slide_size
    wall = center_wall_box(slide_w, slide_h)
    boxes: list[tuple[float, float, float, float]] = []
    for item in _iter_items(slide):
        if not _eligible(item, slide_size):
            continue
        box = _box_of(item)
        if box is None:
            continue
        clipped = _intersect_wall(box, wall) if wall[2] > wall[0] else box
        if clipped:
            boxes.append(clipped)
    gap = GAP_FRAC * max(slide_w, slide_h, 1.0)
    return _cluster(boxes, gap)


def crop_region(
    im: Image.Image, region: Region, slide_size: tuple[float, float]
) -> Image.Image | None:
    slide_w, slide_h = slide_size
    if slide_w <= 0 or slide_h <= 0:
        return None
    sx = im.width / slide_w
    sy = im.height / slide_h
    box = (
        max(0, int(region.x * sx)),
        max(0, int(region.y * sy)),
        min(im.width, int((region.x + region.w) * sx)),
        min(im.height, int((region.y + region.h) * sy)),
    )
    if box[2] - box[0] < MIN_REGION or box[3] - box[1] < MIN_REGION:
        return None
    return im.crop(box)


def _prepared_crops(
    slide: dict, png: Path | Image.Image, slide_size: tuple[float, float]
) -> list[tuple[Region, Image.Image, list[int]]]:
    from obed_edom.diff_keynotes import IMAGE_HAMMING, _average_hash, _hash_distances  # noqa: PLC0415

    regions = content_regions(slide, slide_size)
    if not regions:
        return []
    im = png if isinstance(png, Image.Image) else open_rgb(png)
    crops: list[tuple[Region, Image.Image, list[int]]] = []
    for region in regions:
        crop = crop_region(im, region, slide_size)
        if crop is None:
            continue
        crops.append((region, crop, _average_hash(crop)))
    kept: list[tuple[Region, Image.Image, list[int]]] = []
    for candidate in crops:
        duplicate = False
        for _, _, bits in kept:
            direct, flipped = _hash_distances(candidate[2], bits)
            if min(direct, flipped) <= IMAGE_HAMMING:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def largest_region_crop(
    slide: dict, png: Path | Image.Image, slide_size: tuple[float, float]
) -> Image.Image | None:
    crops = _prepared_crops(slide, png, slide_size)
    if not crops:
        return None
    _, crop, _ = max(crops, key=lambda item: item[1].width * item[1].height)
    return crop


def match_regions(
    left: list[tuple[Region, Image.Image, list[int]]],
    right: list[tuple[Region, Image.Image, list[int]]],
) -> list[tuple[tuple[Region, Image.Image, list[int]], tuple[Region, Image.Image, list[int]]]]:
    """Pair regions of similar aspect. Hash is used later, not as a gate."""
    used: set[int] = set()
    pairs = []
    for left_item in left:
        la = left_item[0].aspect
        best: tuple[float, int] | None = None
        for j, right_item in enumerate(right):
            if j in used:
                continue
            ra = right_item[0].aspect
            denom = max(la, ra, 0.01)
            if abs(la - ra) / denom > ASPECT_TOLERANCE:
                continue
            delta = abs(la - ra)
            if best is None or delta < best[0]:
                best = (delta, j)
        if best is None:
            continue
        used.add(best[1])
        pairs.append((left_item, right[best[1]]))
    return pairs


def _common_size(a: Image.Image, b: Image.Image) -> tuple[int, int]:
    aspect = ((a.width / max(a.height, 1)) + (b.width / max(b.height, 1))) / 2
    width = NORM_WIDTH
    height = max(64, int(width / max(aspect, 0.2)))
    return (width, height)


def _place(im: Image.Image, scale: float, dx: int, dy: int, size: tuple[int, int]) -> Image.Image:
    width, height = size
    if abs(scale - 1.0) > 1e-6:
        scaled = im.resize(
            (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
            Image.Resampling.LANCZOS,
        )
    else:
        scaled = im
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    x = (width - scaled.width) // 2 + dx
    y = (height - scaled.height) // 2 + dy
    canvas.paste(scaled, (x, y))
    return canvas


def _block_means(gray: Image.Image, grid: int = GRID) -> list[list[float]]:
    width, height = gray.size
    pixels = gray.tobytes()
    rows: list[list[float]] = []
    for by in range(grid):
        row: list[float] = []
        y0 = by * height // grid
        y1 = (by + 1) * height // grid
        for bx in range(grid):
            x0 = bx * width // grid
            x1 = (bx + 1) * width // grid
            total = 0
            count = 0
            for y in range(y0, y1):
                start = y * width + x0
                chunk = pixels[start : start + (x1 - x0)]
                total += sum(chunk)
                count += x1 - x0
            row.append(total / max(count, 1))
        rows.append(row)
    return rows


def _vivid_fracs(im: Image.Image, grid: int = GRID) -> list[list[float]]:
    width, height = im.size
    data = im.tobytes()
    rows: list[list[float]] = []
    for by in range(grid):
        row: list[float] = []
        y0 = by * height // grid
        y1 = (by + 1) * height // grid
        for bx in range(grid):
            x0 = bx * width // grid
            x1 = (bx + 1) * width // grid
            vivid = 0
            count = 0
            for y in range(y0, y1):
                start = (y * width + x0) * 3
                end = (y * width + x1) * 3
                for i in range(start, end, 3):
                    r, g, b = data[i], data[i + 1], data[i + 2]
                    mx = r if r >= g and r >= b else g if g >= b else b
                    mn = r if r <= g and r <= b else g if g <= b else b
                    count += 1
                    if mx >= 80 and mx - mn >= 60 and mn <= 200:
                        vivid += 1
            row.append(vivid / max(count, 1))
        rows.append(row)
    return rows


def _location(blocks: list[tuple[int, int]], grid: int = GRID) -> str:
    if not blocks:
        return ""
    cx = sum(b[0] for b in blocks) / len(blocks)
    cy = sum(b[1] for b in blocks) / len(blocks)
    third = grid / 3
    horiz = "left" if cx < third else "right" if cx > 2 * third else ""
    vert = "top" if cy < third else "bottom" if cy > 2 * third else ""
    if vert and horiz:
        return f"{vert} {horiz}"
    return vert or horiz or "centre"


def _interior(bx: int, by: int, grid: int = GRID) -> bool:
    return 0 < bx < grid - 1 and 0 < by < grid - 1


def region_delta(left: Image.Image, right: Image.Image) -> RegionDelta:
    """Scale-normalised block diff, with a small offset/scale search."""
    from obed_edom.diff_keynotes import IMAGE_HAMMING, _average_hash, _hash_distances  # noqa: PLC0415

    size = _common_size(left, right)
    a = left.resize(size, Image.Resampling.LANCZOS)
    b = right.resize(size, Image.Resampling.LANCZOS)
    direct, flipped_dist = _hash_distances(_average_hash(a), _average_hash(b))
    if flipped_dist + 4 < direct and flipped_dist <= IMAGE_HAMMING:
        return RegionDelta(
            rgb_mean=0.0,
            edge_mean=0.0,
            scale=1.0,
            flipped=True,
            location="",
        )

    a_gray = ImageOps.grayscale(a)
    a_edge = a_gray.filter(ImageFilter.FIND_EDGES)
    a_rgb = _block_means(a_gray)
    a_ed = _block_means(a_edge)
    a_vivid = _vivid_fracs(a)

    best: tuple[float, float, Image.Image] | None = None
    for scale in SCALES:
        for dx in OFFSETS:
            for dy in OFFSETS:
                placed = _place(b, scale, dx, dy, size)
                gray = ImageOps.grayscale(placed)
                rgb_blocks = _block_means(gray)
                mean = 0.0
                n = 0
                for by in range(GRID):
                    for bx in range(GRID):
                        mean += abs(a_rgb[by][bx] - rgb_blocks[by][bx])
                        n += 1
                mean /= max(n, 1)
                if best is None or mean < best[0]:
                    best = (mean, scale, placed)

    assert best is not None
    rgb_mean, scale, placed = best
    p_gray = ImageOps.grayscale(placed)
    p_edge = p_gray.filter(ImageFilter.FIND_EDGES)
    p_rgb = _block_means(p_gray)
    p_ed = _block_means(p_edge)
    p_vivid = _vivid_fracs(placed)

    differing: list[tuple[int, int]] = []
    marker_blocks: list[tuple[int, int]] = []
    edge_total = 0.0
    for by in range(GRID):
        for bx in range(GRID):
            rgb = abs(a_rgb[by][bx] - p_rgb[by][bx])
            edge = abs(a_ed[by][bx] - p_ed[by][bx])
            vivid = abs(a_vivid[by][bx] - p_vivid[by][bx])
            edge_total += edge
            if rgb >= RGB_BLOCK or edge >= EDGE_BLOCK:
                differing.append((bx, by))
            if vivid >= VIVID_BLOCK:
                marker_blocks.append((bx, by))
            elif vivid >= VIVID_BLOCK_STRONG:
                marker_blocks.append((bx, by))

    interior_diff = [b for b in differing if _interior(*b)]
    interior_mark = [b for b in marker_blocks if _interior(*b)]
    strong_mark = [
        (bx, by)
        for bx, by in interior_mark
        if abs(a_vivid[by][bx] - p_vivid[by][bx]) >= VIVID_BLOCK_STRONG
    ]
    if not (len(interior_mark) >= 2 or strong_mark):
        interior_mark = []
        marker_blocks = []

    framing = abs(scale - 1.0) >= SCALE_FRAMING and not interior_diff
    return RegionDelta(
        rgb_mean=rgb_mean,
        edge_mean=edge_total / (GRID * GRID),
        scale=scale,
        differing=interior_diff or differing,
        marker_blocks=interior_mark or marker_blocks,
        location=_location(interior_diff or differing or interior_mark),
        framing=framing,
    )


def region_evidence(
    left: Image.Image,
    right: Image.Image,
    delta: RegionDelta,
    out_png: Path,
) -> str:
    """Side-by-side crops with the differing blocks outlined."""
    size = _common_size(left, right)
    a = left.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    b = right.resize(size, Image.Resampling.LANCZOS).convert("RGB")
    gap = 8
    canvas = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), (20, 20, 20))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + gap, 0))
    draw = ImageDraw.Draw(canvas)
    bw, bh = size[0] / GRID, size[1] / GRID
    boxes = {(bx, by): "region" for bx, by in delta.differing}
    for bx, by in delta.marker_blocks:
        boxes[(bx, by)] = "marker"
    for (bx, by), kind in boxes.items():
        colour = (255, 210, 40) if kind == "marker" else (255, 70, 70)
        for origin in (0, a.width + gap):
            x0 = origin + int(bx * bw)
            y0 = int(by * bh)
            x1 = origin + int((bx + 1) * bw) - 1
            y1 = int((by + 1) * bh) - 1
            draw.rectangle([x0, y0, x1, y1], outline=colour, width=2)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png)
    return out_png.name


def _findings_for_delta(delta: RegionDelta, where: str) -> list[RegionFinding]:
    loc = f" at the {delta.location}" if delta.location else ""
    findings: list[RegionFinding] = []
    if delta.flipped:
        findings.append(RegionFinding("photo.flipped", "Photo is flipped."))
        return findings
    if delta.marker_blocks:
        findings.append(
            RegionFinding(
                "photo.marker",
                f"Highlight box or circle differs{loc}.",
            )
        )
    content_blocks = [b for b in delta.differing if b not in set(delta.marker_blocks)]
    if content_blocks and not delta.framing:
        findings.append(
            RegionFinding(
                "photo.region",
                f"Picture content differs{loc}.",
            )
        )
    if delta.framing:
        findings.append(
            RegionFinding(
                "photo.framing",
                "Same picture, framed or cropped differently.",
                default="info",
            )
        )
    _ = where
    return findings


def compare_slide_regions(
    left_slide: dict,
    right_slides: list[dict],
    left_png: Path,
    right_pngs: list[Path | None],
    left_size: tuple[float, float],
    right_size: tuple[float, float],
    evidence_dir: Path,
    pair_index: int,
) -> list[RegionFinding]:
    """Compare matched content regions. Silent when nothing of similar aspect exists."""
    try:
        left_im = open_rgb(left_png)
    except OSError:
        return []
    left_crops = _prepared_crops(left_slide, left_im, left_size)
    right_crops: list[tuple[Region, Image.Image, list[int]]] = []
    for slide, png in zip(right_slides, right_pngs):
        if png is None:
            continue
        try:
            im = open_rgb(png)
        except OSError:
            continue
        right_crops.extend(_prepared_crops(slide, im, right_size))
    if not left_crops or not right_crops:
        return []
    pairs = match_regions(left_crops, right_crops)
    if not pairs:
        return []
    out: list[RegionFinding] = []
    for k, (left_item, right_item) in enumerate(pairs):
        delta = region_delta(left_item[1], right_item[1])
        hits = _findings_for_delta(delta, "")
        if not hits:
            continue
        name = f"region-{pair_index + 1:03d}"
        if len(pairs) > 1:
            name += f"-{k + 1}"
        evidence = region_evidence(
            left_item[1], right_item[1], delta, evidence_dir / f"{name}.png"
        )
        for finding in hits:
            out.append(
                RegionFinding(finding.rule, finding.message, finding.default, evidence)
            )
    return out
