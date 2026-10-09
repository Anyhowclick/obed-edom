"""`scripts/run_gates.sh` driven end to end against stub runs (no Chrome, no Keynote).

The script runs from a fake gate worktree whose `scripts/` holds stub versions of the live probe,
the P2 driver and the H.264 prewarm entry point (`src/` and `continuity_core_variants.py` are the
real ones, symlinked, because the checks import them). Each stub logs what it was asked to do to
an events file and behaves per `STUB_MODES` (artifact/out-dir stem -> mode):

- `pass`    write a passing artifact and exit 0 (P2: exit 1 with an empty log);
- `die`     kill its parent -- the per-run wrapper -- before the wrapper can write the status, as
            when a wrapper is killed or crashes mid-run;
- `foreign` publish a status carrying another round's nonce, then kill the wrapper;
- `hang`    start a child process and sleep, as a live probe holding Chrome does.

What is pinned here:
- a run's previous `.rc`/`.log`/artifact (and the P2 out-dir report) never count: a run that does
  not write a fresh status (this round's nonce) fails its check;
- killing the queue owner (TERM/INT/HUP) leaves none of the queued runs or their children behind;
- `GATE_JOBS` outside 1..5 is refused before anything is launched;
- the H.264 pattern cache is prewarmed (and logged) before the first timed run.
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
event(f"probe {stem} start")
mode = mode_of(stem)
act(mode, artifact.with_suffix(""))
artifact.write_text(json.dumps({"status": "pass", "arms": {}, "visible": {}}))
sys.exit(0)
'''

P2_STUB = _STUB_COMMON + r'''
out = Path(arg("--out-dir"))
event(f"p2 {out.name} start")
act(mode_of(out.name), out)
sys.exit(1)
'''

PREWARM_STUB = r'''
import os

def prewarm_h264_patterns(root):
    with open(os.environ["STUB_EVENTS"], "a") as f:
        f.write(f"prewarm {root.name}\n")
    mode = os.environ.get("STUB_PREWARM", "hit")
    if mode == "fail":
        raise RuntimeError("ffmpeg encode failed")
    if mode == "empty":
        return []
    return [{"seconds": 46.0333, "source": "cache" if mode == "hit" else "encoded", "cacheKey": "k" * 64, "sha256": "s" * 64}]
'''


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

    def env(**extra: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in ("GATE_JOBS", "STUB_MODES", "STUB_DEFAULT", "STUB_PREWARM")}
        return {**base, "STUB_EVENTS": str(events), "STUB_MARKER": str(marker), **extra}

    def run(timeout: float = 120, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/zsh", str(SCRIPT), str(g), str(out)], env=env(**extra), capture_output=True, text=True, timeout=timeout,
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

    yield {"g": g, "out": out, "marker": marker, "run": run, "start": start, "events": events_list, "survivors": survivors}
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
    assert (gates["out"] / "p2--wait-profileslow.rc").read_text().strip() == f"{nonce} 1"
    assert "[P2 --wait-profile slow] exit=1 " in done.stdout
    assert not list(gates["out"].glob("*.rc.tmp")), "the status is published by rename"
    assert done.returncode != 0, "the stub red arms and P2 arms cannot match their registered sets"


def test_a_stale_status_and_artifact_from_an_earlier_round_fail_closed(gates) -> None:
    """The earlier round's `host-2560x1440.rc` says 0 and its artifact says pass; this round's run
    dies before writing a status. Nothing from the earlier round may count."""
    out = gates["out"]
    out.mkdir()
    (out / "host-2560x1440.rc").write_text("0\n")
    (out / "host-2560x1440.json").write_text(json.dumps({"status": "pass"}))
    (out / "host-2560x1440.log").write_text("stale log\n")
    p2 = out / "p2--wait-profileslow"
    (p2 / "gl-replay").mkdir(parents=True)
    (p2 / "report.json").write_text("{}")
    (p2 / "gl-replay" / "report.json").write_text("{}")
    (out / "p2--wait-profileslow.rc").write_text("0\n")
    (out / "p2--wait-profileslow.report.json").write_text("{}")
    done = gates["run"](STUB_MODES=json.dumps({"host-2560x1440": "die", "p2--wait-profileslow": "die"}))
    assert "GATE FAILED: HOST 2560x1440 exit missing" in done.stdout, done.stdout
    assert "HOST 2560x1440: pass" not in done.stdout
    assert "HOST 2560x1440: no artifact" in done.stdout
    assert "stale log" not in (out / "host-2560x1440.log").read_text()
    assert "[P2 --wait-profile slow] exit=missing" in done.stdout
    assert "GATE FAILED: P2 --wait-profile slow" in done.stdout
    assert not (p2 / "report.json").exists() and not (p2 / "gl-replay" / "report.json").exists()
    assert not (out / "p2--wait-profileslow.report.json").exists()
    assert "HOST 1600x1000: pass" in done.stdout, "the other runs are unaffected"
    assert done.returncode != 0


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


def test_the_pattern_cache_is_prewarmed_before_the_first_timed_run(gates) -> None:
    done = gates["run"](STUB_PREWARM="encoded")
    events = gates["events"]()
    assert events[0] == "prewarm html-unmodified"
    assert all(not e.startswith("prewarm") for e in events[1:])
    assert len([e for e in events if e.endswith(" start")]) == 3 + 5 + 9
    assert f"h264 pattern prewarm 46.0333s: encoded key={'k' * 64}" in done.stdout
    assert "cache hit" in gates["run"]().stdout


@pytest.mark.parametrize("mode", ["fail", "empty"])
def test_a_failed_prewarm_launches_nothing(gates, mode: str) -> None:
    done = gates["run"](STUB_PREWARM=mode)
    assert done.returncode == 1
    assert "H.264 pattern prewarm FAILED; no run launched" in done.stdout
    assert gates["events"]() == ["prewarm html-unmodified"]
