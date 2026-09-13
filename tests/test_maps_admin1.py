"""Admin-1 split, cache and name listing. No network in the default tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path as PathType

import pytest

from obed_edom import maps_admin1
from obed_edom.maps_admin1 import (
    ADMIN1_KEYS,
    INDEX_NAME,
    Admin1FetchError,
    admin1_dir,
    ensure_admin1,
    load_admin1,
    split_admin1,
)


def _feature(adm0, code, name, **extra):
    props = {
        "adm0_a3": adm0,
        "adm1_code": code,
        "iso_3166_2": f"{adm0}-X",
        "name": name,
        "type_en": "Province",
        "scalerank": 2,
        "featurecla": "Admin-1 scale rank",
        **extra,
    }
    return {"type": "Feature", "properties": props, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}


def _raw():
    return {
        "type": "FeatureCollection",
        "features": [
            _feature("MYS", "MYS-1186", "Sabah"),
            _feature("MYS", "MYS-1187", "Sarawak"),
            _feature("PHL", "PHL-1234", "Cebu"),
            _feature("XXX", "XXX+99?", None),
        ],
    }


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(maps_admin1, "output_root", lambda: tmp_path)
    maps_admin1._admin1.clear()
    yield
    maps_admin1._admin1.clear()


def test_split_groups_by_country_and_drops_the_nameless_residual():
    count = split_admin1(_raw(), admin1_dir())

    assert count == 3
    assert sorted(p.name for p in admin1_dir().glob("*.geojson")) == ["MYS.geojson", "PHL.geojson"]
    mys = json.loads((admin1_dir() / "MYS.geojson").read_text())
    assert [f["properties"]["name"] for f in mys["features"]] == ["Sabah", "Sarawak"]
    assert not (admin1_dir() / "XXX.geojson").exists()


def test_split_keeps_only_the_five_slim_keys():
    split_admin1(_raw(), admin1_dir())

    props = json.loads((admin1_dir() / "PHL.geojson").read_text())["features"][0]["properties"]
    assert set(props) == set(ADMIN1_KEYS)
    assert "scalerank" not in props


def test_split_writes_the_index_done_marker():
    split_admin1(_raw(), admin1_dir())

    index = json.loads((admin1_dir() / INDEX_NAME).read_text())
    assert index["features"] == 3
    assert index["countries"] == ["MYS", "PHL"]
    assert index["url"].endswith("ne_10m_admin_1_states_provinces.geojson")


def test_split_is_idempotent():
    first = split_admin1(_raw(), admin1_dir())
    before = (admin1_dir() / "MYS.geojson").read_bytes()

    assert split_admin1(_raw(), admin1_dir()) == first
    assert (admin1_dir() / "MYS.geojson").read_bytes() == before
    assert not list(admin1_dir().glob("*.tmp"))


def test_load_admin1_returns_none_for_an_absent_country():
    split_admin1(_raw(), admin1_dir())

    assert load_admin1("ZZZ") is None
    assert load_admin1("xx") is None


def test_load_admin1_reads_the_file_once(monkeypatch):
    split_admin1(_raw(), admin1_dir())
    reads = {"n": 0}
    real_read_text = PathType.read_text

    def counting_read_text(self, *args, **kwargs):
        if self.suffix == ".geojson":
            reads["n"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "read_text", counting_read_text)

    assert load_admin1("MYS") is not None
    assert load_admin1("MYS") is not None
    assert reads["n"] == 1


def test_load_admin1_lru_keeps_recently_accessed_country_on_eviction():
    codes = [f"A{chr(ord('A') + i)}A" for i in range(maps_admin1.ADMIN1_CACHE_MAX)]
    raw = {
        "type": "FeatureCollection",
        "features": [_feature(code, f"{code}-1", code) for code in codes],
    }
    split_admin1(raw, admin1_dir())
    for code in codes:
        assert load_admin1(code) is not None

    load_admin1(codes[0])
    extra_code = "ZZZ"
    split_admin1(
        {
            "type": "FeatureCollection",
            "features": [_feature(extra_code, f"{extra_code}-1", extra_code)],
        },
        admin1_dir(),
    )
    assert load_admin1(extra_code) is not None

    assert codes[0] in maps_admin1._admin1
    assert codes[1] not in maps_admin1._admin1


def test_ensure_admin1_downloads_once_across_two_calls(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return _raw()

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(maps_admin1.requests, "get", fake_get)

    assert ensure_admin1() == admin1_dir()
    assert ensure_admin1() == admin1_dir()
    assert calls["n"] == 1


def test_ensure_admin1_raises_on_a_failed_download(monkeypatch):
    def fake_get(url, **kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr(maps_admin1.requests, "get", fake_get)

    with pytest.raises(Admin1FetchError):
        ensure_admin1()


def _load_fetch_admin1_script():
    root = PathType(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("fetch_admin1", root / "scripts" / "fetch_admin1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_admin1_script_smoke(monkeypatch, capsys):
    script = _load_fetch_admin1_script()
    monkeypatch.setattr(script, "ensure_admin1", lambda: admin1_dir())
    monkeypatch.setattr(script, "admin1_stats", lambda: {"bytes": 123, "files": 2})
    monkeypatch.setattr(script, "clear_admin1", lambda: None)
    monkeypatch.setattr("sys.argv", ["fetch_admin1.py"])
    split_admin1(_raw(), admin1_dir())

    script.main()

    out = capsys.readouterr().out
    assert str(admin1_dir()) in out
    assert "2 countries" in out
