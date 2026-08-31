from __future__ import annotations

import re
from pathlib import Path

import yaml

from obed_edom.bible import check_bible, check_slide_passages
from obed_edom.inspect import highlighted_markup
from obed_edom.models import Flag, OutlineDoc, Paragraph, Run, SlideSpec
from obed_edom.rendered import ocr_unavailable

PACKAGE_DIR = Path(__file__).resolve().parent
RULES_PATH = PACKAGE_DIR / "validation_rules.yaml"

MONTHS = (
    "Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|"
    "Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December"
)
PUNCT_ONLY = re.compile(r"^[\s.,;:!?…'\"“”‘’()\[\]—–-]+$")
HYPHEN_YEAR_SPAN = re.compile(r"\b(\d{3,4})-(\d{2,4})\b")
EMDASH_YEAR_SPAN = re.compile(r"\b(\d{3,4})—(\d{2,4})\b")
HYPHEN_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})-(\d{{1,2}})\s+({MONTHS})\b", re.I)
QUOTE_ATTR = re.compile(
    r"(?:^|\n)\s*[—–\-]\s*([A-Z][^\n]{1,80})$",
)
NAME_WITH_SPAN = re.compile(
    r"^([A-Za-z][A-Za-z .'-]{1,60})\s+(\d{3,4})\s*[–—-]\s*(\d{3,4})$"
)
LOWER_GOD = re.compile(r"(?<![A-Za-z])god(?![A-Za-z])")
LOWER_FATHER = re.compile(r"(?<![A-Za-z])father(?![A-Za-z])")


_RULES_CACHE: dict | None = None


def load_rules() -> dict:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}
    return _RULES_CACHE


def rule_severity(rule: str, default: str = "warning") -> str | None:
    """Configured severity for a rule id, or None when the rule is switched off."""
    configured = (load_rules().get("rules") or {}).get(rule, default)
    text = str(configured).strip().lower()
    if text in {"off", "none", "false", "silent"}:
        return None
    if text in {"info", "warning", "error", "success"}:
        return text
    return default


def rule_title(rule: str) -> str:
    named = (load_rules().get("titles") or {}).get(rule)
    if named:
        return str(named)
    return " ".join(part[:1].upper() + part[1:] for part in rule.replace(".", " ").replace("_", " ").split() if part)


def make_flag(
    rule: str,
    category: str,
    message: str,
    *,
    default: str = "warning",
    location: str = "",
    slide: int | None = None,
    deck: str = "",
    evidence: str = "",
    resolved: str | None = None,
) -> Flag | None:
    """Build a Flag honouring the configured severity. None when the rule is off."""
    severity = rule_severity(rule, default)
    if severity is None:
        return None
    return Flag(
        severity,  # type: ignore[arg-type]
        category,
        message,
        location=location,
        resolved=resolved,
        rule=rule,
        slide=slide,
        deck=deck,
        evidence=evidence,
    )


def flag_dict(flag: Flag) -> dict:
    return {
        "severity": flag.severity,
        "category": flag.category,
        "message": flag.message,
        "location": flag.location,
        "resolved": flag.resolved,
        "rule": flag.rule,
        "title": rule_title(flag.rule) if flag.rule else "",
        "slide": flag.slide,
        "deck": flag.deck,
        "evidence": flag.evidence,
    }


def outline_from_text(text: str, label: str = "inspect") -> OutlineDoc:
    return OutlineDoc(
        path=Path(label),
        paragraphs=[Paragraph(runs=[Run(text=text)])],
        full_text=text,
    )


def validate_outline(outline: OutlineDoc) -> list[Flag]:
    flags = list(check_bible(outline))
    flags.extend(validate_style_text(outline.full_text, location="outline"))
    for para in outline.paragraphs:
        flags.extend(_punctuation_style_flags(para, location="outline"))
    return flags


def validate_outline_paragraphs(outline: OutlineDoc) -> list[Flag]:
    """Outline findings pinned to the paragraph they are about.

    `validate_outline` reports against the whole document, which is fine for a
    review PDF but leaves the dashboard nothing to sit a finding beside. Style
    rules run per paragraph here; the Bible check stays whole-document because
    its cursor is what resolves a relative reference like "Instead, v33", and
    its hits are mapped back afterwards.

    Scoped with `deck="outline"` and a 1-based paragraph in `slide`, so the
    existing Flag plumbing carries them with no new fields.
    """
    flags: list[Flag] = []
    for para in outline.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        for flag in validate_style_text(
            para.text,
            location=f"outline paragraph {para.index + 1}",
            deck="outline",
            slide=para.index + 1,
        ):
            flags.append(flag)
        flags.extend(
            _punctuation_style_flags(
                para,
                location=f"outline paragraph {para.index + 1}",
                deck="outline",
                slide=para.index + 1,
            )
        )
    flags.extend(_bible_flags_by_paragraph(outline))
    return dedupe_flags(flags)


def _bible_flags_by_paragraph(outline: OutlineDoc) -> list[Flag]:
    """Re-pin whole-document Bible findings onto their paragraph.

    `check_bible` sets `location` to the line it found, and `full_text` is a
    newline join of the paragraphs, so the line is the paragraph.
    """
    lookup: dict[str, int] = {}
    for para in outline.paragraphs:
        key = (para.text or "").strip()
        if key and key not in lookup:
            lookup[key] = para.index
    out: list[Flag] = []
    for flag in check_bible(outline):
        index = lookup.get((flag.location or "").strip())
        if index is None:
            out.append(Flag(**{**flag.__dict__, "deck": "outline"}))
            continue
        out.append(
            Flag(**{**flag.__dict__, "deck": "outline", "slide": index + 1})
        )
    return out


def validate_inspect(
    payload: dict,
    *,
    location_prefix: str = "",
    deck: str = "",
    previews: list[Path] | None = None,
    evidence_dir: Path | None = None,
    use_ocr: bool = True,
    check_passages: bool = True,
    rendered: dict[int, str] | None = None,
    ocr: dict[int, str] | None = None,
) -> list[Flag]:
    """House-style checks for one inspected Keynote. Never modifies the deck."""
    from obed_edom.diff_keynotes import map_preview_pngs  # noqa: PLC0415
    from obed_edom.rendered import render_slide  # noqa: PLC0415

    flags: list[Flag] = []
    all_slides = payload.get("slides") or []
    prefix = location_prefix or Path(payload.get("path") or "keynote").name
    deck = deck or ("lw" if float(payload.get("slideWidth") or 0) >= 3000 else "dsk")
    png_map = map_preview_pngs(all_slides, list(previews or []))
    size = (float(payload.get("slideWidth") or 0), float(payload.get("slideHeight") or 0))

    rendered_map: dict[int, str] = dict(rendered or {})
    seen: dict[int, str] = dict(ocr or {})
    for index, slide in enumerate(all_slides):
        if slide.get("skipped"):
            continue
        if index in rendered_map:
            continue
        shot = render_slide(slide, png_map.get(index), size, use_ocr=use_ocr)
        rendered_map[index] = shot.text
        if shot.ocr_used:
            seen[index] = shot.ocr

    rules = load_rules()
    for index, slide in enumerate(all_slides):
        if slide.get("skipped"):
            continue
        num = int(slide.get("number") or slide.get("index", index) + 1)
        loc = f"{prefix} slide {num}"
        body = rendered_map.get(index, "")
        flags.extend(_trinity_flags(body, loc, rules, deck, slide=num))
        flags.extend(_book_name_flags(body, loc, rules, deck, slide=num))
        flags.extend(_date_flags(body, loc, deck, slide=num))
        flags.extend(_highlight_punctuation_flags(slide, loc, num, deck))
        flags.extend(_quote_flags(body, loc, slide=num, deck=deck))
        flags.extend(_glossary_flags(body, loc, num, deck))
        flags.extend(_inspect_overflow_flags(slide, loc, payload, num, deck))

    flags.extend(
        _bounds_flags(
            payload, prefix, deck=deck, png_map=png_map, evidence_dir=evidence_dir
        )
    )
    if check_passages:
        flags.extend(
            check_slide_passages(payload, rendered_map, prefix, deck, ocr=seen, pngs=png_map)
        )
    if use_ocr and png_map:
        problem = ocr_unavailable()
        if problem:
            unavailable = make_flag(
                "ocr.unavailable",
                "ocr",
                f"{problem} Text baked into images or grouped on the slide was not checked.",
                default="info",
                location=prefix,
                deck=deck,
            )
            if unavailable:
                flags.append(unavailable)
    return dedupe_flags(flags)


def dedupe_flags(flags: list[Flag]) -> list[Flag]:
    """One finding per slide per message.

    A wall slide holds the same text box twice, once per side of the center
    panel, so every box-level rule would otherwise report itself twice.
    """
    seen: set[tuple] = set()
    out: list[Flag] = []
    for flag in flags:
        key = (flag.rule, flag.slide, flag.deck, flag.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(flag)
    return out


def _glossary_flags(text: str, location: str, slide: int, deck: str) -> list[Flag]:
    """Catch near-misses of house proper nouns, e.g. First Loved Conference."""
    entries = load_rules().get("glossary") or []
    if not text.strip() or not entries:
        return []
    flags: list[Flag] = []
    for entry in entries:
        wanted = str(entry).strip()
        if not wanted or wanted.lower() in text.lower():
            continue
        words = wanted.split()
        if len(words) < 2:
            continue
        # Anchor on the distinctive tail so "First Loved Conference" is compared
        # with "First Love Conference" but unrelated slides are left alone.
        anchor = re.escape(words[-1])
        head = re.escape(words[0])
        near = re.search(rf"{head}\w*(?:\s+\S+){{0,2}}\s+{anchor}", text, re.I)
        if not near:
            continue
        found = near.group(0)
        if fold_spaces(found).lower() == fold_spaces(wanted).lower():
            continue
        flag = make_flag(
            "style.glossary",
            "glossary",
            f'House spelling is "{wanted}", this slide reads "{found}".',
            location=location,
            slide=slide,
            deck=deck,
        )
        if flag:
            flags.append(flag)
    return flags


def fold_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def slide_plain(slide: dict) -> str:
    parts = []
    for item in slide.get("items") or []:
        t = (item.get("text") or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _overflow_cfg() -> dict:
    rules = load_rules().get("overflow") or {}
    return {
        "enabled": rules.get("enabled", True),
        "height_slack_px": float(rules.get("height_slack_px", 8)),
        "char_em": float(rules.get("char_em", 0.58)),
        "line_height": float(rules.get("line_height", 1.18)),
        "wrap_tolerance": float(rules.get("wrap_tolerance", 1.15)),
    }


def _wrap_line_count(
    text: str, box_width: float, font_size: float, em: float, tolerance: float = 1.15
) -> int:
    """Estimate how many display lines the text occupies.

    Trusts the authored line breaks: `objectText()` returns hard paragraph
    breaks as `\\n` (soft/visual wraps are not returned), so a box that was laid
    out with its lines already breaking where the author put them should be
    counted as those lines, not re-wrapped from scratch. Re-wrapping with a
    per-character width guess is where the noise came from — a proportional font
    is narrower than `char_em` assumes, so a line that fits was split into two
    and the box looked overflowed. A paragraph is only wrapped when its estimated
    width clearly exceeds the box (a genuinely flowing line with no breaks, e.g.
    a pasted MSG paragraph), and then by word packing.
    """
    if not (text or "").strip():
        return 0
    if box_width <= 0 or font_size <= 0:
        return text.count("\n") + 1
    cpl = max(8, int(box_width / (font_size * em)))
    lines = 0
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = para.split()
        if not words:
            lines += 1
            continue
        if len(para) * font_size * em <= box_width * tolerance:
            # The authored line fits its box; keep it as one line.
            lines += 1
            continue
        current = 0
        sub = 1
        for word in words:
            extra = len(word) + (1 if current else 0)
            if current and current + extra > cpl:
                sub += 1
                current = len(word)
            else:
                current += extra
        lines += sub
    return max(1, lines)


def _text_needed_height(text: str, box_width: float, font_size: float, cfg: dict) -> float:
    lines = _wrap_line_count(
        text, box_width, font_size, float(cfg["char_em"]), float(cfg["wrap_tolerance"])
    )
    return lines * font_size * float(cfg["line_height"])


def _verse_char_limit(spec: SlideSpec, masters: dict) -> int:
    cfg = masters.get(spec.deck) or {}
    if spec.deck == "dsk" and spec.context == "offering":
        return int(cfg.get("offering_verse_char_max", 190))
    if spec.deck == "dsk":
        return int(cfg.get("verse_char_max", 220))
    return int(cfg.get("verse_char_max", 320))


def _overflow_message(spec: SlideSpec, n: int, limit: int) -> str:
    preview = re.sub(r"\s+", " ", spec.body or "").strip()
    if len(preview) > 72:
        preview = preview[:72].rstrip() + "…"
    continued = spec.semantic_tag == "VERSE-CONTINUED"
    where = "lower-third" if spec.deck == "dsk" else "LED wall"
    extra = (
        " This [VERSE-CONTINUED] slide keeps the full verse; how overflow should be handled is not decided yet."
        if continued
        else " How overflow should be handled is not decided yet."
    )
    return (
        f"Text may overflow the {where} ({n} characters; box is sized for about {limit})."
        f"{extra} {preview}"
    )


def validate_slide_specs(lw: list[SlideSpec], dsk: list[SlideSpec], masters: dict | None = None) -> list[Flag]:
    """Flag copy that will not fit the mapped Keynote box. Does not rewrite decks."""
    cfg = _overflow_cfg()
    if not cfg["enabled"]:
        return []
    from obed_edom.slide_map import load_masters

    masters = masters or load_masters()
    flags: list[Flag] = []
    for deck_name, slides in (("LW", lw), ("DSK", dsk)):
        for index, spec in enumerate(slides, start=1):
            if spec.is_graphic and not spec.body:
                continue
            if spec.is_verse:
                n = len(spec.body or "")
                limit = _verse_char_limit(spec, masters)
                over_chars = n > limit
                height_over = False
                box_w = 0.0
                box_h = 0.0
                font = 0.0
                needed = 0.0
                if spec.styled_items:
                    body_idx = next(iter(spec.styled_items))
                    box_w = float(spec.text_item_widths.get(body_idx) or 0)
                    box_h = float(spec.text_item_heights.get(body_idx) or 0)
                    font = float(spec.text_item_font_sizes.get(body_idx) or 0)
                    if not font:
                        palette = "dsk" if spec.deck == "dsk" else "lw"
                        font = 45.0 if palette == "dsk" else 70.0
                    if box_w > 0 and box_h > 0 and font > 0 and spec.body:
                        needed = _text_needed_height(spec.body, box_w, font, cfg)
                        height_over = needed > box_h + cfg["height_slack_px"]
                if over_chars or height_over:
                    loc = f"{deck_name} slide {index} ({spec.master})"
                    flags.append(
                        Flag("warning", "overflow", _overflow_message(spec, n, limit), location=loc)
                    )
                continue
            if spec.role in {"pre", "post"} and spec.body:
                max_lines = 3 if spec.role == "post" else 2
                lines = [ln for ln in (spec.body or "").split("\n") if ln.strip()]
                if len(lines) > max_lines:
                    loc = f"{deck_name} slide {index} ({spec.master})"
                    flags.append(
                        Flag(
                            "warning",
                            "overflow",
                            f"Point text may overflow ({len(lines)} lines in a {max_lines}-line box). "
                            "How overflow should be handled is not decided yet.",
                            location=loc,
                        )
                    )
    return flags


def _inspect_overflow_flags(
    slide: dict, location: str, payload: dict, number: int | None = None, deck: str = ""
) -> list[Flag]:
    cfg = _overflow_cfg()
    if not cfg["enabled"]:
        return []
    # Keynote grows a text box to fit its copy, so an over-count against box_h
    # cannot tell a wrapped-but-visible box from a clipped one. What is actually
    # broken is text that leaves the canvas, so flag only when the box runs off
    # the top or bottom edge. slideHeight defaults to the 1080-tall center wall.
    slide_height = float(payload.get("slideHeight") or 1080)
    # A box laid out flush to an edge can end a couple of px past it from leading
    # and rounding; require a small margin so that does not false-positive.
    slack = cfg["height_slack_px"]
    flags: list[Flag] = []
    for item in slide.get("items") or []:
        if (item.get("kind") or "text") != "text":
            continue
        text = (item.get("text") or "").strip()
        if len(text) < 24:
            continue
        box_w = float(item.get("w") or 0)
        box_h = float(item.get("h") or 0)
        if box_w < 40 or box_h < 20:
            continue
        top = float(item.get("y") or 0)
        bottom = top + box_h
        if bottom > slide_height + slack:
            edge, edge_pos, pos = "bottom", "bottom", bottom
        elif top < -slack:
            edge, edge_pos, pos = "top", "top", top
        else:
            continue
        preview = re.sub(r"\s+", " ", text)
        if len(preview) > 72:
            preview = preview[:72].rstrip() + "…"
        _keep(
            flags,
            make_flag(
                "overflow.text",
                "overflow",
                f"Text runs off the {edge} of the screen (box {edge_pos} {int(pos)}px, "
                f"screen is {int(slide_height)}px). {preview}",
                location=location,
                slide=number,
                deck=deck,
            ),
        )
    return flags


def validate_style_text(
    text: str, *, location: str = "", deck: str = "", slide: int | None = None
) -> list[Flag]:
    rules = load_rules()
    flags: list[Flag] = []
    flags.extend(_trinity_flags(text, location, rules, deck, slide=slide))
    flags.extend(_book_name_flags(text, location, rules, deck, slide=slide))
    flags.extend(_date_flags(text, location, deck, slide=slide))
    flags.extend(_quote_flags(text, location, deck=deck, slide=slide))
    return flags


def _keep(flags: list[Flag], flag: Flag | None) -> None:
    if flag is not None:
        flags.append(flag)


def _trinity_flags(
    text: str, location: str, rules: dict, deck: str = "", *, slide: int | None = None
) -> list[Flag]:
    flags: list[Flag] = []
    for match in LOWER_GOD.finditer(text):
        _keep(
            flags,
            make_flag(
                "style.trinity",
                "trinity",
                "Trinity word should be caps: God",
                location=location,
                slide=slide,
                deck=deck,
            ),
        )
    # Avoid every “father”; flag lowercase “father” near God/Lord/pray.
    window = 40
    for match in LOWER_FATHER.finditer(text):
        ctx = text[max(0, match.start() - window) : match.end() + window].lower()
        if any(w in ctx for w in ("god", "lord", "heaven", "pray", "almighty")):
            _keep(
                flags,
                make_flag(
                    "style.trinity",
                    "trinity",
                    "Trinity word should be caps: Father",
                    location=location,
                    slide=slide,
                    deck=deck,
                ),
            )
    if re.search(r"\bthe son\b", text) and not re.search(r"\bthe Son\b", text):
        _keep(
            flags,
            make_flag(
                "style.trinity",
                "trinity",
                "Trinity word should be caps: Son",
                location=location,
                slide=slide,
                deck=deck,
            ),
        )
    if re.search(r"\b(says?|declares?|speaks?)\s+the\s+Lord\b", text, re.I):
        if re.search(r"\bmy\b", text) and not re.search(r"\bMy\b", text):
            _keep(
                flags,
                make_flag(
                    "style.trinity",
                    "trinity",
                    "If God is speaking, associated 'My' should be caps (heuristic).",
                    default="info",
                    location=location,
                    slide=slide,
                    deck=deck,
                ),
            )
    return flags


def _book_name_flags(
    text: str, location: str, rules: dict, deck: str = "", *, slide: int | None = None
) -> list[Flag]:
    flags: list[Flag] = []
    mapping = (rules.get("book_names") or {}) if rules else {}
    # Psalms → Psalm (as a book label, not the word in a sentence like "the psalms")
    if re.search(r"\bPsalms\s+\d", text) or re.search(r"\bPsalms\b", text):
        want = mapping.get("Psalms", "Psalm")
        _keep(
            flags,
            make_flag(
                "style.book_name", "book_name", f"Use '{want}', not 'Psalms'.",
                location=location, slide=slide, deck=deck,
            ),
        )
    # House style: Revelations, not Revelation
    if re.search(r"\bRevelation\s+\d", text) and not re.search(r"\bRevelations\s+\d", text):
        want = mapping.get("Revelation", "Revelations")
        _keep(
            flags,
            make_flag(
                "style.book_name", "book_name", f"Use '{want}', not 'Revelation'.",
                location=location, slide=slide, deck=deck,
            ),
        )
    return flags


def _date_flags(text: str, location: str, deck: str = "", *, slide: int | None = None) -> list[Flag]:
    flags: list[Flag] = []
    for match in HYPHEN_YEAR_SPAN.finditer(text):
        _keep(
            flags,
            make_flag(
                "style.date",
                "date",
                f"Date period should use an en dash: {match.group(1)}–{match.group(2)}",
                location=location,
                slide=slide,
                deck=deck,
            ),
        )
    for match in EMDASH_YEAR_SPAN.finditer(text):
        _keep(
            flags,
            make_flag(
                "style.date",
                "date",
                f"Date period should use an en dash, not an em dash: {match.group(1)}–{match.group(2)}",
                location=location,
                slide=slide,
                deck=deck,
            ),
        )
    for match in HYPHEN_DAY_MONTH.finditer(text):
        _keep(
            flags,
            make_flag(
                "style.date",
                "date",
                f"Date period should use an en dash: {match.group(1)}–{match.group(2)} {match.group(3)}",
                location=location,
                slide=slide,
                deck=deck,
            ),
        )
    return flags


def _quote_flags(text: str, location: str, *, slide: int | None = None, deck: str = "") -> list[Flag]:
    flags: list[Flag] = []
    for match in QUOTE_ATTR.finditer(text):
        attr = match.group(1).strip()
        if NAME_WITH_SPAN.match(attr):
            message = (
                f"Attribution has lifespan (deceased form): {attr}. "
                "Confirm the person is not living, and verify the name spelling."
            )
        else:
            message = (
                f"Attribution is name-only (living form): {attr}. "
                "If deceased, use Name 1950–2012."
            )
        _keep(
            flags,
            make_flag(
                "style.quote", "quote", message, default="info",
                location=location, slide=slide, deck=deck,
            ),
        )
    return flags


def _highlight_punctuation_flags(
    slide: dict, location: str, number: int | None = None, deck: str = ""
) -> list[Flag]:
    flags: list[Flag] = []
    markup = highlighted_markup(slide)
    for match in re.finditer(r"\*([^*]+)\*", markup):
        inner = match.group(1)
        if PUNCT_ONLY.match(inner):
            _keep(
                flags,
                make_flag(
                    "style.highlight",
                    "highlight",
                    f"Don’t highlight punctuation: {inner!r} (default size & colour).",
                    location=location,
                    slide=number,
                    deck=deck,
                ),
            )
    for item in slide.get("items") or []:
        for run in item.get("runs") or []:
            text = run.get("text") or ""
            if run.get("color") and PUNCT_ONLY.match(text):
                from obed_edom.inspect import _looks_highlight

                if _looks_highlight(run.get("color")):
                    _keep(
                        flags,
                        make_flag(
                            "style.highlight",
                            "highlight",
                            f"Don’t highlight punctuation: {text!r}.",
                            location=location,
                            slide=number,
                            deck=deck,
                        ),
                    )
    return flags


def _is_accent_colour(color: str | None) -> bool:
    """True for a direct RGB colour that is not (near-)black.

    `_color_of` only reports a direct `color.rgb`, so an inherited/theme colour
    arrives as None and is left alone. An explicit black run IS default text, so
    near-black is excluded. Word theme accent colours (yellow/cyan applied via a
    theme, not direct RGB) come back None here and are invisible to this check —
    bold/italic/highlight are the reliable signals for those.
    """
    if not color:
        return False
    hexval = str(color).lstrip("#")
    if len(hexval) != 6:
        return False
    try:
        r, g, b = (int(hexval[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return max(r, g, b) > 0x1A


def _punctuation_style_flags(
    para: Paragraph, location: str, deck: str = "", slide: int | None = None
) -> list[Flag]:
    """Punctuation should carry default text colour & style, not bold/italic/highlight.

    Runs on a finalized inspected deck have no per-character style, so this runs
    on the outline `Run` layer where bold/italic/highlight/colour survive. Scoped
    to a run that is entirely punctuation, so a mark inside a bold word ("Amen!",
    one run) is left alone — only a standalone punctuation run is flagged.
    """
    flags: list[Flag] = []
    for run in para.runs:
        if not run.text.strip() or not PUNCT_ONLY.match(run.text):
            continue
        if run.bold or run.italic or run.highlight or _is_accent_colour(run.color):
            _keep(
                flags,
                make_flag(
                    "style.punctuation",
                    "highlight",
                    "Punctuation should be default text colour & style "
                    f"(not bold / italic / highlighted): {run.text!r}.",
                    location=location,
                    slide=slide,
                    deck=deck,
                ),
            )
    return flags


# A sliver of a bounding box past an edge is shadow and letter overhang, not a
# cut-off object. Only flag when a viewer would actually see something missing.
CUT_FRACTION = 0.05
CUT_MIN_PX = 24


def _cut_share(lo: float, hi: float, edge_lo: float, edge_hi: float) -> float:
    """Fraction of an object's width/height that falls outside a boundary pair."""
    span = hi - lo
    if span <= 0:
        return 0.0
    inside = max(0.0, min(hi, edge_hi) - max(lo, edge_lo))
    return max(0.0, (span - inside) / span)


def _is_backdrop(item: dict, slide_w: float, slide_h: float, wall_w: float) -> bool:
    """Full-bleed art and panel-sized fillers are meant to run to the edges."""
    name = str(item.get("fileName") or "")
    if re.search(r"(filler|blank|background|bg[_\- ])", name, re.I):
        return True
    w = float(item.get("w") or 0)
    h = float(item.get("h") or 0)
    if slide_h and h >= slide_h - 1:
        return True
    # A 1920-wide panel graphic on a 7680 wall is one physical screen.
    panel = slide_w / 4 if slide_w >= wall_w * 2 else slide_w
    return bool(panel and abs(w - panel) < 2 and h >= slide_h - 2)


def _bounds_flags(
    payload: dict,
    location: str,
    *,
    deck: str = "",
    png_map: dict[int, Path] | None = None,
    evidence_dir: Path | None = None,
) -> list[Flag]:
    """Flag objects the wall will visibly cut. Objects inside a side panel are fine."""
    rules = load_rules()
    wall = rules.get("center_wall") or {}
    max_w = float(wall.get("width") or 3840)
    max_h = float(wall.get("height") or 1080)
    width = float(payload.get("slideWidth") or 0)
    height = float(payload.get("slideHeight") or 0)
    flags: list[Flag] = []
    if width and height:
        canvas = make_flag(
            "bounds.canvas",
            "bounds",
            f"Canvas is {int(width)}×{int(height)} (center wall target {int(max_w)}×{int(max_h)}).",
            default="info",
            location=location,
            deck=deck,
        )
        if canvas:
            flags.append(canvas)
    if not width or not height:
        return flags

    edges: list[float] = []
    if width > max_w:
        left = (width - max_w) / 2
        edges = [left, left + max_w]

    for index, slide in enumerate(payload.get("slides") or []):
        if slide.get("skipped"):
            continue
        num = int(slide.get("number") or slide.get("index", index) + 1)
        for item_index, item in enumerate(slide.get("items") or []):
            w = float(item.get("w") or 0)
            h = float(item.get("h") or 0)
            if w <= 0 or h <= 0:
                continue
            if _is_backdrop(item, width, height, max_w):
                continue
            x = float(item.get("x") or 0)
            y = float(item.get("y") or 0)
            kind = item.get("kind") or "object"

            straddled = next(
                (
                    edge
                    for edge in edges
                    if x < edge - CUT_MIN_PX and x + w > edge + CUT_MIN_PX
                ),
                None,
            )
            if straddled is not None:
                share = min(_cut_share(x, x + w, edges[0], edges[1]), 1.0)
                if share >= CUT_FRACTION:
                    evidence = _bounds_evidence(
                        png_map, index, slide, item, (width, height), straddled, evidence_dir,
                        f"bounds-{deck or 'deck'}-{num}-{item_index}.png",
                    )
                    flag = make_flag(
                        "bounds.straddles",
                        "bounds",
                        f"This {kind} is split across the wall edge at x={int(straddled)}; "
                        f"about {share:.0%} of it lands on a different screen.",
                        location=f"{location} slide {num}",
                        slide=num,
                        deck=deck,
                        evidence=evidence,
                    )
                    if flag:
                        flags.append(flag)
                    continue

            vertical = _cut_share(y, y + h, 0.0, height)
            if vertical >= CUT_FRACTION and min(-y, y + h - height) > -CUT_MIN_PX:
                cut = max(0.0, -y) + max(0.0, y + h - height)
                if cut >= CUT_MIN_PX:
                    evidence = _bounds_evidence(
                        png_map, index, slide, item, (width, height), None, evidence_dir,
                        f"bounds-{deck or 'deck'}-{num}-{item_index}.png",
                    )
                    flag = make_flag(
                        "bounds.offcanvas",
                        "bounds",
                        f"This {kind} runs {int(cut)}px past the top or bottom of the slide "
                        f"({vertical:.0%} of it is off screen).",
                        location=f"{location} slide {num}",
                        slide=num,
                        deck=deck,
                        evidence=evidence,
                    )
                    if flag:
                        flags.append(flag)
    return flags


def _bounds_evidence(
    png_map: dict[int, Path] | None,
    slide_index: int,
    slide: dict,
    item: dict,
    slide_size: tuple[float, float],
    edge: float | None,
    evidence_dir: Path | None,
    name: str,
) -> str:
    """Crop the preview around the object and mark the wall edge. Returns a filename."""
    if not png_map or evidence_dir is None:
        return ""
    png = png_map.get(slide_index)
    if not png or not Path(png).is_file():
        return ""
    try:
        from PIL import ImageDraw  # noqa: PLC0415

        from obed_edom.images import open_rgb  # noqa: PLC0415

        slide_w, slide_h = slide_size
        im = open_rgb(png).copy()
        sx = im.width / slide_w if slide_w else 1
        sy = im.height / slide_h if slide_h else 1
        pad = 60
        x0 = int(max(0, float(item.get("x") or 0) * sx - pad))
        y0 = int(max(0, float(item.get("y") or 0) * sy - pad))
        x1 = int(min(im.width, (float(item.get("x") or 0) + float(item.get("w") or 0)) * sx + pad))
        y1 = int(min(im.height, (float(item.get("y") or 0) + float(item.get("h") or 0)) * sy + pad))
        if x1 <= x0 or y1 <= y0:
            return ""
        crop = im.crop((x0, y0, x1, y1))
        draw = ImageDraw.Draw(crop)
        box = (
            float(item.get("x") or 0) * sx - x0,
            float(item.get("y") or 0) * sy - y0,
            (float(item.get("x") or 0) + float(item.get("w") or 0)) * sx - x0,
            (float(item.get("y") or 0) + float(item.get("h") or 0)) * sy - y0,
        )
        draw.rectangle(box, outline=(255, 200, 60), width=4)
        if edge is not None:
            ex = edge * sx - x0
            draw.line([(ex, 0), (ex, crop.height)], fill=(255, 70, 70), width=5)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        crop.save(evidence_dir / name)
        return name
    except Exception:  # noqa: BLE001
        return ""
