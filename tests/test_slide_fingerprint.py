"""Tests for the INERT save-churn-immune content key (obed_edom.slide_fingerprint).

The whole scheme is exercised WITHOUT keynote-parser: every unit test builds a
synthetic ``objects``/``id_to_file``/``file_ids`` graph (mirroring
``tests/test_iwa_runs.py``) and calls the pure helpers or :func:`_fingerprint`
(which takes an injected ``data_map``/``font_env``/``os_build`` so no zip, fonts or
Keynote are touched). One gated test runs the full :func:`fingerprint_deck` against a
real local deck when it and the parser are present.

Byte hashes churn on a no-op save (id renumber). The key hashes the decoded
id-normalized graph. Numeric {identifier: N} refs become positional @ref tokens;
string identifiers are style names and stay as content. Assets fold in as
@data CRC:size from the zip central directory (no media bytes read).

TSS.StylesheetArchive is a hard closure boundary: Keynote recompacts it every
save (canCullStyles). Folding it churned 42/42 DSK keys; skipping it loses no
style coverage because applied styles are reached by id. Over-inclusion costs a
cache miss, never a stale serve.

Global key: non-slide Index/*.iwa minus DocumentStylesheet / Metadata /
ViewState* / CalculationEngine / DocumentMetadata / AnnotationAuthorStorage.
Font env + OS build are folded in; Keynote version is not (it already rides
baseline._app_tag).
"""
from __future__ import annotations

import copy
import random
from pathlib import Path

import pytest

from obed_edom.slide_fingerprint import (
    _CLOSURE_BOUNDARY,
    _canon,
    _fingerprint,
    _global_key,
    _slide_key,
    fingerprint_deck,
)

DSK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key")

_FONT = "font-env-fixed"
_OS = "os-build-fixed"
_HEX64 = 64


def _is_hex64(value) -> bool:
    return isinstance(value, str) and len(value) == _HEX64 and all(c in "0123456789abcdef" for c in value)


# --------------------------------------------------------------------------
# Canonical encoder.
# --------------------------------------------------------------------------
def test_canon_is_deterministic_and_key_order_independent():
    a = {"b": 1, "a": [2, 3], "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": [2, 3], "b": 1}
    assert _canon(a) == _canon(b)


def test_canon_token_type_spaces_are_disjoint():
    # A positional {"@ref": 0} token can never collide with a genuine "@ref" string
    # value, nor with a data/boundary token, nor an int-vs-string id.
    assert _canon({"@ref": 0}) != _canon("@ref")
    assert _canon({"@ref": 0}) != _canon({"@ref": "0"})
    assert _canon({"@ref": 0}) != _canon({"@data": "0"})
    assert _canon({"@ref": 0}) != _canon({"@boundary": 0})
    assert _canon(1) != _canon("1")


def test_canon_quantizes_float_noise():
    # Sub-ppm noise below 6dp collapses to one encoding; a real change does not.
    assert _canon(1.0000001) == _canon(1.0)
    assert _canon(0.1234567) == _canon(0.1234571)
    assert _canon(0.123457) != _canon(0.123458)
    # signed zero folds
    assert _canon(-0.0) == _canon(0.0)


# --------------------------------------------------------------------------
# Per-slide reachability classifier + closure.
# --------------------------------------------------------------------------
def _charstyle(color=None, **cp):
    props = dict(cp)
    if color is not None:
        props["fontColor"] = {"r": color[0], "g": color[1], "b": color[2]}
    return {"_pbtype": "TSWP.CharacterStyleArchive", "charProperties": props}


def _base_slide_graph():
    """A slide reaching an intra-file storage, a shared global style (via a DAG) and a
    data-id image asset. No cross-slide / dangling ref, no boundary."""
    objects = {
        "1": {
            "_pbtype": "KN.SlideArchive",
            "templateSlide": {"identifier": "50"},          # -> global master
            "ownedDrawables": [{"identifier": "2"}, {"identifier": "3"}],
        },
        "2": {  # a storage on this slide, two runs both citing the SAME global style
            "_pbtype": "TSWP.StorageArchive",
            "runs": [{"identifier": "40"}, {"identifier": "40"}],
        },
        "3": {  # an image asset -> data id 700
            "_pbtype": "TSD.ImageArchive",
            "data": {"identifier": "700"},
        },
        "40": _charstyle(color=[1, 1, 0], bold=True),        # global style (DAG target)
        "50": {"_pbtype": "KN.TemplateSlide", "style": {"identifier": "40"}},  # reuses 40
    }
    id_to_file = {
        "1": "Index/Slide-1.iwa",
        "2": "Index/Slide-1.iwa",
        "3": "Index/Slide-1.iwa",
        "40": "Index/DocumentStylesheet.iwa",
        "50": "Index/Slide-900.iwa",
    }
    data_map = {"700": (0xABCDEF01, 4096)}
    pres_files = {"Index/Slide-1.iwa"}
    return objects, id_to_file, data_map, pres_files


def test_slide_key_intra_global_data_dag_is_cacheable():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key, reason = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert reason is None
    assert _is_hex64(key)


def test_dag_shared_style_dedups_not_flags():
    # The global style 40 is reached from BOTH runs of storage 2 AND from template 50 —
    # a DAG. It must dedup on first reach (never re-traversed, never an id-uniqueness
    # error) and the slide stays cacheable.
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key, reason = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert reason is None
    assert _is_hex64(key)


def test_reference_cycle_terminates_and_is_cacheable():
    # A cycle (A -> B -> A) must be walked once via the visited set, not loop forever.
    objects = {
        "1": {"_pbtype": "KN.SlideArchive", "a": {"identifier": "2"}},
        "2": {"_pbtype": "TSD.A", "back": {"identifier": "3"}},
        "3": {"_pbtype": "TSD.B", "loop": {"identifier": "2"}},  # cycle back to 2
    }
    id_to_file = {k: "Index/Slide-1.iwa" for k in objects}
    key, reason = _slide_key("1", 0, False, objects, id_to_file, {}, {"Index/Slide-1.iwa"})
    assert reason is None
    assert _is_hex64(key)


def test_cross_slide_ref_is_uncacheable():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    objects["1"]["stray"] = {"identifier": "80"}
    objects["80"] = {"_pbtype": "TSD.ImageArchive"}
    id_to_file["80"] = "Index/Slide-2.iwa"          # another presentation slide's file
    pres_files = {"Index/Slide-1.iwa", "Index/Slide-2.iwa"}
    key, reason = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert key is None
    assert reason == "cross-slide-ref"


def test_numeric_dangling_ref_is_uncacheable():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    objects["1"]["stray"] = {"identifier": "9999"}  # neither an object nor a data id
    key, reason = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert key is None
    assert reason == "dangling-ref"


def test_string_identifier_is_content_not_a_ref():
    # A string (style-name) identifier is kept verbatim, never followed -> cacheable.
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    objects["1"]["motion"] = {"identifier": "motionBackground-9-style"}
    key, reason = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert reason is None
    assert _is_hex64(key)


def test_undecodable_slide_is_uncacheable():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key, reason = _slide_key("404", 0, False, objects, id_to_file, data_map, pres_files)
    assert key is None
    assert reason == "undecodable-slide"


# --------------------------------------------------------------------------
# StylesheetArchive hard boundary.
# --------------------------------------------------------------------------
def test_stylesheet_boundary_content_is_skipped():
    assert "TSS.StylesheetArchive" in _CLOSURE_BOUNDARY
    objects = {
        "1": {"_pbtype": "KN.SlideArchive", "catalog": {"identifier": "500"}},
        "500": {
            "_pbtype": "TSS.StylesheetArchive",
            "canCullStyles": True,
            "names": {"identifier": "40"},  # a ref the boundary must NOT traverse
        },
        "40": _charstyle(color=[1, 0, 0]),
    }
    id_to_file = {"1": "Index/Slide-1.iwa", "500": "Index/DocumentStylesheet.iwa",
                  "40": "Index/DocumentStylesheet.iwa"}
    pres_files = {"Index/Slide-1.iwa"}
    key1, r1 = _slide_key("1", 0, False, objects, id_to_file, {}, pres_files)
    # Churn INSIDE the stylesheet (Keynote's per-save recompaction) must not move the
    # key: its content is not emitted and its refs are not traversed.
    objects["500"]["namePool"] = {"a": 1, "b": 2, "c": 3}
    objects["500"]["names"] = {"identifier": "12345-renumbered"}
    key2, r2 = _slide_key("1", 0, False, objects, id_to_file, {}, pres_files)
    assert r1 is None and r2 is None
    assert key1 == key2


# --------------------------------------------------------------------------
# Churn-immunity (the acceptance test, synthetic): id renumber -> identical key.
# --------------------------------------------------------------------------
def _remap_node(node, mapping):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "identifier" and isinstance(v, str) and v.isdigit() and v in mapping:
                out[k] = mapping[v]
            else:
                out[k] = _remap_node(v, mapping)
        return out
    if isinstance(node, list):
        return [_remap_node(v, mapping) for v in node]
    return node


def _remap_deck(objects, id_to_file, data_map, offset=100000):
    """Apply a bijection (id -> id+offset) to every numeric id: object keys, refs,
    id_to_file keys and data_map keys — a structurally identical renumbered copy."""
    ids = set(objects) | set(data_map)
    mapping = {i: str(int(i) + offset) for i in ids if i.isdigit()}
    new_objects = {mapping.get(k, k): _remap_node(v, mapping) for k, v in objects.items()}
    new_id_to_file = {mapping.get(k, k): v for k, v in id_to_file.items()}
    new_data_map = {mapping.get(k, k): v for k, v in data_map.items()}
    return new_objects, new_id_to_file, new_data_map, mapping


def test_slide_key_is_invariant_under_id_renumber():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key1, _ = _slide_key("1", 3, True, objects, id_to_file, data_map, pres_files)
    r_objects, r_id_to_file, r_data_map, mapping = _remap_deck(objects, id_to_file, data_map)
    key2, _ = _slide_key(
        mapping["1"], 3, True, r_objects, r_id_to_file, r_data_map, pres_files
    )
    assert key1 == key2  # a save's renumber must not move the key


def _scramble_deck(objects, id_to_file, data_map):
    """Remap every numeric id via an ORDER-SCRAMBLING permutation (not id+offset).

    The mapping is a shuffle of the graph's own ids, so the new id VALUES bear no
    relation to their numeric order — the only thing that can keep the key stable is a
    discovery order that is structural (field/list order), never id-value driven.
    """
    ids = sorted(
        (i for i in set(objects) | set(data_map) | set(id_to_file) if i.isdigit()),
        key=int,
    )
    shuffled = list(ids)
    random.Random(1234).shuffle(shuffled)
    mapping = dict(zip(ids, shuffled))
    new_objects = {mapping.get(k, k): _remap_node(v, mapping) for k, v in objects.items()}
    new_id_to_file = {mapping.get(k, k): v for k, v in id_to_file.items()}
    new_data_map = {mapping.get(k, k): v for k, v in data_map.items()}
    return new_objects, new_id_to_file, new_data_map, mapping


def test_slide_key_is_invariant_under_order_scrambling_renumber():
    # The real guarantee: discovery order is STRUCTURAL, not id-value dependent. A
    # permutation that scrambles numeric order (not a uniform +offset) must still
    # yield a byte-identical slide key.
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key1, r1 = _slide_key("1", 2, False, objects, id_to_file, data_map, pres_files)
    r_objects, r_id_to_file, r_data_map, mapping = _scramble_deck(objects, id_to_file, data_map)
    key2, r2 = _slide_key(mapping["1"], 2, False, r_objects, r_id_to_file, r_data_map, pres_files)
    assert r1 is None and r2 is None
    assert key1 == key2


def test_global_key_is_invariant_under_order_scrambling_renumber():
    objects, file_ids, pres_files = _global_deck()
    key1 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    # Scramble every numeric id AND the master file's id-suffixed name (to a value out
    # of numeric order), leaving masked content + stripped names identical.
    _ro, _idf, _dm, mapping = _scramble_deck(objects, {}, {})
    r_objects = {mapping.get(k, k): _remap_node(v, mapping) for k, v in objects.items()}
    r_file_ids = {
        "Index/Document.iwa": [mapping.get(i, i) for i in file_ids["Index/Document.iwa"]],
        "Index/Slide-3.iwa": [mapping.get(i, i) for i in file_ids["Index/Slide-900.iwa"]],
        "Index/Metadata.iwa": [mapping.get(i, i) for i in file_ids["Index/Metadata.iwa"]],
        "Index/Slide-1.iwa": [mapping.get(i, i) for i in file_ids["Index/Slide-1.iwa"]],
    }
    key2 = _global_key(r_objects, r_file_ids, pres_files, _FONT, _OS)
    assert key1 == key2


def test_applied_master_style_ref_swap_moves_slide_key():
    # The mechanism that makes the coarse global mask SAFE: a rendered master change is
    # caught PER-SLIDE. A slide reaches a master by direct numeric ref; the master
    # points at style A. Repointing it to a different style B moves the slide's key.
    objects = {
        "1": {"_pbtype": "KN.SlideArchive", "templateSlide": {"identifier": "50"}},
        "50": {"_pbtype": "KN.TemplateSlide", "style": {"identifier": "40"}},  # -> A
        "40": _charstyle(color=[1, 1, 0], bold=True),   # style A
        "41": _charstyle(color=[0, 1, 1], bold=False),  # style B
    }
    id_to_file = {
        "1": "Index/Slide-1.iwa",
        "50": "Index/Slide-900.iwa",
        "40": "Index/DocumentStylesheet.iwa",
        "41": "Index/DocumentStylesheet.iwa",
    }
    pres_files = {"Index/Slide-1.iwa"}
    key_a, ra = _slide_key("1", 0, False, objects, id_to_file, {}, pres_files)
    objects["50"]["style"] = {"identifier": "41"}  # master now applies style B
    key_b, rb = _slide_key("1", 0, False, objects, id_to_file, {}, pres_files)
    assert ra is None and rb is None
    assert key_a != key_b


def test_movie_asset_crc_moves_key_but_id_renumber_does_not():
    # image/movie share the @data CRC:size path; this mirrors the image-`data` test on
    # the `movieData` ref.
    objects = {
        "1": {"_pbtype": "KN.SlideArchive", "ownedDrawables": [{"identifier": "3"}]},
        "3": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "700"}},
    }
    id_to_file = {"1": "Index/Slide-1.iwa", "3": "Index/Slide-1.iwa"}
    data_map = {"700": (0xDEADBEEF, 8192)}
    pres_files = {"Index/Slide-1.iwa"}
    key1, _ = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    changed = {"700": (0x00000000, 8192)}  # same id, new CRC (movie bytes edited)
    key2, _ = _slide_key("1", 0, False, objects, id_to_file, changed, pres_files)
    assert key1 != key2
    # ...but a pure renumber of the movie's data id (and its ref) does NOT move it.
    r_objects, r_id_to_file, r_data_map, mapping = _remap_deck(objects, id_to_file, data_map)
    key3, _ = _slide_key(mapping["1"], 0, False, r_objects, r_id_to_file, r_data_map, pres_files)
    assert key1 == key3


# --------------------------------------------------------------------------
# Sensitivity: a real edit / position / skip / asset change moves the key.
# --------------------------------------------------------------------------
def test_style_prop_change_moves_key():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key1, _ = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    objects["40"]["charProperties"]["bold"] = False  # resolved style prop edit
    key2, _ = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    assert key1 != key2


def test_data_crc_change_moves_key_but_id_renumber_does_not():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    key1, _ = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    changed = dict(data_map)
    changed["700"] = (0x00000000, 4096)  # same id, new CRC (image bytes edited)
    key2, _ = _slide_key("1", 0, False, objects, id_to_file, changed, pres_files)
    assert key1 != key2
    # ...while a pure renumber of the data id (and its object ref) does NOT move it.
    r_objects, r_id_to_file, r_data_map, mapping = _remap_deck(objects, id_to_file, data_map)
    key3, _ = _slide_key(mapping["1"], 0, False, r_objects, r_id_to_file, r_data_map, pres_files)
    assert key1 == key3


def test_position_and_skip_move_key():
    objects, id_to_file, data_map, pres_files = _base_slide_graph()
    base, _ = _slide_key("1", 0, False, objects, id_to_file, data_map, pres_files)
    moved, _ = _slide_key("1", 1, False, objects, id_to_file, data_map, pres_files)
    skipped, _ = _slide_key("1", 0, True, objects, id_to_file, data_map, pres_files)
    assert base != moved
    assert base != skipped


# --------------------------------------------------------------------------
# Global key.
# --------------------------------------------------------------------------
def _global_deck():
    objects = {
        "d1": {"_pbtype": "KN.DocumentArchive", "canvas": {"width": 1920, "height": 1080},
               "ref": {"identifier": "10"}},
        "10": {"_pbtype": "TSD.SomeArchive", "value": 1},
        "m1": {"_pbtype": "KN.TemplateSlide", "bg": {"identifier": "11"}},
        "11": {"_pbtype": "TSD.Fill", "color": {"r": 0.5}},
        "meta1": {"_pbtype": "KN.MetadataArchive", "thumb": "big"},
        "slide1": {"_pbtype": "KN.SlideArchive"},
    }
    file_ids = {
        "Index/Document.iwa": ["d1", "10"],          # IN
        "Index/Slide-900.iwa": ["m1", "11"],         # a master -> IN
        "Index/Metadata.iwa": ["meta1"],             # EXCLUDED
        "Index/Slide-1.iwa": ["slide1"],             # a presentation slide -> excluded
    }
    pres_files = {"Index/Slide-1.iwa"}
    return objects, file_ids, pres_files


def test_global_key_is_hex_and_reacts_to_included_file():
    objects, file_ids, pres_files = _global_deck()
    key1 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    assert _is_hex64(key1)
    objects["11"]["color"] = {"r": 0.9}  # edit inside an INCLUDED master
    key2 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    assert key1 != key2


def test_global_key_ignores_excluded_file():
    objects, file_ids, pres_files = _global_deck()
    key1 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    objects["meta1"]["thumb"] = "changed"  # edit inside EXCLUDED Metadata
    key2 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    assert key1 == key2


def test_global_key_reacts_to_font_env_and_os_build():
    objects, file_ids, pres_files = _global_deck()
    base = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    assert base != _global_key(objects, file_ids, pres_files, "other-font-env", _OS)
    assert base != _global_key(objects, file_ids, pres_files, _FONT, "other-os")


def test_global_key_is_invariant_under_id_renumber():
    objects, file_ids, pres_files = _global_deck()
    key1 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    # Renumber every numeric id AND the master file's id-suffixed name.
    r_objects, _idf, _dm, mapping = _remap_deck(objects, {}, {})
    r_file_ids = {
        "Index/Document.iwa": [mapping.get(i, i) for i in file_ids["Index/Document.iwa"]],
        "Index/Slide-1200.iwa": [mapping.get(i, i) for i in file_ids["Index/Slide-900.iwa"]],
        "Index/Metadata.iwa": [mapping.get(i, i) for i in file_ids["Index/Metadata.iwa"]],
        "Index/Slide-1.iwa": [mapping.get(i, i) for i in file_ids["Index/Slide-1.iwa"]],
    }
    key2 = _global_key(r_objects, r_file_ids, pres_files, _FONT, _OS)
    assert key1 == key2


def test_document_iwa_slide_size_change_moves_global_key():
    # The slide size (a scalar in Document.iwa) drives all geometry, is INCLUDED in the
    # global key, and survives id-masking — so editing it must move the global key.
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "size": {"width": 1920, "height": 1080}},
    }
    file_ids = {"Index/Document.iwa": ["show"]}
    pres_files: set[str] = set()
    key1 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    objects["show"]["size"] = {"width": 1280, "height": 720}  # resized canvas
    key2 = _global_key(objects, file_ids, pres_files, _FONT, _OS)
    assert key1 != key2


# --------------------------------------------------------------------------
# End-to-end over a synthetic deck (with a ShowArchive so slide_order fires).
# --------------------------------------------------------------------------
def _full_synthetic_deck():
    objects = {
        "node0": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "s0"}},
        "node1": {"_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": "s1"},
                  "isSkipped": True},
        "s0": {"_pbtype": "KN.SlideArchive", "style": {"identifier": "40"},
               "template": {"identifier": "m0"}},
        "s1": {"_pbtype": "KN.SlideArchive", "style": {"identifier": "41"}},
        "40": _charstyle(color=[1, 1, 0]),
        "41": _charstyle(color=[0, 1, 1]),
        "m0": {"_pbtype": "KN.TemplateSlide", "value": 1},
        "meta": {"_pbtype": "KN.MetadataArchive", "thumb": "x"},
        "show": {"_pbtype": "KN.ShowArchive",
                 "slideTree": {"slides": [{"identifier": "node0"}, {"identifier": "node1"}]}},
    }
    id_to_file = {
        "s0": "Index/Slide-10.iwa", "s1": "Index/Slide-11.iwa",
        "40": "Index/DocumentStylesheet.iwa", "41": "Index/DocumentStylesheet.iwa",
        "m0": "Index/Slide-900.iwa",
    }
    file_ids = {
        "Index/Slide-10.iwa": ["s0"], "Index/Slide-11.iwa": ["s1"],
        "Index/DocumentStylesheet.iwa": ["40", "41"],
        "Index/Slide-900.iwa": ["m0"], "Index/Metadata.iwa": ["meta"],
        "Index/Document.iwa": ["node0", "node1", "show"],
    }
    return objects, id_to_file, file_ids


def test_fingerprint_end_to_end_shape():
    objects, id_to_file, file_ids = _full_synthetic_deck()
    out = _fingerprint(objects, id_to_file, file_ids, data_map={}, font_env=_FONT, os_build=_OS)
    assert set(out) == {"global", "slides", "uncacheable"}
    assert _is_hex64(out["global"])
    assert len(out["slides"]) == 2
    assert all(_is_hex64(k) for k in out["slides"])
    assert out["uncacheable"] == {}
    # The two slides differ (different style + skip flag).
    assert out["slides"][0] != out["slides"][1]


def test_fingerprint_records_uncacheable_by_position():
    objects, id_to_file, file_ids = _full_synthetic_deck()
    objects["s1"]["stray"] = {"identifier": "77777"}  # dangling on slide index 1
    out = _fingerprint(objects, id_to_file, file_ids, data_map={}, font_env=_FONT, os_build=_OS)
    assert out["slides"][0] is not None
    assert out["slides"][1] is None
    assert out["uncacheable"] == {1: "dangling-ref"}


# --------------------------------------------------------------------------
# Gated real-deck smoke test.
# --------------------------------------------------------------------------
@pytest.mark.skipif(not DSK.exists(), reason="local DSK deck only")
def test_real_dsk_deck_fingerprint():
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")

    out = fingerprint_deck(DSK, font_env="pinned-for-test")
    assert len(out["slides"]) == 42
    assert _is_hex64(out["global"])
    # Near-empty uncacheable (measured ~0 dangling/cross-slide on the gold decks).
    assert len(out["uncacheable"]) <= 2, out["uncacheable"]
    for i, key in enumerate(out["slides"]):
        if i in out["uncacheable"]:
            assert key is None
        else:
            assert _is_hex64(key)
    # Re-running over the same deck is deterministic.
    again = fingerprint_deck(DSK, font_env="pinned-for-test")
    assert again == out


@pytest.mark.skipif(not DSK.exists(), reason="local DSK deck only")
def test_real_dsk_shared_deck_matches_fresh_decode():
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")
    from obed_edom.iwa_runs import _load_deck

    deck = _load_deck(DSK)
    shared = fingerprint_deck(DSK, deck=copy.deepcopy(deck), font_env="pinned-for-test")
    fresh = fingerprint_deck(DSK, font_env="pinned-for-test")
    assert shared == fresh
