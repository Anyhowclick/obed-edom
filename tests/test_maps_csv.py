import pytest

from obed_edom.maps_csv import (
    COORD_DEFAULT_ZOOM,
    KNOWN_HEADERS,
    PLACE_TYPE_TIER,
    ZOOM_LADDER,
    Place,
    looks_like_header,
    parse_places,
    resolve_zoom,
    zoom_for_place_type,
)


def test_parse_owners_paste():
    text = (
        "China\n"
        'City Harvest Church Kikuyo,"https://maps.google.com/?q=1.35,103.8"\n'
        "Udaipur, 24.58° N, 73.68° E\n"
    )
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["China", "City Harvest Church Kikuyo", "Udaipur"]
    assert places[0].lat is None and places[0].url is None
    assert places[1].url == "https://maps.google.com/?q=1.35,103.8"
    assert places[2].lat == pytest.approx(24.58, abs=1e-6)
    assert places[2].lon == pytest.approx(73.68, abs=1e-6)


@pytest.mark.parametrize(
    "coord_field,expected",
    [
        ('"24.58, 73.68"', (24.58, 73.68)),
        ('"24.58 73.68"', (24.58, 73.68)),
        ('"24.58 N, 73.68 E"', (24.58, 73.68)),
        ('"-24.58, -73.68"', (-24.58, -73.68)),
        ('"24.58 S, 73.68 W"', (-24.58, -73.68)),
        ('"1°17\'N 103°51\'E"', (1 + 17 / 60, 103 + 51 / 60)),
        ('"1°17\'30″N 103°51\'E"', (1 + 17 / 60 + 30 / 3600, 103 + 51 / 60)),
    ],
)
def test_coordinate_shapes_in_one_field(coord_field, expected):
    text = f"Name,{coord_field}"
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].lat == pytest.approx(expected[0], abs=1e-4)
    assert places[0].lon == pytest.approx(expected[1], abs=1e-4)


def test_coordinate_half_split_across_two_fields():
    places, errors = parse_places('Udaipur,24.58° N,73.68° E')
    assert errors == []
    assert places[0].lat == pytest.approx(24.58, abs=1e-6)
    assert places[0].lon == pytest.approx(73.68, abs=1e-6)


def test_blank_lines_and_trailing_commas_ignored():
    places, errors = parse_places("\nChina,\n\nSingapore\n")
    assert errors == []
    assert [p.name for p in places] == ["China", "Singapore"]
    assert places[0].line == 2
    assert places[1].line == 4


def test_name_only_row_has_no_other_fields():
    places, errors = parse_places("Singapore")
    assert errors == []
    place = places[0]
    assert place.lat is None
    assert place.lon is None
    assert place.url is None
    assert place.zoom is None


def test_url_only_row():
    places, errors = parse_places('City Harvest Church Kikuyo,"https://maps.google.com/?q=1.35,103.8"')
    assert errors == []
    assert places[0].url == "https://maps.google.com/?q=1.35,103.8"
    assert places[0].lat is None
    assert places[0].lon is None


@pytest.mark.parametrize("zoom_field", ["z=6.8", "@6.8", "zoom 6.8"])
def test_explicit_zoom_shapes(zoom_field):
    places, errors = parse_places(f"China,{zoom_field}")
    assert errors == []
    assert places[0].zoom == pytest.approx(6.8)


def test_bare_number_after_coordinate_is_still_an_error():
    places, errors = parse_places('Udaipur,"24.58, 73.68",6.8')
    assert places == []
    assert len(errors) == 1
    assert "Line 1" in errors[0]
    assert "6.8" in errors[0]


def test_bare_number_with_only_name_is_an_error():
    places, errors = parse_places("China,6.8")
    assert places == []
    assert len(errors) == 1
    assert "Line 1" in errors[0]


def test_mixed_line_name_url_zoom_kind_any_order():
    places, errors = parse_places(
        'Kikuyo Church,building,z=9,"https://maps.google.com/?q=1.35,103.8"'
    )
    assert errors == []
    place = places[0]
    assert place.name == "Kikuyo Church"
    assert place.kind == "building"
    assert place.zoom == pytest.approx(9.0)
    assert place.url == "https://maps.google.com/?q=1.35,103.8"


def test_error_empty_name():
    places, errors = parse_places(',24.5 N, 73.6 E')
    assert places == []
    assert errors == ["Line 1: no name"]


def test_error_lone_coordinate_half():
    places, errors = parse_places("Udaipur,24.58 N")
    assert places == []
    assert "lone coordinate half" in errors[0]


def test_error_two_kinds():
    places, errors = parse_places("Kikuyo Church,building,church")
    assert places == []
    assert "two kinds" in errors[0]


@pytest.mark.parametrize(
    "line,expect_header",
    [
        ("name,lat,lon", True),
        ("China,", False),
        ("Name, Lat, Lon", True),
        ("China", False),
        ("name", True),
    ],
)
def test_header_detection(line, expect_header):
    fields = [f.strip() for f in line.split(",")]
    assert looks_like_header(fields) is expect_header


def test_header_form_still_works():
    places, errors = parse_places("name,lat,lon\nSingapore,1.3521,103.8198\n")
    assert errors == []
    assert places[0].name == "Singapore"
    assert places[0].lat == pytest.approx(1.3521)
    assert places[0].lon == pytest.approx(103.8198)


@pytest.mark.parametrize("tier", ZOOM_LADDER)
def test_zoom_for_place_type_ladder_keys(tier):
    assert zoom_for_place_type(tier) == ZOOM_LADDER[tier]


@pytest.mark.parametrize("alias,tier", PLACE_TYPE_TIER.items())
def test_zoom_for_place_type_aliases(alias, tier):
    assert zoom_for_place_type(alias) == ZOOM_LADDER[tier]


@pytest.mark.parametrize("place_type", [None, "spaceport", ""])
def test_zoom_for_place_type_unknown_falls_back_to_13(place_type):
    assert zoom_for_place_type(place_type) == 13.0
    assert zoom_for_place_type(place_type) == COORD_DEFAULT_ZOOM


def test_resolve_zoom_precedence():
    explicit = Place(line=1, name="x", zoom=6.8)
    assert resolve_zoom(explicit, place_type="city", zoom_from_url=9.0) == 6.8

    from_url = Place(line=1, name="x")
    assert resolve_zoom(from_url, place_type="city", zoom_from_url=9.0) == 9.0

    from_ladder = Place(line=1, name="x")
    assert resolve_zoom(from_ladder, place_type="country") == ZOOM_LADDER["country"]

    default_only = Place(line=1, name="x")
    assert resolve_zoom(default_only) == COORD_DEFAULT_ZOOM


def test_known_headers_includes_place():
    assert "place" in KNOWN_HEADERS
