"""Tests for obed_edom.cli argument parsing. No test may launch Keynote."""
from __future__ import annotations

import subprocess

import pytest

import obed_edom.cli as cli


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


@pytest.fixture
def source(tmp_path, monkeypatch):
    import obed_edom.offline_inspect as offline_inspect

    deck = tmp_path / "deck.key"
    deck.mkdir()
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 20},
    )
    return deck


def _assemble(source, tmp_path, slides, *extra):
    return cli.main(
        ["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", slides, *extra]
    )


def _fake_assemble(monkeypatch, tmp_path, captured, **result):
    import obed_edom.dsk_assemble as dsk_assemble

    def fake_assemble_dsk_deck(*_args, **kwargs):
        captured.update(kwargs)
        return dsk_assemble.AssembleResult(
            path=tmp_path / "out.key", slides_kept=(17,), ordinals={17: 1}, fits={},
            clips_inserted={}, stroke={}, zorder={}, builds={}, size_bytes=0,
            source_size_bytes=0, wall_s=0.0, warnings=(), movie_props={}, **result,
        )

    monkeypatch.setattr(dsk_assemble, "assemble_dsk_deck", fake_assemble_dsk_deck)


def test_dsk_assemble_new_flags_parse(tmp_path, capsys):
    """The step-10 CLI flags (D6) are recognised by argparse and the command reaches
    its first real check (source file existence) rather than erroring on the flags."""
    rc = _assemble(
        tmp_path / "no.key", tmp_path, "1",
        "--min-text-pt", "66", "--text-slide-words", "8", "--no-split",
        "--crop-dir", str(tmp_path / "crops"), "--no-image-crop", "--no-auto-anchor",
        "--no-dedupe", "--no-drop-panel-backdrop", "--split", "17=2",
    )
    assert rc == 1
    assert "File not found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "slides, extra, message",
    [
        ("1", ["--split", "not-a-spec"], "Bad --split"),
        ("17", ["--split", "17=1"], "k must be 2 or more"),
        ("17", ["--no-split", "--split", "17=2"], "conflicts with --no-split"),
        ("1", ["--split", "17=2"], "not in --slides"),
        ("1", ["--rss-limit-gb", "0"], "Bad --rss-limit-gb"),
        ("17", ["--content-only", "--split", "17=2"], "--split has no meaning with --content-only"),
        ("17", ["--content-only", "--no-split"], "--no-split has no meaning with --content-only"),
        ("17", ["--content-only", "--text-fit", "shrink"],
         "--text-fit shrink has no meaning with --content-only"),
        ("17", ["--content-only", "--min-text-pt", "30"],
         "--min-text-pt has no meaning with --content-only"),
    ],
    ids=[
        "bad-split-spec", "split-k-below-2", "split-vs-no-split", "split-slide-not-in-slides",
        "rss-limit-non-positive", "content-only-split", "content-only-no-split",
        "content-only-text-fit-shrink", "content-only-min-text-pt",
    ],
)
def test_dsk_assemble_rejects_bad_flags(source, tmp_path, capsys, slides, extra, message):
    assert _assemble(source, tmp_path, slides, *extra) == 1
    assert message in capsys.readouterr().err


def test_dsk_assemble_rss_limit_gb_reaches_assemble_dsk_deck(source, tmp_path, monkeypatch):
    captured = {}
    _fake_assemble(monkeypatch, tmp_path, captured)
    assert _assemble(source, tmp_path, "1", "--rss-limit-gb", "2.5") == 0
    assert captured["rss_limit_bytes"] == 2_500_000_000


def test_dsk_assemble_content_only_reaches_assemble_dsk_deck_and_reports_skipped(
    source, tmp_path, capsys, monkeypatch
):
    captured = {}
    _fake_assemble(
        monkeypatch, tmp_path, captured,
        skipped=({"slide": 5, "reason": "text", "category": "static", "longTextIds": []},),
    )
    assert _assemble(source, tmp_path, "5,17", "--content-only") == 0
    assert captured["content_only"] is True
    assert "Skipped (1):" in capsys.readouterr().out


def test_dsk_assemble_content_only_layout_preserve_warns(source, tmp_path, capsys, monkeypatch):
    _fake_assemble(monkeypatch, tmp_path, {})
    assert _assemble(source, tmp_path, "17", "--content-only", "--layout", "preserve") == 0
    assert "layout preserved; stage PNGs may export opaque" in capsys.readouterr().err


def test_dsk_assemble_clip_probed_and_sizes_passed(source, tmp_path, monkeypatch):
    import obed_edom.dsk_movie_export as dsk_movie_export

    clip = tmp_path / "clip.mov"
    clip.write_text("movie")
    monkeypatch.setattr(dsk_movie_export, "_ffprobe", lambda _path: (1920, 1080, 24.0, 2.0))
    captured = {}
    _fake_assemble(monkeypatch, tmp_path, captured)
    assert _assemble(source, tmp_path, "17", "--clip", f"17={clip}") == 0
    assert captured["clip_sizes"] == {str(clip): (1920, 1080)}


def _probe_fails(_path):
    raise RuntimeError("ffprobe failed")


@pytest.mark.parametrize(
    "probe", [_probe_fails, lambda _path: (0, 0, 24.0, 2.0)], ids=["probe-failure", "zero-dimensions"]
)
def test_dsk_assemble_bad_clip_refused(source, tmp_path, capsys, monkeypatch, probe):
    import obed_edom.dsk_movie_export as dsk_movie_export

    clip = tmp_path / "clip.mov"
    clip.write_text("movie")
    monkeypatch.setattr(dsk_movie_export, "_ffprobe", probe)
    assert _assemble(source, tmp_path, "17", "--clip", f"17={clip}") == 1
    assert str(clip) in capsys.readouterr().err


@pytest.mark.parametrize(
    "create, slides, extra, message",
    [
        (False, "2", [], "File not found"),
        (True, "", [], "No slides given"),
        (True, "2", ["--rss-limit-gb", "0"], "Bad --rss-limit-gb"),
    ],
    ids=["missing-file", "no-slides", "rss-limit-non-positive"],
)
def test_dsk_export_stages_rejects_bad_input(tmp_path, capsys, create, slides, extra, message):
    deck = tmp_path / "deck.key"
    if create:
        deck.touch()
    rc = cli.main(
        ["dsk-export-stages", str(deck), "--out", str(tmp_path / "out"), "--slides", slides, *extra]
    )
    assert rc == 1
    assert message in capsys.readouterr().err


def test_dsk_export_stages_reaches_export_stage_pngs(tmp_path, monkeypatch):
    import obed_edom.dsk_stage_export as dsk_stage_export

    source = tmp_path / "deck.key"
    source.touch()
    captured = {}

    def fake_stage_counts(deck, slides, **_kwargs):
        captured["stage_counts_slides"] = list(slides)
        return {2: 3, 4: 1}

    def fake_export_stage_pngs(deck, slides, out_dir, *, expected_stage_counts, rss_limit_bytes, log):
        captured["slides"] = list(slides)
        captured["out_dir"] = out_dir
        captured["expected_stage_counts"] = expected_stage_counts
        captured["rss_limit_bytes"] = rss_limit_bytes
        return [
            dsk_stage_export.StageAsset(
                slide=n, stage_index=i, path=out_dir / f"s{n}.{i}.png", width=1920, height=1080,
                alpha_ok=True, bg_alpha_max=0, content_alpha_frac=0.0, transparent_frac=0.0,
                source_name=f"s{n}.{i}.png",
            )
            for n, count in expected_stage_counts.items()
            for i in range(1, count + 1)
        ]

    monkeypatch.setattr(dsk_stage_export, "stage_counts", fake_stage_counts)
    monkeypatch.setattr(dsk_stage_export, "export_stage_pngs", fake_export_stage_pngs)
    out_dir = tmp_path / "out"
    rc = cli.main(
        [
            "dsk-export-stages", str(source), "--out", str(out_dir), "--slides", "2,4",
            "--rss-limit-gb", "3",
        ]
    )
    assert rc == 0
    assert captured["slides"] == [2, 4]
    assert captured["out_dir"] == out_dir
    assert captured["rss_limit_bytes"] == 3_000_000_000


def test_dsk_export_stages_refusal_reaches_stderr(tmp_path, capsys, monkeypatch):
    import obed_edom.dsk_stage_export as dsk_stage_export

    source = tmp_path / "deck.key"
    source.touch()

    def fake_stage_counts(deck, slides, **_kwargs):
        raise dsk_stage_export.StageCountAmbiguous("Stage count undecidable offline on slides [2]")

    monkeypatch.setattr(dsk_stage_export, "stage_counts", fake_stage_counts)
    rc = cli.main(
        ["dsk-export-stages", str(source), "--out", str(tmp_path / "out"), "--slides", "2"]
    )
    assert rc == 1
    assert "Export failed" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--no-export"], []])
def test_remap_offline_hides_abort_prints_detail_and_exits_1(tmp_path, capsys, monkeypatch, extra):
    """Both remap paths turn an `OfflineHidesAborted` into its operator detail on stderr
    and exit 1 (no traceback)."""
    import obed_edom.remap_keynote as rk
    from obed_edom.offline_write import OfflineHidesAborted

    def boom(*_a, **_k):
        raise OfflineHidesAborted("the IWA writer refused the deck before writing", "disk guard")

    monkeypatch.setattr(rk, "remap_keynote", boom)
    monkeypatch.setattr(rk, "remap_and_inspect", boom)
    source = tmp_path / "wall.key"
    template = tmp_path / "tpl.key"
    source.touch()
    template.touch()
    rc = cli.main(["remap", str(source), "--template", str(template),
                   "--out", str(tmp_path / "out.key"), *extra])
    assert rc == 1
    err = capsys.readouterr().err
    assert "Offline hides aborted: the IWA writer refused the deck before writing (disk guard)." in err
    assert "Rerun with OBED_OFFLINE_HIDES=off." in err
