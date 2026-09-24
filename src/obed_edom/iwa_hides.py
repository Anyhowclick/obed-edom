"""Offline deletion of pass-1 hide targets from a saved .key (``patch_deck_hides``).

One strict whole-deck decode, pure per-slide planning over it (any failure refuses that
slide only, its member byte-identical), one ``_rewrite_members`` that also drops orphaned
``Data/`` members, then one batched read-back of the touched members plus Metadata.
Rules R1-R8 and invariants I1-I6: ``.agents/plans/pass1_hides_offline.plan.md`` §Writer.
"""
from __future__ import annotations

import copy
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from keynote_parser.codec import IWAFile, import_version

from obed_edom.iwa_kindindex import (
    KIND_ORDER,
    TEXT_PLACEHOLDER_SLACK,
    derive_kind_index,
    derived_kind_counts,
    reconcile_counts,
)
from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import (
    _group_child_signature,
    _normalize_text,
    slide_order,
)
from obed_edom.iwa_write import (
    _METADATA_MEMBER,
    _PACKAGE_METADATA_PBTYPE,
    _archive_diff,
    _archives_by_id,
    _archives_equal,
    _decode_apply_reencode_diff,
    _member_locator,
    _rewrite_members,
    OfflineWriteCorrupted,
    OfflineWriteRefused,
    expected_base_counts,
)
from obed_edom.map_remap import is_placeholder_text
from obed_edom.offline_inspect import _build_data_index, _data_identifier, data_member_index

_HIDE_PBTYPES = frozenset(
    {"TSWP.ShapeInfoArchive", "TSD.ImageArchive", "TSD.MovieArchive", "TSD.GroupArchive"}
)
_SLIDE_LIST_FIELDS = frozenset({"drawablesZOrder", "ownedDrawables"})
_HEADER = "<header>"


@dataclass
class SlideHides:
    deleted: int = 0
    refused: bool = False
    reason: str | None = None
    removed_ids: list[str] = field(default_factory=list)
    order_proven: bool = False


@dataclass
class HidesResult:
    slides: dict[int, SlideHides] = field(default_factory=dict)
    dropped_data: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)


class HidesWriteFailed(Exception):
    """Raised once the deck has been (or may have been) written and a later step failed
    (read-back, ``verify``, or the rewrite after its copy-back): the deck's state is unknown."""


class _Refuse(Exception):
    pass


@dataclass
class _Model:
    archives: dict[str, dict]
    member_of: dict[str, str]
    member_ids: dict[str, list[str]]
    duplicates: dict[str, list[str]]
    package_metadata_members: list[str]
    objects: dict[str, dict]
    namelist: list[str]


@dataclass
class _Plan:
    slide_id: str
    member: str
    hide_ids: list[str]
    subtree: set[str]
    data_ids: set[str]
    component_id: str
    post_i3: Counter
    post_i4: set
    expected_order: list[str]
    new_bytes: bytes | None = None


def _load_model(zf: zipfile.ZipFile) -> _Model:
    archives: dict[str, dict] = {}
    member_of: dict[str, str] = {}
    member_ids: dict[str, list[str]] = {}
    duplicates: dict[str, list[str]] = {}
    package_metadata_members: list[str] = []
    namelist = zf.namelist()
    for name in namelist:
        if not name.endswith(".iwa"):
            continue
        try:
            decoded = IWAFile.from_buffer(zf.read(name), name).to_dict()
        except Exception as exc:
            raise OfflineWriteRefused(f"member {name} is undecodable: {exc!r}") from exc
        ids = member_ids.setdefault(name, [])
        for chunk in decoded["chunks"]:
            for arch in chunk["archives"]:
                aid = str(arch["header"]["identifier"])
                ids.append(aid)
                package_metadata_members.extend(
                    name for o in arch.get("objects") or [] if o.get("_pbtype") == _PACKAGE_METADATA_PBTYPE)
                if aid in archives:
                    duplicates.setdefault(aid, [member_of[aid]]).append(name)
                    continue
                archives[aid] = arch
                member_of[aid] = name
    objects = {aid: arch["objects"][0] for aid, arch in archives.items() if arch.get("objects")}
    return _Model(archives, member_of, member_ids, duplicates, package_metadata_members, objects, namelist)


def _require_unambiguous_package(model: _Model, exc_type: type[Exception]) -> None:
    if model.duplicates:
        aid, members = next(iter(sorted(model.duplicates.items())))
        raise exc_type(f"{len(model.duplicates)} duplicate archive id(s), e.g. {aid} in {members}")
    if model.package_metadata_members != [_METADATA_MEMBER]:
        raise exc_type(f"{_PACKAGE_METADATA_PBTYPE} found in {model.package_metadata_members}, "
                       f"need exactly one in {_METADATA_MEMBER}")


def _header_refs(header: dict) -> list[str]:
    out: list[str] = []
    for mi in header.get("messageInfos") or []:
        out.extend(str(r) for r in mi.get("objectReferences") or [])
        for fi in mi.get("fieldInfos") or []:
            out.extend(str(r) for r in fi.get("objectReferences") or [])
    return out


def _header_data_refs(header: dict) -> list[str]:
    out: list[str] = []
    for mi in header.get("messageInfos") or []:
        out.extend(str(r) for r in mi.get("dataReferences") or [])
        for fi in mi.get("fieldInfos") or []:
            out.extend(str(r) for r in fi.get("dataReferences") or [])
    return out


def _walk_refs(value: Any, ids: list[str], uuids: list[tuple[str, str]] | None) -> None:
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            ident = v.get("identifier")
            if ident is not None and not isinstance(ident, (dict, list)):
                ids.append(str(ident))
            if uuids is not None and "lower" in v and "upper" in v:
                uuids.append((str(v["lower"]), str(v["upper"])))
            stack.extend(x for x in v.values() if isinstance(x, (dict, list)))
        elif isinstance(v, list):
            stack.extend(x for x in v if isinstance(x, (dict, list)))


def _body_refs(arch: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, obj in enumerate(arch.get("objects") or []):
        for key, value in obj.items():
            ids: list[str] = []
            _walk_refs(value, ids, None)
            where = key if i == 0 else f"#{i}.{key}"
            out.extend((where, t) for t in ids)
    return out


def _scan(
    model: _Model, targets: set[str], pm_id: str | None,
) -> tuple[dict[str, list[tuple[str, str]]], dict[tuple[str, str], list[str]]]:
    referrers: dict[str, list[tuple[str, str]]] = {}
    uuid_refs: dict[tuple[str, str], list[str]] = {}
    for aid, arch in model.archives.items():
        if aid == pm_id:
            continue
        for t in _header_refs(arch["header"]):
            if t in targets:
                referrers.setdefault(t, []).append((aid, _HEADER))
        outside_meta = model.member_of[aid] != _METADATA_MEMBER
        for i, obj in enumerate(arch.get("objects") or []):
            for key, value in obj.items():
                ids: list[str] = []
                uuids: list[tuple[str, str]] = []
                _walk_refs(value, ids, uuids if outside_meta else None)
                where = key if i == 0 else f"#{i}.{key}"
                for t in ids:
                    if t in targets:
                        referrers.setdefault(t, []).append((aid, where))
                for u in uuids:
                    uuid_refs.setdefault(u, []).append(aid)
    return referrers, uuid_refs


def _package_metadata(decoded_or_model: Any) -> tuple[str, dict] | tuple[None, None]:
    if isinstance(decoded_or_model, _Model):
        for aid in decoded_or_model.member_ids.get(_METADATA_MEMBER, []):
            obj = decoded_or_model.objects.get(aid)
            if obj is not None and obj.get("_pbtype") == _PACKAGE_METADATA_PBTYPE:
                return aid, obj
        return None, None
    for aid, arch in _archives_by_id(decoded_or_model).items():
        objs = arch.get("objects") or []
        if objs and objs[0].get("_pbtype") == _PACKAGE_METADATA_PBTYPE:
            return aid, objs[0]
    return None, None


def _components_by_member(pm: dict, members: list[str]) -> dict[str, dict]:
    by_locator: dict[str, list[dict]] = {}
    for comp in pm.get("components") or []:
        loc = comp.get("locator") or comp.get("preferredLocator")
        if loc is not None:
            by_locator.setdefault(loc, []).append(comp)
    out: dict[str, dict] = {}
    for m in members:
        matches = by_locator.get(_member_locator(m), [])
        if len(matches) == 1:
            out[m] = matches[0]
    return out


def _stored_i3(comp: dict) -> Counter:
    return Counter(
        (str(e.get("dataIdentifier")), str(o.get("objectIdentifier")), int(o.get("count", 0)))
        for e in comp.get("dataReferences") or []
        for o in e.get("objectReferenceList") or []
    )


def _stored_i4(comp: dict) -> Counter:
    return Counter(
        (str(e.get("componentIdentifier")),
         str(e["objectIdentifier"]) if e.get("objectIdentifier") is not None else None)
        for e in comp.get("externalReferences") or []
        if not e.get("isWeak")
    )


def _recompute_tables(
    headers: dict[str, dict], member: str, member_of: dict[str, str], comp_of_member: dict[str, dict],
) -> tuple[Counter, set]:
    i3: Counter = Counter()
    i4: set = set()
    for aid, header in headers.items():
        for data_id, count in Counter(_header_data_refs(header)).items():
            i3[(data_id, aid, count)] += 1
        for t in _header_refs(header):
            tm = member_of.get(t)
            if tm is None or tm == member:
                continue
            comp = comp_of_member.get(tm)
            if comp is None:
                raise _Refuse(f"archive {aid} references {t} in {tm}, which has no component")
            comp_id = str(comp.get("identifier"))
            i4.add((comp_id, None if t == comp_id else t))
    return i3, i4


def _check_tables(comp: dict, i3: Counter, i4: set, where: str) -> None:
    if _stored_i3(comp) != i3:
        raise _Refuse(f"{where}: component dataReferences != recompute (I3)")
    if _stored_i4(comp) != Counter(i4):
        raise _Refuse(f"{where}: component externalReferences != recompute (I4)")


def _identity_check(
    records: list[dict], items: list[dict], objects: dict[str, dict],
    data_index: dict[str, str], group_text: dict[int, str] | None, cache: dict,
) -> None:
    derived_by_kind = {k: [r for r in records if r["kind"] == k] for k in KIND_ORDER}
    for kind in KIND_ORDER:
        derived = derived_by_kind[kind]
        payload = sorted(
            (it for it in items if (it.get("kind") or "") == kind),
            key=lambda it: int(it.get("kindIndex", -1)),
        )
        if [int(it.get("kindIndex", -1)) for it in payload] != list(range(len(payload))):
            raise _Refuse(f"payload {kind} kindIndex is not 0..n-1")
        extra = payload[len(derived):]
        if len(payload) < len(derived) or (extra and (
            kind != "text" or len(extra) > TEXT_PLACEHOLDER_SLACK
            or not all(is_placeholder_text(it) for it in extra)
        )):
            raise _Refuse(f"payload has {len(payload)} {kind} items, deck has {len(derived)}")
        for rec, item in zip(derived, payload):
            ki = rec["kindIndex"]
            if kind in ("text", "shape"):
                if _normalize_text(rec.get("text")) != _normalize_text(item.get("text")):
                    raise _Refuse(f"{kind} {ki} text differs from the payload")
            elif kind in ("image", "movie"):
                did = _data_identifier(objects.get(rec["id"]) or {})
                name = data_index.get(did) if did is not None else None
                if (name or "") != (item.get("fileName") or ""):
                    raise _Refuse(f"{kind} {ki} file {name!r} != payload {item.get('fileName')!r}")
            elif kind == "group" and group_text is not None:
                want = group_text.get(ki)
                if want is None or _group_child_signature(rec["id"], objects, cache) != want:
                    raise _Refuse(f"group {ki} child-text signature differs from the payload")


_GEOM_TOL = 1.0


def _content_signature(
    rec: dict, objects: dict[str, dict], data_index: dict[str, str], group_text: dict[int, str] | None, cache: dict,
) -> str | None:
    """The identity ``_identity_check`` verified against the source; ``None`` = unverified."""
    kind = rec["kind"]
    if kind in ("text", "shape"):
        return _normalize_text(rec.get("text"))
    if kind in ("image", "movie"):
        did = _data_identifier(objects.get(rec["id"]) or {})
        return data_index.get(did) if did is not None else None
    if kind == "group" and group_text is not None:
        return _group_child_signature(rec["id"], objects, cache)
    return None


def _rect(d: dict | None) -> tuple[float, ...] | None:
    try:
        return tuple(float(d[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return None


def _near(a: tuple[float, ...] | None, b: tuple[float, ...] | None) -> bool:
    return a is not None and b is not None and all(abs(p - q) <= _GEOM_TOL for p, q in zip(a, b))


def _check_unambiguous(
    records: list[dict], hides: list[dict], items: list[dict], slide: dict,
    objects: dict[str, dict], data_index: dict[str, str], group_text: dict[int, str] | None, cache: dict,
) -> None:
    """A hide whose content class (same kind and signature; lines and unresolved content
    match everything of their kind) holds a survivor must be the only class member whose
    saved geometry matches the hide's payload geometry; otherwise a twin swap is invisible."""
    hide_keys = {(str(h.get("kind")), int(h.get("kindIndex", -1))) for h in hides}
    sigs = {(r["kind"], r["kindIndex"]): _content_signature(r, objects, data_index, group_text, cache)
            for r in records}
    composed = {(r["kind"], r["kindIndex"]): r for r in compose_geometry(slide, objects)}
    geom = {k: _rect(r) for k, r in composed.items()}
    payload = {(str(it.get("kind")), int(it.get("kindIndex", -1))): it for it in items}
    for key in sorted(hide_keys):
        sig = sigs[key]
        survivors = [k for k in sigs if k[0] == key[0] and k not in hide_keys
                     and (sig is None or sigs[k] is None or sigs[k] == sig)]
        if not survivors:
            continue
        competing = [k for k in sigs if k[0] == key[0] and (sig is None or sigs[k] is None or sigs[k] == sig)]
        approximate = {f"{k[0]} {k[1]}": composed[k]["needs_keynote"]
                       for k in competing if (composed.get(k) or {}).get("needs_keynote")}
        if approximate:
            raise _Refuse(f"{key[0]} {key[1]} has a survivor twin and approximate saved geometry {approximate}")
        want = _rect(payload.get(key))
        if not _near(geom.get(key), want) or any(_near(geom.get(k), want) for k in survivors):
            raise _Refuse(f"{key[0]} {key[1]} has a survivor twin that geometry cannot tell apart")


_APPROXIMABLE_KINDS = frozenset({"text", "image", "movie", "group"})


def pre_deferral_twin_risk(
    items: list[dict], hide_keys: set[tuple[str, int]], group_text: dict | None,
    *, planned: dict[tuple[str, int], dict] | None = None,
) -> set[tuple[str, int]]:
    """Hide keys ``_check_unambiguous`` could refuse after the save.

    A hide is at risk when its twin class (the writer's signature, from the payload) holds
    a survivor and either a member whose saved geometry may be approximate, or a member
    pass 1 writes BEFORE the hide stage. ``planned`` keys every such pre-hide write
    (``{(kind, kindIndex): {...}}``, any keys or none; empty for slides whose pass-1
    geometry is suppressed): until the projection is proven, any write can move a survivor
    onto the hide's source rectangle, so its class is excluded. Offline-read items carry
    the reader's ``needsKeynote``; payloads without it count every kind the composer can
    flag (text, image, movie, group) as approximate.
    """
    def sig(item: dict) -> str | None:
        kind = str(item.get("kind") or "")
        if kind in ("text", "shape"):
            return _normalize_text(item.get("text"))
        if kind in ("image", "movie"):
            return item.get("fileName") or None
        if kind == "group" and group_text is not None:
            return group_text.get(int(item.get("kindIndex", -1)))
        return None

    flagged = bool(items) and all("needsKeynote" in it for it in items)
    written = set(planned or ())
    by_key = {(str(it.get("kind") or ""), int(it.get("kindIndex", -1))): it for it in items}
    sigs = {k: sig(it) for k, it in by_key.items()}

    def approximate(key: tuple[str, int]) -> bool:
        item = by_key[key]
        if not flagged:
            return key[0] in _APPROXIMABLE_KINDS
        return bool(item.get("needsKeynote"))

    risky: set[tuple[str, int]] = set()
    for key in hide_keys:
        if key not in sigs:
            risky.add(key)
            continue
        s = sigs[key]
        twins = [k for k, v in sigs.items() if k[0] == key[0] and (s is None or v is None or v == s)]
        if any(k not in hide_keys for k in twins) and any(k in written or approximate(k) for k in twins):
            risky.add(key)
    return risky


_STRONG_REF_FIELDS = frozenset({
    "children", "ownedStorage", "deprecatedStorage", "mask", "fakeShapeForEmptyGroup",
    "title", "caption", "drawable", "containedStorage", "calloutSubStorages", "subStorages",
})
_WEAK_REF_FIELDS = frozenset({"parent", "style", "styleSheet", "stylesheet"})
_FORBIDDEN_REF_FIELDS = frozenset({
    "comment", "pencilAnnotations", "commentStorage", "pencilAnnotationStorage", "author", "replies",
    "textFlow",
})
_STRONG_TABLES = frozenset({"tableAttachment", "tableFootnote"})
_FORBIDDEN_TABLES = frozenset({
    "tableHighlight", "tableOverlappingHighlight", "tablePencilAnnotation", "tableInsertion", "tableDeletion",
})
_STORAGE_TABLE_REF = re.compile(r"(?:^|\.)(table\w+)\.entries\.(?:object|field)$")


_REFERENCE_TYPE = "TSP.Reference"
_FORBIDDEN_ARCHIVE_TYPE = re.compile(r"Comment|Highlight|PencilAnnotation|Change")


def _descriptor_refs(obj: dict, descriptor: Any, path: str, out: list[tuple[str, str]], unknown: list[str]) -> None:
    for key, value in obj.items():
        if key == "_pbtype":
            continue
        p = f"{path}.{key}" if path else key
        fd = descriptor.fields_by_camelcase_name.get(key)
        if fd is None or fd.message_type is None:
            ids: list[str] = []
            _walk_refs(value, ids, None)
            if fd is None and ids:
                unknown.append(p)
            continue
        values = value if isinstance(value, list) else [value]
        if fd.message_type.full_name == _REFERENCE_TYPE:
            out.extend((p, str(v["identifier"])) for v in values
                       if isinstance(v, dict) and v.get("identifier") is not None)
            continue
        for v in values:
            if isinstance(v, dict):
                _descriptor_refs(v, fd.message_type, p, out, unknown)


def _archive_refs(arch: dict) -> list[tuple[str, str]]:
    """Descriptor-confirmed body refs of every object; refuses an untypeable object or field."""
    out: list[tuple[str, str]] = []
    for obj in arch.get("objects") or []:
        pbtype = obj.get("_pbtype")
        cls = import_version()[1].get(pbtype) if pbtype else None
        if cls is None:
            raise _Refuse(f"{arch['header']['identifier']} has an untyped object {pbtype!r}")
        unknown: list[str] = []
        _descriptor_refs(obj, cls.DESCRIPTOR, "", out, unknown)
        if unknown:
            raise _Refuse(f"{arch['header']['identifier']} unclassified {unknown[0]} carries a reference")
    return out


def _ref_class(path: str) -> str:
    """strong (owned: header-listed, same member), weak (shared: anywhere), forbidden
    (comments, pencil, highlights, tracked changes, linked text flow) or unclassified."""
    table = _STORAGE_TABLE_REF.search(path)
    if table:
        name = table.group(1)
        if name in _STRONG_TABLES:
            return "strong"
        if name in _FORBIDDEN_TABLES:
            return "forbidden"
        return "weak" if name.endswith("Style") else "unclassified"
    field = path.rsplit(".", 1)[-1]
    if field in _FORBIDDEN_REF_FIELDS:
        return "forbidden"
    if field in _STRONG_REF_FIELDS:
        return "strong"
    if field in _WEAK_REF_FIELDS:
        return "weak"
    return "unclassified"


def _close_subtree(hide_ids: list[str], slide_id: str, member: str, model: _Model) -> tuple[set[str], set[str]]:
    """(subtree, weak boundary). Closure follows only strong, header-listed, same-member
    body refs; weak targets stay outside; forbidden/unclassified refs and header refs no
    decoded body ref accounts for refuse; comment/highlight/pencil/change archives refuse."""
    subtree: set[str] = set()
    weak: set[str] = set()
    queue = list(hide_ids)
    while queue:
        x = queue.pop()
        if x in subtree:
            continue
        subtree.add(x)
        arch = model.archives[x]
        for obj in arch.get("objects") or []:
            if _FORBIDDEN_ARCHIVE_TYPE.search(str(obj.get("_pbtype") or "")):
                raise _Refuse(f"{x} is a {obj.get('_pbtype')}")
        refs = _archive_refs(arch)
        header = set(_header_refs(arch["header"]))
        for path, t in refs:
            cls = _ref_class(path)
            if cls in ("forbidden", "unclassified"):
                raise _Refuse(f"{x} {cls} {path} references {t}")
        unattributed = header - {t for _p, t in refs}
        if unattributed:
            raise _Refuse(f"{x} header references {sorted(unattributed)[:3]} with no decoded body reference")
        for path, t in refs:
            tm = model.member_of.get(t)
            if _ref_class(path) == "strong":
                if t not in header or tm != member or t == slide_id:
                    raise _Refuse(f"{x} {path} owns {t} ({tm}) without a same-member header reference")
                queue.append(t)
                continue
            if t not in model.archives:
                continue
            if tm == member and t not in header and t != slide_id and t not in hide_ids:
                if t not in subtree and (model.objects.get(t) or {}).get("_pbtype") != "TSD.GroupArchive":
                    raise _Refuse(f"{x} {path} references {t} in {member} without a header reference")
            weak.add(t)
    return subtree, weak - subtree - {slide_id}


def _metadata_refs(comp: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in ("externalReferences", "versionedExternalReferences"):
        for e in comp.get(f) or []:
            for k in ("objectIdentifier", "componentIdentifier"):
                if e.get(k) is not None:
                    out.append((f"{f}.{k}", str(e[k])))
    for e in comp.get("dataReferences") or []:
        out.extend(("dataReferences", str(o.get("objectIdentifier"))) for o in e.get("objectReferenceList") or [])
    out.extend(("objectUuidMapEntries", str(e.get("identifier"))) for e in comp.get("objectUuidMapEntries") or [])
    out.extend(("ambiguousObjectIdentifiers", str(i)) for i in comp.get("ambiguousObjectIdentifiers") or [])
    return out


_EDITED_METADATA_FIELDS = frozenset({"objectUuidMapEntries", "dataReferences"})


def _plan_slide(
    n: int, hides: list[dict], model: _Model, order: list[tuple[str, bool]],
    slide_count_by_member: Counter, *, source_counts: dict[str, int] | None,
    items: list[dict] | None, group_text: dict[int, str] | None, data_index: dict[str, str],
    comp_of_member: dict[str, dict], cache: dict,
) -> tuple[str, str, list[str]]:
    """R1-R4 plus identity and twin ambiguity: a refusal here leaves the saved order unproven."""
    if not (1 <= n <= len(order)):
        raise _Refuse(f"slide {n} out of range (deck has {len(order)})")
    slide_id = order[n - 1][0]
    slide = model.objects.get(slide_id)
    if slide is None or slide.get("_pbtype") != "KN.SlideArchive":
        raise _Refuse(f"slide archive {slide_id} not decoded")
    member = model.member_of[slide_id]
    if slide_count_by_member[member] != 1:
        raise _Refuse(f"member {member} holds {slide_count_by_member[member]} slide archives")
    z_ids = [str(r.get("identifier")) for r in slide.get("drawablesZOrder") or []]
    owned = [str(r.get("identifier")) for r in slide.get("ownedDrawables") or []]
    if any(model.member_of.get(i) != member for i in z_ids):
        raise _Refuse(f"slide drawables are not all in {member}")
    if owned != z_ids:
        raise _Refuse("ownedDrawables != drawablesZOrder (I2)")
    if len(set(z_ids)) != len(z_ids):
        raise _Refuse("drawablesZOrder has a duplicate id")
    slide_header = model.archives[slide_id]["header"]
    body_ids = {t for _w, t in _body_refs(model.archives[slide_id])}
    if set(_header_refs(slide_header)) != body_ids:
        raise _Refuse("slide header objectReferences != body refs (I1)")
    comp = comp_of_member.get(member)
    if comp is None:
        raise _Refuse(f"no unique component for {member}")
    member_ids = set(model.member_ids[member])
    if any(str(e.get("identifier")) not in member_ids for e in comp.get("objectUuidMapEntries") or []):
        raise _Refuse("uuid entry names an archive outside the member (I5)")

    records = derive_kind_index(slide, model.objects)
    if source_counts is None:
        raise _Refuse("source counts missing")
    mismatched = reconcile_counts(derived_kind_counts(records), source_counts)
    if mismatched:
        raise _Refuse(f"reconcile mismatch on kinds {mismatched}")

    by_key = {(r["kind"], r["kindIndex"]): r for r in records}
    memberships = Counter(r["id"] for r in records)
    hide_ids: list[str] = []
    for spec in hides:
        kind = str(spec.get("kind"))
        rec = by_key.get((kind, int(spec.get("kindIndex", -1))))
        if rec is None:
            raise _Refuse(f"hide {kind} {spec.get('kindIndex')} does not resolve")
        hid = rec["id"]
        if hid not in z_ids:
            raise _Refuse(f"hide {hid} is not top-level")
        pbtype = (model.objects.get(hid) or {}).get("_pbtype")
        if pbtype not in _HIDE_PBTYPES:
            raise _Refuse(f"hide {hid} is {pbtype}")
        if memberships[hid] != 1:
            raise _Refuse(f"hide {hid} is a dual target ({memberships[hid]} kind slots)")
        if hid in hide_ids:
            raise _Refuse(f"two hide specs resolve to {hid}")
        hide_ids.append(hid)
    if items is None:
        raise _Refuse("payload items missing")
    _identity_check(records, items, model.objects, data_index, group_text, cache)
    _check_unambiguous(records, hides, items, slide, model.objects, data_index, group_text, cache)
    return slide_id, member, hide_ids


def _prove_references(
    slide_id: str, hide_ids: list[str], subtree: set[str], boundary: set[str],
    referrers: dict[str, list[tuple[str, str]]], uuid_refs: dict[tuple[str, str], list[str]],
    pm: dict, comp: dict, model: _Model,
) -> None:
    """R5: every reference into the subtree comes from the subtree, the slide's two lists
    or header, or PackageMetadata; no boundary archive is owned solely by the subtree."""
    hides = set(hide_ids)
    slide_header = model.archives[slide_id]["header"]
    header_count = Counter(_header_refs(slide_header))
    mi_refs = [str(r) for mi in slide_header.get("messageInfos") or [] for r in mi.get("objectReferences") or []]
    for x in subtree:
        for ref, where in referrers.get(x, []):
            if ref in subtree:
                continue
            if ref == slide_id and x in hides and (where in _SLIDE_LIST_FIELDS or where == _HEADER):
                continue
            pbtype = (model.objects.get(ref) or {}).get("_pbtype")
            raise _Refuse(f"{x} is referenced by {ref} ({pbtype}) field {where}")
    for h in hide_ids:
        if header_count[h] != 1:
            raise _Refuse(f"slide header lists hide {h} {header_count[h]} times")
        if mi_refs.count(h) != 1:
            raise _Refuse(f"slide header fieldInfos reference hide {h}")
    for b in boundary:
        refs = referrers.get(b, [])
        if refs and all(ref in subtree for ref, _w in refs):
            raise _Refuse(f"{b} in {model.member_of[b]} is referenced only from the hide subtree")
    for table in ("components", "versionedComponents"):
        for other in pm.get(table) or []:
            for f, t in _metadata_refs(other):
                if t in subtree and not (table == "components" and other is comp and f in _EDITED_METADATA_FIELDS):
                    raise _Refuse(f"{table} {other.get('identifier')} {f} names subtree id {t}")
    for e in comp.get("objectUuidMapEntries") or []:
        if str(e.get("identifier")) not in subtree:
            continue
        u = e.get("uuid") or {}
        key = (str(u.get("lower")), str(u.get("upper")))
        if key in uuid_refs:
            raise _Refuse(f"uuid of {e.get('identifier')} is referenced by {uuid_refs[key][0]}")
    if (comp.get("featureInfos") and any(
            (model.objects.get(h) or {}).get("_pbtype") == "TSD.MovieArchive" for h in hide_ids)):
        raise _Refuse("movie hide on a component with featureInfos")


def _post_tables(
    plan_slide_id: str, member: str, hide_ids: list[str], subtree: set[str],
    model: _Model, comp_of_member: dict[str, dict],
) -> tuple[Counter, set]:
    headers: dict[str, dict] = {}
    for aid in model.member_ids[member]:
        if aid in subtree:
            continue
        header = model.archives[aid]["header"]
        if aid == plan_slide_id:
            header = _strip_header_refs(copy.deepcopy(header), set(hide_ids))
        headers[aid] = header
    return _recompute_tables(headers, member, model.member_of, comp_of_member)


def _strip_header_refs(header: dict, ids: set[str]) -> dict:
    for mi in header.get("messageInfos") or []:
        refs = mi.get("objectReferences")
        if refs:
            mi["objectReferences"] = [r for r in refs if str(r) not in ids]
    return header


def _slide_apply_fn(plan: _Plan):
    hides = set(plan.hide_ids)

    def apply_fn(patched: dict) -> int:
        removed = 0
        for chunk in patched["chunks"]:
            kept = []
            for arch in chunk["archives"]:
                aid = str(arch["header"]["identifier"])
                if aid in plan.subtree:
                    removed += 1
                    continue
                if aid == plan.slide_id:
                    obj = arch["objects"][0]
                    for key in _SLIDE_LIST_FIELDS:
                        obj[key] = [r for r in obj.get(key) or [] if str(r.get("identifier")) not in hides]
                    _strip_header_refs(arch["header"], hides)
                kept.append(arch)
            chunk["archives"] = kept
        patched["chunks"] = [c for c in patched["chunks"] if c["archives"]]
        return removed

    return apply_fn


def _edit_slide_member(zf: zipfile.ZipFile, plan: _Plan) -> bytes:
    new_bytes, removed, _o, _h, decoded, reparsed = _decode_apply_reencode_diff(
        zf, plan.member, _slide_apply_fn(plan), expect=len(plan.subtree))
    if new_bytes is None:
        raise _Refuse(f"removed {removed} archives, expected {len(plan.subtree)}")
    gone, added, changed = _archive_diff(decoded, reparsed)
    if gone != plan.subtree or added or set(changed) != {plan.slide_id}:
        raise _Refuse(
            f"re-encode gate: removed {len(gone)}/{len(plan.subtree)}, added {sorted(added)}, "
            f"changed {sorted(changed)}")
    hides = set(plan.hide_ids)
    expected = copy.deepcopy(_archives_by_id(decoded)[plan.slide_id])
    obj = expected["objects"][0]
    for key in _SLIDE_LIST_FIELDS:
        obj[key] = [r for r in obj.get(key) or [] if str(r.get("identifier")) not in hides]
        if [str(r.get("identifier")) for r in obj[key]] != plan.expected_order:
            raise _Refuse(f"{key} minus hides != expected order")
        if not obj[key]:
            del obj[key]
    _strip_header_refs(expected["header"], hides)
    if not _archives_equal(_archives_by_id(reparsed)[plan.slide_id], expected):
        raise _Refuse("re-encoded slide archive != original minus the hide references")
    return new_bytes


def _metadata_apply_fn(removed: set[str], drop_ext: dict[str, set], orphans: set[str]):
    def apply_fn(patched: dict) -> int:
        _pid, pm = _package_metadata(patched)
        touched = 0
        for comp in pm.get("components") or []:
            cid = str(comp.get("identifier"))
            before = copy.deepcopy(comp)
            if comp.get("objectUuidMapEntries"):
                comp["objectUuidMapEntries"] = [
                    e for e in comp["objectUuidMapEntries"] if str(e.get("identifier")) not in removed]
            if comp.get("dataReferences"):
                refs = []
                for e in comp["dataReferences"]:
                    lst = [o for o in e.get("objectReferenceList") or []
                           if str(o.get("objectIdentifier")) not in removed]
                    if lst:
                        e["objectReferenceList"] = lst
                        refs.append(e)
                comp["dataReferences"] = refs
            drop = drop_ext.get(cid)
            if drop and comp.get("externalReferences"):
                comp["externalReferences"] = [
                    e for e in comp["externalReferences"]
                    if e.get("isWeak") or (
                        str(e.get("componentIdentifier")),
                        str(e["objectIdentifier"]) if e.get("objectIdentifier") is not None else None,
                    ) not in drop
                ]
            for key in ("objectUuidMapEntries", "dataReferences", "externalReferences"):
                if key in comp and not comp[key] and before.get(key):
                    del comp[key]
            if comp != before:
                touched += 1
        if orphans:
            pm["datas"] = [d for d in pm.get("datas") or [] if str(d.get("identifier")) not in orphans]
            touched += 1
        return touched

    return apply_fn


def _referenced_data(pm: dict) -> set[str]:
    out: set[str] = set()
    for comps in (pm.get("components") or [], pm.get("versionedComponents") or []):
        for comp in comps:
            for e in comp.get("dataReferences") or []:
                if e.get("objectReferenceList"):
                    out.add(str(e.get("dataIdentifier")))
    return out


def _data_metadata_ids(model: _Model, pm: dict) -> set[str]:
    ref = (pm.get("dataMetadataMap") or {}).get("identifier")
    if ref is None:
        return set()
    obj = model.objects.get(str(ref)) or {}
    return {str(e.get("dataIdentifier")) for e in obj.get("dataMetadataEntries") or []}


def _validate_all_components(model: _Model, pm: dict, comp_of_member: dict[str, dict]) -> set[str]:
    """I3/I4 on every component against its decoded headers; refuses the whole stage on any
    mismatch. Returns the data ids named by components with no decoded member (kept live)."""
    unresolved_live: set[str] = set()
    by_id = {id(c) for c in comp_of_member.values()}
    for comp in pm.get("components") or []:
        if id(comp) not in by_id:
            unresolved_live |= {str(e.get("dataIdentifier")) for e in comp.get("dataReferences") or []}
    for comp in pm.get("versionedComponents") or []:
        unresolved_live |= {str(e.get("dataIdentifier")) for e in comp.get("dataReferences") or []}
    for member, comp in comp_of_member.items():
        headers = {aid: model.archives[aid]["header"] for aid in model.member_ids[member]
                   if model.member_of.get(aid) == member}
        try:
            i3, i4 = _recompute_tables(headers, member, model.member_of, comp_of_member)
            _check_tables(comp, i3, i4, member)
        except _Refuse as exc:
            raise OfflineWriteRefused(f"component tables do not match the headers: {exc}") from exc
    return unresolved_live


def _orphans(plans: dict[int, _Plan], data_by_archive: dict[str, set[str]], unresolved_live: set[str]) -> set[str]:
    removed = set().union(*(p.subtree for p in plans.values())) if plans else set()
    live = set(unresolved_live)
    for aid, datas in data_by_archive.items():
        if aid not in removed:
            live |= datas
    candidates = set().union(*(p.data_ids for p in plans.values())) if plans else set()
    return candidates - live


def _data_member_names(namelist: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw in namelist:
        for did, name in data_member_index([raw]).items():
            out.setdefault(did, []).append(name)
    return out


def _orphan_violation(did: str, datas_ids: set[str], dmm_ids: set[str],
                      member_names: dict[str, list[str]]) -> str | None:
    if did not in datas_ids:
        return f"orphan data {did} has no datas entry"
    if did in dmm_ids:
        return f"orphan data {did} is in DataMetadataMap"
    names = member_names.get(did, [])
    if len(names) != 1:
        return f"orphan data {did} has {len(names)} Data/ members"
    return None


def _readback(
    deck: Path, plans: dict[int, _Plan], hides_by_slide: dict[int, list[dict]],
    source_counts_by_slide: dict[int, dict[str, int]], model: _Model,
    removed: set[str], orphans: set[str], dropped: list[str],
) -> None:
    with zipfile.ZipFile(deck) as zf:
        names = set(zf.namelist())
        members = sorted({p.member for p in plans.values()} | {_METADATA_MEMBER})
        decoded = {m: IWAFile.from_buffer(zf.read(m), m).to_dict() for m in members}
    gone = [m for m in dropped if m in names]
    if gone:
        raise HidesWriteFailed(f"hides read-back: dropped members still present: {gone}")
    _pid, pm = _package_metadata(decoded[_METADATA_MEMBER])
    if pm is None:
        raise HidesWriteFailed("hides read-back: no PackageMetadata")
    member_of = dict(model.member_of)
    for aid in removed:
        member_of.pop(aid, None)
    comp_of_member = _components_by_member(pm, list(model.member_ids))
    _check_metadata_invariants(pm, removed, orphans, "hides read-back")
    for n, plan in plans.items():
        archs = _archives_by_id(decoded[plan.member])
        objects = {aid: a["objects"][0] for aid, a in archs.items() if a.get("objects")}
        present = removed & set(archs)
        if present:
            raise HidesWriteFailed(f"hides read-back slide {n}: removed archives present {sorted(present)[:5]}")
        for aid, arch in archs.items():
            refs = set(_header_refs(arch["header"])) | {t for _w, t in _body_refs(arch)}
            if refs & removed:
                raise HidesWriteFailed(f"hides read-back slide {n}: {aid} references removed {sorted(refs & removed)[:5]}")
        slide = objects[plan.slide_id]
        z = [str(r.get("identifier")) for r in slide.get("drawablesZOrder") or []]
        owned = [str(r.get("identifier")) for r in slide.get("ownedDrawables") or []]
        if z != plan.expected_order or owned != z:
            raise HidesWriteFailed(f"hides read-back slide {n}: lists != expected")
        if set(_header_refs(archs[plan.slide_id]["header"])) != {t for _w, t in _body_refs(archs[plan.slide_id])}:
            raise HidesWriteFailed(f"hides read-back slide {n}: I1")
        comp = comp_of_member.get(plan.member)
        if comp is None:
            raise HidesWriteFailed(f"hides read-back slide {n}: component lost")
        try:
            i3, i4 = _recompute_tables(
                {aid: a["header"] for aid, a in archs.items()}, plan.member, member_of, comp_of_member)
            _check_tables(comp, i3, i4, f"slide {n}")
        except _Refuse as exc:
            raise HidesWriteFailed(f"hides read-back: {exc}") from exc
        if any(str(e.get("identifier")) not in archs for e in comp.get("objectUuidMapEntries") or []):
            raise HidesWriteFailed(f"hides read-back slide {n}: I5")
        base = expected_base_counts(source_counts_by_slide[n], hides_by_slide[n])
        mismatched = reconcile_counts(derived_kind_counts(derive_kind_index(slide, objects)), base)
        if mismatched:
            raise HidesWriteFailed(f"hides read-back slide {n}: reconcile mismatch on {mismatched}")


def _check_metadata_invariants(pm: dict, removed: set[str], orphans: set[str], where: str) -> None:
    datas = {str(d.get("identifier")) for d in pm.get("datas") or []}
    if datas & orphans:
        raise HidesWriteFailed(f"{where}: orphan datas entries remain {sorted(datas & orphans)}")
    unreferenced = datas - _referenced_data(pm)
    if unreferenced:
        raise HidesWriteFailed(f"{where}: unreferenced datas (I6) {sorted(unreferenced)[:5]}")
    for table in ("components", "versionedComponents"):
        for comp in pm.get(table) or []:
            for f, t in _metadata_refs(comp):
                if t in removed:
                    raise HidesWriteFailed(f"{where}: {table} {comp.get('identifier')} {f} names removed {t}")


def _verify_deck(deck: Path, removed: set[str], orphans: set[str]) -> None:
    with zipfile.ZipFile(deck) as zf:
        model = _load_model(zf)
    _require_unambiguous_package(model, HidesWriteFailed)
    pm_id, pm = _package_metadata(model)
    referrers, _uuids = _scan(model, removed, pm_id)
    if referrers:
        t, refs = next(iter(referrers.items()))
        raise HidesWriteFailed(f"hides verify: removed {t} still referenced by {refs[:3]}")
    _check_metadata_invariants(pm, removed, orphans, "hides verify")
    comp_of_member = _components_by_member(pm, list(model.member_ids))
    for member, comp in comp_of_member.items():
        headers = {aid: model.archives[aid]["header"] for aid in model.member_ids[member]
                   if aid in model.archives}
        try:
            i3, i4 = _recompute_tables(headers, member, model.member_of, comp_of_member)
            _check_tables(comp, i3, i4, member)
        except _Refuse as exc:
            raise HidesWriteFailed(f"hides verify: {exc}") from exc
        ids = set(model.member_ids[member])
        if any(str(e.get("identifier")) not in ids for e in comp.get("objectUuidMapEntries") or []):
            raise HidesWriteFailed(f"hides verify: {member}: I5")


def patch_deck_hides(
    deck: Path | str,
    hides_by_slide: dict[int, list[dict]],
    *,
    source_counts_by_slide: dict[int, dict[str, int]],
    items_by_slide: dict[int, list[dict]],
    verify: bool = False,
    force_refuse: frozenset[int] | set[int] = frozenset(),
    group_text_by_slide: dict[int, dict[int, str]] | None = None,
) -> HidesResult:
    """Delete each slide's role=hide targets (WALL kindIndex; the deck still holds them).

    Per-slide refusal leaves that slide's member byte-identical; ``order_proven`` marks a
    refused slide whose saved kind order was proven to match the payload. Every failure
    before the first byte is written raises ``OfflineWriteRefused`` (deck untouched);
    ``OfflineWriteCorrupted`` propagates; any failure after that raises ``HidesWriteFailed``.
    """
    deck = Path(deck)
    try:
        result, plans, edits, dropped, model, removed, orphans = _prepare(
            deck, hides_by_slide, source_counts_by_slide, items_by_slide,
            force_refuse, group_text_by_slide or {})
    except OfflineWriteRefused:
        raise
    except Exception as exc:
        raise OfflineWriteRefused(f"hides planning failed: {exc!r}") from exc
    if not plans:
        return result

    try:
        _rewrite_members(deck, edits, drop=dropped)
    except (OfflineWriteRefused, OfflineWriteCorrupted):
        raise
    except Exception as exc:
        raise HidesWriteFailed(f"rewrite failed after its copy-back: {exc!r}") from exc

    for n, p in plans.items():
        result.slides[n] = SlideHides(deleted=len(p.hide_ids), removed_ids=sorted(p.subtree), order_proven=True)
    result.dropped_data = dropped
    result.members = sorted(edits)

    wanted = {n: list(h) for n, h in hides_by_slide.items() if h}
    try:
        _readback(deck, plans, wanted, source_counts_by_slide, model, removed, orphans, dropped)
        if verify:
            _verify_deck(deck, removed, orphans)
    except HidesWriteFailed:
        raise
    except Exception as exc:
        raise HidesWriteFailed(f"hides read-back failed: {exc!r}") from exc
    return result


def _prepare(
    deck: Path, hides_by_slide: dict[int, list[dict]], source_counts_by_slide: dict[int, dict[str, int]],
    items_by_slide: dict[int, list[dict]], force_refuse: frozenset[int] | set[int],
    group_text_by_slide: dict[int, dict[int, str]],
) -> tuple:
    if 0 in hides_by_slide:
        raise OfflineWriteRefused("slide numbers are 1-based")
    result = HidesResult()
    wanted = {n: list(h) for n, h in hides_by_slide.items() if h}
    for n in hides_by_slide:
        result.slides[n] = SlideHides()
    if not wanted:
        return result, {}, {}, [], None, set(), set()

    def refuse(n: int, reason: str, proven: bool) -> None:
        result.slides[n] = SlideHides(refused=True, reason=reason, order_proven=proven)

    with zipfile.ZipFile(deck) as zf:
        model = _load_model(zf)
        _require_unambiguous_package(model, OfflineWriteRefused)
        pm_id, pm = _package_metadata(model)
        order = slide_order(model.objects)
        data_index = _build_data_index(model.namelist)
        comp_of_member = _components_by_member(pm, list(model.member_ids))
        unresolved_live = _validate_all_components(model, pm, comp_of_member)
        datas_ids = {str(d.get("identifier")) for d in pm.get("datas") or []}
        unreferenced = datas_ids - _referenced_data(pm)
        if unreferenced:
            raise OfflineWriteRefused(f"datas unreferenced before the edit (I6): {sorted(unreferenced)[:5]}")
        slide_count_by_member = Counter(
            model.member_of[aid] for aid, obj in model.objects.items() if obj.get("_pbtype") == "KN.SlideArchive")
        cache: dict = {}

        aliases = Counter(sid for sid, _skipped in order)
        planned: dict[int, tuple] = {}
        for n in sorted(wanted):
            if 1 <= n <= len(order) and aliases[order[n - 1][0]] > 1:
                refuse(n, f"slide archive {order[n - 1][0]} appears under {aliases[order[n - 1][0]]} slide numbers",
                       False)
                continue
            try:
                plan = _plan_slide(
                    n, wanted[n], model, order, slide_count_by_member,
                    source_counts=source_counts_by_slide.get(n), items=items_by_slide.get(n),
                    group_text=group_text_by_slide.get(n), data_index=data_index,
                    comp_of_member=comp_of_member, cache=cache)
            except _Refuse as exc:
                refuse(n, str(exc), False)
                continue
            except Exception as exc:
                refuse(n, f"planning failed: {exc!r}", False)
                continue
            if n in force_refuse:
                refuse(n, "forced refusal", True)
                continue
            try:
                planned[n] = (*plan, *_close_subtree(plan[2], plan[0], plan[1], model))
            except _Refuse as exc:
                refuse(n, str(exc), True)
            except Exception as exc:
                refuse(n, f"planning failed: {exc!r}", True)

        targets = set().union(*(p[3] | p[4] for p in planned.values())) if planned else set()
        referrers, uuid_refs = _scan(model, targets, pm_id) if planned else ({}, {})

        plans: dict[int, _Plan] = {}
        for n, (slide_id, member, hide_ids, subtree, boundary) in planned.items():
            try:
                comp = comp_of_member[member]
                _prove_references(slide_id, hide_ids, subtree, boundary, referrers, uuid_refs, pm, comp, model)
                post_i3, post_i4 = _post_tables(slide_id, member, hide_ids, subtree, model, comp_of_member)
                data_ids = {d for aid in subtree for d in _header_data_refs(model.archives[aid]["header"])}
                z_ids = [str(r.get("identifier")) for r in model.objects[slide_id].get("drawablesZOrder") or []]
                plan = _Plan(slide_id, member, hide_ids, subtree, data_ids, str(comp.get("identifier")),
                             post_i3, post_i4, [i for i in z_ids if i not in set(hide_ids)])
                plan.new_bytes = _edit_slide_member(zf, plan)
                plans[n] = plan
            except _Refuse as exc:
                refuse(n, str(exc), True)
            except Exception as exc:
                refuse(n, f"planning failed: {exc!r}", True)

        data_by_archive = {aid: set(_header_data_refs(arch["header"])) for aid, arch in model.archives.items()}
        data_by_archive = {aid: d for aid, d in data_by_archive.items() if d}
        dmm_ids = _data_metadata_ids(model, pm)
        member_names = _data_member_names(model.namelist)
        while True:
            orphans = _orphans(plans, data_by_archive, unresolved_live)
            bad = {did: why for did in orphans
                   if (why := _orphan_violation(did, datas_ids, dmm_ids, member_names))}
            if not bad:
                break
            for n in [n for n, p in plans.items() if p.data_ids & set(bad)]:
                did = sorted(plans[n].data_ids & set(bad))[0]
                refuse(n, bad[did], True)
                del plans[n]

        if not plans:
            return result, {}, {}, [], model, set(), set()

        removed = set().union(*(p.subtree for p in plans.values()))
        drop_ext: dict[str, set] = {}
        for p in plans.values():
            comp = comp_of_member[p.member]
            drop_ext[p.component_id] = set(_stored_i4(comp)) - p.post_i4
        new_meta, _t, _o, _h, meta_decoded, meta_reparsed = _decode_apply_reencode_diff(
            zf, _METADATA_MEMBER, _metadata_apply_fn(removed, drop_ext, orphans))
        gone, added, changed = _archive_diff(meta_decoded, meta_reparsed)
        if gone or added or set(changed) != {pm_id}:
            raise OfflineWriteRefused(f"{_METADATA_MEMBER} re-encode gate: changed {sorted(changed)}")
        intended = copy.deepcopy(meta_decoded)
        _metadata_apply_fn(removed, drop_ext, orphans)(intended)
        if not _archives_equal(_archives_by_id(meta_reparsed)[pm_id], _archives_by_id(intended)[pm_id]):
            raise OfflineWriteRefused(f"{_METADATA_MEMBER}: re-encoded PackageMetadata != intended edit")
        _rp_id, rpm = _package_metadata(meta_reparsed)
        rcomps = {str(c.get("identifier")): c for c in rpm.get("components") or []}
        for p in plans.values():
            c = rcomps.get(p.component_id)
            if c is None or _stored_i3(c) != p.post_i3 or _stored_i4(c) != Counter(p.post_i4):
                raise OfflineWriteRefused(f"component {p.component_id} post-edit tables != recompute")
            if any(str(e.get("identifier")) in removed for e in c.get("objectUuidMapEntries") or []):
                raise OfflineWriteRefused(f"component {p.component_id} still maps removed uuids")
        rdatas = {str(d.get("identifier")) for d in rpm.get("datas") or []}
        if rdatas != datas_ids - orphans:
            raise OfflineWriteRefused("datas after edit != datas minus orphans")
        unreferenced = rdatas - _referenced_data(rpm)
        if unreferenced:
            raise OfflineWriteRefused(f"datas live only outside Metadata after the edit (I6): {sorted(unreferenced)[:5]}")

    dropped = sorted(member_names[did][0] for did in orphans)
    edits = {p.member: p.new_bytes for p in plans.values()}
    edits[_METADATA_MEMBER] = new_meta
    return result, plans, edits, dropped, model, removed, orphans
