"""Tests for obed_edom.dsk_live: the offline helpers extracted for reuse (d4/d5), and
LiveBatch's order-of-operations against fakes. No test may launch Keynote or reach
subprocess.run/Popen without an explicit monkeypatch of the module's own seams.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import obed_edom.dsk_live as dl


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


# --- guard_out_dir -------------------------------------------------------------


def test_guard_out_dir_rejects_tmp(tmp_path):
    with pytest.raises(ValueError, match="Keynote cannot reliably open"):
        dl.guard_out_dir(Path("/tmp/clips"), tmp_path / "Sermon.key")


def test_guard_out_dir_rejects_private_tmp(tmp_path):
    with pytest.raises(ValueError, match="Keynote cannot reliably open"):
        dl.guard_out_dir(Path("/private/tmp/clips"), tmp_path / "Sermon.key")


def test_guard_out_dir_rejects_inside_source_package(tmp_path):
    deck = tmp_path / "Sermon.key"
    deck.mkdir()
    with pytest.raises(ValueError, match="must not be inside the source"):
        dl.guard_out_dir(deck / "clips", deck)


def test_guard_out_dir_allows_sibling_dir(tmp_path):
    deck = tmp_path / "Sermon.key"
    deck.mkdir()
    out_dir = tmp_path / "clips"
    dl.guard_out_dir(out_dir, deck)


# --- ordinal_map -----------------------------------------------------------


def test_ordinal_map_ranks_kept_slides():
    assert dl.ordinal_map({17, 32, 33}) == {17: 1, 32: 2, 33: 3}


def test_ordinal_map_unaffected_by_deck_size():
    assert dl.ordinal_map({17, 32, 33}) == {17: 1, 32: 2, 33: 3}


# --- lock contention ---------------------------------------------------------


def test_lock_acquire_writes_pid_and_release_unlocks(tmp_path, monkeypatch):
    lock_path = tmp_path / "keynote.lock"
    monkeypatch.setattr(dl, "LOCK_PATH", lock_path)
    fd = dl._acquire_lock()
    assert lock_path.read_text().splitlines()[0] == str(dl.os.getpid())
    dl._release_lock(fd)


def test_lock_second_acquire_contends_on_open_flock(tmp_path, monkeypatch):
    lock_path = tmp_path / "keynote.lock"
    monkeypatch.setattr(dl, "LOCK_PATH", lock_path)
    fd1 = dl._acquire_lock()
    with pytest.raises(RuntimeError, match="lock held"):
        dl._acquire_lock()
    dl._release_lock(fd1)
    fd2 = dl._acquire_lock()
    dl._release_lock(fd2)


def test_lock_release_allows_reacquire(tmp_path, monkeypatch):
    lock_path = tmp_path / "keynote.lock"
    monkeypatch.setattr(dl, "LOCK_PATH", lock_path)
    fd1 = dl._acquire_lock()
    dl._release_lock(fd1)
    fd2 = dl._acquire_lock()
    dl._release_lock(fd2)


# --- LiveBatch order of operations -------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


def _stub_batch(monkeypatch, *, keynote_running=False, fingerprints=None):
    calls: list[str] = []
    state = {"running": keynote_running}

    monkeypatch.setattr(dl, "_keynote_running", lambda: (calls.append("keynote_running"), state["running"])[1])
    monkeypatch.setattr(dl, "_acquire_lock", lambda: (calls.append("acquire_lock"), 99)[1])
    monkeypatch.setattr(dl, "_release_lock", lambda fd: calls.append(f"release_lock:{fd}"))

    fingerprint_values = iter(fingerprints or [("before",), ("before",)])
    monkeypatch.setattr(dl, "_fingerprint_source", lambda path: (calls.append("fingerprint"), next(fingerprint_values))[1])

    def fake_copy_keynote(src, dest):
        calls.append("copy_keynote")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"key")
        return dest

    monkeypatch.setattr(dl, "copy_keynote", fake_copy_keynote)
    monkeypatch.setattr(dl._DisplayPoke, "start", lambda self: calls.append("poke_start"))
    monkeypatch.setattr(dl._DisplayPoke, "stop", lambda self: calls.append("poke_stop"))
    monkeypatch.setattr(dl._RssWatchdog, "start", lambda self: calls.append("watchdog_start"))
    monkeypatch.setattr(dl._RssWatchdog, "stop", lambda self: calls.append("watchdog_stop"))
    monkeypatch.setattr(dl, "_keynote_pid", lambda: None)
    monkeypatch.setattr(dl, "_run_quit_script", lambda *a: calls.append("run_quit_script"))

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls.append("run_osascript")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(dl, "_run_osascript", fake_run_osascript)
    return calls, state


def test_live_batch_happy_path_order(monkeypatch, tmp_path):
    calls, state = _stub_batch(monkeypatch)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    with dl.LiveBatch(fw, out_dir) as batch:
        assert batch.scratch is not None and batch.scratch.exists()
        script_path = batch.work / "script.applescript"
        script_path.write_text("script")
        proc = batch.run(script_path)
        assert proc.returncode == 0

    assert calls == [
        "keynote_running",
        "acquire_lock",
        "fingerprint",
        "poke_start",
        "copy_keynote",
        "watchdog_start",
        "run_osascript",
        "watchdog_stop",
        "keynote_running",
        "poke_stop",
        "release_lock:99",
        "fingerprint",
    ]
    assert not batch.work.exists()


def test_live_batch_refuses_when_keynote_already_running(monkeypatch, tmp_path):
    _stub_batch(monkeypatch, keynote_running=True)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    with pytest.raises(RuntimeError, match="already running"):
        with dl.LiveBatch(fw, out_dir):
            pass


def test_live_batch_quits_keynote_on_exit_when_still_running(monkeypatch, tmp_path):
    calls, state = _stub_batch(monkeypatch)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    with dl.LiveBatch(fw, out_dir) as batch:
        script_path = batch.work / "script.applescript"
        script_path.write_text("script")
        state["running"] = True
        batch.run(script_path)

    assert "run_quit_script" in calls
    assert calls.index("run_quit_script") > calls.index("run_osascript")


def test_live_batch_source_changed_raises_when_no_primary_exception(monkeypatch, tmp_path):
    _stub_batch(monkeypatch, fingerprints=[("before",), ("after",)])
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    with pytest.raises(RuntimeError, match="Source deck changed"):
        with dl.LiveBatch(fw, out_dir) as batch:
            script_path = batch.work / "script.applescript"
            script_path.write_text("script")
            batch.run(script_path)


def test_live_batch_1712_retry_recopies_scratch(monkeypatch, tmp_path):
    calls, state = _stub_batch(monkeypatch)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    monkeypatch.setattr(dl, "_quit_and_wait_for_exit", lambda *a: calls.append("quit_and_wait"))

    attempts = {"n": 0}

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls.append("run_osascript")
        attempts["n"] += 1
        if attempts["n"] == 1:
            return _FakeCompleted(returncode=1, stderr="-1712")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(dl, "_run_osascript", fake_run_osascript)

    with dl.LiveBatch(fw, out_dir) as batch:
        script_path = batch.work / "script.applescript"
        script_path.write_text("script")
        proc = batch.run(script_path)
        assert proc.returncode == 0

    assert calls.count("copy_keynote") == 2
    assert "quit_and_wait" in calls


def test_live_batch_logs_peak_rss_on_exit(monkeypatch, tmp_path):
    calls, state = _stub_batch(monkeypatch)
    monkeypatch.setattr(dl._RssWatchdog, "start", lambda self: None)
    monkeypatch.setattr(dl._RssWatchdog, "stop", lambda self: None)
    monkeypatch.setattr(dl, "_sample_rss_bytes", lambda pid: 123_456)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")
    logged: list[str] = []

    with dl.LiveBatch(fw, out_dir, rss_limit_bytes=999_999, log=logged.append) as batch:
        script_path = batch.work / "script.applescript"
        script_path.write_text("script")
        batch.run(script_path)
        batch._watchdog.peak_rss_bytes = dl._sample_rss_bytes(1)

    assert "Keynote peak RSS: 123456 bytes (limit 999999 bytes)" in logged


def test_live_batch_run_no_retry_flag(monkeypatch, tmp_path):
    calls, state = _stub_batch(monkeypatch)
    out_dir = tmp_path / "clips"
    out_dir.mkdir()
    fw = tmp_path / "Sermon.key"
    fw.write_bytes(b"source")

    monkeypatch.setattr(dl, "_quit_and_wait_for_exit", lambda *a: calls.append("quit_and_wait"))

    def fake_run_osascript(script_path, *, timeout=3600, register_proc=None, on_progress=None):
        calls.append("run_osascript")
        return _FakeCompleted(returncode=1, stderr="-1712")

    monkeypatch.setattr(dl, "_run_osascript", fake_run_osascript)

    with dl.LiveBatch(fw, out_dir) as batch:
        script_path = batch.work / "script.applescript"
        script_path.write_text("script")
        proc = batch.run(script_path, retry_on_1712=False)
        assert proc.returncode == 1

    assert calls.count("run_osascript") == 1
    assert calls.count("copy_keynote") == 1
    assert "quit_and_wait" not in calls
