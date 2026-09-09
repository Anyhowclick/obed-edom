from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import types
from pathlib import Path

from PIL import Image, ImageDraw

from obed_edom import watercolour as current


REFERENCE = Path("/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-020ec8c5-a735-43cb-827e-fbe9e53ece9c.png")
CHURCHES = (
    Path("/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-1e0413fe-b00f-4df9-86ee-a546a3af90a6.png"),
    Path("/var/folders/cm/y6d43l6j57s65blyxxy1ty6r0000gn/T/codex-clipboard-1f75a4ef-f1b2-4fe8-be8a-953e8da4451d.png"),
)
COEFFICIENT = "* (0.6 * busy)[:, :, None]"


def source_variant(*, no_blotch: bool = True, name: str = "watercolour_ablation_no_blotch") -> types.ModuleType:
    source_path = Path(current.__file__ or "")
    source = source_path.read_text()
    changed = source
    if no_blotch:
        assert source.count(COEFFICIENT) == 1
        changed = source.replace(COEFFICIENT, "* (0.0 * busy)[:, :, None]", 1)
        assert changed.count("* (0.0 * busy)[:, :, None]") == 1
    module = types.ModuleType(name)
    module.__file__ = str(source_path)
    sys.modules[module.__name__] = module
    exec(compile(changed, str(source_path), "exec"), module.__dict__)
    return module


def without_wobble(module: types.ModuleType) -> None:
    original = module._wobble

    def consume_and_keep(image, rng, scale):
        original(image, rng, scale)
        return image

    module._wobble = consume_and_keep


def variants() -> dict[str, types.ModuleType]:
    no_wobble = source_variant(no_blotch=False, name="watercolour_ablation_no_wobble")
    without_wobble(no_wobble)
    no_blotch = source_variant(name="watercolour_ablation_no_blotch")
    both = source_variant(name="watercolour_ablation_both")
    without_wobble(both)
    return {"current": current, "no_wobble": no_wobble, "no_blotch": no_blotch, "both": both}


def encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def labelled(image: Image.Image, label: str) -> Image.Image:
    view = image.copy()
    draw = ImageDraw.Draw(view)
    draw.rectangle((0, 0, min(view.width, len(label) * 8 + 14), 22), fill="#241f18")
    draw.text((5, 4), label, fill="#fff7e5")
    return view


def board(images: dict[str, Image.Image], crop: tuple[int, int, int, int], output: Path) -> None:
    views = [labelled(images[name].crop(crop), name) for name in images]
    width = max(view.width for view in views)
    height = max(view.height for view in views)
    canvas = Image.new("RGB", (width * 2, height * 2), "#f1dfbd")
    for index, view in enumerate(views):
        canvas.paste(view, ((index % 2) * width, (index // 2) * height))
    canvas.save(output)


def render_set(raw: bytes, modules: dict[str, types.ModuleType], output: Path) -> dict[str, Image.Image]:
    rendered: dict[str, Image.Image] = {}
    for name, module in modules.items():
        payload, _ = module.convert(raw, module.WatercolourOptions(seed=20260908))
        (output / f"{name}.png").write_bytes(payload)
        rendered[name] = Image.open(io.BytesIO(payload)).convert("RGB")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate controlled Watercolour architecture ablations.")
    parser.add_argument("--output", type=Path, default=Path("output/watercolour-architecture-ablation"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    modules = variants()
    reference = Image.open(REFERENCE).convert("RGB")
    mumbai = reference.crop((0, 0, reference.width, min(437, reference.height // 2)))
    mumbai_raw = encode(mumbai)
    mumbai_dir = args.output / "mumbai"
    mumbai_dir.mkdir(exist_ok=True)
    mumbai.save(mumbai_dir / "input.png")
    rendered = render_set(mumbai_raw, modules, mumbai_dir)
    board(rendered, (270, 20, 600, 310), mumbai_dir / "facade-board.png")
    board(rendered, (0, 0, 600, 437), mumbai_dir / "full-board.png")
    manifest: dict[str, dict[str, str]] = {"mumbai": {name: hashlib.sha256((mumbai_dir / f"{name}.png").read_bytes()).hexdigest() for name in modules}}
    for index, source in enumerate(CHURCHES, 1):
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = args.output / f"church-{index}"
        destination.mkdir(exist_ok=True)
        raw = source.read_bytes()
        Image.open(io.BytesIO(raw)).convert("RGB").save(destination / "input.png")
        render_set(raw, modules, destination)
        manifest[f"church-{index}"] = {name: hashlib.sha256((destination / f"{name}.png").read_bytes()).hexdigest() for name in modules}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
