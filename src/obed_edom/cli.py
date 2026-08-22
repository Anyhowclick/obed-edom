from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from obed_edom.map_remap import resolve_slides
from obed_edom.paths import find_repo_root
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
        help="LW Keynote template (.key). Omit to skip the LW deck. At least one of --lw-template / --dsk-template is required unless a local Default Templates file exists.",
    )
    gen.add_argument(
        "--dsk-template",
        type=Path,
        help="DSK Keynote template (.key). Omit to skip the DSK deck. At least one of --lw-template / --dsk-template is required unless a local Default Templates file exists.",
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
        help="Slides to remap, e.g. 2 or 2,4-6 (default: 2).",
    )
    remap.add_argument(
        "--from-slide",
        type=int,
        dest="range_from",
        help="First slide, or the only slide. Omit for every slide. Prefer --slides for gaps.",
    )
    remap.add_argument(
        "--to-slide",
        type=int,
        dest="range_to",
        help="Last slide (defaults to --from-slide).",
    )
    remap.add_argument("--no-export", action="store_true", help="Skip PNG preview export after remap.")
    remap.add_argument(
        "--include-lists",
        action="store_true",
        help=(
            "Bring church-name lists across, resized to the template sample size "
            "and placed where the CG frame is empty. Map labels come across "
            "either way; off drops the side-panel name columns."
        ),
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
        try:
            result = generate(
                args.docx,
                make_keynote=not args.no_keynote,
                check_visuals=not args.no_keynote and not args.no_contrast,
                lw_template=args.lw_template,
                dsk_template=args.dsk_template,
                only_provided=args.lw_template is not None or args.dsk_template is not None,
            )
        except FileNotFoundError as exc:
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
    return 2


def _run_remap(args: argparse.Namespace) -> int:
    from obed_edom.remap_keynote import remap_and_inspect, remap_keynote

    source = Path(args.keynote).expanduser()
    if not source.exists():
        print(f"File not found: {source}", file=sys.stderr)
        return 1
    dest = Path(args.out).expanduser() if args.out else find_repo_root() / "output" / f"{source.stem}_CG.key"
    template = args.template or args.gold
    if template is None:
        print("CG template .key is required (--template CG_Template.key).", file=sys.stderr)
        return 1
    template = Path(template).expanduser()
    if not template.exists():
        print(f"CG template not found: {template}", file=sys.stderr)
        return 1
    try:
        # No selection means the whole deck. It used to mean slide 2 only, from
        # when the map lived there by convention.
        slide_range = resolve_slides(
            spec=getattr(args, "slides", None),
            range_from=args.range_from,
            range_to=args.range_to,
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
            include_lists=args.include_lists,
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
            include_lists=args.include_lists,
            export_dir=export_dir,
            source_previews=source_previews,
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
