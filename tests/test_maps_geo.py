from obed_edom.maps_geo import (
    MAX_LAT,
    WORLD_MIN_ZOOM,
    camera_from_bbox,
    clamp_cg_shift,
    clamp_lat,
    clamp_lon,
    clamp_zoom,
    geocode,
    geometry_bbox,
    infer_hop_kind,
    parse_maps_query,
    sea_overview_camera,
    search_places,
    toggle_adm0,
    world_width,
)


def test_parse_at_and_google_url():
    at = parse_maps_query("@3.14,101.69,8z")
    assert at is not None
    assert abs(at["camera"]["lat"] - 3.14) < 1e-6
    assert abs(at["camera"]["lon"] - 101.69) < 1e-6
    assert at["camera"]["zoom"] == 8
    google = parse_maps_query("https://www.google.com/maps/@1.35,103.8,10z")
    assert google is not None
    assert abs(google["camera"]["lat"] - 1.35) < 1e-6
    assert abs(google["camera"]["lon"] - 103.8) < 1e-6


def test_camera_from_bbox_never_below_world_min_zoom():
    cam = camera_from_bbox({"west": -180, "south": -85, "east": 180, "north": 85}, 7680, 1080)
    assert cam["zoom"] >= WORLD_MIN_ZOOM


def test_sea_seed_world_width_covers_wall():
    cam = sea_overview_camera()
    assert world_width(cam["zoom"]) >= 7680
    assert 70 <= cam["lon"] <= 155
    assert -42 <= cam["lat"] <= 28


def test_lat_clamp_is_web_mercator_not_90():
    assert clamp_lat(90) == MAX_LAT
    assert clamp_lat(-90) == -MAX_LAT
    assert MAX_LAT == 85.051129


def test_lon_wraps_across_the_dateline():
    assert clamp_lon(190) == -170
    assert clamp_lon(-190) == 170
    assert clamp_lon(180) == 180
    assert clamp_lon(-180) == -180


def test_world_min_zoom_is_the_camera_floor():
    assert clamp_zoom(0) == WORLD_MIN_ZOOM
    assert clamp_zoom(2) == WORLD_MIN_ZOOM
    assert clamp_zoom(8) == 8
    assert clamp_zoom(30) == 22


def test_toggle_adm0():
    assert toggle_adm0([], "mys") == ["MYS"]
    assert toggle_adm0(["MYS", "MMR"], "MYS") == ["MMR"]


def test_clamp_cg_shift():
    assert clamp_cg_shift(500, 10) == (500.0, 0.0)
    assert clamp_cg_shift(2000, 10) == (960.0, 0.0)
    assert clamp_cg_shift(-300, 0) == (-300.0, 0.0)


def test_infer_hop_kind_cut_on_style_or_highlights():
    a = {"style": "positron", "highlights": ["MYS"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    b = {"style": "dark", "highlights": ["MYS"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, b) == "cut"
    c = {"style": "positron", "highlights": ["MMR"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, c) == "cut"


def test_kl_and_singapore_skip_nominatim(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    kl = geocode("KL")
    assert kl["source"] == "places"
    assert "kuala" in kl["label"].lower()
    sg = geocode("Singapore")
    assert sg["source"] == "places"


def test_usa_is_not_lusaka(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    hit = geocode("USA")
    assert hit["source"] == "admin0"
    assert hit["camera"]["lon"] < 0
    place = search_places("usa")
    assert place is None or "lusaka" not in str(place.get("label") or "").lower()


def test_geometry_bbox_antimeridian_not_lon_zero():
    geom = {
        "type": "MultiPoint",
        "coordinates": [[170.0, -18.0], [-170.0, -18.0], [175.0, -16.0], [-175.0, -16.0]],
    }
    bbox = geometry_bbox(geom)
    assert bbox is not None
    cam = camera_from_bbox(bbox)
    assert abs(cam["lon"]) > 90
