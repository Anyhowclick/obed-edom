"""Detect a movie file's video codec from its ISO-BMFF/QuickTime box tree.

No ffprobe (not installed) and no third-party dependency: this reads only box
headers, seeking past `mdat` payloads rather than loading them, and returns
`None` on anything it cannot parse instead of raising.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

_HEADER_SIZE = 8
_EXTENDED_HEADER_SIZE = 16
_MAX_BOXES = 20_000

_H264_FOURCCS = frozenset({"avc1", "avc3"})
_HEVC_FOURCCS = frozenset({"hvc1", "hev1"})
_PRORES_FOURCCS = frozenset({"apch", "apcn", "apcs", "apco", "ap4h", "ap4x"})
_AV1_FOURCCS = frozenset({"av01"})
_VP9_FOURCCS = frozenset({"vp09"})


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


def _video_fourcc_in_trak(f: BinaryIO, start: int, end: int, budget: list[int]) -> str | None:
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
    return _first_sample_fourcc(f, *stsd)


def movie_codec(path: Path) -> str | None:
    """First video sample entry's fourcc (e.g. `avc1`, `hvc1`), or `None` when the
    file is unreadable or has no video track. Never raises."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            budget = [_MAX_BOXES]
            moov = _find_box(f, b"moov", 0, size, budget)
            if moov is None:
                return None
            for trak_start, trak_end in _each_box(f, b"trak", *moov, budget):
                fourcc = _video_fourcc_in_trak(f, trak_start, trak_end, budget)
                if fourcc is not None:
                    return fourcc
    except OSError:
        return None
    return None


def codec_family(fourcc: str | None) -> str:
    """`av1`/`vp9` are kept as their own conservative families rather than folded
    into `other`: Chrome's decode support for them is not verified in this host,
    so they must fail closed exactly like any other unproven codec."""
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
