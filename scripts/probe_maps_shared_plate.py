#!/usr/bin/env python3
"""Probe: shared-plate Magic Move is a geometry delta, not a same-size raster swap.

Writes an AppleScript *file* (bundle id, with timeout): new doc, place an image,
duplicate the slide, move/scale that image (not only ``set file name``), set
Magic Move on the departing slide. ``--dry-run`` prints the script and exits 0.
Live Keynote is optional; if it is not runnable the probe skips with exit 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obed_edom.maps_keynote import (  # noqa: E402
    build_shared_plate_probe_script,
    keynote_is_available,
    run_osascript,
)
from obed_edom.paths import output_root  # noqa: E402

DEFAULT_OUT = output_root() / "maps-plate-probe"
DOC_NAME = "shared-plate.key"
IMAGE_NAME = "map BG_probe.png"
SCRIPT_NAME = "shared_plate.applescript"
WIDTH = 800
HEIGHT = 200


def write_probe_image(path: Path, width: int = WIDTH, height: int = HEIGHT) -> Path:
    """Left/right split so a pan+zoom is obvious if someone steps Magic Move."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), (20, 40, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width // 2, height], fill=(180, 40, 40))
    draw.rectangle([width // 2, 0, width, height], fill=(40, 80, 180))
    draw.rectangle([width // 4, height // 4, width * 3 // 4, height * 3 // 4], outline=(255, 255, 255), width=4)
    image.save(path, "PNG")
    return path


def build_probe(out_dir: Path) -> tuple[Path, Path, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = write_probe_image(out_dir / IMAGE_NAME)
    dest = out_dir / DOC_NAME
    script = build_shared_plate_probe_script(dest, image_path, width=WIDTH, height=HEIGHT)
    script_path = out_dir / SCRIPT_NAME
    script_path.write_text(script, encoding="utf-8")
    return dest, script_path, script


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the AppleScript and exit 0")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output folder for the probe deck")
    args = parser.parse_args(argv)
    dest, script_path, script = build_probe(args.out)
    if args.dry_run:
        print(script)
        return 0
    if not keynote_is_available():
        print("skip: Keynote is not runnable; passing --dry-run prints the script")
        return 0
    proc = run_osascript(script, script_path=script_path)
    if proc.returncode != 0:
        sys.stderr.write((proc.stderr or proc.stdout or "osascript failed") + "\n")
        return proc.returncode
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
