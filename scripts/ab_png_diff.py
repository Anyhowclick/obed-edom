#!/usr/bin/env python3
"""Pixel-exact A/B PNG diff. No resizing, no thresholding, no numpy.

`diff_keynotes.visual_diff()` LANCZOS-resizes mismatched dimensions and
thresholds per-pixel deltas at 18 before counting — good for an eyeball
heatmap, useless as a verdict when the question is single-level pixel
equality. This script never resizes: differing dimensions is an immediate
FAIL. Decoded-pixel equality is the gating criterion; the SHA256 of each
file's raw bytes is printed as a secondary observation only.

Usage:
    .venv/bin/python scripts/ab_png_diff.py A.png B.png [--expect identical|different] [--heatmap OUT.png] [--label NAME]

Without --expect, the exit code is always 0 regardless of verdict; pass
--expect to make a mismatch fail the run.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from PIL import Image, ImageChops


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _differing_pixels(diff: Image.Image) -> int:
    bands = [b.point(lambda v: 0 if v == 0 else 255) for b in diff.split()]
    combined = bands[0]
    for b in bands[1:]:
        combined = ImageChops.lighter(combined, b)
    return combined.histogram()[255]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", help="first PNG")
    ap.add_argument("b", help="second PNG")
    ap.add_argument("--expect", choices=["identical", "different"], help="verdict to require; exit 1 on mismatch")
    ap.add_argument("--heatmap", help="write an eyeball heatmap PNG via diff_keynotes.visual_diff() (does not gate the verdict)")
    ap.add_argument("--label", default="AB", help="label shown in the verdict line (default AB)")
    args = ap.parse_args(argv)

    a_path, b_path = Path(args.a), Path(args.b)
    a_img = Image.open(a_path)
    b_img = Image.open(b_path)

    if a_img.size != b_img.size:
        print(f"PIXEL-DIFF: FAIL — [{args.label}] size mismatch: A={a_img.size[0]}x{a_img.size[1]} B={b_img.size[0]}x{b_img.size[1]}")
        return 1

    mode_note = ""
    if a_img.mode != b_img.mode:
        mode_note = f" (mode mismatch: A={a_img.mode} B={b_img.mode}, both converted to RGBA)"
    if a_img.mode not in ("RGB", "RGBA") or b_img.mode not in ("RGB", "RGBA") or a_img.mode != b_img.mode:
        a_img = a_img.convert("RGBA")
        b_img = b_img.convert("RGBA")

    diff = ImageChops.difference(a_img, b_img)
    max_delta = max(hi for _, hi in diff.getextrema())
    bbox = diff.getbbox(alpha_only=False)
    changed = _differing_pixels(diff)
    total = a_img.width * a_img.height

    sha_a, sha_b = _sha256(a_path), _sha256(b_path)
    size_str = f"{a_img.width}x{a_img.height}"

    if changed == 0:
        verdict = "identical"
        line = (
            f"PIXEL-DIFF: IDENTICAL — [{args.label}] {size_str} · 0 differing pixels · maxDelta {max_delta} "
            f"· sha A={sha_a[:8]}… B={sha_b[:8]}…{mode_note}"
        )
    else:
        verdict = "different"
        ratio = changed / max(1, total)
        line = (
            f"PIXEL-DIFF: DIFFERENT — [{args.label}] {size_str} · {changed} differing pixels ({ratio:.7f}) "
            f"· maxDelta {max_delta} · bbox {bbox} · sha A={sha_a[:8]}… B={sha_b[:8]}…{mode_note}"
        )

    print(line)

    if args.heatmap:
        try:
            from obed_edom.diff_keynotes import visual_diff

            visual_diff(a_path, b_path, Path(args.heatmap))
        except Exception as exc:
            print(f"heatmap write failed: {exc}", file=sys.stderr)

    if args.expect and args.expect != verdict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
