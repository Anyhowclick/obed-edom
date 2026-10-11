"""Synthetic tests for the pure DX-1 scorer in `scripts/dissolve_probe.py` (plan `keynote_live_dissolve_crossfade` §10 item 4).

No browser, host or export. One parametrized test over a case table: every case builds its numpy evidence (or a whole
run record in the shape the hook and driver produce) here and states the verdict the scorer must return. The rows cover
the cross-fade model, pop-in, dip, +-1 LSB, masked video, curve, monotone, hand-off and capture integrity; cut union,
complementary and clean swap; strip decode (valid / parity error) and strip under incoming content (Ô decodes, the raw
frame does not); holder binding (match / ambiguous); frozen index, drifting Ô and too few demixable frames; the patch-off
media arm (complete -> FAIL, no playback or a holder -> INCONCLUSIVE, never an expected FAIL); foreground correct /
omitted / shifted / double-painted / swapped; tone within 2, untoned and the identity decision; cost; independent
overlay; the measured-LUT construction; and the round's control rule (controls read before candidates).

The world is 640x360 (`VIEWPORT` patched): outgoing texture opaque for x < 520, incoming for x >= 500, and a 1920x540
counter movie drawn at (10, 10) x 0.25 inside the outgoing-only class.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

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
INSERT_MS, DURATION_MS = 100.0, 1500.0
STOCK = next(iter(live_runtime.SUPPORTED_PLAYERS))
CAL = probe.Calibration()


def unpremul(p: np.ndarray) -> np.ndarray:
    a = np.clip(p[..., 3:4], 0, 255)
    rgb = np.where(a > 0, p[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(np.concatenate([rgb, a], axis=2)), 0, 255).astype(np.uint8)


def strip_frame(index: int, size: tuple[int, int] = (binary.WIDTH, binary.HEIGHT)) -> np.ndarray:
    """A natural-size opaque movie frame: mid-grey with the binary strip coding `index`."""
    w, h = size
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = 126
    img[..., 3] = 255
    img[..., 0] = (126 + (np.arange(w) % 40)).astype(np.uint8)
    sx, sy, sw, sh = binary.STRIP_RECT
    img[sy:sy + sh, sx:sx + sw, :3] = 126
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
         classes: tuple[str, ...] = ("out", "in", "overlap")) -> dict[str, str]:
    A, B = textures()
    frames = [mix(A, B, e, kind) for e in es]
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
        v = probe.ease_in_out(ct / DURATION_MS) if shape == "ease" else ct / DURATION_MS
        start_out = 0.0 if shape != "two-starts" else 4.0
        rows.append({"t": ct, "eff": [v, 1 - v], "anims": [
            {"leaf": "in", "ct": ct, "start": 0.0, "state": "running", "dur": DURATION_MS, "value": v},
            {"leaf": "out", "ct": ct, "start": start_out, "state": "running", "dur": DURATION_MS, "value": 1 - v}]})
    return rows


def cut(kind: str) -> str:
    eff = {"union": [(1, 1), (1, 1), (1, 0)], "complementary": [(0, 1), (0.5, 0.5), (1, 0)], "swap": [(0, 1), (1, 0), (1, 0)]}[kind]
    raf = [{"t": 0.0, "eff": list(eff[0]), "anims": []}]
    raf += [{"t": 16.0 * (k + 1), "eff": list(v), "anims": [{"ct": 1.0}]} for k, v in enumerate(eff[1:])]
    raf += [{"t": 16.0 * k} for k in range(4, 8)]
    cast = {"union": [(255.0, 255.0)], "complementary": [(127.5, 127.5)], "swap": [(0.0, 255.0), (255.0, 0.0)]}[kind]
    return probe.score_cut(raf, cast, 1, CAL)["verdict"]


def strip_under_incoming() -> tuple[bool, bool]:
    e, idx = 0.6, 1365
    S = strip_frame(idx, (720, 64))
    B = strip_frame(idx ^ 0xFFF, (720, 64))
    F = unpremul((1 - e) * probe.premul(S) + e * probe.premul(B))
    return probe.decode_strip(F) == idx, probe.decode_strip(probe.demix(F, B, e)) == idx


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
    out = probe.build_lut(np.array(snap), np.array(live))
    if variant != "table":
        return out["kind"]
    t = out["table"]
    return out["kind"], t[0], t[50], t[75], t[100], t[200], t[255], out["observed"]


def media_run(arm: str, *, holder: bool = True, presented: int = 30, mutate: str | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """A whole run record and its images in the hook/driver shape: P2-like 2->3 with one counter movie."""
    A, B = textures()
    spec = probe.ARMS[arm]
    placed = probe.place(strip_frame(REFERENCE), CONTENT, CONTENT, (H, W))
    with_holder = probe.over(placed, A) if holder else A
    raf, shots, images = [], [], {"tex-in": B, "tex-out": A, "live-0": with_holder, "live-1": with_holder.copy()}
    for t in np.arange(0.0, 1900.0, 16.0):
        present = INSERT_MS <= t < INSERT_MS + DURATION_MS
        e = probe.ease_in_out((t - INSERT_MS) / DURATION_MS)
        video = {"id": 0, "on": not t >= INSERT_MS}
        if video["on"]:
            video.update(rect=CONTENT, eff=1.0, inT=False, inStage=True, paused=False,
                         geo={"content": CONTENT, "region": CONTENT, "size": [binary.WIDTH, binary.HEIGHT]})
        rec = {"t": float(t), "hash": "#5", "scene": 5, "take": 22.0 if t >= INSERT_MS else None, "videos": [video]}
        if present:
            rec["eff"] = [e, 1 - e]
            rec["anims"] = [{"leaf": "in", "ct": t - INSERT_MS, "start": INSERT_MS, "state": "running", "dur": DURATION_MS, "value": e},
                            {"leaf": "out", "ct": t - INSERT_MS, "start": INSERT_MS, "state": "running", "dur": DURATION_MS, "value": 1 - e}]
        raf.append(rec)
    times = [10.0, 40.0, 70.0] + [120.0 + 110.0 * k for k in range(14)] + [1650.0, 1700.0, 1750.0]
    for k, t0 in enumerate(times):
        name = f"shot-{k:03d}"
        if t0 < INSERT_MS:
            img = with_holder
        elif t0 >= INSERT_MS + DURATION_MS:
            img = B
        else:
            e = probe.ease_in_out((t0 + 5 - INSERT_MS) / DURATION_MS)
            img = probe.over(placed, mix(A, B, e)) if arm == "m-hold" else mix(with_holder, B, e)
        images[name] = img
        shots.append({"name": name, "t0": t0, "t1": t0 + 10.0})
    blend, iso = ("plus-lighter", "isolate") if spec.styles == "on" else ("normal", "auto")
    chain = [[{"id": tid, "blend": "normal", "isolation": "auto"}, {"id": leaf, "blend": blend, "isolation": "auto"},
              {"id": "layer2", "blend": "normal", "isolation": iso}] for tid, leaf in (("IN", "layer3"), ("OUT", "layer4"))]
    holders = [{"parent": "layer4-opacity", "rect": CONTENT, "canvasRect": CONTENT, "natural": [binary.WIDTH, binary.HEIGHT]}] if holder else []
    if holder:
        images["holder-0"] = strip_frame(REFERENCE)
    pins = live_runtime.SUPPORTED_PLAYERS[STOCK]
    expected = pins[0 if spec.mode == "on" else 1] if spec.splice is None else "f" * 64
    rv = [[INSERT_MS - 1 - (presented - i) * 33.0, (REFERENCE - presented + i) / binary.FPS, i] for i in range(1, presented + 1)]
    record = {
        "arm": arm, "page": "alpha", "load": 0.5, "headlessBefore": 0, "stage": {"x": 0, "y": 0, "width": W, "height": H},
        "target": {"textures": ["IN", "OUT"], "hashBefore": "#5", "hashAfter": "#7"},
        "served": {"mode": spec.mode, "splice": spec.splice, "stockSha256": STOCK, "expected": expected},
        "output": {"mmOpacity": {"sha256": expected}}, "hashBefore": "#5", "hashAfter": "#7", "shots": shots,
        "dump": {"raf": raf, "first": {"textures": ["IN", "OUT"], "chain": chain, "holders": holders, "layerIds": ["layer1"]},
                 "vids": [{"id": 0, "rv": rv, "detach": INSERT_MS - 0.5, "tuple": "bt709/bt709/bt709/false"}]},
    }
    if mutate == "digest":
        record["output"]["mmOpacity"]["sha256"] = "0" * 64
    elif mutate == "texture-ids":
        record["dump"]["first"]["textures"] = ["OUT", "IN"]
    elif mutate == "no-reference":
        record["dump"]["vids"][0]["rv"] = []
    elif mutate == "no-holder-png":
        images.pop("holder-0", None)
    return record, images


def arm_check(arm: str, check: str, **kwargs: Any) -> str:
    record, images = media_run(arm, **kwargs)
    return probe.score_arm(record, images, probe.ARMS[arm], CAL)["checks"][check]["verdict"]


def arm_outcome(arm: str, **kwargs: Any) -> str:
    record, images = media_run(arm, **kwargs)
    return probe.score_arm(record, images, probe.ARMS[arm], CAL)["outcome"]


def perfect_round() -> dict[str, dict[str, Any]]:
    return {name: {"outcome": "MATCH", "checks": {c: {"verdict": v} for c, v in arm.expect.items()}}
            for name, arm in probe.ARMS.items() if arm.row is None}


def round_gate(mutate: tuple[str, str, str] | None, gate: str) -> str:
    scored = perfect_round()
    if mutate:
        name, check, verdict = mutate
        scored[name]["checks"][check] = {"verdict": verdict}
    out = probe.score_round(scored, CAL, identity=False)
    return out["overall"] if gate == "overall" else out["gates"][gate]["verdict"]


CASES = [
    ("cross-fade", lambda: fade(), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("pop-in (stock)", lambda: fade("stock"), {"model": "FAIL", "complement": "FAIL", "no_dip": "PASS"}),
    ("dip (plain opposite fades)", lambda: fade("noblend"), {"model": "FAIL", "complement": "PASS", "no_dip": "FAIL"}),
    ("+-1 LSB", lambda: fade(noise=True), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("masked video", lambda: fade(garbage=True, masked=True), {"model": "PASS", "complement": "PASS", "no_dip": "PASS"}),
    ("unmasked video", lambda: fade(garbage=True)["model"], "FAIL"),
    ("integrity: < 6 mid frames", lambda: fade(es=[0.2, 0.4, 0.6, 0.8]), {"verdict": "INCONCLUSIVE"}),
    ("integrity: a class < 2000 px", class_too_small, ["class out: 0 px < 2000"]),
    ("curve eased", lambda: probe.score_curve(raf_curve("ease"))["verdict"], "PASS"),
    ("curve linear", lambda: probe.score_curve(raf_curve("linear"))["verdict"], "FAIL"),
    ("curve two start times", lambda: probe.score_curve(raf_curve("two-starts"))["verdict"], "FAIL"),
    ("monotone", lambda: probe.score_monotone([0.06, 0.2, 0.45, 0.7, 0.9, 0.995])["verdict"], "PASS"),
    ("non-monotone e", lambda: probe.score_monotone([0.06, 0.2, 0.45, 0.4, 0.9, 0.995])["verdict"], "FAIL"),
    ("hand-off unchanged", lambda: probe.score_handoff(textures()[1], textures()[1].copy())["verdict"], "PASS"),
    ("hand-off step above tau", lambda: probe.score_handoff(textures()[1], np.clip(textures()[1].astype(int) + 6, 0, 255).astype(np.uint8))["verdict"], "FAIL"),
    ("hand-off frame missing", lambda: probe.score_handoff(textures()[1], None)["verdict"], "INCONCLUSIVE"),
    ("cut union (1, 1)", lambda: cut("union"), "FAIL"),
    ("cut complementary (0.5, 0.5)", lambda: cut("complementary"), "PASS"),
    ("cut clean swap", lambda: cut("swap"), "PASS"),
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
    ("m-off complete", lambda: arm_check("m-off", "frozen_frame", holder=False), "FAIL"),
    ("m-off without playback", lambda: arm_outcome("m-off", holder=False, presented=3), "INCONCLUSIVE"),
    ("m-off with a holder", lambda: arm_outcome("m-off", holder=True), "INCONCLUSIVE"),
    ("integrity: served digest", lambda: arm_check("m-on", "model", mutate="digest"), "INCONCLUSIVE"),
    ("integrity: texture ids", lambda: arm_outcome("m-off", holder=False, mutate="texture-ids"), "INCONCLUSIVE"),
    ("media evidence: no reference record", lambda: arm_check("m-on", "frozen_frame", mutate="no-reference"), "INCONCLUSIVE"),
    ("media evidence: holder pixels missing", lambda: arm_check("m-on", "frozen_frame", mutate="no-holder-png"), "INCONCLUSIVE"),
    ("foreground correct", lambda: foreground("correct"), "PASS"),
    ("foreground omitted", lambda: foreground("omitted"), "FAIL"),
    ("foreground shifted 2 px", lambda: foreground("shifted"), "FAIL"),
    ("foreground double-painted", lambda: foreground("double"), "FAIL"),
    ("foreground swapped", lambda: foreground("swapped"), "FAIL"),
    ("tone within 2", lambda: tone("within"), "PASS"),
    ("tone untoned (-11)", lambda: tone("untoned"), "FAIL"),
    ("tone identity decision: reported only", lambda: tone("identity"), "REPORTED"),
    ("cost 50 ms", lambda: probe.score_cost([50.0])["verdict"], "PASS"),
    ("cost 50 ms + eps", lambda: probe.score_cost([50.0 + 1e-6])["verdict"], "FAIL"),
    ("cost missing", lambda: probe.score_cost([])["verdict"], "INCONCLUSIVE"),
    ("cost NaN", lambda: probe.score_cost([math.nan])["verdict"], "INCONCLUSIVE"),
    ("independent overlay present", lambda: overlay(True), "FAIL"),
    ("independent overlay absent", lambda: overlay(False), "PASS"),
    ("LUT: median, interpolation, endpoints", lambda: lut("table"), ("table", 0, 61, 86, 111, 206, 255, [50, 100, 200])),
    ("LUT: channels disagree -> fallback", lambda: lut("disagree"), "fallback"),
    ("LUT: analytic curve within 1", lambda: lut("analytic"), "analytic"),
    ("round: controls and candidates hold", lambda: round_gate(None, "overall"), "PASS"),
    ("round: control INCONCLUSIVE invalidates", lambda: round_gate(("m-off", "frozen_frame", "INCONCLUSIVE"), "frozen_frame"), "INCONCLUSIVE"),
    ("round: negative control passing invalidates", lambda: round_gate(("off", "model", "PASS"), "model"), "INCONCLUSIVE"),
    ("round: candidate FAIL after controls", lambda: round_gate(("on-dsk", "model", "FAIL"), "model"), "FAIL"),
]


@pytest.mark.parametrize("build, expected", [pytest.param(b, e, id=name) for name, b, e in CASES])
def test_dissolve_scorer(build, expected, monkeypatch):
    monkeypatch.setattr(probe, "VIEWPORT", (W, H))
    assert build() == expected
