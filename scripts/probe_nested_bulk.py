#!/usr/bin/env python3
"""Probe: can ONE nested AppleScript read (``<prop> of every <kind> of every slide of
document 1``) replace the current per-slide bulk geometry loop (``r-nested-bulk-probe``
precursor)?

Six questions, each a criterion below: (1) does the outer list length equal the slide
count, skipped slides in position, AND does the script's own ``_meta`` slide count agree
with ``bulk_geometry``'s; (2) does inner order match per-slide order, values identical
to ``bulk_geometry.js``; (3) does an empty collection read back as ``[]`` (not merely
absent) — needs at least one CONFIRMED empty (slide, kind) pair, zero omissions; (4) do
text placeholders land at the end of a slide's sublist (slack, not a hard mismatch); (5)
is a nested read materially faster than the existing per-slide loop, using the WARM
(second) bulk timing; (6) does a failing element abort the WHOLE nested read
(``whole_event_raise``), silently drop it from its slide's sublist (``silent_partial``),
or complete with a harmless substituted value (``substituted_value``) — "unknown" (FAIL)
unless the failure probe first confirms a genuine zero-character text item exists. The
pure half (shape/compare/criteria/recommend) needs no Keynote; ``--prep``/``--live``
drive an APFS clone of a real deck through Keynote to answer all six.

``osascript`` flattens a returned AppleScript list into text, losing slide boundaries —
every read here is serialized to JSON *inside* the script (``obedSer``) and returned as
a single string, never as a raw list.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

from obed_edom import keynote_app

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "nested-bulk-probe"

KINDS = (("text item", "text"), ("image", "image"), ("movie", "movie"), ("group", "group"))
PROPS = ("position", "width", "height")


# ==========================================================================
# AppleScript text builders (no Keynote touched by calling these).
# ==========================================================================
def _keynote_tell() -> str:
    return f'tell application id "{keynote_app.bundle_id()}"'


def _keynote_terms() -> str:
    return f'using terms from application id "{keynote_app.bundle_id()}"'


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _as_str_lit(text: str) -> str:
    return '"' + _as_escape(text) + '"'


def _json_str_expr(text: str) -> str:
    """AS expression whose VALUE is a JSON-quoted string, e.g. ``"text"`` incl. quotes."""
    return _as_str_lit('"' + text + '"')


def _json_field(key: str, value_expr: str) -> str:
    return _as_str_lit('"' + key + '":') + f" & ({value_expr})"


def _json_object(pairs: list[tuple[str, str]]) -> str:
    joined = f' & {_as_str_lit(",")} & '.join(_json_field(k, v) for k, v in pairs)
    return f"{_as_str_lit('{')} & {joined} & {_as_str_lit('}')}"


def _bind_lines(deck: Path, doc_name: str) -> list[str]:
    """Close-by-name (ext + stem) -> open -> ``document 1`` -> verify name (probe_zorder_patch
    ``verify_applescript``, keynote.py's close-by-name -> open -> ``document 1`` bind)."""
    key = _as_escape(str(Path(deck).resolve()))
    stem = Path(doc_name).stem
    return [
        "  try",
        f'    close (every document whose name is "{doc_name}" or name is "{stem}") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{key}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        f'  if name of theDoc does not start with "{stem}" then error '
        '"bound wrong document: " & (name of theDoc)',
    ]


def _close_lines() -> list[str]:
    """A failed close must not discard an already-completed read (keynote.py's
    ``save theDoc`` / ``close theDoc`` try-wrap, e.g. :1212-1229)."""
    return ["  try", "    close theDoc saving no", "  end try"]


_OBED_SER_LINES = [
    "on obedSer(v)",
    "  if class of v is list then",
    '    set outStr to "["',
    "    set n to count of v",
    "    repeat with i from 1 to n",
    "      set outStr to outStr & (my obedSer(item i of v))",
    '      if i < n then set outStr to outStr & ","',
    "    end repeat",
    '    return outStr & "]"',
    "  else if v is missing value then",
    '    return "null"',
    "  else if class of v is integer or class of v is real then",
    "    return (v as string)",
    "  else",
    "    return " + _as_str_lit('"') + ' & (my obedEscape(v as string)) & ' + _as_str_lit('"'),
    "  end if",
    "end obedSer",
]

# keynote.py's obedReplace (`_sig_handlers`): split on findStr, rejoin on replStr.
_OBED_REPLACE_LINES = [
    "on obedReplace(t, findStr, replStr)",
    "  set od to AppleScript's text item delimiters",
    "  set AppleScript's text item delimiters to findStr",
    "  set _parts to text items of t",
    "  set AppleScript's text item delimiters to replStr",
    "  set t to _parts as text",
    "  set AppleScript's text item delimiters to od",
    "  return t",
    "end obedReplace",
]

# Backslash FIRST, or a literal backslash already in the text would be re-escaped by the
# quote/newline/tab passes that follow it. CRLF must be replaced as a pair BEFORE the
# standalone CR/LF passes, or it would become two escapes ("\\r\\n" -> "\\r" & "\\n"
# doubled into "\\r\\r\\n" style breakage); CR alone maps to "\\r", not "\\n".
_OBED_ESCAPE_LINES = [
    "on obedEscape(t)",
    f"  set t to my obedReplace(t, {_as_str_lit(chr(92))}, {_as_str_lit(chr(92) * 2)})",
    f"  set t to my obedReplace(t, {_as_str_lit(chr(34))}, {_as_str_lit(chr(92) + chr(34))})",
    f"  set t to my obedReplace(t, (return & linefeed), "
    f"{_as_str_lit(chr(92) + 'r' + chr(92) + 'n')})",
    f"  set t to my obedReplace(t, return, {_as_str_lit(chr(92) + 'r')})",
    f"  set t to my obedReplace(t, linefeed, {_as_str_lit(chr(92) + 'n')})",
    f"  set t to my obedReplace(t, tab, {_as_str_lit(chr(92) + 't')})",
    "  return t",
    "end obedEscape",
]

_OBED_HELPER_LINES = _OBED_SER_LINES + _OBED_REPLACE_LINES + _OBED_ESCAPE_LINES


def build_open_close_applescript(deck: Path) -> str:
    """Bind and close only — no reads — so ``--live``'s timing can separate Keynote's
    open/close cost from a read's own cost."""
    doc_name = Path(deck).name
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        *_bind_lines(deck, doc_name),
        *_close_lines(),
        '  return "ok"',
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def build_all_reads_applescript(deck: Path) -> str:
    doc_name = Path(deck).name
    lines = list(_OBED_HELPER_LINES)
    lines += [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        *_bind_lines(deck, doc_name),
        "  set entries to {}",
        "  set t0 to current date",
        "  set slideCount to count of slides of theDoc",
        "  set t1 to current date",
        "  set end of entries to " + _json_object([
            ("kind", _json_str_expr("_meta")),
            ("prop", _json_str_expr("slideCount")),
            ("seconds", "(t1 - t0) as string"),
            ("value", "slideCount as string"),
        ]),
    ]
    for as_kind, py_kind in KINDS:
        for prop in PROPS:
            lines += [
                "  set t0 to current date",
                f"  set v to {prop} of every {as_kind} of every slide of theDoc",
                "  set t1 to current date",
                "  set end of entries to " + _json_object([
                    ("kind", _json_str_expr(py_kind)),
                    ("prop", _json_str_expr(prop)),
                    ("seconds", "(t1 - t0) as string"),
                    ("value", "my obedSer(v)"),
                ]),
            ]
    lines += [
        '  set AppleScript\'s text item delimiters to ","',
        "  set joined to entries as string",
        '  set AppleScript\'s text item delimiters to ""',
        *_close_lines(),
        '  return "[" & joined & "]"',
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


# ``char_counts`` runs FIRST: it confirms the probe's premise (a genuine zero-character
# text item exists on the deck) before ``primary`` tries to trip on it. The scoped
# fallback (a single known item, inserted at index 1 by ``build_failure_probe_applescript``)
# answers the same premise when the whole-deck nested form is itself indeterminate.
_FAILURE_PROBES = (
    ("char_counts", "count of characters of object text of every text item of every slide of theDoc"),
    ("primary", "size of character 1 of object text of every text item of every slide of theDoc"),
    ("images_filename", "file name of every image of every slide of theDoc"),
    ("movies_objecttext", "object text of every movie of every slide of theDoc"),
)


def build_failure_probe_applescript(deck: Path, *, empty_text_slide: int) -> str:
    """Each probe wrapped in its own ``try``: does a per-element failure (the empty text
    box ``build_clone_prep_applescript`` adds has no character 1) abort the WHOLE nested
    read, or does the read complete with a substituted/partial value? ``char_counts_scoped``
    reads only ``text item 1 of slide empty_text_slide`` — the one item known by
    construction to be empty — as a fallback premise check when the whole-deck
    ``char_counts`` form can't answer."""
    doc_name = Path(deck).name
    probes = list(_FAILURE_PROBES)
    probes.insert(1, (
        "char_counts_scoped",
        f"count of characters of object text of text item 1 of slide {empty_text_slide} of theDoc",
    ))
    lines = list(_OBED_HELPER_LINES)
    lines += [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        *_bind_lines(deck, doc_name),
        "  set results to {}",
    ]
    for name, expr in probes:
        success = _json_object([
            ("name", _json_str_expr(name)),
            ("raised", _as_str_lit("false")),
            ("value", "my obedSer(v)"),
        ])
        failure = _json_object([
            ("name", _json_str_expr(name)),
            ("raised", _as_str_lit("true")),
            ("errNum", "errNum as string"),
            ("errMsg", "my obedSer(errMsg as string)"),
        ])
        lines += [
            "  try",
            f"    set v to {expr}",
            f"    set end of results to {success}",
            "  on error errMsg number errNum",
            f"    set end of results to {failure}",
            "  end try",
        ]
    lines += [
        '  set AppleScript\'s text item delimiters to ","',
        "  set joined to results as string",
        '  set AppleScript\'s text item delimiters to ""',
        *_close_lines(),
        '  return "[" & joined & "]"',
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def build_clone_prep_applescript(
    deck: Path, *, lock_image_slide: int, lock_text_slide: int, empty_text_slide: int
) -> str:
    """Lock one image + one text item, add ONE empty text box, save, close — all on
    ``deck`` (must already be a clone; never the user's source). Slide 1 is never a
    valid target here: it must stay the deck's zero-item baseline for criterion 3.
    Each step is individually guarded; the returned ``locked=N emptyBoxes=M`` report
    lets ``main`` verify both locks actually took before trusting ``--live``."""
    doc_name = Path(deck).name
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        *_bind_lines(deck, doc_name),
        "  set lockedCount to 0",
        "  set emptyBoxCount to 0",
        "  try",
        f"    set locked of image 1 of slide {lock_image_slide} of theDoc to true",
        "    set lockedCount to lockedCount + 1",
        "  end try",
        "  try",
        f"    set locked of text item 1 of slide {lock_text_slide} of theDoc to true",
        "    set lockedCount to lockedCount + 1",
        "  end try",
        "  try",
        f"    tell slide {empty_text_slide} of theDoc to make new text item with properties "
        '{position:{10, 10}, width:100, height:50, object text:""}',
        "    set emptyBoxCount to emptyBoxCount + 1",
        "  end try",
        "  try",
        "    save theDoc",
        "  end try",
        *_close_lines(),
        '  return "locked=" & lockedCount & " emptyBoxes=" & emptyBoxCount',
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def build_jxa_nested_read(deck: Path) -> str:
    """JXA's cross-slide bulk specifier, ``doc.slides.<collection>.<prop>()`` — no
    per-slide nesting guarantee, unlike the AppleScript ``of every slide`` glob; a
    secondary (``--with-jxa``) comparison point, not the primary probe."""
    key = json.dumps(str(Path(deck).resolve()))
    collections = (("textItems", "text"), ("images", "image"), ("movies", "movie"), ("groups", "group"))
    lines = [
        f'const Keynote = Application("{keynote_app.bundle_id()}");',
        "Keynote.includeStandardAdditions = true;",
        f"const doc = Keynote.open(Path({key}));",
        "const out = {};",
    ]
    for name, kind in collections:
        for prop in PROPS:
            lines.append(
                f'try {{ out["{kind}_{prop}"] = doc.slides.{name}.{prop}(); }} '
                f'catch (e) {{ out["{kind}_{prop}_error"] = String(e); }}'
            )
    lines += [
        'try { Keynote.close(doc, { saving: "no" }); } catch (e) {}',
        "JSON.stringify(out);",
    ]
    return "\n".join(lines)


# ==========================================================================
# Pure.
# ==========================================================================
def parse_nested(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"parse_nested: invalid JSON, raw[:200]={text[:200]!r}")
        raise


_PREP_REPORT_RE = re.compile(r"locked=(\d+)\s+emptyBoxes=(\d+)")


def parse_prep_report(text: str) -> dict[str, int]:
    match = _PREP_REPORT_RE.search(text or "")
    if not match:
        raise ValueError(f"unparseable prep report: {text!r}")
    return {"locked": int(match.group(1)), "emptyBoxes": int(match.group(2))}


def nested_to_bulk_shape(
    by_kind: dict[str, dict[str, list]], slide_count: int
) -> tuple[dict[int, dict[str, list[list[float]]]], list[dict]]:
    """``{kind: {"position"|"width"|"height": [per-slide lists]}}`` -> the
    ``bulk_geometry.js`` contract, ``{0-based slide: {kind: [[x, y, w, h], ...]}}``, plus
    a shape-error log. Never substitutes and never raises: a ``position``/``width``/
    ``height`` value that isn't even a list — the whole-deck AppleScript collapse seen
    live on ``char_counts`` can happen to any nested read — is ``outer_shape``; a proper
    list shorter than ``slide_count`` is ``outer_length``; a slide whose width/height
    sublist isn't a list (flattened), or whose length disagrees with its position
    sublist, or a position entry that isn't a 2-element ``[x, y]``, is ``inner_shape`` /
    ``inner_length`` / ``inner_shape``. Every case is logged and that (slide, kind)
    OMITTED from ``shaped`` rather than zero-padded or unpacked blind — padding would
    let a broken read masquerade as a genuine empty collection."""
    shaped: dict[int, dict[str, list[list[float]]]] = {i: {} for i in range(slide_count)}
    shape_errors: list[dict] = []
    for kind, props in by_kind.items():
        raw_positions, raw_widths, raw_heights = props.get("position"), props.get("width"), props.get("height")
        for prop, values in (("position", raw_positions), ("width", raw_widths), ("height", raw_heights)):
            if not isinstance(values, list):
                shape_errors.append({
                    "kind": kind, "prop": prop, "reason": "outer_shape",
                    "type": type(values).__name__,
                })
            elif len(values) != slide_count:
                shape_errors.append({
                    "kind": kind, "prop": prop, "reason": "outer_length",
                    "len": len(values), "slide_count": slide_count,
                })
        positions = raw_positions if isinstance(raw_positions, list) else []
        widths = raw_widths if isinstance(raw_widths, list) else []
        heights = raw_heights if isinstance(raw_heights, list) else []
        n = min(len(positions), len(widths), len(heights), slide_count)
        for i in range(n):
            pos_slide, w_slide, h_slide = positions[i], widths[i], heights[i]
            if not (isinstance(pos_slide, list) and isinstance(w_slide, list) and isinstance(h_slide, list)):
                shape_errors.append({
                    "kind": kind, "slide": i, "reason": "inner_shape",
                    "position": pos_slide, "width": w_slide, "height": h_slide,
                })
                continue
            if len(w_slide) != len(pos_slide) or len(h_slide) != len(pos_slide):
                shape_errors.append({
                    "kind": kind, "slide": i, "reason": "inner_length",
                    "position_len": len(pos_slide), "width_len": len(w_slide), "height_len": len(h_slide),
                })
                continue
            rows: list[list[float]] = []
            malformed = False
            for j, xy in enumerate(pos_slide):
                if not isinstance(xy, list) or len(xy) != 2:
                    shape_errors.append({
                        "kind": kind, "slide": i, "index": j, "reason": "inner_shape", "value": xy,
                    })
                    malformed = True
                    continue
                try:
                    row = [float(xy[0]), float(xy[1]), float(w_slide[j]), float(h_slide[j])]
                except (TypeError, ValueError):
                    shape_errors.append({
                        "kind": kind, "slide": i, "index": j, "reason": "inner_shape",
                        "value": xy, "width": w_slide[j], "height": h_slide[j],
                    })
                    malformed = True
                    continue
                rows.append(row)
            if malformed:
                continue
            shaped[i][kind] = rows
    return shaped, shape_errors


def compare_to_bulk(
    shaped: dict[int, dict[str, list[list[float]]]],
    bulk: dict[int, dict[str, list[list[float]]]],
    *,
    text_slack: int = 2,
) -> dict:
    """``text`` sublists may carry up to ``text_slack`` extra trailing rows (placeholders);
    every other kind must match length and value exactly. A ``(slide, kind)`` missing
    from ``shaped`` (never computed, e.g. a shape error) is an "omitted" mismatch, kept
    distinct from a genuine empty ``[]`` read — ``empty_confirmations`` counts only the
    latter."""
    slide_mismatches: list[int] = []
    kind_mismatches: list[dict] = []
    empty_confirmations = 0
    for idx in sorted(bulk):
        shaped_slide = shaped.get(idx)
        if shaped_slide is None:
            slide_mismatches.append(idx)
            continue
        for kind, bulk_rows in bulk[idx].items():
            if kind not in shaped_slide:
                kind_mismatches.append({"slide": idx, "kind": kind, "reason": "omitted"})
                continue
            shaped_rows = shaped_slide[kind]
            if kind == "text":
                extra = len(shaped_rows) - len(bulk_rows)
                if extra < 0 or extra > text_slack:
                    kind_mismatches.append({
                        "slide": idx, "kind": kind, "reason": "length",
                        "shaped_len": len(shaped_rows), "bulk_len": len(bulk_rows),
                    })
                    continue
                compare_rows = shaped_rows[: len(bulk_rows)]
            else:
                if len(shaped_rows) != len(bulk_rows):
                    kind_mismatches.append({
                        "slide": idx, "kind": kind, "reason": "length",
                        "shaped_len": len(shaped_rows), "bulk_len": len(bulk_rows),
                    })
                    continue
                compare_rows = shaped_rows
            if not bulk_rows and not shaped_rows:
                empty_confirmations += 1
            for j, (s_row, b_row) in enumerate(zip(compare_rows, bulk_rows)):
                if list(s_row) != list(b_row):
                    kind_mismatches.append({
                        "slide": idx, "kind": kind, "index": j, "reason": "value",
                        "shaped": s_row, "bulk": b_row,
                    })
    outer_length_match = len(shaped) == len(bulk)
    return {
        "outer_length_match": outer_length_match,
        "slide_mismatches": slide_mismatches,
        "kind_mismatches": kind_mismatches,
        "empty_confirmations": empty_confirmations,
        "pass": outer_length_match and not slide_mismatches and not kind_mismatches,
    }


def zero_char_text_item_count(entry: dict | None) -> tuple[int | None, str]:
    """``(count, reason)`` from the whole-deck ``char_counts`` failure-probe entry:
    ``count`` is how many (slide, text item) pairs read back a 0-character ``object
    text``, or ``None`` when the probe itself couldn't answer — each such case (absent,
    raised, no value, not nested per slide) gets its own reason, kept distinct from a
    probe that answered but simply found nothing (``count == 0``)."""
    if not entry:
        return None, "char_counts probe absent"
    if entry.get("raised"):
        return None, f"char_counts probe raised (errNum={entry.get('errNum')})"
    if "value" not in entry:
        return None, "char_counts probe neither raised nor carried a value"
    value = entry["value"]
    if not isinstance(value, list) or not all(isinstance(slide, list) for slide in value):
        return None, f"char_counts not nested per slide (got {type(value).__name__})"
    count = sum(1 for slide in value for c in slide if c == 0)
    if count < 1:
        return 0, "no zero-character text item confirmed"
    return count, "confirmed by char_counts"


def scoped_zero_char_confirmed(entry: dict | None) -> bool:
    """Does the scoped ``char_counts_scoped`` fallback (a single known text item) confirm
    a zero-character text item, when the whole-deck form was indeterminate?"""
    return bool(entry) and not entry.get("raised") and entry.get("value") == 0


def resolve_zero_char_premise(
    char_counts: dict | None, char_counts_scoped: dict | None
) -> tuple[int, str]:
    """Try the whole-deck probe first; fall back to the scoped one when it can't answer.
    The reason string always names which form answered (or why neither did)."""
    count, reason = zero_char_text_item_count(char_counts)
    if count and count >= 1:
        return count, reason
    if scoped_zero_char_confirmed(char_counts_scoped):
        return 1, "confirmed by char_counts_scoped"
    return count or 0, reason


def _classify_failure_mode(
    primary: dict, bulk_text_counts: dict[int, int], zero_char_items: int, zero_char_reason: str
) -> tuple[str, dict]:
    if zero_char_items < 1:
        return "unknown", {"reason": zero_char_reason}
    if not primary or "raised" not in primary:
        return "unknown", {"reason": "primary probe absent"}
    if primary["raised"]:
        return "whole_event_raise", {}
    if "value" not in primary:
        return "unknown", {"reason": "primary probe neither raised nor carried a value"}
    value = primary["value"]
    if not isinstance(value, list):
        return "unknown", {"reason": f"primary probe value not nested per slide (got {type(value).__name__})"}
    short_slides = []
    for idx, count in bulk_text_counts.items():
        slide_value = value[idx] if idx < len(value) else None
        if slide_value is None or not isinstance(slide_value, list) or len(slide_value) < count:
            short_slides.append(idx)
    if short_slides:
        return "silent_partial", {"short_slides": short_slides}
    return "substituted_value", {}


def evaluate_criteria(
    compare: dict,
    timings: dict,
    failure: dict,
    slide_count: int,
    *,
    shape_errors: list[dict],
    meta_slide_count: int | None,
    bulk_text_counts: dict[int, int],
    zero_char_items: int,
    zero_char_reason: str,
) -> dict[str, dict]:
    kind_mismatches = compare.get("kind_mismatches", [])
    value_mismatches = [m for m in kind_mismatches if m.get("reason") == "value"]
    length_mismatches = [
        m for m in kind_mismatches if m.get("reason") == "length" and m.get("kind") != "text"
    ]
    text_length_mismatches = [
        m for m in kind_mismatches if m.get("reason") == "length" and m.get("kind") == "text"
    ]
    omissions = [m for m in kind_mismatches if m.get("reason") == "omitted"]
    outer_shape_errors = [e for e in shape_errors if e.get("reason") == "outer_shape"]
    outer_length_errors = [e for e in shape_errors if e.get("reason") == "outer_length"]
    inner_length_errors = [e for e in shape_errors if e.get("reason") == "inner_length"]
    inner_shape_errors = [e for e in shape_errors if e.get("reason") == "inner_shape"]

    meta_ok = meta_slide_count == slide_count

    bulk_seconds = timings.get("bulk_seconds_warm")
    nested_seconds = timings.get("nested_seconds")
    speedup = (bulk_seconds / nested_seconds) if bulk_seconds and nested_seconds else 0.0

    primary = (failure or {}).get("primary") or {}
    mode, mode_detail = _classify_failure_mode(primary, bulk_text_counts, zero_char_items, zero_char_reason)

    return {
        "1": {
            "pass": (
                not outer_shape_errors and not outer_length_errors
                and meta_ok and not compare.get("slide_mismatches")
            ),
            "detail": {
                "slide_count": slide_count, "meta_slide_count": meta_slide_count,
                "outer_shape_errors": outer_shape_errors, "outer_length_errors": outer_length_errors,
                "slide_mismatches": compare.get("slide_mismatches", []),
            },
        },
        "2": {
            "pass": (
                not value_mismatches and not length_mismatches
                and not inner_length_errors and not inner_shape_errors
            ),
            "detail": {
                "value_mismatches": len(value_mismatches),
                "length_mismatches": len(length_mismatches),
                "inner_length_errors": len(inner_length_errors),
                "inner_shape_errors": len(inner_shape_errors),
            },
        },
        "3": {
            "pass": compare.get("empty_confirmations", 0) >= 1 and not omissions,
            "detail": {"empty_confirmations": compare.get("empty_confirmations", 0), "omissions": omissions},
        },
        "4": {
            "pass": not text_length_mismatches,
            "detail": {"text_length_mismatches": len(text_length_mismatches)},
        },
        "5": {"pass": speedup >= 3, "detail": {"speedup": speedup, **timings}},
        "6": {"pass": mode in ("whole_event_raise", "substituted_value"), "mode": mode, "detail": mode_detail},
    }


def recommend(criteria: dict[str, dict]) -> str:
    """``substituted_value`` is length-preserving — as safe as ``whole_event_raise`` — so
    both are eligible for "implement nested" once criteria 1-4 and the speedup gate (5)
    pass; the mode is folded into the returned string as the reasoning."""
    core_pass = all(criteria[k]["pass"] for k in ("1", "2", "3", "4"))
    if not core_pass:
        return "r-bulk-counts-plan"
    mode = criteria["6"]["mode"]
    if mode in ("silent_partial", "unknown"):
        return "r-bulk-counts-plan"
    if mode in ("whole_event_raise", "substituted_value") and criteria["5"]["pass"]:
        return f"implement nested ({mode})"
    return "r-bulk-counts-plan"


def clone_gw(source: Path, out: Path) -> Path:
    source = Path(source)
    out = Path(out)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing clone: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-c", str(source), str(out)], check=True)
    return out


def deck_allowed_for_live(deck: Path, out: Path, allow_external: bool) -> bool:
    """``--live`` may only touch a deck under ``--out`` (a clone), unless the caller
    explicitly overrides — e.g. the Map deck used only for a timing run."""
    if allow_external:
        return True
    try:
        Path(deck).resolve().relative_to(Path(out).resolve())
        return True
    except ValueError:
        return False


# ==========================================================================
# Live (--prep / --live): write but do not run.
# ==========================================================================
def _run_osascript(script: str) -> str:
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(["osascript", str(script_path)], capture_output=True, text=True, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("osascript failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    return (proc.stdout or "").strip()


def _run_jxa(script: str) -> str:
    """Repo convention (``inspect.py``'s ``bulk_geometry``): a JS file, not ``-e``."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(["osascript", "-l", "JavaScript", str(script_path)],
                              capture_output=True, text=True, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("JXA failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    return (proc.stdout or "").strip()


def _write_sidecar(out: Path, name: str, text: str) -> Path:
    """Raw Keynote output, written IMMEDIATELY on return — before any parsing — so a
    live run never loses its evidence to a downstream analysis bug."""
    path = out / name
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--prep", action="store_true",
                    help="clone --deck under --out, lock 1 image + 1 text item, add an empty "
                         "text box, save — RUN ONLY WHEN KEYNOTE IS FREE. Never targets slide 1: "
                         "it must stay the deck's zero-item baseline.")
    ap.add_argument("--live", action="store_true",
                    help="run the nested read + bulk baseline + failure probe against --deck "
                         "(or the freshly prepped clone) — RUN ONLY WHEN KEYNOTE IS FREE")
    ap.add_argument("--allow-external-deck", action="store_true",
                    help="allow --live on a deck NOT under --out (e.g. a pre-cloned Map deck "
                         "used only for a timing run)")
    ap.add_argument("--with-jxa", action="store_true", help="also run build_jxa_nested_read")
    ap.add_argument("--lock-image-slide", type=int, default=2)
    ap.add_argument("--lock-text-slide", type=int, default=6)
    ap.add_argument("--empty-text-slide", type=int, default=6,
                    help="slide to add the empty text box to; must NOT be 1 (GW slide 1's "
                         "zero-item baseline is load-bearing for criterion 3)")
    ap.add_argument("--text-slack", type=int, default=2)
    args = ap.parse_args(argv)

    if args.empty_text_slide == 1 or args.lock_text_slide == 1:
        ap.error("--empty-text-slide and --lock-text-slide must not be 1 (GW slide 1 must "
                  "stay the deck's zero-item baseline)")

    if not args.prep and not args.live:
        print("pure mode: no Keynote touched")
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    deck = args.deck

    if args.prep:
        deck = clone_gw(args.deck, args.out / args.deck.name)
        print(f"clone: {deck}")
        raw = _run_osascript(build_clone_prep_applescript(
            deck, lock_image_slide=args.lock_image_slide,
            lock_text_slide=args.lock_text_slide, empty_text_slide=args.empty_text_slide,
        ))
        _write_sidecar(args.out, f"prep-raw-{deck.stem}.txt", raw)
        report = parse_prep_report(raw)
        print(f"prep: locked={report['locked']} emptyBoxes={report['emptyBoxes']}")
        if report["locked"] != 2 or report["emptyBoxes"] != 1:
            print(f"ABORT: expected locked=2 emptyBoxes=1, got {report}")
            return 4

    if not args.live:
        return 0

    if not deck_allowed_for_live(deck, args.out, args.allow_external_deck):
        print(f"ABORT: --live target {Path(deck).resolve()} is not under --out "
              f"{args.out.resolve()}; pass --allow-external-deck to override")
        return 3

    from obed_edom.inspect import bulk_geometry  # noqa: PLC0415

    t_bulk_cold0 = time.perf_counter()
    bulk = bulk_geometry(deck)
    bulk_seconds_cold = time.perf_counter() - t_bulk_cold0
    print(f"bulk_geometry (cold): {bulk_seconds_cold:.1f}s, {len(bulk)} slides")

    t_open_close0 = time.perf_counter()
    openclose_raw = _run_osascript(build_open_close_applescript(deck))
    open_close_seconds = time.perf_counter() - t_open_close0
    openclose_sidecar = _write_sidecar(args.out, f"openclose-raw-{deck.stem}.txt", openclose_raw)

    t_nested0 = time.perf_counter()
    raw = _run_osascript(build_all_reads_applescript(deck))
    nested_seconds = time.perf_counter() - t_nested0
    nested_sidecar = _write_sidecar(args.out, f"nested-raw-{deck.stem}.json", raw)

    t_bulk_warm0 = time.perf_counter()
    bulk_geometry(deck)
    bulk_seconds_warm = time.perf_counter() - t_bulk_warm0
    print(f"bulk_geometry (warm): {bulk_seconds_warm:.1f}s")

    failure_raw = _run_osascript(
        build_failure_probe_applescript(deck, empty_text_slide=args.empty_text_slide)
    )
    failure_sidecar = _write_sidecar(args.out, f"failure-raw-{deck.stem}.json", failure_raw)

    # Raw Keynote output is now safe on disk (openclose/nested/failure sidecars). Every
    # remaining step is pure-Python analysis of that text — a live run must never lose
    # the sidecars to a downstream bug there, so this whole section is wrapped: on ANY
    # exception, findings-{stem}.json still gets written with the error + the sidecar
    # paths, then the exception is re-raised.
    raw_sidecars: list[str] = [str(openclose_sidecar), str(nested_sidecar), str(failure_sidecar)]
    timings: dict[str, Any] = {
        "bulk_seconds_cold": bulk_seconds_cold, "bulk_seconds_warm": bulk_seconds_warm,
        "open_close_seconds": open_close_seconds, "nested_seconds": nested_seconds,
        "per_read": {},
    }
    findings_path = args.out / f"findings-{deck.stem}.json"

    try:
        entries = parse_nested(raw)
        by_kind: dict[str, dict[str, list]] = {}
        meta_slide_count: int | None = None
        for entry in entries:
            if entry["kind"] == "_meta":
                meta_slide_count = int(entry["value"])
                continue
            by_kind.setdefault(entry["kind"], {})[entry["prop"]] = entry["value"]
            timings["per_read"][f'{entry["kind"]}_{entry["prop"]}'] = int(entry["seconds"])
        slide_count = len(bulk)
        print(f"nested read: {nested_seconds:.1f}s, meta slideCount={meta_slide_count}, "
              f"bulk slides={slide_count}")

        shaped, shape_errors = nested_to_bulk_shape(by_kind, slide_count)
        compare = compare_to_bulk(shaped, bulk, text_slack=args.text_slack)

        failure_entries = parse_nested(failure_raw)
        failure = {e["name"]: e for e in failure_entries}
        zero_char_items, zero_char_reason = resolve_zero_char_premise(
            failure.get("char_counts"), failure.get("char_counts_scoped")
        )
        print(f"zero-char premise: {zero_char_items} ({zero_char_reason})")
        bulk_text_counts = {idx: len(bulk[idx].get("text", [])) for idx in bulk}

        jxa_findings: dict[str, Any] | None = None
        if args.with_jxa:
            t_jxa0 = time.perf_counter()
            jxa_raw = _run_jxa(build_jxa_nested_read(deck))
            timings["jxa_seconds"] = time.perf_counter() - t_jxa0
            jxa_sidecar = _write_sidecar(args.out, f"jxa-raw-{deck.stem}.json", jxa_raw)
            raw_sidecars.append(str(jxa_sidecar))
            jxa_payload = parse_nested(jxa_raw)
            jxa_by_kind = {
                kind: {prop: jxa_payload.get(f"{kind}_{prop}") for prop in PROPS}
                for _name, kind in (("textItems", "text"), ("images", "image"),
                                     ("movies", "movie"), ("groups", "group"))
            }
            jxa_shaped, jxa_shape_errors = nested_to_bulk_shape(jxa_by_kind, slide_count)
            jxa_compare = compare_to_bulk(jxa_shaped, bulk, text_slack=args.text_slack)
            jxa_findings = {
                "compare": jxa_compare, "shape_errors": jxa_shape_errors, "raw_sidecar": str(jxa_sidecar),
            }

        criteria = evaluate_criteria(
            compare, timings, failure, slide_count,
            shape_errors=shape_errors, meta_slide_count=meta_slide_count,
            bulk_text_counts=bulk_text_counts,
            zero_char_items=zero_char_items, zero_char_reason=zero_char_reason,
        )
        verdict = recommend(criteria)

        findings = {
            "criteria": criteria, "timings": timings, "shape_errors": shape_errors,
            "mismatches": compare.get("kind_mismatches", []), "failure": failure,
            "zero_char_items": zero_char_items, "zero_char_reason": zero_char_reason,
            "jxa": jxa_findings, "recommendation": verdict, "raw_sidecars": raw_sidecars,
        }
    except Exception:
        findings = {"error": traceback.format_exc(), "timings": timings, "raw_sidecars": raw_sidecars}
        findings_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")
        print(f"ABORT: analysis crashed; raw Keynote output preserved in {raw_sidecars}; "
              f"findings (with the error) at {findings_path}")
        raise

    findings_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")

    for key in sorted(criteria, key=int):
        status = "PASS" if criteria[key]["pass"] else "FAIL"
        print(f"criterion {key}: {status}  {criteria[key].get('detail', {})}")
    print(f"failure probes: {failure}")
    print(f"recommendation: {verdict}")
    print(f"findings: {findings_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
