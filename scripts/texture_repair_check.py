#!/usr/bin/env python3
"""Stage T gates for prepare-time texture repair (plan `keynote_export_texture_repair_stage_t` §4).

g1 (offline): every known export is copied to a temp dir (header, player, slide JSON/JSONP, PDF/PDFP only), run through
`preview_textures.json_hits` and `repair_textures`, and compared with the plan's expected outcome table.

g2 (headless, continuity off, GL replay off): a temp copy of the Alpha 7e3c export with movies is repaired (unless
`--no-repair`) and driven through `LiveOutputHost`:
  (a) settled slide 10: each label crop correlates >= 0.9 with the same crop of Keynote's flattened frame (AF8F0F);
  (b) slides 8 and 9: Vision OCR of each label crop equals the slide's accessibility text;
  (c) a mid-frame of the 9->10 Magic Move: WA0125's slot correlates >= 0.9 with WA0125's poster, < 0.5 with WA0121's.
`--no-repair` is the negative control: it must FAIL (a) and (c).

usage: uv run python scripts/texture_repair_check.py g1 --out RESULT.json
       uv run python scripts/texture_repair_check.py g2 --out DIR [--no-repair] [--export HTML --manifest MANIFEST.json]
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom import live_host  # noqa: E402
from obed_edom.fixture_paths import fixture, main_checkout  # noqa: E402
from obed_edom.html_preview import PreviewError, file_sha256, read_jsonish  # noqa: E402
from obed_edom.live_continuity import canonical_asset_name  # noqa: E402

PREVIEWS = main_checkout() / ".claude" / "worktrees" / "s2-followups-dsk-deck-902af1" / "output" / ".html-preview"
ALPHA_7E3C = "7e3c930194d00effe3a21ee0e86a20baddb74223f661b9fa23186282aaf7081d"
ALPHA_3B9019 = "3b9019f068d8ef1c14e586c86e75274a2bebad3c65116fd2247362ed9f39a7e3"
MINIMAL_59CB = "59cb220d674317326e710ccdc7d65fe1d7e473c83646227d2f691e6373d6fa0c"
G1_FIXTURES = ("alpha-dsk-textures", "qual-decks", "p2-recovery", "p2-binary", "p2-loop", "p2-loop-grey", "p2-soak-loop", "gl-decks")
UNNAMED_FIXTURES = ("minimal-alpha-dsk-17c0c938",)
REFUSAL_3B9019 = (
    "Cannot repair Keynote's HTML export: "
    "slide 9 (288×78 image): its texture is mis-mapped and no verified replacement exists; "
    "slide 10 (287×77 image): its texture is mis-mapped and no verified replacement exists"
)
EXPECT: dict[str, dict[str, Any]] = {
    "alpha-dsk-textures/html-unmodified": {"kind": "repaired", "rules": {"D1": 1, "D2": 3, "D3": 1}},
    "qual-decks/D2/html-unmodified": {"kind": "repaired", "rules": {"D3": None}},
    "qual-decks/D2/html-unmodified.across-first-build": {"kind": "repaired", "rules": {"D3": None}},
    "preview/3b9019": {"kind": "refused", "message": REFUSAL_3B9019},
}
DEFAULT_EXPECT = {"kind": "0 hits"}

G2_EXPORT = PREVIEWS / f"{ALPHA_7E3C}-p3-r1" / "html"
ORACLE_PREFIX = "AF8F0F"
LABEL_SLIDE, OCR_SLIDES, MM_SLIDE = 10, (8, 9), 9
MOVIE, OTHER_MOVIE = "vid-20250608-wa0125.mp4", "vid-20250608-wa0121.mp4"
VIEWPORT = (1920, 1080)
HEADLESS_HEIGHT_PAD = 32
SETTLE_S = 3.0
BURST_S = 2.0
CORR_PASS, CORR_OTHER_MAX = 0.9, 0.5
FLAT_STD = 2.0
IOU_MIN = 0.5
MAX_LOAD, LOAD_PATIENCE_S = 3.0, 60.0
STAGE_MAP_JS = (
    "(function(){var el=document.getElementById('stage');if(!el)return null;var r=el.getBoundingClientRect();"
    "return {sx:r.width/el.offsetWidth,sy:r.height/el.offsetHeight,ox:r.left,oy:r.top};})()"
)


def slides_from_header(root: Path) -> list[dict[str, Any]]:
    header = read_jsonish(root / "assets" / "header.json")
    return [{"exportedUuid": uuid, "playerIndex": k, "originalOrdinal": k + 1, "skipped": False} for k, uuid in enumerate(header["slideList"])]


def export_slides(root: Path) -> tuple[list[dict[str, Any]], str]:
    manifest = root.parent / "manifest.json"
    if manifest.is_file():
        return read_jsonish(manifest)["slides"], "manifest"
    return slides_from_header(root), "header"


def g1_exports() -> list[tuple[str, Path]]:
    exports = []
    tops = [(name, fixture(name)) for name in G1_FIXTURES] + [(name, main_checkout() / "output" / "fixtures" / name) for name in UNNAMED_FIXTURES]
    for name, top in tops:
        if not top.is_dir():
            exports.append((name, top))
        for header in sorted(top.rglob("assets/header.json")):
            root = header.parent.parent
            exports.append((f"{name}/{root.relative_to(top).as_posix()}", root))
    for label, digest in (("preview/3b9019", ALPHA_3B9019), ("preview/59cb", MINIMAL_59CB)):
        exports.append((label, PREVIEWS / f"{digest}-p3-r1" / "html"))
    return exports


def copy_minimal(src: Path, dst: Path) -> None:
    for rel in ("assets/header.json", "assets/player/main.js"):
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, dst / rel)
    for uuid in read_jsonish(src / "assets" / "header.json")["slideList"]:
        for rel in (f"{uuid}.json", f"{uuid}.jsonp", f"assets/{uuid}.pdf", f"assets/{uuid}.pdfp"):
            path = src / "assets" / uuid / rel
            if path.is_file():
                (dst / "assets" / uuid / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst / "assets" / uuid / rel)


def outcome_of(record: dict[str, Any]) -> dict[str, Any]:
    if "skipped" in record:
        return {"kind": "skipped", "reason": record["skipped"]}
    if not record["repaired"]:
        return {"kind": "0 hits"}
    return {"kind": "repaired", "rules": dict(sorted(Counter(entry["rule"] for entry in record["repaired"]).items()))}


def describe(outcome: dict[str, Any]) -> str:
    if outcome["kind"] == "repaired":
        rules = ", ".join(f"{rule}×{count}" for rule, count in outcome["rules"].items())
        return f"repaired {sum(outcome['rules'].values())} via {rules}"
    if outcome["kind"] in ("refused", "error"):
        return f"{outcome['kind']}: {outcome['message']}"
    if outcome["kind"] == "skipped":
        return f"skipped: {outcome.get('reason', '')}"
    return outcome["kind"]


def matches(outcome: dict[str, Any], expected: dict[str, Any], hits_after: list[str]) -> bool:
    if outcome["kind"] != expected["kind"]:
        return False
    if expected["kind"] == "refused":
        return outcome["message"] == expected["message"]
    if expected["kind"] == "repaired":
        if hits_after or set(outcome["rules"]) != set(expected["rules"]):
            return False
        return all(count is None or outcome["rules"][rule] == count for rule, count in expected["rules"].items())
    return True


def run_g1(out: Path) -> int:
    from obed_edom import preview_textures

    rows, failed = [], 0
    for label, root in g1_exports():
        row: dict[str, Any] = {"export": label, "root": str(root)}
        expected = EXPECT.get(label, DEFAULT_EXPECT)
        if not (root / "assets" / "header.json").is_file():
            row.update(outcome={"kind": "missing"}, hitsBefore=None, hitsAfter=None)
        else:
            slides, source = export_slides(root)
            log: list[str] = []
            with tempfile.TemporaryDirectory(prefix="texture-g1-") as tmp:
                copy = Path(tmp) / "html"
                copy_minimal(root, copy)
                before = preview_textures.json_hits(copy, slides)
                try:
                    record = preview_textures.repair_textures(copy, slides, player_digest=file_sha256(copy / "assets/player/main.js"), log=log.append)
                    outcome = outcome_of(record)
                except PreviewError as exc:
                    record, outcome = None, {"kind": "refused", "message": str(exc)}
                except Exception as exc:  # noqa: BLE001
                    record, outcome = None, {"kind": "error", "message": f"{type(exc).__name__}: {exc}"}
                after = preview_textures.json_hits(copy, slides)
            row.update(slidesFrom=source, hitsBefore=before, hitsAfter=after, outcome=outcome, record=record, log=log)
        row["expected"] = expected
        row["ok"] = matches(row["outcome"], expected, row["hitsAfter"] or [])
        failed += not row["ok"]
        rows.append(row)
        before_n = "-" if row["hitsBefore"] is None else len(row["hitsBefore"])
        after_n = "-" if row["hitsAfter"] is None else len(row["hitsAfter"])
        print(f"{'ok  ' if row['ok'] else 'FAIL'} {label}: hits before {before_n} | {describe(row['outcome'])} | hits after {after_n}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"gate": "G1", "rows": rows, "failed": failed}, indent=1, ensure_ascii=False, default=str))
    print(f"G1: {'PASS' if not failed else f'FAIL ({failed} unexpected)'}")
    return 1 if failed else 0


def load_guard() -> None:
    started = time.monotonic()
    while (load := os.getloadavg()[0]) >= MAX_LOAD:
        if time.monotonic() - started >= LOAD_PATIENCE_S:
            top = subprocess.run(["ps", "-Ao", "pcpu,pid,comm", "-r"], capture_output=True, text=True, check=False).stdout.splitlines()[:11]
            print(f"LOAD GUARD: 1-min load {load:.2f} >= {MAX_LOAD} for {LOAD_PATIENCE_S:.0f} s; refusing to start. Top CPU:", flush=True)
            print("\n".join(top), flush=True)
            raise SystemExit(2)
        time.sleep(5)


def uptime() -> str:
    return subprocess.run(["uptime"], capture_output=True, text=True, check=False).stdout.strip()


def norm_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(str.maketrans("‘’“”", "''\"\""))
    return " ".join(text.split()).casefold()


def leaves_abs(node: dict[str, Any], ox: float = 0.0, oy: float = 0.0, out: list | None = None) -> list[tuple[dict[str, Any], tuple[float, float, float, float]]]:
    out = [] if out is None else out
    st = node["initialState"]
    x = ox + st["position"]["pointX"] - st["anchorPoint"]["pointX"] * st["width"]
    y = oy + st["position"]["pointY"] - st["anchorPoint"]["pointY"] * st["height"]
    if node.get("texture"):
        out.append((node, (x, y, st["width"], st["height"])))
    for child in node.get("layers") or []:
        leaves_abs(child, x, y, out)
    return out


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter else 0.0


def slide_payload(root: Path, slides: list[dict[str, Any]], ordinal: int) -> tuple[str, dict[str, Any]]:
    uuid = next(s["exportedUuid"] for s in slides if s.get("originalOrdinal") == ordinal and not s.get("skipped"))
    return uuid, read_jsonish(root / "assets" / uuid / f"{uuid}.json")


def labels(payload: dict[str, Any]) -> list[dict[str, Any]]:
    event = payload["events"][0]
    acc = [(a["text"], (a["targetRectangle"]["x"], a["targetRectangle"]["y"], a["targetRectangle"]["width"], a["targetRectangle"]["height"])) for a in event.get("accessibility") or []]
    found = []
    for slot in event["baseLayer"]["layers"]:
        for leaf, rect in leaves_abs(slot):
            if (leaf.get("texturedRectangle") or {}).get("textureType") != 6:
                continue
            texts = [text for text, target in acc if iou(rect, target) >= IOU_MIN]
            if len(texts) == 1:
                found.append({"text": texts[0], "rect": [round(v) for v in rect]})
    return found


def movie_posters(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    posters = {}
    for effect in payload["events"][0].get("effects") or []:
        if effect.get("name") != "apple:movie-start":
            continue
        for render in effect.get("effects") or []:
            if render.get("name") != "renderMovie":
                continue
            asset = payload["assets"][render["movie"]["asset"]]
            poster = next(l["texture"] for l in render["baseLayer"]["layers"] if l.get("texture") and not l.get("isVideoLayer"))
            posters[canonical_asset_name(asset["url"]["native"])] = {"objectID": effect["objectID"], "poster": poster}
    return posters


def mm_slot_path(payload: dict[str, Any], object_id: str) -> dict[str, Any]:
    start = next(
        rect for slot in payload["events"][0]["baseLayer"]["layers"]
        if len(slot.get("layers") or []) == 1 and slot["layers"][0].get("objectID") == object_id
        for _leaf, rect in leaves_abs(slot)
    )
    effect = next(e for e in payload["events"][-1]["effects"] if e.get("name") == "apple:magic-move-implied-motion-path")
    leaf = next(
        leaf for slot in effect["baseLayer"]["layers"] for leaf, rect in leaves_abs(slot)
        if all(abs(p - q) <= 1.0 for p, q in zip(rect, start))
    )
    to = {"transform.scale.x": 1.0, "transform.scale.y": 1.0, "tx": 0.0, "ty": 0.0}
    for group in leaf.get("animations") or []:
        for anim in group.get("animations") or [group]:
            prop = anim.get("property")
            if prop in ("transform.scale.x", "transform.scale.y"):
                to[prop] = anim["to"]["scalar"]
            elif prop == "transform.translation":
                to["tx"], to["ty"] = anim["to"]["pointX"], anim["to"]["pointY"]
    st = leaf["initialState"]
    return {"start": list(start), "anchor": [st["anchorPoint"]["pointX"], st["anchorPoint"]["pointY"]], **to, "duration": effect["duration"]}


def rect_at(path: dict[str, Any], p: float) -> tuple[float, float, float, float]:
    x, y, w, h = path["start"]
    sx = 1 + (path["transform.scale.x"] - 1) * p
    sy = 1 + (path["transform.scale.y"] - 1) * p
    ax, ay = path["anchor"][0] * w, path["anchor"][1] * h
    return x + path["tx"] * p + ax - sx * ax, y + path["ty"] * p + ay - sy * ay, sx * w, sy * h


def render_page(pdf: Path, index: int, size: tuple[int, int], *, crop: tuple[float, ...] | None = None, grey: float = 0.0) -> np.ndarray:
    import Quartz
    from Foundation import NSURL

    doc = Quartz.CGPDFDocumentCreateWithURL(NSURL.fileURLWithPath_(str(pdf)))
    page = Quartz.CGPDFDocumentGetPage(doc, index + 1)
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    w, h = size
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w, Quartz.CGColorSpaceCreateDeviceGray(), Quartz.kCGImageAlphaNone)
    Quartz.CGContextSetGrayFillColor(ctx, grey, 1)
    Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    if crop:
        cx, cy, cw, ch = crop
        Quartz.CGContextScaleCTM(ctx, w / cw, h / ch)
        Quartz.CGContextTranslateCTM(ctx, -cx, -(box.size.height - cy - ch))
    else:
        Quartz.CGContextScaleCTM(ctx, w / box.size.width, h / box.size.height)
    Quartz.CGContextDrawPDFPage(ctx, page)
    image = Quartz.CGBitmapContextCreateImage(ctx)
    data = bytes(Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image)))
    return np.frombuffer(data, np.uint8).reshape(h, Quartz.CGImageGetBytesPerRow(image))[:, :w].astype(float)


def corr(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.std() < FLAT_STD or b.std() < FLAT_STD:
        return None
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b)))


def screen_crop(shot: Image.Image, stage: dict[str, float], rect: tuple[float, ...], size: tuple[int, int], origin: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    x, y, w, h = rect
    box = (stage["ox"] + x * stage["sx"] - origin[0], stage["oy"] + y * stage["sy"] - origin[1])
    box = (*box, box[0] + w * stage["sx"], box[1] + h * stage["sy"])
    return np.asarray(shot.convert("L").crop(tuple(round(v) for v in box)).resize(size, Image.BILINEAR), float)


def save_grey(array: np.ndarray, path: Path) -> None:
    Image.fromarray(np.clip(array, 0, 255).astype(np.uint8)).save(path)


def screenshot(transport: Any, clip: dict[str, float] | None = None) -> Image.Image:
    params: dict[str, Any] = {"format": "png"}
    if clip:
        params["clip"] = {**clip, "scale": 1}
    return Image.open(io.BytesIO(base64.b64decode(transport.call("Page.captureScreenshot", **params)["data"]))).convert("RGB")


def check_labels_vs_oracle(root: Path, slides: list[dict[str, Any]], shot: Image.Image, stage: dict[str, float], out: Path) -> dict[str, Any]:
    uuid, payload = slide_payload(root, slides, LABEL_SLIDE)
    oracle_id = next(k for k in payload["assets"] if k.startswith(ORACLE_PREFIX))
    pdf = root / "assets" / uuid / "assets" / f"{uuid}.pdf"
    rows = []
    for k, label in enumerate(labels(payload)):
        size = (label["rect"][2], label["rect"][3])
        screen = screen_crop(shot, stage, label["rect"], size)
        oracle = render_page(pdf, payload["assets"][oracle_id]["index"], size, crop=label["rect"])
        save_grey(screen, out / f"a-slide{LABEL_SLIDE}-label{k}-screen.png")
        save_grey(oracle, out / f"a-slide{LABEL_SLIDE}-label{k}-oracle.png")
        value = corr(screen, oracle)
        rows.append({**label, "corr": None if value is None else round(value, 3), "pass": value is not None and value >= CORR_PASS})
    return {"labels": rows, "pass": bool(rows) and all(r["pass"] for r in rows)}


def check_labels_ocr(root: Path, slides: list[dict[str, Any]], ordinal: int, shot: Image.Image, stage: dict[str, float], out: Path) -> dict[str, Any]:
    from obed_edom import ocr

    _uuid, payload = slide_payload(root, slides, ordinal)
    rows = []
    for k, label in enumerate(labels(payload)):
        x, y, w, h = label["rect"]
        pad = 6
        crop = screen_crop(shot, stage, (x - pad, y - pad, w + 2 * pad, h + 2 * pad), (3 * (w + 2 * pad), 3 * (h + 2 * pad)))
        png = out / f"b-slide{ordinal}-label{k}.png"
        save_grey(crop, png)
        text = ocr.ocr_text(png)
        rows.append({**label, "ocr": text, "pass": norm_text(text) == norm_text(label["text"])})
    return {"ordinal": ordinal, "labels": rows, "pass": bool(rows) and all(r["pass"] for r in rows)}


def check_mm_midframe(root: Path, slides: list[dict[str, Any]], host: Any, stage: dict[str, float], out: Path) -> dict[str, Any]:
    uuid, payload = slide_payload(root, slides, MM_SLIDE)
    posters = movie_posters(payload)
    path = mm_slot_path(payload, posters[MOVIE]["objectID"])
    pdf = root / "assets" / uuid / "assets" / f"{uuid}.pdf"
    probe = (64, 36)
    refs = {name: render_page(pdf, payload["assets"][posters[name]["poster"]]["index"], probe, grey=0.5) for name in (MOVIE, OTHER_MOVIE)}
    ends = [rect_at(path, 0.0), rect_at(path, 1.0)]
    x0, y0 = min(r[0] for r in ends), min(r[1] for r in ends)
    x1, y1 = max(r[0] + r[2] for r in ends), max(r[1] + r[3] for r in ends)
    clip = {"x": stage["ox"] + x0 * stage["sx"], "y": stage["oy"] + y0 * stage["sy"], "width": (x1 - x0) * stage["sx"], "height": (y1 - y0) * stage["sy"]}
    transport = host._require_transport()
    host.execute("advance")
    started, frames = time.monotonic(), []
    while time.monotonic() - started < BURST_S:
        frames.append((round(time.monotonic() - started, 3), screenshot(transport, clip)))
    origin = (clip["x"], clip["y"])
    scored = []
    for t, frame in frames:
        best = None
        for p in np.linspace(0.0, 1.0, 51):
            crop = screen_crop(frame, stage, rect_at(path, p), probe, origin)
            values = {name: corr(crop, ref) for name, ref in refs.items()}
            score = max((v for v in values.values() if v is not None), default=-1.0)
            if best is None or score > best[0]:
                best = (score, float(p), values)
        scored.append({"t": t, "p": round(best[1], 2), "corr": {k: None if v is None else round(v, 3) for k, v in best[2].items()}})
    mid = [s for s in scored if 0.25 <= s["p"] <= 0.75]
    record: dict[str, Any] = {"path": path, "frames": scored}
    if not mid:
        return {**record, "pass": False, "reason": "no burst frame between 25% and 75% of the Magic Move"}
    chosen = min(mid, key=lambda s: abs(s["p"] - 0.5))
    k = scored.index(chosen)
    frames[k][1].save(out / "c-mm-midframe.png")
    full = rect_at(path, chosen["p"])
    size = (round(full[2]), round(full[3]))
    save_grey(screen_crop(frames[k][1], stage, full, size, origin), out / "c-mm-slot.png")
    own, other = chosen["corr"][MOVIE], chosen["corr"][OTHER_MOVIE]
    ok = own is not None and other is not None and own >= CORR_PASS and other < CORR_OTHER_MAX
    return {**record, "chosen": chosen, "pass": ok}


def run_g2(args: argparse.Namespace) -> int:
    from obed_edom import preview_textures

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    load_guard()
    result: dict[str, Any] = {"gate": "G2", "arm": "no-repair" if args.no_repair else "repair", "export": str(args.export), "uptimeStart": uptime()}
    with tempfile.TemporaryDirectory(prefix="texture-g2-") as tmp:
        root = Path(tmp) / "html"
        shutil.copytree(args.export, root)
        slides = read_jsonish(args.manifest)["slides"]
        if not args.no_repair:
            result["textureRepair"] = preview_textures.repair_textures(root, slides, player_digest=file_sha256(root / "assets/player/main.js"), log=print)
        result["servedJsonHits"] = preview_textures.json_hits(root, slides)
        width, height = VIEWPORT
        live_host.choose_display = lambda *_a, **_k: live_host.OutputDisplay(0, 0, 0, width, height + HEADLESS_HEIGHT_PAD, True)
        host = live_host.LiveOutputHost(root, slides, headless=True, continuity="off", gl_replay="off")
        host.start()
        try:
            transport = host._require_transport()
            host.execute("show")
            stage = transport.evaluate(STAGE_MAP_JS)
            result["stage"] = stage
            checks: dict[str, Any] = {}
            host.execute("goTo", LABEL_SLIDE)
            time.sleep(SETTLE_S)
            shot = screenshot(transport)
            shot.save(out / f"slide{LABEL_SLIDE}.png")
            checks["a"] = check_labels_vs_oracle(root, slides, shot, stage, out)
            checks["b"] = []
            for ordinal in OCR_SLIDES:
                host.execute("goTo", ordinal)
                time.sleep(SETTLE_S)
                shot = screenshot(transport)
                shot.save(out / f"slide{ordinal}.png")
                checks["b"].append(check_labels_ocr(root, slides, ordinal, shot, stage, out))
            if OCR_SLIDES[-1] != MM_SLIDE:
                host.execute("goTo", MM_SLIDE)
                time.sleep(SETTLE_S)
            checks["c"] = check_mm_midframe(root, slides, host, stage, out)
        finally:
            host.stop()
    verdicts = {"a": checks["a"]["pass"], "b": all(b["pass"] for b in checks["b"]), "c": checks["c"]["pass"]}
    result.update(checks=checks, verdicts=verdicts, uptimeEnd=uptime())
    (out / "result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    for name, ok in verdicts.items():
        print(f"({name}) {'PASS' if ok else 'FAIL'}")
    if args.no_repair:
        confirmed = not verdicts["a"] and not verdicts["c"]
        print(f"negative control: {'confirmed ((a) and (c) FAIL)' if confirmed else 'NOT confirmed — the instrument does not see the defect'}")
        return 0 if confirmed else 1
    print(f"G2: {'PASS' if all(verdicts.values()) else 'FAIL'}")
    return 0 if all(verdicts.values()) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="gate", required=True)
    g1 = sub.add_parser("g1", help="offline detector + repair over every known export")
    g1.add_argument("--out", type=Path, required=True, help="result JSON")
    g2 = sub.add_parser("g2", help="headless check of the repaired Alpha 7e3c export")
    g2.add_argument("--out", type=Path, required=True, help="directory for crops and result.json")
    g2.add_argument("--export", type=Path, default=G2_EXPORT, help="export root (copied; never written)")
    g2.add_argument("--manifest", type=Path, help="manifest.json with slides (default: next to the export root)")
    g2.add_argument("--no-repair", action="store_true", help="negative control: play the export as Keynote wrote it")
    args = parser.parse_args(argv)
    if args.gate == "g2" and args.manifest is None:
        args.manifest = args.export.parent / "manifest.json"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_g1(args.out) if args.gate == "g1" else run_g2(args)


if __name__ == "__main__":
    raise SystemExit(main())
