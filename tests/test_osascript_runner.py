"""``osascript_runner`` — the single shared executor for every Keynote osascript call.

These are pure/process-level tests: no real Keynote involved. The one exception is
`test_timeout_kills_child_and_raises`, which spawns a real PATH-stub `osascript` (a
sleeper) to prove the wall-clock kill actually terminates the child process; it opts
out of the autouse tripwire via the `live_osascript` fixture.
"""
from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest

from obed_edom import osascript_runner as runner


@pytest.fixture(autouse=True)
def _no_launch(monkeypatch):
    monkeypatch.setattr(runner, "_launch_keynote", lambda: None)


def test_run_applescript_writes_file_never_stdin(monkeypatch):
    seen = {}

    def fake_execute(argv, *, timeout=None, is_cancelled=None):
        seen["argv"] = argv
        seen["exists_during_call"] = Path(argv[-1]).is_file()
        return runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0)

    monkeypatch.setattr(runner, "_execute", fake_execute)
    result = runner.run_applescript("tell application \"Keynote\"\nend tell")

    assert seen["argv"][0] == "osascript"
    assert seen["argv"][-1].endswith(".applescript")
    assert seen["exists_during_call"] is True
    assert not Path(seen["argv"][-1]).exists()
    assert result.dump is None


def test_run_jxa_argv_and_plan_roundtrip(monkeypatch):
    plan = {"path": "/x/y.key", "bundleId": "com.apple.Keynote"}
    seen = {}

    def fake_execute(argv, *, timeout=None, is_cancelled=None):
        seen["argv"] = argv
        seen["plan_on_disk"] = json.loads(Path(argv[-1]).read_text())
        return runner.OsaResult(argv=argv, returncode=0, stdout="{}", stderr="", elapsed=0.0)

    monkeypatch.setattr(runner, "_execute", fake_execute)
    js = Path("/tmp/some_script.js")
    runner.run_jxa(js, plan)

    assert seen["argv"] == ["osascript", "-l", "JavaScript", str(js), seen["argv"][-1]]
    assert seen["plan_on_disk"] == plan
    assert not Path(seen["argv"][-1]).exists()


def test_launch_false_does_not_open_keynote(monkeypatch):
    launched = []
    monkeypatch.setattr(runner, "_launch_keynote", lambda: launched.append(True))
    monkeypatch.setattr(
        runner, "_execute",
        lambda argv, **kw: runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0),
    )
    runner.run_applescript("script", launch=False)
    assert launched == []


def test_launch_true_opens_bundle_id_once(monkeypatch):
    order = []
    monkeypatch.setattr(runner, "_launch_keynote", lambda: order.append("launch"))

    def fake_execute(argv, **kw):
        order.append("execute")
        return runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0)

    monkeypatch.setattr(runner, "_execute", fake_execute)
    runner.run_applescript("script", launch=True)
    assert order == ["launch", "execute"]


def test_timeout_kills_child_and_raises(tmp_path, monkeypatch, live_osascript):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pid_file = tmp_path / "pid"
    stub = bin_dir / "osascript"
    stub.write_text(
        "#!/bin/sh\n"
        f"echo $$ > {pid_file}\n"
        "sleep 30\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    start = time.monotonic()
    with pytest.raises(runner.OsascriptTimeout):
        runner.run_applescript("script", timeout=0.5)
    elapsed = time.monotonic() - start

    assert elapsed < 5
    for _ in range(50):
        if pid_file.exists():
            break
        time.sleep(0.05)
    pid = int(pid_file.read_text().strip())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_cancellation_poll_terminates(monkeypatch, live_osascript):
    calls = {"n": 0}

    def is_cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    class FakeProc:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    fake = FakeProc()
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: fake)

    with pytest.raises(runner.OsascriptCancelled, match=r"^Export cancelled\.$"):
        runner._execute(["osascript", "x"], timeout=None, is_cancelled=is_cancelled)
    assert fake.terminated is True


def test_lock_is_rlock_and_serialises(monkeypatch):
    events: list[str] = []
    lock_gate = threading.Event()

    def fake_execute(argv, **kw):
        events.append("enter")
        lock_gate.wait(timeout=2)
        events.append("exit")
        return runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0)

    monkeypatch.setattr(runner, "_execute", fake_execute)

    def worker():
        runner.run_applescript("script")

    t1 = threading.Thread(target=worker)
    t1.start()
    time.sleep(0.1)
    t2 = threading.Thread(target=worker)
    t2.start()
    time.sleep(0.1)
    assert events == ["enter"]
    lock_gate.set()
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert events == ["enter", "exit", "enter", "exit"]


def test_lock_reentrancy_does_not_deadlock(monkeypatch):
    monkeypatch.setattr(
        runner, "_execute",
        lambda argv, **kw: runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0),
    )

    def reentrant_call():
        with runner.KEYNOTE_LOCK:
            runner.run_applescript("script")

    thread = threading.Thread(target=reentrant_call)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_dump_on_failure_written_only_on_rc_nonzero(tmp_path, monkeypatch):
    dump = tmp_path / "out.applescript"

    monkeypatch.setattr(
        runner, "_execute",
        lambda argv, **kw: runner.OsaResult(argv=argv, returncode=0, stdout="", stderr="", elapsed=0.0),
    )
    result = runner.run_applescript("script text", dump_on_failure=dump)
    assert result.dump is None
    assert not dump.exists()

    monkeypatch.setattr(
        runner, "_execute",
        lambda argv, **kw: runner.OsaResult(argv=argv, returncode=1, stdout="", stderr="boom", elapsed=0.0),
    )
    result = runner.run_applescript("script text", dump_on_failure=dump)
    assert result.dump == dump
    assert dump.read_text(encoding="utf-8") == "script text"


def test_parse_json_stdout_error_messages():
    def result(*, returncode=0, stdout="", stderr=""):
        return runner.OsaResult(argv=["osascript"], returncode=returncode, stdout=stdout, stderr=stderr, elapsed=0.0)

    with pytest.raises(RuntimeError, match="X failed"):
        runner.parse_json_stdout(result(returncode=1, stderr="err"), "X")
    with pytest.raises(RuntimeError, match="X returned no JSON"):
        runner.parse_json_stdout(result(stdout=""), "X")
    with pytest.raises(RuntimeError, match="X returned invalid JSON"):
        runner.parse_json_stdout(result(stdout="not json"), "X")
    assert runner.parse_json_stdout(result(stdout='{"a": 1}'), "X") == {"a": 1}


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("OBED_OSASCRIPT_TIMEOUT", "0")
    assert runner.keynote_timeout() == 0
    monkeypatch.setenv("OBED_OSASCRIPT_TIMEOUT", "garbage")
    assert runner.keynote_timeout() == runner.DEFAULT_TIMEOUT
    monkeypatch.delenv("OBED_OSASCRIPT_TIMEOUT", raising=False)
    assert runner.keynote_timeout() == runner.DEFAULT_TIMEOUT
    assert runner.DEFAULT_TIMEOUT > 3600
