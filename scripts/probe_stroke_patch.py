#!/usr/bin/env python3
"""Probe: can an offline stroke-width patch drive Keynote's card borders
(``w-border-stroke-width`` precursor)?

Stroke lives on ``TSD.MediaStyleArchive.mediaProperties.stroke`` in the GLOBAL
``Index/DocumentStylesheet.iwa`` (verified on 4 decks); an image/movie points at
its style via top-level ``obj["style"]["identifier"]``; a style with no OWN
stroke dict inherits its parent's (``super.parent.identifier``, first hit
wins). AppleScript cannot set an image stroke (``line of image`` raises,
probed) — offline is the only route. The pure half (read/select/patch) needs
no Keynote; ``--live`` drives a copy of a real deck through Keynote to answer
whether a save RESETS a patched width, and whether the border widens on-screen.
"""
from __future__ import annotations

import argparse
import copy
import io
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from keynote_parser.codec import IWAFile

from obed_edom import keynote_app
from obed_edom.iwa_geometry import _geom_dict, _leaf_bbox, _xywha
from obed_edom.iwa_runs import _load_deck, slide_order

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "stroke-probe"
DEFAULT_MIN_REFS = 10
DEFAULT_WIDTH = 3.0
STYLESHEET_MEMBER = "Index/DocumentStylesheet.iwa"


# ==========================================================================
# Pure.
# ==========================================================================
def _resolve_stroke(style_id: str, objects: dict[str, dict]) -> tuple[dict | None, bool]:
    """First non-``None`` ``mediaProperties.stroke`` up the ``super.parent`` chain.

    (stroke, inherited) — ``inherited`` is True once the walk had to leave the
    starting style. Capped + seen-set, same shape as ``iwa_geometry._geom_dict``.
    """
    cur: str | None = str(style_id)
    seen: set[str] = set()
    inherited = False
    for _ in range(6):
        if cur is None or cur in seen:
            break
        seen.add(cur)
        obj = objects.get(cur)
        if not obj:
            break
        stroke = (obj.get("mediaProperties") or {}).get("stroke")
        if stroke is not None:
            return stroke, inherited
        parent = ((obj.get("super") or {}).get("parent") or {}).get("identifier")
        if parent is None:
            break
        cur = str(parent)
        inherited = True
    return None, inherited


def _collect_images(obj_id: str, objects: dict[str, dict], seen: set[str], out: list[str]) -> None:
    """DFS ``TSD.GroupArchive.children``, appending image/movie leaf ids. Mirrors
    ``iwa_runs._collect_group_text``'s seen-set group DFS."""
    if obj_id in seen:
        return
    seen.add(obj_id)
    obj = objects.get(obj_id)
    if not obj:
        return
    ptype = obj.get("_pbtype")
    if ptype == "TSD.GroupArchive":
        for ref in obj.get("children") or []:
            cid = ref.get("identifier")
            if cid is not None:
                _collect_images(str(cid), objects, seen, out)
    elif ptype in ("TSD.ImageArchive", "TSD.MovieArchive"):
        out.append(obj_id)


def card_styles(objects: dict[str, dict], id_to_file: dict[str, str]) -> list[dict]:
    """One dict per ``MediaStyleArchive`` referenced by an image/movie, sorted by refs desc.

    ``slide_of`` walks every slide's ``drawablesZOrder`` recursively through groups
    (a card's image is nested; ``compose_geometry`` never reaches it). Each dict:
    ``{id, member, width, color:(r,g,b,a), pattern, refs, slides, inherited}``.
    """
    slide_of: dict[str, int] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide = objects.get(slide_id)
        if not slide:
            continue
        images: list[str] = []
        seen: set[str] = set()
        for ref in slide.get("drawablesZOrder") or []:
            rid = ref.get("identifier")
            if rid is not None:
                _collect_images(str(rid), objects, seen, images)
        number = idx + 1
        for img_id in images:
            slide_of.setdefault(img_id, number)

    refs: dict[str, int] = {}
    slides_by_style: dict[str, set[int]] = {}
    for obj_id, obj in objects.items():
        if obj.get("_pbtype") not in ("TSD.ImageArchive", "TSD.MovieArchive"):
            continue
        style_id = (obj.get("style") or {}).get("identifier")
        if style_id is None:
            continue
        style_id = str(style_id)
        refs[style_id] = refs.get(style_id, 0) + 1
        number = slide_of.get(obj_id)
        if number is not None:
            slides_by_style.setdefault(style_id, set()).add(number)

    styles: list[dict] = []
    for style_id, count in refs.items():
        stroke, inherited = _resolve_stroke(style_id, objects)
        if stroke is None:
            continue
        color = stroke.get("color") or {}
        pattern = (stroke.get("pattern") or {}).get("type")
        styles.append({
            "id": style_id,
            "member": id_to_file.get(style_id),
            "width": stroke.get("width"),
            "color": (color.get("r"), color.get("g"), color.get("b"), color.get("a")),
            "pattern": pattern,
            "refs": count,
            "slides": sorted(slides_by_style.get(style_id, set())),
            "inherited": inherited,
        })
    styles.sort(key=lambda s: -s["refs"])
    return styles


def select_card_styles(styles: list[dict], min_refs: int) -> list[dict]:
    """White + opaque (r,g,b,a each >= 0.95) AND solid AND refs >= ``min_refs``. Never by id."""
    out = []
    for s in styles:
        r, g, b, a = s["color"]
        if r is None or g is None or b is None or a is None:
            continue
        if r >= 0.95 and g >= 0.95 and b >= 0.95 and a >= 0.95 \
                and s["pattern"] == "TSDSolidPattern" and s["refs"] >= min_refs:
            out.append(s)
    return out


def patch_stroke_widths(deck: Path, widths: dict[str, float]) -> dict:
    """Patch ``mediaProperties.stroke.width`` for each id in ``widths``, single-member
    rewrite of ``Index/DocumentStylesheet.iwa`` (a ~30-line copy of
    ``iwa_write.py:431-472``'s decode -> deepcopy -> re-encode -> reparse -> diff ->
    O_TRUNC mechanics; no ``iwa_write`` refactor for a probe).

    Refuses (deck untouched) if an id is absent, has no OWN stroke (inherited-only),
    lives in a different member, or fewer ids matched an archive than requested (the
    silent-no-op guard — every validation happens before any write).
    """
    deck = Path(deck)
    target_member = STYLESHEET_MEMBER
    widths = {str(k): float(v) for k, v in widths.items()}
    objects, id_to_file, _file_ids = _load_deck(deck)

    for sid in widths:
        obj = objects.get(sid)
        if obj is None:
            return {"refused": True, "reason": f"style {sid} not found in deck"}
        if (obj.get("mediaProperties") or {}).get("stroke") is None:
            return {"refused": True, "reason": f"style {sid} has no own stroke (inherited-only)"}
        if id_to_file.get(sid) != target_member:
            return {"refused": True,
                    "reason": f"style {sid} lives in {id_to_file.get(sid)!r}, not {target_member!r}"}

    with zipfile.ZipFile(deck) as zf:
        if target_member not in zf.namelist():
            return {"refused": True, "reason": f"member {target_member} missing from deck"}
        buf = zf.read(target_member)

    decoded = IWAFile.from_buffer(buf, target_member).to_dict()
    patched = copy.deepcopy(decoded)
    applied = 0
    for ch in patched["chunks"]:
        for arch in ch["archives"]:
            aid = str(arch["header"]["identifier"])
            if aid not in widths:
                continue
            for o in arch.get("objects") or []:
                o["mediaProperties"]["stroke"]["width"] = float(widths[aid])
                applied += 1
                break

    if applied != len(widths):
        return {"refused": True,
                "reason": f"only {applied}/{len(widths)} styles matched an archive in {target_member}"}

    new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
    reparsed = IWAFile.from_buffer(new_member, target_member).to_dict()
    obj_diffs = 0
    header_diffs = 0
    for c0, c1 in zip(decoded["chunks"], reparsed["chunks"]):
        for a0, a1 in zip(c0["archives"], c1["archives"]):
            if (a0.get("objects") or []) != (a1.get("objects") or []):
                obj_diffs += 1
            if a0["header"] != a1["header"]:
                header_diffs += 1
    value_clean = obj_diffs <= len(widths) and header_diffs == 0

    # In-place O_TRUNC preserves inode + com.apple.macl; a new file is refused by Keynote.
    out = io.BytesIO()
    with zipfile.ZipFile(deck) as zin, zipfile.ZipFile(out, "w") as zout:
        for zi in zin.infolist():
            data = new_member if zi.filename == target_member else zin.read(zi.filename)
            zout.writestr(zi, data, compress_type=zi.compress_type)
    payload = out.getvalue()
    fd = os.open(str(deck), os.O_WRONLY | os.O_TRUNC)
    try:
        written = 0
        while written < len(payload):
            written += os.write(fd, payload[written:])
    finally:
        os.close(fd)

    return {
        "refused": False,
        "reason": None,
        "target_member": target_member,
        "applied": applied,
        "obj_diffs": obj_diffs,
        "header_diffs": header_diffs,
        "value_clean": value_clean,
        "edited_ids": sorted(widths, key=str),
    }


def card_frames(objects: dict[str, dict], slide_number: int, style_ids: set[str]
                ) -> list[tuple[str, tuple[float, float, float, float]]]:
    """(image_id, (x0,y0,x1,y1)) for every image/movie on slide N whose style is in
    ``style_ids``, descending into ``TSD.GroupArchive`` children (card images are
    nested — ``compose_geometry`` returns none of them)."""
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        return []
    slide = objects.get(order[slide_number - 1][0])
    if not slide:
        return []
    out: list[tuple[str, tuple[float, float, float, float]]] = []
    seen: set[str] = set()

    def walk(obj_id: str, ox: float, oy: float) -> None:
        obj = objects.get(obj_id)
        if not obj:
            return
        ptype = obj.get("_pbtype")
        if ptype == "TSD.GroupArchive":
            if obj_id in seen:
                return
            seen.add(obj_id)
            gx, gy, _gw, _gh, _ga = _xywha(_geom_dict(obj))
            for ref in obj.get("children") or []:
                cid = ref.get("identifier")
                if cid is not None:
                    walk(str(cid), ox + gx, oy + gy)
        elif ptype in ("TSD.ImageArchive", "TSD.MovieArchive"):
            style_id = str((obj.get("style") or {}).get("identifier") or "")
            if style_id in style_ids:
                out.append((obj_id, _leaf_bbox(obj, ox, oy, objects)))

    for ref in slide.get("drawablesZOrder") or []:
        rid = ref.get("identifier")
        if rid is not None:
            walk(str(rid), 0.0, 0.0)
    return out


def border_run(png: Path, frame: tuple[float, float, float, float], px_per_pt: float) -> int:
    """Near-white contiguous run at the frame's left edge: scan the row at the frame's
    vertical centre, rightward from ``x0*px_per_pt - 6`` to ``x1*px_per_pt``; count the
    run of ``min(r,g,b) >= 240`` pixels once the first one is met (0 if none).

    ABSOLUTE values also pick up any near-white background/photo pixel behind the card —
    only the before/after DELTA (this run widening) is interpretable stroke evidence.
    """
    from PIL import Image  # noqa: PLC0415

    x0, y0, x1, y1 = frame
    img = Image.open(png).convert("RGB")
    row = max(0, min(img.height - 1, int(((y0 + y1) / 2.0) * px_per_pt)))
    start_x = max(0, int(x0 * px_per_pt) - 6)
    end_x = min(img.width, int(x1 * px_per_pt))
    pixels = img.load()
    run = 0
    started = False
    for x in range(start_x, end_x):
        r, g, b = pixels[x, row]
        if min(r, g, b) >= 240:
            started = True
            run += 1
        elif started:
            break
    return run


def _row_slice(png: Path, frame: tuple[float, float, float, float], px_per_pt: float,
               n: int = 16) -> list[int]:
    """``min(r,g,b)`` for ``n`` pixels rightward from ``x0*px_per_pt - 6`` at the frame's
    vertical-centre row — eyeball data printed alongside :func:`border_run`."""
    from PIL import Image  # noqa: PLC0415

    x0, y0, _x1, y1 = frame
    img = Image.open(png).convert("RGB")
    row = max(0, min(img.height - 1, int(((y0 + y1) / 2.0) * px_per_pt)))
    start_x = max(0, int(x0 * px_per_pt) - 6)
    pixels = img.load()
    return [min(pixels[x, row]) for x in range(start_x, min(img.width, start_x + n))]


def _canvas_size(objects: dict[str, dict]) -> tuple[float, float]:
    """``KN.ShowArchive.size``, else 1920x1080 (mirrors ``offline_inspect._canvas_size``)."""
    for obj in objects.values():
        if obj.get("_pbtype") == "KN.ShowArchive":
            size = obj.get("size") or {}
            w, h = size.get("width"), size.get("height")
            if w and h:
                return (float(w), float(h))
            break
    return (1920.0, 1080.0)


def _print_table(styles: list[dict], selected_ids: set[str]) -> None:
    print(f"{'sel':3} {'id':>10}  {'member':30}  {'width':>6}  "
          f"{'r':>8} {'g':>8} {'b':>8} {'a':>4}  {'pattern':16}  {'refs':>5}  "
          f"{'inherited':>9}  slides")
    for s in styles:
        r, g, b, a = s["color"]
        fmt = lambda v: f"{v:.5f}" if isinstance(v, (int, float)) else "—"  # noqa: E731
        mark = " * " if s["id"] in selected_ids else "   "
        print(f"{mark} {s['id']:>10}  {str(s['member']):30}  {s['width']!s:>6}  "
              f"{fmt(r):>8} {fmt(g):>8} {fmt(b):>8} {fmt(a):>4}  "
              f"{str(s['pattern']):16}  {s['refs']:>5}  {str(s['inherited']):>9}  {s['slides']}")


# ==========================================================================
# Live (--live): write but do not run here.
# ==========================================================================
def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def stroke_probe_applescript(deck_path: Path, export_dir: Path, *, doc_name: str, save: bool) -> str:
    """Close-by-name -> open -> ``document 1`` (``keynote.py``:983-991 bind) -> export ->
    (save + close saving yes) else (close saving no). Wrapped in ``using terms from`` +
    ``with timeout of 3600 seconds`` (mirrors ``write_gate_ab.py``:232 ``run_aprime`` /
    ``inspect.export_applescript``). ``doc_name`` is the patched copy's file stem — the
    close-by-name probe matches both ``"<stem>"`` and ``"<stem>.key"`` (Keynote's ``name of
    document`` isn't guaranteed to carry the extension), and a post-open guard errors out
    if ``document 1`` isn't actually this copy (stale window from a prior run)."""
    key = _as_escape(str(Path(deck_path).resolve()))
    dest = _as_escape(str(Path(export_dir).resolve()))
    app = keynote_app.bundle_id()
    close_tail = (
        ["  save theDoc", "  try", "    close theDoc saving yes", "  end try"]
        if save else
        ["  try", "    close theDoc saving no", "  end try"]
    )
    return "\n".join([
        f'using terms from application id "{app}"',
        f'tell application id "{app}"',
        "  activate",
        "  with timeout of 3600 seconds",
        "  try",
        f'    close (every document whose name is "{doc_name}") saving no',
        f'    close (every document whose name is "{doc_name}.key") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{key}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        f'  if name of theDoc does not start with "{doc_name}" then error '
        f'"bound wrong document: " & (name of theDoc)',
        f'  set exportFolder to POSIX file "{dest}"',
        "  export theDoc to exportFolder as slide images with properties "
        "{image format:PNG, skipped slides:false}",
        *close_tail,
        "  end timeout",
        "end tell",
        "end using terms from",
    ])


def _run_osascript(script: str) -> str:
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(["osascript", str(script_path)],
                              capture_output=True, text=True, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("osascript failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    return (proc.stdout or "").strip()


def _slide_png(folder: Path, slide_number: int) -> Path | None:
    from obed_edom.inspect import preview_pngs, preview_slide_number  # noqa: PLC0415

    for idx, png in enumerate(preview_pngs(folder)):
        if preview_slide_number(png.name, idx) == slide_number:
            return png
    return None


def _px_per_pt(objects: dict[str, dict], png: Path | None) -> float:
    show_w, _show_h = _canvas_size(objects)
    if png is None:
        return 1.0
    from obed_edom.images import image_size  # noqa: PLC0415

    size = image_size(png)
    return (size[0] / show_w) if size else 1.0


def _pixel_diff(before_png: Path, after_png: Path) -> dict:
    from PIL import Image, ImageChops  # noqa: PLC0415

    a = Image.open(before_png).convert("RGB")
    b = Image.open(after_png).convert("RGB")
    if a.size != b.size:
        return {"refused": True, "reason": f"size mismatch {a.size} != {b.size}"}
    diff = ImageChops.difference(a, b).convert("L")
    changed = sum(diff.histogram()[1:])  # non-zero luma delta
    total = a.size[0] * a.size[1]
    return {"changed_px": changed, "total_px": total, "pct": 100.0 * changed / total}


def _run_live(out: Path, patched_deck: Path, widths: dict[str, float],
              slide_number: int | None, selected: list[dict]) -> int:
    from obed_edom.inspect import preview_pngs  # noqa: PLC0415

    before_dir, after_dir = out / "before", out / "after"
    shutil.rmtree(before_dir, ignore_errors=True)
    before_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(after_dir, ignore_errors=True)
    after_dir.mkdir(parents=True, exist_ok=True)
    doc_name = patched_deck.stem

    print("LIVE: pre-patch export …")
    _run_osascript(stroke_probe_applescript(patched_deck, before_dir, doc_name=doc_name, save=False))
    if not preview_pngs(before_dir):
        raise RuntimeError(f"pre-patch export produced no PNGs in {before_dir} — "
                            "aborting before spending the second 1+ GB Keynote open")

    result = patch_stroke_widths(patched_deck, widths)
    print(f"PATCH: refused={result.get('refused')} obj_diffs={result.get('obj_diffs')} "
          f"header_diffs={result.get('header_diffs')} value_clean={result.get('value_clean')}")
    for style_id, new_w in widths.items():
        old_w = next((s["width"] for s in selected if s["id"] == style_id), None)
        print(f"  {style_id}: old={old_w} new={new_w}")
    if result.get("refused"):
        print(f"REFUSED: {result.get('reason')}")
        return 2

    print("LIVE: post-patch save + export …")
    _run_osascript(stroke_probe_applescript(patched_deck, after_dir, doc_name=doc_name, save=True))
    if not preview_pngs(after_dir):
        raise RuntimeError(f"post-patch export produced no PNGs in {after_dir}")

    p_objects, p_idf, _p_fi = _load_deck(patched_deck)
    reread = {s["id"]: s["width"] for s in card_styles(p_objects, p_idf)}
    for style_id, target in widths.items():
        got = reread.get(style_id)
        print(f"re-read after save {style_id}: {got} (target {target}) reset={got != target}")

    if slide_number is None:
        print("no slide selected for the border check.")
        return 0 if result.get("value_clean") else 1

    frames = card_frames(p_objects, slide_number, set(widths))[:3]
    before_png = _slide_png(before_dir, slide_number)
    after_png = _slide_png(after_dir, slide_number)
    px_per_pt = _px_per_pt(p_objects, before_png)
    print("  (absolute run lengths include background/photo pixels — only the DELTA is evidence)")
    for image_id, frame in frames:
        b_run = border_run(before_png, frame, px_per_pt) if before_png else None
        a_run = border_run(after_png, frame, px_per_pt) if after_png else None
        delta = (a_run - b_run) if (b_run is not None and a_run is not None) else None
        print(f"  card {image_id} frame={frame} before_run={b_run} after_run={a_run} delta={delta}")
        if before_png:
            print(f"    before row: {_row_slice(before_png, frame, px_per_pt)}")
        if after_png:
            print(f"    after  row: {_row_slice(after_png, frame, px_per_pt)}")
    print(f"  before PNG: {before_png}  after PNG: {after_png}")
    if before_png and after_png:
        print(f"  slide {slide_number} pixel diff: {_pixel_diff(before_png, after_png)}")

    return 0 if result.get("value_clean") else 1


def _patch_only(deck: Path, widths: dict[str, float], selected: list[dict]) -> int:
    result = patch_stroke_widths(deck, widths)
    print(f"PATCH: refused={result.get('refused')} obj_diffs={result.get('obj_diffs')} "
          f"header_diffs={result.get('header_diffs')} value_clean={result.get('value_clean')}")
    if result.get("refused"):
        print(f"REFUSED: {result.get('reason')}")
        return 2
    p_objects, p_idf, _p_fi = _load_deck(deck)
    reread = {s["id"]: s["width"] for s in card_styles(p_objects, p_idf)}
    for style_id, target in widths.items():
        old = next((s["width"] for s in selected if s["id"] == style_id), None)
        print(f"  {style_id}: old={old} target={target} re-read={reread.get(style_id)}")
    return 0 if result.get("value_clean") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, required=True, help="finalized .key to probe")
    ap.add_argument("--source", type=Path, help="wall .key — report its matching style width")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="scratch dir for the patched copy + PNGs (Keynote-writable, not /tmp)")
    ap.add_argument("--min-refs", type=int, default=DEFAULT_MIN_REFS)
    ap.add_argument("--width", type=float, default=DEFAULT_WIDTH)
    ap.add_argument("--slide", type=int, default=None,
                    help="default: auto (min slide number carrying a selected style)")
    ap.add_argument("--live", action="store_true",
                    help="drive Keynote — RUN ONLY WHEN KEYNOTE IS FREE")
    ap.add_argument("--patch-only", action="store_true",
                    help="offline: copy + patch + re-read widths, no Keynote")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing patched copy at --out")
    args = ap.parse_args(argv)

    if not args.deck.exists():
        ap.error(f"--deck not found: {args.deck}")

    objects, id_to_file, _file_ids = _load_deck(args.deck)
    styles = card_styles(objects, id_to_file)
    selected = select_card_styles(styles, args.min_refs)
    selected_ids = {s["id"] for s in selected}
    _print_table(styles, selected_ids)

    if not selected:
        print("no card styles selected (white + TSDSolidPattern + refs >= min-refs)")
        return 1

    source_widths: dict[str, float] = {}
    if args.source is not None:
        if not args.source.exists():
            ap.error(f"--source not found: {args.source}")
        src_objects, src_idf, _src_fi = _load_deck(args.source)
        src_by_id = {s["id"]: s for s in card_styles(src_objects, src_idf)}
        for s in selected:
            src = src_by_id.get(s["id"])
            if src is None:
                continue
            src_width = src["width"]
            if src_width is None:
                print(f"WARNING: source style {s['id']} has no width; "
                      f"falling back to --width {args.width}")
                continue
            source_widths[s["id"]] = src_width
            print(f"source width for {s['id']}: {src_width}")
            if src_width == s["width"]:
                print(f"WARNING: source width for {s['id']} equals its current width "
                      f"({s['width']}) — the patch would be a no-op; proceeding anyway")

    widths = {s["id"]: source_widths.get(s["id"], args.width) for s in selected}

    slide_number = args.slide
    style_slides = sorted({n for s in selected for n in s["slides"]})
    if slide_number is None:
        slide_number = style_slides[0] if style_slides else None
    elif slide_number not in style_slides:
        print(f"WARNING: --slide {slide_number} carries none of the selected styles "
              f"(selected styles live on {style_slides})")

    if not (args.live or args.patch_only):
        print("offline read only: no copy, no patch (pass --patch-only or --live to write)")
        return 0

    patched_deck = args.out / f"{args.deck.stem}_stroke.key"
    if patched_deck.resolve() == args.deck.resolve() or args.out.resolve() == args.deck.parent.resolve():
        ap.error("--out would alias --deck")
    if patched_deck.exists() and not args.force:
        ap.error(f"{patched_deck} exists; pass --force")

    args.out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.deck, patched_deck)
    print(f"copied {args.deck} -> {patched_deck}")

    if args.patch_only:
        return _patch_only(patched_deck, widths, selected)
    return _run_live(args.out, patched_deck, widths, slide_number, selected)


if __name__ == "__main__":
    raise SystemExit(main())
