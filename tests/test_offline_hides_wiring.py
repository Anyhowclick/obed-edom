"""Stream D of `.agents/plans/pass1_hides_offline.plan.md`: the `OBED_OFFLINE_HIDES` flag,
pure eligibility, `run_offline_hides` orchestration + AppleScript delete fallback, and the
`remap_keynote` wiring (plan field, abort, Applied accounting, call order).

Keynote-free: `iwa_hides.patch_deck_hides` (Stream B) is replaced by a stub module in
`sys.modules`, and every osascript call goes through a stub or `_fake_osascript`.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from conftest import _fake_osascript
from obed_edom import offline_write
from obed_edom import remap_keynote as rk
from obed_edom.map_remap import ItemTransform, Plan
from test_remap_keynote import _touch_paths


# --- helpers ------------------------------------------------------------------------


class _SlideHides:
    def __init__(self, deleted=0, refused=False, reason=None, removed_ids=(), order_proven=False):
        self.deleted = deleted
        self.refused = refused
        self.reason = reason
        self.removed_ids = list(removed_ids)
        self.order_proven = order_proven


def _proven_refusal(reason="component externalReferences names 9"):
    """A refusal raised after the writer proved saved order == source order (R1-R4 passed)."""
    return _SlideHides(0, True, reason, order_proven=True)


class _HidesResult:
    def __init__(self, slides, dropped_data=(), members=()):
        self.slides = slides
        self.dropped_data = list(dropped_data)
        self.members = list(members)


def _hide(slide, kind, ki):
    return {"slide": slide, "kind": kind, "kindIndex": ki, "role": "hide", "x": 0, "y": 0}


def _move(slide, kind, ki):
    return {"slide": slide, "kind": kind, "kindIndex": ki, "role": "map", "x": 1, "y": 2}


def _install_writer(monkeypatch, fn):
    """Stand in for Stream B's module; `from obed_edom.iwa_hides import ...` resolves here."""
    mod = types.ModuleType("obed_edom.iwa_hides")
    mod.patch_deck_hides = fn
    monkeypatch.setitem(sys.modules, "obed_edom.iwa_hides", mod)


def _record_fallback(monkeypatch, *, ok=True, missed_lines=()):
    calls = []

    def fake(dest, scripts, say, *, suffix=".offline-fallback", marker=None):
        calls.append({"scripts": list(scripts), "suffix": suffix, "marker": marker})
        return ok, ([Path(str(dest) + suffix + ".applescript")] if not ok else []), list(missed_lines)

    monkeypatch.setattr(offline_write, "_run_fallback_scripts", fake)
    return calls


@pytest.fixture
def deck(tmp_path):
    p = tmp_path / "out.key"
    p.write_bytes(b"deck-bytes")
    return p


WALL = {"slides": [
    {"number": 1, "items": [{"kind": "image"}, {"kind": "image"}, {"kind": "text"}]},
    {"number": 2, "items": [{"kind": "shape"}], "builds": [{"kind": "shape", "kindIndex": 0}]},
    {"number": 3, "items": [{"kind": "text"}, {"kind": "group"}], "groupChildText": {"1": "sig"}},
]}


# --- mode helper ----------------------------------------------------------------------


def test_offline_hides_mode_defaults_off(monkeypatch):
    monkeypatch.delenv("OBED_OFFLINE_HIDES", raising=False)
    assert rk.offline_hides_mode(offline_mode="on") == "off"
    assert rk.offline_hides_mode("", offline_mode="on") == "off"
    assert rk.offline_hides_mode("off", offline_mode="on") == "off"


def test_offline_hides_mode_on_and_verify(monkeypatch):
    assert rk.offline_hides_mode("on", offline_mode="on") == "on"
    assert rk.offline_hides_mode(" VERIFY ", offline_mode="verify") == "verify"
    monkeypatch.setenv("OBED_OFFLINE_HIDES", "on")
    assert rk.offline_hides_mode(offline_mode="on") == "on"


def test_offline_hides_mode_unknown_token_is_off_with_a_say():
    said = []
    assert rk.offline_hides_mode("yes", offline_mode="on", say=said.append) == "off"
    assert said and "Unknown OBED_OFFLINE_HIDES" in said[0]


def test_offline_hides_mode_forced_off_with_offline_write_off():
    said = []
    assert rk.offline_hides_mode("on", offline_mode="off", say=said.append) == "off"
    assert "needs OBED_OFFLINE_WRITE on" in said[0]


def test_offline_hides_mode_forced_off_when_iwa_extra_missing(monkeypatch):
    """The extra is probed once by `probe_iwa_extra`, which downgrades `offline_mode`;
    the hides helper follows that kill switch."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name in {"keynote_parser", "obed_edom.iwa_write"}:
            raise ImportError("no iwa extra")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    offline_mode = offline_write.probe_iwa_extra("on", None)
    assert offline_mode == "off"
    assert rk.offline_hides_mode("on", offline_mode=offline_mode) == "off"


# --- eligibility ------------------------------------------------------------------------


def test_eligibility_slides_with_hides_only():
    t = [_hide(1, "image", 0), _move(1, "text", 0), _move(3, "text", 0)]
    assert offline_write.offline_hide_slides(t, WALL, None) == {1}


def test_eligibility_excludes_slide_whose_build_targets_a_hide():
    t = [_hide(1, "image", 1), _hide(2, "shape", 0)]
    assert offline_write.offline_hide_slides(t, WALL, None) == {1}


def test_eligibility_build_on_a_non_hide_keeps_the_slide():
    wall = {"slides": [{"number": 2, "items": [], "builds": [{"kind": "shape", "kindIndex": 3}]}]}
    assert offline_write.offline_hide_slides([_hide(2, "shape", 0)], wall, None) == {2}


def test_eligibility_intersects_wanted():
    t = [_hide(1, "image", 0), _hide(3, "group", 0)]
    assert offline_write.offline_hide_slides(t, WALL, [3, 4]) == {3}
    assert offline_write.offline_hide_slides(t, WALL, None) == {1, 3}


def test_eligibility_empty():
    assert offline_write.offline_hide_slides([], WALL, None) == set()
    assert offline_write.offline_hide_slides([_move(1, "image", 0)], WALL, None) == set()


def test_eligibility_excludes_unaddressable_hide():
    t = [_hide(1, "image", 0), {**_hide(3, "text", 0), "kindIndex": None}]
    assert offline_write.offline_hide_slides(t, WALL, None) == {1}


# --- fallback body ------------------------------------------------------------------------


def test_hide_delete_body_follows_deletehides_order_and_as_index():
    """deleteHides order within a slide: kind ascending, kindIndex descending; AppleScript
    index = kindIndex + 1; delete, else opacity 0 + the miss marker."""
    body = offline_write._hide_delete_body(
        [_hide(4, "text", 0), _hide(4, "image", 2), _hide(4, "text", 5), _hide(4, "image", 7)], 4,
    )
    deletes = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("delete ")]
    assert deletes == ["delete image 8", "delete image 3", "delete text item 6", "delete text item 1"]
    assert body.splitlines()[:2] == ["with timeout of 3600 seconds", "tell slide 4"]
    assert "set opacity of image 8 to 0" in body
    assert 'log "OBED_HIDE_MISSED slide=4 kind=image kindIndex=7"' in body
    assert body.index("delete image 8") < body.index("set opacity of image 8 to 0")


def test_run_fallback_scripts_hides_suffix_and_marker(monkeypatch, tmp_path):
    _fake_osascript(
        monkeypatch, returncode=1,
        stderr="OBED_GEOM_UNWRITABLE slide=1 kind=shape kindIndex=0\n"
               "OBED_HIDE_MISSED slide=2 kind=image kindIndex=0\n",
    )
    dest = tmp_path / "out.key"
    ok, dumps, lines = offline_write._run_fallback_scripts(
        dest, ["S"], lambda m: None, suffix=".hides-fallback", marker=offline_write.HIDE_MISSED_MARKER,
    )
    assert ok is False
    assert dumps == [tmp_path / "out.hides-fallback.applescript"]
    assert lines == ["OBED_HIDE_MISSED slide=2 kind=image kindIndex=0"]


def test_run_fallback_scripts_default_suffix_unchanged(monkeypatch, tmp_path):
    _fake_osascript(monkeypatch, returncode=1)
    ok, dumps, _ = offline_write._run_fallback_scripts(tmp_path / "out.key", ["A", "B"], lambda m: None)
    assert dumps == [tmp_path / "out.offline-fallback-1.applescript",
                     tmp_path / "out.offline-fallback-2.applescript"]


# --- run_offline_hides --------------------------------------------------------------------


TRANSFORMS = [
    _hide(1, "image", 0), _hide(1, "image", 1), _move(1, "text", 0),
    _hide(3, "group", 0), _hide(3, "text", 0),
]


def test_run_offline_hides_noop_without_eligible_slides(monkeypatch, deck):
    calls = []
    _install_writer(monkeypatch, lambda *a, **k: calls.append(a))
    fb = _record_fallback(monkeypatch)
    assert offline_write.run_offline_hides(deck, "on", set(), TRANSFORMS, WALL, print) is None
    assert offline_write.run_offline_hides(deck, "off", {1}, TRANSFORMS, WALL, print) is None
    assert calls == [] and fb == []


def test_run_offline_hides_all_deleted_offline(monkeypatch, deck):
    seen = {}

    def writer(d, hides_by_slide, **kw):
        seen.update(deck=d, hides=hides_by_slide, **kw)
        return _HidesResult({1: _SlideHides(2), 3: _SlideHides(2)}, dropped_data=["Data/a.png"])

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    said = []
    info = offline_write.run_offline_hides(deck, "verify", {1, 3}, TRANSFORMS, WALL, said.append)

    assert fb == []
    assert info["deleted"] == 4 and info["refused"] == []
    assert info["droppedData"] == 1
    assert sorted(seen["hides"]) == [1, 3]
    assert all(s["role"] == "hide" for v in seen["hides"].values() for s in v)
    assert seen["verify"] is True
    assert seen["source_counts_by_slide"][1] == {"image": 2, "text": 1}
    assert seen["items_by_slide"][3] == WALL["slides"][2]["items"]
    assert seen["group_text_by_slide"][3] == {1: "sig"}
    assert seen["force_refuse"] == frozenset()
    assert any(m.startswith("Offline hides (verify): 2 slide(s), 4 deleted, 0 refused") for m in said)


def test_run_offline_hides_order_proven_refusal_goes_to_applescript_delete(monkeypatch, deck):
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult(
        {1: _SlideHides(2), 3: _proven_refusal("R5 build ref")}))
    fb = _record_fallback(monkeypatch)
    said = []
    info = offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, said.append)

    assert len(fb) == 1
    assert fb[0]["suffix"] == ".hides-fallback"
    assert fb[0]["marker"] == offline_write.HIDE_MISSED_MARKER
    script = fb[0]["scripts"][0]
    assert "tell slide 3" in script and "tell slide 1" not in script
    assert script.index("delete group 1") < script.index("delete text item 1")
    assert info["offlineDeleted"] == 2 and info["fallbackDeleted"] == 2
    assert info["deleted"] == 4
    assert "missed" not in info
    assert info["refused"] == [{"slide": 3, "reason": "R5 build ref"}]
    assert any("slide 3 R5 build ref" in m for m in said)


@pytest.mark.parametrize("reason", [
    "group 0 child-text signature differs from the payload",
    "reconcile mismatch on kinds ['image']",
    "hide image 1 does not resolve",
    "planning failed: KeyError('x')",
])
def test_identity_or_address_refusal_aborts_before_any_keynote_reopen(monkeypatch, deck, reason):
    """Codex r1 #1: the saved order may differ from the source (e.g. two groups swapped
    during the pass-1 save), so an AppleScript delete by source kindIndex could remove the
    wrong object. No fallback session may open."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult(
        {1: _proven_refusal(), 3: _SlideHides(0, True, reason, order_proven=False)}))
    fb = _record_fallback(monkeypatch)
    with pytest.raises(RuntimeError, match=r"refused slide\(s\) \[3\] before proving the saved order"):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []


def test_any_hide_missed_marker_is_fatal(monkeypatch, deck):
    """Codex r1 #3: a failed delete (opacity 0 at best) leaves the drawable in its kind
    collection, so `source - hides` no longer holds; the stage must abort, not count a miss."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult(
        {1: _SlideHides(2), 3: _proven_refusal()}))
    _record_fallback(monkeypatch, missed_lines=["OBED_HIDE_MISSED slide=3 kind=text kindIndex=0"])
    with pytest.raises(RuntimeError, match="could not delete 1 hide"):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)


def test_run_offline_hides_fallback_failure_raises(monkeypatch, deck):
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _proven_refusal("x"),
                                                                  3: _SlideHides(2)}))
    _record_fallback(monkeypatch, ok=False)
    with pytest.raises(RuntimeError, match="offline hides fallback failed"):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)


def test_run_offline_hides_debug_refuse_is_passed_as_force_refuse(monkeypatch, deck):
    seen = {}

    def writer(d, h, **kw):
        seen.update(kw)
        return _HidesResult({1: _SlideHides(2), 3: _SlideHides(2)})

    _install_writer(monkeypatch, writer)
    _record_fallback(monkeypatch)
    monkeypatch.setenv("OBED_DEBUG_HIDES_REFUSE", "3, 7")
    offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert seen["force_refuse"] == frozenset({3, 7})


def _assert_all_to_fallback(fb, info):
    assert len(fb) == 1
    script = fb[0]["scripts"][0]
    assert "tell slide 1" in script and "tell slide 3" in script
    assert info["offlineDeleted"] == 0
    assert info["deleted"] == 4
    assert [r["slide"] for r in info["refused"]] == [1, 3]


def test_disk_guard_refusal_routes_every_eligible_slide_to_fallback(monkeypatch, deck):
    iwa_write = pytest.importorskip("obed_edom.iwa_write")

    def writer(d, h, **kw):
        raise iwa_write.OfflineWriteRefused("free space below deck size * 2.1")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    said = []
    info = offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, said.append)
    _assert_all_to_fallback(fb, info)
    assert any(m.startswith("WARNING offline hides refused before writing") for m in said)


def test_refused_with_changed_deck_stamp_still_falls_back(monkeypatch, deck):
    """Codex r1 #7 control: the typed `OfflineWriteRefused` signal decides, not the file's
    stat (a pre-write touch of the deck must not flip it to an abort)."""
    iwa_write = pytest.importorskip("obed_edom.iwa_write")

    def writer(d, h, **kw):
        Path(d).write_bytes(b"different-size-and-mtime")
        raise iwa_write.OfflineWriteRefused("undecodable member")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    info = offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    _assert_all_to_fallback(fb, info)


@pytest.mark.parametrize("exc", [
    RuntimeError("hides read-back slide 1: lists != expected"),
    KeyError("bug before writing"),
    ValueError("slide numbers are 1-based"),
])
def test_any_other_writer_exception_aborts_without_fallback(monkeypatch, deck, exc):
    """Codex r1 #7 control: the deck is untouched here (same stamp), yet only
    `OfflineWriteRefused` proves nothing was written, so everything else aborts."""
    def writer(d, h, **kw):
        raise exc

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    before = deck.read_bytes()
    with pytest.raises(RuntimeError, match="state of .* is unknown"):
        offline_write.run_offline_hides(deck, "verify", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []
    assert deck.read_bytes() == before


def test_writer_import_failure_aborts_without_fallback(monkeypatch, deck):
    monkeypatch.setitem(sys.modules, "obed_edom.iwa_hides", None)
    fb = _record_fallback(monkeypatch)
    with pytest.raises(ImportError):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []


def test_offline_write_corrupted_propagates_without_fallback(monkeypatch, deck):
    iwa_write = pytest.importorskip("obed_edom.iwa_write")

    def writer(d, h, **kw):
        raise iwa_write.OfflineWriteCorrupted("truncated")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    said = []
    with pytest.raises(iwa_write.OfflineWriteCorrupted):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, said.append)
    assert fb == []
    assert any("OFFLINE-HIDES CORRUPTED" in m and "RECOVERY" in m for m in said)


# --- snapshots --------------------------------------------------------------------------


def test_pre_hides_snapshot_naming(monkeypatch, deck, tmp_path):
    snap = tmp_path / "snaps" / "pass1.key"
    snap.parent.mkdir()
    monkeypatch.setenv("OBED_DEBUG_PASS1_SNAPSHOT", str(snap))
    contents_at_write = {}

    def writer(d, h, **kw):
        contents_at_write["pre"] = (tmp_path / "snaps" / "pass1.pre-hides.key").read_bytes()
        return _HidesResult({1: _SlideHides(2), 3: _SlideHides(2)})

    _install_writer(monkeypatch, writer)
    _record_fallback(monkeypatch)
    offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert contents_at_write["pre"] == b"deck-bytes"
    assert not snap.exists()


def test_post_snapshot_keeps_its_name(monkeypatch, deck, tmp_path):
    snap = tmp_path / "pass1.key"
    monkeypatch.setenv("OBED_DEBUG_PASS1_SNAPSHOT", str(snap))
    rk._debug_snapshot_pass1(deck)
    assert snap.read_bytes() == b"deck-bytes"


def test_no_snapshot_without_env(monkeypatch, deck, tmp_path):
    monkeypatch.delenv("OBED_DEBUG_PASS1_SNAPSHOT", raising=False)
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _SlideHides(2), 3: _SlideHides(2)}))
    offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.key"]


# --- remap_keynote wiring -----------------------------------------------------------------


def _remap_transforms():
    return [
        ItemTransform(slide_number=1, item_index=0, kind="image", x=0, y=0, w=1, h=1,
                      role="hide", kind_index=0),
        ItemTransform(slide_number=1, item_index=1, kind="image", x=0, y=0, w=1, h=1,
                      role="hide", kind_index=1),
        ItemTransform(slide_number=1, item_index=2, kind="text", x=5, y=5, w=1, h=1,
                      role="map", kind_index=0),
    ]


def _wire(monkeypatch, *, hides_env, jxa, events=None, hides_info=None):
    """Runs the real `rk.remap_keynote` orchestration with every Keynote-facing call stubbed;
    returns the plan handed to `_run_jxa` and the `run_offline_hides` calls."""
    events = events if events is not None else []
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "on")
    monkeypatch.setenv("OBED_AS_GEOMETRY", "on")
    monkeypatch.setenv("OBED_ZORDER_WRITE", "off")
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    monkeypatch.delenv("OBED_DEBUG_PASS1_SNAPSHOT", raising=False)
    if hides_env is None:
        monkeypatch.delenv("OBED_OFFLINE_HIDES", raising=False)
    else:
        monkeypatch.setenv("OBED_OFFLINE_HIDES", hides_env)
    monkeypatch.setattr(rk, "plan_payload", lambda *a, **k: Plan(
        transforms=_remap_transforms(), placements=[], skipped_slides=[], fitted_slides=[],
        offframe=[], framing=[], child_resize=[], badge_raises=[], card_grid=[], roster={},
    ))
    monkeypatch.setattr(rk, "recipe_for", lambda wall, template: {
        "source": "test", "mapSrc": "src", "mapDst": "dst",
        "destWidth": 1920, "destHeight": 1080, "characterStyles": [],
    })
    monkeypatch.setattr(rk, "score_against_gold", lambda *a, **k: 0.0)
    monkeypatch.setattr(rk, "summarize_plan", lambda transforms: {"map": 0, "pin": 0, "list": 0, "hide": 0})
    monkeypatch.setattr(rk, "copy_keynote", lambda source, dest: dest)
    monkeypatch.setattr(rk.offline_write, "_offline_write_slides", lambda *a, **k: {1})

    captured = {}

    def fake_run_jxa(plan):
        captured.update(plan)
        events.append("runJxa")
        return dict(jxa)

    monkeypatch.setattr(rk, "_run_jxa", fake_run_jxa)

    real_require = rk._require_pass1_saved_closed

    def require(j):
        events.append("requireSavedClosed")
        return real_require(j)

    monkeypatch.setattr(rk, "_require_pass1_saved_closed", require)
    monkeypatch.setattr(rk, "_debug_snapshot_pass1", lambda dest, say=None, **k: events.append("snapshotPass1"))

    hides_calls = []

    def fake_hides(dest, mode, hide_slides, transform_dicts, wall, say):
        events.append("runOfflineHides")
        hides_calls.append({"mode": mode, "slides": set(hide_slides)})
        return hides_info

    monkeypatch.setattr(rk.offline_write, "run_offline_hides", fake_hides)

    def fake_offline_write(*a, **k):
        events.append("runOfflineWrite")
        return {"refused": []}

    monkeypatch.setattr(rk.offline_write, "run_offline_write", fake_offline_write)

    def fake_eligible(*a, **k):
        events.append("zorderEligible")
        return {}, {"zorderUnresolved": 0, "zorderRefused": 0, "zorderGui": []}

    monkeypatch.setattr(rk.offline_write, "zorder_eligible_slides", fake_eligible)
    monkeypatch.setattr(rk, "restore_card_stroke_widths",
                        lambda *a, **k: events.append("cardStroke") or None)
    monkeypatch.setattr(rk, "_run_stat_finalize",
                        lambda *a, **k: events.append("statFinalize") or {"ok": True, "closed": True})
    monkeypatch.setattr(rk, "restore_source_builds",
                        lambda *a, **k: events.append("builds") or None)
    return captured, hides_calls


def _run(tmp_path, said=None):
    source, template, dest = _touch_paths(tmp_path)
    wall_payload = {"slideWidth": 7680, "slideHeight": 1080,
                    "slides": [{"number": 1, "items": [{"kind": "image"}, {"kind": "image"}, {"kind": "text"}]}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    return rk.remap_keynote(
        source, dest, template=template, wall_payload=wall_payload,
        template_payload=template_payload, log=(said.append if said is not None else lambda m: None),
    )


JXA_OK = {"applied": 1, "missed": 0, "saved": True, "closed": True}


def test_plan_field_absent_when_off(monkeypatch, tmp_path):
    plan, hides_calls = _wire(monkeypatch, hides_env=None, jxa=JXA_OK)
    _run(tmp_path)
    assert "offlineHideSlides" not in plan
    assert hides_calls == [{"mode": "off", "slides": set()}]


def test_plan_field_present_when_on(monkeypatch, tmp_path):
    plan, hides_calls = _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "hidesDeferred": 2},
                              hides_info={"deleted": 2})
    _run(tmp_path)
    assert plan["offlineHideSlides"] == [1]
    assert all(isinstance(n, int) for n in plan["offlineHideSlides"])
    assert hides_calls == [{"mode": "on", "slides": {1}}]


def test_plan_field_absent_when_offline_write_off(monkeypatch, tmp_path):
    plan, hides_calls = _wire(monkeypatch, hides_env="on", jxa=JXA_OK)
    monkeypatch.setenv("OBED_OFFLINE_WRITE", "off")
    _run(tmp_path)
    assert "offlineHideSlides" not in plan
    assert hides_calls[0]["mode"] == "off"


def test_call_order_offline_hides_between_saved_closed_and_every_later_stage(monkeypatch, tmp_path):
    events = []
    _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "hidesDeferred": 2}, events=events,
          hides_info={"deleted": 2})
    _run(tmp_path)
    i = events.index("runOfflineHides")
    assert events[i - 1] == "requireSavedClosed"
    assert events.index("runJxa") < i
    after = events[i + 1:]
    assert after[0] == "snapshotPass1"
    assert after.index("snapshotPass1") < after.index("runOfflineWrite")
    for later in ("runOfflineWrite", "zorderEligible", "cardStroke", "builds"):
        assert events.index(later) > i
    assert events.count("runOfflineHides") == 1


def test_applied_accounting_adds_offline_and_fallback_deletes(monkeypatch, tmp_path):
    _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "applied": 7, "missed": 1, "hidesDeferred": 2},
          hides_info={"deleted": 2})
    said = []
    info = _run(tmp_path, said)
    assert "Applied 9, missed 1." in said
    assert info["applied"] == 9 and info["missed"] == 1
    assert info["offlineHides"] == {"deleted": 2}


def test_applied_line_prints_after_the_hides_stage(monkeypatch, tmp_path):
    events = []
    _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "hidesDeferred": 2}, events=events,
          hides_info={"deleted": 2})
    said = []
    source, template, dest = _touch_paths(tmp_path)

    def log(m):
        said.append(m)
        if m.startswith("Applied "):
            events.append("appliedLine")

    rk.remap_keynote(
        source, dest, template=template,
        wall_payload={"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]},
        template_payload={"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]},
        log=log,
    )
    assert events.index("runOfflineHides") < events.index("appliedLine") < events.index("snapshotPass1")


def test_off_mode_applied_line_unchanged(monkeypatch, tmp_path):
    _wire(monkeypatch, hides_env=None, jxa={**JXA_OK, "applied": 3822})
    said = []
    info = _run(tmp_path, said)
    assert "Applied 3822, missed 0." in said
    assert "offlineHides" not in info


def test_zero_applied_with_deferred_hides_does_not_abort(monkeypatch, tmp_path):
    _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "applied": 0, "hidesDeferred": 2},
          hides_info={"deleted": 2})
    said = []
    info = _run(tmp_path, said)
    assert info["applied"] == 2
    assert "Applied 2, missed 0." in said


def test_zero_applied_and_nothing_deferred_aborts(monkeypatch, tmp_path):
    _wire(monkeypatch, hides_env=None, jxa={**JXA_OK, "applied": 0})
    with pytest.raises(RuntimeError, match="moved 0 objects"):
        _run(tmp_path)


def test_bare_jxa_dict_without_hidesdeferred_is_tolerated(monkeypatch, tmp_path):
    _wire(monkeypatch, hides_env=None, jxa={"applied": 1, "missed": 0, "saved": True, "closed": True})
    _run(tmp_path)


def test_deferred_count_mismatch_refuses_before_any_deck_stage(monkeypatch, tmp_path):
    """A pass 1 that did not defer exactly the planned hides (e.g. a stale JS) must not reach
    a positional delete: the hides may already be gone."""
    events = []
    _wire(monkeypatch, hides_env="on", jxa={**JXA_OK, "hidesDeferred": 0}, events=events)
    with pytest.raises(RuntimeError, match="deferred 0 hide"):
        _run(tmp_path)
    assert "runOfflineHides" not in events and "runOfflineWrite" not in events
