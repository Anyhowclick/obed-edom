"""Digest-keyed cache for read_template_stat_sizes.

The template is invariant across runs, so the grouped stat-number sizes are read
from Keynote once and cached by the template's content digest. A cache hit must
return the map without opening Keynote at all. These lock that behaviour without
ever invoking AppleScript (the Keynote reader is mocked).
"""

from pathlib import Path

import pytest

from obed_edom import keynote, keynote_app
from obed_edom.baseline import template_stat_cache_path


@pytest.fixture(autouse=True)
def _isolated_cache(monkeypatch, tmp_path):
    # Route the cache into tmp and pin the Keynote version tag so the path is stable.
    monkeypatch.setenv("OBED_EDOM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(keynote_app, "app_version", lambda *a, **k: "test")


def _template(tmp_path: Path, data: bytes = b"template-bytes") -> Path:
    path = tmp_path / "cg_template.key"
    path.write_bytes(data)
    return path


def test_cache_miss_writes_and_returns(tmp_path, monkeypatch):
    template = _template(tmp_path)
    calls = {"n": 0}

    def fake_reader(_template):
        calls["n"] += 1
        return {"269": 200.0, "183": 150.0}

    monkeypatch.setattr(keynote, "_read_template_stat_sizes_via_keynote", fake_reader)

    result = keynote.read_template_stat_sizes(template)

    assert result == {"269": 200.0, "183": 150.0}
    assert calls["n"] == 1  # Keynote was read exactly once on the miss.
    # The cache file now exists for this template's digest.
    from obed_edom.baseline import deck_digest

    assert template_stat_cache_path(deck_digest(template)).is_file()


def test_cache_hit_does_not_invoke_reader(tmp_path, monkeypatch):
    template = _template(tmp_path)

    # Prime the cache with a real miss.
    monkeypatch.setattr(
        keynote,
        "_read_template_stat_sizes_via_keynote",
        lambda _t: {"269": 200.0},
    )
    first = keynote.read_template_stat_sizes(template)
    assert first == {"269": 200.0}

    # On the hit, the reader must never be called — a hit costs no Keynote open.
    def boom(_t):
        raise AssertionError("Keynote reader was invoked on a cache hit")

    monkeypatch.setattr(keynote, "_read_template_stat_sizes_via_keynote", boom)
    second = keynote.read_template_stat_sizes(template)
    assert second == {"269": 200.0}


def test_different_digest_misses(tmp_path, monkeypatch):
    template = _template(tmp_path, b"first-bytes")
    seen = []

    def fake_reader(_t):
        seen.append(Path(_t).read_bytes())
        return {"1": float(len(seen))}

    monkeypatch.setattr(keynote, "_read_template_stat_sizes_via_keynote", fake_reader)

    keynote.read_template_stat_sizes(template)  # miss #1
    keynote.read_template_stat_sizes(template)  # hit, no read
    assert len(seen) == 1

    template.write_bytes(b"changed-bytes")  # different digest
    keynote.read_template_stat_sizes(template)  # miss #2
    assert len(seen) == 2


def test_use_cache_false_bypasses(tmp_path, monkeypatch):
    template = _template(tmp_path)
    calls = {"n": 0}

    def fake_reader(_t):
        calls["n"] += 1
        return {"269": 200.0}

    monkeypatch.setattr(keynote, "_read_template_stat_sizes_via_keynote", fake_reader)

    keynote.read_template_stat_sizes(template, use_cache=False)
    keynote.read_template_stat_sizes(template, use_cache=False)
    assert calls["n"] == 2  # never served from cache
    # A bypassed read also does not write the cache.
    from obed_edom.baseline import deck_digest

    assert not template_stat_cache_path(deck_digest(template)).is_file()
