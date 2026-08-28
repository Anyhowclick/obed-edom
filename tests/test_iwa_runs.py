"""Tests for offline IWA per-run style extraction (obed_edom.iwa_runs).

The matcher and style resolver are exercised WITHOUT keynote-parser: only
``_load_deck`` (the sole importer of the optional extra) touches it, so every
test here builds a synthetic IWA object graph or calls the pure helpers directly.
A single local-only integration test runs against a real deck when both the deck
and the parser are available.
"""

import copy
from pathlib import Path

import pytest

import obed_edom.iwa_runs as iwa
from obed_edom.iwa_runs import (
    _match_runs_to_items,
    _normalize_text,
    _slide_grouped_text,
    attach_runs,
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
        "210": {"_pbtype": "KN.SlideArchive"},
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

    # groupedText got attached...
    grouped_texts = [g["text"] for g in payload["slides"][0]["groupedText"]]
    assert sorted(grouped_texts) == ["CHC Churches", "Countries"]
    # ...but items (incl. every group's children/childCount/geometry) are UNCHANGED.
    assert payload["slides"][0]["items"] == items_before
    for item in payload["slides"][0]["items"]:
        assert item["children"] == [] and item["childCount"] == 0
    # ...and the reuse fingerprint is byte-identical (groupedText not in the digest).
    assert deck_slide_digests(payload) == digests_before


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
