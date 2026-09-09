from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def crop(image: Image.Image, box: tuple[int, int, int, int], label: str) -> Image.Image:
    view = image.crop(box).resize(((box[2] - box[0]) * 2, (box[3] - box[1]) * 2), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(view)
    draw.rectangle((0, 0, view.width - 1, view.height - 1), outline="#30291f", width=2)
    draw.rectangle((0, 0, min(view.width, len(label) * 7 + 12), 18), fill="#30291f")
    draw.text((5, 3), label, fill="#fff8e8")
    return view


def luma(image: Image.Image, box: tuple[int, int, int, int]) -> np.ndarray:
    rgb = np.asarray(image.crop(box).convert("RGB"), dtype=np.float32) / 255.0
    return rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = Image.open(args.before).convert("RGB")
    after = Image.open(args.after).convert("RGB")
    source = Image.open(args.input).convert("RGB")
    boxes = {
        "domes": (360, 12, 575, 190),
        "couple": (245, 360, 320, 437),
        "sky": (35, 10, 255, 140),
    }
    shirt_box = (263, 395, 280, 416)
    columns = []
    for name, box in boxes.items():
        columns.extend((crop(before, box, f"Before · {name}"), crop(after, box, f"After · {name}")))
    width = max(image.width for image in columns)
    height = sum(max(columns[index].height, columns[index + 1].height) for index in range(0, len(columns), 2))
    board = Image.new("RGB", (width * 2, height), "#f6ead0")
    y = 0
    for index in range(0, len(columns), 2):
        row_height = max(columns[index].height, columns[index + 1].height)
        board.paste(columns[index], (0, y))
        board.paste(columns[index + 1], (width, y))
        y += row_height
    args.output.parent.mkdir(parents=True, exist_ok=True)
    board.save(args.output)
    dark_source = luma(source, shirt_box) < 0.40
    shirt_before = luma(before, shirt_box)
    shirt_after = luma(after, shirt_box)
    sky_before = luma(before, boxes["sky"])
    sky_after = luma(after, boxes["sky"])
    metrics = {
        "dark_source_shirt_pixels": int(dark_source.sum()),
        "shirt_near_paper_before": float((shirt_before[dark_source] > 0.78).mean()),
        "shirt_near_paper_after": float((shirt_after[dark_source] > 0.78).mean()),
        "sky_mean_luma_delta": float(sky_after.mean() - sky_before.mean()),
    }
    args.output.with_suffix(".json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, sort_keys=True))


if __name__ == "__main__":
    main()
