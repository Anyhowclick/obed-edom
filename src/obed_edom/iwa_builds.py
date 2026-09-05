"""Offline read/plan/verify of KN.SlideArchive builds, buildChunks and transition.

Keynote's sdef has no build class (``slide.builds()`` always throws — see
``inspect_keynote.js``), so a reuse target's builds/transition can only be corrected
by a surgical offline IWA patch, proven to survive a Keynote 15.3.1 open and re-save
(``output/probe-builds/RUNBOOK.txt``). This module never opens Keynote; it is only
ever driven by ``remap_keynote.restore_source_builds``.
"""
from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from obed_edom.iwa_kindindex import derive_kind_index
from obed_edom.iwa_runs import _load_deck, _normalize_text, _slide_group_child_text, slide_order
from obed_edom.offline_inspect import _build_data_index, _data_identifier


def build_identity(
    kind: str, text: str | None, file_name: str | None, child_sig: str | None
) -> tuple[Any, ...]:
    """Geometry-free target key: survives the 7680->1920 canvas shrink between wall and CG."""
    if kind in ("text", "shape"):
        return (kind, _normalize_text(text))
    if kind in ("image", "movie"):
        return (kind, file_name or "")
    if kind == "group":
        return ("group", child_sig or "")
    return (kind,)


def _ref_id(ref: dict | None) -> str | None:
    if not ref:
        return None
    value = ref.get("identifier")
    return str(value) if value is not None else None


def _build_effect_animtype(build_obj: dict) -> tuple[Any, Any]:
    """Lifted from output/probe-builds/verify_builds.py::build_effect_animtype."""
    attrs = build_obj.get("attributes") or {}
    anim = attrs.get("animationAttributes") or {}
    effect = anim.get("effect") if anim.get("effect") is not None else attrs.get("databaseEffect")
    animation_type = (
        anim.get("animationType")
        if anim.get("animationType") is not None
        else attrs.get("databaseAnimationType")
    )
    return effect, animation_type


def _transition_effect_duration(transition: dict | None) -> tuple[Any, Any] | None:
    """Lifted from output/probe-builds/verify_builds.py::slide_transition."""
    if not transition:
        return None
    attrs = transition.get("attributes") or {}
    anim = attrs.get("animationAttributes") or {}
    effect = anim.get("effect") if anim.get("effect") is not None else attrs.get("databaseEffect")
    duration = anim.get("duration") if anim.get("duration") is not None else attrs.get("databaseDuration")
    return (effect, duration)


def _contains_identifier(node: Any) -> bool:
    """True if a nested dict anywhere under ``node`` carries an 'identifier' key — a
    cross-member reference the patcher must refuse to copy verbatim into another slide."""
    if isinstance(node, dict):
        if "identifier" in node:
            return True
        return any(_contains_identifier(v) for v in node.values())
    if isinstance(node, list):
        return any(_contains_identifier(v) for v in node)
    return False


def deck_builds(path: str | Path, *, deck: Any = None) -> dict[int, dict]:
    """``{slide number (1-based): {"slideId", "builds": [...], "transition": dict|None}}``.

    Each build record: ``{"buildId", "chunkIds", "kind", "kindIndex", "effect",
    "animationType", "identity"}``. Every build in these decks targets a top-level
    drawable (measured: 593/593 source, 1515/1515 output); a build whose drawable does
    not resolve to one is dropped — it cannot be matched to source/output identity and
    offers no patch instruction.
    """
    objects, _id_to_file, _file_ids = deck if deck is not None else _load_deck(path)
    try:
        with zipfile.ZipFile(path) as zf:
            data_index = _build_data_index(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        # `deck` already decoded (a caller-supplied tuple, e.g. a test double, or a
        # `path` that is no longer the real file) — image/movie identity degrades to
        # an empty fileName rather than crashing a read-only attach.
        data_index = {}

    chunks_by_build: dict[str, list[str]] = {}
    for obj_id, obj in objects.items():
        if obj.get("_pbtype") != "KN.BuildChunkArchive":
            continue
        bid = _ref_id(obj.get("build"))
        if bid is not None:
            chunks_by_build.setdefault(bid, []).append(obj_id)

    cache: dict = {}
    out: dict[int, dict] = {}
    for idx, (slide_id, _skipped) in enumerate(slide_order(objects)):
        slide = objects.get(slide_id)
        if slide is None:
            continue
        # First membership wins (KIND_ORDER order) — a dual text/custom-shape drawable
        # is a narrow edge case never hit by a build's target on these decks.
        addressed: dict[str, dict] = {}
        for rec in derive_kind_index(slide, objects):
            addressed.setdefault(rec["id"], rec)
        group_child_text = _slide_group_child_text(slide, objects, cache)

        records: list[dict] = []
        for ref in slide.get("builds") or []:
            bid = _ref_id(ref)
            build = objects.get(bid) if bid else None
            if build is None:
                continue
            drawable_id = _ref_id(build.get("drawable"))
            rec = addressed.get(drawable_id) if drawable_id else None
            if rec is None:
                continue
            kind, kind_index = rec["kind"], rec["kindIndex"]
            drawable = objects.get(drawable_id) or {}
            text = file_name = child_sig = None
            if kind in ("text", "shape"):
                text = rec.get("text")
            elif kind in ("image", "movie"):
                data_id = _data_identifier(drawable)
                file_name = data_index.get(data_id) if data_id else None
            elif kind == "group":
                child_sig = group_child_text.get(kind_index)
            effect, animation_type = _build_effect_animtype(build)
            records.append(
                {
                    "buildId": bid,
                    "chunkIds": list(chunks_by_build.get(bid, [])),
                    "kind": kind,
                    "kindIndex": kind_index,
                    "effect": effect,
                    "animationType": animation_type,
                    "identity": build_identity(kind, text, file_name, child_sig),
                }
            )
        out[idx + 1] = {
            "slideId": slide_id,
            "builds": records,
            "transition": slide.get("transition"),
        }
    return out


def plan_build_patch(
    src_by_index: dict[int, dict], out_by_index: dict[int, dict], slides: Any
) -> dict[str, Any]:
    """Per-slide build/transition patch instructions for ``slides`` (the reuse
    targets) — pure, no I/O. Keeps ``min(source_count, output_count)`` per
    ``(effect, animationType, identity)`` key, drops every key absent from the
    source, and orders survivors by their matched SOURCE build's index so click
    order matches the source exactly. Returns ``{"plans": {slideId: {"builds":
    [ids], "buildChunks": [ids], "transition": dict|None}}, "report": [{"slide",
    "kept", "dropped", "retimed"}, ...]}``.
    """
    plans: dict[str, dict] = {}
    report: list[dict] = []
    for number in sorted(slides):
        src = src_by_index.get(number)
        out = out_by_index.get(number)
        if src is None or out is None:
            report.append({"slide": number, "kept": 0, "dropped": 0, "retimed": False, "missing": True})
            continue

        def key_of(build: dict) -> tuple:
            return (build["effect"], build["animationType"], build["identity"])

        src_by_key: dict[tuple, list[tuple[int, dict]]] = {}
        for src_index, build in enumerate(src["builds"]):
            src_by_key.setdefault(key_of(build), []).append((src_index, build))
        out_by_key: dict[tuple, list[dict]] = {}
        for build in out["builds"]:
            out_by_key.setdefault(key_of(build), []).append(build)

        assigned: list[tuple[int, dict]] = []
        for key, out_group in out_by_key.items():
            src_group = src_by_key.get(key) or []
            for src_index, out_build in zip((i for i, _b in src_group), out_group):
                assigned.append((src_index, out_build))
        assigned.sort(key=lambda pair: pair[0])
        ordered = [build for _src_index, build in assigned]

        chunk_ids: list[str] = []
        for build in ordered:
            chunk_ids.extend(build["chunkIds"])

        transition = src.get("transition")
        if transition is not None and _contains_identifier(transition):
            transition = None  # refuse a cross-member reference; leave the output's own
        retimed = _transition_effect_duration(transition) != _transition_effect_duration(
            out.get("transition")
        )

        plans[out["slideId"]] = {
            "builds": [b["buildId"] for b in ordered],
            "buildChunks": chunk_ids,
            "transition": transition,
        }
        report.append(
            {
                "slide": number,
                "kept": len(ordered),
                "dropped": len(out["builds"]) - len(ordered),
                "retimed": retimed,
            }
        )
    return {"plans": plans, "report": report}


def verify_builds(
    src_by_index: dict[int, dict], out_by_index: dict[int, dict], slides: Any = None
) -> dict[str, list[dict]]:
    """Multiset-compare every slide in ``slides`` (default: every slide in either
    deck) by ``(effect, animationType, identity)`` and its transition. Surplus
    (output has something the source lacks) or a transition mismatch is load-bearing
    — the caller raises. Shortfall is expected (an object may legitimately have been
    deleted, e.g. a dropped side-panel column) and is reported, never raised.
    """
    wanted = set(slides) if slides is not None else set(out_by_index) | set(src_by_index)
    surplus: list[dict] = []
    missing: list[dict] = []
    transitions: list[dict] = []
    for number in sorted(wanted):
        src = src_by_index.get(number) or {"builds": [], "transition": None}
        out = out_by_index.get(number) or {"builds": [], "transition": None}
        src_counts = Counter((b["effect"], b["animationType"], b["identity"]) for b in src["builds"])
        out_counts = Counter((b["effect"], b["animationType"], b["identity"]) for b in out["builds"])
        for key in set(src_counts) | set(out_counts):
            delta = out_counts.get(key, 0) - src_counts.get(key, 0)
            if delta > 0:
                surplus.append(
                    {"slide": number, "effect": key[0], "animationType": key[1], "identity": key[2], "count": delta}
                )
            elif delta < 0:
                missing.append(
                    {"slide": number, "effect": key[0], "animationType": key[1], "identity": key[2], "count": -delta}
                )
        src_t = _transition_effect_duration(src.get("transition"))
        out_t = _transition_effect_duration(out.get("transition"))
        if src_t != out_t:
            transitions.append({"slide": number, "source": src_t, "output": out_t})
    return {"surplus": surplus, "missing": missing, "transitions": transitions}
