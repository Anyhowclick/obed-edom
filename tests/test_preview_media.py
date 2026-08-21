from pathlib import Path

from obed_edom.inspect import preview_inspect, preview_media, preview_media_type, preview_pngs
from obed_edom.web.jobs import visual_result


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


def test_visual_result_accepts_jpegs(tmp_path: Path):
    left = tmp_path / "lw"
    right = tmp_path / "dsk"
    left.mkdir()
    right.mkdir()
    (left / "wall.001.jpg").write_bytes(b"l")
    (right / "lower.001.jpeg").write_bytes(b"r")
    result = visual_result(left, right)
    assert result["leftPngs"] == ["wall.001.jpg"]
    assert result["rightPngs"] == ["lower.001.jpeg"]
    assert result["pairs"][0]["leftPng"] == "wall.001.jpg"


def test_visual_result_accepts_keynote_jpeg_exports(tmp_path: Path):
    left = tmp_path / "Sermon_PK (GW)"
    right = tmp_path / "Sermon_PK (DSK)_with mistakes"
    left.mkdir()
    right.mkdir()
    (left / "Sermon_PK (GW).001.jpeg").write_bytes(b"l")
    (right / "Sermon_PK (DSK)_with mistakes.001.jpeg").write_bytes(b"r")
    result = visual_result(left, right)
    assert result["leftPngs"] == ["Sermon_PK (GW).001.jpeg"]
    assert result["rightPngs"] == ["Sermon_PK (DSK)_with mistakes.001.jpeg"]
    assert preview_media_type(result["leftPngs"][0]) == "image/jpeg"


def test_visual_result_accepts_mov(tmp_path: Path):
    left = tmp_path / "lw"
    right = tmp_path / "dsk"
    left.mkdir()
    right.mkdir()
    (left / "clip.mov").write_bytes(b"l")
    (right / "clip.mov").write_bytes(b"r")
    result = visual_result(left, right)
    assert result["leftPngs"] == ["clip.mov"]
    assert preview_media_type("clip.mov") == "video/quicktime"
    assert preview_media_type("wall.001.jpg") == "image/jpeg"


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
