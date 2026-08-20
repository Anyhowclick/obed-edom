from __future__ import annotations

from pathlib import Path

from PIL import Image

from obed_edom.models import Flag, SlideSpec

# x, y, w, h as fractions of slide size (origin top-left).
LW_REGIONS = {
    "TITLE": (0.20, 0.15, 0.55, 0.70),
    "VERSES": (0.15, 0.04, 0.70, 0.42),
    "NUMBERED POINT PRE": (0.15, 0.04, 0.70, 0.48),
    "NUMBERED POINT POST": (0.15, 0.04, 0.70, 0.55),
    "NON-NUMBERED POINT PRE": (0.15, 0.04, 0.70, 0.48),
    "NON-NUMBERED POINT POST": (0.15, 0.04, 0.70, 0.55),
    "BLANK": None,
}
DSK_REGIONS = {
    "verse": (0.03, 0.55, 0.70, 0.38),
    "point": (0.03, 0.55, 0.70, 0.38),
    "graphic": None,
}

WHITE = (255, 255, 255)
MIN_RATIO_AUTO = 3.0
MIN_RATIO_FLAG = 4.5
BRIGHT_LUMA = 0.42


def _luminance(rgb: tuple[float, float, float]) -> float:
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1 = _luminance(fg)
    l2 = _luminance(bg)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def _region_for(spec: SlideSpec) -> tuple[float, float, float, float] | None:
    if spec.deck == "lw":
        return LW_REGIONS.get(spec.master)
    if spec.is_graphic:
        return DSK_REGIONS["graphic"]
    if spec.is_verse:
        return DSK_REGIONS["verse"]
    return DSK_REGIONS["point"]


def _mean_color(im: Image.Image, region: tuple[float, float, float, float]) -> tuple[float, float, float]:
    w, h = im.size
    x, y, rw, rh = region
    left = max(0, int(x * w))
    top = max(0, int(y * h))
    right = min(w, int((x + rw) * w))
    bottom = min(h, int((y + rh) * h))
    crop = im.convert("RGB").crop((left, top, right, bottom))
    # Downsample so huge LED stills stay cheap.
    crop.thumbnail((160, 90))
    pixels = list(crop.getdata())
    n = max(1, len(pixels))
    r = sum(p[0] for p in pixels) / n
    g = sum(p[1] for p in pixels) / n
    b = sum(p[2] for p in pixels) / n
    return (r, g, b)


def _preview_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    files = sorted(folder.glob("*.png")) + sorted(folder.glob("*.PNG"))
    # Keynote sometimes writes into a nested folder.
    if not files:
        files = sorted(folder.rglob("*.png"))
    return files


def check_contrast(
    slides: list[SlideSpec],
    preview_dir: Path,
    deck: str,
) -> tuple[list[Flag], list[dict]]:
    flags: list[Flag] = []
    overlays: list[dict] = []
    images = _preview_files(preview_dir)
    if not images:
        flags.append(
            Flag("info", "contrast", f"No PNG previews found in {preview_dir} for {deck.upper()}.")
        )
        return flags, overlays

    for i, spec in enumerate(slides):
        if i >= len(images):
            break
        region = _region_for(spec)
        if region is None:
            continue
        try:
            with Image.open(images[i]) as im:
                bg = _mean_color(im, region)
        except OSError as exc:
            flags.append(Flag("info", "contrast", f"Could not read {images[i].name}: {exc}"))
            continue
        ratio = contrast_ratio(WHITE, bg)
        luma = _luminance(bg)
        loc = f"{deck.upper()} slide {i + 1} ({spec.master})"
        if luma > BRIGHT_LUMA or ratio < MIN_RATIO_AUTO:
            if spec.deck == "lw" and spec.master not in {"TITLE", "BLANK"}:
                flags.append(
                    Flag(
                        "warning",
                        "contrast",
                        f"Background too bright for white text (ratio {ratio:.1f}:1, luma {luma:.2f}). "
                        "Darken the photo in Keynote; text colours were not changed.",
                        location=loc,
                    )
                )
            else:
                flags.append(
                    Flag(
                        "warning",
                        "contrast",
                        f"Possible low contrast (ratio {ratio:.1f}:1). Review manually; text colours were not changed.",
                        location=loc,
                    )
                )
        elif ratio < MIN_RATIO_FLAG:
            flags.append(
                Flag(
                    "info",
                    "contrast",
                    f"Contrast {ratio:.1f}:1 is usable for large type but worth a glance.",
                    location=loc,
                )
            )
    if images and not any(f.severity == "warning" for f in flags):
        flags.append(
            Flag(
                "success",
                "contrast",
                f"Checked {min(len(images), len(slides))} {deck.upper()} previews; contrast looked OK.",
            )
        )
    return flags, overlays
