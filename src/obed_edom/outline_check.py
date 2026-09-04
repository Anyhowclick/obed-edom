"""Check a cued outline against the decks it calls.

Correspondence counts cues vs slides (no text — works on JPEG/.mov exports).
Corroboration ranks wording: outline, then LW, then DSK (or LW first once
the wall is signed off). Findings only; nothing is rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from obed_edom.models import Flag, Paragraph
from obed_edom.parse_outline import (
    CUE_RE,
    SEMANTIC_TAGS,
    STAGE_RE,
    load_paragraphs,
    normalize_cue,
)
from obed_edom.text_diff import fingerprint, text_score, texts_equivalent
from obed_edom.validate import make_flag

# Bracketed tokens that are neither cue nor stage direction.
BRACKET_RE = re.compile(r"\[[^\]\n]{1,60}\]")

# Below this, words after a cue are preacher commentary, not slide copy.
SCRIPT_MATCH = 0.45

# Cap per-item findings before "and N more".
MAX_REPORTED = 8


class SemanticOutlineError(ValueError):
    pass


@dataclass(frozen=True)
class CueRef:
    tag: str
    deck: str
    raw: str
    paragraph: int
    start: int
    end: int


@dataclass
class CueRow:
    index: int
    lw: CueRef | None = None
    dsk: CueRef | None = None
    script: str = ""
    paragraph: int = 0
    offset: int = 0

    @property
    def cues(self) -> list[CueRef]:
        return [c for c in (self.lw, self.dsk) if c is not None]

    @property
    def tags(self) -> list[str]:
        return [c.tag for c in self.cues]

    @property
    def label(self) -> str:
        return " ".join(f"[{tag}]" for tag in self.tags) or "(no cue)"


@dataclass
class Playlist:
    rows: list[CueRow] = field(default_factory=list)
    unknown: list[tuple[int, str]] = field(default_factory=list)

    @property
    def lw_cues(self) -> list[CueRef]:
        return [row.lw for row in self.rows if row.lw is not None]

    @property
    def dsk_cues(self) -> list[CueRef]:
        return [row.dsk for row in self.rows if row.dsk is not None]

    def count(self, deck: str) -> int:
        return len(self.lw_cues if deck == "lw" else self.dsk_cues)


def read_cues(paragraphs: list[Paragraph]) -> list[CueRef]:
    """Operator cues in reading order. Uses `CUE_RE` on paragraph text, not runs."""
    out: list[CueRef] = []
    for para in paragraphs:
        for match in CUE_RE.finditer(para.text):
            cue = normalize_cue(match.group(0))
            if cue.semantic:
                continue
            out.append(
                CueRef(
                    tag=cue.tag,
                    deck=cue.deck or "lw",
                    raw=match.group(0),
                    paragraph=para.index,
                    start=match.start(),
                    end=match.end(),
                )
            )
    return out


def outline_flavour(paragraphs: list[Paragraph]) -> str:
    semantic = deck = 0
    for para in paragraphs:
        for match in CUE_RE.finditer(para.text):
            if normalize_cue(match.group(0)).semantic:
                semantic += 1
            else:
                deck += 1
    if deck:
        return "cued"
    return "semantic" if semantic else "none"


def _unknown_brackets(paragraphs: list[Paragraph]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for para in paragraphs:
        text = para.text
        spans = [(m.start(), m.end()) for m in CUE_RE.finditer(text)]
        spans += [(m.start(), m.end()) for m in STAGE_RE.finditer(text)]
        for match in BRACKET_RE.finditer(text):
            if any(match.start() >= s and match.end() <= e for s, e in spans):
                continue
            out.append((para.index, match.group(0)))
    return out


def _is_bare_reference(text: str) -> bool:
    from obed_edom.parse_outline import _is_bare_reference as bare  # noqa: PLC0415

    return bare(text)


def cue_playlist(paragraphs: list[Paragraph]) -> Playlist:
    """One row per slide advance. Whitespace-only gaps keep `[LW][DSK-PP]` together."""
    cues = read_cues(paragraphs)
    by_index = {para.index: para for para in paragraphs}
    rows: list[CueRow] = []
    current: CueRow | None = None
    previous: CueRef | None = None

    for cue in cues:
        adjacent = (
            current is not None
            and previous is not None
            and cue.paragraph == previous.paragraph
            and not by_index[cue.paragraph].text[previous.end : cue.start].strip()
        )
        slot_taken = current is not None and getattr(current, cue.deck) is not None
        if not adjacent or slot_taken:
            current = CueRow(index=len(rows), paragraph=cue.paragraph, offset=cue.start)
            rows.append(current)
        setattr(current, cue.deck, cue)
        previous = cue

    _attach_script(rows, paragraphs, by_index)
    return Playlist(rows=rows, unknown=_unknown_brackets(paragraphs))


def _attach_script(
    rows: list[CueRow], paragraphs: list[Paragraph], by_index: dict[int, Paragraph]
) -> None:
    order = [para.index for para in paragraphs]
    for position, row in enumerate(rows):
        last = row.cues[-1]
        stop = rows[position + 1].cues[0] if position + 1 < len(rows) else None
        parts: list[str] = []
        start_para = last.paragraph
        tail = by_index[start_para].text[last.end :]
        if stop is not None and stop.paragraph == start_para:
            tail = by_index[start_para].text[last.end : stop.start]
        parts.append(tail)
        if stop is None or stop.paragraph != start_para:
            begin = order.index(start_para) + 1
            for index in order[begin:]:
                if stop is not None and index == stop.paragraph:
                    parts.append(by_index[index].text[: stop.start])
                    break
                parts.append(by_index[index].text)
        # Generate cues the verse body; hand-authored outlines cue the reference line.
        lead = _preceding_reference(rows, position, order, by_index)
        text = "\n".join(part for part in ([lead] + parts) if part and part.strip())
        row.script = STAGE_RE.sub("", text).strip()


def _preceding_reference(
    rows: list[CueRow], position: int, order: list[int], by_index: dict[int, Paragraph]
) -> str:
    row = rows[position]
    first = row.cues[0]
    if first.start != 0 or by_index[first.paragraph].text[: first.start].strip():
        return ""
    place = order.index(first.paragraph)
    if place == 0:
        return ""
    above = by_index[order[place - 1]]
    if not above.text.strip() or not _is_bare_reference(above.text):
        return ""
    if position and rows[position - 1].cues[-1].paragraph == above.index:
        return ""
    return above.text.strip()


def load_playlist(path: Path | str) -> tuple[Playlist, list[Paragraph]]:
    paragraphs = load_paragraphs(Path(path))
    flavour = outline_flavour(paragraphs)
    if flavour != "cued":
        raise SemanticOutlineError(
            "This looks like a pre-generate outline: it still has semantic cues "
            f"({', '.join(sorted(SEMANTIC_TAGS))}) rather than operator [LW] / [DSK] "
            "cues. Run the Sermon Base Generator first, then check the _CUED.docx."
            if flavour == "semantic"
            else "No operator [LW] / [DSK] cues found in this outline."
        )
    return cue_playlist(paragraphs), paragraphs


def outline_report(path: Path | str) -> dict:
    """Paragraphs with cue spans plus findings pinned to a paragraph."""
    from obed_edom.parse_outline import parse_outline  # noqa: PLC0415
    from obed_edom.validate import flag_dict, validate_outline_paragraphs  # noqa: PLC0415

    path = Path(path)
    playlist, paragraphs = load_playlist(path)
    row_of: dict[int, int] = {}
    for row in playlist.rows:
        for cue in row.cues:
            row_of.setdefault(cue.paragraph, row.index)

    cues_by_para: dict[int, list[dict]] = {}
    for row in playlist.rows:
        for cue in row.cues:
            cues_by_para.setdefault(cue.paragraph, []).append(
                {
                    "tag": cue.tag,
                    "deck": cue.deck,
                    "start": cue.start,
                    "end": cue.end,
                    "row": row.index,
                }
            )

    flags = list(correspondence(playlist, {}))
    try:
        flags.extend(validate_outline_paragraphs(parse_outline(path)))
    except Exception as exc:  # noqa: BLE001
        note = make_flag(
            "cue.unknown",
            "outline",
            f"The outline could not be fully parsed for style and scripture checks ({exc}).",
            default="info",
            location=path.name,
            deck="outline",
        )
        if note:
            flags.append(note)

    return {
        "path": str(path),
        "name": path.name,
        "lwCues": playlist.count("lw"),
        "dskCues": playlist.count("dsk"),
        "paragraphs": [
            {
                "index": para.index,
                "number": para.index + 1,
                "text": para.text,
                "cues": cues_by_para.get(para.index, []),
                "row": row_of.get(para.index),
            }
            for para in paragraphs
        ],
        "rows": [
            {
                "index": row.index,
                "tags": row.tags,
                "lw": row.lw.tag if row.lw else None,
                "dsk": row.dsk.tag if row.dsk else None,
                "paragraph": row.paragraph,
                "script": row.script,
            }
            for row in playlist.rows
        ],
        "outlineFlags": [flag_dict(f) for f in flags],
    }


def visible(catalog: list[dict]) -> list[dict]:
    return [s for s in catalog if not s.get("skipped")]


DECK_LABELS = {"lw": "LW", "dsk": "DSK"}


def correspondence(playlist: Playlist, catalogs: dict[str, list[dict]]) -> list[Flag]:
    """Cue counts against slide counts. Reads no slide text."""
    flags: list[Flag] = []

    for para, raw in playlist.unknown:
        _keep(
            flags,
            make_flag(
                "cue.unknown",
                "cue",
                f"{raw} is not a cue or a stage direction. Check the spelling, or "
                "remove it if it is a note.",
                location=f"outline paragraph {para + 1}",
                deck="outline",
            ),
        )

    for deck, catalog in catalogs.items():
        label = DECK_LABELS.get(deck, deck.upper())
        slides = visible(catalog)
        cues = playlist.lw_cues if deck == "lw" else playlist.dsk_cues
        if len(cues) != len(slides):
            _keep(
                flags,
                make_flag(
                    f"cue.{deck}_count",
                    "cue",
                    f"The outline calls {len(cues)} {label} slide"
                    f"{'' if len(cues) == 1 else 's'} but the deck has {len(slides)}. "
                    "Every slide needs exactly one cue.",
                    location=label,
                    deck=deck,
                ),
            )
        for extra in slides[len(cues) :][:MAX_REPORTED]:
            _keep(
                flags,
                make_flag(
                    "cue.uncued_slide",
                    "cue",
                    f"{label} slide {extra.get('number')} has no cue in the outline, "
                    "so the operator has nothing telling them to advance here.",
                    location=f"{label} slide {extra.get('number')}",
                    slide=extra.get("number"),
                    deck=deck,
                ),
            )
        for cue in cues[len(slides) :][:MAX_REPORTED]:
            _keep(
                flags,
                make_flag(
                    "cue.no_slide",
                    "cue",
                    f"[{cue.tag}] calls a {label} slide that is not in the deck.",
                    location=f"outline paragraph {cue.paragraph + 1}",
                    deck=deck,
                ),
            )

    if len(catalogs) > 1:
        flags.extend(_hold_notes(playlist))
    return flags


def _hold_notes(playlist: Playlist) -> list[Flag]:
    flags: list[Flag] = []
    for row in playlist.rows:
        if row.lw and row.dsk:
            continue
        held = "LW" if row.dsk else "DSK"
        moved = "DSK" if row.dsk else "LW"
        _keep(
            flags,
            make_flag(
                "cue.hold",
                "cue",
                f"{row.label} steps {moved} only, so {held} holds on the previous slide.",
                default="info",
                location=f"outline paragraph {row.paragraph + 1}",
                deck="outline",
            ),
        )
    return flags


def slots_from_cues(
    playlist: Playlist,
    lw_catalog: list[dict],
    dsk_catalog: list[dict],
    *,
    left_deck: str = "lw",
) -> list[tuple[int | None, list[int], float]]:
    """Playlist → pairing slots. A DSK-only row folds onto the previous wall hold."""
    lw_left = [s["index"] for s in visible(lw_catalog)]
    dsk_left = [s["index"] for s in visible(dsk_catalog)]
    slots: list[tuple[int | None, list[int], float]] = []
    lw_at = dsk_at = 0
    for row in playlist.rows:
        lw_index = None
        if row.lw is not None and lw_at < len(lw_left):
            lw_index = lw_left[lw_at]
            lw_at += 1
        dsk_indexes: list[int] = []
        if row.dsk is not None and dsk_at < len(dsk_left):
            dsk_indexes.append(dsk_left[dsk_at])
            dsk_at += 1
        if lw_index is None and dsk_indexes and slots:
            previous = slots[-1]
            slots[-1] = (previous[0], previous[1] + dsk_indexes, previous[2])
            continue
        if lw_index is None and not dsk_indexes:
            continue
        slots.append((lw_index, dsk_indexes, 1.0))

    if left_deck != "lw":
        return [(right[0] if right else None, [left] if left is not None else [], score)
                for left, right, score in slots]
    return slots


def rows_for_slots(
    playlist: Playlist, slots: list[tuple[int | None, list[int], float]]
) -> list[CueRow | None]:
    out: list[CueRow | None] = []
    cursor = 0
    for _slot in slots:
        row = playlist.rows[cursor] if cursor < len(playlist.rows) else None
        out.append(row)
        cursor += 1
        while cursor < len(playlist.rows) and playlist.rows[cursor].lw is None:
            cursor += 1
    return out


def corroborate(
    script: str,
    lw_text: str,
    dsk_text: str,
    *,
    location: str = "",
    slide: int | None = None,
    typed: bool = True,
    lw_final: bool = True,
) -> list[Flag]:
    """Signed-off wall: LW, then outline, then DSK. Else outline, then LW, then DSK."""
    script = (script or "").strip()
    lw_text = (lw_text or "").strip()
    dsk_text = (dsk_text or "").strip()
    if not script:
        return []
    have = [t for t in (lw_text, dsk_text) if t]
    if not have:
        return []
    if max(text_score(script, t) for t in have) < SCRIPT_MATCH:
        return []

    suffix = (
        ""
        if typed
        else " Read by OCR because this slide has no selectable text, so check it by eye."
    )

    if not lw_text or not dsk_text:
        deck_text = lw_text or dsk_text
        deck = "lw" if lw_text else "dsk"
        if texts_equivalent(script, deck_text):
            return []
        if deck == "lw" and lw_final:
            return _one(
                "outline.stale",
                "The finalised wall does not match the outline, so the script the "
                "operator is calling from is out of date." + suffix,
                script,
                lw_text,
                "LW",
                typed,
                location,
                slide,
                "outline",
            )
        return _one(
            f"outline.{deck}_deviates",
            f"{DECK_LABELS[deck]} does not match the outline.{suffix}",
            script,
            deck_text,
            DECK_LABELS[deck],
            typed,
            location,
            slide,
            deck,
        )

    lw_ok = texts_equivalent(script, lw_text)
    dsk_ok = texts_equivalent(script, dsk_text)
    if lw_ok and dsk_ok:
        return []
    if lw_ok and not dsk_ok:
        return _one(
            "outline.dsk_deviates",
            "DSK disagrees with the outline and with LW, so DSK is the odd one out."
            + suffix,
            script,
            dsk_text,
            "DSK",
            typed,
            location,
            slide,
            "dsk",
        )
    if dsk_ok and not lw_ok:
        if lw_final:
            return _one(
                "outline.dsk_stale",
                "The wall was finalised past both the outline and DSK, so the "
                "Pastor's change never reached the lower third." + suffix,
                lw_text,
                dsk_text,
                "DSK",
                typed,
                location,
                slide,
                "dsk",
                source="LW",
            )
        return _one(
            "outline.lw_deviates",
            "LW departs from the outline while DSK still follows it. Either the wall "
            "was edited after the script, or the wall is wrong." + suffix,
            script,
            lw_text,
            "LW",
            typed,
            location,
            slide,
            "lw",
        )
    if texts_equivalent(lw_text, dsk_text):
        if lw_final:
            return _one(
                "outline.stale",
                "Both decks agree, so the script the operator is calling from is "
                "out of date." + suffix,
                script,
                lw_text,
                "the decks",
                typed,
                location,
                slide,
                "outline",
            )
        return _one(
            "outline.both_deviate",
            "Both decks agree with each other but not with the outline, so either "
            "the change never reached the script or both decks are wrong." + suffix,
            script,
            lw_text,
            "the decks",
            typed,
            location,
            slide,
            "outline",
        )
    flag = make_flag(
        "outline.three_way",
        "outline",
        "Outline, LW and DSK all read differently here." + suffix + "\n"
        f"Outline: {_brief(script)}\nLW: {_brief(lw_text)}\nDSK: {_brief(dsk_text)}",
        default="info",
        location=location,
        slide=slide,
        deck="outline",
    )
    return [flag] if flag else []


def _one(
    rule: str,
    headline: str,
    source_text: str,
    deck_text: str,
    label: str,
    typed: bool,
    location: str,
    slide: int | None,
    deck: str,
    source: str = "Outline",
) -> list[Flag]:
    flag = make_flag(
        rule,
        "outline",
        f"{headline}\n{source}: {_brief(source_text)}\n{label}: {_brief(deck_text)}",
        location=location,
        slide=slide,
        deck=deck,
    )
    flag = _demote(flag, typed)
    return [flag] if flag else []


def _demote(flag: Flag | None, typed: bool) -> Flag | None:
    """OCR guesses are notes; configured severity otherwise wins over make_flag defaults."""
    if flag is None or typed or flag.severity == "info":
        return flag
    return replace(flag, severity="info")


def _brief(text: str, limit: int = 160) -> str:
    folded = re.sub(r"[\s\u2028\u2029\xa0]+", " ", (text or "")).strip()
    return folded[:limit] + ("…" if len(folded) > limit else "")


def _keep(flags: list[Flag], flag: Flag | None) -> None:
    if flag is not None:
        flags.append(flag)


def script_matches(script: str, text: str) -> bool:
    return bool(script and text and fingerprint(script) and text_score(script, text) >= SCRIPT_MATCH)
