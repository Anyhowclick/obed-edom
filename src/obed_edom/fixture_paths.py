"""Gate fixtures live once, in the main checkout's `output/fixtures/<name>`; every worktree resolves them here."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

FIXTURE_NAMES = ("p2-recovery", "p2-binary", "p2-loop", "p2-loop-grey", "p2-soak-loop", "gl-decks", "qual-decks", "qual-movies")


@lru_cache(maxsize=1)
def main_checkout() -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).parent


def fixture(name: str) -> Path:
    if name not in FIXTURE_NAMES:
        raise ValueError(f"unknown fixture {name!r}; expected one of {FIXTURE_NAMES}")
    return main_checkout() / "output" / "fixtures" / name
