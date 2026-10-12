"""`obed_edom.fixture_paths`: the one resolver for gate fixtures (continuity generalisation plan §3.7 F).

Fixtures live once, in the main checkout's `output/fixtures/<name>`, so a worktree resolves them without a symlink.
The guard scan fails when a fixture path is spelled out anywhere in `src/`, `scripts/` or `tests/` instead of going
through `fixture(name)`; docs and `.agents/` are out of scope. Its patterns are checked against positive and null
controls first, so a scan that finds nothing is known to be able to find something.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from obed_edom import fixture_paths
from obed_edom.fixture_paths import FIXTURE_NAMES, fixture, main_checkout

REPO = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("src", "scripts", "tests")
SCANNED_SUFFIXES = {".py", ".sh", ".js", ".mjs", ".ts"}
RESOLVER = REPO / "src" / "obed_edom" / "fixture_paths.py"

_NAMES = "|".join(re.escape(name) for name in sorted(FIXTURE_NAMES, key=len, reverse=True))
FIXTURE_LITERAL = re.compile(
    rf"""output/(?:{_NAMES})(?![\w-])"""
    rf"""|output["']\s*[/,]\s*["'](?:{_NAMES})(?![\w-])"""
)
OWN_RESOLVER = re.compile(r"git-common-dir")


def _scanned_files() -> list[Path]:
    files = []
    for top in SCANNED_DIRS:
        for path in (REPO / top).rglob("*"):
            if path.suffix in SCANNED_SUFFIXES and path.is_file() and "__pycache__" not in path.parts:
                files.append(path)
    return sorted(files)


def _hits(pattern: re.Pattern[str]) -> list[str]:
    hits = []
    for path in _scanned_files():
        if path == RESOLVER or path == Path(__file__).resolve():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    return hits


def test_fixture_resolves_under_the_main_checkout_output_fixtures() -> None:
    for name in FIXTURE_NAMES:
        assert fixture(name) == main_checkout() / "output" / "fixtures" / name


def test_the_fixture_set_is_the_plans() -> None:
    assert FIXTURE_NAMES == (
        "p2-recovery", "p2-binary", "p2-loop", "p2-loop-grey", "p2-soak-loop", "gl-decks", "qual-decks", "qual-movies",
    )


@pytest.mark.parametrize("name", ["bank", "evidence", "p2-alpha-spike", "", "fixtures", "p2-recovery/html-adversarial"])
def test_an_unknown_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="unknown fixture"):
        fixture(name)


def test_fixture_does_not_check_existence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Callers keep their own fail-closed checks and skips; the resolver only names the path."""
    monkeypatch.setattr(fixture_paths, "main_checkout", lambda: tmp_path)
    assert fixture("qual-movies") == tmp_path / "output" / "fixtures" / "qual-movies"
    assert not fixture("qual-movies").exists()


def test_main_checkout_is_the_git_common_dirs_parent() -> None:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert main_checkout() == Path(common).parent
    assert (main_checkout() / ".git").is_dir()
    assert (main_checkout() / "pyproject.toml").is_file()


@pytest.mark.parametrize("line", [
    'OUT = REPO / "output" / "p2-recovery" / "html-adversarial"',
    "FIXTURE = REPO / 'output' / 'p2-binary'",
    'SOAK = REPO / "output/p2-loop"',
    'GREY = main / "output/p2-loop-grey/html-player"',
    'ROOT = Path("/Users/someone/work/obed-edom/output/gl-decks")',
    'ROOT = Path("/Users/someone/work/obed-edom/output/p2-soak-loop/html-unmodified")',
    'os.path.join("output", "qual-decks")',
    'F=$G/output/p2-recovery/html-adversarial',
    "# built into `output/qual-movies/`",
])
def test_guard_pattern_catches_a_spelled_out_fixture(line: str) -> None:
    assert FIXTURE_LITERAL.search(line)


@pytest.mark.parametrize("line", [
    'ROOT = fixture("p2-recovery") / "html-adversarial"',
    'docs = "output/fixtures/p2-loop"',
    'OUT = REPO / "output" / "p2-alpha-spike"',
    'OUT = REPO / "output" / "p2-native-midframe"',
    'BANK = Path("/Users/someone/work/obed-edom/output/bank/2026-09-16")',
    'EVIDENCE = "output/evidence/p2-loop-gates"',
    'FIXTURE_BASE = "p2-recovery/html-adversarial"',
    'dest = tmp_path / "p2-loop"',
])
def test_guard_pattern_passes_a_resolved_or_unrelated_path(line: str) -> None:
    assert not FIXTURE_LITERAL.search(line)


def test_the_scan_covers_the_known_fixture_callers() -> None:
    scanned = {path.relative_to(REPO).as_posix() for path in _scanned_files()}
    for caller in ("scripts/run_gates.sh", "scripts/loop_fixture.py", "scripts/p2_recovery_html_adversarial.py",
                   "tests/test_live_continuity_decks.py", "src/obed_edom/fixture_paths.py"):
        assert caller in scanned


def test_no_fixture_path_is_spelled_out_outside_the_resolver() -> None:
    assert _hits(FIXTURE_LITERAL) == []


def test_no_second_main_checkout_resolver() -> None:
    assert _hits(OWN_RESOLVER) == []
