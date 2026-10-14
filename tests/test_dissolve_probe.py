"""Synthetic tests for the pure DX-1 scorer in `scripts/dissolve_probe.py` (plan `keynote_live_dissolve_crossfade` §10 item 4).

No browser, host or export. One parametrized test over a case table: every case builds its numpy evidence (or a whole
run record in the shape the hook and driver produce) here and states the verdict the scorer must return. The rows cover
the cross-fade model, pop-in, dip, +-1 LSB, masked video, curve, monotone, hand-off and capture integrity; cut union,
complementary and clean swap; strip decode (valid / parity error) and strip under incoming content (Ô decodes, the raw
frame does not); holder binding (match / ambiguous); frozen index, drifting Ô and too few demixable frames; the patch-off
media arm (complete -> FAIL, no playback or a holder -> INCONCLUSIVE, never an expected FAIL); foreground correct /
omitted / shifted / double-painted / swapped; tone within 2, untoned and the identity decision; cost; independent
overlay; the measured-LUT construction; and the round's control rule (controls read before candidates). Rev 12 adds the
both-opaque no-dip class, device-scale holder decode, holder pixels under `L_path`, production-mask verification against
the twin, the reference-capture profile and `perfect`/`perfect-shift`, tone coverage, timestamped hide/show captures and
their dropped-action controls, and the exterior gate / geometry guard engagement check.

The world is 640x360 (`VIEWPORT` patched): outgoing texture opaque for x < 520, incoming for x >= 500, and a 1920x540
counter movie drawn at (10, 10) x 0.25 inside the outgoing-only class; its holder backing is the 480x135 device box.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie as binary  # noqa: E402
import dissolve_probe as probe  # noqa: E402

from obed_edom import live_runtime  # noqa: E402

W, H = 640, 360
CONTENT = [10.0, 10.0, 480.0, 135.0]
ORIGIN, SCALE = (10.0, 10.0), 0.25
REFERENCE = 42
BAKED = 0
INSERT_MS, DURATION_MS = 96.0, 1500.0
STOCK = next(iter(live_runtime.SUPPORTED_PLAYERS))
CAL = probe.Calibration()


def unpremul(p: np.ndarray) -> np.ndarray:
    a = np.clip(p[..., 3:4], 0, 255)
    rgb = np.where(a > 0, p[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(np.concatenate([rgb, a], axis=2)), 0, 255).astype(np.uint8)


def strip_frame(index: int, size: tuple[int, int] = (binary.WIDTH, binary.HEIGHT), bw: bool = False) -> np.ndarray:
    """A natural-size opaque movie frame: mid-grey (or pure black with `bw`) with the binary strip coding `index`."""
    w, h = size
    img = np.zeros((h, w, 4), np.uint8)
    img[..., 3] = 255
    if not bw:
        img[..., :3] = 126
        img[..., 0] = (126 + (np.arange(w) % 40)).astype(np.uint8)
    sx, sy, sw, sh = binary.STRIP_RECT
    img[sy:sy + sh, sx:sx + sw, :3] = 0 if bw else 126
    for bit, (x, y, bw, bh) in zip(binary.strip_bits(index), binary.BLOCK_RECTS):
        img[y:y + bh, x:x + bw, :3] = 255 if bit else 0
    return img


def textures() -> tuple[np.ndarray, np.ndarray]:
    yy, xx = np.mgrid[0:H, 0:W]
    A = np.zeros((H, W, 4), np.uint8)
    B = np.zeros((H, W, 4), np.uint8)
    A[..., 0], A[..., 1], A[..., 2] = 200, (40 + xx % 60), (30 + yy % 50)
    A[:, :520, 3] = 255
    A = probe.over(probe.place(strip_frame(BAKED), CONTENT, CONTENT, (H, W)), A)
    A[:, 520:] = 0
    B[..., 0], B[..., 1], B[..., 2] = (20 + yy % 40), 90, (150 + xx % 80)
    B[:, 500:, 3] = 255
    B[:, :500] = 0
    return A, B


def mix(A: np.ndarray, B: np.ndarray, e: float, kind: str = "patch") -> np.ndarray:
    Ap, Bp = probe.premul(A), probe.premul(B)
    if kind == "patch":
        return unpremul((1 - e) * Ap + e * Bp)
    if kind == "stock":
        return unpremul((1 - e) * Ap + (1 - (1 - e) * Ap[..., 3:4] / 255.0) * Bp)
    return unpremul((1 - e) * Ap + (1 - (1 - e) * Ap[..., 3:4] / 255.0) * e * Bp)


ES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def fade(kind: str = "patch", *, noise: bool = False, garbage: bool = False, masked: bool = False, es: list[float] = ES,
         classes: tuple[str, ...] = ("out", "in", "overlap"), dent: str | None = None) -> dict[str, str]:
    A, B = textures()
    frames = [mix(A, B, e, kind) for e in es]
    for f in frames:
        if dent == "overlap":
            f[100, 510, 3] = 251
        elif dent == "in-only":
            f[100, 600, 3] = 248
    if dent == "endpoints":
        frames[0][100, 510, 3] = 100
        frames[-1][100, 600, 3] = 100
    rng = np.random.default_rng(7)
    if noise:
        frames = [np.clip(f.astype(int) + rng.integers(-1, 2, f.shape) * (np.arange(4) < 3), 0, 255).astype(np.uint8) for f in frames]
    rect = [560.0, 200.0, 40.0, 40.0]
    if garbage:
        for f in frames:
            f[200:240, 560:600] = (255, 0, 255, 255)
    out = probe.score_fade(frames, A, B, exclude=[rect] if masked else [], classes=classes, cal=CAL)
    if out["problems"]:
        return {"verdict": "INCONCLUSIVE"}
    return {k: "PASS" if v else "FAIL" for k, v in out["checks"].items()}


def class_too_small() -> list[str]:
    A, B = textures()
    return probe.score_fade([mix(A, B, e) for e in ES], A, B, exclude=[[0.0, 0.0, 510.0, 360.0]], classes=("out",))["problems"]


def raf_curve(shape: str) -> list[dict[str, Any]]:
    rows = []
    for i in range(1, 12):
        ct = i * 125.0
        v = probe.ease_in_out(ct / DURATION_MS) if shape != "linear" else ct / DURATION_MS
        start = None if shape == "no-start" else 0.0
        anims = [{"leaf": "in", "ct": ct, "start": start, "state": "running", "dur": DURATION_MS, "value": v},
                 {"leaf": "out", "ct": ct, "start": 4.0 if shape == "two-starts" else start, "state": "running",
                  "dur": DURATION_MS, "value": 1 - v}]
        if shape == "late-nan" and i == 11:
            anims[0]["value"] = math.nan
        if shape == "final-malformed" and i == 11:
            for a in anims:
                a.update(ct=None, value=math.nan)
        if shape == "state-empty" and i == 11:
            for a in anims:
                a.update(state="", ct=math.nan)
        if shape == "duplicate-in":
            anims.append(dict(anims[0], value=0.0))
        rows.append({"t": ct, "eff": [v, 1 - v], "anims": anims})
    if shape in ("pending", "pending-dip"):
        rows[:0] = [{"t": t, "eff": [0, 1], "anims": [{"leaf": leaf, "ct": 0, "start": None, "state": "running", "dur": DURATION_MS,
                                                        "value": value} for leaf, value in (("in", 0), ("out", 1))]} for t in (-30.0, -15.0)]
    if shape == "pending-dip":
        rows[0]["eff"][1] = rows[0]["anims"][1]["value"] = 0.5
    if shape == "late-reset":
        rows.append({"t": rows[-1]["t"] + 16.0, "eff": [0, 1], "anims": [{"leaf": leaf, "ct": 0, "start": None, "state": "running",
                                                                           "dur": DURATION_MS, "value": value} for leaf, value in (("in", 0), ("out", 1))]})
    return rows


def cut(kind: str) -> str:
    """rAFs from insertion (t 0, incoming hidden), the cut's frames, then three more; cast frames carry class alpha ranges."""
    eff = {"union": [(1, 1), (1, 1), (1, 0)], "complementary": [(0, 1), (0.5, 0.5), (1, 0)], "swap": [(0, 1), (1, 0), (1, 0)],
           "completion-union": [(0, 1), (0.5, 0.5), (1, 1)], "no-pre": [(0.5, 0.5), (1, 0)]}.get(kind, [(0, 1), (1, 0), (1, 0)])
    raf = [{"t": 0.0, "eff": list(eff[0]), "anims": [] if kind != "no-pre" else [{"ct": 1.0}]}]
    raf += [{"t": 16.0 * (k + 1), "eff": list(v), "anims": [{"ct": 1.0}]} for k, v in enumerate(eff[1:])]
    raf += [{"t": 16.0 * k} for k in range(4, 8)]
    full, none_, half = (255.0, 255.0), (0.0, 0.0), (127.5, 127.5)
    cast = {"union": [(8.0, full, full)], "complementary": [(8.0, half, half)], "swap": [(8.0, none_, full), (24.0, full, none_)],
            "completion-union": [(8.0, half, half)], "no-pre": [(8.0, half, half)], "cast-after": [(90.0, full, none_)]}.get(kind, [])
    if kind == "straddle":
        return probe.score_cut(raf, [{"t": 8.0, "t0": -20.0, "t1": 36.0, "in": full, "out": none_}], CAL)["verdict"]
    return probe.score_cut(raf, [{"t0": t, "t1": t, "in": i, "out": o} for t, i, o in cast], CAL)["verdict"]


def no_flash(kind: str) -> str:
    if kind == "covered":
        raf = [{"t": 0.0, "eff": [0, 1], "anims": [{"ct": 0}]}, {"t": 16.0, "eff": [0.1, 0.9], "anims": [{"ct": 16.0}]}]
    else:
        raf = [{"t": 16.0, "eff": [0.1, 0.9], "anims": [{"ct": 16.0}]}]
    return probe.score_no_flash(raf, None, CAL)["verdict"]


def strip_under_incoming() -> tuple[bool, bool]:
    e, idx = 0.6, 1365
    S = strip_frame(idx, (720, 64))
    B = strip_frame(idx ^ 0xFFF, (720, 64))
    F = unpremul((1 - e) * probe.premul(S) + e * probe.premul(B))
    return probe.decode_strip(F) == idx, probe.decode_strip(probe.straight(probe.demix(F, B, e))) == idx


def parity_error() -> int | None:
    img = strip_frame(1380, (720, 64))
    x, y, w, h = binary.BLOCK_RECTS[len(binary.START) + binary.DATA_BITS]
    img[y:y + h, x:x + w, :3] = 255 - img[y:y + h, x:x + w, :3]
    return probe.decode_strip(img)


def bind(ambiguous: bool) -> tuple[int, int]:
    holder = {"rect": CONTENT}
    decoders = [{"id": 0, "region": CONTENT}, {"id": 1, "region": [10.6, 9.5, 480.4, 135.0] if ambiguous else [300.0, 10.0, 100.0, 50.0]}]
    bound, problems = probe.bind_holders([holder], decoders)
    return len(bound), len(problems)


def region(drift: bool, frames: int = 4) -> str:
    base = np.full((20, 40, 4), 126, np.uint8)
    base[..., 3] = 255
    es = [0.1, 0.3, 0.5, 0.7][:frames]
    regions = [np.clip(base.astype(float) / (1 - e) if drift else base, 0, 255).astype(np.uint8) for e in es]
    return probe.score_region(regions, es, CAL)["verdict"]


def bw_hold() -> str:
    """A pure black/white movie region left at full strength over the fade: Ô = S / (1 - e) drifts in alpha."""
    S = np.zeros((20, 40, 4), np.uint8)
    S[..., 3] = 255
    S[:, 20:, :3] = 255
    B = np.zeros_like(S)
    es = [0.1, 0.3, 0.5, 0.7]
    return probe.score_region([probe.demix(S, B, e) for e in es], es, CAL)["verdict"]


def foreground(variant: str) -> str:
    shape = (H, W)
    movie = probe.place(strip_frame(REFERENCE), CONTENT, CONTENT, shape)
    red, orange, square = (65.0, 12.0, 40.0, 10.0), (86.0, 14.0, 40.0, 10.0), (95.0, 12.0, 60.0, 10.0)

    def paint(img: np.ndarray, rect: tuple[float, ...], rgb: tuple[int, int, int], dx: int = 0, alpha: float = 1.0) -> None:
        x, y, w, h = (int(v) for v in rect)
        roi = img[y:y + h, x + dx:x + w + dx, :3].astype(float)
        img[y:y + h, x + dx:x + w + dx, :3] = np.rint((1 - alpha) * roi + alpha * np.array(rgb)).astype(np.uint8)

    def draw(order: tuple[str, ...], dx: int = 0, squares: int = 1) -> np.ndarray:
        img = movie.copy()
        for name in order:
            paint(img, red if name == "red" else orange, (230, 20, 20) if name == "red" else (250, 160, 0), dx)
        for _ in range(squares):
            paint(img, square, (240, 240, 240), dx, 0.2947)
        return img

    live = draw(("red", "orange"))
    candidate = {"correct": draw(("red", "orange")), "omitted": movie.copy(), "shifted": draw(("red", "orange"), dx=2),
                 "double": draw(("red", "orange"), squares=2), "swapped": draw(("orange", "red"))}[variant]
    mask = probe.block_mask(shape, ORIGIN, SCALE) & probe.rect_mask(shape, [red, orange, square])
    return probe.score_foreground([candidate], live, mask, CAL)["verdict"]


def foreground_demix_amplification() -> tuple[Any, ...]:
    e = 0.7994
    live = np.full((2, 2, 4), (180, 180, 180, 255), np.uint8)
    incoming = np.full((2, 2, 4), (60, 60, 60, 255), np.uint8)
    frame = unpremul((1 - e) * probe.premul(live) + e * probe.premul(incoming))
    frame[0, 0, 1] += 1
    noisy = probe.straight(probe.demix(frame, incoming, e))
    defect = live.copy()
    defect[0, 0, 1] += 25
    direct = live.copy()
    direct[0, 0, 1] += 5
    mask = np.ones(live.shape[:2], bool)
    noise = probe.score_foreground([live, noisy], live, mask, CAL, demix_es=[e])
    broken = probe.score_foreground([live, defect], live, mask, CAL, demix_es=[e])
    holder = probe.score_foreground([direct], live, mask, CAL)
    return (noise["verdict"], noise["detail"]["worsts"], [round(value, 6) for value in noise["detail"]["limits"]],
            broken["verdict"], holder["verdict"])


def foreground_without_incoming() -> tuple[str, list[float]]:
    record, images = media_run("m-fg")
    arm = probe.ARMS["m-fg"]
    ev = probe.evidence(record, images, arm)
    fade = probe._fade_of(ev, arm, CAL)
    ev.B = None
    foreground = probe.score_media(record, images, ev, arm, fade, CAL, identity=None)[0]["foreground"]
    return foreground["verdict"], foreground["detail"]["limits"]


def tone(variant: str) -> str:
    live = np.full((40, 40, 4), 139, np.uint8)
    live[..., 3] = 255
    holder = live.copy()
    if variant == "within":
        holder[..., :3] = 141
    elif variant in ("untoned", "identity"):
        holder[..., :3] = 128
    mask = np.ones((40, 40), bool)
    return probe.score_tone(holder, live, live.copy(), mask, identity=variant == "identity")["verdict"]


def overlay(present: bool) -> str:
    video = {"id": 3, "on": True, "inT": False, "eff": 1.0, "rect": [100.0, 20.0, 200.0, 80.0]}
    raf = [{"t": 0.0, "eff": [0.2, 0.8], "videos": [video] if present else []}]
    return probe.score_overlay(raf, CONTENT, probe.result(True))["verdict"]


def lut(variant: str) -> Any:
    snap, live = [], []
    for s, values in ((50, (60, 61, 90)), (100, (110, 111, 112)), (200, (205, 206, 207))):
        for v in values:
            snap.append((s, s, s))
            live.append((v, v + (5 if variant == "disagree" else 0), v))
    if variant == "analytic":
        curve = probe.analytic_lut()
        snap = [(s, s, s) for s in (32, 64, 128, 192)]
        live = [(int(curve[s]),) * 3 for s in (32, 64, 128, 192)]
    if variant == "red-off":
        snap, live = [(128, 128, 128)], [(137, 138, 138)]
    if variant == "endpoints":
        snap, live = [(0, 0, 0), (128, 128, 128), (255, 255, 255)], [(30, 30, 30), (139, 139, 139), (220, 220, 220)]
    if variant == "empty":
        snap, live = np.zeros((0, 3)), np.zeros((0, 3))
    out = probe.build_lut(np.array(snap), np.array(live))
    if variant != "table":
        return out["kind"]
    t = out["table"]
    return out["kind"], t[0], t[50], t[75], t[100], t[200], t[255], out["observed"]


FG_RECT = [60.0, 20.0, 40.0, 10.0]
IDENTITY_LUT = np.arange(256, dtype=np.uint8)
TONE_LAYOUT = {"ramp": [[400 + 200 * i, 200, 160, 160, 60 + 40 * i] for i in range(4)],
               "patches": [[400 + 200 * i, 370, 160, 160, [200, 40, 40]] for i in range(4)]}
SHARED_MUTATIONS = ("holder-shift", "holder-shift-undecodable", "edge-step", "tone-step", "tex-zero", "tex-in-opaque")
INJECTED = {"caption": {"box": [-60.0, 300.0, 40.0, 20.0], "paint": [-60.0, 300.0, 456.0, 48.0]},
            "script": {"box": [-60.0, 300.0, 40.0, 20.0], "paint": [-60.0, 300.0, 480.0, 48.0]},
            "svgclip": {"box": [-300.0, 100.0, 200.0, 200.0], "paint": [-50.0, 130.0, 150.0, 40.0]},
            "svg": {"paint": [-50.0, 130.0, 150.0, 40.0]}, "shadow-fixed": {"paint": [0.0, 0.0, 640.0, 360.0]},
            "nav-open": {"box": [0.0, 0.0, 130.0, 360.0]}, "modal": {"open": True, "modal": True},
            "shadow-modal": {"open": True, "modal": True}}


TEXTURE_RECTS = ((65.0, 12.0, 40.0, 10.0), (86.0, 14.0, 40.0, 10.0))


def paint_textures(img: np.ndarray) -> np.ndarray:
    """`m-fg`'s two opaque texture layers, overlapping each other over the counter blocks (later one on top)."""
    out = img.copy()
    for (x, y, w, h), rgb in zip(TEXTURE_RECTS, ((230, 20, 20), (250, 160, 0))):
        out[int(y):int(y + h), int(x):int(x + w)] = (*rgb, 255)
    return out


def edge_foreground_rects() -> tuple[tuple[float, float, float, float], ...]:
    parent_near = (CONTENT[0] - 2.5, CONTENT[1] - 2.5)
    return tuple((parent_near[0] + x, parent_near[1] + y, w, h)
                 for x, y, w, h in (*probe.EDGE_FOREGROUND_RECTS, probe.EDGE_FOREGROUND_SQUARE_RECT))


def paint_edge_foreground(img: np.ndarray) -> np.ndarray:
    out = img.copy()
    for rect, rgba in zip(edge_foreground_rects(), ((230, 20, 20, 255), (250, 160, 0, 255), (240, 240, 240, 75))):
        x, y, w, h = rect
        x0 = probe.jround(CONTENT[0]) + probe.jround(x - CONTENT[0])
        x1 = probe.jround(CONTENT[0]) + probe.jround(x + w - CONTENT[0])
        y0 = probe.jround(CONTENT[1]) + probe.jround(y - CONTENT[1])
        y1 = probe.jround(CONTENT[1]) + probe.jround(y + h - CONTENT[1])
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(out.shape[1], x1), min(out.shape[0], y1)
        layer = np.zeros_like(out)
        layer[y0:y1, x0:x1] = rgba
        out = probe.over(layer, out)
    return out


def paint_fg(img: np.ndarray, rect: list[float] = FG_RECT) -> np.ndarray:
    """The redrawn foreground canvas (opaque light grey) over the movie at `FG_RECT`."""
    out = img.copy()
    x, y, w, h = (int(v) for v in rect)
    out[y:y + h, x:x + w] = (240, 240, 240, 255)
    return out


def reference_block(spec: Any, A: np.ndarray, B: np.ndarray, with_holder: np.ndarray, live: np.ndarray, mutate: str | None,
                    images: dict[str, np.ndarray], box: tuple[int, int, int, int]) -> dict[str, Any]:
    """The paused, seeked reference capture (F50, B, A0 and `perfect`, two shots each) in the driver's shape."""
    pictures = {"F50": mix(with_holder, B, 0.5), "B": mix(with_holder, B, 0.9995), "A0": with_holder.copy()}
    if mutate == "ref-stale":
        pictures["F50"] = pictures["A0"].copy()
    x0, y0, x1, y1 = box
    perfect = with_holder.copy()
    crop = live[y0:y1, x0:x1]
    if spec.shift:
        perfect[y0:y1, x0 + 1:x1], perfect[y0:y1, x0] = crop[:, :-1], A[y0:y1, x0]
    else:
        perfect[y0:y1, x0:x1] = crop
    pictures["perfect"] = perfect
    for k, v in pictures.items():
        images[f"ref-{k}-0"], images[f"ref-{k}-1"] = v, v.copy()
    if mutate == "ref-unstable":
        images["ref-F50-1"][200, 300, 0] ^= 1
    if mutate == "ref-stale-patch":
        for k, dv in (("F50", 10), ("B", 20)):
            images[f"ref-{k}-0"] = images["ref-A0-0"].copy()
            images[f"ref-{k}-0"][200:210, 100:110, 0] -= dv
            images[f"ref-{k}-1"] = images[f"ref-{k}-0"].copy()
    if mutate == "ref-alias-f50":
        del images["ref-F50-1"]
    targets = ("layer3-opacity", "layer4-opacity")
    inventory = [{"target": t, "leaf": leaf, "state": "running"} for t, leaf in zip(targets, ("in", "out"))]
    if mutate == "ref-missing-anim":
        inventory.pop()
    elif mutate == "ref-extra-anim":
        inventory.append({"target": "layer9", "leaf": None, "state": "running"})
    effs = {"F50": [0.5, 0.5], "B": [0.9995, 0.0005], "A0": [0.0, 1.0]}
    states = []
    for k, (label, f) in enumerate(probe.REF_STATES):
        anims = [{"target": t, "state": "paused", "ct": f * DURATION_MS, "dur": DURATION_MS} for t in targets]
        if label == "F50" and mutate == "ref-unpaused":
            anims[0]["state"] = "running"
        if label == "F50" and mutate == "ref-ct-off":
            anims[1]["ct"] += 2.0
        names = [f"ref-{label}-0", f"ref-{label}-0" if label == "F50" and mutate == "ref-alias-f50" else f"ref-{label}-1"]
        states.append({"label": label, "f": f, "t": 10.0 if mutate == "ref-early" and not k else 300.0 + 100 * k,
                       "dom": not (label == "A0" and mutate == "ref-dom-gone"), "eff": effs[label], "anims": anims, "shots": names})
    timers = None if mutate == "timers-missing" else {"minMs": probe.TIMER_MIN_MS, "extraMs": probe.TIMER_EXTRA_MS,
                                                      "delayedMs": [] if mutate == "timers-none" else [DURATION_MS]}
    return {"inventory": inventory, "states": states, **({"timers": timers} if timers else {}),
            "perfect": {"shift": spec.shift, "rect": [0, 0, 1, 1] if mutate == "perfect-rect-bad" else list(box), "dom": True,
                        "t": 700.0, "shots": ["live-0", "live-1"] if mutate == "ref-alias-perfect" else ["ref-perfect-0", "ref-perfect-1"]}}


def media_run(arm: str, *, holder: bool = True, presented: int = 30, mutate: str | None = None, fullstrength: bool = False,
              bw: bool = False) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """A whole run record and its images in the hook/driver shape: P2-like 2->3 with one counter movie. The holder backing
    is device size (480x135 at (10, 10)); reference arms add `FG_RECT`'s foreground canvas (omitted from an `fg-omit`
    twin's holder) and the reference capture; hide rows a 32-ms screencast with dark frames while hidden."""
    A, B = textures()
    spec = probe.ARMS[arm]
    reference = spec.capture == "reference"
    k, dy = spec.dsf, spec.letterbox / 2
    vh, vw = probe.device_shape(spec)
    top = probe.jround(dy * k)

    def dev(img: np.ndarray) -> np.ndarray:
        """CSS world -> device screen: nearest-neighbour by the DSF, below the letterbox's top rows."""
        if k == 1 and not dy:
            return img
        up = np.asarray(Image.fromarray(img).resize((round(W * k), round(H * k)), Image.NEAREST))
        out = np.zeros((vh, vw, 4), np.uint8)
        out[top:top + up.shape[0]] = up[:vh - top]
        return out

    content_x = (probe.NOOFFSET_X_DISPLACEMENT * CONTENT[2] / 951.54296875
                 if "nooffsetx" in spec.overrides else 10.0)
    content_y = (probe.NOOFFSET_Y_DISPLACEMENT * CONTENT[3] / 267.6214599609375
                 if "nooffsety" in spec.overrides else 10.0)
    left = content_x + 0.4 * CONTENT[2] + 0.37 if {"clipnearx", "nooffsetx"} & set(spec.overrides) else content_x
    top_local = content_y + 0.4 * CONTENT[3] + 0.37 if {"clipneary", "nooffsety"} & set(spec.overrides) else content_y
    top_css = top_local + dy
    right = 310.37 if "clipx" in spec.overrides else 490.0
    bottom = 90.37 + dy if "clipy" in spec.overrides else content_y + CONTENT[3] + dy
    box = (probe.jround(left * k), probe.jround(top_css * k), probe.jround(right * k), probe.jround(bottom * k))
    x0, y0, x1, y1 = box
    in_box = np.zeros((vh, vw, 1), bool)
    in_box[y0:y1, x0:x1] = True
    local_content = [content_x, content_y, 480.0, 135.0]
    content = [content_x, content_y + dy, 480.0, 135.0]
    region = [left, top_css, right - left, bottom - top_css]
    css_box = [left, top_css, (x1 - x0) / k, (y1 - y0) / k]
    foreground_local = [max(FG_RECT[0], left + 10), max(FG_RECT[1], top_local + 10), FG_RECT[2], FG_RECT[3]]
    foreground_rect = [foreground_local[0], foreground_local[1] + dy, foreground_local[2], foreground_local[3]]
    frame = strip_frame(REFERENCE, bw=bw)
    if mutate == "holder-y-nooffset":
        frame[..., 1] = (80 + np.arange(frame.shape[0]) % 120)[:, None]
    placed = probe.place(frame, local_content, local_content, (H, W))
    movie = placed.copy()
    if mutate in ("holder-shift", "holder-shift-undecodable"):
        movie[10:145, 11:490] = placed[10:145, 10:489]
    elif mutate == "holder-y-nooffset":
        movie[..., :3] = np.roll(placed[..., :3], round(abs(content_y)), axis=0)
    omit = "fg-omit" in (spec.splice or "")
    if "edgefg" in spec.overrides:
        live_placed, holder_placed = paint_edge_foreground(placed), movie if omit else paint_edge_foreground(movie)
    elif reference or spec.movies == "tone":
        live_placed, holder_placed = paint_fg(placed, foreground_local), movie if omit else paint_fg(movie, foreground_local)
    elif "fg" in spec.overrides:
        live_placed, holder_placed = paint_textures(placed), movie if omit else paint_textures(movie)
    else:
        live_placed, holder_placed = placed, movie
    A_d, B_d = dev(A), dev(B)
    holder_px = dev(holder_placed)[y0:y1, x0:x1].copy()
    if mutate == "holder-shift-undecodable":
        holder_px[:12, :172, :3] = 126
    if mutate == "edge-step":
        holder_px[:, 0, :3] = np.clip(holder_px[:, 0, :3].astype(int) + 8, 0, 255)
    holder_full = np.zeros_like(A_d)
    holder_full[y0:y1, x0:x1] = holder_px
    with_holder = probe.over(holder_full, A_d) if holder else A_d
    live = probe.over(np.where(in_box, dev(live_placed), 0).astype(np.uint8), A_d) if holder else A_d
    movie_d = np.where(in_box, dev(placed), 0).astype(np.uint8)
    if mutate == "tone-step":
        toned = in_box[..., 0].copy()
        fx0, fy0 = x0 + probe.jround(50 * k), y0 + probe.jround(10 * k)
        toned[fy0:fy0 + round(10 * k), fx0:fx0 + round(40 * k)] = False
        live = live.copy()
        live[..., :3][toned] = probe.analytic_lut()[live[..., :3][toned]]
    raf, shots, images = [], [], {"tex-in": B, "tex-out": A, "live-0": live, "live-1": live.copy()}
    for t in np.arange(0.0, 1900.0, 16.0):
        present = INSERT_MS <= t < INSERT_MS + DURATION_MS
        e = probe.ease_in_out((t - INSERT_MS) / DURATION_MS)
        video = {"id": 0, "on": not t >= INSERT_MS}
        if video["on"]:
            video.update(rect=list(content), eff=1.0, inT=False, inStage=True, paused=False,
                         geo={"content": list(content), "region": list(region), "size": [binary.WIDTH, binary.HEIGHT]})
        rec = {"t": float(t), "hash": "#5", "scene": 5, "videos": [video]}
        if (mutate == "stale-take" and t < INSERT_MS) or (mutate == "takes-dup" and t >= INSERT_MS):
            rec["take"] = 22.0
        if mutate in ("delay-42", "delay-99") and present and t < INSERT_MS + 500:
            e = 0.0
        if present:
            rec["eff"] = [e, 1 - e]
            ct = 0.0 if mutate in ("delay-42", "delay-99") and t < INSERT_MS + 500 else t - INSERT_MS
            if mutate == "no-pre-raf" and t == INSERT_MS:
                ct = 1.0
            rec["anims"] = [{"leaf": "in", "ct": ct, "start": INSERT_MS, "state": "running", "dur": DURATION_MS, "value": e},
                            {"leaf": "out", "ct": ct, "start": INSERT_MS, "state": "running", "dur": DURATION_MS, "value": 1 - e}]
        raf.append(rec)
    hiding = (spec.row or "").startswith("hide")
    acts = [(INSERT_MS + 1000 * o, n) for o, n in probe.LIFECYCLE[spec.row].get("actions", ())] if spec.row else []
    when = {n: t for t, n in acts}

    def dark_at(t0: float, t1: float) -> bool:
        if not hiding:
            return False
        if spec.drop == "show":
            return t1 >= when["hide"]
        return spec.drop != "hide" and when["hide"] <= t1 and t0 <= when["show"]

    step = 60.0 if hiding else 110.0
    times = [10.0, 40.0, 70.0] + list(np.arange(120.0, 1590.0, step)) + [1650.0, 1700.0, 1750.0]
    for n, t0 in enumerate([] if reference else times):
        name = f"shot-{n:03d}"
        if t0 < INSERT_MS:
            img = with_holder
        elif t0 >= INSERT_MS + DURATION_MS:
            img = B_d
        else:
            e = probe.ease_in_out((t0 + 5 - INSERT_MS) / DURATION_MS)
            img = probe.over(movie_d, mix(A_d, B_d, e)) if arm == "m-hold" or fullstrength else mix(with_holder, B_d, e)
            if mutate in ("delay-42", "delay-99") and t0 + 10 < INSERT_MS + 500:
                img = probe.over(dev(probe.place(strip_frame(99), CONTENT, CONTENT, (H, W))), A_d) if mutate == "delay-99" and n == 4 else with_holder
            if dark_at(t0, t0 + 10):
                img = np.zeros_like(img)
        images[name] = img
        shots.append({"name": name, "t0": float(t0), "t1": float(t0) + 10.0, "durationMs": 10.0})
    blend, iso = ("plus-lighter", "isolate") if spec.styles == "on" else ("normal", "auto")
    chain = [[{"id": tid, "blend": "normal", "isolation": "auto"}, {"id": leaf, "blend": blend, "isolation": "auto"},
              {"id": f"{leaf}-opacity", "blend": "normal", "isolation": "auto"}, {"id": "layer2", "blend": "normal", "isolation": iso}]
             for tid, leaf in (("IN", "layer3"), ("OUT", "layer4"))]
    parent = "layer2" if spec.splice == "hold" else "layer3-opacity" if mutate == "parent-incoming" else "layer4-opacity"
    holders = [{"parent": parent, "rect": list(css_box), "canvasRect": list(css_box), "natural": [x1 - x0, y1 - y0]}] if holder else []
    if holder:
        images["holder-0"] = holder_px
    pins = live_runtime.SUPPORTED_PLAYERS[STOCK]
    expected = pins[probe.PIN_INDEX[spec.mode]] if spec.splice is None else "f" * 64
    rv = [[present_at, (REFERENCE - presented + i) / binary.FPS, i + int(i >= max(2, presented // 2)), present_at + 16.0]
          for i in range(1, presented + 1)
          for present_at in [INSERT_MS - 1 - (presented - i) * 33.0]]
    timestamp_us = REFERENCE / binary.FPS * 1_000_000
    freeze_draws = [
        {"startedAt": INSERT_MS - 0.8 + index * 0.02, "finishedAt": INSERT_MS - 0.79 + index * 0.02,
         "durationMs": 0.01, "argumentCount": 5,
         "beforeTimestampUs": timestamp_us, "afterTimestampUs": timestamp_us,
         "beforeError": None, "afterError": None}
        for index in range(2 if spec.placement_value == "frac" else 1)
    ]
    record = {
        "arm": arm, "page": spec.page, "load": 0.5, "headlessBefore": 0, "stage": probe.stage_of(spec), "dsf": k,
        "viewport": list(probe.viewport_of(spec)),
        **({"launch": {"chromeArgs": ["--headless=new", f"--force-device-scale-factor={k:g}"],
                       "metricsOverride": {"deviceScaleFactor": k} if mutate == "dsf-emulated" else None}} if k != 1 else {}),
        "target": {"textures": ["IN", "OUT"], "hashBefore": "#5", "hashAfter": "#7"},
        "served": {"mode": spec.mode, "splice": spec.splice, "stockSha256": STOCK, "expected": expected},
        "output": {"mmOpacity": {"sha256": expected}}, "hashBefore": "#5", "hashAfter": "#7", "shots": shots, "advanceAt": 50.0,
        "foreground": {"0": []},
        "dump": {"raf": raf, "first": {"textures": ["IN", "OUT"], "chain": chain, "holders": holders,
                                       "layerIds": ["layer2", "layer3-opacity", "layer4-opacity"]},
                 "vids": [{"id": 0, "rv": rv, "rvAt": [row[0] + 0.1 for row in rv],
                            "freezeDraws": freeze_draws, "detach": INSERT_MS - 0.5,
                            "tuple": "bt709/bt709/bt709/false"}],
                 "takes": [[INSERT_MS - 1.0, 22.0]]},
    }
    if spec.capture in ("paused", "reference"):
        record["paused"] = {"state": "presented", "frame": REFERENCE, "id": 0}
    record["placement"] = (None if spec.page in ("raw", "preview") else "invalid") if spec.grant == "none" else (
        spec.placement_value or "snap")
    if spec.forgery:
        value, kind = probe.FORGERIES[spec.forgery]
        record["placement"] = value
        record["forgery"] = {"read": value, "kind": kind, "configurable": kind != "getter",
                             "enumerable": kind == "assignment", "writable": kind == "assignment"}
    if spec.reason:
        record["output"]["placement"] = {"grant": "snap" if spec.reason == "granted" else None, "reason": spec.reason,
                                         "product": "HeadlessChrome/154.0.8037.59", "gpuCompositing": "enabled", "at": 1.0}
    if spec.regrant:
        record["reload"] = {"before": "invalid", "after": "snap"}
    if spec.capture == "channel":
        record["showRefused"] = True
    if spec.movies == "tone":
        layout = dict(TONE_LAYOUT)
        if mutate == "tone-under-fg":
            layout = {"ramp": [[200, 40, 160, 40, 128]], "patches": [[200, 40, 160, 40, [128, 128, 128]]]}
        if mutate == "tone-small-cells":
            layout["ramp"] = [[x, y, 16 if i else w, 16 if i else h, v] for i, (x, y, w, h, v) in enumerate(TONE_LAYOUT["ramp"])]
        record["movies"] = {"x.mov": {"layout": layout}}
    if "edgefg" in spec.overrides:
        record["foreground"] = {"0": []}
        ids = (*probe.FOREGROUND_TEXTURES, probe.FOREGROUND_SQUARE)
        alphas = (1.0, 1.0, 0.2947)
        for j, (tid, r, alpha) in enumerate(zip(ids, edge_foreground_rects(), alphas)):
            image = np.zeros((int(r[3]), int(r[2]), 4), np.uint8)
            image[...] = (255, 255, 255, round(alpha * 255))
            images[f"fg-0-{j}"] = image
            record["foreground"]["0"].append({"id": tid, "rect": list(r), "alpha": alpha,
                                                   "order": 5 + j, "image": f"fg-0-{j}"})
    elif "fg" in spec.overrides:
        record["foreground"] = {"0": []}
        for j, (tid, r) in enumerate(zip(probe.FOREGROUND_TEXTURES, TEXTURE_RECTS)):
            images[f"fg-0-{j}"] = np.full((int(r[3]), int(r[2]), 4), 255, np.uint8)
            record["foreground"]["0"].append({"id": tid, "rect": [r[0], r[1] + dy, r[2], r[3]], "alpha": 1.0, "order": 5 + j, "image": f"fg-0-{j}"})
    if (reference or spec.movies == "tone") and "edgefg" not in spec.overrides:
        rect, size = (list(foreground_rect), (10, 40))
        if mutate == "mask-whole":
            rect, size = [40.0, 15.0 + dy, 100.0, 30.0], (30, 100)
        elif mutate == "mask-shift3":
            rect = [foreground_rect[0] + 3, *foreground_rect[1:]]
        fg = np.zeros((*size, 4), np.uint8)
        fg[...] = (240, 240, 240, 255)
        images["fg-0-0"] = fg
        record["foreground"] = {"0": [] if mutate == "mask-empty" else [{"id": "FG", "rect": rect, "alpha": 1.0, "order": 7, "image": "fg-0-0"}]}
    if reference:
        record["reference"] = reference_block(spec, A_d, B_d, with_holder, live, mutate, images, box)
    if spec.inject:
        record["inject"] = None if mutate == "no-inject" else {**INJECTED[spec.inject], **({"open": False} if mutate == "inject-false" else {}),
                                                               **({"box": [0.0, 10000.0, 130.0, 360.0]} if mutate == "nav-offscreen" else {})}
    if mutate == "no-take":
        record["dump"]["takes"] = []
    if spec.row:
        images["settled"] = B_d
        record.update(residue={"layers": 0, "rules": 0, "holders": 0},
                      actions=[{"name": n, "t": t, **({"dropped": True} if n == spec.drop and mutate != "drop-flag-del" else {})}
                               for t, n in acts])
    if hiding:
        cast = []
        for n, t in enumerate(np.arange(INSERT_MS, INSERT_MS + DURATION_MS, 32.0)):
            e = probe.ease_in_out((t - INSERT_MS) / DURATION_MS)
            images[f"cast-{n:03d}"] = np.zeros((vh, vw, 4), np.uint8) if dark_at(t, t) else mix(with_holder, B_d, e)
            cast.append({"name": f"cast-{n:03d}", "t": float(t)})
        after = [c for c in cast if c["t"] > when["show"] + 20]
        if mutate == "cast-dup":
            images[after[3]["name"]] = images[after[2]["name"]].copy()
        elif mutate == "cast-shift":
            after[3]["t"] += 40.0
        elif mutate == "cast-few":
            cast = [c for c in cast if c["t"] <= when["show"] + 20 or c in after[:4]]
        elif mutate == "cast-shift64":
            for c in after:
                c["t"] += 64.0
        elif mutate == "hide-after-del":
            cast = [c for c in cast if c not in after]
        elif mutate == "hide-inside-del":
            cast = [c for c in cast if not when["hide"] <= c["t"] <= when["show"]]
        record["cast"] = cast
    if mutate and mutate.startswith("placement-"):
        record["placement"] = {"placement-invalid": "invalid", "placement-snap": "snap", "placement-absent": None}[mutate]
    elif mutate == "reason-other":
        record["output"]["placement"]["reason"] = "unqualified-version"
    elif mutate == "grant-null":
        record["output"]["placement"]["grant"] = None
    elif mutate == "reload-snap":
        record["reload"]["before"] = "snap"
    elif mutate == "show-allowed":
        record["showRefused"] = False
    if mutate == "digest":
        record["output"]["mmOpacity"]["sha256"] = "0" * 64
    elif mutate == "texture-ids":
        record["dump"]["first"]["textures"] = ["OUT", "IN"]
    elif mutate == "no-reference":
        record["dump"]["vids"][0]["rv"] = []
    elif mutate == "no-holder-png":
        images.pop("holder-0", None)
    elif mutate == "requested-41":
        record["paused"]["frame"] = REFERENCE - 1
    elif mutate == "no-hashes":
        for d in (record, record["target"]):
            d.pop("hashBefore"), d.pop("hashAfter")
    elif mutate == "stale-take":
        record["dump"]["takes"] = [[10.0, 22.0]]
    elif mutate == "tone-covered":
        images["fg-0-1"] = np.full((360, 640, 4), 255, np.uint8)
        record["foreground"]["0"].append({"id": "FRAME", "rect": [0.0, 0.0, 640.0, 360.0], "alpha": 1.0, "order": 9, "image": "fg-0-1"})
    elif mutate == "dup-rv":
        record["dump"]["vids"][0]["rv"].append(record["dump"]["vids"][0]["rv"][0])
    elif mutate == "holder-rect-missing":
        del record["dump"]["first"]["holders"][0]["rect"]
    elif mutate == "raf-eff-empty":
        record["dump"]["raf"][20]["eff"] = []
    elif mutate == "detach-zero":
        record["dump"]["vids"][0]["detach"] = 0.0
    elif mutate == "takes-dup":
        record["dump"]["takes"] = record["dump"]["takes"] * 2
    elif mutate == "shot-time-zero":
        record["shots"][5]["t0"] = 0.0
    elif mutate == "live-empty":
        images["live-0"] = images["live-0"][:0]
    elif mutate == "holders-key-missing":
        del record["dump"]["first"]["holders"]
    elif mutate == "anims-key-missing":
        del record["dump"]["raf"][7]["anims"]
    elif mutate == "no-videos":
        for r in record["dump"]["raf"]:
            if "eff" in r:
                del r["videos"]
    elif mutate == "tuple-malformed":
        record["dump"]["vids"][0]["tuple"] = "malformed"
    elif mutate == "tone-no-fg":
        del record["foreground"]
    elif mutate == "three-mid":
        keep = {"shot-000", "shot-001", "shot-002", "shot-007", "shot-009", "shot-011", "shot-017", "shot-018", "shot-019"}
        record["shots"] = [s for s in record["shots"] if s["name"] in keep]
    elif mutate == "action-early":
        record["actions"][0]["t"] = -1_000_000.0
    elif mutate == "no-layer-ids":
        del record["dump"]["first"]["layerIds"]
    elif mutate == "layer-ids-dup":
        record["dump"]["first"]["layerIds"] = ["layer1", "layer1"]
    elif mutate and mutate.startswith("ov-"):
        record["dump"]["vids"].append(
            {"id": 1, "rv": [], "rvAt": [], "freezeDraws": [], "detach": None, "tuple": None}
        )
        video = {"id": 1, "on": True, "rect": list(CONTENT), "eff": 1.0, "inT": False, "inStage": False, "paused": False, "geo": None}
        if mutate == "ov-on-del":
            del video["on"]
        elif mutate == "ov-on-none":
            video["on"] = None
        elif mutate == "ov-rect-nan":
            video["rect"][0] = math.nan
        elif mutate == "ov-eff-negative":
            video["eff"] = -1.0
        elif mutate == "ov-width-negative":
            video["rect"][2] = -480.0
        record["dump"]["raf"][20]["videos"].append(video)
    elif mutate == "dest-video":
        record["dump"]["vids"].append(
            {"id": 9, "rv": [], "rvAt": [], "freezeDraws": [], "detach": None, "tuple": None}
        )
        for r in record["dump"]["raf"]:
            if r["t"] >= INSERT_MS + DURATION_MS:
                r["videos"].append({"id": 9, "on": True, "rect": [500.0, 0.0, 140.0, 360.0], "eff": 1.0, "inT": False, "inStage": True,
                                    "paused": False, "geo": None})
    elif mutate == "anim-state-empty":
        for a in record["dump"]["raf"][-20]["anims"]:
            a.update(state="", ct=math.nan)
    elif mutate == "keep-life":
        keep = {"shot-000", "shot-001", "shot-002", "shot-010", "shot-017", "shot-018", "shot-019"}
        record["shots"] = [s for s in record["shots"] if s["name"] in keep]
    elif mutate in ("tone-rv-del", "tone-tuple-del", "tone-fg-del"):
        if mutate == "tone-rv-del":
            del record["dump"]["vids"][0]["rv"]
        elif mutate == "tone-tuple-del":
            del record["dump"]["vids"][0]["tuple"]
        else:
            del record["foreground"]
    elif mutate == "eff-hole":
        del record["dump"]["raf"][20]["eff"]
    elif mutate == "take-negative":
        record["dump"]["takes"] = [[INSERT_MS - 1.0, -42.0]]
    elif mutate == "no-action":
        record["actions"] = []
    elif mutate == "dsf-mismatch":
        record["dsf"] = 1.0
    elif mutate == "viewport-mismatch":
        record["viewport"] = [W, H]
    elif mutate == "dsf-missing":
        del record["dsf"]
    elif mutate == "tex-zero":
        images["tex-in"], images["tex-out"] = np.zeros_like(B), np.zeros_like(A)
    elif mutate == "tex-in-short":
        images["tex-in"] = B[:-1].copy()
    elif mutate == "tex-in-opaque":
        images["tex-in"] = B.copy()
        images["tex-in"][..., 3] = 255
    elif mutate == "no-decoder-evidence":
        record["dump"]["vids"][0].update(rv=[], tuple=None)
    elif mutate == "no-media-inventory":
        record["dump"]["vids"] = []
        for r in record["dump"]["raf"]:
            r["videos"] = []
    return record, images


def scored(arm: str, identity: bool | None = None, lut: np.ndarray | None = IDENTITY_LUT, spec: Any = None,
           **kwargs: Any) -> dict[str, Any]:
    """`score_arm` on a synthetic run and, for an arm with a twin, its same-frame twin (sharing only `SHARED_MUTATIONS`)."""
    spec = spec or probe.ARMS[arm]
    record, images = media_run(arm, **kwargs)
    twin = None
    if spec.twin:
        shared = {**kwargs, "mutate": kwargs.get("mutate") if kwargs.get("mutate") in SHARED_MUTATIONS else None}
        twin = media_run(spec.twin, **shared)
    return probe.score_arm(record, images, spec, CAL, identity=identity, twin=twin, lut=lut)


def arm_check(arm: str, check: str, identity: bool | None = None, **kwargs: Any) -> str:
    return scored(arm, identity, **kwargs)["checks"][check]["verdict"]


def arm_outcome(arm: str, **kwargs: Any) -> str:
    return scored(arm, **kwargs)["outcome"]


def hide_check(arm: str, check: str, **kwargs: Any) -> str:
    record, images = media_run(arm, holder=probe.ARMS[arm].mode == "on", **kwargs)
    return probe.score_hide_capture(record, images, probe.ARMS[arm], CAL)["checks"][check]["verdict"]


def lifecycle(row: str, twin: str = "ok", **kwargs: Any) -> str:
    record, images = media_run(f"life-{row}", **kwargs)
    if twin == "errored":
        twin_run = ({"error": "Traceback\nboom"}, {"settled": images["settled"]})
    else:
        twin_run = media_run(f"life-{row}-twin", holder=False)
    return probe.score_lifecycle(record, images, twin_run, probe.ARMS[f"life-{row}"], CAL)["outcome"]


def terminal_hash() -> str | None:
    docs = {"assets/header.json": {"slideList": ["a", "b"], "loopSlideshow": 0}}
    leaves = {"layers": [{"layers": [{"texture": "IN"}, {"texture": "OUT"}]}]}
    for uuid in ("a", "b"):
        events = [{"automaticPlay": True, "effects": [{"type": "buildIn", "name": "apple:movie-start"}]},
                  {"automaticPlay": False, "effects": [{"type": "transition", "duration": 1.5,
                                                        "name": "apple:dissolve" if uuid == "b" else "apple:magic-move-implied-motion-path",
                                                        "baseLayer": leaves}]}]
        docs[f"assets/{uuid}/{uuid}.json"] = {"events": events}
    return probe.find_target(docs.__getitem__, 2)["hashAfter"]


def eager_movies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bool:
    """Movie metadata (the tone layout) is in the resolver's fields before any capture requests a movie; a movie the counter
    fixture never replaced (P2's second `.mp4`) is served as exported, not parsed as a counter."""
    root = tmp_path / "deck"
    (root / "assets/a/assets").mkdir(parents=True)
    (root / "assets/player").mkdir(parents=True)
    header = {"slideList": ["a"], "loopSlideshow": 0, "slideWidth": 1920, "slideHeight": 1080}
    (root / "assets/header.json").write_text(probe.json.dumps(header))
    events = [{"automaticPlay": False, "effects": [{"type": "transition", "name": "apple:dissolve", "duration": 1.5,
                                                    "baseLayer": {"layers": [{"layers": [{"texture": "IN"}, {"texture": "OUT"}]}]}}]}]
    (root / "assets/a/a.json").write_text(probe.json.dumps({"events": events}))
    (root / "assets/a/assets/Untitled.mov-0.0000-46.0333.mov").write_bytes(b"movie")
    (root / "assets/a/assets/VID-20250608-WA0125.mp4-0.0000-45.1381.mp4").write_bytes(b"other movie")
    (root / "assets/player/main.js").write_bytes(b"player")
    monkeypatch.setitem(probe.DECKS, "syn", probe.Deck(root))
    monkeypatch.setattr(probe, "served_player", lambda *a, **k: b"served")
    monkeypatch.setattr(probe, "scratch_movie", lambda scratch, kind, encoding, seconds: {
        "path": str(root / "assets/a/assets/Untitled.mov-0.0000-46.0333.mov"), "layout": probe.tone_layout()})
    arm = probe.replace(probe.ARMS["m-tone"], deck="syn", slide=1, strip=False)
    fields = probe.resolve(arm, tmp_path / "scratch").fields()
    return (bool(fields["movies"]) and all(m.get("layout") for m in fields["movies"].values())
            and not any(k.endswith(".mp4") for k in fields["movies"]))


def perfect_round(profile: Any = None) -> dict[str, dict[str, Any]]:
    profile = profile or probe.DX1
    return {name: {"outcome": "MATCH", "checks": {c: {"verdict": v} for c, v in profile.arm(name).expect.items()}}
            for name in profile.required(False)}


def round_gate(mutate: tuple[str, str, str] | None, gate: str, *, only_controls: bool = False, profile: Any = None,
               cvc: str | None = "PASS") -> str:
    profile = profile or probe.DX1
    scored = perfect_round(profile)
    if only_controls:
        names = {n for pair in probe.CONTROLS.values() for side in pair for n in side}
        scored = {n: s for n, s in scored.items() if n in names}
    if mutate:
        name, check, verdict = mutate
        if check == "problems":
            scored[name]["problems"] = [verdict]
        elif check == "outcome":
            scored[name]["outcome"] = verdict
        else:
            scored[name]["checks"][check] = {"verdict": verdict}
    out = probe.score_round(scored, CAL, identity=False, extra={"cvc": {"verdict": cvc}} if cvc else {}, profile=profile)
    return out["overall"] if gate == "overall" else out["gates"][gate]["verdict"]


def delay_one() -> str:
    record, images = media_run("life-automatic", mutate="delay-42")
    record["shots"] = [s for s in record["shots"] if not (120 < s["t0"] and s["t1"] < 596)]
    twin = media_run("life-automatic-twin", holder=False)
    out = probe.score_lifecycle(record, images, twin, probe.ARMS["life-automatic"], CAL)
    return out["checks"]["frozen_delay"]["verdict"]


def interrupted(row: str) -> str:
    """Two mid frames before the action, the transition DOM gone right after it, in run and twin."""
    record, images = media_run(f"life-{row}")
    twin = media_run(f"life-{row}-twin", holder=False)
    keep = {"shot-000", "shot-001", "shot-002", "shot-005", "shot-006", "shot-017", "shot-018", "shot-019"}
    record["shots"] = [s for s in record["shots"] if s["name"] in keep]
    cut_at = record["actions"][0]["t"] + 12
    for rec in (record, twin[0]):
        for r in rec["dump"]["raf"]:
            if r["t"] >= cut_at:
                r.pop("eff", None), r.pop("anims", None)
    return probe.score_lifecycle(record, images, twin, probe.ARMS[f"life-{row}"], CAL)["outcome"]


def tone_identity(mutate: str | None) -> str:
    return scored("m-tone", True, spec=probe.DX1.arm("m-tone", True), mutate=mutate)["outcome"]


def cef_outcome(**kwargs: Any) -> str:
    record, images = media_run("on", **kwargs)
    return probe.score_arm(record, images, probe.CEF.arm("on"), CAL, profile=probe.CEF)["outcome"]


def w3_evidence() -> list[str]:
    import managed_obs_qualify as q

    record = {"output": {"continuity": {"mode": "qualified", "glReplay": {"mode": "injected"}}, "mmOpacity": {"sha256": "a" * 64}},
              "dump": {"vids": [{"src": "x.mov", "rv": [[1.0, 0.0, 1]], "tuple": None, "err": "VideoFrame failed"}]}}
    return q.dissolve_evidence(record)


def w3_calibration() -> bool:
    import managed_obs_qualify as q

    run = {"sessions": [{"session": "opaque-off", "calibration": {"n": None, "model": "INCONCLUSIVE",
                                                                  "calibration": {"tau": 4.0, "complement": 2.0, "no_dip": 252.0}}}]}
    checks = q.dissolve_gates(run, None)["DX-2"]["checks"]
    return next(c for c in checks if c["check"] == "calibration (opaque-off n)")["ok"]


def w3_cast() -> list[str]:
    import inspect

    import managed_obs_qualify as q

    source = inspect.getsource(q.dissolve_session)
    return [k for k in ('"t0": s["t0"]', '"t1": s["t1"]') if k in source]


def profile_headless(profile: Any) -> bool:
    record, images = media_run("m-on")
    record.pop("load"), record.pop("headlessBefore")
    return any("headless" in p for p in probe.capture_problems(record, images, probe.ARMS["m-on"], profile))


def same_colour(kind: str) -> str:
    """No dip on the both-opaque class where A and B have identical colours (rev 9's colour filter left it empty)."""
    A, B = textures()
    B[:, 500:520, :3] = A[:, 500:520, :3]
    out = probe.score_fade([mix(A, B, e, kind) for e in ES], A, B, classes=("overlap",), cal=CAL)
    return "INCONCLUSIVE" if out["problems"] else ("PASS" if out["checks"]["no_dip"] else "FAIL")


def device_strip() -> int | None:
    """The strip read from a 480x135 device-scale holder (content box at its origin, scale 480 / 1920)."""
    holder_px = probe.place(strip_frame(REFERENCE), CONTENT, CONTENT, (H, W))[10:145, 10:490]
    return probe.holder_strip(holder_px, {"canvasRect": CONTENT, "rect": CONTENT},
                              {"content": CONTENT, "size": [binary.WIDTH, binary.HEIGHT]}, 1.0)


def negative_strip_problems() -> list[list[str]]:
    problems = []
    for arm in ("m-snap-cef-nooffset-x", "m-snap-cef-nooffset-x-twin"):
        record, images = media_run(arm, mutate="holder-shift-undecodable")
        problems.append(probe.media_integrity(record, images, probe.ARMS[arm], [])[2])
    return problems


def near_clip_geometry() -> list[tuple[tuple[float, ...], float, float]]:
    root = probe.DECKS["p2bin"].unmodified
    header = probe.read_doc(root / "assets/header.json")
    source = probe.read_doc(root / probe.slide_doc_path(header["slideList"][1]))
    result = []
    for axis in ("x", "y"):
        doc = probe.json.loads(probe.json.dumps(source))
        before = [(n, p) for b in probe._effects(doc["events"]) for n, p in probe._layers(b["baseLayer"])
                  if n.get("isVideoLayer")][0]
        video_node0, parent_node0 = before
        video0, parent0 = video_node0["initialState"], parent_node0["initialState"]
        size, coord = ("width", "pointX") if axis == "x" else ("height", "pointY")
        old_parent_near = parent0["position"][coord] - parent0["anchorPoint"][coord] * parent0[size]
        old_child_nears = [old_parent_near + child["initialState"]["position"][coord]
                           - child["initialState"]["anchorPoint"][coord] * child["initialState"][size]
                           for child in parent_node0["layers"]]
        old_content_near = old_parent_near + video0["position"][coord] - video0["anchorPoint"][coord] * video0[size]
        old_far = old_parent_near + parent0[size]
        intended_near = old_content_near + 0.4 * video0[size] + 0.37
        probe._clip_near(axis)(doc, probe.transition_event(doc))
        video_node, parent_node = [(n, p) for b in probe._effects(doc["events"])
                                   for n, p in probe._layers(b["baseLayer"]) if n.get("isVideoLayer")][0]
        video, parent = video_node["initialState"], parent_node["initialState"]
        parent_near = parent["position"][coord] - parent["anchorPoint"][coord] * parent[size]
        child_nears = [parent_near + child["initialState"]["position"][coord]
                       - child["initialState"]["anchorPoint"][coord] * child["initialState"][size]
                       for child in parent_node["layers"]]
        result.append((tuple(round(after - before, 9) for before, after in zip(old_child_nears, child_nears)),
                       round(parent_near - intended_near, 9), round(parent_near + parent[size] - old_far, 9)))
    return result


def near_clip_rejections() -> tuple[str, str, str]:
    root = probe.DECKS["p2bin"].unmodified
    header = probe.read_doc(root / "assets/header.json")
    source = probe.read_doc(root / probe.slide_doc_path(header["slideList"][1]))
    results = []
    for mutation in ({"boundsOrigin": {"pointX": 1, "pointY": 0}}, {"affineTransform": [1, 0, 0, 1, 1, 0]},
                     {"sublayerTransform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 1]}):
        doc = probe.json.loads(probe.json.dumps(source))
        _, parent = [(n, p) for b in probe._effects(doc["events"]) for n, p in probe._layers(b["baseLayer"])
                     if n.get("isVideoLayer")][0]
        parent["initialState"].update(mutation)
        with pytest.raises(ValueError) as caught:
            probe._clip_near("x")(doc, probe.transition_event(doc))
        results.append(str(caught.value))
    return tuple(results)


def nooffset_real_geometry(axis: str) -> tuple[Any, ...]:
    root = probe.DECKS["p2bin"].unmodified
    header = probe.read_doc(root / "assets/header.json")
    doc = probe.read_doc(root / probe.slide_doc_path(header["slideList"][1]))
    event_index = probe.transition_event(doc)
    override = probe._nooffset_x if axis == "x" else probe._nooffset_y
    override(doc, event_index)
    video_node, parent_node = [(n, p) for b in probe._effects(doc["events"])
                               for n, p in probe._layers(b["baseLayer"]) if n.get("isVideoLayer")][0]
    video, parent = video_node["initialState"], parent_node["initialState"]
    parent_left = parent["position"]["pointX"] - parent["anchorPoint"]["pointX"] * parent["width"]
    parent_top = parent["position"]["pointY"] - parent["anchorPoint"]["pointY"] * parent["height"]
    video_left = parent_left + video["position"]["pointX"] - video["anchorPoint"]["pointX"] * video["width"]
    video_top = parent_top + video["position"]["pointY"] - video["anchorPoint"]["pointY"] * video["height"]
    visible = [max(parent_left, video_left), max(parent_top, video_top),
               min(parent_left + parent["width"], video_left + video["width"]),
               min(parent_top + parent["height"], video_top + video["height"])]
    visible = [visible[0], visible[1], visible[2] - visible[0], visible[3] - visible[1]]
    strip_far = ((video_left + binary.STRIP_RECT[2] * video["width"] / binary.WIDTH) if axis == "x"
                 else (video_top + binary.STRIP_RECT[3] * video["width"] / binary.WIDTH))

    def texture_rects(node: dict[str, Any], left: float = 0.0, top: float = 0.0) -> list[tuple[str, list[float]]]:
        state = node["initialState"]
        x = left + state["position"]["pointX"] - state["anchorPoint"]["pointX"] * state["width"]
        y = top + state["position"]["pointY"] - state["anchorPoint"]["pointY"] * state["height"]
        found = [(node["texture"], [x, y, state["width"], state["height"]])] if node.get("texture") else []
        return found + [item for child in node.get("layers") or [] for item in texture_rects(child, x, y)]

    later = [item for event in doc["events"][:event_index] for effect in event.get("effects") or []
             for item in texture_rects(effect["baseLayer"])]
    displacement = video_left if axis == "x" else video_top
    content = [video_left, video_top, video["width"], video["height"]]
    shifted = list(content)
    target = list(visible)
    index = 0 if axis == "x" else 1
    shifted[index] -= displacement
    target[index] -= displacement
    overlap = [max(visible[0], shifted[0], target[0]), max(visible[1], shifted[1], target[1]),
               min(visible[0] + visible[2], shifted[0] + shifted[2], target[0] + target[2]),
               min(visible[1] + visible[3], shifted[1] + shifted[3], target[1] + target[3])]
    overlap_size = [overlap[2] - overlap[0], overlap[3] - overlap[1]]
    names = (f"m-snap-cef-nooffset-{axis}", f"m-snap-cef-nooffset-{axis}-twin")
    size = video["width"] if axis == "x" else video["height"]
    displacement_constant = probe.NOOFFSET_X_DISPLACEMENT if axis == "x" else probe.NOOFFSET_Y_DISPLACEMENT
    near = video_left if axis == "x" else video_top
    visible_near = visible[index]
    u0, v0 = probe.jround(video_left), probe.jround(video_top)
    a0, b0 = probe.jround(visible[0]), probe.jround(visible[1])
    a1, b1 = probe.jround(visible[0] + visible[2]), probe.jround(visible[1] + visible[3])
    ww, hh = round(a1 - a0), round(b1 - b0)
    dx, dy = u0 - a0, v0 - b0
    fx = dx - u0 if axis == "x" else dx + video_left - u0
    fy = dy - v0 if axis == "y" else dy + video_top - v0
    fw, fh = round(video["width"]), round(video["height"])
    containment_guard = fx > 0.5 or fy > 0.5 or fx + fw < ww - 0.5 or fy + fh < hh - 0.5
    return (round(near, 6), size, abs(displacement_constant) < size,
            tuple(round(value, 6) for value in visible),
            tuple((texture, tuple(round(value, 6) for value in rect)) for texture, rect in later),
            not any(probe.overlaps(visible, rect) for _, rect in later), round(strip_far, 6),
            strip_far <= visible_near, tuple(round(value, 6) for value in overlap_size),
            all(value > 0 for value in overlap_size), parent["masksToBounds"],
            tuple(probe.ARMS[name].overrides for name in names),
            (round(fx, 6), round(fy, 6), fw, fh, ww, hh, containment_guard))


def nooffset_y_outcomes() -> tuple[str, str, str, str, str]:
    arm = probe.ARMS["m-snap-cef-nooffset-y"]
    twin = media_run(arm.twin)
    correct = probe.score_arm(*media_run("m-snap-cef-nooffset-y"), arm,
                              CAL, profile=probe.CEF_PLACEMENT, twin=twin, lut=IDENTITY_LUT)
    defective_twin = media_run(arm.twin, mutate="holder-y-nooffset")
    defective = probe.score_arm(*media_run("m-snap-cef-nooffset-y", mutate="holder-y-nooffset"), arm,
                                CAL, profile=probe.CEF_PLACEMENT, twin=defective_twin, lut=IDENTITY_LUT)
    return (correct["checks"]["holder_pixels"]["verdict"],
            correct["checks"]["holder_pixels"]["detail"]["attribution"]["verdict"], correct["outcome"],
            defective["checks"]["holder_pixels"]["verdict"], defective["outcome"])


def dsk_counter_resolver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    copied = []

    def fake_h264(_scratch: Path, source: Path) -> dict[str, Any]:
        copied.append(source)
        return {"path": str(source), "sha256": probe.binary.sha256_file(source), "kind": "h264"}

    monkeypatch.setattr(probe, "h264_copy", fake_h264)
    arm = probe.ARMS["m-snap-cef-dsk"]
    resolved = probe.resolve(arm, tmp_path / "dsk")
    counters = {path: info for path, info in resolved.movies.items() if "seekOffsetS" in info}
    paths = {info["path"] for info in counters.values()}
    digests = {info["sha256"] for info in counters.values()}
    doc = probe.read_doc(resolved.resolver(resolved.root, probe.slide_doc_path(resolved.target["uuid"])))
    assets = {Path(path).stem: info for path, info in probe.DSK_COUNTER_OFFSETS.items()}
    urls = tuple(doc["assets"][asset]["url"]["native"] for asset in sorted(assets))
    starts = tuple(sorted(float(build["movie"]["startTime"]) for build in probe._effects(doc["events"])))
    aliases = tuple(sorted(Path(path).name for path in counters))
    player = (resolved.root / "assets/player/main.js").read_bytes()
    return (len(counters), len(paths), starts, urls, aliases, digests.pop(),
            bool(copied) and all(resolved.target["uuid"] not in path.parts for path in copied),
            tuple(player.count(anchor) for anchor, _ in probe.DSK_PLAYER_SRC_ANCHORS),
            {info["fps"] for info in counters.values()}, probe.dsk_counter_fps())


def dsk_holder_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    monkeypatch.setattr(probe, "h264_copy", lambda _scratch, source: {
        "path": str(source), "sha256": probe.binary.sha256_file(source), "kind": "h264"
    })
    resolved = probe.resolve(probe.ARMS["m-snap-cef-dsk"], tmp_path / "dsk-identity")
    doc = probe.read_doc(resolved.resolver(resolved.root, probe.slide_doc_path(resolved.target["uuid"])))
    urls = [doc["assets"][Path(name).stem]["url"]["native"] for name in probe.DSK_COUNTER_OFFSETS]
    offsets = [float(url.rsplit("#t=", 1)[1]) if "#t=" in url else 0.0 for url in urls]
    sources = [url.rsplit("/", 1)[-1] for url in urls]
    counter_fps = probe.dsk_counter_fps()
    assert counter_fps is not None
    record, images = media_run("m-snap-cef-dsk")
    first = record["dump"]["first"]
    first["holders"][0]["parent"] = "layer4-opacity"
    second_rect = [150.0, 180.0, 480.0, 135.0]
    first["holders"].append({"parent": "layer4-opacity", "rect": second_rect, "canvasRect": second_rect, "natural": [480, 135]})
    second_frame = REFERENCE + round((offsets[1] - offsets[0]) * counter_fps)
    images["holder-1"] = probe.place(strip_frame(second_frame), CONTENT, CONTENT, (H, W))[10:145, 10:490].copy()
    decoder = record["dump"]["vids"][0]
    decoder["src"] = sources[0]
    shifted = [[presentation, media + offsets[1] - offsets[0], presented, expected]
               for presentation, media, presented, expected in decoder["rv"]]
    second = {**decoder, "id": 1, "src": sources[1], "content": second_rect, "region": second_rect,
              "rv": [[shifted[0][0] - 33.0, 0.0, 0, shifted[0][3] - 33.0], *shifted],
              "rvAt": [decoder["rvAt"][0] - 33.0, *decoder["rvAt"]],
              "freezeDraws": [{**draw,
                               "beforeTimestampUs": draw["beforeTimestampUs"] + (offsets[1] - offsets[0]) * 1_000_000,
                               "afterTimestampUs": draw["afterTimestampUs"] + (offsets[1] - offsets[0]) * 1_000_000}
                              for draw in decoder["freezeDraws"]]}
    record["dump"]["vids"].append(second)
    record["dump"]["vids"].extend({**decoder, "id": decoder_id, "src": "prior.mov"}
                                         for decoder_id in range(2, 13))
    for row in record["dump"]["raf"]:
        if "eff" not in row:
            row["videos"].append({"id": 1, "on": True, "rect": second_rect, "eff": 1.0, "inT": False,
                                  "inStage": True, "paused": False,
                                  "geo": {"content": second_rect, "region": second_rect,
                                          "size": [binary.WIDTH, binary.HEIGHT]}})
    record["foreground"]["1"] = []
    probe.record_dsk_counter_timing(record, probe.ARMS["m-snap-cef-dsk"])
    recorded_ids = [row["id"] for row in record["dskCounterTiming"]["decoders"]]
    recorded_times = [row["firstMediaTimeS"] for row in record["dskCounterTiming"]["decoders"]]
    good = probe.media_integrity(record, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    reordered = probe.json.loads(probe.json.dumps(record))
    reordered["dskCounterTiming"]["decoders"].reverse()
    reordered_good = probe.media_integrity(reordered, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    no_timing = probe.json.loads(probe.json.dumps(record))
    no_timing.pop("dskCounterTiming")
    missing = probe.media_integrity(no_timing, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    inert = probe.json.loads(probe.json.dumps(record))
    for rv in inert["dump"]["vids"][1]["rv"]:
        if rv[1]:
            rv[1] -= offsets[1] - offsets[0]
    probe.record_dsk_counter_timing(inert, probe.ARMS["m-snap-cef-dsk"])
    inert_problems = probe.media_integrity(inert, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    reversed_sources = probe.json.loads(probe.json.dumps(record))
    reversed_sources["dump"]["vids"][0]["src"], reversed_sources["dump"]["vids"][1]["src"] = sources[1], sources[0]
    probe.record_dsk_counter_timing(reversed_sources, probe.ARMS["m-snap-cef-dsk"])
    reversed_problems = probe.media_integrity(
        reversed_sources, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    spacing_tolerance = round(probe.DSK_COUNTER_TIME_TOLERANCE_S * counter_fps)
    allowed_gap_record = probe.json.loads(probe.json.dumps(record))
    for draw in allowed_gap_record["dump"]["vids"][1]["freezeDraws"]:
        draw["beforeTimestampUs"] += spacing_tolerance / counter_fps * 1_000_000
        draw["afterTimestampUs"] += spacing_tolerance / counter_fps * 1_000_000
    probe.record_dsk_counter_timing(allowed_gap_record, probe.ARMS["m-snap-cef-dsk"])
    allowed_gap_images = {**images, "holder-1": probe.place(
        strip_frame(second_frame + spacing_tolerance), CONTENT, CONTENT, (H, W)
    )[10:145, 10:490].copy()}
    allowed_gap = probe.media_integrity(
        allowed_gap_record, allowed_gap_images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    wrong_gap_record = probe.json.loads(probe.json.dumps(record))
    for draw in wrong_gap_record["dump"]["vids"][1]["freezeDraws"]:
        draw["beforeTimestampUs"] += (spacing_tolerance + 1) / counter_fps * 1_000_000
        draw["afterTimestampUs"] += (spacing_tolerance + 1) / counter_fps * 1_000_000
    probe.record_dsk_counter_timing(wrong_gap_record, probe.ARMS["m-snap-cef-dsk"])
    wrong_gap_images = {**images, "holder-1": probe.place(
        strip_frame(second_frame + spacing_tolerance + 1), CONTENT, CONTENT, (H, W)
    )[10:145, 10:490].copy()}
    wrong_gap = probe.media_integrity(
        wrong_gap_record, wrong_gap_images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    wrong_gap_problem = next((problem for problem in wrong_gap if "#t=5 holder frame" in problem), "")
    first_rvfc_times = [probe._dsk_first_rvfc_times(decoder) for decoder in record["dump"]["vids"][:2]]
    diagnostic = probe.json.loads(probe.json.dumps(record))
    diagnostic["dump"]["vids"][0]["rv"][-1][3] += 1000
    diagnostic["dump"]["vids"][0]["rvAt"][-1] += 2000
    probe.record_dsk_counter_timing(diagnostic, probe.ARMS["m-snap-cef-dsk"])
    diagnostic_problems = probe.media_integrity(
        diagnostic, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    changed = probe.json.loads(probe.json.dumps(record))
    changed["dump"]["vids"][0]["freezeDraws"][0]["afterTimestampUs"] += 1
    probe.record_dsk_counter_timing(changed, probe.ARMS["m-snap-cef-dsk"])
    changed_problems = probe.media_integrity(changed, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    frame_us = 1_000_000 / counter_fps
    disagree = probe.json.loads(probe.json.dumps(record))
    disagree["dump"]["vids"][0]["freezeDraws"][1]["beforeTimestampUs"] += frame_us
    disagree["dump"]["vids"][0]["freezeDraws"][1]["afterTimestampUs"] += frame_us
    probe.record_dsk_counter_timing(disagree, probe.ARMS["m-snap-cef-dsk"])
    disagree_problems = probe.media_integrity(
        disagree, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    repaired = probe.json.loads(probe.json.dumps(record))
    for repaired_decoder in repaired["dump"]["vids"][:2]:
        repair = dict(repaired_decoder["freezeDraws"][-1])
        repair.update(argumentCount=9, startedAt=INSERT_MS - 0.7, finishedAt=INSERT_MS - 0.69,
                      beforeTimestampUs=repair["beforeTimestampUs"] + frame_us,
                      afterTimestampUs=repair["afterTimestampUs"] + frame_us)
        repaired_decoder["freezeDraws"].append(repair)
    probe.record_dsk_counter_timing(repaired, probe.ARMS["m-snap-cef-dsk"])
    repaired_problems = probe.media_integrity(
        repaired, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    repair_diagnostics = [row["freezeDraw"]["diagnostics"] for row in repaired["dskCounterTiming"]["decoders"]]
    bad_repair = probe.json.loads(probe.json.dumps(repaired))
    for repaired_decoder in bad_repair["dump"]["vids"][:2]:
        repaired_decoder["freezeDraws"][-1]["beforeTimestampUs"] += frame_us
        repaired_decoder["freezeDraws"][-1]["afterTimestampUs"] += frame_us
    probe.record_dsk_counter_timing(bad_repair, probe.ARMS["m-snap-cef-dsk"])
    bad_repair_problems = probe.media_integrity(
        bad_repair, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    outside_window = probe.json.loads(probe.json.dumps(record))
    for outside_decoder in outside_window["dump"]["vids"][:2]:
        outside_decoder["freezeDraws"].append({
            **outside_decoder["freezeDraws"][0], "startedAt": record["advanceAt"] - 0.1,
            "finishedAt": record["advanceAt"] - 0.09, "beforeTimestampUs": 0, "afterTimestampUs": frame_us * 99,
        })
    probe.record_dsk_counter_timing(outside_window, probe.ARMS["m-snap-cef-dsk"])
    outside_problems = probe.media_integrity(
        outside_window, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    missing_expected = probe.json.loads(probe.json.dumps(record))
    missing_expected["dump"]["vids"][0]["rv"] = []
    missing_expected["dump"]["vids"][0]["rvAt"] = []
    probe.record_dsk_counter_timing(missing_expected, probe.ARMS["m-snap-cef-dsk"])
    missing_expected_problems = probe.media_integrity(
        missing_expected, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    missing_draw = probe.json.loads(probe.json.dumps(record))
    missing_draw["dump"]["vids"][0]["freezeDraws"] = []
    probe.record_dsk_counter_timing(missing_draw, probe.ARMS["m-snap-cef-dsk"])
    missing_draw_problems = probe.media_integrity(
        missing_draw, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7]
    )[2]
    images["holder-0"], images["holder-1"] = images["holder-1"], images["holder-0"]
    swapped = probe.media_integrity(record, images, probe.ARMS["m-snap-cef-dsk"], [0.1, 0.4, 0.7])[2]
    return (good, reordered_good, recorded_ids, round(recorded_times[1] - recorded_times[0], 6),
            record["dskCounterTiming"]["counterFps"], any("!= decoder" in problem for problem in swapped),
            any("draw-timestamp" in problem for problem in missing),
            inert_problems,
            any("#t=5 holder frame" in problem for problem in reversed_problems),
            spacing_tolerance,
            allowed_gap,
            bool(wrong_gap_problem),
            all(f"{label} {times}" in wrong_gap_problem
                for label, times in zip(("base", "#t=5"), first_rvfc_times)),
            diagnostic_problems, any("timestamp changed" in problem for problem in changed_problems),
            any("full-size freeze draws used different" in problem for problem in disagree_problems),
            missing_expected_problems,
            any("no VideoFrame timestamp" in problem for problem in missing_draw_problems),
            record["dskCounterTiming"]["takeMs"],
            all(row[3] >= row[0] for decoder in record["dump"]["vids"][:2] for row in decoder["rv"] if len(row) == 4),
            any(b[2] > a[2] + 1 for decoder in record["dump"]["vids"][:2]
                for a, b in zip(decoder["rv"], decoder["rv"][1:])),
            "callbackLatenessMs" not in probe.json.dumps(record["dskCounterTiming"]),
            repaired_problems, all(len(rows) == 1 for rows in repair_diagnostics),
            any("expected" in problem for problem in bad_repair_problems), outside_problems,
            "argumentCount: arguments.length" in probe.HOOK_JS)


def legacy_non_dsk_without_freeze_draws() -> tuple[bool, str]:
    record, images = media_run("m-on")
    record["dump"]["vids"][0].pop("freezeDraws")
    malformed = "decoder/rVFC records malformed" in probe.schema_problems(record)
    return not malformed, probe.score_arm(record, images, probe.ARMS["m-on"], CAL)["outcome"]


def near_clip_outcomes() -> list[tuple[str, str | None]]:
    outcomes = []
    for name in ("m-snap-cef-near-x", "m-snap-cef-near-y"):
        arm = probe.CEF_PLACEMENT.arm(name)
        scored_run = probe.score_arm(*media_run(name), arm, CAL, profile=probe.CEF_PLACEMENT,
                                     twin=media_run(arm.twin), lut=IDENTITY_LUT)
        outcomes.append((scored_run["outcome"], scored_run["checks"]["holder_pixels"]["detail"].get("strip")))
    return outcomes


def near_clip_fail_closed() -> tuple[str, bool, bool]:
    record, images = media_run("m-snap-cef-near-x")
    decoder_id = record["paused"]["id"]
    partial = [180.0, 10.0, 310.0, 135.0]
    holder = record["dump"]["first"]["holders"][0]
    holder.update(rect=partial, canvasRect=partial, natural=[310, 135])
    frame = probe.place(strip_frame(REFERENCE), CONTENT, CONTENT, (H, W))
    images["holder-0"] = frame[10:145, 180:490].copy()
    for row in record["dump"]["raf"]:
        for video in row.get("videos") or []:
            if video.get("id") == decoder_id and video.get("geo"):
                video["geo"]["region"] = partial
    geometry = probe.holder_strip_geometry(holder, probe.decoders_of(record)[-1])
    partial_problems = probe.media_integrity(record, images, probe.ARMS["m-snap-cef-near-x"], [])[2]
    record["paused"]["frame"] += 1
    stale_problems = probe.media_integrity(record, images, probe.ARMS["m-snap-cef-near-x"], [])[2]
    return geometry, any("strip does not decode" in problem for problem in partial_problems), any(
        "paused reference" in problem for problem in stale_problems)


def edge_fixture_layout() -> tuple[tuple[str, ...], int | None, dict[str, float | None], bool]:
    names = ("m-snap-cef", "m-snap-cef-twin", "wrongrule-cef", "wrongrule-cef-twin")
    root = probe.DECKS["p2bin"].unmodified
    header = probe.read_doc(root / "assets/header.json")
    doc = probe.read_doc(root / probe.slide_doc_path(header["slideList"][1]))
    probe._edge_foreground(doc, probe.transition_event(doc))
    video, parent = [(n, p) for b in probe._effects(doc["events"])
                     for n, p in probe._layers(b["baseLayer"]) if n.get("isVideoLayer")][0]
    state = parent["initialState"]
    parent_near = (state["position"]["pointX"] - state["anchorPoint"]["pointX"] * state["width"],
                   state["position"]["pointY"] - state["anchorPoint"]["pointY"] * state["height"])
    video_index = parent["layers"].index(video)
    children = parent["layers"][video_index + 1:]
    rects = []
    for child in children:
        state = child["initialState"]
        rects.append([parent_near[0] + state["position"]["pointX"] - state["anchorPoint"]["pointX"] * state["width"],
                      parent_near[1] + state["position"]["pointY"] - state["anchorPoint"]["pointY"] * state["height"],
                      state["width"], state["height"]])
    video_state = video["initialState"]
    x = parent_near[0] + video_state["position"]["pointX"] - video_state["anchorPoint"]["pointX"] * video_state["width"]
    y = parent_near[1] + video_state["position"]["pointY"] - video_state["anchorPoint"]["pointY"] * video_state["height"]
    box = (probe.jround(x), probe.jround(y), probe.jround(x) + round(video_state["width"]),
           probe.jround(y) + round(video_state["height"]))
    record, images = media_run("m-snap-cef")
    twin = media_run("m-snap-cef-twin")
    arm = probe.ARMS["m-snap-cef"]
    mask, problems = probe.verified_mask(record, images, arm, probe.CEF_PLACEMENT, CAL, twin)
    holder = record["dump"]["first"]["holders"][0]
    decoder = probe.decoders_of(record)[0]
    device = probe.device_box(holder["rect"], arm.dsf)
    split = probe.region_split(np.zeros(images["live-0"].shape[:2]), device, ~mask) if mask is not None and device else {}
    crosses = any(r[0] < x < r[0] + r[2] for r in rects)
    assert not problems
    assert all(child.get("texture") != probe.FOREGROUND_FRAME for child in children)
    return (tuple(probe.ARMS[name].overrides[0] for name in names),
            probe.holder_strip(images["holder-0"], holder, decoder, arm.dsf), split, crosses)


def displaced_attribution() -> tuple[str, str, str, str, str, tuple[int, int], tuple[str, str]]:
    rng = np.random.default_rng(17)
    live = rng.integers(0, 256, (20, 40, 4), dtype=np.uint8)
    live[..., 3] = 255
    shifted = np.zeros_like(live)
    shifted[..., 3] = 255
    shifted[:, :30, :3] = np.rint(0.63 * live[:, 5:35, :3] + 0.37 * live[:, 6:36, :3]).astype(np.uint8)
    mask = np.zeros(live.shape[:2], bool)
    holder = {"canvasRect": [0.0, 0.0, 30.0, 20.0]}
    decoder = {"rect": [5.37, 0.0, 30.0, 20.0], "content": [5.37, 0.0, 30.0, 20.0]}
    matched = probe.score_displaced_holder(shifted, live, holder, decoder, {"x": 0.0}, mask, IDENTITY_LUT, "x", 1.0)
    minus = probe.score_displaced_holder(shifted, live, holder, {**decoder, "rect": [3.37, 0.0, 30.0, 20.0]},
                                           {"x": 0.0}, mask, IDENTITY_LUT, "x", 1.0)
    plus = probe.score_displaced_holder(shifted, live, holder, {**decoder, "rect": [7.37, 0.0, 30.0, 20.0]},
                                          {"x": 0.0}, mask, IDENTITY_LUT, "x", 1.0)
    empty = probe.score_displaced_holder(shifted, live, {"canvasRect": [30.0, 0.0, 5.0, 20.0]},
                                          {**decoder, "rect": [30.37, 0.0, 30.0, 20.0],
                                           "content": [30.0, 0.0, 30.0, 20.0]},
                                          {"x": 0.0}, mask, IDENTITY_LUT, "x", 1.0)
    subpixel = probe.score_displaced_holder(shifted, live, holder, {**decoder, "rect": [0.5, 0.0, 30.0, 20.0]},
                                             {"x": 0.0}, mask, IDENTITY_LUT, "x", 1.0)
    twins = tuple(probe.ARMS[name].counter_strip for name in
                  ("m-snap-cef-nooffset-x-twin", "m-snap-cef-nooffset-y-twin"))
    return (matched["verdict"], minus["verdict"], plus["verdict"], empty["verdict"], subpixel["verdict"],
            tuple(matched["detail"]["sampleOffsetsPx"]), twins)


def cases(prefix: str, variants: tuple[str, ...]) -> dict[str, str]:
    table = probe.scorer_cases(CAL)
    return {v: table[f"case:{prefix}-{v}"]["verdict"] for v in variants}


def cef_outcome_of(arm: str, mutate: str | None = None, holder: bool = True) -> str:
    record, images = media_run(arm, mutate=mutate, holder=holder)
    return probe.score_arm(record, images, probe.CEF.arm(arm), CAL, profile=probe.CEF)["outcome"]


def launch_map(mutate: str | None, drop: bool = False) -> tuple[bool, float | None]:
    """`launch_lut` from this launch's m-tone session and twin: (found, the map at 128)."""
    runs = {} if drop else {"m-tone": media_run("m-tone", mutate=mutate), "m-tone-twin": media_run("m-tone-twin", mutate=mutate)}
    lut, _ = probe.launch_lut(runs, CAL)
    return lut is not None, None if lut is None else int(lut[128])


def cef_launch_map() -> tuple[bool, str | None]:
    runs = {name: media_run(name) for name in ("m-tone-cef", "m-tone-cef-twin")}
    lut, detail = probe.launch_lut(runs, CAL, profile=probe.CEF_PLACEMENT)
    return lut is not None, detail.get("source")


def stale_patch_blank_in() -> str:
    """Astra impl r3: F50/B are copies of A0 but for a 10x10 patch (red -10 / -20) where incoming = outgoing; the main
    incoming texture is blank."""
    record, images = media_run("m-snap", mutate="ref-stale-patch")
    images["tex-in"] = np.zeros_like(images["tex-in"])
    return probe.score_arm(record, images, probe.ARMS["m-snap"], CAL, twin=media_run("m-snap-twin"), lut=IDENTITY_LUT)["outcome"]


def snap_shift() -> list[int]:
    """The `snap-shift` anchor on the served `on` bytes of both supported players, and on their `fg-omit` twins."""
    counts = []
    for stock, (pin, _, _) in live_runtime.SUPPORTED_PLAYERS.items():
        player = next((f.read_bytes() for f in probe.FIXTURES.glob("**/assets/player/main.js") if probe.sha256_bytes(f.read_bytes()) == stock), None)
        if player is None:
            pytest.skip("supported player export not available")
        on, twin = probe.served_player(player, "on", "snap-shift"), probe.served_player(player, "on", "snap-shift+fg-omit")
        counts.append(on.count(b's.left=a0+1/p+"px"') + twin.count(b's.left=a0+"px"'))
    return counts


def frac_underlay_omit() -> list[int]:
    counts = []
    for stock in live_runtime.SUPPORTED_PLAYERS:
        player = next((f.read_bytes() for f in probe.FIXTURES.glob("**/assets/player/main.js")
                       if probe.sha256_bytes(f.read_bytes()) == stock), None)
        if player is None:
            pytest.skip("supported player export not available")
        served = probe.served_player(player, "on", "frac-underlay-omit")
        counts.append(served.count(b'g=x.getContext("2d");if("frac"===pl)'))
    return counts


def raw_navigate(ack: bool) -> tuple[str, int]:
    """`navigate` on a fake raw page (hash 4 idle, target 5): the hash stays stale for a while after Space (it is
    rewritten only at the next idle), so one press must wait for it to move instead of pressing again (the live
    overshoot); a press the player never takes is refused."""
    stale = [{"ready": True, "state": "IdleAtInitialState", "scene": 4}] * 4
    moved = [{"ready": True, "state": "IdleAtInitialState", "scene": 5}] if ack else []
    snaps = stale + moved

    class Page:
        keys = 0

        def evaluate(self, expression: str) -> Any:
            assert expression == host.snapshot_js
            return snaps.pop(0) if len(snaps) > 1 else snaps[0]

        def key(self, *_: Any) -> None:
            Page.keys += 1

    host = object.__new__(probe.RawHost)
    host.transport, host.snapshot_js = Page(), probe.raw_snapshot_js([6])
    wait, probe.ADVANCE_ACK_S = probe.ADVANCE_ACK_S, 0.3
    try:
        probe.navigate(host, 5, 10)
        return "reached", Page.keys
    except RuntimeError:
        return "refused", Page.keys
    finally:
        probe.ADVANCE_ACK_S = wait


def pre_start_gap(kind: str) -> list[str]:
    """`raf_problems` on a dissolve whose first transition frame lands 70 ms after insertion (CEF), animations pending
    (no start, ct 0) until t 70: allowed only when the record ending the gap holds the declared initial values (incoming
    0, outgoing 1) and the record starting it shows them too; `incoming` shows incoming 0.2 there, `start-dip` starts the
    gap on a record with the DOM present, no animations yet and outgoing 0.5, `after-start` moves the 70 ms gap past the
    start; `stock` is the mode-off player (only the outgoing leaf animates, incoming at 1 throughout)."""
    def rec(t: float, e: float, start: float | None) -> dict[str, Any]:
        ct = 0.0 if start is None else t - start
        return {"t": t, "eff": [e, 1 - e], "videos": [], "anims": [{"leaf": "in", "start": start, "ct": ct, "value": e, "state": "running"},
                                                                    {"leaf": "out", "start": start, "ct": ct, "value": 1 - e, "state": "running"}]}
    first = 0.2 if kind == "incoming" else 0.0
    raf = [rec(0.0, 0.0, None), rec(70.0, first, None), *[rec(70.0 + 20 * i, i / 60, 70.0) for i in range(1, 30)]]
    if kind == "stock":
        def stock(t: float, e: float, start: float | None) -> dict[str, Any]:
            return {"t": t, "eff": [1.0, 1 - e], "videos": [], "anims": [
                {"leaf": "out", "start": start, "ct": 0.0 if start is None else t - start, "value": 1 - e, "state": "running"}]}
        raf = [stock(0.0, 0.0, None), stock(70.0, 0.0, None), *[stock(70.0 + 20 * i, i / 60, 70.0) for i in range(1, 30)]]
    if kind == "start-dip":
        raf[0] = {"t": 0.0, "eff": [0.0, 0.5], "videos": [], "anims": []}
    if kind == "after-start":
        raf = [rec(0.0, 0.0, None), rec(20.0, 0.0, None), *[rec(20.0 + 20 * i + 50 * (i > 5), i / 60, 20.0) for i in range(1, 30)]]
    return probe.raf_problems(raf)


def no_twin() -> str:
    record, images = media_run("m-snap")
    return probe.score_arm(record, images, probe.ARMS["m-snap"], CAL, lut=IDENTITY_LUT)["outcome"]


CASES = [
    ("cross-fade", lambda: fade(), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("pop-in (stock)", lambda: fade("stock"), {"model": "FAIL", "complement": "FAIL", "no_dip": "PASS"}),
    ("dip (plain opposite fades)", lambda: fade("noblend"), {"model": "FAIL", "complement": "PASS", "no_dip": "FAIL"}),
    ("+-1 LSB", lambda: fade(noise=True), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("masked video", lambda: fade(garbage=True, masked=True), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("unmasked video", lambda: fade(garbage=True)["model"], "FAIL"),
    ("r1-5 one overlap pixel at alpha 251 fails no dip", lambda: fade(dent="overlap")["no_dip"], "FAIL"),
    ("r1-5 one in-only pixel off by 7 fails complement", lambda: fade(dent="in-only")["complement"], "FAIL"),
    ("integrity: < 6 mid frames", lambda: fade(es=[0.2, 0.4, 0.6, 0.8]), {"verdict": "INCONCLUSIVE"}),
    ("integrity: a class < 2000 px", class_too_small, ["class out: 0 px < 2000"]),
    ("DX-2 CEF: an inside AA corner (α 223 in A) and its 8 neighbours leave every class; the rest stay out-only",
     lambda: (lambda c: {k: int(v.sum()) for k, v in c.items()})(probe.texture_classes(
         np.pad(np.full((1, 1, 4), 223, np.uint8), ((2, 2), (2, 2), (0, 0)), constant_values=255), np.zeros((5, 5, 4), np.uint8))),
     {"out": 16, "in": 0, "overlap": 0}),
    ("curve eased", lambda: probe.score_curve(raf_curve("ease"))["verdict"], "PASS"),
    ("curve linear", lambda: probe.score_curve(raf_curve("linear"))["verdict"], "FAIL"),
    ("curve two start times", lambda: probe.score_curve(raf_curve("two-starts"))["verdict"], "FAIL"),
    ("DX-1 curve with leading rAFs whose animations are still pending (ct 0, no start)", lambda: probe.score_curve(raf_curve("pending"))["verdict"], "PASS"),
    ("Astra r1: a 'pending' rAF (ct 0, no start) at in 0 / out 0.5 is an unvalidated initial dip, not skipped",
     lambda: probe.score_curve(raf_curve("pending-dip"))["verdict"], "INCONCLUSIVE"),
    ("Astra r2: a pending rAF at its initial values after timed samples (reset before teardown) is not skipped",
     lambda: probe.score_curve(raf_curve("late-reset"))["verdict"], "INCONCLUSIVE"),
    ("r1-4 curve with every start None", lambda: probe.score_curve(raf_curve("no-start"))["verdict"], "INCONCLUSIVE"),
    ("r1-4 curve with a later NaN value", lambda: probe.score_curve(raf_curve("late-nan"))["verdict"], "INCONCLUSIVE"),
    ("r1-4 curve with a duplicate incoming animation", lambda: probe.score_curve(raf_curve("duplicate-in"))["verdict"], "INCONCLUSIVE"),
    ("monotone", lambda: probe.score_monotone([0.06, 0.2, 0.45, 0.7, 0.9, 0.995])["verdict"], "PASS"),
    ("non-monotone e", lambda: probe.score_monotone([0.06, 0.2, 0.45, 0.4, 0.9, 0.995])["verdict"], "FAIL"),
    ("hand-off unchanged", lambda: probe.score_handoff(textures()[1], textures()[1].copy())["verdict"], "PASS"),
    ("hand-off step above tau", lambda: probe.score_handoff(textures()[1], np.clip(textures()[1].astype(int) + 6, 0, 255).astype(np.uint8))["verdict"], "FAIL"),
    ("hand-off frame missing", lambda: probe.score_handoff(textures()[1], None)["verdict"], "INCONCLUSIVE"),
    ("no flash with a pre-animation sample", lambda: no_flash("covered"), "PASS"),
    ("r1-6 no flash without any pre-animation sample", lambda: no_flash("uncovered"), "INCONCLUSIVE"),
    ("cut union (1, 1)", lambda: cut("union"), "FAIL"),
    ("cut complementary (0.5, 0.5)", lambda: cut("complementary"), "PASS"),
    ("cut clean swap", lambda: cut("swap"), "PASS"),
    ("r1-6 cut (1, 1) on the completion frame", lambda: cut("completion-union"), "FAIL"),
    ("r1-6 cut without a pre-animation rAF", lambda: cut("no-pre"), "INCONCLUSIVE"),
    ("r1-6 cut with its only screencast frame after the cut", lambda: cut("cast-after"), "INCONCLUSIVE"),
    ("strip decode valid", lambda: probe.decode_strip(strip_frame(1380, (720, 64))), 1380),
    ("strip decode parity error", parity_error, None),
    ("strip under incoming content: raw flips, Ô decodes", strip_under_incoming, (False, True)),
    ("two decoders, one match", lambda: bind(False), (1, 0)),
    ("two decoders, ambiguous", lambda: bind(True), (0, 1)),
    ("index != reference", lambda: probe.score_frozen(41, REFERENCE, [REFERENCE] * 3)["verdict"], "FAIL"),
    ("Ô misses the reference", lambda: probe.score_frozen(REFERENCE, REFERENCE, [REFERENCE, None, REFERENCE])["verdict"], "FAIL"),
    ("Ô constant", lambda: region(False), "PASS"),
    ("Ô drifting", lambda: region(True), "FAIL"),
    ("< 3 demixable frames", lambda: (probe.demixable([0.1, 0.15, 0.5, 0.85, 0.9])[1], region(False, frames=2)), (2, "INCONCLUSIVE")),
    ("m-on run: frozen frame", lambda: arm_check("m-on", "frozen_frame"), "PASS"),
    ("m-on run: every contract check", lambda: arm_outcome("m-on"), "MATCH"),
    ("m-hold run: frozen region", lambda: arm_check("m-hold", "frozen_region"), "FAIL"),
    ("placement m-fg-cef is the frozen-region PASS control",
     lambda: arm_check("m-fg-cef", "frozen_region"), "PASS"),
    ("r1-2 full-strength black/white movie that never fades", bw_hold, "FAIL"),
    ("r1-1 m-hold without its rVFC reference", lambda: arm_outcome("m-hold", mutate="no-reference"), "INCONCLUSIVE"),
    ("r1-1 m-hold without holder pixels", lambda: arm_outcome("m-hold", mutate="no-holder-png"), "INCONCLUSIVE"),
    ("m-paused complete", lambda: arm_outcome("m-paused"), "MATCH"),
    ("r1-1 m-paused without rVFC", lambda: arm_outcome("m-paused", mutate="no-reference"), "INCONCLUSIVE"),
    ("r1-1 m-paused requested frame != presented", lambda: arm_outcome("m-paused", mutate="requested-41"), "INCONCLUSIVE"),
    ("m-off complete", lambda: arm_check("m-off", "frozen_frame", holder=False), "FAIL"),
    ("m-off without playback", lambda: arm_outcome("m-off", holder=False, presented=3), "INCONCLUSIVE"),
    ("m-off with a holder", lambda: arm_outcome("m-off", holder=True), "INCONCLUSIVE"),
    ("integrity: served digest", lambda: arm_check("m-on", "model", mutate="digest"), "INCONCLUSIVE"),
    ("integrity: texture ids", lambda: arm_outcome("m-off", holder=False, mutate="texture-ids"), "INCONCLUSIVE"),
    ("r1-8 integrity: expected and observed hashes missing", lambda: arm_check("m-on", "frozen_frame", mutate="no-hashes"), "INCONCLUSIVE"),
    ("r1-8 terminal transition holds on #<scene count>", terminal_hash, "#4"),
    ("sweep: duplicated rVFC record", lambda: arm_check("m-on", "frozen_frame", mutate="dup-rv"), "INCONCLUSIVE"),
    ("sweep: a malformed rAF in the fade", lambda: arm_check("m-on", "overlay", mutate="raf-eff-empty"), "INCONCLUSIVE"),
    ("sweep: detach outside [advance, transition DOM]", lambda: arm_check("m-on", "frozen_frame", mutate="detach-zero"), "INCONCLUSIVE"),
    ("sweep: duplicated take publication", lambda: arm_check("m-on", "cost", mutate="takes-dup"), "INCONCLUSIVE"),
    ("sweep: out-of-order screenshot time", lambda: arm_check("m-on", "model", mutate="shot-time-zero"), "INCONCLUSIVE"),
    ("sweep: empty S_live", lambda: arm_check("m-hold", "frozen_region", mutate="live-empty"), "INCONCLUSIVE"),
    ("sweep: holder list missing (patch off)", lambda: arm_check("m-off", "frozen_frame", holder=False, mutate="holders-key-missing"), "INCONCLUSIVE"),
    ("sweep: transition rAF without its animation list", lambda: lifecycle("advance", mutate="anims-key-missing"), "INCONCLUSIVE"),
    ("sweep: holder rect missing", lambda: arm_outcome("m-on", mutate="holder-rect-missing"), "INCONCLUSIVE"),
    ("media evidence: no reference record", lambda: arm_check("m-on", "frozen_frame", mutate="no-reference"), "INCONCLUSIVE"),
    ("media evidence: holder pixels missing", lambda: arm_check("m-on", "frozen_frame", mutate="no-holder-png"), "INCONCLUSIVE"),
    ("foreground correct", lambda: foreground("correct"), "PASS"),
    ("foreground omitted", lambda: foreground("omitted"), "FAIL"),
    ("foreground shifted 2 px", lambda: foreground("shifted"), "FAIL"),
    ("foreground double-painted", lambda: foreground("double"), "FAIL"),
    ("foreground swapped", lambda: foreground("swapped"), "FAIL"),
    ("placement foreground demix scales only the amplified candidates at e=0.7994",
     foreground_demix_amplification, ("PASS", [0.0, 5.0], [4.0, 19.940179], "FAIL", "FAIL")),
    ("placement foreground with no incoming texture scores only the holder candidate",
     foreground_without_incoming, ("PASS", [4.0])),
    ("tone within 2", lambda: tone("within"), "PASS"),
    ("tone untoned (-11)", lambda: tone("untoned"), "FAIL"),
    ("tone identity decision: reported only", lambda: tone("identity"), "REPORTED"),
    ("r1-10 tone under a fully containing later canvas", lambda: arm_check("m-tone", "tone", identity=False, mutate="tone-covered"), "INCONCLUSIVE"),
    ("cost 50 ms", lambda: probe.score_cost([[60.0, 50.0]], 50.0, 96.0)["verdict"], "PASS"),
    ("cost 50 ms + eps", lambda: probe.score_cost([[60.0, 50.0 + 1e-6]], 50.0, 96.0)["verdict"], "FAIL"),
    ("cost missing", lambda: probe.score_cost([], 50.0, 96.0)["verdict"], "INCONCLUSIVE"),
    ("cost NaN", lambda: probe.score_cost([[60.0, None]], 50.0, 96.0)["verdict"], "INCONCLUSIVE"),
    ("r1-9 cost with only a stale pre-transition publication", lambda: arm_check("m-on", "cost", mutate="stale-take"), "INCONCLUSIVE"),
    ("independent overlay present", lambda: overlay(True), "FAIL"),
    ("independent overlay absent", lambda: overlay(False), "PASS"),
    ("LUT: median, interpolation, endpoints", lambda: lut("table"), ("table", 0, 61, 86, 111, 206, 255, [50, 100, 200])),
    ("LUT: channels disagree -> fallback", lambda: lut("disagree"), "fallback"),
    ("LUT: analytic curve within 1", lambda: lut("analytic"), "analytic"),
    ("r1-11 LUT: empty samples", lambda: lut("empty"), "INCONCLUSIVE"),
    ("r1-11 LUT: red channel 2 off the analytic curve", lambda: lut("red-off"), "table"),
    ("lifecycle advance complete", lambda: lifecycle("advance"), "MATCH"),
    ("r1-7 lifecycle with an errored twin holding a matching settled frame", lambda: lifecycle("advance", twin="errored"), "INCONCLUSIVE"),
    ("r1-7 lifecycle queued advance without its timed action", lambda: lifecycle("queued-advance", mutate="no-action"), "INCONCLUSIVE"),
    ("r1-12 resolver fields carry movie metadata before capture", "eager", True),
    ("round: controls and candidates hold", lambda: round_gate(None, "overall"), "PASS"),
    ("round: control INCONCLUSIVE invalidates", lambda: round_gate(("m-off", "frozen_frame", "INCONCLUSIVE"), "frozen_frame"), "INCONCLUSIVE"),
    ("round: negative control passing invalidates", lambda: round_gate(("off", "model", "PASS"), "model"), "INCONCLUSIVE"),
    ("round: candidate FAIL after controls", lambda: round_gate(("on-dsk", "model", "FAIL"), "model"), "FAIL"),
    ("r1-3 round of controls only", lambda: round_gate(None, "overall", only_controls=True), "INCONCLUSIVE"),
    ("r1-3 round without the CvC candidate", lambda: round_gate(None, "cvc", cvc=None), "INCONCLUSIVE"),
    ("r1-3 control with an incomplete capture", lambda: round_gate(("opaque-off", "problems", "no rAF records"), "model"), "INCONCLUSIVE"),
    ("r2-B1 transition rAFs without a videos inventory", lambda: arm_check("m-on", "overlay", mutate="no-videos"), "INCONCLUSIVE"),
    ("r2-B1 malformed colour tuple", lambda: arm_outcome("m-on", mutate="tuple-malformed"), "INCONCLUSIVE"),
    ("r2-B1 tone without the foreground inventory", lambda: arm_check("m-tone", "tone", identity=False, mutate="tone-no-fg"), "INCONCLUSIVE"),
    ("r2-B1 W3 evidence: no G2 state, an error for a tuple", lambda: sorted(w3_evidence()), ["G2 state", "colour tuple of x.mov"]),
    ("r2-B2 m-off with only three mid frames", lambda: arm_outcome("m-off", holder=False, mutate="three-mid"), "INCONCLUSIVE"),
    ("r2-B2 m-hold with only three mid frames", lambda: arm_outcome("m-hold", mutate="three-mid"), "INCONCLUSIVE"),
    ("r2-B2 an INCONCLUSIVE control arm is not read", lambda: round_gate(("off", "outcome", "INCONCLUSIVE"), "model"), "INCONCLUSIVE"),
    ("r2-M3 malformed animations in the final row", lambda: probe.score_curve(raf_curve("final-malformed"))["verdict"], "INCONCLUSIVE"),
    ("r2-M4 endpoint-frame alpha violations", lambda: {k: v for k, v in fade(es=[0.01, *ES, 0.99], dent="endpoints").items() if k != "model"},
     {"complement": "FAIL", "no_dip": "FAIL"}),
    ("r2-M5 queued action far before the advance", lambda: lifecycle("queued-advance", mutate="action-early"), "INCONCLUSIVE"),
    ("r2-M5 cleanup without a layer-id inventory", lambda: lifecycle("advance", mutate="no-layer-ids"), "INCONCLUSIVE"),
    ("sweep r2: duplicated layer-id inventory", lambda: lifecycle("advance", mutate="layer-ids-dup"), "INCONCLUSIVE"),
    ("r2-M5 automatic delay shows frame 99, reference 42", lambda: lifecycle("automatic", mutate="delay-99"), "MISMATCH"),
    ("r2-M5 automatic delay holds the reference", lambda: lifecycle("automatic", mutate="delay-42"), "MATCH"),
    ("r2-M6 LUT endpoint observations off the curve", lambda: lut("endpoints"), "table"),
    ("r2-M7 a capture straddling the cut window", lambda: cut("straddle"), "INCONCLUSIVE"),
    ("r2-M7 W3 keeps each screenshot's [t0, t1]", w3_cast, ['"t0": s["t0"]', '"t1": s["t1"]']),
    ("r2-M8 CEF: a report-only no-flash gap does not block", lambda: cef_outcome(mutate="no-pre-raf"), "MATCH"),
    ("r2-m9 W3 rejects a contradictory cached calibration", w3_calibration, False),
    ("r2-m10 negative take duration", lambda: arm_check("m-on", "cost", mutate="take-negative"), "INCONCLUSIVE"),
    ("r3-1 overlay video record without `on`", lambda: arm_check("m-on", "overlay", mutate="ov-on-del"), "INCONCLUSIVE"),
    ("r3-1 overlay video record with on=None", lambda: arm_check("m-on", "overlay", mutate="ov-on-none"), "INCONCLUSIVE"),
    ("r3-1 overlay video record with a NaN rect", lambda: arm_check("m-on", "overlay", mutate="ov-rect-nan"), "INCONCLUSIVE"),
    ("r3-1 intact overlay observation still FAILs", lambda: arm_check("m-on", "overlay", mutate="ov-intact"), "FAIL"),
    ("r3-2 curve final row state='' and ct=NaN", lambda: probe.score_curve(raf_curve("state-empty"))["verdict"], "INCONCLUSIVE"),
    ("r3-2 CEF on with an out-of-enum animation state", lambda: cef_outcome(mutate="anim-state-empty"), "INCONCLUSIVE"),
    ("r3-3 lifecycle fade with one mid frame", lambda: lifecycle("advance", mutate="keep-life"), "INCONCLUSIVE"),
    ("r3-3 automatic delay with one screenshot", delay_one, "INCONCLUSIVE"),
    ("r3-4 m-tone identity without rVFC", lambda: tone_identity("tone-rv-del"), "INCONCLUSIVE"),
    ("r3-4 m-tone identity without a colour tuple", lambda: tone_identity("tone-tuple-del"), "INCONCLUSIVE"),
    ("r3-4 m-tone identity without the foreground inventory", lambda: tone_identity("tone-fg-del"), "INCONCLUSIVE"),
    ("sweep r3: transition DOM missing from one mid-fade rAF", lambda: arm_outcome("m-on", mutate="eff-hole"), "INCONCLUSIVE"),
    ("sweep r3: cast record with an empty name", lambda: bool(probe.schema_problems({"cast": [{"name": "", "t0": 1.0, "t1": 2.0}]})), True),
    ("live3 animation timing follows unresolved start-time semantics",
     lambda: [probe.anim_problem({"leaf": "out", "value": 0.5, "dur": 1500, **timing}) for timing in (
         {"ct": 750, "start": None, "state": "paused"},
         {"ct": 750, "start": None, "state": "running"},
         {"ct": None, "start": None, "state": "paused"},
         {"ct": None, "start": None, "state": "running"},
         {"ct": 750, "start": None, "state": "finished"},
     )], [None, None, "null timing while paused", "null timing while running", "null timing while finished"]),
    ("r4-1 overlay video record with opacity -1", lambda: arm_check("m-on", "overlay", mutate="ov-eff-negative"), "INCONCLUSIVE"),
    ("r4-1 overlay video record with width -480", lambda: arm_check("m-on", "overlay", mutate="ov-width-negative"), "INCONCLUSIVE"),
    ("r4-2 go-to row with two mid frames before the interruption", lambda: interrupted("goto"), "INCONCLUSIVE"),
    ("r4-2 back row with two mid frames before the interruption", lambda: interrupted("back"), "INCONCLUSIVE"),
    ("r1-13 CEF round needs no headless-only arms", lambda: (round_gate(None, "overall", profile=probe.CEF),
                                                            "lifecycle" in probe.score_round({}, CAL, profile=probe.CEF)["gates"]), ("PASS", False)),
    ("r1-13 headless process/load checks apply to DX-1 only", lambda: (profile_headless(probe.DX1), profile_headless(probe.CEF)), (True, False)),
    ("r12 no dip on the both-opaque class with identical colours (alpha 255)", lambda: same_colour("patch"), "PASS"),
    ("r12 no dip on the both-opaque class with identical colours, KB alpha 191", lambda: same_colour("noblend"), "FAIL"),
    ("r12 strip decode from a device-scale holder", device_strip, REFERENCE),
    ("r12 holder pixels: exact holder", lambda: arm_check("m-snap", "holder_pixels"), "PASS"),
    ("r12 holder pixels: movie drawn 1 px off, under the production mask", lambda: arm_check("m-snap", "holder_pixels", mutate="holder-shift"), "FAIL"),
    ("r12 holder pixels: tone step only, compensated by L_path", lambda: arm_check("m-snap", "holder_pixels", mutate="tone-step", lut=probe.analytic_lut()), "PASS"),
    ("r12 holder pixels: the same tone step read without L_path", lambda: arm_check("m-snap", "holder_pixels", mutate="tone-step"), "FAIL"),
    ("r12 holder pixels: edge-band step of 8", lambda: arm_check("m-snap", "holder_pixels", mutate="edge-step"), "FAIL"),
    ("r12 holder pixels: no L_path for the compositing path", lambda: arm_check("m-snap", "holder_pixels", lut=None), "INCONCLUSIVE"),
    ("r12 holder pixels: scorer case 1-px shifted holder", lambda: probe.scorer_cases(CAL)["case:holder-shift"]["verdict"], "FAIL"),
    ("r12 m-snap complete", lambda: arm_outcome("m-snap"), "MATCH"),
    ("r12 m-snap-dpr15-frac contract on a 1-px-off movie", lambda: arm_outcome("m-snap-dpr15-frac", mutate="holder-shift"), "MATCH"),
    ("r12 mask verification: production mask", lambda: arm_check("m-snap", "mask"), "PASS"),
    ("r12 mask verification: whole-rectangle inventory", lambda: arm_check("m-snap", "mask", mutate="mask-whole"), "INCONCLUSIVE"),
    ("r12 mask verification: 3-px shifted inventory", lambda: arm_check("m-snap", "mask", mutate="mask-shift3"), "INCONCLUSIVE"),
    ("r12 mask verification: empty inventory", lambda: arm_check("m-snap", "mask", mutate="mask-empty"), "INCONCLUSIVE"),
    ("r12 mask verification: twin run missing", no_twin, "INCONCLUSIVE"),
    ("r12 mask scorer cases", lambda: cases("mask", ("production", "whole", "shift3", "empty")),
     {"production": "PASS", "whole": "INCONCLUSIVE", "shift3": "INCONCLUSIVE", "empty": "INCONCLUSIVE"}),
    ("r12 reference: valid set", lambda: arm_check("m-snap", "reference"), "PASS"),
    ("r12 reference: perfect-shift", lambda: arm_check("perfect-shift", "reference"), "FAIL"),
    *[(f"r12 reference: {m}", lambda m=m: arm_check("m-snap", "reference", mutate=m), "INCONCLUSIVE")
      for m in ("ref-stale", "ref-missing-anim", "ref-extra-anim", "ref-unpaused", "ref-ct-off", "ref-unstable", "ref-dom-gone", "ref-early")],
    ("r12 reference scorer cases", lambda: cases("reference", ("valid", "stale", "extra", "unpaused")),
     {"valid": "PASS", "stale": "INCONCLUSIVE", "extra": "INCONCLUSIVE", "unpaused": "INCONCLUSIVE"}),
    ("r12 tone coverage >= 50 %", lambda: arm_check("m-tone", "tone", identity=False), "PASS"),
    ("r12 tone coverage < 50 %", lambda: arm_outcome("m-tone", mutate="tone-small-cells"), "INCONCLUSIVE"),
    ("r12 m-tone identity complete", lambda: tone_identity(None), "MATCH"),
    ("r12 hide row: correct capture", lambda: lifecycle("hide"), "MATCH"),
    ("r12 hide control: stock twin dark while hidden, content after show", lambda: (hide_check("life-hide-twin", "hidden"), hide_check("life-hide-twin", "shown")),
     ("PASS", "PASS")),
    ("r12 hide control: dropped hide leaves a visible frame inside the interval", lambda: hide_check("life-hide-nohide", "hidden"), "FAIL"),
    ("r12 hide control: dropped show leaves no content after show", lambda: hide_check("life-hide-noshow", "shown"), "FAIL"),
    ("r12 hide row: duplicate after-show frame", lambda: lifecycle("hide", mutate="cast-dup"), "INCONCLUSIVE"),
    ("r12 hide row: shifted screencast timestamp", lambda: lifecycle("hide", mutate="cast-shift"), "INCONCLUSIVE"),
    ("r12 hide row: < 6 after-show mid frames", lambda: lifecycle("hide", mutate="cast-few"), "INCONCLUSIVE"),
    ("r12 hide scorer cases", lambda: cases("hide", ("valid", "duplicate", "shift")),
     {"valid": "PASS", "duplicate": "INCONCLUSIVE", "shift": "INCONCLUSIVE"}),
    ("r12 exterior gate: bound holder", lambda: arm_check("m-raw-svgclip", "exterior"), "PASS"),
    ("r12 exterior gate: published take without a holder", lambda: arm_check("m-raw-caption", "exterior", holder=False), "FAIL"),
    ("r12 exterior gate: no published take", lambda: arm_check("m-raw-caption", "exterior", holder=False, mutate="no-take"), "INCONCLUSIVE"),
    ("r12 exterior gate: injection not applied", lambda: arm_check("m-raw-script", "exterior", holder=False, mutate="no-inject"), "INCONCLUSIVE"),
    ("r12 m-raw: exterior gate and frozen frame", lambda: arm_outcome("m-raw"), "MATCH"),
    ("r12 geometry guard: bound holder", lambda: arm_check("m-snap", "geometry"), "PASS"),
    ("r12 geometry guard: published take without a holder", lambda: arm_check("m-geo-scale", "geometry", holder=False), "FAIL"),
    ("r12 geometry guard: no published take", lambda: arm_check("m-geo-base", "geometry", holder=False, mutate="no-take"), "INCONCLUSIVE"),
    ("r13 fractional-letterbox stage and DSF-2 device shape", lambda: (probe.stage_of(probe.ARMS["m-snap-lbfrac"]), probe.device_shape(probe.ARMS["m-snap-dpr2"])),
     ({"x": 0.0, "y": 60.5, "width": 640.0, "height": 360.0}, (720, 1280))),
    ("r12 round: a dropped-action control passing invalidates its gate", lambda: round_gate(("life-hide-nohide", "hidden", "PASS"), "hidden"), "INCONCLUSIVE"),
    ("sweep r12: a dropped-action control recorded as performed", lambda: hide_check("life-hide-nohide", "hidden", mutate="drop-flag-del"), "INCONCLUSIVE"),
    ("r12-1 m-snap without decoder rVFC and colour tuple", lambda: arm_outcome("m-snap", mutate="no-decoder-evidence"), "INCONCLUSIVE"),
    ("r12-1 m-snap-dpr15-frac (1 px off) without decoder evidence", lambda: arm_outcome("m-snap-dpr15-frac", mutate="no-decoder-evidence"), "INCONCLUSIVE"),
    ("r12-1 m-raw-caption without decoder or video inventories", lambda: arm_outcome("m-raw-caption", holder=False, mutate="no-media-inventory"), "INCONCLUSIVE"),
    ("r12-1 m-geo-scale without decoder or video inventories", lambda: arm_outcome("m-geo-scale", holder=False, mutate="no-media-inventory"), "INCONCLUSIVE"),
    ("r12-2 life-hide-nohide without after-show frames", lambda: hide_check("life-hide-nohide", "hidden", mutate="hide-after-del"), "INCONCLUSIVE"),
    ("r12-2 life-hide-noshow without hidden-interval frames", lambda: hide_check("life-hide-noshow", "shown", mutate="hide-inside-del"), "INCONCLUSIVE"),
    ("r12-3 tone cells wholly under the verified mask", lambda: arm_check("m-tone", "tone", identity=False, mutate="tone-under-fg"), "INCONCLUSIVE"),
    ("r12-4 F50 pair aliased to one capture", lambda: arm_outcome("m-snap", mutate="ref-alias-f50"), "INCONCLUSIVE"),
    ("r12-4 perfect pair aliased to S_live", lambda: arm_outcome("m-snap", mutate="ref-alias-perfect"), "INCONCLUSIVE"),
    ("r12-4 perfect-shift with an unbound perfect rect", lambda: arm_outcome("perfect-shift", mutate="perfect-rect-bad"), "INCONCLUSIVE"),
    ("r12-5 life-hide with every after-show timestamp +64 ms", lambda: lifecycle("hide", mutate="cast-shift64"), "INCONCLUSIVE"),
    ("r12-5 hide twin control with every after-show timestamp +64 ms", lambda: hide_check("life-hide-twin", "shown", mutate="cast-shift64"), "INCONCLUSIVE"),
    ("r12-6 m-raw-svgclip holder in the incoming wrapper", lambda: arm_outcome("m-raw-svgclip", mutate="parent-incoming"), "INCONCLUSIVE"),
    ("r12-7 m-raw-modal whose dialog did not open", lambda: arm_outcome("m-raw-modal", holder=False, mutate="inject-false"), "INCONCLUSIVE"),
    ("r12-8 m-tone identity with < 50 % tone coverage", lambda: tone_identity("tone-small-cells"), "INCONCLUSIVE"),
    ("r12-9 DX-2 L_path measured in the launch (tone step -> 139 at 128) / identity / no m-tone session",
     lambda: (launch_map("tone-step"), launch_map(None), launch_map(None, drop=True)), ((True, 139), (True, 128), (False, None))),
    ("placement CEF L_path reads the CEF tone row and twin", cef_launch_map, (True, "m-tone-cef (this launch)")),
    ("r12b-1 m-raw-nav-open with the sidebar below the viewport", lambda: arm_outcome("m-raw-nav-open", holder=False, mutate="nav-offscreen"), "INCONCLUSIVE"),
    ("r12b-2 m-raw-caption with zeroed textures", lambda: arm_outcome("m-raw-caption", holder=False, mutate="tex-zero"), "INCONCLUSIVE"),
    ("r12b-2 m-geo-scale with zeroed textures", lambda: arm_outcome("m-geo-scale", holder=False, mutate="tex-zero"), "INCONCLUSIVE"),
    ("r12b-2 m-snap and twin with an opaque incoming texture (no out-only class)", lambda: arm_outcome("m-snap", mutate="tex-in-opaque"), "INCONCLUSIVE"),
    ("r12c-1 stale F50/B under a blank incoming texture (Astra impl r3)", stale_patch_blank_in, "INCONCLUSIVE"),
    ("r12c-1 stale F50/B with the real incoming texture", lambda: arm_outcome("m-snap", mutate="ref-stale-patch"), "INCONCLUSIVE"),
    *[(f"r13 {n}: engagement, holder pixels, perfect, mask", lambda n=n: arm_outcome(n), "MATCH") for n in probe.SNAPS],
    *[(f"r17 {n}: displaced edge FAILs holder pixels", lambda n=n: arm_outcome(n, mutate="holder-shift"), "MATCH")
      for n in probe.FAILS],
    ("r13 m-geo-dpr125 publishes a take without a holder", lambda: arm_outcome("m-geo-dpr125", holder=False), "MATCH"),
    *[(f"r13 {n}: foreground preserved (blocking)", lambda n=n: arm_outcome(n), "MATCH") for n in ("m-fg", "m-fg-dsf15", "m-fg-dsf2")],
    ("r13 recorded DSF differs from the arm", lambda: arm_outcome("m-snap-dpr2", mutate="dsf-mismatch"), "INCONCLUSIVE"),
    ("r13 recorded viewport differs from the arm", lambda: arm_outcome("m-snap-lbfrac", mutate="viewport-mismatch"), "INCONCLUSIVE"),
    ("r13 DSF not recorded", lambda: arm_outcome("m-fg-dsf15", mutate="dsf-missing"), "INCONCLUSIVE"),
    ("r13 DPR 2 by CDP emulation, not the launch flag", lambda: arm_outcome("m-snap-dpr2", mutate="dsf-emulated"), "INCONCLUSIVE"),
    ("r13 reference capture without held-back player timers", lambda: arm_outcome("m-snap-dpr2", mutate="timers-missing"), "INCONCLUSIVE"),
    ("sweep r13: reference capture whose timer hold caught no player timer", lambda: arm_outcome("m-snap", mutate="timers-none"), "INCONCLUSIVE"),
    ("sweep r13: an incoming texture one row short", lambda: arm_outcome("m-snap-dpr2", mutate="tex-in-short"), "INCONCLUSIVE"),
    ("r13 exact-coverage alpha support at DPR 1.5 (40 -> 60 px, one source px -> its 1.5 device px)",
     lambda: [int(v) for v in probe.coverage_support(np.eye(1, 40, 3, dtype=bool), (1, 60))[0].nonzero()[0]], [4, 5]),
    ("r12 round: perfect-shift passing invalidates the reference gate", lambda: round_gate(("perfect-shift", "reference", "PASS"), "reference"), "INCONCLUSIVE"),
    ("r17 m-snap-shift moves the holder one device px right, once on every supported player and its omit twin", snap_shift, [1, 1]),
    ("placement CEF underlay omission splice matches once on both pinned players", frac_underlay_omit, [1, 1]),
    ("r17 DX-1 alpha arm whose page never received the grant", lambda: arm_outcome("m-on", mutate="placement-invalid"), "INCONCLUSIVE"),
    ("r17 grant-chrome: host-committed snap binds a holder", lambda: arm_check("grant-chrome", "grant"), "PASS"),
    ("r17 grant-attach: no grant (attached), published take without a holder", lambda: arm_outcome("grant-attach", holder=False), "MATCH"),
    ("r17 grant-attach recorded with another reason", lambda: arm_check("grant-attach", "grant", holder=False, mutate="reason-other"), "INCONCLUSIVE"),
    ("r17 grant-chrome holder without a host grant", lambda: arm_check("grant-chrome", "grant", mutate="grant-null"), "INCONCLUSIVE"),
    ("r17 grant-attach page forged to snap", lambda: arm_outcome("grant-attach", holder=False, mutate="placement-snap"), "INCONCLUSIVE"),
    ("r17 channel-predefined: channel-compromised and show refused", lambda: arm_outcome("channel-predefined", holder=False), "MATCH"),
    ("r17 channel-predefined with show allowed", lambda: arm_outcome("channel-predefined", holder=False, mutate="show-allowed"), "INCONCLUSIVE"),
    ("r17 grant-chrome complete: the committed grant freezes the next take (life-grant-valid)", lambda: arm_outcome("grant-chrome"), "MATCH"),
    ("r17 life-grant-reload: invalid until the re-grant, then a holder", lambda: arm_outcome("life-grant-reload"), "MATCH"),
    ("r17 life-grant-reload already snap before the re-grant", lambda: arm_outcome("life-grant-reload", mutate="reload-snap"), "INCONCLUSIVE"),
    *[(f"r17 {n}: no channel, no holder, cross-fade model", lambda n=n: arm_outcome(n, holder=False), "MATCH") for n in ("m-raw-prod", "m-preview-prod")],
    *[(f"placement O1 {n}: forged production page binds no holder", lambda n=n: arm_outcome(n, holder=False), "MATCH")
      for n in sorted(name for name in probe.ARMS if "-prod-forge-" in name and not name.endswith("-kb"))],
    ("placement O1 live known-bad forged raw page binds a holder",
     lambda: arm_outcome("m-raw-prod-forge-snap-getter-kb"), "MATCH"),
    ("placement O1 forged production page binding a holder",
     lambda: arm_outcome("m-raw-prod-forge-frac-getter", holder=True), "MISMATCH"),
    ("placement CEF fractional-only underlay omission refuses the holder",
     lambda: arm_outcome("m-snap-cef-underlay-omit", holder=False), "MATCH"),
    ("placement underlay omission without a published take is inconclusive",
     lambda: arm_outcome("m-snap-cef-underlay-omit", holder=False, mutate="no-take"), "INCONCLUSIVE"),
    *[(f"placement Chrome {name} fractional geometry negative publishes no holder",
       lambda name=name: arm_outcome(name, holder=False), "MATCH")
      for name in ("m-geo-frac-origin-chrome", "m-geo-frac-dpr15", "m-geo-frac-dpr2")],
    ("placement CEF excludes viewport and DPR negatives that its fixed source cannot produce",
     lambda: (set(("m-geo-dpr125", "m-geo-2560", "m-geo-frac-origin-cef")) & set(probe.CEF_PLACEMENT.arms),
              set(("m-geo-frac-origin-chrome", "m-geo-frac-dpr15", "m-geo-frac-dpr2")) <= set(probe.DX1.arms)),
     (set(), True)),
    ("placement raw tone control uses the current identity-tone player bytes",
     lambda: probe.ARMS["m-tone-raw-cef"].splice, None),
    ("placement raw tone control reuses the same-frame CEF omit twin",
     lambda: (probe.ARMS["m-tone-raw-cef"].twin,
              scored("m-tone-raw-cef", identity=False, mutate="tone-step")["outcome"]),
     ("m-tone-cef-twin", "MATCH")),
    ("placement near-side clip preserves every child's absolute edge and moves only the clipping edge", near_clip_geometry,
     [((0.0, 0.0, 0.0), 0.0, 0.0), ((0.0, 0.0, 0.0), 0.0, 0.0)]),
    ("placement near-side clip rejects non-zero parent bounds origins and transforms", near_clip_rejections,
     ("near clipping requires a zero bounds origin and an untransformed parent",) * 3),
    ("placement correct near clips match with geometry-clipped strip evidence", near_clip_outcomes,
     [("MATCH", "strip clipped by geometry"), ("MATCH", "strip clipped by geometry")]),
    ("placement near clip geometry fails closed on partial strip and stale paused rVFC identity",
     near_clip_fail_closed, ("partial", True, True)),
    ("placement base and wrong-rule rows use an inset foreground layout that leaves holder edges",
     edge_fixture_layout, (("edgefg", "edgefg", "edgefg", "edgefg"), REFERENCE, {"interior": 0.0, "edge": 0.0}, True)),
    ("placement nooffset defect remains a valid FAIL when its holder strip is undecodable",
     negative_strip_problems, [[], []]),
    ("placement nooffset-x override keeps a near clip at a useful real-fixture displacement",
     lambda: nooffset_real_geometry("x"),
     (-80.0, 951.54296875, True, (300.987187, 795.036194, 570.555781, 267.62146),
      (("3652165F1CC62CFCEB8D764941CC3950", (1208.0, 624.0, 354, 313)),
       ("74EE7166AEA70C8FD2FEDE82CCDC7157", (1286.0, 133.0, 354, 313)),
       ("18B86872E5CD75C18A5696F17F574999", (740.0, 190.0, 353, 313))),
      True, 260.969564, True, (490.555781, 267.62146), True, True,
      (("nooffsetx",), ("nooffsetx",)), (-301, 0.036194, 952, 268, 571, 268, False))),
    ("placement nooffset-y override keeps a near clip at a useful real-fixture displacement",
     lambda: nooffset_real_geometry("y"),
     (-80.0, 267.6214599609375, True, (109.351707, 27.418584, 951.542969, 160.202876),
      (("3652165F1CC62CFCEB8D764941CC3950", (1208.0, 624.0, 354, 313)),
       ("74EE7166AEA70C8FD2FEDE82CCDC7157", (1286.0, 133.0, 354, 313)),
       ("18B86872E5CD75C18A5696F17F574999", (740.0, 190.0, 353, 313))),
      True, -56.211426, True, (951.542969, 80.202876), True, True,
      (("nooffsety",), ("nooffsety",)), (0.351707, -27, 952, 268, 952, 161, False))),
    ("placement nooffset-y correct holder passes pixels and therefore mismatches the negative arm",
     nooffset_y_outcomes, ("PASS", "PASS", "MISMATCH", "FAIL", "MATCH")),
    ("placement nooffset attribution binds the explicit displaced strip mode",
     displaced_attribution,
     ("PASS", "FAIL", "FAIL", "INCONCLUSIVE", "INCONCLUSIVE", (5, 6), ("displaced-x", "displaced-y"))),
    ("placement DSK uses one pinned counter, a real media fragment, and h264 copies for other movies", "dsk-counter",
     (2, 1, (0.0, 0.0),
      ("assets/clip-10-1000001.mov-0.0000-20.8000.mov", "assets/clip-10-1000002.mov-0.0000-50.2000.mov#t=5"),
      ("clip-10-1000001.mov-0.0000-20.8000.mov", "clip-10-1000002.mov-0.0000-50.2000.mov"),
      probe.DSK_COUNTER_SHA256, True, (1, 2), {30.0}, 30.0)),
    ("placement DSK binds timing past prior-slide decoders and enforces directed #t=5 time/frame deltas", "dsk-identity",
     ([], [], [0, 1], 5.0, 30.0, True, True, [], True, 8, [], True, True, [], True, True, [], True,
      [22.0], True, True, True, [], True, True, [], True)),
    ("legacy non-DSK evidence may omit freeze draws", legacy_non_dsk_without_freeze_draws, (True, "MATCH")),
    ("placement burst records each screenshot duration",
     lambda: probe._shot_record("shot", 10.0, 201.25), {"name": "shot", "t0": 10.0, "t1": 201.25, "durationMs": 191.25}),
    ("placement CEF profile reports inherited cut and identity-tone rows",
     lambda: ({"cut", "tone"} <= set(probe.CEF_PLACEMENT.reported),
              {"cut", "tone"}.isdisjoint(probe.CEF_PLACEMENT.controls()),
              probe.ARMS["m-fg-cef"].expect.get("frozen_region"),
              probe.CEF_PLACEMENT.controls()["frozen_region"]),
     (True, True, "PASS", (("m-fg-cef",), ("m-hold-cef",)))),
    ("DX-1 m-raw-prod: the destination's movies after the hand-off do not empty the in-only class",
     lambda: arm_outcome("m-raw-prod", holder=False, mutate="dest-video"), "MATCH"),
    ("r17 m-raw-prod binding a holder", lambda: arm_check("m-raw-prod", "scope"), "PASS"),
    ("r17 m-preview-prod page carrying a channel", lambda: arm_outcome("m-preview-prod", holder=False, mutate="placement-invalid"), "INCONCLUSIVE"),
    ("r17 CEF cef-skip: invalid page, no holder, cross-fade model", lambda: cef_outcome_of("cef-skip", holder=False), "MATCH"),
    ("r17 CEF cef-skip binding a holder", lambda: cef_outcome_of("cef-skip"), "MISMATCH"),
    ("r17 CEF profile: cross-fade, cut, opaque and cef-skip sessions only; its round passes",
     lambda: (probe.CEF.arms, round_gate(None, "overall", profile=probe.CEF), round_gate(None, "scope", profile=probe.CEF),
              probe.CEF.mid_frames, probe.DX1.mid_frames, probe.ARMS["cef-skip-dsk"].min_class_px, probe.ARMS["cef-skip"].min_class_px),
     (("opaque-off", "off", "noblend", "on2", "cut-on", "cut-off", "on", "opaque-on", "cef-skip", "cef-skip-dsk"), "PASS", "PASS",
      5, 6, 1000, 2000)),
    ("DX-1 raw page: one press, then wait for the hash to move", lambda: raw_navigate(True), ("reached", 1)),
    ("DX-1 raw page: a press the player never takes is refused, not re-pressed", lambda: raw_navigate(False), ("refused", 1)),
    ("DX-1 raw page: the target lists the automatic scenes the readiness waits through",
     lambda: probe.find_target({"assets/header.json": {"slideList": ["a"], "loopSlideshow": 0}, "assets/a/a.json": {"events": [
         {"automaticPlay": True, "effects": []},
         {"automaticPlay": False, "effects": [{"type": "transition", "name": "apple:dissolve", "duration": 1.5,
                                                "baseLayer": {"layers": [{"layers": [{"texture": "IN"}, {"texture": "OUT"}]}]}}]}]}}.__getitem__, 1)
     ["automaticScenes"], [0]),
    ("DX-2 CEF: a 70 ms gap before the start, ending on a pending record at the initial values", lambda: pre_start_gap("pending"), []),
    ("DX-2 CEF: a pre-start gap ending on incoming opacity 0.2", lambda: pre_start_gap("incoming"), ["rAF gap inside the transition"]),
    ("DX-2 CEF stock player (mode off): a 70 ms pre-start gap at incoming 1, outgoing pending at 1", lambda: pre_start_gap("stock"), []),
    ("Astra r3: a pre-start gap starting on outgoing 0.5 (DOM present, no animations yet)", lambda: pre_start_gap("start-dip"),
     ["rAF gap inside the transition"]),
    ("DX-2 CEF: a 70 ms gap after the animations started", lambda: pre_start_gap("after-start"), ["rAF gap inside the transition"]),
    ("r17 round: grant-attach passing invalidates the grant gate", lambda: round_gate(("grant-attach", "grant", "PASS"), "grant"), "INCONCLUSIVE"),
]


@pytest.mark.parametrize("build, expected", [pytest.param(b, e, id=name) for name, b, e in CASES])
def test_dissolve_scorer(build, expected, monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "VIEWPORT", (W, H))
    if build == "eager":
        actual = eager_movies(tmp_path, monkeypatch)
    elif build == "dsk-counter":
        actual = dsk_counter_resolver(tmp_path, monkeypatch)
    elif build == "dsk-identity":
        actual = dsk_holder_identity(tmp_path, monkeypatch)
    else:
        actual = build()
    assert actual == expected
