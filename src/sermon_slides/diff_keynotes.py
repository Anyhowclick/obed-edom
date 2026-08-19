from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from sermon_slides.inspect import highlighted_markup, preview_pngs, slide_plain_text
from sermon_slides.models import Flag
from sermon_slides.validate import validate_inspect


def _open_rgb(path: Path, size: tuple[int, int] | None = None) -> Image.Image:
    im = Image.open(path).convert("RGB")
    if size and im.size != size:
        im = im.resize(size, Image.Resampling.LANCZOS)
    return im


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
    changed = sum(1 for p in gray.getdata() if p > threshold)
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
    if n_left != n_right:
        flags.append(
            Flag(
                "error",
                "diff",
                f"Slide count differs: {left_label} has {n_left}, {right_label} has {n_right}. Compared by index.",
            )
        )

    pairs = []
    count = max(n_left, n_right)
    for i in range(count):
        pair: dict = {"index": i, "number": i + 1}
        ls = left_slides[i] if i < len(left_slides) else None
        rs = right_slides[i] if i < len(right_slides) else None
        if ls is None:
            flags.append(Flag("error", "diff", f"Missing {left_label} slide {i + 1}", location=f"slide {i + 1}"))
            pair["missing"] = left_label
            pairs.append(pair)
            continue
        if rs is None:
            flags.append(Flag("error", "diff", f"Missing {right_label} slide {i + 1}", location=f"slide {i + 1}"))
            pair["missing"] = right_label
            pairs.append(pair)
            continue

        a_text = slide_plain_text(ls)
        b_text = slide_plain_text(rs)
        a_mark = highlighted_markup(ls)
        b_mark = highlighted_markup(rs)
        pair["leftText"] = a_text
        pair["rightText"] = b_text
        pair["leftMarkup"] = a_mark
        pair["rightMarkup"] = b_mark
        loc = f"slide {i + 1}"
        if a_text.strip() != b_text.strip():
            flags.append(
                Flag(
                    "warning",
                    "diff",
                    f"Text differs.\n{left_label}: {a_text[:240]!r}\n{right_label}: {b_text[:240]!r}",
                    location=loc,
                )
            )
        elif a_mark != b_mark:
            flags.append(
                Flag(
                    "warning",
                    "diff",
                    f"Highlight ranges differ ({left_label} vs {right_label}). "
                    f"{left_label}: {a_mark[:240]!r} / {right_label}: {b_mark[:240]!r}",
                    location=loc,
                )
            )

        vis = None
        if i < len(left_pngs) and i < len(right_pngs):
            heat = heat_dir / f"slide-{i + 1:03d}.png"
            vis = visual_diff(left_pngs[i], right_pngs[i], heat)
            pair["visual"] = vis
            pair["leftPng"] = left_pngs[i].name
            pair["rightPng"] = right_pngs[i].name
            pair["heatPng"] = heat.name
            if vis.get("visual") and a_text.strip() == b_text.strip():
                flags.append(
                    Flag(
                        "warning",
                        "diff",
                        "Visual difference with matching text (highlight, circle, blur, or layout).",
                        location=loc,
                    )
                )
            elif vis.get("visual"):
                flags.append(
                    Flag("info", "diff", "Visual difference on this slide.", location=loc)
                )
        pairs.append(pair)

    flags.extend(validate_inspect(left, location_prefix=left_label))
    flags.extend(validate_inspect(right, location_prefix=right_label))
    return {
        "leftSlideCount": n_left,
        "rightSlideCount": n_right,
        "leftSize": [left.get("slideWidth"), left.get("slideHeight")],
        "rightSize": [right.get("slideWidth"), right.get("slideHeight")],
        "pairs": pairs,
        "flags": flags,
    }
