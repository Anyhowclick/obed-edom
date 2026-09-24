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
    attach_group_child_runs,
    attach_group_child_text,
    attach_group_children,
    attach_group_content_signature,
    attach_runs,
    attach_slide_builds,
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


def _grouped_deck_with_image():
    """``_grouped_deck`` plus an ImageArchive leaf in the top-level group, DFS-last."""
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "520"})
    objects["520"] = {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "700"}}
    id_to_file["520"] = "g0"
    file_ids["g0"].append("520")
    return objects, id_to_file, file_ids


def test_group_content_signature_resolves_media_file_name_in_dfs_order():
    objects, _id_to_file, _file_ids = _grouped_deck_with_image()
    data_index = {"700": "photo.jpg"}
    sig = iwa._group_content_signature("500", objects, {}, data_index)
    assert sig == "text:Countries\ntext:CHC Churches\nimage:photo.jpg"


def test_group_content_signature_none_when_media_id_unresolved():
    objects, _id_to_file, _file_ids = _grouped_deck_with_image()
    sig = iwa._group_content_signature("500", objects, {}, {})
    assert sig is None


def _grouped_deck_with_textless_shape():
    """``_grouped_deck`` plus a textless shape in the top-level group, DFS-last."""
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "530"})
    objects["530"] = {"_pbtype": "TSWP.ShapeInfoArchive"}
    id_to_file["530"] = "g0"
    file_ids["g0"].append("530")
    return objects, id_to_file, file_ids


def test_group_content_signature_none_when_shape_has_no_path_source():
    extra_objects, _id_to_file, _file_ids = _grouped_deck_with_textless_shape()
    extra_sig = iwa._group_content_signature("500", extra_objects, {}, {})
    assert extra_sig is None


def _grouped_deck_with_decorative_shape(width):
    """``_grouped_deck`` plus a textless shape with a resolvable path source, DFS-last."""
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "530"})
    objects["530"] = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "pathsource": {
            "bezierPathSource": {"type": "kTSDRoundedRectangle", "naturalSize": {"width": width, "height": 10.0}}
        },
    }
    id_to_file["530"] = "g0"
    file_ids["g0"].append("530")
    return objects, id_to_file, file_ids


def test_group_content_signature_distinguishes_decorative_shape_size():
    same_caption_objects, _id_to_file, _file_ids = _grouped_deck_with_decorative_shape(37.35)
    other_size_objects, _id_to_file, _file_ids = _grouped_deck_with_decorative_shape(41.75)
    sig_a = iwa._group_content_signature("500", same_caption_objects, {}, {})
    sig_b = iwa._group_content_signature("500", other_size_objects, {}, {})
    assert sig_a != sig_b
    assert sig_a.startswith("text:Countries\ntext:CHC Churches\nshape:bezierPathSource:kTSDRoundedRectangle:37.4x10.0:")


def _grouped_deck_with_decorative_shape_points(points):
    """``_grouped_deck`` plus a same-size textless shape whose path points differ."""
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "530"})
    objects["530"] = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "pathsource": {
            "bezierPathSource": {
                "type": "kTSDRoundedRectangle",
                "naturalSize": {"width": 37.35, "height": 10.0},
                "points": points,
            }
        },
    }
    id_to_file["530"] = "g0"
    file_ids["g0"].append("530")
    return objects, id_to_file, file_ids


def test_group_content_signature_distinguishes_decorative_shape_path():
    # Same size, different Bezier points: the digest must still tell them apart.
    objects_a, _id_to_file, _file_ids = _grouped_deck_with_decorative_shape_points([[0, 0], [1, 1]])
    objects_b, _id_to_file, _file_ids = _grouped_deck_with_decorative_shape_points([[0, 0], [2, 2]])
    sig_a = iwa._group_content_signature("500", objects_a, {}, {})
    sig_b = iwa._group_content_signature("500", objects_b, {}, {})
    assert sig_a != sig_b
    assert sig_a.rsplit(":", 1)[0] == sig_b.rsplit(":", 1)[0]  # same size prefix, digest differs


def test_group_content_signature_none_for_unrepresentable_child():
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "540"})
    objects["540"] = {"_pbtype": "TSD.SomeOtherArchive"}
    id_to_file["540"] = "g0"
    file_ids["g0"].append("540")
    sig = iwa._group_content_signature("500", objects, {}, {})
    assert sig is None


def test_group_content_signature_none_for_missing_child_identifier():
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": None})
    sig = iwa._group_content_signature("500", objects, {}, {})
    assert sig is None


def test_group_content_signature_none_for_missing_child_object():
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": "999"})  # no such object
    sig = iwa._group_content_signature("500", objects, {}, {})
    assert sig is None


def test_group_child_text_skips_missing_child_identifier():
    # Text-only mode (data_index=None via _collect_group_text) keeps silently skipping.
    objects, id_to_file, file_ids = _grouped_deck()
    objects["500"]["children"].append({"identifier": None})
    leaves: list[dict] = []
    iwa._collect_group_text("500", objects, {}, set(), leaves)
    assert [leaf["text"] for leaf in leaves] == ["Countries", "CHC Churches"]


def test_attach_group_content_signature_raises_for_unreadable_key_path(monkeypatch):
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _grouped_deck())
    payload = {"slides": [{"index": 0, "items": []}]}
    with pytest.raises(OSError):
        attach_group_content_signature("does-not-exist.key", payload)


def test_attach_slide_builds_addresses_targets_by_kind_and_kindindex(tmp_path):
    pytest.importorskip("keynote_parser")
    from test_iwa_write import _build_builds_deck  # noqa: PLC0415 (cross-test-module fixture, established convention)

    deck = _build_builds_deck(tmp_path / "builds.key")
    # index 9 has no matching slide -- must get no 'builds' key at all, not a crash.
    payload = {"slides": [{"index": 0, "items": []}, {"index": 1, "items": []}, {"index": 9, "items": []}]}
    attach_slide_builds(deck, payload)
    slide0, slide1, slide9 = payload["slides"]
    assert slide0["builds"] == [
        {"effect": "apple:dissolve", "animationType": "In", "kind": "text", "kindIndex": 0},
        {"effect": "apple:wipe-iris", "animationType": "In", "kind": "image", "kindIndex": 0},
        {"effect": "apple:bc-zoom-big", "animationType": "In", "kind": "group", "kindIndex": 0},
    ]
    assert slide1["builds"] == [
        {"effect": "apple:dissolve", "animationType": "In", "kind": "text", "kindIndex": 0},
        {"effect": "apple:wipe-iris", "animationType": "In", "kind": "image", "kindIndex": 0},
    ]
    assert "builds" not in slide9


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


# --------------------------------------------------------------------------
# attach_group_child_runs — {group kindIndex: {child kindIndex: {text, font, size,
# runs}}}; two identical groups (GW 50/51's mirror pair shape) must keep separate
# entries, never merged by text equality.
# --------------------------------------------------------------------------
def _mirror_pair_deck():
    """Slide 250 owns two top-level groups, each a badge (shape) plus one autosize
    text child with IDENTICAL text -- same shape as GW 50/51's L/R mirror pair."""

    def storage(text, style_id):
        return {
            "_pbtype": "TSWP.StorageArchive",
            "text": [text],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": style_id}}]},
        }

    objects = {
        "150": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "250"}},
        "250": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "960"}, {"identifier": "970"}]},
        "960": {
            "_pbtype": "TSD.GroupArchive",
            "children": [{"identifier": "961"}, {"identifier": "962"}],
        },
        "961": {  # badge: plain shape, no isTextBox -> kind "shape" only
            "_pbtype": "TSWP.ShapeInfoArchive",
        },
        "962": {  # verse: autosize text-only child -> kind "text"
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "962-st"},
        },
        "962-st": storage("Same verse text", "400"),
        "970": {
            "_pbtype": "TSD.GroupArchive",
            "children": [{"identifier": "971"}, {"identifier": "972"}],
        },
        "971": {
            "_pbtype": "TSWP.ShapeInfoArchive",
        },
        "972": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "972-st"},
        },
        "972-st": storage("Same verse text", "401"),
        "400": _charstyle("StyleA", fontName="ArgentCF-Bold", fontSize=85.0),
        "401": _charstyle("StyleB", fontName="ArgentCF-Bold", fontSize=51.8),
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "150"}]},
        },
    }
    return objects, {}, {}


def test_attach_group_child_runs_keys_by_group_and_child(monkeypatch):
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _mirror_pair_deck())
    payload = {"slides": [{"index": 0, "items": []}]}
    attach_group_child_runs("ignored.key", payload)
    groups = payload["slides"][0]["groupChildRuns"]
    assert set(groups.keys()) == {0, 1}
    # Same text, but two separate entries -- never merged by text equality.
    assert groups[0][0]["text"] == "Same verse text"
    assert groups[1][0]["text"] == "Same verse text"
    assert groups[0][0]["size"] == pytest.approx(85.0)
    assert groups[1][0]["size"] == pytest.approx(51.8)
    # The badge (a plain shape, no isTextBox) never contributes a text-kind entry;
    # each group has exactly the one text child.
    assert set(groups[0].keys()) == {0}
    assert set(groups[1].keys()) == {0}


def _dual_badge_deck():
    """Slide 260 owns GW 44's shape: a dual shape+text badge (custom-path text box,
    `_memberships` -> ["text", "shape"]) plus an autosize verse text child -- the
    finding gw44-group-badge shape. The badge's kindIndex under `_group_child_records`'
    counter rule is `assigned["shape"]` (it is a shape as far as addressing goes), so
    its caption must be keyed there too, not under `assigned["text"]`."""

    def storage(text, style_id):
        return {
            "_pbtype": "TSWP.StorageArchive",
            "text": [text],
            "tableCharStyle": {"entries": [{"characterIndex": 0, "object": {"identifier": style_id}}]},
        }

    objects = {
        "160": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "260"}},
        "260": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "980"}]},
        "980": {
            "_pbtype": "TSD.GroupArchive",
            "children": [{"identifier": "981"}, {"identifier": "982"}],
        },
        "981": {  # badge: isTextBox + custom bezier path -> dual ["text", "shape"]
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "981-st"},
            "super": {
                "geometry": {"position": {"x": 409.6, "y": 0.0}, "size": {"width": 645.0, "height": 92.0}, "angle": 0.0},
                "pathsource": {"editableBezierPathSource": True},
            },
        },
        "981-st": storage("2 Kings 3", "500"),
        "982": {  # verse: autosize text-only child -> kind "text"
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "982-st"},
        },
        "982-st": storage("15 the verse body", "501"),
        "500": _charstyle("BadgeStyle", fontName="AzoSans-Bold", fontSize=65.0),
        "501": _charstyle("VerseStyle", fontName="AzoSans-Regular", fontSize=70.0),
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "160"}]},
        },
    }
    return objects, {}, {}


def test_attach_group_child_runs_exposes_dual_shape_text_badge_caption(monkeypatch):
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _dual_badge_deck())
    payload = {"slides": [{"index": 0, "items": []}]}
    attach_group_child_runs("ignored.key", payload)
    groups = payload["slides"][0]["groupChildRuns"]
    # The badge is child kindIndex 0 under `_group_child_records`' "shape" counter
    # (it is addressed as a shape); its caption must be keyed there, not under the
    # separate "text" counter (which would also read 0 and mask the bug).
    assert groups[0][0]["text"] == "2 Kings 3"
    assert groups[0][0]["font"] == "AzoSans-Bold"
    assert groups[0][0]["size"] == pytest.approx(65.0)
    assert groups[0][1]["text"] == "15 the verse body"


def test_attach_group_children_skips_a_slide_marked_group_children_unavailable(monkeypatch):
    """A slide merged in from a scoped JXA-fallback read (remap_keynote._merge_legacy_slides)
    carries live union group frames, not archive offsets — attach_group_children must not
    attach them a groupChildren record despite qualifying otherwise."""
    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _badge_deck())
    payload = {
        "slides": [
            {"index": 0, "items": [], "groupChildrenUnavailable": True},
            {"index": 1, "items": []},
        ]
    }
    attach_group_children("ignored.key", payload)
    assert "groupChildren" not in payload["slides"][0]
    assert "groupChildren" not in payload["slides"][1]


# --------------------------------------------------------------------------
# attach_group_autosize — archive-fact marker, valid under any reader. Must mark
# a group even when _group_child_records itself refuses it (nested group, etc):
# those are exactly the cases that collapse without the fix.
# --------------------------------------------------------------------------
def test_attach_group_autosize_marks_the_badge_group_and_leaves_the_plain_one_unmarked(
    monkeypatch,
):
    from obed_edom.iwa_runs import attach_group_autosize

    monkeypatch.setattr(iwa, "_load_deck", lambda _p: _badge_deck())
    payload = {"slides": [{"index": 0, "items": []}, {"index": 1, "items": []}]}
    attach_group_autosize("ignored.key", payload)
    assert payload["slides"][0]["groupAutosize"] == {0: True}
    assert "groupAutosize" not in payload["slides"][1]


def test_attach_group_autosize_marks_a_group_group_child_records_itself_refuses(
    monkeypatch,
):
    """A nested group with an autosize grandchild is refused by _group_child_records
    (same aspect-lock problem one level down) but must still collapse-refuse at
    write time, so attach_group_autosize marks it independently of that refusal."""
    from obed_edom.iwa_runs import attach_group_autosize

    def storage(text):
        return {"_pbtype": "TSWP.StorageArchive", "text": [text]}

    objects = {
        "130": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "230"}},
        "230": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "910"}]},
        "910": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "911"}, {"identifier": "912"}],
        },
        "911": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 50.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "913"}],
        },
        "912": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 50.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "913": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "913-st"},
            "super": {
                "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 40.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 40.0, "height": 30.0}}},
            },
        },
        "913-st": storage("Nested"),
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "130"}]}},
    }
    from obed_edom.iwa_runs import _group_child_records

    assert _group_child_records(objects["910"], objects) is None

    monkeypatch.setattr(iwa, "_load_deck", lambda _p: (objects, {}, {}))
    payload = {"slides": [{"index": 0, "items": []}]}
    attach_group_autosize("ignored.key", payload)
    assert payload["slides"][0]["groupAutosize"] == {0: True}


# --------------------------------------------------------------------------
# _load_deck(skipped=...) — opt-in reporting of undecodable members (fix4).
# --------------------------------------------------------------------------
def test_load_deck_skipped_reports_a_corrupt_member_and_still_loads_the_rest():
    pytest.importorskip("keynote_parser")
    import io
    import zipfile

    from tests.test_iwa_write import _arch, _member

    from obed_edom.iwa_runs import _load_deck

    good = _member([_arch(1, "KN.SlideArchive", {"drawablesZOrder": []})])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Good.iwa", good)
        z.writestr("Index/Bad.iwa", b"not a valid iwa chunk")
    path = io.BytesIO(buf.getvalue())

    skipped: list[tuple[str, str]] = []
    objects, _id_to_file, _file_ids = _load_deck(path, skipped=skipped)
    assert objects["1"]["_pbtype"] == "KN.SlideArchive"
    assert len(skipped) == 1
    assert skipped[0][0] == "Index/Bad.iwa"

    path.seek(0)
    objects_default, _id_to_file, _file_ids = _load_deck(path)
    assert objects_default == objects


# --------------------------------------------------------------------------
# _group_child_records inherits the six-kind _natural_size fix (fix1/fix3).
# --------------------------------------------------------------------------
def test_group_child_records_reads_non_bezier_natural_size():
    """A scalar-path autosize child (e.g. a rounded-rect text box) must not be silently
    read as (0, 0) naturalSize by the old one-hop bezier-only reader."""
    objects = {
        "990": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "991"}, {"identifier": "992"}],
        },
        "991": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "992": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "992-st"},
            "super": {
                "geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 120.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"scalarPathSource": {"naturalSize": {"width": 120.0, "height": 32.0}}},
            },
        },
    }
    records = _group_child_records(objects["990"], objects)
    assert records is not None
    _plate, text = records
    assert text["autosize"] is True
    assert text["w"] == pytest.approx(120.0)
    assert text["h"] == pytest.approx(32.0)


# --------------------------------------------------------------------------
# attach_magic_move — per-slide `magicMoveOut` + `mmKeys` content identity
# (mm_offcanvas_partners.plan.md §Partner rule / §Stream A). Synthetic archives
# only; deck_builds needs a real zip for its data index, so an empty one is used.
# --------------------------------------------------------------------------
_MM_EFFECT = "apple:magic-move-implied-motion-path"
_BY_OBJECT = "TransitionCustomAttributesTextDeliveryTypeByObject"
_BY_WORD = "TransitionCustomAttributesTextDeliveryTypeByWord"


def _transition(effect, delivery=None):
    attrs = {"animationAttributes": {"animationType": "Transition", "effect": effect}}
    if delivery is not None:
        attrs["customTextDeliveryType"] = delivery
    return {"attributes": attrs}


def _triangle(scale):
    points = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
    elements = [{"type": "moveTo", "points": [{"x": points[0][0] * scale, "y": points[0][1] * scale}]}]
    elements += [{"type": "lineTo", "points": [{"x": x * scale, "y": y * scale}]} for x, y in points[1:]]
    elements.append({"type": "closePath"})
    return {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "super": {"pathsource": {"bezierPathSource": {
            "naturalSize": {"width": 10.0 * scale, "height": 8.0 * scale},
            "path": {"elements": elements},
        }}},
    }


def _rounded_rect(width, height, radius):
    return {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "super": {"pathsource": {"scalarPathSource": {
            "type": 0, "scalar": radius, "naturalSize": {"width": width, "height": height},
        }}},
    }


def _mm_deck(slides, extra, datas=()):
    """``slides``: [(transition, [drawable ids])]; ``extra``: drawable/storage objects.
    ``datas``: PackageMetadata ``datas`` records."""
    objects = dict(extra)
    tree = []
    for i, (transition, drawables) in enumerate(slides):
        node, sid = f"node{i}", f"slide{i}"
        tree.append({"identifier": node})
        objects[node] = {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": sid}}
        objects[sid] = {
            "_pbtype": "KN.SlideArchive",
            "drawablesZOrder": [{"identifier": d} for d in drawables],
        }
        if transition is not None:
            objects[sid]["transition"] = transition
    objects["show"] = {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": tree}}
    objects["meta"] = {"_pbtype": "TSP.PackageMetadata", "datas": list(datas)}
    return objects, {}, {}


def _empty_key(tmp_path):
    import zipfile  # noqa: PLC0415

    path = tmp_path / "mm.key"
    with zipfile.ZipFile(path, "w"):
        pass
    return path


def _text_box(storage_id):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": storage_id}}


def _storage(text):
    return {"_pbtype": "TSWP.StorageArchive", "text": [text]}


def _attach(tmp_path, deck, indices):
    payload = {"slides": [{"index": i, "items": []} for i in indices]}
    iwa.attach_magic_move(_empty_key(tmp_path), payload, deck=deck)
    return payload["slides"]


def test_attach_magic_move_gates_on_effect_and_by_object_delivery(tmp_path):
    # Slide 0: dissolve (no pair). Slide 1: MM, no delivery field (default). Slide 2:
    # MM by object. Slide 3: MM by word -- partial-string pairing, not modelled, so not
    # a pair. Slide 4: last slide, no transition.
    extra = {f"t{i}": _text_box(f"s{i}") for i in range(5)} | {f"s{i}": _storage(f"Title {i}") for i in range(5)}
    deck = _mm_deck(
        [
            (_transition("apple:dissolve"), ["t0"]),
            (_transition(_MM_EFFECT), ["t1"]),
            (_transition(_MM_EFFECT, _BY_OBJECT), ["t2"]),
            (_transition(_MM_EFFECT, _BY_WORD), ["t3"]),
            (None, ["t4"]),
        ],
        extra,
    )
    slides = _attach(tmp_path, deck, range(5))
    assert [s.get("magicMoveOut") for s in slides] == [None, True, True, None, None]
    # Pairs are (1,2) and (2,3): keys on 1, 2, 3 only. Slide 0 (dissolve out, no MM in)
    # and slide 4 (after the by-word transition) are in no pair.
    assert ["mmKeys" in s for s in slides] == [False, True, True, True, False]
    assert slides[1]["mmKeys"] == {"text": {0: "text:Title 1"}}


def test_attach_magic_move_reads_database_effect_fallback(tmp_path):
    transition = {"attributes": {"databaseEffect": _MM_EFFECT}}
    extra = {"t0": _text_box("s0"), "s0": _storage("A")}
    deck = _mm_deck([(transition, ["t0"]), (None, [])], extra)
    slides = _attach(tmp_path, deck, range(2))
    assert slides[0]["magicMoveOut"] is True


def test_attach_magic_move_direction_is_out_of_the_slide(tmp_path):
    # MM on slide 1 pairs 1<->2, never 0<->1.
    extra = {f"t{i}": _text_box(f"s{i}") for i in range(3)} | {f"s{i}": _storage("Same") for i in range(3)}
    deck = _mm_deck([(None, ["t0"]), (_transition(_MM_EFFECT), ["t1"]), (None, ["t2"])], extra)
    slides = _attach(tmp_path, deck, range(3))
    assert "magicMoveOut" not in slides[0] and "mmKeys" not in slides[0]
    assert slides[1]["magicMoveOut"] is True
    assert "magicMoveOut" not in slides[2]
    assert slides[1]["mmKeys"] == slides[2]["mmKeys"] == {"text": {0: "text:Same"}}


def test_attach_magic_move_keys_by_true_slide_index_on_a_sliced_payload(tmp_path):
    extra = {f"t{i}": _text_box(f"s{i}") for i in range(3)} | {f"s{i}": _storage(f"T{i}") for i in range(3)}
    deck = _mm_deck([(None, ["t0"]), (_transition(_MM_EFFECT), ["t1"]), (None, ["t2"])], extra)
    slides = _attach(tmp_path, deck, [2, 9])
    assert slides[0]["mmKeys"] == {"text": {0: "text:T2"}}
    assert "magicMoveOut" not in slides[0]
    assert slides[1] == {"index": 9, "items": []}


def test_attach_magic_move_media_keys_by_digest_not_file_name(tmp_path):
    # Images 0/1: two data ids sharing one digest (a re-imported copy) -> one key.
    # Images 2/3: both `pasted-image.pdf` but different digests -> different keys
    # (FRC has dozens of distinct pasted-image.pdf). Image 4: data id missing from
    # PackageMetadata -> falls back to the data id. Movie: digest, `movie:` prefix.
    extra = {
        "i0": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d0"}},
        "i1": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d1"}},
        "i2": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d2"}},
        "i3": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d3"}},
        "i4": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d4"}},
        "i5": {"_pbtype": "TSD.ImageArchive"},
        "m0": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "d5"}},
    }
    datas = [
        {"identifier": "d0", "digest": "SAME=", "fileName": "a-d0.png"},
        {"identifier": "d1", "digest": "SAME=", "fileName": "b-d1.png"},
        {"identifier": "d2", "digest": "ONE=", "fileName": "pasted-image.pdf"},
        {"identifier": "d3", "digest": "TWO=", "fileName": "pasted-image.pdf"},
        {"identifier": "d5", "digest": "MOV=", "fileName": "clip.mov"},
    ]
    deck = _mm_deck([(_transition(_MM_EFFECT), ["i0", "i1", "i2", "i3", "i4", "i5", "m0"]), (None, [])], extra, datas)
    keys = _attach(tmp_path, deck, range(2))[0]["mmKeys"]
    images = keys["image"]
    assert images[0] == images[1] == "image:SAME="
    assert images[2] == "image:ONE=" and images[3] == "image:TWO="
    assert images[4] == "image:id:d4"
    assert 5 not in images  # no data reference: unresolvable, no key, never matches
    assert keys["movie"] == {0: "movie:MOV="}


def test_attach_magic_move_shape_key_is_size_invariant_and_ignores_the_rounded_rect_radius(tmp_path):
    # Shape 0/1: the same triangle at 1x and 2.5x -> one key (a resized copy on the
    # neighbouring slide still pairs). Shape 2/3/4: rounded rects of different size and
    # radius 10 vs 60 -> one key (live 2026-09-24: Keynote morphs radius 10 -> 60; the
    # preset compares by type only). Shape 5: no path source -> no key.
    extra = {
        "p0": _triangle(1.0),
        "p1": _triangle(2.5),
        "r0": _rounded_rect(100.0, 40.0, 10.0),
        "r1": _rounded_rect(300.0, 60.0, 10.0),
        "r2": _rounded_rect(100.0, 40.0, 60.0),
        "bare": {"_pbtype": "TSWP.ShapeInfoArchive"},
    }
    deck = _mm_deck([(_transition(_MM_EFFECT), ["p0", "p1", "r0", "r1", "r2", "bare"]), (None, [])], extra)
    shapes = _attach(tmp_path, deck, range(2))[0]["mmKeys"]["shape"]
    assert shapes[0] == shapes[1]
    assert shapes[0].startswith("shape:bezierPathSource::")
    assert shapes[2] == shapes[3] == shapes[4]
    assert shapes[2].startswith("shape:scalarPathSource:0:")
    assert shapes[0] != shapes[2]
    assert 5 not in shapes


def test_attach_magic_move_shape_key_keeps_the_scalar_of_other_presets(tmp_path):
    # Only the rounded rect's scalar (its radius) is ignored. Other scalarPathSource
    # presets are unmeasured and their scalar changes the outline (polygon sides, star
    # points), so it stays in the key. Named and numeric enum spellings both count as
    # the rounded rect.
    extra = {
        "poly5": {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"scalarPathSource": {
            "type": "kTSDRegularPolygon", "scalar": 5.0, "naturalSize": {"width": 100.0, "height": 100.0}}}}},
        "poly6": {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"scalarPathSource": {
            "type": "kTSDRegularPolygon", "scalar": 6.0, "naturalSize": {"width": 100.0, "height": 100.0}}}}},
        "rrNamed": {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"scalarPathSource": {
            "type": "kTSDRoundedRectangle", "scalar": 10.0, "naturalSize": {"width": 100.0, "height": 100.0}}}}},
        "rrNamed60": {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"scalarPathSource": {
            "type": "kTSDRoundedRectangle", "scalar": 60.0, "naturalSize": {"width": 300.0, "height": 90.0}}}}},
    }
    deck = _mm_deck([(_transition(_MM_EFFECT), ["poly5", "poly6", "rrNamed", "rrNamed60"]), (None, [])], extra)
    shapes = _attach(tmp_path, deck, range(2))[0]["mmKeys"]["shape"]
    assert shapes[0] != shapes[1]
    assert shapes[0].startswith("shape:scalarPathSource:kTSDRegularPolygon:")
    assert shapes[2] == shapes[3]


def _path_shape(points, width, height):
    elements = [{"type": "moveTo", "points": [{"x": points[0][0], "y": points[0][1]}]}]
    elements += [{"type": "lineTo", "points": [{"x": x, "y": y}]} for x, y in points[1:]]
    return {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "super": {"pathsource": {"bezierPathSource": {
            "naturalSize": {"width": width, "height": height}, "path": {"elements": elements},
        }}},
    }


def test_attach_magic_move_shape_key_resolution_tolerates_save_noise_but_splits_distinct_paths(tmp_path):
    # The key rounds bbox-normalised coordinates to 1e-3. Measured on FRC
    # (2026-09-24): every collision at that resolution is Keynote save noise between
    # identical shapes (at most 2.2e-7 normalised); 1e-6 already splits the 17x17 pin-dot
    # class (1.1e-7 apart), and exact ratios split two more. A split re-creates the broken
    # move, a collision only keeps one more object parked off the canvas, so the
    # resolution stays coarse.
    # s0/s1: one 1000pt path, s1 carrying 2e-7 relative noise -> one key.
    # s2: the same path with its apex 5pt (5e-3 normalised) over on a 1000pt wide
    # path -> a different key (near-but-distinct null control).
    base = [(0.0, 0.0), (1000.0, 0.0), (500.0, 800.0)]
    noisy = [(x * (1 + 2e-7), y * (1 + 2e-7)) for x, y in base]
    moved = [(0.0, 0.0), (1000.0, 0.0), (505.0, 800.0)]
    extra = {
        "s0": _path_shape(base, 1000.0, 800.0),
        "s1": _path_shape(noisy, 1000.0, 800.0),
        "s2": _path_shape(moved, 1000.0, 800.0),
    }
    deck = _mm_deck([(_transition(_MM_EFFECT), ["s0", "s1", "s2"]), (None, [])], extra)
    shapes = _attach(tmp_path, deck, range(2))[0]["mmKeys"]["shape"]
    assert shapes[0] == shapes[1]
    assert shapes[2] != shapes[0]


def test_attach_magic_move_empty_text_gets_no_key_and_dual_shape_is_skipped(tmp_path):
    # t0: whitespace/object-replacement-only text -> no key. t1: a custom-path text box
    # (dual: text 1 AND shape 0) -> keyed once, on its text record; the dual shape record
    # carries no key. l0: an open two-point path is a line -> a `line:` key (path gate +
    # stroke/line-end digest; the style-less line has no stroke).
    extra = {
        "t0": _text_box("s0"),
        "s0": _storage(" \n￼\xa0"),
        "t1": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "s1"},
            "super": {"pathsource": {"editableBezierPathSource": {"naturalSize": {"width": 5.0, "height": 5.0}}}},
        },
        "s1": _storage("Pill  caption"),
        "l0": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"pathsource": {"bezierPathSource": {
                "naturalSize": {"width": 100.0, "height": 0.0},
                "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}]},
            }}},
        },
    }
    deck = _mm_deck([(_transition(_MM_EFFECT), ["t0", "t1", "l0"]), (None, [])], extra)
    keys = _attach(tmp_path, deck, range(2))[0]["mmKeys"]
    assert keys["text"] == {1: "text:Pill caption"}
    assert "shape" not in keys
    assert keys["line"][0].startswith("line:bezierPathSource::")


_WHITE = {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"}
_YELLOW = {"model": "rgb", "r": 1.0, "g": 0.9, "b": 0.0, "a": 1.0, "rgbspace": "srgb"}
_RED = {"model": "rgb", "r": 0.93, "g": 0.13, "b": 0.05, "a": 1.0, "rgbspace": "srgb"}
_ARROW = {"identifier": "simple arrow", "isFilled": True, "endPoint": {"x": 3.0, "y": 0.0}}


def _stroke(color=_WHITE, width=4.0, pattern="TSDSolidPattern"):
    return {"color": color, "width": width, "cap": "ButtCap", "join": "MiterJoin", "miterLimit": 4.0,
            "pattern": {"type": pattern, "phase": 0.0, "count": 0, "pattern": [0.0] * 6}}


def _shape_style(parent=None, **props):
    """A TSWP.ShapeStyleArchive as keynote_parser decodes it: TSD shape properties at
    ``super.shapeProperties``, the parent at ``super.super.parent``; the outer
    ``shapeProperties`` holds TSWP-only fields (padding etc.)."""
    inner = {"stylesheet": {"identifier": "sheet"}}
    if parent is not None:
        inner["parent"] = {"identifier": parent}
    return {"_pbtype": "TSWP.ShapeStyleArchive",
            "super": {"super": inner, "shapeProperties": dict(props)},
            "shapeProperties": {"padding": {"left": 4.0}}}


def _rect(points_w, points_h, natural=None, style=None, source="bezierPathSource"):
    """A bezier rect whose points span points_w x points_h; ``natural`` defaults to the
    same size (a UI resize only rewrites naturalSize, leaving the points as drawn)."""
    nw, nh = natural or (points_w, points_h)
    corners = [(0.0, -2.2737368e-13), (points_w, -2.2737368e-13), (points_w, points_h), (0.0, points_h)]
    elements = [{"type": "moveTo", "points": [{"x": corners[0][0], "y": corners[0][1]}]}]
    elements += [{"type": "lineTo", "points": [{"x": x, "y": y}]} for x, y in corners[1:]]
    elements.append({"type": "closeSubpath"})
    obj = {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {source: {
        "naturalSize": {"width": nw, "height": nh}, "path": {"elements": elements},
    }}}}
    if style is not None:
        obj["super"]["style"] = {"identifier": style}
    return obj


def _editable_rect(size):
    nodes = [{"nodePoint": {"x": x, "y": y}, "inControlPoint": {"x": x, "y": y}, "outControlPoint": {"x": x, "y": y},
              "type": "sharp"} for x, y in [(0.0, 0.0), (size, 0.0), (size, size), (0.0, size)]]
    return {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"editableBezierPathSource": {
        "subpaths": [{"nodes": nodes, "closed": True}], "naturalSize": {"width": size, "height": size},
    }}}}


def _oval_ish(size):
    k = size * 0.5523
    h = size / 2
    elements = [
        {"type": "moveTo", "points": [{"x": h, "y": 0.0}]},
        {"type": "curveTo", "points": [{"x": h + k, "y": 0.0}, {"x": size, "y": h - k}, {"x": size, "y": h}]},
        {"type": "curveTo", "points": [{"x": size, "y": h + k}, {"x": h + k, "y": size}, {"x": h, "y": size}]},
        {"type": "curveTo", "points": [{"x": h - k, "y": size}, {"x": 0.0, "y": h + k}, {"x": 0.0, "y": h}]},
        {"type": "curveTo", "points": [{"x": 0.0, "y": h - k}, {"x": h - k, "y": 0.0}, {"x": h, "y": 0.0}]},
        {"type": "closeSubpath"},
    ]
    return {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"pathsource": {"bezierPathSource": {
        "naturalSize": {"width": size, "height": size}, "path": {"elements": elements},
    }}}}


def _line(length, style, natural=300.0):
    return {"_pbtype": "TSWP.ShapeInfoArchive", "super": {"style": {"identifier": style}, "pathsource": {
        "bezierPathSource": {"naturalSize": {"width": natural, "height": 0.0}, "path": {"elements": [
            {"type": "moveTo", "points": [{"x": 0.0, "y": 0.0}]},
            {"type": "lineTo", "points": [{"x": length, "y": 0.0}]},
        ]}},
    }}}


def _mm_slide0(tmp_path, extra, ids):
    deck = _mm_deck([(_transition(_MM_EFFECT), ids), (None, [])], extra)
    return _attach(tmp_path, deck, range(2))[0]


def test_attach_magic_move_shape_gate_ignores_natural_size_and_drawn_size(tmp_path):
    # Live 2026-09-24: Keynote keeps bezier points at the coordinates they were drawn at
    # and a UI resize only rewrites naturalSize. FX's squares store points 174x154 with a
    # naturalSize of 351x310; the unresized copy stores 174x154 / 174x154. Both pair, and
    # the naturalSize-normalised key split them. A rect drawn at 100 vs one drawn at 200
    # (R2 in G_raw) also pairs: equal gate key, but the raw stored path (tier2) differs,
    # which is what Keynote prefers among compatible candidates.
    extra = {
        "fx": _rect(174.0, 154.0, natural=(351.0, 310.0)),
        "fx0": _rect(174.0, 154.0),
        "r100": _rect(100.0, 100.0, natural=(200.0, 200.0)),
        "r200": _rect(200.0, 200.0),
    }
    slide = _mm_slide0(tmp_path, extra, ["fx", "fx0", "r100", "r200"])
    shapes, prefs = slide["mmKeys"]["shape"], slide["mmPrefs"]["shape"]
    assert shapes[0] == shapes[1]
    assert shapes[2] == shapes[3]
    assert shapes[0] == shapes[2]  # aspect is free too: every axis-aligned rect normalises alike
    assert prefs[0][1] == prefs[1][1]  # tier2 excludes naturalSize
    assert prefs[2][1] != prefs[3][1]
    assert prefs[2][0] == prefs[3][0]


def test_attach_magic_move_shape_gate_splits_path_classes_and_outlines(tmp_path):
    # Live never-pairs: rect -> oval, rect -> triangle, bezier rect -> editable path,
    # bezier rect -> preset rounded rect. All at one size, so only class/outline differs.
    extra = {
        "rect": _rect(200.0, 200.0),
        "oval": _oval_ish(200.0),
        "tri": _path_shape([(0.0, 200.0), (100.0, 0.0), (200.0, 200.0)], 200.0, 200.0),
        "ed": _editable_rect(200.0),
        "rr": _rounded_rect(200.0, 200.0, 10.0),
    }
    shapes = _mm_slide0(tmp_path, extra, ["rect", "oval", "tri", "ed", "rr"])["mmKeys"]["shape"]
    assert len(set(shapes.values())) == 5
    assert shapes[3].startswith("shape:editableBezierPathSource::")


def test_attach_magic_move_shape_gate_ignores_style_and_tier1_is_stroke_and_opacity(tmp_path):
    # Live: fill, stroke on/off/colour/width, opacity and a different style object never
    # block a pair; stroke and opacity outrank the raw path, fill/style object only the
    # distance. So every shape here shares one gate key; tier1 moves with stroke/opacity
    # only, tier3 is the shape's own style id.
    # base: red fill, empty-pattern stroke (= no stroke), opacity unset (= 1.0).
    # fill: a child style overriding only the fill -> tier1 equal, tier3 differs.
    # op1: an explicit opacity 1.0 -> tier1 equal to base.
    # op: opacity 0.5 via a child style (resolved through the parent chain).
    # stroked / wide: a solid stroke, then one 4 -> 12 wide.
    extra = {
        "sBase": _shape_style(fill={"color": _RED}, stroke=_stroke(pattern="TSDEmptyPattern")),
        "sFill": _shape_style(parent="sBase", fill={"color": _YELLOW}),
        "sOp1": _shape_style(parent="sBase", opacity=1.0),
        "sOp": _shape_style(parent="sBase", opacity=0.5),
        "sStroke": _shape_style(parent="sBase", stroke=_stroke()),
        "sWide": _shape_style(parent="sStroke", stroke=_stroke(width=12.0)),
        "base": _rect(200.0, 200.0, style="sBase"),
        "fill": _rect(200.0, 200.0, style="sFill"),
        "op1": _rect(200.0, 200.0, style="sOp1"),
        "op": _rect(200.0, 200.0, style="sOp"),
        "stroked": _rect(200.0, 200.0, style="sStroke"),
        "wide": _rect(200.0, 200.0, style="sWide"),
        "nostyle": _rect(200.0, 200.0),
    }
    slide = _mm_slide0(tmp_path, extra, ["base", "fill", "op1", "op", "stroked", "wide", "nostyle"])
    shapes, prefs = slide["mmKeys"]["shape"], slide["mmPrefs"]["shape"]
    assert len(set(shapes.values())) == 1
    tier1 = [prefs[i][0] for i in range(7)]
    assert tier1[0] == tier1[1] == tier1[2] == tier1[6]  # no stroke + opacity 1.0 either way
    assert len({tier1[0], tier1[3], tier1[4], tier1[5]}) == 4
    assert len({prefs[i][1] for i in range(7)}) == 1
    assert [prefs[i][2] for i in range(7)] == ["sBase", "sFill", "sOp1", "sOp", "sStroke", "sWide", ""]


def test_attach_magic_move_line_key_is_length_free_but_stroke_and_ends_sensitive(tmp_path):
    # Live: a line morphs across length (the drawn points and the naturalSize both
    # differ here), but never across arrowhead, width 4 -> 12 or colour white -> yellow.
    # The ancestor mirrors Keynote's line style: empty `{}` line ends mean none.
    extra = {
        "sRoot": _shape_style(stroke=_stroke(width=2.0), opacity=1.0, headLineEnd={}, tailLineEnd={}),
        "sLine": _shape_style(parent="sRoot", stroke=_stroke()),
        "sLine2": _shape_style(parent="sRoot", stroke=_stroke()),
        "sArrow": _shape_style(parent="sRoot", stroke=_stroke(), headLineEnd=_ARROW),
        "sWide": _shape_style(parent="sRoot", stroke=_stroke(width=12.0)),
        "sYellow": _shape_style(parent="sRoot", stroke=_stroke(color=_YELLOW)),
        "l0": _line(141.42136, "sLine"),
        "long": _line(400.0, "sLine2", natural=400.0),
        "arrow": _line(141.42136, "sArrow"),
        "wide": _line(141.42136, "sWide"),
        "yellow": _line(141.42136, "sYellow"),
    }
    slide = _mm_slide0(tmp_path, extra, ["l0", "long", "arrow", "wide", "yellow"])
    lines = slide["mmKeys"]["line"]
    assert "shape" not in slide["mmKeys"]
    assert lines[0] == lines[1]
    assert lines[0].startswith("line:bezierPathSource::")
    assert len({lines[0], lines[2], lines[3], lines[4]}) == 4
    assert slide["mmPrefs"]["line"][0][2] == "sLine"
    assert slide["mmPrefs"]["line"][0][1] != slide["mmPrefs"]["line"][1][1]


def test_attach_magic_move_prefs_cover_keyed_shapes_and_lines_only(tmp_path):
    # mmPrefs lists exactly the shape/line addresses that got an mmKeys entry: not text,
    # media, groups, a dual text-shape's duplicate record, or an unkeyed bare shape. A
    # slide with no keyed shape or line carries no mmPrefs. Every tier is a string.
    extra = {
        "t0": _text_box("s0"), "s0": _storage("Caption"),
        "dual": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "s1"},
            "super": {"pathsource": {"editableBezierPathSource": {"naturalSize": {"width": 5.0, "height": 5.0}}}},
        },
        "s1": _storage("Pill"),
        "bare": {"_pbtype": "TSWP.ShapeInfoArchive"},
        "p0": _triangle(1.0),
        "i0": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "di"}},
        "g0": _mm_group(["gp"]), "gp": _triangle(2.0),
        "sL": _shape_style(stroke=_stroke()),
        "l0": _line(100.0, "sL"),
    }
    deck = _mm_deck(
        [(_transition(_MM_EFFECT), ["t0", "dual", "bare", "p0", "i0", "g0", "l0"]), (None, ["t0", "i0"])],
        extra,
        [{"identifier": "di", "digest": "IMG="}],
    )
    slides = _attach(tmp_path, deck, range(2))
    keys, prefs = slides[0]["mmKeys"], slides[0]["mmPrefs"]
    assert set(prefs) == {"shape", "line"}
    assert set(prefs["shape"]) == set(keys["shape"]) == {2}
    assert set(prefs["line"]) == set(keys["line"]) == {0}
    for tiers in (prefs["shape"][2], prefs["line"][0]):
        assert len(tiers) == 3 and all(isinstance(t, str) for t in tiers)
        assert len(tiers[0]) == len(tiers[1]) == 12
    assert prefs["shape"][2][2] == "" and prefs["line"][0][2] == "sL"
    assert "mmKeys" in slides[1] and "mmPrefs" not in slides[1]


def _mm_group(child_ids):
    return {"_pbtype": "TSD.GroupArchive", "children": [{"identifier": c} for c in child_ids]}


def test_attach_magic_move_group_key_is_dfs_leaves_by_digest_and_normalised_shape(tmp_path):
    # g0 / g1: identical text + a pasted-image.pdf leaf, but the PDFs' digests differ
    # -> different keys (fileName-keyed leaves would collide). g2: g0's content with its
    # triangle leaf resized and the image inside a nested group -> same key as g0 (DFS
    # order, shape leaves size-invariant). g3: an unrepresentable child -> no key.
    extra = {
        "g0": _mm_group(["g0t", "g0i", "g0p"]),
        "g0t": _text_box("g0s"), "g0s": _storage("UPG"),
        "g0i": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "dA"}},
        "g0p": _triangle(1.0),
        "g1": _mm_group(["g1t", "g1i", "g1p"]),
        "g1t": _text_box("g1s"), "g1s": _storage("UPG"),
        "g1i": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "dB"}},
        "g1p": _triangle(1.0),
        "g2": _mm_group(["g2t", "g2n", "g2p"]),
        "g2t": _text_box("g2s"), "g2s": _storage(" UPG "),
        "g2n": _mm_group(["g2i"]),
        "g2i": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "dC"}},
        "g2p": _triangle(3.0),
        "g3": _mm_group(["g3t", "g3x"]),
        "g3t": _text_box("g3s"), "g3s": _storage("UPG"),
        "g3x": {"_pbtype": "TSD.SomeOtherArchive"},
    }
    datas = [
        {"identifier": "dA", "digest": "PDF1=", "fileName": "pasted-image.pdf"},
        {"identifier": "dB", "digest": "PDF2=", "fileName": "pasted-image.pdf"},
        {"identifier": "dC", "digest": "PDF1=", "fileName": "pasted-image-dC.pdf"},
    ]
    deck = _mm_deck([(_transition(_MM_EFFECT), ["g0", "g1", "g2", "g3"]), (None, [])], extra, datas)
    groups = _attach(tmp_path, deck, range(2))[0]["mmKeys"]["group"]
    assert groups[0] != groups[1]
    assert groups[0] == groups[2]
    assert groups[0].startswith("group:text:UPG\nimage:PDF1=\nshape:bezierPathSource::")
    assert 3 not in groups


def test_attach_magic_move_keys_survive_a_json_round_trip(tmp_path):
    import json  # noqa: PLC0415

    extra = {"t0": _text_box("s0"), "s0": _storage("A"), "p0": _triangle(1.0), "sL": _shape_style(stroke=_stroke()),
             "l0": _line(100.0, "sL")}
    deck = _mm_deck([(_transition(_MM_EFFECT), ["t0", "p0", "l0"]), (None, ["t0"])], extra)
    slides = _attach(tmp_path, deck, range(2))
    loaded = json.loads(json.dumps(slides))
    assert "mmPrefs" in slides[0] and "mmPrefs" not in slides[1]
    for before, after in zip(slides, loaded):
        assert after.get("magicMoveOut") == before.get("magicMoveOut")
        restored = {kind: {int(ki): key for ki, key in by_index.items()} for kind, by_index in after["mmKeys"].items()}
        assert restored == before["mmKeys"]
        prefs = {kind: {int(ki): tiers for ki, tiers in by_index.items()}
                 for kind, by_index in (after.get("mmPrefs") or {}).items()}
        assert prefs == before.get("mmPrefs", {})
        assert after["mmOrder"] == before["mmOrder"]
        assert all(isinstance(kind, str) and isinstance(ki, int) for kind, ki in after["mmOrder"])
        assert all(isinstance(ki, int) for by_index in before["mmKeys"].values() for ki in by_index)


def test_attach_magic_move_replaces_stale_fields_from_a_prior_annotation(tmp_path):
    # A payload annotated before (e.g. a reused dict) carries fields for slides the
    # current deck no longer pairs: they are cleared, and current pairs are rewritten.
    extra = {f"t{i}": _text_box(f"s{i}") for i in range(3)} | {f"s{i}": _storage(f"T{i}") for i in range(3)}
    deck = _mm_deck([(_transition(_MM_EFFECT), ["t0"]), (None, ["t1"]), (None, ["t2"])], extra)
    payload = {"slides": [
        {"index": 0, "items": [], "mmKeys": {"text": {0: "text:stale"}}, "mmOrder": [["text", 5]],
         "mmPrefs": {"shape": {3: ["a", "b", "c"]}}},
        {"index": 1, "items": [], "magicMoveOut": True},
        {"index": 2, "items": [], "magicMoveOut": True, "mmKeys": {"text": {0: "text:T2"}}, "mmOrder": [["text", 0]],
         "mmPrefs": {"line": {0: ["a", "b", ""]}}},
    ]}
    iwa.attach_magic_move(_empty_key(tmp_path), payload, deck=deck)
    assert payload["slides"] == [
        {"index": 0, "items": [], "magicMoveOut": True, "mmKeys": {"text": {0: "text:T0"}}, "mmOrder": [["text", 0]]},
        {"index": 1, "items": [], "mmKeys": {"text": {0: "text:T1"}}, "mmOrder": [["text", 0]]},
        {"index": 2, "items": []},
    ]


def test_attach_magic_move_order_is_back_to_front_across_kinds(tmp_path):
    # mmKeys buckets by kind (text before shape before movie), so it cannot say which
    # object sits on top. mmOrder lists [kind, kindIndex] addresses in drawablesZOrder
    # order: here a movie at the back, a triangle, a text box, then an image in front.
    # Unkeyed drawables (the bare shape = shape 1, the empty text box = text 1) take no
    # slot. Slide 2 is outside every pair: no mmOrder.
    extra = {
        "m0": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dm"}},
        "p0": _triangle(1.0),
        "bare": {"_pbtype": "TSWP.ShapeInfoArchive"},
        "t0": _text_box("s0"), "s0": _storage("Caption"),
        "te": _text_box("se"), "se": _storage("  "),
        "i0": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "di"}},
    }
    datas = [{"identifier": "dm", "digest": "MOV="}, {"identifier": "di", "digest": "IMG="}]
    deck = _mm_deck(
        [(_transition(_MM_EFFECT), ["m0", "p0", "bare", "t0", "te", "i0"]), (None, ["i0", "m0"]), (None, ["t0"])],
        extra,
        datas,
    )
    slides = _attach(tmp_path, deck, range(3))
    assert slides[0]["mmOrder"] == [["movie", 0], ["shape", 0], ["text", 0], ["image", 0]]
    assert slides[1]["mmOrder"] == [["image", 0], ["movie", 0]]
    assert "mmOrder" not in slides[2] and "mmKeys" not in slides[2]


def test_attach_magic_move_order_lists_a_dual_text_shape_once(tmp_path):
    # A custom-path text box is two records (text + duplicate shape) but one drawable:
    # one mmOrder entry, its text address.
    extra = {
        "t1": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "s1"},
            "super": {"pathsource": {"editableBezierPathSource": {"naturalSize": {"width": 5.0, "height": 5.0}}}},
        },
        "s1": _storage("Pill"),
        "p0": _triangle(1.0),
    }
    deck = _mm_deck([(_transition(_MM_EFFECT), ["p0", "t1"]), (None, [])], extra)
    slide = _attach(tmp_path, deck, range(2))[0]
    assert slide["mmOrder"] == [["shape", 0], ["text", 0]]
    assert "text:Pill" == slide["mmKeys"]["text"][0] and 1 not in slide["mmKeys"]["shape"]


def test_attach_magic_move_order_tells_duplicate_media_apart(tmp_path):
    # Two movies sharing one digest share one key; their addresses still differ, so the
    # detector can pair each copy by position.
    extra = {
        "m0": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "d0"}},
        "m1": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "d1"}},
    }
    datas = [{"identifier": "d0", "digest": "SAME="}, {"identifier": "d1", "digest": "SAME="}]
    deck = _mm_deck([(_transition(_MM_EFFECT), ["m1", "m0"]), (None, [])], extra, datas)
    slide = _attach(tmp_path, deck, range(2))[0]
    assert slide["mmKeys"] == {"movie": {0: "movie:SAME=", 1: "movie:SAME="}}
    assert slide["mmOrder"] == [["movie", 0], ["movie", 1]]


def test_attach_magic_move_failure_after_a_keyed_pair_leaves_no_annotation(tmp_path, monkeypatch):
    # Pairs (0,1) and (2,3). Keying fails on slide 2's record, after slide 0 and 1 were
    # fully keyed: no slide may keep a partial annotation (it could still convert hides),
    # and a stale field from a prior annotation is cleared too.
    extra = {f"t{i}": _text_box(f"s{i}") for i in range(4)} | {f"s{i}": _storage(f"T{i}") for i in range(4)}
    deck = _mm_deck(
        [(_transition(_MM_EFFECT), ["t0"]), (None, ["t1"]), (_transition(_MM_EFFECT), ["t2"]), (None, ["t3"])],
        extra,
    )
    real_identity = iwa._mm_identity
    keyed: list[str] = []

    def failing_identity(rec, objects, digests):
        if rec.get("text") == "T2":
            raise RuntimeError("unreadable archive")
        key = real_identity(rec, objects, digests)
        keyed.append(key)
        return key

    monkeypatch.setattr(iwa, "_mm_identity", failing_identity)
    payload = {"slides": [{"index": i, "items": []} for i in range(4)]}
    payload["slides"][3]["mmKeys"] = {"text": {0: "text:stale"}}
    payload["slides"][3]["mmPrefs"] = {"shape": {0: ["a", "b", "c"]}}
    with pytest.raises(RuntimeError, match="unreadable archive"):
        iwa.attach_magic_move(_empty_key(tmp_path), payload, deck=deck)
    assert keyed == ["text:T0", "text:T1"]
    assert payload["slides"] == [{"index": i, "items": []} for i in range(4)]


def test_attach_magic_move_real_decks_report_the_census_transitions():
    pytest.importorskip("keynote_parser")
    wall_dir = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
    expected = {
        "Full_Report_Card_Wall.key": [7, 8, 16, 19, 35, 56, 70, 84, 85, 102, 108, 109, 112, 117, 123, 126, 130, 146,
                                      150, 151, 152],
        "Gold_Wall_Input.key": [11, 19, 22],
    }
    for name, out_numbers in expected.items():
        path = wall_dir / name
        if not path.exists():
            pytest.skip(f"local deck missing: {path}")
        deck = iwa._load_deck(path)
        payload = {"slides": [{"index": i, "items": []} for i in range(len(iwa.slide_order(deck[0])))]}
        iwa.attach_magic_move(path, payload, deck=deck)
        assert [s["index"] + 1 for s in payload["slides"] if s.get("magicMoveOut")] == out_numbers
        paired = {n - 1 for n in out_numbers} | {n for n in out_numbers}
        assert {s["index"] for s in payload["slides"] if s.get("mmKeys")} == paired
