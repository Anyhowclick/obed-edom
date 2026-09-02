from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from obed_edom.images import open_rgb
from obed_edom.inspect import (
    PREVIEW_VIDEO_SUFFIXES,
    _looks_highlight,
    highlighted_markup,
    preview_media,
    preview_pngs,
    slide_plain_text,
)
from obed_edom.models import Flag
from obed_edom.rendered import CENTER_WALL, center_wall_box, point_number_lines, render_slide
from obed_edom.text_diff import (
    BIBLE_BOOK_WORDS,
    canonical_token,
    classify_text_diff,
    collapse_repeat as _collapse_repeat,
    comparable_tokens,
    fingerprint,
    is_rotation as _is_rotation,
    text_score,
    texts_equivalent,
)
from obed_edom.validate import make_flag, validate_inspect

LW_WIDTH = 3000
ALIGN_THRESHOLD = 0.58
IMAGE_HAMMING = 12
GRAPHIC_TOKENS = 2
SHORT_TITLE_TOKENS = 8
_PNG_NUM = re.compile(r"(\d+)")
_SOFT_WS = re.compile(r"[\s\u2028\u2029\xa0]+")


def _deck_type(payload: dict, label: str = "") -> str | None:
    """Filename/label beat canvas width — GW/LW is often 1920×1080 like DSK."""
    path = str(payload.get("path") or "")
    stem = Path(path).stem.upper().replace("-", "_").replace(" ", "_")
    name = Path(path).name.upper()
    if "DSK" in stem or "DSK" in name:
        return "dsk"
    if any(tok in stem for tok in ("_LW", "_GW", "_LED", "_FW")) or any(
        tok in name for tok in ("(LW)", "(GW)", "(LED)", "(FW)")
    ):
        return "lw"
    lab = (label or "").strip().upper()
    if lab in {"LW", "GW", "LED", "FW"}:
        return "lw"
    if lab == "DSK":
        return "dsk"
    width = float(payload.get("slideWidth") or 0)
    if width >= LW_WIDTH:
        return "lw"
    if width > 0:
        return "dsk"
    return None


def _same_deck_type(left: dict, right: dict, left_label: str, right_label: str) -> bool:
    a = _deck_type(left, left_label)
    b = _deck_type(right, right_label)
    return bool(a and b and a == b)


def _has_text(slide: dict, *, include_grouped: bool = False) -> bool:
    return bool(slide_plain_text(slide, include_grouped=include_grouped).strip())


def _iter_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        yield item
        yield from _iter_items(item)


def _layout_only(slide: dict) -> bool:
    """Blank TITLE/FILLER chrome. Real photos or copy still count."""
    if _has_text(slide):
        return False
    return not any(
        (item.get("kind") or "") in {"image", "group"}
        and float(item.get("w") or 0) > 0
        and float(item.get("h") or 0) > 0
        for item in _iter_items(slide)
    )


def _token_count(slide: dict, *, include_grouped: bool = False) -> int:
    return len(comparable_tokens(slide_plain_text(slide, include_grouped=include_grouped)))


def _can_positional_pair(left_slide: dict, right_slide: dict) -> bool:
    return _token_count(left_slide) <= GRAPHIC_TOKENS and _token_count(right_slide) <= SHORT_TITLE_TOKENS


def _content_indices(slides: list[dict]) -> list[int]:
    return [i for i, slide in enumerate(slides) if not _skipped(slide) and not _layout_only(slide)]


def _slide_number(slide: dict | None, fallback_index: int) -> int:
    if not slide:
        return fallback_index + 1
    return int(slide.get("number") or slide.get("index", fallback_index) + 1)


def _cached_bits(
    cache: dict[int, list[int] | None],
    idx: int,
    slide: dict,
    png: Path | None,
    slide_size: tuple[float, float],
) -> list[int] | None:
    if idx not in cache:
        cache[idx] = _bits_from_png(slide, png, slide_size) if png else None
    return cache[idx]


def _pair_quality(
    left_slide: dict,
    right_slide: dict,
    li: int,
    ri: int,
    left_map: dict[int, Path],
    right_map: dict[int, Path],
    left_size: tuple[float, float],
    right_size: tuple[float, float],
    left_bits: dict[int, list[int] | None],
    right_bits: dict[int, list[int] | None],
    left_ocr: Callable[[int], str] | None = None,
    right_ocr: Callable[[int], str] | None = None,
) -> float:
    score = text_score(
        slide_plain_text(left_slide, include_grouped=True),
        slide_plain_text(right_slide, include_grouped=True),
    )
    if score >= ALIGN_THRESHOLD:
        return score
    if left_ocr and right_ocr and not (
        _has_text(left_slide, include_grouped=True) and _has_text(right_slide, include_grouped=True)
    ):
        score = max(score, text_score(left_ocr(li), right_ocr(ri)))
        if score >= ALIGN_THRESHOLD:
            return score
    if (
        _token_count(left_slide, include_grouped=True) > SHORT_TITLE_TOKENS
        and _token_count(right_slide, include_grouped=True) > SHORT_TITLE_TOKENS
    ):
        return score
    from obed_edom.photo_regions import content_regions  # noqa: PLC0415

    if not content_regions(left_slide, left_size) or not content_regions(right_slide, right_size):
        return score
    lb = _cached_bits(left_bits, li, left_slide, left_map.get(li), left_size)
    rb = _cached_bits(right_bits, ri, right_slide, right_map.get(ri), right_size)
    if lb is None or rb is None:
        return score
    direct, flipped = _hash_distances(lb, rb)
    best = min(direct, flipped)
    if best <= IMAGE_HAMMING:
        return max(score, 0.93)
    return score


def align_slides(
    left_slides: list[dict],
    right_slides: list[dict],
    *,
    threshold: float = ALIGN_THRESHOLD,
    left_pngs: list[Path] | None = None,
    right_pngs: list[Path] | None = None,
    left_size: tuple[float, float] = (0.0, 0.0),
    right_size: tuple[float, float] = (0.0, 0.0),
    use_ocr: bool = True,
) -> list[tuple[int | None, int | None, float]]:
    """Walk visible slides. Extra LW photos stay unmatched when a later LW fits."""
    n_left = len(left_slides)
    n_right = len(right_slides)
    left_map = map_preview_pngs(left_slides, left_pngs or [])
    right_map = map_preview_pngs(right_slides, right_pngs or [])
    vis_left = _content_indices(left_slides)
    vis_right = _content_indices(right_slides)
    used_left: set[int] = set()
    used_right: set[int] = set()
    left_hash: dict[int, list[int] | None] = {}
    right_hash: dict[int, list[int] | None] = {}

    def reader(
        slides: list[dict], pngs: dict[int, Path], size: tuple[float, float]
    ) -> Callable[[int], str]:
        cache: dict[int, str] = {}

        def read(idx: int) -> str:
            if idx not in cache:
                png = pngs.get(idx)
                cache[idx] = (
                    render_slide(slides[idx], png, size, use_ocr=True).ocr if png else ""
                )
            return cache[idx]

        return read

    left_read = reader(left_slides, left_map, left_size) if use_ocr else None
    right_read = reader(right_slides, right_map, right_size) if use_ocr else None

    def quality(li: int, ri: int) -> float:
        return _pair_quality(
            left_slides[li],
            right_slides[ri],
            li,
            ri,
            left_map,
            right_map,
            left_size,
            right_size,
            left_hash,
            right_hash,
            left_read,
            right_read,
        )

    i = 0
    ordered: list[tuple[int | None, int | None, float]] = []
    for ri in vis_right:
        best_k, best_sc = None, 0.0
        next_sc = 0.0
        for k in range(i, len(vis_left)):
            score = quality(vis_left[k], ri)
            if k == i:
                next_sc = score
            if score > best_sc:
                best_sc, best_k = score, k

        if i < len(vis_left) and next_sc >= threshold:
            li = vis_left[i]
            ordered.append((li, ri, next_sc))
            used_left.add(li)
            used_right.add(ri)
            i += 1
        elif best_k is not None and best_sc >= threshold and best_k > i:
            while i < best_k:
                li = vis_left[i]
                ordered.append((li, None, 0.0))
                used_left.add(li)
                i += 1
            li = vis_left[i]
            ordered.append((li, ri, best_sc))
            used_left.add(li)
            used_right.add(ri)
            i += 1
        elif i < len(vis_left) and not _has_text(left_slides[vis_left[i]]):
            li = vis_left[i]
            ordered.append((li, ri, max(next_sc, 0.5)))
            used_left.add(li)
            used_right.add(ri)
            i += 1
        else:
            ordered.append((None, ri, 0.0))
            used_right.add(ri)

    extra: list[tuple[int, int, float]] = []
    for ri in range(n_right):
        if ri in used_right or _skipped(right_slides[ri]) or not _has_text(right_slides[ri]):
            continue
        best_skip: tuple[float, int] | None = None
        for li in range(n_left):
            if li in used_left or not _skipped(left_slides[li]):
                continue
            score = text_score(slide_plain_text(left_slides[li]), slide_plain_text(right_slides[ri]))
            if score >= threshold and (best_skip is None or score > best_skip[0]):
                best_skip = (score, li)
        if best_skip:
            extra.append((best_skip[1], ri, best_skip[0]))
            used_left.add(best_skip[1])
            used_right.add(ri)

    for li in range(n_left):
        if li in used_left or _skipped(left_slides[li]) or not _has_text(left_slides[li]):
            continue
        best_skip: tuple[float, int] | None = None
        for ri in range(n_right):
            if ri in used_right or not _skipped(right_slides[ri]):
                continue
            score = text_score(slide_plain_text(left_slides[li]), slide_plain_text(right_slides[ri]))
            if score >= threshold and (best_skip is None or score > best_skip[0]):
                best_skip = (score, ri)
        if best_skip:
            extra.append((li, best_skip[1], best_skip[0]))
            used_left.add(li)
            used_right.add(best_skip[1])

    ordered.extend((li, ri, sc) for li, ri, sc in extra)
    for ri in range(n_right):
        if ri not in used_right and not _layout_only(right_slides[ri]) and not _skipped(right_slides[ri]):
            ordered.append((None, ri, 0.0))
    for li in vis_left:
        if li not in used_left:
            ordered.append((li, None, 0.0))
    return _combine_split_verses(ordered, left_slides, right_slides)


def _covers(whole: str, parts: str) -> bool:
    if texts_equivalent(whole, parts):
        return True
    have = {t.lower() for t in comparable_tokens(whole)}
    want = [t.lower() for t in comparable_tokens(parts)]
    if len(want) < 6:
        return False
    return sum(1 for t in want if t in have) / len(want) >= 0.9


def _combine_split_verses(
    ordered: list[tuple[int | None, int | None, float]],
    left_slides: list[dict],
    right_slides: list[dict],
) -> list[tuple[int | None, int | None | list[int], float]]:
    """Fold an unmatched DSK slide into the wall slide that already shows it."""
    out: list[tuple[int | None, int | None | list[int], float]] = []
    i = 0
    while i < len(ordered):
        li, ri, score = ordered[i]
        if li is None or ri is None:
            out.append((li, ri, score))
            i += 1
            continue
        merged = [ri]
        whole = slide_plain_text(left_slides[li])
        j = i + 1
        stranded: list[int] = []
        while j < len(ordered):
            next_li, next_ri, next_score = ordered[j]
            if next_ri is None:
                break
            if next_li is not None and next_score >= ALIGN_THRESHOLD:
                break
            if not comparable_tokens(slide_plain_text(right_slides[next_ri])):
                break
            candidate = merged + [next_ri]
            parts = "\n".join(slide_plain_text(right_slides[k]) for k in candidate)
            if not _covers(whole, parts):
                break
            merged = candidate
            if next_li is not None:
                stranded.append(next_li)
            j += 1
        if len(merged) > 1:
            out.append((li, merged, score))
            out.extend((left_index, None, 0.0) for left_index in stranded)
            i = j
            continue
        out.append((li, ri, score))
        i += 1
    return out


def realign_gaps(
    slots: list[dict],
    left_slides: list[dict],
    right_slides: list[dict],
    *,
    left_pngs: list[Path] | None = None,
    right_pngs: list[Path] | None = None,
    left_size: tuple[float, float] = (0.0, 0.0),
    right_size: tuple[float, float] = (0.0, 0.0),
    use_ocr: bool = True,
) -> list[dict]:
    from obed_edom.baseline import normalize_slot, slot_dict, unpaired_gaps  # noqa: PLC0415

    gaps = unpaired_gaps(slots)
    if not gaps:
        return [normalize_slot(slot) for slot in slots]
    out: list[dict] = []
    cursor = 0
    for start, end, lefts, rights in gaps:
        out.extend(normalize_slot(slot) for slot in slots[cursor:start])
        sub_left = [left_slides[i] for i in lefts]
        sub_right = [right_slides[j] for j in rights]
        aligned = align_slides(
            sub_left,
            sub_right,
            left_pngs=left_pngs,
            right_pngs=right_pngs,
            left_size=left_size,
            right_size=right_size,
            use_ocr=use_ocr,
        )
        for sub_li, sub_ri, score in aligned:
            li = lefts[sub_li] if sub_li is not None and 0 <= sub_li < len(lefts) else None
            ris = [rights[k] for k in _right_indexes(sub_ri) if 0 <= k < len(rights)]
            if li is None and not ris:
                continue
            out.append(slot_dict(li, ris, score))
        cursor = end
    out.extend(normalize_slot(slot) for slot in slots[cursor:])
    return out


def build_repeat_indices(
    left_slides: list[dict], matched: set[int], window: int = 6
) -> set[int]:
    """Wall slides that only repeat a nearby matched slide's copy (Magic Move titles)."""
    visible = [i for i, slide in enumerate(left_slides) if not _skipped(slide)]
    prints = {i: fingerprint(slide_plain_text(left_slides[i])) for i in visible}
    repeats: set[int] = set()
    for position, index in enumerate(visible):
        if index in matched or not prints[index]:
            continue
        lo = max(0, position - window)
        hi = min(len(visible), position + window + 1)
        neighbours = visible[lo:position] + visible[position + 1 : hi]
        if any(other in matched and prints[other] == prints[index] for other in neighbours):
            repeats.add(index)
    return repeats


_POINT_TITLE_TOKENS = 6
_TITLE_FILLER = {"and", "or", "the", "a", "an", "to", "of", "your"}


def point_title_keys(slides: list[dict]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for slide in slides:
        if _skipped(slide):
            continue
        tokens = comparable_tokens(slide_plain_text(slide))
        if tokens and re.fullmatch(r"\d{1,2}", tokens[0] or ""):
            tokens = tokens[1:]
        if not tokens or len(tokens) > _POINT_TITLE_TOKENS:
            continue
        if tokens[0].lower().strip("()") in BIBLE_BOOK_WORDS:
            continue
        key = " ".join(t.lower() for t in tokens)
        if key and key not in seen:
            seen.add(key)
            titles.append(key)
    return titles


def strip_carried_point_title(lw_text: str, dsk_text: str, titles: list[str]) -> tuple[str, str | None]:
    """Drop LW lines that are a carried PRE title, but only on verse slides."""
    if not titles:
        return lw_text, None
    title_set = set(titles)
    title_tokens = [set(title.split()) for title in titles]
    dsk_lines = {fingerprint(line) for line in dsk_text.split("\n") if line.strip()}

    def line_title(line: str) -> str | None:
        tokens = [t.lower() for t in comparable_tokens(line)]
        if tokens and re.fullmatch(r"\d{1,2}", tokens[0] or ""):
            tokens = tokens[1:]
        if not tokens:
            return None
        folded = " ".join(tokens)
        if folded in title_set:
            return folded
        words = set(tokens)
        for title, wanted in zip(titles, title_tokens):
            if words <= wanted and not words <= _TITLE_FILLER:
                return title
        return None

    lines = lw_text.split("\n")
    kept: list[str] = []
    stripped: list[tuple[str, str]] = []
    for line in lines:
        title = line_title(line)
        if title and fingerprint(line) not in dsk_lines:
            stripped.append((line.strip() or title, title))
            continue
        kept.append(line)
    if not stripped:
        return lw_text, None
    if len({title for _, title in stripped}) > 1:
        return lw_text, None
    rest_tokens = [t for t in comparable_tokens("\n".join(kept)) if not re.fullmatch(r"\d{1,2}", t)]
    if len(rest_tokens) < 6:
        return lw_text, None
    label = next((text for text, _ in stripped if text and not re.fullmatch(r"\d{1,2}", text)), stripped[0][0])
    return "\n".join(kept), label


def visual_diff(a_png: Path, b_png: Path, out_png: Path, threshold: int = 18) -> dict:
    a = open_rgb(a_png)
    b = open_rgb(b_png)
    size = (min(a.width, b.width), min(a.height, b.height))
    a = a.resize(size, Image.Resampling.LANCZOS)
    b = b.resize(size, Image.Resampling.LANCZOS)
    diff = ImageChops.difference(a, b)
    extrema = diff.getextrema()
    max_delta = max(ch[1] for ch in extrema)
    gray = ImageOps.grayscale(diff)
    changed = sum(1 for p in gray.tobytes() if p > threshold)
    total = size[0] * size[1]
    ratio = changed / max(1, total)
    heat = ImageOps.colorize(gray.point(lambda p: min(255, p * 4)), black="black", white="red")
    blend = Image.blend(a, heat.convert("RGB"), alpha=0.45)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    blend.save(out_png)
    return {
        "maxDelta": max_delta,
        "changedRatio": ratio,
        "visual": ratio > 0.004 or max_delta > 40,
        "heatmap": str(out_png),
    }


def map_preview_pngs(slides: list[dict], pngs: list[Path]) -> dict[int, Path]:
    """0-based index → PNG. Sequential files are visible-order, not Keynote numbers."""
    if not pngs:
        return {}
    pngs = list(pngs)
    by_num: dict[int, Path] = {}
    for path in pngs:
        found = _PNG_NUM.findall(path.stem)
        if found:
            by_num[int(found[-1])] = path
    visible = [i for i, slide in enumerate(slides) if not _skipped(slide)]
    sequential = sorted(by_num) == list(range(1, len(pngs) + 1))
    if sequential and len(pngs) == len(visible) and len(pngs) != len(slides):
        return {visible[k]: pngs[k] for k in range(len(pngs))}
    out: dict[int, Path] = {}
    for i, slide in enumerate(slides):
        number = _slide_number(slide, i)
        if number in by_num:
            out[i] = by_num[number]
        elif 0 <= i < len(pngs) and len(pngs) == len(slides):
            out[i] = pngs[i]
    return out


def _png_for_slide(
    pngs: list[Path],
    slide: dict | None,
    fallback_index: int,
    *,
    slides: list[dict] | None = None,
) -> Path | None:
    if not pngs:
        return None
    if slides:
        mapped = map_preview_pngs(slides, pngs)
        if fallback_index in mapped:
            return mapped[fallback_index]
    number = _slide_number(slide, fallback_index)
    by_num: dict[int, Path] = {}
    for path in pngs:
        found = _PNG_NUM.findall(path.stem)
        if found:
            by_num[int(found[-1])] = path
    if number in by_num:
        return by_num[number]
    idx = fallback_index
    if slide is not None and slide.get("index") is not None:
        idx = int(slide["index"])
    if 0 <= idx < len(pngs):
        return pngs[idx]
    return None


def _average_hash(im: Image.Image, size: int = 8) -> list[int]:
    gray = im.convert("L")
    gray.thumbnail((64, 64), Image.Resampling.BILINEAR)
    small = gray.resize((size, size), Image.Resampling.BILINEAR)
    pixels = list(small.tobytes())
    avg = sum(pixels) / max(1, len(pixels))
    return [1 if p > avg else 0 for p in pixels]


def _hflip_bits(bits: list[int], size: int = 8) -> list[int]:
    rows = [bits[i * size : (i + 1) * size] for i in range(size)]
    return [pixel for row in rows for pixel in reversed(row)]


def _hamming(a: list[int], b: list[int]) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def _hash_distances(left_bits: list[int], right_bits: list[int]) -> tuple[int, int]:
    direct = _hamming(left_bits, right_bits)
    flipped = _hamming(left_bits, _hflip_bits(right_bits))
    return direct, flipped


def crop_center_wall(im: Image.Image, slide_w: float, slide_h: float) -> Image.Image:
    x0, y0, x1, y1 = center_wall_box(slide_w, slide_h)
    if x1 <= x0 or y1 <= y0 or slide_w <= 0 or slide_h <= 0:
        return im
    if x0 <= 0 and x1 >= slide_w - 0.5:
        return im
    sx = im.width / slide_w
    sy = im.height / slide_h
    box = (
        max(0, int(x0 * sx)),
        max(0, int(y0 * sy)),
        min(im.width, int(x1 * sx)),
        min(im.height, int(y1 * sy)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return im
    return im.crop(box)


def _overlaps_center_wall(item: dict, slide_w: float, slide_h: float) -> bool:
    x0, _y0, x1, _y1 = center_wall_box(slide_w, slide_h)
    x = float(item.get("x") or 0)
    w = float(item.get("w") or 0)
    return x + max(w, 1) > x0 and x < x1


def _slide_probe(slide: dict, png: Path, slide_size: tuple[float, float]) -> Image.Image | None:
    try:
        im = open_rgb(png)
    except OSError:
        return None
    from obed_edom.photo_regions import largest_region_crop  # noqa: PLC0415

    region = largest_region_crop(slide, im, slide_size)
    if region is not None:
        return region
    items = [
        it
        for it in content_photos(slide, slide_size)
        if _overlaps_center_wall(it, slide_size[0], slide_size[1])
    ]
    crops = [c for c in (_crop_item(im, it, slide_size[0], slide_size[1]) for it in items) if c]
    if crops:
        return max(crops, key=lambda crop: crop.width * crop.height)
    return crop_center_wall(im, slide_size[0], slide_size[1])


def _bits_from_png(slide: dict, png: Path, slide_size: tuple[float, float]) -> list[int] | None:
    probe = _slide_probe(slide, png, slide_size)
    if probe is None:
        return None
    return _average_hash(probe)


def _image_items(slide: dict) -> list[dict]:
    return [
        item
        for item in _iter_items(slide)
        if (item.get("kind") or "") == "image" and item.get("w") and item.get("h")
    ]


_CHROME_NAMES = re.compile(r"(filler|blank|background|bg[_\- ]|lower[_\- ]?third|logo|frame)", re.I)
_LABEL_MAX_HEIGHT = 120


def _is_chrome(item: dict, slide_size: tuple[float, float]) -> bool:
    name = str(item.get("fileName") or "")
    if _CHROME_NAMES.search(name):
        return True
    width = float(item.get("w") or 0)
    height = float(item.get("h") or 0)
    slide_w, slide_h = slide_size
    if slide_h and height >= slide_h - 1:
        if width >= slide_w - 1 or not _overlaps_center_wall(item, slide_w, slide_h):
            return True
    return bool(height and height <= _LABEL_MAX_HEIGHT and width and width <= 600)


def content_photos(slide: dict, slide_size: tuple[float, float]) -> list[dict]:
    return [item for item in _image_items(slide) if not _is_chrome(item, slide_size)]


@dataclass(frozen=True)
class PhotoFinding:
    rule: str
    message: str
    default: str = "warning"


def _photo_name(item: dict) -> str:
    return Path(str(item.get("fileName") or "")).name


def _rotation(item: dict) -> float:
    try:
        return round(float(item.get("rotation") or 0.0) % 360, 1)
    except (TypeError, ValueError):
        return 0.0


def photo_findings_for_pair(
    left_slide: dict,
    right_slides: list[dict],
    left_label: str,
    right_label: str,
    left_size: tuple[float, float] = (0.0, 0.0),
    right_size: tuple[float, float] = (0.0, 0.0),
) -> list[PhotoFinding]:
    """Compare photos by Keynote metadata (file name, rotation), not pixels."""
    left_photos = content_photos(left_slide, left_size)
    right_photos: list[dict] = []
    for slide in right_slides:
        right_photos.extend(content_photos(slide, right_size))
    if not left_photos or not right_photos:
        return []

    findings: list[PhotoFinding] = []
    left_names = [n for n in (_photo_name(i) for i in left_photos) if n]
    right_names = [n for n in (_photo_name(i) for i in right_photos) if n]
    if left_names and right_names:
        missing = [n for n in right_names if n not in left_names]
        replaced = [n for n in left_names if n not in right_names]
        if missing and replaced:
            findings.append(
                PhotoFinding(
                    "photo.source",
                    f"Different image file: {left_label} uses "
                    f"{', '.join(sorted(set(replaced))[:3])}, {right_label} uses "
                    f"{', '.join(sorted(set(missing))[:3])}. Check the DSK is on the latest photo.",
                )
            )

    left_rot = sorted(_rotation(i) for i in left_photos)
    right_rot = sorted(_rotation(i) for i in right_photos)
    if left_rot != right_rot and (any(left_rot) or any(right_rot)):
        findings.append(
            PhotoFinding(
                "photo.rotated",
                f"Photo is rotated on one deck only: {left_label} at "
                f"{', '.join(f'{r:g}°' for r in left_rot)}, {right_label} at "
                f"{', '.join(f'{r:g}°' for r in right_rot)}.",
            )
        )
    if len(left_photos) != len(right_photos):
        findings.append(
            PhotoFinding(
                "photo.count",
                f"{left_label} has {len(left_photos)} photo(s), {right_label} has "
                f"{len(right_photos)}.",
                default="info",
            )
        )
    return findings


def _crop_item(png: Image.Image, item: dict, slide_w: float, slide_h: float) -> Image.Image | None:
    if slide_w <= 0 or slide_h <= 0:
        return None
    sx = png.width / slide_w
    sy = png.height / slide_h
    x = float(item.get("x") or 0) * sx
    y = float(item.get("y") or 0) * sy
    w = float(item.get("w") or 0) * sx
    h = float(item.get("h") or 0) * sy
    box = (
        max(0, int(x)),
        max(0, int(y)),
        min(png.width, int(x + max(w, 1))),
        min(png.height, int(y + max(h, 1))),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return png.crop(box)


def _photo_crops(slide: dict, png: Path, size: tuple[float, float]) -> tuple[Image.Image, list[Image.Image]]:
    im = open_rgb(png)
    items = [it for it in content_photos(slide, size) if _overlaps_center_wall(it, size[0], size[1])]
    crops = [c for c in (_crop_item(im, it, size[0], size[1]) for it in items) if c]
    return im, crops


def image_item_diff(
    left_slide: dict,
    right_slide: dict,
    left_png: Path,
    right_png: Path,
    left_size: tuple[float, float],
    right_size: tuple[float, float],
    out_png: Path,
    *,
    extra_rights: list[tuple[dict, Path, tuple[float, float]]] | None = None,
    hamming_limit: int = IMAGE_HAMMING,
    skip_full_frame: bool = False,
) -> dict:
    left_im, left_crops = _photo_crops(left_slide, left_png, left_size)
    right_im, right_crops = _photo_crops(right_slide, right_png, right_size)
    right_has_text = _has_text(right_slide)
    for extra_slide, extra_png, extra_size in extra_rights or []:
        _, extra_crops = _photo_crops(extra_slide, extra_png, extra_size)
        right_crops.extend(extra_crops)
        right_has_text = right_has_text or _has_text(extra_slide)
    if not left_crops or not right_crops:
        if skip_full_frame or _has_text(left_slide) or right_has_text:
            return {"visual": False, "maxDelta": 0, "changedRatio": 0.0, "kind": "images", "reason": ""}
        left_im = crop_center_wall(left_im, left_size[0], left_size[1])
        right_im = crop_center_wall(right_im, right_size[0], right_size[1])
        direct, flip_dist = _hash_distances(_average_hash(left_im), _average_hash(right_im))
        visual = direct > hamming_limit
        flipped = visual and flip_dist + 4 < direct and flip_dist <= hamming_limit
        if visual:
            out_png.parent.mkdir(parents=True, exist_ok=True)
            h = max(left_im.height, right_im.height, 1)
            scale_l = h / max(left_im.height, 1)
            scale_r = h / max(right_im.height, 1)
            show_l = left_im.resize((max(1, int(left_im.width * scale_l)), h), Image.Resampling.LANCZOS)
            show_r = right_im.resize((max(1, int(right_im.width * scale_r)), h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (show_l.width + show_r.width + 8, h), (20, 20, 20))
            canvas.paste(show_l, (0, 0))
            canvas.paste(show_r, (show_l.width + 8, 0))
            canvas.save(out_png)
        return {
            "maxDelta": direct,
            "changedRatio": direct / 64.0,
            "visual": visual,
            "heatmap": str(out_png) if visual else "",
            "kind": "images",
            "reason": "flipped" if flipped else ("differs" if visual else ""),
        }

    left_hashes = [_average_hash(c) for c in left_crops]
    right_hashes = [_average_hash(c) for c in right_crops]
    used_r: set[int] = set()
    worst = 0
    flipped = False
    mismatched: list[tuple[Image.Image, Image.Image]] = []
    for li, lh in enumerate(left_hashes):
        best: tuple[int, int, int] | None = None
        for ri, rh in enumerate(right_hashes):
            if ri in used_r:
                continue
            direct, flip_dist = _hash_distances(lh, rh)
            match = min(direct, flip_dist)
            if best is None or match < best[0]:
                best = (match, direct, ri)
        if best is None:
            continue
        _match, direct, ri = best
        used_r.add(ri)
        worst = max(worst, direct)
        if direct > hamming_limit:
            mismatched.append((left_crops[li], right_crops[ri]))
            _, flip_dist = _hash_distances(lh, right_hashes[ri])
            if flip_dist + 4 < direct and flip_dist <= hamming_limit:
                flipped = True

    count_mismatch = abs(len(left_crops) - len(right_crops))
    visual = bool(mismatched) or count_mismatch > 0 or worst > hamming_limit
    if visual:
        out_png.parent.mkdir(parents=True, exist_ok=True)
        show_l = mismatched[0][0] if mismatched else left_crops[0]
        show_r = mismatched[0][1] if mismatched else right_crops[0]
        h = max(show_l.height, show_r.height, 1)
        canvas = Image.new("RGB", (show_l.width + show_r.width + 8, h), (20, 20, 20))
        canvas.paste(show_l, (0, 0))
        canvas.paste(show_r, (show_l.width + 8, 0))
        canvas.save(out_png)
    reason = ""
    if visual:
        reason = "flipped" if flipped and not count_mismatch else "differs"
    return {
        "maxDelta": worst,
        "changedRatio": worst / 64.0,
        "visual": visual,
        "heatmap": str(out_png) if visual else "",
        "kind": "images",
        "reason": reason,
    }


def _smallcaps_words(slide: dict) -> set[str]:
    words: set[str] = set()
    for item in slide.get("items") or []:
        for run in item.get("runs") or []:
            text = run.get("text") or ""
            if not text.strip():
                continue
            cap = str(run.get("capitalization") or "")
            if bool(run.get("smallCaps")) or "small" in cap.lower():
                words.update(comparable_tokens(text))
    return words


def _style_diff_message(
    header: str, verb: str, left: set[str], right: set[str]
) -> str | None:
    left_keys = {canonical_token(w) for w in left}
    right_keys = {canonical_token(w) for w in right}
    left_only = sorted(w for w in left if canonical_token(w) not in right_keys)
    right_only = sorted(w for w in right if canonical_token(w) not in left_keys)
    if not left_only and not right_only:
        return None
    parts: list[str] = []
    if left_only:
        parts.append(f"LW {verb}: '{' '.join(left_only)}'")
    if right_only:
        parts.append(f"DSK {verb}: '{' '.join(right_only)}'")
    return f"{header} — {'; '.join(parts)}."


def _pair_location(
    left_label: str,
    left_num: int | None,
    right_label: str,
    right_num: int | None,
    right_nums: list[int] | None = None,
) -> str:
    nums = [n for n in (right_nums or []) if n]
    if len(nums) > 1:
        joined = "+".join(str(n) for n in nums)
        if left_num:
            return f"{left_label} slide {left_num} ↔ {right_label} slides {joined}"
        return f"{right_label} slides {joined}"
    if left_num and right_num:
        return f"{left_label} slide {left_num} ↔ {right_label} slide {right_num}"
    if left_num:
        return f"{left_label} slide {left_num}"
    if right_num:
        return f"{right_label} slide {right_num}"
    return ""


def _skipped(slide: dict | None) -> bool:
    return bool(slide and slide.get("skipped"))


def _highlighted_run_words(slide: dict) -> set[str]:
    """Drop coloured verse/point NUMBERS with superscript == \"kSuperscript\"."""
    words: set[str] = set()
    for item in slide.get("items") or []:
        for run in item.get("runs") or []:
            text = run.get("text") or ""
            if not text.strip():
                continue
            if not _looks_highlight(run.get("color")):
                continue
            if run.get("superscript") == "kSuperscript" and text.strip().isdigit():
                continue
            words.update(comparable_tokens(text))
    return words


def _canonical_words(text: str) -> set[str]:
    return {canonical_token(t) for t in comparable_tokens(text)}


def _shared_style_words(left_words: set[str], right_words: set[str], shared: set[str]) -> tuple[set[str], set[str]]:
    """Keep style-run words both slides show. Membership is canonical; spelling is kept."""
    keep = lambda words: {w for w in words if canonical_token(w) in shared}
    return keep(left_words), keep(right_words)


def _brief(text: str, limit: int = 140) -> str:
    return _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()[:limit]


TYPED_COVERAGE = 0.6
FILTER_TOLERANCE = 0.25


def _share(part: str, whole: str) -> float:
    seen = len(comparable_tokens(whole))
    if not seen:
        return 1.0
    return len(comparable_tokens(part)) / seen


def _covers_slide(part: str, whole: str) -> bool:
    return _share(part, whole) >= TYPED_COVERAGE


def _filter_symmetric(a_clean: str, a_text: str, b_clean: str, b_text: str) -> bool:
    return abs(_share(a_clean, a_text) - _share(b_clean, b_text)) <= FILTER_TOLERANCE


def wording_message(left: str, right: str, left_label: str, right_label: str) -> str | None:
    finding = classify_text_diff(left, right, left_label, right_label)
    return finding.message if finding else None


def _add_flag(bucket: list[Flag], flags: list[Flag], flag: Flag | None) -> None:
    if flag is None:
        return
    bucket.append(flag)
    flags.append(flag)


def slide_catalog(slides: list[dict], png_map: dict[int, Path]) -> list[dict]:
    out: list[dict] = []
    for i, slide in enumerate(slides):
        png = png_map.get(i)
        out.append(
            {
                "index": i,
                "number": _slide_number(slide, i),
                "skipped": _skipped(slide),
                "layoutOnly": _layout_only(slide),
                "png": png.name if png else None,
                "text": slide_plain_text(slide),
            }
        )
    return out


def _right_indexes(ri: object) -> list[int]:
    if ri is None:
        return []
    if isinstance(ri, (list, tuple)):
        return [int(x) for x in ri if x is not None]
    return [int(ri)]


def slots_from_pairs(pairs: list[dict]) -> list[tuple[int | None, list[int], float]]:
    out: list[tuple[int | None, list[int], float]] = []
    for pair in pairs:
        li = pair.get("leftIndex")
        ris = pair.get("rightIndexes")
        if ris is None:
            ris = _right_indexes(pair.get("rightIndex"))
        else:
            ris = _right_indexes(ris)
        score = float(pair.get("score") or 0.0)
        out.append((int(li) if li is not None else None, ris, score))
    return out


def _flag_on_pair(flag: Flag, pair: dict) -> bool:
    slide = flag.slide
    if slide is None:
        return False
    deck = (flag.deck or "").lower()
    rights = list(pair.get("rightNumbers") or [])
    if pair.get("rightNumber") is not None and pair["rightNumber"] not in rights:
        rights.append(pair["rightNumber"])
    if deck in {"lw", "left"}:
        return pair.get("leftNumber") == slide
    if deck in {"dsk", "right"}:
        return slide in rights
    return pair.get("leftNumber") == slide or slide in rights


def attach_slide_flags(pairs: list[dict], flags: list[Flag]) -> list[Flag]:
    leftover: list[Flag] = []
    for flag in flags:
        if flag.slide is None:
            leftover.append(flag)
            continue
        hit = False
        for pair in pairs:
            if not _flag_on_pair(flag, pair):
                continue
            bucket = pair.setdefault("flags", [])
            if flag not in bucket:
                bucket.append(flag)
            hit = True
        if not hit:
            leftover.append(flag)
    return leftover


def compare_inspects(
    left: dict,
    right: dict,
    left_previews: Path,
    right_previews: Path,
    heat_dir: Path,
    *,
    left_label: str = "LW",
    right_label: str = "Other",
    slots: list[tuple[int | None, int | None | list[int], float]] | None = None,
    check: bool = True,
    use_ocr: bool = True,
) -> dict:
    left_pngs = preview_media(left_previews) or preview_pngs(left_previews)
    right_pngs = preview_media(right_previews) or preview_pngs(right_previews)
    left_slides = left.get("slides") or []
    right_slides = right.get("slides") or []
    left_map = map_preview_pngs(left_slides, left_pngs)
    right_map = map_preview_pngs(right_slides, right_pngs)
    n_left = left.get("slideCount") or len(left_slides)
    n_right = right.get("slideCount") or len(right_slides)
    flags: list[Flag] = []
    same_type = _same_deck_type(left, right, left_label, right_label)
    if check and same_type and n_left != n_right:
        count_flag = make_flag(
            "diff.count",
            "diff",
            f"Slide count differs: {left_label} has {n_left}, {right_label} has {n_right}. Compared by index.",
            default="info",
        )
        if count_flag:
            flags.append(count_flag)

    left_size = (float(left.get("slideWidth") or 0), float(left.get("slideHeight") or 0))
    right_size = (float(right.get("slideWidth") or 0), float(right.get("slideHeight") or 0))

    def render_deck(
        slides: list[dict], pngs: dict[int, Path], size: tuple[float, float]
    ) -> dict[int, object]:
        out: dict[int, object] = {}
        for index, slide in enumerate(slides):
            if _skipped(slide):
                continue
            out[index] = render_slide(slide, pngs.get(index), size, use_ocr=use_ocr)
        return out

    if slots is None:
        t_align = time.perf_counter()
        if same_type:
            slots = []
            for i in range(max(n_left, n_right, len(left_slides), len(right_slides))):
                li = i if i < len(left_slides) else None
                ri = i if i < len(right_slides) else None
                slots.append((li, ri, 1.0 if li is not None and ri is not None else 0.0))
        else:
            slots = align_slides(
                left_slides,
                right_slides,
                left_pngs=left_pngs,
                right_pngs=right_pngs,
                left_size=left_size,
                right_size=right_size,
                use_ocr=use_ocr,
            )
        align_seconds = time.perf_counter() - t_align
    else:
        align_seconds = 0.0

    left_shots = render_deck(left_slides, left_map, left_size) if check else {}
    right_shots = render_deck(right_slides, right_map, right_size) if check else {}

    matched_left = {
        int(li)
        for li, raw_ri, _ in slots
        if li is not None and _right_indexes(raw_ri)
    }
    build_repeats = build_repeat_indices(left_slides, matched_left) if not same_type else set()
    point_titles = point_title_keys(left_slides) if not same_type else []
    evidence_dir = heat_dir.parent / "evidence"
    if check:
        evidence_dir.mkdir(parents=True, exist_ok=True)

    pairs = []
    for li, raw_ri, score in slots:
        ris = _right_indexes(raw_ri)
        ls = left_slides[li] if li is not None and li < len(left_slides) else None
        right_hits = [(i, right_slides[i]) for i in ris if i < len(right_slides)]
        rs = right_hits[0][1] if right_hits else None
        ri = right_hits[0][0] if right_hits else None
        extra_hits = right_hits[1:]
        all_right_skipped = bool(right_hits) and all(_skipped(slide) for _, slide in right_hits)
        if _skipped(ls) and (not right_hits or all_right_skipped):
            continue
        if ls is None and all_right_skipped:
            continue
        if not right_hits and _skipped(ls):
            continue
        pair_i = len(pairs)
        left_num = _slide_number(ls, li if li is not None else pair_i)
        right_nums = [_slide_number(slide, i) for i, slide in right_hits]
        right_num = right_nums[0] if right_nums else None
        pair_flags: list[Flag] = []
        pair: dict = {
            "index": pair_i,
            "number": pair_i + 1,
            "leftIndex": li if ls else None,
            "rightIndex": ri if rs else None,
            "rightIndexes": [i for i, _ in right_hits] if right_hits else [],
            "leftNumber": left_num if ls else None,
            "rightNumber": right_num if rs else None,
            "rightNumbers": right_nums,
            "leftSkipped": _skipped(ls),
            "rightSkipped": any(_skipped(slide) for _, slide in right_hits),
            "score": score,
            "sameType": same_type,
        }
        loc = _pair_location(
            left_label,
            left_num if ls else None,
            right_label,
            right_num if rs else None,
            right_nums=right_nums,
        ) or f"slide {pair_i + 1}"

        left_png = left_map.get(li) if li is not None else None
        right_png = right_map.get(ri) if ri is not None else None
        right_png_paths = [right_map.get(i) for i, _ in right_hits]
        if left_png:
            pair["leftPng"] = left_png.name
        if right_png:
            pair["rightPng"] = right_png.name
        if right_png_paths:
            pair["rightPngs"] = [p.name if p else None for p in right_png_paths]
        if ls:
            pair["leftText"] = slide_plain_text(ls)
            pair["leftMarkup"] = highlighted_markup(ls)
        if right_hits:
            pair["rightText"] = "\n".join(slide_plain_text(slide) for _, slide in right_hits)
            pair["rightMarkup"] = "\n".join(highlighted_markup(slide) for _, slide in right_hits)

        if ls is None:
            if check:
                if same_type:
                    _add_flag(
                        pair_flags,
                        flags,
                        make_flag(
                            "diff.missing", "diff", f"Missing on {left_label}.", location=loc,
                            slide=right_num, deck="dsk",
                        ),
                    )
                elif rs and not all(_layout_only(slide) for _, slide in right_hits):
                    _add_flag(
                        pair_flags,
                        flags,
                        make_flag(
                            "diff.unmatched",
                            "diff",
                            f"No matching {left_label} slide.",
                            default="info",
                            location=loc,
                            slide=right_num,
                            deck="dsk",
                        ),
                    )
            pair["missing"] = left_label
            pair["flags"] = pair_flags
            pairs.append(pair)
            continue
        if rs is None:
            if check:
                if same_type:
                    _add_flag(
                        pair_flags,
                        flags,
                        make_flag(
                            "diff.missing", "diff", f"Missing on {right_label}.", location=loc,
                            slide=left_num, deck="lw",
                        ),
                    )
                elif not _layout_only(ls) and li not in build_repeats:
                    _add_flag(
                        pair_flags,
                        flags,
                        make_flag(
                            "diff.unmatched",
                            "diff",
                            f"No matching {right_label} slide.",
                            default="info",
                            location=loc,
                            slide=left_num,
                            deck="lw",
                        ),
                    )
            if li in build_repeats:
                pair["buildRepeat"] = True
            pair["missing"] = right_label
            pair["flags"] = pair_flags
            pairs.append(pair)
            continue

        if not check:
            pair["flags"] = pair_flags
            pairs.append(pair)
            continue

        skipped_right = all_right_skipped if extra_hits else _skipped(rs)
        if _skipped(ls) != skipped_right:
            shown = left_label if not _skipped(ls) else right_label
            hidden = right_label if not _skipped(ls) else left_label
            _add_flag(
                pair_flags,
                flags,
                make_flag(
                    "diff.skip_mismatch",
                    "diff",
                    f"Shown on {shown} but skipped on {hidden}.",
                    location=loc,
                    slide=left_num,
                    deck="lw",
                ),
            )

        a_render = left_shots.get(li) if li is not None else None
        if a_render is None:
            a_render = render_slide(ls, left_png, left_size, use_ocr=use_ocr)
        b_renders = []
        for (idx, slide), png in zip(right_hits, right_png_paths):
            shot = right_shots.get(idx)
            if shot is None:
                shot = render_slide(slide, png, right_size, use_ocr=use_ocr)
            b_renders.append(shot)
        a_text = a_render.text
        b_text = "\n".join(r.text for r in b_renders)
        pair["leftRendered"] = a_text
        pair["rightRendered"] = b_text
        pair["ocr"] = a_render.ocr_used or any(r.ocr_used for r in b_renders)

        def compare(left_source: str, right_source: str):
            text = left_source
            dropped = None
            if point_titles:
                text, dropped = strip_carried_point_title(text, right_source, point_titles)
            return (
                classify_text_diff(
                    text,
                    right_source,
                    left_label,
                    right_label,
                    ignore_left_tokens=point_number_lines(text),
                ),
                dropped,
                text,
            )

        a_typed = a_render.typed
        b_typed = "\n".join(r.typed for r in b_renders)
        pair["typed"] = bool(a_typed.strip() or b_typed.strip())
        both_typed = bool(a_typed.strip() and b_typed.strip())
        finding = carried = None
        compare_text = a_text
        if both_typed and _covers_slide(a_typed, a_text) and _covers_slide(b_typed, b_text):
            finding, carried, compare_text = compare(a_typed, b_typed)
        if finding is None:
            a_clean = a_render.outside_photos
            b_clean = "\n".join(r.outside_photos for r in b_renders)
            if _filter_symmetric(a_clean, a_text, b_clean, b_text):
                a_seen, b_seen = a_clean or a_text, b_clean or b_text
            else:
                a_seen, b_seen = a_text, b_text
            found, dropped, text = compare(a_seen, b_seen)
            finding = found
            carried = carried or dropped
            compare_text = text
        if carried:
            _add_flag(
                pair_flags,
                flags,
                make_flag(
                    "text.point_carry",
                    "diff",
                    f'LW keeps the point title "{carried}" on this verse slide; '
                    "the DSK verse slide does not.",
                    default="info",
                    location=loc,
                    slide=left_num,
                    deck="lw",
                ),
            )
        copy_warning = False
        if finding:
            text_flag = make_flag(
                finding.rule,
                "diff",
                finding.message,
                default=finding.default,
                location=loc,
                slide=left_num,
                deck="lw",
            )
            if text_flag:
                _add_flag(pair_flags, flags, text_flag)
                if text_flag.severity in {"warning", "error"}:
                    copy_warning = True
        else:
            shared = _canonical_words(slide_plain_text(ls))
            for _, slide in right_hits:
                shared &= _canonical_words(slide_plain_text(slide))
            style_flag = None
            left_high = _highlighted_run_words(ls)
            right_high = {w for _, slide in right_hits for w in _highlighted_run_words(slide)}
            left_high, right_high = _shared_style_words(left_high, right_high, shared)
            if highlight_msg := _style_diff_message(
                "Highlighting differs", "highlights", left_high, right_high
            ):
                style_flag = make_flag(
                    "style.highlight", "diff", highlight_msg, location=loc,
                    slide=left_num, deck="lw",
                )
            else:
                right_small: set[str] = set()
                for _, slide in right_hits:
                    right_small |= _smallcaps_words(slide)
                left_small = _smallcaps_words(ls)
                left_small, right_small = _shared_style_words(left_small, right_small, shared)
                if smallcaps_msg := _style_diff_message(
                    "Small caps differ", "small-caps", left_small, right_small
                ):
                    style_flag = make_flag(
                        "style.smallcaps", "diff", smallcaps_msg, location=loc,
                        slide=left_num, deck="lw",
                    )
            if style_flag:
                _add_flag(pair_flags, flags, style_flag)

        extra_photo = [
            (slide, png, right_size)
            for (i, slide), png in zip(extra_hits, right_png_paths[1:])
            if png is not None
        ]
        region_hits = []
        video_pair = bool(
            left_png
            and right_png
            and (
                left_png.suffix.lower() in PREVIEW_VIDEO_SUFFIXES
                or right_png.suffix.lower() in PREVIEW_VIDEO_SUFFIXES
            )
        )
        if left_png and right_png and not same_type and not video_pair:
            from obed_edom.photo_regions import compare_slide_regions  # noqa: PLC0415

            region_hits = compare_slide_regions(
                ls,
                [slide for _, slide in right_hits],
                left_png,
                list(right_png_paths),
                left_size,
                right_size,
                evidence_dir,
                pair_i,
            )
            shown_regions = []
            for region in region_hits:
                if copy_warning and region.rule in {"photo.region", "photo.marker", "photo.framing"}:
                    continue
                shown_regions.append(region)
                _add_flag(
                    pair_flags,
                    flags,
                    make_flag(
                        region.rule,
                        "diff",
                        region.message,
                        default=region.default,
                        location=loc,
                        slide=left_num,
                        deck="lw",
                        evidence=region.evidence,
                    ),
                )
            first_evidence = next((r.evidence for r in shown_regions if r.evidence), "")
            if first_evidence:
                src = evidence_dir / first_evidence
                if src.is_file():
                    heat_dir.mkdir(parents=True, exist_ok=True)
                    dest = heat_dir / first_evidence
                    dest.write_bytes(src.read_bytes())
                    pair["heatPng"] = first_evidence
        photo_findings = photo_findings_for_pair(
            ls,
            [slide for _, slide in right_hits],
            left_label,
            right_label,
            left_size,
            right_size,
        )
        for photo in photo_findings:
            if region_hits and photo.rule == "photo.count":
                continue
            _add_flag(
                pair_flags,
                flags,
                make_flag(
                    photo.rule,
                    "diff",
                    photo.message,
                    default=photo.default,
                    location=loc,
                    slide=left_num,
                    deck="lw",
                ),
            )
        if left_png and right_png and not photo_findings and not region_hits:
            if video_pair:
                pair["flags"] = pair_flags
                pairs.append(pair)
                continue
            heat = heat_dir / f"pair-{pair_i + 1:03d}.png"
            if same_type and not extra_photo:
                vis = visual_diff(left_png, right_png, heat)
            else:
                vis = image_item_diff(
                    ls,
                    rs,
                    left_png,
                    right_png,
                    left_size,
                    right_size,
                    heat,
                    extra_rights=extra_photo or None,
                    skip_full_frame=True,
                )
            pair["visual"] = vis
            if vis.get("heatmap"):
                pair["heatPng"] = Path(str(vis["heatmap"])).name
            if vis.get("visual"):
                same_copy = not copy_warning
                if vis.get("reason") == "flipped":
                    rule, message, default = "photo.flipped", "Photo is flipped.", "warning"
                elif same_type:
                    rule, message, default = "photo.differs", "Photo or layout differs.", "warning"
                else:
                    rule, message, default = (
                        "photo.differs",
                        "The copy matches but the photos do not. Check the DSK is on the "
                        "latest image, and that it is not flipped or tilted.",
                        "warning",
                    )
                if not same_copy and rule == "photo.differs":
                    rule = ""
                if rule:
                    _add_flag(
                        pair_flags,
                        flags,
                        make_flag(
                            rule,
                            "diff",
                            message,
                            default=default,
                            location=loc,
                            slide=left_num,
                            deck="lw",
                        ),
                    )
        pair["flags"] = pair_flags
        pairs.append(pair)

    if check:
        left_text = {i: shot.text for i, shot in left_shots.items()}
        right_text = {i: shot.text for i, shot in right_shots.items()}
        left_ocr = {i: shot.ocr for i, shot in left_shots.items() if getattr(shot, "ocr_used", False)}
        right_ocr = {i: shot.ocr for i, shot in right_shots.items() if getattr(shot, "ocr_used", False)}
        inspect_flags: list[Flag] = []
        inspect_flags.extend(
            validate_inspect(
                left,
                location_prefix=left_label,
                deck="lw",
                previews=left_pngs,
                evidence_dir=evidence_dir,
                use_ocr=use_ocr,
                rendered=left_text,
                ocr=left_ocr,
            )
        )
        inspect_flags.extend(
            validate_inspect(
                right,
                location_prefix=right_label,
                deck="dsk",
                previews=right_pngs,
                evidence_dir=evidence_dir,
                use_ocr=use_ocr,
                rendered=right_text,
                ocr=right_ocr,
            )
        )
        flags.extend(inspect_flags)
        attach_slide_flags(pairs, inspect_flags)
    return {
        "leftSlideCount": n_left,
        "rightSlideCount": n_right,
        "leftSize": [left.get("slideWidth"), left.get("slideHeight")],
        "rightSize": [right.get("slideWidth"), right.get("slideHeight")],
        "sameType": same_type,
        "leftCatalog": slide_catalog(left_slides, left_map),
        "rightCatalog": slide_catalog(right_slides, right_map),
        "pairs": pairs,
        "flags": flags,
        "alignSeconds": align_seconds,
    }

