import json
import threading
import time
from pathlib import Path

import pytest

from obed_edom.web.jobs import Job, JobRunner, artifact_status


def _wait(runner: JobRunner, job_id: str, timeout: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = runner.get(job_id)
        if job and job.status in {"done", "error"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_job_persists_and_reloads(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC", "lwCount": 8}, feature="generate")
    done = _wait(runner, job.id)
    assert done.status == "done"
    saved = sessions / f"{job.id}.json"
    assert saved.is_file()
    payload = json.loads(saved.read_text())
    assert payload["feature"] == "generate"
    assert payload["result"]["stem"] == "Sermon_BC"

    reloaded = JobRunner(session_dir=sessions, output_root=output)
    listed = reloaded.list(feature="generate")
    assert len(listed) == 1
    assert listed[0].id == job.id
    assert listed[0].result["stem"] == "Sermon_BC"
    assert reloaded.list(feature="diff") == []


def test_cancel_running_job_keeps_cancelled_terminal_status(tmp_path: Path):
    runner = JobRunner(session_dir=tmp_path / "sessions", output_root=tmp_path / "output")
    started = threading.Event()

    def work(job: Job):
        started.set()
        while not job.cancelled():
            time.sleep(0.01)
        raise RuntimeError("interrupted")

    job = runner.submit("maps", work, feature="maps")
    assert started.wait(1)
    cancelled = runner.cancel(job.id)
    assert cancelled is job
    done = _wait(runner, job.id)
    assert done.status == "error"
    assert done.error == "Export cancelled."
    assert runner.cancel(job.id) is job


def test_cancel_running_job_waits_for_worker_and_discards_result(tmp_path: Path):
    runner = JobRunner(session_dir=tmp_path / "sessions", output_root=tmp_path / "output")
    started = threading.Event()
    release = threading.Event()

    def work(_job: Job):
        started.set()
        assert release.wait(1)
        return {"new": True}

    job = runner.submit("maps", work, feature="maps")
    job.result = {"old": True}
    assert started.wait(1)
    runner.cancel(job.id)
    assert job.status == "running"
    assert job.result == {"old": True}
    release.set()
    done = _wait(runner, job.id)
    assert done.status == "error"
    assert done.error == "Export cancelled."
    assert done.result == {"old": True}


def test_completion_wins_when_job_finishes_before_cancel(tmp_path: Path):
    runner = JobRunner(session_dir=tmp_path / "sessions", output_root=tmp_path / "output")
    job = runner.submit("maps", lambda _job: {"complete": True}, feature="maps")
    done = _wait(runner, job.id)
    assert done.status == "done"
    assert runner.cancel(job.id) is job
    assert job.status == "done"
    assert job.result == {"complete": True}


def test_loop_reverts_result_when_save_fails(tmp_path: Path, monkeypatch):
    thread_errors: list[BaseException] = []
    original_hook = threading.excepthook

    def capturing_hook(args: threading.ExceptHookArgs) -> None:
        thread_errors.append(args.exc_value)

    monkeypatch.setattr(threading, "excepthook", capturing_hook)

    runner = JobRunner(session_dir=tmp_path / "sessions", output_root=tmp_path / "output")

    started = threading.Event()
    release = threading.Event()

    def fn(_job: Job) -> dict:
        started.set()
        release.wait(5)
        return {"new": True}

    job = runner.submit("maps", fn, feature="maps", result={"old": True})
    assert started.wait(5)

    real_save = runner.save

    def failing_save(saved_job: Job) -> None:
        if saved_job.id == job.id:
            raise RuntimeError("disk full")
        real_save(saved_job)

    monkeypatch.setattr(runner, "save", failing_save)
    release.set()

    deadline = time.time() + 5.0
    while time.time() < deadline and job.status not in ("error", "done"):
        time.sleep(0.02)

    assert job.status == "error"
    assert job.error == "disk full"
    assert job.result == {"old": True}
    assert not thread_errors

    monkeypatch.setattr(threading, "excepthook", original_hook)

    monkeypatch.setattr(runner, "save", real_save)
    other = runner.submit("maps", lambda _job: {"ok": True}, feature="maps")
    _wait(runner, other.id)
    assert other.status == "done"
    assert other.result == {"ok": True}


def test_delete_purges_output_under_root(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    work = output / "Sermon_BC"
    work.mkdir(parents=True)
    (work / "preview.png").write_text("x")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "generate",
        lambda _j: {"stem": "Sermon_BC", "outputDir": str(work)},
        feature="generate",
    )
    _wait(runner, job.id)
    assert runner.delete(job.id, purge=True)
    assert not work.exists()
    assert not (sessions / f"{job.id}.json").exists()
    assert JobRunner(session_dir=sessions, output_root=output).get(job.id) is None


def test_delete_does_not_escape_output_root(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "inspect",
        lambda _j: {"path": "/tmp/x.key", "previewDir": str(outside)},
        feature="dsk",
    )
    _wait(runner, job.id)
    runner.delete(job.id, purge=True)
    assert marker.is_file()


def test_delete_does_not_purge_preview_cache(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    # The cache normally lives outside output/, where purging cannot reach it at
    # all. Pointing it back inside is the only way the guard matters, so that is
    # what this exercises.
    monkeypatch.setenv("OBED_EDOM_CACHE_DIR", str(output / ".cache"))
    cache = output / ".cache" / "previews" / "abc"
    cache.mkdir(parents=True)
    marker = cache / "slide-001.png"
    marker.write_bytes(b"png")
    work = output / ".diff" / "job1"
    work.mkdir(parents=True)
    (work / "heat").mkdir()
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "diff",
        lambda _j: {
            "leftPreviews": str(cache),
            "workDir": str(work),
        },
        feature="diff",
    )
    _wait(runner, job.id)
    runner.delete(job.id, purge=True)
    assert marker.is_file()
    assert not work.exists()


def test_save_write_failure_leaves_no_partial_or_temp_session_file(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)
    session_file = sessions / f"{job.id}.json"
    before = session_file.read_text()

    from pathlib import Path as PathType

    real_replace = PathType.write_text

    def flaky_write_text(self, *args, **kwargs):
        if self.suffix == ".tmp":
            raise OSError("disk full")
        return real_replace(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "write_text", flaky_write_text)
    job.status = "done"
    job.result = {"stem": "Changed"}
    with pytest.raises(OSError):
        runner.save(job)

    monkeypatch.undo()
    assert session_file.read_text() == before
    assert not (sessions / f"{job.id}.tmp").exists()


def test_artifact_status_missing_and_suggested(tmp_path: Path):
    output = tmp_path / "output"
    gone = output / "old_name"
    stem_dir = output / "Sermon_BC"
    stem_dir.mkdir(parents=True)
    (stem_dir / "Sermon_BC_LW.key").write_text("k")
    job = Job(
        id="abc",
        kind="generate",
        feature="generate",
        status="done",
        result={"stem": "Sermon_BC", "outputDir": str(gone), "lwKey": str(gone / "Sermon_BC_LW.key")},
    )
    status = artifact_status(job, output)
    assert status["ok"] is False
    assert "output folder" in status["missing"]
    assert "LW.key" in status["missing"]
    assert status["suggestedPath"] == str(stem_dir)


def test_relocate_rewrites_generate_paths(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    renamed = output / "renamed_run"
    (renamed / "previews" / "lw").mkdir(parents=True)
    (renamed / "Sermon_BC_LW.key").write_text("k")
    (renamed / "previews" / "lw" / "lw.001.png").write_text("p")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "generate",
        lambda _j: {"stem": "Sermon_BC", "outputDir": str(output / "missing")},
        feature="generate",
    )
    _wait(runner, job.id)
    updated = runner.relocate(job.id, folder=str(renamed))
    assert updated is not None
    assert updated.result["outputDir"] == str(renamed)
    assert updated.result["lwKey"].endswith("Sermon_BC_LW.key")
    assert updated.result["previewFiles"]["lw"] == ["lw.001.png"]
    assert artifact_status(updated, output)["ok"] is True


def test_delete_when_files_already_gone(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    missing = output / "already_deleted"
    job = runner.submit(
        "generate",
        lambda _j: {"stem": "Gone", "outputDir": str(missing)},
        feature="generate",
    )
    _wait(runner, job.id)
    assert runner.delete(job.id, purge=True)
    assert not (sessions / f"{job.id}.json").exists()
    assert runner.get(job.id) is None


def test_delete_all_purges_finished(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    first = output / "One"
    second = output / "Two"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "a.png").write_text("x")
    (second / "b.png").write_text("y")
    runner = JobRunner(session_dir=sessions, output_root=output)
    a = runner.submit(
        "generate",
        lambda _j: {"stem": "One", "outputDir": str(first)},
        feature="generate",
    )
    b = runner.submit(
        "diff",
        lambda _j: {"stem": "Two", "outputDir": str(second)},
        feature="diff",
    )
    _wait(runner, a.id)
    _wait(runner, b.id)
    assert runner.delete_all(purge=True) == 2
    assert not first.exists()
    assert not second.exists()
    assert runner.list() == []
    assert JobRunner(session_dir=sessions, output_root=output).list() == []


def test_delete_all_skips_running(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    done = runner.submit("generate", lambda _j: {"stem": "Done"}, feature="generate")
    _wait(runner, done.id)
    running = Job(id="live", kind="generate", feature="generate", status="running")
    runner._jobs[running.id] = running
    assert runner.delete_all(purge=True) == 1
    assert runner.get("live") is not None
    assert runner.get(done.id) is None


def test_list_maps_jobs(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    other = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    job = runner.submit("maps", lambda _j: {"stem": "maps-run"}, feature="maps")
    _wait(runner, other.id)
    done = _wait(runner, job.id)
    assert done.status == "done"
    listed = runner.list(feature="maps")
    assert len(listed) == 1
    assert listed[0].id == job.id
    assert listed[0].result["stem"] == "maps-run"
    assert {j.id for j in runner.list(feature="generate")} == {other.id}


def test_purge_maps_dirs_not_geocode(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    work = output / ".maps" / "job1"
    work.mkdir(parents=True)
    (work / "preview.png").write_text("x")
    geocode = output / ".geocode"
    geocode.mkdir(parents=True)
    marker = geocode / "kl.json"
    marker.write_text("{}")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "maps",
        lambda _j: {"stem": "maps-run", "outputDir": str(work)},
        feature="maps",
    )
    _wait(runner, job.id)
    assert runner.delete(job.id, purge=True)
    assert not work.exists()
    assert marker.is_file()
    assert not (sessions / f"{job.id}.json").exists()


def test_relocate_maps_dest_path(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    dest = output / "Map.key"
    dest_cg = output / "Map_CG.key"
    output.mkdir()
    dest.write_text("k")
    dest_cg.write_text("k")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("maps", lambda _j: {"stem": "maps-run"}, feature="maps")
    _wait(runner, job.id)
    updated = runner.relocate(job.id, dest_path=str(dest), dest_path_cg=str(dest_cg))
    assert updated is not None
    assert updated.result["destPath"] == str(dest)
    assert updated.result["destPathCg"] == str(dest_cg)


def test_artifact_status_maps_labels(tmp_path: Path):
    output = tmp_path / "output"
    output.mkdir()
    map_key = output / "Map.key"
    cg_key = output / "Map_CG.key"
    map_key.write_text("k")
    cg_key.write_text("k")

    maps_present = Job(
        id="maps-ok",
        kind="maps",
        feature="maps",
        status="done",
        result={"destPath": str(map_key), "destPathCg": str(cg_key)},
    )
    present = artifact_status(maps_present, output)
    assert present["ok"] is True
    assert "Map Keynote" not in present["missing"]
    assert "CG Keynote" not in present["missing"]

    maps_absent = Job(
        id="maps-gone",
        kind="maps",
        feature="maps",
        status="done",
        result={"outputDir": str(output / "missing"), "destPath": str(output / "gone.key")},
    )
    absent = artifact_status(maps_absent, output)
    assert "output folder" in absent["missing"]
    assert "Map Keynote" in absent["missing"]
    assert "CG Keynote" not in absent["missing"]

    maps_cg = Job(
        id="maps-cg",
        kind="maps",
        feature="maps",
        status="done",
        result={"destPathCg": str(cg_key)},
    )
    cg_status = artifact_status(maps_cg, output)
    assert cg_status["ok"] is True
    assert "CG Keynote" not in cg_status["missing"]

    resize_missing = Job(
        id="resize-gone",
        kind="resize",
        feature="resize",
        status="done",
        result={"destPath": str(output / "gone_cg.key")},
    )
    resize_status = artifact_status(resize_missing, output)
    assert "CG Keynote" in resize_status["missing"]
    assert "Map Keynote" not in resize_status["missing"]

    resize_ok = Job(
        id="resize-ok",
        kind="resize",
        feature="resize",
        status="done",
        result={"destPath": str(map_key)},
    )
    assert "CG Keynote" not in artifact_status(resize_ok, output)["missing"]


def test_concurrent_update_result_race_leaves_valid_state(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)

    ready = threading.Event()
    release = threading.Event()
    real_save = runner.save

    def slow_save(j):
        ready.set()
        release.wait(timeout=2)
        real_save(j)

    runner.save = slow_save
    errors: list[Exception] = []

    def first_writer():
        try:
            runner.update_result(job.id, {"stem": "Sermon_BC", "n": 1})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def second_writer():
        ready.wait(timeout=2)
        try:
            runner.update_result(job.id, {"stem": "Sermon_BC", "n": 2})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=first_writer), threading.Thread(target=second_writer)]
    for t in threads:
        t.start()
    time.sleep(0.05)
    release.set()
    for t in threads:
        t.join(timeout=5)

    assert not errors
    saved = sessions / f"{job.id}.json"
    payload = json.loads(saved.read_text())
    assert payload["result"]["n"] in {1, 2}
    assert not list(sessions.glob(f"{job.id}.json.*.tmp"))
    assert runner.get(job.id).result["n"] == payload["result"]["n"]


def test_worker_finalization_races_update_result(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    release = threading.Event()
    job = runner.submit("generate", lambda j: (release.wait(2), {"stem": "worker"})[1], feature="generate")

    for _ in range(100):
        if runner.get(job.id).status == "running":
            break
        time.sleep(0.01)

    def racer():
        release.wait(1)
        time.sleep(0.005)
        runner.update_result(job.id, {"stem": "worker", "raced": True})

    racer_thread = threading.Thread(target=racer)
    racer_thread.start()
    release.set()
    done = _wait(runner, job.id)
    racer_thread.join(timeout=5)

    assert done.status == "done"
    saved = sessions / f"{job.id}.json"
    payload = json.loads(saved.read_text())
    assert payload["result"]["stem"] == "worker"
    assert not list(sessions.glob(f"{job.id}.json.*.tmp"))


def test_failed_save_leaves_no_temp_file(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        runner.update_result(job.id, {"bad": Unserializable()})

    assert not list(sessions.glob(f"{job.id}.json.*.tmp"))
    assert runner.get(job.id).result == {"stem": "Sermon_BC"}


def test_delete_races_with_inflight_update_result(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)

    entered_save = threading.Event()
    release_save = threading.Event()
    original_save = runner.save

    def blocking_save(j):
        entered_save.set()
        release_save.wait(2)
        original_save(j)

    runner.save = blocking_save

    update_thread = threading.Thread(
        target=runner.update_result, args=(job.id, {"stem": "Sermon_BC", "raced": True})
    )
    update_thread.start()
    assert entered_save.wait(1)

    delete_thread = threading.Thread(target=runner.delete, args=(job.id,))
    delete_thread.start()

    release_save.set()
    update_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert not update_thread.is_alive()
    assert not delete_thread.is_alive()
    assert not (sessions / f"{job.id}.json").exists()


def test_delete_then_update_result_leaves_no_file(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)

    assert runner.delete(job.id) is True
    assert runner.update_result(job.id, {"stem": "Sermon_BC", "late": True}) is None
    assert not (sessions / f"{job.id}.json").exists()

    # save() itself must be a no-op for a deleted job even if called directly.
    runner.save(job)
    assert not (sessions / f"{job.id}.json").exists()


def test_delete_does_not_deadlock_with_concurrent_save(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("generate", lambda _j: {"stem": "Sermon_BC"}, feature="generate")
    _wait(runner, job.id)

    barrier = threading.Barrier(2, timeout=5)

    def save_racer():
        barrier.wait()
        try:
            runner.update_result(job.id, {"stem": "Sermon_BC", "racer": True})
        except Exception:
            pass

    def delete_racer():
        barrier.wait()
        runner.delete(job.id)

    threads = [threading.Thread(target=save_racer), threading.Thread(target=delete_racer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    assert not (sessions / f"{job.id}.json").exists()


def test_submit_does_not_reuse_deleted_job_id(tmp_path: Path, monkeypatch):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    runner = JobRunner(session_dir=sessions, output_root=output)
    old = runner.submit("generate", lambda _j: {"stem": "Old"}, feature="generate")
    _wait(runner, old.id)
    assert runner.delete(old.id)

    ids = iter([old.id, "fresh123"])
    monkeypatch.setattr(runner, "_generate_job_id", lambda: next(ids))

    job = runner.submit("generate", lambda _j: {"stem": "New"}, feature="generate")
    assert job.id == "fresh123"
    done = _wait(runner, job.id)
    assert done.status == "done"
    assert (sessions / f"{job.id}.json").is_file()
    assert not (sessions / f"{old.id}.json").exists()
