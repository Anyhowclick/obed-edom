from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass, replace

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_ENCODED_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 24_000_000
BASE_MIN_SIDE = 440.0
WORK_MIN_SIDE = 880
PAPER = np.array([245, 232, 201], np.float32) / 255
PENCIL = np.array([0.40, 0.29, 0.21], np.float32)


class WatercolourError(ValueError):
    pass


@dataclass(frozen=True)
class WatercolourOptions:
    wash_softness: float = 0.65
    ink_amount: float = 0.42
    transparent: bool = False
    paper: bool = True
    seed: int = 0


def decode_image(raw: bytes) -> Image.Image:
    if not raw or len(raw) > MAX_ENCODED_BYTES:
        raise WatercolourError("Image is empty or exceeds the 20 MB upload limit")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise WatercolourError("Image exceeds the 24 megapixel processing limit")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except Exception as exc:
        raise WatercolourError("Upload is not a valid image") from exc
    if image.width * image.height > MAX_PIXELS:
        raise WatercolourError("Image exceeds the 24 megapixel processing limit")
    return image


def _seed(raw: bytes, seed: int) -> int:
    return (int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") ^ int(seed)) & 0x7FFFFFFF


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(a, (0, 0), sigma) if sigma > 0 else a


def _norm(a: np.ndarray) -> np.ndarray:
    return (a - a.mean()) / (a.std() + 1e-6)


def _noise(rng: np.random.Generator, shape: tuple[int, int], sigma: float = 0.0) -> np.ndarray:
    return _blur(rng.normal(0, 1, shape).astype(np.float32), sigma)


def _odd(value: float) -> int:
    return max(1, int(round(value))) | 1


def _percentile(a: np.ndarray, q: float) -> float:
    step = max(1, int(math.sqrt(a.size / 2_000_000)))
    return max(float(np.percentile(a[::step, ::step], q)), 1e-5)


def _slider_gain(value: float, default: float, below: float, above: float) -> float:
    """Piecewise-linear slider response; exactly 1.0 at the default."""
    ratio = value / default
    return 1.0 + (below * (ratio - 1.0) if ratio <= 1.0 else above * (ratio - 1.0))


def _gradient(a: np.ndarray, sigma: float) -> np.ndarray:
    smooth = _blur(a, sigma)
    return np.hypot(cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)) / 8.0


def _line_kernel(angle: float, length: float) -> np.ndarray:
    size = max(3, int(round(length)) | 1)
    kernel = np.zeros((size, size), dtype=np.float32)
    half = (size - 1) / 2
    dx, dy = math.cos(angle) * half, math.sin(angle) * half
    cv2.line(kernel, (round(half - dx), round(half - dy)), (round(half + dx), round(half + dy)), 1.0, 1, cv2.LINE_AA)
    total = float(kernel.sum())
    return kernel / total if total else kernel


def _paper(shape: tuple[int, int], rng: np.random.Generator, scale: float) -> tuple[np.ndarray, np.ndarray]:
    mottle = _norm(_noise(rng, shape, 18 * scale))
    fibre = _norm(_noise(rng, shape, scale))
    tooth = _norm(_noise(rng, shape, 0.45 * scale if scale > 1.2 else 0))
    height = 0.55 * fibre + 0.30 * tooth + 0.15 * mottle
    colour = PAPER[None, None] * (1 + 0.022 * height + 0.012 * mottle)[:, :, None]
    return np.clip(colour, 0, 1).astype(np.float32), height.astype(np.float32)


def _strokes(shape: tuple[int, int], rng: np.random.Generator, angles: tuple[float, ...], length: float, bias: float, scale: float) -> np.ndarray:
    out = np.zeros(shape, np.float32)
    for angle in angles:
        seeds = _blur(rng.random(shape).astype(np.float32), 0.5 * scale)
        marks = cv2.filter2D(seeds, -1, _line_kernel(angle, length * scale), borderType=cv2.BORDER_REFLECT)
        out = np.maximum(out, _blur(np.clip((_norm(marks) + bias) / 1.6, 0, 1), 0.6 * scale))
    return out


def _wobble(img: np.ndarray, rng: np.random.Generator, scale: float) -> np.ndarray:
    h, w = img.shape[:2]
    # Preserve downstream paper and border randomness without displacing geometry.
    rng.normal(0, 1, (h, w))
    rng.normal(0, 1, (h, w))
    return img


def _pencil_edges(gray: np.ndarray, scale: float, hi: float = 1.5) -> np.ndarray:
    edges = np.maximum(_blur(gray, 0.84 * scale) - _blur(gray, 0.6 * scale), 0)
    t = np.clip((edges / _percentile(edges, 99) - 0.16) / (hi - 0.16), 0, 1)
    return t * t * (3 - 2 * t)


def _smoothness(luminance: np.ndarray, scale: float) -> np.ndarray:
    return np.clip(1 - _blur(_gradient(luminance, scale), 2 * scale) * scale / 0.03, 0, 1)


def _wash(rgb: np.ndarray, busy: np.ndarray, scale: float, softness: float) -> tuple[np.ndarray, np.ndarray]:
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    flat = cv2.pyrMeanShiftFiltering(bgr, max(1, round(5 * scale)), 16, maxLevel=1)
    flat = cv2.bilateralFilter(flat, max(1, round(7 * scale)), 30, 4 * scale)
    blotch = cv2.medianBlur(cv2.medianBlur(flat, _odd(7 * scale)), _odd(5 * scale))
    lab = cv2.cvtColor(flat, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab += (cv2.cvtColor(blotch, cv2.COLOR_BGR2LAB).astype(np.float32) - lab) * (0.6 * busy)[:, :, None]
    luminance = lab[:, :, 0] / 255.0
    chroma = np.clip(np.hypot(lab[:, :, 1] - 128, lab[:, :, 2] - 128) / 60.0, 0, 1)
    tone_gain = _slider_gain(softness, 0.65, -0.20, -0.30)
    tone = np.clip(luminance / ((0.92 - 0.09 * softness + 0.14 * chroma) * tone_gain), 0, 1)
    tone = np.minimum(tone, 1 - 0.3 * chroma)
    tone = 0.14 + 0.86 * tone
    tone += (1 - tone) * busy * 0.25
    lab[:, :, 0] = tone * 255
    boost = 1 + busy * 0.4
    lab[:, :, 1] = 128 + (lab[:, :, 1] - 128) * 1.1 * boost
    lab[:, :, 2] = 128 + (lab[:, :, 2] - 128) * 1.25 * boost
    wash = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB).astype(np.float32) / 255
    return wash, luminance


def _wash_layers(rgb: np.ndarray, busy: np.ndarray, rng: np.random.Generator, scale: float, options: WatercolourOptions) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    wash, luminance = _wash(rgb, busy, scale, options.wash_softness)
    shape = luminance.shape
    smooth = _smoothness(luminance, scale)
    scribble = np.maximum(_strokes(shape, rng, (math.radians(-26), math.radians(-14)), 15, 0.25, scale), _strokes(shape, rng, (math.radians(-20),), 9, 0.0, scale) * 0.8)
    patch = np.clip(_norm(_noise(rng, shape, 14 * scale)) * 0.25 + 0.8, 0, 1)
    shade = np.maximum(_strokes(shape, rng, (math.radians(50),), 9, 0.7, scale), _strokes(shape, rng, (math.radians(122),), 9, 0.4, scale) * 0.7)
    dark = np.clip((0.40 - _blur(luminance, 1.5 * scale)) / 0.40, 0, 1) * (1 - smooth)
    hatch = _slider_gain(options.ink_amount, 0.42, 0.60, 0.435)
    cover = (1 - smooth) + scribble * patch * (0.85 * hatch) * smooth
    cover *= 1 - dark * (1 - shade) * 0.5 * options.ink_amount
    wash = wash * (1 - smooth[:, :, None]) + (wash ** 1.25) * smooth[:, :, None]
    wash = _wobble(wash, rng, scale)
    pool = _blur(_gradient(1 - wash.mean(axis=2), 1.5 * scale), scale)
    pool = np.clip(pool / _percentile(pool, 97), 0, 1) * (1 - smooth)
    return wash, cover, pool, smooth


def _fill_hidden(rgb: np.ndarray, alpha: np.ndarray, scale: float) -> np.ndarray:
    inside = (alpha > 0).astype(np.float32)
    if not inside.any():
        return rgb
    sigma = 12 * scale
    weight = _blur(inside, sigma)
    filled = _blur(rgb.astype(np.float32) * inside[:, :, None], sigma) / np.maximum(weight, 1e-4)[:, :, None]
    filled = np.where(weight[:, :, None] > 1e-3, filled, rgb[alpha > 0].mean(axis=0))
    return np.where(alpha[:, :, None] > 0, rgb, np.clip(filled, 0, 255)).astype(np.uint8)


def _feather_mask(mask: np.ndarray, amount: float = 0.8) -> np.ndarray:
    if mask.dtype != np.uint8:
        mask = np.clip(mask, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(mask, (0, 0), amount)


def grabcut_mask(
    image: Image.Image,
    rect: tuple[float, float, float, float],
    *,
    foreground: list[tuple[float, float]] | None = None,
    background: list[tuple[float, float]] | None = None,
    keep_mask: Image.Image | None = None,
    remove_mask: Image.Image | None = None,
) -> Image.Image:
    x, y, width, height = rect
    if not all(math.isfinite(v) for v in rect) or width <= 0 or height <= 0:
        raise WatercolourError("Foreground rectangle must be finite and non-empty")
    if not (0 <= x < image.width and 0 <= y < image.height and x + width <= image.width and y + height <= image.height):
        raise WatercolourError("Foreground rectangle is outside the image")
    if len(foreground or []) + len(background or []) > 500:
        raise WatercolourError("Too many mask correction points")
    rgb = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    mask = np.zeros((image.height, image.width), np.uint8)
    model_bg = np.zeros((1, 65), np.float64)
    model_fg = np.zeros((1, 65), np.float64)
    cv2.grabCut(rgb, mask, (round(x), round(y), round(width), round(height)), model_bg, model_fg, 5, cv2.GC_INIT_WITH_RECT)
    for points, kind in ((foreground or [], cv2.GC_FGD), (background or [], cv2.GC_BGD)):
        for px, py in points:
            if not (math.isfinite(px) and math.isfinite(py) and 0 <= px < image.width and 0 <= py < image.height):
                raise WatercolourError("Mask correction point is outside the image")
            cv2.circle(mask, (round(px), round(py)), 6, kind, -1)
    for painted, kind in ((remove_mask, cv2.GC_BGD), (keep_mask, cv2.GC_FGD)):
        if painted is None:
            continue
        resized = painted.resize(image.size, Image.NEAREST)
        flag = np.asarray(resized.convert("L")) > 127
        mask[flag] = kind
    if foreground or background or keep_mask is not None or remove_mask is not None:
        cv2.grabCut(rgb, mask, None, model_bg, model_fg, 3, cv2.GC_INIT_WITH_MASK)
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    return Image.fromarray(alpha, "L")


def render(image: Image.Image, options: WatercolourOptions, mask: Image.Image | None = None) -> Image.Image:
    if not 0 <= options.wash_softness <= 1 or not 0 <= options.ink_amount <= 1:
        raise WatercolourError("Watercolour controls must be between zero and one")
    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    h, w = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    if mask is not None:
        if mask.size != image.size:
            raise WatercolourError("Mask dimensions must match the normalized image")
        alpha = np.minimum(alpha, np.asarray(mask.convert("L"), dtype=np.uint8))
    rgb = rgba[:, :, :3]
    scale = max(0.5, min(h, w) / BASE_MIN_SIDE)
    if options.transparent:
        rgb = _fill_hidden(rgb, alpha, scale)
    rng = np.random.default_rng(options.seed)
    paper, height = _paper((h, w), rng, scale)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0
    ink = _pencil_edges(gray, scale)
    busy = np.clip(_blur((ink > 0.35).astype(np.float32), 5 * scale) / 0.45, 0, 1)
    edge_gain = _slider_gain(options.ink_amount, 0.42, 0.40, 0.55)
    drawn = ink if edge_gain == 1.0 else _pencil_edges(gray, scale, 1.5 / edge_gain)
    factor = min(1.0, WORK_MIN_SIDE / min(h, w))
    if factor < 1:
        size = (max(2, round(w * factor)), max(2, round(h * factor)))
        layers = _wash_layers(cv2.resize(rgb, size, interpolation=cv2.INTER_AREA), cv2.resize(busy, size, interpolation=cv2.INTER_AREA), rng, max(0.5, min(size) / BASE_MIN_SIDE), options)
        wash, cover, pool, smooth = (cv2.resize(layer, (w, h), interpolation=cv2.INTER_LINEAR) for layer in layers)
    else:
        wash, cover, pool, smooth = _wash_layers(rgb, busy, rng, scale, options)
    wash_gain = _slider_gain(options.wash_softness, 0.65, -0.30, -0.85)
    cover = cover * ((0.90 - 0.18 * options.wash_softness) * wash_gain) * np.clip(1 - 0.22 * np.maximum(height - 0.4, 0), 0.5, 1)
    dark_source = _blur(gray, 0.6 * scale)
    pigment_floor = np.clip((0.60 - dark_source) / 0.35, 0, 1)
    pigment_floor = pigment_floor * pigment_floor * (3 - 2 * pigment_floor)
    floor_gain = min(max(wash_gain, 0.55), 1.15)
    cover = np.maximum(cover, (0.78 * floor_gain) * pigment_floor)
    transmit = np.clip(1 - (1 - wash) * cover[:, :, None], 0, 1) ** (1 + 0.35 * pool)[:, :, None]
    result = paper * transmit
    strength = _gradient(gray, 1.2 * scale)
    strength = np.clip(strength / _percentile(strength, 95), 0, 1) ** 0.8
    ink = drawn * (0.35 + 0.65 * strength) * (1 - 0.85 * smooth) * (1 - 0.55 * busy) * np.clip(1 - 0.4 * np.maximum(height, 0), 0.4, 1) * options.ink_amount
    if options.transparent:
        out_alpha = _feather_mask(alpha)
        ink = ink * (out_alpha / 255.0)
    ink = np.clip(ink, 0, 1)[:, :, None]
    line = 0.45 * PENCIL[None, None] + 0.55 * wash * 0.75
    result = result * (1 - ink) + line * ink
    if options.transparent:
        return Image.fromarray(np.dstack((np.clip(result * 255, 0, 255).astype(np.uint8), out_alpha)), "RGBA")
    background = paper if options.paper else np.broadcast_to(PAPER, (h, w, 3))
    yy, xx = np.ogrid[:h, :w]
    border = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy)).astype(np.float32)
    irregular = cv2.resize(rng.normal(0, 1, (max(2, h // 50), max(2, w // 50))).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    fade = np.clip((border + irregular * min(w, h) * 0.008) / max(10, min(w, h) * 0.03), 0, 1)[:, :, None]
    fade = fade * (alpha[:, :, None] / 255.0)
    composited = background * (1 - fade) + result * fade
    return Image.fromarray(np.clip(composited * 255, 0, 255).astype(np.uint8), "RGB")


def convert(raw: bytes, options: WatercolourOptions, mask: Image.Image | None = None) -> tuple[bytes, tuple[int, int]]:
    image = decode_image(raw)
    result = render(image, replace(options, seed=_seed(raw, options.seed)), mask)
    output = io.BytesIO()
    result.save(output, "PNG", optimize=False)
    return output.getvalue(), result.size
