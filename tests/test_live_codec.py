from __future__ import annotations

from pathlib import Path

import pytest

from obed_edom.live_codec import codec_family, movie_codec

# --- synthetic ISO-BMFF/QuickTime box builders --------------------------------------------


def box(fourcc: bytes, payload: bytes = b"") -> bytes:
    """A standard 32-bit-size box: size(4) type(4) payload."""
    return (8 + len(payload)).to_bytes(4, "big") + fourcc + payload


def box64(fourcc: bytes, payload: bytes) -> bytes:
    """A box using the 64-bit extended-size form: size==1, type(4), largesize(8), payload."""
    size = 16 + len(payload)
    return (1).to_bytes(4, "big") + fourcc + size.to_bytes(8, "big") + payload


def box_size0(fourcc: bytes, payload: bytes = b"") -> bytes:
    """A box declaring size==0 ("extends to end of file"); only valid as the last box."""
    return (0).to_bytes(4, "big") + fourcc + payload


def hdlr(subtype: bytes) -> bytes:
    payload = b"\x00" * 4 + b"\x00" * 4 + subtype + b"\x00" * 12 + b"Handler\x00"
    return box(b"hdlr", payload)


def sample_entry(fourcc: bytes) -> bytes:
    return box(fourcc, b"\x00" * 78)


def stsd_payload(entry: bytes, *, entry_count: int = 1) -> bytes:
    """`stsd` payload: version+flags(4) entry_count(4) then the sample entry boxes."""
    return b"\x00" * 4 + entry_count.to_bytes(4, "big") + entry


def stsd(fourcc: bytes) -> bytes:
    return box(b"stsd", stsd_payload(sample_entry(fourcc)))


def stbl(fourcc: bytes) -> bytes:
    return box(b"stbl", stsd(fourcc))


def minf(fourcc: bytes) -> bytes:
    return box(b"minf", stbl(fourcc))


def mdia(subtype: bytes, fourcc: bytes | None) -> bytes:
    body = hdlr(subtype)
    if fourcc is not None:
        body += minf(fourcc)
    return box(b"mdia", body)


def trak(subtype: bytes, fourcc: bytes | None) -> bytes:
    return box(b"trak", mdia(subtype, fourcc))


def ftyp() -> bytes:
    return box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2avc1mp41")


def movie_with_video(fourcc: bytes, *, extra_traks: bytes = b"") -> bytes:
    moov = box(b"moov", trak(b"vide", fourcc) + extra_traks)
    return ftyp() + moov


def movie_audio_only() -> bytes:
    moov = box(b"moov", trak(b"soun", None))
    return ftyp() + moov


def movie_with_stsd_payload(payload: bytes) -> bytes:
    """A video trak whose `stsd` payload is written verbatim, for malformed-entry cases."""
    mdia_body = hdlr(b"vide") + box(b"minf", box(b"stbl", box(b"stsd", payload)))
    return ftyp() + box(b"moov", box(b"trak", box(b"mdia", mdia_body)))


# --- movie_codec ----------------------------------------------------------------------------


@pytest.mark.parametrize("fourcc", [b"avc1", b"hvc1", b"hev1", b"apch", b"apcn"])
def test_reports_the_first_video_sample_entry_fourcc(tmp_path, fourcc):
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_video(fourcc))
    assert movie_codec(path) == fourcc.decode()


def test_audio_only_track_has_no_codec(tmp_path):
    path = tmp_path / "audio.mov"
    path.write_bytes(movie_audio_only())
    assert movie_codec(path) is None


def test_second_trak_is_used_when_first_is_audio(tmp_path):
    path = tmp_path / "movie.mov"
    audio_trak = trak(b"soun", None)
    path.write_bytes(ftyp() + box(b"moov", audio_trak + trak(b"vide", b"avc1")))
    assert movie_codec(path) == "avc1"


def test_moov_after_mdat_is_found_by_seeking_past_the_payload(tmp_path):
    mdat_payload = b"\x00" * 10_000
    mdat = box(b"mdat", mdat_payload)
    moov = box(b"moov", trak(b"vide", b"hvc1"))
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + mdat + moov)
    assert movie_codec(path) == "hvc1"


def test_64_bit_box_size_is_handled(tmp_path):
    moov_payload = trak(b"vide", b"avc1")
    moov = box64(b"moov", moov_payload)
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + moov)
    assert movie_codec(path) == "avc1"


def test_size_zero_box_extends_to_end_of_file(tmp_path):
    moov = box_size0(b"moov", trak(b"vide", b"avc1"))
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + moov)
    assert movie_codec(path) == "avc1"


def test_truncated_file_returns_none(tmp_path):
    data = ftyp() + box(b"moov", trak(b"vide", b"avc1"))
    path = tmp_path / "movie.mov"
    path.write_bytes(data[: len(data) - 20])
    assert movie_codec(path) is None


def test_garbage_bytes_return_none(tmp_path):
    path = tmp_path / "movie.mov"
    path.write_bytes(b"\xffnot a real movie file at all, just garbage\x00\x01\x02" * 20)
    assert movie_codec(path) is None


def test_box_declaring_a_size_larger_than_the_file_returns_none(tmp_path):
    bogus = (0xFFFFFFF).to_bytes(4, "big") + b"moov" + b"\x00" * 16
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + bogus)
    assert movie_codec(path) is None


def test_missing_file_returns_none(tmp_path):
    assert movie_codec(tmp_path / "does-not-exist.mov") is None


def test_empty_file_returns_none(tmp_path):
    path = tmp_path / "movie.mov"
    path.write_bytes(b"")
    assert movie_codec(path) is None


def test_box_walk_is_bounded_and_terminates_quickly(tmp_path):
    # Many tiny sibling boxes before a moov that would otherwise be found: the walk
    # must give up within its box budget rather than scanning unboundedly.
    junk = box(b"skip", b"") * 50_000
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + junk + box(b"moov", trak(b"vide", b"avc1")))
    import time

    started = time.monotonic()
    result = movie_codec(path)
    assert time.monotonic() - started < 5
    assert result is None


def test_no_moov_box_returns_none(tmp_path):
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + box(b"free", b"\x00" * 16))
    assert movie_codec(path) is None


def test_zero_size_box_that_is_not_last_is_treated_as_extending_to_eof(tmp_path):
    # A size==0 box is only valid as the file's last box; anything encoded after it
    # is unreachable, so the following moov (if any) must not be found.
    trailing_moov = box(b"moov", trak(b"vide", b"avc1"))
    path = tmp_path / "movie.mov"
    path.write_bytes(ftyp() + box_size0(b"free") + trailing_moov)
    assert movie_codec(path) is None


# --- malformed stsd -------------------------------------------------------------------------


def test_stsd_declaring_zero_entries_returns_none(tmp_path):
    # The trailing bytes still spell a well-formed `avc1` sample entry: a zero entry count
    # must not let them be read as the track's codec.
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_stsd_payload(stsd_payload(sample_entry(b"avc1"), entry_count=0)))
    assert movie_codec(path) is None


def test_sample_entry_larger_than_the_stsd_box_returns_none(tmp_path):
    oversized = (400).to_bytes(4, "big") + b"avc1" + b"\x00" * 78
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_stsd_payload(stsd_payload(oversized)))
    assert movie_codec(path) is None


def test_sample_entry_smaller_than_a_box_header_returns_none(tmp_path):
    undersized = (4).to_bytes(4, "big") + b"avc1" + b"\x00" * 78
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_stsd_payload(stsd_payload(undersized)))
    assert movie_codec(path) is None


def test_sample_entry_with_a_non_printable_fourcc_returns_none(tmp_path):
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_stsd_payload(stsd_payload(sample_entry(b"\x00\x01\x02\xff"))))
    assert movie_codec(path) is None


def test_stsd_too_short_to_hold_an_entry_returns_none(tmp_path):
    path = tmp_path / "movie.mov"
    path.write_bytes(movie_with_stsd_payload(b"\x00" * 4 + (1).to_bytes(4, "big")))
    assert movie_codec(path) is None


# --- codec_family -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fourcc,family",
    [
        ("avc1", "h264"),
        ("avc3", "h264"),
        ("hvc1", "hevc"),
        ("hev1", "hevc"),
        ("apch", "prores"),
        ("apcn", "prores"),
        ("apcs", "prores"),
        ("apco", "prores"),
        ("ap4h", "prores"),
        ("ap4x", "prores"),
        ("av01", "av1"),
        ("vp09", "vp9"),
        # vp08 is VP8, not VP9: it is unsupported either way, but must not be mislabelled.
        ("vp08", "other"),
        ("mp4v", "other"),
        (None, "other"),
    ],
)
def test_codec_family_mapping(fourcc, family):
    assert codec_family(fourcc) == family
