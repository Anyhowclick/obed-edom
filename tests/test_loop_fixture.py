"""Unit tests for `scripts/loop_fixture.py`, the `p2-loop` gate-fixture builder.

The builder splices Keynote's Repeat -> Loop key into a copy of the P2 export. Keynote's
JSON does not round-trip through `json.dumps` (it escapes `/` as `\\/`), so the splice is
textual; these tests pin that every other byte is unchanged, that the read-only source is
never touched, and that the spliced copy derives the two looping plan shas the plan pins
(F5). Synthetic sources are built in `tmp_path` from the committed P2 fixture rewritten in
Keynote's compact form, so no real export is needed; one REAL-gated test runs the real
export's slide JSON through the same build.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from obed_edom.fixture_paths import fixture, main_checkout

REPO = Path(__file__).resolve().parent.parent
COMMITTED = REPO / "tests" / "fixtures" / "live_continuity" / "assets"


def _load_builder():
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("loop_fixture", REPO / "scripts" / "loop_fixture.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


loop_fixture = _load_builder()


def _keynote_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("/", "\\/")


def _keynote_jsonp(name: str, data: Any) -> str:
    return f"local_slide( {_keynote_json({'name': name, 'json': data})} )"


def _write_tree(tree: Path, slides: dict[str, Any], header: dict[str, Any]) -> None:
    (tree / "assets").mkdir(parents=True)
    (tree / "assets" / "header.json").write_text(json.dumps(header))
    (tree / "index.html").write_text("<html></html>")
    for uuid, data in slides.items():
        folder = tree / "assets" / uuid
        folder.mkdir()
        (folder / f"{uuid}.json").write_bytes(_keynote_json(data).encode())
        (folder / f"{uuid}.jsonp").write_bytes(_keynote_jsonp(uuid, data).encode())
        (folder / "assets").mkdir()
        (folder / "assets" / "movie.mov").write_bytes(b"\x00media bytes\x00")


def _committed_source(root: Path) -> Path:
    header = json.loads((COMMITTED / "header.json").read_text())
    slides = {
        uuid: json.loads((COMMITTED / uuid / f"{uuid}.json").read_text()) for uuid in header["slideList"]
    }
    for tree in loop_fixture.TREES:
        _write_tree(root / tree, slides, header)
    (root / "asset-replace.json").write_text('{"files": []}\n')
    return root


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


MOVIE_TEXT = (
    '{"events":[{"effects":[{"objectID":"AAAA0001-X","baseLayer":{"layers":[]},'
    '"movie":{"startTime":0,"asset":"a\\/b.mov","endTime":4.5}},'
    '{"objectID":"BBBB0002-Y","baseLayer":{},"movie":{"asset":"c.mov","volume":1}}]}],'
    '"assets":{"k":{"url":"assets\\/x.pdf"}}}'
)


class TestSpliceText:
    def test_inserts_before_the_closing_brace_of_only_the_targeted_movie(self) -> None:
        after, touched = loop_fixture.splice_text(MOVIE_TEXT, ("AAAA0001",))
        assert touched == ["AAAA0001"]
        assert after == MOVIE_TEXT.replace('"endTime":4.5}', '"endTime":4.5,"loopMode":"looping"}')
        assert '"asset":"a\\/b.mov"' in after and '"url":"assets\\/x.pdf"' in after
        loop_fixture.check_splice(MOVIE_TEXT, after, ("AAAA0001",))

    def test_untargeted_text_is_returned_unchanged(self) -> None:
        after, touched = loop_fixture.splice_text(MOVIE_TEXT, ("CCCC0003",))
        assert after == MOVIE_TEXT and touched == []

    def test_jsonp_wrapper_is_spliced_inside_the_payload_only(self) -> None:
        text = f"local_slide( {{\"name\":\"S\",\"json\":{MOVIE_TEXT}}} )"
        after, touched = loop_fixture.splice_text(text, ("AAAA0001", "BBBB0002"), jsonp=True)
        assert touched == ["AAAA0001", "BBBB0002"]
        assert after.startswith("local_slide( {") and after.endswith("} )")
        assert after.count(loop_fixture.LOOP_KEY) == 2
        loop_fixture.check_splice(text, after, ("AAAA0001", "BBBB0002"), jsonp=True)

    def test_a_movie_object_with_nested_braces_is_refused_not_guessed(self) -> None:
        text = MOVIE_TEXT.replace('"volume":1}', '"volume":1,"extra":{"n":1}}')
        with pytest.raises(loop_fixture.FixtureError, match="flat movie object"):
            loop_fixture.splice_text(text, ("BBBB0002",))

    def test_a_movie_that_already_loops_is_refused(self) -> None:
        text = MOVIE_TEXT.replace('"endTime":4.5}', '"endTime":4.5,"loopMode":"looping"}')
        with pytest.raises(loop_fixture.FixtureError, match="already carries loopMode"):
            loop_fixture.splice_text(text, ("AAAA0001",))

    def test_check_splice_rejects_any_other_change(self) -> None:
        after, _ = loop_fixture.splice_text(MOVIE_TEXT, ("AAAA0001",))
        with pytest.raises(loop_fixture.FixtureError):
            loop_fixture.check_splice(MOVIE_TEXT, after.replace('"volume":1', '"volume":0'), ("AAAA0001",))
        with pytest.raises(loop_fixture.FixtureError):
            loop_fixture.check_splice(MOVIE_TEXT, after.replace("a\\/b.mov", "a/b.mov"), ("AAAA0001",))
        wrong_value = MOVIE_TEXT.replace('"endTime":4.5}', '"endTime":4.5,"loopMode":"loopBackAndForth"}')
        with pytest.raises(loop_fixture.FixtureError):
            loop_fixture.check_splice(MOVIE_TEXT, wrong_value, ("AAAA0001",))


class TestBuild:
    def test_committed_fixture_builds_and_derives_the_pinned_looping_shas(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        before = _tree_bytes(source)
        dest = tmp_path / "p2-loop"
        record = loop_fixture.build(source, dest)
        assert _tree_bytes(source) == before
        assert record["planSha256"] == loop_fixture.EXPECTED_PLAN_SHA256
        assert record["sourceUnchanged"] is True
        assert record["sourceSha256"] == {k: hashlib.sha256(v).hexdigest() for k, v in before.items()}
        assert record["objectIds"] == list(loop_fixture.LOOP_OBJECT_IDS)
        assert len(record["files"]) == 16, "4 slides x (.json, .jsonp) x 2 trees"
        assert json.loads((dest / "loop-splice.json").read_text()) == record
        assert not (dest.parent / "p2-loop.partial").exists()

        after = _tree_bytes(dest)
        spliced = {entry["path"] for entry in record["files"]}
        for rel, data in before.items():
            if rel in spliced:
                assert data != after[rel]
                assert len(after[rel]) - len(data) == len(loop_fixture.LOOP_KEY) * len(
                    next(e["objectIds"] for e in record["files"] if e["path"] == rel)
                )
            else:
                assert after[rel] == data, rel
        for entry in record["files"]:
            assert hashlib.sha256(after[entry["path"]]).hexdigest() == entry["postSha256"]
            assert hashlib.sha256(before[entry["path"]]).hexdigest() == entry["preSha256"]

    def test_wa0125_is_never_spliced(self, tmp_path: Path) -> None:
        dest = tmp_path / "p2-loop"
        loop_fixture.build(_committed_source(tmp_path / "src"), dest)
        for tree in loop_fixture.TREES:
            for path in (dest / tree / "assets").rglob("*.json"):
                if path.name == "header.json":
                    continue
                for node in loop_fixture._movie_nodes(json.loads(path.read_bytes())):
                    loops = node["movie"].get("loopMode") == "looping"
                    assert loops == node["objectID"].startswith(loop_fixture.LOOP_OBJECT_IDS), node["objectID"]

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        dest = tmp_path / "p2-loop"
        dest.mkdir()
        (dest / "keep").write_text("x")
        with pytest.raises(loop_fixture.FixtureError, match="--force"):
            loop_fixture.build(source, dest)
        assert (dest / "keep").read_text() == "x"
        loop_fixture.build(source, dest, force=True)
        assert not (dest / "keep").exists()

    @pytest.mark.parametrize("where", ["same", "inside"])
    def test_refuses_a_destination_overlapping_the_source(self, tmp_path: Path, where: str) -> None:
        source = _committed_source(tmp_path / "src")
        dest = source if where == "same" else source / "p2-loop"
        with pytest.raises(loop_fixture.FixtureError, match="overlaps"):
            loop_fixture.build(source, dest, force=True)

    def test_a_missing_target_movie_fails_and_leaves_nothing(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        with pytest.raises(loop_fixture.FixtureError, match="missing"):
            loop_fixture.build(source, tmp_path / "p2-loop", object_ids=(*loop_fixture.LOOP_OBJECT_IDS, "DEADBEEF"))
        assert not (tmp_path / "p2-loop").exists() and not (tmp_path / "p2-loop.partial").exists()

    def test_wrong_pinned_shas_fail_closed(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        with pytest.raises(loop_fixture.FixtureError, match="not the pinned"):
            loop_fixture.build(source, tmp_path / "p2-loop", expected_shas={"off": "0" * 64, "on": "1" * 64})
        assert not (tmp_path / "p2-loop").exists()

    def test_a_non_loop_splice_derives_different_shas(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        record = loop_fixture.build(source, tmp_path / "p2-loop", object_ids=("6BB39942", "CBACAF27", "F9AFED1B"), expected_shas=None)
        assert record["planSha256"] != loop_fixture.EXPECTED_PLAN_SHA256

    def test_a_source_that_changes_during_the_build_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        source = _committed_source(tmp_path / "src")
        real = loop_fixture.source_shas
        calls: list[int] = []

        def drifting(root: Path) -> dict[str, str]:
            shas = real(root)
            calls.append(1)
            if len(calls) == 2:
                shas["asset-replace.json"] = "0" * 64
            return shas

        monkeypatch.setattr(loop_fixture, "source_shas", drifting)
        with pytest.raises(loop_fixture.FixtureError, match="read-only source changed"):
            loop_fixture.build(source, tmp_path / "p2-loop")
        assert not (tmp_path / "p2-loop").exists()

    def test_jsonp_payload_must_match_its_json(self, tmp_path: Path) -> None:
        source = _committed_source(tmp_path / "src")
        uuid = json.loads((source / "html-player/assets/header.json").read_text())["slideList"][1]
        jsonp = source / "html-player/assets" / uuid / f"{uuid}.jsonp"
        jsonp.write_bytes(jsonp.read_bytes().replace(b'"endTime":46.03', b'"endTime":46.02', 1))
        with pytest.raises(loop_fixture.FixtureError, match="payload differs"):
            loop_fixture.build(source, tmp_path / "p2-loop")

    def test_a_source_without_a_manifest_writes_none(self, tmp_path: Path) -> None:
        dest = tmp_path / "p2-loop"
        loop_fixture.build(_committed_source(tmp_path / "src"), dest)
        assert not (dest / loop_fixture.MANIFEST).exists()


def _binary_manifest(frames: int = 1381) -> dict[str, Any]:
    """The shape `binary_counter_movie.py --build-fixture` writes (fields the builder reads, plus a few it must keep)."""
    return {
        "counter": "binary", "base": "p2-recovery/html-adversarial", "generator": "scripts/binary_counter_movie.py",
        "movies": [{"sha256": "ab" * 32, "seconds": 46.0333, "fps": 30, "frames": frames}],
        "replaced": [{"path": "html-player/assets/x/assets/Untitled.mov-0.0000-46.0333.mov", "sha256": "ab" * 32},
                     {"path": "html-disposable/assets/x/assets/Untitled.mov-0.0000-46.0333.mov", "sha256": "ab" * 32}],
    }


class TestBinarySource:
    """`--source <main>/output/fixtures/p2-binary`: the same splice, plus the binary-counter manifest carried with a `loop` key."""

    def _source(self, root: Path, manifest: dict[str, Any]) -> Path:
        source = _committed_source(root)
        (source / loop_fixture.MANIFEST).write_text(json.dumps(manifest, indent=1))
        return source

    def test_manifest_is_copied_with_the_loop_record_added(self, tmp_path: Path) -> None:
        manifest = _binary_manifest()
        source = self._source(tmp_path / "src", manifest)
        before = _tree_bytes(source)
        dest = tmp_path / "p2-loop"
        record = loop_fixture.build(source, dest)
        assert _tree_bytes(source) == before, "the read-only source (manifest included) is untouched"
        assert loop_fixture.MANIFEST in record["sourceSha256"], "the manifest is part of the proven-unchanged source"
        written = json.loads((dest / loop_fixture.MANIFEST).read_text())
        assert written == {**manifest, "replaced": manifest["replaced"][:1],
                           "loop": {"objectIds": list(loop_fixture.LOOP_OBJECT_IDS),
                                    "planSha256": loop_fixture.EXPECTED_PLAN_SHA256}}, (
            "only the copied trees' movies stay in `replaced` (html-disposable is not copied), so "
            "binary_counter_movie.verify_fixture can check every listed movie on disk"
        )
        assert written["loop"]["planSha256"] == record["planSha256"]

    def test_binary_source_splices_the_same_files_and_shas(self, tmp_path: Path) -> None:
        plain = loop_fixture.build(_committed_source(tmp_path / "plain"), tmp_path / "plain-loop")
        binary = loop_fixture.build(self._source(tmp_path / "bin", _binary_manifest()), tmp_path / "bin-loop")
        assert binary["planSha256"] == plain["planSha256"] == loop_fixture.EXPECTED_PLAN_SHA256
        assert [(f["path"], f["preSha256"], f["postSha256"]) for f in binary["files"]] == [
            (f["path"], f["preSha256"], f["postSha256"]) for f in plain["files"]
        ]

    @pytest.mark.parametrize("frames", [1380, 1382, None])
    def test_a_movie_frame_count_other_than_the_loop_period_is_refused(self, tmp_path: Path, frames: Any) -> None:
        source = self._source(tmp_path / "src", _binary_manifest(frames))
        with pytest.raises(loop_fixture.FixtureError, match="not the loop period 1381"):
            loop_fixture.build(source, tmp_path / "p2-loop")
        assert not (tmp_path / "p2-loop").exists() and not (tmp_path / "p2-loop.partial").exists()

    @pytest.mark.parametrize("movies", [[], None])
    def test_a_manifest_without_movies_is_refused(self, tmp_path: Path, movies: Any) -> None:
        """Codex r4 #6: an empty movie list would otherwise pass the frame check vacuously."""
        manifest = {**_binary_manifest(), "movies": movies}
        source = self._source(tmp_path / "src", manifest)
        with pytest.raises(loop_fixture.FixtureError, match="not the loop period 1381"):
            loop_fixture.build(source, tmp_path / "p2-loop")
        assert not (tmp_path / "p2-loop").exists()

    def test_a_manifest_that_already_loops_is_refused(self, tmp_path: Path) -> None:
        source = self._source(tmp_path / "src", {**_binary_manifest(), "loop": {}})
        with pytest.raises(loop_fixture.FixtureError, match="already carries a loop key"):
            loop_fixture.build(source, tmp_path / "p2-loop")

    def test_cli_accepts_a_binary_source(self) -> None:
        args = loop_fixture.parse_args(["--source", str(fixture("p2-binary")), "--force"])
        assert args.source == fixture("p2-binary") and args.force is True


class TestCli:
    def test_cli_defaults_point_at_the_main_checkout_fixtures(self) -> None:
        args = loop_fixture.parse_args([])
        assert args.source == main_checkout() / "output/fixtures/p2-recovery/html-adversarial"
        assert args.dest == main_checkout() / "output/fixtures/p2-loop"
        assert args.force is False


REAL_SOURCE = fixture("p2-recovery") / "html-adversarial"


@pytest.mark.skipif(not (REAL_SOURCE / "html-player").is_dir(), reason="real P2 export not available")
def test_real_export_slide_json_splices_to_the_pinned_shas(tmp_path: Path) -> None:
    """The real Keynote bytes (slide JSON only, media left out) through the same build."""
    source = tmp_path / "src"
    for tree in loop_fixture.TREES:
        real_tree = REAL_SOURCE / tree
        for path in [real_tree / "assets/header.json", *loop_fixture.slide_files(real_tree)]:
            target = source / tree / path.relative_to(real_tree)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    shutil.copy2(REAL_SOURCE / "asset-replace.json", source / "asset-replace.json")
    record = loop_fixture.build(source, tmp_path / "p2-loop")
    assert record["planSha256"] == loop_fixture.EXPECTED_PLAN_SHA256
    assert len(record["files"]) == 16
