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


def _item(kind, ki, iwa_id="auto", **extra):
    item = {"kind": kind, "kindIndex": ki, **extra}
    if iwa_id is not None:
        item["iwaId"] = f"{kind}{ki}" if iwa_id == "auto" else iwa_id
    return item


SLIDE1_ITEMS = [_item("image", 0), _item("image", 1), _item("text", 0)]

WALL = {"slides": [
    {"number": 1, "items": SLIDE1_ITEMS},
    {"number": 2, "items": [_item("shape", 0)], "builds": [{"kind": "shape", "kindIndex": 0}]},
    {"number": 3, "items": [_item("text", 0), _item("group", 0)]},
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


def test_eligibility_requires_a_source_id_on_every_hide():
    """Decision 7: the writer proves each hide by its source archive id, so a hide whose
    payload item has no `iwaId` (JXA payload, old cache) keeps its slide on the Keynote delete."""
    t = [_hide(1, "image", 0), _hide(1, "image", 1), _hide(3, "text", 0)]
    wall = {"slides": [
        {"number": 1, "items": [_item("image", 0), _item("image", 1, iwa_id=None), _item("text", 0)]},
        {"number": 3, "items": [_item("text", 0), _item("group", 0, iwa_id=None)]},
    ]}
    assert offline_write.offline_hide_slides(t, wall, None) == {3}


def test_eligibility_id_less_payload_makes_no_slide_eligible():
    jxa_wall = {"slides": [
        {"number": n, "items": [{k: v for k, v in it.items() if k != "iwaId"} for it in sl["items"]]}
        for n, sl in ((1, WALL["slides"][0]), (3, WALL["slides"][2]))
    ]}
    t = [_hide(1, "image", 0), _hide(3, "group", 0)]
    assert offline_write.offline_hide_slides(t, jxa_wall, None) == set()
    assert offline_write.offline_hide_slides(t, WALL, None) == {1, 3}


def test_eligibility_slides_with_hides_only():
    t = [_hide(1, "image", 0), _move(1, "text", 0), _move(3, "text", 0)]
    assert offline_write.offline_hide_slides(t, WALL, None) == {1}


def test_eligibility_excludes_slide_whose_build_targets_a_hide():
    t = [_hide(1, "image", 1), _hide(2, "shape", 0)]
    assert offline_write.offline_hide_slides(t, WALL, None) == {1}


def test_eligibility_build_on_a_non_hide_keeps_the_slide():
    wall = {"slides": [{"number": 2, "items": [_item("shape", 0)],
                        "builds": [{"kind": "shape", "kindIndex": 3}]}]}
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
            _item("text", 0), _item("text", 1), _item("shape", 0),
            _item("shape", 1, duplicateOf={"kind": "text", "kindIndex": 1}),
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


def test_fallback_script_binds_unique_canonical_path_match_before_any_delete(tmp_path):
    """Astra H #6 / r2 #4: bind the UNIQUE open document whose `file ... as alias` path
    canonicalises to realpath(dest), before any mutation; no name-prefix match, no
    `document 1`, no closing of unrelated same-name documents."""
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    dest = tmp_path / "link" / "sub" / ".." / "out.key"
    script = offline_write._hide_fallback_script(dest, {3: "      tell slide 3\n      end tell"})
    target = str((real / "out.key").resolve())
    assert "/link/" not in script
    assert f'open (POSIX file "{target}")' in script
    assert "POSIX path of ((file of d) as alias)" in script
    assert "if my obedIsTarget(p, target) then" in script
    bind = script.index(f'set matches to my obedMatches("{target}")')
    assert bind < script.index("if (count of matches) is not 1 then") < script.index("tell slide 3")
    assert "starts with" not in script and "start with" not in script
    assert "whose name" not in script
    assert "document 1" not in script


def test_fallback_script_closes_nothing_on_binding_failure(tmp_path):
    """Astra r3 #3: zero or several matches abort without closing anything; only the
    document bound exactly is ever closed."""
    script = offline_write._hide_fallback_script(tmp_path / "out.key", {3: "      tell slide 3\n      end tell"})
    lines = [ln.strip() for ln in script.splitlines()]
    check = lines.index("if (count of matches) is not 1 then")
    assert lines[check + 1].startswith('error "hides fallback bound " & (count of matches)')
    assert lines[check + 2] == "end if"
    assert "contents of m" not in script
    closes = [ln for ln in lines if ln.startswith("close ")]
    assert closes == ["close theDoc saving no", "close theDoc saving yes"]
    assert script.index("set theDoc to item 1 of matches") < script.index("close theDoc saving no")


def test_fallback_script_saves_and_confirms_close_by_the_same_identity(tmp_path):
    """Astra H #4 / r2 #4: the save and the close are not swallowed; after closing, the same
    canonical-path scan must find no open document; the success token comes last. A delete
    error closes WITHOUT saving and re-raises."""
    dest = tmp_path / "out.key"
    script = offline_write._hide_fallback_script(dest, {3: "      tell slide 3\n      end tell"})
    target = str(dest.resolve())
    lines = [ln.strip() for ln in script.splitlines()]
    save = lines.index("save theDoc")
    close = lines.index("close theDoc saving yes")
    assert lines[close - 1] == "end try"
    assert lines[close + 1] == (
        f'if (count of (my obedMatches("{target}"))) is not 0 then '
        'error "hides fallback: document still open after close"'
    )
    assert save < close
    assert lines.index("close theDoc saving no") > save
    assert lines.index(f'return "{offline_write.HIDE_FALLBACK_OK}"') > close


def _same(p, t):
    """Run the shell step exactly as `obedIsTarget` does; True iff it would bind."""
    import subprocess

    return subprocess.run(["sh", "-c", f"p='{p}'; t='{t}'; " + offline_write._SAME_PATH_SH],
                          capture_output=True, text=True).returncode == 0


def test_same_path_accepts_symlink_and_alias_spellings(tmp_path):
    """The alias path Keynote reports must match `os.path.realpath(dest)` through symlinked
    directories, `/tmp` vs `/private/tmp`, and a package's trailing slash."""
    import os

    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    (real / "out.key").write_bytes(b"x")
    (real / "pkg.key").mkdir()
    want = os.path.realpath(real / "out.key")
    assert _same(str(tmp_path / "link" / "out.key"), want)
    assert _same(str(real / "out.key"), want)
    assert _same(str(tmp_path / "link" / "pkg.key") + "/", os.path.realpath(real / "pkg.key"))
    if os.path.realpath("/tmp") == "/private/tmp":
        assert _same("/tmp/obed-hides-canon.key", "/private/tmp/obed-hides-canon.key")


def test_same_path_is_byte_exact(tmp_path):
    """Astra r3 #3: a differently cased path (same file on a case-insensitive volume, or an
    unrelated document) never matches; neither does a missing directory or a sibling."""
    import os

    real = tmp_path / "real"
    real.mkdir()
    (real / "out.key").write_bytes(b"x")
    want = os.path.realpath(real / "out.key")
    assert not _same(str(real / "OUT.key"), want)
    assert not _same(str(real / "Out.key"), want)
    assert not _same(str(real / "out.key.bak"), want)
    assert not _same(str(tmp_path / "missing-dir" / "out.key"), want)
    assert not _same("", want)


def test_obed_is_target_handler_semantics_under_osascript(tmp_path):
    """Run the real `obedIsTarget` handler through osascript with NO `tell application`
    (pure string/shell work): exact match binds; a case variant does not."""
    import os
    import shutil
    import subprocess

    if shutil.which("osascript") is None:
        pytest.skip("osascript unavailable")
    handler = offline_write._same_path_handler()
    assert "tell application" not in handler
    real = tmp_path / "real"
    real.mkdir()
    (real / "out.key").write_bytes(b"x")
    want = os.path.realpath(real / "out.key")

    def run(p):
        esc = offline_write._as_escape
        script = handler + f'\nreturn my obedIsTarget("{esc(p)}", "{esc(want)}")'
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    assert run(str(real / "out.key")) == "true"
    assert run(str(real / "OUT.key")) == "false"
    assert run("") == "false"


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
    assert "group_text_by_slide" not in seen
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
    assert err.value.needs_fresh_output is False
    assert err.value.detail == str(err.value)


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
    assert err.value.needs_fresh_output is True
    assert "fresh --out" in err.value.detail and "never replay" in err.value.detail
    assert "OBED_HIDE_MISSED slide=3" in err.value.detail


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
    assert err.value.needs_fresh_output is True
    assert "WITHOUT saving" in err.value.detail


def test_fallback_timeout_aborts(monkeypatch, deck):
    """Astra H #4: a timeout or runner failure aborts, and exactly one session was attempted."""
    _install_writer(monkeypatch, lambda d, h, **kw: _HidesResult({1: _proven_refusal("x"),
                                                                  3: _proven_refusal("y")}))
    fb = _record_fallback(monkeypatch, raises=TimeoutError("osascript timed out"))
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert err.value.reason == "hide fallback session did not finish"
    assert err.value.needs_fresh_output is True
    assert "osascript timed out" in err.value.detail and "fresh --out" in err.value.detail
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
    assert err.value.needs_fresh_output is False
    assert "free space" in err.value.detail
    assert "Rerun with OBED_OFFLINE_HIDES=off" in str(err.value)


def test_hides_write_failed_aborts_with_shared_message(monkeypatch, deck):
    """A read-back or verify failure after the write is an `OfflineHidesAborted`, so the CLI
    and the dashboard share one message and the dashboard turns hides off; the rerun copies
    the source afresh, so no fresh-output flag is set."""
    def writer(d, h, **kw):
        raise _HidesWriteFailed("hides read-back slide 1: lists != expected")

    _install_writer(monkeypatch, writer)
    fb = _record_fallback(monkeypatch)
    with pytest.raises(offline_write.OfflineHidesAborted) as err:
        offline_write.run_offline_hides(deck, "on", {1, 3}, TRANSFORMS, WALL, lambda m: None)
    assert fb == []
    assert err.value.reason == "the offline delete failed after writing"
    assert err.value.needs_fresh_output is False
    assert "lists != expected" in err.value.detail
    assert "Rerun with OBED_OFFLINE_HIDES=off" in err.value.detail


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
                    "slides": [{"number": 1, "items": SLIDE1_ITEMS}]}
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
        wall_payload={"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": SLIDE1_ITEMS}]},
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
    assert err.value.needs_fresh_output is False
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


def test_off_mode_applied_line_keeps_its_original_position(monkeypatch, tmp_path):
    """Default-off output is unchanged: `Applied …` prints before the pass-1 saved/closed
    check and the WARNING remap lines, exactly as before offline hides existed."""
    events = []
    _wire(monkeypatch, hides_env=None, jxa={**JXA_OK, "applied": 5, "missReasons": ["slide 2 x"]},
          events=events)
    said = []

    def log(m):
        said.append(m)
        if m.startswith("Applied "):
            events.append("appliedLine")

    source, template, dest = _touch_paths(tmp_path)
    rk.remap_keynote(
        source, dest, template=template,
        wall_payload={"slideWidth": 7680, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]},
        template_payload={"slideWidth": 1920, "slideHeight": 1080, "slides": [{"number": 1, "items": []}]},
        log=log,
    )
    assert said.count("Applied 5, missed 0.") == 1
    assert said.index("Applied 5, missed 0.") < said.index("WARNING remap: slide 2 x")
    assert events.index("appliedLine") < events.index("requireSavedClosed")
