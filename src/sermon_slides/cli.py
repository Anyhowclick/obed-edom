from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from sermon_slides.paths import find_repo_root
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
    dash = sub.add_parser("dashboard", help="Run the local operator dashboard.")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--no-browser", action="store_true")
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

    if args.command == "dashboard":
        return _run_dashboard(args.host, args.port, open_browser=not args.no_browser)
    return 2


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

    uvicorn.run("sermon_slides.web.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
