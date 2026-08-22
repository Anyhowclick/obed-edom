from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from obed_edom.models import Flag, OutlineDoc, SlideSpec

NAVY = HexColor("#1B2A4A")
DANGER = HexColor("#B42318")
DANGER_BG = HexColor("#FEF3F2")
BODY = HexColor("#222222")
MUTED = HexColor("#5C5C5C")


def _plain(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\u201c", "&quot;")
        .replace("\u201d", "&quot;")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2022", "-")
        .replace("\xa0", " ")
    )


def slide_kind(spec: SlideSpec) -> str:
    tag = spec.cue_tag.upper()
    master = spec.master.upper()
    if "QR" in tag or "QR" in master:
        return "Ways to give (QR code)"
    if "GIVING" in tag:
        if spec.master == "BLANK":
            return "Giving options (paste the graphic)"
        return "Giving options"
    if tag == "SERIES-TITLE" or spec.master == "TITLE" or spec.semantic_tag == "TITLE":
        return "Series title"
    if spec.role == "pre":
        return "Point (pre)"
    if spec.role == "post":
        return "Point with verse (post)"
    if spec.master == "BLANK" or (spec.is_graphic and not spec.body):
        return "Blank holding slide"
    if spec.is_verse:
        return "Bible verse"
    if spec.is_graphic:
        return "Graphic"
    return "Statement"


def _action_items(flags: list[Flag]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        if flag.severity not in {"warning", "error"}:
            continue
        text = _friendly_flag(flag)
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _friendly_flag(flag: Flag) -> str:
    msg = flag.message.strip()
    low = msg.lower()
    if "giving-options master" in low or "giving graphic" in low:
        return (
            "The LED wall file has a blank slide for giving options. "
            "Please paste in the giving graphic in Keynote."
        )
    if "credit card" in low or "bil" in low:
        return (
            "The lower-third giving slide uses the credit-card layout. "
            "In Keynote, switch to the BIL / no-card version if that is what you need this week."
        )
    if "cited as" in low and "wording matches" in low:
        return msg
    if "does not match" in low:
        return msg
    if "missing master" in low:
        return "A slide layout was missing from the Keynote template. Please tell the person who maintains the templates."
    if "png export" in low or "contrast not measured" in low:
        return "Preview pictures could not be exported, so we did not check how readable the words are on photo backgrounds."
    return msg


def _bible_notes(flags: list[Flag]) -> list[str]:
    notes: list[str] = []
    seen: set[str] = set()
    for flag in flags:
        if flag.category != "bible":
            continue
        text = _friendly_bible(flag)
        if not text or text in seen:
            continue
        seen.add(text)
        notes.append(text)
    return notes


def _friendly_bible(flag: Flag) -> str | None:
    msg = flag.message.strip()
    low = msg.lower()
    if "set passage cursor" in low:
        return None
    if low.startswith("resolved "):
        return None
    if "cited as" in low and "wording matches" in low:
        return msg
    if "does not match" in low or "please check the book" in low:
        return msg
    if "not text-checked" in low or "returned no passage" in low or "bible gateway error" in low or "bible gateway http" in low:
        return (
            "We could not fully auto-check every verse against Bible Gateway. "
            "The wording on the slide is taken from the Word outline."
        )
    if "overlap" in low or "bible gateway" in low:
        return None
    if flag.severity in {"warning", "error"}:
        return msg
    return None


def _contrast_note(flags: list[Flag]) -> str:
    contrast = [f for f in flags if f.category == "contrast"]
    if any(
        "could not" in f.message.lower()
        or "did not run" in f.message.lower()
        or "no png" in f.message.lower()
        for f in contrast
    ):
        return "Preview pictures were not exported, so please check the Keynote files yourself."
    if any(f.severity == "warning" for f in contrast):
        return (
            "Some LED wall slides sit on a bright photo. Darken the background in Keynote "
            "so the words stay readable. Do not recolor the text unless something still looks wrong."
        )
    if contrast:
        return "We looked at the preview pictures. Contrast looked OK."
    return "Open the previews folder for a quick look before service."


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=NAVY,
            spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            textColor=MUTED,
            spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=10.5,
            leading=14.5,
            textColor=BODY,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),
        "item": ParagraphStyle(
            "item",
            fontName="Helvetica",
            fontSize=10.5,
            leading=14.5,
            textColor=BODY,
        ),
        "danger": ParagraphStyle(
            "danger",
            fontName="Helvetica",
            fontSize=10.5,
            leading=14.5,
            textColor=HexColor("#7A271A"),
        ),
    }


SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "success": 3}


def write_outline_findings(path: Path, report: dict) -> Path:
    """A printable copy of the outline findings, in reading order.

    Operators mark up a paper script, so the findings are listed against the
    paragraph they belong to rather than grouped by rule.
    """
    path = Path(path).with_suffix(".pdf")
    styles = _styles()
    name = str(report.get("name") or "Outline")
    flags = list(report.get("outlineFlags") or [])

    story: list = [Paragraph(_plain(name), styles["title"])]
    story.append(
        Paragraph(
            _plain(
                f"{report.get('lwCues', 0)} LW and {report.get('dskCues', 0)} DSK cues "
                f"across {len(report.get('rows') or [])} slide advances."
            ),
            styles["subtitle"],
        )
    )

    by_paragraph: dict[int, list[dict]] = {}
    loose: list[dict] = []
    for flag in flags:
        number = flag.get("slide")
        if number is None:
            loose.append(flag)
        else:
            by_paragraph.setdefault(int(number), []).append(flag)

    def line(flag: dict) -> Paragraph:
        head = flag.get("title") or flag.get("rule") or flag.get("category") or "Finding"
        text = f"<b>{_plain(str(head))}</b> &#8212; {_plain(str(flag.get('message') or ''))}"
        style = styles["danger"] if flag.get("severity") in {"error", "warning"} else styles["item"]
        return Paragraph(text, style)

    story.append(Paragraph("Findings in the script", styles["h1"]))
    if not flags:
        story.append(Paragraph("Nothing to flag.", styles["body"]))
    for para in report.get("paragraphs") or []:
        found = by_paragraph.get(int(para.get("number") or 0))
        if not found:
            continue
        story.append(Paragraph(_plain(f"Paragraph {para.get('number')}"), styles["h1"]))
        story.append(Paragraph(_plain((para.get("text") or "").strip()[:400]), styles["body"]))
        for flag in sorted(found, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9)):
            story.append(line(flag))
            story.append(Spacer(1, 3))

    if loose:
        story.append(Paragraph("Whole outline", styles["h1"]))
        for flag in sorted(loose, key=lambda f: SEVERITY_ORDER.get(f.get("severity"), 9)):
            story.append(line(flag))
            story.append(Spacer(1, 3))

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=name,
        author="Obed-Edom",
    ).build(story)
    return path


def write_review(
    path: Path,
    outline: OutlineDoc,
    lw: list[SlideSpec],
    dsk: list[SlideSpec],
    flags: list[Flag],
    lw_key: Path | None,
    dsk_key: Path | None,
) -> None:
    _ = lw, dsk, lw_key, dsk_key
    path = path.with_suffix(".pdf")
    styles = _styles()
    kind = "Offering" if outline.context == "offering" else "Sermon"
    series = " ".join(p for p in (outline.series_title, outline.series_subtitle) if p).strip()
    date = (outline.date_line or "").strip("() ").strip()
    heading = series or kind

    subtitle_bits = [kind]
    if date:
        subtitle_bits.append(date)
    subtitle = "  |  ".join(bit for bit in subtitle_bits if bit != heading)

    story: list = []
    story.append(Paragraph(_plain(heading), styles["title"]))
    if subtitle:
        story.append(Paragraph(_plain(subtitle), styles["subtitle"]))

    actions = _action_items(flags)
    story.append(Paragraph("Please check", styles["h1"]))
    if actions:
        inner = [Paragraph("Please look at these before service:", styles["danger"]), Spacer(1, 4)]
        for item in actions:
            inner.append(Paragraph(f"&#8226; {_plain(item)}", styles["danger"]))
            inner.append(Spacer(1, 3))
        table = Table([[inner]], colWidths=[7.1 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), DANGER_BG),
                    ("BOX", (0, 0), (-1, -1), 0.75, DANGER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        story.append(table)
    else:
        story.append(
            Paragraph(
                "Nothing urgent. Please still skim the preview pictures before service.",
                styles["body"],
            )
        )

    bible = _bible_notes(flags)
    story.append(Paragraph("Bible wording", styles["h1"]))
    if bible:
        items = [ListItem(Paragraph(_plain(n), styles["item"]), leftIndent=8) for n in bible]
        story.append(ListFlowable(items, bulletType="bullet", leftIndent=12, bulletFontSize=9))
        story.append(
            Paragraph(
                "The words on the slide always come from the Word outline. Please proofread verses in Keynote.",
                styles["body"],
            )
        )
    else:
        story.append(
            Paragraph(
                "Nothing unusual came up. The words on the slides come from the Word outline. Please still proofread verses.",
                styles["body"],
            )
        )

    story.append(Paragraph("Readability", styles["h1"]))
    story.append(Paragraph(_plain(_contrast_note(flags)), styles["body"]))

    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "When you are done checking, open both Keynote files and polish as needed. "
            "The original templates were not changed.",
            styles["subtitle"],
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
        title=heading,
        author="Obed-Edom",
    )
    doc.build(story)
