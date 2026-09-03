from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from obed_edom import keynote_app
from obed_edom.models import SlideSpec
from obed_edom.paths import output_root, select_deck_template


def _keynote_tell() -> str:
    """Tell header: address by bundle id, never by name."""
    return f'tell application id "{keynote_app.bundle_id()}"'


def _keynote_terms() -> str:
    return f'using terms from application id "{keynote_app.bundle_id()}"'


def _keynote_process_tell() -> str:
    """System Events process matched by bundle id, not name."""
    return (
        'tell application "System Events" to tell '
        f'(first application process whose bundle identifier is "{keynote_app.bundle_id()}")'
    )


def _stem(docx: Path) -> str:
    return docx.stem.replace(" ", "_")


def output_dir_for(docx: Path, root: Path | None = None) -> Path:
    out = (root / "output" if root else output_root()) / _stem(docx)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _copy_template(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
        dest.unlink(missing_ok=True)
    shutil.copy2(src, dest)
    return dest


STYLE_PALETTES = {
    "dsk": {
        "verse_number": {"color": [65535, 41386, 0], "size": 45},
        "normal": {"color": [65530, 65535, 65524], "font": "AzoSans-Regular", "size": 45},
        "highlight": {"color": [65535, 41386, 0], "font": "AzoSans-Bold", "size": 45},
    },
    "lw": {
        "verse_number": {"color": [8368, 65520, 65472], "size": 70},
        "normal": {"color": [65527, 65535, 65524], "font": "AzoSans-Regular", "size": 70},
        "highlight": {"color": [65534, 65532, 2687], "font": "AzoSans-Bold", "size": 70},
    },
    "lw_point": {
        "normal": {"color": [65527, 65535, 65524]},
        "highlight": {"color": [65534, 65532, 2687]},
    },
    "dsk_point": {
        "normal": {"color": [65530, 65535, 65524]},
        "highlight": {"color": [65535, 41386, 0]},
    },
}


def _runs_to_payload(runs) -> list[dict]:
    return [{"text": r.text, "style": r.style} for r in runs]


def _prepare_styled_runs(runs: list[dict]) -> tuple[str, str, list[dict]]:
    """Split leading template-superscript digits from the body-baseline rest.

    Later verse numbers stay ASCII; pass 2 copies superscript from the seed character.
    """
    cleaned: list[dict] = []
    skipping = True
    for run in runs:
        text = run.get("text") or ""
        if not text:
            continue
        style = run.get("style") or "normal"
        if skipping and style != "verse_number" and not text.strip():
            continue
        skipping = False
        cleaned.append({"text": text, "style": style})
    runs = cleaned

    prepared: list[dict] = []
    first_super = ""
    rest_parts: list[str] = []
    first_kind: str | None = None
    seen_super = False
    for run in runs:
        text = run.get("text") or ""
        style = run.get("style") or "normal"
        kind = "super" if style == "verse_number" else "body"
        if first_kind is None:
            first_kind = kind
        if kind == "super" and first_kind == "super" and not seen_super:
            first_super = text
            seen_super = True
            prepared.append({"text": text, "style": style})
        elif kind == "super":
            rest_parts.append(text)
            prepared.append({"text": text, "style": style})
        else:
            rest_parts.append(text)
            prepared.append({"text": text, "style": style})
    if first_kind != "super":
        prepared = []
        for run in runs:
            text = run.get("text") or ""
            if not text:
                continue
            style = run.get("style") or "normal"
            prepared.append({"text": text, "style": style})
        return "", "".join(p["text"] for p in prepared), prepared
    return first_super, "".join(rest_parts), prepared


def _append_created_text_item(lines: list[str], item: dict) -> None:
    """POST masters hide point placeholders at 0×0; add a real box for Magic Move."""
    text = item.get("text") or ""
    x, y = int(item["x"]), int(item["y"])
    w, h = int(item.get("width") or 350), int(item.get("height") or 125)
    palette = STYLE_PALETTES.get(item.get("palette") or "", STYLE_PALETTES["dsk_point"])
    normal = palette.get("normal") or STYLE_PALETTES["dsk_point"]["normal"]
    lines += [
        "        try",
        "          set extraItem to make new text item with properties "
        f'{{object text:"{_as_escape(text)}", position:{{{x}, {y}}}, width:{w}, height:{h}}}',
    ]
    runs = item.get("runs") or [{"text": text, "style": "normal"}]
    total = sum(len(r.get("text") or "") for r in runs)
    if total >= 1:
        lines.append("          tell object text of extraItem")
        lines.append(
            f"            set color of characters 1 thru {total} to "
            f"{{{normal['color'][0]}, {normal['color'][1]}, {normal['color'][2]}}}"
        )
        cursor = 1
        for run in runs:
            chunk = run.get("text") or ""
            n = len(chunk)
            if n < 1:
                continue
            style_name = run.get("style") or "normal"
            look = palette.get(style_name) or normal
            start, end = cursor, cursor + n - 1
            lines.append(
                f"            set color of characters {start} thru {end} to "
                f"{{{look['color'][0]}, {look['color'][1]}, {look['color'][2]}}}"
            )
            cursor += n
        lines.append("          end tell")
    lines.append("        end try")


def _append_plain_text(lines: list[str], idx: int, value: str, size: float | None = None) -> None:
    lines.append("        try")
    if not (value or "").strip():
        lines.append(f"          tell object text of text item {idx}")
        lines.append("            set clearN to count of characters")
        lines.append("            if clearN > 0 then delete characters 1 thru clearN")
        lines.append("          end tell")
    else:
        lines.append(f'          set object text of text item {idx} to "{_as_escape(value)}"')
        if size is not None:
            lines.append(f"          tell object text of text item {idx}")
            lines.append("            set plainCount to count of characters")
            lines.append(f"            if plainCount > 0 then set size of characters 1 thru plainCount to {size}")
            lines.append("          end tell")
    lines.append("        end try")


def _text_seed_mode(first_super: str, spec: dict, palette_name: str) -> str:
    """keep_super / body_only / replace — so SuperScript does not leak onto body copy."""
    if first_super:
        return "keep_super"
    if palette_name in {"lw_point", "dsk_point"}:
        return "replace"
    master = spec.get("master") or ""
    if spec.get("isVerse") or master == "VERSES" or str(master).startswith("Verse"):
        return "body_only"
    return "replace"


def _append_seeded_text(
    lines: list[str],
    idx: int,
    first_super: str,
    rest: str,
    *,
    mode: str = "keep_super",
) -> None:
    """Write verse body without turning the whole box into superscript.

    Replacing object text copies the seed's superscript onto every character.
    """
    if mode == "replace" or (mode == "keep_super" and not first_super):
        lines.append("        try")
        lines.append(f'          set object text of text item {idx} to "{_as_escape(rest)}"')
        lines.append("        end try")
        return

    if mode == "body_only":
        expected = len(rest)
        fallback = rest
        lines += [
            "        try",
            "          set usedSeed to false",
            f"          tell object text of text item {idx}",
            "            set seedCount to count of characters",
            "            if seedCount >= 2 then",
            "              set superSize to size of character 1",
            "              set bodyIdx to 0",
            "              set seedI to 1",
            "              repeat while seedI <= seedCount",
            "                if (size of character seedI) > (superSize + 1) then",
            "                  set bodyIdx to seedI",
            "                  exit repeat",
            "                end if",
            "                set seedI to seedI + 1",
            "              end repeat",
            "              if bodyIdx > 1 then",
            "                if seedCount > bodyIdx then delete characters (bodyIdx + 1) thru seedCount",
            "                delete characters 1 thru (bodyIdx - 1)",
            "                set usedSeed to true",
            "              end if",
            "            end if",
            "          end tell",
            "          if usedSeed then",
            f"            tell object text of text item {idx}",
            f'              set character 1 to "{_as_escape(rest)}"',
            "              set finalCount to count of characters",
            f"              if finalCount > {expected} then "
            f"delete characters {expected + 1} thru finalCount",
            "            end tell",
            "          else",
            f'            set object text of text item {idx} to "{_as_escape(fallback)}"',
            "          end if",
            "        end try",
        ]
        return

    expected = len(first_super) + len(rest)
    fallback = first_super + rest
    lines += [
        "        try",
        "          set usedSeed to false",
        f"          tell object text of text item {idx}",
        "            set seedCount to count of characters",
        "            if seedCount >= 2 then",
        "              set superSize to size of character 1",
        "              set bodyIdx to 0",
        "              set seedI to 1",
        "              repeat while seedI <= seedCount",
        "                if (size of character seedI) > (superSize + 1) then",
        "                  set bodyIdx to seedI",
        "                  exit repeat",
        "                end if",
        "                set seedI to seedI + 1",
        "              end repeat",
        "              if bodyIdx > 1 then",
        "                if seedCount > bodyIdx then delete characters (bodyIdx + 1) thru seedCount",
        "                if bodyIdx > 2 then delete characters 2 thru (bodyIdx - 1)",
        "                set usedSeed to true",
        "              end if",
        "            end if",
        "          end tell",
        "          if usedSeed then",
        f"            tell object text of text item {idx}",
        f'              set character 1 to "{_as_escape(first_super)}"',
    ]
    if rest:
        lines += [
            "              set seedN to count of characters",
            f'              set character seedN to "{_as_escape(rest)}"',
        ]
    else:
        lines += [
            "              set seedN to count of characters",
            f"              if seedN > {len(first_super)} then "
            f"delete characters {len(first_super) + 1} thru seedN",
        ]
    lines += [
        "              set finalCount to count of characters",
        f"              if finalCount > {expected} then "
        f"delete characters {expected + 1} thru finalCount",
        "            end tell",
    ]
    lines += [
        "          else",
        f'            set object text of text item {idx} to "{_as_escape(fallback)}"',
        "          end if",
        "        end try",
    ]


def _append_styling_pass(
    lines: list[str],
    idx: int,
    prepared: list[dict],
    palette: dict,
    body_size: float | None,
) -> None:
    """Per-run colours/fonts; never a blanket Regular-font sweep over verse numbers."""
    normal = palette.get("normal") or STYLE_PALETTES["lw"]["normal"]
    total = sum(len(r.get("text") or "") for r in prepared)
    if total < 1:
        return
    lines.append("        try")
    lines.append(f"          tell object text of text item {idx}")
    lines.append(
        f"            set color of characters 1 thru {total} to "
        f"{{{normal['color'][0]}, {normal['color'][1]}, {normal['color'][2]}}}"
    )
    cursor = 1
    for run in prepared:
        text = run.get("text") or ""
        n = len(text)
        if n < 1:
            continue
        style_name = run.get("style") or "normal"
        look = palette.get(style_name) or normal
        start = cursor
        end = cursor + n - 1
        if style_name == "verse_number":
            lines.append(
                f"            set color of characters {start} thru {end} to "
                f"{{{look['color'][0]}, {look['color'][1]}, {look['color'][2]}}}"
            )
        elif style_name == "highlight":
            lines.append(
                f"            set color of characters {start} thru {end} to "
                f"{{{look['color'][0]}, {look['color'][1]}, {look['color'][2]}}}"
            )
            if look.get("font"):
                lines.append(f'            set font of characters {start} thru {end} to "{look["font"]}"')
            run_size = look["size"] if look.get("size") is not None else body_size
            if run_size is not None:
                lines.append(f"            set size of characters {start} thru {end} to {run_size}")
        else:
            if normal.get("font"):
                lines.append(f'            set font of characters {start} thru {end} to "{normal["font"]}"')
            if body_size is not None:
                lines.append(f"            set size of characters {start} thru {end} to {body_size}")
        cursor += n
    lines.append("          end tell")
    lines.append("        end try")


# Find is the only scripted way to place a text selection; later verse numbers use the following copy as the needle.
_ANCHOR_MAX_CHARS = 24


def _verse_anchor(prepared: list[dict], run_index: int) -> str:
    """Text right after a verse number — Find needle that selects it."""
    tail = "".join((r.get("text") or "") for r in prepared[run_index + 1 :])
    anchor = tail.split("\n", 1)[0][:_ANCHOR_MAX_CHARS]
    return anchor if anchor.strip() else ""


def _seed_verse_job(prepared: list[dict]) -> dict | None:
    """First verse number, whose character style pass 2 copies from."""
    for run_index, run in enumerate(prepared):
        text = run.get("text") or ""
        if not text:
            continue
        if (run.get("style") or "normal") == "verse_number":
            anchor = _verse_anchor(prepared, run_index)
            if not anchor:
                return None
            return {"digits": text.strip(), "len": len(text), "anchor": anchor}
    return None


def _later_verse_jobs(prepared: list[dict]) -> list[dict]:
    jobs: list[dict] = []
    cursor = 1
    seen_super = False
    for run_index, run in enumerate(prepared):
        text = run.get("text") or ""
        n = len(text)
        if n < 1:
            continue
        if (run.get("style") or "normal") == "verse_number":
            if not seen_super:
                seen_super = True
            else:
                jobs.append(
                    {
                        "start": cursor,
                        "digits": text.strip(),
                        "len": n,
                        "anchor": _verse_anchor(prepared, run_index),
                    }
                )
        cursor += n
    return jobs


def _collect_superscript_jobs(slides: list[SlideSpec]) -> list[dict]:
    """Later-verse superscript targets keyed by verse text marker (not slide index)."""
    jobs: list[dict] = []
    for spec in slides:
        for idx, runs in spec.styled_items.items():
            payload = [{"text": r.text, "style": r.style} for r in runs]
            first_super, _, prepared = _prepare_styled_runs(payload)
            # Skip jobs pass 2 cannot do: a non-empty list makes pass 1 leave the deck open and unexported.
            later = [v for v in _later_verse_jobs(prepared) if v["anchor"]]
            if not first_super or not later:
                continue
            seed = _seed_verse_job(prepared)
            if not seed:
                continue
            marker = ""
            for run in prepared:
                if (run.get("style") or "normal") == "normal" and (run.get("text") or "").strip():
                    marker = (run.get("text") or "").strip().split("\n", 1)[0][:24]
                    break
            jobs.append(
                {
                    "textItem": int(idx),
                    "marker": marker,
                    "seed": seed,
                    "laterVerses": later,
                }
            )
    return jobs


def _superscript_anchor_plan(jobs: list[dict]) -> list[dict]:
    """One Find pass per distinct anchor, once per slide that shows that verse."""
    counts: dict[tuple[str, int], int] = {}
    order: list[tuple[str, int]] = []
    for job in jobs:
        for verse in job.get("laterVerses") or []:
            anchor = verse.get("anchor") or ""
            if not anchor:
                continue
            key = (anchor, int(verse.get("len") or len(verse["digits"])))
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += 1
    return [
        {"anchor": anchor, "len": length, "occurrences": counts[(anchor, length)]}
        for anchor, length in order
    ]


def _append_select_digits(lines: list[str], anchor: str, digit_len: int, indent: str) -> None:
    lines += [
        f'{indent}keystroke "f" using {{command down}}',
        f"{indent}delay 0.7",
        f'{indent}keystroke "{anchor}"',
        f"{indent}delay 0.9",
        f"{indent}key code 36",
        f"{indent}delay 0.7",
        f"{indent}key code 53",
        f"{indent}delay 0.5",
        f"{indent}key code 123",
        f"{indent}delay 0.25",
        f"{indent}repeat {digit_len} times",
        f"{indent}  key code 123 using {{shift down}}",
        f"{indent}  delay 0.15",
        f"{indent}end repeat",
        f"{indent}delay 0.25",
    ]


def _append_superscript_gui_pass(lines: list[str], seed: dict, plan: list[dict]) -> None:
    """Copy Style from the seed verse number, Paste Style onto the rest.

    AppleScript cannot set superscript; Accessibility drives Format. Apply once per occurrence.
    """
    seed_anchor = _as_escape(seed["anchor"])
    seed_len = int(seed["len"])
    lines += [
        "try",
        "  " + _keynote_process_tell(),
    ]
    _append_select_digits(lines, seed_anchor, seed_len, "    ")
    lines += [
        '    click menu item "Copy Style" of menu "Format" '
        'of menu bar item "Format" of menu bar 1',
        "    delay 0.6",
        "    key code 53",
        "    delay 0.25",
        "  end tell",
        "on error errMsg number errNum",
        '  set guiError to guiError & " [copy " & errNum & ": " & errMsg & "]"',
        "end try",
    ]
    for entry in plan:
        anchor = _as_escape(entry["anchor"])
        digit_len = int(entry["len"])
        occurrences = int(entry["occurrences"])
        lines += [
            f"repeat {occurrences} times",
            "  try",
            "    " + _keynote_process_tell(),
        ]
        _append_select_digits(lines, anchor, digit_len, "      ")
        lines += [
            '      click menu item "Paste Style" of menu "Format" '
            'of menu bar item "Format" of menu bar 1',
            "      delay 0.6",
            "      key code 53",
            "      delay 0.25",
            "    end tell",
            "  on error errMsg number errNum",
            '    set guiError to guiError & " [" & errNum & ": " & errMsg & "]"',
            "  end try",
            "end repeat",
        ]


def _build_superscript_fix_script(
    key_path: Path, jobs: list[dict], export_dir: Path | None = None
) -> str:
    """Pass 2: style later verse numbers in the deck pass 1 left open.

    `open` here is bring-to-front of the already-loaded document, then export and close.
    """
    plan = _superscript_anchor_plan(jobs)
    seed = next((job.get("seed") for job in jobs if job.get("seed")), None)
    if not plan or not seed:
        return ""
    escaped = _as_escape(str(key_path))
    lines = [
        'set guiError to ""',
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        f'  set theFile to POSIX file "{escaped}"',
        "  open theFile",
        "  delay 0.8",
        "end tell",
        "end using terms from",
    ]
    _append_superscript_gui_pass(lines, seed, plan)
    lines += [
        _keynote_terms(),
        _keynote_tell(),
        "  set theDoc to document 1",
        '  set sizeReport to ""',
        "  tell theDoc",
    ]
    for job in jobs:
        text_item = int(job["textItem"])
        marker = _as_escape(job.get("marker") or "")
        later = job.get("laterVerses") or []
        if not later:
            continue
        lines += [
            "    try",
            "      repeat with s from 1 to count of slides",
            "        tell slide s",
            "          try",
            f'            if (object text of text item {text_item} as string) contains "{marker}" then',
            f'              tell object text of text item {text_item}',
            f'                set sizeReport to sizeReport & " s=" & s & " ti={text_item}"',
            '                set sizeReport to sizeReport & " c1=" & (size of character 1)',
        ]
        for verse in later:
            start = int(verse["start"])
            lines.append(
                f'                set sizeReport to sizeReport & " c{start}=" & (size of character {start})'
            )
        lines += [
            "              end tell",
            "            end if",
            "          end try",
            "        end tell",
            "      end repeat",
            "    end try",
        ]
    lines += [
        "  end tell",
        "  save theDoc",
        '  set exported to "false"',
    ]
    if export_dir:
        # Pass 2 exports; pass 1 must not.
        lines += [
            f'  set exportFolder to POSIX file "{_as_escape(str(export_dir))}"',
            "  try",
            "    export theDoc to exportFolder as slide images with properties "
            "{image format:PNG, skipped slides:false}",
            '    set exported to "true"',
            "  end try",
        ]
    lines += [
        "  try",
        "    close theDoc saving yes",
        "  end try",
        '  return sizeReport & " gui=" & guiError & " exported=" & exported',
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def _run_superscript_fix(
    key_path: Path, jobs: list[dict], export_dir: Path | None = None
) -> dict:
    script = _build_superscript_fix_script(key_path, jobs, export_dir)
    if not script:
        return {"ok": True, "skipped": True}
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    size_report = (proc.stdout or "").strip()
    verdict = _read_superscript_report(size_report)
    ok = proc.returncode == 0 and verdict["allSuperscript"]
    if not ok:
        debug = Path(key_path).with_suffix(".superscript.applescript")
        debug.write_text(script, encoding="utf-8")
    return {
        "ok": ok,
        "raw": size_report,
        "boxes": verdict["boxes"],
        "accessibilityDenied": verdict["accessibilityDenied"],
        "exported": verdict["exported"],
        "stderr": proc.stderr or "",
    }


def _stat_leaf_font_writes(container: str) -> list[str]:
    """Font pass for each text leaf of `container`: stat numbers → template size; all
    other uniform text → its own size × `s` (the group's affine scale). Keynote scales a
    group's child GEOMETRY on resize but NOT font size, so without this the text keeps its
    wall-size font in a shrunk box and clips. Mixed-run leaves are skipped. `s` is in scope
    from ``obedStatJob``."""
    return [
        f"  repeat with _i from 1 to count of iWork items of {container}",
        "    try",
        f"      set _leaf to iWork item _i of {container}",
        "      if (class of _leaf) is not group then",
        "        try",
        "          set _str to (object text of _leaf as string)",
        "          set _tgt to my statSizeFor(_str)",
        "          set _c1 to size of character 1 of object text of _leaf",
        "          set _cN to size of character -1 of object text of _leaf",
        "          if _c1 = _cN then",
        "            if _tgt > 0 then",
        "              set size of characters 1 thru -1 of object text of _leaf to _tgt",
        "            else",
        "              set size of characters 1 thru -1 of object text of _leaf to (_c1 * s)",
        "            end if",
        "            set sized to sized + 1",
        "          else",
        "            set sizeSkips to sizeSkips + 1",
        "          end if",
        "        end try",
        "      end if",
        "    end try",
        "  end repeat",
    ]


def _stat_size_handler(size_map: dict) -> list[str]:
    """`statSizeFor` returns the template size for a trimmed number string, else 0."""
    lines = ["on statSizeFor(theStr)"]
    lines += [
        '  set _t to theStr',
        '  repeat while _t starts with " " or _t starts with tab or _t starts with return or _t starts with linefeed',
        "    if (count of _t) is 0 then exit repeat",
        "    set _t to text 2 thru -1 of _t",
        "  end repeat",
        '  repeat while _t ends with " " or _t ends with tab or _t ends with return or _t ends with linefeed',
        "    if (count of _t) is 0 then exit repeat",
        "    set _t to text 1 thru -2 of _t",
        "  end repeat",
    ]
    for content, size in size_map.items():
        key = _as_escape(str(content).strip())
        lines.append(f'  if _t is "{key}" then return {float(size)}')
    lines += ["  return 0", "end statSizeFor"]
    return lines


# DFS-leaf-signature separator MUST equal iwa_runs._SIG_JOIN ("\n").
_SIG_JOIN = "\n"


def _as_string_list(parts: list[str]) -> str:
    return "{" + ", ".join('"' + _as_escape(p) + '"' for p in parts) + "}"


def _sig_list_literal(sig: str) -> str:
    return _as_string_list([p for p in sig.split(_SIG_JOIN) if p])


def _as_norm_sig_simulate(text: str | None) -> str:
    """Python mirror of AppleScript `obedNormSig` for the offline parity test."""
    t = text or ""
    t = t.replace("￼", "").replace("\xa0", " ")
    for ws in ("\t", "\r", "\n", " ", " "):
        t = t.replace(ws, " ")
    while "  " in t:
        t = t.replace("  ", " ")
    return t.strip(" ")


def _sig_handlers() -> list[str]:
    """Replace / normalize / DFS leaf-list. `obedSigLeaves` must `tell application id`."""
    return [
        "on obedReplace(t, findStr, replStr)",
        "  set od to AppleScript's text item delimiters",
        "  set AppleScript's text item delimiters to findStr",
        "  set _parts to text items of t",
        "  set AppleScript's text item delimiters to replStr",
        "  set t to _parts as text",
        "  set AppleScript's text item delimiters to od",
        "  return t",
        "end obedReplace",
        "on obedNormSig(theStr)",
        "  set t to theStr as string",
        '  set t to my obedReplace(t, (character id 65532), "")',
        '  set t to my obedReplace(t, (character id 160), " ")',
        '  set t to my obedReplace(t, tab, " ")',
        '  set t to my obedReplace(t, return, " ")',
        '  set t to my obedReplace(t, linefeed, " ")',
        '  set t to my obedReplace(t, (character id 8232), " ")',
        '  set t to my obedReplace(t, (character id 8233), " ")',
        '  repeat while t contains "  "',
        '    set t to my obedReplace(t, "  ", " ")',
        "  end repeat",
        '  repeat while t starts with " "',
        "    if (count of t) is 0 then exit repeat",
        "    set t to text 2 thru -1 of t",
        "  end repeat",
        '  repeat while t ends with " "',
        "    if (count of t) is 0 then exit repeat",
        "    set t to text 1 thru -2 of t",
        "  end repeat",
        "  return t",
        "end obedNormSig",
        # Must wrap in `tell application id` (not just `using terms from`) or `count of iWork items` fails -1700.
        "on obedSigLeaves(g)",
        "  " + _keynote_tell(),
        "    set acc to {}",
        "    repeat with _i from 1 to count of iWork items of g",
        "      set _it to iWork item _i of g",
        "      if (class of _it) is group then",
        "        set acc to acc & my obedSigLeaves(_it)",
        "      else",
        "        try",
        "          set _t to my obedNormSig(object text of _it as string)",
        '          if _t is not "" then set end of acc to _t',
        "        end try",
        "      end if",
        "    end repeat",
        "    return acc",
        "  end tell",
        "end obedSigLeaves",
    ]


_STAT_ACCUMULATORS = (
    "theDoc",
    "doneJobs",
    "skipJobs",
    "sized",
    "sizeSkips",
    "dedupDeleted",
    "dedupShortfall",
    "frontRaised",
    "frontErr",
    "report",
    "raiseTargets",
    "claimed",
    "sigFallbacks",
    "unresolved",
)


def _stat_job_handlers() -> list[str]:
    """Index verified by content; descending raise relies on Bring-to-Front append semantics."""
    lines = [
        "on obedSlideSigs(slideNo)",
        "  global theDoc",
        "  set _acc to {}",
        "  " + _keynote_tell(),
        "    repeat with _gi from 1 to count of groups of slide slideNo of theDoc",
        "      set end of _acc to {idx:_gi, sig:my obedSigLeaves(group _gi of slide slideNo of theDoc)}",
        "    end repeat",
        "  end tell",
        "  return _acc",
        "end obedSlideSigs",
        "on obedDedupPick(slideNo, sigs, targetSig, keepN, delN)",
        "  global dedupShortfall, report",
        "  set _idxs to {}",
        "  repeat with _e in sigs",
        "    set _r to contents of _e",
        "    if (sig of _r) is targetSig then set end of _idxs to (idx of _r)",
        "  end repeat",
        "  if (count of _idxs) = (keepN + delN) then",
        "    set _del to {}",
        "    repeat with _j from 1 to delN",
        "      set end of _del to (item _j of _idxs)",
        "    end repeat",
        "    return _del",
        "  else",
        "    set dedupShortfall to dedupShortfall + delN",
        '    set report to report & " dedupMiss(s=" & slideNo & ",live=" & (count of _idxs) & ",keep=" & keepN & ",del=" & delN & ")"',
        "    return {}",
        "  end if",
        "end obedDedupPick",
        # Delete collected group indices highest-first so lower cached indices stay valid.
        "on obedApplyDeletes(slideNo, idxs)",
        "  global theDoc, dedupDeleted",
        "  set _rem to idxs",
        "  " + _keynote_tell(),
        "    repeat while (count of _rem) > 0",
        "      set _mx to item 1 of _rem",
        "      repeat with _k from 2 to count of _rem",
        "        if (item _k of _rem) > _mx then set _mx to item _k of _rem",
        "      end repeat",
        "      delete group _mx of slide slideNo of theDoc",
        "      set dedupDeleted to dedupDeleted + 1",
        "      set _new to {}",
        "      repeat with _k from 1 to count of _rem",
        "        if (item _k of _rem) is not _mx then set end of _new to item _k of _rem",
        "      end repeat",
        "      set _rem to _new",
        "    end repeat",
        "  end tell",
        "end obedApplyDeletes",
        "on obedResolveGroup(slideNo, sigs, gi, targetSig, allowFallback)",
        "  global claimed, sigFallbacks, unresolved, skipJobs, report",
        "  set _hits to {}",
        "  repeat with _e in sigs",
        "    set _r to contents of _e",
        "    if (sig of _r) is targetSig then",
        "      set _idx to (idx of _r)",
        "      if _idx is not in claimed then set end of _hits to _idx",
        "    end if",
        "  end repeat",
        "  if gi > 0 then",
        "    repeat with _h in _hits",
        "      if (contents of _h) is gi then",
        "        set end of claimed to gi",
        "        return gi",
        "      end if",
        "    end repeat",
        "  end if",
        "  if (allowFallback is not 0) and ((count of _hits) = 1) then",
        "    set sigFallbacks to sigFallbacks + 1",
        '    set report to report & " sigFallback(s=" & slideNo & ",gi=" & gi & ")"',
        "    set _w to item 1 of _hits",
        "    set end of claimed to _w",
        "    return _w",
        "  else",
        "    set unresolved to unresolved + 1",
        "    set skipJobs to skipJobs + 1",
        '    set report to report & " unresolved(s=" & slideNo & ",gi=" & gi & ",n=" & (count of _hits) & ")"',
        "    return 0",
        "  end if",
        "end obedResolveGroup",
        "on obedStatJob(slideNo, sigs, gi, targetSig, s, allowFallback)",
        "  global theDoc, doneJobs, skipJobs, sized, sizeSkips, report, raiseTargets",
        "  set _gi to my obedResolveGroup(slideNo, sigs, gi, targetSig, allowFallback)",
        "  if _gi is 0 then return",
        "  set end of raiseTargets to {sl:slideNo, idx:_gi}",
        "  " + _keynote_tell(),
        "    try",
        "      set g to group _gi of slide slideNo of theDoc",
    ]
    lines += ["  " + ln for ln in _stat_leaf_font_writes("g")]
    lines += [
        "      repeat with _sgi from 1 to count of groups of g",
        "        set _sub to group _sgi of g",
    ]
    lines += ["    " + ln for ln in _stat_leaf_font_writes("_sub")]
    lines += [
        "      end repeat",
        "      set doneJobs to doneJobs + 1",
        "    on error errMsg number errNum",
        "      set skipJobs to skipJobs + 1",
        '      set report to report & " skip(font,s=" & slideNo & ",err=" & errNum & ":" & errMsg & ")"',
        "    end try",
        "  end tell",
        "end obedStatJob",
        "on obedRaiseSlide(slideNo)",
        "  global theDoc, raiseTargets",
        "  set _rem to {}",
        "  repeat with _e in raiseTargets",
        "    set _r to contents of _e",
        "    if (sl of _r) is slideNo then set end of _rem to (idx of _r)",
        "  end repeat",
        "  repeat while (count of _rem) > 0",
        "    set _mx to item 1 of _rem",
        "    repeat with _k from 2 to count of _rem",
        "      if (item _k of _rem) > _mx then set _mx to item _k of _rem",
        "    end repeat",
        "    " + _keynote_tell(),
        "      set selection of theDoc to {group _mx of slide slideNo of theDoc}",
        "    end tell",
        "    my obedFront()",
        "    set _new to {}",
        "    repeat with _k from 1 to count of _rem",
        "      if (item _k of _rem) is not _mx then set end of _new to item _k of _rem",
        "    end repeat",
        "    set _rem to _new",
        "  end repeat",
        "end obedRaiseSlide",
        "on obedRaiseItem(slideNo, theKind, idx)",
        "  global theDoc",
        "  set _found to false",
        "  " + _keynote_tell(),
        "    try",
        "      tell slide slideNo of theDoc",
        '        if theKind is "shape" then',
        "          set selection of theDoc to {shape idx}",
        '        else if theKind is "image" then',
        "          set selection of theDoc to {image idx}",
        '        else if theKind is "group" then',
        "          set selection of theDoc to {group idx}",
        "        else",
        "          set selection of theDoc to {text item idx}",
        "        end if",
        "        set _found to true",
        "      end tell",
        "    end try",
        "  end tell",
        "  if _found then my obedFront()",
        "end obedRaiseItem",
        "on obedBadgeRaise(slideNo)",
        "  global theDoc",
        "  set _found to false",
        "  " + _keynote_tell(),
        "    try",
        "      tell slide slideNo of theDoc",
        "        repeat with _gi from 1 to count of groups",
        "          set _bg to group _gi",
        "          repeat with _ti from 1 to count of text items of _bg",
        "            try",
        '              if (object text of text item _ti of _bg as string) contains "Global Missions" then',
        "                set selection of theDoc to {_bg}",
        "                set _found to true",
        "              end if",
        "            end try",
        "            if _found then exit repeat",
        "          end repeat",
        "          if _found then exit repeat",
        "        end repeat",
        "        if not _found then",
        "          repeat with _ti from 1 to count of text items",
        "            try",
        '              if (object text of text item _ti as string) contains "Global Missions" then',
        "                set selection of theDoc to {text item _ti}",
        "                set _found to true",
        "              end if",
        "            end try",
        "            if _found then exit repeat",
        "          end repeat",
        "        end if",
        "        if not _found then",
        "          repeat with _si from 1 to count of shapes",
        "            try",
        '              if (object text of shape _si as string) contains "Global Missions" then',
        "                set selection of theDoc to {shape _si}",
        "                set _found to true",
        "              end if",
        "            end try",
        "            if _found then exit repeat",
        "          end repeat",
        "        end if",
        "      end tell",
        "    end try",
        "  end tell",
        "  if _found then my obedFront()",
        "end obedBadgeRaise",
        "on obedFront()",
        "  global frontRaised, frontErr",
        "  delay 0.35",
        "  try",
        "    " + _keynote_process_tell(),
        '      click menu item "Bring to Front" of menu "Arrange" of menu bar item "Arrange" of menu bar 1',
        "    end tell",
        "    set frontRaised to frontRaised + 1",
        "    delay 0.2",
        "  on error errMsg number errNum",
        '    set frontErr to frontErr & " [" & errNum & "]"',
        "  end try",
        "end obedFront",
    ]
    return lines


def _build_stat_finalize_script(
    dest: Path,
    jobs: list[dict],
    size_map: dict,
    export_dir: Path | None = None,
    group_removes: list[dict] | None = None,
    badge_raises: list[dict] | None = None,
) -> str:
    """Post-JXA: template stat sizes, then Bring to Front (stat groups + badge). Optional PNG export before close."""
    group_removes = group_removes or []
    badge_raises = badge_raises or []
    if not jobs and not group_removes and not badge_raises:
        return ""
    escaped = _as_escape(str(dest))
    doc_name = _as_escape(Path(dest).name)
    font_jobs = [j for j in jobs if j.get("childSig")]
    font_skips = len(jobs) - len(font_jobs)
    dedup: dict[tuple[int, str], dict] = {}
    no_sig_removes = 0
    for gr in group_removes:
        sig = gr.get("childSig")
        if not sig:
            no_sig_removes += 1
            continue
        key = (int(gr["slide"]), sig)
        d = dedup.setdefault(key, {"count": 0, "expectedKeep": int(gr.get("expectedKeep") or 0)})
        d["count"] += 1
    badge_by_slide: dict[int, list[dict]] = {}
    for br in badge_raises:
        badge_by_slide.setdefault(int(br["slide"]), []).append(br)
    lines: list[str] = ["global " + ", ".join(_STAT_ACCUMULATORS)]
    lines += _stat_size_handler(size_map)
    lines += _sig_handlers()
    lines += _stat_job_handlers()
    lines += [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 3600 seconds",
        "  try",
        f'    close (every document whose name is "{doc_name}") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{escaped}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        "  set doneJobs to 0",
        "  set skipJobs to 0",
        "  set sized to 0",
        "  set sizeSkips to 0",
        "  set dedupDeleted to 0",
        f"  set dedupShortfall to {no_sig_removes}",
        "  set raiseTargets to {}",
        "  set sigFallbacks to 0",
        "  set unresolved to 0",
        '  set exported to "false"',
        '  set report to ""',
    ]
    dedup_by_slide: dict[int, list[tuple[str, int, int]]] = {}
    for (slide, sig), d in dedup.items():
        dedup_by_slide.setdefault(slide, []).append(
            (sig, int(d["expectedKeep"]), int(d["count"]))
        )
    for slide in sorted(dedup_by_slide):
        lines += [f"  set _sigs to my obedSlideSigs({slide})", "  set _dels to {}"]
        for sig, keep, dele in dedup_by_slide[slide]:
            sig_lit = _sig_list_literal(sig)
            lines += [
                f"  set _dels to _dels & my obedDedupPick({slide}, _sigs, {sig_lit}, {keep}, {dele})"
            ]
        lines += [f"  my obedApplyDeletes({slide}, _dels)"]
    if font_skips:
        lines += [f"  set skipJobs to skipJobs + {font_skips}"]
    sig_counts: dict[tuple[int, str], int] = {}
    for job in font_jobs:
        key = (int(job["slide"]), str(job["childSig"]))
        sig_counts[key] = sig_counts.get(key, 0) + 1
    font_by_slide: dict[int, list[tuple[int, str, float, int]]] = {}
    for job in font_jobs:
        slide = int(job["slide"])
        childsig = str(job["childSig"])
        gi = int(job.get("groupIndex") or 0)
        s = float(job.get("s") or 1.0)
        allow_fallback = 0 if sig_counts[(slide, childsig)] > 1 else 1
        font_by_slide.setdefault(slide, []).append((gi, childsig, s, allow_fallback))
    for slide in sorted(font_by_slide):
        lines += [
            f"  set _sigs to my obedSlideSigs({slide})",
            "  set claimed to {}",
        ]
        for gi, childsig, s, allow_fallback in font_by_slide[slide]:
            sig_lit = _sig_list_literal(childsig)
            lines += [
                f"  my obedStatJob({slide}, _sigs, {gi}, {sig_lit}, {float(s)}, {allow_fallback})"
            ]
    lines += ["  save theDoc"]
    # Z-order: raise recorded targets per slide, highest index first (Bring to Front appends).
    lines += ['  set frontRaised to 0', '  set frontErr to ""']
    for slide in sorted(font_by_slide):
        lines += [f"  my obedRaiseSlide({slide})"]
    for slide in sorted(badge_by_slide):
        for entry in badge_by_slide[slide]:
            if entry.get("isTitle"):
                lines += [f"  my obedBadgeRaise({slide})"]
            else:
                kind_lit = _as_escape(str(entry.get("kind") or "shape"))
                idx = int(entry.get("index") or 0)
                lines += [f'  my obedRaiseItem({slide}, "{kind_lit}", {idx})']
    lines += [
        "  try",
        "    save theDoc",
        "  end try",
    ]
    if export_dir:
        lines += [
            f'  set exportFolder to POSIX file "{_as_escape(str(export_dir))}"',
            "  try",
            "    export theDoc to exportFolder as slide images with properties "
            "{image format:PNG, skipped slides:false}",
            '    set exported to "true"',
            "  end try",
        ]
    lines += [
        "  try",
        "    close theDoc saving yes",
        "  end try",
        "  end timeout",
        '  return "done=" & doneJobs & " skipped=" & skipJobs & " sized=" & sized '
        '& " sizeSkips=" & sizeSkips & " front=" & frontRaised & " dedupDeleted=" '
        '& dedupDeleted & " dedupShortfall=" & dedupShortfall & " frontErr=" '
        '& frontErr & " exported=" & exported & " sigFallback=" & sigFallbacks '
        '& " unresolved=" & unresolved & " detail=" & report',
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def _run_stat_finalize(
    dest: Path,
    jobs: list[dict],
    size_map: dict,
    export_dir: Path | None = None,
    group_removes: list[dict] | None = None,
    badge_raises: list[dict] | None = None,
) -> dict:
    """Run stat-finalize (dedup + sizes + bring-to-front). No-op if all three job lists are empty."""
    export_dir = Path(export_dir) if export_dir else None
    if export_dir is not None:
        export_dir.mkdir(parents=True, exist_ok=True)
    script = _build_stat_finalize_script(
        Path(dest),
        jobs,
        size_map or {},
        export_dir,
        group_removes=group_removes,
        badge_raises=badge_raises,
    )
    if not script:
        return {"ok": True, "skipped": True, "done": 0, "jobs": 0, "exported": False}
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    raw = (proc.stdout or "").strip()

    def _num(key: str) -> int:
        match = re.search(rf"{key}=(\d+)", raw)
        return int(match.group(1)) if match else 0

    ok = proc.returncode == 0 and bool(raw)
    if not ok:
        debug = Path(dest).with_suffix(".stat-finalize.applescript")
        debug.write_text(script, encoding="utf-8")
    preview_files: list[str] = []
    exported = False
    if export_dir is not None:
        from obed_edom.inspect import preview_pngs  # noqa: PLC0415

        pngs = preview_pngs(export_dir)
        preview_files = [p.name for p in pngs]
        exported = bool(pngs)
    return {
        "ok": ok,
        "jobs": len(jobs),
        "done": _num("done"),
        "skipped": _num("skipped"),
        "sized": _num("sized"),
        "sizeSkips": _num("sizeSkips"),
        "front": _num("front"),
        "dedupDeleted": _num("dedupDeleted"),
        "dedupShortfall": _num("dedupShortfall"),
        "sigFallback": _num("sigFallback"),
        "unresolved": _num("unresolved"),
        "exported": exported,
        "previewFiles": preview_files,
        "raw": raw,
        "stderr": proc.stderr or "",
    }


def read_template_stat_sizes(template: Path, *, use_cache: bool = True) -> dict[str, float]:
    """Template `{digits: pt}` map for grouped/loose numeric text. Cached by digest; JXA cannot see grouped numbers."""
    template = Path(template)
    cache_path: Path | None = None
    if use_cache:
        from obed_edom.baseline import (  # noqa: PLC0415
            deck_digest,
            template_stat_cache_path,
        )

        try:
            cache_path = template_stat_cache_path(deck_digest(template))
        except (FileNotFoundError, OSError):
            cache_path = None
        if cache_path is not None and cache_path.is_file():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): float(v) for k, v in data.items()}
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                pass
    sizes = _read_template_stat_sizes_via_keynote(template)
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(sizes), encoding="utf-8")
        except OSError:
            pass
    return sizes


def _read_template_stat_sizes_via_keynote(template: Path) -> dict[str, float]:
    template = Path(template)
    escaped = _as_escape(str(template))
    doc_name = _as_escape(template.name)
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  with timeout of 400 seconds",
        "  try",
        f'    close (every document whose name is "{doc_name}") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{escaped}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        '  set report to ""',
        "  repeat with s from 1 to count of slides of theDoc",
        "    tell slide s of theDoc",
        "      repeat with ti from 1 to count of text items",
        "        try",
        "          set _t to text item ti",
        '          set report to report & (object text of _t as string) & tab & (size of character 1 of object text of _t) & linefeed',
        "        end try",
        "      end repeat",
        "      repeat with gi from 1 to count of groups",
        "        set g to group gi",
        "        repeat with ti from 1 to count of text items of g",
        "          try",
        "            set _t to text item ti of g",
        '            set report to report & (object text of _t as string) & tab & (size of character 1 of object text of _t) & linefeed',
        "          end try",
        "        end repeat",
        "        repeat with sgi from 1 to count of groups of g",
        "          set sg to group sgi of g",
        "          repeat with ti from 1 to count of text items of sg",
        "            try",
        "              set _t to text item ti of sg",
        '              set report to report & (object text of _t as string) & tab & (size of character 1 of object text of _t) & linefeed',
        "            end try",
        "          end repeat",
        "        end repeat",
        "      end repeat",
        "    end tell",
        "  end repeat",
        "  try",
        "    close theDoc saving no",
        "  end try",
        "  end timeout",
        "  return report",
        "end tell",
        "end using terms from",
    ]
    script = "\n".join(lines)
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)], capture_output=True, text=True, check=False
        )
    finally:
        script_path.unlink(missing_ok=True)
    sizes: dict[str, float] = {}
    for line in (proc.stdout or "").splitlines():
        if "\t" not in line:
            continue
        content, _, raw_size = line.rpartition("\t")
        key = content.strip()
        if not key.isdigit():
            continue
        try:
            size = float(raw_size)
        except ValueError:
            continue
        if size > sizes.get(key, 0.0):
            sizes[key] = size
    return sizes


# Accessibility off: System Events cannot drive the app's menus.
_AX_DENIED_CODES = ("-1743", "-25211")


def _read_superscript_report(raw: str) -> dict:
    """Per-text-box check that later verse numbers now render at the seed's size."""
    body, _, tail = raw.partition(" gui=")
    gui_error, _, exported = tail.partition(" exported=")
    boxes: list[dict] = []
    for chunk in f" {body.strip()}".split(" s=")[1:]:
        fields: dict[str, float] = {}
        head = chunk.split()
        for token in head:
            key, sep, value = token.partition("=")
            if not sep or not key.startswith("c"):
                continue
            try:
                fields[key] = float(value)
            except ValueError:
                continue
        seed = fields.pop("c1", None)
        if seed is None or not fields:
            continue
        boxes.append(
            {
                "slide": head[0] if head else "",
                "seed": seed,
                "later": fields,
                "ok": all(abs(v - seed) <= 2 for v in fields.values()),
            }
        )
    return {
        "boxes": boxes,
        "allSuperscript": bool(boxes) and all(b["ok"] for b in boxes),
        "accessibilityDenied": any(code in gui_error for code in _AX_DENIED_CODES),
        "guiError": gui_error,
        "exported": exported.strip() == "true",
    }


def _plan_payload(slides: list[SlideSpec], output: Path, export_dir: Path | None, overlays: list[dict] | None = None) -> dict:
    return {
        "output": str(output),
        "exportDir": str(export_dir) if export_dir else "",
        "overlays": overlays or [],
        "superscriptJobs": _collect_superscript_jobs(slides),
        "slides": [
            {
                "master": s.master,
                "deck": s.deck,
                "isVerse": bool(s.is_verse),
                "textItems": {str(k): v for k, v in s.text_items.items()},
                "styledItems": {
                    str(idx): _runs_to_payload(runs) for idx, runs in s.styled_items.items()
                },
                "textItemWidths": {str(k): int(v) for k, v in s.text_item_widths.items()},
                "textItemHeights": {str(k): int(v) for k, v in s.text_item_heights.items()},
                "textItemPositions": {
                    str(k): [int(v[0]), int(v[1])] for k, v in s.text_item_positions.items()
                },
                "textItemFontSizes": {str(k): float(v) for k, v in s.text_item_font_sizes.items()},
                "itemPalettes": {str(k): v for k, v in s.item_palettes.items()},
                "extraTextItems": s.extra_text_items,
                "cue": s.cue_tag,
                "transition": (
                    {
                        "effect": s.transition.effect,
                        "duration": float(s.transition.duration),
                        "match": s.transition.match,
                    }
                    if s.transition
                    else None
                ),
            }
            for s in slides
        ],
    }


def _as_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", '" & return & "')
    )


def _build_applescript(plan: dict) -> str:
    output = plan["output"]
    export_dir = plan.get("exportDir") or ""
    # Close this deck by name first; `open` of a still-open stale copy returns that document, not the file we just wrote.
    doc_name = _as_escape(Path(output).name)
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  activate",
        "  try",
        f'    close (every document whose name is "{doc_name}") saving no',
        "    delay 0.3",
        "  end try",
        f'  set theFile to POSIX file "{_as_escape(output)}"',
        "  open theFile",
        "  delay 0.4",
        "  set theDoc to document 1",
        "  tell theDoc",
        "    set originalCount to count of slides",
        '    set missingMasters to ""',
        "    set createdCount to 0",
        "    set magicDonor to 0",
        "    repeat with donorI from 1 to originalCount",
        "      set donorProps to transition properties of slide donorI",
        "      if (transition effect of donorProps) is magic move then",
        "        set magicDonor to donorI",
        "        exit repeat",
        "      end if",
        "    end repeat",
    ]
    for spec in plan["slides"]:
        master = spec["master"]
        trans = spec.get("transition") or {}
        use_magic = trans.get("effect") == "magic_move"
        duration = float(trans.get("duration") or 1)
        lines.append("    try")
        lines.append(f'      set theMaster to master slide "{_as_escape(master)}"')
        if use_magic:
            lines += [
                "      if magicDonor > 0 then",
                "        duplicate slide magicDonor",
                "        set newSlide to slide (count of slides)",
                "        set base slide of newSlide to theMaster",
                "      else",
                "        set newSlide to make new slide with properties {base slide:theMaster}",
                "      end if",
            ]
        else:
            lines.append("      set newSlide to make new slide with properties {base slide:theMaster}")
        lines.append("      tell newSlide")
        styled_items = spec.get("styledItems") or {}
        styled_idxs = {int(k) for k in styled_items}
        font_sizes = spec.get("textItemFontSizes") or {}
        item_palettes = spec.get("itemPalettes") or {}
        for key, runs in styled_items.items():
            idx = int(key)
            first_super, rest, prepared = _prepare_styled_runs(runs)
            palette_name = item_palettes.get(str(idx), "")
            mode = _text_seed_mode(first_super, spec, palette_name)
            _append_seeded_text(lines, idx, first_super, rest, mode=mode)
        for key, value in sorted((spec.get("textItems") or {}).items(), key=lambda kv: int(kv[0])):
            idx = int(key)
            if idx in styled_idxs:
                continue
            size = float(font_sizes[str(idx)]) if str(idx) in font_sizes else None
            _append_plain_text(lines, idx, value if value is not None else "", size)
        palette_default = STYLE_PALETTES.get(spec.get("deck") or "dsk", STYLE_PALETTES["dsk"])
        for key, runs in styled_items.items():
            idx = int(key)
            first_super, rest, prepared = _prepare_styled_runs(runs)
            total = sum(len(r.get("text") or "") for r in prepared)
            if total < 1:
                continue
            palette = STYLE_PALETTES.get(item_palettes.get(str(idx), ""), palette_default)
            normal = palette.get("normal") or palette_default["normal"]
            if str(idx) in font_sizes:
                body_size: float | None = float(font_sizes[str(idx)])
            elif normal.get("size") is not None:
                body_size = float(normal["size"])
            else:
                body_size = None
            _append_styling_pass(lines, idx, prepared, palette, body_size)
        # Geometry after text: 0×0 POST placeholders ignore moves until they have content.
        for key, pair in sorted((spec.get("textItemPositions") or {}).items(), key=lambda kv: int(kv[0])):
            idx = int(key)
            x, y = int(pair[0]), int(pair[1])
            lines.append("        try")
            lines.append(f"          set position of text item {idx} to {{{x}, {y}}}")
            lines.append("        end try")
        for key, width in sorted((spec.get("textItemWidths") or {}).items(), key=lambda kv: int(kv[0])):
            idx = int(key)
            lines.append("        try")
            lines.append(f"          set width of text item {idx} to {int(width)}")
            lines.append("        end try")
        for key, height in sorted((spec.get("textItemHeights") or {}).items(), key=lambda kv: int(kv[0])):
            idx = int(key)
            lines.append("        try")
            lines.append(f"          set height of text item {idx} to {int(height)}")
            lines.append("        end try")
        for extra in spec.get("extraTextItems") or []:
            _append_created_text_item(lines, extra)
        if use_magic:
            lines += [
                "        try",
                "          if magicDonor is 0 then",
                "            set transition properties to {transition effect:magic move, "
                f"transition duration:{duration}}}",
                "          end if",
                "        end try",
            ]
        lines.append("      end tell")
        lines.append("      set createdCount to createdCount + 1")
        lines.append("    on error")
        lines.append(f'      set missingMasters to missingMasters & "{_as_escape(master)}" & linefeed')
        lines.append("    end try")

    lines += [
        "    repeat originalCount times",
        "      delete slide 1",
        "    end repeat",
    ]

    overlays = plan.get("overlays") or []
    if overlays:
        lines += [
            "    set slideW to (slide width of theDoc)",
            "    set slideH to (slide height of theDoc)",
        ]
        for overlay in overlays:
            idx = int(overlay.get("slideIndex", 0)) + 1
            x = float(overlay.get("x", 0))
            y = float(overlay.get("y", 0.45))
            w = float(overlay.get("w", 1))
            h = float(overlay.get("h", 0.55))
            opacity = int(overlay.get("opacity", 50))
            lines += [
                "    try",
                f"      tell slide {idx}",
                "        set shp to make new shape with properties {shape type:rectangle}",
                f"        set position of shp to {{slideW * {x}, slideH * {y}}}",
                f"        set width of shp to (slideW * {w})",
                f"        set height of shp to (slideH * {h})",
                "        try",
                "          set fill type of shp to color fill",
                "        end try",
                "        try",
                "          set fill color of shp to {0, 0, 0}",
                "        end try",
                "        try",
                f"          set opacity of shp to {opacity}",
                "        end try",
                "      end tell",
                "    end try",
            ]

    lines += [
        "  end tell",
        "  save theDoc",
        '  set exported to "false"',
    ]
    # Pass 2 exports and closes. Exporting here would show verse numbers pre-superscript.
    hand_off = bool(plan.get("superscriptJobs")) and bool(plan.get("superscriptFix"))
    if export_dir and not hand_off:
        lines += [
            f'  set exportFolder to POSIX file "{_as_escape(export_dir)}"',
            "  try",
            "    export theDoc to exportFolder as slide images with properties {image format:PNG, skipped slides:false}",
            '    set exported to "true"',
            "  end try",
        ]
    elif export_dir:
        lines.append('  set exported to "deferred"')
    if not hand_off:
        lines += [
            "  try",
            "    close theDoc saving yes",
            "  end try",
        ]
    lines += [
        "  return (createdCount as text) & tab & exported & tab & missingMasters",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def run_applescript(plan: dict) -> dict:
    script = _build_applescript(plan)
    # File + LaunchServices, not stdin: uvicorn workers break osascript's HIServices and Keynote's dictionary never loads.
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osascript", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        debug = Path(plan["output"]).with_suffix(".applescript")
        debug.write_text(script, encoding="utf-8")
        raise RuntimeError(
            "Keynote AppleScript failed:\n"
            + (proc.stderr or "")
            + "\n"
            + (proc.stdout or "")
            + f"\nScript saved to {debug}"
        )
    raw = (proc.stdout or "").strip()
    parts = raw.split("\t")
    created = int(parts[0]) if parts and parts[0].isdigit() else 0
    export_state = parts[1].strip().lower() if len(parts) > 1 else "false"
    missing = []
    if len(parts) > 2:
        missing = [m.strip() for m in parts[2].splitlines() if m.strip()]
    return {
        "ok": not missing and created > 0,
        "slideCount": created,
        "exported": export_state == "true",
        "exportDeferred": export_state == "deferred",
        "missingMasters": missing,
        "raw": raw,
    }


def generate_deck(
    slides: list[SlideSpec],
    template: str | Path,
    dest: Path,
    export_dir: Path | None = None,
    overlays: list[dict] | None = None,
    *,
    superscript_fix: bool = True,
) -> dict:
    src = Path(template).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"Template not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copy_template(src, dest)
    plan = _plan_payload(slides, dest, export_dir, overlays)
    # Pass 1 leaves the deck open (and defers export) only if pass 2 follows.
    plan["superscriptFix"] = superscript_fix
    result = run_applescript(plan)
    result["key"] = str(dest)
    if superscript_fix:
        super_result = _run_superscript_fix(dest, plan.get("superscriptJobs") or [], export_dir)
        if result.get("exportDeferred"):
            result["exported"] = bool(super_result.get("exported"))
    else:
        super_result = {"ok": True, "skipped": True, "reason": "overlay_regen"}
    result["superscriptFix"] = super_result
    return result


_SKIPPED_DECK = {
    "skipped": True,
    "exported": True,
    "missingMasters": [],
    "superscriptFix": {"ok": True, "skipped": True, "reason": "no_template"},
}


def generate_both(
    docx: Path,
    lw_slides: list[SlideSpec],
    dsk_slides: list[SlideSpec],
    export: bool = True,
    *,
    lw_template: Path | str | None = None,
    dsk_template: Path | str | None = None,
) -> tuple[Path, Path | None, Path | None, dict, dict]:
    lw_src = select_deck_template(lw_template)
    dsk_src = select_deck_template(dsk_template)
    if lw_src is None and dsk_src is None:
        raise FileNotFoundError(
            "At least one Keynote template is required (LW, DSK, or both)."
        )
    out_dir = output_dir_for(docx)
    stem = _stem(docx)
    lw_path = out_dir / f"{stem}_LW.key"
    dsk_path = out_dir / f"{stem}_DSK.key"
    lw_export = out_dir / "previews" / "lw" if export and lw_src else None
    dsk_export = out_dir / "previews" / "dsk" if export and dsk_src else None
    if lw_export:
        lw_export.mkdir(parents=True, exist_ok=True)
    if dsk_export:
        dsk_export.mkdir(parents=True, exist_ok=True)
    lw_result = generate_deck(lw_slides, lw_src, lw_path, lw_export) if lw_src else dict(_SKIPPED_DECK)
    dsk_result = generate_deck(dsk_slides, dsk_src, dsk_path, dsk_export) if dsk_src else dict(_SKIPPED_DECK)
    return (
        out_dir,
        lw_path if lw_src else None,
        dsk_path if dsk_src else None,
        lw_result,
        dsk_result,
    )
