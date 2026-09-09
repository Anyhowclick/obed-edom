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
plus a summary diff, for a deliberate re-baseline to be reviewable; it refuses a
deck/template digest change unless `--accept-input-drift` is passed. `capture`
writes the full canonical plan (a few MB) so a hash mismatch can be diffed at the
transform level against a capture from the pre-refactor revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
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

GOLDEN_VERSION = 1
WALL_PAYLOAD_SOURCE = "offline_wall_payload"
PREVIEWS_NONE = "none"

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


_FACES_UNAVAILABLE = "FONT_ENV_UNAVAILABLE"


def _os_build() -> str:
    """The actual macOS build (`sw_vers -buildVersion`), not `platform.mac_ver`'s
    product version: a supplemental build can share a product version while
    resolving fonts differently."""
    return subprocess.run(
        ["sw_vers", "-buildVersion"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _caption_faces(wall: dict[str, Any]) -> list[tuple[str, bool, bool]]:
    """Every `(font, bold, italic)` triple `map_remap.caption_point_size` actually
    measures, read from the SOURCE wall's `groupCaption` records (attached in place
    by `iwa_runs.attach_group_captions` during `remap_keynote`'s enrichment)."""
    faces: set[tuple[str, bool, bool]] = set()
    for slide in wall.get("slides") or []:
        for cap in (slide.get("groupCaption") or {}).values():
            font = cap.get("font")
            if font:
                faces.add((font, bool(cap.get("bold")), bool(cap.get("italic"))))
    return sorted(faces)


def _resolve_faces(faces: list[tuple[str, bool, bool]]) -> dict[str, str] | str:
    """Resolved PostScript name + family per face via `iwa_text_shape._ns_font`
    at a fixed 12pt, keyed `"<font>|<bold>|<italic>"` for JSON stability. Mirrors
    `slide_fingerprint._compute_font_env`'s bridge-availability probe."""
    try:
        from AppKit import NSFont  # noqa: F401,PLC0415 (bridge probe)

        from obed_edom.iwa_text_shape import _ns_font  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — no bridge -> stable sentinel, never raise
        return _FACES_UNAVAILABLE

    out: dict[str, str] = {}
    for font, bold, italic in faces:
        key = f"{font}|{bold}|{italic}"
        try:
            resolved, missing, _trait_bad = _ns_font(font, 12.0, bold=bold, italic=italic)
        except Exception:  # noqa: BLE001 — a single bad font must not sink the env
            out[key] = "missing"
            continue
        out[key] = "missing" if missing else f"{resolved.fontName()}|{resolved.familyName()}"
    return out


def planner_env(wall: dict[str, Any]) -> dict[str, Any]:
    """OS build + resolved caption faces for the SOURCE wall: the hidden inputs of
    `map_remap.caption_point_size` (AppKit/TextKit text measurement via
    `iwa_text_shape._ns_font`). Must be called after enrichment, since `faces`
    reads the `groupCaption` records `remap_keynote` attaches in place."""
    return {"osBuild": _os_build(), "faces": _resolve_faces(_caption_faces(wall))}


def capture_plan(
    source: Path, template: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Wall + template payloads (offline, mutated in place by the enrichment
    preamble), the captured apply plan, and the source wall's `planner_env`
    (computed after enrichment, since `faces` fingerprints the attached
    `groupCaption` records). Never opens Keynote: `_keynote_free` is applied
    around the one `remap_keynote()` call, which must raise `_PlanCaptured` at
    `_run_jxa` -- a normal return means the stub was bypassed."""
    from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415 (optional extra)

    source_deck = _load_deck(source)
    wall = offline_wall_payload(source, deck=source_deck)
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
    env = planner_env(wall)
    return wall, tmpl, out, env


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
    source: Path,
    template: Path,
    wall: dict[str, Any],
    tmpl: dict[str, Any],
    plan: dict[str, Any],
    planner_env_: dict[str, Any],
) -> dict[str, Any]:
    return {
        "goldenVersion": GOLDEN_VERSION,
        "deck": source.name,
        "template": template.name,
        "sourceDigest": baseline.deck_digest(source),
        "templateDigest": baseline.deck_digest(template),
        "inspectVersion": baseline.INSPECT_VERSION,
        "wallPayloadSource": WALL_PAYLOAD_SOURCE,
        "previews": PREVIEWS_NONE,
        "env": dict(ENV_PINS),
        "plannerEnv": planner_env_,
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
        _wall, _tmpl, plan, _env = capture_plan(deck, template)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(canonical(plan))
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes), plan sha {plan_hash(plan)}")


def _do_update(args: argparse.Namespace) -> None:
    deck = DECKS / args.deck
    template = Path(args.template) if args.template else TEMPLATE
    path = golden_path(args.deck)
    old = json.loads(path.read_text()) if path.exists() else None
    source_digest = baseline.deck_digest(deck)
    template_digest = baseline.deck_digest(template)
    if old is not None:
        print(f"source digest {old.get('sourceDigest')} -> {source_digest}")
        print(f"template digest {old.get('templateDigest')} -> {template_digest}")
        drifted = old.get("sourceDigest") != source_digest or old.get("templateDigest") != template_digest
        if drifted and not args.accept_input_drift:
            raise SystemExit(
                "input digest drift vs the committed golden; pass --accept-input-drift to "
                "re-bank against the new deck/template bytes"
            )
    with _pinned_env():
        wall, tmpl, plan, planner_env_ = capture_plan(deck, template)
    golden = build_golden(deck, template, wall, tmpl, plan, planner_env_)
    if old is not None:
        print(f"old plan sha {old.get('planSha256')}")
        diff_lines = summary_diff(old, golden)
        if diff_lines:
            for line in diff_lines:
                print(f"  {line}")
        elif old.get("planSha256") != golden["planSha256"]:
            print("  projected summary unchanged; hash differs (a field the summary does not project moved)")
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
    upd.add_argument(
        "--accept-input-drift",
        action="store_true",
        help="allow re-banking when the deck/template digest differs from the committed golden",
    )

    args = ap.parse_args(argv)
    if args.command == "capture":
        _do_capture(args)
    else:
        _do_update(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
