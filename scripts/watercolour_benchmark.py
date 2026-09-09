from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from obed_edom.watercolour import WatercolourOptions, convert


DEFAULT_REFERENCE = Path("/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-020ec8c5-a735-43cb-827e-fbe9e53ece9c.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the supplied pencil-and-watercolour benchmark locally.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output", type=Path, default=Path("output/watercolour-benchmark"))
    args = parser.parse_args()
    reference = Image.open(args.reference).convert("RGB")
    split = min(437, reference.height // 2)
    original = reference.crop((0, 0, reference.width, split))
    target = reference.crop((0, split, reference.width, reference.height))
    args.output.mkdir(parents=True, exist_ok=True)
    original.save(args.output / "input.png")
    target.save(args.output / "reference-target.png")
    import io

    encoded = io.BytesIO()
    original.save(encoded, "PNG")
    payload, _size = convert(encoded.getvalue(), WatercolourOptions(seed=20260908))
    (args.output / "render.png").write_bytes(payload)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
