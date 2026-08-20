from pathlib import Path

from PIL import Image

from obed_edom.diff_keynotes import align_slides, compare_inspects, text_score
from obed_edom.resolve_drop import pick_drop_path


def _slide(number: int, text: str, *, master: str = "", kind: str = "text", **item) -> dict:
    rec = {"kind": kind, "text": text, **item}
    return {"number": number, "master": master, "items": [rec]}


def test_text_score_pairs_near_misses():
    assert text_score("First Love Conference", "First Loved Conference") >= 0.8
    assert text_score("John 3:16 (AMP)", "John 3:16 (MSG)") >= 0.7
    assert text_score("love and faith", "love & faith") >= 0.55
    assert text_score("1 Samuel 17:1", "Samuel 17:1") >= 0.7
    assert text_score("Your Faith", "Faith") >= 0.55
    assert text_score("", "hello") == 0.0


def test_same_type_diff_count_is_info_missing_is_warning(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            {"number": 1, "items": [{"text": "a"}]},
            {"number": 2, "items": [{"text": "b"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Copy_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "items": [{"text": "a"}]}],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="LW")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any(f.severity == "info" and "Slide count differs" in f.message for f in diffs)
    assert any(f.severity == "warning" and "Missing" in f.message for f in diffs)
    assert result["sameType"] is True
    assert not any(f.severity == "error" and f.category == "diff" for f in result["flags"])


def test_mixed_type_diff_skips_count_and_index_missing(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            {"number": 1, "items": [{"text": "hello"}]},
            {"number": 2, "items": [{"text": "extra leftover point"}]},
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "items": [{"text": "hello"}]}],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="Other"
    )
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert result["sameType"] is False
    assert not any("Slide count differs" in f.message for f in diffs)
    assert not any("Missing" in f.message for f in diffs)
    assert any("No matching Other slide" in f.message or "Unmatched LW" in f.message for f in diffs)


def test_mixed_skips_lw_title_and_flags_loved_typo(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 3,
        "slides": [
            _slide(1, "", master="TITLE"),
            _slide(2, "First Love Conference"),
            _slide(3, "Keep going"),
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            _slide(1, "First Loved Conference"),
            _slide(2, "Keep going"),
        ],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Unmatched" in f.message and "TITLE" in f.message for f in diffs)
    assert not any("slide 1" in (f.location or "") and "Missing" in f.message for f in diffs)
    loved = [f for f in diffs if "Loved" in f.message or "Love" in f.message]
    assert loved
    pair = next(p for p in result["pairs"] if p.get("rightNumber") == 1)
    assert pair["leftNumber"] == 2
    assert not any(p.get("heatPng") for p in result["pairs"])


def test_mixed_flags_known_text_mistakes(tmp_path):
    cases = [
        ("(plural)", "(Plural)"),
        ("John 3:16 (AMP)", "John 3:16 (MSG)"),
        ("love and faith", "love & faith"),
        ("1 Samuel 17:1", "Samuel 17:1"),
        ("Faith", "Your Faith"),
    ]
    for lw_text, dsk_text in cases:
        left = {
            "path": str(tmp_path / "Sermon_LW.key"),
            "slideWidth": 3840,
            "slides": [_slide(1, lw_text)],
        }
        right = {
            "path": str(tmp_path / "Sermon_DSK.key"),
            "slideWidth": 1920,
            "slides": [_slide(1, dsk_text)],
        }
        result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
        diffs = [f for f in result["flags"] if f.category == "diff"]
        assert any("Wording differs" in f.message or "Text differs" in f.message for f in diffs), (lw_text, dsk_text, diffs)


def test_mixed_does_not_full_frame_heatmap_without_images(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    Image.new("RGB", (3840, 1080), (255, 0, 0)).save(left_dir / "slide-001.png")
    Image.new("RGB", (1920, 1080), (0, 0, 255)).save(right_dir / "slide-001.png")
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [_slide(1, "Same words")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [_slide(1, "Same words")],
    }
    result = compare_inspects(left, right, left_dir, right_dir, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Visual" in f.message or "Image content" in f.message for f in diffs)
    assert not any(p.get("heatPng") for p in result["pairs"])


def test_same_type_still_index_pairs_and_heatmaps(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    heat = tmp_path / "heat"
    left_dir.mkdir()
    right_dir.mkdir()
    Image.new("RGB", (3840, 1080), (255, 0, 0)).save(left_dir / "slide-001.png")
    Image.new("RGB", (3840, 1080), (0, 0, 255)).save(right_dir / "slide-001.png")
    Image.new("RGB", (3840, 1080), (255, 0, 0)).save(left_dir / "slide-002.png")
    Image.new("RGB", (3840, 1080), (255, 0, 0)).save(right_dir / "slide-002.png")
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [_slide(1, "Same"), _slide(2, "Also same")],
    }
    right = {
        "path": str(tmp_path / "Copy_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [_slide(1, "Same"), _slide(2, "Also same")],
    }
    result = compare_inspects(left, right, left_dir, right_dir, heat, left_label="LW", right_label="LW")
    assert result["sameType"] is True
    assert result["pairs"][0]["leftNumber"] == 1
    assert result["pairs"][0]["rightNumber"] == 1
    assert result["pairs"][0].get("heatPng")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any("Photo" in f.message or "layout differs" in f.message for f in diffs)


def test_mixed_image_crop_flags_flipped_photo(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    lw = Image.new("RGB", (3840, 1080), (10, 10, 10))
    dsk = Image.new("RGB", (1920, 1080), (10, 10, 10))
    for y in range(80, 280):
        for x in range(80, 280):
            lw.putpixel((x, y), (220, 30, 30) if x < 180 else (30, 30, 220))
            dsk.putpixel((x, y), (30, 30, 220) if x < 180 else (220, 30, 30))
    lw.save(left_dir / "slide-001.png")
    dsk.save(right_dir / "slide-001.png")
    item = {"kind": "image", "text": "", "x": 80, "y": 80, "w": 200, "h": 200}
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"text": "Speaker"}, item]}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [{"text": "Speaker"}, item]}],
    }
    result = compare_inspects(left, right, left_dir, right_dir, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert result["sameType"] is False
    assert any("Photo" in f.message or "Image content" in f.message or "Visual difference" in f.message for f in diffs)
    assert result["pairs"][0].get("heatPng")


def test_small_caps_signature_diff(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            {
                "number": 1,
                "items": [{"text": "Lord", "runs": [{"text": "Lord", "smallCaps": True}]}],
            }
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            {
                "number": 1,
                "items": [{"text": "Lord", "runs": [{"text": "Lord", "smallCaps": False}]}],
            }
        ],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any("Small caps" in f.message for f in diffs)


def test_align_preserves_order_across_gap():
    left = [
        _slide(1, "", master="TITLE"),
        _slide(2, "Point one about mercy"),
        _slide(3, "A photo caption"),
        _slide(4, "Point two about grace"),
    ]
    right = [
        _slide(1, "Point one about mercy"),
        _slide(2, "Different photo"),
        _slide(3, "Point two about grace"),
    ]
    slots = align_slides(left, right)
    paired = [(li, ri) for li, ri, _ in slots if li is not None and ri is not None]
    assert paired[0] == (1, 0)
    assert paired[-1] == (3, 2)
    assert (2, 1) in paired


def test_align_does_not_zip_empty_lw_with_dsk_text():
    left = [
        {"number": 1, "items": [{"kind": "image", "text": "", "w": 100, "h": 100}]},
        {"number": 2, "items": [{"kind": "image", "text": "", "w": 100, "h": 100}]},
        _slide(3, "Amazed by the corporate anointing"),
    ]
    right = [
        _slide(1, "Book of Romans Seminar"),
        _slide(3, "Matthew 18 two of you on earth agree"),
    ]
    slots = align_slides(left, right)
    paired = [(li, ri) for li, ri, _ in slots if li is not None and ri is not None]
    assert paired == []
    unmatched_r = [ri for li, ri, _ in slots if li is None]
    assert unmatched_r == [0, 1]


def test_pk_subset_fixture_catches_known_mistakes(tmp_path):
    import json
    from pathlib import Path

    data = json.loads((Path(__file__).resolve().parent / "fixtures/diff/pk_subset.json").read_text())
    result = compare_inspects(
        data["left"], data["right"], tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK"
    )
    assert result["sameType"] is False
    diffs = [f for f in result["flags"] if f.category == "diff"]
    blob = "\n".join(f.message for f in diffs)
    assert "1 Samuel" in blob and "Samuel" in blob
    assert "(AMP)" in blob and "(MSG)" in blob
    assert "Your Faith" in blob
    assert not any("Slide count differs" in f.message for f in diffs)
    triune = next(p for p in result["pairs"] if p.get("leftNumber") == 6)
    assert triune.get("rightNumber") == 4
    assert not any("Triune" in f.message for f in diffs)


def test_gw_filename_is_lw_even_at_1920(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_PK (GW).key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [_slide(1, "", master="TITLE"), _slide(2, "Faith")],
    }
    right = {
        "path": str(tmp_path / "Sermon_PK (DSK)_with mistakes.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [_slide(1, "Your Faith")],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="Other")
    assert result["sameType"] is False
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any("Wording differs" in f.message or "Text differs" in f.message for f in diffs)
    assert not any("Slide count differs" in f.message for f in diffs)


def test_pick_drop_path_unique_and_diff_checker(tmp_path):
    a = tmp_path / "Sermon.key"
    a.write_bytes(b"abc")
    assert pick_drop_path("Sermon.key", None, [a]) == a
    other = tmp_path / "other" / "Sermon.key"
    other.parent.mkdir()
    other.write_bytes(b"abc")
    preferred = tmp_path / "Diff-Checker" / "Sermon.key"
    preferred.parent.mkdir()
    preferred.write_bytes(b"abc")
    assert pick_drop_path("Sermon.key", None, [other, preferred]) == preferred
    assert pick_drop_path("Sermon.key", None, [a, other]) is None


def test_wrap_and_ref_order_are_not_wording_diffs(tmp_path):
    from obed_edom.diff_keynotes import compare_inspects, texts_equivalent

    lw = "Genesis 11\n8 So the\xa0Lord scattered them from there over\u2028all the earth,\xa0and they stopped building the city."
    dsk = "8 So the\xa0Lord scattered them from there over all the earth,\xa0and they stopped\u2028building the city.\nGenesis 11"
    assert texts_equivalent(lw, dsk)
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [_slide(1, lw)],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [_slide(1, dsk)],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Wording" in f.message or "Text differs" in f.message for f in diffs)


def test_anagram_is_still_a_wording_diff(tmp_path):
    from obed_edom.diff_keynotes import texts_equivalent

    assert not texts_equivalent("The Lord is good", "good is The Lord")
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [_slide(1, "The Lord is good")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [_slide(1, "good is The Lord")],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    assert any("Wording differs" in f.message for f in result["flags"] if f.category == "diff")


def test_both_skipped_omitted_skip_mismatch_warned(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            {**_slide(1, "Same copy"), "skipped": True},
            {**_slide(2, "Visible verse"), "skipped": False},
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            {**_slide(1, "Same copy"), "skipped": True},
            {**_slide(2, "Visible verse"), "skipped": True},
        ],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    nums = [(p.get("leftNumber"), p.get("rightNumber")) for p in result["pairs"]]
    assert (1, 1) not in nums
    assert (2, 2) in nums
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any("skipped" in f.message.lower() for f in diffs)


def test_png_for_slide_matches_generate_style_names(tmp_path):
    from obed_edom.diff_keynotes import _png_for_slide

    seven = tmp_path / "lw.007.png"
    seven.write_bytes(b"x")
    (tmp_path / "lw.001.png").write_bytes(b"x")
    pngs = sorted(tmp_path.glob("*.png"))
    slide = {"number": 7, "index": 6}
    assert _png_for_slide(pngs, slide, 6) == seven


def test_export_applescript_uses_posix_png():
    from obed_edom.inspect import export_applescript

    script = export_applescript(Path("/tmp/Sermon.key"), Path("/tmp/previews"))
    assert "POSIX file" in script
    assert "as slide images" in script
    assert "image format:PNG" in script
    assert "saving no" in script
