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
