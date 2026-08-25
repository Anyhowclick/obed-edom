import json
import time
from pathlib import Path

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


def test_visual_result_pairs_png_folders(tmp_path: Path):
    from obed_edom.web.jobs import visual_result

    left = tmp_path / "lw"
    right = tmp_path / "dsk"
    left.mkdir()
    right.mkdir()
    (left / "wall.002.png").write_bytes(b"x")
    (left / "wall.003.png").write_bytes(b"x")
    (right / "dsk.001.png").write_bytes(b"x")
    result = visual_result(left, right)
    assert result["phase"] == "visual"
    assert result["leftLabel"] == "LW"
    assert result["pairs"][0]["leftNumber"] == 2
    assert result["pairs"][0]["rightNumber"] == 1
    assert result["pairs"][1]["rightNumber"] is None
    assert result["leftCatalog"][0]["png"] == "wall.002.png"


def test_visual_delete_does_not_purge_preview_folders(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    left = output / "lw"
    left.mkdir(parents=True)
    marker = left / "keep.png"
    marker.write_bytes(b"x")
    right = tmp_path / "dsk"
    right.mkdir()
    (right / "a.png").write_bytes(b"x")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit("visual", lambda _j: {"leftPreviews": str(left), "rightPreviews": str(right)}, feature="visual")
    _wait(runner, job.id)
    runner.delete(job.id, purge=True)
    assert marker.is_file()


def test_visual_delete_purges_work_dir(tmp_path: Path):
    sessions = tmp_path / "sessions"
    output = tmp_path / "output"
    left = output / "lw"
    left.mkdir(parents=True)
    (left / "keep.png").write_bytes(b"x")
    right = tmp_path / "dsk"
    right.mkdir()
    (right / "a.png").write_bytes(b"x")
    work = output / ".visual" / "job1"
    heat = work / "heat"
    heat.mkdir(parents=True)
    (heat / "pair-001.png").write_bytes(b"h")
    runner = JobRunner(session_dir=sessions, output_root=output)
    job = runner.submit(
        "visual",
        lambda _j: {
            "leftPreviews": str(left),
            "rightPreviews": str(right),
            "workDir": str(work),
        },
        feature="visual",
    )
    _wait(runner, job.id)
    runner.delete(job.id, purge=True)
    assert (left / "keep.png").is_file()
    assert not work.exists()
