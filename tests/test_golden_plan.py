"""Keynote-free golden-plan gate: same source+template deck bytes must reproduce
the same `remap_keynote()` apply plan, byte-for-byte, without opening Keynote.
See `scripts/golden_plan.py` for the capture mechanism and canonicalisation."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from scripts import golden_plan  # noqa: E402
from scripts.bank_jxa_slide_digests import BANK_VERSION, bank_path  # noqa: E402
from scripts.golden_plan import (  # noqa: E402
    ENV_PINS,
    FONT_ENV_UNAVAILABLE,
    GOLDEN_VERSION,
    PREVIEWS_NONE,
    TEMPLATE as SCRIPT_TEMPLATE,
    WALL_DECKS,
    WALL_PAYLOAD_SOURCE,
    canonical,
    capture_plan,
    enrichment_markers,
    golden_path,
    plan_hash,
    summarize,
    summary_diff,
    validate_planner_env,
)

from obed_edom import baseline  # noqa: E402
from obed_edom import framing  # noqa: E402
from obed_edom.offline_inspect import offline_wall_payload  # noqa: E402

DECKS = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
TEMPLATE = DECKS / "Base_CG_Assets.key"
assert TEMPLATE == SCRIPT_TEMPLATE

ROLE_SET = {"map", "list", "pin", "title", "other"}

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _pin_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV_PINS.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _skip_ladder(deck_name: str) -> dict:
    """Skip on a missing deck/template/golden or a deck/template digest drift
    (a missing input), naming the regeneration command. Fail on any other
    provenance drift (schema/version/config): a mis-described golden is a bug,
    not a missing input. Returns the loaded golden fixture."""
    deck = DECKS / deck_name
    if not deck.exists():
        pytest.skip(f"deck missing: {deck}")
    if not TEMPLATE.exists():
        pytest.skip(f"template missing: {TEMPLATE}")
    golden_file = golden_path(deck_name)
    if not golden_file.exists():
        pytest.skip(f"golden fixture missing: {golden_file}")
    golden = json.loads(golden_file.read_text())

    for field, expected in (
        ("goldenVersion", GOLDEN_VERSION),
        ("deck", deck_name),
        ("template", TEMPLATE.name),
        ("wallPayloadSource", WALL_PAYLOAD_SOURCE),
        ("previews", PREVIEWS_NONE),
        ("env", ENV_PINS),
        ("inspectVersion", baseline.INSPECT_VERSION),
    ):
        actual = golden.get(field, "<missing>")
        if actual != expected:
            pytest.fail(f"golden fixture schema drift: {field} expected {expected!r}, got {actual!r}")

    for field in ("sourceDigest", "templateDigest"):
        value = golden.get(field)
        if not isinstance(value, str) or not _HEX64.fullmatch(value):
            pytest.fail(f"golden fixture schema drift: {field} expected a 64-char lowercase hex digest, got {value!r}")

    problems = validate_planner_env(golden.get("plannerEnv"))
    if problems:
        pytest.fail("golden fixture schema drift: " + "; ".join(problems))

    source_digest = baseline.deck_digest(deck)
    template_digest = baseline.deck_digest(TEMPLATE)
    if source_digest != golden["sourceDigest"] or template_digest != golden["templateDigest"]:
        pytest.skip(
            f"deck/template digest drift (source {source_digest} vs {golden['sourceDigest']}, "
            f"template {template_digest} vs {golden['templateDigest']}); regenerate with "
            f"scripts/golden_plan.py update --deck {deck_name}"
        )
    return golden


def _check_planner_env(golden: dict, actual_env: dict) -> None:
    """A different machine (OS build or installed/resolved caption faces) is a
    missing input, not a bug: skip naming the differing component (a single
    differing face names that face, not the whole `faces` mapping)."""
    golden_env = golden["plannerEnv"]
    if golden_env.get("osBuild") != actual_env.get("osBuild"):
        pytest.skip(
            f"planner env drift (osBuild): {golden_env.get('osBuild')!r} vs {actual_env.get('osBuild')!r}"
        )
    golden_faces = golden_env.get("faces")
    actual_faces = actual_env.get("faces")
    if golden_faces == actual_faces:
        return
    if not isinstance(golden_faces, dict) or not isinstance(actual_faces, dict):
        pytest.skip(f"planner env drift (faces): {golden_faces!r} vs {actual_faces!r}")
    for face in sorted(set(golden_faces) | set(actual_faces)):
        if golden_faces.get(face) != actual_faces.get(face):
            pytest.skip(
                f"planner env drift (faces[{face}]): {golden_faces.get(face)!r} vs {actual_faces.get(face)!r}"
            )


def _check_plan(deck_name: str, golden: dict, wall: dict, tmpl: dict, plan: dict, tmp_path: Path) -> None:
    """One diagnostic helper for marker (enrichment), totals and hash
    discrepancies: always writes `actual-plan.json`, prints the summary diff
    (totals/enrichment first) and the capture command for a transform-level
    diff against the pre-refactor revision."""
    actual_enrichment = enrichment_markers(wall, tmpl)
    actual = {**summarize(plan), "enrichment": actual_enrichment}
    actual_sha = plan_hash(plan)
    markers_match = actual_enrichment == golden["enrichment"]
    totals_match = actual["totals"] == golden["totals"]
    hash_match = actual_sha == golden["planSha256"]
    if markers_match and totals_match and hash_match:
        return

    actual_path = tmp_path / "actual-plan.json"
    actual_path.write_text(canonical(plan))
    diff_lines = summary_diff(golden, actual) or [
        "summary is identical; a field the summary does not project moved "
        "(an x/y, a font, an asGeom body byte)"
    ]
    header = f"golden plan mismatch for {deck_name}: sha {golden['planSha256']} != {actual_sha}"
    footer = (
        f"actual canonical plan written to {actual_path}; for a transform-level diff, capture the "
        f"pre-refactor revision with .venv/bin/python scripts/golden_plan.py capture --deck {deck_name} "
        f"--out /tmp/before.json and diff it against {actual_path}"
    )
    pytest.fail("\n".join([header, *diff_lines[:20], footer]))


def _gate(deck_name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    golden = _skip_ladder(deck_name)
    _pin_env(monkeypatch)
    wall, tmpl, plan, planner_env = capture_plan(DECKS / deck_name, TEMPLATE)
    problems = validate_planner_env(planner_env)
    if problems:
        pytest.fail("live planner env malformed: " + "; ".join(problems))
    _check_planner_env(golden, planner_env)
    _check_plan(deck_name, golden, wall, tmpl, plan, tmp_path)


def test_golden_apply_plan_gold_wall_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _gate("Gold_Wall_Input.key", monkeypatch, tmp_path)


def test_golden_apply_plan_full_report_card_wall(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _gate("Full_Report_Card_Wall.key", monkeypatch, tmp_path)


def test_validate_planner_env_rejects_malformed() -> None:
    cases: dict[str, tuple[dict, str]] = {
        "blank osBuild": ({"osBuild": "  ", "faces": FONT_ENV_UNAVAILABLE}, "osBuild"),
        "faces typo": ({"osBuild": "25G83", "faces": "typo"}, "faces"),
        "face key missing bools": (
            {"osBuild": "25G83", "faces": {"Amplitude-Bold": "Amplitude-Bold|Amplitude"}},
            "faces",
        ),
        "face value one part": (
            {"osBuild": "25G83", "faces": {"Amplitude-Bold|True|False": "OnlyOnePart"}},
            "faces",
        ),
        "empty faces mapping": ({"osBuild": "25G83", "faces": {}}, "faces"),
    }
    for label, (env, field) in cases.items():
        problems = validate_planner_env(env)
        assert problems, f"{label}: expected a problem, got none"
        assert any(field in p for p in problems), f"{label}: {problems} does not name {field!r}"

    for deck_name in WALL_DECKS:
        golden = json.loads(golden_path(deck_name).read_text())
        assert validate_planner_env(golden["plannerEnv"]) == []


def test_gate_fails_on_malformed_live_planner_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    deck_name = "Gold_Wall_Input.key"
    _skip_ladder(deck_name)

    def _malformed_planner_env(wall: dict) -> dict:
        return {"osBuild": "25G83", "faces": "typo"}

    monkeypatch.setattr(golden_plan, "planner_env", _malformed_planner_env)
    with pytest.raises(pytest.fail.Exception, match="faces"):
        _gate(deck_name, monkeypatch, tmp_path)


def test_propose_auto_rects_match_apply_transforms(monkeypatch: pytest.MonkeyPatch) -> None:
    deck_name = "Full_Report_Card_Wall.key"
    golden = _skip_ladder(deck_name)
    deck = DECKS / deck_name

    _pin_env(monkeypatch)
    _wall, _tmpl, plan, planner_env = capture_plan(deck, TEMPLATE)
    problems = validate_planner_env(planner_env)
    if problems:
        pytest.fail("live planner env malformed: " + "; ".join(problems))
    _check_planner_env(golden, planner_env)

    def _no_thumbs(deck: Path, payload: dict, *, log=None) -> dict[int, str]:
        return {}

    monkeypatch.setattr(framing, "build_preview_thumbs", _no_thumbs)
    fresh_wall = offline_wall_payload(deck)
    fresh_template = offline_wall_payload(TEMPLATE)
    proposal = framing.propose_framings(
        deck, TEMPLATE, wall_payload=fresh_wall, template_payload=fresh_template, log=lambda _m: None
    )

    apply_by_slide: dict[int, list[tuple]] = {}
    for t in plan["transforms"]:
        if t["role"] not in ROLE_SET:
            continue
        apply_by_slide.setdefault(int(t["slide"]), []).append(
            (t["role"], t["kind"], round(t["x"]), round(t["y"]), round(t["w"]), round(t["h"]))
        )

    differing: list[int] = []
    detail: list[str] = []
    for page in proposal.get("pages") or []:
        slide_no = int(page["slide"])
        propose_rows = [
            (r["role"], r["kind"], r["x"], r["y"], r.get("w", 0), r.get("h", 0))
            for r in page.get("autoRects") or []
            if r["role"] in ROLE_SET
        ]
        apply_rows = apply_by_slide.get(slide_no, [])
        if apply_rows != propose_rows:
            differing.append(slide_no)
            if len(detail) < 3:
                detail.append(f"slide {slide_no}: apply={apply_rows} propose={propose_rows}")

    assert differing == [], "\n".join([f"{len(differing)} slide(s) differ", *detail])


_FULL_WALL_BANK_SKIP = (
    "no JXA slide-digest bank for Full_Report_Card_Wall.key: a legacy Keynote read of a "
    "155-slide, 6.7 GB deck is deliberately not run on this machine (Gold, at 19 slides, "
    "peaked at 2.29 GB). Gold_Wall_Input.key is the cross-check deck; bank Full with "
    "scripts/bank_jxa_slide_digests.py --deck Full_Report_Card_Wall.key if you ever want it."
)


def _bank_skip_ladder(deck_name: str) -> dict:
    """Skip on a missing deck or bank file (Full's bank is deliberately absent, by
    name) or a deck digest drift (a missing input), naming the regeneration
    command. Fail on any other provenance drift (schema/version/config) or a bank
    whose digests no longer describe its own parts: a mis-described bank is a bug,
    not a missing input. Returns the loaded bank fixture."""
    deck = DECKS / deck_name
    if not deck.exists():
        pytest.skip("local gold deck only")
    bank_file = bank_path(deck_name)
    if not bank_file.exists():
        if deck_name == "Full_Report_Card_Wall.key":
            pytest.skip(_FULL_WALL_BANK_SKIP)
        pytest.skip(f"no JXA slide-digest bank for {deck_name}: {bank_file}")
    bank = json.loads(bank_file.read_text())

    for field, expected in (
        ("bankVersion", BANK_VERSION),
        ("slideDigestVersion", baseline.SLIDE_DIGEST_VERSION),
        ("inspectVersion", baseline.INSPECT_VERSION),
        ("deck", deck_name),
        ("reader", "jxa"),
    ):
        actual = bank.get(field, "<missing>")
        if actual != expected:
            pytest.fail(f"bank schema drift: {field} expected {expected!r}, got {actual!r}")

    source_digest = bank.get("sourceDigest")
    if not isinstance(source_digest, str) or not _HEX64.fullmatch(source_digest):
        pytest.fail(
            f"bank schema drift: sourceDigest expected a 64-char lowercase hex digest, got {source_digest!r}"
        )

    slides = bank.get("slides")
    slide_count = bank.get("slideCount")
    if not isinstance(slides, list) or slide_count != len(slides) or not slide_count:
        pytest.fail(
            f"bank schema drift: slideCount {slide_count!r} does not match "
            f"{len(slides) if isinstance(slides, list) else '<slides is not a list>'} banked slides"
        )

    problems = []
    for row in slides:
        parts = {"skipped": row.get("skipped"), "text": row.get("text"), "images": row.get("images")}
        recomputed = baseline.slide_digest(parts)
        if recomputed != row.get("digest"):
            problems.append(
                f"slide {row.get('slide')}: bank digest {row.get('digest')!r} != "
                f"{recomputed!r} recomputed from its own banked parts"
            )
    if problems:
        pytest.fail(
            "the bank's digests disagree with its own parts: `deck_slide_digests` changed "
            "without a `SLIDE_DIGEST_VERSION` bump\n" + "\n".join(problems)
        )

    actual_deck_digest = baseline.deck_digest(deck)
    if actual_deck_digest != source_digest:
        pytest.skip(
            f"deck digest drift (source {actual_deck_digest} vs {source_digest}); regenerate "
            f"with scripts/bank_jxa_slide_digests.py --deck {deck_name} --accept-input-drift"
        )
    return bank


@pytest.mark.parametrize("deck_name", WALL_DECKS)
def test_deck_slide_digests_offline_matches_banked_jxa(deck_name: str) -> None:
    bank = _bank_skip_ladder(deck_name)
    deck = DECKS / deck_name
    offline = offline_wall_payload(deck)
    actual = [baseline.slide_digest_parts(s) for s in offline.get("slides") or []]
    assert len(actual) == bank["slideCount"]

    problems: list[str] = []
    for index, (row, parts) in enumerate(zip(bank["slides"], actual)):
        for field in ("skipped", "text", "images"):
            if row.get(field) != parts.get(field):
                problems.append(f"slide {index} {field}: bank={row.get(field)!r} offline={parts.get(field)!r}")
    assert not problems, "\n".join(problems)

    assert baseline.deck_slide_digests(offline) == [row["digest"] for row in bank["slides"]]
