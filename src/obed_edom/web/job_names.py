"""Human two-word job names: `<adjective>-<place>`, minted at submit and used as the
basename of the id-derived private output folders."""

from __future__ import annotations

import random
import re
from typing import Container

ADJECTIVES: tuple[str, ...] = (
    "amber",
    "ancient",
    "bright",
    "broad",
    "calm",
    "clear",
    "cool",
    "dawn",
    "deep",
    "distant",
    "dry",
    "dusty",
    "early",
    "eastern",
    "faithful",
    "far",
    "fertile",
    "fresh",
    "gentle",
    "golden",
    "green",
    "hidden",
    "high",
    "holy",
    "humble",
    "kind",
    "level",
    "little",
    "lofty",
    "lonely",
    "loyal",
    "low",
    "narrow",
    "new",
    "northern",
    "old",
    "open",
    "patient",
    "plain",
    "quiet",
    "rocky",
    "sandy",
    "silent",
    "small",
    "soft",
    "southern",
    "steady",
    "still",
    "stony",
    "strong",
    "sunny",
    "swift",
    "warm",
    "western",
    "wide",
    "wild",
    "windy",
    "wise",
    "young",
)

PLACES: tuple[str, ...] = (
    "aaron",
    "abraham",
    "andrew",
    "antioch",
    "aram",
    "asher",
    "babel",
    "babylon",
    "barnabas",
    "bethany",
    "bethel",
    "bethlehem",
    "boaz",
    "caesarea",
    "cana",
    "canaan",
    "capernaum",
    "carmel",
    "corinth",
    "damascus",
    "daniel",
    "david",
    "dothan",
    "eden",
    "edom",
    "egypt",
    "elijah",
    "elisha",
    "emmaus",
    "endor",
    "enoch",
    "ephesus",
    "esther",
    "gaza",
    "gilead",
    "gilgal",
    "goliath",
    "hebron",
    "isaac",
    "isaiah",
    "jacob",
    "jericho",
    "jerusalem",
    "jesse",
    "jezreel",
    "joel",
    "john",
    "jonah",
    "jonathan",
    "joppa",
    "jordan",
    "joseph",
    "joshua",
    "judah",
    "kidron",
    "laban",
    "lazarus",
    "levi",
    "luke",
    "lydia",
    "mark",
    "martha",
    "mary",
    "megiddo",
    "midian",
    "miriam",
    "moab",
    "moriah",
    "moses",
    "nazareth",
    "nineveh",
    "noah",
    "paul",
    "peter",
    "philip",
    "rachel",
    "rebekah",
    "rome",
    "ruth",
    "samaria",
    "samuel",
    "sarah",
    "saul",
    "shechem",
    "shiloh",
    "silas",
    "simon",
    "sinai",
    "sodom",
    "solomon",
    "tabor",
    "tarsus",
    "thomas",
    "timothy",
    "tyre",
    "zion",
)

_MAX_ATTEMPTS = 20
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_LENGTH = 48


def generate_job_name(taken: Container[str], *, rng: random.Random | None = None) -> str:
    """Mint a `adjective-place` name not present (case-insensitively) in `taken`.

    Falls back to a numeric suffix after `_MAX_ATTEMPTS` collisions so minting can
    never fail or loop unboundedly.
    """
    rng = rng or random
    lowered_taken = {name.lower() for name in taken}
    for _ in range(_MAX_ATTEMPTS):
        candidate = f"{rng.choice(ADJECTIVES)}-{rng.choice(PLACES)}"
        if candidate not in lowered_taken:
            return candidate
    base = f"{rng.choice(ADJECTIVES)}-{rng.choice(PLACES)}"
    suffix = 2
    candidate = f"{base}-{suffix}"
    while candidate in lowered_taken:
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def normalise_job_name(raw: str) -> str:
    """Normalise user-supplied text into a valid folder-safe job name.

    Strips, lowercases, collapses whitespace/repeated hyphens, and keeps only
    `[a-z0-9-]`. Raises `ValueError` with a plain, user-facing message.
    """
    text = (raw or "").strip().lower()
    if not text:
        raise ValueError("Name cannot be empty.")
    if "/" in text or "\\" in text:
        raise ValueError("Name cannot contain a path separator.")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        raise ValueError("Name must contain at least one letter or digit.")
    if text in {".", ".."}:
        raise ValueError("Name is not valid.")
    if len(text) > _MAX_LENGTH:
        raise ValueError(f"Name must be {_MAX_LENGTH} characters or fewer.")
    if not _NAME_RE.match(text):
        raise ValueError("Name is not valid.")
    return text
