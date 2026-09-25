"""P2 red-control arms: `--core-variant NAME` and `--strip ACTION[@atScene]`
(continuity generalisation plan S1, WS-H). The scorers keep reading the reference
plan (`build_continuity_plan(bridge34)`); only the injected plan / core change, and
the report header names both shas.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from obed_edom import p2_verdict as v
from obed_edom.live_continuity_js import PRESERVE_CORE_JS, js_sha256
from obed_edom.live_gl_replay_js import GL_REPLAY_JS

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from continuity_core_variants import variant_core, variant_sha  # noqa: E402
from test_p2_adversarial_driver import p2 as drv  # noqa: E402
from test_p2_adversarial_gl_replay import CANVAS, _boot_check, _fake_player  # noqa: E402


def _arm(monkeypatch, *argv: str) -> tuple[dict, str, dict]:
    monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", *argv])
    return drv._injection_arm(v.build_continuity_plan(True))


def _sha(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj).encode()).hexdigest()


def test_no_arm_injects_the_reference_plan_and_todays_core(monkeypatch):
    reference = v.build_continuity_plan(True)
    injected, core, arm = _arm(monkeypatch)
    assert injected == reference
    assert core is PRESERVE_CORE_JS
    assert arm["coreVariant"] is None and arm["strip"] is None
    assert arm["coreSha256"] == js_sha256()
    assert arm["injectedPlanSha256"] == arm["referencePlanSha256"] == _sha(reference)


@pytest.mark.parametrize("name", ["stash-any", "wrong-instance", "fifo-reuse"])
def test_core_variant_injects_the_variant_and_reports_its_sha(monkeypatch, name):
    injected, core, arm = _arm(monkeypatch, "--core-variant", name)
    assert core == variant_core(name)
    assert arm["coreVariant"] == name
    assert arm["coreSha256"] == variant_sha(name)
    assert injected == v.build_continuity_plan(True)


def test_every_variant_reports_its_own_sha_never_the_cores(monkeypatch):
    shas = [_arm(monkeypatch, f"--core-variant={name}")[2]["coreSha256"] for name in ("stash-any", "wrong-instance", "fifo-reuse")]
    assert js_sha256() not in shas
    assert len(set(shas)) == 3


@pytest.mark.parametrize("strip, kept", [
    ("bridge@8", ["glReplay", "restart"]),
    ("glReplay@2", ["restart", "bridge"]),
    ("restart@6", ["glReplay", "bridge"]),
    ("bridge", ["glReplay", "restart"]),
])
def test_strip_removes_exactly_one_injected_entry_and_leaves_the_reference(monkeypatch, strip, kept):
    reference = v.build_continuity_plan(True)
    injected, core, arm = _arm(monkeypatch, "--strip", strip)
    assert [b["action"] for b in injected["boundaries"]] == kept
    assert v.build_continuity_plan(True) == reference
    assert core is PRESERVE_CORE_JS
    assert arm["strip"] == strip
    assert arm["injectedPlanSha256"] == _sha(injected) != arm["referencePlanSha256"]
    assert arm["injectedPlan"] == injected


def test_strip_bridge_injects_what_disable_bridge34_injects(monkeypatch):
    injected, _, _ = _arm(monkeypatch, "--strip", "bridge@8")
    assert injected == v.build_continuity_plan(False)


@pytest.mark.parametrize("argv, match", [
    (("--strip", "retire@2"), "no retire@2 boundary"),
    (("--strip", "bridge@7"), "no bridge@7 boundary"),
    (("--strip", "bridge@x"), "invalid strip"),
    (("--core-variant", "nope"), "unknown core variant"),
])
def test_an_arm_that_cannot_apply_refuses_loudly(monkeypatch, argv, match):
    with pytest.raises(SystemExit, match=match):
        _arm(monkeypatch, *argv)


def test_variant_core_replaces_the_injected_preserve_script(tmp_path):
    player = _fake_player(tmp_path, "variant")
    core = variant_core("stash-any")
    preserve, _, gl = drv._inject_player(player, v.build_continuity_plan(True), gl_auto=False, canvas=CANVAS, core=core)
    html = (player / "index.html").read_text(encoding="utf-8")
    assert gl is None and preserve["injected"] is True
    assert html.count('data-obed-p2-preserve="1"') == 1
    body = html.split('<script data-obed-p2-preserve="1">', 1)[1].split("</script>", 1)[0]
    assert body == core != PRESERVE_CORE_JS


def test_stripped_glreplay_under_auto_still_ships_the_module(tmp_path):
    """The GL body is plan-independent; the stripped plan is what the page reads, so
    the module finds no entry and declines to install."""
    player = _fake_player(tmp_path, "strip-gl")
    reference = v.build_continuity_plan(True)
    stripped = {**reference, "boundaries": reference["boundaries"][1:]}
    _, plan_inject, gl = drv._inject_player(
        player, stripped, gl_auto=True, canvas=CANVAS, gl_plan=reference
    )
    html = (player / "index.html").read_text(encoding="utf-8")
    assert gl["servedOrder"] == drv.GL_SERVED_ORDER
    gl_tag = html.split('<script data-obed-p2-gl-replay="1">', 1)[1].split("</script>", 1)[0]
    assert gl_tag.replace("<\\/", "</") == GL_REPLAY_JS
    assert f"window.__OBED_CONTINUITY__ = {json.dumps(stripped)};" in html
    with pytest.raises(SystemExit, match="no usable glReplay entry"):
        drv._inject_player(_fake_player(tmp_path, "no-gl-plan"), stripped, gl_auto=True, canvas=CANVAS)


def test_boot_check_without_the_module_requires_it_absent():
    absent = _boot_check(glVersion=None, glState=None)
    assert drv._gl_boot_ok(absent, expect_module=False) is True
    assert drv._gl_boot_ok(absent) is False
    assert drv._gl_boot_ok(_boot_check(), expect_module=False) is False
    assert drv._gl_boot_ok(_boot_check(glVersion=None, glState="IDLE"), expect_module=False) is False
    missing_key = _boot_check(glState=None)
    del missing_key["glVersion"]
    assert drv._gl_boot_ok(missing_key, expect_module=False) is False
    for over in ({"webgl": False}, {"obedLive": False}, {"info": None}, {"order": ["plan", "core", "main"]}):
        assert drv._gl_boot_ok(_boot_check(glVersion=None, glState=None, **over), expect_module=False) is False


@pytest.mark.parametrize("argv, bridged", [
    ((), True),
    (("--strip", "bridge@8"), False),
    (("--strip", "restart@6"), True),
    (("--core-variant", "stash-any"), True),
])
def test_bridge_presence_is_read_from_the_injected_plan(monkeypatch, argv, bridged):
    """`--strip bridge@8` must skip the freeze bracket exactly as `--disable-bridge34` does."""
    injected, _, _ = _arm(monkeypatch, *argv)
    assert drv._bridge_injected(injected) is bridged
    assert drv._bridge_injected(v.build_continuity_plan(False)) is False


def test_freeze_bracket_skips_on_the_injected_bridge_not_the_flag(monkeypatch, tmp_path):
    import asyncio

    monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", "--strip", "bridge@8"])
    skipped = asyncio.run(drv._run_freeze_bracket(tmp_path, tmp_path, {}, "fast", bridge34=False))
    assert skipped["verdict"] == "skipped" and skipped["reason"] == "bridge disabled"
    assert drv._freeze_control_blocks_success(skipped["verdict"], True) is False


# --------------------------------------------------------------------------- #
# `--skip-freeze-bracket` (owner decision 8b, 2026-10-09, "option 2"): the freeze
# bracket runs once per paint path -- `--wait-profile fast` (DOM) and
# `--gl-replay auto` (WebGL) -- and is skipped by flag everywhere else. A positive
# fast/gl-auto arm must never be able to skip it silently.
# --------------------------------------------------------------------------- #
def _skip(monkeypatch, *argv: str) -> bool:
    monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", *argv])
    return drv._skip_freeze_bracket()


@pytest.mark.parametrize("argv", [
    (),
    ("--wait-profile", "fast"),
    ("--wait-profile=fast",),
    ("--gl-replay", "auto"),
    ("--wait-profile", "fast", "--gl-replay", "auto"),
    ("--wait-profile", "fast", "--gl-replay=auto", "--mm-opacity", "off"),
    ("--wait-profile", "fast", "--strip", ""),
    ("--wait-profile", "fast", "--core-variant="),
    ("--wait-profile", "slow", "--gl-replay", "auto"),
    ("--wait-profile=slow", "--gl-replay=auto", "--mm-opacity", "off"),
    ("--gl-replay", "auto", "--wait-profile", "slow", "--strip", ""),
])
def test_skip_freeze_bracket_is_refused_on_the_positive_arms(monkeypatch, argv):
    """The fast and gl-auto positive arms are the bracket's two paint paths: the
    flag is refused before any work, never accepted and quietly obeyed. An empty
    `--strip`/`--core-variant` value is no arm at all, so it is refused too. A
    positive gl-auto arm is refused whatever its wait profile (Codex round 2)."""
    with pytest.raises(SystemExit, match=r"--skip-freeze-bracket (on a --gl-replay auto arm )?needs"):
        _skip(monkeypatch, *argv, "--skip-freeze-bracket")


def test_slow_gl_auto_skip_is_refused_regression(monkeypatch):
    """Codex round-2 MAJOR: `slow` alone used to authorise the skip, so
    `--wait-profile slow --gl-replay auto --skip-freeze-bracket` ran a positive
    WebGL arm with no bracket and a non-blocking skip. Positive control: the same
    flags without `--gl-replay auto` (the DOM slow arm) are still accepted."""
    with pytest.raises(SystemExit, match="a positive gl-auto arm always runs the WebGL freeze bracket"):
        _skip(monkeypatch, "--wait-profile", "slow", "--gl-replay", "auto", "--skip-freeze-bracket")
    assert _skip(monkeypatch, "--wait-profile", "slow", "--skip-freeze-bracket") is True
    assert _skip(monkeypatch, "--wait-profile", "slow", "--gl-replay", "auto", "--strip", "glReplay@2",
                 "--skip-freeze-bracket") is True


@pytest.mark.parametrize("argv", [
    ("--wait-profile", "slow"),
    ("--wait-profile=slow",),
    ("--wait-profile", "fast", "--core-variant", "stash-any"),
    ("--wait-profile", "fast", "--strip", "bridge@8"),
    ("--wait-profile", "fast", "--strip=restart@6"),
    ("--wait-profile", "fast", "--strip", "glReplay@2"),
    ("--wait-profile", "fast", "--gl-replay", "auto", "--strip", "glReplay@2"),
    ("--wait-profile", "fast", "--disable-bridge34"),
    ("--wait-profile", "slow", "--gl-replay", "auto", "--core-variant", "stash-any"),
    ("--wait-profile", "slow", "--gl-replay", "off"),
])
def test_skip_freeze_bracket_is_accepted_on_slow_and_red_arms(monkeypatch, argv):
    assert _skip(monkeypatch, *argv, "--skip-freeze-bracket") is True


@pytest.mark.parametrize("argv", [
    (),
    ("--wait-profile", "slow"),
    ("--wait-profile", "fast", "--strip", "bridge@8"),
    ("--gl-replay", "auto"),
])
def test_without_the_flag_the_bracket_is_never_skipped_by_flag(monkeypatch, argv):
    assert _skip(monkeypatch, *argv) is False


def test_skip_flag_skips_the_bracket_without_booting_even_with_the_bridge(monkeypatch, tmp_path):
    """With the bridge present the bracket would boot three Chromes; the flag must
    return before any of that (no server, no `freeze-bracket` dir). The server and
    Chrome factories are booby-trapped so a regression fails fast instead of
    launching a browser."""
    import asyncio

    def _no_boot(*_a, **_k):
        raise AssertionError("the skipped bracket started a server or Chrome")

    monkeypatch.setattr(drv, "ThreadingHTTPServer", _no_boot)
    monkeypatch.setattr(drv, "_chrome", _no_boot)

    skipped = asyncio.run(drv._run_freeze_bracket(tmp_path, tmp_path, {}, "slow", bridge34=True, skip=True))
    assert skipped == {
        "skipped": True, "reason": "--skip-freeze-bracket", "verdict": "skipped", "ok": False, "waitProfile": "slow",
    }
    assert not (tmp_path / "freeze-bracket").exists()
    both = asyncio.run(drv._run_freeze_bracket(tmp_path, tmp_path, {}, "fast", bridge34=False, skip=True))
    assert both["reason"] == "--skip-freeze-bracket", "the flag names the skip when both apply"


def test_flag_skip_is_non_blocking_but_a_bare_skip_with_the_bridge_still_blocks():
    """The advisor's trap: before the flag, a skipped bracket with the bridge present
    went through `_freeze_control_blocks_success("skipped", False)` and BLOCKED."""
    assert drv._freeze_control_blocks_success("skipped", False, skipped_by_flag=True) is False
    assert drv._freeze_control_blocks_success("skipped", False) is True
    for verdict in ("inconclusive", "fail", None, "weird"):
        assert drv._freeze_control_blocks_success(verdict, False, skipped_by_flag=True) is True
        assert drv._freeze_control_blocks_success(verdict, True, skipped_by_flag=True) is True
    assert drv._freeze_control_blocks_success("pass", False, skipped_by_flag=True) is False


# The regex `scripts/run_gates.sh` `expect()` classifies REPORT.md finding lines with.
_GATE_LINE = r"^- ([A-Za-z0-9]+): \*\*(True|False)\*\*(?: \(([^)]*)\))?"


def _gate_class(line: str) -> tuple[str, str, str | None]:
    import re

    m = re.match(_GATE_LINE, line)
    assert m, line
    name, val, verdict = m.groups()
    kind = "inconclusive" if verdict == "inconclusive" else ("red" if val == "False" else "green")
    return name, kind, verdict


def test_flag_skip_renders_as_skipped_by_the_flag_never_false():
    finding = {"id": "freezeControlCaughtByCounter", "pass": True, "verdict": "skipped",
               "skippedBy": "--skip-freeze-bracket", "note": "n"}
    line = drv._finding_line(finding)
    assert line == "- freezeControlCaughtByCounter: **True** (skipped by --skip-freeze-bracket) — n"
    assert _gate_class(line) == ("freezeControlCaughtByCounter", "green", "skipped by --skip-freeze-bracket")


def test_finding_line_unchanged_for_every_other_shape():
    """Byte-identical to the pre-extraction inline render for the shapes rounds produce."""
    cases = [
        ({"id": "a", "pass": True, "verdict": "pass"}, "- a: **True**"),
        ({"id": "a", "pass": False, "verdict": "fail"}, "- a: **False**"),
        ({"id": "a", "pass": False, "verdict": "inconclusive", "note": "x"}, "- a: **False** (inconclusive) — x"),
        ({"id": "a", "pass": True, "verdict": "skipped", "skippedBy": None}, "- a: **True** (skipped)"),
        ({"id": "a", "pass": False, "verdict": "skipped"}, "- a: **False** (skipped)"),
        ({"id": "a", "pass": True}, "- a: **True**"),
    ]
    for finding, want in cases:
        assert drv._finding_line(finding) == want
    assert _gate_class("- a: **False** (skipped)")[1] == "red", "a blocking skip stays red for run_gates"


def test_freeze_bracket_header_names_why_it_was_skipped():
    assert drv._freeze_bracket_header({"skipped": True, "reason": "--skip-freeze-bracket"}) == (
        "skipped (--skip-freeze-bracket)"
    )
    assert drv._freeze_bracket_header({"skipped": True, "reason": "bridge disabled"}) == "skipped (bridge disabled)"
    assert drv._freeze_bracket_header({"verdict": "pass", "ok": True}) == "run"
    assert drv._freeze_bracket_header({"verdict": "inconclusive", "ok": False}) == "run"


# Codex round 2 replaced two source-substring checks of `_run` with behavioural
# tests of the pure helpers `_run` now delegates to (`_freeze_bracket_finding`,
# `_report_lines`, `_moving_mm34_verdict`) plus `_run`'s own early refusal. The
# remaining call-site wiring (the flag reaching `_run_freeze_bracket`) is checked
# live by run_gates' `expect`: every arm's `Freeze bracket:` header line must
# match its own arguments.
def test_run_refuses_a_positive_arm_skip_before_touching_the_out_dir(monkeypatch, tmp_path):
    """`_run` parses the flag before it creates (or clears) the out dir: a refused
    skip leaves no trace. Booby-trapped so a regression cannot launch anything."""
    import asyncio

    def _no_boot(*_a, **_k):
        raise AssertionError("a refused skip reached a server or Chrome")

    monkeypatch.setattr(drv, "ThreadingHTTPServer", _no_boot)
    monkeypatch.setattr(drv, "_chrome", _no_boot)
    for i, argv in enumerate([
        ("--wait-profile", "fast"),
        ("--wait-profile", "fast", "--gl-replay", "auto"),
        ("--wait-profile", "slow", "--gl-replay", "auto"),
    ]):
        out = tmp_path / f"out{i}"
        monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", "--out-dir", str(out), *argv,
                                          "--skip-freeze-bracket"])
        with pytest.raises(SystemExit, match="--skip-freeze-bracket"):
            asyncio.run(drv._run())
        assert not out.exists(), argv


def _bracket(verdict: str | None, **extra) -> dict:
    return {"verdict": verdict, **extra}


@pytest.mark.parametrize("freeze_control, bridge_injected, skip_freeze, want_pass, want_skipped_by", [
    (_bracket("pass", ok=True), True, False, True, None),
    (_bracket("fail", ok=False), True, False, False, None),
    (_bracket("inconclusive", ok=False), True, False, False, None),
    (_bracket("skipped", skipped=True, reason="--skip-freeze-bracket"), True, True, True, "--skip-freeze-bracket"),
    (_bracket("skipped", skipped=True, reason="bridge disabled"), False, False, True, None),
    (_bracket("skipped", skipped=True, reason="bridge disabled"), True, False, False, None),
    (_bracket("fail", ok=False), True, True, False, "--skip-freeze-bracket"),
])
def test_freeze_bracket_finding(freeze_control, bridge_injected, skip_freeze, want_pass, want_skipped_by):
    """The finding `_run` appends: its pass is `_freeze_control_blocks_success`
    (owner decision 8b), its verdict the bracket's, and it names the flag skip."""
    f = drv._freeze_bracket_finding(freeze_control, bridge_injected=bridge_injected, skip_freeze=skip_freeze)
    assert f["id"] == "freezeControlCaughtByCounter"
    assert f["pass"] is want_pass
    assert f["verdict"] == freeze_control["verdict"]
    assert f["skippedBy"] == want_skipped_by
    assert f["detail"] is freeze_control


def _report(findings: list[dict], freeze_control: dict, *, success: bool, variant=None, strip=None) -> dict:
    return {
        "generated": "2026-10-09 21:00:00",
        "sourceUnchanged": True,
        "injection": {"coreVariant": variant, "coreSha256": "c" * 64, "strip": strip, "injectedPlanSha256": "p" * 64},
        "freezeControl": freeze_control,
        "success": success,
        "findings": findings,
    }


def test_report_lines_render_the_header_and_every_finding_from_the_report(tmp_path):
    """REPORT.md as run_gates' `expect` parses it: the `Core variant:`, `Strip:`,
    `Freeze bracket:` and `success:` header lines come from report.json's own
    fields, and every finding renders through `_finding_line` in order, so a skip
    by flag is green and an unmeasured 3->4 run is inconclusive, never red."""
    skipped = {"skipped": True, "reason": "--skip-freeze-bracket", "verdict": "skipped"}
    findings = [
        {"id": "continue1to2", "pass": True},
        {"id": "continueThroughMovingMagicMove3to4", "pass": False, "verdict": "inconclusive"},
        drv._freeze_bracket_finding(skipped, bridge_injected=True, skip_freeze=True),
    ]
    lines = drv._report_lines(_report(findings, skipped, success=False, strip="restart@6"), tmp_path)
    assert lines[3:8] == [
        "Source unchanged: **True**",
        f"Core variant: none · injected core sha256: {'c' * 64}",
        f"Strip: restart@6 · injected plan sha256: {'p' * 64}",
        "Freeze bracket: skipped (--skip-freeze-bracket)",
        "success: **False**",
    ]
    rendered = [line for line in lines if line.startswith("- ")]
    assert rendered == [drv._finding_line(f) for f in findings]
    assert [_gate_class(line)[1] for line in rendered] == ["green", "inconclusive", "green"]
    assert lines[-3:] == [f"Samples: `{tmp_path}`", "", "P3 still unwired."]

    ran = drv._report_lines(_report([], {"verdict": "pass", "ok": True}, success=True, variant="stash-any"), tmp_path)
    assert "Freeze bracket: run" in ran
    assert f"Core variant: stash-any · injected core sha256: {'c' * 64}" in ran
    assert "success: **True**" in ran


def test_mm34_inconclusive_finding_renders_inconclusive_and_a_measured_failure_red():
    """`_run` builds `continueThroughMovingMagicMove3to4` as
    `{"pass": verdict == "pass", "verdict": verdict}` from `_moving_mm34_verdict`:
    an unmeasured at-cut run is `**False** (inconclusive)` (blocks success, never
    red for run_gates); a measured counter failure is plain red."""
    green = {
        "moving_continuity": {"ok": True}, "moving_index_run": {"ok": True},
        "footprint_live": {"ok": True}, "advance_ok": True, "player_build_errors": [],
    }
    cases = [
        ({"ok": False, "reason": "flip window not decodable"}, False, "inconclusive"),
        ({"ok": False, "reason": "freeze run at cut", "freezeRunAtCut": 9}, True, "red"),
        ({"ok": True, "reason": None}, True, "green"),
    ]
    for at_cut, decodable, want in cases:
        verdict = v._moving_mm34_verdict(
            moving_index_run_at_cut=at_cut, flip_window_decodable=decodable, **green
        )
        finding = {"id": "continueThroughMovingMagicMove3to4", "pass": verdict == "pass", "verdict": verdict}
        assert _gate_class(drv._finding_line(finding))[1] == want
