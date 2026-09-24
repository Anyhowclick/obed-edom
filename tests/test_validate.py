from pathlib import Path

import pytest
from obed_edom.parse_outline import parse_outline
from obed_edom.slide_map import map_slides
from obed_edom.validate import validate_inspect, validate_slide_specs, validate_style_text

OUTLINES = Path(__file__).resolve().parents[1] / "Sermon Outlines"


def test_style_en_dash_and_books():
    flags = validate_style_text("See Psalms 23 and Revelation 1. Lived 1980-2012. Meet 3-4 Jun.", location="t")
    cats = {f.category for f in flags}
    assert "book_name" in cats
    assert "date" in cats
    messages = " ".join(f.message for f in flags)
    assert "Psalm" in messages
    assert "Revelations" in messages
    assert "en dash" in messages


def test_trinity_lowercase_god():
    flags = validate_style_text("we love god forever", location="t")
    assert any(f.category == "trinity" for f in flags)


def test_continued_dsk_verse_overflow_is_flagged():
    offering_path = OUTLINES / "Offering JX.docx"
    if not offering_path.is_file():
        pytest.skip("Missing operator outline Offering JX.docx (Sermon Outlines/ is gitignored)")
    offering = parse_outline(offering_path)
    lw, dsk, _ = map_slides(offering)
    flags = validate_slide_specs(lw, dsk)
    overflow = [f for f in flags if f.category == "overflow"]
    assert overflow
    assert any("DSK" in (f.location or "") for f in overflow)
    assert any("VERSE-CONTINUED" in f.message for f in overflow)
    assert any("lower-third" in f.message for f in overflow)
    assert not any("LW" in (f.location or "") for f in overflow)


def _overflow_payload(*, x=100.0, y=100.0, w=1540.0, h=200.0, slide_height=1080):
    return {
        "path": "demo.key",
        "slideWidth": 1920,
        "slideHeight": slide_height,
        "slides": [
            {
                "number": 1,
                "items": [
                    {
                        "kind": "text",
                        "text": "Steep your life in God-reality, God-initiative, God-provisions.",
                        "x": x,
                        "y": y,
                        "w": w,
                        "h": h,
                    }
                ],
            }
        ],
    }


def test_inspect_overflow_flags_box_off_the_bottom():
    # bottom = 1000 + 200 = 1200, well past the 1080 canvas -> runs off-screen.
    payload = _overflow_payload(y=1000.0, h=200.0)
    flags = [f for f in validate_inspect(payload, location_prefix="demo.key") if f.category == "overflow"]
    assert flags
    assert "bottom" in flags[0].message


def test_inspect_overflow_flags_box_off_the_top():
    # top = -60 sits above the canvas -> runs off-screen.
    payload = _overflow_payload(y=-60.0, h=200.0)
    flags = [f for f in validate_inspect(payload, location_prefix="demo.key") if f.category == "overflow"]
    assert flags
    assert "top" in flags[0].message


def test_inspect_overflow_ignores_boxes_that_stay_on_screen():
    """Geometry that sits comfortably inside the canvas is not overflow, even
    when a per-character height estimate would over-count a line. Mirrors the
    real GW slide 12 verse (bottom 529) and DSK slide 9 verse (bottom 1043)."""
    gw12 = _overflow_payload(y=90.0, h=439.0)  # bottom 529
    assert not any(
        f.category == "overflow"
        for f in validate_inspect(gw12, location_prefix="gw.key")
    )
    dsk9 = _overflow_payload(y=866.0, h=177.0)  # bottom 1043 < 1080
    assert not any(
        f.category == "overflow"
        for f in validate_inspect(dsk9, location_prefix="dsk.key")
    )


def test_validate_inspect_skips_hidden_slides():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slides": [
            {
                "number": 1,
                "skipped": True,
                "items": [
                    {
                        "kind": "text",
                        "text": "we love god forever",
                        "w": 1540,
                        "h": 120,
                        "size": 45,
                    }
                ],
            },
            {
                "number": 2,
                "skipped": False,
                "items": [{"kind": "text", "text": "Faith", "w": 400, "h": 80, "size": 45}],
            },
        ],
    }
    flags = validate_inspect(payload, location_prefix="demo.key")
    assert not any(f.category == "trinity" for f in flags)
    assert not any("slide 1" in (f.location or "") for f in flags)


def _wall(*items) -> dict:
    return {
        "path": "wall.key",
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slides": [{"number": 1, "items": list(items)}],
    }


def test_bounds_ignores_side_panels_and_backdrops():
    """A 7680 wall legitimately uses both wings; only cut objects are mistakes."""
    from obed_edom.validate import _bounds_flags

    payload = _wall(
        {"kind": "image", "text": "", "x": 0, "y": 0, "w": 7680, "h": 1080},
        {"kind": "image", "text": "", "x": 0, "y": 0, "w": 1920, "h": 1080},
        {"kind": "image", "text": "", "x": 5760, "y": 0, "w": 1920, "h": 1080},
        {"kind": "text", "text": "Faith", "x": 2200, "y": 400, "w": 1200, "h": 200},
    )
    assert _bounds_flags(payload, "LW", deck="lw") == []


def test_bounds_flags_straddling_object_with_evidence(tmp_path):
    from PIL import Image

    from obed_edom.validate import _bounds_flags

    png = tmp_path / "slide-001.png"
    Image.new("RGB", (7680, 1080), (20, 20, 20)).save(png)
    payload = _wall({"kind": "text", "text": "Faith", "x": 1400, "y": 400, "w": 1400, "h": 200})
    evidence_dir = tmp_path / "evidence"
    flags = _bounds_flags(
        payload, "LW", deck="lw", png_map={0: png}, evidence_dir=evidence_dir
    )
    assert [f.rule for f in flags] == ["bounds.straddles"]
    assert flags[0].slide == 1
    assert "x=1920" in flags[0].message
    assert flags[0].evidence
    assert (evidence_dir / flags[0].evidence).exists()


def test_rule_severity_map_can_silence_a_rule(monkeypatch):
    from obed_edom import validate

    monkeypatch.setattr(validate, "load_rules", lambda: {"rules": {"text.word": "off"}})
    assert validate.rule_severity("text.word") is None
    assert validate.make_flag("text.word", "diff", "nope") is None
    monkeypatch.setattr(validate, "load_rules", lambda: {"rules": {"text.word": "error"}})
    flag = validate.make_flag("text.word", "diff", "yep", default="warning")
    assert flag is not None and flag.severity == "error"


def test_flag_dict_includes_yaml_title():
    from obed_edom.validate import flag_dict, make_flag

    flag = make_flag("style.glossary", "glossary", "near miss", location="LW slide 1", slide=1, deck="lw")
    assert flag is not None
    body = flag_dict(flag)
    assert body["title"] == "House spelling"
    trinity = make_flag("style.trinity", "trinity", "caps", location="LW slide 3", slide=3, deck="lw")
    assert trinity is not None
    assert flag_dict(trinity)["title"] == "Trinity Word Style"


def test_rule_title_uses_yaml_and_fallback(monkeypatch):
    from obed_edom import validate

    monkeypatch.setattr(
        validate,
        "load_rules",
        lambda: {"titles": {"style.trinity": "Trinity Word Style", "text.major": "Wording differs."}},
    )
    assert validate.rule_title("style.trinity") == "Trinity Word Style"
    assert validate.rule_title("text.major") == "Wording differs."
    assert validate.rule_title("bible.wrong_reference") == "Bible Wrong Reference"


def test_inspect_trinity_names_a_slide():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slides": [
            {"number": 3, "items": [{"kind": "text", "text": "we love god forever"}]},
        ],
    }
    flags = validate_inspect(
        payload, location_prefix="LW", deck="lw", use_ocr=False, check_passages=False
    )
    trinity = [f for f in flags if f.rule == "style.trinity"]
    assert trinity
    assert trinity[0].slide == 3
    assert trinity[0].location == "LW slide 3"


def test_inspect_date_names_a_slide():
    payload = {
        "path": "demo.key",
        "slideWidth": 1920,
        "slides": [
            {"number": 4, "items": [{"kind": "text", "text": "Lived 1980-2012."}]},
        ],
    }
    flags = validate_inspect(
        payload, location_prefix="DSK", deck="dsk", use_ocr=False, check_passages=False
    )
    dates = [f for f in flags if f.rule == "style.date"]
    assert dates
    assert dates[0].slide == 4
    assert dates[0].location == "DSK slide 4"
    assert dates[0].deck == "dsk"


def test_missing_previews_are_info_not_warning():
    from obed_edom.contrast import check_contrast

    flags, overlays = check_contrast([], Path("/tmp/no-such-previews"), "lw")
    assert overlays == []
    assert flags
    assert all(f.severity == "info" for f in flags)
    assert all(f.category == "contrast" for f in flags)


def test_same_type_diff_count_is_info_missing_is_warning(tmp_path):
    from obed_edom.diff_keynotes import compare_inspects

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
    assert not any(f.severity == "error" and f.category == "diff" for f in result["flags"])


def test_mixed_type_diff_skips_count_and_missing(tmp_path):
    from obed_edom.diff_keynotes import compare_inspects

    left = {
        "path": str(tmp_path / "Sermon_LW.key"),
        "slideWidth": 3840,
        "slideHeight": 1080,
        "slideCount": 2,
        "slides": [
            {"number": 1, "items": [{"text": "hello"}]},
            {"number": 2, "items": [{"text": "extra"}]},
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
    assert not any("Slide count differs" in f.message for f in diffs)
    assert not any("Missing" in f.message for f in diffs)



def test_new_cue_and_outline_rules_ship_with_severities():
    """The checker's rule ids must be tunable from the YAML like every other."""
    from obed_edom.validate import load_rules, rule_severity, rule_title

    rules = load_rules()["rules"]
    expected = {
        "cue.deprecated_alias": "warning",
        "cue.lw_count": "warning",
        "cue.dsk_count": "warning",
        "cue.uncued_slide": "warning",
        "cue.no_slide": "warning",
        "cue.unknown": "warning",
        "cue.hold": "info",
        "outline.dsk_deviates": "warning",
        "outline.dsk_stale": "warning",
        "outline.stale": "info",
        "outline.lw_deviates": "warning",
        "outline.both_deviate": "warning",
        "outline.three_way": "info",
    }
    for rule, severity in expected.items():
        assert rules.get(rule) == severity, rule
        assert rule_severity(rule) == severity
        # A generated title reads like "Cue Lw Count"; these are hand-written.
        assert rule_title(rule) != rule


def test_outline_findings_are_pinned_to_their_paragraph(tmp_path):
    """The reader sits a finding next to the line it is about."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from outline_fixtures import build_outline

    from obed_edom.validate import validate_outline_paragraphs

    path = build_outline(
        tmp_path / "style.docx",
        [
            "[LW][DSK-PP] A quiet opening line.",
            "[LW][DSK-PP] We read Psalms 23 together.",
        ],
    )
    flags = validate_outline_paragraphs(parse_outline(path))
    book = next(f for f in flags if f.category == "book_name")
    assert book.deck == "outline"
    assert book.slide is not None
    para = parse_outline(path).paragraphs[book.slide - 1]
    assert "Psalms 23" in para.text


def _punct_flags(*runs):
    from obed_edom.models import Paragraph
    from obed_edom.validate import _punctuation_style_flags

    return _punctuation_style_flags(Paragraph(runs=list(runs)), location="t")


def test_bold_punctuation_run_is_flagged():
    from obed_edom.models import Run

    flags = _punct_flags(Run(text="!", bold=True))
    assert len(flags) == 1
    assert flags[0].rule == "style.punctuation"


def test_plain_punctuation_run_is_not_flagged():
    from obed_edom.models import Run

    assert _punct_flags(Run(text="!")) == []


def test_highlighted_punctuation_run_is_flagged():
    from obed_edom.models import Run

    flags = _punct_flags(Run(text=":", highlight="yellow"))
    assert len(flags) == 1


def test_italic_punctuation_run_is_flagged():
    from obed_edom.models import Run

    flags = _punct_flags(Run(text="…", italic=True))
    assert len(flags) == 1


def test_explicit_black_punctuation_run_is_not_flagged():
    from obed_edom.models import Run

    assert _punct_flags(Run(text=".", color="000000")) == []


def test_accent_colour_punctuation_run_is_flagged():
    from obed_edom.models import Run

    flags = _punct_flags(Run(text="!", color="FFCC00"))
    assert len(flags) == 1


def test_punctuation_inside_bold_word_run_is_not_flagged():
    from obed_edom.models import Run

    assert _punct_flags(Run(text="Amen!", bold=True)) == []


# --------------------------------------------------------------------------
# mm.zorder_flip — Magic Move tweens geometry, not stacking, so a matched pair
# whose back/front order inverts across the cut snaps at the transition.
# Pairing follows what live Keynote was observed to do
# (output/mm-dup-pairing/ and output/mm-shape-id/, 2026-09-24): a key (Keynote's
# hard gate) unique on both sides pairs directly; a repeated key pairs by the
# assignment preferring equal tier1 (stroke+opacity), then equal tier2 (raw stored
# path), then equal tier3 (style), then the least total centre distance (optimal,
# not greedy). Tiers come from mmPrefs (shapes and lines only).
# --------------------------------------------------------------------------
_SHAPE, _LINE = "shape:bezier:rect", "line:bezier:white:4:none"
_SMALL, _BIG, _CLIP = "movie:WA0125=", "movie:UNTITLED=", "movie:SAME="
_SQ = "image:SQ="
_TITLE, _VERSE = "text:Welcome", "text:John 3:16"
_NAMES = {_SMALL: "IMG-WA0125.mp4", _BIG: "untitled.mov", _CLIP: "clip.mov", _SQ: "sq.png"}


def _mm_slide(number, objects, *, out=False, skipped=False):
    """``objects`` back→front: a key, (key, (x, y, side)) for a square on the slide, or
    (key, (x, y, side), [tier1, tier2, tier3]) to add mmPrefs.
    kindIndex follows stacking order within each kind."""
    by_kind: dict[str, dict[int, str]] = {}
    prefs: dict[str, dict[int, list]] = {}
    items, order = [], []
    for entry in objects:
        key, rect, tiers = (*entry, None)[:3] if isinstance(entry, tuple) else (entry, None, None)
        kind = key.split(":", 1)[0]
        ki = len(by_kind.setdefault(kind, {}))
        by_kind[kind][ki] = key
        if tiers is not None:
            prefs.setdefault(kind, {})[ki] = list(tiers)
        item = {"kind": kind, "kindIndex": ki, "text": "", "fileName": _NAMES.get(key, "")}
        if kind == "text":
            item["text"] = key.split(":", 1)[1]
        if rect:
            x, y, side = rect
            item.update(x=x, y=y, w=side, h=side)
        items.append(item)
        order.append([kind, ki])
    slide = {"number": number, "index": number - 1, "items": items, "mmKeys": by_kind, "mmOrder": order}
    if prefs:
        slide["mmPrefs"] = prefs
    if out:
        slide["magicMoveOut"] = True
    if skipped:
        slide["skipped"] = True
    return slide


def _mm_payload(*slides) -> dict:
    return {"path": "wall.key", "slideWidth": 1920, "slideHeight": 1080, "slides": list(slides)}


def _zorder(payload):
    from obed_edom.validate import _mm_zorder_flags

    return _mm_zorder_flags(payload, "wall.key", deck="dsk")


def _pairs(flags):
    return [f.message.split(" swap ")[0] for f in flags]


def _matches(before, after):
    from obed_edom.validate import _mm_matches

    return sorted(_mm_matches(_mm_slide(1, before, out=True), _mm_slide(2, after)))


def test_mm_zorder_flip_names_the_one_swapped_pair():
    payload = _mm_payload(
        _mm_slide(1, [_SMALL, _TITLE, _BIG], out=True),
        _mm_slide(2, [_TITLE, _SMALL, _BIG]),
    )
    flags = _zorder(payload)
    assert len(flags) == 1
    flag = flags[0]
    assert (flag.rule, flag.severity, flag.slide, flag.deck) == ("mm.zorder_flip", "warning", 1, "dsk")
    assert flag.location == "wall.key slide 1"
    assert flag.message == (
        "'IMG-WA0125.mp4' and 'Welcome' swap stacking order slide 1→2; "
        "Magic Move will snap the layering at the cut."
    )


def test_mm_zorder_flip_reaches_validate_inspect_one_flag_per_inverted_pair():
    # Slide 2 fully reverses slide 1's four objects: all six pairs invert, and each is
    # its own flag (dedupe keys on the message, which names the pair). Order follows
    # slide 1's back→front stacking.
    payload = _mm_payload(
        _mm_slide(1, [_TITLE, _SMALL, _BIG, _VERSE], out=True),
        _mm_slide(2, [_VERSE, _BIG, _SMALL, _TITLE]),
    )
    flags = [
        f for f in validate_inspect(payload, use_ocr=False, check_passages=False)
        if f.rule == "mm.zorder_flip"
    ]
    assert _pairs(flags) == [
        "'Welcome' and 'IMG-WA0125.mp4'",
        "'Welcome' and 'untitled.mov'",
        "'Welcome' and 'John 3:16'",
        "'IMG-WA0125.mp4' and 'untitled.mov'",
        "'IMG-WA0125.mp4' and 'John 3:16'",
        "'untitled.mov' and 'John 3:16'",
    ]
    assert flags == _zorder(payload)


@pytest.mark.parametrize(
    "slides",
    [
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE]), _mm_slide(2, [_TITLE, _SMALL])],
            id="no-magic-move-out",
        ),
        pytest.param(
            [_mm_slide(1, [_TITLE, _SMALL, _BIG], out=True), _mm_slide(2, [_TITLE, _SMALL, _BIG])],
            id="same-order",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE, _TITLE], out=True), _mm_slide(2, [_TITLE, _SMALL])],
            id="repeated-text-before",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE], out=True), _mm_slide(2, [_TITLE, _SMALL, _TITLE])],
            id="repeated-text-after",
        ),
        pytest.param(
            [
                {**_mm_slide(1, [_SMALL, _TITLE], out=True), "mmOrder": None},
                _mm_slide(2, [_TITLE, _SMALL]),
            ],
            id="missing-order",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE], out=True), _mm_slide(2, [_TITLE, _SMALL], skipped=True)],
            id="skipped-neighbour",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE], out=True, skipped=True), _mm_slide(2, [_TITLE, _SMALL])],
            id="skipped-self",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE], out=True), _mm_slide(3, [_TITLE, _SMALL])],
            id="absent-neighbour",
        ),
        pytest.param(
            [_mm_slide(1, [_SMALL, _TITLE], out=True), _mm_slide(2, [_TITLE, _BIG])],
            id="key-on-one-slide-only",
        ),
    ],
)
def test_mm_zorder_flip_null_controls(slides):
    assert _zorder(_mm_payload(*slides)) == []


def test_mm_zorder_flip_no_mm_data_is_silent():
    payload = _mm_payload(
        {"number": 1, "items": [{"kind": "shape"}]},
        {"number": 2, "items": [{"kind": "shape"}]},
    )
    assert _zorder(payload) == []


def test_mm_zorder_flip_checks_unique_lines_and_shapes():
    # A unique compatible pair (one each side) always pairs: the line and the shape each
    # swap stacking against the movie.
    payload = _mm_payload(
        _mm_slide(1, [_SHAPE, _SMALL, _LINE], out=True),
        _mm_slide(2, [_LINE, _SMALL, _SHAPE]),
    )
    assert _pairs(_zorder(payload)) == [
        "'shape #0' and 'IMG-WA0125.mp4'",
        "'shape #0' and 'line #0'",
        "'IMG-WA0125.mp4' and 'line #0'",
    ]


def test_mm_lines_pair_only_by_equal_key():
    # Lines no longer share the bare key "line": a different stroke or end is a
    # different gate key, so it never pairs.
    other = "line:bezier:yellow:4:none"
    assert _matches([_LINE, _TITLE], [_TITLE, _LINE]) == [
        (("line", 0), ("line", 0)),
        (("text", 0), ("text", 0)),
    ]
    assert _matches([_LINE, _TITLE], [_TITLE, other]) == [(("text", 0), ("text", 0))]


@pytest.mark.parametrize(
    "group",
    [
        pytest.param("group:text:UPG\nshape:scalarPathSource:0:abc", id="shape-leaf"),
        # A shape leaf whose text is whitespace-only is dropped from the group key, so
        # this key carries no shape: leaf although the group holds a shape.
        pytest.param("group:text:UPG\nimage:PDF1=", id="whitespace-text-shape-dropped-from-key"),
    ],
)
def test_mm_zorder_flip_checks_groups(group):
    payload = _mm_payload(
        _mm_slide(1, [group, _SMALL], out=True),
        _mm_slide(2, [_SMALL, group]),
    )
    assert _pairs(_zorder(payload)) == ["'group #0' and 'IMG-WA0125.mp4'"]
    assert _matches([group, _TITLE], [_TITLE, group]) == [
        (("group", 0), ("group", 0)),
        (("text", 0), ("text", 0)),
    ]


def test_mm_repeated_text_and_groups_are_skipped():
    # Keynote's pairing of repeated text and groups was never measured, so a repeated
    # text or group key pairs nothing even with geometry; unique keys still pair.
    group = "group:text:UPG\nshape:scalarPathSource:0:abc"
    for key in (_TITLE, group):
        assert _matches(
            [(key, (0, 0, 100)), (key, (900, 0, 100)), _SMALL],
            [_SMALL, (key, (10, 0, 100)), (key, (910, 0, 100))],
        ) == [(("movie", 0), ("movie", 0))]


_LEFT, _RIGHT = (100, 400, 200), (1500, 400, 200)
_PLAIN = ("stroke:none|op:1", "path:174x154", "style:red")


def test_mm_identical_shapes_pair_by_least_total_distance():
    # Two shapes of one gate key and equal prefs: position decides. Slide 2 stacks the
    # right-hand copy behind the left-hand one, so the pairs flip only when each shape
    # stays on its side.
    before = [(_SHAPE, _LEFT, _PLAIN), (_SHAPE, _RIGHT, _PLAIN)]
    stays = _mm_payload(
        _mm_slide(1, before, out=True),
        _mm_slide(2, [(_SHAPE, (1450, 450, 200), _PLAIN), (_SHAPE, (150, 350, 200), _PLAIN)]),
    )
    assert _matches(before, [(_SHAPE, (1450, 450, 200), _PLAIN), (_SHAPE, (150, 350, 200), _PLAIN)]) == [
        (("shape", 0), ("shape", 1)),
        (("shape", 1), ("shape", 0)),
    ]
    assert _pairs(_zorder(stays)) == ["'shape #0' and 'shape #1'"]
    crosses = _mm_payload(
        _mm_slide(1, before, out=True),
        _mm_slide(2, [(_SHAPE, (150, 350, 200), _PLAIN), (_SHAPE, (1450, 450, 200), _PLAIN)]),
    )
    assert _zorder(crosses) == []


def test_mm_shape_tier1_beats_distance():
    # S0 (no stroke) sits left, S1 (white stroke) right. Slide 2 puts the stroked copy
    # left and the plain copy right. Distance alone would keep each on its side (no
    # flip); Keynote sends each to its matching stroke, so both cross and the
    # back/front order inverts.
    stroked = ("stroke:white4|op:1", *_PLAIN[1:])
    before = [(_SHAPE, _LEFT, _PLAIN), (_SHAPE, _RIGHT, stroked)]
    after = [(_SHAPE, _LEFT, stroked), (_SHAPE, _RIGHT, _PLAIN)]
    assert _matches(before, after) == [(("shape", 0), ("shape", 1)), (("shape", 1), ("shape", 0))]
    assert _pairs(_zorder(_mm_payload(_mm_slide(1, before, out=True), _mm_slide(2, after)))) == [
        "'shape #0' and 'shape #1'",
    ]
    plain_only = [(_SHAPE, _LEFT, _PLAIN), (_SHAPE, _RIGHT, _PLAIN)]
    assert _zorder(_mm_payload(_mm_slide(1, plain_only, out=True), _mm_slide(2, plain_only))) == []


_NEAR, _FAR = (200, 400, 200), (1500, 400, 200)


@pytest.mark.parametrize(
    ("near", "far"),
    [
        pytest.param(
            ("stroke:none|op:1", "path:348x308", "style:red"),
            ("stroke:none|op:1", "path:174x154", "style:blue"),
            id="raw-path-beats-style",
        ),
        pytest.param(
            ("stroke:none|op:0.29", "path:174x154", "style:red"),
            ("stroke:none|op:1", "path:348x308", "style:red"),
            id="tier1-beats-raw-path",
        ),
        pytest.param(
            ("stroke:none|op:1", "path:174x154", "style:blue"),
            ("stroke:none|op:1", "path:174x154", "style:red"),
            id="style-beats-distance",
        ),
    ],
)
def test_mm_shape_tier_order_picks_the_farther_candidate(near, far):
    # One source; the nearer target differs in a higher tier than the farther one.
    got = _matches([(_SHAPE, (100, 400, 200), _PLAIN)], [(_SHAPE, _NEAR, near), (_SHAPE, _FAR, far)])
    assert got == [(("shape", 0), ("shape", 1))]


def test_mm_shape_full_tie_is_skipped():
    # Equal prefs and the target exactly between the two sources: ambiguous, skipped
    # (the unique title still pairs). A tier difference breaks the same geometric tie.
    between = [_TITLE, (_SHAPE, (100, 0, 100), _PLAIN)]
    assert _matches(
        [(_SHAPE, (0, 0, 100), _PLAIN), (_SHAPE, (200, 0, 100), _PLAIN), _TITLE], between,
    ) == [(("text", 0), ("text", 0))]
    assert _matches(
        [(_SHAPE, (0, 0, 100), _PLAIN), (_SHAPE, (200, 0, 100), ("stroke:red|op:1", *_PLAIN[1:])), _TITLE],
        between,
    ) == [(("shape", 0), ("shape", 0)), (("text", 0), ("text", 0))]


def test_mm_shapes_without_prefs_pair_by_distance_like_media():
    assert _matches(
        [(_SHAPE, (100, 400, 150)), (_SHAPE, (600, 400, 150))],
        [(_SHAPE, (550, 400, 150)), (_SHAPE, (1150, 400, 150))],
    ) == [(("shape", 0), ("shape", 0)), (("shape", 1), ("shape", 1))]


def test_mm_minimal_alpha_fixture_like_pairs_black_and_green_by_tier1():
    # Minimal Alpha_DSK 1→2 as the IWA reads it: all six squares share one gate key
    # and one raw path. Slide 1: black (white stroke) back, green (op 0.29) front.
    # Slide 2: black at ki 0, theme yellow/red/pink at ki 1–3, green at ki 4. Tier 1
    # alone sends black→ki 0 and green→ki 4, whatever the distances.
    black = ("stroke:white4|op:1", "path:174x154", "style:15336742")
    green = ("stroke:none|op:0.29", "path:174x154", "style:15336941")
    theme = [("stroke:none|op:1", "path:174x154", f"style:{s}") for s in (8520, 8519, 8521)]
    before = [(_SHAPE, (900, 100, 174), black), (_SHAPE, (100, 100, 174), green)]
    after = [
        (_SHAPE, (100, 600, 174), black),
        *[(_SHAPE, (x, 100, 351), t) for x, t in zip((150, 500, 900), theme)],
        (_SHAPE, (1500, 600, 351), green),
    ]
    assert _matches(before, after) == [(("shape", 0), ("shape", 0)), (("shape", 1), ("shape", 4))]


def test_mm_prefs_survive_a_json_round_trip():
    # mmKeys/mmPrefs kindIndex become strings after JSON; the tier1 case still resolves.
    import json

    from obed_edom.validate import _mm_matches

    stroked = ("stroke:white4|op:1", *_PLAIN[1:])
    payload = json.loads(json.dumps(_mm_payload(
        _mm_slide(1, [(_SHAPE, _LEFT, _PLAIN), (_SHAPE, _RIGHT, stroked)], out=True),
        _mm_slide(2, [(_SHAPE, _LEFT, stroked), (_SHAPE, _RIGHT, _PLAIN)]),
    )))
    assert set(payload["slides"][0]["mmPrefs"]["shape"]) == {"0", "1"}
    assert sorted(_mm_matches(*payload["slides"])) == [
        (("shape", 0), ("shape", 1)),
        (("shape", 1), ("shape", 0)),
    ]
    assert _pairs(_zorder(payload)) == ["'shape #0' and 'shape #1'"]


_MINIMAL_ALPHA = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")


@pytest.mark.skipif(not _MINIMAL_ALPHA.exists(), reason="Minimal Alpha_DSK.key not on this machine")
def test_mm_real_minimal_alpha_pairs_black_and_green_like_keynote():
    # Live Keynote (FX, 2026-09-24): black 1:0 ↔ 2:0, green 1:1 ↔ 2:4 (the big green).
    from obed_edom.iwa_runs import attach_magic_move
    from obed_edom.offline_inspect import offline_wall_payload
    from obed_edom.validate import _mm_matches

    payload = offline_wall_payload(_MINIMAL_ALPHA)
    attach_magic_move(_MINIMAL_ALPHA, payload)
    slides = {int(s["number"]): s for s in payload["slides"]}
    matches = _mm_matches(slides[1], slides[2])
    assert (("shape", 0), ("shape", 0)) in matches
    assert (("shape", 1), ("shape", 4)) in matches


# The live Keynote experiment geometries (gen.py `V`): squares (x, y, side) of one
# image; slide-1 lists are back→front creation order.
_A, _B = (100, 100, 200), (1300, 500, 500)


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        pytest.param([_A, _B], [(800, 400, 300)], [(1, 0)], id="Z0-big-B-to-C"),
        pytest.param([_B, _A], [(800, 400, 300)], [(0, 0)], id="Z1-big-B-to-C"),
        pytest.param([_A, _B], [(150, 150, 250)], [(0, 0)], id="N0-A-to-C"),
        pytest.param([_B, _A], [(150, 150, 250)], [(1, 0)], id="N1-A-to-C"),
        pytest.param([_A, _B], [(1350, 550, 300)], [(1, 0)], id="D0-B-to-C"),
        pytest.param([_A, _B], [(150, 150, 250)], [(0, 0)], id="D1-A-to-C"),
        pytest.param([_A, _B], [(1300, 100, 300), (100, 500, 300)], [(0, 1), (1, 0)], id="M2-A-down-B-up"),
        pytest.param([(100, 100, 100), (400, 100, 600)], [(300, 100, 100)], [(0, 0)], id="C1-small-to-target"),
        # Greedy would take the 50pt 600→550 pair first and leave 100→1150; Keynote
        # (and the optimal assignment) moves both right instead.
        pytest.param(
            [(100, 400, 150), (600, 400, 150)], [(550, 400, 150), (1150, 400, 150)], [(0, 0), (1, 1)],
            id="G1-optimal-not-greedy",
        ),
    ],
)
def test_mm_duplicate_media_pair_like_keynote(before, after, expected):
    got = _matches([(_SQ, r) for r in before], [(_SQ, r) for r in after])
    assert got == [(("image", i), ("image", j)) for i, j in expected]


def test_mm_zorder_flip_fires_on_a_flip_among_duplicated_movies():
    # M2 geometry with movies: A (back) pairs with the (100, 500) copy, B (front) with
    # the (1300, 100) copy — which slide 2 stacks behind A's partner. Both are clip.mov,
    # so the labels carry their kind/kindIndex.
    before = [(_CLIP, _A), (_CLIP, _B)]
    payload = _mm_payload(
        _mm_slide(1, before, out=True),
        _mm_slide(2, [(_CLIP, (1300, 100, 300)), (_CLIP, (100, 500, 300))]),
    )
    assert _pairs(_zorder(payload)) == ["'clip.mov (movie #0)' and 'clip.mov (movie #1)'"]
    same = _mm_payload(
        _mm_slide(1, before, out=True),
        _mm_slide(2, [(_CLIP, (100, 500, 300)), (_CLIP, (1300, 100, 300))]),
    )
    assert _zorder(same) == []


def test_mm_duplicate_media_tie_is_skipped():
    # The target sits exactly between the two copies: either pairing is as close, so
    # the class is ambiguous and nothing is matched (a unique title still is).
    assert _matches(
        [(_SQ, (0, 0, 100)), (_SQ, (200, 0, 100)), _TITLE],
        [_TITLE, (_SQ, (100, 0, 100))],
    ) == [(("text", 0), ("text", 0))]


def test_mm_duplicate_media_near_tie_at_large_totals_keeps_the_strict_minimum():
    # Totals near 1e8 differ by 0.02pt: a relative tolerance would call this a tie,
    # the absolute 1e-6 does not.
    assert _matches(
        [(_SQ, (0, 0, 100)), (_SQ, (200_000_000, 0, 100))],
        [(_SQ, (100_000_000 - 0.01, 0, 100))],
    ) == [(("image", 0), ("image", 0))]


def test_mm_duplicate_media_without_geometry_is_skipped():
    assert _matches([(_SQ, (0, 0, 100)), _SQ], [(_SQ, (0, 0, 100))]) == []


def test_mm_duplicate_media_unequal_counts_match_the_smaller_side():
    got = _matches(
        [(_SQ, (0, 0, 100)), (_SQ, (900, 0, 100)), (_SQ, (1800, 0, 100))],
        [(_SQ, (1750, 0, 100)), (_SQ, (50, 0, 100))],
    )
    assert got == [(("image", 0), ("image", 1)), (("image", 2), ("image", 0))]
    assert _matches([(_SQ, (0, 0, 100))], [(_SQ, (900, 0, 100)), (_SQ, (50, 0, 100))]) == [
        (("image", 0), ("image", 1)),
    ]


def test_mm_duplicate_media_class_too_large_is_skipped():
    before = [(_SQ, (i * 200, 0, 100)) for i in range(8)]
    after = [(_SQ, (i * 200 + 10, 0, 100)) for i in range(8)]
    assert _matches(before, after) == []
    assert len(_matches(before[:7], after[:7])) == 7


def test_mm_zorder_flip_disambiguates_colliding_labels_after_a_json_round_trip():
    # Two different clips both called clip.mov: without the kind/kindIndex suffix the
    # two inverted pairs would share a message and dedupe_flags would drop one.
    import json

    first, second = "movie:A=", "movie:B="
    payload = json.loads(json.dumps(_mm_payload(
        _mm_slide(1, [first, second, _TITLE], out=True),
        _mm_slide(2, [_TITLE, first, second]),
    )))
    for item in payload["slides"][0]["items"]:
        if item["kind"] == "movie":
            item["fileName"] = "clip.mov"
    flags = [
        f for f in validate_inspect(payload, use_ocr=False, check_passages=False)
        if f.rule == "mm.zorder_flip"
    ]
    assert _pairs(flags) == [
        "'clip.mov (movie #0)' and 'Welcome'",
        "'clip.mov (movie #1)' and 'Welcome'",
    ]


def test_mm_zorder_flip_labels_text_by_snippet():
    long = "text:" + "Grace upon grace " * 3
    payload = _mm_payload(
        _mm_slide(1, [long, _SMALL], out=True),
        _mm_slide(2, [_SMALL, long]),
    )
    (flag,) = _zorder(payload)
    assert flag.message.startswith("'Grace upon grace Grace upon g…' and 'IMG-WA0125.mp4'")


def test_mm_zorder_flip_labels_stay_distinct_when_a_raw_name_matches_a_disambiguated_one():
    # Adversarial: a third clip is literally named "clip.mov (movie #0)", which is the
    # label the first of two "clip.mov" movies is given, and a fourth is named after the
    # label that resolving that second collision produces. Every inverted pair must keep
    # its own message so dedupe_flags drops none of them.
    keys = ["movie:A=", "movie:B=", "movie:C=", "movie:D="]
    payload = _mm_payload(
        _mm_slide(1, [*keys, _TITLE], out=True),
        _mm_slide(2, [_TITLE, *keys]),
    )
    names = ["clip.mov", "clip.mov", "clip.mov (movie #0)", "clip.mov (movie #0) (movie #0)"]
    for item, name in zip([i for i in payload["slides"][0]["items"] if i["kind"] == "movie"], names):
        item["fileName"] = name
    flags = [
        f for f in validate_inspect(payload, use_ocr=False, check_passages=False)
        if f.rule == "mm.zorder_flip"
    ]
    assert _pairs(flags) == [
        "'clip.mov (movie #0) (movie #0) (movie #0)' and 'Welcome'",
        "'clip.mov (movie #1)' and 'Welcome'",
        "'clip.mov (movie #0) (movie #2)' and 'Welcome'",
        "'clip.mov (movie #0) (movie #0) (movie #3)' and 'Welcome'",
    ]
