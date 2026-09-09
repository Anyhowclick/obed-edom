from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image

from obed_edom.watercolour import WatercolourOptions, convert


def mumbai_payload(reference: Path) -> bytes:
    image = Image.open(reference).convert("RGB")
    crop = image.crop((0, 0, image.width, min(437, image.height // 2)))
    output = io.BytesIO()
    crop.save(output, "PNG")
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the production no-wobble renderer against approved ablation PNGs.")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--church", type=Path, action="append", required=True)
    parser.add_argument("--ablation", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260908)
    args = parser.parse_args()
    if len(args.church) != 2:
        raise SystemExit("Provide exactly two --church images")
    cases = [("mumbai", mumbai_payload(args.reference)), *[(f"church-{index}", source.read_bytes()) for index, source in enumerate(args.church, 1)]]
    for name, raw in cases:
        rendered, _ = convert(raw, WatercolourOptions(seed=args.seed))
        expected = (args.ablation / name / "no_wobble.png").read_bytes()
        if rendered != expected:
            raise SystemExit(f"{name} does not match its approved no-wobble render")
    print("No-wobble byte verification passed for Mumbai and both church photos.")


if __name__ == "__main__":
    main()
