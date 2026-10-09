"""`scripts/run_gates.sh` driven end to end against stub runs (no Chrome, no Keynote).

The script runs from a fake gate worktree whose `scripts/` holds stub versions of the live probe,
the P2 driver and the H.264 prewarm entry point (`src/` and `continuity_core_variants.py` are the
real ones, symlinked, because the checks import them). Each stub logs what it was asked to do to
an events file and behaves per `STUB_MODES` (artifact/out-dir stem -> mode):

- `pass`    write a passing artifact and exit 0 (P2: exit 1 with an empty log); the probe's artifact
            records `--skip-arms` as `skippedArms` and leaves those arms out, as the real probe does;
- `report`  (P2) print a well-formed 15-finding report whose red set is `STUB_P2_RED[<out-dir name>]`
            and whose `Freeze bracket:` header names the arm's own flags (or `STUB_P2_FREEZE`);
- `ignore-skip` / `lose-A` (probe) run every arm and record no skip / record the skip but drop arm A;
- `die`     kill its parent -- the per-run wrapper -- before the wrapper can write the status, as
            when a wrapper is killed or crashes mid-run;
- `foreign` publish a status carrying another round's nonce, then kill the wrapper;
- `hang`    start a child process and sleep, as a live probe holding Chrome does.

What is pinned here:
- a non-empty (or non-directory) `<outdir>` is refused before anything runs, so nothing from an
  earlier round can be read and nothing under output/ is ever removed; a run that does not write a
  fresh status (this round's nonce) still fails its check;
- the host arm matrix (owner decision 2026-10-09): 2560x1440 and 1600x1000 skip attach, B and Voff,
  1920x1080 skips C; every host arm runs at least once a round or the round is refused; a host gate
  passes only when its artifact records exactly that skip and holds exactly the other arms;
- the S0 deck red arms (S2, plan §3.4 Q3): every `DECK_ARMS` entry goes through the same queue as a host
  red run on its deck's own `html-unmodified` export, after the P2 host red arms and before the P2 arms,
  is checked after the wait in the same order, and runs in the full tier only;
- the P2 arm list: no `--strip bridge@8` arm, `--skip-freeze-bracket` on every arm but the two
  positive freeze-bracket arms (and refused on those), and the `Freeze bracket:` header checked;
- `--tier dev` runs the 1920x1080 + 1600x1000 host gates and three P2 arms, says DEV loudly and
  exits 10 on a pass (never 0);
- killing the queue owner (TERM/INT/HUP) leaves none of the queued runs or their children behind;
- `GATE_JOBS` outside 1..5 is refused before anything is launched, and above 3 warns loudly;
- the H.264 pattern cache is prewarmed (and logged) before the first timed run, and a round refuses to start (exit 2)
  when `OBED_H264_PATTERN_CACHE` is set, a duration has no usable cache key, or a second lookup is not a sha-verified
  hit of the prewarmed entry (Codex round 2);
- the load guard: a round refuses to start (exit 2) when the 1-minute load average (`sysctl -n vm.loadavg`, stubbed
  on PATH here so the real host's load never decides a test) exceeds `GATE_MAX_START_LOAD` (default 4), and the
  summary prints the load at start and end and the round's wall time.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "run_gates.sh"
PY = Path("/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python")
VIEWPORTS = ("2560x1440", "1600x1000", "1920x1080")

pytestmark = pytest.mark.skipif(not PY.exists(), reason=f"run_gates.sh runs its runs with {PY}")

_STUB_COMMON = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path

def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None

def event(text):
    with open(os.environ["STUB_EVENTS"], "a") as f:
        f.write(text + "\n")

def mode_of(stem):
    return json.loads(os.environ.get("STUB_MODES") or "{}").get(stem, os.environ.get("STUB_DEFAULT", "pass"))

def act(mode, out_stem_path):
    if mode == "die":
        os.kill(os.getppid(), signal.SIGKILL)
        time.sleep(1)
        sys.exit(0)
    if mode == "foreign":
        Path(str(out_stem_path) + ".rc").write_text("1-2-3 0\n")
        os.kill(os.getppid(), signal.SIGKILL)
        time.sleep(1)
        sys.exit(0)
    if mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", os.environ["STUB_MARKER"]])
        Path(os.environ["STUB_MARKER"], f"child-{child.pid}").touch()
        time.sleep(600)
'''

PROBE_STUB = _STUB_COMMON + r'''
artifact = Path(arg("--artifact"))
stem = artifact.stem
event(f"probe {stem} viewport={arg('--viewport')} skip={arg('--skip-arms')} start")
event(f"probeargs {stem} fixture={arg('--fixture')} index={arg('--original-index')} argv={json.dumps(sys.argv[1:])}")
mode = mode_of(stem)
act(mode, artifact.with_suffix(""))
given = (arg("--skip-arms") or "").split(",")
skip = [] if mode == "ignore-skip" else [n for n in ("A", "B", "C", "V", "Voff", "attach") if n in given]
d = {
    "status": "pass", "skippedArms": skip,
    "arms": {n: {} for n in ("A", "B", "C") if n not in skip and not (mode == "lose-A" and n == "A")},
    "visible": {n: {} for n in ("V", "Voff") if n not in skip},
}
if "attach" not in skip:
    d["attach"] = {}
artifact.write_text(json.dumps(d))
sys.exit(0)
'''

P2_STUB = _STUB_COMMON + r'''
out = Path(arg("--out-dir"))
event(f"p2 {out.name} start")
event("p2argv " + json.dumps(sys.argv[1:]))
mode = mode_of(out.name)
act(mode, out)
if mode != "report":
    sys.exit(1)
sys.path.insert(0, "scripts")
from obed_edom.live_continuity_js import js_sha256
red = set(json.loads(os.environ.get("STUB_P2_RED") or "{}").get(out.name, []))
auto = "--gl-replay" in sys.argv and sys.argv[sys.argv.index("--gl-replay") + 1] == "auto"
ids = ["glReplayCarry1to2" if auto else "refusedCarry1to2", *red - {"glReplayCarry1to2", "refusedCarry1to2"}]
ids += [f"filler{i}" for i in range(15 - len(ids))]
freeze = os.environ.get("STUB_P2_FREEZE") or (
    "skipped (--skip-freeze-bracket)" if "--skip-freeze-bracket" in sys.argv
    else "skipped (bridge disabled)" if "--disable-bridge34" in sys.argv else "run"
)
print(f"Core variant: none · injected core sha256: {js_sha256()}")
print(f"Strip: none · injected plan sha256: {'0' * 64}")
print(f"Freeze bracket: {freeze}")
print(f"success: **{not red}**")
print("Source unchanged: **True**")
for i in ids:
    print(f"- {i}: **{i not in red}**")
sys.exit(1 if red else 0)
'''

# Modes: `hit` (both lookups hit), `encoded` (first encodes, second hits), `fail`, `empty`, and the vacuous prewarms
# Codex round 2 named: `nokey` (cache I/O failed: encoded, no key), `off` (no cache at all), `miss-again` (the second
# lookup encodes again), `sha-drift` / `key-drift` (the second lookup hits a different entry), `partial` (one of two
# durations has no key).
PREWARM_STUB = r'''
import os

CALLS = [0]

def prewarm_h264_patterns(root):
    CALLS[0] += 1
    with open(os.environ["STUB_EVENTS"], "a") as f:
        f.write(f"prewarm {root.name}\n")
    mode = os.environ.get("STUB_PREWARM", "hit")
    second = CALLS[0] > 1
    record = {"seconds": 46.0333, "source": "cache" if mode == "hit" or second else "encoded",
              "cacheKey": "k" * 64, "sha256": "s" * 64}
    if mode == "fail":
        raise RuntimeError("ffmpeg encode failed")
    if mode == "empty":
        return []
    if mode == "nokey":
        record["cacheKey"] = None
    if mode == "off":
        record = {"seconds": 46.0333, "source": "off", "cacheKey": None}
    if mode == "miss-again" and second:
        record["source"] = "encoded"
    if mode == "sha-drift" and second:
        record["sha256"] = "t" * 64
    if mode == "key-drift" and second:
        record["cacheKey"] = "j" * 64
    if mode == "partial":
        return [record, {**record, "seconds": 12.5, "cacheKey": None}]
    return [record]
'''

SYSCTL_STUB = """#!/bin/sh
[ "$*" = "-n vm.loadavg" ] || exit 64
[ "$STUB_LOAD" = fail ] && exit 1
load=${STUB_LOAD:-0.50}
if [ -n "$STUB_LOAD_AFTER_PREWARM" ] && grep -q '^prewarm' "$STUB_EVENTS" 2>/dev/null; then load=$STUB_LOAD_AFTER_PREWARM; fi
echo "{ $load 9.99 9.99 }"
"""


@pytest.fixture
def gates(tmp_path: Path):
    """A fake gate worktree plus a runner; every stub process is killed at teardown whatever happens."""
    g = tmp_path / "gate"
    (g / "scripts").mkdir(parents=True)
    (g / "src").symlink_to(REPO / "src")
    (g / "scripts" / "continuity_core_variants.py").symlink_to(REPO / "scripts" / "continuity_core_variants.py")
    (g / "scripts" / "live_continuity_probe.py").write_text(PROBE_STUB)
    (g / "scripts" / "p2_recovery_html_adversarial.py").write_text(P2_STUB)
    (g / "scripts" / "p2_recovery_html_dissolve_live.py").write_text(PREWARM_STUB)
    out = tmp_path / "out"
    marker = tmp_path / "marker"
    marker.mkdir()
    events = tmp_path / "events.txt"
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    (stub_bin / "sysctl").write_text(SYSCTL_STUB)
    (stub_bin / "sysctl").chmod(0o755)

    def env(**extra: str) -> dict[str, str]:
        drop = (
            "GATE_JOBS", "GATE_MAX_START_LOAD", "OBED_H264_PATTERN_CACHE", "STUB_MODES", "STUB_DEFAULT", "STUB_PREWARM",
            "STUB_P2_RED", "STUB_P2_FREEZE", "STUB_LOAD", "STUB_LOAD_AFTER_PREWARM", "GATE_SETTLE_S",
        )
        base = {k: v for k, v in os.environ.items() if k not in drop}
        base["PATH"] = f"{stub_bin}{os.pathsep}{base.get('PATH', '')}"
        return {**base, "STUB_EVENTS": str(events), "STUB_MARKER": str(marker), **extra}

    def run(
        *args: str, timeout: float = 120, script: Path = SCRIPT, outdir: Path = out, **extra: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/zsh", str(script), str(g), str(outdir), *args], env=env(**extra), capture_output=True, text=True,
            timeout=timeout,
        )

    def start(**extra: str) -> subprocess.Popen[str]:
        """Output goes to a file: a leaked run would hold a pipe open and hang the reader."""
        with open(tmp_path / "gates.out", "w") as sink:
            return subprocess.Popen(
                ["/bin/zsh", str(SCRIPT), str(g), str(out)], env=env(**extra), stdout=sink, stderr=subprocess.STDOUT, text=True,
            )

    def events_list() -> list[str]:
        return events.read_text().splitlines() if events.exists() else []

    def survivors() -> list[str]:
        found = subprocess.run(["pgrep", "-fl", str(tmp_path)], capture_output=True, text=True).stdout
        return [line for line in found.splitlines() if line.strip()]

    def patched(old: str, new: str) -> Path:
        """A copy of run_gates.sh with one exact line changed (the copy runs from the fake worktree)."""
        text = SCRIPT.read_text()
        assert text.count(old) == 1, old
        copy = tmp_path / "run_gates_patched.sh"
        copy.write_text(text.replace(old, new))
        return copy

    yield {
        "g": g, "out": out, "marker": marker, "run": run, "start": start, "events": events_list, "survivors": survivors,
        "patched": patched, "tmp": tmp_path,
    }
    subprocess.run(["pkill", "-KILL", "-f", str(tmp_path)], capture_output=True)


def _nonce(stdout: str) -> str:
    match = re.search(r"^round nonce (\S+)$", stdout, re.M)
    assert match, stdout
    return match.group(1)


@pytest.mark.parametrize("jobs", ["1", "5"])
def test_a_fresh_round_publishes_this_round_nonce_and_the_host_checks_read_it(gates, jobs: str) -> None:
    done = gates["run"](GATE_JOBS=jobs)
    nonce = _nonce(done.stdout)
    for v in VIEWPORTS:
        assert f"HOST {v}: pass" in done.stdout, done.stdout
        assert f"GATE FAILED: HOST {v}" not in done.stdout
        assert (gates["out"] / f"host-{v}.rc").read_text().strip() == f"{nonce} 0"
    assert (gates["out"] / "p2--wait-profileslow--skip-freeze-bracket.rc").read_text().strip() == f"{nonce} 1"
    assert "[P2 --wait-profile slow --skip-freeze-bracket] exit=1 " in done.stdout
    assert not list(gates["out"].glob("*.rc.tmp")), "the status is published by rename"
    assert done.returncode != 0, "the stub red arms and P2 arms cannot match their registered sets"


@pytest.mark.parametrize("leftover", ["host-2560x1440.rc", "host-2560x1440.json", ".hidden", "p2--wait-profileslow/report.json"])
def test_a_non_empty_outdir_is_refused_before_anything_runs(gates, leftover: str) -> None:
    """Owner rule: nothing under output/ is ever removed, so an earlier round's files are never
    cleared -- the round refuses to start instead, and leaves every file as it was."""
    out = gates["out"]
    stale = out / leftover
    stale.parent.mkdir(parents=True)
    stale.write_text("0\n")
    done = gates["run"](timeout=20)
    assert done.returncode == 2
    assert f"outdir {out} exists and is not an empty directory" in done.stderr
    assert gates["events"]() == [], "not even the prewarm runs"
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [leftover]
    assert stale.read_text() == "0\n"


def test_an_outdir_that_is_a_file_is_refused(gates) -> None:
    gates["out"].write_text("not a directory")
    done = gates["run"](timeout=20)
    assert done.returncode == 2 and "is not an empty directory" in done.stderr
    assert gates["events"]() == []


def test_positive_control_an_existing_empty_outdir_is_accepted(gates) -> None:
    gates["out"].mkdir()
    done = gates["run"]()
    assert "round nonce " in done.stdout and "HOST 1920x1080: pass" in done.stdout, done.stdout + done.stderr


def test_a_run_that_writes_no_status_fails_closed_even_with_a_passing_artifact(gates) -> None:
    """The nonce check stays as defence in depth: a wrapper that dies before publishing its
    status fails its check, whatever the artifact says."""
    done = gates["run"](STUB_MODES=json.dumps({"host-2560x1440": "die", "p2--wait-profileslow--skip-freeze-bracket": "die"}))
    assert "GATE FAILED: HOST 2560x1440 exit missing" in done.stdout, done.stdout
    assert "[P2 --wait-profile slow --skip-freeze-bracket] exit=missing" in done.stdout
    assert "GATE FAILED: P2 --wait-profile slow --skip-freeze-bracket" in done.stdout
    assert "HOST 1600x1000: pass" in done.stdout, "the other runs are unaffected"
    assert done.returncode == 1


def test_a_status_from_another_round_fails_closed(gates) -> None:
    done = gates["run"](STUB_MODES=json.dumps({"host-1600x1000": "foreign", "host-red--strip bridge@8".replace(" ", ""): "foreign"}))
    assert "GATE FAILED: HOST 1600x1000 exit stale(1-2-3 0)" in done.stdout, done.stdout
    assert "[HOST --strip bridge@8] no fresh status (stale(1-2-3 0)) -> MISMATCH" in done.stdout
    assert "GATE FAILED: HOST red --strip bridge@8" in done.stdout


@pytest.mark.parametrize(("sig", "code"), [(signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129)])
def test_killing_the_queue_owner_leaves_no_run_or_child_behind(gates, sig: signal.Signals, code: int) -> None:
    proc = gates["start"](GATE_JOBS="3", STUB_DEFAULT="hang")
    try:
        deadline = time.monotonic() + 30
        while len(list(gates["marker"].glob("child-*"))) < 3:
            assert proc.poll() is None, "the round ended before its runs started"
            assert time.monotonic() < deadline, f"runs never started: {gates['events']()}"
            time.sleep(0.05)
        time.sleep(0.3)
        started = [e for e in gates["events"]() if e.endswith(" start")]
        assert len(started) == 3, f"GATE_JOBS=3 caps the queue: {started}"
        assert len(gates["survivors"]()) > 3, "the stubs and their children are running"
        proc.send_signal(sig)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    deadline = time.monotonic() + 10
    while gates["survivors"]() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert gates["survivors"]() == []
    assert proc.returncode == code


@pytest.mark.parametrize("jobs", ["0", "6", "10", "abc", "3x", " 3", "-1", "1.5"])
def test_gate_jobs_outside_one_to_five_is_refused_before_anything_runs(gates, jobs: str) -> None:
    done = gates["run"](timeout=20, GATE_JOBS=jobs)
    assert done.returncode == 2
    assert f"GATE_JOBS must be an integer in 1..5, got '{jobs}'" in done.stderr
    assert gates["events"]() == []
    assert not gates["out"].exists()


def test_the_pattern_cache_is_prewarmed_and_verified_before_the_first_timed_run(gates) -> None:
    done = gates["run"](STUB_PREWARM="encoded")
    events = gates["events"]()
    assert events[:2] == ["prewarm html-unmodified", "prewarm html-unmodified"], "the fill, then the verifying lookup"
    assert all(not e.startswith("prewarm") for e in events[2:])
    assert len([e for e in events if e.endswith(" start")]) == 3 + 5 + 22 + 8
    assert f"h264 pattern prewarm 46.0333s: encoded key={'k' * 64}" in done.stdout
    assert f"h264 pattern cache verified 46.0333s: hit key={'k' * 64} sha256={'s' * 64}" in done.stdout
    assert "cache hit" in gates["run"](outdir=gates["tmp"] / "out2").stdout


@pytest.mark.parametrize("mode", ["fail", "empty"])
def test_a_failed_prewarm_launches_nothing(gates, mode: str) -> None:
    done = gates["run"](STUB_PREWARM=mode)
    assert done.returncode == 2
    assert "H.264 pattern prewarm FAILED; no run launched" in done.stdout
    assert gates["events"]() == ["prewarm html-unmodified"]


@pytest.mark.parametrize(("mode", "why"), [
    ("nokey", "no usable pattern cache key for [46.0333] s"),
    ("off", "no usable pattern cache key for [46.0333] s"),
    ("partial", "no usable pattern cache key for [12.5] s"),
])
def test_known_bad_a_prewarm_with_no_usable_cache_key_launches_nothing(gates, mode: str, why: str) -> None:
    """Codex round-2 MAJOR: a prewarm that "succeeds" without a cache key (cache I/O failed, or no
    cache) leaves every later P2 arm to encode during the concurrent timed captures."""
    done = gates["run"](STUB_PREWARM=mode)
    assert done.returncode == 2, done.stdout + done.stderr
    assert why in done.stderr, done.stderr
    assert "H.264 pattern prewarm FAILED; no run launched" in done.stdout
    assert gates["events"]() == ["prewarm html-unmodified"]


@pytest.mark.parametrize("mode", ["miss-again", "sha-drift", "key-drift"])
def test_known_bad_a_second_lookup_that_is_not_a_verified_hit_launches_nothing(gates, mode: str) -> None:
    done = gates["run"](STUB_PREWARM=mode)
    assert done.returncode == 2
    assert "pattern cache re-lookup for 46.0333 s is not a sha-verified hit of the prewarmed entry" in done.stderr
    assert gates["events"]() == ["prewarm html-unmodified", "prewarm html-unmodified"]


@pytest.mark.parametrize("value", ["off", "", "on"])
def test_known_bad_a_round_with_the_pattern_cache_env_set_is_refused_before_anything_runs(gates, value: str) -> None:
    """`OBED_H264_PATTERN_CACHE=off` makes every P2 arm encode; any other value is invalid in P2 too."""
    done = gates["run"](timeout=20, OBED_H264_PATTERN_CACHE=value)
    assert done.returncode == 2
    assert f"OBED_H264_PATTERN_CACHE is set ('{value}')" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


# --------------------------------------------------------------------------
# Load guard (coordinator, 2026-10-09): a round started 1 min after a full `pytest -n auto` (5-min load 33)
# produced a load-induced host red mismatch. No automatic retries.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("load", "limit"), [("4.01", None), ("33.70", None), ("2.50", "2"), ("0.51", "0.5")])
def test_known_bad_a_loaded_host_is_refused_before_anything_runs(gates, load: str, limit: str | None) -> None:
    extra = {"STUB_LOAD": load} | ({"GATE_MAX_START_LOAD": limit} if limit else {})
    done = gates["run"](timeout=20, **extra)
    assert done.returncode == 2
    assert f"1-minute load average {load} exceeds GATE_MAX_START_LOAD={limit or 4}" in done.stderr, done.stderr
    assert gates["events"]() == [] and not gates["out"].exists(), "not even the prewarm runs"


@pytest.mark.parametrize(("load", "limit"), [("4.00", None), ("3.99", None), ("0.00", None), ("7.5", "8")])
def test_positive_control_a_host_at_or_under_the_limit_starts(gates, load: str, limit: str | None) -> None:
    extra = {"STUB_LOAD": load} | ({"GATE_MAX_START_LOAD": limit} if limit else {})
    done = gates["run"](**extra)
    assert f"load average (1 min) at start {load} (GATE_MAX_START_LOAD {limit or 4})" in done.stdout, done.stderr
    assert gates["events"]()[0] == "prewarm html-unmodified"
    assert re.search(rf"^load average \(1 min\) at start {re.escape(load)}, at launch {re.escape(load)}, at end {re.escape(load)}; wall \d+s$",
                     done.stdout, re.M), done.stdout


def test_known_bad_load_that_does_not_settle_after_the_prewarm_launches_no_timed_run(gates) -> None:
    """Codex r3 MAJOR: a cold prewarm's ffmpeg encode can push the load over the limit after the start check passed,
    so the load is re-checked (with a bounded settle wait) right before the first queued run."""
    done = gates["run"](timeout=30, STUB_LOAD="1.00", STUB_LOAD_AFTER_PREWARM="9.50", GATE_SETTLE_S="0")
    assert done.returncode == 2
    assert "1-minute load average 9.50 still exceeds GATE_MAX_START_LOAD=4 0s after the prewarm" in done.stderr, done.stderr
    assert all(e.startswith("prewarm") for e in gates["events"]()), gates["events"]()


def test_the_settle_wait_never_sleeps_past_its_deadline(gates) -> None:
    """Codex r4: a fixed 5 s sleep overshot a GATE_SETTLE_S that is not a multiple of 5."""
    start = time.monotonic()
    done = gates["run"](timeout=30, STUB_LOAD="1.00", STUB_LOAD_AFTER_PREWARM="9.50", GATE_SETTLE_S="2")
    elapsed = time.monotonic() - start
    assert done.returncode == 2
    assert "still exceeds GATE_MAX_START_LOAD=4 2s after the prewarm" in done.stderr, done.stderr
    assert elapsed < 4.5, f"settle wait overshot its 2 s deadline: round took {elapsed:.1f} s"


def test_positive_control_load_that_stays_low_after_the_prewarm_launches(gates) -> None:
    done = gates["run"](STUB_LOAD="1.00", STUB_LOAD_AFTER_PREWARM="2.00", GATE_SETTLE_S="0")
    assert "load average (1 min) at launch 2.00" in done.stdout, done.stderr
    assert any(not e.startswith("prewarm") for e in gates["events"]())


def test_known_bad_an_unreadable_load_average_is_refused(gates) -> None:
    done = gates["run"](timeout=20, STUB_LOAD="fail")
    assert done.returncode == 2
    assert "cannot read the 1-minute load average (sysctl -n vm.loadavg)" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


@pytest.mark.parametrize("limit", ["four", "-1", "1e3", "4.", ".5", " 4"])
def test_known_bad_a_malformed_load_limit_is_refused(gates, limit: str) -> None:
    done = gates["run"](timeout=20, GATE_MAX_START_LOAD=limit)
    assert done.returncode == 2
    assert "GATE_MAX_START_LOAD must be a non-negative number" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


GATE_JOBS_WARNING = (
    "GATE_JOBS>3 is NOT qualified on this machine (2026-10-09: 5-wide pushed the P2 slide-3 restart observation to "
    "0.479 s vs the 0.35 s limit and reddened 3->4)"
)


@pytest.mark.parametrize(("jobs", "warned"), [("4", True), ("5", True), ("3", False), ("1", False), (None, False)])
def test_gate_jobs_above_three_warns_loudly_but_still_runs(gates, jobs: str | None, warned: bool) -> None:
    done = gates["run"](**({"GATE_JOBS": jobs} if jobs else {}))
    assert (GATE_JOBS_WARNING in done.stdout) is warned
    if warned:
        assert f"## WARNING: GATE_JOBS={jobs}. {GATE_JOBS_WARNING}" in done.stdout
    assert gates["events"]()[0] == "prewarm html-unmodified", "a warning, never a refusal"


# --------------------------------------------------------------------------
# Owner decision 2026-10-09: the arm matrix, the P2 arm list and the tiers.
# --------------------------------------------------------------------------

FULL_HOST_SKIPS = {"2560x1440": "attach,B,Voff", "1600x1000": "attach,B,Voff", "1920x1080": "C"}
HOST_RED_STEMS = {
    "host-red--core-variantstash-any", "host-red--stripbridge@8", "host-red--stripretire@2", "host-red--striprestart@6",
    "host-red--stripglReplay@2--gl-replayauto",
}
FULL_P2_ARMS = [
    ["--wait-profile", "fast"],
    ["--wait-profile", "fast", "--disable-bridge34", "--skip-freeze-bracket"],
    ["--wait-profile", "slow", "--skip-freeze-bracket"],
    ["--wait-profile", "fast", "--core-variant", "stash-any", "--skip-freeze-bracket"],
    ["--wait-profile", "fast", "--strip", "glReplay@2", "--skip-freeze-bracket"],
    ["--wait-profile", "fast", "--strip", "restart@6", "--skip-freeze-bracket"],
    ["--wait-profile", "fast", "--gl-replay", "auto"],
    ["--wait-profile", "fast", "--gl-replay", "auto", "--strip", "glReplay@2", "--skip-freeze-bracket"],
]
DEV_P2_ARMS = [FULL_P2_ARMS[0], FULL_P2_ARMS[1], FULL_P2_ARMS[6]]
DECK_ARMS = [
    ("D1", "--strip bridge@2"), ("D1", "--strip bridge@4"), ("D1", "--strip pin@6"),
    ("D2", "--strip bridge@2"), ("D2", "--strip restart@4"), ("D2", "--strip pin@6"), ("D2", "--strip bridge@8"),
    ("D3", "--strip pin@2"), ("D3", "--strip bridge@2"), ("D3", "--strip retire@4"), ("D3", "--strip pin@4"),
    ("D3", "--strip bridge@6"),
    ("D4", "--core-variant wrong-instance"), ("D4", "--core-variant fifo-reuse"), ("D4", "--strip bridge@3"),
    ("D4", "--strip pin@5"),
    ("D5", "--core-variant stash-any"), ("D5", "--core-variant fifo-reuse"), ("D5", "--strip pin@2"), ("D5", "--strip pin@4"),
    ("D6", "--strip bridge@2"), ("D6", "--strip retire@8"),
]
DECK_RED_STEMS = [f"host-red{deck}{args.replace(' ', '')}" for deck, args in DECK_ARMS]
ARMS = ("A", "B", "C", "V", "Voff", "attach")


def _probe_runs(events: list[str]) -> dict[str, tuple[str, str]]:
    runs = {}
    for e in events:
        m = re.fullmatch(r"probe (\S+) viewport=(\S+) skip=(\S+) start", e)
        if m:
            runs[m.group(1)] = (m.group(2), m.group(3))
    return runs


def _p2_argvs(events: list[str]) -> list[list[str]]:
    out = []
    for e in events:
        if e.startswith("p2argv "):
            argv = json.loads(e[len("p2argv "):])
            assert argv[:3] == ["--reuse-export", "--disposable", "--out-dir"]
            out.append(argv[4:])
    return out


def _p2_name(argv: list[str]) -> str:
    return "p2" + "".join(argv)


def test_the_full_round_host_arm_matrix(gates) -> None:
    done = gates["run"](GATE_JOBS="1")
    runs = _probe_runs(gates["events"]())
    assert {k: v for k, v in runs.items() if k.startswith("host-") and not k.startswith("host-red")} == {
        f"host-{v}": (v, skip) for v, skip in FULL_HOST_SKIPS.items()
    }
    assert {k: v for k, v in runs.items() if k.startswith("host-red")} == {
        s: ("1920x1080", "None") for s in HOST_RED_STEMS | set(DECK_RED_STEMS)
    }
    ran = {name: [v for v, skip in FULL_HOST_SKIPS.items() if name not in skip.split(",")] for name in ARMS}
    assert ran == {
        "A": list(FULL_HOST_SKIPS), "V": list(FULL_HOST_SKIPS), "C": ["2560x1440", "1600x1000"],
        "B": ["1920x1080"], "Voff": ["1920x1080"], "attach": ["1920x1080"],
    }, "attach once; B and Voff at 1920 only; C at 2560 and 1600 (host red bridge@8 covers 1920)"
    for v in FULL_HOST_SKIPS:
        assert f"HOST {v}: pass" in done.stdout and f"GATE FAILED: HOST {v}" not in done.stdout, done.stdout
    assert done.stdout.count("attach skipped by flag") == 2 and done.stdout.count("C skipped by flag") == 1


@pytest.mark.parametrize(
    ("mode", "problem"),
    [("ignore-skip", "inventory: skippedArms [] != ['C']"), ("lose-A", "inventory: A missing")],
)
def test_known_bad_a_host_artifact_whose_inventory_disagrees_with_the_skip_fails(gates, mode: str, problem: str) -> None:
    """A skipped arm is never a pass of that arm, and an arm that should have run must be there."""
    done = gates["run"](STUB_MODES=json.dumps({"host-1920x1080": mode}))
    assert "HOST 1920x1080: pass" in done.stdout, "the artifact's own status says pass"
    assert problem in done.stdout, done.stdout
    assert "GATE FAILED: HOST 1920x1080 status" in done.stdout
    assert "GATE FAILED: HOST 2560x1440" not in done.stdout


@pytest.mark.parametrize(
    ("matrix", "arm"),
    [
        ("2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C,B", "B"),
        ("2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C,Voff", "Voff"),
        ("2560x1440 attach,B,Voff,C 1600x1000 attach,B,Voff,C 1920x1080 C", "C"),
        ("2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C,attach", "attach"),
    ],
)
def test_known_bad_a_matrix_that_drops_a_host_arm_from_the_round_is_refused(gates, matrix: str, arm: str) -> None:
    script = gates["patched"](
        "typeset -A HOST_SKIP=(2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C)",
        f"typeset -A HOST_SKIP=({matrix})",
    )
    done = gates["run"](script=script, timeout=20)
    assert done.returncode == 2
    assert f"host arm {arm} runs in no full-tier host gate" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


def test_known_bad_the_dev_tier_is_held_to_the_same_coverage(gates) -> None:
    """In dev only 1920x1080 and 1600x1000 run, so C must run at 1600x1000."""
    script = gates["patched"](
        "typeset -A HOST_SKIP=(2560x1440 attach,B,Voff 1600x1000 attach,B,Voff 1920x1080 C)",
        "typeset -A HOST_SKIP=(2560x1440 attach,B,Voff 1600x1000 attach,B,Voff,C 1920x1080 C)",
    )
    assert gates["run"](script=script, timeout=20).returncode != 2, "full still runs C at 2560x1440"
    done = gates["run"]("--tier", "dev", script=script, timeout=20, outdir=gates["tmp"] / "dev-out")
    assert done.returncode == 2 and "host arm C runs in no dev-tier host gate" in done.stderr


def _probe_args(events: list[str]) -> dict[str, tuple[str, str, list[str]]]:
    runs = {}
    for e in events:
        m = re.fullmatch(r"probeargs (\S+) fixture=(\S+) index=(\S+) argv=(.+)", e)
        if m:
            runs[m.group(1)] = (m.group(2), m.group(3), json.loads(m.group(4)))
    return runs


def test_the_deck_red_arms_run_on_their_own_export_through_the_queue_in_order(gates) -> None:
    """S2 (plan §3.4 Q3): the 22 S0 deck red arms are host red runs on the deck's `html-unmodified`
    export (both fixture and original index), launched after the P2 host red arms and before the P2
    arms, and checked after the wait in the same order."""
    done = gates["run"](GATE_JOBS="1")
    events = gates["events"]()
    starts = [e.split()[1] for e in events if e.endswith(" start")]
    p2_host_red = [s for s in starts if s.startswith("host-red--")]
    assert [s for s in starts if s.startswith("host-redD")] == DECK_RED_STEMS
    assert starts.index(DECK_RED_STEMS[0]) == starts.index(p2_host_red[-1]) + 1
    assert starts.index(DECK_RED_STEMS[-1]) + 1 == next(i for i, s in enumerate(starts) if s.startswith("p2"))
    args = _probe_args(events)
    for (deck, arm), stem in zip(DECK_ARMS, DECK_RED_STEMS, strict=True):
        fixture, index, argv = args[stem]
        assert Path(fixture).parts[-3:] == ("qual-decks", deck, "html-unmodified"), fixture
        assert index == f"{fixture}/index.html"
        assert argv[-len(arm.split()):] == arm.split()
    for stem in HOST_RED_STEMS:
        assert Path(args[stem][0]).parts[-2:] == ("html-adversarial", "html-player")
    failed = [line for line in done.stdout.splitlines() if line.startswith("    GATE FAILED: HOST red D")]
    assert failed == [f"    GATE FAILED: HOST red {deck} {arm}" for deck, arm in DECK_ARMS], "a stub artifact is no red artifact"
    first_deck_check = done.stdout.index("GATE FAILED: HOST red D1 --strip bridge@2")
    assert done.stdout.index("GATE FAILED: HOST red --strip glReplay@2 --gl-replay auto") < first_deck_check
    assert first_deck_check < done.stdout.index("[P2 --wait-profile fast]")


def test_known_bad_a_deck_red_run_that_writes_no_status_fails_closed(gates) -> None:
    done = gates["run"](STUB_MODES=json.dumps({"host-redD4--core-variantwrong-instance": "die"}))
    assert "[HOST D4 --core-variant wrong-instance] no fresh status (missing) -> MISMATCH" in done.stdout, done.stdout
    assert "GATE FAILED: HOST red D4 --core-variant wrong-instance" in done.stdout


def test_the_full_round_p2_arm_list(gates) -> None:
    gates["run"](GATE_JOBS="1")
    argvs = _p2_argvs(gates["events"]())
    assert argvs == FULL_P2_ARMS
    assert not any("bridge@8" in a for argv in argvs for a in argv), "P2 --strip bridge@8 == --disable-bridge34, dropped"
    bracket = [argv for argv in argvs if "--skip-freeze-bracket" not in argv]
    assert bracket == [["--wait-profile", "fast"], ["--wait-profile", "fast", "--gl-replay", "auto"]]


def test_the_registered_sets_no_longer_carry_the_skipped_freeze_finding() -> None:
    text = SCRIPT.read_text()
    assert "freezeControlCaughtByCounter" not in text
    assert 'p2 full "refusedCarry1to2 overlayRemovedOnLeave preserveDidNotBlockRestart continueThroughMovingMagicMove3to4 noStrayVideo" "" --wait-profile fast --core-variant stash-any' in text
    assert 'p2 full "" "" --wait-profile fast --strip restart@6' in text


def test_the_p2_red_arms_carry_the_owner_approved_v6_registrations() -> None:
    """S2 (owner-approved 2026-10-09): the four P2 red arms whose sets the v6 core changed, each with
    its reason and the pre-rebase control evidence path written beside it."""
    lines = SCRIPT.read_text().splitlines()
    registered = {
        ("--core-variant", "stash-any", ""): (
            "refusedCarry1to2 overlayRemovedOnLeave preserveDidNotBlockRestart continueThroughMovingMagicMove3to4 noStrayVideo"
        ),
        ("--strip", "glReplay@2", ""): "refusedCarry1to2 preserveDidNotBlockRestart",
        ("--strip", "restart@6", ""): "",
        ("--strip", "glReplay@2", "--gl-replay auto "): "glReplayCarry1to2 preserveDidNotBlockRestart",
    }
    for (flag, value, gl), red in registered.items():
        line = f'p2 full "{red}" "" --wait-profile fast {gl}{flag} {value} --skip-freeze-bracket'
        assert lines.count(line) == 1, line
        comment = []
        for above in reversed(lines[:lines.index(line)]):
            if not above.startswith("#"):
                break
            comment.insert(0, above)
        text = " ".join(comment)
        assert "owner-approved 2026-10-09" in text and "output/evidence/s2-dev/p2-4a2ea70f/" in text, line
        assert "p2ctrl-089a0393" in text, line


@pytest.mark.parametrize(
    "line",
    ["p2 dev \"\" \"\" --wait-profile fast\n", "p2 dev \"\" \"\" --wait-profile fast --gl-replay auto\n"],
)
def test_known_bad_skip_freeze_bracket_on_a_positive_bracket_arm_is_refused(gates, line: str) -> None:
    script = gates["patched"](line, line.replace("\n", " --skip-freeze-bracket\n"))
    done = gates["run"](script=script, timeout=20)
    assert done.returncode == 2
    assert "--skip-freeze-bracket on a positive freeze-bracket arm is refused" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


def test_known_bad_skip_freeze_bracket_on_a_slow_gl_auto_arm_is_refused(gates) -> None:
    """Codex round 2: `slow` alone no longer authorises the skip -- a positive gl-auto arm runs the
    WebGL bracket whatever its wait profile, the same rule P2 itself enforces. The unpatched slow DOM
    arm (`--wait-profile slow --skip-freeze-bracket`) is the positive control: every default round
    above runs it."""
    line = "p2 full \"\" \"\" --wait-profile slow --skip-freeze-bracket\n"
    script = gates["patched"](line, line.replace("slow", "slow --gl-replay auto"))
    done = gates["run"](script=script, timeout=20)
    assert done.returncode == 2
    assert "--skip-freeze-bracket on a positive freeze-bracket arm is refused" in done.stderr
    assert gates["events"]() == [] and not gates["out"].exists()


def _dev_red() -> str:
    return json.dumps({_p2_name(DEV_P2_ARMS[1]): ["continueThroughMovingMagicMove3to4"]})


def test_the_dev_tier_runs_its_subset_and_a_pass_exits_10(gates) -> None:
    done = gates["run"]("--tier", "dev", GATE_JOBS="1", STUB_MODES=json.dumps({_p2_name(a): "report" for a in DEV_P2_ARMS}),
                        STUB_P2_RED=_dev_red())
    events = gates["events"]()
    assert _probe_runs(events) == {"host-1920x1080": ("1920x1080", "C"), "host-1600x1000": ("1600x1000", "attach,B,Voff")}
    assert _p2_argvs(events) == DEV_P2_ARMS
    assert done.stdout.count("DEV TIER -- NOT A QUALIFICATION PASS") == 2, done.stdout
    assert done.stdout.rstrip().splitlines()[-1] == "## DEV TIER -- NOT A QUALIFICATION PASS (exit 10) ##"
    assert "DONE tier=dev failed=0 pending=0" in done.stdout
    assert done.stdout.count("-> MATCH") == 3, done.stdout
    assert done.returncode == 10, done.stdout


def test_known_bad_a_dev_round_with_a_failure_exits_1_and_still_says_dev(gates) -> None:
    done = gates["run"]("--tier", "dev", STUB_MODES=json.dumps({_p2_name(DEV_P2_ARMS[0]): "report"}))
    assert done.returncode == 1
    assert done.stdout.rstrip().splitlines()[-1] == "## DEV TIER -- NOT A QUALIFICATION PASS (exit 1) ##"


def test_known_bad_a_freeze_bracket_header_that_disagrees_with_the_flags_fails(gates) -> None:
    """The positive bracket arms must have run the bracket; a flagged arm must say it skipped it."""
    done = gates["run"]("--tier", "dev", STUB_MODES=json.dumps({_p2_name(a): "report" for a in DEV_P2_ARMS}),
                        STUB_P2_RED=_dev_red(), STUB_P2_FREEZE="skipped (--skip-freeze-bracket)")
    assert "freeze bracket 'skipped (--skip-freeze-bracket)' (want 'run') WRONG" in done.stdout, done.stdout
    assert "GATE FAILED: P2 --wait-profile fast" in done.stdout
    assert "GATE FAILED: P2 --wait-profile fast --gl-replay auto" in done.stdout
    assert "GATE FAILED: P2 --wait-profile fast --disable-bridge34 --skip-freeze-bracket" not in done.stdout
    assert done.returncode == 1


def test_a_full_round_never_says_dev_and_never_exits_10(gates) -> None:
    done = gates["run"]("--tier", "full")
    assert "DEV TIER" not in done.stdout and "DONE tier=full " in done.stdout
    assert done.returncode == 1, "the stub red arms cannot match"


@pytest.mark.parametrize("args", [["--tier"], ["--tier", "qa"], ["--tier", "DEV"], ["--bogus"], ["--allow-record", "x"]])
def test_known_bad_arguments_are_refused_before_anything_runs(gates, args: list[str]) -> None:
    done = gates["run"](*args, timeout=20)
    assert done.returncode == 2
    assert gates["events"]() == [] and not gates["out"].exists()
