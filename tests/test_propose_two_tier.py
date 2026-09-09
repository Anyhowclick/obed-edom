"""R2b: propose reads the wall through the same acquisition path as apply.

Keynote-free except test 5, which is a local-only real-deck gate. Every test
that touches the digest cache sets ``CACHE_DIR_ENV`` to a tmp dir. Every stub
of a Keynote-touching function is signature-faithful -- ``inspect.py``'s
broad ``except`` swallows a ``TypeError`` from a wrong-signature stub and
falls back to a real Keynote read.
"""
from __future__ import annotations

import json
from pathlib import Path

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

    def fake_prepare(source, wall_payload, template_path, template_data_arg, say):
        seen["prepared_wall"] = wall_payload
        return 4.0

    def fake_inspect(key_path, *, export_dir=None, slide_range=None, use_cache=None, is_cancelled=None):
        if Path(key_path) == wall:
            pytest.fail("propose must never read the wall through the legacy inspect_keynote path")
        return template_data

    def fake_propose(_wall_path, _template_path, **kwargs):
        seen["propose_kwargs"] = kwargs
        return {"wallDigests": [], "templateDigest": "", "pages": []}

    monkeypatch.setattr(app_mod, "acquire_wall_payload", fake_acquire)
    monkeypatch.setattr(app_mod, "prepare_wall_payload", fake_prepare)
    monkeypatch.setattr(app_mod, "inspect_keynote", fake_inspect)
    monkeypatch.setattr(app_mod, "propose_framings", fake_propose)
    monkeypatch.setattr(app_mod, "load_settings", lambda: {"reusePairings": False})

    logs: list[str] = []
    app_mod._run_resize_propose(
        type("Job", (), {"log": logs.append})(), wall, template, None, False
    )

    assert seen["acquire_slide_range"] is None
    assert seen["prepared_wall"] is full_wall
    assert seen["propose_kwargs"]["wall_payload"] is full_wall
    assert seen["propose_kwargs"]["card_stroke"] == 4.0


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
        app_mod, "prepare_wall_payload",
        lambda source, wall_payload, template_path, template_data, say: 3.0,
    )
    monkeypatch.setattr(
        app_mod, "inspect_keynote",
        lambda key_path, **kwargs: {"slideWidth": 1920, "slideHeight": 1080, "slides": []},
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


@pytest.mark.skipif(
    not (FULL_DECK.exists() and TEMPLATE_DECK.exists()), reason="local gold deck only"
)
def test_propose_rects_equal_the_apply_plan_for_every_slide():
    """Real-deck parity gate for invariant 2 (R2b plan): same slide, same recipe, same
    enriched payload, no previews -> propose's rects equal apply's.

    ``plan_payload_transforms``'s fallback branch (map_remap.py) and ``propose_framings``'s
    fallback branch (framing.py) both carry ``characterStyles``/``listFontSize``/
    ``listSample``/``cardSamples`` from the pre-fit recipe onto a ``fit_to_frame_recipe``
    result via the shared ``carry_fit_context`` helper, so this gate calls the real
    production helper rather than reimplementing the carry. Confirmed by measurement:
    without the carry, 7 of 155 Full-wall slides mismatch, every one a fallback
    (fit-to-frame) slide carrying card/list/character-style context; with it, 0 of 155
    mismatch.
    """
    pytest.importorskip("keynote_parser")
    from obed_edom.baseline import inspect_cache_path
    from obed_edom.framing import planned_rects
    from obed_edom.map_remap import (
        CG_HEIGHT,
        CG_WIDTH,
        MIN_ON_CANVAS_FRACTION,
        carry_fit_context,
        fit_to_frame_recipe,
        is_degenerate_scale,
        learn_recipe,
        on_canvas_fraction,
        plan_payload_transforms,
    )
    from obed_edom.offline_inspect import offline_wall_payload
    from obed_edom.remap_keynote import prepare_wall_payload, recipe_for

    banked_template_path = inspect_cache_path(BANKED_TEMPLATE_DIGEST)
    if not banked_template_path.is_file():
        pytest.skip("no banked JXA payload for Base_CG_Assets.key in this cache")

    wall = offline_wall_payload(FULL_DECK)
    wall["reader"] = "offline"
    wall["path"] = str(FULL_DECK)
    wall["slideCount"] = len(wall["slides"])

    template = json.loads(banked_template_path.read_text(encoding="utf-8"))
    template.setdefault("reader", "jxa")

    card_stroke = prepare_wall_payload(FULL_DECK, wall, TEMPLATE_DECK, template, lambda _m: None)
    recipe = recipe_for(wall, template)
    wall_w = float(wall["slideWidth"])
    wall_h = float(wall["slideHeight"])

    def dropped(t) -> bool:
        return t.role == "hide" or (t.opacity is not None and t.opacity <= 0.0)

    mismatches: list[int] = []
    for slide in wall["slides"]:
        if slide.get("skipped"):
            continue
        n = int(slide["number"])
        single = {"slideWidth": wall["slideWidth"], "slideHeight": wall["slideHeight"], "slides": [slide]}
        auto = learn_recipe(single, template, template_slide=None).get("templateSlide")

        apply_transforms = plan_payload_transforms(
            wall, recipe, slide_range=frozenset({n}), template=template,
            framing_overrides={n: auto}, card_stroke=card_stroke, previews=None,
        )
        apply_tuples = sorted(
            (t.role, t.kind, round(t.x), round(t.y), round(t.w), round(t.h), not dropped(t))
            for t in apply_transforms
        )

        propose_recipe = learn_recipe(single, template, template_slide=auto)
        shown = propose_recipe
        falls_back = (
            on_canvas_fraction(slide, propose_recipe, wall_w, wall_h) < MIN_ON_CANVAS_FRACTION
            or is_degenerate_scale(propose_recipe, wall_w, wall_h)
        )
        if falls_back:
            fitted = fit_to_frame_recipe(
                slide, wall_w, wall_h,
                float(propose_recipe.get("destWidth") or CG_WIDTH),
                float(propose_recipe.get("destHeight") or CG_HEIGHT),
            )
            if fitted:
                shown = carry_fit_context(fitted, propose_recipe)
        propose_rects = planned_rects(
            slide, shown, wall_size=(wall_w, wall_h), card_stroke=card_stroke
        )
        propose_tuples = sorted(
            (r["role"], r["kind"], r["x"], r["y"], r["w"], r["h"], r["willBeInOutput"])
            for r in propose_rects
        )

        if apply_tuples != propose_tuples:
            mismatches.append(n)

    assert mismatches == []
