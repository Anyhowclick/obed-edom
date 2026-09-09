"""R2b: propose reads the wall through the same acquisition path as apply.

Keynote-free except test 5, which is a local-only real-deck gate. Every test
that touches the digest cache sets ``CACHE_DIR_ENV`` to a tmp dir. Every stub
of a Keynote-touching function is signature-faithful -- ``inspect.py``'s
broad ``except`` swallows a ``TypeError`` from a wrong-signature stub and
falls back to a real Keynote read.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from obed_edom.baseline import CACHE_DIR_ENV

FULL_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key")
TEMPLATE_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Base_CG_Assets.key")
BANKED_TEMPLATE_DIGEST = "bbb0d1d45b46e7fe943bee2badeea8cdaac9ca5e7dac29fa74403913b9ea38f1"


def test_propose_acquires_through_the_shared_path_and_never_the_legacy_wall_read(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")

    full_wall = {
        "slideWidth": 7680, "slideHeight": 1080, "slideCount": 1,
        "slides": [{"number": 1, "index": 0, "items": []}],
    }
    template_data = {"slideWidth": 1920, "slideHeight": 1080, "slides": []}
    seen: dict = {}

    def fake_acquire(source, *, slide_range, mode, say):
        seen["acquire_slide_range"] = slide_range
        return full_wall

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None):
        if Path(key_path) == wall:
            pytest.fail("propose must never read the wall through the legacy inspect_keynote path")
        return template_data

    def fake_propose(_wall_path, _template_path, **kwargs):
        seen["propose_kwargs"] = kwargs
        return {"wallDigests": [], "templateDigest": "", "pages": []}

    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": False})

    logs: list[str] = []
    app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(), wall, template, None, False
    )

    assert seen["acquire_slide_range"] is None
    assert seen["propose_kwargs"]["wall_payload"] is full_wall


def test_ranged_propose_slices_the_acquired_full_payload_and_uses_navigator_numbering(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    wall = tmp_path / "Wall.key"
    template = tmp_path / "Base_CG_Assets.key"
    wall.write_text("wall")
    template.write_text("template")

    full_wall = {
        "slideWidth": 7680, "slideHeight": 1080, "slideCount": 3,
        "slides": [
            {"number": 1, "index": 0, "items": []},
            {"number": 2, "index": 1, "skipped": True, "items": []},
            {"number": 3, "index": 2, "items": []},
        ],
    }
    seen: dict = {}

    def fake_propose(_wall_path, _template_path, **kwargs):
        seen.update(kwargs)
        return {"wallDigests": [], "templateDigest": "", "pages": []}

    monkeypatch.setattr(
        app_mod, "acquire_wall_payload", lambda source, *, slide_range, mode, say: full_wall
    )
    monkeypatch.setattr(
        app_mod, "inspect_keynote",
        lambda key_path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None: {
            "slideWidth": 1920, "slideHeight": 1080, "slides": []
        },
    )
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": False})

    logs: list[str] = []
    app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(), wall, template, frozenset({2}), False
    )

    assert [s["number"] for s in seen["wall_payload"]["slides"]] == [3]
    assert [s["number"] for s in seen["full_wall_payload"]["slides"]] == [1, 2, 3]
    assert seen["wall_payload"]["slides"][0] is not seen["full_wall_payload"]["slides"][2]
    assert not any("not been read in full" in line for line in logs)


def test_two_tier_payload_is_cached_under_the_digest_and_served_back(tmp_path, monkeypatch):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod
    import obed_edom.remap_keynote as rk
    from obed_edom.baseline import deck_digest, inspect_cache_path

    deck = tmp_path / "Wall.key"
    deck.write_text("wall bytes")

    sample_errors = [{"slide": 1, "kind": "movie", "where": "collection", "error": "boom"}]

    def fake_bulk(key_path, slides=None, keep_open=False):
        return {}

    def fake_two_tier(key_path, *, bulk_geometry_fn=None, slide_range=None, log=None):
        return {
            "slideCount": 1,
            "slides": [{"number": 1, "index": 0, "items": []}],
            "bulkErrors": sample_errors,
            "_offline": {"bulk_ok": True, "fallback_slides": []},
        }

    monkeypatch.setattr(inspect_mod, "bulk_geometry", fake_bulk)
    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)

    logs: list[str] = []
    with monkeypatch.context() as m:
        m.setattr(rk, "cached_payload", lambda _source: None)
        out = rk.acquire_wall_payload(deck, slide_range=None, mode="on", say=logs.append)

    assert out["reader"] == "offline"
    assert out["bulkErrors"] == sample_errors

    json_path = inspect_cache_path(deck_digest(deck))
    assert json_path.is_file()
    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert stored["reader"] == "offline"
    assert stored["bulkErrors"] == sample_errors
    assert not any(str(k).startswith("_") for k in stored)

    def fail_two_tier(key_path, *, bulk_geometry_fn=None, slide_range=None, log=None):
        pytest.fail("cached offline payload must be served; two_tier_wall_payload must not run again")

    def fail_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None):
        pytest.fail("cached offline payload must be served; inspect_keynote must not run")

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fail_two_tier)
    monkeypatch.setattr(rk, "inspect_keynote", fail_inspect)

    out2 = rk.acquire_wall_payload(deck, slide_range=None, mode="on", say=logs.append)
    assert out2["reader"] == "offline"
    assert out2["bulkErrors"] == sample_errors


def test_cache_write_failure_does_not_fail_the_read(tmp_path, monkeypatch):
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    import obed_edom.inspect as inspect_mod
    import obed_edom.offline_inspect as offline_mod
    import obed_edom.remap_keynote as rk

    deck = tmp_path / "Wall.key"
    deck.write_text("wall bytes")

    monkeypatch.setattr(rk, "cached_payload", lambda _source: None)
    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda key_path, slides=None, keep_open=False: {})

    def fake_two_tier(key_path, *, bulk_geometry_fn=None, slide_range=None, log=None):
        return {
            "slideCount": 1,
            "slides": [{"number": 1, "index": 0, "items": []}],
            "_offline": {"bulk_ok": True, "fallback_slides": []},
        }

    monkeypatch.setattr(offline_mod, "two_tier_wall_payload", fake_two_tier)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(rk, "store_inspect_payload", boom)

    logs: list[str] = []
    out = rk.acquire_wall_payload(deck, slide_range=None, mode="on", say=logs.append)

    assert out["reader"] == "offline"
    assert out["slideCount"] == 1
    cache_warnings = [line for line in logs if "cache" in line.lower()]
    assert len(cache_warnings) == 1


_AUTO_RECT_ROLES = {"map", "list", "pin", "title", "other"}


class _PlanCaptured(Exception):
    pass


def _boom_jxa(plan: dict) -> dict:
    raise _PlanCaptured()


def _no_copy(source: Path, dest: Path) -> Path:
    return dest


def _no_previews(source, wall, *, folder=None, wanted=None):
    return {}, ""


def _no_thumbs(deck, payload, *, log=None):
    return {}


@pytest.mark.skipif(
    not (FULL_DECK.exists() and TEMPLATE_DECK.exists()), reason="local gold deck only"
)
def test_propose_framings_rects_equal_the_apply_plan_for_every_slide(tmp_path, monkeypatch):
    """Real-deck parity gate for invariant 2 (R2b plan): ``propose_framings`` itself
    (the production entry point, not a reimplementation of its fallback selection)
    plans ``autoRects`` that equal the apply plan's transforms for the same slide,
    same enriched payload. ``remap_keynote()`` is driven the same way
    ``scripts/golden_plan.py``'s ``_keynote_free``/``capture_plan`` does (not
    imported -- the minimal stub set is reproduced here): every Keynote-opening
    call is stubbed and ``_run_jxa`` raises a sentinel once the plan is built.
    """
    pytest.importorskip("keynote_parser")
    from obed_edom import framing as framing_mod
    from obed_edom import remap_keynote as rk
    from obed_edom.baseline import inspect_cache_path
    from obed_edom.offline_inspect import offline_wall_payload

    banked_template_path = inspect_cache_path(BANKED_TEMPLATE_DIGEST)
    if not banked_template_path.is_file():
        pytest.skip("no banked JXA payload for Base_CG_Assets.key in this cache")

    def fresh_wall() -> dict:
        wall = offline_wall_payload(FULL_DECK)
        wall["reader"] = "offline"
        wall["path"] = str(FULL_DECK)
        wall["slideCount"] = len(wall["slides"])
        return wall

    def fresh_template() -> dict:
        template = json.loads(banked_template_path.read_text(encoding="utf-8"))
        template.setdefault("reader", "jxa")
        return template

    monkeypatch.setattr(rk, "_run_jxa", _boom_jxa)
    monkeypatch.setattr(rk, "copy_keynote", _no_copy)
    monkeypatch.setattr(rk, "resolve_source_previews", _no_previews)

    apply_out: dict = {}
    dest = tmp_path / "golden-plan-never-written.key"
    try:
        rk.remap_keynote(
            FULL_DECK, dest, template=TEMPLATE_DECK,
            wall_payload=fresh_wall(), template_payload=fresh_template(),
            plan_out=apply_out, log=lambda _m: None,
        )
    except _PlanCaptured:
        pass
    else:
        pytest.fail("plan capture did not reach _run_jxa")

    apply_by_slide: dict[int, list[tuple]] = {}
    for t in apply_out["transforms"]:
        if t.get("role") not in _AUTO_RECT_ROLES:
            continue
        apply_by_slide.setdefault(int(t["slide"]), []).append(
            (t["role"], t["kind"], round(t["x"]), round(t["y"]),
             round(t.get("w", 0.0)), round(t.get("h", 0.0)))
        )

    monkeypatch.setattr(framing_mod, "build_preview_thumbs", _no_thumbs)

    proposal = framing_mod.propose_framings(
        FULL_DECK, TEMPLATE_DECK,
        wall_payload=fresh_wall(),
        template_payload=fresh_template(),
        log=lambda _m: None,
    )

    diffs: list[dict[str, Any]] = []
    for page in proposal["pages"]:
        n = int(page["slide"])
        propose_tuples = [
            (r["role"], r["kind"], round(r["x"]), round(r["y"]), round(r["w"]), round(r["h"]))
            for r in (page.get("autoRects") or [])
            if r["role"] in _AUTO_RECT_ROLES
        ]
        apply_tuples = apply_by_slide.get(n, [])

        if len(apply_tuples) != len(propose_tuples):
            diffs.append({
                "slide": n, "kind": "count",
                "apply_count": len(apply_tuples), "propose_count": len(propose_tuples),
            })
            continue

        apply_counts = Counter(apply_tuples)
        propose_counts = Counter(propose_tuples)
        if apply_counts != propose_counts:
            diffs.append({
                "slide": n, "kind": "multiset",
                "only_in_apply": list((apply_counts - propose_counts).elements()),
                "only_in_propose": list((propose_counts - apply_counts).elements()),
            })

    assert diffs == [], f"{len(diffs)} slide diff(s) across {len(proposal['pages'])} slides: {diffs}"
