"""Repair Keynote's HTML-export texture mis-mapping in the cached export copy: a leaf whose
texture id points at another object's page is re-pointed to a verified page of its own slide,
or to a page grafted from the previous slide's Magic Move, before the export is used."""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from obed_edom.html_preview import PreviewError, file_sha256, read_jsonish, rewrite_pdfp_from_pdf
from obed_edom.live_continuity import _asset_url, canonical_asset_name
from obed_edom.live_runtime import SUPPORTED_PLAYERS

TEXTURE_REPAIR_VERSION = 1
MAGIC_MOVE = "apple:magic-move-implied-motion-path"
TEXT_TYPE = 6
SIZE_TOL = 1.5
DONOR_SIZE_TOL = 0.5
RECT_TOL = 0.01
GROUP_TOL = 0.5
MEDIABOX_TOL = 0.01
CORR_HIT = 0.5
CORR_MATCH = 0.9
FLAT_STD = 2.0
OCR_AGREE = 0.8
ACCESSIBILITY_IOU = 0.5
THUMB = (64, 36)
OCR_SCALE = 4
GREY = 0.5

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"'})


def _is_pdf(entry: Any) -> bool:
    return isinstance(entry, dict) and str((entry.get("url") or {}).get("native", "")).endswith(".pdf")


@dataclass(frozen=True)
class _Leaf:
    event: int
    path: tuple[str | int, ...]
    node: dict[str, Any]
    rect: tuple[float, float, float, float]
    effects: tuple[str, ...]

    @property
    def key(self) -> str:
        return "/".join(map(str, (self.event, *self.path)))

    @property
    def texture(self) -> str:
        return self.node["texture"]

    @property
    def kind(self) -> Any:
        return (self.node.get("texturedRectangle") or {}).get("textureType")

    @property
    def in_magic_move(self) -> bool:
        return MAGIC_MOVE in self.effects

    @property
    def is_base(self) -> bool:
        return not self.effects


@dataclass
class _Slide:
    ordinal: int
    uuid: str
    folder: Path
    payload: dict[str, Any]
    leaves: list[_Leaf] = field(default_factory=list)
    movies: dict[str, tuple[str, str | None]] = field(default_factory=dict)

    @property
    def assets(self) -> dict[str, Any]:
        return self.payload.get("assets") or {}

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.payload.get("events") or []

    @property
    def json_path(self) -> Path:
        return self.folder / f"{self.uuid}.json"

    @property
    def pdf_path(self) -> Path:
        return self.folder / "assets" / f"{self.uuid}.pdf"

    def texture_entry(self, texture: str) -> dict[str, Any] | None:
        entry = self.assets.get(texture)
        return entry if isinstance(entry, dict) and entry.get("type") == "texture" else None

    def page_index(self, texture: str) -> int | None:
        entry = self.texture_entry(texture)
        return int(entry["index"]) if entry is not None and _is_pdf(entry) else None


@dataclass(frozen=True)
class _Hit:
    slide: int
    leaf: _Leaf
    rule: str
    detail: str


@dataclass
class _Group:
    slide: int
    old: str
    leaves: list[_Leaf]

    @property
    def first(self) -> _Leaf:
        return self.leaves[0]

    @property
    def size(self) -> tuple[float, float]:
        return self.first.rect[2], self.first.rect[3]


@dataclass
class _Fix:
    group: _Group
    rule: str
    new: str
    donor: tuple[int, str] | None
    verify: dict[str, Any] = field(default_factory=dict)


def _walk(
    node: dict[str, Any], ox: float, oy: float, event: int, path: tuple, effects: tuple, out: list[_Leaf]
) -> None:
    state = node["initialState"]
    x = ox + state["position"]["pointX"] - state["anchorPoint"]["pointX"] * state["width"]
    y = oy + state["position"]["pointY"] - state["anchorPoint"]["pointY"] * state["height"]
    if isinstance(node.get("texture"), str):
        out.append(_Leaf(event, path, node, (x, y, state["width"], state["height"]), effects))
    for k, child in enumerate(node.get("layers") or []):
        _walk(child, x, y, event, (*path, "layers", k), effects, out)


def _event_leaves(event: dict[str, Any], index: int) -> list[_Leaf]:
    out: list[_Leaf] = []
    _walk(event["baseLayer"], 0.0, 0.0, index, ("baseLayer",), (), out)

    def visit(effects: list[dict[str, Any]], path: tuple, names: tuple) -> None:
        for k, effect in enumerate(effects or []):
            here, chain = (*path, "effects", k), (*names, str(effect.get("name")))
            if effect.get("baseLayer"):
                _walk(effect["baseLayer"], 0.0, 0.0, index, (*here, "baseLayer"), chain, out)
            visit(effect.get("effects"), here, chain)

    visit(event.get("effects"), (), ())
    return out


def _movies(payload: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    """objectID -> (canonical asset name, renderMovie poster texture id)."""
    out: dict[str, tuple[str, str | None]] = {}
    for event in payload.get("events") or []:
        for effect in event.get("effects") or []:
            if effect.get("name") != "apple:movie-start" or not effect.get("objectID"):
                continue
            for render in effect.get("effects") or []:
                asset = (render.get("movie") or {}).get("asset")
                if render.get("name") != "renderMovie" or not asset:
                    continue
                poster = next(
                    (
                        layer["texture"]
                        for layer in (render.get("baseLayer") or {}).get("layers") or []
                        if isinstance(layer.get("texture"), str) and not layer.get("isVideoLayer")
                    ),
                    None,
                )
                name = canonical_asset_name(_asset_url(payload.get("assets") or {}, asset))
                out.setdefault(effect["objectID"], (name, poster))
    return out


def _load(export_root: Path, slides: list[dict[str, Any]]) -> list[_Slide]:
    out = []
    for entry in sorted((s for s in slides if not s.get("skipped")), key=lambda s: s["playerIndex"]):
        uuid = entry["exportedUuid"]
        folder = export_root / "assets" / uuid
        payload = read_jsonish(folder / f"{uuid}.json")
        slide = _Slide(int(entry["originalOrdinal"]), uuid, folder, payload)
        for index, event in enumerate(slide.events):
            slide.leaves.extend(_event_leaves(event, index))
        slide.movies = _movies(payload)
        out.append(slide)
    return out


def _close(a: tuple[float, ...], b: tuple[float, ...], tol: float) -> bool:
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


def _fits(entry: dict[str, Any] | None, size: tuple[float, float]) -> bool:
    return entry is not None and _close((entry["width"], entry["height"]), size, SIZE_TOL)


def _consistent(slide: _Slide, leaf: _Leaf) -> bool:
    return _fits(slide.texture_entry(leaf.texture), leaf.rect[2:])


def _scaled_movie_frame(leaf: _Leaf, entry: dict[str, Any]) -> bool:
    if "renderMovie" not in leaf.effects or not (leaf.node.get("isVideoLayer") or leaf.kind is None):
        return False
    aspect = entry["width"] / entry["height"]
    return abs(aspect - leaf.rect[2] / leaf.rect[3]) < 0.01 * aspect


def _end_rect(leaf: _Leaf) -> tuple[str | None, tuple[float, float, float, float]]:
    """A Magic Move leaf's `contents.to` texture and end rect: scale about the anchor, then translate."""
    sx = sy = 1.0
    tx = ty = 0.0
    to = None
    for group in leaf.node.get("animations") or []:
        for anim in group.get("animations") or [group]:
            prop = anim.get("property")
            if prop == "transform.scale.x":
                sx = anim["to"]["scalar"]
            elif prop == "transform.scale.y":
                sy = anim["to"]["scalar"]
            elif prop == "transform.translation":
                tx, ty = anim["to"]["pointX"], anim["to"]["pointY"]
            elif prop == "contents":
                to = (anim.get("to") or {}).get("texture")
    x, y, w, h = leaf.rect
    anchor = leaf.node["initialState"]["anchorPoint"]
    ax, ay = anchor["pointX"] * w, anchor["pointY"] * h
    return to, (x + tx + ax - sx * ax, y + ty + ay - sy * ay, sx * w, sy * h)


def _json_hits(slides: list[_Slide]) -> list[_Hit]:
    hits = []
    for index, slide in enumerate(slides):
        for leaf in slide.leaves:
            entry = slide.texture_entry(leaf.texture)
            w, h = leaf.rect[2:]
            if entry is None:
                hits.append(_Hit(index, leaf, "R1", f"texture {leaf.texture[:8]} is not in the slide's table"))
            elif not _fits(entry, (w, h)) and not _scaled_movie_frame(leaf, entry):
                table = f"{entry['width']:.0f}×{entry['height']:.0f}"
                hits.append(_Hit(index, leaf, "R1", f"{w:.0f}×{h:.0f} leaf uses {table} texture {leaf.texture[:8]}"))
            if leaf.in_magic_move:
                to, end = _end_rect(leaf)
                if to and not _fits(slide.texture_entry(to), end[2:]):
                    detail = f"Magic Move contents.to {to[:8]} does not fit its {end[2]:.0f}×{end[3]:.0f} end rect"
                    hits.append(_Hit(index, leaf, "R1b", detail))
    return hits


def json_hits(export_root: Path, slides: list[dict[str, Any]]) -> list[str]:
    """R1 + R1b only (no pixels, no Quartz). Human-readable hit strings; [] when consistent."""
    loaded = _load(export_root, slides)
    return [f"slide {loaded[h.slide].ordinal} {h.leaf.key}: {h.detail}" for h in _json_hits(loaded)]


class _Renderer:
    def __init__(self) -> None:
        self._docs: dict[Path, Any] = {}
        self._thumbs: dict[tuple[Path, int], np.ndarray | None] = {}

    def _page(self, pdf: Path, index: int) -> Any:
        import Quartz  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415

        if pdf not in self._docs:
            url = NSURL.fileURLWithPath_(str(pdf))
            self._docs[pdf] = Quartz.CGPDFDocumentCreateWithURL(url) if pdf.is_file() else None
        doc = self._docs[pdf]
        page = Quartz.CGPDFDocumentGetPage(doc, index + 1) if doc is not None else None
        if not page:
            return None, None
        box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
        if box.size.width < 1 or box.size.height < 1:
            return None, None
        return page, box

    def thumb(self, pdf: Path, index: int | None) -> np.ndarray | None:
        """The page at 64×36 over 50% grey, as grey levels."""
        if index is None:
            return None
        key = (pdf, index)
        if key not in self._thumbs:
            import Quartz  # noqa: PLC0415

            page, box = self._page(pdf, index)
            if page is None:
                self._thumbs[key] = None
            else:
                w, h = THUMB
                grey = Quartz.CGColorSpaceCreateDeviceGray()
                ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w, grey, Quartz.kCGImageAlphaNone)
                Quartz.CGContextSetGrayFillColor(ctx, GREY, 1)
                Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
                Quartz.CGContextScaleCTM(ctx, w / box.size.width, h / box.size.height)
                Quartz.CGContextDrawPDFPage(ctx, page)
                image = Quartz.CGBitmapContextCreateImage(ctx)
                data = bytes(Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image)))
                row = Quartz.CGImageGetBytesPerRow(image)
                self._thumbs[key] = np.frombuffer(data, np.uint8).reshape(h, row)[:, :w].astype(float)
        return self._thumbs[key]

    def png(self, pdf: Path, index: int, dest: Path) -> bool:
        import Quartz  # noqa: PLC0415
        from Foundation import NSURL  # noqa: PLC0415

        page, box = self._page(pdf, index)
        if page is None:
            return False
        w, h = round(box.size.width * OCR_SCALE), round(box.size.height * OCR_SCALE)
        ctx = Quartz.CGBitmapContextCreate(
            None, w, h, 8, 4 * w, Quartz.CGColorSpaceCreateDeviceRGB(), Quartz.kCGImageAlphaNoneSkipLast
        )
        Quartz.CGContextSetRGBFillColor(ctx, GREY, GREY, GREY, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
        Quartz.CGContextScaleCTM(ctx, w / box.size.width, h / box.size.height)
        Quartz.CGContextDrawPDFPage(ctx, page)
        image = Quartz.CGBitmapContextCreateImage(ctx)
        target = Quartz.CGImageDestinationCreateWithURL(NSURL.fileURLWithPath_(str(dest)), "public.png", 1, None)
        Quartz.CGImageDestinationAddImage(target, image, None)
        return bool(Quartz.CGImageDestinationFinalize(target))


def _corr(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    """Pixel correlation of two thumbnails; None (no verdict) when either is missing or flat."""
    if a is None or b is None:
        return None
    if np.array_equal(a, b):
        return 1.0
    if a.std() < FLAT_STD or b.std() < FLAT_STD:
        return None
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / (np.linalg.norm(a) * np.linalg.norm(b)))


def _thumb(renderer: _Renderer, slide: _Slide, texture: str | None) -> np.ndarray | None:
    return renderer.thumb(slide.pdf_path, slide.page_index(texture)) if texture else None


def _movie_of(slide: _Slide, leaf: _Leaf) -> str | None:
    """objectID of the movie slot wrapper (`/baseLayer/layers/k/layers/0`) above a base leaf."""
    if not leaf.is_base or len(leaf.path) < 5 or leaf.path[:2] != ("baseLayer", "layers") or leaf.path[3] != "layers":
        return None
    slot = slide.events[leaf.event]["baseLayer"]["layers"][leaf.path[2]]
    wrapper = (slot.get("layers") or [{}])[0]
    oid = wrapper.get("objectID")
    return oid if oid in slide.movies else None


def _poster_hits(slide: _Slide, index: int, renderer: _Renderer) -> list[_Hit]:
    if len({name for name, _ in slide.movies.values()}) < 2:
        return []
    posters = {oid: _thumb(renderer, slide, poster) for oid, (_, poster) in slide.movies.items()}
    hits = []
    for leaf in slide.leaves:
        oid = _movie_of(slide, leaf)
        if oid is None:
            continue
        page = _thumb(renderer, slide, leaf.texture)
        own = _corr(page, posters[oid])
        others = [
            _corr(page, posters[other])
            for other, (name, _) in slide.movies.items()
            if name != slide.movies[oid][0]
        ]
        if own is not None and own < CORR_HIT and any(c is not None and c >= CORR_MATCH for c in others):
            hits.append(_Hit(index, leaf, "R4", f"poster {leaf.texture[:8]} shows another movie (corr {own:.2f})"))
    return hits


def _landings(previous: _Slide, slide: _Slide) -> list[tuple[_Leaf, str, _Leaf]]:
    """(Magic Move leaf, its contents.to, the unique destination event-0 leaf at its end rect)."""
    targets = [leaf for leaf in slide.leaves if leaf.is_base and leaf.event == 0]
    out = []
    for leaf in previous.leaves:
        if not leaf.in_magic_move:
            continue
        to, end = _end_rect(leaf)
        if not to:
            continue
        found = [target for target in targets if _close(target.rect, end, RECT_TOL)]
        if len(found) == 1:
            out.append((leaf, to, found[0]))
    return out


def _landing_hits(slides: list[_Slide], index: int, renderer: _Renderer) -> list[_Hit]:
    if index == 0:
        return []
    previous, slide = slides[index - 1], slides[index]
    hits = []
    for _leaf, to, target in _landings(previous, slide):
        corr = _corr(_thumb(renderer, previous, to), _thumb(renderer, slide, target.texture))
        if corr is not None and corr < CORR_HIT:
            detail = f"Magic Move lands {to[:8]} on {target.texture[:8]} (corr {corr:.2f})"
            hits.append(_Hit(index, target, "R6", detail))
    return hits


def _detect(slides: list[_Slide], renderer: _Renderer) -> list[_Hit]:
    hits = _json_hits(slides)
    for index, slide in enumerate(slides):
        hits += _poster_hits(slide, index, renderer)
        hits += _landing_hits(slides, index, renderer)
    return hits


def _same_object(slide: _Slide, a: _Leaf, b: _Leaf) -> bool:
    return (
        a.texture == b.texture
        and _close(a.rect, b.rect, GROUP_TOL)
        and (a.kind == TEXT_TYPE) == (b.kind == TEXT_TYPE)
        and _text_key(slide, a) == _text_key(slide, b)
    )


def _groups(slides: list[_Slide], hits: list[_Hit]) -> tuple[list[_Group], list[tuple[int, _Leaf]]]:
    """Partition the bad leaves into groups whose members share slide, old id, rect, category,
    normalised accessibility text and movie owner. An unbound copy beside more than one owner is
    ambiguous and returned separately, never grouped."""
    groups: list[_Group] = []
    ambiguous: list[tuple[int, _Leaf]] = []
    seen: set[tuple[int, str]] = set()
    for hit in hits:
        if hit.rule == "R1b" or (hit.slide, hit.leaf.key) in seen:
            continue
        slide = slides[hit.slide]
        candidates = [
            leaf for leaf in slide.leaves if (hit.slide, leaf.key) not in seen and _same_object(slide, leaf, hit.leaf)
        ]
        owners = {leaf.key: _owner(slide, leaf) for leaf in candidates}
        movies = {oid for bound, oid in owners.values() if bound}
        parts: dict[tuple[bool, str | None], list[_Leaf]] = {}
        for leaf in candidates:
            seen.add((hit.slide, leaf.key))
            bound, oid = owners[leaf.key]
            if bound or len(movies) == 1:
                parts.setdefault((True, oid if bound else next(iter(movies))), []).append(leaf)
            elif movies:
                ambiguous.append((hit.slide, leaf))
            else:
                parts.setdefault((False, None), []).append(leaf)
        groups.extend(_Group(hit.slide, hit.leaf.texture, sorted(m, key=lambda leaf: leaf.key)) for m in parts.values())
    return groups, ambiguous


def _normal(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_QUOTES).split())


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / (a[2] * a[3] + b[2] * b[3] - inter) if inter else 0.0


def _slot_text(slide: _Slide, event: int, rect: tuple[float, ...]) -> str | None:
    found = []
    for item in slide.events[event].get("accessibility") or []:
        target = item.get("targetRectangle") or {}
        box = (target.get("x", 0.0), target.get("y", 0.0), target.get("width", 0.0), target.get("height", 0.0))
        if isinstance(item.get("text"), str) and _iou(rect, box) >= ACCESSIBILITY_IOU:
            found.append(item["text"])
    return found[0] if len(found) == 1 else None


def _leaf_text(slide: _Slide, leaf: _Leaf) -> str | None:
    return _slot_text(slide, leaf.event, leaf.rect) if leaf.kind == TEXT_TYPE else None


def _text_key(slide: _Slide, leaf: _Leaf) -> str | None:
    text = _leaf_text(slide, leaf)
    return None if text is None else _normal(text)


def _owner(slide: _Slide, leaf: _Leaf) -> tuple[bool, str | None]:
    """Whether a leaf is bound to one movie identity, and which: base leaves under a slot wrapper
    through it (None for an ordinary slot), movie-start copies through the effect's objectID. A
    flattened slot (the leaf itself at the wrapper's place, as in later events) carries none."""
    if leaf.is_base and (len(leaf.path) > 5 or leaf.node.get("objectID")):
        return True, _movie_of(slide, leaf)
    if leaf.is_base:
        return False, None
    if leaf.effects[0] == "apple:movie-start":
        return True, slide.events[leaf.event]["effects"][leaf.path[1]].get("objectID")
    return False, None


def _group_text(slide: _Slide, group: _Group) -> str | None:
    return _leaf_text(slide, group.first)


def _group_movie(slide: _Slide, group: _Group) -> str | None:
    oids = {oid for leaf in group.leaves if (oid := _movie_of(slide, leaf))}
    return oids.pop() if len(oids) == 1 else None


def _describe(slide: _Slide, group: _Group) -> str:
    w, h = (round(v) for v in group.size)
    if group.first.kind == TEXT_TYPE:
        text = _group_text(slide, group)
        return f"'{text}' label" if text else f"{w}×{h} text"
    oid = _group_movie(slide, group)
    return f"movie {slide.movies[oid][0]}" if oid else f"{w}×{h} image"


def _d1(slide: _Slide, group: _Group, bad: set[str]) -> _Fix | None:
    text = _group_text(slide, group)
    if text is None:
        return None
    donors = {
        leaf.texture
        for leaf in slide.leaves
        if leaf.kind == TEXT_TYPE
        and leaf.texture != group.old
        and leaf.key not in bad
        and _consistent(slide, leaf)
        and _close(leaf.rect[:2], group.first.rect[:2], RECT_TOL)
        and _close(leaf.rect[2:], group.size, DONOR_SIZE_TOL)
        and (other := _slot_text(slide, leaf.event, leaf.rect)) is not None
        and _normal(other) == _normal(text)
    }
    return _Fix(group, "D1", donors.pop(), None) if len(donors) == 1 else None


def _d3(slide: _Slide, group: _Group) -> _Fix | None:
    oid = _group_movie(slide, group)
    poster = slide.movies[oid][1] if oid else None
    if not poster or poster == group.old or not _fits(slide.texture_entry(poster), group.size):
        return None
    return _Fix(group, "D3", poster, None)


def _d2(slides: list[_Slide], group: _Group, bad_textures: dict[int, set[str]]) -> _Fix | None:
    if group.slide == 0:
        return None
    previous, slide = slides[group.slide - 1], slides[group.slide]
    keys = {leaf.key for leaf in group.leaves}
    donors = {
        to
        for _leaf, to, target in _landings(previous, slide)
        if target.key in keys
        and _fits(previous.texture_entry(to), group.size)
        and to not in bad_textures.get(group.slide - 1, set())
    }
    if len(donors) != 1:
        return None
    donor = donors.pop()
    new = hashlib.sha256(f"{slide.uuid}:{previous.uuid}:{donor}".encode()).hexdigest()[:32].upper()
    return _Fix(group, "D2", new, (group.slide - 1, donor))


def _mediabox_ok(slide: _Slide, texture: str) -> bool:
    from pypdf import PdfReader  # noqa: PLC0415

    entry, index = slide.texture_entry(texture), slide.page_index(texture)
    if entry is None or index is None or not slide.pdf_path.is_file():
        return False
    reader = PdfReader(str(slide.pdf_path))
    if index >= len(reader.pages):
        return False
    box = reader.pages[index].mediabox
    return _close((float(box.width), float(box.height)), (entry["width"], entry["height"]), MEDIABOX_TOL)


def _ocr(renderer: _Renderer, slide: _Slide, texture: str, scratch: Path) -> str:
    from obed_edom.ocr import ocr_lines  # noqa: PLC0415

    png = scratch / f"{slide.uuid}-{texture}.png"
    index = slide.page_index(texture)
    if index is None or not renderer.png(slide.pdf_path, index, png):
        return ""
    return " ".join(line.text for line in ocr_lines(png))


def _verify(slides: list[_Slide], fix: _Fix, renderer: _Renderer, scratch: Path) -> bool:
    slide = slides[fix.group.slide]
    source, texture = (slides[fix.donor[0]], fix.donor[1]) if fix.donor else (slide, fix.new)
    if not _fits(source.texture_entry(texture), fix.group.size) or not _mediabox_ok(source, texture):
        return False
    if fix.group.first.kind == TEXT_TYPE:
        read = _ocr(renderer, source, texture, scratch)
        fix.verify = {"ocr": read}
        expected = _group_text(slide, fix.group)
        if read and expected is not None:
            a, b = _normal(read).casefold(), _normal(expected).casefold()
            return difflib.SequenceMatcher(None, a, b).ratio() >= OCR_AGREE
        return True
    oid = _group_movie(slide, fix.group)
    if oid:
        corr = _corr(_thumb(renderer, source, texture), _thumb(renderer, slide, slide.movies[oid][1]))
        fix.verify = {"corr": round(corr, 3) if corr is not None else None}
        return corr is not None and corr >= CORR_MATCH
    return False


def _plan(
    slides: list[_Slide], hits: list[_Hit], renderer: _Renderer, scratch: Path
) -> tuple[list[_Fix], list[tuple[int, str]]]:
    groups, ambiguous = _groups(slides, hits)
    bad_keys: dict[int, set[str]] = {}
    bad_textures: dict[int, set[str]] = {}
    for hit in hits:
        bad_keys.setdefault(hit.slide, set()).add(hit.leaf.key)
        if hit.rule == "R1b":
            bad_textures.setdefault(hit.slide, set()).add(_end_rect(hit.leaf)[0])
    fixes: list[_Fix] = []
    refused = [
        (slides[h.slide].ordinal, _describe(slides[h.slide], _Group(h.slide, h.leaf.texture, [h.leaf])))
        for h in hits
        if h.rule == "R1b"
    ]
    refused += [(slides[i].ordinal, _describe(slides[i], _Group(i, leaf.texture, [leaf]))) for i, leaf in ambiguous]
    for group in groups:
        slide = slides[group.slide]
        candidates = (
            _d1(slide, group, bad_keys.get(group.slide, set())),
            _d3(slide, group),
            _d2(slides, group, bad_textures),
        )
        fix = next((c for c in candidates if c is not None and _verify(slides, c, renderer, scratch)), None)
        if fix is None:
            refused.append((slide.ordinal, _describe(slide, group)))
        elif fix.donor and fix.new in slide.assets:
            raise PreviewError(
                f"Cannot repair Keynote's HTML export: grafted id {fix.new} already exists on slide {slide.ordinal}"
            )
        else:
            fixes.append(fix)
    return fixes, refused


def _temp_sibling(path: Path) -> Path:
    return path.with_name(f".{path.name}.texture-repair")


def _write_text(path: Path, text: str) -> None:
    tmp = _temp_sibling(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _node(payload: dict[str, Any], leaf: _Leaf) -> dict[str, Any]:
    node: Any = payload["events"][leaf.event]
    for part in leaf.path:
        node = node[part]
    return node


def _repoint(node: dict[str, Any], old: str, new: str) -> None:
    node["texture"] = new
    for group in node.get("animations") or []:
        for anim in group.get("animations") or [group]:
            source = anim.get("from") if anim.get("property") == "contents" else None
            if isinstance(source, dict) and source.get("texture") == old:
                source["texture"] = new


def _graft_pdf(slides: list[_Slide], slide: _Slide, grafts: list[tuple[int, str]]) -> None:
    from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

    writer = PdfWriter(clone_from=str(slide.pdf_path))
    for donor_slide, donor in grafts:
        source = slides[donor_slide]
        writer.add_page(PdfReader(str(source.pdf_path)).pages[source.page_index(donor)])
    tmp = _temp_sibling(slide.pdf_path)
    try:
        with tmp.open("wb") as handle:
            writer.write(handle)
        os.replace(tmp, slide.pdf_path)
    finally:
        tmp.unlink(missing_ok=True)
    pdfp = slide.pdf_path.with_suffix(".pdfp")
    if pdfp.is_file():
        tmp = _temp_sibling(pdfp)
        try:
            shutil.copyfile(pdfp, tmp)
            rewrite_pdfp_from_pdf(slide.pdf_path, tmp)
            os.replace(tmp, pdfp)
        finally:
            tmp.unlink(missing_ok=True)


def _write_slide(export_root: Path, slides: list[_Slide], slide: _Slide, fixes: list[_Fix]) -> dict[str, Any] | None:
    from pypdf import PdfReader  # noqa: PLC0415

    payload = json.loads(json.dumps(slide.payload))
    grafts: list[tuple[int, str]] = []
    for fix in fixes:
        if fix.donor and fix.new not in payload["assets"]:
            source = slides[fix.donor[0]]
            donor = source.texture_entry(fix.donor[1])
            assert donor is not None
            siblings = [e["url"] for e in payload["assets"].values() if _is_pdf(e)]
            url = dict(siblings[0]) if siblings else {"native": f"assets/{slide.uuid}.pdf"}
            pages = len(PdfReader(str(slide.pdf_path)).pages)
            payload["assets"][fix.new] = {
                "type": "texture",
                "index": pages + len(grafts),
                "url": url,
                "width": donor["width"],
                "height": donor["height"],
            }
            grafts.append(fix.donor)
        for leaf in fix.group.leaves:
            _repoint(_node(payload, leaf), fix.group.old, fix.new)
    pdf_record = None
    if grafts:
        source_sha = file_sha256(slide.pdf_path)
        _graft_pdf(slides, slide, grafts)
        pdf_record = {
            "path": slide.pdf_path.relative_to(export_root).as_posix(),
            "sourceSha256": source_sha,
            "sha256": file_sha256(slide.pdf_path),
        }
    _write_text(slide.json_path, _dumps(payload))
    jsonp = slide.json_path.with_suffix(".jsonp")
    if jsonp.is_file():
        _write_text(jsonp, f"local_slide( {_dumps({'name': slide.uuid, 'json': payload})} )")
    return pdf_record


def _blind(node: Any) -> Any:
    if isinstance(node, list):
        return [_blind(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "texture" and isinstance(v, str):
            out[k] = ""
        elif k == "assets" and isinstance(v, dict):
            out[k] = {i: e for i, e in v.items() if not (isinstance(e, dict) and e.get("type") == "texture")}
        else:
            out[k] = _blind(v)
    return out


def _fingerprint(payload: dict[str, Any]) -> str:
    return json.dumps(_blind(payload), sort_keys=True)


def _postcondition(
    export_root: Path, slides: list[dict[str, Any]], before: list[_Slide], fixes: list[_Fix]
) -> str | None:
    after = _load(export_root, slides)
    renderer = _Renderer()
    hits = _detect(after, renderer)
    if hits:
        first = hits[0]
        return f"the detector still finds {len(hits)} hit(s), first slide {after[first.slide].ordinal} {first.leaf.key}"
    for old, new in zip(before, after, strict=True):
        if _fingerprint(old.payload) != _fingerprint(new.payload):
            return f"slide {new.ordinal} changed beyond its texture ids"
    for fix in fixes:
        if fix.donor:
            slide, source = after[fix.group.slide], after[fix.donor[0]]
            grafted = renderer.thumb(slide.pdf_path, slide.page_index(fix.new))
            donor = renderer.thumb(source.pdf_path, source.page_index(fix.donor[1]))
            if grafted is None or donor is None or not np.array_equal(grafted, donor):
                return f"slide {slide.ordinal} grafted page {fix.new[:8]} does not render as its donor"
    for slide in after:
        jsonp = slide.json_path.with_suffix(".jsonp")
        if jsonp.is_file() and read_jsonish(jsonp).get("json") != slide.payload:
            return f"slide {slide.ordinal} .jsonp differs from its .json"
        pdfp = slide.pdf_path.with_suffix(".pdfp")
        if pdfp.is_file() and base64.b64decode(read_jsonish(pdfp)["pdf"]) != slide.pdf_path.read_bytes():
            return f"slide {slide.ordinal} .pdfp differs from its .pdf"
    return None


def repair_textures(
    export_root: Path, slides: list[dict[str, Any]], *, player_digest: str, log: Callable[[str], None]
) -> dict[str, Any]:
    """Detect (R1, R1b, R4, R6), plan donors (D1, D3, D2), verify (V1, V3), write
    (temp + os.replace; .json, .jsonp, .pdf, .pdfp), check the postcondition (V4), return
    manifest.textureRepair. Raises PreviewError on refusal or a failed postcondition."""
    record: dict[str, Any] = {"version": TEXTURE_REPAIR_VERSION, "playerDigest": player_digest}
    if player_digest not in SUPPORTED_PLAYERS:
        return record | {"skipped": "unsupported player", "repaired": [], "pdfs": []}
    loaded = _load(export_root, slides)
    renderer = _Renderer()
    hits = _detect(loaded, renderer)
    if not hits:
        return record | {"repaired": [], "pdfs": []}
    with tempfile.TemporaryDirectory(prefix="obed-texture-repair-") as scratch:
        fixes, refused = _plan(loaded, hits, renderer, Path(scratch))
    if refused:
        raise PreviewError(
            "Cannot repair Keynote's HTML export: "
            + "; ".join(
                f"slide {ordinal} ({obj}): its texture is mis-mapped and no verified replacement exists"
                for ordinal, obj in sorted(set(refused))
            )
        )
    pdfs = []
    for index, slide in enumerate(loaded):
        mine = [fix for fix in fixes if fix.group.slide == index]
        if mine and (pdf := _write_slide(export_root, loaded, slide, mine)):
            pdfs.append(pdf)
    problem = _postcondition(export_root, slides, loaded, fixes)
    if problem:
        raise PreviewError(f"Texture repair failed its own check: {problem}")
    repaired = []
    for fix in fixes:
        slide = loaded[fix.group.slide]
        donor = None
        if fix.donor:
            source = loaded[fix.donor[0]]
            donor = {"uuid": source.uuid, "id": fix.donor[1], "page": source.page_index(fix.donor[1]) + 1}
        repaired.append(
            {
                "object": _describe(slide, fix.group),
                "ordinal": slide.ordinal,
                "uuid": slide.uuid,
                "leaves": [leaf.key for leaf in fix.group.leaves],
                "rule": fix.rule,
                "from": fix.group.old,
                "to": fix.new,
                "donor": donor,
                "verify": fix.verify,
            }
        )
    repaired.sort(key=lambda entry: (entry["ordinal"], entry["leaves"][0]))
    for entry in repaired:
        obj = entry.pop("object")
        log(f"Repaired slide {entry['ordinal']} {obj}: {entry['rule']} {entry['from'][:8]} → {entry['to'][:8]}")
    log(f"Repaired {len(repaired)} mis-mapped texture{'s' if len(repaired) != 1 else ''}")
    return record | {"repaired": repaired, "pdfs": sorted(pdfs, key=lambda entry: entry["path"])}
