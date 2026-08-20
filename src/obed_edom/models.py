from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["info", "warning", "error", "success"]
Deck = Literal["lw", "dsk"]
Context = Literal["sermon", "offering"]
Role = Literal["graphic", "pre", "post", "verse", "point"]


@dataclass
class Run:
    text: str
    bold: bool = False
    highlight: str | None = None
    superscript: bool = False
    color: str | None = None


@dataclass
class Paragraph:
    runs: list[Run]
    index: int = 0

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Cue:
    raw: str
    tag: str  # TITLE, VERSE, LW-TITLE, DSK-PP, ...
    paragraph: int
    offset: int
    end: int = 0
    deck: Deck | None = None
    semantic: bool = True


@dataclass
class TextSpan:
    text: str
    bold: bool = False
    verse_number: str | None = None
    highlight: str | None = None


@dataclass
class StyledRun:
    text: str
    style: str  # verse_number | normal | highlight


@dataclass
class Transition:
    effect: str = "magic_move"
    duration: float = 1.0
    match: str = "word"


@dataclass
class SlideSpec:
    deck: Deck
    cue_tag: str
    master: str
    title: str = ""
    body: str = ""
    header: str = ""
    text_items: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    context: Context = "sermon"
    source_paragraphs: list[int] = field(default_factory=list)
    is_verse: bool = False
    is_graphic: bool = False
    translation: str = "NIV"
    reference: str = ""
    styled_items: dict[int, list[StyledRun]] = field(default_factory=dict)
    text_item_widths: dict[int, int] = field(default_factory=dict)
    text_item_heights: dict[int, int] = field(default_factory=dict)
    text_item_positions: dict[int, tuple[int, int]] = field(default_factory=dict)
    text_item_font_sizes: dict[int, float] = field(default_factory=dict)
    item_palettes: dict[int, str] = field(default_factory=dict)
    extra_text_items: list[dict] = field(default_factory=list)
    transition: Transition | None = None
    semantic_tag: str = ""
    role: Role = "point"
    block_index: int = -1
    bind: str = "cue"  # cue | verse_body
    anchor_verse: str = ""
    chunk_index: int = 0
    operator_tag: str = ""


@dataclass
class Flag:
    severity: Severity
    category: str
    message: str
    location: str = ""
    resolved: str | None = None


@dataclass
class BibleCursor:
    book: str | None = None
    chapter: int | None = None
    verse: int | None = None
    verse_end: int | None = None
    translation: str = "NIV"

    def label(self) -> str:
        if not self.book:
            return ""
        if self.chapter is None:
            return self.book
        if self.verse is None:
            return f"{self.book} {self.chapter}"
        if self.verse_end and self.verse_end != self.verse:
            return f"{self.book} {self.chapter}:{self.verse}-{self.verse_end}"
        return f"{self.book} {self.chapter}:{self.verse}"


@dataclass
class SlideDraft:
    cue_tag: str
    body_spans: list[TextSpan] = field(default_factory=list)
    source_paragraphs: list[int] = field(default_factory=list)
    speaker_notes: list[str] = field(default_factory=list)
    green_title: str = ""
    force_verse: bool = False
    point_number: int | None = None
    cue_raw: str = ""
    cue_paragraph: int = 0
    cue_offset: int = 0
    cue_end: int = 0
    verse_follows: bool = False
    following_verse_index: int | None = None

    @property
    def body(self) -> str:
        return "".join(s.text for s in self.body_spans).strip()

    @property
    def has_verse_numbers(self) -> bool:
        return any(s.verse_number for s in self.body_spans)

    @property
    def is_empty(self) -> bool:
        return not self.body and not self.green_title


@dataclass
class OutlineDoc:
    path: Path
    paragraphs: list[Paragraph]
    series_title: str = ""
    series_subtitle: str = ""
    date_line: str = ""
    context: Context = "sermon"
    blocks: list[SlideDraft] = field(default_factory=list)
    lw_slides: list[SlideDraft] = field(default_factory=list)
    dsk_slides: list[SlideDraft] = field(default_factory=list)
    full_text: str = ""


@dataclass
class GenerationResult:
    output_dir: Path
    lw_key: Path | None
    dsk_key: Path | None
    review_path: Path
    flags: list[Flag]
    lw_slides: list[SlideSpec]
    dsk_slides: list[SlideSpec]
    cued_docx: Path | None = None
    extras: dict[str, Any] = field(default_factory=dict)
