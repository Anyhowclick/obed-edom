"""Per-slide, per-build-stage PNG export (d5, offline half): stage-count derivation,
`<basename>.NNN.png` reconstruction, the export AppleScript, and alpha validation.

The exporter (d5b) is `export_stage_pngs` pointed at any 1920x1080 DSK deck; it
reuses `dsk_live.LiveBatch` for the operator safety rails and never imports
`dsk_movie_export`, `dsk_assemble`, or `cli` (see SKILL.md ownership split).
Offline helpers (`stage_counts`, `stage_name`, `reconstruct`, `build_stage_script`,
`validate_alpha`, `write_manifest`) never touch Keynote. Must not import `web.*`.
"""
from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from obed_edom import dsk_live
from obed_edom.dsk_live import (
    DEFAULT_RSS_LIMIT_BYTES,
    LiveBatch,
    _applescript_string_list,
    _as_escape,
    _ERROR_RE,
    _keynote_tell,
    _keynote_terms,
    _osascript_path,
    guard_out_dir,
)
from obed_edom.iwa_builds import _build_effect_animtype, _ref_id, deck_builds
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.offline_inspect import offline_wall_payload

DEFAULT_TRANSPARENT_LAYOUT_NAMES: tuple[str, ...] = ("Blank", "BLANK", "blank")
EXPECTED_GEOMETRY: tuple[int, int] = (1920, 1080)
_STAGE_NAME_RE = re.compile(r"\.(\d+)\.[^.]+$")


@dataclass(frozen=True)
class StageAsset:
    slide: int
    stage_index: int
    path: Path
    width: int
    height: int
    alpha_ok: bool
    bg_alpha_max: int
    content_alpha_frac: float
    transparent_frac: float
    source_name: str


class StageCountAmbiguous(ValueError):
    pass


class StageCountMismatch(ValueError):
    pass


def stage_counts(
    deck: Path, slides: Sequence[int], *, deck_obj: Any = None, allow_automatic: bool = False
) -> dict[int, int]:
    """`{slide: referent_chunk_count + 1}`. Derived from each slide's own raw
    `KN.SlideArchive.buildChunks` -- Keynote's render timeline (D8) -- rather than
    `iwa_builds.deck_builds()["builds"]`, which drops builds whose drawable does not
    resolve to a top-level member. Keynote emits one stage PNG per click, and a
    chunk's `referent` flag marks whether it starts a new click; a chunk with
    `referent` False is chained onto the previous click's chunk. Refuses
    (`StageCountAmbiguous`) wherever a `buildChunks` entry does not resolve to a
    `KN.BuildChunkArchive` object, naming the slide (and any movie-start builds,
    resolved cheaply via each referent chunk's own `build` ref).

    Also refuses (unless `allow_automatic=True`) any slide where a referent chunk's
    raw `automatic` field is `True` -- Keynote may run that build after the slide's
    transition rather than on a click, and it is unproven offline whether it still
    consumes a stage PNG."""
    deck_obj = deck_obj if deck_obj is not None else _load_deck(deck)
    objects = deck_obj[0]
    slide_ids = [sid for sid, _skipped in slide_order(objects)]
    counts: dict[int, int] = {}
    ambiguous: list[int] = []
    movie_start: list[str] = []
    automatic: list[int] = []
    for n in slides:
        if n < 1 or n > len(slide_ids):
            raise StageCountAmbiguous(f"Slide {n} not found in slide order (deck has {len(slide_ids)} slides)")
        slide = objects.get(slide_ids[n - 1]) or {}
        chunk_refs = slide.get("buildChunks") or []
        referent_count = 0
        slide_ambiguous = False
        slide_automatic = False
        for ref in chunk_refs:
            chunk = objects.get(_ref_id(ref) or "")
            if chunk is None or chunk.get("_pbtype") != "KN.BuildChunkArchive":
                slide_ambiguous = True
                continue
            if not chunk.get("referent"):
                continue
            referent_count += 1
            if chunk.get("automatic"):
                slide_automatic = True
            build = objects.get(_ref_id(chunk.get("build")) or "")
            if build is not None:
                effect, _animation_type = _build_effect_animtype(build)
                if isinstance(effect, str) and "movie-start" in effect.lower():
                    movie_start.append(f"slide {n} build {_ref_id(chunk.get('build'))}")
        if slide_ambiguous:
            ambiguous.append(n)
        if slide_automatic and not allow_automatic:
            automatic.append(n)
        counts[n] = referent_count + 1
    if ambiguous:
        detail = f"; movie-start builds: {', '.join(movie_start)}" if movie_start else ""
        raise StageCountAmbiguous(
            f"Stage count undecidable offline on slides {ambiguous} "
            f"(buildChunks entries unresolved to KN.BuildChunkArchive){detail}"
        )
    if automatic:
        raise StageCountAmbiguous(
            f"Slides {automatic} have a referent build chunk with automatic=True "
            "(runs after the transition, not on a click); unproven whether Keynote "
            "still emits a stage PNG for it. Pass allow_automatic=True to proceed unverified."
        )
    return counts


def stage_name(stem: str, slide: int, stage: int) -> str:
    return f"{stem}.{slide:03d}.{stage:02d}.png"


def reconstruct(
    files: Sequence[Path], slides: Sequence[int], expected: Mapping[int, int]
) -> list[tuple[int, int, Path]]:
    """Attributes flat, 1-based sequential `<basename>.NNN.png` exports to `(slide,
    stage_index, path)` (`stage_index` 1-based) by walking `slides` ascending and
    consuming `expected[slide]` files per slide, in export order. Raises
    `StageCountMismatch` if the total file count disagrees with the sum of
    `expected`, or if the extracted NNN indices are not exactly the unique set
    `1..len(files)` (duplicates or gaps)."""
    ordered_slides = sorted(set(slides))
    total_expected = sum(expected[n] for n in ordered_slides)
    if len(files) != total_expected:
        per_slide = {n: expected[n] for n in ordered_slides}
        raise StageCountMismatch(
            f"Expected {total_expected} stage PNGs (per-slide {per_slide}), got {len(files)}"
        )

    def _sort_key(path: Path) -> int:
        match = _STAGE_NAME_RE.search(path.name)
        if not match:
            raise StageCountMismatch(f"Stage PNG name not numbered: {path.name}")
        return int(match.group(1))

    indices = [_sort_key(p) for p in files]
    if sorted(indices) != list(range(1, len(indices) + 1)):
        raise StageCountMismatch(
            f"Stage PNG indices are not exactly 1..{len(indices)} (duplicates or gaps): {sorted(indices)}"
        )

    sorted_files = [p for _, p in sorted(zip(indices, files))]
    out: list[tuple[int, int, Path]] = []
    cursor = 0
    for n in ordered_slides:
        count = expected[n]
        for stage in range(1, count + 1):
            out.append((n, stage, sorted_files[cursor]))
            cursor += 1
    return out


def stage_folder(stages_root: Path, slide: int) -> Path:
    return stages_root / f"stage_{slide:03d}"


def build_stage_script(
    scratch: Path,
    kept_slides: Sequence[int],
    total_slides: int,
    stages_root: Path,
    *,
    transparent_layout_names: Sequence[str] | None = None,
    layout_template: Path | None = None,
    unskip_all: bool = False,
) -> str:
    """One AppleScript, one open document: delete non-target slides descending, then
    for each of `kept_slides` in turn -- skip every other kept slide, unskip the
    target, wipe and recreate that slide's own folder under `stages_root`
    (`stage_folder`) with a shell `rm -rf && mkdir -p` so every osascript attempt
    (LiveBatch retries by re-running this same script) starts from an empty folder,
    then `export ... as slide images {all stages:true, skipped slides:false}` into
    it, then re-skip the target before moving to the next slide. Per-slide export
    means each folder's flat `<prefix>.NNN.png` sequence can only belong to that one
    slide -- no cross-slide attribution. When `transparent_layout_names` is `None`
    (default), layouts are left untouched -- no layout import, no `base layout`
    assignment. Passing names emits the import/apply block. `unskip_all` clears the
    `skipped` flag on the (already-filtered) kept slides before the per-slide loop.
    Each kept slide's own `skipped` flag is captured before any toggling and
    restored once the per-slide loop finishes, on both the success and the
    on-error path."""
    keep = sorted(set(kept_slides))
    stem_name = _as_escape(scratch.stem)
    doc_name = _as_escape(scratch.name)
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  with timeout of 3600 seconds",
        "    activate",
        "    try",
        f'      close (every document whose name is "{stem_name}" or name is "{doc_name}") saving no',
        "      delay 0.3",
        "    end try",
        f'    set theFile to POSIX file "{_as_escape(str(scratch))}"',
        "    set theDoc to open theFile",
        "    delay 8",
        f'    if (name of theDoc) is not "{stem_name}" and (name of theDoc) is not "{doc_name}" then',
        '      error "scratch document name mismatch"',
        "    end if",
        "    tell theDoc",
        f"      set keepList to {{{', '.join(str(n) for n in keep)}}}",
        f"      repeat with i from {total_slides} to 1 by -1",
        "        if keepList does not contain i then delete slide i of theDoc",
        "      end repeat",
    ]
    if transparent_layout_names is not None:
        approved_names = _applescript_string_list(transparent_layout_names)
        lines += [
            '      set blackLayoutName to ""',
            f"      set approvedBlackNames to {approved_names}",
            "      repeat with lay in slide layouts of theDoc",
            "        set lname to (name of lay as text)",
            "        ignoring case",
            '          if blackLayoutName is "" and lname is in approvedBlackNames then set blackLayoutName to lname',
            "        end ignoring",
            "      end repeat",
            "      set donorSlide to missing value",
        ]
        if layout_template is not None:
            lines += dsk_live.layout_import_lines("theDoc", "approvedBlackNames", layout_template)
        lines += [
            '      if blackLayoutName is "" then',
            '        error "no transparent layout resolvable in the deck or layout_template"',
            "      end if",
            "      set targetLayout to missing value",
            "      repeat with lay in slide layouts of theDoc",
            "        if (name of lay as text) is blackLayoutName then",
            "          set targetLayout to lay",
            "          exit repeat",
            "        end if",
            "      end repeat",
            '      if targetLayout is missing value then error "resolved layout name not found in theDoc"',
            "      repeat with s in slides of theDoc",
            "        if s is not donorSlide then set base layout of s to targetLayout",
            "      end repeat",
            "      if donorSlide is not missing value then delete donorSlide",
        ]
    lines += [
        "      set slideRefs to {}",
        "      repeat with i from 1 to (count of slides of theDoc)",
        "        set end of slideRefs to slide i of theDoc",
        "      end repeat",
        "      set origSkipped to {}",
        "      repeat with s in slideRefs",
        "        set end of origSkipped to (skipped of s)",
        "      end repeat",
    ]
    if unskip_all:
        lines += [
            "      repeat with s in slideRefs",
            "        set skipped of s to false",
            "      end repeat",
        ]
    lines += ["      try"]
    for ordinal, n in enumerate(keep, start=1):
        folder = stage_folder(stages_root, n)
        folder_posix = _as_escape(str(folder))
        lines += [
            f"        repeat with j from 1 to (count of slideRefs)",
            f"          set skipped of (item j of slideRefs) to (j is not {ordinal})",
            "        end repeat",
            f'        do shell script "rm -rf " & quoted form of "{folder_posix}" & " && mkdir -p " & quoted form of "{folder_posix}"',
            "        try",
            f'          export theDoc to POSIX file "{folder_posix}" as slide images with properties '
            "{image format:PNG, all stages:true, skipped slides:false}",
            "        on error errMsg number errNum",
            f'          log ("ERR" & tab & "{n}" & tab & errNum & tab & errMsg)',
            "          error errMsg number errNum",
            "        end try",
            f'        log ("OBED" & tab & "{n}" & tab & ((current date) as string))',
        ]
    lines += [
        "      on error errMsg number errNum",
        "        repeat with j from 1 to (count of slideRefs)",
        "          set skipped of (item j of slideRefs) to (item j of origSkipped)",
        "        end repeat",
        "        error errMsg number errNum",
        "      end try",
        "      repeat with j from 1 to (count of slideRefs)",
        "        set skipped of (item j of slideRefs) to (item j of origSkipped)",
        "      end repeat",
        "    end tell",
        "    try",
        "      close theDoc saving no",
        "    end try",
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def validate_alpha(
    png: Path, *, expected_size: tuple[int, int], min_transparent_frac: float = 0.05
) -> tuple[bool, int, float, float]:
    """`(alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac)`. `RGBA` and
    `expected_size` are required, else raises. `transparent_frac` is the fraction of
    the whole frame that is transparent (alpha <= 2). `alpha_ok` requires
    `transparent_frac >= min_transparent_frac` (default 0.05) and a nonzero fraction
    of the interior (non-edge) pixels carrying alpha > 2 (`content_alpha_frac`).
    `bg_alpha_max`, the minimum of the four edges' own max alpha, is informational
    only -- it flags an edge-touching artefact even on a frame that otherwise clears
    `min_transparent_frac`."""
    import numpy as np

    with Image.open(png) as img:
        if img.mode != "RGBA":
            raise ValueError(f"{png}: expected RGBA, got {img.mode}")
        if img.size != tuple(expected_size):
            raise ValueError(f"{png}: expected size {expected_size}, got {img.size}")
        arr = np.array(img)

    alpha = arr[:, :, 3]
    h, w = alpha.shape
    edges = (alpha[0, :], alpha[-1, :], alpha[:, 0], alpha[:, -1])
    bg_alpha_max = min(int(edge.max()) for edge in edges)

    bg_mask = np.zeros((h, w), dtype=bool)
    bg_mask[0, :] = True
    bg_mask[-1, :] = True
    bg_mask[:, 0] = True
    bg_mask[:, -1] = True
    content_mask = ~bg_mask
    content_alpha_frac = float((alpha[content_mask] > 2).mean()) if content_mask.any() else 0.0
    transparent_frac = float((alpha <= 2).mean())
    alpha_ok = transparent_frac >= min_transparent_frac and content_alpha_frac > 0
    return alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac


def write_manifest(
    out_dir: Path,
    deck: Path,
    assets: Sequence[StageAsset],
    *,
    categories: Mapping[int, str],
    clips: Mapping[int, Path] | None = None,
    generated: str | None = None,
) -> Path:
    """`generated` is omitted from the manifest when `None` (the default) -- callers
    that need it stamped pass an ISO timestamp explicitly. Serialised with
    `sort_keys=True` so the file is byte-identical across runs of an unchanged
    export."""
    clips = clips or {}
    by_slide: dict[int, list[StageAsset]] = {}
    for asset in assets:
        by_slide.setdefault(asset.slide, []).append(asset)

    slides_out: dict[str, dict[str, Any]] = {}
    for slide, stage_assets in by_slide.items():
        stage_assets = sorted(stage_assets, key=lambda a: a.stage_index)
        entry: dict[str, Any] = {
            "category": categories.get(slide, ""),
            "stages": [
                {
                    "index": a.stage_index,
                    "file": a.path.name,
                    "source_name": a.source_name,
                    "alpha_ok": a.alpha_ok,
                    "bg_alpha_max": a.bg_alpha_max,
                    "content_alpha_frac": a.content_alpha_frac,
                    "transparent_frac": a.transparent_frac,
                    "alpha_route": "keynote-stage-png",
                }
                for a in stage_assets
            ],
        }
        clip = clips.get(slide)
        if clip is not None:
            entry["clip"] = Path(clip).name
        slides_out[str(slide)] = entry

    geometry = {"width": assets[0].width, "height": assets[0].height} if assets else {}
    manifest: dict[str, Any] = {
        "deck": str(Path(deck)),
        "geometry": geometry,
        "slides": slides_out,
    }
    if generated is not None:
        manifest["generated"] = generated
    path = Path(out_dir) / "manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2))
    return path


def export_stage_pngs(
    deck: Path,
    slides: Sequence[int],
    out_dir: Path,
    *,
    expected_stage_counts: Mapping[int, int],
    transparent_layout_names: Sequence[str] | None = None,
    layout_template: Path | None = None,
    exclude_items: Any = None,
    clips: Mapping[int, Path] | None = None,
    categories: Mapping[int, str] | None = None,
    rss_limit_bytes: int = DEFAULT_RSS_LIMIT_BYTES,
    include_skipped: bool = False,
    log: Callable[[str], None] = print,
) -> list[StageAsset]:
    """Exports one PNG per build stage for `slides` of `deck` into `out_dir`, named by
    `stage_name` (1-based stage index) and validated by `validate_alpha`, then writes
    `manifest.json`. Layouts are left untouched unless `transparent_layout_names` is
    passed. Refuses slides `skipped` in the offline payload unless `include_skipped`,
    and decks whose offline geometry is not `EXPECTED_GEOMETRY` (1920x1080).

    Each requested slide is exported on its own, into its own folder
    (`build_stage_script`/`stage_folder`), inside one open Keynote session; a
    folder's flat `<prefix>.NNN.png` sequence can therefore only ever belong to
    that slide, and `reconstruct` is called once per slide against it."""
    if exclude_items:
        raise NotImplementedError("exclude_items export scoping is a d6 hook")

    deck = Path(deck)
    out_dir = Path(out_dir).resolve()
    guard_out_dir(out_dir, deck)
    out_dir.mkdir(parents=True, exist_ok=True)
    slides_sorted = sorted(set(slides))
    categories = categories or {}
    clips = clips or {}

    payload = offline_wall_payload(deck)
    expected_size = (int(payload["slideWidth"]), int(payload["slideHeight"]))
    if expected_size != EXPECTED_GEOMETRY:
        raise ValueError(f"{deck}: offline geometry {expected_size} != expected {EXPECTED_GEOMETRY}")

    skipped_numbers = {s["number"] for s in payload["slides"] if s["skipped"]}
    requested_skipped = sorted(set(slides_sorted) & skipped_numbers)
    if requested_skipped and not include_skipped:
        raise ValueError(
            f"Slides {requested_skipped} are skipped in the source payload; "
            "pass include_skipped=True to export them anyway"
        )

    total_slides = len(deck_builds(deck))

    with LiveBatch(deck, out_dir, rss_limit_bytes=rss_limit_bytes, log=log) as batch:
        assert batch.scratch is not None and batch.work is not None
        stages_root = batch.work / "stages"

        script = build_stage_script(
            batch.scratch,
            slides_sorted,
            total_slides,
            stages_root,
            transparent_layout_names=transparent_layout_names,
            layout_template=layout_template,
            unskip_all=bool(requested_skipped),
        )
        script_path = _osascript_path(script, batch.work)
        proc = batch.run(script_path)

        last_error: tuple[int, str] | None = None
        for line in (proc.stderr or "").splitlines():
            match = _ERROR_RE.match(line)
            if match:
                last_error = (int(match.group(2)), match.group(3))
        if proc.returncode != 0:
            if last_error is not None:
                errnum, errmsg = last_error
                raise RuntimeError(f"Keynote stage export failed (errNum {errnum}): {errmsg}")
            raise RuntimeError(f"Keynote stage export failed: {proc.stderr}")

        assets: list[StageAsset] = []
        for slide in slides_sorted:
            folder = stage_folder(stages_root, slide)
            files = sorted(folder.glob(f"{folder.name}.*.png"))
            reconstructed = reconstruct(files, [slide], {slide: expected_stage_counts[slide]})
            for _slide, idx, src_path in reconstructed:
                dest_path = out_dir / stage_name(deck.stem, slide, idx)
                shutil.copy2(src_path, dest_path)
                alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = validate_alpha(
                    dest_path, expected_size=expected_size
                )
                width, height = expected_size
                assets.append(
                    StageAsset(
                        slide=slide,
                        stage_index=idx,
                        path=dest_path,
                        width=width,
                        height=height,
                        alpha_ok=alpha_ok,
                        bg_alpha_max=bg_alpha_max,
                        content_alpha_frac=content_alpha_frac,
                        transparent_frac=transparent_frac,
                        source_name=src_path.name,
                    )
                )

    write_manifest(out_dir, deck, assets, categories=categories, clips=clips)
    return assets
