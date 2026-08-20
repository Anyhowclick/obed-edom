from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from sermon_slides.models import SlideSpec
from sermon_slides.paths import find_repo_root, template_path
from sermon_slides.slide_map import load_masters


def _stem(docx: Path) -> str:
    return docx.stem.replace(" ", "_")


def output_dir_for(docx: Path, root: Path | None = None) -> Path:
    root = root or find_repo_root()
    out = root / "output" / _stem(docx)
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
    # Point titles keep the template serif; only colour (and size) is overridden.
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

    Later verse numbers stay ASCII. Unicode superscripts ² and ⁷/⁸ come from
    different code charts, so mixing them makes 27/28 look like mismatched
    digit sizes. Later numbers copy superscript from the template seed character.
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
    """How to write a text box so SuperScript does not leak onto body copy.

    keep_super: verse number uses the template seed character.
    body_only: no verse number (continuation / mid-verse split); drop the seed.
    replace: point titles and unseeded POST boxes — replace the whole object.
    """
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

    The VERSES master stores a superscript seed as character 1. Replacing the
    whole object text copies that superscript onto every character. Keep the
    seed only when the template actually has a larger body-sized character.
    Point titles and DSK POST verse boxes have no seed — replace the box.
    Continuation slides have no leading verse number; drop the seed and write
    onto the body-sized character so Regular copy stays on the baseline.
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
    """Apply per-run colours/fonts without a blanket Regular-font sweep over verse numbers."""
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


# Keynote's Find bar is the only way to place a text selection from a script, so
# each later verse number is located by the copy that immediately follows it.
_ANCHOR_MAX_CHARS = 24


def _verse_anchor(prepared: list[dict], run_index: int) -> str:
    """Text right after a verse number, used as the Find needle that selects it."""
    tail = "".join((r.get("text") or "") for r in prepared[run_index + 1 :])
    anchor = tail.split("\n", 1)[0][:_ANCHOR_MAX_CHARS]
    return anchor if anchor.strip() else ""


def _seed_verse_job(prepared: list[dict]) -> dict | None:
    """The first verse number, whose character style pass 2 copies from.

    The template applies its verse-number character style ("SuperScript" on LW,
    "Verse Number" on DSK) to this one only, so it is the donor for the rest.
    """
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
    """Character positions and digits for verse numbers after the first superscript seed."""
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
            # Only keep work pass 2 can actually do: pass 1 hands the open deck
            # over whenever this list is non-empty, so an entry it would skip
            # would leave the deck open, unexported and never closed.
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
    """One Find pass per distinct anchor, repeated once per slide that shows that verse."""
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
    """Place a selection on the digits that sit just before ``anchor``.

    Find is the only scripted way to place a text selection: find the anchor,
    collapse the selection to its left edge, then extend back over the digits.
    """
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
    """Copy the seed verse number's character style, then paste it onto the rest.

    Keynote's AppleScript dictionary has no style support at all -- no character
    styles, and superscript is not a character property. So the deck's own
    verse-number character style ("SuperScript" on the LW template, "Verse
    Number" on DSK) can only be applied through the UI, which needs
    Accessibility. Format > Copy Style on the first verse number and Paste Style
    onto the later ones carries that named style across, which is why no style
    name is hardcoded here: whatever the template puts on the first number is
    what the rest inherit.

    Each anchor is applied once per occurrence, because Find cycles through
    matches and the same verse box is reused on more than one slide (a magic-move
    POST slide repeats it). Applying once would style a single instance and leave
    the others on the baseline.
    """
    seed_anchor = _as_escape(seed["anchor"])
    seed_len = int(seed["len"])
    lines += [
        "try",
        '  tell application "System Events" to tell process "Keynote"',
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
            '    tell application "System Events" to tell process "Keynote"',
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

    Pass 1 saves but does not close, so ``open`` here is a bring-to-front on the
    document that is already loaded rather than a reopen; it only actually loads
    the file if something else closed it in between.
    """
    plan = _superscript_anchor_plan(jobs)
    seed = next((job.get("seed") for job in jobs if job.get("seed")), None)
    if not plan or not seed:
        return ""
    escaped = _as_escape(str(key_path))
    lines = [
        'set guiError to ""',
        'using terms from application "Keynote"',
        'tell application "Keynote"',
        "  activate",
        f'  set theFile to POSIX file "{escaped}"',
        "  open theFile",
        "  delay 0.8",
        "end tell",
        "end using terms from",
    ]
    _append_superscript_gui_pass(lines, seed, plan)
    lines += [
        'using terms from application "Keynote"',
        'tell application "Keynote"',
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
        # Pass 1 deferred the export so the previews show the styled numbers.
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


# Accessibility is off: System Events cannot drive Keynote's menus.
_AX_DENIED_CODES = ("-1743", "-25211")


def _read_superscript_report(raw: str) -> dict:
    """Per-text-box check that later verse numbers now render at the seed's size."""
    body, _, tail = raw.partition(" gui=")
    gui_error, _, exported = tail.partition(" exported=")
    boxes: list[dict] = []
    # Leading space is stripped from stdout, so re-pad before splitting on the separator.
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
    # Python has already overwritten this path with a fresh template copy, so a
    # document still open from an earlier run is stale: opening the file would
    # hand back that stale document and the rebuild fails with -10000. Discard it
    # without saving -- only ever this deck, which we just regenerated.
    doc_name = _as_escape(Path(output).name)
    lines = [
        'using terms from application "Keynote"',
        'tell application "Keynote"',
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
    # Pass 2 restyles this deck, then exports and closes it. Exporting here too
    # would render every slide twice and show the verse numbers pre-superscript.
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
    # File + LaunchServices, not stdin: uvicorn's worker thread makes
    # osascript's HIServices/clipboard connection fail, and then Keynote's
    # dictionary never loads (syntax error on ``properties``).
    subprocess.run(["open", "-a", "Keynote"], check=False)
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
    template_rel: str,
    dest: Path,
    export_dir: Path | None = None,
    overlays: list[dict] | None = None,
    *,
    superscript_fix: bool = True,
) -> dict:
    src = template_path(template_rel)
    if not src.exists():
        raise FileNotFoundError(f"Template not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _copy_template(src, dest)
    plan = _plan_payload(slides, dest, export_dir, overlays)
    # Pass 1 only leaves the deck open (and defers its export) if pass 2 follows.
    plan["superscriptFix"] = superscript_fix
    result = run_applescript(plan)
    result["key"] = str(dest)
    if superscript_fix:
        super_result = _run_superscript_fix(dest, plan.get("superscriptJobs") or [], export_dir)
        # Pass 1 handed the export to pass 2, so take the outcome from there.
        if result.get("exportDeferred"):
            result["exported"] = bool(super_result.get("exported"))
    else:
        super_result = {"ok": True, "skipped": True, "reason": "overlay_regen"}
    result["superscriptFix"] = super_result
    return result


def generate_both(
    docx: Path,
    lw_slides: list[SlideSpec],
    dsk_slides: list[SlideSpec],
    export: bool = True,
) -> tuple[Path, Path, Path, dict, dict]:
    masters = load_masters()
    out_dir = output_dir_for(docx)
    stem = _stem(docx)
    lw_path = out_dir / f"{stem}_LW.key"
    dsk_path = out_dir / f"{stem}_DSK.key"
    lw_export = out_dir / "previews" / "lw" if export else None
    dsk_export = out_dir / "previews" / "dsk" if export else None
    if lw_export:
        lw_export.mkdir(parents=True, exist_ok=True)
    if dsk_export:
        dsk_export.mkdir(parents=True, exist_ok=True)
    lw_result = generate_deck(lw_slides, masters["lw"]["template"], lw_path, lw_export)
    dsk_result = generate_deck(dsk_slides, masters["dsk"]["template"], dsk_path, dsk_export)
    return out_dir, lw_path, dsk_path, lw_result, dsk_result
