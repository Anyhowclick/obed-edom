#!/usr/bin/env python3
"""SUPERSEDED by D8 (``output/bank/2026-09-08/build-order/D8-build-chunks.md``):
``buildChunks``, not ``builds``, is Keynote's render timeline. This script's
default census reports the D7 metric (the ``builds`` array's key sequence), which
D8 showed is not what renders; ``WITNESS_SLIDE`` 36's ``AFTER_ORDER`` constant is
the PRE-FIX expectation (what a builds-index-ordered patch produces), not the
correct one. Left as historical/diagnostic tooling, not retargeted.

Premise probe for ``w1-build-order-nondeterminism`` (D7): does Keynote's own
RENDERING actually follow a patched ``KN.SlideArchive.builds`` array on a
NON-reuse slide? All 19 positive controls in D7 are reuse targets — this has
never been checked on a slide the writer never touches.

Three modes. Default (no Keynote): census — classify every slide's build key
sequence against source (``identical``/``reordered``/``diffset``/``empty``) and
report what a deck-wide ``plan_build_patch`` would change, using the production
functions (``iwa_builds.deck_builds``, ``iwa_builds.plan_build_patch``) verbatim.
``--patch-only``: copy + deck-wide write via the production path
(``deck_builds`` -> ``plan_build_patch`` -> ``iwa_write.patch_slide_builds``),
timed. ``--live``: copy, export the build stages of one slide before and after
the patch via ``export options``' ``all stages``/``skipped slides`` (Keynote.sdef
``Kxop``, verified present), and derive the on-screen reveal order from the PNG
stage sequence by pixel-diffing each build's target group's frame.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from obed_edom import iwa_builds, keynote_app
from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_write import patch_slide_builds

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.probe_stroke_patch import _px_per_pt  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "bank" / "probes" / "build-order-probe"
WITNESS_SLIDE = 36
BEFORE_ORDER = ("Ps Aizhen", "Ps Bob", "Caijuan", "Guo Rong")
AFTER_ORDER = ("Ps Bob", "Guo Rong", "Caijuan", "Ps Aizhen")


# ==========================================================================
# Pure: census.
# ==========================================================================
def _key_seq(slide: dict) -> list[tuple]:
    return [iwa_builds._key_of(b) for b in slide["builds"]]  # noqa: SLF001


def classify_slide(src: dict, out: dict) -> str:
    src_keys, out_keys = _key_seq(src), _key_seq(out)
    if not src_keys and not out_keys:
        return "empty"
    if Counter(src_keys) != Counter(out_keys):
        return "diffset"
    return "identical" if src_keys == out_keys else "reordered"


def census(src_by_number: dict[int, dict], out_by_number: dict[int, dict]) -> dict:
    common = sorted(set(src_by_number) & set(out_by_number))
    only_src = sorted(set(src_by_number) - set(out_by_number))
    only_out = sorted(set(out_by_number) - set(src_by_number))
    by_class: dict[str, list[int]] = {"identical": [], "reordered": [], "diffset": [], "empty": []}
    for n in common:
        by_class[classify_slide(src_by_number[n], out_by_number[n])].append(n)
    plan = iwa_builds.plan_build_patch(src_by_number, out_by_number, common)
    kept = sum(r.get("kept", 0) for r in plan["report"])
    dropped = sum(r.get("dropped", 0) for r in plan["report"])
    retimed = sum(1 for r in plan["report"] if r.get("retimed"))
    return {
        "common": common, "only_src": only_src, "only_out": only_out,
        "by_class": by_class, "kept": kept, "dropped": dropped, "retimed": retimed,
    }


def _print_census(result: dict) -> None:
    bc = result["by_class"]
    print(f"slides compared: {len(result['common'])}  "
          f"(only in source: {result['only_src']}, only in output: {result['only_out']})")
    print(f"identical={len(bc['identical'])} reordered={len(bc['reordered'])} "
          f"diffset={len(bc['diffset'])} empty={len(bc['empty'])}")
    print(f"reordered: {bc['reordered']}")
    print(f"diffset:   {bc['diffset']}")
    print(f"deck-wide plan_build_patch over the {len(result['common'])} common slides: "
          f"kept={result['kept']} dropped={result['dropped']} retimed={result['retimed']}")


# ==========================================================================
# Pure: --patch-only.
# ==========================================================================
def patch_only(deck: Path, source: Path) -> int:
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    src_by_number = iwa_builds.deck_builds(source)
    timings["read_source"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    out_by_number = iwa_builds.deck_builds(deck)
    timings["read_copy_before"] = time.perf_counter() - t0

    common = sorted(set(src_by_number) & set(out_by_number))
    t0 = time.perf_counter()
    plan = iwa_builds.plan_build_patch(src_by_number, out_by_number, common)
    timings["plan"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    patch_result = patch_slide_builds(deck, plan["plans"])
    timings["write"] = time.perf_counter() - t0

    print(f"PATCH: refused={patch_result.get('refused')} touched={len(patch_result.get('touched', []))} "
          f"applied={patch_result.get('applied')}")
    if patch_result.get("refused"):
        print(f"REFUSED: {patch_result.get('reason')}")
        print(f"copy left on disk: {deck}")
        return 2

    t0 = time.perf_counter()
    after_by_number = iwa_builds.deck_builds(deck)
    timings["reread_after"] = time.perf_counter() - t0

    changed = [n for n in common if _key_seq(out_by_number[n]) != _key_seq(after_by_number[n])]
    source_exact = sum(1 for n in common if _key_seq(after_by_number[n]) == _key_seq(src_by_number[n]))

    print(f"changed slides ({len(changed)}): {changed}")
    print(f"now source-exact: {source_exact} / {len(common)}")
    for label in ("read_source", "read_copy_before", "plan", "write", "reread_after"):
        print(f"  t[{label}] = {timings[label]:.3f}s")
    print(f"copy left on disk: {deck}")
    return 0


# ==========================================================================
# Live (--live): write but do not run here.
# ==========================================================================
def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def stage_export_applescript(
    deck_path: Path, pdf_out: Path, png_out: Path, *, doc_name: str, witness_slide: int
) -> str:
    """Close-by-name -> open -> ``document 1`` bind -> skip every slide but
    ``witness_slide`` -> export the build stages both as PDF (``all stages``,
    ``export style:IndividualSlides`` -- the primary, human-facing artifact) and
    as PNG slide images (``all stages`` -- the artifact this probe pixel-diffs;
    one Keynote session covers both so a 5.7GB deck is only opened once per
    before/after step) -> close saving no. Everything from the wrong-document
    guard through the PNG export is wrapped in its own ``try``/``on error`` so
    ``theDoc`` is closed on every path, including a mid-export failure, and the
    error still propagates to a non-zero osascript exit. Mirrors
    ``probe_stroke_patch.py``'s ``stroke_probe_applescript``."""
    key = _as_escape(str(Path(deck_path).resolve()))
    pdf = _as_escape(str(Path(pdf_out).resolve()))
    png_dir = _as_escape(str(Path(png_out).resolve()))
    app = keynote_app.bundle_id()
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
        "  try",
        f'    if name of theDoc does not start with "{doc_name}" then error '
        f'"bound wrong document: " & (name of theDoc)',
        "    set slideCount to count of slides of theDoc",
        "    repeat with i from 1 to slideCount",
        f"      if i is not {witness_slide} then set skipped of slide i of theDoc to true",
        "    end repeat",
        f'    export theDoc to POSIX file "{pdf}" as PDF with properties '
        "{all stages:true, skipped slides:false, export style:IndividualSlides}",
        f'    set pngFolder to POSIX file "{png_dir}"',
        "    export theDoc to pngFolder as slide images with properties "
        "{image format:PNG, all stages:true, skipped slides:false}",
        "  on error errMsg number errNum",
        "    close theDoc saving no",
        "    error errMsg number errNum",
        "  end try",
        "  close theDoc saving no",
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


_HARNESS_FAILURE_MARKERS = (
    "bound wrong document",  # our own stale-window guard, not Keynote refusing the file
    "not authorized", "-1743",  # Automation/TCC denial
    "syntax error", "-2741", "-2740",  # malformed AppleScript
)
_CONTENT_REFUSAL_MARKERS = ("damaged", "repair", "could not be opened", "could not export")


def _classify_export_failure(exc: RuntimeError) -> str:
    """``FALSIFIED-C`` only for text that names Keynote refusing/repairing the
    file itself; every other osascript failure (permission denial, a syntax
    slip, our own wrong-document guard, or anything unrecognised) is a harness
    failure -- INCONCLUSIVE, not evidence about the premise."""
    text = str(exc).lower()
    if any(m in text for m in _HARNESS_FAILURE_MARKERS):
        return "INCONCLUSIVE"
    if any(m in text for m in _CONTENT_REFUSAL_MARKERS):
        return "FALSIFIED-C"
    return "INCONCLUSIVE"


def _pdf_page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader  # noqa: PLC0415

    if not pdf_path.is_file():
        return 0
    return len(PdfReader(str(pdf_path)).pages)


def _stage_pngs(png_dir: Path) -> list[Path]:
    import re  # noqa: PLC0415

    from obed_edom.inspect import preview_pngs  # noqa: PLC0415

    num = re.compile(r"\d+")

    def sort_key(p: Path) -> tuple[int, ...]:
        return tuple(int(g) for g in num.findall(p.stem))

    return sorted(preview_pngs(png_dir), key=sort_key)


def _group_frames(objects: dict, slide: dict, builds: list[dict]) -> dict[str, tuple[float, float, float, float]]:
    """``{group name: (x0,y0,x1,y1)}`` for every ``kind == "group"`` build target,
    via ``derive_kind_index``'s own frame (not ``iwa_geometry``'s union — this is
    read-only pixel-region analysis, not a write)."""
    by_kind_index: dict[int, dict] = {}
    for rec in derive_kind_index(slide, objects):
        if rec["kind"] == "group":
            by_kind_index[rec["kindIndex"]] = rec

    frames: dict[str, tuple[float, float, float, float]] = {}
    for b in builds:
        if b["kind"] != "group":
            continue
        rec = by_kind_index.get(b["kindIndex"])
        if rec is None or rec["x"] is None:
            continue
        frames[b["identity"][1]] = (rec["x"], rec["y"], rec["x"] + rec["w"], rec["y"] + rec["h"])
    return frames


def _region_diff(a, b, bbox_px: tuple[float, float, float, float]) -> float:
    from PIL import ImageChops  # noqa: PLC0415

    x0, y0, x1, y1 = (max(0, int(v)) for v in bbox_px)
    x1, y1 = min(a.width, x1), min(a.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    diff = ImageChops.difference(a.crop((x0, y0, x1, y1)), b.crop((x0, y0, x1, y1))).convert("L")
    hist = diff.histogram()
    return sum(i * c for i, c in enumerate(hist)) / ((x1 - x0) * (y1 - y0))


def derive_reveal_order(
    pngs: list[Path], frames: dict[str, tuple[float, float, float, float]], px_per_pt: float
) -> list[str] | None:
    """Order the named groups revealed by pixel-diffing consecutive stage images
    against each group's frame; None (ambiguous/wrong page count) rather than a
    guess -- ``derive_deck_kind_index``'s docstring warns these frames are not
    write-precise, and AA/photo-background noise near a boundary is possible."""
    from PIL import Image  # noqa: PLC0415

    if len(pngs) != len(frames) + 1:
        return None
    images = [Image.open(p).convert("RGB") for p in pngs]
    remaining = dict(frames)
    order: list[str] = []
    for k in range(1, len(images)):
        scores = {
            name: _region_diff(images[k - 1], images[k],
                                tuple(v * px_per_pt for v in bbox))
            for name, bbox in remaining.items()
        }
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        top_name, top_score = ranked[0]
        runner_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_score <= 1.0 or (runner_score > 0 and top_score < 3 * runner_score):
            return None
        order.append(top_name)
        del remaining[top_name]
    return order


def _run_live(deck: Path, source: Path, out: Path, witness_slide: int) -> int:
    copy_deck = out / f"{deck.stem}_liveprobe.key"
    if copy_deck.resolve() == deck.resolve() or out.resolve() == deck.parent.resolve():
        print("ERROR: --out would alias --deck")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    if copy_deck.exists():
        copy_deck.unlink()
    subprocess.run(["ditto", str(deck), str(copy_deck)], check=True)
    doc_name = copy_deck.stem
    print(f"copy left on disk: {copy_deck}")

    src_by_number = iwa_builds.deck_builds(source)
    out_by_number = iwa_builds.deck_builds(copy_deck)
    plan = iwa_builds.plan_build_patch(src_by_number, out_by_number, [witness_slide])
    slide_id = out_by_number[witness_slide]["slideId"]
    planned_ids = plan["plans"][slide_id]["builds"]
    by_id = {b["buildId"]: b for b in out_by_number[witness_slide]["builds"]}
    live_before = tuple(b["identity"][1] for b in out_by_number[witness_slide]["builds"] if b["kind"] == "group")
    live_after = tuple(by_id[bid]["identity"][1] for bid in planned_ids if by_id[bid]["kind"] == "group")
    print(f"re-derived before order: {live_before}")
    print(f"re-derived after order:  {live_after}")
    if live_before != BEFORE_ORDER or live_after != AFTER_ORDER:
        print(f"MISMATCH against hardcoded constants BEFORE_ORDER={BEFORE_ORDER} "
              f"AFTER_ORDER={AFTER_ORDER} -- refusing to proceed on an unverified premise.")
        return 2

    objects, _id_to_file, _file_ids = _load_deck(copy_deck)
    order = slide_order(objects)
    slide = objects[order[witness_slide - 1][0]]
    frames = _group_frames(objects, slide, out_by_number[witness_slide]["builds"])

    before_dir, after_dir = out / "before", out / "after"
    before_pdf, after_pdf = out / "before.pdf", out / "after.pdf"
    before_png, after_png = before_dir / "png", after_dir / "png"
    for d in (before_png, after_png):
        stage_dir = d.parent
        if stage_dir.exists() and (
            not stage_dir.is_dir() or stage_dir.is_symlink()
            or set(p.name for p in stage_dir.iterdir()) - {"png"}
        ):
            raise RuntimeError(
                f"refusing to rmtree {stage_dir}: does not look like a directory this probe created")
        shutil.rmtree(stage_dir, ignore_errors=True)
        d.mkdir(parents=True)
    for pdf in (before_pdf, after_pdf):
        pdf.unlink(missing_ok=True)

    try:
        print("LIVE: pre-patch stage export …")
        _run_osascript(stage_export_applescript(
            copy_deck, before_pdf, before_png, doc_name=doc_name, witness_slide=witness_slide))
    except RuntimeError as exc:
        kind = _classify_export_failure(exc)
        if kind == "FALSIFIED-C":
            print(f"VERDICT: FALSIFIED-C (Keynote repaired or refused the file on pre-patch export)\n{exc}")
        else:
            print(f"VERDICT: INCONCLUSIVE (harness failure on pre-patch export, not a Keynote "
                  f"finding about the premise)\n{exc}")
        return 1

    n_builds = len(out_by_number[witness_slide]["builds"])
    before_pdf_pages = _pdf_page_count(before_pdf)
    before_pngs = _stage_pngs(before_png)
    print(f"before.pdf pages={before_pdf_pages} (expected {n_builds + 1}); "
          f"before PNG stages={len(before_pngs)}")
    if before_pdf_pages < n_builds + 1 and len(before_pngs) < n_builds + 1:
        print("VERDICT: INCONCLUSIVE (neither PDF nor PNG export honoured `all stages` on the "
              "pre-patch export; a human must play the slide)")
        return 1

    patch_result = patch_slide_builds(copy_deck, plan["plans"])
    print(f"PATCH: refused={patch_result.get('refused')} applied={patch_result.get('applied')}")
    if patch_result.get("refused"):
        print(f"ABORT: patch refused ({patch_result.get('reason')}) -- could be a plan bug, or "
              f"Keynote altered the on-disk copy during the pre-patch export (the skip loop dirties "
              f"the document for the export and autosave can write that to the copy); inspect "
              f"before.pdf and the copy's builds before assuming the plan is wrong")
        return 2

    try:
        print("LIVE: post-patch stage export …")
        _run_osascript(stage_export_applescript(
            copy_deck, after_pdf, after_png, doc_name=doc_name, witness_slide=witness_slide))
    except RuntimeError as exc:
        kind = _classify_export_failure(exc)
        if kind == "FALSIFIED-C":
            print(f"VERDICT: FALSIFIED-C (Keynote repaired or refused the file on post-patch export)\n{exc}")
        else:
            print(f"VERDICT: INCONCLUSIVE (harness failure on post-patch export, not a Keynote "
                  f"finding about the premise)\n{exc}")
        return 1

    after_pdf_pages = _pdf_page_count(after_pdf)
    after_pngs = _stage_pngs(after_png)
    print(f"after.pdf pages={after_pdf_pages} (expected {n_builds + 1}); "
          f"after PNG stages={len(after_pngs)}")
    if after_pdf_pages < n_builds + 1 and len(after_pngs) < n_builds + 1:
        print("VERDICT: INCONCLUSIVE (post-patch export did not honour `all stages`; "
              "a human must play the slide)")
        return 1

    try:
        reread_objects, _i2, _f2 = _load_deck(copy_deck)
    except Exception as exc:  # noqa: BLE001 -- a corrupted re-read IS the FALSIFIED-C signal
        print(f"VERDICT: FALSIFIED-C (deck failed to re-open after the round trip)\n{exc}")
        return 1
    reread_builds = iwa_builds.deck_builds(copy_deck, deck=(reread_objects, _i2, _f2))[witness_slide]["builds"]
    reread_identities = tuple(b["identity"][1] for b in reread_builds if b["kind"] == "group")
    print(f"offline re-read array (post round-trip): {reread_identities}")
    if reread_identities != live_after:
        print(f"VERDICT: INCONCLUSIVE (offline re-read after the round trip does not match the "
              f"expected post-patch array: expected {live_after}, got {reread_identities} -- this "
              f"can be the close-saving-no round trip, but the skip loop also dirties the document "
              f"for the whole export and Keynote autosave can write that in-memory state into the "
              f"disposable copy; not evidence either way about whether Keynote's renderer follows "
              f"the builds array)")
        return 1

    before_px_per_pt = _px_per_pt(objects, before_pngs[0] if before_pngs else None)
    after_px_per_pt = _px_per_pt(objects, after_pngs[0] if after_pngs else None)
    before_derived = (derive_reveal_order(before_pngs, frames, before_px_per_pt)
                       if len(before_pngs) == n_builds + 1 else None)
    after_derived = (derive_reveal_order(after_pngs, frames, after_px_per_pt)
                      if len(after_pngs) == n_builds + 1 else None)
    print(f"pixel-derived before order: {before_derived}")
    print(f"pixel-derived after order:  {after_derived}")

    if before_derived is None or tuple(before_derived) != live_before:
        print(f"VERDICT: INCONCLUSIVE (pixel method failed its own before-control: the BEFORE "
              f"deck is unpatched, so the pixel-derived order should reproduce Keynote's own "
              f"offline array for free -- derived {before_derived}, expected {live_before}; a "
              f"frame<->name mis-registration would falsely pass everything downstream, so this "
              f"is treated as fatal. Read before.pdf/after.pdf by hand.)")
        return 1

    if after_derived is None:
        print("VERDICT: INCONCLUSIVE (stage images present but the reveal order could not be "
              "robustly pixel-derived; a human must inspect before.pdf/after.pdf)")
        return 1
    after_derived_t = tuple(after_derived)
    if after_derived_t == AFTER_ORDER:
        print("VERDICT: PASS (the AFTER stage export reveals groups in source order; the "
              "pixel method's before-control also held). Read before.pdf/after.pdf regardless.")
        return 0
    if after_derived_t == BEFORE_ORDER:
        print("VERDICT: FALSIFIED-A (the AFTER stage export still reveals groups in the "
              "pre-patch order -- the builds array is not the rendering authority)")
        return 1
    print(f"VERDICT: FALSIFIED-B (the AFTER stage export reveals a third order {after_derived_t}, "
          "matching neither before nor source)")
    return 1


# ==========================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, required=True, help="finalized .key to probe")
    ap.add_argument("--source", type=Path, required=True, help="wall .key to compare/patch against")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="scratch dir for copies + exports (Keynote-writable, not /tmp)")
    ap.add_argument("--patch-only", action="store_true",
                    help="offline: ditto + deck-wide patch + re-read + timings, no Keynote")
    ap.add_argument("--live", action="store_true",
                    help="drive Keynote — RUN ONLY WHEN KEYNOTE IS FREE")
    ap.add_argument("--slide", type=int, default=WITNESS_SLIDE, help="--live witness slide")
    args = ap.parse_args(argv)

    if not args.deck.exists():
        ap.error(f"--deck not found: {args.deck}")
    if not args.source.exists():
        ap.error(f"--source not found: {args.source}")

    if args.live:
        return _run_live(args.deck, args.source, args.out, args.slide)

    if args.patch_only:
        copy_deck = args.out / f"{args.deck.stem}_buildpatch.key"
        if copy_deck.resolve() == args.deck.resolve() or args.out.resolve() == args.deck.parent.resolve():
            ap.error("--out would alias --deck")
        args.out.mkdir(parents=True, exist_ok=True)
        if copy_deck.exists():
            copy_deck.unlink()
        t0 = time.perf_counter()
        subprocess.run(["ditto", str(args.deck), str(copy_deck)], check=True)
        print(f"ditto {args.deck} -> {copy_deck}  ({time.perf_counter() - t0:.3f}s)")
        return patch_only(copy_deck, args.source)

    src_by_number = iwa_builds.deck_builds(args.source)
    out_by_number = iwa_builds.deck_builds(args.deck)
    _print_census(census(src_by_number, out_by_number))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
