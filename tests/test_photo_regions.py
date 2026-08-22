from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from obed_edom.diff_keynotes import compare_inspects
from obed_edom.photo_regions import (
    content_regions,
    match_regions,
    region_delta,
    _prepared_crops,
)


def _paint_chat(im: Image.Image, origin: tuple[int, int], size: tuple[int, int], *, blur=False, yellow=False) -> None:
    x, y = origin
    w, h = size
    draw = ImageDraw.Draw(im)
    draw.rectangle([x, y, x + w - 1, y + h - 1], fill=(18, 22, 28))
    mid = y + h // 2
    draw.rectangle([x + 8, y + 8, x + w - 8, mid - 8], fill=(42, 48, 58))
    draw.rectangle([x + 8, mid + 4, x + w - 8, y + h - 8], fill=(42, 48, 58))
    for row in range(12):
        yy = y + 20 + row * 16
        if yy + 8 >= mid - 8:
            break
        draw.rectangle([x + 20, yy, x + w - 28, yy + 8], fill=(230, 230, 235))
    for row in range(10):
        yy = mid + 16 + row * 16
        if yy + 8 >= y + h - 12:
            break
        draw.rectangle([x + 20, yy, x + w - 28, yy + 8], fill=(230, 230, 235))
    if yellow:
        draw.rectangle(
            [x + 6, mid, x + w - 6, y + h - 10],
            outline=(255, 220, 20),
            width=max(8, w // 40),
        )
    if blur:
        box = (x + w // 3, mid, x + w, y + h)
        patch = im.crop(box).filter(ImageFilter.GaussianBlur(radius=max(6, h // 80)))
        im.paste(patch, box[:2])


def _chat_bitmap(size: tuple[int, int], *, blur=False, yellow_right=False) -> Image.Image:
    im = Image.new("RGB", size, (10, 10, 10))
    w, h = size
    _paint_chat(im, (0, 0), (w // 2, h))
    _paint_chat(im, (w // 2, 0), (w - w // 2, h), yellow=yellow_right, blur=blur)
    return im


def _lw_items():
    return [
        {"kind": "image", "text": "", "x": 200, "y": 40, "w": 480, "h": 900, "fileName": "1.png"},
        {"kind": "image", "text": "", "x": 700, "y": 40, "w": 480, "h": 900, "fileName": "2.png"},
        {"kind": "shape", "text": "", "x": 720, "y": 80, "w": 400, "h": 300},
    ]


def _dsk_group():
    return {"kind": "group", "text": "", "x": 200, "y": 200, "w": 560, "h": 500, "childCount": 0}


def test_content_regions_cluster_and_keep_groups():
    slide = {"items": _lw_items()}
    regions = content_regions(slide, (3840, 1080))
    assert len(regions) == 1
    assert regions[0].w > 900
    grouped = {"items": [_dsk_group()]}
    dsk = content_regions(grouped, (1920, 1080))
    assert len(dsk) == 1
    assert abs(regions[0].aspect - dsk[0].aspect) / regions[0].aspect < 0.15


def test_rescaled_identical_crop_is_silent():
    src = _chat_bitmap((1000, 900), yellow_right=True)
    small = src.resize((500, 450), Image.Resampling.LANCZOS)
    delta = region_delta(src, small)
    assert not delta.flipped
    assert not delta.differing
    assert not delta.marker_blocks


def test_blur_patch_is_a_region_finding():
    clean = _chat_bitmap((500, 900))
    blurred = _chat_bitmap((500, 900), blur=True)
    delta = region_delta(clean, blurred)
    assert delta.differing
    assert "bottom" in (delta.location or "bottom") or "right" in (delta.location or "")


def test_yellow_box_is_a_marker_finding():
    clean = _chat_bitmap((500, 900))
    boxed = _chat_bitmap((500, 900), yellow_right=True)
    delta = region_delta(clean, boxed)
    assert delta.marker_blocks


def _paste_chat(dest: Image.Image, box: tuple[int, int, int, int], src: Image.Image) -> None:
    x, y, w, h = box
    dest.paste(src.resize((w, h), Image.Resampling.LANCZOS), (x, y))


def test_group_only_dsk_pairs_and_flags_blur(tmp_path: Path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    src = _chat_bitmap((980, 900), yellow_right=True)
    dirty = _chat_bitmap((980, 900), yellow_right=True, blur=True)
    lw = Image.new("RGB", (3840, 1080), (8, 8, 8))
    dsk = Image.new("RGB", (1920, 1080), (8, 8, 8))
    _paste_chat(lw, (200, 40, 980, 900), src)
    _paste_chat(dsk, (200, 200, 560, 500), dirty)
    lw.save(left_dir / "slide-001.png")
    dsk.save(right_dir / "slide-001.png")
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": _lw_items()}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [_dsk_group()]}],
    }
    result = compare_inspects(
        left,
        right,
        left_dir,
        right_dir,
        tmp_path / "heat",
        left_label="LW",
        right_label="DSK",
        use_ocr=False,
    )
    pair = result["pairs"][0]
    assert pair.get("leftNumber") == 1
    assert pair.get("rightNumber") == 1
    rules = [f.rule for f in result["flags"] if f.category == "diff"]
    assert "photo.region" in rules
    region = next(f for f in result["flags"] if f.rule == "photo.region")
    assert region.evidence


def test_identical_group_pair_is_silent(tmp_path: Path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    src = _chat_bitmap((980, 900), yellow_right=True)
    lw = Image.new("RGB", (3840, 1080), (8, 8, 8))
    dsk = Image.new("RGB", (1920, 1080), (8, 8, 8))
    _paste_chat(lw, (200, 40, 980, 900), src)
    _paste_chat(dsk, (200, 200, 560, 500), src)
    lw.save(left_dir / "slide-001.png")
    dsk.save(right_dir / "slide-001.png")
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": _lw_items()}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [_dsk_group()]}],
    }
    result = compare_inspects(
        left,
        right,
        left_dir,
        right_dir,
        tmp_path / "heat",
        left_label="LW",
        right_label="DSK",
        use_ocr=False,
    )
    rules = [f.rule for f in result["flags"] if f.category == "diff"]
    assert "photo.region" not in rules
    assert "photo.marker" not in rules


def test_prepared_crops_drop_the_wall_mirror(tmp_path: Path):
    im = Image.new("RGB", (7680, 1080), (8, 8, 8))
    _paint_chat(im, (2000, 40), (480, 900))
    _paint_chat(im, (2500, 40), (480, 900))
    _paint_chat(im, (4700, 40), (480, 900))
    _paint_chat(im, (5200, 40), (480, 900))
    path = tmp_path / "wall.png"
    im.save(path)
    slide = {
        "items": [
            {"kind": "image", "x": 2000, "y": 40, "w": 480, "h": 900, "fileName": "1.png"},
            {"kind": "image", "x": 2500, "y": 40, "w": 480, "h": 900, "fileName": "2.png"},
            {"kind": "image", "x": 4700, "y": 40, "w": 480, "h": 900, "fileName": "1.png"},
            {"kind": "image", "x": 5200, "y": 40, "w": 480, "h": 900, "fileName": "2.png"},
        ]
    }
    crops = _prepared_crops(slide, path, (7680, 1080))
    assert len(crops) == 1
    dsk = {"items": [_dsk_group()]}
    dsk_im = Image.new("RGB", (1920, 1080), (8, 8, 8))
    _paint_chat(dsk_im, (200, 200), (270, 500))
    _paint_chat(dsk_im, (470, 200), (270, 500))
    dsk_crops = _prepared_crops(dsk, dsk_im, (1920, 1080))
    pairs = match_regions(crops, dsk_crops)
    assert len(pairs) == 1
