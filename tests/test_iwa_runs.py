"""Tests for offline IWA per-run style extraction (obed_edom.iwa_runs).

The matcher and style resolver are exercised WITHOUT keynote-parser: only
``_load_deck`` (the sole importer of the optional extra) touches it, so every
test here builds a synthetic IWA object graph or calls the pure helpers directly.
A single local-only integration test runs against a real deck when both the deck
and the parser are available.

JXA inspect reports plain objectText() but no per-run style, so item["runs"] is
[] without this module. attach_runs raises ImportError (caught; runs stay [])
when the optional iwa extra is missing.

Normalize by stripping the object-replacement char and collapsing whitespace —
JXA and IWA disagree on breaks/nbsp. Colour is IWA 0-1 floats → 0-255 for
highlight detection. Inheritance: first value up super.parent wins. Identical
twins assign IWA order → payload order. Grouped copy with JXA childCount 0 goes
to slide.groupedText only, never items/geometry. groupChildText signatures must
use the same join as keynote._norm_sig_handler or reuse dedup misses.
"""

import copy
from pathlib import Path

import pytest

import obed_edom.iwa_runs as iwa
from obed_edom.iwa_runs import (
    _match_runs_to_items,
    _normalize_text,
    _slide_group_child_text,
    _slide_grouped_text,
    attach_group_captions,
    attach_group_child_text,
    attach_group_children,
    attach_runs,
    resolve_para_style,
    resolve_style,
)

REAL_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key")
GW_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (GW).key")
MAP_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Map_Extracted_Wall_1st.key")


# --------------------------------------------------------------------------
# Matcher — pure, no parser.
# --------------------------------------------------------------------------
def _run(marker):
    return [{"text": marker, "color": None}]


def test_match_attaches_by_normalized_text():
    text_objects = [{"text": "Hello world", "runs": _run("A")}]
    items = [{"kind": "text", "text": "Hello world"}]
    _match_runs_to_items(text_objects, items)
    assert items[0]["runs"] == _run("A")


def test_match_identical_twins_assign_in_iwa_order():
    # Two text objects with the same copy, two items with the same copy: the runs
    # are handed out in IWA order to the items in payload order.
    text_objects = [
        {"text": "Same", "runs": _run("first")},
        {"text": "Same", "runs": _run("second")},
    ]
    items = [
        {"kind": "text", "text": "Same"},
        {"kind": "text", "text": "Same"},
    ]
    _match_runs_to_items(text_objects, items)
    assert items[0]["runs"] == _run("first")
    assert items[1]["runs"] == _run("second")


def test_match_survives_newline_normalization_drift():
    # IWA carries a real \n and  ; JXA objectText carries \n and \xa0. Both
    # must normalize to the same string and still match.
    text_objects = [{"text": "Line one Line two\xa0end", "runs": _run("A")}]
    items = [{"kind": "text", "text": "Line one\nLine two end"}]
    _match_runs_to_items(text_objects, items)
    assert items[0]["runs"] == _run("A")


def test_match_no_candidate_leaves_runs_empty():
    text_objects = [{"text": "Present", "runs": _run("A")}]
    items = [{"kind": "text", "text": "Absent"}]
    _match_runs_to_items(text_objects, items)
    assert items[0]["runs"] == []


def test_match_skips_duplicate_and_non_text_items():
    text_objects = [{"text": "Copy", "runs": _run("A")}]
    items = [
        {"kind": "text", "text": "Copy", "duplicateOf": 3},  # duplicate shape copy
        {"kind": "image", "text": "Copy"},  # not text/shape
        {"kind": "shape", "text": "Copy"},  # the real target
    ]
    _match_runs_to_items(text_objects, items)
    assert "runs" not in items[0]  # duplicate untouched
    assert "runs" not in items[1]  # image untouched
    assert items[2]["runs"] == _run("A")


def test_normalize_strips_object_replacement_and_collapses_ws():
    assert _normalize_text("  a\n b\xa0￼ c  ") == "a b c"
    assert _normalize_text(None) == ""
    assert _normalize_text("￼") == ""


# --------------------------------------------------------------------------
# Style resolver — pure, no parser.
# --------------------------------------------------------------------------
def _charstyle(name, parent=None, color=None, **cp):
    props = dict(cp)
    if color is not None:
        props["fontColor"] = {"r": color[0], "g": color[1], "b": color[2]}
    sup = {"name": name}
    if parent is not None:
        sup["parent"] = {"identifier": parent}
    return {"_pbtype": "TSWP.CharacterStyleArchive", "charProperties": props, "super": sup}


def test_resolve_inherits_color_and_bold_up_parent_chain():
    objects = {
        "1": _charstyle("Child", parent="2", bold=True),  # own bold, no colour
        "2": _charstyle("Base", color=[1, 1, 0], italic=True),  # colour + italic
    }
    resolved = resolve_style("1", objects, {})
    assert resolved["color"] == [255, 255, 0]  # inherited from parent
    assert resolved["bold"] is True  # own override
    assert resolved["italic"] is True  # inherited
    assert resolved["styleName"] == "Child"  # first named ancestor


def test_resolve_missing_color_is_none():
    objects = {"1": _charstyle("Plain", bold=False)}
    resolved = resolve_style("1", objects, {})
    assert resolved["color"] is None
    assert resolved["capitalization"] is None
    # WIN 3: both new keys are present and default to None when absent.
    assert resolved["fontName"] is None
    assert resolved["superscript"] is None


def test_resolve_extracts_smallcaps_capitalization():
    objects = {"1": _charstyle("Scripture", capitalization="kSmallCaps")}
    resolved = resolve_style("1", objects, {})
    assert resolved["capitalization"] == "kSmallCaps"


def test_resolve_extracts_fontname_and_superscript():
    objects = {
        "1": _charstyle("Verse Number", fontName="Amplitude-Bold", superscript="kSuperscript")
    }
    resolved = resolve_style("1", objects, {})
    assert resolved["fontName"] == "Amplitude-Bold"
    assert resolved["superscript"] == "kSuperscript"


def test_resolve_inherits_fontname_and_superscript_up_chain():
    objects = {
        "1": _charstyle("Child", parent="2", bold=True),  # no font/superscript of its own
        "2": _charstyle("Base", fontName="AzoSans-Medium", superscript="kSuperscript"),
    }
    resolved = resolve_style("1", objects, {})
    assert resolved["fontName"] == "AzoSans-Medium"  # inherited
    assert resolved["superscript"] == "kSuperscript"  # inherited


def test_resolve_exposes_tracking_kerning():
    # charProperties.kerning surfaces as `tracking` for the offline shaper; absent -> None.
    objects = {"1": _charstyle("Spaced", kerning=1.5)}
    assert resolve_style("1", objects, {})["tracking"] == 1.5
    assert resolve_style("2", {"2": _charstyle("Plain")}, {})["tracking"] is None


# --------------------------------------------------------------------------
# Paragraph-style resolver — the metrics the offline text shaper needs.
# --------------------------------------------------------------------------
def _parastyle(name=None, parent=None, **pp):
    sup: dict = {}
    if name is not None:
        sup["name"] = name
    if parent is not None:
        sup["parent"] = {"identifier": parent}
    return {"_pbtype": "TSWP.ParagraphStyleArchive", "paraProperties": dict(pp), "super": sup}


def test_resolve_para_style_reads_metrics():
    objects = {"1": _parastyle(lineSpacing={"amount": 0.8}, alignment="TATvalue2",
                               spaceBefore=6.0, firstLineIndent=12.0)}
    m = resolve_para_style("1", objects, {})
    assert m["lineSpacing"] == {"amount": 0.8}  # passed through unchanged
    assert m["alignment"] == "TATvalue2"
    assert m["spaceBefore"] == 6.0
    assert m["firstLineIndent"] == 12.0


def test_resolve_para_style_inherits_up_parent_chain():
    objects = {
        "1": _parastyle(parent="2", alignment="TATvalue0"),  # own alignment only
        "2": _parastyle(lineSpacing={"amount": 0.7}, spaceAfter=4.0),
    }
    m = resolve_para_style("1", objects, {})
    assert m["alignment"] == "TATvalue0"  # own override
    assert m["lineSpacing"] == {"amount": 0.7}  # inherited
    assert m["spaceAfter"] == 4.0  # inherited


def test_resolve_para_style_none_and_cache_namespacing():
    assert resolve_para_style(None, {}, {}) == {}
    # A shared cache must not let the char-style entry for id "1" collide with the
    # paragraph-style entry for id "1" (different archives can share an id space).
    cache: dict = {}
    resolve_style("1", {"1": _charstyle("C", fontName="AzoSans-Regular")}, cache)
    para = resolve_para_style("1", {"1": _parastyle(alignment="TATvalue1")}, cache)
    assert para["alignment"] == "TATvalue1"


# --------------------------------------------------------------------------
# attach_runs — index keying, with a synthetic graph (only _load_deck stubbed).
# --------------------------------------------------------------------------
def _synthetic_deck():
    def storage(text, style_id):
        return {
            "_pbtype": "TSWP.StorageArchive",
            "text": [text],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": style_id}}]},
        }

    objects = {
        "100": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "200"}},
        "101": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "201"}},
        "102": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "202"}},
        "200": {"_pbtype": "KN.SlideArchive"},
        "201": {"_pbtype": "KN.SlideArchive"},
        "202": {"_pbtype": "KN.SlideArchive"},
        "300": storage("Alpha", "400"),
        "301": storage("Bravo", "401"),
        "302": storage("Charlie", "402"),
        "400": _charstyle("StyleA", color=[1, 1, 0]),
        "401": _charstyle("StyleB", color=[0, 1, 1]),
        "402": _charstyle("StyleC", color=[1, 0, 0]),
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "100"}, {"identifier": "101"}, {"identifier": "102"}]},
        },
    }
    id_to_file = {"200": "f0", "201": "f1", "202": "f2", "300": "f0", "301": "f1", "302": "f2"}
    file_ids = {"f0": ["200", "300"], "f1": ["201", "301"], "f2": ["202", "302"]}
    return objects, id_to_file, file_ids


def test_attach_keys_by_true_slide_index_on_ranged_subset(monkeypatch):
    # A ranged inspect ships only slide index 2. attach_runs must look the deck's
    # third slide up by that true index, not positionally (which would grab slide 0).
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _synthetic_deck())
    payload = {"slides": [{"index": 2, "items": [{"index": 0, "kind": "text", "text": "Charlie"}]}]}
    attach_runs("ignored.key", payload)
    runs = payload["slides"][0]["items"][0]["runs"]
    assert runs and runs[0]["styleName"] == "StyleC"
    assert runs[0]["color"] == [255, 0, 0]


def test_attach_full_deck_matches_each_slide(monkeypatch):
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _synthetic_deck())
    payload = {
        "slides": [
            {"index": 0, "items": [{"kind": "text", "text": "Alpha"}]},
            {"index": 1, "items": [{"kind": "text", "text": "Bravo"}]},
            {"index": 2, "items": [{"kind": "text", "text": "Charlie"}]},
        ]
    }
    attach_runs("ignored.key", payload)
    names = [s["items"][0]["runs"][0]["styleName"] for s in payload["slides"]]
    assert names == ["StyleA", "StyleB", "StyleC"]


def test_attach_import_error_is_graceful(monkeypatch):
    # Base install without the `iwa` extra: _load_deck's lazy import raises, and
    # the inspect caller's try/except swallows it. attach_runs itself raises, so
    # here we assert the runs stay untouched when the caller-style guard is used.
    def boom(_p):
        raise ImportError("No module named 'keynote_parser'")

    monkeypatch.setattr(iwa, "_load_deck", boom)
    payload = {"slides": [{"index": 0, "items": [{"kind": "text", "text": "Alpha"}]}]}
    with pytest.raises(ImportError):
        attach_runs("ignored.key", payload)
    assert "runs" not in payload["slides"][0]["items"][0]


# --------------------------------------------------------------------------
# WIN 2 — grouped text: collection from a group subtree + the resizer invariant.
# --------------------------------------------------------------------------
def _grouped_deck():
    """One slide whose only copy lives inside a nested group subtree.

    Slide 210 owns top-level group 500; 500 holds a text shape ("Countries") and a
    NESTED group 510, which holds another text shape ("CHC Churches"). No top-level
    (ungrouped) text object exists, mirroring the Map deck's stat-block slides.
    """

    def storage(text, style_id):
        return {
            "_pbtype": "TSWP.StorageArchive",
            "text": [text],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": style_id}}]},
        }

    def shape(storage_id):
        return {"_pbtype": "TSWP.ShapeInfoArchive", "ownedStorage": {"identifier": storage_id}}

    objects = {
        "110": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "210"}},
        # drawablesZOrder lets iwa_kindindex.derive_kind_index assign the top-level
        # group its (kind, kindIndex); the groupChildText helper reads it from here.
        "210": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "500"}]},
        "500": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"parent": {"identifier": "210"}},  # top-level: parent is the slide
            "children": [{"identifier": "501"}, {"identifier": "510"}],
        },
        "501": shape("601"),
        "601": storage("Countries", "400"),
        "510": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"parent": {"identifier": "500"}},  # nested: parent is group 500
            "children": [{"identifier": "511"}],
        },
        "511": shape("611"),
        "611": storage("CHC Churches", "401"),
        "400": _charstyle("StyleA", color=[1, 1, 0]),
        "401": _charstyle("StyleB", color=[0, 1, 1]),
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "110"}]},
        },
    }
    id_to_file = {k: "g0" for k in ("210", "500", "501", "601", "510", "511", "611")}
    file_ids = {"g0": ["210", "500", "501", "601", "510", "511", "611"]}
    return objects, id_to_file, file_ids


def test_grouped_text_collected_from_nested_group_subtree():
    objects, _id_to_file, file_ids = _grouped_deck()
    grouped = _slide_grouped_text(file_ids["g0"], objects, {})
    texts = [g["text"] for g in grouped]
    # Both the top-level-group shape and the once-nested-group shape are collected,
    # each exactly once (no double-count).
    assert sorted(texts) == ["CHC Churches", "Countries"]
    assert all(g["runs"] for g in grouped)  # runs come along via storage_runs
    styles = {g["text"]: g["runs"][0]["styleName"] for g in grouped}
    assert styles == {"Countries": "StyleA", "CHC Churches": "StyleB"}
    # WIN 3 keys are present on every emitted run dict (here None: styles set none).
    run = grouped[0]["runs"][0]
    assert "fontName" in run and "superscript" in run


def test_grouped_text_reaches_scoring_but_not_default_plain_text():
    from obed_edom.inspect import slide_plain_text

    objects, _id_to_file, file_ids = _grouped_deck()
    grouped = _slide_grouped_text(file_ids["g0"], objects, {})
    slide = {"items": [], "groupedText": grouped}
    # Default plain text (the reuse-fingerprint path) never sees grouped copy.
    assert slide_plain_text(slide) == ""
    # The scoring path opts in and sees it.
    scored = slide_plain_text(slide, include_grouped=True)
    assert "Countries" in scored and "CHC Churches" in scored


def test_grouped_attach_leaves_resizer_input_and_digests_untouched(monkeypatch):
    # THE safety invariant: attaching groupedText must not perturb the resize input
    # (items / group children / childCount / geometry) or the reuse fingerprint.
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _grouped_deck())
    payload = {
        "slides": [
            {
                "index": 0,
                "items": [
                    # JXA reports every group as childCount 0, children [] — exactly
                    # what map_remap.coincident_duplicate_ids keys on.
                    {"index": 0, "kind": "group", "children": [], "childCount": 0,
                     "x": 10.0, "y": 20.0, "w": 30.0, "h": 40.0},
                    {"index": 1, "kind": "group", "children": [], "childCount": 0,
                     "x": 50.0, "y": 60.0, "w": 70.0, "h": 80.0},
                ],
            }
        ]
    }
    from obed_edom.baseline import deck_slide_digests

    items_before = copy.deepcopy(payload["slides"][0]["items"])
    digests_before = deck_slide_digests(copy.deepcopy(payload))

    attach_runs("ignored.key", payload)
    # The resizer-only groupChildText attach must ALSO be side-effect-free.
    attach_group_child_text("ignored.key", payload)

    # groupedText got attached...
    grouped_texts = [g["text"] for g in payload["slides"][0]["groupedText"]]
    assert sorted(grouped_texts) == ["CHC Churches", "Countries"]
    # ...and groupChildText got attached: the top-level group's DFS leaf signature.
    assert payload["slides"][0]["groupChildText"] == {0: "Countries\nCHC Churches"}
    # ...but items (incl. every group's children/childCount/geometry) are UNCHANGED.
    assert payload["slides"][0]["items"] == items_before
    for item in payload["slides"][0]["items"]:
        assert item["children"] == [] and item["childCount"] == 0
    # ...and the reuse fingerprint is byte-identical (neither groupedText nor
    # groupChildText is in the digest).
    assert deck_slide_digests(payload) == digests_before


def test_group_child_text_dfs_signature_and_kindindex_alignment():
    # The signature is the DFS-order concatenation of full-depth normalized leaf text
    # (Countries at depth 1, then CHC Churches inside the nested group), keyed by the
    # SAME kindIndex derive_kind_index assigns the top-level group (0).
    objects, _id_to_file, _file_ids = _grouped_deck()
    gct = _slide_group_child_text(objects["210"], objects, {})
    assert gct == {0: "Countries\nCHC Churches"}

    from obed_edom.iwa_kindindex import derive_kind_index

    groups = [r for r in derive_kind_index(objects["210"], objects) if r["kind"] == "group"]
    assert [r["kindIndex"] for r in groups] == [0]  # helper key == derive's kindIndex


def test_group_child_text_absent_when_no_groups(monkeypatch):
    # A slide with no top-level groups gets no groupChildText field at all.
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _grouped_deck())
    payload = {"slides": [{"index": 5, "items": []}]}  # index with no matching slide
    attach_group_child_text("ignored.key", payload)
    assert "groupChildText" not in payload["slides"][0]


# --------------------------------------------------------------------------
# Consumer lights up when a yellow punctuation run is present.
# --------------------------------------------------------------------------
def test_highlight_punctuation_flags_fire_on_yellow_punctuation():
    from obed_edom.validate import _highlight_punctuation_flags

    slide = {
        "items": [
            {
                "kind": "text",
                "text": "God,",
                "runs": [
                    {"text": "God", "color": [255, 255, 255]},
                    {"text": ",", "color": [255, 251, 0]},  # yellow highlight on punctuation
                ],
            }
        ]
    }
    flags = _highlight_punctuation_flags(slide, "loc", 1, "L")
    assert any(f.category == "highlight" for f in flags)


# --------------------------------------------------------------------------
# Local-only integration test against a real finalized deck.
# --------------------------------------------------------------------------
def test_real_deck_populates_verse_number_run():
    if not REAL_DECK.is_file():
        pytest.skip("real DSK deck not present (local operator file)")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")

    from obed_edom.iwa_runs import _load_deck, _slide_text_objects, slide_order

    # Build a payload mirroring the deck's own text objects, then attach.
    objects, id_to_file, file_ids = _load_deck(REAL_DECK)
    order = slide_order(objects)
    cache: dict = {}
    slides = []
    for idx, (slide_id, _skipped) in enumerate(order):
        tos = _slide_text_objects(file_ids.get(id_to_file.get(slide_id), []), objects, cache)
        items = [{"index": i, "kind": "text", "text": t["text"]} for i, t in enumerate(tos)]
        slides.append({"index": idx, "items": items})
    payload = {"slides": slides}
    attach_runs(REAL_DECK, payload)

    all_runs = [r for s in payload["slides"] for it in s["items"] for r in (it.get("runs") or [])]
    assert all_runs, "expected runs to be populated on the real deck"
    verse = [
        r
        for r in all_runs
        if r.get("styleName") == "Verse Number" and r.get("color") == [255, 251, 0]
    ]
    assert verse, "expected the yellow #FFFB00 Verse Number run to be present"
    # The DSK deck small-caps "Lord" must surface capitalization for the diff.
    assert any(str(r.get("capitalization") or "").lower().find("small") >= 0 for r in all_runs)


def test_real_deck_gw_populates_superscript_verse_numbers():
    # WIN 3: the GW deck's superscript verse numbers must surface as kSuperscript.
    if not GW_DECK.is_file():
        pytest.skip("real GW deck not present (local operator file)")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")

    from obed_edom.iwa_runs import (
        _load_deck,
        _slide_grouped_text,
        _slide_text_objects,
        slide_order,
    )

    objects, id_to_file, file_ids = _load_deck(GW_DECK)
    order = slide_order(objects)
    cache: dict = {}
    all_runs = []
    for _idx, (slide_id, _skipped) in enumerate(order):
        ids = file_ids.get(id_to_file.get(slide_id), [])
        for to in _slide_text_objects(ids, objects, cache) + _slide_grouped_text(ids, objects, cache):
            all_runs.extend(to["runs"])
    assert all_runs, "expected runs on the GW deck"
    assert any(
        r.get("superscript") == "kSuperscript" for r in all_runs
    ), "expected a kSuperscript verse-number run on the GW deck"
    # fontName is best-effort (often None, lives on the paragraph style) but the
    # deck should carry at least some resolved PostScript font names.
    assert any(r.get("fontName") for r in all_runs)


def test_real_deck_map_grouped_stat_labels_reach_scoring_text():
    # WIN 2: the Map deck's grouped stat-block labels must land in the SCORING text.
    if not MAP_DECK.is_file():
        pytest.skip("real Map deck not present (local operator file)")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")

    from obed_edom.inspect import slide_plain_text

    # Re-inspect the CURRENT deck via the IWA graph (the .cache is stale). Build a
    # payload with the group items JXA would report as childCount 0, attach, then
    # assert the labels appear ONLY in the grouped scoring text, not the default.
    objects, id_to_file, file_ids = iwa._load_deck(MAP_DECK)
    order = iwa.slide_order(objects)
    payload = {"slides": [{"index": i, "items": []} for i in range(len(order))]}
    attach_runs(MAP_DECK, payload)

    scoring = "\n".join(
        slide_plain_text(s, include_grouped=True) for s in payload["slides"]
    )
    default = "\n".join(slide_plain_text(s) for s in payload["slides"])
    scoring = _normalize_text(scoring)
    default = _normalize_text(default)
    for label in ("CHC Churches", "Countries", "Total Church Buildings"):
        assert label in scoring, f"expected {label!r} in grouped scoring text"
        assert label not in default, f"{label!r} must stay out of the default fingerprint text"


# --------------------------------------------------------------------------
# attach_group_captions — one-caption-leaf groups only, real archive shape
# (leaf geometry at super.super.geometry, leaf style ref at leaf.super.style).
# --------------------------------------------------------------------------
def _card_deck():
    """Slide 310 owns two top-level groups: 700 (a card: one image + one caption
    leaf, styled 10pt Amplitude-Bold, 4.0pt padding) and 710 (a roster: two text
    leaves — must NOT get a groupCaption entry)."""

    def leaf_geom(x, y, w, h):
        return {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}, "flags": 3, "angle": 0.0}

    objects = {
        "120": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "310"}},
        "310": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "700"}, {"identifier": "710"}]},
        "700": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"parent": {"identifier": "310"}},
            "geometry": {"position": {"x": 1251.1, "y": 190.5}, "size": {"width": 131.8, "height": 109.5}},
            "children": [{"identifier": "701"}, {"identifier": "702"}],
        },
        "701": {"_pbtype": "TSD.ImageArchive"},  # non-text sibling; ignored
        "702": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "ownedStorage": {"identifier": "702-st"},
            "super": {"style": {"identifier": "702-style"}, "super": {"geometry": leaf_geom(3.7, 1.3, 124.4, 19.5)}},
        },
        "702-st": {
            "_pbtype": "TSWP.StorageArchive", "text": ["CHC Villamonte"],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": "702-c"}}]},
        },
        "702-c": {"_pbtype": "TSWP.CharacterStyleArchive",
                  "charProperties": {"fontName": "Amplitude-Bold", "fontSize": 10.0}},
        "702-style": {"_pbtype": "TSWP.ShapeStyleArchive",
                      "shapeProperties": {"padding": {"left": 4.0, "top": 4.0, "right": 4.0, "bottom": 4.0}}},
        "710": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"parent": {"identifier": "310"}},
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 400.0}},
            "children": [{"identifier": "711"}, {"identifier": "712"}],
        },
        "711": {
            "_pbtype": "TSWP.ShapeInfoArchive", "ownedStorage": {"identifier": "711-st"},
            "super": {"super": {"geometry": leaf_geom(0.0, 0.0, 200.0, 30.0)}},
        },
        "711-st": {"_pbtype": "TSWP.StorageArchive", "text": ["CHC Aaliana"]},
        "712": {
            "_pbtype": "TSWP.ShapeInfoArchive", "ownedStorage": {"identifier": "712-st"},
            "super": {"super": {"geometry": leaf_geom(0.0, 40.0, 200.0, 30.0)}},
        },
        "712-st": {"_pbtype": "TSWP.StorageArchive", "text": ["CHC Bindoy"]},
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "120"}]}},
    }
    return objects, {}, {}


def test_attach_group_captions_only_single_text_leaf_groups():
    objects, id_to_file, file_ids = _card_deck()
    payload = {"slides": [{"index": 0, "number": 1, "items": []}]}
    attach_group_captions("ignored.key", payload, deck=(objects, id_to_file, file_ids))
    caps = payload["slides"][0]["groupCaption"]
    assert list(caps.keys()) == [0]  # only the card group (kindIndex 0); the roster is excluded
    cap = caps[0]
    assert cap["text"] == "CHC Villamonte"
    assert cap["font"] == "Amplitude-Bold"
    assert cap["size"] == 10.0
    assert cap["inset"] == 4.0
    assert cap["groupW"] == pytest.approx(131.8)
    assert cap["boxW"] == pytest.approx(124.4)
    assert cap["boxH"] == pytest.approx(19.5)


def test_single_text_leaf_ignores_object_replacement_only_siblings():
    # Review finding: _card_sample_for (via groupChildText/_normalize_text) strips U+FFFC
    # (object-replacement char, an inline image placeholder), but _single_text_leaf used a
    # bare .strip() and counted a placeholder-only leaf as a SECOND text leaf — so a real
    # card (one caption leaf + one placeholder leaf) got a single-leaf groupChildText
    # signature (looks like a card) but NO groupCaption record (looks like a roster),
    # silently losing its caption sizing. Both sources must agree.
    objects = {
        "800": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"parent": {"identifier": "310"}},
            "geometry": {"position": {"x": 1251.1, "y": 190.5}, "size": {"width": 131.8, "height": 109.5}},
            "children": [{"identifier": "801"}, {"identifier": "802"}],
        },
        "801": {
            # A placeholder-only leaf: text is JUST the object-replacement char.
            "_pbtype": "TSWP.ShapeInfoArchive", "ownedStorage": {"identifier": "801-st"},
            "super": {"super": {"geometry": {"position": {"x": 0.0, "y": 0.0},
                                             "size": {"width": 10.0, "height": 10.0},
                                             "flags": 3, "angle": 0.0}}},
        },
        "801-st": {"_pbtype": "TSWP.StorageArchive", "text": ["￼"]},
        "802": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "ownedStorage": {"identifier": "802-st"},
            "super": {"style": {"identifier": "802-style"},
                      "super": {"geometry": {"position": {"x": 3.7, "y": 1.3},
                                             "size": {"width": 124.4, "height": 19.5},
                                             "flags": 3, "angle": 0.0}}},
        },
        "802-st": {
            "_pbtype": "TSWP.StorageArchive", "text": ["CHC Villamonte"],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": "802-c"}}]},
        },
        "802-c": {"_pbtype": "TSWP.CharacterStyleArchive",
                  "charProperties": {"fontName": "Amplitude-Bold", "fontSize": 10.0}},
        "802-style": {"_pbtype": "TSWP.ShapeStyleArchive",
                      "shapeProperties": {"padding": {"left": 4.0}}},
    }
    from obed_edom.iwa_runs import _single_text_leaf, _group_child_signature

    leaf = _single_text_leaf("800", objects)
    assert leaf is not None and leaf is objects["802"]
    sig = _group_child_signature("800", objects, {})
    assert sig == "CHC Villamonte"  # one part: the placeholder normalizes to empty and drops out


# --------------------------------------------------------------------------
# _group_child_records (fix3) — per-child address + SOURCE geometry for a flat
# group holding an autosize text box. A Keynote group resize is an aspect-locked
# uniform scale about the group's LIVE frame that permanently freezes such a
# child wrapped, so the children must be written instead of the group.
# --------------------------------------------------------------------------
from obed_edom.iwa_runs import _group_child_records  # noqa: E402


def test_group_child_records_refuses_a_group_without_an_autosize_child():
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "901"}, {"identifier": "902"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "902": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
    }
    assert _group_child_records(objects["900"], objects) is None


def test_group_child_records_refuses_a_nested_group_or_rotated_child():
    nested = {
        "910": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "911"}, {"identifier": "912"}],
        },
        "911": {"_pbtype": "TSD.GroupArchive", "geometry": {"position": {"x": 0.0, "y": 0.0},
                                                            "size": {"width": 50.0, "height": 40.0}, "angle": 0.0},
                "children": []},
        "912": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "912-st"},
            "super": {
                "geometry": {"position": {"x": 50.0, "y": 0.0}, "size": {"width": 150.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 150.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(nested["910"], nested) is None

    rotated = {
        "920": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "921"}, {"identifier": "922"}],
        },
        "921": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 15.0}},
        },
        "922": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "922-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(rotated["920"], rotated) is None


def test_group_child_records_maps_autosize_centre_and_natural_size():
    # Shaped like Gold slide 2's badge group: plate local (42.6, 0, 278.0, 87.6),
    # text local (47.5, 42.8, 268.2, 0.0) with naturalSize (268.2, 70.0).
    objects = {
        "930": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4121.7, "y": 39.4}, "size": {"width": 278.0, "height": 87.6}, "angle": 0.0},
            "children": [{"identifier": "931"}, {"identifier": "932"}],
        },
        "931": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 42.6, "y": 0.0}, "size": {"width": 278.0, "height": 87.6}, "angle": 0.0}},
        },
        "932": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "932-st"},
            "super": {
                "geometry": {"position": {"x": 47.5, "y": 42.8}, "size": {"width": 268.2, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 268.2, "height": 70.0}}},
            },
        },
    }
    records = _group_child_records(objects["930"], objects)
    assert records is not None
    plate, text = records
    assert plate["kind"] == "shape" and plate["kindIndex"] == 0 and plate["autosize"] is False
    assert plate["x"] == pytest.approx(4164.3)
    assert plate["y"] == pytest.approx(39.4)
    assert plate["w"] == pytest.approx(278.0)
    assert plate["h"] == pytest.approx(87.6)
    assert text["kind"] == "text" and text["kindIndex"] == 0 and text["autosize"] is True
    assert text["x"] == pytest.approx(4169.2)
    assert text["cy"] == pytest.approx(82.2)
    assert text["y"] == pytest.approx(47.2)
    assert text["w"] == pytest.approx(268.2)
    assert text["h"] == pytest.approx(70.0)


def test_group_child_records_refuses_zero_natural_height():
    # naturalSize.height, not just .width, must be positive: an untested gate (review
    # finding 4) — h == 0 both disqualifies the "real" height AND is exactly the value
    # the AS/JS writers' _ch <= 0 fallback triggers on, so the two failure modes would
    # otherwise coincide and land the box half a box low.
    objects = {
        "970": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "971"}, {"identifier": "972"}],
        },
        "971": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "972": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "972-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 0.0}}},
            },
        },
    }
    assert _group_child_records(objects["970"], objects) is None


def test_group_child_records_refuses_zero_natural_width():
    objects = {
        "975": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "976"}, {"identifier": "977"}],
        },
        "976": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "977": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "977-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 0.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 0.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(objects["975"], objects) is None


def test_group_child_records_refuses_frame_width_natural_size_mismatch():
    # iwa_geometry._autosize_rect documents naturalSize as stale; the fix must not
    # trust it blindly when it disagrees with the child's own frame width (also read
    # from the pristine source deck) by more than 1% (review finding 3) — refuse
    # rather than write the wrong width and re-wrap the very box this fix un-wraps.
    objects = {
        "980": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "981"}, {"identifier": "982"}],
        },
        "981": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "982": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "982-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 50.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(objects["980"], objects) is None


def test_group_child_records_refuses_unresolved_mask():
    objects = {
        "940": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "941"}, {"identifier": "942"}],
        },
        "941": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "mask": {"identifier": "999"},  # no "999" in objects: unresolvable
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "942": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "942-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(objects["940"], objects) is None


def test_group_child_records_refuses_off_axis_mask():
    # Same frame/mask numbers as test_group_off_axis_masked_child_is_residual_flagged
    # in test_iwa_geometry.py (known to swing the snapped-vs-raw corner past
    # _MASK_TRUST_PX): a long lever arm (4000x1000) at a 2 degree residual angle.
    objects = {
        "950": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 4200.0, "height": 1100.0}, "angle": 0.0},
            "children": [{"identifier": "951"}, {"identifier": "952"}],
        },
        "951": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "mask": {"identifier": "951-mask"},
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 4000.0, "height": 1000.0}, "angle": 2.0}},
        },
        "951-mask": {"geometry": {"position": {"x": 10.0, "y": 10.0}, "size": {"width": 100.0, "height": 60.0}, "angle": 0.0}},
        "952": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "952-st"},
            "super": {
                "geometry": {"position": {"x": 4000.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 30.0}}},
            },
        },
    }
    assert _group_child_records(objects["950"], objects) is None


def test_group_child_records_line_child_does_not_disqualify_the_group():
    # A zero-height line legitimately has h == 0 (iwa_kindindex._is_line's own
    # docstring): review finding 5 — the group must NOT be refused just because a
    # child shares TSWP.ShapeInfoArchive + h == 0 with a genuine autosize text box.
    objects = {
        "960": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "961"}, {"identifier": "962"}],
        },
        "961": {
            "_pbtype": "TSWP.ShapeInfoArchive",  # not isTextBox: a plain line
            "super": {
                "geometry": {"position": {"x": 0.0, "y": 20.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 0.0}}},
            },
        },
        "962": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "962-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 30.0}}},
            },
        },
    }
    records = _group_child_records(objects["960"], objects)
    assert records is not None
    kinds = {r["kind"] for r in records}
    assert kinds == {"line", "text"}
    line = next(r for r in records if r["kind"] == "line")
    assert line["autosize"] is False
    assert line["w"] == pytest.approx(100.0)
    assert line["h"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# attach_group_children — slide-index alignment, int kindIndex keys, group-only
# filter, omitting the key entirely when a slide has no qualifying group. The
# wiring itself (as opposed to _group_child_records, covered above) had no test.
# --------------------------------------------------------------------------
def _badge_deck():
    """Slide 230 owns a badge group (plate + autosize text, same shape as Gold slide
    2); slide 231 owns a plain two-shape group with no autosize child."""

    def storage(text):
        return {"_pbtype": "TSWP.StorageArchive", "text": [text]}

    objects = {
        "130": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "230"}},
        "131": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "231"}},
        "230": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "930"}]},
        "231": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "940"}]},
        "930": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4121.7, "y": 39.4}, "size": {"width": 278.0, "height": 87.6}, "angle": 0.0},
            "children": [{"identifier": "931"}, {"identifier": "932"}],
        },
        "931": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 42.6, "y": 0.0}, "size": {"width": 278.0, "height": 87.6}, "angle": 0.0}},
        },
        "932": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "932-st"},
            "super": {
                "geometry": {"position": {"x": 47.5, "y": 42.8}, "size": {"width": 268.2, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 268.2, "height": 70.0}}},
            },
        },
        "932-st": storage("Ps George"),
        "940": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "941"}, {"identifier": "942"}],
        },
        "941": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "942": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "130"}, {"identifier": "131"}]},
        },
    }
    return objects, {}, {}


def test_attach_group_children_wires_records_by_slide_index_and_int_kindindex(monkeypatch):
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _badge_deck())
    payload = {"slides": [{"index": 0, "items": []}, {"index": 1, "items": []}]}
    attach_group_children("ignored.key", payload)
    assert "groupChildren" in payload["slides"][0]
    kids = payload["slides"][0]["groupChildren"]
    assert set(kids.keys()) == {0}
    assert all(isinstance(k, int) for k in kids)  # JSON-payload keys, not numpy/str
    assert {r["kind"] for r in kids[0]} == {"shape", "text"}
    # The plain (no-autosize-child) group's slide never gets a groupChildren key at all.
    assert "groupChildren" not in payload["slides"][1]
