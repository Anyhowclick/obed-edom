from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sermon_slides.pipeline import generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sermon-slides",
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
    args = parser.parse_args(argv)

    if args.command == "generate":
        if not args.docx.exists():
            print(f"File not found: {args.docx}", file=sys.stderr)
            return 1
        result = generate(
            args.docx,
            make_keynote=not args.no_keynote,
            check_visuals=not args.no_keynote and not args.no_contrast,
        )
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
