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
        if shape == "duplicate-in":
            anims.append(dict(anims[0], value=0.0))
        rows.append({"t": ct, "eff": [v, 1 - v], "anims": anims})
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
            "completion-union": [(8.0, half, half)], "no-pre": [(8.0, half, half)], "cast-after": [(90.0, full, none_)]}[kind]
    return probe.score_cut(raf, [{"t": t, "in": i, "out": o} for t, i, o in cast], CAL)["verdict"]


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
    if variant == "empty":
        snap, live = np.zeros((0, 3)), np.zeros((0, 3))
    out = probe.build_lut(np.array(snap), np.array(live))
    if variant != "table":
        return out["kind"]
    t = out["table"]
    return out["kind"], t[0], t[50], t[75], t[100], t[200], t[255], out["observed"]


def media_run(arm: str, *, holder: bool = True, presented: int = 30, mutate: str | None = None, fullstrength: bool = False,
              bw: bool = False) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """A whole run record and its images in the hook/driver shape: P2-like 2->3 with one counter movie."""
    A, B = textures()
    spec = probe.ARMS[arm]
    frame = strip_frame(REFERENCE, bw=bw)
    placed = probe.place(frame, CONTENT, CONTENT, (H, W))
    with_holder = probe.over(placed, A) if holder else A
    raf, shots, images = [], [], {"tex-in": B, "tex-out": A, "live-0": with_holder, "live-1": with_holder.copy()}
    for t in np.arange(0.0, 1900.0, 16.0):
        present = INSERT_MS <= t < INSERT_MS + DURATION_MS
        e = probe.ease_in_out((t - INSERT_MS) / DURATION_MS)
        video = {"id": 0, "on": not t >= INSERT_MS}
        if video["on"]:
            video.update(rect=CONTENT, eff=1.0, inT=False, inStage=True, paused=False,
                         geo={"content": CONTENT, "region": CONTENT, "size": [binary.WIDTH, binary.HEIGHT]})
        rec = {"t": float(t), "hash": "#5", "scene": 5, "videos": [video]}
        if (mutate == "stale-take" and t < INSERT_MS) or (mutate == "takes-dup" and t >= INSERT_MS):
            rec["take"] = 22.0
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
            img = probe.over(placed, mix(A, B, e)) if arm == "m-hold" or fullstrength else mix(with_holder, B, e)
        images[name] = img
        shots.append({"name": name, "t0": t0, "t1": t0 + 10.0})
    blend, iso = ("plus-lighter", "isolate") if spec.styles == "on" else ("normal", "auto")
    chain = [[{"id": tid, "blend": "normal", "isolation": "auto"}, {"id": leaf, "blend": blend, "isolation": "auto"},
              {"id": "layer2", "blend": "normal", "isolation": iso}] for tid, leaf in (("IN", "layer3"), ("OUT", "layer4"))]
    holders = [{"parent": "layer4-opacity", "rect": CONTENT, "canvasRect": CONTENT, "natural": [binary.WIDTH, binary.HEIGHT]}] if holder else []
    if holder:
        images["holder-0"] = frame
    pins = live_runtime.SUPPORTED_PLAYERS[STOCK]
    expected = pins[0 if spec.mode == "on" else 1] if spec.splice is None else "f" * 64
    rv = [[INSERT_MS - 1 - (presented - i) * 33.0, (REFERENCE - presented + i) / binary.FPS, i] for i in range(1, presented + 1)]
    record = {
        "arm": arm, "page": spec.page, "load": 0.5, "headlessBefore": 0, "stage": {"x": 0, "y": 0, "width": W, "height": H},
        "target": {"textures": ["IN", "OUT"], "hashBefore": "#5", "hashAfter": "#7"},
        "served": {"mode": spec.mode, "splice": spec.splice, "stockSha256": STOCK, "expected": expected},
        "output": {"mmOpacity": {"sha256": expected}}, "hashBefore": "#5", "hashAfter": "#7", "shots": shots, "advanceAt": 50.0,
        "dump": {"raf": raf, "first": {"textures": ["IN", "OUT"], "chain": chain, "holders": holders, "layerIds": ["layer1"]},
                 "vids": [{"id": 0, "rv": rv, "detach": INSERT_MS - 0.5, "tuple": "bt709/bt709/bt709/false"}],
                 "takes": [[INSERT_MS - 1.0, 22.0]]},
    }
    if spec.capture == "paused":
        record["paused"] = {"state": "presented", "frame": REFERENCE, "id": 0}
    if spec.row:
        images["settled"] = B
        record.update(residue={"layers": 0, "rules": 0, "holders": 0},
                      actions=[{"name": n, "t": INSERT_MS + 1000 * o} for o, n in probe.LIFECYCLE[spec.row].get("actions", ())])
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
        record["movies"] = {"x.mov": {"layout": probe.tone_layout()}}
        record["foreground"] = {"0": [{"id": "FRAME", "rect": [0.0, 0.0, 640.0, 360.0]}]}
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
    elif mutate == "no-action":
        record["actions"] = []
    return record, images


def arm_check(arm: str, check: str, identity: bool | None = None, **kwargs: Any) -> str:
    record, images = media_run(arm, **kwargs)
    return probe.score_arm(record, images, probe.ARMS[arm], CAL, identity=identity)["checks"][check]["verdict"]


def arm_outcome(arm: str, **kwargs: Any) -> str:
    record, images = media_run(arm, **kwargs)
    return probe.score_arm(record, images, probe.ARMS[arm], CAL)["outcome"]


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
    """Movie metadata (the tone layout) is in the resolver's fields before any capture requests a movie."""
    root = tmp_path / "deck"
    (root / "assets/a/assets").mkdir(parents=True)
    (root / "assets/player").mkdir(parents=True)
    header = {"slideList": ["a"], "loopSlideshow": 0, "slideWidth": 1920, "slideHeight": 1080}
    (root / "assets/header.json").write_text(probe.json.dumps(header))
    events = [{"automaticPlay": False, "effects": [{"type": "transition", "name": "apple:dissolve", "duration": 1.5,
                                                    "baseLayer": {"layers": [{"layers": [{"texture": "IN"}, {"texture": "OUT"}]}]}}]}]
    (root / "assets/a/a.json").write_text(probe.json.dumps({"events": events}))
    (root / "assets/a/assets/Untitled.mov-0.0000-46.0333.mov").write_bytes(b"movie")
    (root / "assets/player/main.js").write_bytes(b"player")
    monkeypatch.setitem(probe.DECKS, "syn", probe.Deck(root))
    monkeypatch.setattr(probe, "served_player", lambda *a, **k: b"served")
    monkeypatch.setattr(probe, "scratch_movie", lambda scratch, kind, encoding, seconds: {
        "path": str(root / "assets/a/assets/Untitled.mov-0.0000-46.0333.mov"), "layout": probe.tone_layout()})
    arm = probe.replace(probe.ARMS["m-tone"], deck="syn", slide=1, strip=False)
    fields = probe.resolve(arm, tmp_path / "scratch").fields()
    return bool(fields["movies"]) and all(m.get("layout") for m in fields["movies"].values())


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
        else:
            scored[name]["checks"][check] = {"verdict": verdict}
    out = probe.score_round(scored, CAL, identity=False, extra={"cvc": {"verdict": cvc}} if cvc else {}, profile=profile)
    return out["overall"] if gate == "overall" else out["gates"][gate]["verdict"]


def profile_headless(profile: Any) -> bool:
    record, images = media_run("m-on")
    record.pop("load"), record.pop("headlessBefore")
    return any("headless" in p for p in probe.capture_problems(record, images, probe.ARMS["m-on"], profile))


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
    ("curve eased", lambda: probe.score_curve(raf_curve("ease"))["verdict"], "PASS"),
    ("curve linear", lambda: probe.score_curve(raf_curve("linear"))["verdict"], "FAIL"),
    ("curve two start times", lambda: probe.score_curve(raf_curve("two-starts"))["verdict"], "FAIL"),
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
    ("r1-13 CEF round needs no headless-only arms", lambda: (round_gate(None, "overall", profile=probe.CEF),
                                                            "lifecycle" in probe.score_round({}, CAL, profile=probe.CEF)["gates"]), ("PASS", False)),
    ("r1-13 headless process/load checks apply to DX-1 only", lambda: (profile_headless(probe.DX1), profile_headless(probe.CEF)), (True, False)),
]


@pytest.mark.parametrize("build, expected", [pytest.param(b, e, id=name) for name, b, e in CASES])
def test_dissolve_scorer(build, expected, monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "VIEWPORT", (W, H))
    assert (eager_movies(tmp_path, monkeypatch) if build == "eager" else build()) == expected
