"""Detect a movie file's video codec from its BMFF or WebM metadata.

No ffprobe or third-party dependency: this reads only container metadata,
seeking past media payloads, and returns `None` on anything it cannot parse.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, TypeVar

_T = TypeVar("_T")
_Span = tuple[int, int]
_VideoTrak = tuple[str, _Span, _Span, _Span, _Span]

_HEADER_SIZE = 8
_EXTENDED_HEADER_SIZE = 16
_MAX_BOXES = 20_000
_MAX_EBML_ELEMENTS = 20_000

_H264_FOURCCS = frozenset({"avc1", "avc3"})
_HEVC_FOURCCS = frozenset({"hvc1", "hev1"})
_PRORES_FOURCCS = frozenset({"apch", "apcn", "apcs", "apco", "ap4h", "ap4x"})
_AV1_FOURCCS = frozenset({"av01"})
_VP9_FOURCCS = frozenset({"vp09", "V_VP9"})

_EBML = 0x1A45DFA3
_DOCTYPE = 0x4282
_SEGMENT = 0x18538067
_INFO = 0x1549A966
_TIMECODE_SCALE = 0x2AD7B1
_DURATION = 0x4489
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_TRACK_TYPE = 0x83
_CODEC_ID = 0x86
_DEFAULT_DURATION = 0x23E383
_VIDEO = 0xE0
_PIXEL_WIDTH = 0xB0
_PIXEL_HEIGHT = 0xBA
_ALPHA_MODE = 0x53C0
_CLUSTER = 0x1F43B675
_EBML_MASTERS = frozenset({_EBML, _SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO})
_EBML_LEAVES = frozenset({
    _DOCTYPE, _TIMECODE_SCALE, _DURATION, _TRACK_TYPE, _CODEC_ID,
    _DEFAULT_DURATION, _PIXEL_WIDTH, _PIXEL_HEIGHT, _ALPHA_MODE,
})


def _read_box_header(f: BinaryIO, start: int, end: int) -> tuple[bytes, int, int] | None:
    if start + _HEADER_SIZE > end:
        return None
    f.seek(start)
    header = f.read(_HEADER_SIZE)
    if len(header) != _HEADER_SIZE:
        return None
    size = int.from_bytes(header[:4], "big")
    box_type = header[4:8]
    payload_start = start + _HEADER_SIZE
    if size == 1:
        if start + _EXTENDED_HEADER_SIZE > end:
            return None
        extended = f.read(8)
        if len(extended) != 8:
            return None
        size = int.from_bytes(extended, "big")
        payload_start = start + _EXTENDED_HEADER_SIZE
        if size < _EXTENDED_HEADER_SIZE:
            return None
    elif size == 0:
        size = end - start
    elif size < _HEADER_SIZE:
        return None
    box_end = start + size
    if box_end > end or box_end <= start:
        return None
    return box_type, payload_start, box_end


def _find_box(f: BinaryIO, box_type: bytes, start: int, end: int, budget: list[int]) -> tuple[int, int] | None:
    pos = start
    while pos < end:
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        header = _read_box_header(f, pos, end)
        if header is None:
            return None
        candidate_type, payload_start, box_end = header
        if candidate_type == box_type:
            return payload_start, box_end
        pos = box_end
    return None


def _each_box(f: BinaryIO, box_type: bytes, start: int, end: int, budget: list[int]):
    pos = start
    while pos < end:
        if budget[0] <= 0:
            return
        budget[0] -= 1
        header = _read_box_header(f, pos, end)
        if header is None:
            return
        candidate_type, payload_start, box_end = header
        if candidate_type == box_type:
            yield payload_start, box_end
        pos = box_end


def _hdlr_is_video(f: BinaryIO, start: int, end: int) -> bool:
    """`hdlr` payload: version+flags(4) pre_defined(4) handler_type(4) ..., so the
    subtype sits 8 bytes into the payload, not straight after the box header."""
    if end - start < 12:
        return False
    f.seek(start + 8)
    handler = f.read(4)
    return handler == b"vide"


def _first_sample_fourcc(f: BinaryIO, start: int, end: int) -> str | None:
    """`stsd` payload: version+flags(4) entry_count(4) then the sample entries, each a
    box of its own -- so the first entry's fourcc counts only when the count is at least
    one and the entry's declared box fits inside the `stsd` payload."""
    if end - start < 16:
        return None
    f.seek(start + 4)
    head = f.read(12)
    if len(head) != 12 or int.from_bytes(head[:4], "big") < 1:
        return None
    entry_size = int.from_bytes(head[4:8], "big")
    if entry_size < _HEADER_SIZE or start + 8 + entry_size > end:
        return None
    fourcc = head[8:12]
    if not all(32 <= byte < 127 for byte in fourcc):
        return None
    return fourcc.decode("ascii").lower()


def _video_trak(f: BinaryIO, start: int, end: int, budget: list[int], moov: _Span) -> _VideoTrak | None:
    mdia = _find_box(f, b"mdia", start, end, budget)
    if mdia is None:
        return None
    hdlr = _find_box(f, b"hdlr", *mdia, budget)
    if hdlr is None or not _hdlr_is_video(f, *hdlr):
        return None
    minf = _find_box(f, b"minf", *mdia, budget)
    if minf is None:
        return None
    stbl = _find_box(f, b"stbl", *minf, budget)
    if stbl is None:
        return None
    stsd = _find_box(f, b"stsd", *stbl, budget)
    if stsd is None:
        return None
    fourcc = _first_sample_fourcc(f, *stsd)
    if fourcc is None:
        return None
    return fourcc, mdia, stbl, (start, end), moov


def _mdhd_timescale(f: BinaryIO, start: int, end: int) -> int | None:
    """`mdhd` payload: version+flags(4), then creation and modification times (4 bytes each
    in version 0, 8 in version 1) before the timescale."""
    if end - start < 4:
        return None
    f.seek(start)
    version = f.read(1)
    if len(version) != 1 or version[0] not in (0, 1):
        return None
    offset = 4 + (16 if version[0] == 1 else 8)
    if end - start < offset + 4:
        return None
    f.seek(start + offset)
    raw = f.read(4)
    if len(raw) != 4:
        return None
    return int.from_bytes(raw, "big")


def _stts_totals(f: BinaryIO, start: int, end: int) -> tuple[int, int] | None:
    """`stts` payload: version+flags(4) entry_count(4) then (sample_count, sample_delta)
    pairs; returns the total samples and the total duration in media timescale units."""
    if end - start < 8:
        return None
    f.seek(start + 4)
    raw = f.read(4)
    if len(raw) != 4:
        return None
    count = int.from_bytes(raw, "big")
    if end - start < 8 + count * 8:
        return None
    table = f.read(count * 8)
    if len(table) != count * 8:
        return None
    samples = duration = 0
    for i in range(0, len(table), 8):
        sample_count = int.from_bytes(table[i : i + 4], "big")
        samples += sample_count
        duration += sample_count * int.from_bytes(table[i + 4 : i + 8], "big")
    return samples, duration


def _trak_fps(f: BinaryIO, mdia: tuple[int, int], stbl: tuple[int, int], budget: list[int]) -> float | None:
    mdhd = _find_box(f, b"mdhd", *mdia, budget)
    stts = _find_box(f, b"stts", *stbl, budget)
    if mdhd is None or stts is None:
        return None
    timescale = _mdhd_timescale(f, *mdhd)
    totals = _stts_totals(f, *stts)
    if not timescale or totals is None or not totals[0] or not totals[1]:
        return None
    samples, duration = totals
    return samples * timescale / duration


def _read_at(f: BinaryIO, start: int, end: int, offset: int, length: int) -> bytes | None:
    if offset < 0 or start + offset + length > end:
        return None
    f.seek(start + offset)
    raw = f.read(length)
    return raw if len(raw) == length else None


def _read_ebml_vint(f: BinaryIO, pos: int, end: int, *, identifier: bool) -> tuple[int, int, bool] | None:
    if pos >= end:
        return None
    f.seek(pos)
    first_raw = f.read(1)
    if len(first_raw) != 1 or first_raw[0] == 0:
        return None
    first = first_raw[0]
    length = 1
    mask = 0x80
    while not first & mask:
        length += 1
        mask >>= 1
    limit = 4 if identifier else 8
    if length > limit or pos + length > end:
        return None
    rest = f.read(length - 1)
    if len(rest) != length - 1:
        return None
    value = int.from_bytes(first_raw + rest, "big")
    if identifier:
        return value, length, False
    value &= (1 << (7 * length)) - 1
    return value, length, value == (1 << (7 * length)) - 1


def _read_ebml_header(
    f: BinaryIO, pos: int, end: int, budget: list[int]
) -> tuple[int, int, int | None] | None:
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    element_id = _read_ebml_vint(f, pos, end, identifier=True)
    if element_id is None:
        return None
    size = _read_ebml_vint(f, pos + element_id[1], end, identifier=False)
    if size is None:
        return None
    payload_start = pos + element_id[1] + size[1]
    return element_id[0], payload_start, None if size[2] else payload_start + size[0]


def _walk_ebml(
    f: BinaryIO, start: int, end: int, budget: list[int], values: dict[int, bytes]
) -> bool | None:
    pos = start
    while pos < end:
        header = _read_ebml_header(f, pos, end, budget)
        if header is None:
            return None
        element_id, payload_start, element_end = header
        if element_end is None:
            if element_id != _SEGMENT:
                return None
            element_end = end
        if element_end > end:
            return None
        if element_id == _CLUSTER:
            return True
        if element_id in _EBML_MASTERS:
            stopped = _walk_ebml(f, payload_start, element_end, budget, values)
            if stopped is None or stopped:
                return stopped
        elif element_id in _EBML_LEAVES:
            size = element_end - payload_start
            if element_id in values or size > 64:
                return None
            f.seek(payload_start)
            raw = f.read(size)
            if len(raw) != size:
                return None
            values[element_id] = raw
        pos = element_end
    return False


@dataclass(frozen=True)
class WebMInfo:
    width: int
    height: int
    duration_s: float
    fps: float | None
    alpha: bool


def webm_info(path: Path) -> WebMInfo | None:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            values: dict[int, bytes] = {}
            if _walk_ebml(f, 0, size, [_MAX_EBML_ELEMENTS], values) is None:
                return None
            required = {_DOCTYPE, _DURATION, _TRACK_TYPE, _CODEC_ID, _PIXEL_WIDTH, _PIXEL_HEIGHT}
            if not required <= values.keys() or values[_DOCTYPE] != b"webm" or values[_CODEC_ID] != b"V_VP9":
                return None
            integer_ids = {
                element_id for element_id in (
                    _TIMECODE_SCALE, _TRACK_TYPE, _DEFAULT_DURATION,
                    _PIXEL_WIDTH, _PIXEL_HEIGHT, _ALPHA_MODE,
                ) if element_id in values
            }
            if any(not 1 <= len(values[element_id]) <= 8 for element_id in integer_ids):
                return None
            integers = {element_id: int.from_bytes(values[element_id], "big") for element_id in integer_ids}
            scale = integers.get(_TIMECODE_SCALE, 1_000_000)
            width, height = integers[_PIXEL_WIDTH], integers[_PIXEL_HEIGHT]
            default_duration = integers.get(_DEFAULT_DURATION)
            alpha = integers.get(_ALPHA_MODE, 0)
            raw_duration = values[_DURATION]
            if (
                integers[_TRACK_TYPE] != 1 or not scale or not width or not height
                or alpha not in (0, 1) or (default_duration is not None and not default_duration)
                or len(raw_duration) not in (4, 8)
            ):
                return None
            duration = struct.unpack(">f" if len(raw_duration) == 4 else ">d", raw_duration)[0]
            duration_s = duration * scale / 1_000_000_000
            if not math.isfinite(duration) or duration <= 0 or not math.isfinite(duration_s):
                return None
            fps = 1_000_000_000 / default_duration if default_duration else None
            return WebMInfo(width, height, duration_s, fps, alpha == 1)
    except (OSError, RecursionError):
        return None


def _header_duration(f: BinaryIO, start: int, end: int) -> int | None:
    """`mvhd`/`mdhd` duration, right after the timescale (4 bytes in version 0, 8 in version 1)."""
    version = _read_at(f, start, end, 0, 1)
    if version is None or version[0] not in (0, 1):
        return None
    size = 8 if version[0] == 1 else 4
    raw = _read_at(f, start, end, 4 + 2 * size + 4, size)
    return int.from_bytes(raw, "big") if raw is not None else None


def _elst_entries(f: BinaryIO, start: int, end: int) -> tuple[tuple[int, int, float], ...] | None:
    """`elst` payload: version+flags(4) entry_count(4), then (segment_duration, media_time,
    media_rate 16.16) per entry, with 8-byte duration and time in version 1."""
    head = _read_at(f, start, end, 0, 8)
    if head is None or head[0] not in (0, 1):
        return None
    size = 8 if head[0] == 1 else 4
    count = int.from_bytes(head[4:8], "big")
    table = _read_at(f, start, end, 8, count * (2 * size + 4))
    if table is None:
        return None
    entries = []
    for i in range(0, len(table), 2 * size + 4):
        duration = int.from_bytes(table[i : i + size], "big")
        media_time = int.from_bytes(table[i + size : i + 2 * size], "big", signed=True)
        rate = int.from_bytes(table[i + 2 * size : i + 2 * size + 4], "big", signed=True) / 65536
        entries.append((duration, media_time, rate))
    return tuple(entries)


@dataclass(frozen=True)
class MovieTiming:
    timescale: int
    samples: int
    stts_duration: int
    edits: tuple[tuple[int, int, float], ...]
    presented_s: float

    @property
    def identity_edits(self) -> bool:
        return not self.edits or (len(self.edits) == 1 and self.edits[0][1] == 0)


@dataclass(frozen=True)
class MovieGeometry:
    width: int
    height: int
    depth: int
    matrix: tuple[int, ...]


def _trak_timing(f: BinaryIO, video: _VideoTrak, budget: list[int]) -> MovieTiming | None:
    _fourcc, mdia, stbl, trak, moov = video
    mdhd = _find_box(f, b"mdhd", *mdia, budget)
    stts = _find_box(f, b"stts", *stbl, budget)
    if mdhd is None or stts is None:
        return None
    timescale = _mdhd_timescale(f, *mdhd)
    totals = _stts_totals(f, *stts)
    if not timescale or totals is None or not totals[0] or not totals[1]:
        return None
    edits: tuple[tuple[int, int, float], ...] = ()
    edts = _find_box(f, b"edts", *trak, budget)
    elst = _find_box(f, b"elst", *edts, budget) if edts is not None else None
    if elst is not None:
        read = _elst_entries(f, *elst)
        if read is None:
            return None
        edits = read
    if edits:
        mvhd = _find_box(f, b"mvhd", *moov, budget)
        movie_scale = _mdhd_timescale(f, *mvhd) if mvhd is not None else None
        if not movie_scale:
            return None
        presented = sum(entry[0] for entry in edits) / movie_scale
    else:
        duration = _header_duration(f, *mdhd)
        if not duration:
            return None
        presented = duration / timescale
    return MovieTiming(timescale, totals[0], totals[1], edits, presented)


def _trak_geometry(f: BinaryIO, video: _VideoTrak, budget: list[int]) -> MovieGeometry | None:
    """Visual sample entry: coded width/height at 24 bytes into its payload and depth at 74;
    `tkhd` matrix after the version-sized times, track id, duration and 16 fixed bytes."""
    _fourcc, _mdia, stbl, trak, _moov = video
    stsd = _find_box(f, b"stsd", *stbl, budget)
    tkhd = _find_box(f, b"tkhd", *trak, budget)
    if stsd is None or tkhd is None:
        return None
    entry = _read_at(f, *stsd, 8, 86)
    version = _read_at(f, *tkhd, 0, 1)
    if entry is None or version is None or version[0] not in (0, 1):
        return None
    raw_matrix = _read_at(f, *tkhd, (36 if version[0] == 1 else 24) + 16, 36)
    if raw_matrix is None:
        return None
    matrix = tuple(int.from_bytes(raw_matrix[i : i + 4], "big", signed=True) for i in range(0, 36, 4))
    return MovieGeometry(
        int.from_bytes(entry[32:34], "big"),
        int.from_bytes(entry[34:36], "big"),
        int.from_bytes(entry[82:84], "big"),
        matrix,
    )


def _probe_video_trak(path: Path, read: Callable[[BinaryIO, _VideoTrak, list[int]], _T]) -> _T | None:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            budget = [_MAX_BOXES]
            moov = _find_box(f, b"moov", 0, size, budget)
            if moov is None:
                return None
            for trak_start, trak_end in _each_box(f, b"trak", *moov, budget):
                video = _video_trak(f, trak_start, trak_end, budget, moov)
                if video is not None:
                    return read(f, video, budget)
    except OSError:
        return None
    return None


def movie_codec(path: Path) -> str | None:
    """First video codec (`avc1`, `hvc1`, `V_VP9`), or `None` when unreadable. Never raises."""
    if webm_info(path) is not None:
        return "V_VP9"
    return _probe_video_trak(path, lambda _f, video, _budget: video[0])


def movie_fps(path: Path) -> float | None:
    """Frame rate from BMFF timing or WebM `DefaultDuration`, when readable. Never raises."""
    info = webm_info(path)
    if info is not None:
        return info.fps
    return _probe_video_trak(path, lambda f, video, budget: _trak_fps(f, video[1], video[2], budget))


def movie_timing(path: Path) -> MovieTiming | None:
    """Video track timing: `mdhd` timescale, `stts` totals, edit list and the presented
    duration in seconds (the edit list's, else `mdhd`'s), or `None` when unreadable."""
    return _probe_video_trak(path, _trak_timing)


def movie_geometry(path: Path) -> MovieGeometry | None:
    """Video track's sample-entry coded size and depth plus its `tkhd` matrix, or `None`."""
    return _probe_video_trak(path, _trak_geometry)


def codec_family(fourcc: str | None) -> str:
    """Map BMFF fourccs and the WebM VP9 codec id to playback families."""
    if fourcc in _H264_FOURCCS:
        return "h264"
    if fourcc in _HEVC_FOURCCS:
        return "hevc"
    if fourcc in _PRORES_FOURCCS:
        return "prores"
    if fourcc in _AV1_FOURCCS:
        return "av1"
    if fourcc in _VP9_FOURCCS:
        return "vp9"
    return "other"
