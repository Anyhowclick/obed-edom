"""Stage T: Keynote HTML-export texture repair (`preview_textures`).

Synthetic exports use blank PDF pages: blank renders are flat, so the pixel rules give no verdict
and OCR reads nothing, which isolates the JSON detector, the donor rules and the writer. The pixel
rules (R4, R6) and OCR are exercised by the fixture-backed Alpha round trip.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
from dataclasses import replace
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject

from obed_edom import live_continuity as lc, preview_textures as pt
from obed_edom.fixture_paths import fixture
from obed_edom.html_preview import PreviewError, PreviewStale, file_sha256
from obed_edom.live_continuity import derive_plan
from obed_edom.live_runtime import SUPPORTED_PLAYERS

PLAYER = next(iter(SUPPORTED_PLAYERS))
CANVAS = (1920, 1080)


def _state(x: float, y: float, w: float, h: float) -> dict:
    """initialState whose rect, relative to its parent's origin, is (x, y, w, h)."""
    return {
        "position": {"pointX": x + w / 2, "pointY": y + h / 2},
        "anchorPoint": {"pointX": 0.5, "pointY": 0.5},
        "width": w,
        "height": h,
    }


def _leaf(texture: str, w: float, h: float, kind: int | None = 6, **extra) -> dict:
    node = {"texture": texture, "initialState": _state(0, 0, w, h), **extra}
    if kind is not None:
        node["texturedRectangle"] = {"textureType": kind}
    return node


def _slot(rect: tuple, texture: str, kind: int | None = 6, oid: str | None = None) -> dict:
    """A base-tree slot as the export writes it: canvas layer -> wrapper at rect -> leaf."""
    wrapper = {"initialState": _state(*rect), "layers": [_leaf(texture, rect[2], rect[3], kind)]}
    if oid:
        wrapper["objectID"] = oid
    return {"initialState": _state(0, 0, *CANVAS), "layers": [wrapper]}


def _flat(rect: tuple, texture: str, kind: int | None = 5) -> dict:
    """A flattened slot as later events write it: canvas layer -> leaf at rect, no wrapper."""
    leaf = _leaf(texture, rect[2], rect[3], kind)
    leaf["initialState"] = _state(*rect)
    return {"initialState": _state(0, 0, *CANVAS), "layers": [leaf]}


def _event(slots: list, effects: list | None = None, texts: list | None = None) -> dict:
    return {
        "baseLayer": {"initialState": _state(0, 0, *CANVAS), "layers": slots},
        "effects": effects or [],
        "accessibility": [
            {"text": text, "targetRectangle": {"x": r[0], "y": r[1], "width": r[2], "height": r[3]}}
            for text, r in texts or []
        ],
    }


def _movie(oid: str, asset: str, rect: tuple, poster: str) -> dict:
    w, h = rect[2:]
    return {
        "name": "apple:movie-start",
        "type": "buildIn",
        "objectID": oid,
        "baseLayer": {"initialState": _state(*rect), "layers": []},
        "effects": [
            {
                "name": "renderMovie",
                "objectID": oid,
                "movie": {"asset": asset},
                "baseLayer": {
                    "initialState": _state(*rect),
                    "layers": [_leaf(poster, w, h, 5), _leaf("VIDEO", w * 0.5, h * 0.5, None, isVideoLayer=True)],
                },
            }
        ],
    }


def _magic_move(rect: tuple, texture: str, to: str | None, dx: float, kind: int | None = 6) -> dict:
    """A Magic Move leaf moving right by dx; `to=None` means it has no contents animation."""
    leaf = _leaf(texture, rect[2], rect[3], kind)
    animations = [{"property": "transform.translation", "to": {"pointX": dx, "pointY": 0}}]
    if to:
        animations.append({"property": "contents", "from": {"texture": texture}, "to": {"texture": to}})
    leaf["animations"] = [{"animations": animations}]
    return {
        "name": pt.MAGIC_MOVE,
        "type": "transition",
        "baseLayer": {"initialState": _state(0, 0, *CANVAS), "layers": [{"initialState": _state(*rect), "layers": [leaf]}]},
    }


def _export(root: Path, slides: list[tuple[str, dict, list]]) -> list[dict]:
    """Write (uuid, textures {id: (w, h[, fill])}, events) slides with blank PDF pages, or pages whose
    left ("L") or top ("T") half is filled black; return manifest slides."""
    for uuid, textures, events in slides:
        folder = root / "assets" / uuid
        (folder / "assets").mkdir(parents=True)
        url = {"native": f"assets/{uuid}.pdf"}
        assets = {
            tid: {"type": "texture", "index": i, "url": url, "width": w, "height": h}
            for i, (tid, (w, h, *_)) in enumerate(textures.items())
        }
        assets["VIDEO"] = {"type": "texture", "index": 0, "url": {"native": "assets/frame.jpg"}, "width": 400, "height": 200}
        assets["MOVIE"] = {"type": "video", "index": 0, "url": {"native": "assets/Clip.mov-0.0000-5.0000.mov"}}
        payload = {"assets": assets, "events": events}
        (folder / f"{uuid}.json").write_text(json.dumps(payload))
        (folder / f"{uuid}.jsonp").write_text(f"local_slide( {json.dumps({'name': uuid, 'json': payload})} )")
        writer = PdfWriter()
        for w, h, *fill in textures.values():
            page = writer.add_blank_page(w, h)
            if fill:
                box = {"L": (0, 0, w / 2, h), "T": (0, h / 2, w, h / 2)}[fill[0]]
                stream = DecodedStreamObject()
                stream.set_data(b"0 g %f %f %f %f re f" % box)
                page.replace_contents(stream)
        pdf = folder / "assets" / f"{uuid}.pdf"
        with pdf.open("wb") as handle:
            writer.write(handle)
        encoded = base64.b64encode(pdf.read_bytes()).decode()
        pdf.with_suffix(".pdfp").write_text(f"local_pdf( {json.dumps({'slide': uuid, 'pdf': encoded})} );")
    return [
        {
            "originalOrdinal": i + 1,
            "originalSlideId": uuid,
            "skipped": False,
            "exportedUuid": uuid,
            "playerIndex": i,
        }
        for i, (uuid, _, _) in enumerate(slides)
    ]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _repair(root: Path, slides: list[dict], player: str = PLAYER, **kwargs) -> tuple[dict, list[str]]:
    lines: list[str] = []
    return pt.repair_textures(root, slides, player_digest=player, log=lines.append, **kwargs), lines


LABEL = (100, 100, 100, 20)
TEXT_BOX = (100, 98, 100, 24)
POSTER = (300, 300, 200, 100)


def test_json_hits_flag_a_missized_leaf_but_not_a_scaled_movie_frame(tmp_path):
    slides = _export(
        tmp_path,
        [
            (
                "S1",
                {"BIG": (400, 300), "POSTER": (200, 100), "OK": (100, 20)},
                [_event([_slot(LABEL, "BIG"), _slot((100, 200, 100, 20), "OK")], [_movie("M1", "MOVIE", POSTER, "POSTER")])],
            )
        ],
    )
    hits = pt.json_hits(tmp_path, slides)
    assert hits == ["slide 1 0/baseLayer/layers/0/layers/0/layers/0: 100×20 leaf uses 400×300 texture BIG"]

    before = _snapshot(tmp_path)
    record, lines = _repair(tmp_path, slides, player="0" * 64)
    assert record == {"version": 1, "playerDigest": "0" * 64, "skipped": "unsupported player", "repaired": [], "pdfs": []}
    assert lines == ["Texture check skipped: unsupported player"] and _snapshot(tmp_path) == before


def _d1_slides():
    return [
        (
            "S1",
            {"BAD": (400, 300), "GOOD": (100, 20)},
            [
                _event([_slot(LABEL, "BAD")], texts=[("Sunday Service", TEXT_BOX)]),
                _event([_slot(LABEL, "GOOD")], texts=[("\uff33unday Service", TEXT_BOX)]),
            ],
        )
    ]


def _d3_slides():
    return [
        (
            "S1",
            {"WRONG": (1920, 1080), "POSTER": (200, 100)},
            [_event([_slot(POSTER, "WRONG", kind=5, oid="M1")], [_movie("M1", "MOVIE", POSTER, "POSTER")])],
        )
    ]


def _glyph_slides(bad="base", variant=None):
    rects = [(100, 100, 40, 60), (180, 100, 40, 60)]
    base = ["BASE_I", "BASE_A"]
    effect = ["EFFECT_I", "EFFECT_A"]
    if bad == "base":
        base[0] = "BAD"
    else:
        effect[0] = "BAD"
    if variant == "both":
        effect[0] = "BAD"
    elif variant == "donor-hit":
        effect[0] = "DONOR_BAD"
    elif variant == "donor-reused":
        effect[1] = effect[0]
    wrapper = {
        "initialState": _state(0, 0, *CANVAS),
        "objectID": "GLYPHS",
        "layers": [],
    }
    for texture, rect in zip(base, rects, strict=True):
        leaf = _leaf(texture, rect[2], rect[3])
        leaf["initialState"] = _state(*rect)
        wrapper["layers"].append(leaf)
    effect_wrappers = []
    for texture, rect in zip(effect, rects, strict=True):
        effect_wrappers.append({"initialState": _state(*rect), "layers": [_leaf(texture, rect[2], rect[3])]})
    if variant == "rect":
        effect_wrappers[0]["initialState"] = _state(rects[0][0] + 1, *rects[0][1:])
    if variant == "textured-rectangle":
        effect_wrappers[0]["layers"][0]["texturedRectangle"]["variant"] = "other"
    glyph_effect = {
        "name": "apple:any-per-glyph-build",
        "type": "buildIn",
        "objectID": "GLYPHS",
        "baseLayer": {
            "initialState": _state(0, 0, *CANVAS),
            "objectID": "GLYPHS",
            "layers": effect_wrappers,
        },
    }
    textures = {
        "BAD": (400, 300, "T"),
        "BASE_I": (40, 60, "L"),
        "BASE_A": (40, 60, "T"),
        "EFFECT_I": (40, 60, "L"),
        "EFFECT_A": (40, 60, "T"),
    }
    if variant == "donor-hit":
        textures["DONOR_BAD"] = (300, 400, "L")
    slot = {"initialState": _state(0, 0, *CANVAS), "layers": [wrapper]}
    return [("S1", textures, [_event([slot], [glyph_effect])])]


def _d2_slides():
    landed = (150, 100, 100, 20)
    return [
        (
            "S1",
            {"HELLO": (100, 20), "TO": (100, 20)},
            [_event([_slot(LABEL, "HELLO")]), _event([], [_magic_move(LABEL, "HELLO", "TO", 50)])],
        ),
        # Event 1 repeats the bad leaf with NFKC-equivalent accessibility text: same group, one graft.
        (
            "S2",
            {"BIG": (400, 300)},
            [
                _event([_slot(landed, "BIG")], texts=[("Hello", landed)]),
                _event([_slot(landed, "BIG")], texts=[("\uff28ello", landed)]),
            ],
        ),
    ]


def _d2_image_slides(group_competitor: bool = False):
    landed = (150, 100, 100, 20)
    later = [_slot(landed, "BIG", kind=5)]
    textures = {"BIG": (400, 300, "T")}
    if group_competitor:
        later.append(_slot(landed, "OTHER", kind=6))
        textures["OTHER"] = (100, 20, "L")
    return [
        (
            "S1",
            {"HELLO": (100, 20, "L"), "TO": (100, 20, "L")},
            [
                _event([_slot(LABEL, "HELLO", kind=5)]),
                _event([], [_magic_move(LABEL, "HELLO", "TO", 50, kind=5)]),
            ],
        ),
        (
            "S2",
            textures,
            [_event([_slot(landed, "BIG", kind=5)]), _event(later)],
        ),
    ]


def _source_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(100, 20)
    stream = DecodedStreamObject()
    stream.set_data(b"0 g 0 0 50 20 re f")
    page.replace_contents(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _source_deck(tmp_path: Path, monkeypatch, case: str) -> tuple[Path, str]:
    source = tmp_path / "source.key"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("Data/map-44137.pdf", _source_pdf())
    destination_data = "44140" if case == "different-data" else "44137"
    objects = {
        "S1": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "SRC"}]},
        "S2": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "DEST"}]},
        "SRC": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": 101, "y": 101}, "size": {"width": 98, "height": 18}},
            "data": {"identifier": "44137"},
            "style": {"opacity": 0},
        },
        "DEST": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": 151, "y": 101}, "size": {"width": 98, "height": 18}},
            "data": {"identifier": destination_data},
        },
    }
    if case == "drawable-competitor":
        objects["S2"]["drawablesZOrder"].append({"identifier": "OTHER"})
        objects["OTHER"] = {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "geometry": {"position": {"x": 152, "y": 102}, "size": {"width": 96, "height": 16}},
        }
    monkeypatch.setattr(
        "obed_edom.iwa_runs._load_deck_full",
        lambda *_args, **_kwargs: (objects, {}, {}, set()),
    )
    return source, file_sha256(source)


def _d2_chained_slides():
    source, middle, target = (100, 500, 60, 30), (150, 500, 60, 30), (200, 500, 60, 30)
    text = "Point 1"
    return [
        (
            "S1",
            {"Y": (60, 30, "L")},
            [
                _event([_slot(source, "Y")], texts=[(text, source)]),
                _event([], [_magic_move(source, "Y", "Y", 50)], texts=[(text, source)]),
            ],
        ),
        (
            "S2",
            {"Y": (60, 30, "T"), "Y2": (60, 30, "L")},
            [
                _event([_slot(middle, "Y")], texts=[(text, middle)]),
                _event([_slot(middle, "Y2")], texts=[(text, middle)]),
                _event([], [_magic_move(middle, "Y", "Y", 50)], texts=[(text, middle)]),
            ],
        ),
        (
            "S3",
            {"Y": (60, 30, "L")},
            [_event([_slot(target, "Y")], texts=[(text, target)])],
        ),
    ]


def _d4_slides(movie_copy: bool = True):
    tag, landed = (100, 400, 60, 30), (150, 400, 60, 30)
    textures = {"BIG": (400, 300), "CAND": (60, 30, "L")}
    events = [_event([_slot(landed, "BIG", kind=5)]), _event([_slot(landed, "CAND", kind=5)])]
    if movie_copy:
        textures["MOVIE_COPY"] = (60, 30, "T")
        events += [
            _event([_slot(landed, "MOVIE_COPY", kind=5, oid="M1")], [_movie("M1", "MOVIE", landed, "MOVIE_COPY")]),
            _event([_flat(landed, "MOVIE_COPY")]),
        ]
    return [
        (
            "S1",
            {"TAG": (60, 30, "L")},
            [_event([_slot(tag, "TAG", kind=5)]), _event([], [_magic_move(tag, "TAG", None, 50, kind=5)])],
        ),
        ("S2", textures, events),
    ]


def _d4_chained_slides(contents_to=None):
    source, middle, target = (100, 500, 60, 30), (150, 500, 60, 30), (200, 500, 60, 30)
    return [
        (
            "S1",
            {"LAND": (60, 30, "L")},
            [_event([_slot(source, "LAND", kind=5)]), _event([], [_magic_move(source, "LAND", "LAND", 50, kind=5)])],
        ),
        (
            "S2",
            {"BAD": (60, 30, "T"), "GOOD": (60, 30, "L")},
            [
                _event([_slot(middle, "BAD", kind=5)]),
                _event([_slot(middle, "GOOD", kind=5)]),
                _event([], [_magic_move(middle, "BAD", contents_to, 50, kind=5)]),
            ],
        ),
        (
            "S3",
            {"WRONG": (400, 300), "BAD_COPY": (60, 30, "T")},
            [_event([_slot(target, "WRONG", kind=5)]), _event([_slot(target, "BAD_COPY", kind=5)])],
        ),
    ]


D2_ID = hashlib.sha256(b"S2:S1:TO").hexdigest()[:32].upper()


@pytest.mark.parametrize(
    "build, expected",
    [
        pytest.param(
            _d1_slides,
            {"ordinal": 1, "rule": "D1", "from": "BAD", "to": "GOOD", "donor": None},
            id="D1-same-rect-same-text",
        ),
        pytest.param(
            _d3_slides,
            {"ordinal": 1, "rule": "D3", "from": "WRONG", "to": "POSTER", "donor": None},
            id="D3-poster-by-objectID",
        ),
        pytest.param(
            lambda: _glyph_slides("base"),
            {
                "ordinal": 1,
                "rule": "D1g",
                "from": "BAD",
                "to": "EFFECT_I",
                "donor": None,
                "verify": {
                    "objectID": "GLYPHS",
                    "glyph": 0,
                    "twin": "0/effects/0/baseLayer/layers/0/layers/0",
                },
                "leaf": "0/baseLayer/layers/0/layers/0/layers/0",
            },
            id="D1g-base-glyph-uses-effect-twin",
        ),
        pytest.param(
            lambda: _glyph_slides("effect"),
            {
                "ordinal": 1,
                "rule": "D1g",
                "from": "BAD",
                "to": "BASE_I",
                "donor": None,
                "verify": {
                    "objectID": "GLYPHS",
                    "glyph": 0,
                    "twin": "0/baseLayer/layers/0/layers/0/layers/0",
                },
                "leaf": "0/effects/0/baseLayer/layers/0/layers/0",
            },
            id="D1g-effect-glyph-uses-base-twin",
        ),
        pytest.param(
            lambda: _glyph_slides("base", "both"),
            {"refused": "slide 1 (40×60 text): its texture is mis-mapped and no verified replacement exists"},
            id="D1g-refuses-shared-bad-id",
        ),
        pytest.param(
            lambda: _glyph_slides("base", "rect"),
            {"refused": "slide 1 (40×60 text): its texture is mis-mapped and no verified replacement exists"},
            id="D1g-refuses-twin-rect-mismatch",
        ),
        pytest.param(
            lambda: _glyph_slides("base", "textured-rectangle"),
            {"refused": "slide 1 (40×60 text): its texture is mis-mapped and no verified replacement exists"},
            id="D1g-refuses-textured-rectangle-mismatch",
        ),
        pytest.param(
            lambda: _glyph_slides("base", "donor-hit"),
            {"refused": "slide 1 (40×60 text): its texture is mis-mapped and no verified replacement exists"},
            id="D1g-refuses-donor-hit",
        ),
        pytest.param(
            lambda: _glyph_slides("base", "donor-reused"),
            {"refused": "slide 1 (40×60 text): its texture is mis-mapped and no verified replacement exists"},
            id="D1g-refuses-donor-used-by-another-glyph",
        ),
        pytest.param(
            _d2_slides,
            {"ordinal": 2, "rule": "D2", "from": "BIG", "to": D2_ID, "donor": {"uuid": "S1", "id": "TO", "page": 2}},
            id="D2-graft-magic-move-landing",
        ),
        pytest.param(
            _d2_image_slides,
            {
                "ordinal": 2,
                "rule": "D2",
                "from": "BIG",
                "to": D2_ID,
                "donor": {"uuid": "S1", "id": "TO", "page": 2},
                "verify": {"corr": 1.0, "object": "DEST", "sourceObject": "SRC", "data": "44137"},
                "source": "ok",
            },
            id="D2-image-source-certificate-opacity-zero",
        ),
        pytest.param(
            _d2_image_slides,
            {
                "refused": "slide 2 (100×20 image): its texture is mis-mapped and no verified replacement exists",
                "source": "drawable-competitor",
            },
            id="D2-image-refuses-envelope-drawable-competitor",
        ),
        pytest.param(
            _d2_image_slides,
            {
                "refused": "slide 2 (100×20 image): its texture is mis-mapped and no verified replacement exists",
                "source": "different-data",
            },
            id="D2-image-refuses-different-source-data",
        ),
        pytest.param(
            lambda: _d2_image_slides(group_competitor=True),
            {
                "refused": "slide 2 (100×20 image): its texture is mis-mapped and no verified replacement exists",
                "source": "ok",
            },
            id="D2-image-refuses-unresolved-group-member",
        ),
        pytest.param(
            _d2_image_slides,
            {"stale": True, "source": "wrong-digest"},
            id="D2-image-refuses-stale-source-before-writing",
        ),
        pytest.param(
            _d2_chained_slides,
            {"refused": "slide 3 ('Point 1' label): its texture is mis-mapped and no verified replacement exists"},
            id="D2-refuses-landing-repointed-in-this-pass",
        ),
        pytest.param(
            _d4_slides,
            {"ordinal": 2, "rule": "D4", "from": "BIG", "to": "CAND", "donor": None, "verify": {"corr": 1.0}},
            id="D4-ignores-flattened-movie-copy",
        ),
        pytest.param(
            _d4_chained_slides,
            {"refused": "slide 3 (60×30 image): its texture is mis-mapped and no verified replacement exists"},
            id="D4-refuses-landing-repointed-in-this-pass",
        ),
        pytest.param(
            lambda: _d4_chained_slides("BAD"),
            {"refused": "slide 3 (60×30 image): its texture is mis-mapped and no verified replacement exists"},
            id="D4-refuses-unchanged-contents-landing-repointed-in-this-pass",
        ),
        pytest.param(
            lambda: _d4_slides(movie_copy=False),
            {
                "refused": "slide 2 (60×30 image): its texture is mis-mapped and no verified replacement exists",
                "raw_corr": 0.8996,
            },
            id="D4-compares-raw-correlation",
        ),
    ],
)
def test_repair_picks_the_rule_and_writes_a_consistent_export(tmp_path, monkeypatch, build, expected):
    slides = _export(tmp_path, build())
    expected = dict(expected)
    expected_leaf = expected.pop("leaf", "0/baseLayer/layers/0/layers/0/layers/0")
    unchanged_payload = None
    unchanged_pdf = None
    if expected.get("rule") == "D1g":
        uuid = slides[expected["ordinal"] - 1]["exportedUuid"]
        folder = tmp_path / "assets" / uuid
        unchanged_payload = json.loads((folder / f"{uuid}.json").read_text())["assets"]
        unchanged_pdf = (folder / "assets" / f"{uuid}.pdf").read_bytes()
    kwargs = {}
    source_case = expected.pop("source", None)
    if source_case is not None:
        source, digest = _source_deck(tmp_path, monkeypatch, source_case)
        kwargs = {"source_path": source, "source_digest": "0" * 64 if source_case == "wrong-digest" else digest}
    if (corr := expected.pop("raw_corr", None)) is not None:
        monkeypatch.setattr(pt, "_corr", lambda _a, _b: corr)
    if expected.pop("stale", False):
        before = _snapshot(tmp_path)
        with pytest.raises(PreviewStale, match="source deck changed during texture repair"):
            _repair(tmp_path, slides, **kwargs)
        assert _snapshot(tmp_path) == before
        return
    if refused := expected.pop("refused", None):
        before = _snapshot(tmp_path)
        with pytest.raises(pt.TextureRepairRefused) as raised:
            _repair(tmp_path, slides, **kwargs)
        assert str(raised.value) == f"Cannot repair Keynote's HTML export: {refused}"
        assert _snapshot(tmp_path) == before
        return
    record, lines = _repair(tmp_path, slides, **kwargs)

    [entry] = record["repaired"]
    assert {k: entry[k] for k in expected} == expected
    assert entry["leaves"][0] == expected_leaf
    assert set(entry["verify"]) <= {"ocr", "corr", "object", "sourceObject", "data", "objectID", "glyph", "twin"}
    assert lines[-1] == "Repaired 1 mis-mapped texture"
    assert pt.json_hits(tmp_path, slides) == []

    uuid = slides[expected["ordinal"] - 1]["exportedUuid"]
    folder = tmp_path / "assets" / uuid
    payload = json.loads((folder / f"{uuid}.json").read_text())
    jsonp = (folder / f"{uuid}.jsonp").read_text()
    assert jsonp == f"local_slide( {json.dumps({'name': uuid, 'json': payload}, separators=(',', ':'))} )"
    actual_leaf = payload["events"]
    for part in expected_leaf.split("/"):
        actual_leaf = actual_leaf[int(part)] if part.isdigit() else actual_leaf[part]
    assert actual_leaf["texture"] == expected["to"]
    pdf = folder / "assets" / f"{uuid}.pdf"
    if expected["rule"] == "D2":
        assert payload["assets"][D2_ID] == {
            "type": "texture", "index": 1, "url": {"native": "assets/S2.pdf"}, "width": 100, "height": 20,
        }
        assert len(PdfReader(str(pdf)).pages) == 2
        assert record["pdfs"] == [
            {"path": "assets/S2/assets/S2.pdf", "sourceSha256": record["pdfs"][0]["sourceSha256"], "sha256": file_sha256(pdf)}
        ]
        assert payload["assets"]["BIG"]["index"] == 0
    else:
        assert record["pdfs"] == []
    if expected["rule"] == "D1g":
        assert payload["assets"] == unchanged_payload
        assert pdf.read_bytes() == unchanged_pdf


def test_refusal_names_every_unrepairable_object_and_writes_nothing(tmp_path):
    # Event 1 swaps the label's text in place under the same bad id: it is its own group, and the
    # event 2 "Point 1" donor must not fix it. The Magic Move lands a contents.to on slide 2's
    # non-poster image: D2 has no source certificate for it, so it is refused. Slide 2 event 1 has movie
    # M1's slot at that image's rect on the same bad id: the image must not borrow M1's poster.
    # Slide 1 MIX: text without accessibility text (event 0) and an ordinary image (event 1) on one
    # bad id at one rect are two objects, each refused. Slide 2 SHARED: a flattened copy between
    # movie M2's slot (event 0) and M3's (event 2) is ambiguous and refused, though D3 fixes both slots.
    point1, point2 = [("Point 1", TEXT_BOX)], [("Point 2", TEXT_BOX)]
    # The three SHARED slots sit at x offsets 0 / 0.4 / 0.8: M3's slot is outside GROUP_TOL of M2's,
    # so the copy's ambiguity must be judged around the copy itself, not around the hit.
    # Slide 2 BIGTAG: D4 finds a same-rect image candidate and a no-contents landing, but their pixels
    # disagree (left half vs top half), so it is refused.
    image, mix, shared = (500, 500, 40, 30), (700, 700, 60, 20), (800, 300, 160, 80)
    tag, landed = (600, 900, 60, 30), (650, 900, 60, 30)

    def nudge(dx: float) -> tuple:
        return (shared[0] + dx, *shared[1:])
    slides = _export(
        tmp_path,
        [
            (
                "S1",
                {
                    "BAD": (400, 300), "GOOD": (100, 20), "IMGBAD": (400, 300), "IMG": (40, 30), "PTO": (200, 100),
                    "MIX": (400, 300), "TAG": (60, 30, "L"),
                },
                [
                    _event([_slot(LABEL, "BAD"), _slot(image, "IMGBAD", kind=5), _slot(mix, "MIX")], texts=point1),
                    _event([_slot(LABEL, "BAD"), _slot(image, "IMG", kind=5), _slot(mix, "MIX", kind=5)], texts=point2),
                    _event(
                        [_slot(LABEL, "GOOD"), _slot(tag, "TAG", kind=5)],
                        [_magic_move((250, 300, 200, 100), "PTO", "PTO", 50), _magic_move(tag, "TAG", None, 50)],
                        texts=point1,
                    ),
                ],
            ),
            (
                "S2",
                {
                    "WRONG": (1920, 1080), "POSTER": (200, 100), "SHARED": (1920, 1080), "P2": (160, 80), "P3": (160, 80),
                    "BIGTAG": (400, 300), "CAND": (60, 30, "T"),
                },
                [
                    _event(
                        [
                            _slot(POSTER, "WRONG", kind=5),
                            _slot(shared, "SHARED", kind=5, oid="M2"),
                            _slot(landed, "BIGTAG", kind=5),
                        ],
                        [
                            _movie("M1", "MOVIE", POSTER, "POSTER"),
                            _movie("M2", "MOVIE", shared, "P2"),
                            _movie("M3", "MOVIE", shared, "P3"),
                        ],
                    ),
                    _event([_slot(POSTER, "WRONG", kind=5, oid="M1"), _flat(nudge(0.4), "SHARED")]),
                    _event([_slot(nudge(0.8), "SHARED", kind=5, oid="M3"), _slot(landed, "CAND", kind=5)]),
                ],
            ),
        ],
    )
    before = _snapshot(tmp_path)
    with pytest.raises(pt.TextureRepairRefused) as raised:
        _repair(tmp_path, slides)
    assert str(raised.value) == (
        "Cannot repair Keynote's HTML export: "
        "slide 1 ('Point 2' label): its texture is mis-mapped and no verified replacement exists; "
        "slide 1 (40×30 image): its texture is mis-mapped and no verified replacement exists; "
        "slide 1 (60×20 image): its texture is mis-mapped and no verified replacement exists; "
        "slide 1 (60×20 text): its texture is mis-mapped and no verified replacement exists; "
        "slide 2 (160×80 image): its texture is mis-mapped and no verified replacement exists; "
        "slide 2 (200×100 image): its texture is mis-mapped and no verified replacement exists; "
        "slide 2 (60×30 image): its texture is mis-mapped and no verified replacement exists"
    )
    assert _snapshot(tmp_path) == before


def test_a_grafted_id_that_already_exists_is_refused(tmp_path):
    built = _d2_slides()
    built[1][1][D2_ID] = (10, 10)
    slides = _export(tmp_path, built)
    with pytest.raises(PreviewError, match=f"grafted id {D2_ID} already exists on slide 2"):
        _repair(tmp_path, slides)


FIXTURES = fixture("alpha-dsk-textures").parent
QUAL = FIXTURES / "qual-decks"
CLEAN_EXPORTS = [
    "minimal-alpha-dsk-17c0c938/html",
    "gl-decks/Minimal Alpha_DSK/html",
    "gl-decks/Positive Control/html",
    "p2-binary/html-unmodified",
    "p2-loop/html-unmodified",
    "p2-loop-grey/html-unmodified",
    "p2-recovery/html-adversarial/html-unmodified",
    "p2-soak-loop/html-unmodified",
    "qual-decks/D1/html-unmodified",
    "qual-decks/D2-across/html-unmodified",
    "qual-decks/D3/html-unmodified",
    "qual-decks/D4/html-unmodified",
    "qual-decks/D5/html-unmodified",
    "qual-decks/D6/html-unmodified",
]


def _header_slides(root: Path) -> list[dict]:
    uuids = json.loads((root / "assets" / "header.json").read_text())["slideList"]
    return [{"originalOrdinal": i + 1, "skipped": False, "exportedUuid": u, "playerIndex": i} for i, u in enumerate(uuids)]


def _copy(source: Path, dest: Path) -> Path:
    """Copy what the repair and the plan read: header, player, slide JSON/JSONP and PDFs."""
    skipped = {".mov", ".mp4", ".m4v", ".jpeg", ".png"}
    shutil.copytree(source, dest, ignore=lambda _d, names: [n for n in names if Path(n).suffix.lower() in skipped])
    return dest


@pytest.mark.parametrize("relative", CLEAN_EXPORTS)
def test_detector_finds_nothing_on_consistent_exports(relative):
    root = FIXTURES / relative
    if not root.is_dir():
        pytest.skip(f"{relative} not available")
    slides = _header_slides(root)
    assert pt._detect(pt._load(root, slides), pt._Renderer()) == []
    record, lines = _repair(root, slides)
    assert record["repaired"] == [] and record["pdfs"] == []
    assert lines == ["Checked textures: none mis-mapped"]


D2_S2 = ("636833147196CC7D947490110BCD3542", "E606C252A387C4E3EAAB06B7C19B5A46")
D2_S5 = ("A8B76C19C45D52867EC4842AA1788B40", "B07083CFFFE18A79AC218F386836B5D9")


@pytest.mark.parametrize(
    "variant, expected",
    [
        ("html-unmodified", {2: D2_S2, 5: D2_S5}),
        ("html-unmodified.across-first-build", {5: D2_S5}),
    ],
)
def test_d2_gate_export_posters_are_repaired_via_d3(tmp_path, variant, expected):
    source = QUAL / "D2" / variant
    if not source.is_dir():
        pytest.skip("qual-decks D2 not available")
    root = _copy(source, tmp_path / "html")
    slides = _header_slides(root)
    record, _ = _repair(root, slides)
    assert {e["ordinal"]: (e["from"], e["to"]) for e in record["repaired"]} == expected
    assert {e["rule"] for e in record["repaired"]} == {"D3"} and record["pdfs"] == []
    assert all(len(e["leaves"]) == 2 for e in record["repaired"])


def test_alpha_export_round_trip_repairs_every_hit_and_keeps_the_plan(tmp_path):
    source = fixture("alpha-dsk-textures")
    if not source.is_dir():
        pytest.skip("alpha-dsk-textures fixture not available")
    root = _copy(source / "html-unmodified", tmp_path / "html")
    manifest = json.loads((source / "manifest.json").read_text())
    slides = manifest["slides"]
    plan_before = derive_plan(root, slides, resolver=lambda r, rel: r / rel)
    loaded = pt._load(root, slides)
    assert sorted((loaded[h.slide].ordinal, h.rule) for h in pt._detect(loaded, pt._Renderer())) == [
        (8, "R1"), (9, "R1"), (9, "R1"), (9, "R1"), (9, "R4"), (9, "R6"), (9, "R6"),
        (10, "R1"), (10, "R1"), (10, "R6"), (10, "R6"),
    ]

    record, lines = _repair(root, slides, player=manifest["playerDigest"])

    summary = [
        (
            e["ordinal"],
            e["rule"],
            e["from"][:6],
            (e["donor"]["page"], e["donor"]["id"][:6]) if e["donor"] else e["to"][:6],
            len(e["leaves"]),
        )
        for e in record["repaired"]
    ]
    assert summary == [
        (8, "D1", "B95077", "67C064", 1),
        (9, "D3", "309718", "CF6BC1", 4),
        (9, "D2", "8194C7", (13, "8194C7"), 3),
        (10, "D2", "C6571B", (19, "1A75DB"), 1),
        (10, "D2", "F89B74", (20, "A0B577"), 1),
    ]
    assert [e["verify"] for e in record["repaired"]] == [
        {"ocr": "Sunday Service"},
        {"corr": 1.0},
        {"ocr": "Sunday Service"},
        {"ocr": "Children's Church"},
        {"ocr": "Sunday Service"},
    ]
    assert [p["path"].split("/")[1] for p in record["pdfs"]] == [
        "D4A1DF22-D248-4A45-8125-8C2288F5AB11", "DAC21D01-4C0B-4292-A009-8B511D36F68D",
    ]
    assert lines[-1] == "Repaired 5 mis-mapped textures"
    plan_after = derive_plan(root, slides, resolver=lambda r, rel: r / rel)

    def normalise_feed_sizes(plan):
        def normalise_movie(movie):
            if movie.feed is None:
                return movie
            feed = {
                **movie.feed,
                "from": {**movie.feed["from"], "size": None},
                "to": {**movie.feed["to"], "size": None} if movie.feed["to"] is not None else None,
            }
            return replace(movie, feed=feed)

        return replace(
            plan,
            boundaries=tuple(
                replace(boundary, movies=tuple(normalise_movie(movie) for movie in boundary.movies))
                for boundary in plan.boundaries
            ),
        )

    assert normalise_feed_sizes(plan_after) == normalise_feed_sizes(plan_before)

    def feed_entries(plan):
        return {
            (boundary.from_player_index, movie.src_object_id): movie.feed
            for boundary in plan.boundaries
            for movie in boundary.movies
            if movie.feed is not None
        }

    before_feeds = feed_entries(plan_before)
    after_feeds = feed_entries(plan_after)

    def ordinals(feed):
        return (
            feed["draw"],
            feed["drawCount"],
            feed["from"]["upload"],
            feed["to"]["upload"] if feed["to"] is not None else None,
        )

    assert {key: ordinals(feed) for key, feed in after_feeds.items()} == {
        key: ordinals(feed) for key, feed in before_feeds.items()
    }

    slides_by_player = {slide["playerIndex"]: slide for slide in slides if not slide["skipped"]}
    for (from_player, _object_id), feed in after_feeds.items():
        slide = slides_by_player[from_player]
        payload = json.loads((root / slide["assetPaths"]["payload"]).read_text())
        transition = lc._boundary_transition(payload["events"], slide["exportedUuid"])
        rows, _ = lc._feed_table(transition, payload["assets"], slide["exportedUuid"])
        row = next(row for row in rows if row["draw"] == feed["draw"])

        def json_size(texture):
            asset = payload["assets"][texture]
            return [asset["width"], asset["height"]]

        assert feed["from"]["size"] == json_size(row["from"]["texture"])
        if feed["to"] is not None:
            assert row["to"] is not None
            assert feed["to"]["size"] == json_size(row["to"]["texture"])
        else:
            assert row["to"] is None
    assert pt._detect(pt._load(root, slides), pt._Renderer()) == []
    assert _repair(root, slides, player=manifest["playerDigest"])[0]["repaired"] == []
