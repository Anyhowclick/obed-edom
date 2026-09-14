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
_MASK_PATH_TYPE = "kTSDRoundedRectangle"
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


@dataclass
class _Expected:
    """What `_verify` must find for one ordinal, threaded through from the write so it
    does not have to re-derive which path was taken -- or which drawable is the pill --
    from the re-read deck alone. `pill_id` identifies the pill by id, never by data id
    alone: an unrelated content image can legitimately share the pill's data id.
    `fingerprint` is the pill's own complete immutable fingerprint (raw geometry incl.
    angle, originalSize, media naturalSize, style reference) captured pre-write, for
    proving after reread that ONLY the mask changed. The mint-path fields below carry the
    exact metadata registration `_verify` must find -- in that one target component, not
    anywhere in the package."""
    width: float
    layout: str
    pill_id: str
    fingerprint: dict | None = None
    minted_ids: list[str] | None = None  # [image, mask, title, caption] iff the mint path ran
    minted_types: list[str] | None = None  # _pbtype per minted_ids entry
    target_component_id: str | None = None
    expected_data_ids: list[str] | None = None
    style_ref: tuple[str, str] | None = None  # (style_id, style_component_id) iff cross-component
    final_counter: str | None = None


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


def _mask_full_law_ok(mask_obj: dict, width: float) -> bool:
    """Full mask law: geometry (incl. the 180 deg angle) AND the pathsource's tracked
    naturalSize/scalar -- the render-derived fields `_mask_law_ok` alone does not see."""
    geom = (mask_obj.get("super") or {}).get("geometry") or {}
    if not _mask_law_ok(geom, width):
        return False
    if abs(float(geom.get("angle", -1)) - 180.0) > 0.01:
        return False
    sps = ((mask_obj.get("pathsource") or {}).get("scalarPathSource") or {})
    ns = sps.get("naturalSize") or {}
    return (
        abs(float(ns.get("width", -1)) - width) <= 0.01
        and abs(float(ns.get("height", -1)) - _MASK_H) <= 0.01
        and abs(float(sps.get("scalar", -1)) - _MASK_SCALAR) <= 0.01
    )


def _points_match(a: dict | None, b: dict | None, *, keys: tuple[str, str]) -> bool:
    a, b = a or {}, b or {}
    ka, kb = keys
    try:
        return (
            abs(float(a.get(ka, -1)) - float(b.get(ka, -2))) <= 0.01
            and abs(float(a.get(kb, -1)) - float(b.get(kb, -2))) <= 0.01
        )
    except (TypeError, ValueError):
        return False


def _sizes_match(a: dict | None, b: dict | None) -> bool:
    return _points_match(a, b, keys=("width", "height"))


def _positions_match(a: dict | None, b: dict | None) -> bool:
    return _points_match(a, b, keys=("x", "y"))


def _pill_fingerprint_matches(image_obj: dict, mask_obj: dict, layout_pill: dict, layout_mask: dict) -> bool:
    """The complete layout-pill fingerprint an untagged same-data-id candidate must carry
    to be eligible for reuse: image geometry (incl. the 180 deg angle), `originalSize`,
    the media's own `naturalSize`, mask type/scalar 15.0, and style -- all equal to the
    resolved layout's own Media drawable. A candidate failing this is refused, never
    rewritten (an unrelated content image sharing a data id must not be touched)."""
    img_geom = (image_obj.get("super") or {}).get("geometry") or {}
    layout_geom = (layout_pill.get("super") or {}).get("geometry") or {}
    if not (
        _positions_match(img_geom.get("position"), layout_geom.get("position"))
        and _sizes_match(img_geom.get("size"), layout_geom.get("size"))
        and abs(float(img_geom.get("angle", -1)) - float(layout_geom.get("angle", -2))) <= 0.01
        and abs(float(img_geom.get("angle", -1)) - 180.0) <= 0.01
    ):
        return False
    if not _sizes_match(image_obj.get("originalSize"), layout_pill.get("originalSize")):
        return False
    if not _sizes_match(image_obj.get("naturalSize"), layout_pill.get("naturalSize")):
        return False
    if str((image_obj.get("style") or {}).get("identifier") or "") != str(
        (layout_pill.get("style") or {}).get("identifier") or ""
    ):
        return False
    mask_sps = ((mask_obj.get("pathsource") or {}).get("scalarPathSource") or {})
    layout_mask_sps = ((layout_mask.get("pathsource") or {}).get("scalarPathSource") or {})
    if (
        str(mask_sps.get("type") or "") != _MASK_PATH_TYPE
        or str(layout_mask_sps.get("type") or "") != _MASK_PATH_TYPE
    ):
        return False
    try:
        if abs(float(mask_sps.get("scalar", -1)) - _MASK_SCALAR) > 0.01:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _image_fingerprint(image_obj: dict) -> dict:
    """The pill's complete immutable fingerprint: raw geometry (incl. angle), the two
    size fields, and the style reference -- everything a reuse/mint write must leave
    untouched. Captured pre-write and re-checked after reread (see `_fingerprints_match`)
    so a changed raw geometry that still composes to the expected frame is caught."""
    geom = (image_obj.get("super") or {}).get("geometry") or {}
    return {
        "position": dict(geom.get("position") or {}),
        "size": dict(geom.get("size") or {}),
        "angle": geom.get("angle"),
        "originalSize": dict(image_obj.get("originalSize") or {}),
        "naturalSize": dict(image_obj.get("naturalSize") or {}),
        "style": str((image_obj.get("style") or {}).get("identifier") or ""),
    }


def _fingerprints_match(a: dict, b: dict) -> bool:
    try:
        angle_ok = abs(float(a.get("angle", -1)) - float(b.get("angle", -2))) <= 0.01
    except (TypeError, ValueError):
        angle_ok = False
    return (
        _positions_match(a.get("position"), b.get("position"))
        and _sizes_match(a.get("size"), b.get("size"))
        and angle_ok
        and _sizes_match(a.get("originalSize"), b.get("originalSize"))
        and _sizes_match(a.get("naturalSize"), b.get("naturalSize"))
        and a.get("style") == b.get("style")
    )


def _resolve_slide_media_candidates(
    objects: dict[str, dict], slide: dict, data_id: str, layout_pill: dict, layout_mask: dict | None
) -> list[str]:
    """Reuse-eligible pills on `slide`: a `Media`-tagged image using `data_id`, or an
    untagged same-`data_id` image whose fingerprint matches the resolved layout's own
    Media drawable exactly (see `_pill_fingerprint_matches`). An unrelated content image
    that merely shares the data id -- tagged or not -- is never a candidate."""
    tags = _sage_tags(slide)
    owned = [str(r["identifier"]) for r in (slide.get("ownedDrawables") or [])]
    found: list[str] = []
    for oid in owned:
        obj = objects.get(oid) or {}
        if obj.get("_pbtype") != _IMAGE_PBTYPE:
            continue
        if str((obj.get("data") or {}).get("identifier") or "") != data_id:
            continue
        if tags.get(oid) == _MEDIA_TAG:
            found.append(oid)
            continue
        if layout_mask is None:
            continue
        mask_id = str((obj.get("mask") or {}).get("identifier") or "")
        mask_obj = objects.get(mask_id)
        if mask_obj is not None and _pill_fingerprint_matches(obj, mask_obj, layout_pill, layout_mask):
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
        self._registered_ids: set[str] = set()
        for comp in package_meta.get("components") or []:
            for u in comp.get("objectUuidMapEntries") or []:
                uu = u.get("uuid") or {}
                self._existing_uuids.add((str(uu.get("lower")), str(uu.get("upper"))))
                self._registered_ids.add(str(u.get("identifier")))
            for ref in comp.get("externalReferences") or []:
                self._registered_ids.add(str(ref.get("objectIdentifier")))
            for dref in comp.get("dataReferences") or []:
                self._registered_ids.add(str(dref.get("dataIdentifier")))
                for orl in dref.get("objectReferenceList") or []:
                    self._registered_ids.add(str(orl.get("objectIdentifier")))

    def mint_id(self) -> str:
        while True:
            self._last_id += 1
            cand = str(self._last_id)
            if (
                cand in self._id_to_file or cand in self._objects or cand in self._hor
                or cand in self._registered_ids
            ):
                continue
            self._package_meta["lastObjectIdentifier"] = cand
            return cand

    def mint_uuid(self) -> dict:
        lower, upper = secrets.randbits(64), secrets.randbits(64)
        while (lower, upper) == (0, 0) or (str(lower), str(upper)) in self._existing_uuids:
            lower, upper = secrets.randbits(64), secrets.randbits(64)
        self._existing_uuids.add((str(lower), str(upper)))
        return {"lower": str(lower), "upper": str(upper)}


def _resolve_layout_mask(
    objects: dict[str, dict], id_to_file: dict[str, str], layout_member: str,
    layout_pill_id: str, layout_pill: dict,
) -> dict:
    """The resolved layout's own Media mask, required before any candidate is
    considered: must resolve, live in the layout member, have `super.parent` equal to
    `layout_pill_id`, and use `_MASK_PATH_TYPE`. Any violation refuses -- mutation is
    never authorized off an invalid layout source."""
    mask_id = str((layout_pill.get("mask") or {}).get("identifier") or "")
    mask_obj = objects.get(mask_id)
    if not mask_id or mask_obj is None:
        raise OfflineWriteRefused(f"layout pill {layout_pill_id}: mask {mask_id!r} unresolved")
    if id_to_file.get(mask_id) != layout_member:
        raise OfflineWriteRefused(f"layout pill {layout_pill_id}: mask {mask_id} not in layout member")
    parent_id = str(((mask_obj.get("super") or {}).get("parent") or {}).get("identifier") or "")
    if parent_id != layout_pill_id:
        raise OfflineWriteRefused(
            f"layout pill {layout_pill_id}: mask {mask_id} parent {parent_id!r} != {layout_pill_id!r}"
        )
    sps = (mask_obj.get("pathsource") or {}).get("scalarPathSource") or {}
    if str(sps.get("type") or "") != _MASK_PATH_TYPE:
        raise OfflineWriteRefused(
            f"layout pill {layout_pill_id}: mask {mask_id} pathsource type is not {_MASK_PATH_TYPE!r}"
        )
    return mask_obj


def _mask_exclusively_owned(
    objects: dict[str, dict], id_to_file: dict[str, str], slide_member: str,
    image_id: str, mask_id: str, mask_member: str,
) -> bool:
    """Before a reuse mutates a candidate's mask: the image must live in the target
    slide member, the mask must live in that same member, the mask's own parent must be
    that image (never the layout's mask, never some other drawable's), and no other image
    anywhere in the deck may reference that mask id. Any violation refuses the mutation --
    a mask shared with an unrelated drawable is never touched."""
    if id_to_file.get(image_id) != slide_member:
        return False
    if mask_member != slide_member:
        return False
    mask_obj = objects.get(mask_id) or {}
    parent_id = str(((mask_obj.get("super") or {}).get("parent") or {}).get("identifier") or "")
    if parent_id != image_id:
        return False
    for oid, obj in objects.items():
        if oid == image_id or obj.get("_pbtype") != _IMAGE_PBTYPE:
            continue
        if str((obj.get("mask") or {}).get("identifier") or "") == mask_id:
            return False
    return True


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
            if str(ref.get("componentIdentifier")) != str(style_component_id):
                raise OfflineWriteRefused(
                    f"style {style_id} already registered against component "
                    f"{ref.get('componentIdentifier')!r}, not {style_component_id!r}"
                )
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
    expected: dict[int, _Expected] = {}

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

        layout_mask = _resolve_layout_mask(objects, id_to_file, layout_member, layout_pill_id, layout_pill)

        candidates = _resolve_slide_media_candidates(objects, slide, data_id, layout_pill, layout_mask)
        if len(candidates) > 1:
            raise OfflineWriteRefused(f"slide {ordinal}: {len(candidates)} candidate pills, expected at most 1")

        if candidates:
            # Reuse mutates ONLY the mask fields -- the fingerprint check above already
            # guarantees the image's own geometry equals the resolved layout's.
            image_id = candidates[0]
            image = objects[image_id]
            mask_ref = image.get("mask") or {}
            mask_id = str(mask_ref.get("identifier") or "")
            mask_member = id_to_file.get(mask_id)
            if not mask_id or mask_member is None:
                raise OfflineWriteRefused(f"slide {ordinal}: pill {image_id} has no resolvable mask")
            if not _mask_exclusively_owned(objects, id_to_file, slide_member, image_id, mask_id, mask_member):
                raise OfflineWriteRefused(
                    f"slide {ordinal}: pill {image_id} mask {mask_id} is not exclusively owned by it"
                )

            fingerprint = _image_fingerprint(image)
            mask_arch = _find_archive(get_decoded(mask_member), mask_id)
            mask_obj = mask_arch["objects"][0]
            _apply_mask_fields(mask_obj, width)
            touched.add(mask_member)

            result.reused += 1
            result.edited_ids[ordinal] = image_id
            expected[ordinal] = _Expected(width, spec.layout, image_id, fingerprint=fingerprint)
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
        style_ref = None
        if style_id:
            style_member = id_to_file.get(style_id)
            if style_member is None:
                raise OfflineWriteRefused(f"slide {ordinal}: style {style_id} unresolved")
            if style_member != slide_member:
                style_component = component_for_member(style_member)
                style_component_id = str(style_component["identifier"])
                _register_style_ext_ref(slide_component, style_id, style_component_id)
                style_ref = (style_id, style_component_id)

        touched.add(slide_member)
        touched.add(_METADATA_MEMBER)
        result.minted += 1
        result.edited_ids[ordinal] = new_image_id
        expected[ordinal] = _Expected(
            width, spec.layout, new_image_id,
            fingerprint=_image_fingerprint(new_image_obj),
            minted_ids=[new_image_id, new_mask_id, new_title_id, new_caption_id],
            minted_types=[
                new_image_obj.get("_pbtype"), new_mask_obj.get("_pbtype"),
                new_title_obj.get("_pbtype"), new_caption_obj.get("_pbtype"),
            ],
            target_component_id=str(slide_component["identifier"]),
            expected_data_ids=data_ids,
            style_ref=style_ref,
        )

    final_counter = str(minter._last_id)
    for exp in expected.values():
        if exp.minted_ids is not None:
            exp.final_counter = final_counter

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
    _verify(out_path, expected)
    result.applied = result.reused + result.minted
    return result


def _verify(out_path: Path, expected: Mapping[int, "_Expected"]) -> None:
    objects, id_to_file, _file_ids = _load_deck_full(out_path)[:3]
    order = slide_order(objects)
    meta_decoded = None
    package_meta = None
    with zipfile.ZipFile(out_path) as zf:
        if _METADATA_MEMBER in set(zf.namelist()):
            meta_decoded = IWAFile.from_buffer(zf.read(_METADATA_MEMBER), _METADATA_MEMBER).to_dict()
    if meta_decoded is not None:
        meta_arch = _find_package_metadata_archive(meta_decoded)
        package_meta = meta_arch["objects"][0] if meta_arch is not None else None

    for ordinal, exp in expected.items():
        slide_id, _skipped = order[ordinal - 1]
        slide = objects[slide_id]
        records = compose_geometry(slide, objects)
        layout_id = str(slide["templateSlide"]["identifier"])
        _lp_id, layout_pill = _find_media_pill(objects, objects[layout_id])
        data_id = str((layout_pill.get("data") or {}).get("identifier") or "") if layout_pill else None
        layout_mask_id = str((layout_pill.get("mask") or {}).get("identifier") or "") if layout_pill else None
        layout_mask = objects.get(layout_mask_id) if layout_pill else None
        pills = [r for r in records if r["kind"] == "image" and str(r["id"]) == exp.pill_id]
        if len(pills) != 1:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read shows {len(pills)} pill(s) for {exp.pill_id}, expected 1")
        rec = pills[0]
        if str((objects.get(rec["id"]) or {}).get("data", {}).get("identifier")) != data_id:
            raise OfflineWriteRefused(f"slide {ordinal}: pill {exp.pill_id} data id no longer matches the layout")
        width = exp.width
        if abs(rec["x"] - _FRAME_X) > 0.02 or abs(rec["w"] - width) > 0.02:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read frame {rec} fails the mask law for width {width}")
        expected_y = _LAYOUT_FRAME_Y[exp.layout]
        if abs(rec["y"] - expected_y) > 0.02:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read frame y {rec['y']} != {expected_y}")

        pill_id = rec["id"]
        image_obj = objects[pill_id]
        mask_id = str((image_obj.get("mask") or {}).get("identifier"))
        mask_obj = objects.get(mask_id)
        if mask_obj is None:
            raise OfflineWriteRefused(f"slide {ordinal}: re-read mask {mask_id} unresolved")
        if not _mask_full_law_ok(mask_obj, width):
            raise OfflineWriteRefused(
                f"slide {ordinal}: re-read mask {mask_id} fails the full mask law for width {width}"
            )
        if exp.fingerprint is not None and not _fingerprints_match(exp.fingerprint, _image_fingerprint(image_obj)):
            raise OfflineWriteRefused(
                f"slide {ordinal}: re-read pill {pill_id} image fingerprint changed -- only the mask may change"
            )
        mask_sps = (mask_obj.get("pathsource") or {}).get("scalarPathSource") or {}
        if str(mask_sps.get("type") or "") != _MASK_PATH_TYPE:
            raise OfflineWriteRefused(
                f"slide {ordinal}: re-read mask {mask_id} pathsource type is not {_MASK_PATH_TYPE!r}"
            )
        if layout_mask is None:
            raise OfflineWriteRefused(f"slide {ordinal}: layout mask {layout_mask_id} unresolved")
        layout_mask_sps = (layout_mask.get("pathsource") or {}).get("scalarPathSource") or {}
        if str(layout_mask_sps.get("type") or "") != _MASK_PATH_TYPE:
            raise OfflineWriteRefused(
                f"slide {ordinal}: layout mask {layout_mask_id} pathsource type is not {_MASK_PATH_TYPE!r}"
            )

        if exp.minted_ids is None:
            continue

        # Mint path: both drawable lists carry the new image id identically, and the
        # slide's metadata component registered every minted id.
        new_image_id = exp.minted_ids[0]
        if new_image_id != pill_id:
            raise OfflineWriteRefused(f"slide {ordinal}: minted id {new_image_id} != resolved pill {pill_id}")
        owned = [str(r["identifier"]) for r in (slide.get("ownedDrawables") or [])]
        z_order = [str(r["identifier"]) for r in (slide.get("drawablesZOrder") or [])]
        if owned.count(new_image_id) != 1 or z_order.count(new_image_id) != 1:
            raise OfflineWriteRefused(
                f"slide {ordinal}: minted pill {new_image_id} not registered identically in "
                f"ownedDrawables ({owned.count(new_image_id)}) and drawablesZOrder ({z_order.count(new_image_id)})"
            )
        # Mint object graph: all four archives live in the slide member with the
        # expected types, image->mask/title/caption and mask->image are exactly the
        # minted ids, and the mask is (still) exclusively owned by the minted image.
        minted_mask_id, minted_title_id, minted_caption_id = exp.minted_ids[1:4]
        minted_types = exp.minted_types or [None, None, None, None]
        minted_labels = ("image", "mask", "title", "caption")
        slide_member = id_to_file.get(slide_id)
        for label, nid, ntype in zip(minted_labels, exp.minted_ids, minted_types):
            nobj = objects.get(nid)
            if nobj is None:
                raise OfflineWriteRefused(f"slide {ordinal}: minted {label} archive {nid} unresolved on re-read")
            if id_to_file.get(nid) != slide_member:
                raise OfflineWriteRefused(f"slide {ordinal}: minted {label} archive {nid} not in the slide member")
            if ntype is not None and nobj.get("_pbtype") != ntype:
                raise OfflineWriteRefused(
                    f"slide {ordinal}: minted {label} archive {nid} is {nobj.get('_pbtype')!r}, expected {ntype!r}"
                )
        image_title_id = str((image_obj.get("super") or {}).get("title", {}).get("identifier") or "")
        image_caption_id = str((image_obj.get("super") or {}).get("caption", {}).get("identifier") or "")
        if mask_id != minted_mask_id or image_title_id != minted_title_id or image_caption_id != minted_caption_id:
            raise OfflineWriteRefused(
                f"slide {ordinal}: minted pill {new_image_id} references mask={mask_id!r} "
                f"title={image_title_id!r} caption={image_caption_id!r}, expected "
                f"mask={minted_mask_id!r} title={minted_title_id!r} caption={minted_caption_id!r}"
            )
        mask_parent_id = str(((mask_obj.get("super") or {}).get("parent") or {}).get("identifier") or "")
        if mask_parent_id != new_image_id:
            raise OfflineWriteRefused(
                f"slide {ordinal}: minted mask {mask_id} parent {mask_parent_id!r} != {new_image_id!r}"
            )
        mask_member = id_to_file.get(mask_id)
        if not _mask_exclusively_owned(objects, id_to_file, slide_member, new_image_id, mask_id, mask_member):
            raise OfflineWriteRefused(
                f"slide {ordinal}: minted mask {mask_id} is not exclusively owned by pill {new_image_id}"
            )

        if package_meta is None:
            raise OfflineWriteRefused(f"slide {ordinal}: no package metadata to verify mint registration")

        target_component = None
        for comp in package_meta.get("components") or []:
            if str(comp.get("identifier")) == exp.target_component_id:
                target_component = comp
                break
        if target_component is None:
            raise OfflineWriteRefused(
                f"slide {ordinal}: target metadata component {exp.target_component_id} not found"
            )

        registered_uuid_ids_raw = [
            str(u.get("identifier")) for u in target_component.get("objectUuidMapEntries") or []
        ]
        for nid in exp.minted_ids:
            count = registered_uuid_ids_raw.count(nid)
            if count != 1:
                raise OfflineWriteRefused(
                    f"slide {ordinal}: minted id {nid} has {count} objectUuidMapEntries in "
                    f"component {exp.target_component_id}, expected exactly 1"
                )

        data_entries_raw = target_component.get("dataReferences") or []
        for did in exp.expected_data_ids or []:
            matching_entries = [d for d in data_entries_raw if str(d.get("dataIdentifier")) == did]
            if len(matching_entries) != 1:
                raise OfflineWriteRefused(
                    f"slide {ordinal}: data id {did} has {len(matching_entries)} dataReferences entries "
                    f"in component {exp.target_component_id}, expected exactly 1"
                )
            refs_raw = matching_entries[0].get("objectReferenceList") or []
            matching_refs = [r for r in refs_raw if str(r.get("objectIdentifier")) == new_image_id]
            if len(matching_refs) != 1 or int(matching_refs[0].get("count", -1)) != 1:
                raise OfflineWriteRefused(
                    f"slide {ordinal}: data id {did} does not have an exact "
                    f"{{objectIdentifier: {new_image_id}, count: 1}} registration in "
                    f"component {exp.target_component_id}"
                )

        if exp.style_ref is not None:
            style_id, style_component_id = exp.style_ref
            ext_refs = target_component.get("externalReferences") or []
            matching_ext_refs = [r for r in ext_refs if str(r.get("objectIdentifier")) == style_id]
            if (
                len(matching_ext_refs) != 1
                or str(matching_ext_refs[0].get("componentIdentifier")) != style_component_id
            ):
                raise OfflineWriteRefused(
                    f"slide {ordinal}: style {style_id} external reference is not exactly one "
                    f"non-conflicting reference to component {style_component_id} in "
                    f"component {exp.target_component_id}"
                )

        if str(package_meta.get("lastObjectIdentifier")) != exp.final_counter:
            raise OfflineWriteRefused(
                f"slide {ordinal}: persisted lastObjectIdentifier "
                f"{package_meta.get('lastObjectIdentifier')!r} != expected {exp.final_counter!r}"
            )
