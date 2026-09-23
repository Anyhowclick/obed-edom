"""m0 census: text drawables (stored w > 0) by h sentinel, flags, vertical/paragraph alignment, path source, rotation."""
import sys
from collections import Counter

from obed_edom.iwa_geometry import _geom_dict, _is_rotated, _path_source, _vertical_alignment, _xywha, compose_geometry
from obed_edom.iwa_runs import _load_deck, slide_order
from obed_edom.iwa_text_shape import geometry_flags, shape_style

DETAIL_SLIDES = (96, 103)


def rows(deck):
    objects, _id_to_file, _file_ids = _load_deck(deck)
    cache = {}
    for n, (slide_id, _skipped) in enumerate(slide_order(objects), 1):
        slide = objects.get(slide_id)
        if not slide:
            continue
        for rec in compose_geometry(slide, objects):
            if rec["kind"] != "text":
                continue
            obj = objects.get(rec["id"]) or {}
            geom = _geom_dict(obj)
            x, y, w, h, a = _xywha(geom)
            if w <= 0:
                continue
            ps = _path_source(obj)
            nat = (ps[1].get("naturalSize") or {}) if ps else {}
            style = shape_style(obj, objects, cache)
            yield {
                "slide": n, "ki": rec["kindIndex"], "id": rec["id"],
                "x": x, "y": y, "w": w, "h": h, "angle": a,
                "grow": h == 0.0, "flags": geometry_flags(geom),
                "valign": _vertical_alignment(obj, objects),
                "halign": style.alignment if style else "<no-storage>",
                "path": ps[0] if ps else None, "rot": _is_rotated(a),
                "nw": float(nat.get("width") or 0.0), "nh": float(nat.get("height") or 0.0),
                "text": (rec.get("text") or "")[:30].replace("\n", " "),
            }


def table(title, counter, header):
    print(f"\n### {title}\n")
    print("| " + " | ".join(header) + " | n |")
    print("|" + "---|" * (len(header) + 1))
    for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        key = key if isinstance(key, tuple) else (key,)
        print("| " + " | ".join(str(k) for k in key) + f" | {n} |")
    print(f"| **total** |" + " |" * (len(header) - 1) + f" {sum(counter.values())} |")


def main(deck):
    data = list(rows(deck))
    grow = [r for r in data if r["grow"]]
    print(f"# m0 census: {deck}\n\ntext drawables with stored w > 0: {len(data)}; h == 0: {len(grow)}; h > 0: {len(data) - len(grow)}")
    table("h class x width-fixed bit x height-fixed bit", Counter(
        ("h==0" if r["grow"] else "h>0", bool(r["flags"] & 1), bool(r["flags"] & 2)) for r in data),
        ["h", "width-fixed", "height-fixed"])
    table("h class x naturalSize state", Counter(
        ("h==0" if r["grow"] else "h>0", "nw>0" if r["nw"] > 0 else "nw=0", "nh>0" if r["nh"] > 0 else "nh=0") for r in data),
        ["h", "nw", "nh"])
    table("h == 0: vertical x paragraph alignment x path source x rotated", Counter(
        (r["valign"], r["halign"], r["path"], r["rot"]) for r in grow),
        ["valign", "halign", "path", "rotated"])
    table("h == 0: vertical alignment", Counter(r["valign"] for r in grow), ["valign"])
    table("h == 0: paragraph alignment", Counter(r["halign"] for r in grow), ["halign"])
    table("h > 0: vertical alignment", Counter(r["valign"] for r in data if not r["grow"]), ["valign"])
    for n in DETAIL_SLIDES:
        print(f"\n### slide {n} text rows\n")
        print("| ki | id | x | y | w | h | angle | flags | valign | halign | path | nw | nh | text |")
        print("|" + "---|" * 14)
        for r in data:
            if r["slide"] == n:
                print(f"| {r['ki']} | {r['id']} | {r['x']:.1f} | {r['y']:.1f} | {r['w']:.1f} | {r['h']:.1f} | {r['angle']:.1f} "
                      f"| {r['flags']} | {r['valign']} | {r['halign']} | {r['path']} | {r['nw']:.1f} | {r['nh']:.1f} | {r['text']} |")


if __name__ == "__main__":
    main(sys.argv[1])
