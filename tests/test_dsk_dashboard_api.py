"""API tests for the DSK Generator (P3) and Exporter (P4) dashboard endpoints.

Everything Keynote-shaped is monkeypatched: `assemble_dsk_deck`, `export_slide_clips`,
`export_stage_pngs`, `stage_counts`, `classify_deck` and `build_preview_thumbs` are all
faked, mirroring `tests/test_dashboard_api.py`'s resize tests. No test may start Keynote.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from obed_edom.dsk_plan import SlideClass
from obed_edom.web.app import app


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


def _wait(client, job_id, tries=120):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _cls(number, category, *, is_text=False, build_count=0, movie_count=0):
    return SlideClass(
        number=number,
        category=category,
        build_count=build_count,
        movie_count=movie_count,
        kept=(("shape", 0),),
        dropped_side=(),
        dropped_backdrop=(),
        transition=None,
        is_text=is_text,
    )


def _fw_payload(count=5):
    return {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": count,
        "slides": [{"number": n, "index": n - 1, "items": []} for n in range(1, count + 1)],
    }


def _dsk_payload(count=5):
    return {
        "slideWidth": 1920,
        "slideHeight": 1080,
        "slideCount": count,
        "slides": [{"number": n, "index": n - 1, "items": []} for n in range(1, count + 1)],
    }


def _patch_common(monkeypatch, app_mod, *, classes, thumbs=None):
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: list(classes.values()))
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: thumbs or {})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _p: "digest")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _d: Path("/tmp/thumbs"))


def _propose_dsk(client, deck, **extra):
    data = {"path": str(deck), **extra}
    return client.post("/api/dsk", data=data)


def test_dsk_propose_marks_text_and_empty_slides_skipped(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {
        1: _cls(1, "static"),
        2: _cls(2, "static", is_text=True),
        3: _cls(3, "empty"),
    }
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    started = _propose_dsk(client, deck)
    assert started.status_code == 200
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["phase"] == "review"
    assert result["contentOnly"] is True
    skipped = {(s["slide"], s["reason"]) for s in result["skipped"]}
    assert skipped == {(2, "text"), (3, "empty")}
    pages = {p["slide"]: p for p in result["pages"]}
    assert set(pages) == {1, 2}
    assert pages[1]["decision"]["include"] is True
    # A text page defaults to excluded under content-only.
    assert pages[2]["isText"] is True
    assert pages[2]["decision"]["include"] is False


def test_dsk_decisions_cannot_include_a_text_page_in_content_only(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "static", is_text=True)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)

    res = client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 2, "include": True}]},
    )
    assert res.status_code == 200
    pages = {p["slide"]: p for p in res.json()["result"]["pages"]}
    assert pages[2]["decision"]["include"] is False


def test_dsk_decisions_roundtrip_survives_re_propose(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "keepSide": True, "anchor": "left"}]},
    )
    job = client.get(f"/api/jobs/{job_id}").json()
    pages = {p["slide"]: p for p in job["result"]["pages"]}
    assert pages[1]["decision"]["keepSide"] is True
    assert pages[1]["decision"]["anchor"] == "left"
    assert pages[2]["needsClip"] is True


def test_dsk_apply_passes_content_only_and_derived_fields(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    seen = {}

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        seen["export_clips"] = (list(slides), kwargs)
        from obed_edom.dsk_movie_export import ClipResult
        from obed_edom.map_remap import Rect

        dest = Path(out_dir) / "clip.001.mov"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dest.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=dest, crop_rect=Rect(0, 0, 100, 100),
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, clip_sizes, clip_crops, content_only, **kwargs):
        seen["assemble"] = {
            "decisions": decisions,
            "clips": clips,
            "clip_sizes": clip_sizes,
            "clip_crops": clip_crops,
            "content_only": content_only,
        }
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path,
            slides_kept=(1, 2),
            ordinals={1: 1, 2: 2},
            fits={},
            clips_inserted={2: next(iter(clips[2].values()))},
            stroke={},
            zorder={},
            builds={},
            size_bytes=10,
            source_size_bytes=20,
            wall_s=1.0,
            warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "keepSide": True, "anchor": "right"}]},
    )
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["phase"] == "done"
    assert seen["assemble"]["content_only"] is True
    assert seen["assemble"]["decisions"][1].keep_side is True
    assert seen["assemble"]["decisions"][1].anchor == "right"
    assert seen["assemble"]["decisions"][2].action == "both"
    assert seen["export_clips"][0] == [2]
    assert seen["export_clips"][1]["per_movie"] is True
    assert 2 in seen["assemble"]["clips"]
    assert ("movie", 0) in seen["assemble"]["clips"][2]
    clip_path = seen["assemble"]["clips"][2][("movie", 0)]
    assert seen["assemble"]["clip_sizes"][str(clip_path)] == (1920, 1080)
    from obed_edom.map_remap import Rect

    assert seen["assemble"]["clip_crops"][2][("movie", 0)] == Rect(0, 0, 100, 100)
    # dsk output lands under output/<FW stem>/dsk/<stem>_DSK.key
    assert Path(job["result"]["deckPath"]).name == "GW_DSK.key"
    assert Path(job["result"]["deckPath"]).parent.name == "dsk"
    out_dir = tmp_path / "output" / "GW" / "dsk"
    published_clip = out_dir / "src" / "GW_DSK.002.01.src.mov"
    assert published_clip.is_file(), "the generator intermediate is renamed into out_dir/src"
    assert job["result"]["clips"] == {"2": ["src/GW_DSK.002.01.src.mov"]}
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["slides"]["2"]["srcClips"] == ["src/GW_DSK.002.01.src.mov"]
    assert "clip" not in manifest["slides"]["2"]
    assert manifest["slides"]["2"]["source_slide"] == 2
    assert manifest["slides"]["1"]["source_slide"] == 1


def test_dsk_apply_rerun_deletes_orphaned_src_clip(tmp_path, monkeypatch):
    """A Generator rerun that drops a movie slide deletes its now-unreferenced
    `src/*.src.mov` intermediate once the new deck and manifest are written."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def fake_export_clips(fw, slides, out_dir, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        results = []
        for n in slides:
            dest = Path(out_dir) / f"clip.{n:03d}.mov"
            dest.write_text("movie")
            results.append(
                ClipResult(
                    slide=n, movie_id=("movie", 0), path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
                )
            )
        return results

    def make_fake_assemble(ordinals):
        def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
            from obed_edom.dsk_assemble import AssembleResult

            return AssembleResult(
                path=out_path,
                slides_kept=tuple(sorted(ordinals)),
                ordinals=dict(ordinals),
                fits={}, stroke={}, zorder={}, builds={},
                clips_inserted={n: next(iter(clips[n].values())) for n in clips},
                size_bytes=10, source_size_bytes=20, wall_s=1.0,
                warnings=(), movie_props={},
            )

        return fake_assemble

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)

    client = TestClient(app)

    # Run 1: slides 2 and 3 both need clips.
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", make_fake_assemble({1: 1, 2: 2, 3: 3}))
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    clip_2 = src_dir / "GW_DSK.002.01.src.mov"
    clip_3 = src_dir / "GW_DSK.003.01.src.mov"
    assert clip_2.is_file()
    assert clip_3.is_file()

    # Run 2: slide 3 is gone; only slides 1 and 2 remain.
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes2 = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes2)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", make_fake_assemble({1: 1, 2: 2}))
    job_id2 = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id2)
    applied2 = client.post(f"/api/dsk/{job_id2}/apply")
    assert applied2.status_code == 200
    job2 = _wait(client, job_id2)
    assert job2["status"] == "done", job2.get("error")

    assert clip_2.is_file(), "still referenced this run"
    assert not clip_3.is_file(), "orphaned once slide 3 dropped out of the manifest"
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert "3" not in manifest["slides"]


def test_dsk_apply_rerun_failure_before_manifest_write_deletes_nothing(tmp_path, monkeypatch):
    """If assembly fails, the rerun never reaches the manifest write, so no
    previously published `src/*.src.mov` intermediate is deleted."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def fake_export_clips(fw, slides, out_dir, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        results = []
        for n in slides:
            dest = Path(out_dir) / f"clip.{n:03d}.mov"
            dest.write_text("movie")
            results.append(
                ClipResult(
                    slide=n, movie_id=("movie", 0), path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
                )
            )
        return results

    def fake_assemble_ok(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2, 3), ordinals={1: 1, 2: 2, 3: 3},
            fits={}, stroke={}, zorder={}, builds={},
            clips_inserted={n: next(iter(clips[n].values())) for n in clips},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
        )

    def fake_assemble_fail(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)

    client = TestClient(app)

    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble_ok)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    clip_2 = src_dir / "GW_DSK.002.01.src.mov"
    clip_3 = src_dir / "GW_DSK.003.01.src.mov"
    assert clip_2.is_file()
    assert clip_3.is_file()

    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble_fail)
    job_id2 = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id2)
    applied2 = client.post(f"/api/dsk/{job_id2}/apply")
    assert applied2.status_code == 200
    job2 = _wait(client, job_id2)
    assert job2["status"] == "error"

    assert clip_2.is_file()
    assert clip_3.is_file(), "nothing is deleted before a successful manifest write"


def test_dsk_apply_failed_assembly_leaves_no_unmanaged_clips_or_temp_dir(tmp_path, monkeypatch):
    """A generator run whose export succeeds but whose assembly fails must not leak
    per-movie clips into out_dir/src, and must remove its temporary export dir."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    def fake_export_clips(fw, slides, out_dir, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dest = Path(out_dir) / "clip.002.mov"
        dest.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=dest, crop_rect=None,
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble_fail(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble_fail)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"

    out_dir = tmp_path / "output" / "GW" / "dsk"
    if out_dir.is_dir():
        remaining = [p for p in out_dir.iterdir() if p.name != "manifest.json"]
        assert remaining == [], f"no leftover files/dirs expected, found: {remaining}"


def test_dsk_apply_operator_clip_rejected_for_multi_movie_slide(tmp_path, monkeypatch):
    """An operator-supplied single `decision.clip` cannot cover a slide with more
    than one kept movie -- accepting it would silently drop the other movie."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    two_movies = SlideClass(
        number=2, category="mixed", build_count=0, movie_count=2,
        kept=(("movie", 0), ("movie", 1)), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=False,
    )
    classes = {1: _cls(1, "static"), 2: two_movies}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    operator_clip = tmp_path / "operator.mov"
    operator_clip.write_text("movie")

    def unexpected_export(*_a, **_k):
        raise AssertionError("export_slide_clips must not run once the override is rejected")

    monkeypatch.setattr(app_mod, "export_slide_clips", unexpected_export)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 2, "clip": str(operator_clip)}]},
    )
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "cannot cover 2 kept" in job["error"]


def test_dsk_apply_operator_clip_maps_single_movie_slide(tmp_path, monkeypatch):
    """A single operator-supplied clip is a valid override for a single-movie slide."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    one_movie = SlideClass(
        number=2, category="movie", build_count=0, movie_count=1,
        kept=(("movie", 0),), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=False,
    )
    classes = {1: _cls(1, "static"), 2: one_movie}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "_ffprobe", lambda _p: (1920, 1080, 30.0, 1.0))

    operator_clip = tmp_path / "operator.mov"
    operator_clip.write_text("movie")
    seen = {}

    def unexpected_export(*_a, **_k):
        raise AssertionError("export_slide_clips must not run when the operator supplied a clip")

    def fake_assemble(fw, out_path, *, decisions, clips, clip_sizes, content_only, **kwargs):
        seen["clips"] = clips
        seen["clip_sizes"] = clip_sizes
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: next(iter(clips[2].values()))}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", unexpected_export)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 2, "clip": str(operator_clip)}]},
    )
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["clips"][2] == {("movie", 0): operator_clip}
    assert seen["clip_sizes"][str(operator_clip)] == (1920, 1080)


def test_dsk_apply_operator_clip_probe_failure_surfaces_error(tmp_path, monkeypatch):
    """A clip the ffprobe seam cannot read must fail the job rather than silently
    skip the aspect guard."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    one_movie = SlideClass(
        number=2, category="movie", build_count=0, movie_count=1,
        kept=(("movie", 0),), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=False,
    )
    classes = {1: _cls(1, "static"), 2: one_movie}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def broken_probe(_path):
        raise RuntimeError("ffprobe unavailable/failed and no ffmpeg fallback")

    monkeypatch.setattr(app_mod, "_ffprobe", broken_probe)

    operator_clip = tmp_path / "operator.mov"
    operator_clip.write_text("movie")

    def unexpected_export(*_a, **_k):
        raise AssertionError("export_slide_clips must not run when the operator supplied a clip")

    monkeypatch.setattr(app_mod, "export_slide_clips", unexpected_export)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/{job_id}/decisions",
        json={"decisions": [{"slide": 2, "clip": str(operator_clip)}]},
    )
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "could not probe" in job["error"]


def test_dsk_apply_manifest_clips_keyed_by_dsk_ordinal_not_fw_slide(tmp_path, monkeypatch):
    """When excluded FW slides shift ordinals (FW slide 5 becomes DSK slide 2), the
    manifest must key the clip by the resulting DSK ordinal, not the original FW
    slide number."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(5))
    classes = {n: _cls(n, "static") for n in range(1, 5)}
    classes[5] = _cls(5, "movie", movie_count=1)
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        dest = Path(out_dir) / "clip.mov"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dest.write_text("movie")
        return [
            ClipResult(
                slide=5, movie_id=("movie", 0), path=dest, crop_rect=None,
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        # only FW slides 1 and 5 kept; FW 5 becomes DSK ordinal 2.
        return AssembleResult(
            path=out_path,
            slides_kept=(1, 5),
            ordinals={1: 1, 5: 2},
            fits={},
            clips_inserted={2: next(iter(clips[5].values()))},
            stroke={},
            zorder={},
            builds={},
            size_bytes=10,
            source_size_bytes=20,
            wall_s=1.0,
            warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["ordinals"] == {"1": 1, "5": 2}
    assert result["clips"] == {"2": ["src/GW_DSK.002.01.src.mov"]}
    out_dir = tmp_path / "output" / "GW" / "dsk"
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["slides"]["2"]["srcClips"] == ["src/GW_DSK.002.01.src.mov"]
    assert manifest["slides"]["2"]["source_slide"] == 5
    assert "5" not in manifest["slides"], "the manifest must not be keyed by the original FW slide"


def test_dsk_apply_409_when_keynote_is_open(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: True)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    res = client.post(f"/api/dsk/{job_id}/apply")
    assert res.status_code == 409
    assert "keynote" in res.json()["detail"].lower()


def test_dsk_thumb_path_traversal_refused(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: list(classes.values()))
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: {1: "0001.jpg"})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _p: "digest")
    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    (thumb_dir / "0001.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _d: thumb_dir)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    ok = client.get(f"/api/dsk/{job_id}/thumb/0001.jpg")
    assert ok.status_code == 200
    bad = client.get(f"/api/dsk/{job_id}/thumb/../secrets.txt")
    assert bad.status_code in {400, 404}


def test_dsk_export_stage_pngs_any_1920_deck(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "hand_built_DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1, 2: 1})

    seen = {}

    def fake_export_stage_pngs(deck_path, slides, out_dir, **kwargs):
        seen["export"] = (deck_path, list(slides), kwargs)
        from obed_edom.dsk_stage_export import StageAsset

        return [
            StageAsset(
                slide=n, stage_index=1, path=Path(out_dir) / f"{n:04d}.001.png",
                width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
                content_alpha_frac=1.0, transparent_frac=0.0, source_name="x",
            )
            for n in slides
        ]

    monkeypatch.setattr(app_mod, "export_stage_pngs", fake_export_stage_pngs)

    def fake_export_dsk_clips(deck_path, slides, out_dir, **kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        seen["clips"] = (deck_path, list(slides))
        out = []
        for n in slides:
            dest = Path(out_dir) / f"{deck_path.stem}.{n:03d}.mov"
            dest.write_bytes(b"mov")
            out.append(
                ClipResult(
                    slide=n, movie_id=None, path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=0.1, crop_width=1920,
                )
            )
        return out

    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", fake_export_dsk_clips)

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck)})
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["result"]["isStageDeck"] is True
    actions = {p["slide"]: p["decision"]["action"] for p in job["result"]["pages"]}
    assert actions == {1: "stage", 2: "clip"}
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["phase"] == "done"
    assert seen["export"][1] == [1], "only the image slide goes to the stage exporter"
    assert seen["clips"][1] == [2], "the movie slide goes to the clip exporter"
    assert result["pngDir"] == str(deck.parent)
    assert result["sequence"] == ["0001.001.png", "hand_built_DSK.002.mov"]
    manifest = json.loads((deck.parent / "manifest.json").read_text())
    assert manifest["slides"]["2"]["clip"] == "hand_built_DSK.002.mov"
    assert manifest["slides"]["2"]["category"] == "movie"


def _fake_clip_exporter(seen):
    def fake(deck_path, slides, out_dir, **kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        seen.append(list(slides))
        out = []
        for n in slides:
            dest = Path(out_dir) / f"{deck_path.stem}.{n:03d}.mov"
            dest.write_bytes(b"mov")
            out.append(
                ClipResult(
                    slide=n, movie_id=None, path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=0.1, crop_width=1920,
                )
            )
        return out

    return fake


def test_dsk_export_re_exports_and_deletes_a_src_clip_the_generator_published(tmp_path, monkeypatch):
    """Generator + Exporter case: a manifest naming a Generator `srcClips` intermediate
    does not stop the Exporter from re-exporting that slide -- the Exporter never
    reuses a Generator clip. After a successful apply, the consumed src/ intermediate
    is deleted and `srcClips` is dropped from the manifest; `source_slide` survives."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    src_dir = folder / "src"
    src_dir.mkdir(parents=True)
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    (src_dir / "Sermon (GW)_DSK.002.01.src.mov").write_bytes(b"mov")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {
            "2": {"category": "movie", "source_slide": 32, "srcClips": ["src/Sermon (GW)_DSK.002.01.src.mov"]},
            "3": {"category": "mixed", "source_slide": 33},
        },
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "mixed", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert seen == [[2, 3]], "both movie/mixed slides are re-exported; the src clip is never reused"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["slides"]["2"]["clip"] == "Sermon (GW)_DSK.002.mov"
    assert manifest["slides"]["2"]["source_slide"] == 32
    assert "srcClips" not in manifest["slides"]["2"]
    assert manifest["slides"]["3"]["clip"] == "Sermon (GW)_DSK.003.mov"
    assert job["result"]["clips"] == {"2": "Sermon (GW)_DSK.002.mov", "3": "Sermon (GW)_DSK.003.mov"}
    assert job["result"]["exportedClips"] == [2, 3]
    assert not (src_dir / "Sermon (GW)_DSK.002.01.src.mov").exists(), "the consumed src clip is deleted"


def test_dsk_export_apply_refuses_symlinked_src_dir(tmp_path, monkeypatch):
    """`out_dir/src` being a symlink must not let deletion escape the output tree."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    folder.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "Sermon (GW)_DSK.002.01.src.mov"
    victim.write_bytes(b"mov")
    src_dir = folder / "src"
    src_dir.symlink_to(outside, target_is_directory=True)
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {
            "2": {"category": "movie", "source_slide": 32, "srcClips": ["src/Sermon (GW)_DSK.002.01.src.mov"]},
        },
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert victim.is_file(), "a file outside out_dir must never be deleted via a symlinked src/"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert "srcClips" not in manifest["slides"]["2"], "the manifest key is still dropped after export"


def test_dsk_export_apply_refuses_traversal_and_symlinked_src_entries(tmp_path, monkeypatch):
    """A manifest `srcClips` entry that isn't a plain `src/<name>` path, or whose
    filename is itself a symlink, must be skipped rather than deleted or followed."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    src_dir = folder / "src"
    src_dir.mkdir(parents=True)
    outside = tmp_path / "outside.mov"
    outside.write_bytes(b"mov")
    (src_dir / "linked.mov").symlink_to(outside)
    kept = src_dir / "Sermon (GW)_DSK.002.01.src.mov"
    kept.write_bytes(b"mov")
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {
            "2": {
                "category": "movie", "source_slide": 32,
                "srcClips": [
                    "../outside.mov",
                    "src/linked.mov",
                    "src/Sermon (GW)_DSK.002.01.src.mov",
                ],
            },
        },
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert outside.is_file(), "the traversal target must never be deleted"
    assert (src_dir / "linked.mov").is_symlink(), "a symlinked candidate must never be followed or deleted"
    assert not kept.exists(), "the legitimate src clip is still deleted"


def test_dsk_export_apply_dedupes_duplicate_src_clip_entries(tmp_path, monkeypatch):
    """A duplicate `srcClips` entry (e.g. across two slides) must not raise on the
    second unlink of an already-deleted file."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    src_dir = folder / "src"
    src_dir.mkdir(parents=True)
    shared = src_dir / "Sermon (GW)_DSK.002.01.src.mov"
    shared.write_bytes(b"mov")
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {
            "2": {
                "category": "movie", "source_slide": 32,
                "srcClips": ["src/Sermon (GW)_DSK.002.01.src.mov"],
            },
            "3": {
                "category": "movie", "source_slide": 33,
                "srcClips": ["src/Sermon (GW)_DSK.002.01.src.mov"],
            },
        },
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert not shared.exists()


def test_dsk_export_apply_writes_drop_src_even_with_no_src_clips(tmp_path, monkeypatch):
    """`drop_src=True` must always be written after a successful export, even when
    the manifest had no `srcClips` entries to delete."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    folder.mkdir(parents=True)
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {"2": {"category": "movie", "source_slide": 32}},
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    manifest = json.loads((folder / "manifest.json").read_text())
    assert "srcClips" not in manifest["slides"]["2"]


def test_dsk_export_apply_failure_leaves_src_clips_in_place(tmp_path, monkeypatch):
    """A failed apply must not delete the Generator's src/ intermediates -- deletion only
    happens after a successful manifest write."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    src_dir = folder / "src"
    src_dir.mkdir(parents=True)
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    src_clip = src_dir / "Sermon (GW)_DSK.002.01.src.mov"
    src_clip.write_bytes(b"mov")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {
            "2": {"category": "movie", "source_slide": 32, "srcClips": ["src/Sermon (GW)_DSK.002.01.src.mov"]},
        },
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])

    def fake_clip_exporter_raises(*_a, **_k):
        raise RuntimeError("Keynote export failed")

    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", fake_clip_exporter_raises)

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "error"
    assert src_clip.is_file(), "src clip must survive a failed apply"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["slides"]["2"]["srcClips"] == ["src/Sermon (GW)_DSK.002.01.src.mov"]


def test_dsk_export_apply_writes_fresh_manifest_without_other_decks_entries(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    folder = tmp_path / "dsk"
    folder.mkdir(parents=True)
    deck_a = folder / "DeckA_DSK.key"
    deck_a.write_text("placeholder")
    deck_b = folder / "DeckB_DSK.key"
    deck_b.write_text("placeholder")
    (folder / "DeckA_DSK.002.mov").write_bytes(b"mov")
    (folder / "manifest.json").write_text(json.dumps({
        "deck": str(deck_a),
        "geometry": {"width": 1920, "height": 1080},
        "slides": {"2": {"category": "movie", "clip": "DeckA_DSK.002.mov"}},
    }))
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", lambda *_a, **_k: [])
    seen: list = []
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen))

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck_b)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert seen == [[2]], "slide 2 is re-exported for deck B; deck A's clip is not reused"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["deck"] == str(deck_b)
    assert "DeckA_DSK.002.mov" not in json.dumps(manifest)


def test_dsk_export_clip_refuses_a_non_fw_deck(tmp_path, monkeypatch):
    """Clip export is FW-only; the exporter has no clip-export endpoint of its own
    (§2.3) -- the FW-only refusal instead guards a stage export accidentally pointed
    at a deck that is not 1920x1080."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "Wall_FW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck)})
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["result"]["isStageDeck"] is False
    assert job["result"]["isFwDeck"] is True
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "1920x1080" in (job.get("error") or "")


def test_dsk_export_requires_slides_selected(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app)
    job_id = client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"]
    _wait(client, job_id)
    client.post(
        f"/api/dsk/export/{job_id}/decisions",
        json={"decisions": [{"slide": 1, "include": False}]},
    )
    applied = client.post(f"/api/dsk/export/{job_id}/apply")
    job = _wait(client, job_id)
    assert job["status"] == "error"
    assert "no slides selected" in (job.get("error") or "").lower()


def test_dsk_export_tag_allowed_by_validate_keynote(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "DSK.key"
    deck.write_text("placeholder")

    def fake_inspect(job, path, export, slide_range, *, outline=None, lw_final=True):
        return {"path": str(path), "flags": []}

    monkeypatch.setattr(app_mod, "_run_inspect", fake_inspect)
    client = TestClient(app)
    started = client.post(
        "/api/validate-keynote", data={"path": str(deck), "feature": "dsk-export"}
    )
    assert started.status_code == 200
    job_id = started.json()["id"]
    job = _wait(client, job_id)
    assert job["feature"] == "dsk-export"


def test_dsk_propose_quits_the_keynote_it_launched_for_previews(tmp_path, monkeypatch):
    """Plan §4 bug 1: a preview-export cache miss launches Keynote; propose must quit it
    again so apply's strictly-serial gate does not answer 409."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "Sermon (FW).key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    state = {"running": False}

    def fake_thumbs(*_a, **_k):
        state["running"] = True
        return {1: "0001.jpg"}

    quits = []

    def fake_quit(stem, doc_name, out_dir):
        quits.append((stem, doc_name, Path(out_dir)))
        state["running"] = False

    monkeypatch.setattr(app_mod, "build_preview_thumbs", fake_thumbs)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: state["running"])
    monkeypatch.setattr(app_mod, "quit_and_wait_for_exit", fake_quit)

    client = TestClient(app)
    job = _wait(client, _propose_dsk(client, deck).json()["id"])
    assert job["status"] == "done", job.get("error")
    assert quits == [("Sermon (FW)", "Sermon (FW).key", tmp_path / "output" / "Sermon (FW)" / "dsk")]
    assert quits[0][2].is_dir()
    assert state["running"] is False


def test_dsk_propose_leaves_an_operator_keynote_alone(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "Sermon (FW).key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")}, thumbs={1: "0001.jpg"})
    monkeypatch.setattr(app_mod, "keynote_running", lambda: True)

    def forbidden_quit(*_a, **_k):
        raise AssertionError("must not quit a Keynote the operator had open")

    monkeypatch.setattr(app_mod, "quit_and_wait_for_exit", forbidden_quit)

    client = TestClient(app)
    job = _wait(client, _propose_dsk(client, deck).json()["id"])
    assert job["status"] == "done", job.get("error")


def test_dsk_export_propose_quits_the_keynote_it_launched(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "hand_built_DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    state = {"running": False}

    def fake_thumbs(*_a, **_k):
        state["running"] = True
        return {}

    quits = []
    monkeypatch.setattr(app_mod, "build_preview_thumbs", fake_thumbs)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: state["running"])
    monkeypatch.setattr(app_mod, "quit_and_wait_for_exit", lambda *a: quits.append(a))

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck)})
    job = _wait(client, started.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert [q[:2] for q in quits] == [("hand_built_DSK", "hand_built_DSK.key")]
