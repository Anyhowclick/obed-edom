"""Census of group-residual sub-causes on the operator wall deck. READ-ONLY.

Usage: uv run python group_census.py <deck.key> > groups_census_raw.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from obed_edom import iwa_geometry as G
from obed_edom.iwa_geometry import (
    _geom_dict, _group_union, _has_effect_style, _is_rotated, _mask_geom,
    _masked_rect, _path_source, _xywha, compose_geometry,
)
from obed_edom.iwa_runs import _load_deck, slide_order

SLIDES = set(range(1, 130)) | set(range(135, 144)) | set(range(145, 156))


def sub_causes(group_id, objects, seen, depth=0, acc=None):
    """Per-trigger detail mirroring _group_residual_reason, but WITHOUT early return."""
    if acc is None:
        acc = {"zero_extent_text": [], "off_axis_mask": [], "effect": [],
               "rotated_nested_group": [], "max_depth": 0, "child_kinds": Counter(),
               "n_children": 0}
    if group_id in seen:
        return acc
    seen.add(group_id)
    acc["max_depth"] = max(acc["max_depth"], depth)
    group = objects.get(group_id)
    if not group:
        return acc
    for ref in group.get("children") or []:
        cid = ref.get("identifier")
        if cid is None:
            continue
        child = objects.get(str(cid))
        if not child:
            continue
        acc["n_children"] += 1
        pb = child.get("_pbtype")
        acc["child_kinds"][pb] += 1
        if pb == "TSD.GroupArchive":
            if _is_rotated(_xywha(_geom_dict(child))[4]):
                acc["rotated_nested_group"].append(
                    {"id": str(cid), "angle": _xywha(_geom_dict(child))[4], "depth": depth + 1})
            sub_causes(str(cid), objects, seen, depth + 1, acc)
            continue
        _cx, _cy, cw, ch, _ca = _xywha(_geom_dict(child))
        if pb == "TSWP.ShapeInfoArchive" and (cw == 0.0 or ch == 0.0):
            found = _path_source(child)
            key = found[0] if found else None
            ns = (found[1].get("naturalSize") or {}) if found else {}
            acc["zero_extent_text"].append({
                "id": str(cid), "w": cw, "h": ch,
                "isTextBox": bool(child.get("isTextBox")),
                "pathsource": key,
                "nw": float(ns.get("width") or 0.0), "nh": float(ns.get("height") or 0.0),
                "depth": depth + 1,
            })
        if pb in ("TSD.ImageArchive", "TSD.MovieArchive"):
            mg = _mask_geom(child, objects)
            if mg:
                _rect, off = _masked_rect(_geom_dict(child), mg)
                if off:
                    acc["off_axis_mask"].append({
                        "id": str(cid), "frame_angle": _xywha(_geom_dict(child))[4],
                        "mask_angle": _xywha(mg)[4], "depth": depth + 1})
        if _has_effect_style(child):
            acc["effect"].append({"id": str(cid), "pbtype": pb, "depth": depth + 1})
    return acc


def main(path):
    objects, id_to_file, _fi = _load_deck(path)
    out = []
    masked_top = []
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        n = idx + 1
        if n not in SLIDES or slide_id not in objects:
            continue
        slide = objects[slide_id]
        for rec in compose_geometry(slide, objects):
            if rec["kind"] in ("image", "movie"):
                obj = objects.get(rec["id"]) or {}
                mref = (obj.get("mask") or {}).get("identifier")
                if mref is None:
                    continue
                mg = _mask_geom(obj, objects)
                mid = str(mref)
                masked_top.append({
                    "slide": n, "ki": rec["kindIndex"], "id": rec["id"],
                    "needs": rec.get("needs_keynote"),
                    "frame_angle": _xywha(_geom_dict(obj))[4] if obj else None,
                    "mask_angle": _xywha(mg)[4] if mg else None,
                    "mask_resolved": bool(mg),
                    "cross_member": id_to_file.get(mid) != id_to_file.get(rec["id"]),
                })
            if rec["kind"] != "group":
                continue
            gobj = objects.get(rec["id"]) or {}
            gx, gy, gw, gh, ga = _xywha(_geom_dict(gobj))
            acc = sub_causes(rec["id"], objects, set())
            union = _group_union(rec["id"], gx, gy, objects, set())
            out.append({
                "slide": n, "ki": rec["kindIndex"], "id": rec["id"],
                "needs": rec.get("needs_keynote"),
                "angle": ga, "stored": [gx, gy, gw, gh],
                "union": list(union) if union else None,
                "depth": acc["max_depth"], "n_children": acc["n_children"],
                "child_kinds": dict(acc["child_kinds"]),
                "zero_extent_text": acc["zero_extent_text"],
                "off_axis_mask": acc["off_axis_mask"],
                "effect": acc["effect"],
                "rotated_nested_group": acc["rotated_nested_group"],
            })
    json.dump({"groups": out, "masked_top": masked_top}, sys.stdout)


if __name__ == "__main__":
    main(sys.argv[1])
