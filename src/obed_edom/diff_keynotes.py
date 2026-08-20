from __future__ import annotations

import difflib
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from obed_edom.inspect import highlighted_markup, preview_pngs, slide_plain_text
from obed_edom.models import Flag
from obed_edom.validate import validate_inspect

LW_WIDTH = 3000
CENTER_WALL = (3840, 1080)
ALIGN_THRESHOLD = 0.58
IMAGE_HAMMING = 12
GRAPHIC_TOKENS = 2
SHORT_TITLE_TOKENS = 8
_PNG_NUM = re.compile(r"(\d+)")
_SOFT_WS = re.compile(r"[\s\u2028\u2029\xa0]+")
_EDGE_PUNCT = re.compile(r"^[\s.,;:!?…'\"“”‘’()\[\]—–-]+|[\s.,;:!?…'\"“”‘’()\[\]—–-]+$")


def _deck_type(payload: dict, label: str = "") -> str | None:
    """Classify a Keynote as lw or dsk. Filename/label beat canvas width.

    GW/LW LED walls are often 1920×1080, same as DSK, so width alone cannot
    tell mixed-type compares apart.
    """
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


def fingerprint(text: str) -> str:
    return " ".join(_SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).lower().split())


def comparable_tokens(text: str) -> list[str]:
    """Whitespace-folded tokens, original case. Ignores wrap/nbsp/line-separator."""
    folded = _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()
    out: list[str] = []
    for raw in folded.split() if folded else []:
        core = _EDGE_PUNCT.sub("", raw)
        out.append(core or raw)
    return out


def _is_rotation(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b) or not a:
        return False
    doubled = a + a
    n = len(a)
    return any(doubled[i : i + n] == b for i in range(n))


def _collapse_repeat(tokens: list[str]) -> list[str]:
    """LW often duplicates a verse on both sides of the wall."""
    n = len(tokens)
    if n >= 4 and n % 2 == 0 and tokens[: n // 2] == tokens[n // 2 :]:
        return tokens[: n // 2]
    return tokens


def texts_equivalent(left: str, right: str) -> bool:
    """True when copy matches aside from wrap, nbsp, wall-duplication, and ref order."""
    a, b = _collapse_repeat(comparable_tokens(left)), _collapse_repeat(comparable_tokens(right))
    if a == b or _is_rotation(a, b):
        return True
    sa, sb = " ".join(a), " ".join(b)
    if not sa or not sb:
        return False
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if short not in long:
        return False
    rest = " ".join(long.replace(short, " ", 1).split())
    return rest in {"", short}


def text_score(left: str, right: str) -> float:
    """Similarity for pairing. Case-folded fingerprints; does not rewrite originals."""
    a = fingerprint(left)
    b = fingerprint(right)
    if not a or not b:
        return 1.0 if a == b and a else 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 8 and shorter in longer:
        seq = max(seq, 0.9)
    wa, wb = a.split(), b.split()
    ta, tb = set(wa), set(wb)
    if not ta or not tb:
        return seq
    short_n, long_n = (len(wa), len(wb)) if len(wa) <= len(wb) else (len(wb), len(wa))
    similar_len = long_n <= max(8, short_n * 4)
    if not similar_len:
        return seq
    cov = len(ta & tb) / min(len(ta), len(tb))
    if min(len(ta), len(tb)) >= 2:
        seq = max(seq, cov * 0.95)
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    content = {t for t in small if not t.isdigit() and len(t) > 1}
    if content and len(content) <= 4 and content <= large:
        seq = max(seq, 0.82)
    return seq


def _has_text(slide: dict) -> bool:
    return bool(slide_plain_text(slide).strip())


def _iter_items(node: dict):
    items = node.get("items") or node.get("children") or []
    for item in items:
        yield item
        yield from _iter_items(item)


def _layout_only(slide: dict) -> bool:
    """Blank TITLE/FILLER chrome. Real photos or copy on those masters still count."""
    if _has_text(slide):
        return False
    return not any((item.get("kind") or "") == "image" for item in _iter_items(slide))


def _token_count(slide: dict) -> int:
    return len(comparable_tokens(slide_plain_text(slide)))


def _can_positional_pair(left_slide: dict, right_slide: dict) -> bool:
    """Empty LW graphic vs short DSK title (event thumbs / title cards)."""
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
) -> float:
    score = text_score(slide_plain_text(left_slide), slide_plain_text(right_slide))
    if score >= ALIGN_THRESHOLD:
        return score
    if _token_count(left_slide) > SHORT_TITLE_TOKENS and _token_count(right_slide) > SHORT_TITLE_TOKENS:
        return score
    if not _image_items(left_slide) or not _image_items(right_slide):
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
) -> list[tuple[int | None, int | None, float]]:
    """Walk visible slides. Extra LW photos stay unmatched when a later LW fits.

    Skipped slides are ignored unless a visible slide on the other deck is similar.
    Title graphics with little extracted text pair positionally with short DSK titles.
    Photo hash is flip-tolerant for matching only; flips are flagged later.
    """
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
    return ordered


def visual_diff(a_png: Path, b_png: Path, out_png: Path, threshold: int = 18) -> dict:
    a = Image.open(a_png).convert("RGB")
    b = Image.open(b_png).convert("RGB")
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
    """Map 0-based slide index → preview PNG.

    Keynote names exports left.001.png in export order. With skipped slides
    omitted, file numbers are visible-order, not Keynote slide numbers.
    """
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
    """Return (direct hamming, flipped hamming). Flip is matching-only similarity."""
    direct = _hamming(left_bits, right_bits)
    flipped = _hamming(left_bits, _hflip_bits(right_bits))
    return direct, flipped


def center_wall_box(slide_w: float, slide_h: float) -> tuple[float, float, float, float]:
    """Slide-space box for the 3840×1080 center wall. Sides outside it are decorative."""
    wall_w, wall_h = CENTER_WALL
    if slide_w <= 0 or slide_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    if slide_w <= wall_w:
        return (0.0, 0.0, slide_w, min(slide_h, wall_h))
    x0 = (slide_w - wall_w) / 2.0
    return (x0, 0.0, x0 + wall_w, min(slide_h, wall_h))


def crop_center_wall(im: Image.Image, slide_w: float, slide_h: float) -> Image.Image:
    """Keep the center wall; drop LW side wings for pixel/hash compares."""
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
        im = Image.open(png).convert("RGB")
    except OSError:
        return None
    items = [
        it
        for it in _image_items(slide)
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
    im = Image.open(png).convert("RGB")
    items = [it for it in _image_items(slide) if _overlaps_center_wall(it, size[0], size[1])]
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
) -> dict:
    """Compare photo items after cropping; ignores full-frame layout chrome."""
    left_im, left_crops = _photo_crops(left_slide, left_png, left_size)
    right_im, right_crops = _photo_crops(right_slide, right_png, right_size)
    right_has_text = _has_text(right_slide)
    for extra_slide, extra_png, extra_size in extra_rights or []:
        _, extra_crops = _photo_crops(extra_slide, extra_png, extra_size)
        right_crops.extend(extra_crops)
        right_has_text = right_has_text or _has_text(extra_slide)
    if not left_crops or not right_crops:
        if _has_text(left_slide) or right_has_text:
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


def _smallcaps_signature(slide: dict) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for item in slide.get("items") or []:
        for run in item.get("runs") or []:
            text = run.get("text") or ""
            if not text.strip():
                continue
            cap = str(run.get("capitalization") or "")
            small = bool(run.get("smallCaps")) or "small" in cap.lower()
            out.append((text, small))
    return out


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


def _highlighted_words(markup: str) -> set[str]:
    words: set[str] = set()
    for chunk in re.findall(r"\*([^*]+)\*", markup or ""):
        words.update(comparable_tokens(chunk))
    return words


def _brief(text: str, limit: int = 140) -> str:
    return _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()[:limit]


def wording_message(left: str, right: str, left_label: str, right_label: str) -> str | None:
    if texts_equivalent(left, right):
        return None
    la, ra = set(comparable_tokens(left)), set(comparable_tokens(right))
    only_l = sorted(la - ra)
    only_r = sorted(ra - la)
    lines = [
        "Wording differs.",
        f"{left_label}: {_brief(left)}",
        f"{right_label}: {_brief(right)}",
    ]
    if only_l:
        lines.append(f"Only in {left_label}: " + ", ".join(only_l[:8]))
    if only_r:
        lines.append(f"Only in {right_label}: " + ", ".join(only_r[:8]))
    return "\n".join(lines)


def _add_flag(bucket: list[Flag], flags: list[Flag], flag: Flag) -> None:
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
) -> dict:
    left_pngs = preview_pngs(left_previews)
    right_pngs = preview_pngs(right_previews)
    left_slides = left.get("slides") or []
    right_slides = right.get("slides") or []
    left_map = map_preview_pngs(left_slides, left_pngs)
    right_map = map_preview_pngs(right_slides, right_pngs)
    n_left = left.get("slideCount") or len(left_slides)
    n_right = right.get("slideCount") or len(right_slides)
    flags: list[Flag] = []
    same_type = _same_deck_type(left, right, left_label, right_label)
    if check and same_type and n_left != n_right:
        flags.append(
            Flag(
                "info",
                "diff",
                f"Slide count differs: {left_label} has {n_left}, {right_label} has {n_right}. Compared by index.",
            )
        )

    left_size = (float(left.get("slideWidth") or 0), float(left.get("slideHeight") or 0))
    right_size = (float(right.get("slideWidth") or 0), float(right.get("slideHeight") or 0))

    if slots is None:
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
            )

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
                        Flag("warning", "diff", f"Missing on {left_label}.", location=loc),
                    )
                elif rs and not all(_layout_only(slide) for _, slide in right_hits):
                    _add_flag(
                        pair_flags,
                        flags,
                        Flag("warning", "diff", f"No matching {left_label} slide.", location=loc),
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
                        Flag("warning", "diff", f"Missing on {right_label}.", location=loc),
                    )
                elif not _layout_only(ls):
                    _add_flag(
                        pair_flags,
                        flags,
                        Flag("info", "diff", f"No matching {right_label} slide.", location=loc),
                    )
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
                Flag(
                    "warning",
                    "diff",
                    f"Shown on {shown} but skipped on {hidden}.",
                    location=loc,
                ),
            )

        a_text = pair.get("leftText") or ""
        b_text = pair.get("rightText") or ""
        a_mark = pair.get("leftMarkup") or ""
        b_mark = pair.get("rightMarkup") or ""
        wording = wording_message(a_text, b_text, left_label, right_label)
        if wording:
            _add_flag(pair_flags, flags, Flag("warning", "diff", wording, location=loc))
        elif _highlighted_words(a_mark) != _highlighted_words(b_mark):
            _add_flag(
                pair_flags,
                flags,
                Flag("warning", "diff", "Highlighting differs.", location=loc),
            )
        else:
            right_sig: list[tuple[str, bool]] = []
            for _, slide in right_hits:
                right_sig.extend(_smallcaps_signature(slide))
            if _smallcaps_signature(ls) != right_sig:
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("warning", "diff", "Small caps differ.", location=loc),
                )

        extra_photo = [
            (slide, png, right_size)
            for (i, slide), png in zip(extra_hits, right_png_paths[1:])
            if png is not None
        ]
        if left_png and right_png:
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
                )
            pair["visual"] = vis
            if vis.get("heatmap"):
                pair["heatPng"] = Path(str(vis["heatmap"])).name
            if vis.get("visual") and texts_equivalent(a_text, b_text):
                if vis.get("reason") == "flipped":
                    photo_msg = "Photo is flipped."
                elif same_type:
                    photo_msg = "Photo or layout differs."
                else:
                    photo_msg = "Photo differs."
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("warning", "diff", photo_msg, location=loc),
                )
            elif vis.get("visual"):
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("info", "diff", "Photo or layout differs.", location=loc),
                )
        pair["flags"] = pair_flags
        pairs.append(pair)

    if check:
        flags.extend(validate_inspect(left, location_prefix=left_label))
        flags.extend(validate_inspect(right, location_prefix=right_label))
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
    }

