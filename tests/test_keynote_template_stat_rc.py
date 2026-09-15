"""Defect 4: a non-zero rc from the template stat-size read must raise, not silently
collapse to ``{}``, and ``read_template_stat_sizes`` must never cache on failure."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import _fake_osascript
from obed_edom import keynote as keynote_mod
from obed_edom.baseline import CACHE_DIR_ENV, deck_digest, template_stat_cache_path


@pytest.fixture()
def template(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "Base_CG_Assets.key"
    path.write_bytes(b"template deck bytes")
    return path


def test_template_stat_read_raises_on_nonzero_rc(template, monkeypatch):
    _fake_osascript(monkeypatch, returncode=1, stderr="stat read failed")

    with pytest.raises(RuntimeError, match="Template stat-size read failed"):
        keynote_mod.read_template_stat_sizes(template)

    cache_path = template_stat_cache_path(deck_digest(template))
    assert not cache_path.is_file()


def test_template_stat_read_parses_on_success(template, monkeypatch):
    raw = "12\t24.0\n34\t18.5\n"
    _fake_osascript(monkeypatch, stdout=raw)

    sizes = keynote_mod.read_template_stat_sizes(template)

    assert sizes == {"12": 24.0, "34": 18.5}
    cache_path = template_stat_cache_path(deck_digest(template))
    assert cache_path.is_file()
