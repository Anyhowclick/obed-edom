#!/usr/bin/env python3
"""Probe: can an offline ``drawablesZOrder``/``ownedDrawables`` patch drive Keynote's
z-order (``w-zorder-patch`` precursor)?

Three questions: (1) does Keynote honour a permuted ``drawablesZOrder`` (+ identical
``ownedDrawables``) on open; (2) does a re-save keep it; (3) does the AS per-kind
collection order (``every shape``) follow it. The pure half (permute/read/patch) needs
no Keynote; ``--live`` drives a throwaway three-shape deck through Keynote to answer
all three and pixel-diffs the before/after renders.
"""
from __future__ import annotations

import argparse
import copy
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from keynote_parser.codec import IWAFile

from obed_edom import keynote_app
from obed_edom.iwa_runs import _load_deck, slide_order

# Direct execution (`python scripts/probe_zorder_patch.py`) puts scripts/ itself, not the
# repo root, on sys.path[0]; pytest and `python -c "import scripts…"` already have the
# root. Idempotent to add twice.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.write_gate_ab import target_member_for_slide  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "zorder-probe"
DOC_NAME = "zprobe.key"


# ==========================================================================
# Pure.
# ==========================================================================
def permute_front(ids: list[str]) -> list[str]:
    """Rotate the back-most (index 0) id to the front-most (last) slot. [] and [x] unchanged."""
    return ids[1:] + ids[:1] if len(ids) > 1 else list(ids)


def permute_front_within(order: list[str], subset: list[str]) -> list[str]:
    """``permute_front``, restricted to the slots ``subset`` occupies in ``order``; every
    other id (e.g. the default theme's placeholder drawables) stays in place."""
    subset_ids = set(subset)
    positions = [i for i, x in enumerate(order) if x in subset_ids]
    rotated = permute_front([order[i] for i in positions])
    result = list(order)
    for pos, val in zip(positions, rotated):
        result[pos] = val
    return result


def read_zorder(deck: Path, slide_number: int) -> tuple[list[str], list[str]]:
    """(drawablesZOrder ids, ownedDrawables ids) as strings, via _load_deck + slide_order."""
    try:
        objects, _id_to_file, _file_ids = _load_deck(deck)
    except Exception as exc:  # noqa: BLE001 — surfaced as a hint, not swallowed
        raise RuntimeError(
            f"_load_deck failed on {deck}: {exc} (keynote_parser may not decode a "
            "15.3.1-authored member — check the installed keynote_parser version)"
        ) from exc
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        raise ValueError(f"slide {slide_number} out of range (deck has {len(order)} slides)")
    slide = objects[order[slide_number - 1][0]]
    z = [str(r["identifier"]) for r in slide.get("drawablesZOrder") or []]
    owned = [str(r["identifier"]) for r in slide.get("ownedDrawables") or []]
    return z, owned


def reorder_slide_zorder(deck: Path, slide_number: int, new_order: list[str]) -> dict:
    """Overwrite ``drawablesZOrder`` AND ``ownedDrawables`` with ``new_order``, in place.

    A ~25-line copy of ``iwa_write.patch_slide_geometry``'s member-rewrite mechanics
    (:431-472) — no ``iwa_write`` refactor for a probe. Refuses (deck untouched) when the
    slide's own member disagrees with its drawables' member, or ``new_order`` adds/drops
    an id.
    """
    deck = Path(deck)
    objects, id_to_file, _file_ids = _load_deck(deck)
    order = slide_order(objects)
    if not (1 <= slide_number <= len(order)):
        return {"refused": True, "reason": f"slide {slide_number} out of range (deck has {len(order)})"}
    slide_id = order[slide_number - 1][0]
    slide = objects.get(slide_id)
    if not slide:
        return {"refused": True, "reason": f"slide archive {slide_id} not decoded"}

    target_member = id_to_file.get(slide_id)
    expected = target_member_for_slide(objects, id_to_file, slide_number)
    if target_member != expected:
        return {"refused": True,
                "reason": f"slide member {target_member!r} != drawables' member {expected!r}"}

    orig_ids = [str(r["identifier"]) for r in slide.get("drawablesZOrder") or []]
    if set(new_order) != set(orig_ids) or len(new_order) != len(orig_ids):
        return {"refused": True, "reason": "new_order id set/length mismatch; deck untouched"}

    with zipfile.ZipFile(deck) as zf:
        buf = zf.read(target_member)
    decoded = IWAFile.from_buffer(buf, target_member).to_dict()
    patched = copy.deepcopy(decoded)
    new_refs = [{"identifier": i} for i in new_order]
    for ch in patched["chunks"]:
        for arch in ch["archives"]:
            if str(arch["header"]["identifier"]) != slide_id:
                continue
            for o in arch.get("objects") or []:
                o["drawablesZOrder"] = new_refs
                o["ownedDrawables"] = list(new_refs)

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
    value_clean = obj_diffs <= 1 and header_diffs == 0

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
        "member": target_member,
        "obj_diffs": obj_diffs,
        "header_diffs": header_diffs,
        "value_clean": value_clean,
        "slide_id": slide_id,
        "new_order": new_order,
    }


# ==========================================================================
# Live (--live): write but do not run.
# ==========================================================================
def _keynote_tell() -> str:
    return f'tell application id "{keynote_app.bundle_id()}"'


def _keynote_terms() -> str:
    return f'using terms from application id "{keynote_app.bundle_id()}"'


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def make_deck_applescript(deck_path: Path, before_dir: Path) -> str:
    """Three overlapping shapes (ONE back .. THREE front, ``probe_gui_zorder.applescript``'s
    shape block), saved to ``deck_path``, before/-exported, closed. No System Events."""
    key = _as_escape(str(Path(deck_path).resolve()))
    before = _as_escape(str(Path(before_dir).resolve()))
    return "\n".join([
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        "    set doc to make new document",
        "    tell slide 1 of doc",
        '      make new shape with properties {position:{300, 300}, width:360, height:280, object text:"ONE"}',
        '      make new shape with properties {position:{420, 360}, width:360, height:280, object text:"TWO"}',
        '      make new shape with properties {position:{540, 420}, width:360, height:280, object text:"THREE"}',
        "    end tell",
        f'    save doc in POSIX file "{key}"',
        f'    export doc to POSIX file "{before}" as slide images with properties '
        "{image format:PNG, skipped slides:false}",
        "    close doc saving yes",
        "  end timeout",
        "end tell",
        "end using terms from",
    ])


def verify_applescript(deck_path: Path, after_dir: Path, doc_name: str = DOC_NAME) -> str:
    """Close-by-name (with and without the extension) -> open -> ``document 1`` (the
    ``keynote.py``:983-991 bind), asserted to be ``zprobe`` before it is touched; collect
    coerced ``object text`` of every shape in AS collection order, export ``after/``,
    save, close."""
    key = _as_escape(str(Path(deck_path).resolve()))
    after = _as_escape(str(Path(after_dir).resolve()))
    stem = Path(doc_name).stem
    return "\n".join([
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        "  try",
        f'    close (every document whose name is "{doc_name}" or name is "{stem}") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{key}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        '  if name of theDoc does not start with "zprobe" then error '
        '"bound wrong document: " & (name of theDoc)',
        "  set shapeTexts to {}",
        "  repeat with sh in shapes of slide 1 of theDoc",
        "    set end of shapeTexts to ((object text of sh) as string)",
        "  end repeat",
        "  set od to AppleScript's text item delimiters",
        '  set AppleScript\'s text item delimiters to ", "',
        "  set joined to shapeTexts as string",
        "  set AppleScript's text item delimiters to od",
        f'  set exportFolder to POSIX file "{after}"',
        "  export theDoc to exportFolder as slide images with properties "
        "{image format:PNG, skipped slides:false}",
        "  save theDoc",
        "  close theDoc saving yes",
        "  end timeout",
        "  return joined",
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


def _pixel_diff(before_dir: Path, after_dir: Path) -> dict:
    """Slide-1 PNG pixel diff (before vs after), changed-pixel count + percentage."""
    from PIL import Image, ImageChops

    from obed_edom.inspect import preview_pngs, preview_slide_number

    before_pngs = sorted(preview_pngs(before_dir), key=lambda p: preview_slide_number(p.name, 0))
    after_pngs = sorted(preview_pngs(after_dir), key=lambda p: preview_slide_number(p.name, 0))
    if not before_pngs or not after_pngs:
        return {"refused": True, "reason": "missing before/after PNG"}
    a = Image.open(before_pngs[0]).convert("RGB")
    b = Image.open(after_pngs[0]).convert("RGB")
    if a.size != b.size:
        return {"refused": True, "reason": f"size mismatch {a.size} != {b.size}"}
    diff = ImageChops.difference(a, b)
    changed = sum(1 for px in diff.getdata() if px != (0, 0, 0))
    total = a.size[0] * a.size[1]
    return {"changed_px": changed, "total_px": total, "pct": 100.0 * changed / total}


def _object_text_by_id(deck: Path, slide_number: int) -> dict[str, str]:
    """``{id: object text}`` for slide N, so the AS shape order can be self-checked."""
    from obed_edom.iwa_kindindex import derive_kind_index

    objects, _id_to_file, _file_ids = _load_deck(deck)
    slide = objects[slide_order(objects)[slide_number - 1][0]]
    return {r["id"]: r["text"] for r in derive_kind_index(slide, objects)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="scratch dir for the probe deck + PNGs (Keynote-writable, not /tmp)")
    ap.add_argument("--live", action="store_true",
                    help="drive a throwaway deck through Keynote — RUN ONLY WHEN KEYNOTE IS FREE")
    args = ap.parse_args(argv)

    if not args.live:
        print("pure mode: no Keynote touched")
        return 0

    out = args.out
    before_dir, after_dir = out / "before", out / "after"
    shutil.rmtree(before_dir, ignore_errors=True)
    shutil.rmtree(after_dir, ignore_errors=True)
    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)
    deck_path = out / DOC_NAME
    deck_path.unlink(missing_ok=True)

    print("make-deck: three overlapping shapes (ONE back .. THREE front) …")
    _run_osascript(make_deck_applescript(deck_path, before_dir))

    if not deck_path.is_file():
        print("ABORT: not a flat .key (package save?)")
        return 2

    z_before, owned_before = read_zorder(deck_path, 1)
    labels = _object_text_by_id(deck_path, 1)
    shape_ids = [i for i in z_before if labels.get(i) in {"ONE", "TWO", "THREE"}]
    if len(shape_ids) != 3 or z_before != owned_before:
        print(f"ABORT: expected our 3 shapes among the drawables, got z={z_before} owned={owned_before}")
        return 2
    print(f"before: drawablesZOrder={z_before} ownedDrawables={owned_before}")
    print(f"shape ids: {[(i, labels[i]) for i in shape_ids]}")

    # The default theme's slide 1 carries its own placeholder drawables (title/body/etc);
    # rotate only OUR shapes' slots, leaving placeholders exactly where they are.
    new_order = permute_front_within(z_before, shape_ids)
    print(f"permute_front_within -> {new_order}")

    expected_front_id = [i for i in new_order if i in shape_ids][-1]
    expected_front = labels[expected_front_id]

    result = reorder_slide_zorder(deck_path, 1, new_order)
    if result.get("refused"):
        print(f"PATCH REFUSED: {result.get('reason')}")
        return 2
    print(f"PATCH: member={result['member']} obj_diffs={result['obj_diffs']} "
          f"header_diffs={result['header_diffs']} value_clean={result['value_clean']}")

    print("verify: close -> open -> read AS shape order -> export -> save -> close …")
    shape_order = _run_osascript(verify_applescript(deck_path, after_dir))
    print(f"AS every-shape object text order (question 3): {shape_order}  "
          f"(expected front-most, offline: {expected_front!r})")

    z_after, owned_after = read_zorder(deck_path, 1)
    print(f"after save: drawablesZOrder={z_after} ownedDrawables={owned_after}")
    print(f"save kept the patch (question 2): "
          f"{z_after == new_order and owned_after == new_order}")

    diff = _pixel_diff(before_dir, after_dir)
    print(f"before/after pixel diff (question 1): {diff}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
