"""Load-bearing tests for `src/obed_edom/live_gl_replay_js.py` (GL-replay G2, stream S2).

Two layers, both of which must be able to FAIL:

1. **Unconditional Python-level contract** — the version/hash pinning, the closed
   reason set of the plan's §2.7 (each reason emitted from exactly one site in the
   JS), the seam-access restriction of §2.6, the geometry constants shared with
   `p2_verdict`/`html_alpha_probe`, and `validate_gl_replay_entry`/`gl_replay_script`
   refusing every malformed shape of §2.0/§2.8.

2. **A Node sandbox** (skipped without `node`, exactly as
   `tests/test_live_continuity_js.py` does) that runs `GL_REPLAY_JS` against a
   *scripted* fake WebGL implementation: programs carrying real uniform tables,
   textures carrying last-upload metadata, and a `readPixels` computed from the
   draws executed since the last `clear` plus their uniform values, as solid
   colours with exact alpha arithmetic. There is no rasteriser: a draw covers the
   rectangle its `MVPMatrix` decodes to and nothing else.

   **What the sandbox proves:** dispatch, state ordering, the write-back/forward
   ordering, fail-closed coverage of every §2.7 reason, and the shape of the
   published handle. **What it cannot prove:** pixel fidelity, real timing, or the
   real settle frame — those belong to the S3 headless harness.

The settle frame replayed through the sandbox lives in
`tests/fixtures/gl_replay/settle_frame.json`. Its *measured* content (88 calls,
five draws at indices 17/33/50/66/83, one distinct program each, the five
`MVPMatrix` values, the `Texture→unit 1`/`Texture2→unit 0` sampler bindings,
`mixFactor` 1 on draw 17 and 0 elsewhere, rest `Opacity` 1/0/1/1/1, and the fact
that the frame re-sets `Opacity` for programs 0–3 but not for program 4) comes
from the archived `m2-s3/result.json` (`analyze`, `remeasure.perUnit`,
`remeasure.sentinelAfterFrame`, `segment`) and §0 of
`.agents/plans/keynote_live_gl_replay_opacity.plan.md`. The *argument list* of the
88 calls is not recorded anywhere and is synthesised to that measured shape, as
are the solid source colours of slots 1/2/3; see the fixture's `_provenance`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from obed_edom import html_alpha_probe, live_gl_replay_js, p2_verdict

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "gl_replay" / "settle_frame.json"
SETTLE_FRAME = json.loads(FIXTURE_PATH.read_text())

# --- the plan literal under test -------------------------------------------------------
#
# Shaped exactly like `EXPECTED_GL_REPLAY_RUNTIME_PLAN` in `tests/test_live_continuity.py`
# (the flag-on derivation of the `html-adversarial` fixture), plus the three G1b fields
# of plan §2.0 that stream S0 adds: `instanceId`, `instanceRect`, `movieSlot`.

SLOT4_OPACITY = 0.29468628764152527

GL_REPLAY_ENTRY: dict = {
    "atScene": 2,
    "action": "glReplay",
    "movieKey": "movie1",
    "fallback": "retire",
    "slotSizes": [[1920, 1080], [671, 195], [266, 236], [960, 276], [178, 157]],
    "slotRects": [
        [0.0, 0.0, 1920.0, 1080.0],
        [1071.6833801269531, 871.9523239135742, 671.0, 195.0],
        [541.858301475681, 721.0772309801108, 181.0, 161.0],
        [105.1231918334961, 790.846923828125, 960.0, 276.0],
        [788.725538103768, 672.9158876261134, 353.0, 313.0],
    ],
    "opacityOverrides": [{"slot": 4, "opacity": SLOT4_OPACITY, "texW": 178, "texH": 157}],
    "instanceId": "untitled.mov#1",
    "instanceRect": {"x": 109.35, "y": 795.04, "w": 951.54, "h": 267.62},
    "movieSlot": 3,
}

RUNTIME_PLAN: dict = {
    "movies": {
        "movie1": {
            "assetKeys": ["untitled.mov"],
            "footprint": {"x": 109, "y": 795, "w": 952, "h": 268},
        }
    },
    "boundaries": [
        copy.deepcopy(GL_REPLAY_ENTRY),
        {"atScene": 6, "action": "restart"},
    ],
}

MOVIE_SLOT = GL_REPLAY_ENTRY["movieSlot"]
DESTINATION_RECT = {
    "x": GL_REPLAY_ENTRY["slotRects"][MOVIE_SLOT][0],
    "y": GL_REPLAY_ENTRY["slotRects"][MOVIE_SLOT][1],
    "w": GL_REPLAY_ENTRY["slotRects"][MOVIE_SLOT][2],
    "h": GL_REPLAY_ENTRY["slotRects"][MOVIE_SLOT][3],
}

# --- plan §2.7, verbatim ---------------------------------------------------------------

STAND_DOWN_REASONS = [
    "planUnreadable",
    "runtimeSeamAbsent",
    "glReplayUnavailable",
    "settleSignalAbsent",
    "sceneMismatch",
    "observerNotArmed",
    "canvasShape",
    "posterAmbiguous",
    "posterUnreadable",
    "frameNotDelimited",
    "contextLost",
    "rvfcUnavailable",
    "videoNotReady",
    "assetUnbound",
    "occlusionTooHigh",
    "unflaggedPlayerCall",
    "frameLengthChanged",
    "glError",
    "writebackFailed",
]
NORMAL_EXIT_REASON = "canvasRemoved"
MILESTONE_NOTES = ["glreplay-arm", "glreplay-live"]
OPACITY_UNPROVEN_REASONS = [
    "count",
    "uniforms",
    "mixfactor",
    "size",
    "mvp",
    "rest-opacity",
    "ablation",
    "identity",
]

# `js_sha256()` of the shipped bytes. Recompute and re-pin whenever the module's
# JS changes on purpose; a surprise here means the bytes moved without a decision.
PINNED_JS_SHA256 = "39bb40ebf54d28e612ed65961a4da23ddc266be56d865fbf7bb21a5566908610"


# =======================================================================================
# 1. Unconditional Python-level contract
# =======================================================================================


def test_gl_replay_version_is_pinned_int():
    assert live_gl_replay_js.GL_REPLAY_VERSION == 1
    assert isinstance(live_gl_replay_js.GL_REPLAY_VERSION, int)


def test_js_sha256_matches_the_shipped_bytes():
    expected = hashlib.sha256(live_gl_replay_js.GL_REPLAY_JS.encode()).hexdigest()
    assert live_gl_replay_js.js_sha256() == expected
    assert live_gl_replay_js.js_sha256() == live_gl_replay_js.js_sha256()


def test_js_sha256_matches_the_pinned_literal():
    assert live_gl_replay_js.js_sha256() == PINNED_JS_SHA256


def _js_source() -> str:
    return live_gl_replay_js.GL_REPLAY_JS


def _quoted_literals(source: str) -> list[str]:
    """Every single- or double-quoted string literal in the JS source."""
    return [
        m.group(1) or m.group(2)
        for m in re.finditer(r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\"", source)
    ]


def _emitted_reasons(source: str) -> set[str]:
    """Every reason literal the module can actually emit: the first string argument
    of an `assertOr`/`refuseInstall`/`provenOr`/`unproven`/`standDown` call site,
    plus the named constants those helpers are handed."""
    direct = set(re.findall(
        r"(?:assertOr|refuseInstall|provenOr|unproven|standDown)\s*\(\s*"
        r"(?:[A-Za-z0-9_.]+\s*,\s*)?['\"]([A-Za-z0-9_-]+)['\"]",
        source,
    ))
    named = set(re.findall(r"var\s+[A-Z][A-Z_]*\s*=\s*['\"]([A-Za-z0-9_-]+)['\"]", source))
    return direct | named


def test_stand_down_reason_set_is_closed_and_matches_the_plan():
    """Every §2.7 reason appears, and nothing outside §2.7 can be emitted as one."""
    source = _js_source()
    literals = set(_quoted_literals(source))
    for reason in STAND_DOWN_REASONS + [NORMAL_EXIT_REASON]:
        assert reason in literals, f"§2.7 reason {reason!r} is never mentioned in the JS"

    emitted = _emitted_reasons(source)
    assert emitted, "no reason-emitting call sites found — this grep would be vacuous"
    expected = set(STAND_DOWN_REASONS) | {NORMAL_EXIT_REASON} | set(OPACITY_UNPROVEN_REASONS)
    assert emitted == expected, (
        f"missing: {sorted(expected - emitted)}; outside the closed set: "
        f"{sorted(emitted - expected)}"
    )


# A reason bound to a `var NAME = '<reason>'` constant can be emitted from several
# places while the quoted literal still appears once, so counting literals would be
# blind exactly where it matters. `canvasRemoved` is the one documented exception:
# it is both returned by the LIVE `guards()` and raised by the MutationObserver.
REASONS_WITH_TWO_SITES = {
    NORMAL_EXIT_REASON: "returned by `guards()` and raised by the MutationObserver",
}


def _constant_for(source: str, reason: str) -> str | None:
    match = re.search(rf"var\s+([A-Z][A-Z_]*)\s*=\s*['\"]{re.escape(reason)}['\"]", source)
    return match.group(1) if match else None


def _emitting_sites(source: str, name: str) -> list[str]:
    """Uses of a reason constant that can reach a stand-down: every reference to it
    except its own declaration and the `=== NAME` / `!== NAME` guard comparisons
    (those only ask whether a reason is being forced, they never raise it)."""
    sites = []
    for match in re.finditer(rf"\b{name}\b", source):
        before = source[max(0, match.start() - 40) : match.start()]
        if re.search(r"var\s+$", before):
            continue
        if re.search(r"[=!]==\s*$", before):
            continue
        line = source[: match.start()].count("\n") + 1
        sites.append(f"{name}@line {line}")
    return sites


@pytest.mark.parametrize("reason", STAND_DOWN_REASONS + [NORMAL_EXIT_REASON])
def test_each_reason_is_emitted_from_exactly_one_site(reason):
    """A reason emitted from two sites cannot be told apart by the sandbox tests
    below, so the fail-closed coverage they claim would be a half-truth."""
    source = _js_source()
    expected = 2 if reason in REASONS_WITH_TWO_SITES else 1
    name = _constant_for(source, reason)
    if name is None:
        occurrences = len(re.findall(rf"['\"]{re.escape(reason)}['\"]", source))
        assert occurrences == expected, (
            f"{reason!r} appears {occurrences} times; §2.7 requires {expected}")
        return
    # Bound to a constant: the literal count is meaningless, count the uses.
    assert len(re.findall(rf"['\"]{re.escape(reason)}['\"]", source)) == 1, (
        f"{reason!r} is bound to {name} but the literal is also written elsewhere")
    sites = _emitting_sites(source, name)
    assert len(sites) == expected, (
        f"{reason!r} (via {name}) can be emitted from {len(sites)} sites, "
        f"expected {expected}: {sites}"
        + (f" — documented exception: {REASONS_WITH_TWO_SITES[reason]}"
           if reason in REASONS_WITH_TWO_SITES else "")
    )


@pytest.mark.parametrize("note", MILESTONE_NOTES + ["glreplay-standdown", "glreplay-handoff",
                                                    "glreplay-opacity-unproven"])
def test_milestone_and_note_kinds_are_present(note):
    assert f"'{note}'" in _js_source() or f'"{note}"' in _js_source()


def test_module_touches_only_the_gl_replay_seam():
    """Plan §2.6: G2 reads NOTHING else off `__OBED_P2_PRESERVE__`."""
    source = _js_source()
    accesses = re.findall(r"__OBED_P2_PRESERVE__\s*\.\s*(\w+)", source)
    assert accesses, "the module never reaches for the seam at all"
    assert set(accesses) == {"glReplay"}, f"non-seam core access: {sorted(set(accesses))}"
    # Bracket access would sidestep the grep above.
    assert not re.search(r"__OBED_P2_PRESERVE__\s*\[", source)


@pytest.mark.parametrize(
    "minified_name",
    ["renderFrameWithContext", "textureInfoFromEffect", "_renderFrame", "kTextureInfo"],
)
def test_no_minified_player_identifiers(minified_name):
    """The mapping must be structural (GLSL uniform names read back with
    `getActiveUniform`), never a `main.js` identifier that a re-export renames."""
    assert minified_name not in _js_source()


SCRIPT_PREFIX = '<script id="obed-gl-replay">'
SCRIPT_SUFFIX = "</script>\n"


def test_script_builder_wraps_the_module_in_a_script_tag():
    script = live_gl_replay_js.gl_replay_script(RUNTIME_PLAN)
    assert script.startswith(SCRIPT_PREFIX)
    assert script.endswith(SCRIPT_SUFFIX)
    assert "</script" not in script[len(SCRIPT_PREFIX) : -len(SCRIPT_SUFFIX)]


def test_script_builder_escapes_the_script_close_sequence(monkeypatch):
    """Exercised directly rather than conditionally: today's bytes contain no
    `</script`, so guarding the assertion on the shipped source made it vacuous.
    An HTML parser ends the element on `</SCRIPT` too, so the escape must not be
    case-sensitive."""
    monkeypatch.setattr(live_gl_replay_js, "GL_REPLAY_JS", "var s = '</SCRIPT>';")
    script = live_gl_replay_js.gl_replay_script(RUNTIME_PLAN)
    assert script.startswith(SCRIPT_PREFIX)
    assert script.endswith(SCRIPT_SUFFIX)
    body = script[len(SCRIPT_PREFIX) : -len(SCRIPT_SUFFIX)]
    assert "</script" not in body.lower(), body
    assert "SCRIPT" in body, "the payload was dropped rather than escaped"


def test_script_builder_embeds_the_module_bytes_once():
    script = live_gl_replay_js.gl_replay_script(RUNTIME_PLAN)
    assert script.count('<script id="obed-gl-replay">') == 1


@pytest.mark.parametrize(
    "name,constant,py_value",
    [
        ("CONTROL_PATCH_PX", "CONTROL_PATCH_PX", p2_verdict.CONTROL_PATCH_PX),
        ("CONTROL_INSET_PX", "CONTROL_INSET_PX", p2_verdict.CONTROL_INSET_PX),
        ("BAND_COLS", "BAND_COLS", html_alpha_probe.LIVE_BAND_COLS),
        ("BAND_ROWS", "BAND_ROWS", html_alpha_probe.LIVE_BAND_ROWS),
    ],
)
def test_geometry_constants_match_the_python_scorer(name, constant, py_value):
    match = re.search(rf"\b{constant}\s*=\s*(\d+)", _js_source())
    assert match, f"{constant} is not a JS literal in the module"
    assert int(match.group(1)) == py_value


def test_control_and_band_constants_have_the_expected_python_values():
    """Guards the parity test above against both sides drifting together."""
    assert (p2_verdict.CONTROL_PATCH_PX, p2_verdict.CONTROL_INSET_PX) == (40, 4)
    assert (html_alpha_probe.LIVE_BAND_COLS, html_alpha_probe.LIVE_BAND_ROWS) == (16, 8)
    assert html_alpha_probe.INPAGE_BAND_COUNT == 128


# --- validate_gl_replay_entry / gl_replay_script refusals -------------------------------


def _plan_with(entry: dict | None, *, extra_entry: dict | None = None) -> dict:
    plan = copy.deepcopy(RUNTIME_PLAN)
    boundaries = [b for b in plan["boundaries"] if b.get("action") != "glReplay"]
    if entry is not None:
        boundaries.insert(0, entry)
    if extra_entry is not None:
        boundaries.insert(1, extra_entry)
    plan["boundaries"] = boundaries
    return plan


def _mutated(**changes) -> dict:
    entry = copy.deepcopy(GL_REPLAY_ENTRY)
    entry.update(changes)
    return entry


def _override(**changes) -> dict:
    override = copy.deepcopy(GL_REPLAY_ENTRY["opacityOverrides"][0])
    override.update(changes)
    return _mutated(opacityOverrides=[override])


MALFORMED_PLANS: list[tuple[str, dict]] = [
    ("no_glreplay_entry", _plan_with(None)),
    ("two_glreplay_entries", _plan_with(copy.deepcopy(GL_REPLAY_ENTRY),
                                        extra_entry=_mutated(atScene=4))),
    ("fallback_not_retire", _plan_with(_mutated(fallback="restart"))),
    ("fallback_missing", _plan_with({k: v for k, v in GL_REPLAY_ENTRY.items()
                                     if k != "fallback"})),
    ("at_scene_not_int", _plan_with(_mutated(atScene="2"))),
    ("at_scene_bool", _plan_with(_mutated(atScene=True))),
    ("movie_key_not_in_movies", _plan_with(_mutated(movieKey="movie9"))),
    ("slot_sizes_not_pairs", _plan_with(_mutated(
        slotSizes=[[1920, 1080], [671], [266, 236], [960, 276], [178, 157]]))),
    ("slot_sizes_non_int", _plan_with(_mutated(
        slotSizes=[[1920.5, 1080], [671, 195], [266, 236], [960, 276], [178, 157]]))),
    ("slot_rects_length_mismatch", _plan_with(_mutated(
        slotRects=GL_REPLAY_ENTRY["slotRects"][:4]))),
    ("slot_rect_not_four_floats", _plan_with(_mutated(
        slotRects=[[0.0, 0.0, 1920.0]] + GL_REPLAY_ENTRY["slotRects"][1:]))),
    ("slot_rect_non_finite", _plan_with(_mutated(
        slotRects=[[0.0, 0.0, float("inf"), 1080.0]] + GL_REPLAY_ENTRY["slotRects"][1:]))),
    ("override_slot_out_of_range", _plan_with(_override(slot=5))),
    ("override_slot_negative", _plan_with(_override(slot=-1))),
    ("override_opacity_zero", _plan_with(_override(opacity=0.0))),
    ("override_opacity_one", _plan_with(_override(opacity=1.0))),
    ("override_opacity_above_one", _plan_with(_override(opacity=1.5))),
    ("override_texw_mismatch", _plan_with(_override(texW=179))),
    ("override_texh_mismatch", _plan_with(_override(texH=158))),
    ("movie_slot_out_of_range", _plan_with(_mutated(movieSlot=5))),
    ("movie_slot_negative", _plan_with(_mutated(movieSlot=-1))),
    ("movie_slot_not_int", _plan_with(_mutated(movieSlot="3"))),
    ("instance_rect_missing_key", _plan_with(_mutated(
        instanceRect={"x": 1.0, "y": 2.0, "w": 3.0}))),
    ("instance_rect_non_finite", _plan_with(_mutated(
        instanceRect={"x": float("nan"), "y": 795.04, "w": 951.54, "h": 267.62}))),
    ("instance_rect_not_a_dict", _plan_with(_mutated(instanceRect=[109.35, 795.04, 951.54, 267.62]))),
    ("instance_id_not_str", _plan_with(_mutated(instanceId=1))),
    ("instance_id_missing", _plan_with({k: v for k, v in GL_REPLAY_ENTRY.items()
                                        if k != "instanceId"})),
]


def test_valid_plan_validates_and_builds():
    """The positive control for every refusal below — without it they are vacuous."""
    entry = live_gl_replay_js.validate_gl_replay_entry(RUNTIME_PLAN)
    assert entry is not None
    assert entry["movieKey"] == "movie1"
    assert entry["movieSlot"] == MOVIE_SLOT
    assert entry["instanceId"] == "untitled.mov#1"
    assert live_gl_replay_js.gl_replay_script(RUNTIME_PLAN) != ""


@pytest.mark.parametrize("label,plan", MALFORMED_PLANS, ids=[p[0] for p in MALFORMED_PLANS])
def test_validate_refuses_every_malformed_shape(label, plan):
    assert live_gl_replay_js.validate_gl_replay_entry(plan) is None, label


@pytest.mark.parametrize("label,plan", MALFORMED_PLANS, ids=[p[0] for p in MALFORMED_PLANS])
def test_builder_returns_empty_for_every_malformed_shape(label, plan):
    assert live_gl_replay_js.gl_replay_script(plan) == "", label


@pytest.mark.parametrize("junk", [None, {}, {"boundaries": None}, {"movies": {}},
                                  {"boundaries": [], "movies": {}}, "not a plan", []])
def test_validate_refuses_junk_plans(junk):
    assert live_gl_replay_js.validate_gl_replay_entry(junk) is None
    assert live_gl_replay_js.gl_replay_script(junk) == ""


# --- the fixture itself -----------------------------------------------------------------


def test_settle_frame_fixture_matches_the_measured_shape():
    """The fixture is the sandbox's only source of frame truth; if it drifts from
    the measured facts of opacity-plan §0 every sandbox assertion below is hollow."""
    assert SETTLE_FRAME["frameLen"] == 88
    assert len(SETTLE_FRAME["calls"]) == 88
    assert SETTLE_FRAME["drawIndices"] == [17, 33, 50, 66, 83]
    assert [d["index"] for d in SETTLE_FRAME["draws"]] == [17, 33, 50, 66, 83]
    for draw in SETTLE_FRAME["draws"]:
        assert SETTLE_FRAME["calls"][draw["index"]]["m"] == draw["method"]
    assert SETTLE_FRAME["calls"][0]["m"] == "clearColor"
    assert SETTLE_FRAME["calls"][1]["m"] == "clear"
    progs = [d["prog"] for d in SETTLE_FRAME["draws"]]
    assert len(set(progs)) == 5
    assert [p["restOpacity"] for p in SETTLE_FRAME["programs"]] == [1, 0, 1, 1, 1]
    assert [p["setsOpacityInFrame"] for p in SETTLE_FRAME["programs"]] == [
        True, True, True, True, False]
    assert [d["mixFactor"] for d in SETTLE_FRAME["draws"]] == [1, 0, 0, 0, 0]
    for draw in SETTLE_FRAME["draws"]:
        assert draw["samplers"] == {"Texture": 1, "Texture2": 0}
        assert draw["unitsBound"]["1"] == SETTLE_FRAME["sharedTexture"]
    assert SETTLE_FRAME["slotSizes"] == GL_REPLAY_ENTRY["slotSizes"]
    assert SETTLE_FRAME["slotRects"] == GL_REPLAY_ENTRY["slotRects"]
    assert SETTLE_FRAME["background"] == [65, 62, 62, 255]
    for program in SETTLE_FRAME["programs"]:
        assert [u["name"] for u in program["uniforms"]] == [
            "MVPMatrix", "mixFactor", "Opacity", "Texture", "Texture2"]


def test_settle_frame_mvp_matrices_decode_to_the_slot_rects():
    """Opacity-plan §0's zero-replay geometry check, recomputed here so that the
    sandbox's coverage model and the module's `mvp` proof agree on the decode."""
    for draw in SETTLE_FRAME["draws"]:
        program = SETTLE_FRAME["programs"][draw["prog"]]
        mvp = next(u["value"] for u in program["uniforms"] if u["name"] == "MVPMatrix")
        tex_w, tex_h = SETTLE_FRAME["slotSizes"][draw["slot"]]
        x0 = (mvp[12] + 1) / 2 * 1920
        x1 = (mvp[0] * tex_w + mvp[12] + 1) / 2 * 1920
        y0 = (mvp[13] + 1) / 2 * 1080
        y1 = (mvp[5] * tex_h + mvp[13] + 1) / 2 * 1080
        rect = SETTLE_FRAME["slotRects"][draw["slot"]]
        assert x0 == pytest.approx(rect[0], abs=1.0)
        assert (x1 - x0) == pytest.approx(rect[2], abs=1.0)
        assert (1080 - y1) == pytest.approx(rect[1], abs=1.0)
        assert (y1 - y0) == pytest.approx(rect[3], abs=1.0)


def test_settle_frame_measured_patch_is_exact_alpha_arithmetic():
    """`patched == α·clean + (1−α)·ablated` to the byte — the arithmetic the
    sandbox's `readPixels` reproduces."""
    patch = SETTLE_FRAME["measuredPatch"]
    alpha = patch["alpha"]
    for i in range(3):
        blended = round(alpha * patch["clean"][i] + (1 - alpha) * patch["ablated"][i])
        assert blended == patch["patched"][i]
    assert patch["restored"][:3] == patch["clean"][:3]
    assert patch["alpha0EqualsAblation"] is True


# =======================================================================================
# 2. Node sandbox
# =======================================================================================

# The fake platform below is a state machine, not an emulator. Its GL:
#   * holds the five player programs of the fixture with real uniform tables, so
#     `getActiveUniform`/`getUniformLocation`/`getUniform` answer truthfully;
#   * refuses a uniform write aimed at a program that is not CURRENT (it raises
#     INVALID_OPERATION and drops the write) — this is what makes the override
#     ordering and the write-back ordering testable rather than assumed;
#   * records each texture's last upload (source kind, size, format, flipY, premul);
#   * on a draw, records {slot, Opacity, decoded rect, source colour}, and clears
#     that list on `clear`;
#   * computes `readPixels` by filling each recorded draw's rect, in order, with
#     `round(a*src + (1-a)*dst)` — exact alpha arithmetic over solid colours.

_SANDBOX_JS = r"""
'use strict';
const FIXTURE = __FIXTURE__;
const CFG = __CFG__;

// ------------------------------------------------------------------ clock / scheduling
const clock = { t: 0 };
const performance = { now() { return clock.t; } };
let rafQueue = [], rvfcQueue = [];
function requestAnimationFrame(cb) { rafQueue.push(cb); return rafQueue.length; }
function cancelAnimationFrame() {}
function setTimeout(cb) { rafQueue.push(cb); return 0; }
function clearTimeout() {}
function setInterval() { return 0; }
function clearInterval() {}
function tickRaf(dtMs) {
  clock.t += (dtMs === undefined ? 16.7 : dtMs);
  const due = rafQueue; rafQueue = [];
  for (const cb of due) { try { cb(clock.t); } catch (e) { world.harnessErrors.push('raf:' + e); } }
}
function tickRvfc() {
  const due = rvfcQueue; rvfcQueue = [];
  for (const cb of due) {
    try { cb(clock.t, { mediaTime: world.video.currentTime, presentedFrames: ++world.presented }); }
    catch (e) { world.harnessErrors.push('rvfc:' + e); }
  }
}

// ------------------------------------------------------------------ GL enums
const E = FIXTURE.glEnums;
const GLC = {
  TEXTURE_2D: E.TEXTURE_2D, TEXTURE0: E.TEXTURE0, TEXTURE1: E.TEXTURE1,
  RGBA: 6408, UNSIGNED_BYTE: 5121, FLOAT: E.FLOAT,
  COLOR_BUFFER_BIT: E.COLOR_BUFFER_BIT, DEPTH_BUFFER_BIT: E.DEPTH_BUFFER_BIT,
  CURRENT_PROGRAM: 35725, ACTIVE_UNIFORMS: 35718,
  FRAMEBUFFER: 36160, FRAMEBUFFER_BINDING: 36006, COLOR_ATTACHMENT0: 36064,
  FRAMEBUFFER_COMPLETE: 36053, FRAMEBUFFER_INCOMPLETE_ATTACHMENT: 36054,
  UNPACK_FLIP_Y_WEBGL: 37440, UNPACK_PREMULTIPLY_ALPHA_WEBGL: 37441,
  NO_ERROR: 0, INVALID_OPERATION: 1282,
  TEXTURE_BINDING_2D: 32873, ACTIVE_TEXTURE: 34016,
  ARRAY_BUFFER: E.ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER: E.ELEMENT_ARRAY_BUFFER,
  BLEND: E.BLEND, SRC_ALPHA: E.SRC_ALPHA, ONE_MINUS_SRC_ALPHA: E.ONE_MINUS_SRC_ALPHA,
  TRIANGLE_STRIP: E.TRIANGLE_STRIP, UNSIGNED_SHORT: E.UNSIGNED_SHORT,
};

function decodeRect(mvp, w, h, bw, bh) {
  // y-up drawing-buffer coordinates, the frame readPixels reads in.
  const x0 = (mvp[12] + 1) / 2 * bw;
  const x1 = (mvp[0] * w + mvp[12] + 1) / 2 * bw;
  const y0 = (mvp[13] + 1) / 2 * bh;
  const y1 = (mvp[5] * h + mvp[13] + 1) / 2 * bh;
  return { x: Math.round(Math.min(x0, x1)), y: Math.round(Math.min(y0, y1)),
           w: Math.round(Math.abs(x1 - x0)), h: Math.round(Math.abs(y1 - y0)) };
}

// ------------------------------------------------------------------ the scripted fake GL
function FakeGL(canvas) {
  const gl = this;
  this.canvas = canvas;
  this._programs = new Map();
  this._textures = new Map();
  this._nextTex = 100;
  this._units = {};
  this._activeUnit = 0;
  this._current = null;
  this._error = GLC.NO_ERROR;
  this._lost = false;
  this._flipY = false; this._premul = false;
  this._drawn = [];
  this._clearColour = [0, 0, 0, 0];
  this._pendingClearColour = [0, 0, 0, 0];
  this._fboStatus = CFG.fboStatus === undefined ? GLC.FRAMEBUFFER_COMPLETE : CFG.fboStatus;
  this._uniform1fThrows = false;
  this.callLog = [];

  // Internals live on the INSTANCE: anything on the prototype would be wrapped by
  // the module's `wrapContexts` loop and logged as a player call.
  this._rec = function (name) { gl.callLog.push({ m: name }); };
  this._tex = function (id) {
    if (!gl._textures.has(id)) gl._textures.set(id, { id: id, upload: null, colour: null });
    return gl._textures.get(id);
  };
  this._write = function (loc, value) {
    if (gl._uniform1fThrows) throw new Error('uniform write refused');
    if (!loc || !loc.__loc) { gl._error = GLC.INVALID_OPERATION; return; }
    if (loc.prog !== gl._current) { gl._error = GLC.INVALID_OPERATION; return; }
    loc.prog.uniforms.get(loc.name).value = value;
  };
  this._draw = function (slotFromOffset) {
    gl._rec('draw');
    // A driver failure that throws WITHOUT setting a GL error — `getError()` stays
    // clean, so only the exception itself can reveal it (codex r1 spec 1).
    if (gl._drawThrows) throw new Error('draw refused');
    const prog = gl._current;
    if (!prog) { gl._error = GLC.INVALID_OPERATION; return; }
    const opacity = prog.uniforms.has('Opacity') ? prog.uniforms.get('Opacity').value : 1;
    const mvp = prog.uniforms.get('MVPMatrix').value;
    const mix = prog.uniforms.get('mixFactor').value;
    // The sampler-visible unit, per opacity-plan §0: mixFactor 1 selects
    // `Texture` (unit 1), 0 selects `Texture2` (unit 0).
    const unit = mix === 1 ? prog.uniforms.get('Texture').value
                           : prog.uniforms.get('Texture2').value;
    const tex = gl._units[unit];
    // The slot comes from the draw's own index-buffer offset, NOT from the program:
    // two draws may legitimately share one program with different uniforms.
    const slot = slotFromOffset;
    const size = FIXTURE.slotSizes[slot];
    const rect = decodeRect(mvp, size[0], size[1], gl.canvas.width, gl.canvas.height);
    const colour = (tex && tex.colour) ? tex.colour : FIXTURE.draws[slot].sourceColour;
    gl._drawn.push({ slot: slot, opacity: opacity, rect: rect, colour: colour });
  };

  for (const p of FIXTURE.programs) {
    const prog = { slot: p.prog, uniforms: new Map(), locs: new Map() };
    for (const u of p.uniforms) {
      prog.uniforms.set(u.name, { name: u.name, type: u.type,
                                  value: Array.isArray(u.value) ? u.value.slice() : u.value });
      prog.locs.set(u.name, { __loc: true, prog: prog, name: u.name });
    }
    this._programs.set(p.prog, prog);
  }
}
Object.assign(FakeGL.prototype, GLC);
FakeGL.prototype.isContextLost = function () { return this._lost; };
FakeGL.prototype.getError = function () { const e = this._error; this._error = GLC.NO_ERROR; return e; };
FakeGL.prototype.getExtension = function (name) {
  const gl = this;
  if (name === 'WEBGL_lose_context') return { loseContext() { gl._lost = true; } };
  return null;
};
FakeGL.prototype.getParameter = function (p) {
  if (p === GLC.CURRENT_PROGRAM) return this._current;
  if (p === GLC.ACTIVE_TEXTURE) return GLC.TEXTURE0 + this._activeUnit;
  if (p === GLC.TEXTURE_BINDING_2D) return this._units[this._activeUnit] || null;
  if (p === GLC.FRAMEBUFFER_BINDING) return this._fbo || null;
  if (p === GLC.UNPACK_FLIP_Y_WEBGL) return this._flipY;
  if (p === GLC.UNPACK_PREMULTIPLY_ALPHA_WEBGL) return this._premul;
  return 0;
};
FakeGL.prototype.useProgram = function (p) { this._rec('useProgram'); this._current = p; };
FakeGL.prototype.getProgramParameter = function (p, what) {
  if (what === GLC.ACTIVE_UNIFORMS) return p ? p.uniforms.size : 0;
  return 0;
};
FakeGL.prototype.getActiveUniform = function (p, i) {
  const names = Array.from(p.uniforms.keys());
  if (i >= names.length) return null;
  const u = p.uniforms.get(names[i]);
  return { name: u.name, size: 1, type: u.type };
};
FakeGL.prototype.getUniformLocation = function (p, name) { return (p && p.locs.get(name)) || null; };
FakeGL.prototype.getUniform = function (p, loc) {
  if (!loc || !loc.__loc) return null;
  const u = loc.prog.uniforms.get(loc.name);
  return u ? u.value : null;
};
FakeGL.prototype.uniform1f = function (loc, v) { this._rec('uniform1f'); this._write(loc, v); };
FakeGL.prototype.uniform1i = function (loc, v) { this._rec('uniform1i'); this._write(loc, v); };
FakeGL.prototype.uniformMatrix4fv = function (loc, transpose, v) {
  this._rec('uniformMatrix4fv'); this._write(loc, Array.prototype.slice.call(v));
};
FakeGL.prototype.activeTexture = function (unit) {
  this._rec('activeTexture'); this._activeUnit = unit - GLC.TEXTURE0;
};
FakeGL.prototype.createTexture = function () { return this._tex(this._nextTex++); };
FakeGL.prototype.deleteTexture = function () {};
FakeGL.prototype.bindTexture = function (target, tex) {
  this._rec('bindTexture'); this._units[this._activeUnit] = tex || null;
};
FakeGL.prototype.pixelStorei = function (pname, v) {
  this._rec('pixelStorei');
  if (pname === GLC.UNPACK_FLIP_Y_WEBGL) this._flipY = !!v;
  if (pname === GLC.UNPACK_PREMULTIPLY_ALPHA_WEBGL) this._premul = !!v;
};
FakeGL.prototype.texImage2D = function () {
  this._rec('texImage2D');
  const a = arguments, tex = this._units[this._activeUnit];
  if (!tex) { this._error = GLC.INVALID_OPERATION; return; }
  let upload;
  if (a.length >= 9) {                       // target, level, ifmt, w, h, border, fmt, type, px
    upload = { srcType: 'pixels', w: a[3], h: a[4], format: a[6], type: a[7] };
    const px = a[8];
    if (px && px.length >= 4) tex.colour = [px[0], px[1], px[2], px[3]];
  } else {                                   // target, level, ifmt, fmt, type, source
    const src = a[5] || {};
    const kind = src.tagName === 'CANVAS' ? 'canvas' : (src.tagName === 'VIDEO' ? 'video' : 'other');
    upload = { srcType: kind, w: kind === 'video' ? src.videoWidth : src.width,
               h: kind === 'video' ? src.videoHeight : src.height, format: a[3], type: a[4] };
    tex.colour = src.__colour ? src.__colour.slice() : null;
  }
  upload.flipY = this._flipY; upload.premultiplyAlpha = this._premul;
  tex.upload = upload;
  world.uploads.push({ tex: tex.id, upload: upload });
};
FakeGL.prototype.texSubImage2D = function () { return FakeGL.prototype.texImage2D.apply(this, arguments); };
FakeGL.prototype.texParameteri = function () {};
FakeGL.prototype.clearColor = function (r, g, b, a) {
  this._rec('clearColor');
  this._pendingClearColour = [Math.round(r * 255), Math.round(g * 255),
                              Math.round(b * 255), Math.round(a * 255)];
};
FakeGL.prototype.clear = function () {
  this._rec('clear');
  this._drawn = [];
  this._clearColour = this._pendingClearColour.slice();
  world.clears.push(clock.t);
};
FakeGL.prototype.drawElements = function (mode, count, type, offset) {
  this._draw(offset / FIXTURE.drawSlotStride);
};
FakeGL.prototype.drawArrays = function (mode, first) {
  this._draw(first / FIXTURE.drawSlotStride);
};
FakeGL.prototype.bindBuffer = function () {};
FakeGL.prototype.vertexAttribPointer = function () {};
FakeGL.prototype.enableVertexAttribArray = function () {};
FakeGL.prototype.enable = function () { this._rec('enable'); };
FakeGL.prototype.blendFunc = function () {};
FakeGL.prototype.flush = function () {};
FakeGL.prototype.finish = function () {};
FakeGL.prototype.viewport = function () {};
FakeGL.prototype.createFramebuffer = function () { return { id: 'fbo' }; };
FakeGL.prototype.deleteFramebuffer = function () {};
FakeGL.prototype.bindFramebuffer = function (t, f) { this._fbo = f; };
FakeGL.prototype.framebufferTexture2D = function (t, a, tt, tex) { this._fboTex = tex; };
FakeGL.prototype.checkFramebufferStatus = function () { return this._fboStatus; };
FakeGL.prototype.readPixels = function (x, y, w, h, fmt, type, out) {
  if (this._readPixelsThrows && !this._fbo) throw new Error('readPixels refused');
  if (this._fbo) {                            // poster readback off the attached texture
    const col = (this._fboTex && this._fboTex.colour) || [0, 0, 0, 255];
    for (let i = 0; i < w * h; i++) {
      out[i * 4] = col[0]; out[i * 4 + 1] = col[1]; out[i * 4 + 2] = col[2];
      out[i * 4 + 3] = col[3] === undefined ? 255 : col[3];
    }
    return;
  }
  for (let i = 0; i < w * h; i++) {
    out[i * 4] = this._clearColour[0]; out[i * 4 + 1] = this._clearColour[1];
    out[i * 4 + 2] = this._clearColour[2]; out[i * 4 + 3] = this._clearColour[3];
  }
  const fill = (rx, ry, rw, rh, colour, alpha) => {
    if (alpha === 0) return;
    const x0 = Math.max(x, rx), x1 = Math.min(x + w, rx + rw);
    const y0 = Math.max(y, ry), y1 = Math.min(y + h, ry + rh);
    const ca = colour[3] === undefined ? 255 : colour[3];
    for (let yy = y0; yy < y1; yy++) {
      const row = (yy - y) * w;
      for (let xx = x0; xx < x1; xx++) {
        const px = (row + (xx - x)) * 4;
        out[px] = Math.round(alpha * colour[0] + (1 - alpha) * out[px]);
        out[px + 1] = Math.round(alpha * colour[1] + (1 - alpha) * out[px + 1]);
        out[px + 2] = Math.round(alpha * colour[2] + (1 - alpha) * out[px + 2]);
        out[px + 3] = Math.round(alpha * ca + (1 - alpha) * out[px + 3]);
      }
    }
  };
  for (const d of this._drawn) fill(d.rect.x, d.rect.y, d.rect.w, d.rect.h, d.colour, d.opacity);
};

// ------------------------------------------------------------------ fake DOM
function FakeElement(id, tag) {
  this.id = id || ''; this.tagName = (tag || 'div').toUpperCase(); this.nodeType = 1;
  this.children = []; this.parentNode = null; this.isConnected = false;
  this.style = { setProperty() {} }; this.dataset = {};
}
FakeElement.prototype.appendChild = function (child) {
  child.parentNode = this; this.children.push(child);
  const connect = (n) => { n.isConnected = this.isConnected; n.children.forEach(connect); };
  connect(child);
  world.fireMutation([{ type: 'childList', target: this, addedNodes: [child], removedNodes: [] }]);
  return child;
};
FakeElement.prototype.removeChild = function (child) {
  const i = this.children.indexOf(child);
  if (i >= 0) this.children.splice(i, 1);
  child.parentNode = null;
  const disconnect = (n) => { n.isConnected = false; n.children.forEach(disconnect); };
  disconnect(child);
  world.fireMutation([{ type: 'childList', target: this, addedNodes: [], removedNodes: [child] }]);
  return child;
};
FakeElement.prototype.contains = function (n) {
  if (n === this) return true;
  return this.children.some((c) => c.contains(n));
};
FakeElement.prototype.querySelector = function () { return null; };
FakeElement.prototype.querySelectorAll = function () { return []; };
FakeElement.prototype.addEventListener = function (type, fn) {
  (this._listeners || (this._listeners = {}))[type] =
    ((this._listeners[type]) || []).concat([fn]);
};
FakeElement.prototype.removeEventListener = function (type, fn) {
  if (!this._listeners || !this._listeners[type]) return;
  this._listeners[type] = this._listeners[type].filter((f) => f !== fn);
};
FakeElement.prototype.dispatchEvent = function (event) {
  const fns = (this._listeners && this._listeners[event.type]) || [];
  for (const fn of fns) fn.call(this, event);
  return true;
};
FakeElement.prototype.checkVisibility = function () { return true; };

function FakeCanvas(id, w, h) {
  FakeElement.call(this, id, 'canvas');
  this.width = w; this.height = h;
  this.__colour = [17, 17, 17, 255];
  this._ctx = null;
}
FakeCanvas.prototype = Object.create(FakeElement.prototype);
FakeCanvas.prototype.constructor = FakeCanvas;
FakeCanvas.prototype.getContext = function (kind) {
  if (kind !== 'webgl' && kind !== 'experimental-webgl' && kind !== 'webgl2') return null;
  if (!this._ctx) { this._ctx = new FakeGL(this); world.contexts.push(this._ctx); }
  return this._ctx;
};

function FakeVideo(src) {
  FakeElement.call(this, '', 'video');
  this.currentSrc = src; this.src = src;
  this.readyState = 4; this.paused = false; this.ended = false; this.currentTime = 0.5;
  this.videoWidth = 1920; this.videoHeight = 540;
  this.__colour = [80, 90, 100, 255];
}
FakeVideo.prototype = Object.create(FakeElement.prototype);
FakeVideo.prototype.constructor = FakeVideo;
FakeVideo.prototype.play = function () {
  this.paused = false; world.videoCalls.push('play'); return Promise.resolve();
};
FakeVideo.prototype.pause = function () { this.paused = true; world.videoCalls.push('pause'); };
FakeVideo.prototype.requestVideoFrameCallback = function (cb) {
  // At end of media the browser stops delivering these; the registration is
  // accepted and then simply never fires. That is N1's whole shape.
  if (world.rvfcDead) return 1;
  rvfcQueue.push(cb); return 1;
};

// ------------------------------------------------------------------ the world
const world = {
  uploads: [], clears: [], contexts: [], videoCalls: [], seamCalls: [],
  mutationCallbacks: [], harnessErrors: [], presented: 0,
  observerThrows: !!CFG.observerThrows,
  fireMutation(records) {
    for (const cb of this.mutationCallbacks) {
      try { cb(records, { disconnect() {} }); } catch (e) { this.harnessErrors.push('mo:' + e); }
    }
  },
};

function MutationObserver(cb) {
  this.observe = function () {
    if (world.observerThrows) throw new Error('observe refused');
    world.mutationCallbacks.push(cb);
  };
  this.disconnect = function () {};
  this.takeRecords = function () { return []; };
}

const documentElement = new FakeElement('', 'html');
documentElement.isConnected = true;
const body = new FakeElement('body', 'body');
documentElement.appendChild(body);
const stage = new FakeElement('stage', 'div');
const document = {
  documentElement: documentElement, body: body, readyState: 'complete',
  getElementById(id) { return id === 'stage' ? stage : null; },
  querySelector(sel) { return sel === '#stage' ? stage : null; },
  querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {},
  createElement(tag) {
    return tag === 'canvas' ? new FakeCanvas('', 1, 1) : new FakeElement('', tag);
  },
};

const location = { hash: CFG.initialHash === undefined ? '#1' : CFG.initialHash };
world.video = new FakeVideo('file:///assets/untitled.mov');

const seam = {
  version: 1,
  carried(movieKey) {
    world.seamCalls.push({ fn: 'carried', movieKey: movieKey });
    if (CFG.carriedNull) return { video: null, reason: 'ambiguous' };
    return { video: world.video, reason: null };
  },
  movieKeyOf(v) {
    world.seamCalls.push({ fn: 'movieKeyOf' });
    return v === world.video ? 'movie1' : null;
  },
  setKeepWarm(v, on) { world.seamCalls.push({ fn: 'setKeepWarm', on: !!on }); },
  release(movieKey, opts) {
    world.seamCalls.push({ fn: 'release', movieKey: movieKey,
                           rect: (opts && opts.rect) || null });
    return { ok: true, reason: null };
  },
  note(kind, detail) { world.seamCalls.push({ fn: 'note', kind: kind }); },
};

const window = {
  __OBED_CONTINUITY__: CFG.plan,
  __OBED_CONTINUITY_INFO__: { authoredWidth: 1920, authoredHeight: 1080 },
  location: location, performance: performance, document: document,
  requestAnimationFrame: requestAnimationFrame, cancelAnimationFrame: cancelAnimationFrame,
  setTimeout: setTimeout, clearTimeout: clearTimeout,
  setInterval: setInterval, clearInterval: clearInterval,
  MutationObserver: MutationObserver,
  addEventListener() {}, removeEventListener() {},
};
function installSeam() {
  window.__OBED_P2_PRESERVE__ = CFG.noGlReplaySeam ? {} : { glReplay: seam };
}
if (!CFG.noSeam && !CFG.lateSeamTicks) installSeam();
if (!CFG.noObedLive) {
  window.__obedLive = {
    _ready: false,
    _sceneId: CFG.sceneId === undefined ? 1 : CFG.sceneId,
    snapshot() { return { state: this._ready ? 'IdleAtFinalState' : 'Playing',
                          ready: this._ready, sceneId: this._sceneId }; },
  };
}
if (CFG.nonWritableMethod) {
  // Assignment to this in non-strict code fails SILENTLY; the module must notice.
  Object.defineProperty(FakeGL.prototype, CFG.nonWritableMethod, {
    value: FakeGL.prototype[CFG.nonWritableMethod], writable: false, configurable: false,
  });
}
const HTMLCanvasElement = FakeCanvas;
const HTMLVideoElement = FakeVideo;
const WebGLRenderingContext = FakeGL;
if (!CFG.noWebGL) window.WebGLRenderingContext = FakeGL;
if (CFG.noRvfc) delete FakeVideo.prototype.requestVideoFrameCallback;
// The module reads `debugForceFail` off a pre-seeded (version-less) API object.
if (CFG.debugForceFail) window.__OBED_GL_REPLAY__ = { debugForceFail: CFG.debugForceFail };
if (CFG.seedDebug && !CFG.debugForceFail) window.__OBED_GL_REPLAY__ = {};

// The pre-wrap prototype methods. Calling through these simulates a writer that
// is not the player and not us (a future probe, a re-record), which is the only
// honest way to dirty a sticky uniform without tripping the LIVE wrapper guard.
const RAW = { useProgram: FakeGL.prototype.useProgram, uniform1f: FakeGL.prototype.uniform1f };

// ------------------------------------------------------------------ install the module
// The product module is injected as a plain <script>, so it is NOT strict mode.
// Evaluating it through the Function constructor reproduces that; inlining it here
// would inherit this file's own `use strict`, under which a failed assignment to a
// non-writable prototype method THROWS instead of failing silently — the exact
// difference codex r1 spec 6 turns on.
let installThrew = null;
try {
  const moduleFn = new Function(
    'window', 'document', 'location', 'performance',
    'HTMLCanvasElement', 'HTMLVideoElement', 'WebGLRenderingContext',
    'MutationObserver', 'requestAnimationFrame', 'cancelAnimationFrame',
    'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval',
    __MODULE_SOURCE__);
  moduleFn(window, document, location, performance,
           FakeCanvas, FakeVideo, FakeGL,
           MutationObserver, requestAnimationFrame, cancelAnimationFrame,
           setTimeout, clearTimeout, setInterval, clearInterval);
} catch (e) { installThrew = String((e && e.stack) || e); }
const M = window.__OBED_GL_REPLAY__ && window.__OBED_GL_REPLAY__.version
  ? window.__OBED_GL_REPLAY__ : null;

// ------------------------------------------------------------------ the "player"
function playerFrame(gl, len) {
  const calls = FIXTURE.calls.slice(0, len === undefined ? FIXTURE.calls.length : len);
  for (const call of calls) {
    const args = call.a.map((a) => {
      if (a && typeof a === 'object' && a.prog !== undefined && a.name !== undefined) {
        return gl.getUniformLocation(gl._programs.get(a.prog), a.name);
      }
      return a;
    });
    if (call.m === 'useProgram') gl.useProgram(args[0] === null ? null : gl._programs.get(args[0]));
    else if (call.m === 'bindTexture') gl.bindTexture(args[0], args[1] === null ? null : gl._tex(args[1]));
    else gl[call.m].apply(gl, args);
  }
}

function playerUpload(gl, texId, w, h, colour) {
  const src = new FakeCanvas('', w, h);
  if (colour) src.__colour = colour;
  gl.activeTexture(GLC.TEXTURE0);
  gl.bindTexture(GLC.TEXTURE_2D, gl._tex(texId));
  gl.pixelStorei(GLC.UNPACK_FLIP_Y_WEBGL, true);
  gl.pixelStorei(GLC.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
  gl.texImage2D(GLC.TEXTURE_2D, 0, GLC.RGBA, GLC.RGBA, GLC.UNSIGNED_BYTE, src);
}

// ------------------------------------------------------------------ the timeline
async function settle(ticks) {
  for (let i = 0; i < (ticks || 8); i++) { tickRaf(); tickRvfc(); await null; await null; }
}

async function pumpUntil(promise, budget) {
  let done = false, value = null, err = null;
  promise.then((v) => { done = true; value = v; }, (e) => { done = true; err = e; });
  for (let i = 0; i < (budget || 400) && !done; i++) {
    tickRaf(); tickRvfc(); await null; await null;
  }
  if (err) throw err;
  return { done: done, value: value };
}

function detailsOf(list) {
  return (list || []).map((r) => (typeof r === 'string' ? { kind: r, detail: {} }
                                                        : { kind: r.kind, detail: r.detail || {} }));
}

function snapshotState() {
  const handle = window.__OBED_GL_ORACLE__;
  const gl = world.contexts.length ? world.contexts[0] : null;
  let stats = null;
  if (M && typeof M.stats === 'function') {
    try { stats = M.stats(); } catch (e) { stats = { statsThrew: String(e) }; }
  }
  return {
    installed: !!M,
    installThrew: installThrew,
    debugHooks: M ? Object.keys(M).filter((k) => k === 'debug' || k === 'debugForceFail')
                      .filter((k) => M[k] != null).sort() : null,
    state: M ? M.state : null,
    standDowns: M ? M.standDowns.slice() : [],
    events: M ? detailsOf(M.events) : [],
    notes: M ? detailsOf(M.notes) : [],
    eventKinds: M ? M.events.map((e) => e.kind) : [],
    seamCalls: world.seamCalls,
    videoCalls: world.videoCalls,
    handlePresent: !!handle,
    handleFields: handle ? Object.keys(handle).sort() : null,
    handleScalars: handle ? {
      sceneId: handle.sceneId, instanceId: handle.instanceId, rect: handle.rect,
      canvasId: handle.canvasId, epoch: handle.epoch,
    } : null,
    drawnOpacities: gl ? gl._drawn.map((d) => d.opacity) : null,
    drawnSlots: gl ? gl._drawn.map((d) => d.slot) : null,
    currentProgramSlot: gl && gl._current ? gl._current.slot : null,
    uploads: world.uploads.length,
    harnessErrors: world.harnessErrors,
    opacityAfter: gl ? FIXTURE.programs.map(
      (p) => gl._programs.get(p.prog).uniforms.get('Opacity').value) : null,
    stats: stats,
  };
}

async function armAndGoLive(out) {
  await settle(3);                                   // IDLE -> ARM-PRE on the hash
  if (CFG.lateSeamTicks) {
    // An ARM-PRE requirement that appears N ticks late must be DEFERRED, not a
    // stand-down, for as long as no armed context exists (plan §2.2).
    await settle(CFG.lateSeamTicks);
    out.beforeSeam = { standDowns: M ? M.standDowns.slice() : [],
                       pending: M ? M.stats().pending : null,
                       state: M ? M.state : null };
    installSeam();
    await settle(2);
  }
  const canvas = new FakeCanvas(CFG.canvasId === undefined ? '0-canvas' : CFG.canvasId,
                                CFG.canvasW === undefined ? 1920 : CFG.canvasW,
                                CFG.canvasH === undefined ? 1080 : CFG.canvasH);
  stage.isConnected = true;
  body.appendChild(stage);
  world.canvas = canvas;
  // Connected, but NOT under `#stage` when the test asks for that.
  (CFG.canvasOutsideStage ? body : stage).appendChild(canvas);
  const gl = canvas.getContext('webgl');
  world.gl = gl;
  if (CFG.videoNotReady) world.video.readyState = 1;
  // The player's per-slot texture uploads. Slot `movieSlot`'s is the poster: the
  // measured signature is a canvas source at slotSizes[movieSlot], RGBA /
  // UNSIGNED_BYTE, flipY + premultiplied.
  FIXTURE.textureUploads.forEach(function (up, slot) {
    playerUpload(gl, up.tex, up.width, up.height, FIXTURE.draws[slot].sourceColour);
  });
  // Draw 17 samples the SHARED texture (mixFactor 1 -> unit 1), so it carries slot 0's colour.
  playerUpload(gl, FIXTURE.sharedTexture, 1920, 1080, FIXTURE.draws[0].sourceColour);
  if (CFG.secondPosterTexture) {
    const poster = FIXTURE.slotSizes[MOVIE_SLOT_JS];
    playerUpload(gl, 900, poster[0], poster[1]);
  }
  for (let f = 0; f < 3; f++) { playerFrame(gl, CFG.frameLen); await settle(2); }
  if (CFG.floodWithoutClear) {
    for (let i = 0; i < 600; i++) gl.enable(GLC.BLEND);
  }
  if (CFG.readPixelsThrowsAtArmPost) gl._readPixelsThrows = true;
  if (window.__obedLive) window.__obedLive._ready = true;
  await settle(CFG.settleTicks === undefined ? 14 : CFG.settleTicks);
  return gl;
}

const DEBUG_ONLY_SLOT = CFG.debugOnlySlot === undefined ? 4 : CFG.debugOnlySlot;
const MOVIE_ENTRY = (CFG.plan && CFG.plan.boundaries
  ? CFG.plan.boundaries.filter((b) => b && b.action === 'glReplay')[0] : null) || {atScene: 2};
const MOVIE_SLOT_JS = CFG.plan && CFG.plan.boundaries
  ? (CFG.plan.boundaries.filter((b) => b && b.action === 'glReplay')[0] || {}).movieSlot
  : 3;

async function main() {
  const out = { scenario: CFG.scenario };
  if (CFG.scenario === 'install_only') {
    out.afterInstall = snapshotState();
    await settle(6);
    out.final = snapshotState();
    return out;
  }
  const gl = await armAndGoLive(out);
  out.afterLive = snapshotState();

  if (CFG.scenario === 'happy') {
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'sample') {
    const handle = window.__OBED_GL_ORACLE__;
    if (handle) {
      out.epochAtPublish = handle.epoch;
      out.samples = (await pumpUntil(handle.sample(24))).value;
      out.epochAfterSamples = handle.epoch;
      out.markerBands = (await pumpUntil(handle.markerBands())).value;
      out.handleStillSame = window.__OBED_GL_ORACLE__ === handle;
    }
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'pause_resume') {
    const handle = window.__OBED_GL_ORACLE__;
    if (handle) {
      world.seamCalls.length = 0; world.videoCalls.length = 0;
      await pumpUntil(handle.pause());
      out.afterPause = { seam: world.seamCalls.slice(), video: world.videoCalls.slice() };
      world.seamCalls.length = 0; world.videoCalls.length = 0;
      await pumpUntil(handle.resume());
      out.afterResume = { seam: world.seamCalls.slice(), video: world.videoCalls.slice() };
    }
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'draw_throws') {
    gl.callLog.length = 0;
    gl._drawThrows = true;              // throws, and getError() stays clean
    await settle(4);
    out.glErrorAfter = gl._error;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'context_lost_event_only') {
    // The event arrives BEFORE `isContextLost()` flips, which is legal.
    world.rvfcDead = true;
    rafQueue = [];
    gl.callLog.length = 0;
    world.canvas.dispatchEvent({ type: 'webglcontextlost', preventDefault() {} });
    await null; await null;
    out.callOrder = gl.callLog.slice();
    out.isContextLostStayedFalse = gl.isContextLost() === false;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'writeback_fails_unflagged') {
    gl._uniform1fThrows = true;
    gl.callLog.length = 0;
    gl.enable(GLC.BLEND);               // the player's unflagged call
    out.callOrder = gl.callLog.slice();
    await settle(3);
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'video_ended') {
    const handle = window.__OBED_GL_ORACLE__;
    let resolved = null;
    handle.sample(24).then(function (v) { resolved = v; });
    const iterBefore = M.stats().iter;
    const uploadsBefore = M.stats().uploads;
    world.video.ended = true;
    world.video.paused = true;
    world.rvfcDead = true;                       // no more rVFC callbacks, ever
    for (let i = 0; i < 200 && resolved === null; i++) { tickRaf(); await null; await null; }
    out.endedSamples = resolved === null ? null : resolved.length;
    out.iterDelta = M.stats().iter - iterBefore;
    out.uploadsDelta = M.stats().uploads - uploadsBefore;
    out.loopMode = M.stats().loopMode;
    out.videoEnded = M.stats().videoEnded;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'context_lost_no_ticks') {
    // The loop is dead: NOTHING is delivered after this point, so a stand-down can
    // only come from the `webglcontextlost` event itself.
    world.rvfcDead = true;
    rafQueue = [];
    gl.callLog.length = 0;
    gl._lost = true;
    world.canvas.dispatchEvent({ type: 'webglcontextlost', preventDefault() {} });
    await null; await null;                      // microtasks only — no rAF, no rVFC
    out.callOrder = gl.callLog.slice();
    out.ticksDelivered = 0;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'gl_error_replay') {
    gl.callLog.length = 0;
    gl._error = GLC.INVALID_OPERATION;
    await settle(4);
    out.callOrder = gl.callLog.slice();
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'debug_replay_only') {
    // `API.debug.replay({only: n})` with no `value` must leave EVERY program at its
    // rest opacity — the same shape as D1, in the hook S3 drives gate 3 with.
    const dirty = [];
    for (const p of FIXTURE.programs) {
      const prog = gl._programs.get(p.prog);
      const loc = gl.getUniformLocation(prog, 'Opacity');
      const prev = gl._current;
      RAW.useProgram.call(gl, prog);
      RAW.uniform1f.call(gl, loc, 0.5);
      RAW.useProgram.call(gl, prev);
      dirty.push(prog.uniforms.get('Opacity').value);
    }
    out.dirtiedBefore = dirty;
    // Slot 4 is the ONLY meaningful target: the recorded frame re-sets `Opacity`
    // for programs 0-3 itself, so a replay that writes nothing for them still
    // leaves them at rest and the assertion would pass on the broken shape.
    M.debug.replay({only: DEBUG_ONLY_SLOT});
    out.afterDebugReplay = FIXTURE.programs.map(
      (p) => gl._programs.get(p.prog).uniforms.get('Opacity').value);
    out.debugPrograms = M.debug.programs().length;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'dirty_unset_program') {
    // Program 4 is the one the recorded frame never re-sets (opacity plan F-10),
    // and with its override dropped nothing else writes it either. Dirty it from
    // outside, then let ONE LIVE tick run: the replay must write its rest value.
    const prog = gl._programs.get(4);
    const loc = gl.getUniformLocation(prog, 'Opacity');
    const prev = gl._current;
    RAW.useProgram.call(gl, prog);
    RAW.uniform1f.call(gl, loc, 0);
    RAW.useProgram.call(gl, prev);
    out.dirtied = prog.uniforms.get('Opacity').value;
    const iterBefore = M.stats().iter;
    await settle(3);
    out.liveTicked = M.stats().iter > iterBefore;
    out.afterLiveTick = prog.uniforms.get('Opacity').value;
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'hash_flip') {
    location.hash = '#' + MOVIE_ENTRY.atScene;
    await settle(4);
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'pause_twice') {
    const handle = window.__OBED_GL_ORACLE__;
    if (handle) {
      await pumpUntil(handle.pause());
      await pumpUntil(handle.pause());          // a second pause must not spawn a 2nd loop
      const before = M.stats().iter;
      await settle(5);                          // 5 rAF ticks of the paused loop
      out.pausedIterDelta = M.stats().iter - before;
      out.pausedTicks = 5;
      await pumpUntil(handle.resume());
      const afterResume = M.stats().iter;
      await settle(4);
      out.resumedIterDelta = M.stats().iter - afterResume;
      out.resumedTicks = 4;
    }
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'sample_interrupted') {
    const handle = window.__OBED_GL_ORACLE__;
    if (handle) {
      let resolved = null;
      handle.sample(24).then(function (v) { resolved = v; });
      for (let i = 0; i < 4; i++) { tickRaf(); tickRvfc(); await null; await null; }
      out.samplesBeforeRemoval = 4;
      stage.removeChild(world.canvas);          // stand-down with the window outstanding
      for (let i = 0; i < 40 && resolved === null; i++) {
        tickRaf(); tickRvfc(); await null; await null;
      }
      out.interruptedSamples = resolved === null ? null : resolved.length;
    }
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'second_context') {
    // A later Magic Move creates a NEW canvas + context; v1 has one boundary, so
    // the module must neither re-arm on it nor stand down because of it.
    const second = new FakeCanvas('1-canvas', 1920, 1080);
    stage.appendChild(second);
    out.secondContext = !!second.getContext('webgl');
    second.getContext('webgl').enable(GLC.BLEND);
    await settle(4);
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'canvas_removed') {
    gl.callLog.length = 0;
    stage.removeChild(world.canvas);
    await settle(4);
    out.callOrder = gl.callLog.slice();
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'unflagged_player_call') {
    // The player wakes up and issues ONE call the module never issues itself.
    gl.callLog.length = 0;
    gl.enable(GLC.BLEND);
    out.callOrder = gl.callLog.slice();
    await settle(3);
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'context_lost') {
    gl.getExtension('WEBGL_lose_context').loseContext();
    gl.callLog.length = 0;
    await settle(4);
    out.callOrder = gl.callLog.slice();
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'gl_error') {
    gl._error = GLC.INVALID_OPERATION;
    await settle(4);
    out.final = snapshotState();
    return out;
  }
  if (CFG.scenario === 'writeback_fails') {
    gl._uniform1fThrows = true;
    stage.removeChild(world.canvas);
    await settle(4);
    out.final = snapshotState();
    return out;
  }
  await settle(6);
  out.final = snapshotState();
  return out;
}

main().then((out) => {
  console.log('__RESULT__' + JSON.stringify(out));
}, (e) => {
  console.log('__RESULT__' + JSON.stringify({ harnessThrew: String((e && e.stack) || e) }));
});
"""


def _node() -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the GL-replay JS")
    return node


_DEFAULT_PLAN = object()


def _run_sandbox(*, scenario: str = "happy", plan: object = _DEFAULT_PLAN,
                 frame: dict | None = None, **cfg) -> dict:
    node = _node()
    config = {"scenario": scenario,
              "plan": RUNTIME_PLAN if plan is _DEFAULT_PLAN else plan}
    config.update(cfg)
    harness = (
        _SANDBOX_JS.replace("__FIXTURE__", json.dumps(SETTLE_FRAME if frame is None else frame))
        .replace("__CFG__", json.dumps(config))
        .replace("__MODULE_SOURCE__", json.dumps(live_gl_replay_js.GL_REPLAY_JS))
    )
    result = subprocess.run([node, "-e", harness], text=True, capture_output=True)
    for line in result.stdout.splitlines():
        if line.startswith("__RESULT__"):
            return json.loads(line[len("__RESULT__") :])
    raise AssertionError(
        f"sandbox produced no result\nexit={result.returncode}\n"
        f"stdout={result.stdout[-4000:]}\nstderr={result.stderr[-4000:]}"
    )


def _assert_clean(out: dict) -> dict:
    assert "harnessThrew" not in out, out.get("harnessThrew")
    final = out["final"]
    assert final["installThrew"] is None, final["installThrew"]
    assert final["harnessErrors"] == [], final["harnessErrors"]
    return final


def _unproven(final: dict) -> dict[int, str]:
    """Slot -> reason, from the `glreplay-opacity-unproven` notes."""
    out: dict[int, str] = {}
    for note in final["notes"]:
        if note["kind"] != "glreplay-opacity-unproven":
            continue
        out[note["detail"]["slot"]] = note["detail"]["reason"]
    return out


def _mutate_frame(**kw) -> dict:
    """A copy of the settle frame with program 4's uniform `name` changed to
    `value`, in both the program table and the call that sets it."""
    name, value = kw["name"], kw["value"]
    frame = copy.deepcopy(SETTLE_FRAME)
    for program in frame["programs"]:
        if program["prog"] != 4:
            continue
        for uniform in program["uniforms"]:
            if uniform["name"] == name:
                uniform["value"] = value
        if name == "Opacity":
            program["restOpacity"] = value
    for draw in frame["draws"]:
        if draw["slot"] == 4 and name == "mixFactor":
            draw["mixFactor"] = value
    for call in frame["calls"]:
        target = call["a"][0] if call["a"] else None
        if not isinstance(target, dict) or target != {"prog": 4, "name": name}:
            continue
        call["a"][-1] = value
    return frame


# --- install / arming -------------------------------------------------------------------


def test_install_is_a_no_op_without_a_plan():
    out = _run_sandbox(scenario="install_only", plan=None)
    assert "harnessThrew" not in out, out.get("harnessThrew")
    assert out["afterInstall"]["installed"] is False
    assert out["afterInstall"]["installThrew"] is None
    assert out["final"]["handlePresent"] is False


def test_install_is_a_no_op_for_a_plan_without_a_gl_replay_boundary():
    out = _run_sandbox(scenario="install_only", plan=_plan_with(None))
    assert out["afterInstall"]["installed"] is False
    assert out["final"]["handlePresent"] is False


def test_malformed_plan_stands_down_plan_unreadable_and_installs_nothing():
    out = _run_sandbox(scenario="install_only", plan=_plan_with(_override(opacity=5.0)))
    final = out["final"]
    assert final["installed"] is True, "the API object must exist to carry the reason"
    assert final["standDowns"] == ["planUnreadable"], final["standDowns"]
    assert final["state"] == "RETIRED"
    assert final["handlePresent"] is False


def test_install_stands_down_without_the_seam_at_arm_pre():
    """Plan §2.2: the seam is an ARM-PRE requirement, never a silent carry."""
    out = _run_sandbox(scenario="arm_only", noSeam=True)
    final = _assert_clean(out)
    assert final["handlePresent"] is False
    assert final["standDowns"] == ["runtimeSeamAbsent"]


def test_full_happy_path_reaches_live_with_the_milestone_notes():
    out = _run_sandbox(scenario="happy")
    live = out["afterLive"]
    assert live["installThrew"] is None, live["installThrew"]
    assert live["standDowns"] == [], live["standDowns"]
    assert live["state"] == "LIVE", live["state"]
    for milestone in MILESTONE_NOTES:
        assert milestone in live["eventKinds"], live["eventKinds"]
    assert live["handlePresent"] is True
    # `glreplay-arm`/`glreplay-live` also reach the core through the seam.
    seam_notes = [c["kind"] for c in live["seamCalls"] if c["fn"] == "note"]
    for milestone in MILESTONE_NOTES:
        assert milestone in seam_notes, seam_notes


def test_published_handle_carries_exactly_the_plan_fields():
    out = _run_sandbox(scenario="happy")
    live = out["afterLive"]
    assert live["handlePresent"] is True
    assert live["handleFields"] == sorted([
        "gl", "canvas", "video", "epoch", "sceneId", "instanceId", "rect", "canvasId",
        "sample", "markerBands", "pause", "resume",
    ])
    scalars = live["handleScalars"]
    assert scalars["sceneId"] == GL_REPLAY_ENTRY["atScene"] - 1
    assert scalars["instanceId"] == GL_REPLAY_ENTRY["instanceId"]
    assert scalars["rect"] == GL_REPLAY_ENTRY["instanceRect"]
    assert scalars["canvasId"] == "0-canvas"
    # One armed boundary in v1 means exactly one record, so the frozen epoch is 1.
    assert scalars["epoch"] == 1
    assert live["stats"]["epoch"] == 1


def test_handle_epoch_is_frozen_at_publish_for_the_single_record():
    """Plan §2.4 (Opus r1 finding 12): `epoch` is incremented on every record and
    frozen on the handle at publish. v1 arms ONE boundary, so exactly one record
    exists: the handle's epoch is 1, never moves while LIVE, and every awaited
    answer the probe re-checks (`markerBands`) reports that same epoch."""
    out = _run_sandbox(scenario="sample")
    final = _assert_clean(out)
    assert out["epochAtPublish"] == 1, out["epochAtPublish"]
    assert out["epochAfterSamples"] == 1, out["epochAfterSamples"]
    assert out["handleStillSame"] is True, "the handle object was replaced mid-LIVE"
    assert out["markerBands"]["epoch"] == out["epochAtPublish"], out["markerBands"]["epoch"]
    # `stats()` reports the same single record — the probe's re-check compares them.
    assert final["stats"]["epoch"] == out["epochAtPublish"], final["stats"]["epoch"]
    assert final["handleScalars"]["epoch"] == out["epochAtPublish"]
    assert len(out["markerBands"]["dark"]) == html_alpha_probe.INPAGE_BAND_COUNT
    assert len(out["markerBands"]["light"]) == html_alpha_probe.INPAGE_BAND_COUNT


def test_sample_returns_monotonic_ticks_with_128_bands():
    out = _run_sandbox(scenario="sample")
    samples = out.get("samples")
    assert samples, "sample(24) never resolved"
    assert len(samples) == 24
    times = [s["t"] for s in samples]
    assert all(b > a for a, b in zip(times, times[1:])), times
    for s in samples:
        assert len(s["bands"]) == html_alpha_probe.INPAGE_BAND_COUNT
        assert s["glErr"] == 0
        assert len(s["greenRGB"]) == 3


def test_pause_suspends_keep_warm_before_pausing_and_resume_reverses():
    """Plan §2.4 / rev-2 A4: without the keep-warm suspension the core's 200 ms
    sweep un-pauses the probe's control decoder mid-window."""
    out = _run_sandbox(scenario="pause_resume")
    pause = out["afterPause"]
    keep_warm_off = [c for c in pause["seam"] if c["fn"] == "setKeepWarm" and c["on"] is False]
    assert keep_warm_off, f"pause() never suspended the keep-warm sweep: {pause}"
    assert pause["video"] == ["pause"], pause["video"]
    resume = out["afterResume"]
    keep_warm_on = [c for c in resume["seam"] if c["fn"] == "setKeepWarm" and c["on"] is True]
    assert keep_warm_on, f"resume() never restored the keep-warm sweep: {resume}"
    assert resume["video"] == ["play"], resume["video"]


# --- stand-down coverage ----------------------------------------------------------------

# Every §2.7 reason, driven through the sandbox's natural path where one exists and
# through `debugForceFail` where it does not. The middle column records which.
STAND_DOWN_CASES: list[tuple[str, str, dict]] = [
    ("planUnreadable", "natural", {"scenario": "install_only",
                                   "plan": _plan_with(_override(opacity=5.0))}),
    ("runtimeSeamAbsent", "natural", {"scenario": "arm_only", "noSeam": True}),
    ("glReplayUnavailable", "natural", {"scenario": "install_only", "noWebGL": True}),
    ("settleSignalAbsent", "natural", {"scenario": "arm_only", "noObedLive": True}),
    ("rvfcUnavailable", "natural", {"scenario": "arm_only", "noRvfc": True}),
    ("observerNotArmed", "natural", {"scenario": "arm_only", "observerThrows": True}),
    ("canvasShape", "natural", {"scenario": "arm_only", "canvasW": 1280, "canvasH": 720}),
    ("assetUnbound", "natural", {"scenario": "arm_only", "carriedNull": True}),
    ("videoNotReady", "natural", {"scenario": "arm_only", "videoNotReady": True}),
    ("posterAmbiguous", "natural", {"scenario": "arm_only", "secondPosterTexture": True}),
    ("posterUnreadable", "natural", {"scenario": "arm_only", "fboStatus": 36054}),
    ("sceneMismatch", "natural", {"scenario": "arm_only", "sceneId": 7}),
    ("frameNotDelimited", "natural", {"scenario": "arm_only", "floodWithoutClear": True}),
    ("occlusionTooHigh", "forced", {"scenario": "arm_only",
                                    "debugForceFail": "occlusionTooHigh"}),
    ("contextLost", "natural", {"scenario": "context_lost"}),
    ("glError", "natural", {"scenario": "gl_error"}),
    ("unflaggedPlayerCall", "natural", {"scenario": "unflagged_player_call"}),
    ("frameLengthChanged", "forced", {"scenario": "arm_only",
                                      "debugForceFail": "frameLengthChanged"}),
]

# Reasons reached before the module ever holds the seam: `release()` cannot be
# called at all. Every other reason owes the §2.5 step-6 hand-off, including the
# ones where no decoder was ever bound.
NO_RELEASE_REASONS = {"planUnreadable", "glReplayUnavailable", "runtimeSeamAbsent"}


def test_stand_down_cases_cover_the_closed_reason_set():
    """The parametrisation below must exercise every §2.7 reason — `writebackFailed`
    has its own test because it is recorded *in addition* to a trigger."""
    covered = {case[0] for case in STAND_DOWN_CASES} | {"writebackFailed"}
    assert covered == set(STAND_DOWN_REASONS)
    assert len(STAND_DOWN_CASES) == len({c[0] for c in STAND_DOWN_CASES})


@pytest.mark.parametrize("reason,how,cfg", STAND_DOWN_CASES,
                         ids=[f"{c[0]}-{c[1]}" for c in STAND_DOWN_CASES])
def test_each_reason_stands_down_exactly_once(reason, how, cfg):
    out = _run_sandbox(**cfg)
    final = _assert_clean(out)
    assert final["standDowns"] == [reason], final["standDowns"]
    assert final["handlePresent"] is False, "the handle survived the stand-down"
    assert final["state"] == "RETIRED", final["state"]
    standdowns = [e for e in final["events"] if e["kind"] == "glreplay-standdown"]
    assert len(standdowns) == 1, final["events"]
    assert standdowns[0]["detail"]["reason"] == reason
    releases = [c for c in final["seamCalls"] if c["fn"] == "release"]
    if reason in NO_RELEASE_REASONS:
        assert releases == [], f"{reason} released a decoder it never bound"
    else:
        assert len(releases) == 1, f"release called {len(releases)} times"
        assert releases[0]["movieKey"] == GL_REPLAY_ENTRY["movieKey"]
        assert releases[0]["rect"] == DESTINATION_RECT


def test_canvas_removal_is_the_normal_exit_and_hands_off():
    out = _run_sandbox(scenario="canvas_removed")
    final = _assert_clean(out)
    assert final["standDowns"] == [NORMAL_EXIT_REASON], final["standDowns"]
    assert final["handlePresent"] is False
    handoffs = [e for e in final["events"] if e["kind"] == "glreplay-handoff"]
    assert len(handoffs) == 1, final["events"]
    assert not [e for e in final["events"] if e["kind"] == "glreplay-standdown"]
    releases = [c for c in final["seamCalls"] if c["fn"] == "release"]
    assert len(releases) == 1
    assert releases[0]["rect"] == DESTINATION_RECT
    assert handoffs[0]["detail"]["released"] == {"ok": True, "reason": None}


def test_writeback_failure_is_recorded_alongside_its_trigger():
    out = _run_sandbox(scenario="writeback_fails")
    final = _assert_clean(out)
    assert final["standDowns"] == ["writebackFailed", NORMAL_EXIT_REASON], final["standDowns"]
    assert final["handlePresent"] is False


# --- write-back ordering and the opacity proofs -----------------------------------------


def test_writeback_precedes_forwarded_player_call():
    """§2.5 step 2: when the trigger is an unflagged player call, the write-back and
    the `CURRENT_PROGRAM` restore run inside the wrapper BEFORE `orig.apply`."""
    out = _run_sandbox(scenario="unflagged_player_call")
    final = _assert_clean(out)
    assert final["standDowns"] == ["unflaggedPlayerCall"]
    order = [c["m"] for c in out["callOrder"]]
    assert order.count("enable") == 1, order
    forwarded = order.index("enable")
    assert forwarded == len(order) - 1, ("the forwarded player call was not last", order)
    before = order[:forwarded]
    assert "uniform1f" in before, order
    assert "useProgram" in before, order
    # The CURRENT_PROGRAM restore is the last program switch of the write-back,
    # after every `uniform1f` (§2.5 step 3's poster restore may follow it).
    last_uniform = len(before) - 1 - before[::-1].index("uniform1f")
    last_use = len(before) - 1 - before[::-1].index("useProgram")
    assert last_use > last_uniform, order
    # Every program is back at its recorded rest Opacity.
    assert final["opacityAfter"] == [p["restOpacity"] for p in SETTLE_FRAME["programs"]]


def test_context_lost_exempts_writeback():
    """§2.5: the write-back is skipped only when `isContextLost()` is true, and the
    stand-down still completes with the hand-off."""
    out = _run_sandbox(scenario="context_lost")
    final = _assert_clean(out)
    assert final["standDowns"] == ["contextLost"], final["standDowns"]
    assert final["handlePresent"] is False
    assert [c["m"] for c in out["callOrder"]] == [], out["callOrder"]
    assert len([c for c in final["seamCalls"] if c["fn"] == "release"]) == 1


def test_override_applied_before_mapped_draw():
    """The override must be written while its program is CURRENT and before that
    program's draw. The fake drops a uniform write aimed at a non-current program,
    so a mis-ordered module leaves slot 4 at 1.0 instead of the override."""
    out = _run_sandbox(scenario="happy")
    final = _assert_clean(out)
    assert final["state"] == "LIVE"
    assert final["stats"]["opacityUnproven"] == [], final["stats"]["opacityUnproven"]
    assert final["opacityAfter"][4] == pytest.approx(SLOT4_OPACITY, abs=1e-12)
    # The slots with no override are left exactly as the frame set them.
    assert final["opacityAfter"][:4] == [p["restOpacity"] for p in SETTLE_FRAME["programs"][:4]]


def test_rest_opacity_not_one_is_unproven():
    """Opacity-plan §2: an override slot whose recorded rest `Opacity` is not 1.0
    cannot be patched multiplicatively; the slot is dropped with `rest-opacity`."""
    out = _run_sandbox(scenario="happy", frame=_mutate_frame(name="Opacity", value=0.5))
    final = _assert_clean(out)
    assert _unproven(final).get(4) == "rest-opacity", _unproven(final)


def test_mixfactor_between_zero_and_one_is_unproven():
    """Opacity-plan §1.2 (F-9): a `mixFactor` strictly between 0 and 1 leaves the
    sampler-visible texture undetermined, so that slot is unproven."""
    out = _run_sandbox(scenario="happy", frame=_mutate_frame(name="mixFactor", value=0.5))
    final = _assert_clean(out)
    assert _unproven(final).get(4) == "mixfactor", _unproven(final)


def test_mvp_decode_must_match_settled_rect():
    """The zero-replay geometry check: a draw whose `MVPMatrix` decodes somewhere
    other than its `slotRects` entry is unproven with `mvp`."""
    shifted = None
    for program in SETTLE_FRAME["programs"]:
        if program["prog"] == 4:
            shifted = list(next(u["value"] for u in program["uniforms"]
                                if u["name"] == "MVPMatrix"))
    shifted[12] += 0.25                        # ≈ 240 px to the right
    out = _run_sandbox(scenario="happy", frame=_mutate_frame(name="MVPMatrix", value=shifted))
    final = _assert_clean(out)
    assert _unproven(final).get(4) == "mvp", _unproven(final)


def test_unproven_slot_replays_opaque_and_notes():
    """A dropped override must not silently become a patch: the slot keeps its
    recorded rest Opacity and a `glreplay-opacity-unproven` note names it."""
    out = _run_sandbox(scenario="happy", frame=_mutate_frame(name="mixFactor", value=0.5))
    final = _assert_clean(out)
    notes = [n for n in final["notes"] if n["kind"] == "glreplay-opacity-unproven"]
    assert notes, final["notes"]
    assert [n["detail"]["slot"] for n in notes] == [4], notes
    assert final["state"] == "LIVE", final["state"]
    assert final["opacityAfter"][4] == 1, final["opacityAfter"]
    assert final["stats"]["opacityUnproven"] == [{"slot": 4, "reason": "mixfactor"}]


# --- regression cases for the round-1 fixes (Opus r2 spec 5) ----------------------------


def test_late_arm_pre_requirement_is_deferred_not_a_stand_down():
    """Plan §2.2 / r1 finding 3: an ARM-PRE requirement that appears a few ticks
    late must be RECORDED as pending, never retire a module that has not armed a
    context yet. The seam here arrives six ARM-PRE ticks after the hash."""
    out = _run_sandbox(scenario="happy", lateSeamTicks=6)
    final = _assert_clean(out)
    before = out["beforeSeam"]
    assert before["standDowns"] == [], before
    assert before["pending"] == "runtimeSeamAbsent", before
    assert before["state"] == "ARM-PRE", before
    # Once the seam appears the module arms and goes LIVE with nothing recorded.
    assert final["state"] == "LIVE", final["state"]
    assert final["standDowns"] == [], final["standDowns"]
    assert final["stats"]["pending"] is None, final["stats"]["pending"]
    assert final["handlePresent"] is True


def test_settle_to_hash_is_measured_after_the_hash_flips():
    """r1 finding 4: `settleToHashMs` was unreachable. The measured timeline flips
    the hash to `atScene` ~100 ms AFTER `ready`, so the value only exists once the
    LIVE poll sees the flip."""
    live_only = _run_sandbox(scenario="happy")
    assert live_only["final"]["stats"]["settleToHashMs"] is None, (
        "settleToHashMs reported before the hash ever flipped")
    out = _run_sandbox(scenario="hash_flip")
    final = _assert_clean(out)
    assert final["state"] == "LIVE", final["state"]
    value = final["stats"]["settleToHashMs"]
    assert isinstance(value, (int, float)) and value == value, value   # finite, not NaN
    assert value > 0, value
    assert final["stats"]["settleGapMs"] is not None


def test_double_pause_does_not_spawn_a_second_loop():
    """r1 finding 5: `pause()`/`resume()` must not leave two loops running. The
    paused loop is rAF-driven, so `stats().iter` must advance exactly once per tick
    however many times `pause()` was called."""
    out = _run_sandbox(scenario="pause_twice")
    final = _assert_clean(out)
    assert out["pausedIterDelta"] == out["pausedTicks"], (
        f"paused loop ticked {out['pausedIterDelta']}x over "
        f"{out['pausedTicks']} frames — duplicate loop?")
    assert out["resumedIterDelta"] == out["resumedTicks"], (
        f"resumed loop ticked {out['resumedIterDelta']}x over "
        f"{out['resumedTicks']} frames — duplicate loop?")
    assert final["standDowns"] == [], final["standDowns"]


def test_outstanding_sample_resolves_short_on_stand_down():
    """r1 finding 6: a `sample(n)` still collecting when the module stands down must
    RESOLVE with what it has, not hang. A short list is safe — the scorer fails
    closed on count (`INPAGE_MIN_SAMPLES`), so a truncated window can never read
    LIVE, and the probe keeps the diagnostic `n`."""
    out = _run_sandbox(scenario="sample_interrupted")
    final = _assert_clean(out)
    assert out["interruptedSamples"] is not None, "sample(24) never settled — it hung"
    assert out["interruptedSamples"] < 24, out["interruptedSamples"]
    assert final["standDowns"] == [NORMAL_EXIT_REASON], final["standDowns"]
    assert final["handlePresent"] is False


def test_second_magic_move_context_does_not_rearm_or_stand_down():
    """r1 closed check 3(d): v1 arms ONE boundary. A later Magic Move's new canvas
    and context must be ignored — not a second arm, and not an `unflaggedPlayerCall`
    either, since its calls are not on the armed context."""
    out = _run_sandbox(scenario="second_context")
    final = _assert_clean(out)
    assert out["secondContext"] is True
    assert final["state"] == "LIVE", final["state"]
    assert final["standDowns"] == [], final["standDowns"]
    assert final["eventKinds"].count("glreplay-arm") == 1, final["eventKinds"]
    assert final["handleScalars"]["canvasId"] == "0-canvas"


def test_happy_path_uses_the_current_segment_not_the_retained_fallback():
    """r2 spec 2: the `state.retained` fallback may only fire on a malformed final
    frame, and must say so. The measured settle frame is `clearColor,clear`
    delimited, so the fallback must not be taken."""
    out = _run_sandbox(scenario="happy")
    final = _assert_clean(out)
    assert "glreplay-retained-frame" not in final["eventKinds"], final["eventKinds"]
    assert final["stats"]["frameLen"] == SETTLE_FRAME["frameLen"]


def test_green_roi_is_plan_derived_and_reported_in_both_spaces():
    """Owner decision D1(a): the green ROI is the largest part of the front-most
    overlapping slot that is OFF the movie rect, inset 8 px. `stats()` must report
    the authored rect and the buffer ROI actually read under distinct names."""
    out = _run_sandbox(scenario="happy")
    stats = _assert_clean(out)["stats"]
    authored = stats["greenAuthored"]
    assert authored is not None, "no green ROI derived from the plan"
    assert authored["x"] == pytest.approx(796.7255, abs=0.01)
    assert authored["y"] == pytest.approx(680.9159, abs=0.01)
    assert authored["w"] == pytest.approx(337.0, abs=0.01)
    assert authored["h"] == pytest.approx(101.931, abs=0.01)
    roi = stats["greenRoi"]
    assert roi is not None and roi != authored, (
        "greenRoi must be the buffer ROI, not the authored rect")
    assert (roi["w"], roi["h"]) == (337, 102)
    # Drawing-buffer y is measured from the bottom.
    assert roi["y"] == 1080 - (round(authored["y"]) + roi["h"])


def test_proofs_leave_every_program_at_its_recorded_rest_opacity():
    """S3's headless D1, as a unit invariant. The opacity proofs probe each draw by
    writing `Opacity` (alpha=0 identity, ablation, restore). GLSL uniforms are
    STICKY per program and the measured frame re-sets `Opacity` for programs 0–3
    only (opacity-plan F-10), so a probe value left behind on program 4 survives
    into every later replay. After `proveOpacity`, every program must read back at
    the rest value captured before any probing — including a slot whose override
    was dropped as unproven."""
    out = _run_sandbox(scenario="happy")
    final = _assert_clean(out)
    stats = final["stats"]
    rest = stats["restOpacity"]
    after = stats["opacityAfterProofs"]
    assert after is not None, "opacityAfterProofs not published — the proofs never ran"
    assert rest == [p["restOpacity"] for p in SETTLE_FRAME["programs"]], rest
    assert after == rest, f"a probe value survived the proofs: rest={rest} after={after}"
    # This per-SLOT invariant is only sound while every draw has its own program;
    # with a shared program slots i and j report one value and it stays green while
    # the composite is wrong (Opus r3 spec 3). The shared case has its own test.
    assert stats.get("programsDistinct") is True, stats.get("programsDistinct")


def test_slot_unproven_after_the_probes_is_left_opaque_not_transparent():
    """The exact path S3 hit headlessly. A slot dropped at `mixfactor` never gets
    probed, but one dropped at `ablation` is dropped AFTER the alpha=0 identity
    probe has written 0.0 to its program — and program 4 is the one the recorded
    frame never re-sets, so that 0.0 is sticky. It must be restored, or the movie
    slot replays as a transparent hole and the oracle reads DEAD."""
    out = _run_sandbox(scenario="happy", debugForceFail="ablation")
    final = _assert_clean(out)
    assert _unproven(final).get(4) == "ablation", _unproven(final)
    assert final["state"] == "LIVE", final["state"]
    stats = final["stats"]
    assert stats["opacityAfterProofs"] == stats["restOpacity"], stats
    assert stats["opacityAfterProofs"][4] == 1, stats["opacityAfterProofs"]
    # And the replayed frame really is opaque there, not a transparent hole.
    assert final["opacityAfter"][4] == 1, final["opacityAfter"]


def test_debug_hooks_are_absent_on_the_normal_install_path():
    """§2.7: `debugForceFail` — and the `API.debug` replay hooks S3 needs — are
    seeded only from a pre-existing version-less `window.__OBED_GL_REPLAY__`, so no
    product injection can reach them."""
    out = _run_sandbox(scenario="happy")
    assert _assert_clean(out)["debugHooks"] == [], out["final"]["debugHooks"]
    # The seeded path is what the forced stand-downs rely on, so prove it works —
    # and that both hooks are gated on the same pre-seeded object, never one alone.
    forced = _run_sandbox(scenario="arm_only", debugForceFail="occlusionTooHigh")
    assert forced["final"]["debugHooks"] == ["debug", "debugForceFail"], \
        forced["final"]["debugHooks"]


def test_live_replay_writes_opacity_for_every_draw_not_just_overrides():
    """The LIVE-path half of the D1 fix, which the proofs' `finally` cannot reach.
    `replayFrame()` with no options must write an explicit `Opacity` for EVERY
    draw, not only for slots carrying an override. Program 4 is the one the
    recorded frame never re-sets, and with its override dropped as unproven
    nothing else writes it either — so if the replay skips it, the LIVE composite
    silently inherits whatever wrote last. Here an outside writer leaves 0 on it
    and one LIVE tick must restore the rest value."""
    out = _run_sandbox(scenario="dirty_unset_program", debugForceFail="ablation")
    final = _assert_clean(out)
    assert _unproven(final).get(4) == "ablation", _unproven(final)
    assert out["dirtied"] == 0, "the harness failed to dirty the uniform"
    assert out["liveTicked"] is True, "no LIVE tick ran, so the assertion below is vacuous"
    assert out["afterLiveTick"] == 1, (
        f"the LIVE replay left program 4 at {out['afterLiveTick']} — a non-override "
        "slot got no Opacity write, so the composite depends on the last writer")
    assert final["state"] == "LIVE", final["state"]


# --- shared-program frames (Opus r3 spec 1) ---------------------------------------------

SHARED_PROGRAM_SLOTS = (2, 3)
SHARED_PROGRAM_OPACITIES = (1.0, 0.6)


def _shared_program_frame() -> dict:
    """The settle frame with draws 2 and 3 bound to ONE program, carrying different
    in-frame `Opacity` values (1.0 then 0.6).

    The measured deck gives every draw its own program, so the fixture as recorded
    cannot express this — but Keynote reuses shaders, and a capture taken once per
    *slot* after a whole frame replays both draws at whichever value the frame set
    last. This variant is the only way S2 can see that.
    """
    frame = copy.deepcopy(SETTLE_FRAME)
    keep, share = SHARED_PROGRAM_SLOTS          # draw `share` moves onto `keep`'s program
    first, second = SHARED_PROGRAM_OPACITIES
    start = frame["drawIndices"][keep]          # exclusive: the kept slot's own draw
    end = frame["drawIndices"][share]           # inclusive: the moved slot's draw

    def retarget(call, value=None):
        for i, arg in enumerate(call["a"]):
            if isinstance(arg, dict) and arg.get("prog") == share:
                call["a"][i] = {"prog": keep, "name": arg["name"]}
        if call["m"] == "useProgram" and call["a"][0] == share:
            call["a"][0] = keep

    for call in frame["calls"][start + 1 : end + 1]:
        retarget(call)
    # Each draw keeps its OWN in-frame Opacity on the now-shared program.
    for index, (slot, opacity) in enumerate(zip(SHARED_PROGRAM_SLOTS, SHARED_PROGRAM_OPACITIES)):
        lo = 0 if slot == keep else start + 1
        hi = frame["drawIndices"][slot] + 1
        for call in frame["calls"][lo:hi]:
            if call["m"] == "uniform1f" and isinstance(call["a"][0], dict) \
                    and call["a"][0] == {"prog": keep, "name": "Opacity"}:
                call["a"][1] = opacity
    frame["draws"][share]["prog"] = keep
    return frame


EXPECTED_SHARED_DRAW_OPACITIES = {2: 1.0, 3: 0.6}


def test_shared_program_draws_replay_at_their_own_in_frame_opacity():
    """Opus r3 spec 1. Two draws on one program with different in-frame `Opacity`
    must each replay at the value the frame set for THAT draw. A rest capture taken
    once per slot at end of frame collapses both onto the last value, and the LIVE
    composite then differs from the player everywhere the first draw shows."""
    out = _run_sandbox(scenario="happy", frame=_shared_program_frame())
    final = _assert_clean(out)
    assert final["state"] == "LIVE", final["state"]
    assert final["drawnSlots"] == [0, 1, 2, 3, 4], final["drawnSlots"]
    executed = final["drawnOpacities"]
    for slot, expected in EXPECTED_SHARED_DRAW_OPACITIES.items():
        assert executed[slot] == pytest.approx(expected, abs=1e-9), (
            f"draw {slot} replayed at {executed[slot]}, not its own in-frame "
            f"{expected}: {executed}")
    # The capture that feeds the replay and the write-back must be per DRAW too.
    rest = final["stats"]["restOpacity"]
    assert len(rest) == len(SETTLE_FRAME["draws"])
    for slot, expected in EXPECTED_SHARED_DRAW_OPACITIES.items():
        assert rest[slot] == pytest.approx(expected, abs=1e-9), rest
    assert final["stats"].get("programsDistinct") is False, final["stats"].get("programsDistinct")


def test_programs_are_distinct_on_the_measured_frame():
    """The control for the case above: the recorded deck gives every draw its own
    program, so `programsDistinct` is true and the per-slot `opacityAfterProofs`
    invariant is sound here — it is NOT sound when this flag is false."""
    out = _run_sandbox(scenario="happy")
    final = _assert_clean(out)
    assert final["stats"].get("programsDistinct") is True, final["stats"].get("programsDistinct")
    assert final["drawnSlots"] == [0, 1, 2, 3, 4]
    assert final["drawnOpacities"][4] == pytest.approx(SLOT4_OPACITY, abs=1e-12)


def test_debug_replay_without_a_value_leaves_every_program_at_rest():
    """Opus r3 spec 2: `API.debug.replay({only: n})` with no `value` must not
    reproduce D1's shape through the very hook S3 drives the gate-3 readback with.

    Targets slot 4 deliberately. The recorded frame re-sets `Opacity` for programs
    0-3 on its own, so aiming at any of those would pass even on the broken shape;
    program 4 is the one where writing nothing is visible."""
    out = _run_sandbox(scenario="debug_replay_only", seedDebug=True)
    final = _assert_clean(out)
    assert out["debugPrograms"] == len(SETTLE_FRAME["draws"])
    # Every program is dirtied first, so "left at rest" cannot be satisfied by
    # writing nothing at all — which is exactly the shape being guarded against.
    assert out["dirtiedBefore"] == [0.5] * len(SETTLE_FRAME["programs"]), out["dirtiedBefore"]
    assert out["afterDebugReplay"] == final["stats"]["restOpacity"], out["afterDebugReplay"]
    assert out["afterDebugReplay"] == [p["restOpacity"] for p in SETTLE_FRAME["programs"]]


# --- S3 Q3 soak findings (s3-gates-r2.md N1–N3) -----------------------------------------


def _frames_replayed(call_order: list[dict]) -> int:
    """How many whole frames were replayed in this window. Every replay of the
    recorded frame begins with its `clearColor,clear` delimiter, so counting
    `clear` counts frames.

    Anchoring on the last `uniform1f` instead would be structurally broken: r3
    spec 1 requires every replay to write `Opacity` immediately BEFORE each draw,
    so the last uniform write always precedes the last draw and any such count is
    1 for every module that satisfies both D1 and r3 spec 1.
    """
    return [c["m"] for c in call_order].count("clear")


def _draws_in_final_frame(call_order: list[dict]) -> int:
    methods = [c["m"] for c in call_order]
    if "clear" not in methods:
        return 0
    last_clear = len(methods) - 1 - methods[::-1].index("clear")
    return methods[last_clear:].count("draw")


def test_live_loop_survives_end_of_media_and_keeps_sampling():
    """S3 N1 (high). The LIVE loop is rVFC-driven, and at end of media the browser
    stops delivering rVFC callbacks entirely — S3's soak froze `iter` at 1281 with
    the state still LIVE, the handle still published and `sample(n)` unable to ever
    resolve. The loop must fall back to rAF and keep replaying the last frame; the
    movie is over, so there is nothing new to upload."""
    out = _run_sandbox(scenario="video_ended")
    final = _assert_clean(out)
    assert out["endedSamples"] == 24, (
        f"sample(24) resolved with {out['endedSamples']} after end of media "
        "— the probe would hang or read short")
    assert out["iterDelta"] > 0, "the loop stopped ticking when rVFC went quiet"
    assert out["loopMode"] == "raf", out["loopMode"]
    assert out["videoEnded"] is True, out["videoEnded"]
    assert out["uploadsDelta"] == 0, (
        f"{out['uploadsDelta']} uploads after end of media — there is no new frame")
    assert final["standDowns"] == [], final["standDowns"]
    assert final["state"] == "LIVE", final["state"]
    assert final["handlePresent"] is True


def test_context_loss_stands_down_without_a_single_tick():
    """S3 N2 (high). The only `contextLost` check lived in the tick guards, so with
    the loop dead `loseContext()` produced no stand-down for seven minutes. The
    `webglcontextlost` event must retire the module on its own, with no rAF and no
    rVFC delivered at all after it fires."""
    out = _run_sandbox(scenario="context_lost_no_ticks")
    final = _assert_clean(out)
    assert out["ticksDelivered"] == 0
    assert final["standDowns"] == ["contextLost"], final["standDowns"]
    assert final["handlePresent"] is False, "the handle outlived the lost context"
    # A lost context exempts the write-back (§2.5) — nothing may be issued on it.
    assert [c["m"] for c in out["callOrder"]] == [], out["callOrder"]
    releases = [c for c in final["seamCalls"] if c["fn"] == "release"]
    assert len(releases) == 1, releases
    assert releases[0]["rect"] == DESTINATION_RECT


def test_context_lost_still_has_exactly_one_emitting_site():
    """N2's fix adds an event listener; it must route through the existing site
    rather than become a second one, or the coverage above stops being specific."""
    source = _js_source()
    name = _constant_for(source, "contextLost")
    assert name is not None, "contextLost is no longer bound to a constant"
    sites = _emitting_sites(source, name)
    assert len(sites) == 1, sites


def test_stand_down_on_a_live_context_leaves_the_clean_frame_composited():
    """S3 N3 (low). The stand-down restored the uniforms and the poster but never
    redrew, so the last thing on screen stayed the PATCHED frame — S3 measured
    (9,52,0) where the clean deck is (29,177,0). One rest replay after the
    write-back closes it."""
    out = _run_sandbox(scenario="gl_error_replay")
    final = _assert_clean(out)
    assert final["standDowns"] == ["glError"], final["standDowns"]
    assert final["drawnSlots"] == [0, 1, 2, 3, 4], final["drawnSlots"]
    rest = final["stats"]["restOpacity"]
    assert final["drawnOpacities"] == rest, (
        f"the composited frame is still patched: {final['drawnOpacities']} vs rest {rest}")
    # The window opens just before the erroring tick, so it holds that tick's own
    # replay plus exactly one more — the stand-down's rest replay — and that last
    # frame is complete.
    assert _frames_replayed(out["callOrder"]) == 2, (
        f"expected one LIVE tick plus exactly one rest replay, saw "
        f"{_frames_replayed(out['callOrder'])} frames")
    assert _draws_in_final_frame(out["callOrder"]) == len(SETTLE_FRAME["draws"])


def test_canvas_removal_does_not_replay_onto_a_detached_canvas():
    """The other half of N3: the rest replay is for a stand-down on a LIVE context.
    When the canvas has already been removed there is nothing to redraw onto, and
    issuing a frame at it would be pointless work on the hand-off path."""
    out = _run_sandbox(scenario="canvas_removed")
    final = _assert_clean(out)
    assert final["standDowns"] == [NORMAL_EXIT_REASON], final["standDowns"]
    assert _frames_replayed(out["callOrder"]) == 0, (
        "a frame was replayed onto a canvas that is no longer in the document")


# --- codex r1: caught GL failures, canvas qualification, cleanup edges ------------------


def test_recorded_draw_that_throws_without_a_gl_error_stands_down():
    """codex r1 spec 1. `replayFrame` turns a thrown recorded call into an `errs`
    count that every production caller discards, and a driver failure can throw
    with `getError()` still clean — so the exception is the ONLY evidence. It must
    take the single `glError` path, not vanish."""
    out = _run_sandbox(scenario="draw_throws")
    final = _assert_clean(out)
    assert out["glErrorAfter"] == 0, "the fake set a GL error; the test would pass for free"
    assert final["standDowns"] == ["glError"], final["standDowns"]
    assert final["state"] == "RETIRED", final["state"]
    assert final["handlePresent"] is False
    assert len([c for c in final["seamCalls"] if c["fn"] == "release"]) == 1


def test_read_pixels_throwing_during_arm_post_stands_down():
    """codex r1 spec 1, the other half: `sampleOnce` swallows a read failure into
    `bands = null`, `markerSwap` then reads `dark.length`, and that TypeError
    escapes `armPost` into the rAF callback — leaving the module stranded in
    ARM-POST with the seam never released and no handle ever published.

    The injection is scoped to reads of the DRAWING BUFFER. A throw on every read
    would be hit first by the poster snapshot, which reads through a bound
    framebuffer and has its own, more specific reason — `posterUnreadable`, covered
    by the `fboStatus` case — and would never reach the path this guards."""
    out = _run_sandbox(scenario="arm_only", readPixelsThrowsAtArmPost=True)
    final = _assert_clean(out)
    assert final["standDowns"] == ["glError"], final["standDowns"]
    assert final["state"] == "RETIRED", final["state"]
    assert final["handlePresent"] is False
    assert len([c for c in final["seamCalls"] if c["fn"] == "release"]) == 1


@pytest.mark.parametrize(
    "label,cfg",
    [
        ("bad_canvas_id", {"canvasId": "stage-canvas"}),
        ("connected_outside_stage", {"canvasOutsideStage": True}),
    ],
)
def test_canvas_that_fails_qualification_stands_down(label, cfg):
    """codex r1 spec 2. A context on a canvas with the wrong id, or on a connected
    canvas that is not under `#stage`, was silently ignored — the module then sat
    in ARM-PRE forever with no stand-down and the decoder never handed back. Both
    must reach the single `canvasShape` site."""
    out = _run_sandbox(scenario="arm_only", **cfg)
    final = _assert_clean(out)
    assert final["standDowns"] == ["canvasShape"], (label, final["standDowns"])
    assert final["state"] == "RETIRED", final["state"]
    assert final["handlePresent"] is False
    assert len([c for c in final["seamCalls"] if c["fn"] == "release"]) == 1


def test_context_lost_event_exempts_cleanup_before_is_context_lost_flips():
    """codex r1 spec 4. `standDown` recomputed the exemption from `isContextLost()`
    alone, but the event may arrive before that flag flips. The reason itself must
    carry the exemption, or the write-back and poster restore run on a dead
    context."""
    out = _run_sandbox(scenario="context_lost_event_only")
    final = _assert_clean(out)
    assert out["isContextLostStayedFalse"] is True, (
        "the fake flipped isContextLost(); this test would not exercise the edge")
    assert final["standDowns"] == ["contextLost"], final["standDowns"]
    assert final["state"] == "RETIRED", final["state"]
    assert [c["m"] for c in out["callOrder"]] == [], out["callOrder"]
    releases = [c for c in final["seamCalls"] if c["fn"] == "release"]
    assert len(releases) == 1 and releases[0]["rect"] == DESTINATION_RECT


def test_writeback_failure_still_restores_the_current_program():
    """codex r1 spec 5. If `uniform1f` throws, control skipped `useProgram(prev)`
    and the player inherited whichever replay program happened to be selected."""
    out = _run_sandbox(scenario="writeback_fails")
    final = _assert_clean(out)
    assert final["standDowns"] == ["writebackFailed", NORMAL_EXIT_REASON], final["standDowns"]
    # The recorded frame ends on `useProgram(null)`, so that is what the player
    # must get back — not the program the write-back died on.
    assert final["currentProgramSlot"] is None, final["currentProgramSlot"]
    releases = [c for c in final["seamCalls"] if c["fn"] == "release"]
    assert len(releases) == 1 and releases[0]["rect"] == DESTINATION_RECT
    assert final["handlePresent"] is False


def test_writeback_failure_on_the_unflagged_path_keeps_the_forwarded_call_last():
    """codex r1 spec 5, the ordering half: a throwing write-back must not reorder
    the stand-down around the player's own call."""
    out = _run_sandbox(scenario="writeback_fails_unflagged")
    final = _assert_clean(out)
    assert set(final["standDowns"]) == {"writebackFailed", "unflaggedPlayerCall"}, \
        final["standDowns"]
    order = [c["m"] for c in out["callOrder"]]
    assert order.count("enable") == 1, order
    assert order[-1] == "enable", ("the forwarded player call was not last", order)
    assert final["currentProgramSlot"] is None, final["currentProgramSlot"]
    assert len([c for c in final["seamCalls"] if c["fn"] == "release"]) == 1


def test_unwritable_prototype_method_refuses_installation():
    """codex r1 spec 6. The module is injected as a plain `<script>`, so it is not
    strict: assigning a wrapper over a non-writable prototype method fails SILENTLY.
    Nothing would then be captured and no reason would ever be emitted, so the
    module must read the assignment back and refuse to install."""
    out = _run_sandbox(scenario="install_only", nonWritableMethod="clear")
    final = out["final"]
    assert final["installThrew"] is None, (
        "the assignment threw — the sandbox is running the module in strict mode, "
        "which is not how a <script> behaves")
    assert final["standDowns"] == ["glReplayUnavailable"], final["standDowns"]
    assert final["state"] == "RETIRED", final["state"]
    assert final["handlePresent"] is False
    assert "glreplay-arm" not in final["eventKinds"], final["eventKinds"]
