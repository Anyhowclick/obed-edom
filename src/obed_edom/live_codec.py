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


def _ebml_uint(f: BinaryIO, start: int, end: int) -> int | None:
    raw = _read_at(f, start, end, 0, end - start)
    if raw is None or not 1 <= len(raw) <= 8:
        return None
    return int.from_bytes(raw, "big")


def _ebml_text(f: BinaryIO, start: int, end: int) -> str | None:
    if end - start > 64:
        return None
    raw = _read_at(f, start, end, 0, end - start)
    if raw is None:
        return None
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None


def _webm_info_element(
    f: BinaryIO, start: int, end: int, budget: list[int]
) -> float | None:
    duration = None
    scale = 1_000_000
    pos = start
    while pos < end:
        header = _read_ebml_header(f, pos, end, budget)
        if header is None or header[2] is None or header[2] > end:
            return None
        element_id, payload_start, element_end = header
        if element_id == _TIMECODE_SCALE:
            value = _ebml_uint(f, payload_start, element_end)
            if not value:
                return None
            scale = value
        elif element_id == _DURATION:
            raw = _read_at(f, payload_start, element_end, 0, element_end - payload_start)
            if raw is None or len(raw) not in (4, 8):
                return None
            value = struct.unpack(">f" if len(raw) == 4 else ">d", raw)[0]
            if not math.isfinite(value) or value <= 0:
                return None
            duration = value
        pos = element_end
    if duration is None:
        return None
    return duration * scale / 1_000_000_000


def _webm_video_element(f: BinaryIO, start: int, end: int, budget: list[int]) -> tuple[int, int, bool] | None:
    width = height = None
    alpha = False
    pos = start
    while pos < end:
        header = _read_ebml_header(f, pos, end, budget)
        if header is None or header[2] is None or header[2] > end:
            return None
        element_id, payload_start, element_end = header
        if element_id in (_PIXEL_WIDTH, _PIXEL_HEIGHT, _ALPHA_MODE):
            value = _ebml_uint(f, payload_start, element_end)
            if value is None:
                return None
            if element_id == _PIXEL_WIDTH:
                width = value
            elif element_id == _PIXEL_HEIGHT:
                height = value
            elif value in (0, 1):
                alpha = value == 1
            else:
                return None
        pos = element_end
    if not width or not height:
        return None
    return width, height, alpha


def _webm_track_entry(
    f: BinaryIO, start: int, end: int, budget: list[int]
) -> tuple[int | None, str | None, int | None, tuple[int, int, bool] | None] | None:
    track_type = None
    codec = None
    default_duration = None
    video = None
    pos = start
    while pos < end:
        header = _read_ebml_header(f, pos, end, budget)
        if header is None or header[2] is None or header[2] > end:
            return None
        element_id, payload_start, element_end = header
        if element_id == _TRACK_TYPE:
            track_type = _ebml_uint(f, payload_start, element_end)
        elif element_id == _CODEC_ID:
            codec = _ebml_text(f, payload_start, element_end)
        elif element_id == _DEFAULT_DURATION:
            default_duration = _ebml_uint(f, payload_start, element_end)
            if not default_duration:
                return None
        elif element_id == _VIDEO:
            video = _webm_video_element(f, payload_start, element_end, budget)
            if video is None:
                return None
        pos = element_end
    return track_type, codec, default_duration, video


def _webm_tracks_element(
    f: BinaryIO, start: int, end: int, budget: list[int]
) -> tuple[str, int, int, int | None, bool] | None:
    videos = []
    pos = start
    while pos < end:
        header = _read_ebml_header(f, pos, end, budget)
        if header is None or header[2] is None or header[2] > end:
            return None
        element_id, payload_start, element_end = header
        if element_id == _TRACK_ENTRY:
            entry = _webm_track_entry(f, payload_start, element_end, budget)
            if entry is None:
                return None
            if entry[0] == 1:
                videos.append(entry)
        pos = element_end
    if len(videos) != 1:
        return None
    _track_type, codec, default_duration, video = videos[0]
    if codec != "V_VP9" or video is None:
        return None
    return codec, video[0], video[1], default_duration, video[2]


@dataclass(frozen=True)
class WebMInfo:
    codec: str
    width: int
    height: int
    duration_s: float
    fps: float | None
    alpha: bool


def webm_info(path: Path) -> WebMInfo | None:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            budget = [_MAX_EBML_ELEMENTS]
            ebml = _read_ebml_header(f, 0, size, budget)
            if ebml is None or ebml[0] != _EBML or ebml[2] is None or ebml[2] > size:
                return None
            doc_type = None
            pos = ebml[1]
            while pos < ebml[2]:
                header = _read_ebml_header(f, pos, ebml[2], budget)
                if header is None or header[2] is None or header[2] > ebml[2]:
                    return None
                if header[0] == _DOCTYPE:
                    doc_type = _ebml_text(f, header[1], header[2])
                pos = header[2]
            if doc_type != "webm":
                return None
            segment = _read_ebml_header(f, ebml[2], size, budget)
            if segment is None or segment[0] != _SEGMENT:
                return None
            segment_end = size if segment[2] is None else segment[2]
            if segment_end > size:
                return None
            info = tracks = None
            pos = segment[1]
            while pos < segment_end:
                header = _read_ebml_header(f, pos, segment_end, budget)
                if header is None:
                    return None
                if header[0] == _CLUSTER:
                    break
                if header[2] is None or header[2] > segment_end:
                    return None
                if header[0] == _INFO:
                    info = _webm_info_element(f, header[1], header[2], budget)
                    if info is None:
                        return None
                elif header[0] == _TRACKS:
                    tracks = _webm_tracks_element(f, header[1], header[2], budget)
                    if tracks is None:
                        return None
                pos = header[2]
            if info is None or tracks is None:
                return None
            codec, width, height, default_duration, alpha = tracks
            fps = 1_000_000_000 / default_duration if default_duration else None
            return WebMInfo(codec, width, height, info, fps, alpha)
    except OSError:
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


def _has_webm_header(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == _EBML.to_bytes(4, "big")
    except OSError:
        return False


def movie_codec(path: Path) -> str | None:
    """First video codec (`avc1`, `hvc1`, `V_VP9`), or `None` when unreadable."""
    if _has_webm_header(path):
        info = webm_info(path)
        return info.codec if info is not None else None
    return _probe_video_trak(path, lambda _f, video, _budget: video[0])


def movie_fps(path: Path) -> float | None:
    """Frame rate from BMFF timing or WebM `DefaultDuration`, when readable."""
    if _has_webm_header(path):
        info = webm_info(path)
        return info.fps if info is not None else None
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
