#!/usr/bin/env python3
"""Build the digest-bound visual report for the offline text/mask feature gate."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from obed_edom.baseline import deck_digest
from obed_edom.iwa_geometry import _vertical_alignment, compose_geometry
from obed_edom.iwa_runs import _load_deck_full, slide_order
from obed_edom.iwa_text_shape import shape_style
from obed_edom.offline_inspect import _canvas_size
from scripts.offline_write_ab import TOL_TEXT_TRANSLATION, preview_manifest
from scripts.write_gate_ab import render_signature


PREVIEW_NUMBER = re.compile(r"(\d+)(?=\.png$)", re.IGNORECASE)


def preview_paths(folder: Path) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for path in folder.glob("*.png"):
        match = PREVIEW_NUMBER.search(path.name)
        if match is None:
            continue
        number = int(match.group(1))
        if number in paths:
            raise ValueError(f"duplicate preview number {number} in {folder}")
        paths[number] = path
    if not paths:
        raise ValueError(f"no numbered PNG previews in {folder}")
    return paths


def deck_records(
    path: Path,
) -> tuple[dict[int, dict[str, dict[str, Any]]], tuple[float, float]]:
    objects, _id_to_file, _file_ids, _header_refs = _load_deck_full(path, strict=True)
    style_cache: dict[str, Any] = {}
    records: dict[int, dict[str, dict[str, Any]]] = {}
    for number, (slide_id, _skipped) in enumerate(slide_order(objects), start=1):
        slide = objects.get(slide_id)
        if slide is None:
            continue
        per_id: dict[str, dict[str, Any]] = {}
        for rec in compose_geometry(slide, objects):
            obj = objects.get(rec["id"]) or {}
            text_style = shape_style(obj, objects, style_cache) if rec["kind"] == "text" else None
            per_id[rec["id"]] = {
                "id": rec["id"],
                "kind": rec["kind"],
                "x": float(rec["x"]),
                "y": float(rec["y"]),
                "w": float(rec["w"]),
                "h": float(rec["h"]),
                "sig": render_signature(rec, obj, objects),
                "horizontalAlignment": text_style.alignment if text_style else None,
                "verticalAlignment": (
                    _vertical_alignment(obj, objects) if rec["kind"] == "text" else None
                ),
            }
        records[number] = per_id
    return records, _canvas_size(objects)


def clipped_region(
    frames: list[tuple[float, float, float, float]],
    image_size: tuple[int, int],
    *,
    padding: int,
) -> tuple[int, int, int, int] | None:
    x0 = math.floor(min(frame[0] for frame in frames) - padding)
    y0 = math.floor(min(frame[1] for frame in frames) - padding)
    x1 = math.ceil(max(frame[0] + frame[2] for frame in frames) + padding)
    y1 = math.ceil(max(frame[1] + frame[3] for frame in frames) + padding)
    width, height = image_size
    clipped = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return clipped


def changed_ratio(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        raise ValueError(f"image size mismatch: {a.size} != {b.size}")
    diff = ImageChops.difference(a.convert("RGBA"), b.convert("RGBA"))
    mask = Image.new("L", diff.size)
    for channel in diff.split():
        mask = ImageChops.lighter(mask, channel)
    changed = a.width * a.height - mask.histogram()[0]
    return changed / max(a.width * a.height, 1)


def difference_support(a: Image.Image, b: Image.Image) -> Image.Image:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    red, green, blue = diff.split()
    support = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    support = support.point(lambda value: 255 if value else 0).filter(ImageFilter.MaxFilter(5))
    if support.getbbox() is not None:
        return support
    edges = a.convert("L").filter(ImageFilter.FIND_EDGES)
    support = edges.point(lambda value: 255 if value > 12 else 0).filter(ImageFilter.MaxFilter(5))
    if support.getbbox() is None:
        support = Image.new("L", a.size, 255)
    return support


def masked_difference_score(a: Image.Image, b: Image.Image, support: Image.Image) -> float:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    support_pixels = support.width * support.height - support.histogram()[0]
    if support_pixels <= 0:
        return 0.0
    return sum(ImageStat.Stat(diff, mask=support).sum) / (support_pixels * 3 * 255)


def displaced_control_score(
    source: Image.Image,
    reference: Image.Image,
    support: Image.Image,
    pixels: int,
) -> float:
    scores: list[float] = []
    for offset in ((pixels, 0), (-pixels, 0), (0, pixels), (0, -pixels)):
        shifted = reference.copy()
        shifted.paste(source, offset)
        scores.append(masked_difference_score(shifted, reference, support))
    return max(scores)


def estimated_translation(
    image_a: Image.Image,
    image_b: Image.Image,
    region: tuple[int, int, int, int],
) -> tuple[int, int, float]:
    """Estimate A→B pixel translation from phase correlation of local edge images."""
    edge_a = image_a.crop(region).convert("L").filter(ImageFilter.FIND_EDGES)
    edge_b = image_b.crop(region).convert("L").filter(ImageFilter.FIND_EDGES)
    a = np.asarray(edge_a, dtype=np.float64)
    b = np.asarray(edge_b, dtype=np.float64)
    if a.size == 0 or b.size == 0 or a.shape != b.shape:
        return (0, 0, 0.0)
    for values in (a, b):
        values -= values.mean()
        values[:2, :] = 0.0
        values[-2:, :] = 0.0
        values[:, :2] = 0.0
        values[:, -2:] = 0.0
    spectrum = np.fft.fft2(a) * np.conj(np.fft.fft2(b))
    magnitude = np.abs(spectrum)
    if not np.any(magnitude > 1e-9):
        return (0, 0, 0.0)
    spectrum /= np.maximum(magnitude, 1e-9)
    correlation = np.abs(np.fft.ifft2(spectrum))
    y, x = np.unravel_index(np.argmax(correlation), correlation.shape)
    if y > a.shape[0] // 2:
        y -= a.shape[0]
    if x > a.shape[1] // 2:
        x -= a.shape[1]
    return (-int(x), -int(y), float(correlation.max()))


def text_translation_pass(row: dict[str, Any], tolerance: float) -> bool:
    return bool(row["pass"] and float(row["translationPx"]) <= tolerance)


def autosize_left(anchor_x: float, width: float, alignment: str | None) -> float:
    if alignment == "TATvalue2":
        return anchor_x - width / 2.0
    if alignment == "TATvalue1":
        return anchor_x - width
    return anchor_x


def autosize_top(anchor_y: float, height: float, alignment: str | None) -> float:
    if alignment == "kFrameAlignTop":
        return anchor_y
    if alignment == "kFrameAlignBottom":
        return anchor_y - height
    return anchor_y - height / 2.0


def region_oracle(
    image_a: Image.Image,
    image_b: Image.Image,
    image_null_a: Image.Image,
    region: tuple[int, int, int, int],
    *,
    control_shift: int,
) -> dict[str, Any]:
    crop_a = image_a.crop(region).convert("RGBA")
    crop_b = image_b.crop(region).convert("RGBA")
    crop_null_a = image_null_a.crop(region).convert("RGBA")
    support = difference_support(crop_a, crop_b)
    actual = masked_difference_score(crop_a, crop_b, support)
    null = masked_difference_score(crop_a, crop_null_a, support)
    positive = displaced_control_score(crop_a, crop_b, support, control_shift)
    support_pixels = support.width * support.height - support.histogram()[0]
    extrema = crop_a.convert("RGB").getextrema()
    visual_span = max(high - low for low, high in extrema)
    visually_inert = (
        visual_span == 0
        and ImageChops.difference(crop_a.convert("RGB"), crop_b.convert("RGB")).getbbox()
        is None
        and ImageChops.difference(
            crop_a.convert("RGB"), crop_null_a.convert("RGB")
        ).getbbox()
        is None
    )
    controlled_pass = positive > 0.0 and actual < positive and null < positive
    return {
        "region": list(region),
        "actualRatio": actual,
        "nullRatio": null,
        "positiveRatio": positive,
        "actualToPositive": actual / positive if positive else None,
        "controlShiftPx": control_shift,
        "controlDirections": ["right", "left", "down", "up"],
        "supportPixels": support_pixels,
        "visualSpan": visual_span,
        "visuallyInert": visually_inert,
        "pass": controlled_pass or visually_inert,
    }


def region_is_visually_inert(
    image_a: Image.Image,
    image_b: Image.Image,
    image_null_a: Image.Image,
    region: tuple[int, int, int, int],
) -> bool:
    crop_a = image_a.crop(region).convert("RGB")
    crop_b = image_b.crop(region).convert("RGB")
    crop_null_a = image_null_a.crop(region).convert("RGB")
    return (
        all(low == high for low, high in crop_a.getextrema())
        and ImageChops.difference(crop_a, crop_b).getbbox() is None
        and ImageChops.difference(crop_a, crop_null_a).getbbox() is None
    )


def _images(
    number: int,
    previews_a: dict[int, Path],
    previews_b: dict[int, Path],
    previews_null_a: dict[int, Path],
) -> tuple[Image.Image, Image.Image, Image.Image]:
    image_a = Image.open(previews_a[number]).convert("RGBA")
    image_b = Image.open(previews_b[number]).convert("RGBA")
    image_null_a = Image.open(previews_null_a[number]).convert("RGBA")
    if image_a.size != image_b.size or image_a.size != image_null_a.size:
        raise ValueError(
            f"slide {number} preview size mismatch: "
            f"{image_a.size}, {image_b.size}, {image_null_a.size}"
        )
    return image_a, image_b, image_null_a


def build_report(
    deck_a: Path,
    deck_b: Path,
    preview_dir_a: Path,
    preview_dir_b: Path,
    preview_dir_null_a: Path,
    *,
    text_shift: int = 8,
    text_translation_tolerance: float = TOL_TEXT_TRANSLATION,
    crop_tolerance: float = 2.0,
) -> dict[str, Any]:
    previews_a = preview_paths(preview_dir_a)
    previews_b = preview_paths(preview_dir_b)
    previews_null_a = preview_paths(preview_dir_null_a)
    if set(previews_a) != set(previews_b) or set(previews_a) != set(previews_null_a):
        raise ValueError("A/B/null preview slide-number sets differ")

    records_a, canvas_a = deck_records(deck_a)
    records_b, canvas_b = deck_records(deck_b)
    if canvas_a != canvas_b:
        raise ValueError(f"A/B deck canvas sizes differ: {canvas_a} != {canvas_b}")
    if set(records_a) != set(records_b):
        raise ValueError("A/B deck slide-number sets differ")
    if set(records_a) != set(previews_a):
        raise ValueError("deck and preview slide-number sets differ")
    with Image.open(previews_a[min(previews_a)]) as preview:
        preview_size = preview.size
    canvas_size = tuple(int(round(value)) for value in canvas_a)
    if preview_size != canvas_size:
        raise ValueError(
            f"preview size {preview_size} is not 1:1 with deck canvas {canvas_size}"
        )

    text_rows: list[dict[str, Any]] = []
    crop_rows: list[dict[str, Any]] = []
    for number in sorted(records_a):
        image_a: Image.Image | None = None
        image_b: Image.Image | None = None
        image_null_a: Image.Image | None = None
        a_by_id = records_a[number]
        b_by_id = records_b[number]
        for obj_id in sorted(set(a_by_id) & set(b_by_id)):
            a_rec, b_rec = a_by_id[obj_id], b_by_id[obj_id]
            a_sig, b_sig = a_rec["sig"], b_rec["sig"]
            if (
                a_rec["kind"] == b_rec["kind"] == "text"
                and a_sig.get("type") == b_sig.get("type") == "autosize"
                and a_rec["w"] > 0.0
                and a_rec["h"] > 0.0
                and (b_rec["w"] == 0.0 or b_rec["h"] == 0.0)
            ):
                if image_a is None or image_b is None or image_null_a is None:
                    image_a, image_b, image_null_a = _images(
                        number, previews_a, previews_b, previews_null_a
                    )
                frame = (
                    a_rec["x"],
                    a_rec["y"],
                    a_rec["w"],
                    a_rec["h"],
                )
                projected_b = (
                    autosize_left(
                        b_rec["x"], a_rec["w"], b_rec["horizontalAlignment"]
                    ),
                    autosize_top(
                        b_rec["y"], a_rec["h"], b_rec["verticalAlignment"]
                    ),
                    a_rec["w"],
                    a_rec["h"],
                )
                region = clipped_region([frame, projected_b], image_a.size, padding=2)
                footprint_regions = [
                    clipped_region([candidate], image_a.size, padding=0)
                    for candidate in (frame, projected_b)
                ]
                if region is None:
                    row = region_oracle(
                        image_a,
                        image_b,
                        image_null_a,
                        (0, 0, image_a.width, image_a.height),
                        control_shift=text_shift,
                    )
                    row.update({"offCanvas": True, "fallbackRegion": "whole-slide"})
                else:
                    exact_regions = [candidate for candidate in footprint_regions if candidate]
                    if len(exact_regions) == 2 and all(
                        region_is_visually_inert(
                            image_a, image_b, image_null_a, candidate
                        )
                        for candidate in exact_regions
                    ):
                        row = region_oracle(
                            image_a,
                            image_b,
                            image_null_a,
                            exact_regions[0],
                            control_shift=text_shift,
                        )
                        row["checkedRegions"] = [list(candidate) for candidate in exact_regions]
                    else:
                        row = region_oracle(
                            image_a, image_b, image_null_a, region, control_shift=text_shift
                        )
                translation_x, translation_y, translation_peak = estimated_translation(
                    image_a, image_b, tuple(row["region"])
                )
                translation = max(abs(translation_x), abs(translation_y))
                row.update(
                    {
                        "translationX": translation_x,
                        "translationY": translation_y,
                        "translationPx": translation,
                        "translationPeak": translation_peak,
                    }
                )
                row["pass"] = text_translation_pass(row, text_translation_tolerance)
                row.update(
                    {
                        "slide": number,
                        "id": obj_id,
                        "frameA": list(frame),
                        "frameBProjected": list(projected_b),
                        "horizontalAlignment": b_rec["horizontalAlignment"],
                        "verticalAlignment": b_rec["verticalAlignment"],
                    }
                )
                text_rows.append(row)

            if a_sig.get("type") == b_sig.get("type") == "masked" and a_sig != b_sig:
                if image_a is None or image_b is None or image_null_a is None:
                    image_a, image_b, image_null_a = _images(
                        number, previews_a, previews_b, previews_null_a
                    )
                crop_a = tuple(float(value) for value in a_sig["crop"])
                crop_b = tuple(float(value) for value in b_sig["crop"])
                crop_delta = max(abs(x - y) for x, y in zip(crop_a, crop_b))
                region = clipped_region([crop_a, crop_b], image_a.size, padding=3)
                if region is None:
                    control_shift = 8
                    row = region_oracle(
                        image_a,
                        image_b,
                        image_null_a,
                        (0, 0, image_a.width, image_a.height),
                        control_shift=control_shift,
                    )
                    row.update({"offCanvas": True, "fallbackRegion": "whole-slide"})
                else:
                    region_width = max(region[2] - region[0], 1)
                    control_shift = max(2, min(8, math.ceil(region_width / 4)))
                    row = region_oracle(
                        image_a, image_b, image_null_a, region, control_shift=control_shift
                    )
                row.update(
                    {
                        "slide": number,
                        "id": obj_id,
                        "cropA": list(crop_a),
                        "cropB": list(crop_b),
                        "cropDeltaPx": crop_delta,
                    }
                )
                row["pass"] = bool(row["pass"] and crop_delta <= crop_tolerance)
                crop_rows.append(row)

        if image_a is not None:
            image_a.close()
        if image_b is not None:
            image_b.close()
        if image_null_a is not None:
            image_null_a.close()

    def section(rows: list[dict[str, Any]], count_key: str) -> dict[str, Any]:
        return {
            "pass": bool(rows) and all(row["pass"] for row in rows),
            "nullControl": bool(rows) and all(
                row["visuallyInert"]
                or row["nullRatio"] < row["positiveRatio"] for row in rows
            ),
            "positiveControl": bool(rows) and all(
                row["visuallyInert"] or row["positiveRatio"] > 0.0 for row in rows
            ),
            count_key: len(rows),
            "offCanvas": sum(bool(row.get("offCanvas")) for row in rows),
            "maxActualToPositive": max(
                (row["actualToPositive"] or 0.0 for row in rows), default=None
            ),
            "rows": rows,
        }

    crop = section(crop_rows, "regions")
    crop["cropTolerancePx"] = crop_tolerance
    crop["maxCropDeltaPx"] = max(
        (row["cropDeltaPx"] for row in crop_rows), default=None
    )
    text = section(text_rows, "labels")
    text["controlShiftPx"] = text_shift
    text["translationTolerancePx"] = text_translation_tolerance
    text["maxTranslationPx"] = max(
        (row["translationPx"] for row in text_rows), default=None
    )
    return {
        "version": 3,
        "oracleDigest": deck_digest(Path(__file__)),
        "canvasSize": list(canvas_size),
        "armADigest": deck_digest(deck_a),
        "armBDigest": deck_digest(deck_b),
        "armAPreviews": preview_manifest(preview_dir_a),
        "armBPreviews": preview_manifest(preview_dir_b),
        "nullAPreviews": preview_manifest(preview_dir_null_a),
        "crop": crop,
        "text": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, required=True, help="arm A .key")
    parser.add_argument("--b", type=Path, required=True, help="arm B .key")
    parser.add_argument("--previews-a", type=Path, required=True)
    parser.add_argument("--previews-b", type=Path, required=True)
    parser.add_argument("--previews-null-a", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = build_report(
        args.a, args.b, args.previews_a, args.previews_b, args.previews_null_a
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        f"text: {report['text']['labels']} labels, "
        f"max actual/control={report['text']['maxActualToPositive']:.3f}, "
        f"{'PASS' if report['text']['pass'] else 'FAIL'}"
    )
    print(
        f"crop: {report['crop']['regions']} regions, "
        f"max actual/control={report['crop']['maxActualToPositive']:.3f}, "
        f"max delta={report['crop']['maxCropDeltaPx']:.3f}px, "
        f"{'PASS' if report['crop']['pass'] else 'FAIL'}"
    )
    return 0 if report["text"]["pass"] and report["crop"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
