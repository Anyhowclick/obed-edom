from pathlib import Path

from PIL import Image

from obed_edom.diff_keynotes import ALIGN_THRESHOLD, align_slides, compare_inspects, text_score
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
    verse = (
        "17 One day Jesus was teaching, and Pharisees and teachers of the law were sitting there. "
        "They had come from every village of Galilee and from Judea and Jerusalem."
    )
    assert text_score("3\nFaith", verse) < ALIGN_THRESHOLD
    assert text_score("3\nFaith", "Your Faith") >= ALIGN_THRESHOLD


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
    """Each documented mistake gets its own rule, not one blunt warning."""
    cases = [
        ("(plural)", "(Plural)", "text.case"),
        ("John 3:16 (AMP)", "John 3:16 (MSG)", "text.reference"),
        ("love and faith", "love & faith", "text.symbol"),
        ("1 Samuel 17:1", "Samuel 17:1", "text.reference"),
        ("Faith", "Your Faith", "text.word"),
    ]
    for lw_text, dsk_text, rule in cases:
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
        rules = [f.rule for f in result["flags"] if f.category == "diff"]
        assert rule in rules, (lw_text, dsk_text, rules)


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
    assert all(not getattr(f, "evidence", None) for f in diffs if f.rule == "photo.differs")


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
    assert any(f.message == "Photo is flipped." or "Photo is flipped" in f.message for f in diffs)
    assert result["pairs"][0].get("heatPng")
    flipped = [f for f in diffs if f.rule == "photo.flipped"]
    assert flipped
    assert flipped[0].evidence


def test_wall_duplicated_verse_is_not_a_wording_diff(tmp_path):
    from obed_edom.diff_keynotes import texts_equivalent

    lw = (
        "Genesis 1\n1 In the beginning God created the heavens and the earth.\n"
        "Genesis 1\n1 In the beginning God created the heavens and the earth."
    )
    dsk = "1 In the beginning God created the heavens and the earth.\nGenesis 1"
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
    assert not any("Wording" in f.message for f in diffs)


def _paint_split(im: Image.Image, *, flipped: bool) -> None:
    for y in range(80, 280):
        for x in range(80, 280):
            left_red = x < 180
            red = left_red if not flipped else not left_red
            im.putpixel((x, y), (220, 30, 30) if red else (30, 30, 220))


def test_extra_lw_photos_do_not_steal_flipped_match(tmp_path):
    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    item = {"kind": "image", "text": "", "x": 80, "y": 80, "w": 200, "h": 200}

    def save(folder, number, size, paint):
        im = Image.new("RGB", size, (10, 10, 10))
        paint(im)
        im.save(folder / f"slide-{number:03d}.png")

    save(left_dir, 1, (3840, 1080), lambda im: None)
    save(left_dir, 2, (3840, 1080), lambda im: [im.putpixel((x, y), (20, 180, 20)) for y in range(80, 280) for x in range(80, 280)])
    save(left_dir, 3, (3840, 1080), lambda im: _paint_split(im, flipped=False))
    save(left_dir, 4, (3840, 1080), lambda im: [im.putpixel((x, y), (180, 180, 20)) for y in range(80, 280) for x in range(80, 280)])
    save(left_dir, 5, (3840, 1080), lambda im: None)
    save(right_dir, 1, (1920, 1080), lambda im: None)
    save(right_dir, 2, (1920, 1080), lambda im: _paint_split(im, flipped=True))
    save(right_dir, 3, (1920, 1080), lambda im: None)

    photo = lambda n: {"number": n, "index": n - 1, "items": [item]}
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [_slide(1, "Alpha"), photo(2), photo(3), photo(4), _slide(5, "Omega")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [_slide(1, "Alpha"), photo(2), _slide(3, "Omega")],
    }
    result = compare_inspects(left, right, left_dir, right_dir, tmp_path / "heat", left_label="LW", right_label="DSK")
    pairs = {(p.get("leftNumber"), p.get("rightNumber")) for p in result["pairs"]}
    assert (1, 1) in pairs
    assert (5, 3) in pairs
    assert (3, 2) in pairs
    assert (2, 2) not in pairs
    flip = next(p for p in result["pairs"] if p.get("leftNumber") == 3 and p.get("rightNumber") == 2)
    msgs = [f.message for f in (flip.get("flags") or [])]
    assert any("Photo is flipped." in m for m in msgs)
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert any(f.message == "Photo is flipped." for f in diffs)


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
    # The genuine divergence names the word so the reader knows what to check.
    assert any("Lord" in f.message for f in diffs if "Small caps" in f.message)


def test_highlight_diff_ignores_verse_number_superscript():
    from obed_edom.diff_keynotes import _highlighted_run_words, _style_diff_message

    yellow = [65535, 65535, 0]
    # Both decks highlight the same phrase; DSK additionally paints the yellow
    # superscript verse number "4" — a numbering style, not word highlighting.
    lw = {"items": [{"runs": [{"text": "so that we may make a name", "color": yellow}]}]}
    dsk = {
        "items": [
            {
                "runs": [
                    {"text": "4", "color": yellow, "superscript": "kSuperscript"},
                    {"text": "so that we may make a name", "color": yellow},
                ]
            }
        ]
    }
    assert _highlighted_run_words(lw) == _highlighted_run_words(dsk)
    assert (
        _style_diff_message(
            "Highlighting differs",
            "highlights",
            _highlighted_run_words(lw),
            _highlighted_run_words(dsk),
        )
        is None
    )


def test_highlight_diff_keeps_baseline_digit():
    # superscript is an enum ("kSuperscript" / "kNoScript" / None), all truthy but
    # only "kSuperscript" is a verse/point number. A baseline (kNoScript) highlighted
    # digit is a real number in the copy, so it must NOT be excluded — highlighting it
    # is a genuine difference the checker should still catch.
    from obed_edom.diff_keynotes import _highlighted_run_words

    yellow = [65535, 65535, 0]
    slide = {"items": [{"runs": [{"text": "40", "color": yellow, "superscript": "kNoScript"}]}]}
    assert _highlighted_run_words(slide) == {"40"}
    verse = {"items": [{"runs": [{"text": "40", "color": yellow, "superscript": "kSuperscript"}]}]}
    assert _highlighted_run_words(verse) == set()  # verse number dropped


def test_highlight_diff_names_differing_words():
    from obed_edom.diff_keynotes import _highlighted_run_words, _style_diff_message

    yellow = [65535, 65535, 0]
    lw = {"items": [{"runs": [{"text": "mercy", "color": yellow}]}]}
    dsk = {"items": [{"runs": [{"text": "grace", "color": yellow}]}]}
    msg = _style_diff_message(
        "Highlighting differs",
        "highlights",
        _highlighted_run_words(lw),
        _highlighted_run_words(dsk),
    )
    assert msg is not None
    assert "mercy" in msg and "grace" in msg


def _highlight_diff(lw: dict, dsk: dict) -> str | None:
    """Reproduce the call site: filter run styles to the shared vocabulary first."""
    from obed_edom.diff_keynotes import (
        _canonical_words,
        _highlighted_run_words,
        _shared_style_words,
        _style_diff_message,
    )
    from obed_edom.inspect import slide_plain_text

    shared = _canonical_words(slide_plain_text(lw)) & _canonical_words(slide_plain_text(dsk))
    left, right = _shared_style_words(
        _highlighted_run_words(lw), _highlighted_run_words(dsk), shared
    )
    return _style_diff_message("Highlighting differs", "highlights", left, right)


def _run_item(*runs: dict) -> dict:
    return {"text": "".join(r["text"] for r in runs), "runs": list(runs)}


def test_highlight_diff_ignores_lw_only_point_title():
    # LW carries the sermon-theme point title "Faith" (yellow) on the bumper; the
    # DSK lower third never shows it. A word only one deck has is content the other
    # lacks, not a divergent highlight, so it must not raise style.highlight —
    # whether or not the verse copy happens to repeat the word (real slides 52↔35
    # fired, 53↔36 didn't; both are false positives).
    yellow = [65535, 65535, 0]
    white = [65535, 65535, 65535]

    def title(word):
        return _run_item({"text": word, "color": yellow})

    def verse(highlight, plain):
        return _run_item({"text": highlight, "color": yellow}, {"text": plain, "color": white})

    lw52 = {"items": [title("Faith"), verse("lowered", " him on his mat")]}
    dsk35 = {"items": [verse("lowered", " him on his mat")]}
    assert _highlight_diff(lw52, dsk35) is None

    lw53 = {"items": [title("Faith"), verse("When Jesus saw their faith", ", He said")]}
    dsk53 = {"items": [verse("When Jesus saw their faith", ", He said")]}
    assert _highlight_diff(lw53, dsk53) is None


def test_highlight_diff_still_flags_a_shared_word():
    # The word both decks show is highlighted on LW only — a genuine difference.
    yellow = [65535, 65535, 0]
    white = [65535, 65535, 65535]
    lw = {"items": [_run_item({"text": "mercy", "color": yellow}, {"text": " and grace", "color": white})]}
    dsk = {"items": [_run_item({"text": "mercy and grace", "color": white})]}
    msg = _highlight_diff(lw, dsk)
    assert msg is not None and "mercy" in msg


def test_bullet_prefix_is_not_a_wording_diff():
    from obed_edom.text_diff import classify_text_diff, comparable_tokens

    # A bulleted verse box extracts / OCRs the line as "•the"; folded it is "the".
    assert comparable_tokens("•the") == ["the"]
    assert comparable_tokens("·item") == ["item"]
    lw = "While the harpist was playing •the hand of the Lord came on Elisha"
    dsk = "While the harpist was playing the hand of the Lord came on Elisha"
    assert classify_text_diff(lw, dsk, "LW", "DSK") is None


def test_smallcaps_no_flag_on_text_difference_without_small_caps():
    from obed_edom.diff_keynotes import _smallcaps_words, _style_diff_message

    # Different layout/text, but neither run is small caps (real slides 57↔39).
    lw = {
        "items": [
            {
                "runs": [
                    {"text": "Spiritual", "smallCaps": False},
                    {"text": "Actions", "smallCaps": False},
                    {"text": "4", "smallCaps": False},
                ]
            }
        ]
    }
    dsk = {"items": [{"runs": [{"text": "Spiritual Actions", "smallCaps": False}]}]}
    assert _smallcaps_words(lw) == set()
    assert _smallcaps_words(dsk) == set()
    assert (
        _style_diff_message(
            "Small caps differ", "small-caps", _smallcaps_words(lw), _smallcaps_words(dsk)
        )
        is None
    )


def test_smallcaps_flag_names_the_word():
    from obed_edom.diff_keynotes import _smallcaps_words, _style_diff_message

    lw = {"items": [{"runs": [{"text": "Lord", "smallCaps": True}]}]}
    dsk = {"items": [{"runs": [{"text": "Lord", "smallCaps": False}]}]}
    msg = _style_diff_message(
        "Small caps differ", "small-caps", _smallcaps_words(lw), _smallcaps_words(dsk)
    )
    assert msg is not None
    assert "Lord" in msg


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


def test_point_title_does_not_steal_verse_slide(tmp_path):
    verse = (
        "17 One day Jesus was teaching, and Pharisees and teachers of the law were sitting there. "
        "They had come from every village of Galilee and from Judea and Jerusalem."
    )
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            _slide(1, "Hello"),
            _slide(2, "3\nFaith"),
            _slide(3, f"Luke 5\n{verse}"),
            _slide(4, "Bye"),
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            _slide(1, "Hello"),
            _slide(2, f"Your Faith\n{verse}"),
            _slide(3, "Bye"),
        ],
    }
    result = compare_inspects(left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK")
    dsk2 = next(p for p in result["pairs"] if p.get("rightNumber") == 2)
    assert dsk2.get("leftNumber") == 3
    nums = {(p.get("leftNumber"), p.get("rightNumber")) for p in result["pairs"]}
    assert (2, 2) not in nums
    assert (2, None) in nums or any(p.get("leftNumber") == 2 and p.get("rightNumber") is None for p in result["pairs"])


def test_align_title_graphic_pairs_then_skips_extra_photos():
    genesis_lw = (
        "Genesis 1\n1 In the beginning God created the heavens and the earth.\n"
        "Genesis 1\n1 In the beginning God created the heavens and the earth."
    )
    genesis_dsk = "Genesis 1\n1 In the beginning God created the heavens and the earth.\nElohim (Plural)"
    left = [
        _slide(1, "", master="TITLE"),
        {"number": 2, "items": [{"kind": "image", "text": "", "w": 100, "h": 100}]},
        _slide(3, "Matthew 18 19 if two of you on earth agree"),
        _slide(4, genesis_lw),
        {"number": 12, "items": [{"kind": "image", "text": "", "w": 100, "h": 100}]},
        _slide(20, "Acts 4 33 With great power the apostles continued to testify"),
    ]
    right = [
        _slide(1, "Book of Romans Seminar"),
        _slide(2, "Matthew 18 19 if two of you on earth agree"),
        _slide(3, genesis_dsk),
        _slide(16, "33 With great power the apostles continued to testify"),
    ]
    slots = align_slides(left, right)
    paired = [(li, ri) for li, ri, _ in slots if li is not None and ri is not None]
    assert paired[0] == (1, 0)
    assert (2, 1) in paired
    assert (3, 2) in paired
    assert (5, 3) in paired
    assert (4, 3) not in paired
    unmatched_left = [li for li, ri, _ in slots if ri is None]
    assert 4 in unmatched_left


def test_empty_lw_graphic_pairs_with_dsk_verse_in_sequence():
    left = [
        {"number": 1, "items": [{"kind": "image", "text": "", "w": 100, "h": 100}]},
        _slide(2, "Genesis 1 In the beginning God created the heavens and the earth"),
    ]
    right = [
        _slide(
            1,
            "19 Again, truly I tell you that if two of you on earth agree about anything they ask for, "
            "it will be done for them by My Father in heaven.",
        ),
        _slide(2, "Genesis 1 In the beginning God created the heavens and the earth"),
    ]
    slots = align_slides(left, right)
    paired = [(li, ri) for li, ri, _ in slots if li is not None and ri is not None]
    assert paired[0] == (0, 0)
    assert paired[1] == (1, 1)


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
    faith_title = next(p for p in result["pairs"] if p.get("leftNumber") == 53)
    assert faith_title.get("rightNumber") == 38
    verse_combo = next(p for p in result["pairs"] if p.get("rightNumber") == 32)
    assert verse_combo.get("leftNumber") is None
    assert not any("Triune" in f.message for f in diffs)


def test_photo_slide_is_not_absorbed_into_a_verse_pair():
    """Only verses fold into a 1-vs-many pair; a photo slide must stay visible."""
    v12 = "12 All the Levites who were musicians stood on the east side of the altar."
    left = [_slide(1, v12), _slide(2, "Closing")]
    right = [
        _slide(1, v12),
        {"number": 2, "items": [{"kind": "image", "text": "", "w": 800, "h": 600}]},
        _slide(3, "Closing"),
    ]
    slots = align_slides(left, right, use_ocr=False)
    merged = [ri for _, ri, _ in slots if isinstance(ri, list) and len(ri) > 1]
    assert not merged, slots


def test_pair_quality_falls_back_to_ocr_when_extraction_is_blank():
    """Copy inside a group is invisible to Keynote, so pairing must read pixels."""
    from obed_edom.diff_keynotes import _pair_quality

    graphic = {"number": 1, "items": [{"kind": "group", "text": "", "w": 900, "h": 400}]}
    lw_seen = "Overall Consecration Spiritual Actions Faith Prayer Praise and Worship"
    dsk_seen = "Praise and Worship Prayer Faith Spiritual Actions Overall Consecration"
    args = (graphic, graphic, 0, 0, {}, {}, (3840.0, 1080.0), (1920.0, 1080.0), {}, {})
    assert _pair_quality(*args) == 0.0
    assert _pair_quality(*args, lambda _: lw_seen, lambda _: dsk_seen) >= ALIGN_THRESHOLD


PK_PASSAGES = {
    ("Genesis", 1, 1, 1): "In the beginning God created the heavens and the earth.",
    ("1 Samuel", 10, 10, 10): (
        "When he and his servant arrived at Gibeah, a procession of prophets met him."
    ),
    ("James", 5, 16, 16): (
        "The earnest, heartfelt, continued prayer of a righteous man makes tremendous "
        "power available."
    ),
    ("2 Corinthians", 1, 20, 20): (
        "For no matter how many promises God has made, they are Yes in Christ."
    ),
}


def _stub_gateway(monkeypatch):
    """Serve the fixture's passages locally; 2 Corinthians 2:20 does not exist."""

    def fake_fetch(book, chapter, verse, verse_end, translation):
        text = PK_PASSAGES.get((book, chapter, verse, verse_end or verse))
        if text is None:
            return None, "no passage text"
        return text, f"Bible Gateway {(translation or 'NIV').upper()}"

    monkeypatch.setattr("obed_edom.bible.fetch_passage", fake_fetch)


def test_pk_mistakes_fixture_catches_every_documented_mistake(tmp_path, monkeypatch):
    """One finding per mistake in DSK List of Mistakes.docx, and little else.

    Slide text in the fixture is written as the wall reads, so this exercises the
    classifiers without needing rendered PNGs. The small-caps mistake needs pixel
    geometry and is covered by test_smallcaps_needs_pixel_evidence.
    """
    import json

    _stub_gateway(monkeypatch)
    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures/diff/pk_mistakes.json").read_text()
    )
    result = compare_inspects(
        data["left"],
        data["right"],
        tmp_path,
        tmp_path,
        tmp_path / "heat",
        left_label="LW",
        right_label="DSK",
        use_ocr=False,
    )
    assert result["sameType"] is False
    flags = result["flags"]
    by_slide = {}
    for flag in flags:
        by_slide.setdefault(flag.rule, []).append(flag.message)
    blob = "\n".join(f.message for f in flags)

    # 1 First Loved
    assert "style.glossary" in by_slide or "text.word" in by_slide
    assert "First Love" in blob
    # 2 (Plural)
    assert "text.case" in by_slide
    assert "Plural" in blob
    # 3 tilted photo
    assert "photo.rotated" in by_slide
    # 4 dated photo
    assert "photo.source" in by_slide
    assert "conference_2019.jpg" in blob
    # 5 Samuel, 7 (MSG), 9 wrong chapter label
    refs = "\n".join(by_slide.get("text.reference") or [])
    assert "1 Samuel" in refs
    assert "MSG" in refs and "AMP" in refs
    # 8 Your Faith
    assert "text.word" in by_slide
    assert "Your Faith" in blob or "Your" in blob
    # 9 the citation the wording actually came from
    wrong = by_slide.get("bible.wrong_reference") or []
    assert wrong and "2 Corinthians 1:20" in wrong[0]
    # 10 ampersand
    assert "text.symbol" in by_slide

    # Every pair matched, and nothing shouts about wording in the blunt old way.
    assert all(p.get("leftNumber") and p.get("rightNumber") for p in result["pairs"])
    assert not any(f.rule == "text.major" for f in flags)
    assert len(flags) <= 30, [(f.rule, f.message) for f in flags]


def test_pk_mistakes_findings_land_on_the_right_slides(tmp_path, monkeypatch):
    import json

    _stub_gateway(monkeypatch)
    data = json.loads(
        (Path(__file__).resolve().parent / "fixtures/diff/pk_mistakes.json").read_text()
    )
    result = compare_inspects(
        data["left"],
        data["right"],
        tmp_path,
        tmp_path,
        tmp_path / "heat",
        left_label="LW",
        right_label="DSK",
        use_ocr=False,
    )
    rules_on = {p["number"]: {f.rule for f in p.get("flags") or []} for p in result["pairs"]}
    assert "text.case" in rules_on[2]
    assert "photo.rotated" in rules_on[3]
    assert "photo.source" in rules_on[4]
    assert "text.symbol" in rules_on[9]
    assert all(flag.slide for flag in result["flags"] if flag.rule.startswith("text."))


def test_smallcaps_needs_pixel_evidence(monkeypatch):
    """Neither Keynote nor OCR reports small caps, so the glyph heights decide."""
    from obed_edom import bible

    payload = {
        "path": "/tmp/Sermon_DSK.key",
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 4, "index": 3, "items": [{"kind": "text", "text": ""}]}],
    }
    quoted = "Psalm 23\n1 The Lord is my shepherd, I lack nothing."
    monkeypatch.setattr(
        bible,
        "fetch_passage",
        lambda *a, **k: ("The LORD is my shepherd, I lack nothing.", "Bible Gateway NIV"),
    )
    rendered = {0: quoted}

    monkeypatch.setattr("obed_edom.rendered.word_is_small_caps", lambda *a, **k: False)
    flags = bible.check_slide_passages(
        payload, rendered, "DSK", "dsk", ocr={0: quoted}, pngs={0: object()}
    )
    assert [f.rule for f in flags] == ["style.smallcaps"]
    assert flags[0].slide == 4

    monkeypatch.setattr("obed_edom.rendered.word_is_small_caps", lambda *a, **k: True)
    assert not bible.check_slide_passages(
        payload, rendered, "DSK", "dsk", ocr={0: quoted}, pngs={0: object()}
    )

    # Unknown (no preview, or Vision unavailable) must stay quiet.
    monkeypatch.setattr("obed_edom.rendered.word_is_small_caps", lambda *a, **k: None)
    assert not bible.check_slide_passages(
        payload, rendered, "DSK", "dsk", ocr={0: quoted}, pngs={0: object()}
    )


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
    assert any(f.rule in {"text.major", "text.word"} for f in diffs)
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
    assert any(f.rule == "text.major" for f in result["flags"] if f.category == "diff")


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


def test_png_maps_visible_export_order_not_slide_numbers(tmp_path):
    from obed_edom.diff_keynotes import map_preview_pngs

    first = tmp_path / "left.001.png"
    second = tmp_path / "left.002.png"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    slides = [
        {"number": 1, "index": 0, "skipped": True, "items": []},
        {"number": 2, "index": 1, "skipped": False, "items": []},
        {"number": 3, "index": 2, "skipped": True, "items": []},
        {"number": 4, "index": 3, "skipped": False, "items": []},
    ]
    mapped = map_preview_pngs(slides, [first, second])
    assert mapped[1] == first
    assert mapped[3] == second
    assert 0 not in mapped
    assert 2 not in mapped


def test_lw_pixel_compare_ignores_side_wings(tmp_path):
    from obed_edom.diff_keynotes import crop_center_wall

    left_dir = tmp_path / "left"
    right_dir = tmp_path / "right"
    left_dir.mkdir()
    right_dir.mkdir()
    lw = Image.new("RGB", (7680, 1080), (220, 30, 30))
    lw.paste(Image.new("RGB", (3840, 1080), (30, 180, 30)), (1920, 0))
    dsk = Image.new("RGB", (1920, 1080), (30, 180, 30))
    lw.save(left_dir / "slide-001.png")
    dsk.save(right_dir / "slide-001.png")
    cropped = crop_center_wall(lw, 7680, 1080)
    assert cropped.size == (3840, 1080)
    assert cropped.getpixel((0, 0)) == (30, 180, 30)
    photo = {"kind": "image", "text": ""}
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [photo]}],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": [photo]}],
    }
    result = compare_inspects(left, right, left_dir, right_dir, tmp_path / "heat", left_label="LW", right_label="DSK")
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Photo" in f.message for f in diffs)


def test_grouped_text_is_visible_to_diff():
    from obed_edom.inspect import slide_plain_text

    slide = {
        "number": 4,
        "items": [
            {
                "kind": "group",
                "text": "",
                "children": [
                    {"kind": "text", "text": "Genesis 1"},
                    {"kind": "text", "text": "In the beginning God created the heavens and the earth."},
                ],
            }
        ],
    }
    blob = slide_plain_text(slide)
    assert "Genesis 1" in blob
    assert "beginning God created" in blob


def test_export_applescript_uses_posix_png():
    from obed_edom.inspect import export_applescript

    script = export_applescript(Path("/tmp/Sermon.key"), Path("/tmp/previews"))
    assert "POSIX file" in script
    assert "as slide images" in script
    assert "image format:PNG" in script
    assert "saving no" in script


def test_match_pass_skips_wording_and_photos(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [_slide(1, "First Love Conference")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [_slide(1, "First Loved Conference")],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK", check=False
    )
    assert result["pairs"][0]["leftIndex"] == 0
    assert result["pairs"][0]["rightIndex"] == 0
    assert result["leftCatalog"][0]["number"] == 1
    diffs = [f for f in result["flags"] if f.category == "diff"]
    assert not any("Wording" in f.message or "Loved" in f.message for f in diffs)


def test_check_uses_operator_slots(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [_slide(1, "Alpha"), _slide(2, "First Love Conference")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [_slide(1, "First Loved Conference")],
    }
    result = compare_inspects(
        left,
        right,
        tmp_path,
        tmp_path,
        tmp_path / "heat",
        left_label="LW",
        right_label="DSK",
        slots=[(None, 0, 0.0), (1, None, 0.0)],
        check=True,
    )
    dsk = next(p for p in result["pairs"] if p.get("rightNumber") == 1)
    assert dsk.get("leftNumber") is None
    lw = next(p for p in result["pairs"] if p.get("leftNumber") == 2)
    assert lw.get("rightNumber") is None
    blob = "\n".join(f.message for f in result["flags"] if f.category == "diff")
    assert "No matching LW" in blob or "No matching" in blob


def test_slots_from_pairs_reads_right_indexes():
    from obed_edom.diff_keynotes import slots_from_pairs

    assert slots_from_pairs([{"leftIndex": 0, "rightIndexes": [1, 2]}]) == [(0, [1, 2], 0.0)]
    assert slots_from_pairs([{"leftIndex": 0, "rightIndex": 4}]) == [(0, [4], 0.0)]
    assert slots_from_pairs([{"leftIndex": None, "rightIndex": None}]) == [(None, [], 0.0)]


def test_combined_wall_vs_split_dsks_is_not_wording_diff(tmp_path):
    v12 = "12 All the Levites who were musicians stood on the east side of the altar."
    v13 = "13 The trumpeters and musicians joined in unison to give praise."
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [_slide(38, f"{v12}\n{v13}")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [_slide(22, v12), _slide(23, v13)],
    }
    split = compare_inspects(
        left,
        right,
        tmp_path,
        tmp_path,
        tmp_path / "heat-split",
        left_label="LW",
        right_label="DSK",
        slots=[(0, 0, 1.0), (None, 1, 0.0)],
        check=True,
    )
    # Split apart, the wall slide carries a verse the paired DSK slide does not.
    assert any(f.rule == "text.verse_split" for f in split["flags"] if f.category == "diff")
    combined = compare_inspects(
        left,
        right,
        tmp_path,
        tmp_path,
        tmp_path / "heat-combined",
        left_label="LW",
        right_label="DSK",
        slots=[(0, [0, 1], 1.0)],
        check=True,
    )
    assert combined["pairs"][0]["rightIndexes"] == [0, 1]
    assert combined["pairs"][0]["rightNumbers"] == [22, 23]
    assert len(combined["pairs"]) == 1
    diffs = [f for f in combined["flags"] if f.category == "diff"]
    assert not any("Wording" in f.message for f in diffs)


def test_realign_gaps_pairs_leftover_neighbours():
    from obed_edom.baseline import slot_dict
    from obed_edom.diff_keynotes import realign_gaps

    left = [_slide(1, "Alpha"), _slide(2, "Bravo verse about mercy"), _slide(3, "Omega")]
    right = [_slide(1, "Alpha"), _slide(2, "Bravo verse about mercy"), _slide(3, "Omega")]
    slots = [
        slot_dict(0, [0], 1.0),
        slot_dict(1, []),
        slot_dict(None, [1]),
        slot_dict(2, [2], 1.0),
    ]
    filled = realign_gaps(slots, left, right, use_ocr=False)
    mids = [s for s in filled if s["leftIndex"] == 1]
    assert mids and mids[0]["rightIndexes"] == [1]


def test_attach_slide_flags_puts_bible_on_pair():
    from obed_edom.diff_keynotes import attach_slide_flags
    from obed_edom.models import Flag

    pairs = [{"leftNumber": 50, "rightNumbers": [29], "rightNumber": 29, "flags": []}]
    flag = Flag(
        "error",
        "bible",
        "mismatch",
        location="DSK slide 29",
        rule="bible.mismatch",
        slide=29,
        deck="dsk",
    )
    leftover = attach_slide_flags(pairs, [flag])
    assert leftover == []
    assert pairs[0]["flags"] == [flag]


def test_compare_inspects_skips_mov_heatmap(tmp_path: Path):
    from PIL import Image

    from obed_edom.diff_keynotes import compare_inspects
    from obed_edom.inspect import preview_inspect

    left = tmp_path / "lw"
    right = tmp_path / "dsk"
    left.mkdir()
    right.mkdir()
    Image.new("RGB", (32, 32), (10, 10, 10)).save(left / "wall.001.png")
    Image.new("RGB", (32, 32), (10, 10, 10)).save(right / "dsk.001.png")
    (left / "clip.002.mov").write_bytes(b"l")
    (right / "clip.002.mov").write_bytes(b"r")
    heat = tmp_path / "heat"
    heat.mkdir()
    result = compare_inspects(
        preview_inspect(left),
        preview_inspect(right),
        left,
        right,
        heat,
        left_label="LW",
        right_label="DSK",
        slots=[
            (0, [0], 1.0),
            (1, [1], 1.0),
        ],
        check=True,
        use_ocr=False,
    )
    assert len(result["pairs"]) == 2
    mov_pair = next(p for p in result["pairs"] if p.get("leftNumber") == 2)
    assert not mov_pair.get("heatPng")
    still_pair = next(p for p in result["pairs"] if p.get("leftNumber") == 1)
    assert still_pair.get("heatPng") or still_pair.get("visual") is not None


def test_ocr_unavailable_and_count_stay_deck_wide():
    from obed_edom.diff_keynotes import attach_slide_flags
    from obed_edom.models import Flag

    pairs = [{"leftNumber": 1, "rightNumbers": [1], "flags": []}]
    leftover = attach_slide_flags(
        pairs,
        [
            Flag("info", "ocr", "no vision", location="LW", rule="ocr.unavailable", deck="lw"),
            Flag("info", "diff", "count", rule="diff.count"),
        ],
    )
    assert len(leftover) == 2
    assert pairs[0]["flags"] == []


def test_carried_point_title_is_info_not_wording(tmp_path):
    verse = (
        "18 Some men came carrying a paralyzed man on a mat and tried to take him "
        "into the house to lay him before Jesus."
    )
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            _slide(1, "3\nFaith"),
            _slide(2, f"Luke 5\n{verse}\n3\nFaith"),
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            _slide(1, "Your Faith"),
            _slide(2, f"Luke 5\n{verse}"),
        ],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK"
    )
    title_pair = next(p for p in result["pairs"] if p.get("leftNumber") == 1)
    assert title_pair.get("rightNumber") == 1
    assert any(f.rule == "text.word" for f in (title_pair.get("flags") or []))
    verse_pair = next(p for p in result["pairs"] if p.get("leftNumber") == 2)
    assert verse_pair.get("rightNumber") == 2
    rules = [f.rule for f in (verse_pair.get("flags") or []) if f.category == "diff"]
    assert "text.word" not in rules
    assert "text.point_carry" in rules


def test_carried_title_still_strips_when_verse_uses_the_word(tmp_path):
    verse = '20 When Jesus saw their faith, He said, "Friend, your sins are forgiven."'
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            _slide(1, "3\nFaith"),
            _slide(2, f"Luke 5\n{verse}\nFaith"),
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            _slide(1, "Your Faith"),
            _slide(2, f"Luke 5\n{verse}"),
        ],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK"
    )
    verse_pair = next(p for p in result["pairs"] if p.get("leftNumber") == 2)
    rules = [f.rule for f in (verse_pair.get("flags") or []) if f.category == "diff"]
    assert "text.word" not in rules
    assert "text.point_carry" in rules


def test_recap_list_is_not_a_carried_title(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slides": [
            _slide(1, "3\nFaith"),
            _slide(2, "4\nSpiritual Actions"),
            _slide(3, "Overall Consecration\nSpiritual Actions\nFaith\nPrayer\nPraise and Worship"),
        ],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slides": [
            _slide(1, "Your Faith"),
            _slide(2, "Spiritual Actions"),
            _slide(3, "Overall Consecration"),
        ],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK"
    )
    recap = next(p for p in result["pairs"] if p.get("leftNumber") == 3)
    rules = [f.rule for f in (recap.get("flags") or []) if f.category == "diff"]
    assert "text.point_carry" not in rules


def test_enclosed_numerals_are_a_numbering_style_not_a_wording_change():
    """A wall sets ① ② ③ where the lower third types 1 2 3."""
    from obed_edom.text_diff import classify_text_diff

    wall = "\u2460 Praise and Worship\n\u2461 Prayer\n\u2462 Faith"
    lower = "1 Praise and Worship\n2 Prayer\n3 Faith"
    assert classify_text_diff(wall, lower, "LW", "DSK") is None


def test_ampersand_is_named_even_when_ocr_adds_logo_noise(tmp_path):
    """The typed copy is diffed first, so "&" reads as a symbol swap.

    Diffing the OCR-merged text instead buries it: a stylised logo and circled
    numerals come back spelled differently every run, and the classifier falls
    through to its blunt last resort.
    """
    from obed_edom.rendered import RenderedSlide
    from obed_edom.text_diff import classify_text_diff

    typed_lw = "\u2460 Praise and Worship\n\u2461 Prayer\n\u2462 Faith"
    typed_dsk = "1 Praise & Worship\n2 Prayer\n3 Faith"
    noise_lw = f"{typed_lw}\nATMOSPHERE\nO 3 5"
    noise_dsk = f"{typed_dsk}\nATM\u00dcSPH\u00c9RE\n8 4"

    blunt = classify_text_diff(noise_lw, noise_dsk, "LW", "DSK")
    assert blunt is not None and blunt.rule == "text.major"

    precise = classify_text_diff(typed_lw, typed_dsk, "LW", "DSK")
    assert precise is not None
    assert precise.rule == "text.symbol"
    assert '"and"' in precise.message and '"&"' in precise.message
    # The numbering style must not dilute the one difference that matters.
    assert "\u2460" not in precise.message

    # RenderedSlide keeps the typed copy separate, which is what makes the
    # two-layer diff in compare_inspects possible.
    shot = RenderedSlide(text=noise_lw, extracted=typed_lw, ocr="ATMOSPHERE\nO 3 5", ocr_used=True)
    assert shot.extracted == typed_lw


def test_typed_copy_is_preferred_over_ocr_merged_text(tmp_path):
    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slides": [_slide(1, "Praise and Worship")],
    }
    right = {
        "path": str(tmp_path / "Sermon_DSK.key"),
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [_slide(1, "Praise & Worship")],
    }
    result = compare_inspects(
        left, right, tmp_path, tmp_path, tmp_path / "heat", left_label="LW", right_label="DSK"
    )
    pair = result["pairs"][0]
    rules = [f.rule for f in (pair.get("flags") or [])]
    assert "text.symbol" in rules
    assert "text.major" not in rules


def test_ocr_inside_a_pasted_graphic_is_left_to_the_photo_rules(tmp_path):
    """Text baked into a screenshot belongs to photo.*, not to the wording diff."""
    from obed_edom.ocr import OcrLine
    from obed_edom.rendered import _outside_photos

    slide = {
        "number": 1,
        "items": [
            {"kind": "text", "text": "Praise and Worship", "x": 0, "y": 0, "w": 800, "h": 120},
            {"kind": "image", "fileName": "screenshot.png", "x": 200, "y": 400, "w": 900, "h": 400},
        ],
    }
    size = (1920.0, 1080.0)
    inside = OcrLine(text="ATMOSPHERE", confidence=0.9, x0=0.30, y0=0.50, x1=0.55, y1=0.60)
    outside = OcrLine(text="Praise and Worship", confidence=0.9, x0=0.01, y0=0.02, x1=0.40, y1=0.09)
    kept = _outside_photos([inside, outside], slide, size)
    assert kept == ["Praise and Worship"]
