"""Tests for obed_edom.dsk_stage_export: pure helpers, the generated AppleScript, alpha
validation, manifest shape, and a faked live export. No test may launch Keynote; the
autouse fixture below raises if subprocess.run/Popen is reached without an explicit
monkeypatch of the module's own seams.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import obed_edom.dsk_stage_export as dse


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


# --- stage_name --------------------------------------------------------------


def test_stage_name_padding():
    assert dse.stage_name("Deck", 3, 1) == "Deck.003.01.png"


def test_stage_name_slide_over_99():
    assert dse.stage_name("Deck", 142, 5) == "Deck.142.05.png"


# --- reconstruct ---------------------------------------------------------------


def _numbered(tmp_path: Path, n: int) -> Path:
    p = tmp_path / f"Scratch.{n:03d}.png"
    p.write_bytes(b"x")
    return p


def test_reconstruct_multi_slide_uneven_counts(tmp_path):
    files = [_numbered(tmp_path, i) for i in (1, 2, 3, 4, 5)]
    expected = {5: 2, 9: 3}
    result = dse.reconstruct(files, [9, 5], expected)
    assert [(s, i) for s, i, _p in result] == [(5, 1), (5, 2), (9, 1), (9, 2), (9, 3)]
    assert [p.name for _s, _i, p in result] == [f.name for f in files]


def test_reconstruct_refuses_on_duplicate_indices(tmp_path):
    files = [_numbered(tmp_path, i) for i in (1, 2, 3)]
    files.append(tmp_path / "Scratch.0001.png")
    files[-1].write_bytes(b"x")
    with pytest.raises(dse.StageCountMismatch, match="duplicates or gaps"):
        dse.reconstruct(files, [5], {5: 4})


def test_reconstruct_refuses_on_gap_in_indices(tmp_path):
    files = [_numbered(tmp_path, i) for i in (1, 2, 4, 5)]
    with pytest.raises(dse.StageCountMismatch, match="duplicates or gaps"):
        dse.reconstruct(files, [5], {5: 4})


def test_reconstruct_refuses_on_count_mismatch_plus_one(tmp_path):
    files = [_numbered(tmp_path, i) for i in range(1, 6)]
    with pytest.raises(dse.StageCountMismatch):
        dse.reconstruct(files, [5, 9], {5: 2, 9: 4})


def test_reconstruct_refuses_on_count_mismatch_minus_one(tmp_path):
    files = [_numbered(tmp_path, i) for i in range(1, 4)]
    with pytest.raises(dse.StageCountMismatch):
        dse.reconstruct(files, [5, 9], {5: 2, 9: 2})


# --- stage_counts ----------------------------------------------------------------


def _objects_for_slides(slides_chunks: dict[int, list[dict]]) -> dict:
    """Builds a minimal `_load_deck`-shaped `objects` dict: a `KN.ShowArchive` whose
    `slideTree` orders slides 1..max(slides_chunks) ascending, each slide's raw
    `buildChunks` resolving to `KN.BuildChunkArchive` objects per the given specs
    (`{"referent": bool, "automatic": bool, "effect": str, "build_id": str}`,
    all optional except `referent` which defaults True)."""
    max_n = max(slides_chunks)
    objects: dict[str, dict] = {}
    node_refs = []
    for n in range(1, max_n + 1):
        chunk_refs = []
        for i, spec in enumerate(slides_chunks.get(n, [])):
            cid = f"s{n}c{i}"
            chunk_obj: dict = {
                "_pbtype": "KN.BuildChunkArchive",
                "referent": spec.get("referent", True),
            }
            if "automatic" in spec:
                chunk_obj["automatic"] = spec["automatic"]
            bid = spec.get("build_id")
            if bid is not None:
                chunk_obj["build"] = {"identifier": bid}
                objects.setdefault(bid, {"attributes": {}})
                if spec.get("effect"):
                    objects[bid]["attributes"]["databaseEffect"] = spec["effect"]
            chunk_refs.append({"identifier": cid})
            objects[cid] = chunk_obj
        sid, nid = f"slide{n}", f"node{n}"
        objects[sid] = {"_pbtype": "KN.SlideArchive", "buildChunks": chunk_refs}
        objects[nid] = {"slide": {"identifier": sid}, "isSkipped": False}
        node_refs.append({"identifier": nid})
    objects["show"] = {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": node_refs}}
    return objects


def test_stage_counts_agree(monkeypatch):
    objects = _objects_for_slides({1: [{"referent": True}], 2: []})
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    out = dse.stage_counts(Path("d.key"), [1, 2])
    assert out == {1: 2, 2: 1}


def test_stage_counts_chained_build_shares_a_click(monkeypatch):
    objects = _objects_for_slides(
        {29: [{"referent": True, "build_id": "b1"}, {"referent": False, "build_id": "b1"}]}
    )
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    out = dse.stage_counts(Path("d.key"), [29])
    assert out == {29: 2}


def test_stage_counts_missing_referent_raises_ambiguous_naming_slide(monkeypatch):
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"_pbtype": "KN.SlideArchive", "buildChunks": [{"identifier": "cX"}]},
    }
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    with pytest.raises(dse.StageCountAmbiguous, match=r"slides \[1\]"):
        dse.stage_counts(Path("d.key"), [1])


def test_stage_counts_names_movie_start_build_in_refusal(monkeypatch):
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {
            "_pbtype": "KN.SlideArchive",
            "buildChunks": [{"identifier": "cX"}, {"identifier": "c2"}],
        },
        "c2": {"_pbtype": "KN.BuildChunkArchive", "referent": True, "build": {"identifier": "b2"}},
        "b2": {"attributes": {"databaseEffect": "apple:movie-start"}},
    }
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    with pytest.raises(dse.StageCountAmbiguous, match="movie-start"):
        dse.stage_counts(Path("d.key"), [1])


def test_stage_counts_raises_on_automatic_referent_chunk(monkeypatch):
    objects = _objects_for_slides({9: [{"referent": True, "automatic": True}]})
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    with pytest.raises(dse.StageCountAmbiguous, match=r"\[9\].*automatic"):
        dse.stage_counts(Path("d.key"), [9])


def test_stage_counts_allow_automatic_opts_in(monkeypatch):
    objects = _objects_for_slides({9: [{"referent": True, "automatic": True}]})
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    out = dse.stage_counts(Path("d.key"), [9], allow_automatic=True)
    assert out == {9: 2}


def test_stage_counts_nonautomatic_chunk_passes(monkeypatch):
    objects = _objects_for_slides({9: [{"referent": True, "automatic": False}]})
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    out = dse.stage_counts(Path("d.key"), [9])
    assert out == {9: 2}


def test_stage_counts_automatic_nonreferent_chunk_passes(monkeypatch):
    objects = _objects_for_slides({9: [{"referent": False, "automatic": True}]})
    monkeypatch.setattr(dse, "_load_deck", lambda d: (objects, {}, {}))
    out = dse.stage_counts(Path("d.key"), [9])
    assert out == {9: 1}


REAL_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key")


def test_stage_counts_real_deck_matches_measured_click_counts():
    if not REAL_DECK.is_file():
        pytest.skip("real DSK deck not present (local operator file)")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")

    slides = [14, 17, 26, 29, 30]
    out = dse.stage_counts(REAL_DECK, slides)
    assert out == {14: 2, 17: 2, 26: 2, 29: 2, 30: 2}


# --- validate_alpha --------------------------------------------------------------


def _write_png(tmp_path: Path, mode: str, size: tuple[int, int], make_arr) -> Path:
    arr = make_arr(size)
    img = Image.fromarray(arr, mode=mode)
    path = tmp_path / "stage.png"
    img.save(path)
    return path


def test_validate_alpha_clean_bg_is_ok(tmp_path):
    def make(size):
        w, h = size
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = [255, 0, 0, 255]
        return arr

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = dse.validate_alpha(
        path, expected_size=(200, 100)
    )
    assert alpha_ok is True
    assert bg_alpha_max == 0
    assert content_alpha_frac > 0
    assert transparent_frac >= 0.05


def test_validate_alpha_full_bleed_opaque_not_ok_no_raise(tmp_path):
    def make(size):
        w, h = size
        return np.full((h, w, 4), 255, dtype=np.uint8)

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, _frac, transparent_frac = dse.validate_alpha(path, expected_size=(200, 100))
    assert alpha_ok is False
    assert bg_alpha_max == 255
    assert transparent_frac == 0.0


def test_validate_alpha_content_touching_corner_is_ok(tmp_path):
    def make(size):
        w, h = size
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[0 : h // 2, 0 : w // 2] = [255, 0, 0, 255]
        arr[0, :] = [0, 0, 0, 0]
        arr[-1, :] = [0, 0, 0, 0]
        arr[:, 0] = [0, 0, 0, 0]
        arr[:, -1] = [0, 0, 0, 0]
        return arr

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = dse.validate_alpha(
        path, expected_size=(200, 100)
    )
    assert alpha_ok is True
    assert bg_alpha_max == 0
    assert content_alpha_frac > 0
    assert transparent_frac >= 0.05


def test_validate_alpha_opaque_bottom_band_ok_via_clean_top_edge(tmp_path):
    def make(size):
        w, h = size
        arr = np.zeros((h, w, 4), dtype=np.uint8)
        arr[h - 10 :, :] = [0, 0, 0, 255]
        return arr

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = dse.validate_alpha(
        path, expected_size=(200, 100)
    )
    assert alpha_ok is True
    assert bg_alpha_max == 0
    assert content_alpha_frac > 0
    assert transparent_frac >= 0.05


def test_validate_alpha_all_edges_touched_with_transparent_centre_is_ok(tmp_path):
    def make(size):
        w, h = size
        arr = np.full((h, w, 4), 255, dtype=np.uint8)
        arr[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = [0, 0, 0, 0]
        return arr

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = dse.validate_alpha(
        path, expected_size=(200, 100)
    )
    assert bg_alpha_max == 255
    assert transparent_frac >= 0.05
    assert alpha_ok is True


def test_validate_alpha_uniform_alpha_one_not_ok(tmp_path):
    def make(size):
        w, h = size
        return np.full((h, w, 4), [0, 0, 0, 1], dtype=np.uint8)

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    alpha_ok, bg_alpha_max, content_alpha_frac, transparent_frac = dse.validate_alpha(
        path, expected_size=(200, 100)
    )
    assert alpha_ok is False
    assert content_alpha_frac == 0.0
    assert transparent_frac == 1.0


def test_validate_alpha_rgb_raises(tmp_path):
    def make(size):
        w, h = size
        return np.zeros((h, w, 3), dtype=np.uint8)

    path = _write_png(tmp_path, "RGB", (200, 100), make)
    with pytest.raises(ValueError, match="RGBA"):
        dse.validate_alpha(path, expected_size=(200, 100))


def test_validate_alpha_wrong_size_raises(tmp_path):
    def make(size):
        w, h = size
        return np.zeros((h, w, 4), dtype=np.uint8)

    path = _write_png(tmp_path, "RGBA", (200, 100), make)
    with pytest.raises(ValueError, match="size"):
        dse.validate_alpha(path, expected_size=(199, 100))


# --- write_manifest --------------------------------------------------------------


def test_manifest_shape_and_clip_linkage(tmp_path):
    assets = [
        dse.StageAsset(
            slide=5, stage_index=1, path=tmp_path / "Deck.005.01.png",
            width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
            content_alpha_frac=0.1, transparent_frac=0.5, source_name="Scratch.001.png",
        ),
        dse.StageAsset(
            slide=5, stage_index=2, path=tmp_path / "Deck.005.02.png",
            width=1920, height=1080, alpha_ok=False, bg_alpha_max=200,
            content_alpha_frac=0.9, transparent_frac=0.02, source_name="Scratch.002.png",
        ),
    ]
    clip_path = tmp_path / "Deck.005.mov"
    path = dse.write_manifest(
        tmp_path, Path("Deck.key"), assets,
        categories={5: "built"}, clips={5: clip_path},
    )
    manifest = json.loads(path.read_text())
    assert manifest["deck"] == "Deck.key"
    assert manifest["geometry"] == {"width": 1920, "height": 1080}
    assert "generated" not in manifest
    slide = manifest["slides"]["5"]
    assert slide["category"] == "built"
    assert slide["clip"] == "Deck.005.mov"
    assert [s["index"] for s in slide["stages"]] == [1, 2]
    assert slide["stages"][0]["file"] == "Deck.005.01.png"
    assert slide["stages"][1]["alpha_ok"] is False
    assert slide["stages"][0]["content_alpha_frac"] == 0.1
    assert slide["stages"][0]["alpha_route"] == "keynote-stage-png"
    assert slide["stages"][1]["content_alpha_frac"] == 0.9


def test_manifest_omits_clip_when_none(tmp_path):
    assets = [
        dse.StageAsset(
            slide=2, stage_index=1, path=tmp_path / "Deck.002.01.png",
            width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
            content_alpha_frac=0.1, transparent_frac=0.5, source_name="Scratch.001.png",
        ),
    ]
    path = dse.write_manifest(tmp_path, Path("Deck.key"), assets, categories={})
    manifest = json.loads(path.read_text())
    assert "clip" not in manifest["slides"]["2"]


def test_manifest_generated_omitted_by_default_and_injectable(tmp_path):
    assets = [
        dse.StageAsset(
            slide=2, stage_index=1, path=tmp_path / "Deck.002.01.png",
            width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
            content_alpha_frac=0.1, transparent_frac=0.5, source_name="Scratch.001.png",
        ),
    ]
    path = dse.write_manifest(tmp_path, Path("Deck.key"), assets, categories={})
    assert "generated" not in json.loads(path.read_text())

    path = dse.write_manifest(
        tmp_path, Path("Deck.key"), assets, categories={}, generated="2026-09-10T00:00:00+00:00"
    )
    assert json.loads(path.read_text())["generated"] == "2026-09-10T00:00:00+00:00"


def test_manifest_is_deterministic_sort_keys(tmp_path):
    assets = [
        dse.StageAsset(
            slide=2, stage_index=1, path=tmp_path / "Deck.002.01.png",
            width=1920, height=1080, alpha_ok=True, bg_alpha_max=0,
            content_alpha_frac=0.1, transparent_frac=0.5, source_name="Scratch.001.png",
        ),
    ]
    path1 = dse.write_manifest(tmp_path, Path("Deck.key"), assets, categories={2: "built"})
    text1 = path1.read_text()
    path2 = dse.write_manifest(tmp_path, Path("Deck.key"), assets, categories={2: "built"})
    text2 = path2.read_text()
    assert text1 == text2
    assert list(json.loads(text1).keys()) == sorted(json.loads(text1).keys())


# --- build_stage_script snapshot --------------------------------------------------


def _script():
    return dse.build_stage_script(
        Path("/work/Scratch.key"),
        [3, 7],
        10,
        Path("/work/stages"),
        transparent_layout_names=dse.DEFAULT_TRANSPARENT_LAYOUT_NAMES,
    )


def test_script_uses_application_id_not_app_display_name():
    script = _script()
    assert "application id" in script
    assert "Keynote Creator Studio" not in script
    assert 'tell application "Keynote"' not in script


def test_script_export_clause_shape():
    script = _script()
    assert "as slide images" in script
    assert "all stages:true" in script
    assert "image format:PNG" in script
    assert "skipped slides:false" in script


def test_script_destination_is_one_folder_per_slide():
    script = _script()
    assert 'POSIX file "/work/stages/stage_003"' in script
    assert 'POSIX file "/work/stages/stage_007"' in script
    assert "/work/stages/stage_003.png" not in script


def test_script_has_n_export_clauses():
    script = _script()
    assert script.count("as slide images") == 2


def test_script_toggles_skipped_per_slide_ordinal():
    script = _script()
    assert "(j is not 1)" in script
    assert "(j is not 2)" in script


def test_script_wipes_each_stage_folder_before_its_export():
    script = _script()
    lines = script.splitlines()
    for folder in ("/work/stages/stage_003", "/work/stages/stage_007"):
        wipe_idx = next(i for i, l in enumerate(lines) if "rm -rf" in l and folder in l)
        export_idx = next(i for i, l in enumerate(lines) if f'POSIX file "{folder}"' in l)
        assert wipe_idx < export_idx


def test_script_closes_without_saving():
    script = _script()
    assert "close theDoc saving no" in script


def test_script_deletes_non_targets_descending():
    script = _script()
    lines = script.splitlines()
    delete_idx = next(i for i, l in enumerate(lines) if "repeat with i from 10 to 1 by -1" in l)
    assert "delete slide i of theDoc" in lines[delete_idx + 1]


def test_script_has_transparent_layout_block_with_names():
    script = _script()
    assert '"Blank"' in script
    assert '"BLANK"' in script
    assert '"blank"' in script


def test_script_default_args_touch_no_layouts():
    script = dse.build_stage_script(
        Path("/work/Scratch.key"), [3, 7], 10, Path("/work/stages")
    )
    assert "base layout" not in script
    assert "blackLayoutName" not in script
    assert "approvedBlackNames" not in script
    assert "slide layouts" not in script
    assert "set skipped of s to false" not in script


def test_script_captures_and_restores_original_skipped(monkeypatch):
    script = dse.build_stage_script(
        Path("/work/Scratch.key"), [3, 7], 10, Path("/work/stages"), unskip_all=True
    )
    assert "set origSkipped to {}" in script
    assert "set end of origSkipped to (skipped of s)" in script
    restore_line = "set skipped of (item j of slideRefs) to (item j of origSkipped)"
    restores = script.count(restore_line)
    assert restores == 2

    error_restore_idx = script.index(restore_line)
    on_error_idx = script.rindex("on error errMsg number errNum", 0, error_restore_idx)
    reraise_idx = script.index("error errMsg number errNum", error_restore_idx)
    end_try_idx = script.index("end try", reraise_idx)
    success_restore_idx = script.index(restore_line, end_try_idx)
    assert on_error_idx < error_restore_idx < reraise_idx < end_try_idx < success_restore_idx


def test_script_has_error_clause():
    script = _script()
    assert "on error errMsg number errNum" in script
    assert 'log ("ERR"' in script


# --- export_stage_pngs end-to-end with a fake LiveBatch --------------------------


def _stage_arr():
    arr = np.zeros((1080, 1920, 4), dtype=np.uint8)
    arr[400:700, 700:1200] = [255, 0, 0, 255]
    return arr


def _make_fake_batch(files_by_slide):
    """A `LiveBatch` stand-in whose `run` writes `files_by_slide[n]` numbered PNGs
    into `stage_<n:03d>/` under `work/stages`, mirroring what the fixed AppleScript
    produces per requested slide."""

    class _FakeBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = deck
            self.out_dir = out_dir
            self.work = None
            self.scratch = None

        def __enter__(self):
            self.work = self.out_dir / ".work"
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch = self.work / self.deck.name
            self.scratch.touch()
            return self

        def run(self, script_path, on_progress=None):
            arr = _stage_arr()
            for slide, count in files_by_slide.items():
                folder = self.work / "stages" / f"stage_{slide:03d}"
                folder.mkdir(parents=True, exist_ok=True)
                for i in range(1, count + 1):
                    Image.fromarray(arr, mode="RGBA").save(folder / f"{folder.name}.{i:03d}.png")
            return subprocess.CompletedProcess(["osascript"], 0, "", "")

        def __exit__(self, *exc):
            return False

    return _FakeBatch


def _payload(width=1920, height=1080, skipped_numbers=()):
    return {
        "slideWidth": width,
        "slideHeight": height,
        "slides": [
            {"number": n, "skipped": n in skipped_numbers} for n in (1, 2)
        ],
    }


def test_export_stage_pngs_end_to_end(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()
    out_dir = tmp_path / "out"

    monkeypatch.setattr(dse, "LiveBatch", _make_fake_batch({2: 3}))
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload())
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    assets = dse.export_stage_pngs(
        deck, [2], out_dir,
        expected_stage_counts={2: 3},
        categories={2: "built"},
    )

    assert len(assets) == 3
    assert {a.slide for a in assets} == {2}
    assert [a.stage_index for a in assets] == [1, 2, 3]
    assert all(a.path.exists() for a in assets)
    assert all(a.path.name == dse.stage_name("Deck", 2, a.stage_index) for a in assets)
    assert all(a.alpha_ok for a in assets)

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["slides"]["2"]["category"] == "built"
    assert len(manifest["slides"]["2"]["stages"]) == 3


def test_export_stage_pngs_multi_slide_each_own_folder(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()
    out_dir = tmp_path / "out"

    monkeypatch.setattr(dse, "LiveBatch", _make_fake_batch({1: 2, 2: 3}))
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload())
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    assets = dse.export_stage_pngs(
        deck, [1, 2], out_dir, expected_stage_counts={1: 2, 2: 3},
    )
    assert {a.slide for a in assets} == {1, 2}
    assert [a.stage_index for a in assets if a.slide == 1] == [1, 2]
    assert [a.stage_index for a in assets if a.slide == 2] == [1, 2, 3]


def test_export_stage_pngs_refuses_wrong_geometry(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()

    monkeypatch.setattr(dse, "LiveBatch", _make_fake_batch({2: 3}))
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload(width=200, height=100))
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    with pytest.raises(ValueError, match="geometry"):
        dse.export_stage_pngs(deck, [2], tmp_path / "out", expected_stage_counts={2: 3})


def test_export_stage_pngs_refuses_skipped_slide_by_default(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()

    monkeypatch.setattr(dse, "LiveBatch", _make_fake_batch({2: 3}))
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload(skipped_numbers=(2,)))
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    with pytest.raises(ValueError, match="skipped"):
        dse.export_stage_pngs(
            deck, [2], tmp_path / "out",
            expected_stage_counts={2: 3},
        )


def test_export_stage_pngs_allows_skipped_slide_when_opted_in(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()

    monkeypatch.setattr(dse, "LiveBatch", _make_fake_batch({2: 3}))
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload(skipped_numbers=(2,)))
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    assets = dse.export_stage_pngs(
        deck, [2], tmp_path / "out",
        expected_stage_counts={2: 3},
        include_skipped=True,
    )
    assert len(assets) == 3


def test_export_stage_pngs_export_folder_fresh_per_attempt(tmp_path, monkeypatch):
    """A LiveBatch retry re-runs the same (fixed) script, which wipes each slide's
    stage folder before writing again -- a shorter second attempt must not leave a
    stale tail from the first, and the final file count must be exactly enforced."""
    deck = tmp_path / "Deck.key"
    deck.touch()

    class _RetryBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = deck
            self.out_dir = out_dir
            self.work = None
            self.scratch = None

        def __enter__(self):
            self.work = self.out_dir / ".work"
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch = self.work / self.deck.name
            self.scratch.touch()
            return self

        def run(self, script_path, on_progress=None):
            arr = _stage_arr()
            folder = self.work / "stages" / "stage_002"

            folder.mkdir(parents=True, exist_ok=True)
            for i in range(1, 4):
                Image.fromarray(arr, mode="RGBA").save(folder / f"{folder.name}.{i:03d}.png")

            shutil.rmtree(folder)
            folder.mkdir(parents=True)
            for i in range(1, 3):
                Image.fromarray(arr, mode="RGBA").save(folder / f"{folder.name}.{i:03d}.png")

            return subprocess.CompletedProcess(["osascript"], 0, "", "")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(dse, "LiveBatch", _RetryBatch)
    monkeypatch.setattr(dse, "offline_wall_payload", lambda d: _payload())
    monkeypatch.setattr(dse, "deck_builds", lambda d: {1: {}, 2: {}})

    with pytest.raises(dse.StageCountMismatch):
        dse.export_stage_pngs(deck, [2], tmp_path / "out1", expected_stage_counts={2: 3})

    assets = dse.export_stage_pngs(deck, [2], tmp_path / "out2", expected_stage_counts={2: 2})
    assert len(assets) == 2


def test_export_stage_pngs_guards_out_dir_before_mkdir(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.mkdir()
    out_dir = deck / "out"

    with pytest.raises(ValueError, match="source .key package"):
        dse.export_stage_pngs(deck, [1], out_dir, expected_stage_counts={1: 1})
    assert not out_dir.exists()


def test_export_stage_pngs_refuses_exclude_items(tmp_path, monkeypatch):
    deck = tmp_path / "Deck.key"
    deck.touch()
    with pytest.raises(NotImplementedError):
        dse.export_stage_pngs(
            deck, [1], tmp_path / "out",
            expected_stage_counts={1: 1},
            exclude_items=["some-id"],
        )
