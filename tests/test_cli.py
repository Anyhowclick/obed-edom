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
        ]
    )
    assert rc == 1
    assert "File not found" in capsys.readouterr().err
