"""API tests for the DSK Generator (P3) and Exporter (P4) dashboard endpoints.

Everything Keynote-shaped is monkeypatched: `assemble_dsk_deck`, `export_slide_clips`,
`export_stage_pngs`, `stage_counts`, `classify_deck` and `build_preview_thumbs` are all
faked, mirroring `tests/test_dashboard_api.py`'s resize tests. No test may start Keynote.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
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
    import obed_edom.web.app as app_mod

    # The offline layout-import precondition (contract A) actually parses the
    # template/FW `.key` IWA archives; the fixture decks here are plain text
    # stand-ins, so it is a no-op by default. Tests exercising the precondition
    # itself re-patch this to something that raises.
    monkeypatch.setattr(app_mod, "check_layout_import_preconditions", lambda *_a, **_k: None)
    monkeypatch.setattr(app_mod, "owned_alpha_safe_layout", lambda *_a, **_k: None)
    yield


_DSK_TEMPLATE_FIXTURE_NAME = "_dsk_template_fixture.key"


def _wait(client, job_id, tries=120):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _wait_for_progress_step(client, job_id, step, tries=200):
    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        progress = job.get("progress")
        if progress and progress.get("step") == step:
            return progress
        if job["status"] in {"done", "error"}:
            raise AssertionError(f"job finished before reaching progress step {step}: {job}")
        time.sleep(0.01)
    raise AssertionError(f"job never reached progress step {step}")


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
    if "dsk_template" not in data:
        template = deck.parent / _DSK_TEMPLATE_FIXTURE_NAME
        if not template.exists():
            template.write_text("template fixture")
        data["dsk_template"] = str(template)
    return client.post("/api/dsk", data=data)


def test_v2_apply_exports_compiled_occurrences_and_writes_composition_manifest(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod
    from obed_edom.dsk_assemble import AssembleResult
    from obed_edom.dsk_movie_export import ClipResult
    from obed_edom.map_remap import Rect

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "index": 0, "items": [{
            "kind": "movie", "kindIndex": 0, "index": 0, "fileName": "clip.mov",
            "x": 1920, "y": 0, "w": 3840, "h": 1080,
        }]}],
    }
    cls = SlideClass(1, "movie", 0, 1, (("movie", 0),), (), (), None, False)
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _path: payload)
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: [cls])
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: {1: "slide-1.png"})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _path: "bound")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _digest: tmp_path)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "_dsk_archive_ids", lambda _path: {(1, "movie", 0): "movie-1"})
    monkeypatch.setattr(app_mod, "_dsk_build_records", lambda _path: {})
    observed = {}

    def fake_export(_deck, slides, out_dir, *, movie_plans, **_kwargs):
        observed["movie_plans"] = movie_plans
        target = Path(out_dir) / "compiled.mov"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("clip")
        plan = movie_plans[0]
        return [ClipResult(
            slide=plan.source_slide, movie_id=plan.source_item, path=target,
            width=935, height=263, duration_s=1, wall_s=1, crop_width=935,
            crop_rect=Rect(1920, 0, 3840, 1080), occurrence_id=plan.occurrence_id,
        )]

    def fake_assemble(_deck, out_path, *, compiled_compositions, compiled_clips, **_kwargs):
        observed["compiled"] = compiled_compositions
        observed["clips"] = compiled_clips
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("deck")
        synthetic = ("movie", 1_000_000)
        occurrence = compiled_compositions[0].media[0].occurrence_id
        return AssembleResult(
            path=Path(out_path), slides_kept=(1,), ordinals={1: 1}, fits={},
            clips_inserted={1: {synthetic: compiled_clips[occurrence]}}, stroke={}, zorder={},
            builds={}, size_bytes=4, source_size_bytes=7, wall_s=1, warnings=(), movie_props={},
            clip_rects={1: {synthetic: Rect(43, 802, 935, 263)}},
            clip_occurrences={1: {synthetic: occurrence}},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)
    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    proposed = _wait(client, job_id)
    review = proposed["result"]["review"]
    envelope = {
        "schemaVersion": 2,
        "sourceFingerprint": review["source"]["fingerprint"],
        "defaults": review["defaults"],
        "decisions": [{"id": comp["id"], **comp["decision"]} for comp in review["compositions"]],
    }
    response = client.post(
        f"/api/dsk/{job_id}/apply",
        json={"review": envelope, "baseRevision": 0, "exportDir": str(tmp_path / "workspace")},
    )
    assert response.status_code == 200
    done = _wait(client, job_id)
    assert done["status"] == "done", done.get("error")
    assert len(observed["movie_plans"]) == 1
    assert len(observed["compiled"]) == 1
    manifest = json.loads((tmp_path / "workspace" / "manifest.json").read_text())
    assert manifest["slides"]["1"]["composition_id"] == "slide:1"
    assert manifest["slides"]["1"]["media"][0]["occurrence_id"] == "1:movie-1"


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
            clips_inserted={2: dict(clips[2])},
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


def test_dsk_apply_publishes_clips_in_visual_not_crop_rect_order(tmp_path, monkeypatch):
    """Publish must name clips by the assembler's `result.clips_inserted` order (the
    real, left-to-right placement it committed), not by sorting `ClipResult.crop_rect`
    x-offsets. The ClipResults here carry crop rects whose x-sort would pick the
    OPPOSITE order from `clips_inserted`, proving crop rects are no longer the
    authority: the LEFT movie is `.002.01.src.mov` and the RIGHT movie is
    `.002.02.src.mov`, and the manifest `srcClips` / job `clips` order must match."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "mixed", movie_count=2)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    from obed_edom.dsk_movie_export import ClipResult
    from obed_edom.map_remap import Rect

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        right = Path(out_dir) / "right.mov"
        left = Path(out_dir) / "left.mov"
        right.write_text("movie")
        left.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=right, crop_rect=Rect(1000, 0, 500, 1080),
                width=500, height=1080, duration_s=1.0, wall_s=1.0, crop_width=500,
            ),
            ClipResult(
                slide=2, movie_id=("movie", 1), path=left, crop_rect=Rect(5000, 0, 500, 1080),
                width=500, height=1080, duration_s=1.0, wall_s=1.0, crop_width=500,
            ),
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, clip_sizes, clip_crops, content_only, **kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path,
            slides_kept=(1, 2),
            ordinals={1: 1, 2: 2},
            fits={},
            clips_inserted={2: {("movie", 1): clips[2][("movie", 1)], ("movie", 0): clips[2][("movie", 0)]}},
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

    out_dir = tmp_path / "output" / "GW" / "dsk"
    left_dest = out_dir / "src" / "GW_DSK.002.01.src.mov"
    right_dest = out_dir / "src" / "GW_DSK.002.02.src.mov"
    assert left_dest.is_file(), "the LEFT movie (first in clips_inserted) must be MM=01"
    assert right_dest.is_file(), "the RIGHT movie (second in clips_inserted) must be MM=02"
    assert job["result"]["clips"] == {
        "2": ["src/GW_DSK.002.01.src.mov", "src/GW_DSK.002.02.src.mov"]
    }
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["slides"]["2"]["srcClips"] == [
        "src/GW_DSK.002.01.src.mov",
        "src/GW_DSK.002.02.src.mov",
    ]


def test_dsk_apply_forwards_bare_clips_from_the_export(tmp_path, monkeypatch):
    """Plan §4 item 30(d): only a clip the exporter bared may take the source build-in, so
    the dashboard must carry `ClipResult.bare` through to `assemble_dsk_deck` per movie
    item -- the upper stacked clip is listed, the one below it is not."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "mixed", movie_count=2)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    from obed_edom.dsk_movie_export import ClipResult
    from obed_edom.map_remap import Rect

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        lower = Path(out_dir) / "lower.mov"
        upper = Path(out_dir) / "upper.mov"
        lower.write_text("movie")
        upper.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=lower, crop_rect=Rect(1000, 0, 500, 1080),
                width=500, height=1080, duration_s=1.0, wall_s=1.0, crop_width=500,
            ),
            ClipResult(
                slide=2, movie_id=("movie", 1), path=upper, crop_rect=Rect(1000, 0, 500, 1080),
                width=500, height=1080, duration_s=1.0, wall_s=1.0, crop_width=500, bare=True,
            ),
        ]

    seen = {}

    def fake_assemble(fw, out_path, *, decisions, clips, **kwargs):
        seen["bare_clips"] = kwargs.get("bare_clips")
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path,
            slides_kept=(1, 2),
            ordinals={1: 1, 2: 2},
            fits={},
            clips_inserted={2: dict(clips[2])},
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

    assert seen["bare_clips"] == {2: {("movie", 1)}}


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
                clips_inserted={n: dict(clips[n]) for n in clips},
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
            clips_inserted={n: dict(clips[n]) for n in clips},
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


def test_dsk_apply_export_failure_mid_batch_leaves_no_temp_dir(tmp_path, monkeypatch):
    """If `export_slide_clips` raises partway through a batch, the per-run
    `.src-<uuid>` directory must not be left behind."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    def failing_export(fw, slides, out_dir, **_kwargs):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "clip.002.mov").write_text("movie")
        raise RuntimeError("export failed mid-batch")

    def unexpected_assemble(*_a, **_k):
        raise AssertionError("assembly must not run once export fails")

    monkeypatch.setattr(app_mod, "export_slide_clips", failing_export)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", unexpected_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"

    out_dir = tmp_path / "output" / "GW" / "dsk"
    if out_dir.is_dir():
        leftover_tmp = [p for p in out_dir.iterdir() if p.name.startswith(".src-")]
        assert leftover_tmp == [], f"no .src-* dir expected, found: {leftover_tmp}"


def test_dsk_apply_manifest_write_failure_removes_this_runs_published_clips(tmp_path, monkeypatch):
    """If the manifest write fails after publication, the clips this run published
    into `src/` are removed, and the previous manifest is left intact."""
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
                clips_inserted={n: dict(clips[n]) for n in clips},
                size_bytes=10, source_size_bytes=20, wall_s=1.0,
                warnings=(), movie_props={},
            )

        return fake_assemble

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)

    client = TestClient(app)

    # Run 1 succeeds and publishes a manifest with a clip for slide 2.
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", make_fake_assemble({1: 1, 2: 2}))
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    manifest_path = out_dir / "manifest.json"
    previous_manifest = manifest_path.read_text()

    # Run 2: assembly succeeds and publication runs, but the manifest write fails.
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes2 = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes2)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", make_fake_assemble({1: 1, 2: 2, 3: 3}))

    def failing_write_manifest(*_a, **_k):
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(app_mod, "write_manifest", failing_write_manifest)
    job_id2 = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id2)
    applied2 = client.post(f"/api/dsk/{job_id2}/apply")
    assert applied2.status_code == 200
    job2 = _wait(client, job_id2)
    assert job2["status"] == "error"

    assert not (src_dir / "GW_DSK.003.01.src.mov").is_file(), "run 2's new clip must be rolled back"
    assert manifest_path.read_text() == previous_manifest, "the previous manifest must be left intact"
    leftover_tmp = [p for p in out_dir.iterdir() if p.name.startswith(".src-")]
    assert leftover_tmp == [], f"no .src-* dir expected, found: {leftover_tmp}"


def test_dsk_apply_publish_failure_on_later_destination_leaves_no_new_file(tmp_path, monkeypatch):
    """If publishing slide 2's clip succeeds but writing slide 3's clip then fails,
    the already-written slide 2 file must not survive -- it was new this run, so
    rollback removes it rather than leaving a half-published run behind."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    def fake_export_clips(fw, slides, out_dir, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir).mkdir(parents=True, exist_ok=True)
        results = []
        for n in slides:
            dest = Path(out_dir) / f"clip.{n:03d}.mov"
            dest.write_text(f"movie-{n}")
            results.append(
                ClipResult(
                    slide=n, movie_id=("movie", 0), path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
                )
            )
        return results

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2, 3), ordinals={1: 1, 2: 2, 3: 3}, fits={},
            clips_inserted={n: dict(clips[n]) for n in clips}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    # Freshly exported intermediates are moved via os.replace; count both write
    # mechanisms so the second destination write is the one that fails regardless
    # of which one the publisher picks for a given source.
    real_copy2 = shutil.copy2
    real_replace = app_mod.os.replace
    calls: list[Path] = []

    def flaky_copy2(src, dst, *a, **k):
        if Path(dst).name.startswith("GW_DSK."):
            calls.append(Path(dst))
            if len(calls) >= 2:
                raise OSError("disk full")
        return real_copy2(src, dst, *a, **k)

    def flaky_replace(src, dst, *a, **k):
        if Path(dst).name.startswith("GW_DSK."):
            calls.append(Path(dst))
            if len(calls) >= 2:
                raise OSError("disk full")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(app_mod.shutil, "copy2", flaky_copy2)
    monkeypatch.setattr(app_mod.os, "replace", flaky_replace)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "error"

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    assert len(calls) == 2, "the second destination write is the one that fails"
    assert not (src_dir / "GW_DSK.002.01.src.mov").is_file(), "the earlier successful write is rolled back"
    assert not (src_dir / "GW_DSK.003.01.src.mov").is_file(), "the failed write leaves no file"
    assert not (out_dir / "manifest.json").exists(), "no manifest is committed on this first-ever run"


def test_dsk_apply_rerun_overwrite_failure_restores_original_bytes(tmp_path, monkeypatch):
    """A rerun that overwrites slide 2's clip and then fails the manifest write
    must restore slide 2's original bytes, and the previous manifest must still
    reference a file that exists on disk."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def make_fake_export_clips(content):
        def fake_export_clips(fw, slides, out_dir, **_kwargs):
            from obed_edom.dsk_movie_export import ClipResult

            Path(out_dir).mkdir(parents=True, exist_ok=True)
            results = []
            for n in slides:
                dest = Path(out_dir) / f"clip.{n:03d}.mov"
                dest.write_text(content)
                results.append(
                    ClipResult(
                        slide=n, movie_id=("movie", 0), path=dest, crop_rect=None,
                        width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
                    )
                )
            return results

        return fake_export_clips

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
            movie_props={},
        )

    client = TestClient(app)

    # Run 1 succeeds and publishes slide 2's clip with original content.
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "export_slide_clips", make_fake_export_clips("movie-v1"))
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    manifest_path = out_dir / "manifest.json"
    published = src_dir / "GW_DSK.002.01.src.mov"
    assert published.read_text() == "movie-v1"
    previous_manifest = manifest_path.read_text()

    # Run 2: publication overwrites slide 2's clip, then the manifest write fails.
    monkeypatch.setattr(app_mod, "export_slide_clips", make_fake_export_clips("movie-v2"))

    def failing_write_manifest(*_a, **_k):
        raise RuntimeError("manifest write failed")

    monkeypatch.setattr(app_mod, "write_manifest", failing_write_manifest)
    job_id2 = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id2)
    applied2 = client.post(f"/api/dsk/{job_id2}/apply")
    assert applied2.status_code == 200
    job2 = _wait(client, job_id2)
    assert job2["status"] == "error"

    assert published.is_file(), "the overwritten clip must survive as a file"
    assert published.read_text() == "movie-v1", "the original bytes are restored"
    assert manifest_path.read_text() == previous_manifest, "the previous manifest is left intact"
    assert published.is_file(), "the previous manifest's srcClips entry still resolves to a real file"
    leftover_backups = [p for p in src_dir.iterdir() if ".prev-" in p.name]
    assert leftover_backups == [], f"no backup file expected to remain, found: {leftover_backups}"


def test_dsk_apply_refuses_symlinked_src_dir(tmp_path, monkeypatch):
    """Publication must refuse when `out_dir/src` is a symlink rather than follow it."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    out_dir = tmp_path / "output" / "GW" / "dsk"
    out_dir.mkdir(parents=True)
    outside = tmp_path / "outside-src"
    outside.mkdir()
    (out_dir / "src").symlink_to(outside, target_is_directory=True)

    def fake_export_clips(fw, slides, out_dir_, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir_).mkdir(parents=True, exist_ok=True)
        dest = Path(out_dir_) / "clip.002.mov"
        dest.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=dest, crop_rect=None,
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
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
    assert job["status"] == "error"
    assert "symlink" in job["error"]
    assert list(outside.iterdir()) == [], "nothing is written through the symlink"


def test_dsk_apply_refuses_symlinked_destination_file(tmp_path, monkeypatch):
    """Publication must refuse when a destination clip path is itself a symlink,
    rather than overwrite whatever it points at."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    src_dir.mkdir(parents=True)
    victim = tmp_path / "victim.mov"
    victim.write_text("do not overwrite")
    (src_dir / "GW_DSK.002.01.src.mov").symlink_to(victim)

    def fake_export_clips(fw, slides, out_dir_, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir_).mkdir(parents=True, exist_ok=True)
        dest = Path(out_dir_) / "clip.002.mov"
        dest.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=dest, crop_rect=None,
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
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
    assert job["status"] == "error"
    assert "symlink" in job["error"]
    assert victim.read_text() == "do not overwrite"


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
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={},
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


def test_dsk_apply_stale_cleanup_failure_still_succeeds(tmp_path, monkeypatch):
    """A rerun that drops a movie slide must still succeed, with the new clip and
    manifest committed, even if deleting the now-orphaned intermediate fails --
    stale cleanup runs after commit and must be best-effort."""
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
                clips_inserted={n: dict(clips[n]) for n in clips},
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

    # Run 2: slide 3 is gone, so clip_3 becomes stale; deleting it fails.
    real_unlink = Path.unlink

    def flaky_unlink(self, *a, **k):
        if self == clip_3:
            raise OSError("permission denied")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

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

    assert clip_2.is_file(), "the new run's published clip is intact"
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert "3" not in manifest["slides"], "the new manifest is committed regardless of cleanup failure"


def test_dsk_apply_operator_clip_inside_src_dir_survives_later_rollback(tmp_path, monkeypatch):
    """An operator-supplied clip that happens to live inside `out_dir/src` must be
    copied, never moved: if a later destination in the same run fails and rollback
    undoes this run's publications, the operator's original file must still exist
    at its original path."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(3))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1), 3: _cls(3, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "_ffprobe", lambda _p: (1920, 1080, 30.0, 1.0))

    out_dir = tmp_path / "output" / "GW" / "dsk"
    src_dir = out_dir / "src"
    src_dir.mkdir(parents=True)
    operator_clip = src_dir / "operator-owned.mov"
    operator_clip.write_text("operator's own clip")

    def fake_export_clips(fw, slides, out_dir_, **_kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        Path(out_dir_).mkdir(parents=True, exist_ok=True)
        results = []
        for n in slides:
            dest = Path(out_dir_) / f"clip.{n:03d}.mov"
            dest.write_text(f"movie-{n}")
            results.append(
                ClipResult(
                    slide=n, movie_id=("movie", 0), path=dest, crop_rect=None,
                    width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
                )
            )
        return results

    def fake_assemble(fw, out_path, *, decisions, clips, content_only, **_kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2, 3), ordinals={1: 1, 2: 2, 3: 3}, fits={},
            clips_inserted={n: dict(clips[n]) for n in clips}, stroke={}, zorder={},
            builds={}, size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    # The operator's clip (slide 2) is copied and succeeds; slide 3's freshly
    # exported intermediate is moved via os.replace and fails, forcing rollback.
    real_replace = app_mod.os.replace

    def flaky_replace(src, dst, *a, **k):
        if Path(dst).name.startswith("GW_DSK.003."):
            raise OSError("disk full")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(app_mod.os, "replace", flaky_replace)

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

    assert operator_clip.is_file(), "the operator's own file must survive at its original path"
    assert operator_clip.read_text() == "operator's own clip"
    assert not (src_dir / "GW_DSK.002.01.src.mov").is_file(), "the rolled-back new destination leaves no file"
    assert not (src_dir / "GW_DSK.003.01.src.mov").is_file(), "the failed write leaves no file"


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
            clips_inserted={5: dict(clips[5])},
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


def test_dsk_export_apply_succeeds_when_intermediate_deletion_fails(tmp_path, monkeypatch):
    """The final manifest is committed with `srcClips` already dropped before
    cleanup runs, so a failure deleting a src/ intermediate is logged but does not
    fail the apply, and never leaves the manifest pointing at a deleted file."""
    import obed_edom.web.app as app_mod

    folder = tmp_path / "Sermon (GW)" / "dsk"
    src_dir = folder / "src"
    src_dir.mkdir(parents=True)
    deck = folder / "Sermon (GW)_DSK.key"
    deck.write_text("placeholder")
    stale = src_dir / "Sermon (GW)_DSK.002.01.src.mov"
    stale.write_bytes(b"mov")
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

    real_unlink = Path.unlink

    def flaky_unlink(self, *a, **k):
        if self == stale:
            raise OSError("permission denied")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    client = TestClient(app)
    job = _wait(client, client.post("/api/dsk/export", data={"path": str(deck)}).json()["id"])
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    assert stale.is_file(), "the file that failed to delete is still on disk"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert "srcClips" not in manifest["slides"]["2"], "the final manifest never references the file"
    assert manifest["slides"]["2"]["clip"] == "Sermon (GW)_DSK.002.mov"


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


def test_dsk_apply_writes_deck_into_chosen_workspace(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    workspace = tmp_path / "sunday"
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    classes = {1: _cls(1, "static")}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "export_slide_clips", lambda *_a, **_k: [])

    def fake_assemble(fw, out_path, **kwargs):
        from obed_edom.dsk_assemble import AssembleResult

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("deck")
        return AssembleResult(
            path=out_path,
            slides_kept=(1,),
            ordinals={1: 1},
            fits={},
            clips_inserted={},
            stroke={},
            zorder={},
            builds={},
            size_bytes=10,
            source_size_bytes=20,
            wall_s=1.0,
            warnings=(),
            movie_props={},
        )

    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply", json={"exportDir": str(workspace)})
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["exportDir"] == str(workspace.resolve())
    assert Path(job["result"]["deckPath"]) == workspace.resolve() / "GW_DSK.key"
    assert (workspace / "GW_DSK.key").is_file()
    assert not (tmp_path / "output" / "GW" / "dsk" / "GW_DSK.key").exists()


def test_dsk_export_writes_assets_to_chosen_dir_and_cleans_deck_src(tmp_path, monkeypatch):
    """A chosen export folder receives the playback assets; Generator src/ next to
    the deck is still cleaned up."""
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
        },
    }))
    export_dir = tmp_path / "playback"
    seen = {}

    def fake_export_stage_pngs(deck_path, slides, out_dir, **kwargs):
        seen["export"] = (deck_path, list(slides), Path(out_dir))
        from obed_edom.dsk_stage_export import StageAsset

        return [
            StageAsset(
                slide=n, stage_index=1, path=Path(out_dir) / f"{n:04d}.001.png",
                width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
                content_alpha_frac=1.0, transparent_frac=0.0, source_name="x",
            )
            for n in slides
        ]

    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "stage_counts", lambda *_a, **_k: {1: 1})
    monkeypatch.setattr(app_mod, "export_stage_pngs", fake_export_stage_pngs)
    monkeypatch.setattr(app_mod, "export_dsk_slide_clips", _fake_clip_exporter(seen.setdefault("clips", [])))

    client = TestClient(app)
    started = client.post("/api/dsk/export", data={"path": str(deck), "export_dir": str(export_dir)})
    job = _wait(client, started.json()["id"])
    assert job["result"]["exportDir"] == str(export_dir.resolve())
    job = _wait(client, client.post(f"/api/dsk/export/{job['id']}/apply").json()["id"])
    assert job["status"] == "done", job.get("error")
    result = job["result"]
    assert result["pngDir"] == str(export_dir.resolve())
    assert result["exportDir"] == str(export_dir.resolve())
    assert seen["export"][2] == export_dir.resolve()
    assert seen["clips"] == [[2]]
    assert (export_dir / "Sermon (GW)_DSK.002.mov").is_file()
    export_manifest = json.loads((export_dir / "manifest.json").read_text())
    assert export_manifest["slides"]["2"]["clip"] == "Sermon (GW)_DSK.002.mov"
    deck_manifest = json.loads((folder / "manifest.json").read_text())
    assert "srcClips" not in deck_manifest["slides"]["2"]
    assert deck_manifest["slides"]["2"]["source_slide"] == 32
    assert not (src_dir / "Sermon (GW)_DSK.002.01.src.mov").exists()


def test_dsk_export_rejects_private_root_export_dir(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod
    from obed_edom.paths import output_root

    deck = tmp_path / "hand_built_DSK.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _dsk_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    client = TestClient(app)
    response = client.post(
        "/api/dsk/export",
        data={"path": str(deck), "export_dir": str(output_root() / ".watercolour")},
    )
    assert response.status_code == 400


def _movie_cls(number, *, movie_ids, movie_count=None, category="movie", is_text=False):
    """A class whose `kept` carries real top-level movie ids — what `canVideosOnly` reads.
    `movie_count` defaults to len(movie_ids); pass a larger number to model a movie
    hidden inside a group, which must disqualify the slide."""
    return SlideClass(
        number=number,
        category=category,
        build_count=0,
        movie_count=len(movie_ids) if movie_count is None else movie_count,
        kept=tuple(movie_ids) + (("shape", 0),),
        dropped_side=(),
        dropped_backdrop=(),
        transition=None,
        is_text=is_text,
    )


def _movie_item(kind_index, x, y, w=1000, h=600):
    return {"kind": "movie", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _fw_payload_with_items(items_by_slide, count=4):
    payload = _fw_payload(count)
    for slide in payload["slides"]:
        slide["items"] = list(items_by_slide.get(slide["number"], []))
    return payload


def test_dsk_propose_emits_can_videos_only_and_stacked_movies(tmp_path, monkeypatch):
    """canVideosOnly needs every counted movie to be a kept TOP-LEVEL item; stackedMovies
    means two kept movies overlap across nearly all of the smaller one (the
    `_MOVIE_STACK_OVERLAP` threshold, 0.9 since 2026-09-20)."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    items = {
        # 2: one movie, nothing to stack with.
        2: [_movie_item(0, 2000, 100)],
        # 3: two movies dissolving over one another (intersection 980x590 = 96% of the
        # smaller 1000x600, clearing the 0.9 threshold).
        3: [_movie_item(0, 2000, 100), _movie_item(1, 2020, 110)],
        # 4: a second movie lives inside a group, so movie_count outruns the kept ids.
        4: [_movie_item(0, 2000, 100)],
    }
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload_with_items(items))
    classes = {
        1: _cls(1, "static"),
        2: _movie_cls(2, movie_ids=(("movie", 0),)),
        3: _movie_cls(3, movie_ids=(("movie", 0), ("movie", 1))),
        4: _movie_cls(4, movie_ids=(("movie", 0),), movie_count=2, category="mixed"),
    }
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    pages = {p["slide"]: p for p in job["result"]["pages"]}
    assert (pages[1]["canVideosOnly"], pages[1]["stackedMovies"]) == (False, False)
    assert (pages[2]["canVideosOnly"], pages[2]["stackedMovies"]) == (True, False)
    assert (pages[3]["canVideosOnly"], pages[3]["stackedMovies"]) == (True, True)
    assert (pages[4]["canVideosOnly"], pages[4]["stackedMovies"]) == (False, False)
    assert all(p["decision"]["videosOnly"] is False for p in pages.values())


def test_dsk_propose_does_not_stack_movies_that_merely_touch(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    items = {1: [_movie_item(0, 2000, 100, w=800), _movie_item(1, 4000, 100, w=800)]}
    monkeypatch.setattr(
        app_mod, "offline_wall_payload", lambda _p: _fw_payload_with_items(items, count=1)
    )
    classes = {1: _movie_cls(1, movie_ids=(("movie", 0), ("movie", 1)))}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    job = _wait(client, job_id)
    pages = {p["slide"]: p for p in job["result"]["pages"]}
    assert pages[1]["canVideosOnly"] is True
    assert pages[1]["stackedMovies"] is False
    assert pages[1]["stackedMoviesKeepSide"] is False


def test_dsk_propose_stacked_flag_has_a_keep_side_variant(tmp_path, monkeypatch):
    """Codex r2 (plan §4 item 30c): with Keep side on, the assembler decides stacking on the
    WHOLE-WALL visible rects. Two movies that only layer on the left side panel are not
    stacked for the centre-panel crop (nothing of them overlaps there) but are with Keep
    side -- the review chip needs both answers."""
    from obed_edom.web import app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    items = {1: [_movie_item(0, 0, 100, w=2400), _movie_item(1, 100, 120, w=1700)]}
    monkeypatch.setattr(
        app_mod, "offline_wall_payload", lambda _p: _fw_payload_with_items(items, count=1)
    )
    classes = {1: _movie_cls(1, movie_ids=(("movie", 0), ("movie", 1)))}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    job = _wait(client, job_id)
    page = job["result"]["pages"][0]
    assert page["stackedMovies"] is False
    assert page["stackedMoviesKeepSide"] is True


def test_dsk_decisions_roundtrip_videos_only_and_force_false_where_unavailable(
    tmp_path, monkeypatch
):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    items = {2: [_movie_item(0, 2000, 100)]}
    monkeypatch.setattr(
        app_mod, "offline_wall_payload", lambda _p: _fw_payload_with_items(items, count=2)
    )
    classes = {1: _cls(1, "static"), 2: _movie_cls(2, movie_ids=(("movie", 0),))}
    _patch_common(monkeypatch, app_mod, classes=classes)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    res = client.post(
        f"/api/dsk/{job_id}/decisions",
        json={
            "decisions": [
                {"slide": 1, "videosOnly": True},
                {"slide": 2, "videosOnly": True, "anchor": "left"},
            ]
        },
    )
    assert res.status_code == 200
    pages = {p["slide"]: p for p in res.json()["result"]["pages"]}
    # Slide 1 has no movies at all, so the server pins it false.
    assert pages[1]["decision"]["videosOnly"] is False
    assert pages[2]["decision"]["videosOnly"] is True
    assert pages[2]["decision"]["anchor"] == "left"


def test_dsk_apply_passes_videos_only_through_to_the_assembler(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    items = {2: [_movie_item(0, 2000, 100)]}
    monkeypatch.setattr(
        app_mod, "offline_wall_payload", lambda _p: _fw_payload_with_items(items, count=2)
    )
    classes = {1: _cls(1, "static"), 2: _movie_cls(2, movie_ids=(("movie", 0),))}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    seen = {}

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        from obed_edom.dsk_movie_export import ClipResult

        dest = Path(out_dir) / "clip.001.mov"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dest.write_text("movie")
        return [
            ClipResult(
                slide=2, movie_id=("movie", 0), path=dest, crop_rect=None,
                width=1920, height=1080, duration_s=1.0, wall_s=1.0, crop_width=1920,
            )
        ]

    def fake_assemble(fw, out_path, *, decisions, clips, **kwargs):
        seen["decisions"] = decisions
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path,
            slides_kept=(1, 2),
            ordinals={1: 1, 2: 2},
            fits={},
            clips_inserted={2: dict(clips[2])},
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
        json={
            "decisions": [
                {"slide": 1, "videosOnly": True},
                {"slide": 2, "videosOnly": True, "anchor": "right"},
            ]
        },
    )
    client.post(f"/api/dsk/{job_id}/apply")
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["decisions"][2].videos_only is True
    assert seen["decisions"][2].anchor == "right"
    # Slide 1 cannot take it, so the flag never reaches the assembler as True.
    assert seen["decisions"][1].videos_only is False


def test_dsk_export_propose_pages_default_videos_only_false(tmp_path, monkeypatch):
    """Exporter pages carry no `canVideosOnly`, so the shared decision plumbing must
    treat them as incapable rather than crash or let the flag through."""
    import obed_edom.web.app as app_mod

    result = {
        "contentOnly": False,
        "pages": [{"slide": 1, "category": "movie", "isText": False, "needsClip": True}],
    }
    app_mod._apply_dsk_decisions(result, [{"slide": 1, "videosOnly": True}])
    assert result["pages"][0]["decision"]["videosOnly"] is False


# --- DSK template (contract A) -------------------------------------------------


def test_dsk_propose_refuses_blank_template(tmp_path):
    deck = tmp_path / "FW.key"
    deck.write_text("fixture")

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "dsk_template": ""})
    assert res.status_code == 400
    assert res.json()["detail"] == {
        "field": "dskTemplate",
        "message": "Choose the DSK template (.key): FW.key has no transparent 'Blank Black' layout and no reference deck supplies one.",
    }


def test_dsk_propose_needs_no_template_when_fw_deck_owns_blank_black(tmp_path, monkeypatch):
    """Donor hierarchy tier 1: the FW deck already owns an alpha-safe transparent layout, so
    no template is required and the proposal records an empty donor."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    monkeypatch.setattr(app_mod, "owned_alpha_safe_layout", lambda _deck, names: names[0])

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "dsk_template": ""})
    assert res.status_code == 200, res.text
    job = _wait(client, res.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["dskTemplate"] == ""


def test_dsk_propose_reference_deck_donates_before_template(tmp_path, monkeypatch):
    """Donor hierarchy tier 2: a reference deck that passes the layout-import precondition
    is the donor, and the template is not consulted at all."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    reference = tmp_path / "Reference_DSK.key"
    reference.write_text("reference")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    seen = []
    monkeypatch.setattr(
        app_mod, "check_layout_import_preconditions",
        lambda fw_deck, *, layout_template, layout_names: seen.append(layout_template),
    )

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "reference_deck": str(reference), "dsk_template": ""})
    assert res.status_code == 200, res.text
    job = _wait(client, res.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert job["result"]["dskTemplate"] == str(reference.resolve())
    assert seen == [reference]


def test_dsk_propose_falls_back_to_template_when_reference_cannot_donate(tmp_path, monkeypatch):
    """Donor hierarchy tier 3: a reference deck that fails the precondition is skipped and
    the template is validated instead."""
    import obed_edom.web.app as app_mod
    from obed_edom.dsk_assemble import AssemblyRefusal

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    reference = tmp_path / "Reference_DSK.key"
    reference.write_text("reference")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    def check(fw_deck, *, layout_template, layout_names):
        if layout_template == reference:
            raise AssemblyRefusal("no layout named 'Blank Black' found in layout template")

    monkeypatch.setattr(app_mod, "check_layout_import_preconditions", check)

    client = TestClient(app)
    res = client.post(
        "/api/dsk", data={"path": str(deck), "reference_deck": str(reference), "dsk_template": str(template)}
    )
    assert res.status_code == 200, res.text
    job = _wait(client, res.json()["id"])
    assert job["result"]["dskTemplate"] == str(template.resolve())


def test_dsk_apply_honours_an_explicit_template_override_even_when_no_donor_is_needed(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    monkeypatch.setattr(app_mod, "owned_alpha_safe_layout", lambda _deck, names: names[0])
    seen = {}
    monkeypatch.setattr(app_mod, "_run_dsk_apply", lambda _job, proposal: seen.update(proposal) or {})

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template="").json()["id"]
    assert _wait(client, job_id)["result"]["dskTemplate"] == ""
    res = client.post(f"/api/dsk/{job_id}/apply", json={"decisions": [], "dskTemplate": str(template)})
    assert res.status_code == 200, res.text
    _wait(client, job_id)
    assert seen["dskTemplate"] == str(template.resolve())


def test_dsk_propose_full_text_path_always_requires_template(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    monkeypatch.setattr(app_mod, "owned_alpha_safe_layout", lambda _deck, names: names[0])

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "dsk_template": "", "content_only": "false"})
    assert res.status_code == 400
    assert res.json()["detail"]["field"] == "dskTemplate"


def test_dsk_propose_refuses_missing_template_field(tmp_path):
    deck = tmp_path / "FW.key"
    deck.write_text("fixture")

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck)})
    assert res.status_code == 400
    assert res.json()["detail"]["field"] == "dskTemplate"


def test_dsk_propose_refuses_template_not_found(tmp_path):
    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    missing = tmp_path / "nope.key"

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "dsk_template": str(missing)})
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["field"] == "dskTemplate"
    assert str(missing) in detail["message"]
    assert "Choose on this Mac" in detail["message"]


def test_dsk_propose_stores_dsk_template_in_result(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["result"]["dskTemplate"] == str(template)


def test_dsk_propose_runs_offline_layout_precondition(tmp_path, monkeypatch):
    """The offline `check_layout_import_preconditions` refusal (contract A) surfaces
    as the same structured 400 as a missing/blank template."""
    import obed_edom.web.app as app_mod
    from obed_edom.dsk_assemble import AssemblyRefusal

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    seen = {}

    def fake_check(fw_deck, *, layout_template, layout_names):
        seen["fw_deck"] = fw_deck
        seen["layout_template"] = layout_template
        seen["layout_names"] = layout_names
        raise AssemblyRefusal("no layout named 'Blank Black' found in layout template")

    monkeypatch.setattr(app_mod, "check_layout_import_preconditions", fake_check)

    client = TestClient(app)
    res = client.post("/api/dsk", data={"path": str(deck), "dsk_template": str(template)})
    assert res.status_code == 400
    assert res.json()["detail"] == {
        "field": "dskTemplate",
        "message": "no layout named 'Blank Black' found in layout template",
    }
    assert seen["fw_deck"] == deck
    assert seen["layout_template"] == template
    assert tuple(seen["layout_names"]) == ("Blank Black",)


def test_dsk_apply_refuses_when_proposal_has_no_dsk_template(tmp_path, monkeypatch):
    """A proposal saved before this feature shipped has no `dskTemplate`; apply must
    refuse with the same structured 400, telling the operator to re-propose."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")

    def fake_propose(_job, path, _reference_deck, _dsk_template, _slide_range, content_only, _words):
        return {
            "phase": "review",
            "path": str(path),
            "pages": [],
            "skipped": [],
            "contentOnly": content_only,
        }

    monkeypatch.setattr(app_mod, "_run_dsk_propose", fake_propose)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    proposed = _wait(client, job_id)
    assert proposed["status"] == "done", proposed.get("error")
    assert "dskTemplate" not in proposed["result"]

    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 400
    assert applied.json()["detail"] == {
        "field": "dskTemplate",
        "message": "Choose the DSK template (.key) — the lower-thirds deck that supplies the DSK layouts.",
    }


def test_dsk_apply_refuses_when_stored_template_no_longer_exists(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    _wait(client, job_id)
    template.unlink()

    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 400
    detail = applied.json()["detail"]
    assert detail["field"] == "dskTemplate"
    assert str(template) in detail["message"]


def test_dsk_apply_passes_layout_template_to_export_and_assemble(tmp_path, monkeypatch):
    """The legacy (non-review) apply path's `export_slide_clips` and
    `assemble_dsk_deck` calls both receive the stored `dskTemplate` as
    `layout_template` (contract A)."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    seen = {}

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        seen["export_layout_template"] = kwargs.get("layout_template")
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

    def fake_assemble(fw, out_path, *, clips, **kwargs):
        seen["assemble_layout_template"] = kwargs.get("layout_template")
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={}, builds={},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["export_layout_template"] == template
    assert seen["assemble_layout_template"] == template


def test_dsk_v2_apply_passes_layout_template_to_compiled_clip_export(tmp_path, monkeypatch):
    """The v2/review apply path's compiled-composition `export_slide_clips` call
    (a different call site than the legacy path's) also receives `layout_template`."""
    import obed_edom.web.app as app_mod
    from obed_edom.dsk_assemble import AssembleResult
    from obed_edom.dsk_movie_export import ClipResult
    from obed_edom.map_remap import Rect

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    template = tmp_path / "Lower-Thirds.key"
    template.write_text("template")
    payload = {
        "slideWidth": 7680,
        "slideHeight": 1080,
        "slideCount": 1,
        "slides": [{"number": 1, "index": 0, "items": [{
            "kind": "movie", "kindIndex": 0, "index": 0, "fileName": "clip.mov",
            "x": 1920, "y": 0, "w": 3840, "h": 1080,
        }]}],
    }
    cls = SlideClass(1, "movie", 0, 1, (("movie", 0),), (), (), None, False)
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _path: payload)
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: [cls])
    monkeypatch.setattr(app_mod, "build_preview_thumbs", lambda *_a, **_k: {1: "slide-1.png"})
    monkeypatch.setattr(app_mod, "deck_digest", lambda _path: "bound")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _digest: tmp_path)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")
    monkeypatch.setattr(app_mod, "_dsk_archive_ids", lambda _path: {(1, "movie", 0): "movie-1"})
    monkeypatch.setattr(app_mod, "_dsk_build_records", lambda _path: {})
    seen = {}

    def fake_export(_deck, slides, out_dir, *, movie_plans, **kwargs):
        seen["layout_template"] = kwargs.get("layout_template")
        target = Path(out_dir) / "compiled.mov"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("clip")
        plan = movie_plans[0]
        return [ClipResult(
            slide=plan.source_slide, movie_id=plan.source_item, path=target,
            width=935, height=263, duration_s=1, wall_s=1, crop_width=935,
            crop_rect=Rect(1920, 0, 3840, 1080), occurrence_id=plan.occurrence_id,
        )]

    def fake_assemble(_deck, out_path, *, compiled_compositions, compiled_clips, **_kwargs):
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("deck")
        synthetic = ("movie", 1_000_000)
        occurrence = compiled_compositions[0].media[0].occurrence_id
        return AssembleResult(
            path=Path(out_path), slides_kept=(1,), ordinals={1: 1}, fits={},
            clips_inserted={1: {synthetic: compiled_clips[occurrence]}}, stroke={}, zorder={},
            builds={}, size_bytes=4, source_size_bytes=7, wall_s=1, warnings=(), movie_props={},
            clip_rects={1: {synthetic: Rect(43, 802, 935, 263)}},
            clip_occurrences={1: {synthetic: occurrence}},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)
    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    proposed = _wait(client, job_id)
    review = proposed["result"]["review"]
    envelope = {
        "schemaVersion": 2,
        "sourceFingerprint": review["source"]["fingerprint"],
        "defaults": review["defaults"],
        "decisions": [{"id": comp["id"], **comp["decision"]} for comp in review["compositions"]],
    }
    response = client.post(
        f"/api/dsk/{job_id}/apply",
        json={"review": envelope, "baseRevision": 0, "exportDir": str(tmp_path / "workspace")},
    )
    assert response.status_code == 200
    done = _wait(client, job_id)
    assert done["status"] == "done", done.get("error")
    assert seen["layout_template"] == template


# --- Stage progress + plain log (contract B) -----------------------------------


def test_dsk_propose_routes_library_callback_to_details_and_narration_to_logs(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "FW.key"
    deck.write_text("fixture")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    monkeypatch.setattr(app_mod, "classify_deck", lambda *_a, **_k: [_cls(1, "static")])
    monkeypatch.setattr(app_mod, "deck_digest", lambda _p: "digest")
    monkeypatch.setattr(app_mod, "wall_thumb_dir", lambda _d: tmp_path)

    def fake_thumbs(_path, _payload, *, log):
        log("IWA export: wrote 0001.jpg via ordinal 1")
        return {1: "0001.jpg"}

    monkeypatch.setattr(app_mod, "build_preview_thumbs", fake_thumbs)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert "IWA export: wrote 0001.jpg via ordinal 1" in job["details"]
    assert not any("IWA export" in line for line in job["logs"])
    assert any(line.startswith("Reading") for line in job["logs"])
    assert any("Made 1 slide preview" in line for line in job["logs"])
    assert job["progress"] is None


def test_dsk_apply_sets_progress_and_routes_assembler_log_to_details(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        kwargs["log"]("technical: exported via ffmpeg pass 1")
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

    def fake_assemble(fw, out_path, *, clips, **kwargs):
        kwargs["log"]("technical: wrote staging deck")
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={}, builds={},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
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
    assert "technical: exported via ffmpeg pass 1" in job["details"]
    assert "technical: wrote staging deck" in job["details"]
    assert not any("technical:" in line for line in job["logs"])
    assert any("Exporting 1 video clip" in line for line in job["logs"])
    assert any(line.startswith("Assembling") for line in job["logs"])
    assert any(line.startswith("Wrote") for line in job["logs"])
    # progress is cleared once the job finishes (Job B: "cleared on finish")
    assert job["progress"] is None


def test_dsk_apply_progress_stages_with_clip_export(tmp_path, monkeypatch):
    """3 stages when a clip export is needed: exporting clips, assembling, finishing
    outputs. Each fake blocks on an event so the test can observe the *live* progress
    the API reports mid-run, not just the finished job."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    export_entered = threading.Event()
    release_export = threading.Event()
    assemble_entered = threading.Event()
    release_assemble = threading.Event()
    finishing_entered = threading.Event()
    release_finishing = threading.Event()

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        export_entered.set()
        assert release_export.wait(2)
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

    def fake_assemble(fw, out_path, *, clips, **kwargs):
        assemble_entered.set()
        assert release_assemble.wait(2)
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={}, builds={},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
        )

    real_write_manifest = app_mod.write_manifest

    def fake_write_manifest(*args, **kwargs):
        finishing_entered.set()
        assert release_finishing.wait(2)
        return real_write_manifest(*args, **kwargs)

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)
    monkeypatch.setattr(app_mod, "write_manifest", fake_write_manifest)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200

    assert export_entered.wait(2)
    progress = _wait_for_progress_step(client, job_id, 1)
    assert progress["steps"] == 3
    assert progress["label"] == "Exporting video clips"
    release_export.set()

    assert assemble_entered.wait(2)
    progress = _wait_for_progress_step(client, job_id, 2)
    assert progress["steps"] == 3
    assert progress["label"] == "Assembling the DSK deck"
    release_assemble.set()

    assert finishing_entered.wait(2)
    progress = _wait_for_progress_step(client, job_id, 3)
    assert progress["steps"] == 3
    assert progress["label"] == "Finishing outputs"
    release_finishing.set()

    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["progress"] is None


def test_dsk_apply_progress_stages_without_clip_export(tmp_path, monkeypatch):
    """2 stages when no clip export is needed: assembling, finishing outputs."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    assemble_entered = threading.Event()
    release_assemble = threading.Event()
    finishing_entered = threading.Event()
    release_finishing = threading.Event()

    def fake_assemble(fw, out_path, *, clips, **kwargs):
        assemble_entered.set()
        assert release_assemble.wait(2)
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1,), ordinals={1: 1}, fits={},
            clips_inserted={}, stroke={}, zorder={}, builds={},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
        )

    real_write_manifest = app_mod.write_manifest

    def fake_write_manifest(*args, **kwargs):
        finishing_entered.set()
        assert release_finishing.wait(2)
        return real_write_manifest(*args, **kwargs)

    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)
    monkeypatch.setattr(app_mod, "write_manifest", fake_write_manifest)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck).json()["id"]
    _wait(client, job_id)
    applied = client.post(f"/api/dsk/{job_id}/apply")
    assert applied.status_code == 200

    assert assemble_entered.wait(2)
    progress = _wait_for_progress_step(client, job_id, 1)
    assert progress["steps"] == 2
    assert progress["label"] == "Assembling the DSK deck"
    release_assemble.set()

    assert finishing_entered.wait(2)
    progress = _wait_for_progress_step(client, job_id, 2)
    assert progress["steps"] == 2
    assert progress["label"] == "Finishing outputs"
    release_finishing.set()

    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert job["progress"] is None


# --- DSK template override at apply time (Codex r1 finding 1) -----------------


def test_dsk_apply_with_new_template_overrides_stored_one(tmp_path, monkeypatch):
    """A `dskTemplate` given to apply overrides the stored proposal value -- even
    when the stored one no longer exists -- validates and persists it, and reaches
    export/assemble with the new path."""
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    old_template = tmp_path / "old.key"
    old_template.write_text("old template")
    new_template = tmp_path / "new.key"
    new_template.write_text("new template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(2))
    classes = {1: _cls(1, "static"), 2: _cls(2, "movie", movie_count=1)}
    _patch_common(monkeypatch, app_mod, classes=classes)
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)
    monkeypatch.setattr(app_mod, "default_output_root", lambda: tmp_path / "output")

    seen = {}

    def fake_export_clips(fw, slides, out_dir, **kwargs):
        seen["export_layout_template"] = kwargs.get("layout_template")
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

    def fake_assemble(fw, out_path, *, clips, **kwargs):
        seen["assemble_layout_template"] = kwargs.get("layout_template")
        from obed_edom.dsk_assemble import AssembleResult

        return AssembleResult(
            path=out_path, slides_kept=(1, 2), ordinals={1: 1, 2: 2}, fits={},
            clips_inserted={2: dict(clips[2])}, stroke={}, zorder={}, builds={},
            size_bytes=10, source_size_bytes=20, wall_s=1.0, warnings=(), movie_props={},
        )

    monkeypatch.setattr(app_mod, "export_slide_clips", fake_export_clips)
    monkeypatch.setattr(app_mod, "assemble_dsk_deck", fake_assemble)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(old_template)).json()["id"]
    _wait(client, job_id)
    old_template.unlink()

    applied = client.post(f"/api/dsk/{job_id}/apply", json={"dskTemplate": str(new_template)})
    assert applied.status_code == 200
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    assert seen["export_layout_template"] == new_template.resolve()
    assert seen["assemble_layout_template"] == new_template.resolve()

    # The stored proposal now carries the new template.
    refetched = client.get(f"/api/jobs/{job_id}").json()
    assert refetched["result"].get("dskTemplate") == str(new_template.resolve())


def test_dsk_apply_with_bad_new_template_refuses_and_keeps_stored_value(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    deck = tmp_path / "GW.key"
    deck.write_text("placeholder")
    old_template = tmp_path / "old.key"
    old_template.write_text("old template")
    bad_template = tmp_path / "does-not-exist.key"
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})
    monkeypatch.setattr(app_mod, "keynote_running", lambda: False)

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(old_template)).json()["id"]
    _wait(client, job_id)

    applied = client.post(f"/api/dsk/{job_id}/apply", json={"dskTemplate": str(bad_template)})
    assert applied.status_code == 400
    detail = applied.json()["detail"]
    assert detail["field"] == "dskTemplate"
    assert str(bad_template) in detail["message"]

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["result"]["dskTemplate"] == str(old_template)
    assert job["status"] == "done"


# --- Relative DSK template resolved to an absolute path (Codex r1 finding 5) ---


def test_dsk_propose_resolves_relative_template_to_absolute(tmp_path, monkeypatch):
    import obed_edom.web.app as app_mod

    monkeypatch.chdir(tmp_path)
    deck = Path("FW.key")
    deck.write_text("fixture")
    template = Path("Lower-Thirds.key")
    template.write_text("template")
    monkeypatch.setattr(app_mod, "offline_wall_payload", lambda _p: _fw_payload(1))
    _patch_common(monkeypatch, app_mod, classes={1: _cls(1, "static")})

    client = TestClient(app)
    job_id = _propose_dsk(client, deck, dsk_template=str(template)).json()["id"]
    job = _wait(client, job_id)
    assert job["status"] == "done", job.get("error")
    stored = job["result"]["dskTemplate"]
    assert Path(stored).is_absolute()
    assert Path(stored) == (tmp_path / "Lower-Thirds.key").resolve()
