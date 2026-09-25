"""Offline tests for the pure parts of `scripts/managed_obs_qualify.py` (loopMode plan §10 WS-C); no OBS, no browser.

The looping soak fixture (`output/p2-loop`, built by `scripts/loop_fixture.py`) must qualify on product code: the
harness no longer splices the continuity allowlist in-process. A fixture is looping iff its `fixture.json` carries the
`loop` record the builder adds; the P2 family is the P2 base without that key. Pre-check (a) is enforced: every slide-1
`untitled.mov` and the handed-back carried element report `video.loop`, and the export differs from P2 only in the
spliced files, by `loopMode="looping"` keys. Synthetic fixtures are built from the committed P2 slide JSON with the
real builder, so the representation check reads Keynote-shaped bytes.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie  # noqa: E402
import loop_fixture  # noqa: E402
import managed_obs_qualify as q  # noqa: E402

from test_loop_fixture import _binary_manifest, _committed_source  # noqa: E402

HARNESS = REPO / "scripts" / "managed_obs_qualify.py"


def _manifest(root: Path, manifest: dict[str, Any] | None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (root / binary_counter_movie.MANIFEST).write_text(json.dumps(manifest))
    return root


@pytest.fixture
def looped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A P2 base (the harness's FIXTURE) and its `loop_fixture.build` copy with the binary manifest."""
    base = _committed_source(tmp_path / "p2")
    (base / binary_counter_movie.MANIFEST).write_text(json.dumps(_binary_manifest()))
    monkeypatch.setattr(q, "FIXTURE", base)
    dest = tmp_path / "p2-loop"
    loop_fixture.build(base, dest)
    return dest


class TestFixtureFamily:
    def test_binary_copy_without_loop_is_p2_family_and_not_looping(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "p2-binary", _binary_manifest())
        assert q.p2_family(fixture) is True
        assert q.fixture_loops(fixture) is False

    def test_a_loop_key_takes_it_out_of_the_p2_family_and_makes_it_looping(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "p2-loop", {**_binary_manifest(), "loop": {"objectIds": [], "planSha256": {}}})
        assert q.p2_family(fixture) is False
        assert q.fixture_loops(fixture) is True

    def test_the_p2_fixture_itself_is_p2_family(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        base = _manifest(tmp_path / "p2", None)
        monkeypatch.setattr(q, "FIXTURE", base)
        assert q.p2_family(base) is True and q.fixture_loops(base) is False

    def test_no_manifest_elsewhere_is_neither(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "other", None)
        assert q.p2_family(fixture) is False, "no path-inequality inference: an unknown fixture is not P2"
        assert q.fixture_loops(fixture) is False, "and not looping either: looping is the manifest's loop key only"

    def test_a_different_base_is_not_p2_family(self, tmp_path: Path) -> None:
        fixture = _manifest(tmp_path / "x", {**_binary_manifest(), "base": "elsewhere"})
        assert q.p2_family(fixture) is False

    def test_the_built_loop_fixture_is_looping(self, looped: Path) -> None:
        assert q.fixture_loops(looped) is True and q.p2_family(looped) is False

    def test_soak_default_is_p2_loop(self) -> None:
        assert q.SOAK_FIXTURE == q.REPO / "output/p2-loop"


class TestSpliceGone:
    def test_harness_never_patches_the_allowlist(self) -> None:
        text = HARNESS.read_text()
        assert "QUALIFIED_PLAN_SHA256" not in text
        assert not re.search(r"mock\.patch[^\n]*plan_signature", text)
        for name in ("allow_soak_plan", "build_fixture", "--build-fixture", "--i-have-owner-go", "allowlistSplice"):
            assert name not in text.replace("binary_counter_movie.py --build-fixture", ""), name
        assert not hasattr(q, "allow_soak_plan") and not hasattr(q, "build_fixture")

    def test_no_path_inequality_looping_inference(self) -> None:
        text = HARNESS.read_text()
        assert 'ctx["fixture"] != FIXTURE' not in text
        assert len(re.findall(r"not p2_family\(", text)) == 1, "the only negation is the non-soak arms' --fixture refusal"

    def test_cli_has_no_build_fixture(self) -> None:
        with pytest.raises(SystemExit):
            q.main(["--arm", "soak", "--build-fixture", "x.key"])

    def test_a_fixture_that_does_not_qualify_on_product_code_exits_clearly(self, tmp_path: Path) -> None:
        """Known-bad: a splice on slides 1-2 only derives, but its plan sha is not allowlisted (the conftest cache root holds the export)."""
        source = _committed_source(tmp_path / "p2")
        partial = tmp_path / "partial-loop"
        loop_fixture.build(source, partial, object_ids=("6BB39942", "CBACAF27", "F9AFED1B"), expected_shas=None)
        with pytest.raises(SystemExit, match="does not qualify on product code"):
            q.fixture_facts(partial)

    def test_the_built_loop_fixture_qualifies_on_product_code(self, looped: Path) -> None:
        """Control: the full five-movie splice is allowlisted on product code and yields the armed facts."""
        armed = q.fixture_facts(looped)
        assert {"instanceRect", "movieSlot", "assetKeys"} <= set(armed)


class TestLoopFrames:
    def test_matching_frames_pass(self, tmp_path: Path) -> None:
        q.check_loop_frames(_manifest(tmp_path / "f", _binary_manifest()))

    def test_no_manifest_passes(self, tmp_path: Path) -> None:
        q.check_loop_frames(_manifest(tmp_path / "f", None))

    def test_other_frames_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="not the soak loop period 1381"):
            q.check_loop_frames(_manifest(tmp_path / "f", _binary_manifest(1380)))


def _session(**over: Any) -> dict[str, Any]:
    """A pre-check session that passes every check: two wraps, LIVE throughout, uploads rising."""
    times = [30.0, 40.0, 4.0, 14.0, 24.0, 34.0, 44.0, 8.0]
    session = {
        "session": "precheck",
        "slide1Videos": [
            {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True},
            {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True},
            {"src": "WA0125.mp4", "loop": False},
        ],
        "handedBack": {"elId": 7, "loop": True, "isConnected": True, "paused": False, "t": 12.0},
        "outputAtStop": {"continuity": {"mode": "qualified", "glReplay": {"mode": "injected"}}},
        "samples": [{"t": 2.0 * i, "state": "LIVE", "standDowns": [], "videoEnded": False, "uploads": 100 * (i + 1),
                     "carriedT": t} for i, t in enumerate(times)],
    }
    session.update(over)
    return session


def _precheck(session: dict[str, Any], fixture: Path) -> dict[str, Any]:
    return q.precheck_gates({"sessions": [session]}, fixture)["precheck"]


def _check(result: dict[str, Any], prefix: str) -> dict[str, Any]:
    return next(c for c in result["checks"] if c["check"].startswith(prefix))


class TestPrecheckA:
    def test_control_passes(self, looped: Path) -> None:
        result = _precheck(_session(), looped)
        assert result["verdict"] == "PASS", result["failing"]
        static = _check(result, "(a) loop representation")["value"]
        assert static["differing"] == static["spliced"] and len(static["spliced"]) == 8
        assert static["addedLoopKeys"] and all(k.endswith(':loopMode="looping"') for k in static["addedLoopKeys"])
        assert all(c["enforced"] for c in result["checks"] if c["check"].startswith("(a)"))

    def test_a_slide1_movie_that_does_not_loop_fails(self, looped: Path) -> None:
        videos = [{"src": "Untitled.mov-0.0000-46.0333.mov", "loop": True}, {"src": "Untitled.mov-0.0000-46.0333.mov", "loop": False}]
        result = _precheck(_session(slide1Videos=videos), looped)
        assert result["verdict"] == "FAIL"
        assert result["failing"] == ["(a) video.loop on every slide-1 untitled.mov"]

    def test_no_slide1_movie_read_fails(self, looped: Path) -> None:
        result = _precheck(_session(slide1Videos=[{"src": "WA0125.mp4", "loop": False}]), looped)
        assert result["failing"] == ["(a) video.loop on every slide-1 untitled.mov"]

    @pytest.mark.parametrize("handed", [None, {"elId": None, "missing": True}, {"elId": 7, "missing": True},
                                        {"elId": 7, "loop": False}])
    def test_a_missing_or_non_looping_handed_back_element_fails(self, looped: Path, handed: Any) -> None:
        session = _session()
        if handed is None:
            del session["handedBack"]
        else:
            session["handedBack"] = handed
        result = _precheck(session, looped)
        assert result["failing"] == ["(a) video.loop on the handed-back carried element"]

    def test_an_extra_differing_json_fails(self, looped: Path) -> None:
        header = looped / "html-unmodified/assets/header.json"
        header.write_text(header.read_text() + " ")
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert "assets/header.json" in _check(result, "(a) loop representation")["value"]["differing"]

    def test_a_spliced_file_left_unspliced_fails(self, looped: Path) -> None:
        record = json.loads((looped / "loop-splice.json").read_text())
        rel = next(f["path"] for f in record["files"] if f["path"].startswith("html-unmodified/"))
        shutil.copy2(q.FIXTURE / rel, looped / rel)
        assert _precheck(_session(), looped)["failing"] == ["(a) loop representation"]

    @pytest.mark.parametrize("value", ['"loopBackAndForth"', '"none"', "true"])
    def test_a_loop_key_other_than_looping_fails(self, looped: Path, value: str) -> None:
        record = json.loads((looped / "loop-splice.json").read_text())
        rel = next(f["path"] for f in record["files"] if f["path"].startswith("html-unmodified/") and f["path"].endswith(".json"))
        path = looped / rel
        path.write_text(path.read_text().replace('"loopMode":"looping"', f'"loopMode":{value}', 1))
        result = _precheck(_session(), looped)
        assert result["failing"] == ["(a) loop representation"]
        assert any(f"loopMode={value}" in k for k in _check(result, "(a) loop representation")["value"]["addedLoopKeys"])

    def test_a_fixture_without_the_splice_record_fails(self, looped: Path) -> None:
        (looped / "loop-splice.json").unlink()
        assert _precheck(_session(), looped)["failing"] == ["(a) loop representation"]

    def test_the_p2_base_itself_fails_the_representation(self, looped: Path) -> None:
        """Known-bad: a non-looping export has no added loop keys and no splice record."""
        assert _precheck(_session(), q.FIXTURE)["failing"] == ["(a) loop representation"]


class TestTiming:
    def test_timing_summary_keys(self) -> None:
        run = {"arm": "soak", "take": 1, "timingS": {"launch": 4.2, "quit": 3.1, "total": 400.0},
               "sessions": [{"session": "soak", "timingS": {"script": 330.5, "decode": 20.25}},
                            {"session": "soak-off", "timingS": {"script": 20.0, "decode": 0.0}}]}
        summary = q.timing_summary(run)
        assert summary == {"arm": "soak", "take": 1, "launch": 4.2, "script": 350.5, "quit": 3.1, "decode": 20.25,
                           "total": 400.0, "sessions": {"soak": {"script": 330.5, "decode": 20.25},
                                                        "soak-off": {"script": 20.0, "decode": 0.0}}}

    def test_timing_summary_of_a_run_that_never_launched(self) -> None:
        summary = q.timing_summary({"arm": "g2", "take": 1, "timingS": {"quit": 0.5}, "sessions": []})
        assert summary["launch"] is None and summary["script"] == 0 and summary["decode"] == 0
