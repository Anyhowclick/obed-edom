from __future__ import annotations

import re
from pathlib import Path

import yaml

from sermon_slides.bible import ABS_REF_RE, _norm_book
from sermon_slides.models import (
    Flag,
    OutlineDoc,
    SlideDraft,
    SlideSpec,
    StyledRun,
    Transition,
)
from sermon_slides.parse_outline import VERSE_TAGS

PACKAGE_DIR = Path(__file__).resolve().parent
MAGIC_MOVE = Transition(effect="magic_move", duration=1.0, match="word")

# What an inline reference leaves behind once "Book Chapter" is removed:
# "30-32 (MSG)" from "Mark 6:30-32 (MSG) 31 “If God gives…". The colon is
# already gone by then. A range or a translation is required, because a bare
# number here is indistinguishable from the verse number itself.
_REF_RANGE = r"\s*[-–]\s*\d{1,3}"
_REF_TRANS = r"\s*\([A-Za-z]+\)"
REF_TAIL_RE = re.compile(
    rf"^(?P<tail>:?\s*\d{{1,3}}(?:{_REF_RANGE}(?:{_REF_TRANS})?|{_REF_TRANS}))(?P<rest>[\s\S]*)$"
)
VERSE_LEAD_RE = re.compile(r"^\s*\d{1,3}\s")


def load_masters() -> dict:
    return yaml.safe_load((PACKAGE_DIR / "masters.yaml").read_text())


def _passage_header(ref: str, trans: str, series_bit: str = "") -> str:
    header = ref or ""
    if header and trans and trans.upper() != "NIV":
        header = f"{header} ({trans})"
    if not header:
        return series_bit
    if series_bit and series_bit.lower() not in header.lower():
        return f"{header} • {series_bit}"
    return header


def _lw_verse_body_height(cfg: dict) -> int:
    default = int(cfg.get("verse_body_default_height", 372))
    max_height = cfg.get("verse_body_max_height")
    if max_height is not None:
        return max(default, int(max_height))
    bottom = int(cfg.get("verse_body_max_bottom", 550))
    y = int(cfg.get("verse_body_y", 97))
    margin = int(cfg.get("verse_body_margin", 12))
    return max(default, bottom - y - margin)


def _lw_body_font_size(cfg: dict, body_len: int) -> float:
    base = float(cfg.get("verse_body_font_size", 70))
    threshold = int(cfg.get("verse_body_shrink_threshold", 260))
    min_size = float(cfg.get("verse_body_min_font_size", 52))
    if body_len <= threshold:
        return base
    scaled = base - (body_len - threshold) * 0.04
    return max(min_size, scaled)


def _line_font_size(base: float, min_size: float, n: int, threshold: int, shrink_rate: float = 0.008) -> float:
    if n <= threshold:
        return base
    scale = max(min_size / base, 1.0 - (n - threshold) * shrink_rate)
    return max(min_size, base * scale)


def _points_line_font_sizes(cfg: dict, lines: list[str], mapping: dict) -> dict[int, float]:
    defaults = {
        "line1": float(cfg.get("points_line1_font_size", 250)),
        "line2": float(cfg.get("points_line2_font_size", 85)),
        "line3": float(cfg.get("points_line3_font_size", 55)),
    }
    thresholds = {
        "line1": int(cfg.get("points_line1_max_chars", 72)),
        "line2": int(cfg.get("points_line2_max_chars", 120)),
        "line3": int(cfg.get("points_line3_max_chars", 55)),
    }
    mins = {
        "line1": float(cfg.get("points_line1_min_font_size", 140)),
        "line2": float(cfg.get("points_line2_min_font_size", 62)),
        "line3": float(cfg.get("points_line3_min_font_size", 42)),
    }
    computed: dict[str, float] = {}
    for key in ("line1", "line2", "line3"):
        idx = mapping.get(key)
        if idx is None:
            continue
        line_idx = {"line1": 0, "line2": 1, "line3": 2}[key]
        if line_idx >= len(lines) or not lines[line_idx]:
            continue
        computed[key] = _line_font_size(
            defaults[key],
            mins[key],
            len(lines[line_idx]),
            thresholds[key],
        )

    order = [key for key in ("line1", "line2", "line3") if key in computed]
    for i in range(len(order) - 1):
        upper_key = order[i]
        lower_key = order[i + 1]
        ratio = defaults[lower_key] / defaults[upper_key]
        cap = computed[upper_key] * ratio * 0.98
        if computed[lower_key] >= computed[upper_key]:
            computed[lower_key] = max(mins[lower_key], cap)
        if computed[lower_key] >= computed[upper_key]:
            computed[upper_key] = computed[lower_key] + max(8.0, defaults[upper_key] * 0.04)

    sizes: dict[int, float] = {}
    for key, size in computed.items():
        idx = int(mapping[key])
        if abs(size - defaults[key]) >= 0.5:
            sizes[idx] = size
    return sizes


def _point_styled_runs(draft: SlideDraft) -> list[StyledRun]:
    """Bold → gold (highlight), unbolded → white (normal). Prefer green-marked title spans."""
    spans = [s for s in draft.body_spans if not s.verse_number and s.text]
    green = [s for s in spans if s.highlight and "green" in (s.highlight or "").lower()]
    use = green or spans
    runs: list[StyledRun] = []
    for span in use:
        text = span.text.replace("\xa0", " ")
        if not text:
            continue
        runs.append(StyledRun(text=text, style="highlight" if span.bold else "normal"))
    merged = _merge_runs(runs)
    return _lstrip_runs(merged)


def _fit_font_size(n_chars: int, box_width: float, base: float, min_size: float, em: float) -> float:
    if n_chars <= 0:
        return base
    fitted = box_width / (n_chars * em)
    return max(min_size, min(base, fitted))


def _fit_point_runs(
    runs: list[StyledRun],
    *,
    box_width: float,
    base_size: float,
    min_size: float,
    em: float,
    max_lines: int = 3,
) -> tuple[list[list[StyledRun]], float]:
    """Keep template size when the line fits; wrap in one box before shrinking hard."""
    pending = [StyledRun(text=r.text, style=r.style) for r in runs if r.text]
    n = sum(len(r.text) for r in pending)
    if n == 0:
        return [[]], base_size
    chars_at_base = max(8, int(box_width / (base_size * em)))
    if n <= chars_at_base + 2:
        return [pending], base_size if n <= chars_at_base else _line_font_size(
            base_size, min_size, n, chars_at_base
        )
    size = _line_font_size(base_size, min_size, n, chars_at_base)
    max_chars = max(8, int(box_width / (size * em)))
    if n <= max_chars:
        return [pending], size
    lines = _split_runs_by_words(pending, max_chars) or [pending]
    if len(lines) > max_lines:
        target = max(8, (n + max_lines - 1) // max_lines)
        lines = _split_runs_by_words(pending, max(target, max_chars)) or [pending]
        lines = lines[:max_lines]
    longest = max(sum(len(r.text) for r in line) for line in lines) if lines else n
    size = _line_font_size(base_size, min_size, longest, chars_at_base)
    return lines, size


def _point_line_count(n: int, one_line_chars: int, max_lines: int) -> int:
    if n <= 0 or n <= one_line_chars or max_lines <= 1:
        return 1
    if max_lines >= 3 and n > one_line_chars * 2:
        return 3
    return 2


def _run_tokens(runs: list[StyledRun]) -> list[StyledRun]:
    tokens: list[StyledRun] = []
    for run in runs:
        parts = re.split(r"(\s+)", run.text)
        for part in parts:
            if part:
                tokens.append(StyledRun(text=part, style=run.style))
    return tokens


def _wrap_runs_to_lines(
    runs: list[StyledRun],
    *,
    max_lines: int,
    one_line_chars: int,
) -> list[StyledRun]:
    """Insert returns so a long point becomes 2 (PRE) or 3 (POST) lines."""
    pending = [StyledRun(text=r.text, style=r.style) for r in runs if r.text]
    n = sum(len(r.text) for r in pending)
    lines_n = _point_line_count(n, one_line_chars, max_lines)
    if lines_n <= 1 or n == 0:
        return pending
    tokens = _run_tokens(pending)
    target = max(8, (n + lines_n - 1) // lines_n)
    per_line = target + 12

    lines: list[list[StyledRun]] = []
    current: list[StyledRun] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        trimmed = _merge_runs(current)
        if len(trimmed) == 1:
            text = trimmed[0].text.strip()
            trimmed = [StyledRun(text=text, style=trimmed[0].style)] if text else []
        elif trimmed:
            first = trimmed[0].text.lstrip()
            last = trimmed[-1].text.rstrip()
            trimmed[0] = StyledRun(text=first, style=trimmed[0].style)
            trimmed[-1] = StyledRun(text=last, style=trimmed[-1].style)
            trimmed = [r for r in trimmed if r.text]
        if trimmed:
            lines.append(trimmed)
        current = []
        current_len = 0

    for tok in tokens:
        text = tok.text
        if text.isspace() and not current:
            continue
        extra = len(text)
        would = current_len + extra
        lines_left = lines_n - len(lines)
        should_break = False
        if current and lines_left > 1:
            prev_word = next((t for t in reversed(current) if t.text.strip()), None)
            after_highlight = prev_word is not None and prev_word.style == "highlight"
            at_dash = text.strip().startswith("-")
            if after_highlight and current_len >= int(target * 0.7):
                should_break = True
            elif at_dash and current_len >= int(target * 0.55):
                should_break = True
            elif would > per_line:
                should_break = True
        if should_break:
            flush()
            if text.isspace():
                continue
        current.append(tok)
        current_len += extra
    flush()
    while len(lines) > lines_n and len(lines) >= 2:
        lines[-2] = _merge_runs(lines[-2] + [StyledRun(text=" ", style="normal")] + lines[-1])
        lines.pop()
    return _join_run_lines(lines)


def _lw_point_max_chars(cfg: dict, *, post: bool) -> int:
    pre_max = int(cfg.get("points_line1_max_chars", 28))
    if not post:
        return pre_max
    pre_w = float(cfg.get("points_pre_box_width", 1680))
    post_w = float(cfg.get("points_post_box_width", 820))
    if pre_w <= 0:
        return pre_max
    return max(8, int(pre_max * post_w / pre_w))


def _join_run_lines(lines: list[list[StyledRun]]) -> list[StyledRun]:
    out: list[StyledRun] = []
    for i, line in enumerate(lines):
        if i:
            out.append(StyledRun(text="\n", style="normal"))
        out.extend(line)
    return _merge_runs(out)


def _split_point_lines(draft: SlideDraft) -> list[str]:
    if draft.green_title:
        text = draft.body or draft.green_title
        if draft.green_title in text:
            rest = text.replace(draft.green_title, "", 1).strip(" .")
            lines = [draft.green_title]
            if rest:
                lines.append(rest)
            return lines[:3]
        return [draft.green_title]

    bold_parts: list[str] = []
    rest_parts: list[str] = []
    seen_non_bold = False
    for span in draft.body_spans:
        if span.verse_number:
            continue
        raw = span.text
        if not raw:
            continue
        if not seen_non_bold and span.bold:
            bold_parts.append(raw)
        else:
            seen_non_bold = True
            rest_parts.append(raw)
    line1 = "".join(bold_parts).strip()
    line2 = "".join(rest_parts).strip()
    if line1 and line2:
        return [line1, line2]
    if line1:
        return [line1]
    body = draft.body.strip()
    return [body] if body else []


def _points_text_items(
    mapping: dict,
    lines: list[str],
    point_number: int | None = None,
) -> dict[int, str]:
    text_items: dict[int, str] = {}
    for i, key in enumerate(("line1", "line2", "line3")):
        idx = mapping.get(key)
        if idx is None:
            continue
        text_items[int(idx)] = lines[i] if i < len(lines) else ""
    point_idx = mapping.get("point_number")
    if point_idx is not None and point_number is not None:
        text_items[int(point_idx)] = str(point_number)
    return text_items


def _dsk_point_text(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


def _is_verse_draft(draft: SlideDraft) -> bool:
    if draft.cue_tag in VERSE_TAGS or draft.force_verse or draft.has_verse_numbers:
        return True
    return bool(draft.body_spans) and any(s.verse_number for s in draft.body_spans)


def _drop_prefix(runs: list[StyledRun], count: int) -> list[StyledRun]:
    remaining = count
    out: list[StyledRun] = []
    for run in runs:
        if remaining <= 0:
            out.append(run)
            continue
        if remaining >= len(run.text):
            remaining -= len(run.text)
            continue
        out.append(StyledRun(text=run.text[remaining:], style=run.style))
        remaining = 0
    return out


def _lstrip_runs(runs: list[StyledRun]) -> list[StyledRun]:
    out: list[StyledRun] = []
    stripping = True
    for run in runs:
        text = run.text
        if stripping:
            text = text.lstrip(" :-")
            if not text:
                continue
            stripping = False
        out.append(StyledRun(text=text, style=run.style))
    return out


def _merge_runs(runs: list[StyledRun]) -> list[StyledRun]:
    merged: list[StyledRun] = []
    for run in runs:
        if not run.text:
            continue
        if merged and merged[-1].style == run.style:
            merged[-1] = StyledRun(text=merged[-1].text + run.text, style=run.style)
        else:
            merged.append(StyledRun(text=run.text, style=run.style))
    return merged


def _split_at_word(text: str, room: int) -> tuple[str, str]:
    if room <= 0:
        return "", text
    if len(text) <= room:
        return text, ""
    window = text[:room]
    break_at = -1
    for sep in (" ", "\u2014", "\u2013", "-"):
        idx = window.rfind(sep)
        if idx > break_at:
            break_at = idx
    min_head = min(8, max(1, room // 4))
    if break_at >= min_head:
        cut = break_at + 1 if text[break_at] in " \u2014\u2013-" else break_at
        return text[:cut], text[cut:]
    return text[:room], text[room:]


def _flush_chunk(current: list[StyledRun]) -> list[StyledRun]:
    merged = _lstrip_runs(_merge_runs(current))
    if merged:
        last = merged[-1]
        trimmed = last.text.rstrip()
        if trimmed:
            merged[-1] = StyledRun(text=trimmed, style=last.style)
        else:
            merged = merged[:-1]
        merged = [r for r in merged if r.text]
    return merged


def _verse_segments(runs: list[StyledRun]) -> list[list[StyledRun]]:
    segments: list[list[StyledRun]] = []
    current: list[StyledRun] = []
    for run in runs:
        if run.style == "verse_number" and current:
            segments.append(current)
            current = [run]
        else:
            current.append(run)
    if current:
        segments.append(current)
    return segments


def _split_runs_by_words(runs: list[StyledRun], max_chars: int) -> list[list[StyledRun]]:
    pending = [StyledRun(text=r.text, style=r.style) for r in runs if r.text]
    if not pending:
        return []
    total = sum(len(r.text) for r in pending)
    if total <= max_chars:
        return [pending]

    chunks: list[list[StyledRun]] = []
    current: list[StyledRun] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        flushed = _flush_chunk(current)
        if flushed:
            chunks.append(flushed)
        current = []
        current_len = 0

    i = 0
    while i < len(pending):
        run = pending[i]
        room = max_chars - current_len
        if len(run.text) <= room:
            current.append(run)
            current_len += len(run.text)
            i += 1
            continue
        if room < 12 and current:
            flush()
            continue
        head, tail = _split_at_word(run.text, room)
        if tail.strip() and len(tail.strip()) < 40 and current:
            current.append(run)
            current_len += len(run.text)
            i += 1
            continue
        if head.strip():
            current.append(StyledRun(text=head.rstrip(), style=run.style))
        flush()
        if tail.strip():
            pending[i] = StyledRun(text=tail.lstrip(), style=run.style)
            continue
        i += 1
    flush()
    return chunks or [pending]


def _merge_small_chunks(chunks: list[list[StyledRun]], min_chars: int = 40) -> list[list[StyledRun]]:
    if not chunks:
        return chunks
    merged: list[list[StyledRun]] = [chunks[0]]
    for chunk in chunks[1:]:
        n = sum(len(r.text) for r in chunk)
        if n < min_chars:
            merged[-1] = _merge_runs(merged[-1] + chunk)
        else:
            merged.append(chunk)
    if len(merged) >= 2 and sum(len(r.text) for r in merged[-1]) < min_chars:
        merged[-2] = _merge_runs(merged[-2] + merged[-1])
        merged.pop()
    return merged


def _split_styled_runs(runs: list[StyledRun], max_chars: int) -> list[list[StyledRun]]:
    """Split verse runs across slides, preferring verse boundaries then words."""
    if max_chars < 20:
        max_chars = 20
    pending = [StyledRun(text=r.text, style=r.style) for r in runs if r.text]
    if not pending:
        return []
    total = sum(len(r.text) for r in pending)
    if total <= max_chars:
        return [pending]

    segments = _verse_segments(pending)
    chunks: list[list[StyledRun]] = []
    current: list[StyledRun] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current, current_len
        flushed = _flush_chunk(current)
        if flushed:
            chunks.append(flushed)
        current = []
        current_len = 0

    for segment in segments:
        seg_len = sum(len(r.text) for r in segment)
        if seg_len > max_chars:
            if current:
                flush_current()
            chunks.extend(_split_runs_by_words(segment, max_chars))
            continue
        if current and current_len + seg_len > max_chars:
            flush_current()
        current.extend(segment)
        current_len += seg_len
    flush_current()
    return _merge_small_chunks(chunks)


def _styled_verse_runs(draft: SlideDraft, ref: str) -> list[StyledRun]:
    import re

    runs: list[StyledRun] = []
    for span in draft.body_spans:
        raw = span.text.replace("\xa0", " ")
        if not raw:
            continue
        if span.verse_number:
            if runs and not runs[-1].text[-1:].isspace():
                runs.append(StyledRun(text=" ", style="normal"))
            runs.append(StyledRun(text=span.verse_number, style="verse_number"))
            extra = raw
            if extra.startswith(span.verse_number):
                extra = extra[len(span.verse_number) :]
            if extra.strip():
                extra_style = "highlight" if span.bold and extra.strip() else "normal"
                runs.append(StyledRun(text=extra, style=extra_style))
            elif extra:
                runs.append(StyledRun(text=extra, style="normal"))
            continue
        style = "highlight" if span.bold and raw.strip() else "normal"
        runs.append(StyledRun(text=raw, style=style))

    runs = _lstrip_runs(runs)
    while runs and runs[0].style != "verse_number":
        candidate = runs[0].text.strip().rstrip(":")
        if ABS_REF_RE.fullmatch(candidate):
            runs = _lstrip_runs(runs[1:])
            continue
        break
    full = "".join(r.text for r in runs)
    intro = re.match(r"(verse\s+\d+\s+says\s*[.….\s]*)", full, re.IGNORECASE)
    if intro:
        runs = _drop_prefix(runs, len(intro.group(1)))
        runs = _lstrip_runs(runs)
    if ref:
        full = "".join(r.text for r in runs)
        if full.lower().startswith(ref.lower()):
            runs = _drop_prefix(runs, len(ref))
            runs = _lstrip_runs(runs)
            # `ref` is only "Book Chapter", so an inline reference leaves its
            # verse range and translation behind ("30-32 (MSG) 31 …"). Drop that
            # tail only when a real verse number follows, so a reference whose
            # range *is* the first verse ("Ezekiel 36:26 I will give…") keeps it.
            tail = REF_TAIL_RE.match("".join(r.text for r in runs))
            if tail and VERSE_LEAD_RE.match(tail.group("rest")):
                runs = _lstrip_runs(_drop_prefix(runs, tail.end("tail")))
    squeezed: list[StyledRun] = []
    for run in runs:
        text = re.sub(r"\s+", " ", run.text)
        squeezed.append(StyledRun(text=text, style=run.style))
    # Squeeze turns a dropped-ref newline into a leading space; strip again so
    # the first run is the verse number and Keynote can keep the superscript seed.
    return _lstrip_runs(_merge_runs(squeezed))


def _reference_from_body(draft: SlideDraft) -> str:
    text = draft.body
    match = ABS_REF_RE.search(text)
    if match:
        book = _norm_book(match.group("book"))
        return f"{book} {match.group('chapter')}"
    if draft.body_spans:
        first = "".join(s.text for s in draft.body_spans[:3]).strip()
        match = ABS_REF_RE.search(first)
        if match:
            return f"{_norm_book(match.group('book'))} {match.group('chapter')}"
    return ""


def _nearest_ref(outline: OutlineDoc, para_index: int) -> tuple[str, str]:
    last_ref = ""
    translation = "NIV"
    for para in outline.paragraphs:
        if para.index > para_index:
            break
        for match in ABS_REF_RE.finditer(para.text):
            book = _norm_book(match.group("book"))
            chapter = match.group("chapter")
            last_ref = f"{book} {chapter}"
            if match.group("translation"):
                translation = match.group("translation").upper()
    if "(MSG)" in outline.full_text.upper() and outline.context == "offering" and translation == "NIV":
        translation = "MSG"
    return last_ref, translation


def _resolve_ref(outline: OutlineDoc, draft: SlideDraft) -> tuple[str, str]:
    para = min(draft.source_paragraphs) if draft.source_paragraphs else 0
    nearest, trans = _nearest_ref(outline, para)
    if nearest:
        return nearest, trans
    return _reference_from_body(draft), trans


def _first_verse_number(runs: list[StyledRun]) -> str:
    for run in runs:
        if run.style == "verse_number" and run.text.strip():
            return run.text.strip()
    return ""


def _last_verse_number(runs: list[StyledRun]) -> str:
    for run in reversed(runs):
        if run.style == "verse_number" and run.text.strip():
            return run.text.strip()
    return ""


def _runs_from_verse(runs: list[StyledRun], verse_num: str) -> list[StyledRun]:
    out: list[StyledRun] = []
    capturing = False
    for run in runs:
        if run.style == "verse_number":
            if capturing:
                break
            if run.text.strip() == verse_num:
                capturing = True
        if capturing:
            out.append(StyledRun(text=run.text, style=run.style))
    return out


def _join_continued_runs(prefix: list[StyledRun], suffix: list[StyledRun]) -> list[StyledRun]:
    if not prefix:
        return list(suffix)
    if not suffix:
        return list(prefix)
    joined = list(prefix)
    if joined[-1].text and suffix[0].text:
        if not joined[-1].text[-1].isspace() and not suffix[0].text[0].isspace():
            joined.append(StyledRun(text=" ", style="normal"))
    joined.extend(suffix)
    return _merge_runs(joined)


def _continuation_prefix(outline: OutlineDoc, blocks: list[SlideDraft], index: int) -> list[StyledRun]:
    """Earlier fragments of the same verse, from the last numbered verse through here."""
    parts: list[list[StyledRun]] = []
    for j in range(index - 1, -1, -1):
        draft = blocks[j]
        if draft.cue_tag not in VERSE_TAGS and not _is_verse_draft(draft):
            if parts:
                break
            continue
        ref, _ = _resolve_ref(outline, draft)
        styled = _styled_verse_runs(draft, ref)
        verse_num = _last_verse_number(styled)
        if verse_num:
            parts.append(_runs_from_verse(styled, verse_num))
            break
        parts.append(styled)
    parts.reverse()
    joined: list[StyledRun] = []
    for part in parts:
        joined = _join_continued_runs(joined, part)
    return joined


def _looks_continued(draft: SlideDraft, blocks: list[SlideDraft], index: int) -> bool:
    if draft.cue_tag == "VERSE-CONTINUED":
        return True
    if draft.cue_tag != "VERSE" or draft.has_verse_numbers:
        return False
    return any(
        blocks[j].cue_tag in VERSE_TAGS or _is_verse_draft(blocks[j])
        for j in range(index - 1, -1, -1)
    )


def _graphic_spec(**kwargs) -> SlideSpec:
    kwargs.setdefault("is_graphic", True)
    kwargs.setdefault("role", "graphic")
    return SlideSpec(**kwargs)


def _verse_chunks(
    draft: SlideDraft,
    outline: OutlineDoc,
    max_chars: int,
    *,
    prefix_runs: list[StyledRun] | None = None,
    split: bool = True,
) -> tuple[str, str, list[list[StyledRun]]]:
    ref, trans = _resolve_ref(outline, draft)
    styled = _styled_verse_runs(draft, ref)
    if prefix_runs:
        styled = _join_continued_runs(prefix_runs, styled)
    if split:
        chunks = _split_styled_runs(styled, max_chars) or ([styled] if styled else [])
    else:
        chunks = [styled] if styled else []
    return ref, trans, chunks


def _lw_verse_specs(
    draft: SlideDraft,
    outline: OutlineDoc,
    masters: dict,
    block_index: int,
    *,
    role: str = "verse",
    bind: str = "verse_body",
    extra_source: list[int] | None = None,
    prefix_runs: list[StyledRun] | None = None,
    continued: bool = False,
) -> list[SlideSpec]:
    cfg = masters["lw"]
    mapping = cfg["text_items"].get("VERSES", {})
    body_idx = int(mapping["body"]) if "body" in mapping else 2
    ref_idx = int(mapping["reference"]) if "reference" in mapping else 1
    verse_height = _lw_verse_body_height(cfg)
    max_chars = int(cfg.get("verse_char_max", 200))
    ref, trans, chunks = _verse_chunks(
        draft, outline, max_chars, prefix_runs=prefix_runs, split=not continued
    )
    source = list(draft.source_paragraphs)
    if extra_source:
        for idx in extra_source:
            if idx not in source:
                source.append(idx)
    specs: list[SlideSpec] = []
    for i, chunk in enumerate(chunks):
        body = "".join(r.text for r in chunk)
        chunk_items: dict[int, str] = {}
        if ref or outline.series_title:
            chunk_items[ref_idx] = ref or outline.series_title
        chunk_items[body_idx] = body
        specs.append(
            SlideSpec(
                deck="lw",
                cue_tag="LW",
                operator_tag="LW",
                master="VERSES",
                title=ref,
                body=body,
                reference=ref,
                text_items=chunk_items,
                styled_items={body_idx: chunk},
                text_item_heights={body_idx: verse_height},
                text_item_font_sizes={body_idx: _lw_body_font_size(cfg, len(body))},
                is_verse=True,
                translation=trans,
                context=outline.context,
                source_paragraphs=source,
                semantic_tag="VERSE-CONTINUED" if continued else "VERSE",
                role=role,  # type: ignore[arg-type]
                block_index=block_index,
                bind=bind,
                chunk_index=i,
                anchor_verse=_first_verse_number(chunk),
            )
        )
    return specs


def _dsk_verse_specs(
    draft: SlideDraft,
    outline: OutlineDoc,
    masters: dict,
    block_index: int,
    *,
    role: str = "verse",
    bind: str = "verse_body",
    prefix_runs: list[StyledRun] | None = None,
    continued: bool = False,
) -> list[SlideSpec]:
    cfg = masters["dsk"]
    pp = cfg["cues"]["VERSE"]
    offering = outline.context == "offering"
    series_bit = outline.series_subtitle or outline.series_title
    if offering:
        one_line_limit = int(cfg.get("offering_verse_char_one_line", 90))
        max_chars = int(cfg.get("offering_verse_char_max", 190))
        body_width = int(cfg.get("offering_verse_body_width", 1540))
    else:
        one_line_limit = int(cfg.get("verse_char_one_line", 80))
        max_chars = int(cfg.get("verse_char_max", 220))
        body_width = 0
    ref, trans, chunks = _verse_chunks(
        draft, outline, max_chars, prefix_runs=prefix_runs, split=not continued
    )
    if "(MSG)" in outline.full_text.upper() and offering:
        trans = "MSG"
    header_text = _passage_header(ref or series_bit, trans, series_bit)
    specs: list[SlideSpec] = []
    for i, chunk in enumerate(chunks):
        body = "".join(r.text for r in chunk)
        if offering:
            master = (
                pp["offering_verse_one_line"]
                if len(body) <= one_line_limit
                else pp["offering_verse_standard"]
            )
        else:
            master = (
                pp["sermon_verse_one_line"]
                if len(body) <= one_line_limit
                else pp["sermon_verse_standard"]
            )
        specs.append(
            SlideSpec(
                deck="dsk",
                cue_tag="DSK-PP",
                operator_tag="DSK-PP",
                master=master,
                body=body,
                header=header_text,
                reference=ref,
                text_items={1: body, 2: header_text},
                styled_items={1: chunk},
                text_item_widths={1: body_width} if body_width else {},
                is_verse=True,
                translation=trans,
                context=outline.context,
                source_paragraphs=list(draft.source_paragraphs),
                semantic_tag="VERSE-CONTINUED" if continued else "VERSE",
                role=role,  # type: ignore[arg-type]
                block_index=block_index,
                bind=bind,
                chunk_index=i,
                anchor_verse=_first_verse_number(chunk),
            )
        )
    return specs


def _dsk_post_point_fits(draft: SlideDraft, masters: dict) -> bool:
    """Skip DSK POST (point + verse) when the point cannot sit in the left column."""
    cfg = masters["dsk"]
    n = sum(len(r.text) for r in _point_styled_runs(draft))
    limit = int(cfg.get("point_post_max_chars", 50))
    return n <= limit


def _lw_point_spec(
    draft: SlideDraft,
    outline: OutlineDoc,
    masters: dict,
    block_index: int,
    *,
    post: bool,
    verse_draft: SlideDraft | None = None,
) -> SlideSpec:
    cfg = masters["lw"]
    numbered = draft.cue_tag == "NUM-POINT"
    tag = "NUM-POINT" if numbered else "POINT"
    rule = cfg["cues"][tag]
    master = rule["post"] if post else rule["pre"]
    mapping = cfg["text_items"].get(master, {})
    runs = _wrap_runs_to_lines(
        _point_styled_runs(draft),
        max_lines=3 if post else 2,
        one_line_chars=_lw_point_max_chars(cfg, post=post),
    )
    text_items: dict[int, str] = {}
    styled_items: dict[int, list[StyledRun]] = {}
    font_sizes: dict[int, float] = {}
    item_palettes: dict[int, str] = {}
    # line2/line3 are separate boxes far apart on the GW master — wrap with returns in line1.
    for key in ("line1", "line2", "line3"):
        idx = mapping.get(key)
        if idx is None:
            continue
        text_items[int(idx)] = ""
    line1 = mapping.get("line1")
    if line1 is not None:
        text_items[int(line1)] = "".join(r.text for r in runs)
        if runs:
            styled_items[int(line1)] = runs
            item_palettes[int(line1)] = "lw_point"
    if numbered and mapping.get("point_number") is not None and draft.point_number is not None:
        text_items[int(mapping["point_number"])] = str(draft.point_number)
    heights: dict[int, int] = {}
    ref = ""
    trans = "NIV"
    is_verse = False
    bind = "cue"
    role = "post" if post else "pre"
    source = list(draft.source_paragraphs)
    anchor = ""
    if post and verse_draft is not None:
        ref, trans, chunks = _verse_chunks(verse_draft, outline, int(cfg.get("verse_char_max", 320)))
        chunk = chunks[0] if chunks else []
        body = "".join(r.text for r in chunk)
        ref_idx = mapping.get("reference")
        body_idx = mapping.get("body")
        if ref_idx is not None:
            text_items[int(ref_idx)] = ref
        if body_idx is not None:
            text_items[int(body_idx)] = body
            styled_items[int(body_idx)] = chunk
            heights[int(body_idx)] = _lw_verse_body_height(cfg)
            font_sizes[int(body_idx)] = _lw_body_font_size(cfg, len(body))
            item_palettes[int(body_idx)] = "lw"
        is_verse = True
        bind = "verse_body"
        for para in verse_draft.source_paragraphs:
            if para not in source:
                source.append(para)
        anchor = _first_verse_number(chunk)
    return SlideSpec(
        deck="lw",
        cue_tag="LW",
        operator_tag="LW",
        master=master,
        body=draft.body or draft.green_title,
        reference=ref,
        text_items=text_items,
        styled_items=styled_items,
        text_item_heights=heights,
        text_item_font_sizes=font_sizes,
        item_palettes=item_palettes,
        is_verse=is_verse,
        translation=trans,
        context=outline.context,
        source_paragraphs=source,
        semantic_tag=tag,
        role=role,  # type: ignore[arg-type]
        block_index=block_index,
        bind=bind,
        chunk_index=0,
        anchor_verse=anchor,
        transition=MAGIC_MOVE if not post else None,
    )


def _dsk_point_spec(
    draft: SlideDraft,
    outline: OutlineDoc,
    masters: dict,
    block_index: int,
    *,
    post: bool,
    verse_draft: SlideDraft | None = None,
) -> SlideSpec:
    cfg = masters["dsk"]
    numbered = draft.cue_tag == "NUM-POINT"
    tag = "NUM-POINT" if numbered else "POINT"
    rule = cfg["cues"][tag]
    master = rule["post"] if post else rule["pre"]
    items_key = f"{tag}-{'POST' if post else 'PRE'}"
    mapping = cfg["text_items"].get(items_key, {})
    one_line = int(cfg.get("point_char_two_lines", 90) if not post else cfg.get("point_post_max_chars", 50))
    runs = _wrap_runs_to_lines(
        _point_styled_runs(draft),
        max_lines=2 if not post else 3,
        one_line_chars=one_line,
    )
    point_text = "".join(r.text for r in runs)
    text_items: dict[int, str] = {}
    styled_items: dict[int, list[StyledRun]] = {}
    widths: dict[int, int] = {}
    heights: dict[int, int] = {}
    positions: dict[int, tuple[int, int]] = {}
    font_sizes: dict[int, float] = {}
    item_palettes: dict[int, str] = {}
    extra_text_items: list[dict] = []
    for raw_idx, frame in (mapping.get("frames") or {}).items():
        idx = int(raw_idx)
        positions[idx] = (int(frame["x"]), int(frame["y"]))
        if frame.get("width") is not None:
            widths[idx] = int(frame["width"])
        if frame.get("height") is not None:
            heights[idx] = int(frame["height"])
    extras = mapping.get("extra") or {}
    body_idx = mapping.get("body")
    extra_body = extras.get("body")
    extra_num = extras.get("point_number")
    if body_idx is not None:
        text_items[int(body_idx)] = point_text
        if runs:
            styled_items[int(body_idx)] = runs
            item_palettes[int(body_idx)] = "dsk_point"
    elif extra_body:
        extra_text_items.append(
            {
                "text": point_text,
                "x": int(extra_body["x"]),
                "y": int(extra_body["y"]),
                "width": int(extra_body.get("width") or 350),
                "height": int(extra_body.get("height") or 125),
                "runs": [{"text": r.text, "style": r.style} for r in runs],
                "palette": "dsk_point",
            }
        )
    num_idx = mapping.get("point_number")
    if numbered and num_idx is not None and draft.point_number is not None:
        text_items[int(num_idx)] = str(draft.point_number)
    elif numbered and extra_num and draft.point_number is not None:
        extra_text_items.append(
            {
                "text": str(draft.point_number),
                "x": int(extra_num["x"]),
                "y": int(extra_num["y"]),
                "width": int(extra_num.get("width") or 140),
                "height": int(extra_num.get("height") or 50),
            }
        )
    ref = ""
    trans = "NIV"
    is_verse = False
    bind = "cue"
    role = "post" if post else "pre"
    source = list(draft.source_paragraphs)
    anchor = ""
    series_bit = outline.series_subtitle or outline.series_title
    if post and verse_draft is not None:
        offering = outline.context == "offering"
        max_chars = int(
            cfg.get("offering_verse_char_max", 190) if offering else cfg.get("verse_char_max", 220)
        )
        ref, trans, chunks = _verse_chunks(verse_draft, outline, max_chars)
        if "(MSG)" in outline.full_text.upper() and offering:
            trans = "MSG"
        chunk = chunks[0] if chunks else []
        verse_body = "".join(r.text for r in chunk)
        header = _passage_header(ref or series_bit, trans, series_bit)
        verse_idx = mapping.get("verse_body")
        ref_idx = mapping.get("reference")
        if verse_idx is not None:
            text_items[int(verse_idx)] = verse_body
            styled_items[int(verse_idx)] = chunk
            item_palettes[int(verse_idx)] = "dsk"
            if offering:
                widths[int(verse_idx)] = int(cfg.get("offering_verse_body_width", 1540))
        if ref_idx is not None:
            text_items[int(ref_idx)] = header
        is_verse = True
        bind = "verse_body"
        for para in verse_draft.source_paragraphs:
            if para not in source:
                source.append(para)
        anchor = _first_verse_number(chunk)
    return SlideSpec(
        deck="dsk",
        cue_tag="DSK-PP",
        operator_tag="DSK-PP",
        master=master,
        body=point_text,
        header=ref,
        reference=ref,
        text_items=text_items,
        styled_items=styled_items,
        text_item_widths=widths,
        text_item_heights=heights,
        text_item_positions=positions,
        text_item_font_sizes=font_sizes,
        item_palettes=item_palettes,
        extra_text_items=extra_text_items,
        is_verse=is_verse,
        translation=trans,
        context=outline.context,
        source_paragraphs=source,
        semantic_tag=tag,
        role=role,  # type: ignore[arg-type]
        block_index=block_index,
        bind=bind,
        chunk_index=0,
        anchor_verse=anchor,
        transition=MAGIC_MOVE if not post else None,
    )


def map_slides(outline: OutlineDoc) -> tuple[list[SlideSpec], list[SlideSpec], list[Flag]]:
    masters = load_masters()
    flags: list[Flag] = []
    lw: list[SlideSpec] = []
    dsk: list[SlideSpec] = []
    lw_cfg = masters["lw"]["cues"]
    dsk_cfg = masters["dsk"]["cues"]
    context = outline.context
    blocks = outline.blocks

    bumper_tags = {"TITLE", "FILLER"} if context == "sermon" else {"TITLE"}
    has_title = any(d.cue_tag in bumper_tags for d in blocks)
    if outline.series_title and not has_title:
        lw.append(
            SlideSpec(
                deck="lw",
                cue_tag="SERIES-TITLE",
                operator_tag="LW-TITLE",
                master=masters["lw"]["series_opener_master"],
                title=outline.series_title,
                body=outline.series_subtitle,
                is_graphic=True,
                notes=["Series bumper uses the TITLE master graphic as-is."],
                context=context,
                semantic_tag="TITLE",
                role="graphic",
                bind="cue",
            )
        )

    for i, draft in enumerate(blocks):
        tag = draft.cue_tag
        following = (
            blocks[draft.following_verse_index]
            if draft.verse_follows and draft.following_verse_index is not None
            else None
        )

        if tag == "TITLE" or (tag == "FILLER" and context == "sermon"):
            rule = lw_cfg["TITLE"] if tag == "TITLE" else lw_cfg["FILLER"]
            master = rule.get("master") or rule.get("sermon_master", "TITLE")
            operator = rule.get("operator") or rule.get("sermon_operator", "LW-TITLE")
            lw.append(
                _graphic_spec(
                    deck="lw",
                    cue_tag=operator,
                    operator_tag=operator,
                    master=master,
                    notes=[rule.get("note", "Title / filler uses the TITLE master background.")],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            continue

        if tag == "FILLER" and context == "offering":
            rule = lw_cfg["FILLER"]
            lw.append(
                _graphic_spec(
                    deck="lw",
                    cue_tag=rule["offering_operator"],
                    operator_tag=rule["offering_operator"],
                    master=rule["offering_master"],
                    notes=["Offering filler uses the BLANK holding slide (QR background)."],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            dsk.append(
                _graphic_spec(
                    deck="dsk",
                    cue_tag=rule["offering_dsk_operator"],
                    operator_tag=rule["offering_dsk_operator"],
                    master=rule["offering_dsk"],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            continue

        if tag == "FILLER-QR":
            rule = lw_cfg["FILLER-QR"]
            lw.append(
                _graphic_spec(
                    deck="lw",
                    cue_tag=rule["operator"],
                    operator_tag=rule["operator"],
                    master=rule["master"],
                    notes=["Offering filler uses the BLANK holding slide (QR background)."],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            dsk.append(
                _graphic_spec(
                    deck="dsk",
                    cue_tag=rule["dsk_operator"],
                    operator_tag=rule["dsk_operator"],
                    master=rule["dsk"],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            continue

        if tag == "GIVING-OPTIONS":
            rule = lw_cfg["GIVING-OPTIONS"]
            if rule.get("flag"):
                flags.append(Flag("warning", "mapping", rule["flag"], location=tag))
            lw.append(
                _graphic_spec(
                    deck="lw",
                    cue_tag=rule["operator"],
                    operator_tag=rule["operator"],
                    master=rule["master"],
                    flags=[rule["flag"]] if rule.get("flag") else [],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            dsk_rule = dsk_cfg["GIVING-OPTIONS"]
            if dsk_rule.get("flag"):
                flags.append(Flag("info", "mapping", dsk_rule["flag"], location=tag))
            dsk.append(
                _graphic_spec(
                    deck="dsk",
                    cue_tag=dsk_rule["operator"],
                    operator_tag=dsk_rule["operator"],
                    master=dsk_rule["master"],
                    flags=[dsk_rule["flag"]] if dsk_rule.get("flag") else [],
                    context=context,
                    source_paragraphs=draft.source_paragraphs,
                    semantic_tag=tag,
                    block_index=i,
                    bind="cue",
                )
            )
            continue

        if tag in {"POINT", "NUM-POINT"}:
            lw.append(_lw_point_spec(draft, outline, masters, i, post=False))
            dsk.append(_dsk_point_spec(draft, outline, masters, i, post=False))
            if following is not None:
                lw.append(
                    _lw_point_spec(draft, outline, masters, i, post=True, verse_draft=following)
                )
                if _dsk_post_point_fits(draft, masters):
                    dsk.append(
                        _dsk_point_spec(draft, outline, masters, i, post=True, verse_draft=following)
                    )
            continue

        if tag in VERSE_TAGS or _is_verse_draft(draft):
            continued = _looks_continued(draft, blocks, i)
            prefix = _continuation_prefix(outline, blocks, i) if continued else []
            lw.extend(
                _lw_verse_specs(
                    draft, outline, masters, i, prefix_runs=prefix, continued=continued
                )
            )
            dsk.extend(
                _dsk_verse_specs(
                    draft, outline, masters, i, prefix_runs=prefix, continued=continued
                )
            )
            continue

        # Unknown / legacy tag: treat like a point PRE on both decks.
        lw.append(_lw_point_spec(draft, outline, masters, i, post=False))
        dsk.append(_dsk_point_spec(draft, outline, masters, i, post=False))

    if not any(s.deck == "lw" for s in lw):
        flags.append(Flag("warning", "mapping", "No LW slides mapped from the outline."))
    if not dsk:
        flags.append(Flag("warning", "mapping", "No DSK slides mapped from the outline."))
    return lw, dsk, flags
