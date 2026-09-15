"""Offline write of the DSK "template style" milestone's stylesheet patch, plan
`dsk_template_style.plan.md` sections 1.4/2.2 -- Mechanism D.

Targets, in ``Index/DocumentStylesheet.iwa`` only: every paragraph style archive whose
``charProperties`` say ``fontName == AzoSans-Bold``, ``capitalization == kAllCaps`` and
``fontColor`` == DSK cyan is a badge candidate. A candidate at a verse-badge font size
(40/60 pt, plan section 1.4) is whitened AND cleared to ``kNoCaps``; any other matching
candidate is the point-column reference badge (plan Q2) and gets ONLY its capitalization
cleared -- its cyan is left untouched, never whitened. The named
``TSWP.CharacterStyleArchive`` "SuperScript" (the verse-number style) is recoloured gold
yellow.

Dual-field write: Keynote treats ``charProperties.tsdFill.color`` as authoritative and
resyncs ``fontColor`` from it on save (plan "Probe results", p2 round 1 vs round 2) -- a
fontColor-only write reverts silently. Every colour edit here writes both fields, and
refuses outright if a target archive has no ``tsdFill`` to write into: a silent partial
colour write is exactly the probe's round-1 failure mode.
"""
from __future__ import annotations

import copy
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from keynote_parser.codec import IWAFile

from obed_edom.iwa_runs import UndecodableIWAMember, _load_deck, _load_deck_full, resolve_style
from obed_edom.iwa_write import OfflineWriteCorrupted, _rewrite_members

_STYLESHEET_MEMBER = "Index/DocumentStylesheet.iwa"
_PARA_PBTYPE = "TSWP.ParagraphStyleArchive"
_CHAR_PBTYPE = "TSWP.CharacterStyleArchive"
_BADGE_FONT = "AzoSans-Bold"
_ALL_CAPS = "kAllCaps"
_NO_CAPS = "kNoCaps"
_SUPERSCRIPT_NAME = "SuperScript"
_COLOR_TOL = 0.02
_SIZE_TOL = 0.05

# Plan section 1.2 measurement: DSK cyan, and the gold "Yellow Bold" (2651127) float
# triple the plan pins bit-for-bit for the verse-number recolour.
CYAN = (0.0, 0.9914394, 1.0)
WHITE = (1.0, 1.0, 1.0)
GOLD_YELLOW = (0.99942404, 0.9855537, 0.0)

# Plan section 1.4, r13 measurement: verse-badge paragraph styles sit at 40.0/60.0 pt.
# The point-column badge sizes measured on the same deck (52.66/64.0) are deliberately
# excluded -- any kAllCaps/cyan/AzoSans-Bold candidate at a size outside this set is
# treated as the point-column badge (plan Q2), never whitened.
_VERSE_BADGE_SIZES = (40.0, 60.0)


@dataclass(frozen=True)
class StyleSpec:
    badge_color: tuple[float, float, float] = WHITE
    badge_caps: str = _NO_CAPS
    verse_number_color: tuple[float, float, float] = GOLD_YELLOW


DEFAULT_DSK_STYLE = StyleSpec()


@dataclass
class StyleResult:
    applied: int = 0
    members: list[str] = field(default_factory=list)
    edited_ids: dict[str, str] = field(default_factory=dict)  # id -> role
    skipped_reason: dict[str, str] = field(default_factory=dict)  # id -> why untouched


class OfflineWriteRefused(Exception):
    """A precondition of ``write_styles`` failed; the source deck and ``out_path`` are untouched."""


def _is_color(value: object, target: tuple[float, float, float]) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        return all(abs(float(value.get(k, 0.0)) - t) < _COLOR_TOL for k, t in zip("rgb", target))
    except (TypeError, ValueError):
        return False


def _is_verse_badge_size(size: object) -> bool:
    try:
        size = float(size)
    except (TypeError, ValueError):
        return False
    return any(abs(size - s) < _SIZE_TOL for s in _VERSE_BADGE_SIZES)


def _color_dict(rgb: tuple[float, float, float]) -> dict:
    r, g, b = rgb
    return {"model": "rgb", "r": float(r), "g": float(g), "b": float(b), "a": 1.0, "rgbspace": "srgb"}


def _classify(
    objects: dict[str, dict], id_to_file: dict[str, str]
) -> tuple[dict[str, float], dict[str, float], str | None]:
    """(verse_badge_ids -> fontSize, point_column_ids -> fontSize, superscript_id).

    ``superscript_id`` is ``None`` if the named style is absent or ambiguous (more than
    one archive named "SuperScript" in the stylesheet) -- never guessed.
    """
    verse_badges: dict[str, float] = {}
    point_column: dict[str, float] = {}
    superscript_id: str | None = None
    superscript_hits = 0
    for ident, obj in objects.items():
        if id_to_file.get(ident) != _STYLESHEET_MEMBER:
            continue
        pbtype = obj.get("_pbtype")
        cp = obj.get("charProperties") or {}
        if (
            pbtype == _PARA_PBTYPE
            and cp.get("fontName") == _BADGE_FONT
            and cp.get("capitalization") == _ALL_CAPS
            and _is_color(cp.get("fontColor"), CYAN)
        ):
            size = cp.get("fontSize")
            if _is_verse_badge_size(size):
                verse_badges[ident] = size
            else:
                point_column[ident] = size
        elif pbtype == _CHAR_PBTYPE and (obj.get("super") or {}).get("name") == _SUPERSCRIPT_NAME:
            superscript_hits += 1
            superscript_id = ident
    if superscript_hits > 1:
        superscript_id = None
    return verse_badges, point_column, superscript_id


def write_styles(
    key_path: str | Path, *, out_path: str | Path, spec: StyleSpec = DEFAULT_DSK_STYLE,
) -> StyleResult:
    key_path, out_path = Path(key_path), Path(out_path)

    try:
        objects, id_to_file, _file_ids, _hor = _load_deck_full(key_path, strict=True)
    except UndecodableIWAMember as exc:
        raise OfflineWriteRefused(f"member {exc} is undecodable") from exc

    verse_badges, point_column, superscript_id = _classify(objects, id_to_file)
    if not verse_badges:
        raise OfflineWriteRefused(
            "zero verse-badge styles matched (AzoSans-Bold + kAllCaps + cyan at "
            f"{_VERSE_BADGE_SIZES} pt) in {_STYLESHEET_MEMBER}"
        )

    with zipfile.ZipFile(key_path) as zf:
        if _STYLESHEET_MEMBER not in set(zf.namelist()):
            raise OfflineWriteRefused(f"member {_STYLESHEET_MEMBER} missing from deck")
        buf = zf.read(_STYLESHEET_MEMBER)

    decoded = IWAFile.from_buffer(buf, _STYLESHEET_MEMBER).to_dict()
    patched = copy.deepcopy(decoded)

    edits: dict[str, dict] = {}
    for ident in verse_badges:
        edits[ident] = {"role": "verse_badge", "fontColor": spec.badge_color, "capitalization": spec.badge_caps}
    for ident in point_column:
        edits[ident] = {"role": "point_column_badge", "capitalization": spec.badge_caps}
    if superscript_id is not None:
        edits[superscript_id] = {"role": "superscript", "fontColor": spec.verse_number_color}

    result = StyleResult()
    applied = 0
    for ch in patched["chunks"]:
        for arch in ch["archives"]:
            aid = str(arch["header"]["identifier"])
            if aid not in edits:
                continue
            objs = arch.get("objects") or []
            if not objs:
                continue
            edit = edits[aid]
            for o in objs:
                cp = o.setdefault("charProperties", {})
                if "fontColor" in edit:
                    if not isinstance(cp.get("tsdFill"), dict):
                        raise OfflineWriteRefused(
                            f"style {aid} ({edit['role']}) has no charProperties.tsdFill -- a "
                            "fontColor-only write would silently revert on save (dual-field rule)"
                        )
                    cp["fontColor"] = _color_dict(edit["fontColor"])
                    cp["tsdFill"]["color"] = dict(cp["fontColor"])
                if "capitalization" in edit:
                    cp["capitalization"] = edit["capitalization"]
                break
            result.edited_ids[aid] = edit["role"]
            applied += 1

    if applied != len(edits):
        raise OfflineWriteRefused(f"only {applied}/{len(edits)} target styles matched an archive")

    new_member = IWAFile.from_dict(copy.deepcopy(patched)).to_buffer()
    try:
        IWAFile.from_buffer(new_member, _STYLESHEET_MEMBER)  # round-trip self-check
    except Exception as exc:  # noqa: BLE001 -- any re-encode failure refuses, source untouched
        raise OfflineWriteRefused(f"member {_STYLESHEET_MEMBER} failed to re-encode/reparse: {exc}") from exc

    shutil.copy2(key_path, out_path)
    try:
        _rewrite_members(out_path, {_STYLESHEET_MEMBER: new_member})
    except OfflineWriteCorrupted:
        raise
    except Exception as exc:  # noqa: BLE001 -- rewrite failure refuses; out_path is a copy, source untouched
        raise OfflineWriteRefused(f"rewrite failed: {exc}") from exc

    result.members = [_STYLESHEET_MEMBER]
    result.applied = applied
    _verify(out_path, spec, verse_badges, point_column, superscript_id)
    return result


def _verify(
    out_path: Path,
    spec: StyleSpec,
    verse_badges: dict[str, float],
    point_column: dict[str, float],
    superscript_id: str | None,
) -> None:
    """Read back through ``resolve_style`` (which now prefers ``tsdFill.color`` over
    ``fontColor``, matching what Keynote itself resyncs on save) and assert every
    targeted style resolved to the intended colour/caps, and every point-column style
    kept its cyan.
    """
    objects, _id_to_file, _file_ids = _load_deck(out_path)
    cache: dict = {}
    for ident in verse_badges:
        resolved = resolve_style(ident, objects, cache)
        if resolved["color"] != list(round(c * 255) for c in spec.badge_color):
            raise OfflineWriteRefused(f"re-read verse badge {ident} colour {resolved['color']} != white")
        if resolved["capitalization"] != spec.badge_caps:
            raise OfflineWriteRefused(
                f"re-read verse badge {ident} capitalization {resolved['capitalization']!r} != {spec.badge_caps!r}"
            )
    for ident in point_column:
        resolved = resolve_style(ident, objects, cache)
        if resolved["capitalization"] != spec.badge_caps:
            raise OfflineWriteRefused(
                f"re-read point-column badge {ident} capitalization {resolved['capitalization']!r} "
                f"!= {spec.badge_caps!r}"
            )
        if not _is_color({"r": resolved["color"][0] / 255.0, "g": resolved["color"][1] / 255.0,
                          "b": resolved["color"][2] / 255.0}, CYAN):
            raise OfflineWriteRefused(f"re-read point-column badge {ident} colour {resolved['color']} != cyan")
    if superscript_id is not None:
        resolved = resolve_style(superscript_id, objects, cache)
        expected = [round(c * 255) for c in spec.verse_number_color]
        if resolved["color"] != expected:
            raise OfflineWriteRefused(
                f"re-read SuperScript {superscript_id} colour {resolved['color']} != {expected}"
            )
