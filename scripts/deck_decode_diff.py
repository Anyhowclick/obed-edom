#!/usr/bin/env python3
"""ID-insensitive, reference-aware decode diff of two Keynote decks (no Keynote).

Each deck is decoded once. Archives are canonicalised with ``identifier``,
``randomNumberSeed``, ``saveToken`` and UUIDs dropped. A body reference and each header
``objectReferences`` entry becomes the target's content label (pbtype + ref-free body
hash, ``<dangling>`` when the target is missing); a data reference becomes the data's
digest. Slides (by ``slide_order``) and the other ``.iwa`` members compare as multisets of
archives. ``Index/Metadata.iwa`` compares per component (by locator) in label space, plus
the ``datas`` table and the non-IWA ZIP members.

Leftover archives that share an identifier and pbtype on both sides are explained per
field, so every difference has a key such as ``slide:12:KN.SlideArchive.drawablesZOrder``,
``member:Index/Document.iwa:KN.SlideNodeArchive.thumbnails``,
``metadata:Slide-101:dataReferences``, ``datas:photo.jpg`` or ``zip:Data/photo.jpg``.

Exit 0 iff every difference key matches an ``--allow`` regex.

Usage:
    uv run python scripts/deck_decode_diff.py A.key B.key [--allow REGEX ...] [--json OUT]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from obed_edom.iwa_runs import UndecodableIWAMember, slide_order

METADATA_MEMBER = "Index/Metadata.iwa"
PACKAGE_METADATA = "TSP.PackageMetadata"
DANGLING = "<dangling>"
DANGLING_DATA = "<dangling-data>"
REF = "<ref>"

_DROP_KEYS = frozenset({"identifier", "randomNumberSeed", "saveToken"})
_REF_KEYS = frozenset({"identifier", "deprecatedType", "deprecatedIsExternal"})
_DATA_MEMBER = re.compile(r"^(?P<base>Data/.+)-\d+(?P<ext>\.[^./]+)$")
_LOCATOR_SUFFIX = re.compile(r"-\d+$")


@dataclass
class Archive:
    member: str
    pbtype: str
    header: dict
    objects: list[dict]


@dataclass
class Deck:
    path: Path
    archives: dict[str, Archive] = field(default_factory=dict)
    members: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    data_labels: dict[str, str] = field(default_factory=dict)
    zip_entries: list[tuple[str, int, int]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)


@lru_cache(maxsize=None)
def _descriptors() -> dict[str, Any]:
    from keynote_parser.codec import import_version  # noqa: PLC0415 (optional iwa extra)

    return {c.DESCRIPTOR.full_name: c.DESCRIPTOR for c in import_version()[0].values()}


@lru_cache(maxsize=None)
def _fields(desc: Any) -> dict[str, Any]:
    return {f.json_name: f for f in desc.fields}


def _hash(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.blake2b(blob.encode(), digest_size=8).hexdigest()


def normalise_zip_name(raw: str) -> str:
    try:
        name = raw.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        name = raw
    m = _DATA_MEMBER.match(name)
    return f"{m.group('base')}{m.group('ext')}" if m else name


def load_deck(path: str | Path) -> Deck:
    from keynote_parser.codec import IWAFile  # noqa: PLC0415 (optional iwa extra)

    deck = Deck(Path(path))
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            name = info.filename
            if not name.endswith(".iwa"):
                if not info.is_dir():
                    deck.zip_entries.append((normalise_zip_name(name), info.CRC, info.file_size))
                continue
            try:
                decoded = IWAFile.from_buffer(zf.read(name), name).to_dict()
            except Exception as exc:
                raise UndecodableIWAMember(name) from exc
            ids = deck.members.setdefault(name, [])
            for chunk in decoded["chunks"]:
                for arch in chunk["archives"]:
                    ident = str(arch["header"]["identifier"])
                    objs = arch.get("objects") or []
                    pbtype = str((objs[0] if objs else {}).get("_pbtype"))
                    if pbtype == PACKAGE_METADATA and name == METADATA_MEMBER:
                        deck.metadata = objs[0]
                        continue
                    deck.archives.setdefault(ident, Archive(name, pbtype, arch["header"], objs))
                    ids.append(ident)
    for entry in deck.metadata.get("datas") or []:
        label = entry.get("digest") or entry.get("preferredFileName") or entry.get("fileName") or ""
        deck.data_labels[str(entry.get("identifier"))] = f"data:{label}"
    deck.labels = {
        ident: f"{arch.pbtype}#{_hash(_canon_archive(deck, arch, labels=None, header=False))}"
        for ident, arch in deck.archives.items()
    }
    return deck


def _ref_label(ident: Any, labels: dict[str, str] | None) -> str:
    if labels is None:
        return REF
    return labels.get(str(ident), DANGLING)


def _data_label(deck: Deck, ident: Any) -> str:
    return deck.data_labels.get(str(ident), DANGLING_DATA)


def _canon_loose(deck: Deck, value: Any, labels: dict[str, str] | None) -> Any:
    if isinstance(value, list):
        return [_canon_loose(deck, v, labels) for v in value]
    if not isinstance(value, dict):
        return value
    keys = set(value) - {"_pbtype"}
    if "identifier" in keys and keys <= _REF_KEYS and str(value["identifier"]).isdigit():
        return _ref_label(value["identifier"], labels)
    if keys == {"lower", "upper"}:
        return None
    return {
        k: _canon_loose(deck, v, labels)
        for k, v in value.items()
        if k != "_pbtype" and k not in _DROP_KEYS
    }


def _canon_message(deck: Deck, value: Any, desc: Any, labels: dict[str, str] | None) -> Any:
    if not isinstance(value, dict):
        return _canon_loose(deck, value, labels)
    fields = _fields(desc)
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key == "_pbtype" or key in _DROP_KEYS:
            continue
        f = fields.get(key)
        if f is None or f.message_type is None:
            out[key] = _canon_loose(deck, item, labels) if f is None else item
            continue
        if f.message_type.full_name == "TSP.UUID":
            continue
        if isinstance(item, list):
            out[key] = [_canon_field(deck, x, f.message_type, labels) for x in item]
        else:
            out[key] = _canon_field(deck, item, f.message_type, labels)
    return out


def _canon_field(deck: Deck, value: Any, desc: Any, labels: dict[str, str] | None) -> Any:
    if desc.full_name == "TSP.Reference":
        return _ref_label((value or {}).get("identifier"), labels)
    if desc.full_name == "TSP.DataReference":
        return _data_label(deck, (value or {}).get("identifier"))
    return _canon_message(deck, value, desc, labels)


def _canon_object(deck: Deck, obj: dict, labels: dict[str, str] | None) -> Any:
    desc = _descriptors().get(str(obj.get("_pbtype")))
    if desc is None:
        return _canon_loose(deck, obj, labels)
    return _canon_message(deck, obj, desc, labels)


def _canon_archive(
    deck: Deck, arch: Archive, *, labels: dict[str, str] | None, header: bool = True
) -> dict[str, Any]:
    out: dict[str, Any] = {"_pbtype": arch.pbtype}
    bodies = [_canon_object(deck, o, labels) for o in arch.objects]
    if len(bodies) == 1 and isinstance(bodies[0], dict):
        out.update(bodies[0])
    else:
        out["objects"] = bodies
    if header and labels is not None:
        infos = arch.header.get("messageInfos") or []
        out["@objectReferences"] = sorted(
            _ref_label(r, labels) for mi in infos for r in mi.get("objectReferences") or []
        )
        out["@dataReferences"] = sorted(
            _data_label(deck, r) for mi in infos for r in mi.get("dataReferences") or []
        )
    return out


def _full(deck: Deck, ident: str, refs: bool) -> dict[str, Any]:
    return _canon_archive(deck, deck.archives[ident], labels=deck.labels if refs else None)


def _member_counter(deck: Deck, ids: list[str], refs: bool) -> dict[str, list[str]]:
    by_hash: dict[str, list[str]] = {}
    for ident in ids:
        by_hash.setdefault(_hash(_full(deck, ident, refs)), []).append(ident)
    return by_hash


def _diff_archives(
    scope: str, a: Deck, ids_a: list[str], b: Deck, ids_b: list[str], refs: bool
) -> list[dict]:
    ha, hb = _member_counter(a, ids_a, refs), _member_counter(b, ids_b, refs)
    only_a: list[str] = []
    only_b: list[str] = []
    for h in set(ha) | set(hb):
        la, lb = ha.get(h, []), hb.get(h, [])
        n = min(len(la), len(lb))
        only_a += la[n:]
        only_b += lb[n:]
    diffs: list[dict] = []
    left_b = {(i, b.archives[i].pbtype): i for i in only_b}
    unpaired: dict[str, dict[str, list[str]]] = {}
    for ident in only_a:
        pbtype = a.archives[ident].pbtype
        if left_b.pop((ident, pbtype), None) is None:
            unpaired.setdefault(pbtype, {"a": [], "b": []})["a"].append(a.labels[ident])
            continue
        ca, cb = _full(a, ident, refs), _full(b, ident, refs)
        for key in sorted(set(ca) | set(cb)):
            if ca.get(key) != cb.get(key):
                diffs.append({
                    "key": f"{scope}:{pbtype}.{key}", "id": ident, "a": ca.get(key), "b": cb.get(key),
                })
    for ident, pbtype in left_b:
        unpaired.setdefault(pbtype, {"a": [], "b": []})["b"].append(b.labels[ident])
    for pbtype, sides in sorted(unpaired.items()):
        diffs.append({"key": f"{scope}:{pbtype}", "a": sorted(sides["a"]), "b": sorted(sides["b"])})
    return diffs


def _multiset_diff(key: str, a: list, b: list) -> list[dict]:
    ca, cb = Counter(a), Counter(b)
    if ca == cb:
        return []
    return [{"key": key, "a": sorted((ca - cb).elements(), key=repr), "b": sorted((cb - ca).elements(), key=repr)}]


def _slides(deck: Deck) -> list[str | None]:
    objects = {i: arch.objects[0] for i, arch in deck.archives.items() if arch.objects}
    return [
        deck.archives[sid].member if sid in deck.archives else None
        for sid, _skipped in slide_order(objects)
    ]


def _components(deck: Deck) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for comp in deck.metadata.get("components") or []:
        locator = str(comp.get("locator") or comp.get("preferredLocator") or comp.get("identifier"))
        if locator in out:
            raise ValueError(f"{deck.path}: two Metadata components share locator {locator!r}")
        out[locator] = comp
    return out


def _component_tables(deck: Deck, comp: dict) -> dict[str, list]:
    by_id = {str(c.get("identifier")): c for c in deck.metadata.get("components") or []}
    data_refs = [
        (_data_label(deck, d.get("dataIdentifier")), deck.labels.get(str(o.get("objectIdentifier")), DANGLING),
         o.get("count"))
        for d in comp.get("dataReferences") or []
        for o in d.get("objectReferenceList") or []
    ]
    ext_refs = []
    for ref in comp.get("externalReferences") or []:
        target_comp = by_id.get(str(ref.get("componentIdentifier")))
        target_locator = (target_comp or {}).get("locator") or (target_comp or {}).get("preferredLocator")
        locator = _LOCATOR_SUFFIX.sub("", str(target_locator or DANGLING))
        target = ref.get("objectIdentifier", ref.get("componentIdentifier"))
        ext_refs.append((locator, deck.labels.get(str(target), DANGLING), bool(ref.get("isWeak"))))
    return {
        "objectUuidMapEntries": [len(comp.get("objectUuidMapEntries") or [])],
        "featureInfos": [_hash(f) for f in comp.get("featureInfos") or []],
        "dataReferences": data_refs,
        "externalReferences": ext_refs,
    }


def compare(a: Deck, b: Deck, *, refs: bool = True) -> list[dict]:
    diffs: list[dict] = []
    slides_a, slides_b = _slides(a), _slides(b)
    for n in range(1, max(len(slides_a), len(slides_b)) + 1):
        ma = slides_a[n - 1] if n <= len(slides_a) else None
        mb = slides_b[n - 1] if n <= len(slides_b) else None
        if ma is None or mb is None:
            diffs.append({"key": f"slide:{n}", "a": ma, "b": mb})
            continue
        diffs += _diff_archives(f"slide:{n}", a, a.members[ma], b, b.members[mb], refs)
    rest_a = set(a.members) - set(slides_a)
    rest_b = set(b.members) - set(slides_b)
    for member in sorted(rest_a | rest_b):
        if member not in rest_a or member not in rest_b:
            diffs.append({"key": f"member:{member}", "a": member in rest_a, "b": member in rest_b})
            continue
        diffs += _diff_archives(f"member:{member}", a, a.members[member], b, b.members[member], refs)
    comps_a, comps_b = _components(a), _components(b)
    for locator in sorted(set(comps_a) | set(comps_b)):
        if locator not in comps_a or locator not in comps_b:
            diffs.append({"key": f"metadata:{locator}", "a": locator in comps_a, "b": locator in comps_b})
            continue
        ta, tb = _component_tables(a, comps_a[locator]), _component_tables(b, comps_b[locator])
        for table in ta:
            diffs += _multiset_diff(f"metadata:{locator}:{table}", ta[table], tb[table])
    datas_a = [(d.get("preferredFileName"), d.get("digest")) for d in a.metadata.get("datas") or []]
    datas_b = [(d.get("preferredFileName"), d.get("digest")) for d in b.metadata.get("datas") or []]
    for entry in _multiset_diff("datas", datas_a, datas_b):
        names = {n for n, _d in entry["a"] + entry["b"]}
        for name in sorted(names, key=str):
            diffs.append({
                "key": f"datas:{name}",
                "a": [d for d in entry["a"] if d[0] == name],
                "b": [d for d in entry["b"] if d[0] == name],
            })
    zip_a = Counter(a.zip_entries)
    zip_b = Counter(b.zip_entries)
    for name in sorted({e[0] for e in (zip_a - zip_b) + (zip_b - zip_a)}):
        diffs.append({
            "key": f"zip:{name}",
            "a": [list(e[1:]) for e in (zip_a - zip_b).elements() if e[0] == name],
            "b": [list(e[1:]) for e in (zip_b - zip_a).elements() if e[0] == name],
        })
    return diffs


def mark_allowed(diffs: list[dict], allow: list[str]) -> list[dict]:
    patterns = [re.compile(p) for p in allow]
    for d in diffs:
        d["allowed"] = any(p.search(d["key"]) for p in patterns)
    return diffs


def differing_slides(diffs: list[dict]) -> list[int]:
    return sorted({int(d["key"].split(":")[1]) for d in diffs if d["key"].startswith("slide:")})


def run(a_path: str | Path, b_path: str | Path, *, allow: Sequence[str] = (), refs: bool = True) -> dict:
    a, b = load_deck(a_path), load_deck(b_path)
    diffs = mark_allowed(compare(a, b, refs=refs), list(allow))
    return {
        "a": str(a_path),
        "b": str(b_path),
        "allow": list(allow),
        "differing_slides": differing_slides(diffs),
        "unallowed": sum(not d["allowed"] for d in diffs),
        "diffs": diffs,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--allow", action="append", default=[], metavar="REGEX")
    ap.add_argument("--json", dest="json_out", metavar="OUT")
    args = ap.parse_args(argv)
    try:
        report = run(args.a, args.b, allow=args.allow)
    except UndecodableIWAMember as exc:
        print(f"undecodable member: {exc}", file=sys.stderr)
        return 2
    for d in report["diffs"]:
        print(f"{'allowed ' if d['allowed'] else 'DIFF    '}{d['key']}")
    print(
        f"{len(report['diffs'])} differences, {report['unallowed']} not allowed; "
        f"differing slides: {report['differing_slides'] or 'none'}"
    )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
    return 0 if report["unallowed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
