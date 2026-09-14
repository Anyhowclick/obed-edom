"""Offline write of the DSK verse-pill (`Media` slot) mask law, §1.4 of the layout plan.

The pill is the same image data (rotated 180 deg, masked) on every verse layout/slide.
Measured across gold slides 3/5/9/20/23/35/38 and both verse layouts' own default pill
(8 widths total): the image drawable's own geometry never varies with width -- only the
mask does. Mask height 75.52111 and y 50.9344 are constant; mask x + width == 1832.5315
(right edge pinned); the mask's rounded-rect pathsource naturalSize tracks its own size
(width with the mask, height constant) with a constant scalar (corner radius) 15.0.
Composed frame x is 50.4 constant; frame width == mask width; frame y is a property of
the resolved layout (789.1 "Verse Standard (Variation 2)", 879.1 "Verse 1 Line
(Variation 2)"), not written directly -- it falls out of the (constant) image geometry.
"""
from __future__ import annotations

import copy
import secrets
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from keynote_parser.codec import IWAFile

from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import UndecodableIWAMember, _load_deck_full, slide_order
from obed_edom.iwa_write import (
    _METADATA_MEMBER,
    OfflineWriteCorrupted,
    _components_by_locator,
    _find_archive,
    _find_package_metadata_archive,
    _member_locator,
    _rewrite_members,
)

_MASK_Y = 50.9344
_MASK_H = 75.52111
_MASK_RIGHT = 1832.5315
_MASK_SCALAR = 15.0
_MAX_WIDTH = 958.4864
_FRAME_X = 50.4
_LAYOUT_FRAME_Y = {"standard": 789.1, "one_line": 879.1}
_IMAGE_PBTYPE = "TSD.ImageArchive"
_SLIDE_PBTYPE = "KN.SlideArchive"
_MEDIA_TAG = "Media"
_DATA_REF_KEYS = ("data", "thumbnailData", "adjustedImageData", "thumbnailAdjustedImageData")


class OfflineWriteRefused(Exception):
    """A precondition of `write_pills` failed; the source deck and `out_path` are untouched."""


@dataclass(frozen=True)
class PillSpec:
    width: float
    layout: str  # "standard" | "one_line" -- cross-checked against the slide's resolved layout


@dataclass
class PillResult:
    applied: int = 0
    reused: int = 0
    minted: int = 0
    members: list[str] = field(default_factory=list)
    edited_ids: dict[int, str] = field(default_factory=dict)


def _sage_tags(slide: dict) -> dict[str, str]:
    return {str(e["info"]["identifier"]): e["tag"] for e in (slide.get("sageTagToInfoMap") or [])}


def _find_media_pill(objects: dict[str, dict], layout_slide: dict) -> tuple[str | None, dict | None]:
    tags = _sage_tags(layout_slide)
    owned = [str(r["identifier"]) for r in (layout_slide.get("ownedDrawables") or [])]
    found = [
        oid for oid in owned
        if tags.get(oid) == _MEDIA_TAG and (objects.get(oid) or {}).get("_pbtype") == _IMAGE_PBTYPE
    ]
    if len(found) != 1:
        return None, None
    return found[0], objects[found[0]]


def _data_id_present(namelist: set[str], data_id: str) -> bool:
    needle = f"-{data_id}."
    return any(name.startswith("Data/") and needle in name.split("/")[-1] for name in namelist)


def _apply_mask_fields(mask_obj: dict, width: float) -> None:
    geom = mask_obj["super"]["geometry"]
    geom["position"] = {"x": _MASK_RIGHT - width, "y": _MASK_Y}
    geom["size"] = {"width": width, "height": _MASK_H}
    geom["angle"] = 180.0
    sps = mask_obj["pathsource"]["scalarPathSource"]
    sps["naturalSize"] = {"width": width, "height": _MASK_H}
    sps["scalar"] = _MASK_SCALAR


def _mask_law_ok(mask_geom: dict, width: float) -> bool:
    pos, size = mask_geom.get("position") or {}, mask_geom.get("size") or {}
    return (
        abs(float(pos.get("y", -1)) - _MASK_Y) <= 0.01
        and abs(float(size.get("height", -1)) - _MASK_H) <= 0.01
        and abs(float(size.get("width", -1)) - width) <= 0.01
        and abs(float(pos.get("x", -1)) - (_MASK_RIGHT - width)) <= 0.01
    )


def _resolve_slide_media_candidates(objects: dict[str, dict], slide: dict, data_id: str) -> list[str]:
    tags = _sage_tags(slide)
    owned = [str(r["identifier"]) for r in (slide.get("ownedDrawables") or [])]
    found: list[str] = []
    for oid in owned:
        obj = objects.get(oid) or {}
        if obj.get("_pbtype") != _IMAGE_PBTYPE:
            continue
        if tags.get(oid) == _MEDIA_TAG or str((obj.get("data") or {}).get("identifier")) == data_id:
            found.append(oid)
    seen: list[str] = []
    for oid in found:
        if oid not in seen:
            seen.append(oid)
    return seen


class _Minter:
    """Sequential archive id + UUID allocation off `Index/Metadata.iwa`'s counter, mirroring
    `iwa_write.mint_media_style`'s collision checks."""

    def __init__(self, package_meta: dict, objects: dict[str, dict], id_to_file: dict[str, str],
                header_object_references: set[str]):
        self._package_meta = package_meta
        self._objects = objects
        self._id_to_file = id_to_file
        self._hor = header_object_references
        try:
            self._last_id = int(package_meta.get("lastObjectIdentifier"))
        except (TypeError, ValueError) as exc:
            raise OfflineWriteRefused(
                f"lastObjectIdentifier {package_meta.get('lastObjectIdentifier')!r} is not numeric"
            ) from exc
        self._existing_uuids: set[tuple[str, str]] = set()
        for comp in package_meta.get("components") or []:
            for u in comp.get("objectUuidMapEntries") or []:
                uu = u.get("uuid") or {}
                self._existing_uuids.add((str(uu.get("lower")), str(uu.get("upper"))))

    def mint_id(self) -> str:
        while True:
            self._last_id += 1
            cand = str(self._last_id)
            if cand in self._id_to_file or cand in self._objects or cand in self._hor:
                continue
            self._package_meta["lastObjectIdentifier"] = cand
            return cand

    def mint_uuid(self) -> dict:
        lower, upper = secrets.randbits(64), secrets.randbits(64)
        while (lower, upper) == (0, 0) or (str(lower), str(upper)) in self._existing_uuids:
            lower, upper = secrets.randbits(64), secrets.randbits(64)
        self._existing_uuids.add((str(lower), str(upper)))
        return {"lower": str(lower), "upper": str(upper)}


def _register_new_ids(component: dict, minter: _Minter, new_ids: list[str]) -> None:
    entries = component.setdefault("objectUuidMapEntries", [])
    for nid in new_ids:
        entries.append({"identifier": nid, "uuid": minter.mint_uuid()})


def _register_data_refs(component: dict, image_id: str, data_ids: list[str]) -> None:
    by_data = {str(e.get("dataIdentifier")): e for e in component.get("dataReferences") or []}
    for did in data_ids:
        entry = by_data.get(did)
        if entry is None:
            entry = {"dataIdentifier": did, "objectReferenceList": []}
            component.setdefault("dataReferences", []).append(entry)
            by_data[did] = entry
        entry.setdefault("objectReferenceList", []).append({"objectIdentifier": image_id, "count": 1})


def _register_style_ext_ref(component: dict, style_id: str, style_component_id: str) -> None:
    ext_refs = component.setdefault("externalReferences", [])
    for ref in ext_refs:
        if str(ref.get("objectIdentifier")) == style_id:
            return
    ext_refs.append({"componentIdentifier": style_component_id, "objectIdentifier": style_id})


def write_pills(key_path: str | Path, *, slides: Mapping[int, PillSpec], out_path: str | Path) -> PillResult:
    key_path, out_path = Path(key_path), Path(out_path)
    if not slides:
        raise OfflineWriteRefused("slides is empty")

    try:
        objects, id_to_file, file_ids, header_object_references = _load_deck_full(key_path, strict=True)
    except UndecodableIWAMember as exc:
        raise OfflineWriteRefused(f"member {exc} is undecodable") from exc

    order = slide_order(objects)
    with zipfile.ZipFile(key_path) as zf:
        namelist = set(zf.namelist())
        member_bytes = {m: zf.read(m) for m in set(file_ids)}

    decoded: dict[str, dict] = {}

    def get_decoded(member: str) -> dict:
        if member not in decoded:
            decoded[member] = IWAFile.from_buffer(member_bytes[member], member).to_dict()
        return decoded[member]

    meta_decoded = get_decoded(_METADATA_MEMBER)
    meta_arch = _find_package_metadata_archive(meta_decoded)
    if meta_arch is None:
        raise OfflineWriteRefused(f"no package metadata in {_METADATA_MEMBER}")
    package_meta = meta_arch["objects"][0]
    minter = _Minter(package_meta, objects, id_to_file, header_object_references)
    components_by_locator = _components_by_locator(package_meta.get("components") or [])

    def component_for_member(member: str) -> dict:
        locator = _member_locator(member)
        matches = components_by_locator.get(locator) or []
        if len(matches) != 1:
            raise OfflineWriteRefused(f"member {member} has {len(matches)} metadata components, not 1")
        return matches[0]

    result = PillResult()
    touched: set[str] = set()

    for ordinal in sorted(slides):
        spec = slides[ordinal]
        width = float(spec.width)
        if not (0.0 < width <= _MAX_WIDTH):
            raise OfflineWriteRefused(f"slide {ordinal}: width {width} out of (0, {_MAX_WIDTH}]")
        if spec.layout not in _LAYOUT_FRAME_Y:
            raise OfflineWriteRefused(f"slide {ordinal}: unknown layout {spec.layout!r}")
        if ordinal < 1 or ordinal > len(order):
            raise OfflineWriteRefused(f"slide {ordinal}: no such ordinal")

        slide_id, _skipped = order[ordinal - 1]
        slide = objects.get(slide_id)
        if slide is None or slide.get("_pbtype") != _SLIDE_PBTYPE:
            raise OfflineWriteRefused(f"slide {ordinal}: {slide_id} is not a KN.SlideArchive")
        slide_member = id_to_file.get(slide_id)
        if slide_member is None:
            raise OfflineWriteRefused(f"slide {ordinal}: {slide_id} has no owning member")

        layout_ref = slide.get("templateSlide")
        if not layout_ref or layout_ref.get("identifier") is None:
            raise OfflineWriteRefused(f"slide {ordinal}: no templateSlide")
        layout_id = str(layout_ref["identifier"])
        layout_slide = objects.get(layout_id)
        if layout_slide is None or layout_slide.get("_pbtype") != _SLIDE_PBTYPE:
            raise OfflineWriteRefused(f"slide {ordinal}: templateSlide {layout_id} unresolved")

        layout_pill_id, layout_pill = _find_media_pill(objects, layout_slide)
        if layout_pill_id is None:
            raise OfflineWriteRefused(f"slide {ordinal}: resolved layout {layout_id} has no Media slot")
        layout_member = id_to_file[layout_pill_id]

        data_id = str((layout_pill.get("data") or {}).get("identifier") or "")
        if not data_id or not _data_id_present(namelist, data_id):
            raise OfflineWriteRefused(f"slide {ordinal}: data id {data_id!r} absent from the deck")

        candidates = _resolve_slide_media_candidates(objects, slide, data_id)
        if len(candidates) > 1:
            raise OfflineWriteRefused(f"slide {ordinal}: {len(candidates)} candidate pills, expected at most 1")

        if candidates:
            image_id = candidates[0]
            image = objects[image_id]
            image_member = id_to_file[image_id]
            mask_ref = image.get("mask") or {}
            mask_id = str(mask_ref.get("identifier") or "")
            mask_member = id_to_file.get(mask_id)
            if not mask_id or mask_member is None:
                raise OfflineWriteRefused(f"slide {ordinal}: pill {image_id} has no resolvable mask")

            image_arch = _find_archive(get_decoded(image_member), image_id)
            image_obj = image_arch["objects"][0]
            image_obj["super"]["geometry"] = copy.deepcopy(layout_pill["super"]["geometry"])

            mask_arch = _find_archive(get_decoded(mask_member), mask_id)
            mask_obj = mask_arch["objects"][0]
            _apply_mask_fields(mask_obj, width)
            touched.add(image_member)
            touched.add(mask_member)

            result.reused += 1
            result.edited_ids[ordinal] = image_id
            continue

        # Copy path: mint image/mask/title/caption archives from the layout's own pill.
        layout_decoded = get_decoded(layout_member)
        src_image_arch = _find_archive(layout_decoded, layout_pill_id)
        mask_src_id = str((layout_pill.get("mask") or {}).get("identifier") or "")
        title_src_id = str(((layout_pill.get("super") or {}).get("title") or {}).get("identifier") or "")
        caption_src_id = str(((layout_pill.get("super") or {}).get("caption") or {}).get("identifier") or "")
        for src_id, label in ((mask_src_id, "mask"), (title_src_id, "title"), (caption_src_id, "caption")):
            if not src_id or objects.get(src_id) is None:
                raise OfflineWriteRefused(f"slide {ordinal}: layout pill {label} unresolved")
        src_mask_arch = _find_archive(layout_decoded, mask_src_id)
        src_title_arch = _find_archive(layout_decoded, title_src_id)
        src_caption_arch = _find_archive(layout_decoded, caption_src_id)

        new_image_id = minter.mint_id()
        new_mask_id = minter.mint_id()
        new_title_id = minter.mint_id()
        new_caption_id = minter.mint_id()

        new_image_obj = copy.deepcopy(src_image_arch["objects"][0])
        new_image_obj["super"]["parent"] = {"identifier": slide_id}
        new_image_obj["super"]["title"] = {"identifier": new_title_id}
        new_image_obj["super"]["caption"] = {"identifier": new_caption_id}
        new_image_obj["mask"] = {"identifier": new_mask_id}
        new_image_header = copy.deepcopy(src_image_arch["header"])
        new_image_header["identifier"] = new_image_id
        for mi in new_image_header.get("messageInfos") or []:
            refs = mi.get("objectReferences")
            if refs:
                mi["objectReferences"] = [
                    {caption_src_id: new_caption_id, title_src_id: new_title_id,
                     mask_src_id: new_mask_id}.get(r, r)
                    for r in refs
                ]

        new_mask_obj = copy.deepcopy(src_mask_arch["objects"][0])
        new_mask_obj["super"]["parent"] = {"identifier": new_image_id}
        _apply_mask_fields(new_mask_obj, width)
        new_mask_header = copy.deepcopy(src_mask_arch["header"])
        new_mask_header["identifier"] = new_mask_id

        new_title_obj = copy.deepcopy(src_title_arch["objects"][0])
        new_title_header = copy.deepcopy(src_title_arch["header"])
        new_title_header["identifier"] = new_title_id

        new_caption_obj = copy.deepcopy(src_caption_arch["objects"][0])
        new_caption_header = copy.deepcopy(src_caption_arch["header"])
        new_caption_header["identifier"] = new_caption_id

        slide_decoded = get_decoded(slide_member)
        slide_decoded["chunks"][0]["archives"].extend([
            {"header": new_image_header, "objects": [new_image_obj]},
            {"header": new_mask_header, "objects": [new_mask_obj]},
            {"header": new_title_header, "objects": [new_title_obj]},
            {"header": new_caption_header, "objects": [new_caption_obj]},
        ])
        slide_arch = _find_archive(slide_decoded, slide_id)
        slide_obj = slide_arch["objects"][0]
        slide_obj.setdefault("ownedDrawables", []).append({"identifier": new_image_id})
        slide_obj.setdefault("drawablesZOrder", []).append({"identifier": new_image_id})

        slide_component = component_for_member(slide_member)
        _register_new_ids(slide_component, minter, [new_image_id, new_mask_id, new_title_id, new_caption_id])
        data_ids = [str((layout_pill.get(k) or {}).get("identifier")) for k in _DATA_REF_KEYS
                    if layout_pill.get(k)]
        _register_data_refs(slide_component, new_image_id, data_ids)
        style_id = str((layout_pill.get("style") or {}).get("identifier") or "")
        if style_id:
            style_member = id_to_file.get(style_id)
            if style_member is None:
                raise OfflineWriteRefused(f"slide {ordinal}: style {style_id} unresolved")
            if style_member != slide_member:
                style_component = component_for_member(style_member)
                _register_style_ext_ref(slide_component, style_id, str(style_component["identifier"]))

        touched.add(slide_member)
        touched.add(_METADATA_MEMBER)
        result.minted += 1
        result.edited_ids[ordinal] = new_image_id

    edits: dict[str, bytes] = {}
    for member in touched:
        d = decoded[member]
        new_bytes = IWAFile.from_dict(copy.deepcopy(d)).to_buffer()
        try:
            IWAFile.from_buffer(new_bytes, member)
        except Exception as exc:  # noqa: BLE001 -- any re-encode failure refuses, source untouched
            raise OfflineWriteRefused(f"member {member} failed to re-encode/reparse: {exc}") from exc
        edits[member] = new_bytes

    shutil.copy2(key_path, out_path)
    try:
        _rewrite_members(out_path, edits)
    except OfflineWriteCorrupted:
        raise
    except Exception as exc:  # noqa: BLE001 -- rewrite failure refuses; out_path is a copy, source untouched
        raise OfflineWriteRefused(f"rewrite failed: {exc}") from exc

    result.members = sorted(edits)
    _verify(out_path, slides)
    result.applied = result.reused + result.minted
    return result


def _verify(out_path: Path, slides: Mapping[int, PillSpec]) -> None:
    objects, id_to_file, _file_ids = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    for ordinal, spec in slides.items():
        slide_id, _skipped = order[ordinal - 1]
        slide = objects[slide_id]
        records = compose_geometry(slide, objects)
        data_id = None
        layout_id = str(slide["templateSlide"]["identifier"])
        _lp_id, layout_pill = _find_media_pill(objects, objects[layout_id])
        if layout_pill is not None:
            data_id = str((layout_pill.get("data") or {}).get("identifier") or "")
        pills = [
            r for r in records
            if r["kind"] == "image" and str((objects.get(r["id"]) or {}).get("data", {}).get("identifier")) == data_id
        ]
        if len(pills) != 1:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read shows {len(pills)} pills, expected 1")
        rec = pills[0]
        width = float(spec.width)
        if abs(rec["x"] - _FRAME_X) > 0.02 or abs(rec["w"] - width) > 0.02:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read frame {rec} fails the mask law for width {width}")
        expected_y = _LAYOUT_FRAME_Y[spec.layout]
        if abs(rec["y"] - expected_y) > 0.02:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read frame y {rec['y']} != {expected_y}")
        pill_id = rec["id"]
        mask_id = str((objects[pill_id].get("mask") or {}).get("identifier"))
        mask_geom = (objects[mask_id]["super"] or {}).get("geometry") or {}
        if not _mask_law_ok(mask_geom, width):
            raise OfflineWriteRefused(f"slide {ordinal}: re-read mask geometry {mask_geom} fails the mask law")
