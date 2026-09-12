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
        'Kikuyo Church,landmark,z=9,"https://maps.google.com/?q=1.35,103.8"'
    )
    assert errors == []
    place = places[0]
    assert place.name == "Kikuyo Church"
    assert place.kind == "landmark"
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
    places, errors = parse_places("Kikuyo Church,dot,landmark")
    assert places == []
    assert "two kinds" in errors[0]


def test_arbitrary_leftover_words_become_query_context():
    places, errors = parse_places("China,Asia")
    assert errors == []
    assert places[0].name == "China"
    assert places[0].kind is None
    assert places[0].query == "Asia"

    places, errors = parse_places("Kikuyo Church,Kenya,building")
    assert errors == []
    assert places[0].kind is None
    assert places[0].query == "Kenya, building"


@pytest.mark.parametrize(
    "line,expect_header",
    [
        ("name,lat,lon", True),
        ("China,", False),
        ("Name, Lat, Lon", True),
        ("China", False),
        ("name", False),
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


def test_unquoted_google_maps_url_with_commas_is_not_split():
    text = (
        "City Harvest Church Kikuyo,"
        "https://www.google.com/maps/place/City+Harvest+Church/@1.3431,103.6919,19.6z/"
        "data=!4m6!3m5!1s0x0:0x0!8m2!3d1.3431!4d103.6919"
    )
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].name == "City Harvest Church Kikuyo"
    assert places[0].url == (
        "https://www.google.com/maps/place/City+Harvest+Church/@1.3431,103.6919,19.6z/"
        "data=!4m6!3m5!1s0x0:0x0!8m2!3d1.3431!4d103.6919"
    )


def test_quoted_google_maps_url_with_commas_still_works():
    text = (
        'City Harvest Church Kikuyo,"https://www.google.com/maps/place/@1.3431,103.6919,19.6z/"'
    )
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].url == "https://www.google.com/maps/place/@1.3431,103.6919,19.6z/"


def test_two_adjacent_bare_numbers_in_range_are_a_coordinate_pair():
    places, errors = parse_places("Udaipur,24.58,73.68")
    assert errors == []
    assert places[0].lat == pytest.approx(24.58)
    assert places[0].lon == pytest.approx(73.68)


def test_single_bare_number_error_hints_zoom_or_coordinate():
    places, errors = parse_places("China,6.8")
    assert places == []
    assert "use z=" in errors[0]
    assert "N/E" in errors[0]


def test_hemisphere_sign_applied_to_absolute_value():
    places, errors = parse_places('Windhoek,"-24.58 S, -73.68 W"')
    assert errors == []
    assert places[0].lat == pytest.approx(-24.58)
    assert places[0].lon == pytest.approx(-73.68)


def test_header_form_bad_lat_lon_reports_error_not_crash():
    places, errors = parse_places("name,lat,lon\nBadRow,notalat,103.8\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "bad lat/lon" in errors[0]


def test_header_form_line_numbers_skip_blank_lines():
    places, errors = parse_places("name,lat,lon\n\nSingapore,1.3521,103.8198\n")
    assert errors == []
    assert places[0].line == 3


def test_header_form_leading_blank_line_before_header():
    places, errors = parse_places("\nname,lat,lon\nSingapore,1.3521,103.8198\n")
    assert errors == []
    assert places[0].name == "Singapore"
    assert places[0].line == 3


def test_header_form_place_column_without_name_falls_back():
    places, errors = parse_places("name,place\n,China\n")
    assert errors == []
    assert places[0].name == ""
    assert places[0].query == "China"
    assert places[0].full_query is True


def test_header_form_bad_zoom_reports_error_not_crash():
    places, errors = parse_places("name,zoom\nParis,notazoom\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "bad zoom" in errors[0]


def test_header_form_unknown_kind_reports_error_not_crash():
    places, errors = parse_places("name,kind\nParis,spaceport\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "unknown kind" in errors[0]


def test_header_form_canonicalizes_kind():
    places, errors = parse_places("name,kind\nParis,landmark\n")
    assert errors == []
    assert places[0].kind == "landmark"


def test_headerless_leftover_words_are_marked_as_qualifiers_not_full_query():
    places, errors = parse_places("Paris,France")
    assert errors == []
    assert places[0].query == "France"
    assert places[0].full_query is False


def test_single_column_name_header_requires_more_lines():
    places, errors = parse_places("name\nParis\nLondon\n")
    assert errors == []
    assert [p.name for p in places] == ["Paris", "London"]


def test_single_column_name_alone_is_headerless():
    places, errors = parse_places("name")
    assert errors == []
    assert places[0].name == "name"


def test_single_word_place_alone_is_headerless():
    places, errors = parse_places("China")
    assert errors == []
    assert places[0].name == "China"


def test_unspaced_field_after_url_is_peeled_off_not_swallowed():
    text = 'City Harvest Church Kikuyo,https://maps.google.com/?q=1.35,103.8,24.58 N,73.68 E'
    places, errors = parse_places(text)
    assert errors == []
    place = places[0]
    assert place.url == "https://maps.google.com/?q=1.35,103.8"
    assert place.lat == pytest.approx(24.58, abs=1e-6)
    assert place.lon == pytest.approx(73.68, abs=1e-6)


def test_spaced_field_after_url_already_stays_separate():
    text = 'City Harvest Church Kikuyo,https://maps.google.com/?q=1.35,103.8, 24.58 N,73.68 E'
    places, errors = parse_places(text)
    assert errors == []
    place = places[0]
    assert place.url == "https://maps.google.com/?q=1.35,103.8"
    assert place.lat == pytest.approx(24.58, abs=1e-6)
    assert place.lon == pytest.approx(73.68, abs=1e-6)


def test_place_only_header_row_with_extra_comma_is_joined_not_a_crash():
    places, errors = parse_places("place\nParis, France\n")
    assert errors == []
    assert places[0].query == "Paris, France"
    assert places[0].full_query is True


def test_multi_column_header_row_with_extra_columns_is_an_error_not_a_crash():
    places, errors = parse_places("name,lat,lon\nX,1,2,3\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "too many columns" in errors[0]


def test_header_form_zoom_out_of_range_reports_error():
    places, errors = parse_places("name,zoom\nParis,25\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "zoom out of range" in errors[0]


def test_header_form_negative_zoom_out_of_range_reports_error():
    places, errors = parse_places("name,zoom\nParis,-1\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "zoom out of range" in errors[0]


def test_header_form_lat_without_lon_reports_error():
    places, errors = parse_places("name,lat,lon\nX,1\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "lat without lon" in errors[0]


def test_header_form_lon_without_lat_reports_error():
    places, errors = parse_places("name,lat,lon\nX,,2\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "lon without lat" in errors[0]


@pytest.mark.parametrize("bad_lon", ["inf", "-inf", "1e400"])
def test_header_form_non_finite_lon_reports_bad_lat_lon_not_hang(bad_lon):
    places, errors = parse_places(f"name,lat,lon\nX,1,{bad_lon}\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "bad lat/lon" in errors[0]


def test_header_form_nan_lon_reports_bad_lat_lon():
    places, errors = parse_places("name,lat,lon\nX,1,nan\n")
    assert places == []
    assert "Line 2" in errors[0]
    assert "bad lat/lon" in errors[0]


def test_header_form_non_finite_lon_does_not_hang():
    import signal

    def _timeout(_signum, _frame):
        raise TimeoutError("clamp_lon hung on non-finite input")

    old_handler = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(2)
    try:
        places, errors = parse_places("name,lat,lon\nX,1,inf\n")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    assert places == []
    assert "bad lat/lon" in errors[0]


def test_headerless_non_finite_lat_hemisphere_reports_error_not_hang():
    places, errors = parse_places("Paris, inf N, 3 E")
    assert places == []
    assert "Line 1" in errors[0]


def test_headerless_bad_zoom_out_of_range_reports_error():
    places, errors = parse_places("Paris,z=500")
    assert places == []
    assert "Line 1" in errors[0]
    assert "zoom out of range" in errors[0]


def test_duplicate_header_column_reports_error():
    places, errors = parse_places("name,lat,lon,name\nX,1,2,dup\n")
    assert places == []
    assert "Line 1" in errors[0]
    assert "duplicate column" in errors[0]
    assert "'name'" in errors[0]


def test_field_over_size_limit_reports_unreadable_row_not_crash():
    huge = "a" * 200_000
    places, errors = parse_places(f"Paris\n{huge},1,2\n")
    assert places == [Place(line=1, name="Paris")]
    assert "Line 2" in errors[0]
    assert "unreadable row" in errors[0]


def test_header_form_oversized_field_reports_unreadable_row_not_crash():
    huge = "a" * 200_000
    places, errors = parse_places(f"name,lat,lon\nOK,1,2\n{huge},3,4\n")
    assert places == [Place(line=2, name="OK", lat=1.0, lon=2.0)]
    assert any("unreadable row" in e for e in errors)


def test_headerless_multiline_quoted_name_is_one_place():
    text = '"Foo\nBar",1,2\nSingapore\n'
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["Foo\nBar", "Singapore"]
    assert places[0].line == 1
    assert places[0].lat == pytest.approx(1.0)
    assert places[0].lon == pytest.approx(2.0)
    assert places[1].line == 3


def test_url_peeling_is_fast_for_adversarial_input():
    import time

    text = "Landmark,https://maps.google.com/?q=1.35,103.8" + ",landmark" * 25_000
    assert len(text) > 200_000
    start = time.perf_counter()
    parse_places(text)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0


def test_stray_unterminated_quote_reports_error_and_resumes_parsing():
    text = 'Paris\n"London\nRome\nTokyo'
    places, errors = parse_places(text)
    assert [p.name for p in places] == ["Paris", "Rome", "Tokyo"]
    assert len(errors) == 1
    assert "Line 2" in errors[0]
    assert "unterminated quote" in errors[0]


def test_legitimate_two_line_quoted_name_still_works():
    text = '"Foo\nBar",1,2\nSingapore\n'
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["Foo\nBar", "Singapore"]


def test_multiline_record_bound_at_four_lines_reports_unterminated_and_resumes_per_line():
    # Past the 4-line bound the record is reported as unterminated, and
    # parsing resumes per remaining physical line (the resume-per-line
    # policy), so lines B/C/D/E are ingested individually as bogus places
    # rather than being swallowed as part of the failed record.
    text = '"A\nB\nC\nD\nE",1,2\nSingapore\n'
    places, errors = parse_places(text)
    assert "Line 1" in errors[0]
    assert "unterminated quote" in errors[0]
    assert [p.name for p in places] == ["B", "C", "D", 'E"', "Singapore"]


def test_blank_line_inside_quoted_multiline_name_is_preserved():
    text = '"Foo\n\nBar",1,2\nSingapore\n'
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["Foo\n\nBar", "Singapore"]


def test_url_peel_bound_reports_error_when_peelable_fields_remain():
    fields = ",".join(["z=1"] * 9)
    text = f"Landmark,https://maps.google.com/?q=1.35,103.8,{fields}"
    places, errors = parse_places(text)
    assert places == []
    assert len(errors) == 1
    assert "Line 1" in errors[0]
    assert "too many fields after URL" in errors[0]


def test_url_inside_quoted_name_is_not_mangled():
    text = '"Visit https://example.com/place, it is nice",1,2\n'
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].name == "Visit https://example.com/place, it is nice"
    assert places[0].url is None


def test_header_form_multiline_record_reports_starting_line():
    text = 'name,lat,lon\n"Foo\nBar",1,2\n'
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].line == 2


def test_header_form_multiline_record_is_bounded_and_resumes():
    text = 'name,lat,lon\nParis,1,2\n"London\nRome,3,4\nTokyo,5,6\n'
    places, errors = parse_places(text)
    assert [p.name for p in places] == ["Paris", "Rome", "Tokyo"]
    assert places[1].lat == pytest.approx(3.0)
    assert places[1].lon == pytest.approx(4.0)
    assert places[2].lat == pytest.approx(5.0)
    assert places[2].lon == pytest.approx(6.0)
    assert len(errors) == 1
    assert "Line 3" in errors[0]
    assert "unreadable row" in errors[0]
    assert "unterminated quote" in errors[0]


def test_header_form_multiline_start_line_sums_embedded_newlines():
    text = 'name,url,lat,lon\n"Foo\nBar","http://x\nyz",1,2\nSingapore,,3,4\n'
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].name == "Foo\nBar"
    assert places[0].line == 2
    assert places[1].name == "Singapore"
    assert places[1].line == 5


def test_nul_byte_in_field_parses_without_error():
    text = "Paris\x00,1,2\n"
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].name == "Paris\x00"


def test_headerless_stray_quote_mid_name_is_literal():
    text = 'Paris,1,2\nO"Brien,1,2'
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["Paris", 'O"Brien']


def test_header_form_stray_quote_mid_name_is_literal():
    text = 'name,lat,lon\nParis,1,2\nO"Brien,1,2'
    places, errors = parse_places(text)
    assert errors == []
    assert [p.name for p in places] == ["Paris", 'O"Brien']
    assert [p.line for p in places] == [2, 3]


def test_header_form_five_line_quoted_record_is_bounded_and_resumes():
    # The quoted field spans 5 physical lines (A..E), past the 4-line
    # bound, so it is reported as unterminated at its starting line and
    # parsing resumes per remaining physical line.
    text = 'name,lat,lon\n"A\nB\nC\nD\nE",1,2\nSingapore,3,4\n'
    places, errors = parse_places(text)
    assert len(errors) == 1
    assert "Line 2" in errors[0]
    assert "unterminated quote" in errors[0]
    assert [p.name for p in places] == ["B", "C", "D", 'E"', "Singapore"]
    assert [p.line for p in places] == [3, 4, 5, 6, 7]


def test_header_form_four_line_quoted_record_is_accepted():
    text = 'name,lat,lon\n"A\nB\nC\nD",1,2\n'
    places, errors = parse_places(text)
    assert errors == []
    assert places[0].name == "A\nB\nC\nD"
    assert places[0].line == 2
