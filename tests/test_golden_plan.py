"""Keynote-free golden-plan gate: same source+template deck bytes must reproduce
the same `remap_keynote()` apply plan, byte-for-byte, without opening Keynote.
See `scripts/golden_plan.py` for the capture mechanism and canonicalisation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("keynote_parser")

from scripts.golden_plan import (  # noqa: E402
    ENV_PINS,
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
)

from obed_edom import baseline  # noqa: E402
from obed_edom import framing  # noqa: E402
from obed_edom.offline_inspect import offline_wall_payload  # noqa: E402

DECKS = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
TEMPLATE = DECKS / "Base_CG_Assets.key"
assert TEMPLATE == SCRIPT_TEMPLATE

ROLE_SET = {"map", "list", "pin", "title", "other"}


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
    """A different machine (OS build or installed/resolved fonts) is a missing
    input, not a bug: skip naming the differing component."""
    golden_env = golden["plannerEnv"]
    for component in ("osBuild", "fontEnv"):
        if golden_env.get(component) != actual_env.get(component):
            pytest.skip(
                f"planner env drift ({component}): {golden_env.get(component)!r} vs {actual_env.get(component)!r}"
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
    _check_planner_env(golden, planner_env)
    _check_plan(deck_name, golden, wall, tmpl, plan, tmp_path)


def test_golden_apply_plan_gold_wall_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _gate("Gold_Wall_Input.key", monkeypatch, tmp_path)


def test_golden_apply_plan_full_report_card_wall(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _gate("Full_Report_Card_Wall.key", monkeypatch, tmp_path)


@pytest.mark.xfail(
    strict=False,
    reason="propose plans on the UN-enriched payload (framing.py:376-377 never runs the "
    "remap_keynote.py:860-925 preamble); 32 of 155 slides differ today, measured "
    "2026-09-09. R2b turns this green.",
)
def test_propose_auto_rects_match_apply_transforms(monkeypatch: pytest.MonkeyPatch) -> None:
    deck_name = "Full_Report_Card_Wall.key"
    golden = _skip_ladder(deck_name)
    deck = DECKS / deck_name

    _pin_env(monkeypatch)
    _wall, _tmpl, plan, planner_env = capture_plan(deck, TEMPLATE)
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


@pytest.mark.parametrize("deck_name", WALL_DECKS)
def test_deck_slide_digests_offline_matches_cached_jxa(deck_name: str) -> None:
    deck = DECKS / deck_name
    if not deck.exists():
        pytest.skip("local gold deck only")
    cache_path = baseline.inspect_cache_path(baseline.deck_digest(deck))
    if not cache_path.is_file():
        pytest.skip("cache is cold for the current deck bytes; refuse to open Keynote")
    offline = offline_wall_payload(deck)
    cached = json.loads(cache_path.read_text())
    assert baseline.deck_slide_digests(offline) == baseline.deck_slide_digests(cached)
