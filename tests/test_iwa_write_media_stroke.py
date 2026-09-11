"""Offline tests for ``iwa_write.patch_media_stroke`` (no Keynote).

Reuses the ``_build_deck`` synthetic stylesheet fixture from
``test_stroke_probe`` (styles 900/901 in ``Index/DocumentStylesheet.iwa``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from obed_edom.iwa_runs import _load_deck  # noqa: E402
from obed_edom.iwa_write import patch_media_stroke  # noqa: E402
from scripts.write_gate_ab import changed_members  # noqa: E402
from test_iwa_write import _arch, _member  # noqa: E402
from test_stroke_probe import _build_deck  # noqa: E402


@pytest.fixture()
def deck(tmp_path):
    return _build_deck(tmp_path / "stroke.key")


def test_overwrites_existing_stroke(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())

    result = patch_media_stroke(deck, {"900": {"width": 3.5, "color": (0.2, 0.4, 0.6, 1.0)}})
    assert not result["refused"]
    assert result["patched"] == ["900"]
    assert result["created"] == []
    assert result["value_clean"]

    objects, id_to_file, _fi = _load_deck(deck)
    stroke = objects["900"]["mediaProperties"]["stroke"]
    assert stroke["width"] == pytest.approx(3.5)
    color = stroke["color"]
    assert (color["r"], color["g"], color["b"], color["a"]) == pytest.approx((0.2, 0.4, 0.6, 1.0))
    assert stroke["pattern"]["type"] == "TSDSolidPattern"

    other = objects["901"]["mediaProperties"]["stroke"]
    assert other["width"] == pytest.approx(1.0)
    assert (other["color"]["r"], other["color"]["g"], other["color"]["b"]) == pytest.approx((0.0, 0.0, 0.0))

    assert changed_members(original, deck) == {"Index/DocumentStylesheet.iwa"}


def test_creates_stroke_where_absent(tmp_path):
    bare = _arch(902, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "image-2-imageStyle"}})
    deck = _build_deck(tmp_path / "bare.key", extra_stylesheet_archives=(bare,))

    result = patch_media_stroke(deck, {"902": {"width": 2.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert not result["refused"]
    assert result["created"] == ["902"]
    assert result["patched"] == ["902"]

    objects, id_to_file, _fi = _load_deck(deck)
    stroke = objects["902"]["mediaProperties"]["stroke"]
    assert stroke == {
        "color": {"model": "rgb", "r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0, "rgbspace": "srgb"},
        "width": 2.0,
        "cap": "ButtCap",
        "join": "MiterJoin",
        "miterLimit": 4.0,
        "pattern": {
            "type": "TSDSolidPattern",
            "phase": 0.0,
            "count": 0,
            "pattern": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
    }


def test_stroke_message_writes_the_submessage_verbatim(deck):
    full_stroke = {
        "color": {"model": "rgb", "r": 0.1, "g": 0.2, "b": 0.3, "a": 1.0, "rgbspace": "srgb"},
        "width": 7.0,
        "cap": "RoundCap",
        "join": "RoundJoin",
        "miterLimit": 10.0,
        "pattern": {"type": "TSDSolidPattern", "phase": 1.0, "count": 2, "pattern": [1.0, 2.0, 0.0, 0.0, 0.0, 0.0]},
        "frame": {"frameName": "square", "assetScale": 1.0},
    }
    result = patch_media_stroke(deck, {"900": {"stroke_message": full_stroke}})
    assert not result["refused"]
    assert result["patched"] == ["900"]

    objects, _id_to_file, _fi = _load_deck(deck)
    assert objects["900"]["mediaProperties"]["stroke"] == full_stroke


def test_refuses_stroke_message_missing_width(deck):
    before = deck.read_bytes()
    bad_stroke = {"color": {"model": "rgb", "r": 0.1, "g": 0.2, "b": 0.3, "a": 1.0, "rgbspace": "srgb"}}
    result = patch_media_stroke(deck, {"900": {"stroke_message": bad_stroke}})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_stroke_message_with_nan_width(deck):
    before = deck.read_bytes()
    bad_stroke = {
        "color": {"model": "rgb", "r": 0.1, "g": 0.2, "b": 0.3, "a": 1.0, "rgbspace": "srgb"},
        "width": float("nan"),
    }
    result = patch_media_stroke(deck, {"900": {"stroke_message": bad_stroke}})
    assert result["refused"]
    assert "width" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_synthesized_bool_width(deck):
    before = deck.read_bytes()
    result = patch_media_stroke(deck, {"900": {"width": True, "color": (0.1, 0.2, 0.3, 1.0)}})
    assert result["refused"]
    assert "4-tuple color" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_synthesized_nan_color_component(deck):
    before = deck.read_bytes()
    result = patch_media_stroke(deck, {"900": {"width": 2.0, "color": (float("nan"), 0.2, 0.3, 1.0)}})
    assert result["refused"]
    assert "4-tuple color" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_stroke_message_with_nan_color_leaf(deck):
    before = deck.read_bytes()
    bad_stroke = {
        "color": {"model": "rgb", "r": float("nan"), "g": 0.2, "b": 0.3, "a": 1.0, "rgbspace": "srgb"},
        "width": 2.0,
    }
    result = patch_media_stroke(deck, {"900": {"stroke_message": bad_stroke}})
    assert result["refused"]
    assert "non-finite value" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_unknown_style_id(deck):
    before = deck.read_bytes()
    result = patch_media_stroke(deck, {"999999": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert deck.read_bytes() == before


def test_refuses_wrong_archive_type(tmp_path):
    bogus = _arch(950, "TSD.ImageArchive", {"super": {"geometry": {"position": {"x": 0, "y": 0},
                                                                     "size": {"width": 1, "height": 1}, "angle": 0.0}}})
    deck = _build_deck(tmp_path / "wrongtype.key", extra_slide_archives=(bogus,))
    before = deck.read_bytes()

    result = patch_media_stroke(deck, {"950": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert "TSD.MediaStyleArchive" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_style_id_from_a_different_member(tmp_path):
    rogue = _arch(950, "TSD.MediaStyleArchive", {"super": {"styleIdentifier": "rogue-style"}})
    deck = _build_deck(tmp_path / "wrongmember.key", extra_slide_archives=(rogue,))
    before = deck.read_bytes()

    result = patch_media_stroke(deck, {"950": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]
    assert "Index/Slide-100.iwa" in result["reason"]
    assert deck.read_bytes() == before


def test_refuses_when_stylesheet_member_missing(tmp_path):
    import io
    import zipfile

    show = _arch(2, "KN.ShowArchive", {
        "slideTree": {"slides": [{"identifier": 10}]},
        "size": {"width": 1920.0, "height": 1080.0},
    })
    node = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    slide = _arch(100, "KN.SlideArchive", {"drawablesZOrder": []})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show, node, slide]))
    path = tmp_path / "no_stylesheet.key"
    path.write_bytes(buf.getvalue())

    result = patch_media_stroke(path, {"900": {"width": 3.0, "color": (1.0, 1.0, 1.0, 1.0)}})
    assert result["refused"]


def test_only_stylesheet_member_changes(deck, tmp_path):
    original = tmp_path / "original.key"
    original.write_bytes(deck.read_bytes())
    inode_before = deck.stat().st_ino

    result = patch_media_stroke(deck, {"901": {"width": 7.0, "color": (0.1, 0.2, 0.3, 1.0)}})
    assert not result["refused"]

    assert changed_members(original, deck) == {"Index/DocumentStylesheet.iwa"}
    assert deck.stat().st_ino == inode_before


_DSK_SAMPLE = Path("~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key").expanduser()


@pytest.mark.skipif(not _DSK_SAMPLE.exists(), reason="real DSK sample not present")
def test_created_stroke_matches_real_sample_shape():
    objects, id_to_file, _fi = _load_deck(_DSK_SAMPLE)
    real = objects["15303898"]["mediaProperties"]["stroke"]

    from obed_edom.iwa_write import _stroke_submessage
    built = _stroke_submessage({"width": real["width"], "color": (
        real["color"]["r"], real["color"]["g"], real["color"]["b"], real["color"]["a"],
    )})
    assert set(built) == set(real)
    assert set(built["color"]) == set(real["color"])
    assert set(built["pattern"]) == set(real["pattern"])
    assert built["cap"] == real["cap"]
    assert built["join"] == real["join"]
    assert built["miterLimit"] == pytest.approx(real["miterLimit"])
    assert built["pattern"]["type"] == real["pattern"]["type"]


def test_refuses_when_reparse_stroke_does_not_match_requested_message(deck, monkeypatch):
    """The reparse-equality gate must refuse when the post-write reparse of the
    stylesheet member disagrees with the `stroke_message` that was requested -- e.g. a
    keynote_parser round-trip bug that silently mangles a field. Monkeypatches
    `IWAFile.from_buffer` so only the second call (the post-write reparse) returns a
    mutated stroke; the deck must be left byte-identical."""
    import obed_edom.iwa_write as iwa_write_mod

    before = deck.read_bytes()
    orig_from_buffer = iwa_write_mod.IWAFile.from_buffer
    calls = {"n": 0}
    target_member = "Index/DocumentStylesheet.iwa"

    def _fake_from_buffer(data, filename=None):
        result = orig_from_buffer(data, filename)
        if filename == target_member:
            calls["n"] += 1
        if filename == target_member and calls["n"] == 3:
            orig_to_dict = result.to_dict

            def _mutated_to_dict():
                decoded = orig_to_dict()
                for ch in decoded["chunks"]:
                    for arch in ch["archives"]:
                        if str(arch["header"]["identifier"]) != "900":
                            continue
                        for o in arch.get("objects") or []:
                            stroke = (o.get("mediaProperties") or {}).get("stroke")
                            if stroke is not None:
                                o["mediaProperties"]["stroke"] = dict(stroke, width=999.0)
                return decoded

            result.to_dict = _mutated_to_dict
        return result

    monkeypatch.setattr(iwa_write_mod.IWAFile, "from_buffer", staticmethod(_fake_from_buffer))

    full_stroke = {
        "color": {"model": "rgb", "r": 0.1, "g": 0.2, "b": 0.3, "a": 1.0, "rgbspace": "srgb"},
        "width": 7.0,
        "cap": "RoundCap",
        "join": "RoundJoin",
        "miterLimit": 10.0,
        "pattern": {"type": "TSDSolidPattern", "phase": 1.0, "count": 2, "pattern": [1.0, 2.0, 0.0, 0.0, 0.0, 0.0]},
        "frame": {"frameName": "square", "assetScale": 1.0},
    }
    result = patch_media_stroke(deck, {"900": {"stroke_message": full_stroke}})

    assert result["refused"]
    assert "reparsed stroke does not match requested message" in result["reason"]
    assert deck.read_bytes() == before
