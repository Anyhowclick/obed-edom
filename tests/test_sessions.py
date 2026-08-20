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
