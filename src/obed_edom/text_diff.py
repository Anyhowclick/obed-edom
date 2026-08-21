"""Token comparison for slide copy, and the classifier behind text findings.

A single "Wording differs" warning tells an operator nothing. These helpers say
which kind of difference it is, so a stray capital reads differently from a
rewritten verse and each can carry its own severity.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_SOFT_WS = re.compile(r"[\s\u2028\u2029\xa0]+")
_EDGE_PUNCT = re.compile(r"^[\s.,;:!?…'\"“”‘’()\[\]{}—–-]+|[\s.,;:!?…'\"“”‘’()\[\]{}—–-]+$")
_STANDALONE_NUMBER = re.compile(r"^\d{1,2}$")

TRANSLATIONS = {
    "NIV", "NIV84", "AMP", "AMPC", "MSG", "ESV", "KJV", "NKJV", "NLT",
    "NASB", "CSB", "HCSB", "TPT", "RSV", "NRSV", "GNT", "CEV", "TLB",
}

BIBLE_BOOK_WORDS = {
    "genesis", "exodus", "leviticus", "numbers", "deuteronomy", "joshua",
    "judges", "ruth", "samuel", "kings", "chronicles", "ezra", "nehemiah",
    "esther", "job", "psalm", "psalms", "proverbs", "ecclesiastes", "song",
    "isaiah", "jeremiah", "lamentations", "ezekiel", "daniel", "hosea", "joel",
    "amos", "obadiah", "jonah", "micah", "nahum", "habakkuk", "zephaniah",
    "haggai", "zechariah", "malachi", "matthew", "mark", "luke", "john",
    "acts", "romans", "corinthians", "galatians", "ephesians", "philippians",
    "colossians", "thessalonians", "timothy", "titus", "philemon", "hebrews",
    "james", "peter", "jude", "revelation", "revelations",
}

# Typographic variants that mean the same thing to a reader but not to ==.
_SYMBOL_WORDS = {"&": "and", "+": "and", "w/": "with"}
_SYMBOL_CHARS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u00a0": " ",
    }
)


def fingerprint(text: str) -> str:
    return " ".join(_SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).lower().split())


def comparable_tokens(text: str) -> list[str]:
    """Whitespace-folded tokens, original case. Ignores wrap/nbsp/line-separator."""
    folded = _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()
    out: list[str] = []
    for raw in folded.split() if folded else []:
        core = _EDGE_PUNCT.sub("", raw)
        out.append(core or raw)
    return out


def canonical_token(token: str) -> str:
    """Fold case and typographic variants so only real wording differences remain."""
    folded = token.translate(_SYMBOL_CHARS).lower()
    return _SYMBOL_WORDS.get(folded, folded)


def is_rotation(a: list[str], b: list[str]) -> bool:
    if len(a) != len(b) or not a:
        return False
    doubled = a + a
    n = len(a)
    return any(doubled[i : i + n] == b for i in range(n))


def collapse_repeat(tokens: list[str]) -> list[str]:
    """LW often duplicates a verse on both sides of the wall."""
    n = len(tokens)
    if n >= 4 and n % 2 == 0 and tokens[: n // 2] == tokens[n // 2 :]:
        return tokens[: n // 2]
    return tokens


def texts_equivalent(left: str, right: str) -> bool:
    """True when copy matches aside from wrap, nbsp, wall-duplication, and ref order."""
    a, b = collapse_repeat(comparable_tokens(left)), collapse_repeat(comparable_tokens(right))
    if a == b or is_rotation(a, b):
        return True
    sa, sb = " ".join(a), " ".join(b)
    if not sa or not sb:
        return False
    short, long = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if short not in long:
        return False
    rest = " ".join(long.replace(short, " ", 1).split())
    return rest in {"", short}


def text_score(left: str, right: str) -> float:
    """Similarity for pairing. Case-folded fingerprints; does not rewrite originals."""
    a = fingerprint(left)
    b = fingerprint(right)
    if not a or not b:
        return 1.0 if a == b and a else 0.0
    if a == b:
        return 1.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 8 and shorter in longer:
        seq = max(seq, 0.9)
    wa, wb = a.split(), b.split()
    ta, tb = set(wa), set(wb)
    if not ta or not tb:
        return seq
    short_n, long_n = (len(wa), len(wb)) if len(wa) <= len(wb) else (len(wb), len(wa))
    similar_len = long_n <= max(8, short_n * 4)
    if not similar_len:
        return seq
    cov = len(ta & tb) / min(len(ta), len(tb))
    if min(len(ta), len(tb)) >= 2:
        seq = max(seq, cov * 0.95)
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    content = {t for t in small if not t.isdigit() and len(t) > 1}
    if content and len(content) <= 4 and content <= large:
        seq = max(seq, 0.82)
    return seq


@dataclass(frozen=True)
class TextFinding:
    rule: str
    message: str
    default: str = "warning"


VERSE_RUN_TOKENS = 6


def _verse_split(
    a: list[str],
    b: list[str],
    ops: list[tuple],
    left_label: str,
    right_label: str,
) -> TextFinding | None:
    """A whole extra verse on one deck is a different split, not a typo.

    The wall fits more text than the lower third, so the two decks group verses
    differently all the time. Reporting it as rewritten copy buries real errors.
    """
    extras: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in ops:
        for tokens, lo, hi, label in ((a, i1, i2, left_label), (b, j1, j2, right_label)):
            run = tokens[lo:hi]
            if not run:
                continue
            if len(run) < VERSE_RUN_TOKENS or not _strip(run[0]).isdigit():
                return None
            extras.append((label, _strip(run[0])))
        if tag == "replace" and not (i2 - i1) or not (j2 - j1):
            continue
    if not extras:
        return None
    detail = "; ".join(f"{label} also shows verse {verse}" for label, verse in extras[:3])
    return TextFinding(
        "text.verse_split",
        f"The decks split the passage differently: {detail}. "
        "Check the extra verse appears somewhere on the other deck.",
        default="info",
    )


def _strip(token: str) -> str:
    return token.strip("()[]{}.,:;").strip()


def _is_translation(token: str) -> bool:
    return _strip(token).upper() in TRANSLATIONS


def _phrase(tokens: list[str], start: int, end: int, pad: int = 2) -> str:
    lo = max(0, start - pad)
    hi = min(len(tokens), end + pad)
    body = " ".join(tokens[lo:hi])
    if not body:
        return "(nothing)"
    return ("… " if lo > 0 else "") + body + (" …" if hi < len(tokens) else "")


def _brief(text: str, limit: int = 160) -> str:
    return _SOFT_WS.sub(" ", (text or "").replace("\xa0", " ")).strip()[:limit]


LINE_MATCH = 0.55


def _residual_lines(a: list[str], b: list[str]) -> tuple[list[str], list[str]] | None:
    """Pair up the lines the two decks share, and hand back only what is left.

    The wall and the lower third stack the same blocks in different orders, so a
    straight token diff of the whole slide reports the layout instead of the one
    line that actually reads differently. Returns None when the slides do not
    share enough lines for this to be meaningful.
    """
    if len(a) < 2 or len(b) < 2:
        return None
    available = list(range(len(b)))
    extra_left: list[str] = []
    changed: list[tuple[str, str]] = []
    matched = 0
    for line in a:
        best, best_score = None, 0.0
        for index in available:
            score = text_score(line, b[index])
            if score > best_score:
                best, best_score = index, score
        if best is None or best_score < LINE_MATCH:
            extra_left.append(line)
            continue
        available.remove(best)
        if fingerprint(line) == fingerprint(b[best]):
            matched += 1
        else:
            changed.append((line, b[best]))
    if not matched:
        return None
    extra_right = [b[index] for index in available]
    return (
        [line for line, _ in changed] + extra_left,
        [line for _, line in changed] + extra_right,
    )


def _split_reference_label(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Pull every "1 Samuel 10 (NIV)" out of a token list, wherever it sits.

    Returns (label tokens, remaining tokens). A combined pair carries one label
    per DSK slide, so all of them have to come out for the bodies to line up.
    """
    labels: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _strip(token).lower() not in BIBLE_BOOK_WORDS:
            rest.append(token)
            index += 1
            continue
        end = index + 1
        if end >= len(tokens) or not _strip(tokens[end]).isdigit():
            rest.append(token)  # A book name with no chapter is prose.
            index += 1
            continue
        start = index
        # A numbered book ("1 Samuel") carries its numeral in front.
        if rest and _strip(rest[-1]).isdigit() and len(_strip(rest[-1])) == 1:
            labels.append(rest.pop())
        end += 1
        if end < len(tokens) and _is_translation(tokens[end]):
            end += 1
        labels.extend(tokens[start:end])
        index = end
    return labels, rest


_QUOTE_CHARS = set("\"'“”‘’")


def _substantive_symbol(left: str, right: str) -> bool:
    """True for swaps a reader notices: & for and, a hyphen for an en dash."""
    if set(left) <= _QUOTE_CHARS and set(right) <= _QUOTE_CHARS:
        return False
    return True


def _is_point_number(token: str) -> bool:
    """A bare one or two digit number, i.e. a point number rather than a word."""
    bare = _strip(token)
    return bare.isdigit() and len(bare) <= 2


def _format_label(tokens: list[str]) -> str:
    """Render a reference label the way it reads on a slide: John 3 (MSG)."""
    return " ".join(f"({t})" if _is_translation(t) else t for t in _dedupe_labels(tokens))


def _dedupe_labels(tokens: list[str]) -> list[str]:
    """Drop the repeat when a combined pair carries the same label twice."""
    half = len(tokens) // 2
    if half and len(tokens) % 2 == 0 and tokens[:half] == tokens[half:]:
        return tokens[:half]
    return tokens


def _unique_label(tokens: list[str]) -> list[str]:
    folded = [canonical_token(t) for t in _dedupe_labels(tokens)]
    return _dedupe_labels(folded)


def _near_reference(tokens: list[str], start: int, end: int) -> bool:
    lo = max(0, start - 1)
    hi = min(len(tokens), end + 1)
    for token in tokens[lo:hi]:
        bare = _strip(token).lower()
        if bare in BIBLE_BOOK_WORDS or _is_translation(token):
            return True
    return False


def classify_text_diff(
    left: str,
    right: str,
    left_label: str = "LW",
    right_label: str = "DSK",
    *,
    ignore_left_tokens: set[str] | None = None,
    split_labels: bool = True,
) -> TextFinding | None:
    """Name the difference between two slides' copy, or None when they agree."""
    a = collapse_repeat(comparable_tokens(left))
    b = collapse_repeat(comparable_tokens(right))
    if ignore_left_tokens:
        a = [t for t in a if t not in ignore_left_tokens]
    if not a or not b:
        if not a and not b:
            return None
        empty = left_label if not a else right_label
        return TextFinding(
            "text.unreadable",
            f"No readable text on {empty}; the other deck has "
            f'"{_brief(right if not a else left, 80)}". '
            "Check the preview export or the slide contents.",
            default="info",
        )
    if a == b or is_rotation(a, b):
        return None

    lower_a = [t.lower() for t in a]
    lower_b = [t.lower() for t in b]
    if lower_a == lower_b:
        pairs = [(x, y) for x, y in zip(a, b) if x != y]
        detail = "; ".join(f'{left_label} "{x}" vs {right_label} "{y}"' for x, y in pairs[:4])
        return TextFinding("text.case", f"Capitalisation differs: {detail}.")

    canon_a = [canonical_token(t) for t in a]
    canon_b = [canonical_token(t) for t in b]
    if canon_a == canon_b:
        pairs = [(x, y) for x, y in zip(a, b) if x != y and _substantive_symbol(x, y)]
        if not pairs:
            # Curly quote direction and similar OCR artefacts. Nobody reads a
            # difference here, and flagging it drowns out the ones they do.
            return None
        detail = "; ".join(f'{left_label} "{x}" vs {right_label} "{y}"' for x, y in pairs[:4])
        return TextFinding("text.symbol", f"Symbol or punctuation differs: {detail}.")

    # The reference label sits at the top of the wall and the bottom of the
    # lower third. Comparing raw token order makes that single move look like a
    # rewrite of the whole slide, so set it aside and diff what is left.
    if split_labels:
        label_a, rest_a = _split_reference_label(a)
        label_b, rest_b = _split_reference_label(b)
        if label_a and label_b and rest_a and rest_b:
            # The wall sets labels in caps by design, so compare them folded, and
            # a combined pair repeats the label once per DSK slide.
            if _unique_label(label_a) != _unique_label(label_b):
                return TextFinding(
                    "text.reference",
                    f'Scripture reference differs: {left_label} cites "{_format_label(label_a)}", '
                    f'{right_label} cites "{_format_label(label_b)}".',
                )
            inner = classify_text_diff(
                " ".join(rest_a), " ".join(rest_b), left_label, right_label,
                split_labels=False,
            )
            if inner is None:
                return TextFinding(
                    "text.order",
                    "The scripture label sits in a different place; the wording matches.",
                    default="info",
                )
            return inner

    if split_labels:
        residual = _residual_lines(
            [ln for ln in left.split("\n") if ln.strip()],
            [ln for ln in right.split("\n") if ln.strip()],
        )
        if residual is not None:
            rest_left, rest_right = residual
            if not rest_left and not rest_right:
                return None
            return classify_text_diff(
                "\n".join(rest_left),
                "\n".join(rest_right),
                left_label,
                right_label,
                split_labels=False,
            )

    ops = [op for op in difflib.SequenceMatcher(None, canon_a, canon_b).get_opcodes() if op[0] != "equal"]
    if sorted(canon_a) == sorted(canon_b):
        # A reference label sits above the body on the wall and below it in the
        # lower third; that is layout. Any other reshuffle is a real rewrite.
        moved = {
            _strip(t).lower()
            for _tag, i1, i2, j1, j2 in ops
            for t in a[i1:i2] + b[j1:j2]
        }
        label_only = moved and all(
            token in BIBLE_BOOK_WORDS or token.isdigit() or token.upper() in TRANSLATIONS
            for token in moved
        )
        if label_only:
            return TextFinding(
                "text.order",
                f"Scripture label sits in a different place. {left_label}: {_brief(left, 90)} / "
                f"{right_label}: {_brief(right, 90)}",
                default="info",
            )

    if not ops:
        return None
    changed = sum(max(i2 - i1, j2 - j1) for _tag, i1, i2, j1, j2 in ops)
    reference = any(
        _near_reference(a, i1, i2) or _near_reference(b, j1, j2)
        for _tag, i1, i2, j1, j2 in ops
    )
    moved = [t for _tag, i1, i2, j1, j2 in ops for t in a[i1:i2] + b[j1:j2]]
    if moved and not reference and all(_is_point_number(t) for t in moved):
        # The wall shows a point number beside the title and the lower third
        # sometimes does not. That is the template, not a mistake.
        return None
    parts = []
    for _tag, i1, i2, j1, j2 in ops[:3]:
        parts.append(f'{left_label}: "{_phrase(a, i1, i2)}" vs {right_label}: "{_phrase(b, j1, j2)}"')
    detail = "; ".join(parts)

    if reference and changed <= 4:
        return TextFinding("text.reference", f"Scripture reference differs: {detail}.")
    if changed <= 2:
        return TextFinding("text.word", f"Wording differs: {detail}.")
    split = _verse_split(a, b, ops, left_label, right_label)
    if split:
        return split
    only_l = sorted({t for t in canon_a if t not in set(canon_b)})
    only_r = sorted({t for t in canon_b if t not in set(canon_a)})
    lines = [
        f"{left_label}: {_brief(left)}",
        f"{right_label}: {_brief(right)}",
    ]
    if only_l:
        lines.append(f"Only in {left_label}: " + ", ".join(only_l[:8]))
    if only_r:
        lines.append(f"Only in {right_label}: " + ", ".join(only_r[:8]))
    return TextFinding("text.major", "\n".join(lines))


def standalone_numbers(text: str) -> set[str]:
    """Point numbers that sit alone on an LW line and never reach the lower third."""
    return {
        line.strip()
        for line in (text or "").split("\n")
        if _STANDALONE_NUMBER.match(line.strip())
    }
