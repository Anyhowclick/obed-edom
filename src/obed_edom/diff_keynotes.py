from __future__ import annotations

import difflib
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from obed_edom.inspect import highlighted_markup, preview_pngs, slide_plain_text
from obed_edom.models import Flag
from obed_edom.validate import validate_inspect

LW_WIDTH = 3000
ALIGN_THRESHOLD = 0.58
IMAGE_HAMMING = 12
_PNG_NUM = re.compile(r"(\d+)")
_LAYOUT_MASTER = re.compile(r"TITLE|\bBLANK\b|FILLER", re.I)
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


def texts_equivalent(left: str, right: str) -> bool:
    """True when copy matches aside from wrap, nbsp, and field order (ref first vs last)."""
    a, b = comparable_tokens(left), comparable_tokens(right)
    if a == b:
        return True
    return _is_rotation(a, b)


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
    ta, tb = set(a.split()), set(b.split())
    if ta and tb:
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


def _layout_only(slide: dict) -> bool:
    master = str(slide.get("master") or "")
    if _LAYOUT_MASTER.search(master):
        return True
    text = slide_plain_text(slide).strip()
    has_image = any((item.get("kind") or "") == "image" for item in slide.get("items") or [])
    return not text and not has_image


def _gap_buckets(slides: list[dict], indices: list[int]) -> tuple[list[int], list[int]]:
    text: list[int] = []
    photos: list[int] = []
    for i in indices:
        if _layout_only(slides[i]):
            continue
        if _has_text(slides[i]):
            text.append(i)
        else:
            photos.append(i)
    return text, photos


def _slide_number(slide: dict | None, fallback_index: int) -> int:
    if not slide:
        return fallback_index + 1
    return int(slide.get("number") or slide.get("index", fallback_index) + 1)


def align_slides(
    left_slides: list[dict],
    right_slides: list[dict],
    *,
    threshold: float = ALIGN_THRESHOLD,
) -> list[tuple[int | None, int | None, float]]:
    """Order-preserving fuzzy pairs, then positional fill in the gaps.

    Returns (left_index or None, right_index or None, score). Unmatched layout-only
    left slides are omitted. Unmatched right content is kept as (None, ri).
    """
    n_left = len(left_slides)
    n_right = len(right_slides)
    fps_left = [fingerprint(slide_plain_text(s)) for s in left_slides]
    fps_right = [fingerprint(slide_plain_text(s)) for s in right_slides]
    used_left: set[int] = set()
    used_right: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    last_left = -1
    for ri in range(n_right):
        best: tuple[float, int] | None = None
        for li in range(last_left + 1, n_left):
            score = text_score(fps_left[li], fps_right[ri])
            if score >= threshold and (best is None or score > best[0]):
                best = (score, li)
        if best:
            _score, li = best
            used_left.add(li)
            used_right.add(ri)
            last_left = li
            matches.append((li, ri, _score))

    extra: list[tuple[int, int, float]] = []
    # Only fill gaps *between* confident matches — not the leading/trailing ends.
    for (l0, r0, _), (l1, r1, _) in zip(matches, matches[1:]):
        gap_left = [i for i in range(l0 + 1, l1) if i not in used_left]
        gap_right = [j for j in range(r0 + 1, r1) if j not in used_right]
        left_text, left_photos = _gap_buckets(left_slides, gap_left)
        right_text, right_photos = _gap_buckets(right_slides, gap_right)
        for li, ri in list(zip(left_text, right_text)) + list(zip(left_photos, right_photos)):
            extra.append((li, ri, 0.0))
            used_left.add(li)
            used_right.add(ri)

    ordered: list[tuple[int | None, int | None, float]] = [
        (li, ri, sc) for li, ri, sc in matches + extra
    ]
    for ri in range(n_right):
        if ri not in used_right and not _layout_only(right_slides[ri]):
            ordered.append((None, ri, 0.0))
    for li in range(n_left):
        if li not in used_left and not _layout_only(left_slides[li]) and _has_text(left_slides[li]):
            ordered.append((li, None, 0.0))

    def _key(slot: tuple[int | None, int | None, float]) -> tuple[int, int, int]:
        li, ri, _sc = slot
        if ri is not None:
            return (0, ri, li if li is not None else -1)
        return (1, li if li is not None else 0, 0)

    ordered.sort(key=_key)
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


def _png_for_slide(pngs: list[Path], slide: dict | None, fallback_index: int) -> Path | None:
    if not pngs:
        return None
    idx = fallback_index
    if slide is not None and slide.get("index") is not None:
        idx = int(slide["index"])
    number = _slide_number(slide, fallback_index)
    by_num: dict[int, Path] = {}
    for path in pngs:
        found = _PNG_NUM.findall(path.stem)
        if found:
            by_num[int(found[-1])] = path
    if number in by_num:
        return by_num[number]
    if 0 <= idx < len(pngs):
        return pngs[idx]
    return None


def _average_hash(im: Image.Image, size: int = 8) -> list[int]:
    small = im.convert("L").resize((size, size), Image.Resampling.LANCZOS)
    pixels = list(small.tobytes())
    avg = sum(pixels) / max(1, len(pixels))
    return [1 if p > avg else 0 for p in pixels]


def _hamming(a: list[int], b: list[int]) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def _image_items(slide: dict) -> list[dict]:
    return [item for item in slide.get("items") or [] if (item.get("kind") or "") == "image" and item.get("w") and item.get("h")]


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


def image_item_diff(
    left_slide: dict,
    right_slide: dict,
    left_png: Path,
    right_png: Path,
    left_size: tuple[float, float],
    right_size: tuple[float, float],
    out_png: Path,
    *,
    hamming_limit: int = IMAGE_HAMMING,
) -> dict:
    """Compare photo items after cropping; ignores full-frame layout chrome."""
    left_im = Image.open(left_png).convert("RGB")
    right_im = Image.open(right_png).convert("RGB")
    left_items = _image_items(left_slide)
    right_items = _image_items(right_slide)
    left_crops = [c for c in (_crop_item(left_im, it, left_size[0], left_size[1]) for it in left_items) if c]
    right_crops = [c for c in (_crop_item(right_im, it, right_size[0], right_size[1]) for it in right_items) if c]
    if not left_crops or not right_crops:
        return {"visual": False, "maxDelta": 0, "changedRatio": 0.0, "kind": "images"}

    left_hashes = [_average_hash(c) for c in left_crops]
    right_hashes = [_average_hash(c) for c in right_crops]
    used_r: set[int] = set()
    worst = 0
    mismatched: list[tuple[Image.Image, Image.Image]] = []
    for li, lh in enumerate(left_hashes):
        best: tuple[int, int] | None = None
        for ri, rh in enumerate(right_hashes):
            if ri in used_r:
                continue
            dist = _hamming(lh, rh)
            if best is None or dist < best[0]:
                best = (dist, ri)
        if best is None:
            continue
        dist, ri = best
        used_r.add(ri)
        worst = max(worst, dist)
        if dist > hamming_limit:
            mismatched.append((left_crops[li], right_crops[ri]))

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
    return {
        "maxDelta": worst,
        "changedRatio": worst / 64.0,
        "visual": visual,
        "heatmap": str(out_png) if visual else "",
        "kind": "images",
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
) -> str:
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


def compare_inspects(
    left: dict,
    right: dict,
    left_previews: Path,
    right_previews: Path,
    heat_dir: Path,
    *,
    left_label: str = "LW",
    right_label: str = "Other",
) -> dict:
    left_pngs = preview_pngs(left_previews)
    right_pngs = preview_pngs(right_previews)
    left_slides = left.get("slides") or []
    right_slides = right.get("slides") or []
    n_left = left.get("slideCount") or len(left_slides)
    n_right = right.get("slideCount") or len(right_slides)
    flags: list[Flag] = []
    same_type = _same_deck_type(left, right, left_label, right_label)
    if same_type and n_left != n_right:
        flags.append(
            Flag(
                "info",
                "diff",
                f"Slide count differs: {left_label} has {n_left}, {right_label} has {n_right}. Compared by index.",
            )
        )

    if same_type:
        slots: list[tuple[int | None, int | None, float]] = []
        for i in range(max(n_left, n_right, len(left_slides), len(right_slides))):
            li = i if i < len(left_slides) else None
            ri = i if i < len(right_slides) else None
            slots.append((li, ri, 1.0 if li is not None and ri is not None else 0.0))
    else:
        slots = align_slides(left_slides, right_slides)

    left_size = (float(left.get("slideWidth") or 0), float(left.get("slideHeight") or 0))
    right_size = (float(right.get("slideWidth") or 0), float(right.get("slideHeight") or 0))
    pairs = []
    for li, ri, score in slots:
        ls = left_slides[li] if li is not None and li < len(left_slides) else None
        rs = right_slides[ri] if ri is not None and ri < len(right_slides) else None
        if _skipped(ls) and _skipped(rs):
            continue
        if ls is None and _skipped(rs):
            continue
        if rs is None and _skipped(ls):
            continue
        pair_i = len(pairs)
        left_num = _slide_number(ls, li if li is not None else pair_i)
        right_num = _slide_number(rs, ri if ri is not None else pair_i)
        pair_flags: list[Flag] = []
        pair: dict = {
            "index": pair_i,
            "number": pair_i + 1,
            "leftNumber": left_num if ls else None,
            "rightNumber": right_num if rs else None,
            "leftSkipped": _skipped(ls),
            "rightSkipped": _skipped(rs),
            "score": score,
            "sameType": same_type,
        }
        loc = _pair_location(
            left_label,
            left_num if ls else None,
            right_label,
            right_num if rs else None,
        ) or f"slide {pair_i + 1}"

        if ls is None:
            if same_type:
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("warning", "diff", f"Missing on {left_label}.", location=loc),
                )
            elif rs and not _layout_only(rs):
                _add_flag(
                    pair_flags,
                    flags,
                    Flag(
                        "warning",
                        "diff",
                        f"No matching {left_label} slide.",
                        location=loc,
                    ),
                )
            pair["missing"] = left_label
            pair["rightText"] = slide_plain_text(rs) if rs else ""
            pair["rightMarkup"] = highlighted_markup(rs) if rs else ""
            right_png = _png_for_slide(right_pngs, rs, ri if ri is not None else -1)
            if right_png:
                pair["rightPng"] = right_png.name
            pair["flags"] = pair_flags
            pairs.append(pair)
            continue
        if rs is None:
            if same_type:
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("warning", "diff", f"Missing on {right_label}.", location=loc),
                )
            elif _has_text(ls):
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("info", "diff", f"No matching {right_label} slide.", location=loc),
                )
            pair["missing"] = right_label
            pair["leftText"] = slide_plain_text(ls)
            pair["leftMarkup"] = highlighted_markup(ls)
            left_png = _png_for_slide(left_pngs, ls, li if li is not None else -1)
            if left_png:
                pair["leftPng"] = left_png.name
            pair["flags"] = pair_flags
            pairs.append(pair)
            continue

        if _skipped(ls) != _skipped(rs):
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

        a_text = slide_plain_text(ls)
        b_text = slide_plain_text(rs)
        a_mark = highlighted_markup(ls)
        b_mark = highlighted_markup(rs)
        pair["leftText"] = a_text
        pair["rightText"] = b_text
        pair["leftMarkup"] = a_mark
        pair["rightMarkup"] = b_mark
        wording = wording_message(a_text, b_text, left_label, right_label)
        if wording:
            _add_flag(pair_flags, flags, Flag("warning", "diff", wording, location=loc))
        elif _highlighted_words(a_mark) != _highlighted_words(b_mark):
            _add_flag(
                pair_flags,
                flags,
                Flag("warning", "diff", "Highlighting differs.", location=loc),
            )
        elif _smallcaps_signature(ls) != _smallcaps_signature(rs):
            _add_flag(
                pair_flags,
                flags,
                Flag("warning", "diff", "Small caps differ.", location=loc),
            )

        left_png = _png_for_slide(left_pngs, ls, li if li is not None else -1)
        right_png = _png_for_slide(right_pngs, rs, ri if ri is not None else -1)
        if left_png:
            pair["leftPng"] = left_png.name
        if right_png:
            pair["rightPng"] = right_png.name
        if left_png and right_png:
            heat = heat_dir / f"pair-{pair_i + 1:03d}.png"
            if same_type:
                vis = visual_diff(left_png, right_png, heat)
            else:
                vis = image_item_diff(ls, rs, left_png, right_png, left_size, right_size, heat)
            pair["visual"] = vis
            if vis.get("heatmap"):
                pair["heatPng"] = Path(str(vis["heatmap"])).name
            if vis.get("visual") and texts_equivalent(a_text, b_text):
                _add_flag(
                    pair_flags,
                    flags,
                    Flag(
                        "warning",
                        "diff",
                        "Photo or layout differs." if same_type else "Photo differs.",
                        location=loc,
                    ),
                )
            elif vis.get("visual"):
                _add_flag(
                    pair_flags,
                    flags,
                    Flag("info", "diff", "Photo or layout differs.", location=loc),
                )
        pair["flags"] = pair_flags
        pairs.append(pair)

    flags.extend(validate_inspect(left, location_prefix=left_label))
    flags.extend(validate_inspect(right, location_prefix=right_label))
    return {
        "leftSlideCount": n_left,
        "rightSlideCount": n_right,
        "leftSize": [left.get("slideWidth"), left.get("slideHeight")],
        "rightSize": [right.get("slideWidth"), right.get("slideHeight")],
        "sameType": same_type,
        "pairs": pairs,
        "flags": flags,
    }
