from pathlib import Path

from obed_edom.inspect import preview_inspect, preview_media, preview_media_type, preview_pngs


def test_preview_media_lists_jpeg_and_mov(tmp_path: Path):
    folder = tmp_path / "lw"
    folder.mkdir()
    (folder / "slide.001.jpg").write_bytes(b"j")
    (folder / "slide.002.JPEG").write_bytes(b"J")
    (folder / "slide.003.mov").write_bytes(b"m")
    (folder / "notes.txt").write_text("no")
    names = [p.name.lower() for p in preview_media(folder)]
    assert names == ["slide.001.jpg", "slide.002.jpeg", "slide.003.mov"]
    assert preview_pngs(folder) == []


def test_preview_pngs_still_png_only(tmp_path: Path):
    folder = tmp_path / "lw"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"p")
    (folder / "b.jpg").write_bytes(b"j")
    assert [p.name for p in preview_pngs(folder)] == ["a.png"]


def test_preview_media_type():
    assert preview_media_type("clip.mov") == "video/quicktime"
    assert preview_media_type("wall.001.jpg") == "image/jpeg"
    assert preview_media_type("wall.001.jpeg") == "image/jpeg"
    assert preview_media_type("wall.001.png") == "image/png"


def test_preview_inspect_uses_filename_numbers(tmp_path: Path):
    from PIL import Image

    folder = tmp_path / "lw"
    folder.mkdir()
    Image.new("RGB", (64, 36), (0, 0, 0)).save(folder / "wall.050.png")
    (folder / "clip.029.mov").write_bytes(b"mov")
    payload = preview_inspect(folder)
    assert payload["slideWidth"] == 64
    assert payload["slideHeight"] == 36
    numbers = [s["number"] for s in payload["slides"]]
    assert numbers == [29, 50]
    assert all(s["items"] == [] for s in payload["slides"])
