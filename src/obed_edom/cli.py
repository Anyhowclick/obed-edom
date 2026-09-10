from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from pathlib import Path

from obed_edom.map_remap import parse_slide_spec, resolve_slides
from obed_edom.paths import find_repo_root, output_root
from obed_edom.pipeline import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="obed-edom",
        description="Generate LW and DSK Keynote decks plus a cued outline from semantic layout cues.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Parse an outline and build Keynote decks.")
    gen.add_argument("docx", type=Path, help="Path to the sermon/offering .docx")
    gen.add_argument(
        "--no-keynote",
        action="store_true",
        help="Parse, map, and write review.pdf only (no Keynote.app).",
    )
    gen.add_argument(
        "--no-contrast",
        action="store_true",
        help="Skip PNG export and contrast checks.",
    )
    gen.add_argument(
        "--lw-template",
        type=Path,
        help="LW Keynote template (.key). Omit to skip the LW deck. At least one of --lw-template / --dsk-template is required (unless --no-keynote).",
    )
    gen.add_argument(
        "--dsk-template",
        type=Path,
        help="DSK Keynote template (.key). Omit to skip the DSK deck. At least one of --lw-template / --dsk-template is required (unless --no-keynote).",
    )
    dash = sub.add_parser("dashboard", help="Run the local operator dashboard.")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--no-browser", action="store_true")
    remap = sub.add_parser(
        "remap",
        help="Copy a wall Keynote and remap map + pins into a 1920×1080 CG deck.",
    )
    remap.add_argument("keynote", type=Path, help="Source LW/FW .key (typically 7680×1080).")
    remap.add_argument(
        "--template",
        type=Path,
        help="Required 16:9 CG template (Empty_Map.key). Its slide layouts are copied onto the wall copy; object positions teach the crop.",
    )
    remap.add_argument("--gold", type=Path, help="Deprecated alias for --template.")
    remap.add_argument("--out", type=Path, help="Destination .key (default: output/<stem>_CG.key).")
    remap.add_argument(
        "--slides",
        dest="slides",
        help="Slides to remap, e.g. 2 or 2,4-6 (default: 2). Counted by document position, including any slides set to Skip Slide, so these are not the numbers Keynote's navigator shows on a deck that skips any. The dashboard reads them the other way.",
    )
    remap.add_argument(
        "--from-slide",
        type=int,
        dest="range_from",
        help=(
            "First slide, or the only slide. Omit for every slide. Prefer "
            "--slides for gaps. Document position, as with --slides."
        ),
    )
    remap.add_argument(
        "--to-slide",
        type=int,
        dest="range_to",
        help="Last slide (defaults to --from-slide).",
    )
    remap.add_argument("--no-export", action="store_true", help="Skip PNG preview export after remap.")
    remap.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Read the remapped deck back to build off-frame/validation flags. OFF by "
            "default (recommended when the wall content is already checked): skipping it "
            "avoids a full per-object read of the output deck, and the previews come from "
            "the remap pass either way."
        ),
    )
    remap.add_argument(
        "--keep-side-panels",
        nargs="?",
        const="all",
        default=None,
        metavar="SLIDES",
        help=(
            "Keep content outside the centre wall band (church-name side panels, "
            "badges). Bare flag = every slide; '4,7' or '4-9' = those slides only."
        ),
    )
    dsk_export = sub.add_parser(
        "dsk-export-clips",
        help="Export per-slide movie clips from a wall Keynote for the DSK generator.",
    )
    dsk_export.add_argument("keynote", type=Path, help="Source FW/LW .key (7680x1080 or 3840x1080).")
    dsk_export.add_argument("--slides", required=True, help="Slides to export, e.g. 32,33 or 32-34.")
    dsk_export.add_argument("--out", type=Path, required=True, help="Destination folder for .mov clips.")
    dsk_export.add_argument(
        "--include-side",
        help="Slides to export at full wall width with side content kept, e.g. 44 or 44,46.",
    )
    dsk_export.add_argument("--codec", default="AppleProRes422LT", help="Keynote movie codec for the export.")
    dsk_export.add_argument("--fps", type=float, default=30, help="Export framerate.")
    dsk_assemble = sub.add_parser(
        "dsk-assemble",
        help="Assemble a DSK deck from a wall Keynote via copy-and-transform.",
    )
    dsk_assemble.add_argument("keynote", type=Path, help="Source FW deck, 7680x1080 wall canvas only.")
    dsk_assemble.add_argument("--out", type=Path, required=True, help="Destination .key path for the assembled deck.")
    dsk_assemble.add_argument("--slides", required=True, help="Slides to keep, e.g. 8,13,17,32 or 8-12.")
    dsk_assemble.add_argument(
        "--include-side", help="Slides to keep with side content, e.g. 8 or 8,10."
    )
    dsk_assemble.add_argument(
        "--anchor",
        action="append",
        default=[],
        help="Per-slide anchor override, e.g. 32=centre. SLIDE must be in --slides; "
        "anchor is one of centre, left, right. Repeatable.",
    )
    dsk_assemble.add_argument(
        "--clip",
        action="append",
        default=[],
        help="Per-slide clip path, e.g. 32=/path/to/clip.mov. SLIDE must be in --slides; "
        "path must exist and end in .mov. Repeatable.",
    )
    dsk_assemble.add_argument(
        "--reference-deck", type=Path, help="Reference deck to derive the centre band from."
    )
    dsk_assemble.add_argument(
        "--layout",
        choices=("preserve", "import"),
        default="import",
        help="import (default): always import the alpha-safe layout named --layout-name "
        "from the layout template -- a full-canvas drawable on a kept slide's own layout "
        "exports opaque even off an alpha-native PNG stage export. preserve: leave kept "
        "slides' base layouts untouched.",
    )
    dsk_assemble.add_argument(
        "--layout-name",
        default=None,
        help="Override the imported layout's name (default: 'Blank Black').",
    )
    dsk_assemble.add_argument(
        "--stroke-min-refs", type=int, default=1, help="Minimum refs for the card-border stroke classifier."
    )
    dsk_assemble.add_argument(
        "--text-fit",
        choices=("warn", "shrink"),
        default="warn",
        help="warn (default): log an overflow for a mixed-run text box that autosizes past "
        "its fitted band, leave it for the operator to adjust. shrink: also set that box's "
        "size to its largest source run size, flattening run sizes to fit.",
    )
    remap.add_argument(
        "--source-previews",
        help=(
            "Folder of exported wall slide images. Used to measure where the CG is "
            "empty so loose text lands off the artwork. Optional: a cached inspect "
            "of the same deck is used when available, else packing falls back to "
            "the old right-to-left fill."
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "generate":
        if not args.docx.exists():
            print(f"File not found: {args.docx}", file=sys.stderr)
            return 1
        if args.docx.suffix.lower() != ".docx":
            print(f"Generate expects a .docx outline, got {args.docx.name}", file=sys.stderr)
            return 1
        try:
            result = generate(
                args.docx,
                make_keynote=not args.no_keynote,
                check_visuals=not args.no_keynote and not args.no_contrast,
                lw_template=args.lw_template,
                dsk_template=args.dsk_template,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Output: {result.output_dir}")
        print(f"Review: {result.review_path}")
        if result.lw_key:
            print(f"LW:     {result.lw_key}")
        if result.dsk_key:
            print(f"DSK:    {result.dsk_key}")
        if result.cued_docx:
            print(f"Cued:   {result.cued_docx}")
        warn = [f for f in result.flags if f.severity in {"warning", "error"}]
        print(f"Slides: {len(result.lw_slides)} LW, {len(result.dsk_slides)} DSK")
        print(f"Flags:  {len(warn)} warning/error, {len(result.flags)} total")
        return 0

    if args.command == "dashboard":
        return _run_dashboard(args.host, args.port, open_browser=not args.no_browser)

    if args.command == "remap":
        return _run_remap(args)

    if args.command == "dsk-export-clips":
        return _run_dsk_export_clips(args)

    if args.command == "dsk-assemble":
        return _run_dsk_assemble(args)
    return 2


def _run_dsk_export_clips(args: argparse.Namespace) -> int:
    from obed_edom.dsk_movie_export import CODECS, export_slide_clips, fps_enum_name

    source = Path(args.keynote).expanduser()
    if not source.exists():
        print(f"File not found: {source}", file=sys.stderr)
        return 1
    if args.codec not in CODECS:
        print(f"Unsupported --codec {args.codec!r}; expected one of {sorted(CODECS)}", file=sys.stderr)
        return 1
    try:
        fps_enum_name(args.fps)
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    try:
        slide_numbers = sorted(parse_slide_spec(args.slides) or ())
        include_side = set(parse_slide_spec(args.include_side) or ()) if args.include_side else set()
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    if not slide_numbers:
        print("No slides given (--slides).", file=sys.stderr)
        return 1

    out_dir = Path(args.out).expanduser()
    t0 = time.monotonic()
    try:
        results = export_slide_clips(
            source,
            slide_numbers,
            out_dir,
            include_side=include_side,
            codec=args.codec,
            fps=args.fps,
            log=print,
        )
    except Exception as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    for r in results:
        print(
            f"slide {r.slide}: {r.path} {r.width}x{r.height} @ {r.duration_s:.2f}s "
            f"(scratch {r.scratch_width}px, {r.wall_s:.1f}s wall)"
        )
    print(f"Total wall time: {time.monotonic() - t0:.1f}s")
    return 0


_DSK_ASSEMBLE_ANCHORS = frozenset({"centre", "left", "right"})


def _run_dsk_assemble(args: argparse.Namespace) -> int:
    from obed_edom.dsk_assemble import (
        DEFAULT_LAYOUT_TEMPLATE,
        DEFAULT_TRANSPARENT_LAYOUT_NAMES,
        AssemblyRefusal,
        SlideDecision,
        assemble_dsk_deck,
    )
    from obed_edom.offline_inspect import offline_wall_payload

    source = Path(args.keynote).expanduser()
    if not source.exists():
        print(f"File not found: {source}", file=sys.stderr)
        return 1
    try:
        slide_numbers = sorted(parse_slide_spec(args.slides) or ())
        include_side = set(parse_slide_spec(args.include_side) or ()) if args.include_side else set()
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    if not slide_numbers:
        print("No slides given (--slides).", file=sys.stderr)
        return 1

    try:
        payload = offline_wall_payload(source)
    except Exception as exc:
        print(f"Could not read source deck: {exc}", file=sys.stderr)
        return 1
    wall = (payload.get("slideWidth"), payload.get("slideHeight"))
    if wall != (7680.0, 1080.0) and wall != (7680, 1080):
        print(
            f"Source canvas is {wall[0]}x{wall[1]}; dsk-assemble requires a 7680x1080 FW deck.",
            file=sys.stderr,
        )
        return 1

    slide_count = int(payload.get("slideCount") or 0)
    out_of_range = sorted(n for n in set(slide_numbers) | include_side if not (1 <= n <= slide_count))
    if out_of_range:
        print(
            f"Bad --slides/--include-side; slide(s) {out_of_range} out of range (deck has {slide_count} slides).",
            file=sys.stderr,
        )
        return 1
    if not include_side <= set(slide_numbers):
        print(
            f"Bad --include-side; {sorted(include_side - set(slide_numbers))} not in --slides.",
            file=sys.stderr,
        )
        return 1
    if args.reference_deck:
        reference_deck_check = Path(args.reference_deck).expanduser()
        if not reference_deck_check.is_file():
            print(f"Reference deck not found: {reference_deck_check}", file=sys.stderr)
            return 1
    if args.layout == "import" and not DEFAULT_LAYOUT_TEMPLATE.is_file():
        print(f"Layout template not found: {DEFAULT_LAYOUT_TEMPLATE}", file=sys.stderr)
        return 1

    slide_set = set(slide_numbers)
    anchors: dict[int, str] = {}
    for spec in args.anchor:
        slide_text, sep, anchor = spec.partition("=")
        if not sep:
            print(f"Bad --anchor {spec!r}; expected SLIDE=anchor.", file=sys.stderr)
            return 1
        try:
            slide_no = int(slide_text)
        except ValueError:
            print(f"Bad --anchor {spec!r}; expected SLIDE=anchor.", file=sys.stderr)
            return 1
        if slide_no not in slide_set:
            print(f"Bad --anchor {spec!r}; slide {slide_no} is not in --slides.", file=sys.stderr)
            return 1
        if anchor not in _DSK_ASSEMBLE_ANCHORS:
            print(f"Bad --anchor {spec!r}; anchor must be one of {sorted(_DSK_ASSEMBLE_ANCHORS)}.", file=sys.stderr)
            return 1
        anchors[slide_no] = anchor

    clips: dict[int, Path] = {}
    for spec in args.clip:
        slide_text, sep, clip_text = spec.partition("=")
        if not sep:
            print(f"Bad --clip {spec!r}; expected SLIDE=/path/to/clip.mov.", file=sys.stderr)
            return 1
        try:
            slide_no = int(slide_text)
        except ValueError:
            print(f"Bad --clip {spec!r}; expected SLIDE=/path/to/clip.mov.", file=sys.stderr)
            return 1
        if slide_no not in slide_set:
            print(f"Bad --clip {spec!r}; slide {slide_no} is not in --slides.", file=sys.stderr)
            return 1
        clip_path = Path(clip_text).expanduser()
        if clip_path.suffix.lower() != ".mov":
            print(f"Bad --clip {spec!r}; clip path must end with .mov.", file=sys.stderr)
            return 1
        if not clip_path.is_file():
            print(f"Bad --clip {spec!r}; clip path does not exist: {clip_path}", file=sys.stderr)
            return 1
        clips[slide_no] = clip_path

    decisions = {
        n: SlideDecision(
            n, "both" if n in clips else "in_deck", anchor=anchors.get(n, "centre"), keep_side=n in include_side
        )
        for n in slide_numbers
    }

    out_path = Path(args.out).expanduser()
    reference_deck = Path(args.reference_deck).expanduser() if args.reference_deck else None
    black_layout_names = (args.layout_name,) if args.layout_name else DEFAULT_TRANSPARENT_LAYOUT_NAMES
    try:
        result = assemble_dsk_deck(
            source,
            out_path,
            decisions=decisions,
            reference_deck=reference_deck,
            clips=clips,
            log=print,
            layout_policy=args.layout,
            black_layout_names=black_layout_names,
            stroke_min_refs=args.stroke_min_refs,
            text_fit=args.text_fit,
        )
    except AssemblyRefusal as exc:
        print(f"Assembly refused: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Assembly failed: {exc}", file=sys.stderr)
        return 1

    print(f"Assembled: {result.path}")
    print(f"Slides kept: {list(result.slides_kept)}")
    print(f"Clips inserted: {result.clips_inserted}")
    print(f"Movie props: {result.movie_props}")
    print(f"Stroke: {result.stroke}")
    print(f"Builds: {result.builds}")
    print(f"Size: {result.size_bytes} bytes (source {result.source_size_bytes} bytes)")
    print(f"Wall time: {result.wall_s:.1f}s")
    if result.overflows:
        print(f"Overflows ({len(result.overflows)}):")
        for o in result.overflows:
            print(f"  - slide {o['slide']} {o['item']}: {o['height']}")
    if result.warnings:
        print(f"Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  - {w}")
    return 0


def _run_remap(args: argparse.Namespace) -> int:
    from obed_edom.remap_keynote import remap_and_inspect, remap_keynote

    source = Path(args.keynote).expanduser()
    if not source.exists():
        print(f"File not found: {source}", file=sys.stderr)
        return 1
    dest = Path(args.out).expanduser() if args.out else output_root() / f"{source.stem}_CG.key"
    template = args.template or args.gold
    if template is None:
        print("CG template .key is required (--template CG_Template.key).", file=sys.stderr)
        return 1
    template = Path(template).expanduser()
    if not template.exists():
        print(f"CG template not found: {template}", file=sys.stderr)
        return 1
    try:
        # Empty selection is the whole deck (it used to mean slide 2).
        slide_range = resolve_slides(
            spec=getattr(args, "slides", None),
            range_from=args.range_from,
            range_to=args.range_to,
        )
        keep_all = args.keep_side_panels == "all"
        side = (
            None
            if (keep_all or not args.keep_side_panels)
            else set(parse_slide_spec(args.keep_side_panels) or ())
        )
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1

    def log(message: str) -> None:
        print(message)

    source_previews = Path(args.source_previews).expanduser() if args.source_previews else None
    if source_previews and not source_previews.is_dir():
        print(f"Wall preview folder not found: {source_previews}", file=sys.stderr)
        return 1
    if args.no_export:
        info = remap_keynote(
            source,
            dest,
            template=template,
            slide_range=slide_range,
            keep_side_panels=keep_all,
            side_content_slides=side,
            source_previews=source_previews,
            log=log,
        )
    else:
        export_dir = dest.parent / "previews" / dest.stem
        info = remap_and_inspect(
            source,
            dest,
            template=template,
            slide_range=slide_range,
            keep_side_panels=keep_all,
            side_content_slides=side,
            export_dir=export_dir,
            source_previews=source_previews,
            validate=args.validate,
            log=log,
        )
    print(f"Wrote {info['dest']}")
    counts = info.get("counts") or {}
    print(
        f"Applied {info.get('applied')} objects "
        f"({counts.get('map', 0)} map, {counts.get('pin', 0)} pin, {counts.get('list', 0)} list); "
        f"missed {info.get('missed')}."
    )
    score = info.get("templateScore") or info.get("goldScore")
    if score and score.get("pinRmse") is not None:
        print(f"Template pin RMSE: {score['pinRmse']} px over {score.get('pinPairs')} pairs (plan, not post-JXA).")
    return 0


def _run_dashboard(host: str, port: int, *, open_browser: bool) -> int:
    dist = find_repo_root() / "dashboard" / "dist"
    if not dist.is_dir():
        print(
            "UI bundle not found. From repo root:\n"
            "  cd dashboard && npm install && npm run build\n"
            "Or run the Vite dev server (npm run dev) against this API.",
            file=sys.stderr,
        )
    url = f"http://{host}:{port}"
    print(f"Dashboard API: {url}")
    if open_browser:
        webbrowser.open(url)
    import uvicorn

    uvicorn.run("obed_edom.web.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
