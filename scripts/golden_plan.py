"""Keynote-free golden-plan gate for the CG resizer.

Captures `remap_keynote.remap_keynote`'s apply plan (transforms, reuses, asGeom,
group removes, badge raises, stat jobs) through the real public entry point with
every Keynote-opening call replaced by a signature-faithful stub (`_keynote_free`),
then hashes the canonicalised plan. Same source+template deck bytes must always
reproduce the same plan; the committed golden under `tests/fixtures/golden-plan/`
is the byte-for-byte baseline `tests/test_golden_plan.py` gates against.

    .venv/bin/python scripts/golden_plan.py update --deck Gold_Wall_Input.key
    .venv/bin/python scripts/golden_plan.py capture --deck Full_Report_Card_Wall.key \\
        --out /tmp/before.json

`update` rewrites the committed golden and prints the before/after `planSha256`
plus a summary diff, for a deliberate re-baseline to be reviewable. `capture`
writes the full canonical plan (a few MB) so a hash mismatch can be diffed at the
transform level against a capture from the pre-refactor revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from obed_edom import baseline, remap_keynote
from obed_edom.offline_inspect import offline_wall_payload

DECKS = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs")
TEMPLATE = DECKS / "Base_CG_Assets.key"
WALL_DECKS = ("Gold_Wall_Input.key", "Full_Report_Card_Wall.key")

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden-plan"

# `None` marks a var this gate delenv's rather than sets. Single source of truth for
# the CLI's `_pinned_env` and the test's `monkeypatch.setenv`/`delenv` calls, and for
# the golden's own "env" record, so the three cannot drift apart.
ENV_PINS: dict[str, str | None] = {
    "OBED_OFFLINE_WRITE": "off",
    "OBED_OFFLINE_READ": "on",
    "OBED_AS_GEOMETRY": "1",
    "OBED_SUPPRESS_GEOMETRY": None,
    "OBED_WRITE_TIMING": None,
    "OBED_GEOM_PROPS": None,
}

ROLE_SET = {"map", "list", "pin", "title", "other"}


class _PlanCaptured(Exception):
    pass


def _boom(name: str):
    def _f(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(f"{name} must not be called: this gate never opens Keynote")

    return _f


def _boom_jxa(plan: dict[str, Any]) -> dict[str, Any]:
    raise _PlanCaptured()


def _no_copy(source: Path, dest: Path) -> Path:
    return dest


def _no_previews(
    source: Path, wall: dict[str, Any], *, folder: Path | str | None = None, wanted: list[int] | None = None
) -> tuple[dict[int, Any], str]:
    return {}, ""


@contextmanager
def _keynote_free():
    """Patch `obed_edom.remap_keynote`'s Keynote-opening module attributes so a
    capture through the public `remap_keynote()` entry point cannot reach Keynote,
    however the refactor around it moves. Used identically by the CLI and the test."""
    patches: dict[str, Any] = {
        "_run_jxa": _boom_jxa,
        "copy_keynote": _no_copy,
        "resolve_source_previews": _no_previews,
        "inspect_keynote": _boom("inspect_keynote"),
        "acquire_wall_payload": _boom("acquire_wall_payload"),
        "export_slide_images": _boom("export_slide_images"),
        "inspect_keynote_checker": _boom("inspect_keynote_checker"),
    }
    originals = {name: getattr(remap_keynote, name) for name in patches}
    for name, stub in patches.items():
        setattr(remap_keynote, name, stub)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(remap_keynote, name, original)


@contextmanager
def _pinned_env():
    saved = {name: os.environ.get(name) for name in ENV_PINS}
    try:
        for name, value in ENV_PINS.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def capture_plan(source: Path, template: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Wall + template payloads (offline, mutated in place by the enrichment
    preamble) and the captured apply plan. Never opens Keynote: `_keynote_free`
    is applied around the one `remap_keynote()` call, which must raise
    `_PlanCaptured` at `_run_jxa` -- a normal return means the stub was bypassed."""
    wall = offline_wall_payload(source)
    tmpl = offline_wall_payload(template)
    assert "reader" not in wall
    out: dict[str, Any] = {}
    dest = Path(tempfile.gettempdir()) / "golden-plan-never-written.key"
    with _keynote_free():
        try:
            remap_keynote.remap_keynote(
                source,
                dest,
                template=template,
                wall_payload=wall,
                template_payload=tmpl,
                plan_out=out,
                log=lambda _m: None,
            )
        except _PlanCaptured:
            pass
        else:
            raise RuntimeError("plan capture did not reach _run_jxa")
    return wall, tmpl, out


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, 6)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def canonical(plan: dict[str, Any]) -> str:
    return json.dumps(
        _round_floats(plan), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(plan).encode()).hexdigest()


def enrichment_markers(wall: dict[str, Any], template: dict[str, Any]) -> dict[str, int]:
    def _count(payload: dict[str, Any], key: str) -> int:
        return sum(1 for s in payload.get("slides") or [] if s.get(key))

    return {
        "groupChildText": _count(wall, "groupChildText"),
        "groupCaption": _count(wall, "groupCaption"),
        "groupChildren": _count(wall, "groupChildren"),
        "builds": _count(wall, "builds"),
        "templateGroupCaption": _count(template, "groupCaption"),
    }


def summarize(plan: dict[str, Any]) -> dict[str, Any]:
    transforms = plan.get("transforms") or []
    reuses = plan.get("reuses") or []
    as_geom = plan.get("asGeom") or {}
    group_removes = plan.get("groupRemoves") or []
    badge_raises = plan.get("badgeRaises") or []
    stat_jobs = plan.get("statJobs") or []
    stat_slides = plan.get("statSlides") or []
    suppress = plan.get("suppressGeometry") or []

    totals = {
        "transforms": len(transforms),
        "reuses": len(reuses),
        "statJobs": len(stat_jobs),
        "statSlides": len(stat_slides),
        "badgeRaises": len(badge_raises),
        "groupRemoves": len(group_removes),
        "suppressGeometry": len(suppress),
        "asGeom": len(as_geom),
    }

    by_slide: dict[int, list[dict[str, Any]]] = {}
    for t in transforms:
        by_slide.setdefault(int(t["slide"]), []).append(t)
    stat_by_slide = Counter(int(r["slide"]) for r in stat_jobs)
    badge_by_slide = Counter(int(r["slide"]) for r in badge_raises)
    group_remove_by_slide = Counter(int(r["slide"]) for r in group_removes)

    slides = []
    for slide_no in sorted(by_slide):
        items = by_slide[slide_no]
        roles = Counter(str(t.get("role")) for t in items)
        body = as_geom.get(str(slide_no))
        slides.append(
            {
                "slide": slide_no,
                "n": len(items),
                "roles": dict(sorted(roles.items())),
                "statJobs": stat_by_slide.get(slide_no, 0),
                "badgeRaises": badge_by_slide.get(slide_no, 0),
                "groupRemoves": group_remove_by_slide.get(slide_no, 0),
                "asGeomSha": hashlib.sha256(body.encode()).hexdigest()[:12] if body else None,
                "asGeomLines": body.count("\n") + 1 if body else 0,
            }
        )

    reuse_rows = [
        {
            "slide": int(r["slide"]),
            "from": r.get("from"),
            "persist": r.get("persist"),
            "add": len(r.get("add") or []),
            "remove": len(r.get("remove") or []),
            "strip": len(r.get("strip") or []),
            "mutate": len(r.get("mutate") or []),
            "groupRemove": len(r.get("groupRemove") or []),
        }
        for r in reuses
    ]

    return {
        "totals": totals,
        "slides": slides,
        "reuses": reuse_rows,
        "suppressGeometry": sorted(int(x) for x in suppress),
        "statSlides": sorted(int(x) for x in stat_slides),
    }


def build_golden(
    source: Path, template: Path, wall: dict[str, Any], tmpl: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    return {
        "goldenVersion": 1,
        "deck": source.name,
        "template": template.name,
        "sourceDigest": baseline.deck_digest(source),
        "templateDigest": baseline.deck_digest(template),
        "inspectVersion": baseline.INSPECT_VERSION,
        "wallPayloadSource": "offline_wall_payload",
        "previews": "none",
        "env": dict(ENV_PINS),
        "enrichment": enrichment_markers(wall, tmpl),
        "planSha256": plan_hash(plan),
        **summarize(plan),
    }


def summary_diff(golden: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    if golden.get("totals") != actual.get("totals"):
        diffs.append(f"totals: {golden.get('totals')} -> {actual.get('totals')}")
    if golden.get("enrichment") != actual.get("enrichment"):
        diffs.append(f"enrichment: {golden.get('enrichment')} -> {actual.get('enrichment')}")

    g_reuses = {r["slide"]: r for r in golden.get("reuses") or []}
    a_reuses = {r["slide"]: r for r in actual.get("reuses") or []}
    for slide in sorted(set(g_reuses) | set(a_reuses)):
        if g_reuses.get(slide) != a_reuses.get(slide):
            diffs.append(f"reuse slide {slide}: {g_reuses.get(slide)} -> {a_reuses.get(slide)}")

    g_slides = {s["slide"]: s for s in golden.get("slides") or []}
    a_slides = {s["slide"]: s for s in actual.get("slides") or []}
    for slide in sorted(set(g_slides) | set(a_slides)):
        g_row, a_row = g_slides.get(slide), a_slides.get(slide)
        if g_row == a_row:
            continue
        if g_row is None or a_row is None:
            diffs.append(f"slide {slide}: {g_row} -> {a_row}")
            continue
        for field in sorted(set(g_row) | set(a_row)):
            if g_row.get(field) != a_row.get(field):
                diffs.append(f"slide {slide} {field}: {g_row.get(field)} -> {a_row.get(field)}")
    return diffs


def golden_path(deck_name: str) -> Path:
    return FIXTURES_DIR / f"{Path(deck_name).stem.lower()}.json"


def _do_capture(args: argparse.Namespace) -> None:
    deck = DECKS / args.deck
    template = Path(args.template) if args.template else TEMPLATE
    with _pinned_env():
        _wall, _tmpl, plan = capture_plan(deck, template)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(canonical(plan))
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes), plan sha {plan_hash(plan)}")


def _do_update(args: argparse.Namespace) -> None:
    deck = DECKS / args.deck
    template = Path(args.template) if args.template else TEMPLATE
    with _pinned_env():
        wall, tmpl, plan = capture_plan(deck, template)
    golden = build_golden(deck, template, wall, tmpl, plan)
    path = golden_path(args.deck)
    if path.exists():
        old = json.loads(path.read_text())
        print(f"old plan sha {old.get('planSha256')}")
        for line in summary_diff(old, golden):
            print(f"  {line}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(golden, sort_keys=True, indent=1) + "\n")
    totals = golden["totals"]
    print(
        f"{deck.name} {len(golden['slides'])} slides, {totals['transforms']} transforms, "
        f"{totals['reuses']} reuses, {totals['asGeom']} asGeom bodies\n"
        f"  source {golden['sourceDigest'][:16]}… template {golden['templateDigest'][:16]}… "
        f"plan sha {golden['planSha256'][:16]}…\n"
        f"  wrote {path}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--deck", required=True, help="deck file name under DECKS, e.g. Gold_Wall_Input.key")
        p.add_argument("--template", default=None, help="template .key path (default: Base_CG_Assets.key)")

    cap = sub.add_parser("capture", help="write the full canonical plan for a transform-level diff")
    _common(cap)
    cap.add_argument("--out", required=True, type=Path, help="output path for the canonical plan JSON")

    upd = sub.add_parser("update", help="rewrite the committed golden fixture")
    _common(upd)

    args = ap.parse_args(argv)
    if args.command == "capture":
        _do_capture(args)
    else:
        _do_update(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
