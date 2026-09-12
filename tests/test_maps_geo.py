from obed_edom.maps_geo import (
    CG_MIN_ZOOM,
    CG_WIDTH,
    DEFAULT_HIDDEN_LAYERS,
    MAX_LAT,
    SEA_OVERVIEW_BBOX,
    WALL_HEIGHT,
    WORLD_MIN_ZOOM,
    camera_from_bbox,
    clamp_cg_shift,
    clamp_lat,
    clamp_lon,
    clamp_zoom,
    geocode,
    geometry_bbox,
    infer_hop_kind,
    inherit_hidden_layers,
    mercator_y,
    parse_maps_query,
    sea_overview_camera,
    search_places,
    slide_hidden_layers,
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


def test_camera_from_bbox_can_zoom_below_wrap_floor():
    cam = camera_from_bbox({"west": -180, "south": -85, "east": 180, "north": 85}, 7680, 1080)
    assert cam["zoom"] < WORLD_MIN_ZOOM
    assert cam["zoom"] >= 0


def test_sea_overview_fits_cg():
    cam = sea_overview_camera()
    world = world_width(cam["zoom"])
    bbox = SEA_OVERVIEW_BBOX
    span_y = abs(mercator_y(bbox["south"]) - mercator_y(bbox["north"]))
    span_x = (bbox["east"] - bbox["west"]) / 360.0
    assert span_y * world <= WALL_HEIGHT + 1e-6
    assert span_x * world <= CG_WIDTH + 1e-6
    assert cam["zoom"] < WORLD_MIN_ZOOM
    assert cam["zoom"] >= CG_MIN_ZOOM
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


def test_clamp_zoom_allows_below_wrap_thresholds():
    assert clamp_zoom(0) == 0
    assert clamp_zoom(1) == 1
    assert clamp_zoom(8) == 8
    assert clamp_zoom(30) == 22
    assert clamp_zoom(2, WORLD_MIN_ZOOM) == WORLD_MIN_ZOOM


def test_world_bbox_height_contains_in_cg():
    cam = camera_from_bbox({"west": -180, "south": -85, "east": 180, "north": 85}, 1920, 1080)
    world = world_width(cam["zoom"])
    span_y = abs(mercator_y(-85) - mercator_y(85))
    assert span_y * world <= WALL_HEIGHT + 1e-6
    assert cam["zoom"] < CG_MIN_ZOOM
    assert world < 1920


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


def test_infer_hop_kind_cut_on_hidden_layers():
    a = {"style": "positron", "highlights": [], "hiddenLayers": ["roadnames", "arrows"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    b = {"style": "positron", "highlights": [], "hiddenLayers": ["roadnames", "pois"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, b) == "cut"
    c = {"style": "positron", "highlights": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, c) == "morph"


def test_infer_hop_kind_cut_on_hillshade():
    a = {"style": "positron", "highlights": [], "hillshade": True, "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    b = {"style": "positron", "highlights": [], "hillshade": False, "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, b) == "cut"
    c = {"style": "positron", "highlights": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    d = {"style": "positron", "highlights": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(c, d) == "morph"


def test_infer_hop_kind_distinguishes_explicit_empty_hidden_layers():
    a = {"style": "positron", "highlights": [], "hiddenLayers": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    b = {"style": "positron", "highlights": [], "hiddenLayers": ["roadnames"], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, b) == "cut"
    c = {"style": "positron", "highlights": [], "hiddenLayers": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 0}}
    assert infer_hop_kind(a, c) == "morph"


def test_infer_hop_kind_allows_matching_rotation_and_zoom_delta_two():
    a = {"style": "positron", "highlights": [], "camera": {"zoom": 4, "pitch": 0, "bearing": 22}}
    b = {"style": "positron", "highlights": [], "camera": {"zoom": 6, "pitch": 0, "bearing": 22}}
    assert infer_hop_kind(a, b) == "morph"
    b["camera"] = {**b["camera"], "bearing": 23}
    assert infer_hop_kind(a, b) == "movie"
    b["camera"] = {**b["camera"], "bearing": 22, "zoom": 6.1}
    assert infer_hop_kind(a, b) == "movie"


def test_slide_hidden_layers():
    assert slide_hidden_layers({"hiddenLayers": None}) == list(DEFAULT_HIDDEN_LAYERS)
    assert slide_hidden_layers({}) == list(DEFAULT_HIDDEN_LAYERS)
    assert slide_hidden_layers({"hiddenLayers": []}) == []
    source = ["pois", "shields"]
    slide = {"hiddenLayers": source}
    result = slide_hidden_layers(slide)
    assert result == source
    assert result is not source


def test_inherit_hidden_layers():
    no_deck = {"slides": [{"id": "s1", "hiddenLayers": None}]}
    assert inherit_hidden_layers(no_deck)["slides"][0]["hiddenLayers"] == list(DEFAULT_HIDDEN_LAYERS)

    empty_deck = {"hiddenLayers": [], "slides": [{"id": "s1", "hiddenLayers": None}]}
    assert inherit_hidden_layers(empty_deck)["slides"][0]["hiddenLayers"] == []

    explicit_slide = {"hiddenLayers": ["pois"], "slides": [{"id": "s1", "hiddenLayers": ["shields"]}]}
    assert inherit_hidden_layers(explicit_slide)["slides"][0]["hiddenLayers"] == ["shields"]

    no_slides = {"hiddenLayers": ["pois"]}
    assert inherit_hidden_layers(no_slides) == no_slides

    original = {"hiddenLayers": ["pois"], "slides": [{"id": "s1", "hiddenLayers": None}]}
    snapshot = {"hiddenLayers": ["pois"], "slides": [{"id": "s1", "hiddenLayers": None}]}
    inherit_hidden_layers(original)
    assert original == snapshot


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


def test_geocode_singapore_carries_place_type(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    hit = geocode("Singapore")
    assert hit["source"] == "places"
    assert hit["placeType"] == "city"


def test_parse_maps_query_zoom_from_url():
    at = parse_maps_query("@1.3,103.8,6.8z")
    assert at["zoomFromUrl"] is True
    comma_zoom = parse_maps_query("https://www.google.com/maps/@1.3,103.8/data=!3d1!4d1,6.8z")
    assert comma_zoom["zoomFromUrl"] is True
    no_zoom = parse_maps_query("https://www.google.com/maps/@1.3,103.8")
    assert no_zoom["zoomFromUrl"] is False
    bare_pair = parse_maps_query("1.3,103.8")
    assert bare_pair["zoomFromUrl"] is False


def test_country_via_admin0_has_place_type(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Nominatim should not run")

    monkeypatch.setattr("obed_edom.maps_geo.requests.get", boom)
    hit = geocode("USA")
    assert hit["placeType"] == "country"


def test_geometry_bbox_antimeridian_not_lon_zero():
    geom = {
        "type": "MultiPoint",
        "coordinates": [[170.0, -18.0], [-170.0, -18.0], [175.0, -16.0], [-175.0, -16.0]],
    }
    bbox = geometry_bbox(geom)
    assert bbox is not None
    cam = camera_from_bbox(bbox)
    assert abs(cam["lon"]) > 90
