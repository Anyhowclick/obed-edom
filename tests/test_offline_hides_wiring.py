"""Stream D of `.agents/plans/pass1_hides_offline.plan.md`: the `OBED_OFFLINE_HIDES` flag,
pure eligibility, `run_offline_hides` orchestration + AppleScript delete fallback, and the
`remap_keynote` wiring (plan field, abort, Applied accounting, call order).

Keynote-free: `iwa_hides.patch_deck_hides` (Stream B) is replaced by a stub module in
`sys.modules`, and every osascript call goes through a stub.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

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


class _HidesWriteFailed(Exception):
    pass


def _install_writer(monkeypatch, fn):
    """Stand in for Stream B's module; `from obed_edom.iwa_hides import ...` resolves here."""
    mod = types.ModuleType("obed_edom.iwa_hides")
    mod.patch_deck_hides = fn
    mod.HidesWriteFailed = _HidesWriteFailed
    monkeypatch.setitem(sys.modules, "obed_edom.iwa_hides", mod)


def _record_fallback(monkeypatch, *, returncode=0, stdout=None, stderr="", raises=None):
    """Replace osascript for the hide-fallback session; records each script it would run."""
    from obed_edom.osascript_runner import OsaResult

    calls = []

    def fake(script, *, launch=False, timeout=None, dump_on_failure=None, is_cancelled=None):
        calls.append({"script": script, "dump": dump_on_failure})
        if raises is not None:
            raise raises
        out = offline_write.HIDE_FALLBACK_OK if stdout is None else stdout
        return OsaResult(argv=["osascript"], returncode=returncode, stdout=out, stderr=stderr,
                         elapsed=0.0, dump=dump_on_failure if returncode else None)

    monkeypatch.setattr(offline_write, "run_applescript", fake)
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


def test_eligibility_excludes_dual_membership_hide_targets():
    """Astra H #3: a custom-path text box sits in shapes AND textItems (the shape copy carries
    `duplicateOf`); deleting it shifts both collections, so its slide keeps the Keynote delete.
    Either face of the dual excludes the slide; an unrelated shape does not."""
    wall = {"slides": [
        {"number": 5, "items": [
            {"kind": "text", "kindIndex": 0}, {"kind": "text", "kindIndex": 1},
            {"kind": "shape", "kindIndex": 0},
            {"kind": "shape", "kindIndex": 1, "duplicateOf": {"kind": "text", "kindIndex": 1}},
        ]},
    ]}
    assert offline_write.offline_hide_slides([_hide(5, "text", 1)], wall, None) == set()
    assert offline_write.offline_hide_slides([_hide(5, "shape", 1)], wall, None) == set()
    assert offline_write.offline_hide_slides([_hide(5, "text", 0)], wall, None) == {5}
    assert offline_write.offline_hide_slides([_hide(5, "shape", 0)], wall, None) == {5}


# --- fallback session -------------------------------------------------------------------


def test_hide_delete_body_follows_deletehides_order_and_as_index():
    """deleteHides order within a slide: kind ascending, kindIndex descending; AppleScript
    index = kindIndex + 1."""
    body = offline_write._hide_delete_body(
        [_hide(4, "text", 0), _hide(4, "image", 2), _hide(4, "text", 5), _hide(4, "image", 7)], 4,
    )
    deletes = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("delete ")]
    assert deletes == ["delete image 8", "delete image 3", "delete text item 6", "delete text item 1"]
    assert body.splitlines()[0].strip() == "tell slide 4"


def test_hide_delete_body_stops_at_first_error_without_opacity():
    """Astra H #5: the first delete error raises out of the session (with the marker);
    nothing is retried through a positional address."""
    body = offline_write._hide_delete_body([_hide(4, "image", 2), _hide(4, "image", 7)], 4)
    assert "opacity" not in body
    assert "log " not in body
    assert body.count('error "OBED_HIDE_MISSED slide=4 kind=image kindIndex=') == 2
    assert body.index("delete image 8") < body.index("kindIndex=7") < body.index("delete image 3")


def test_fallback_script_binds_by_exact_resolved_path_before_any_delete(tmp_path):
    """Astra H #6: verify `file of theDoc` against the exact resolved path before mutating;
    no name-prefix match, no closing of other same-name documents."""
    dest = tmp_path / "sub" / ".." / "out.key"
    script = offline_write._hide_fallback_script(dest, {3: "      tell slide 3\n      end tell"})
    resolved = str(dest.resolve())
    assert f'set theDoc to open (POSIX file "{resolved}")' in script
    assert f'if docPath is not "{resolved}" then error' in script
    assert script.index(f'if docPath is not "{resolved}"') < script.index("tell slide 3")
    assert "starts with" not in script and "start with" not in script
    assert "every document whose name" not in script
    assert "document 1" not in script


def test_fallback_script_saves_and_confirms_close(tmp_path):
    """Astra H #4: the save and the close are not swallowed; after closing, no document at
    the exact path may remain open; the success token is returned only at the end.
    A delete error closes WITHOUT saving and re-raises."""
    dest = tmp_path / "out.key"
    script = offline_write._hide_fallback_script(dest, {3: "      tell slide 3\n      end tell"})
    lines = [ln.strip() for ln in script.splitlines()]
    save = lines.index("save theDoc")
    close = lines.index("close theDoc saving yes")
    assert lines[close - 1] == "end try"
    assert lines[close + 1] != "end try"
    assert save < close
    assert lines.index("close theDoc saving no") > save
    assert "document still open after close" in script
    assert lines.index(f'return "{offline_write.HIDE_FALLBACK_OK}"') > close


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
    assert fb[0]["dump"] == deck.with_suffix(".hides-fallback.applescript")
    script = fb[0]["script"]
    assert "tell slide 3" in script and "tell slide 1" not in script
    assert script.index("delete group 1") < script.index("delete text item 1")
    assert info["offlineDeleted"] == 2 and info["fallbackDeleted"] == 2
    assert info["deleted"] == 4
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
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []
    assert err.value.reason == "slide(s) [3] refused before the saved order was proven"
    assert "Rerun with OBED_OFFLINE_HIDES=off" in str(err.value)


def test_hide_missed_marker_is_fatal(monkeypatch, deck):
    """Codex r1 #3 / Astra H #5: a failed delete leaves the drawable in its kind collection,
    so `source - hides` no longer holds; the stage aborts rather than counting a miss."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult(
        {1: _SlideHides(2), 3: _proven_refusal()}))
    _record_fallback(monkeypatch, returncode=1, stdout="",
                     stderr="execution error: OBED_HIDE_MISSED slide=3 kind=text kindIndex=0: nope (-2700)")
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert err.value.reason == "a hide delete failed"
    assert "fresh --out" in str(err.value) and "never replay" in str(err.value)


@pytest.mark.parametrize("returncode,stdout,stderr", [
    (1, "", "execution error: hides fallback bound the wrong document: /x/y.key"),
    (1, "", "execution error: hides fallback: document still open after close"),
    (1, "", "execution error: Keynote got an error: The document could not be saved."),
    (0, "", ""),
    (0, "something else", ""),
])
def test_fallback_session_without_confirmed_success_aborts(monkeypatch, deck, returncode, stdout, stderr):
    """Astra H #4/#6: a wrong-document bind, a failed save, an unconfirmed close, or a zero
    exit without the success token all abort."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _proven_refusal("x"),
                                                                  3: _SlideHides(2)}))
    _record_fallback(monkeypatch, returncode=returncode, stdout=stdout, stderr=stderr)
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert err.value.reason == "hide fallback session failed"


def test_fallback_timeout_aborts(monkeypatch, deck):
    """Astra H #4: a timeout or runner failure aborts, and exactly one session was attempted."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _proven_refusal("x"),
                                                                  3: _proven_refusal("y")}))
    fb = _record_fallback(monkeypatch, raises=TimeoutError("osascript timed out"))
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert err.value.reason == "hide fallback session did not finish"
    assert len(fb) == 1


def test_fallback_is_one_session_for_every_refused_slide(monkeypatch, deck):
    """Astra H #5: no chunking, so nothing runs after a failed session."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _proven_refusal("x"),
                                                                  3: _proven_refusal("y")}))
    fb = _record_fallback(monkeypatch)
    offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert len(fb) == 1
    assert "tell slide 1" in fb[0]["script"] and "tell slide 3" in fb[0]["script"]


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


def test_whole_deck_refusal_aborts_without_fallback(monkeypatch, deck):
    """Owner decision (reverses r1): `OfflineWriteRefused` proves nothing was written, not that
    the saved order matches the source (Keynote's save reorders same-kind groups), so it
    aborts instead of deleting by position."""
    iwa_write = pytest.importorskip("obed_edom.iwa_write")

    def writer(d, h, **kw):
        raise iwa_write.OfflineWriteRefused("free space below deck size * 2.1")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []
    assert err.value.reason == "the IWA writer refused the deck before writing"
    assert "free space" in str(err.value)
    assert "Rerun with OBED_OFFLINE_HIDES=off" in str(err.value)


@pytest.mark.parametrize("exc", [
    RuntimeError("unexpected"),
    KeyError("bug before writing"),
    ValueError("slide numbers are 1-based"),
])
def test_any_other_writer_exception_aborts_without_fallback(monkeypatch, deck, exc):
    """Codex r1 #7: only `OfflineWriteRefused` proves nothing was written; anything else
    leaves the deck's state unknown -- not an `OfflineHidesAborted` (a rerun needs a fresh
    --out, not just the flag)."""
    def writer(d, h, **kw):
        raise exc

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    with pytest.raises(RuntimeError, match="fresh --out") as err:
        offline_write.run_offline_hides(deck, "verify", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert not isinstance(err.value, offline_write.OfflineHidesAborted)
    assert fb == []


def test_hides_write_failed_propagates_distinct_with_fresh_out(monkeypatch, deck):
    def writer(d, h, **kw):
        raise _HidesWriteFailed("hides read-back slide 1: lists != expected")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    with pytest.raises(_HidesWriteFailed, match="lists != expected.*fresh --out"):
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []


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
    with pytest.raises(iwa_write.OfflineWriteCorrupted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, said.append)
    assert not isinstance(err.value, offline_write.OfflineHidesAborted)
    assert fb == []
    assert any("OFFLINE-HIDES CORRUPTED" in m and "RECOVERY" in m and "fresh --out" in m for m in said)


def test_map_readback_is_diagnostic_only():
    """Astra H #7: `mapReadback` is only ever printed, never checked."""
    import inspect as _inspect

    src = _inspect.getsource(rk.remap_keynote)
    uses = [ln.strip() for ln in src.splitlines() if "mapReadback" in ln]
    assert uses == [
        'if jxa.get("mapReadback") and map_slide not in offline_slides:',
        "say(f\"Map object after apply: {jxa.get('mapReadback')}\")",
    ]


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


def _run(tmp_path, said=None, **kw):
    source, template, dest = _touch_paths(tmp_path)
    wall_payload = {"slideWidth": 7680, "slideHeight": 1080,
                    "slides": [{"number": 1, "items": [{"kind": "image"}, {"kind": "image"}, {"kind": "text"}]}]}
    template_payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]}
    return rk.remap_keynote(
        source, dest, template=template, wall_payload=wall_payload,
        template_payload=template_payload, log=(said.append if said is not None else lambda m: None),
        **kw,
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
    with pytest.raises(offline_write.OfflineHidesAborted, match="deferred 0, expected 2") as err:
        _run(tmp_path)
    assert err.value.reason == "pass 1 deferred a different number of hides than planned"
    assert "runOfflineHides" not in events and "runOfflineWrite" not in events


def test_offline_hides_argument_overrides_the_env(monkeypatch, tmp_path):
    plan, hides_calls = _wire(monkeypatch, hides_env=None, jxa={**JXA_OK, "hidesDeferred": 2},
                              hides_info={"deleted": 2})
    _run(tmp_path, offline_hides="verify")
    assert plan["offlineHideSlides"] == [1]
    assert hides_calls == [{"mode": "verify", "slides": {1}}]


def test_offline_hides_argument_off_overrides_env_on(monkeypatch, tmp_path):
    plan, hides_calls = _wire(monkeypatch, hides_env="on", jxa=JXA_OK)
    _run(tmp_path, offline_hides="off")
    assert "offlineHideSlides" not in plan
    assert hides_calls[0]["mode"] == "off"


def test_remap_and_inspect_threads_offline_hides(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(rk, "remap_keynote", lambda *a, **k: seen.update(k) or {"exported": True})
    source, template, dest = _touch_paths(tmp_path)
    rk.remap_and_inspect(source, dest, template=template, validate=False, offline_hides="on")
    assert seen["offline_hides"] == "on"
