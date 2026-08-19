from __future__ import annotations

import html as html_lib
import re
import unicodedata
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from sermon_slides.models import BibleCursor, Flag, OutlineDoc

load_dotenv()

BOOK_ALIASES = {
    "genesis": "Genesis",
    "gen": "Genesis",
    "gn": "Genesis",
    "exodus": "Exodus",
    "exod": "Exodus",
    "ex": "Exodus",
    "leviticus": "Leviticus",
    "lev": "Leviticus",
    "numbers": "Numbers",
    "num": "Numbers",
    "nm": "Numbers",
    "deuteronomy": "Deuteronomy",
    "deut": "Deuteronomy",
    "dt": "Deuteronomy",
    "joshua": "Joshua",
    "josh": "Joshua",
    "judges": "Judges",
    "judg": "Judges",
    "jdg": "Judges",
    "ruth": "Ruth",
    "1 samuel": "1 Samuel",
    "1 sam": "1 Samuel",
    "2 samuel": "2 Samuel",
    "2 sam": "2 Samuel",
    "1 kings": "1 Kings",
    "1 kgs": "1 Kings",
    "2 kings": "2 Kings",
    "2 kgs": "2 Kings",
    "1 chronicles": "1 Chronicles",
    "1 chr": "1 Chronicles",
    "2 chronicles": "2 Chronicles",
    "2 chr": "2 Chronicles",
    "ezra": "Ezra",
    "nehemiah": "Nehemiah",
    "neh": "Nehemiah",
    "esther": "Esther",
    "est": "Esther",
    "job": "Job",
    "psalm": "Psalm",
    "psalms": "Psalm",
    "ps": "Psalm",
    "psa": "Psalm",
    "proverbs": "Proverbs",
    "prov": "Proverbs",
    "prv": "Proverbs",
    "ecclesiastes": "Ecclesiastes",
    "eccl": "Ecclesiastes",
    "ecc": "Ecclesiastes",
    "song of songs": "Song of Songs",
    "song of solomon": "Song of Songs",
    "sos": "Song of Songs",
    "isaiah": "Isaiah",
    "isa": "Isaiah",
    "jeremiah": "Jeremiah",
    "jer": "Jeremiah",
    "lamentations": "Lamentations",
    "lam": "Lamentations",
    "ezekiel": "Ezekiel",
    "ezek": "Ezekiel",
    "eze": "Ezekiel",
    "ez": "Ezekiel",
    "daniel": "Daniel",
    "dan": "Daniel",
    "hosea": "Hosea",
    "hos": "Hosea",
    "joel": "Joel",
    "amos": "Amos",
    "obadiah": "Obadiah",
    "obad": "Obadiah",
    "jonah": "Jonah",
    "jon": "Jonah",
    "micah": "Micah",
    "mic": "Micah",
    "nahum": "Nahum",
    "nah": "Nahum",
    "habakkuk": "Habakkuk",
    "hab": "Habakkuk",
    "zephaniah": "Zephaniah",
    "zeph": "Zephaniah",
    "haggai": "Haggai",
    "hag": "Haggai",
    "zechariah": "Zechariah",
    "zech": "Zechariah",
    "zec": "Zechariah",
    "malachi": "Malachi",
    "mal": "Malachi",
    "matthew": "Matthew",
    "matt": "Matthew",
    "mt": "Matthew",
    "mark": "Mark",
    "mk": "Mark",
    "luke": "Luke",
    "lk": "Luke",
    "john": "John",
    "jn": "John",
    "acts": "Acts",
    "romans": "Romans",
    "rom": "Romans",
    "ro": "Romans",
    "1 corinthians": "1 Corinthians",
    "1 cor": "1 Corinthians",
    "1 co": "1 Corinthians",
    "2 corinthians": "2 Corinthians",
    "2 cor": "2 Corinthians",
    "galatians": "Galatians",
    "gal": "Galatians",
    "ephesians": "Ephesians",
    "eph": "Ephesians",
    "philippians": "Philippians",
    "phil": "Philippians",
    "php": "Philippians",
    "colossians": "Colossians",
    "col": "Colossians",
    "1 thessalonians": "1 Thessalonians",
    "1 thess": "1 Thessalonians",
    "1 th": "1 Thessalonians",
    "2 thessalonians": "2 Thessalonians",
    "2 thess": "2 Thessalonians",
    "1 timothy": "1 Timothy",
    "1 tim": "1 Timothy",
    "2 timothy": "2 Timothy",
    "2 tim": "2 Timothy",
    "titus": "Titus",
    "tit": "Titus",
    "philemon": "Philemon",
    "phlm": "Philemon",
    "hebrews": "Hebrews",
    "heb": "Hebrews",
    "james": "James",
    "jas": "James",
    "1 peter": "1 Peter",
    "1 pet": "1 Peter",
    "1 pe": "1 Peter",
    "2 peter": "2 Peter",
    "2 pet": "2 Peter",
    "1 john": "1 John",
    "1 jn": "1 John",
    "2 john": "2 John",
    "2 jn": "2 John",
    "3 john": "3 John",
    "3 jn": "3 John",
    "jude": "Jude",
    "revelation": "Revelation",
    "rev": "Revelation",
}

BOOK_PATTERN = "|".join(
    sorted((re.escape(k) for k in BOOK_ALIASES), key=len, reverse=True)
)

ABS_REF_RE = re.compile(
    rf"(?P<book>{BOOK_PATTERN})\.?\s+(?P<chapter>\d{{1,3}})"
    rf"(?::(?P<verse>\d{{1,3}})(?:\s*[-–]\s*(?P<end>\d{{1,3}}))?)?"
    rf"(?:\s*\((?P<translation>[A-Za-z]+)\))?",
    re.IGNORECASE,
)
REL_VERSE_RE = re.compile(
    r"\b(?:verse|v\.?|vv\.?)\s*(?P<verse>\d+)(?:\s*[-–]\s*(?P<end>\d+))?\b",
    re.IGNORECASE,
)
FEW_VERSES_RE = re.compile(
    r"a few verses?\s+(down|later|earlier|back|before|after)|"
    r"(next|previous|preceding)\s+verse|"
    r"verses?\s+later",
    re.IGNORECASE,
)
SAME_CHAPTER_RE = re.compile(r"\b(same chapter|this chapter|in this chapter)\b", re.IGNORECASE)
FEW_CHAPTERS_RE = re.compile(
    r"a few chapters?\s+(later|down|earlier)|next chapter|previous chapter",
    re.IGNORECASE,
)


def _norm_book(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip().lower().rstrip("."))
    return BOOK_ALIASES.get(key, name.strip().title())


_STOPWORDS = {
    "the", "and", "to", "of", "a", "in", "you", "your", "for", "that", "this",
    "with", "from", "not", "but", "are", "was", "were", "will", "have", "has",
    "had", "his", "her", "their", "them", "they", "him", "she", "who", "what",
    "when", "then", "than", "into", "onto", "over", "such", "most", "dont",
    "does", "did", "been", "being", "its", "our", "out", "all", "can", "so",
}
_CHROME_MARKERS = (
    "bible gateway logo",
    "available versions",
    "advanced search",
    "bible gateway plus",
    "log in/sign up",
)
GOSPEL_BOOKS = ("Matthew", "Mark", "Luke", "John")
MATCH_OVERLAP = 0.55
MISMATCH_OVERLAP = 0.45


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace("\xa0", " ")
    text = re.sub(r"[“”\"'`‘’]", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _content_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _normalize_text(text).split()
        if len(tok) >= 4 and tok not in _STOPWORDS and not tok.isdigit()
    }


def _token_overlap(a: str, b: str) -> float:
    """How much of the outline wording appears in the fetched passage."""
    ta = _content_tokens(a)
    tb = _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def _quote_without_refs(body: str) -> str:
    return ABS_REF_RE.sub(" ", body)


@dataclass
class _Hit:
    kind: str
    start: int
    text: str
    book: str | None = None
    chapter: int | None = None
    verse: int | None = None
    verse_end: int | None = None
    translation: str | None = None
    phrase: str | None = None


def _line_at(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    if end < 0:
        end = len(text)
    return text[start:end].strip()


_GATEWAY_CACHE: dict[tuple[str, int, int, int, str], tuple[str | None, str]] = {}
_GATEWAY_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


def _looks_like_chrome(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _CHROME_MARKERS)


def _parse_gateway_html(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    start = re.search(
        r"(?is)<div[^>]*class=['\"][^'\"]*passage-content[^'\"]*['\"]",
        html,
    )
    if start:
        rest = html[start.start() :]
        cut = re.search(
            r"(?is)<a[^>]*class=['\"][^'\"]*full-chap-link|"
            r"<div[^>]*class=['\"][^'\"]*copyright-table|"
            r"<div[^>]*class=['\"][^'\"]*publisher-info",
            rest,
        )
        chunk = rest[: cut.start()] if cut else rest[:12000]
    else:
        chunk = html
    chunk = re.sub(r"(?is)<sup[^>]*class=['\"][^'\"]*footnote[^'\"]*['\"][^>]*>.*?</sup>", "", chunk)
    chunk = re.sub(r"(?is)<h[1-6][^>]*>.*?</h[1-6]>", " ", chunk)
    chunk = re.sub(r"(?is)<span[^>]*class=['\"][^'\"]*chapternum[^'\"]*['\"][^>]*>.*?</span>", " ", chunk)
    chunk = re.sub(r"(?is)<sup[^>]*class=['\"][^'\"]*versenum[^'\"]*['\"][^>]*>(.*?)</sup>", r" \1 ", chunk)
    chunk = re.sub(r"(?i)<br\s*/?>", " ", chunk)
    chunk = re.sub(r"(?is)<[^>]+>", " ", chunk)
    chunk = html_lib.unescape(chunk)
    chunk = chunk.replace("\xa0", " ")
    chunk = re.sub(r"Read full chapter", " ", chunk, flags=re.IGNORECASE)
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if _looks_like_chrome(chunk):
        return ""
    return chunk


def fetch_passage(book: str, chapter: int, verse: int, verse_end: int | None, translation: str) -> tuple[str | None, str]:
    """Return (text, source_label) from Bible Gateway. Never invents wording."""
    wanted = (translation or "NIV").upper()
    if wanted in {"THE MESSAGE", "MESSAGE"}:
        wanted = "MSG"
    end = verse_end or verse
    cache_key = (book, chapter, verse, end, wanted)
    if cache_key in _GATEWAY_CACHE:
        return _GATEWAY_CACHE[cache_key]

    ref = f"{book} {chapter}:{verse}"
    if end != verse:
        ref += f"-{end}"
    try:
        resp = requests.get(
            "https://www.biblegateway.com/passage/",
            params={"search": ref, "version": wanted, "interface": "print"},
            headers={"User-Agent": _GATEWAY_UA, "Accept": "text/html"},
            timeout=15,
        )
        if not resp.ok:
            result = (None, f"Bible Gateway HTTP {resp.status_code}")
            _GATEWAY_CACHE[cache_key] = result
            return result
        text = _parse_gateway_html(resp.text)
        if not text:
            result = (None, "Bible Gateway returned no passage text")
            _GATEWAY_CACHE[cache_key] = result
            return result
        result = (text, f"Bible Gateway {wanted}")
        _GATEWAY_CACHE[cache_key] = result
        return result
    except Exception as exc:  # noqa: BLE001
        result = (None, f"Bible Gateway error: {exc}")
        _GATEWAY_CACHE[cache_key] = result
        return result


def check_bible(outline: OutlineDoc) -> list[Flag]:
    flags: list[Flag] = []
    text = outline.full_text
    hits: list[_Hit] = []

    for match in ABS_REF_RE.finditer(text):
        verse = int(match.group("verse")) if match.group("verse") else None
        end = int(match.group("end")) if match.group("end") else None
        trans = match.group("translation")
        hits.append(
            _Hit(
                kind="absolute",
                start=match.start(),
                text=match.group(0),
                book=_norm_book(match.group("book")),
                chapter=int(match.group("chapter")),
                verse=verse,
                verse_end=end,
                translation=trans.upper() if trans else None,
            )
        )
    for match in REL_VERSE_RE.finditer(text):
        hits.append(
            _Hit(
                kind="relative_verse",
                start=match.start(),
                text=match.group(0),
                verse=int(match.group("verse")),
                verse_end=int(match.group("end")) if match.group("end") else None,
            )
        )
    for match in FEW_VERSES_RE.finditer(text):
        hits.append(
            _Hit(kind="few_verses", start=match.start(), text=match.group(0), phrase=match.group(0))
        )
    for match in SAME_CHAPTER_RE.finditer(text):
        hits.append(
            _Hit(kind="same_chapter", start=match.start(), text=match.group(0), phrase=match.group(0))
        )
    for match in FEW_CHAPTERS_RE.finditer(text):
        hits.append(
            _Hit(kind="few_chapters", start=match.start(), text=match.group(0), phrase=match.group(0))
        )

    hits.sort(key=lambda h: h.start)
    cursor = BibleCursor()
    pending_relative: _Hit | None = None
    spoken_range: tuple[int, int] | None = None
    heading_range: tuple[int, int] | None = None

    for hit in hits:
        loc = _line_at(text, hit.start)
        if hit.kind == "absolute":
            prev = cursor.label()
            if (
                pending_relative
                and pending_relative.kind == "few_chapters"
                and cursor.chapter is not None
                and hit.chapter is not None
                and hit.book == cursor.book
                and abs(hit.chapter - cursor.chapter) < 2
            ):
                flags.append(
                    Flag(
                        "warning",
                        "bible",
                        f'Phrase "{pending_relative.text}" suggested a chapter jump, but next ref is {hit.book} {hit.chapter}.',
                        location=loc,
                        resolved=f"{hit.book} {hit.chapter}",
                    )
                )
            if (
                pending_relative
                and pending_relative.kind == "same_chapter"
                and hit.chapter != cursor.chapter
            ):
                flags.append(
                    Flag(
                        "warning",
                        "bible",
                        f'Phrase "{pending_relative.text}" but next ref leaves {cursor.book} {cursor.chapter} for {hit.book} {hit.chapter}.',
                        location=loc,
                    )
                )
            cursor.book = hit.book
            cursor.chapter = hit.chapter
            cursor.verse = hit.verse
            cursor.verse_end = hit.verse_end
            if hit.translation:
                cursor.translation = hit.translation
            flags.append(
                Flag(
                    "info",
                    "bible",
                    f"Set passage cursor to {cursor.label()} ({cursor.translation}).",
                    location=loc,
                    resolved=cursor.label(),
                )
            )
            if prev and hit.book and prev.split()[0] != hit.book and pending_relative is None:
                flags.append(
                    Flag(
                        "info",
                        "bible",
                        f"Book changed from {prev} to {cursor.label()}.",
                        location=loc,
                    )
                )
            # Track spoken vs heading range mismatches in nearby lines.
            if hit.verse and hit.verse_end:
                if "turn" in loc.lower() or "bibles" in loc.lower():
                    spoken_range = (hit.verse, hit.verse_end)
                else:
                    heading_range = (hit.verse, hit.verse_end)
                if spoken_range and heading_range and spoken_range != heading_range:
                    flags.append(
                        Flag(
                            "warning",
                            "bible",
                            f"Spoken range {cursor.book} {cursor.chapter}:{spoken_range[0]}-{spoken_range[1]} "
                            f"does not match heading {cursor.book} {cursor.chapter}:{heading_range[0]}-{heading_range[1]}.",
                            location=loc,
                        )
                    )
            pending_relative = None
            continue

        if hit.kind == "relative_verse":
            if not cursor.book or cursor.chapter is None:
                flags.append(
                    Flag(
                        "error",
                        "bible",
                        f'Could not resolve "{hit.text}" — no current book/chapter.',
                        location=loc,
                    )
                )
                continue
            resolved = f"{cursor.book} {cursor.chapter}:{hit.verse}"
            if hit.verse_end:
                resolved += f"-{hit.verse_end}"
            jump = None
            if cursor.verse is not None:
                jump = hit.verse - cursor.verse
            if pending_relative and pending_relative.kind == "few_verses" and jump is not None and abs(jump) > 8:
                flags.append(
                    Flag(
                        "warning",
                        "bible",
                        f'Phrase "{pending_relative.text}" but resolved {resolved} is {abs(jump)} verses from {cursor.label()}.',
                        location=loc,
                        resolved=resolved,
                    )
                )
            elif jump is not None and abs(jump) > 15:
                flags.append(
                    Flag(
                        "warning",
                        "bible",
                        f'Relative "{hit.text}" jumps {abs(jump)} verses from {cursor.label()} to {resolved}.',
                        location=loc,
                        resolved=resolved,
                    )
                )
            else:
                flags.append(
                    Flag(
                        "info",
                        "bible",
                        f'Resolved "{hit.text}" to {resolved}.',
                        location=loc,
                        resolved=resolved,
                    )
                )
            cursor.verse = hit.verse
            cursor.verse_end = hit.verse_end
            pending_relative = None
            continue

        pending_relative = hit
        flags.append(
            Flag(
                "info",
                "bible",
                f'Noted relative phrase "{hit.text}" at cursor {cursor.label() or "(none)"}.',
                location=loc,
            )
        )

    if pending_relative:
        flags.append(
            Flag(
                "warning",
                "bible",
                f'Relative phrase "{pending_relative.text}" was never followed by a resolvable reference.',
                location=_line_at(text, pending_relative.start),
            )
        )

    def _para_for_offset(offset: int) -> int:
        pos = 0
        for para in outline.paragraphs:
            end = pos + len(para.text) + 1
            if offset < end:
                return para.index
            pos = end
        return outline.paragraphs[-1].index if outline.paragraphs else 0

    abs_hits = [h for h in hits if h.kind == "absolute"]

    # Compare quoted verse bodies on slides against fetched text.
    seen_refs: set[str] = set()
    for draft in outline.blocks:
        if not draft.has_verse_numbers:
            continue
        numbers = [s.verse_number for s in draft.body_spans if s.verse_number]
        if not numbers:
            continue
        body = draft.body
        local = list(ABS_REF_RE.finditer(body))
        book = None
        chapter = None
        translation = "NIV"
        if local:
            last = local[-1]
            book = _norm_book(last.group("book"))
            chapter = int(last.group("chapter"))
            if last.group("translation"):
                translation = last.group("translation").upper()
        if book is None:
            para_min = min(draft.source_paragraphs) if draft.source_paragraphs else 0
            nearest = None
            for hit in abs_hits:
                if _para_for_offset(hit.start) <= para_min:
                    nearest = hit
            if nearest:
                book = nearest.book
                chapter = nearest.chapter
                if nearest.translation:
                    translation = nearest.translation
        if not book or chapter is None:
            continue
        ref_key = f"{book}-{chapter}-{numbers[0]}-{numbers[-1]}-{translation}"
        if ref_key in seen_refs:
            continue
        seen_refs.add(ref_key)
        start_v = int(numbers[0])
        end_v = int(numbers[-1])
        quoted = _quote_without_refs(body)
        official, source = fetch_passage(book, chapter, start_v, end_v, translation)
        ref = f"{book} {chapter}:{start_v}" + (f"-{end_v}" if end_v != start_v else "")
        if official is None:
            flags.append(
                Flag(
                    "info",
                    "bible",
                    f"Quoted {ref} ({translation}) not text-checked ({source}). Outline wording will be used on slides.",
                    location=quoted[:80],
                    resolved=ref,
                )
            )
            continue
        overlap = _token_overlap(quoted, official)
        alt_hit: tuple[str, float] | None = None
        if overlap < MATCH_OVERLAP and book in GOSPEL_BOOKS:
            best_name = None
            best_score = MATCH_OVERLAP
            for other in GOSPEL_BOOKS:
                if other == book:
                    continue
                alt_text, _ = fetch_passage(other, chapter, start_v, end_v, translation)
                if not alt_text:
                    continue
                score = _token_overlap(quoted, alt_text)
                if score > best_score:
                    best_score = score
                    best_name = other
            if best_name:
                alt_hit = (best_name, best_score)
        alt_ref = (
            f"{alt_hit[0]} {chapter}:{start_v}" + (f"-{end_v}" if end_v != start_v else "")
            if alt_hit
            else None
        )
        if alt_hit and alt_ref:
            flags.append(
                Flag(
                    "warning",
                    "bible",
                    f"Cited as {ref} but the outline wording matches {alt_ref} on {source} "
                    f"(cited overlap {overlap:.0%}, {alt_hit[0]} overlap {alt_hit[1]:.0%}). "
                    "Slides keep the outline text.",
                    location=quoted[:80],
                    resolved=ref,
                )
            )
        elif overlap < MISMATCH_OVERLAP:
            flags.append(
                Flag(
                    "warning",
                    "bible",
                    f"Outline wording for {ref} does not match {source} (overlap {overlap:.0%}). "
                    "Please check the book, chapter, and verses. Slides keep the outline text.",
                    location=quoted[:80],
                    resolved=ref,
                )
            )
        else:
            flags.append(
                Flag(
                    "info",
                    "bible",
                    f"Quoted {ref} matches {source} (overlap {overlap:.0%}).",
                    location=quoted[:80],
                    resolved=ref,
                )
            )

    return flags
