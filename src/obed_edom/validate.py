from __future__ import annotations

import re
from pathlib import Path

import yaml

from obed_edom.bible import check_bible
from obed_edom.inspect import highlighted_markup
from obed_edom.models import Flag, OutlineDoc, Paragraph, Run, SlideSpec

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


def load_rules() -> dict:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")) or {}


def flag_dict(flag: Flag) -> dict:
    return {
        "severity": flag.severity,
        "category": flag.category,
        "message": flag.message,
        "location": flag.location,
        "resolved": flag.resolved,
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
    return flags


def _visible_slides(payload: dict) -> list[dict]:
    return [slide for slide in payload.get("slides") or [] if not slide.get("skipped")]


def validate_inspect(payload: dict, *, location_prefix: str = "") -> list[Flag]:
    flags: list[Flag] = []
    slides = _visible_slides(payload)
    text = "\n\n".join(slide_plain(s) for s in slides)
    prefix = location_prefix or Path(payload.get("path") or "keynote").name
    if text.strip():
        flags.extend(check_bible(outline_from_text(text, prefix)))
        flags.extend(validate_style_text(text, location=prefix))
    for slide in slides:
        loc = f"{prefix} slide {slide.get('number') or slide.get('index', 0) + 1}"
        flags.extend(_highlight_punctuation_flags(slide, loc))
        flags.extend(_quote_flags(slide_plain(slide), loc))
        flags.extend(_inspect_overflow_flags(slide, loc, payload))
    flags.extend(_center_wall_flags(payload, prefix))
    return flags


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
    }


def _wrap_line_count(text: str, box_width: float, font_size: float, em: float) -> int:
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
        current = 0
        for word in words:
            extra = len(word) + (1 if current else 0)
            if current and current + extra > cpl:
                lines += 1
                current = len(word)
            else:
                current += extra
        lines += 1
    return max(1, lines)


def _text_needed_height(text: str, box_width: float, font_size: float, cfg: dict) -> float:
    lines = _wrap_line_count(text, box_width, font_size, float(cfg["char_em"]))
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


def _inspect_item_font_size(item: dict, payload: dict) -> float:
    for run in item.get("runs") or []:
        size = run.get("size")
        if size:
            return float(size)
    if item.get("size"):
        return float(item["size"])
    width = float(payload.get("slideWidth") or 1920)
    return 70.0 if width >= 3000 else 45.0


def _inspect_overflow_flags(slide: dict, location: str, payload: dict) -> list[Flag]:
    cfg = _overflow_cfg()
    if not cfg["enabled"]:
        return []
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
        font = _inspect_item_font_size(item, payload)
        needed = _text_needed_height(text, box_w, font, cfg)
        if needed <= box_h + cfg["height_slack_px"]:
            continue
        preview = re.sub(r"\s+", " ", text)
        if len(preview) > 72:
            preview = preview[:72].rstrip() + "…"
        flags.append(
            Flag(
                "warning",
                "overflow",
                f"Text may overflow this box (needs about {int(needed)}px, box is {int(box_h)}px). "
                f"How overflow should be handled is not decided yet. {preview}",
                location=location,
            )
        )
    return flags


def validate_style_text(text: str, *, location: str = "") -> list[Flag]:
    rules = load_rules()
    flags: list[Flag] = []
    flags.extend(_trinity_flags(text, location, rules))
    flags.extend(_book_name_flags(text, location, rules))
    flags.extend(_date_flags(text, location))
    flags.extend(_quote_flags(text, location))
    return flags


def _trinity_flags(text: str, location: str, rules: dict) -> list[Flag]:
    flags: list[Flag] = []
    for match in LOWER_GOD.finditer(text):
        flags.append(
            Flag(
                "warning",
                "trinity",
                "Trinity word should be caps: God",
                location=f"{location}:{match.start()}" if location else str(match.start()),
            )
        )
    # Avoid every “father”; flag lowercase “father” near God/Lord/pray.
    window = 40
    for match in LOWER_FATHER.finditer(text):
        ctx = text[max(0, match.start() - window) : match.end() + window].lower()
        if any(w in ctx for w in ("god", "lord", "heaven", "pray", "almighty")):
            flags.append(
                Flag(
                    "warning",
                    "trinity",
                    "Trinity word should be caps: Father",
                    location=location,
                )
            )
    if re.search(r"\bthe son\b", text) and not re.search(r"\bthe Son\b", text):
        flags.append(
            Flag("warning", "trinity", "Trinity word should be caps: Son", location=location)
        )
    if re.search(r"\b(says?|declares?|speaks?)\s+the\s+Lord\b", text, re.I):
        if re.search(r"\bmy\b", text) and not re.search(r"\bMy\b", text):
            flags.append(
                Flag(
                    "info",
                    "trinity",
                    "If God is speaking, associated 'My' should be caps (heuristic).",
                    location=location,
                )
            )
    return flags


def _book_name_flags(text: str, location: str, rules: dict) -> list[Flag]:
    flags: list[Flag] = []
    mapping = (rules.get("book_names") or {}) if rules else {}
    # Psalms → Psalm (as a book label, not the word in a sentence like "the psalms")
    if re.search(r"\bPsalms\s+\d", text) or re.search(r"\bPsalms\b", text):
        want = mapping.get("Psalms", "Psalm")
        flags.append(
            Flag(
                "warning",
                "book_name",
                f"Use '{want}', not 'Psalms'.",
                location=location,
            )
        )
    # House style: Revelations, not Revelation
    if re.search(r"\bRevelation\s+\d", text) and not re.search(r"\bRevelations\s+\d", text):
        want = mapping.get("Revelation", "Revelations")
        flags.append(
            Flag(
                "warning",
                "book_name",
                f"Use '{want}', not 'Revelation'.",
                location=location,
            )
        )
    return flags


def _date_flags(text: str, location: str) -> list[Flag]:
    flags: list[Flag] = []
    for match in HYPHEN_YEAR_SPAN.finditer(text):
        flags.append(
            Flag(
                "warning",
                "date",
                f"Date period should use an en dash: {match.group(1)}–{match.group(2)}",
                location=location,
            )
        )
    for match in EMDASH_YEAR_SPAN.finditer(text):
        flags.append(
            Flag(
                "warning",
                "date",
                f"Date period should use an en dash, not an em dash: {match.group(1)}–{match.group(2)}",
                location=location,
            )
        )
    for match in HYPHEN_DAY_MONTH.finditer(text):
        flags.append(
            Flag(
                "warning",
                "date",
                f"Date period should use an en dash: {match.group(1)}–{match.group(2)} {match.group(3)}",
                location=location,
            )
        )
    return flags


def _quote_flags(text: str, location: str) -> list[Flag]:
    flags: list[Flag] = []
    for match in QUOTE_ATTR.finditer(text):
        attr = match.group(1).strip()
        if NAME_WITH_SPAN.match(attr):
            flags.append(
                Flag(
                    "info",
                    "quote",
                    f"Attribution has lifespan (deceased form): {attr}. Confirm the person is not living, and verify the name spelling.",
                    location=location,
                )
            )
        else:
            flags.append(
                Flag(
                    "info",
                    "quote",
                    f"Attribution is name-only (living form): {attr}. If deceased, use Name 1950–2012. Name spelling not verified online in v1.",
                    location=location,
                )
            )
    return flags


def _highlight_punctuation_flags(slide: dict, location: str) -> list[Flag]:
    flags: list[Flag] = []
    markup = highlighted_markup(slide)
    for match in re.finditer(r"\*([^*]+)\*", markup):
        inner = match.group(1)
        if PUNCT_ONLY.match(inner):
            flags.append(
                Flag(
                    "warning",
                    "highlight",
                    f"Don’t highlight punctuation: {inner!r} (default size & colour).",
                    location=location,
                )
            )
    for item in slide.get("items") or []:
        for run in item.get("runs") or []:
            text = run.get("text") or ""
            if run.get("color") and PUNCT_ONLY.match(text):
                from obed_edom.inspect import _looks_highlight

                if _looks_highlight(run.get("color")):
                    flags.append(
                        Flag(
                            "warning",
                            "highlight",
                            f"Don’t highlight punctuation: {text!r}.",
                            location=location,
                        )
                    )
    return flags


def _center_wall_flags(payload: dict, location: str) -> list[Flag]:
    rules = load_rules()
    wall = rules.get("center_wall") or {}
    max_w = int(wall.get("width") or 3840)
    max_h = int(wall.get("height") or 1080)
    width = float(payload.get("slideWidth") or 0)
    height = float(payload.get("slideHeight") or 0)
    flags: list[Flag] = []
    if width and height:
        flags.append(
            Flag(
                "info",
                "bounds",
                f"Canvas is {int(width)}×{int(height)} (center wall target {max_w}×{max_h}).",
                location=location,
            )
        )
    if width > max_w:
        left = (width - max_w) / 2
        right = left + max_w
        for slide in payload.get("slides") or []:
            num = slide.get("number") or slide.get("index", 0) + 1
            for item in slide.get("items") or []:
                x = float(item.get("x") or 0)
                w = float(item.get("w") or 0)
                y = float(item.get("y") or 0)
                h = float(item.get("h") or 0)
                if w <= 0 and h <= 0:
                    continue
                if x < left - 1 or x + w > right + 1 or y < -1 or y + h > max_h + 1:
                    flags.append(
                        Flag(
                            "warning",
                            "bounds",
                            f"Object may exceed the {max_w}×{max_h} center wall "
                            f"({item.get('kind')} at x={int(x)}, y={int(y)}, {int(w)}×{int(h)}).",
                            location=f"{location} slide {num}",
                        )
                    )
    elif height > max_h:
        flags.append(
            Flag(
                "warning",
                "bounds",
                f"Slide height {int(height)} exceeds center wall {max_h}.",
                location=location,
            )
        )
    return flags
