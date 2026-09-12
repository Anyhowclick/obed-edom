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


def test_dsk_assemble_new_flags_parse(tmp_path, capsys):
    """The step-10 CLI flags (D6) are recognised by argparse and the command reaches
    its first real check (source file existence) rather than erroring on the flags."""
    missing = tmp_path / "no.key"
    rc = cli.main(
        [
            "dsk-assemble", str(missing), "--out", str(tmp_path / "out.key"), "--slides", "1",
            "--min-text-pt", "66", "--text-slide-words", "8", "--no-split",
            "--crop-dir", str(tmp_path / "crops"), "--no-image-crop", "--no-auto-anchor",
            "--no-dedupe", "--no-drop-panel-backdrop", "--split", "17=2",
        ]
    )
    assert rc == 1
    assert "File not found" in capsys.readouterr().err


def test_dsk_assemble_bad_split_spec_rejected(tmp_path, capsys, monkeypatch):
    import obed_edom.offline_inspect as offline_inspect

    source = tmp_path / "deck.key"
    source.mkdir()
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 20},
    )
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "1",
            "--split", "not-a-spec",
        ]
    )
    assert rc == 1
    assert "Bad --split" in capsys.readouterr().err


def test_dsk_assemble_split_k_below_2_rejected(tmp_path, capsys, monkeypatch):
    import obed_edom.offline_inspect as offline_inspect

    source = tmp_path / "deck.key"
    source.mkdir()
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 20},
    )
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "17",
            "--split", "17=1",
        ]
    )
    assert rc == 1
    assert "k must be 2 or more" in capsys.readouterr().err


def test_dsk_assemble_split_conflicts_with_no_split_rejected(tmp_path, capsys, monkeypatch):
    import obed_edom.offline_inspect as offline_inspect

    source = tmp_path / "deck.key"
    source.mkdir()
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 20},
    )
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "17",
            "--no-split", "--split", "17=2",
        ]
    )
    assert rc == 1
    assert "conflicts with --no-split" in capsys.readouterr().err


def test_dsk_assemble_split_slide_not_in_slides_rejected(tmp_path, capsys, monkeypatch):
    import obed_edom.offline_inspect as offline_inspect

    source = tmp_path / "deck.key"
    source.mkdir()
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 20},
    )
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "1",
            "--split", "17=2",
        ]
    )
    assert rc == 1
    assert "not in --slides" in capsys.readouterr().err
