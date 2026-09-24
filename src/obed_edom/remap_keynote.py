from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from obed_edom import keynote_app, offline_write
from obed_edom.inspect import (
    LegacyInspectFailed,
    _truthy_cache,
    cached_payload,
    complete_cached_wall_payload,
    export_slide_images,
    inspect_keynote,
    inspect_keynote_checker,
    preview_pngs,
    store_inspect_payload,
    wall_payload_carries_aspect,
)
from obed_edom.keynote import _run_stat_finalize, read_template_stat_sizes
from obed_edom.map_remap import (
    adjust_child_resize_indexes,
    navigator_numbering,
    CG_HEIGHT,
    CG_WIDTH,
    DEFAULT_CARD_STROKE,
    GRID_MIN_CLEAR,
    format_slide_range,
    learn_recipe,
    plan_payload,
    roster_slides,
    score_against_gold,
    slides_for_plan,
    summarize_plan,
)
from obed_edom.osascript_runner import parse_json_stdout, run_jxa

REMAP_JS = Path(__file__).resolve().parent / "remap_keynote.js"

# AppleScript index is JXA kindIndex + 1 (same sdef collection, same order).
_AS_KIND_NAMES = {
    "text": "text item",
    "image": "image",
    "shape": "shape",
    "movie": "movie",
    "group": "group",
    "line": "line",
}


def _as_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", '" & return & "')
    )


def _delete_or_hide_placeholder_lines(
    number: int, ordinal: int, addr: str, *, indent: str = "        "
) -> list[str]:
    """``delete theObj``, except Keynote refuses to delete the slide's default title/body
    item (errNum -10003, read-only per Keynote.sdef) -- hide it instead and log
    ``HIDDEN\\t<number>\\t<addr>\\ttitle``/``body``."""
    escaped_addr = _as_escape(addr)
    body = [
        "set isTitle to false",
        "set isBody to false",
        "try",
        f"  set isTitle to (theObj is (default title item of slide {ordinal}))",
        "end try",
        "try",
        f"  if not isTitle then set isBody to (theObj is (default body item of slide {ordinal}))",
        "end try",
        "if isTitle then",
        f"  set title showing of slide {ordinal} to false",
        f'  log ("HIDDEN" & tab & "{number}" & tab & "{escaped_addr}" & tab & "title")',
        "else if isBody then",
        f"  set body showing of slide {ordinal} to false",
        f'  log ("HIDDEN" & tab & "{number}" & tab & "{escaped_addr}" & tab & "body")',
        "else",
        "  delete theObj",
        "end if",
    ]
    return [f"{indent}{ln}" for ln in body]

# Emitted by `_build_slide_geometry_script`'s per-spec `on error` and parsed back out of
# osascript's stderr by `offline_write._run_fallback_scripts`. Pass 1 runs the same body
# via JXA's `runAppleScript` -> `doShellScript`, which discards stderr on a zero exit, so
# a pass-1 marker is swallowed today (harmless: no diagnostic, not a regression).
GEOM_UNWRITABLE_MARKER = "OBED_GEOM_UNWRITABLE"


def as_geometry_enabled() -> bool:
    """Batched-AppleScript geometry path (default ON). `OBED_AS_GEOMETRY=0` forces legacy JXA."""
    return os.environ.get("OBED_AS_GEOMETRY", "").strip().lower() not in {"0", "false", "no", "off"}


def suppress_geometry_slides() -> set[int]:
    """1-based slides whose pass-1 write is attrs-only. Without `OBED_SUPPRESS_GEOMETRY`, empty-asGeom falls through to JXA full path."""
    raw = os.environ.get("OBED_SUPPRESS_GEOMETRY", "")
    slides: set[int] = set()
    for token in raw.replace(",", " ").split():
        try:
            slides.add(int(token))
        except ValueError:
            continue
    return slides


def offline_read_mode(explicit: str | None = None) -> str:
    """`on` (default two-tier IWA+bulk) or `off` (legacy JXA inspect). `explicit` wins over `OBED_OFFLINE_READ`."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_READ", "")).strip().lower()
    return raw if raw in {"on", "off"} else "on"


def offline_write_mode(explicit: str | None = None, *, say: Callable[[str], None] | None = None) -> str:
    """`on` (default, surgical offline IWA patch), `off` (scripted AppleScript geometry),
    or `verify` (patch + live verify). Env `OBED_OFFLINE_WRITE`; unknown tokens fall back to `on`. Forced `off` when `as_geometry_enabled()` is False:
    the offline write's AppleScript fallback is the same batched-geometry body that flag disables."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_WRITE", "")).strip().lower()
    mode = raw if raw in {"off", "verify"} else "on"
    if mode != "off" and not as_geometry_enabled():
        if say:
            say(
                f"OBED_OFFLINE_WRITE={mode!r} needs OBED_AS_GEOMETRY on (its AppleScript "
                "fallback is the batched-geometry body); forcing offline write off."
            )
        return "off"
    return mode


def zorder_write_mode(
    explicit: str | None = None, *, offline_mode: str | None = None,
    say: Callable[[str], None] | None = None,
) -> str:
    """`on` (default, offline z-order patch), `off` (GUI Bring-to-Front raise path), or
    `verify` (patch + a second read-back decode). Env `OBED_ZORDER_WRITE`; unknown tokens
    fall back to `on`. Forced `off` without the `iwa` extra (mirrors `probe_iwa_extra`),
    and forced `off` when `offline_mode` (the caller's already-resolved
    `offline_write_mode()`) is `off` — there are no offline slides to raise against."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_ZORDER_WRITE", "")).strip().lower()
    mode = raw if raw in {"off", "verify"} else "on"
    if mode == "off":
        return mode
    if offline_mode == "off":
        if say:
            say(f"OBED_ZORDER_WRITE={mode!r} needs OBED_OFFLINE_WRITE on; forcing z-order write off.")
        return "off"
    try:
        import keynote_parser  # noqa: F401,PLC0415
        import obed_edom.iwa_write  # noqa: F401,PLC0415
    except Exception as exc:  # noqa: BLE001 — any import failure forces off
        if say:
            say(f"OBED_ZORDER_WRITE={mode!r} needs the `iwa` extra ({type(exc).__name__}: {exc}); "
                "forcing z-order write off.")
        return "off"
    return mode


def offline_text_reposition_enabled(
    explicit: str | None = None, *, offline_mode: str | None = None,
    say: Callable[[str], None] | None = None,
) -> bool:
    """Offline reposition of autosize text boxes (default ON). Env `OBED_OFFLINE_TEXT`
    (`0`/`false`/`no`/`off` disables). An autosize box's `naturalSize` is Keynote's render
    cache, unwritable offline, so today it hard-misses to the AppleScript fallback; when ON
    the offline writer re-seats it (position only, no size -- pass 1 already regrew it).
    Forced OFF when `offline_mode` is `off` (no offline slides to patch)."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_TEXT", "")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw not in {"", "1", "true", "yes", "on"}:
        if say:
            say(f"Unknown OBED_OFFLINE_TEXT value {raw!r}; forcing offline text off.")
        return False
    if offline_mode == "off":
        if say:
            say("OBED_OFFLINE_TEXT needs OBED_OFFLINE_WRITE on; no offline slides to reposition.")
        return False
    return True


def offline_maskcrop_enabled(
    explicit: str | None = None, *, offline_mode: str | None = None,
    say: Callable[[str], None] | None = None,
) -> bool:
    """Offline write of masked-media CROPs (default ON). Env `OBED_OFFLINE_MASKCROP`
    (`0`/`false`/`no`/`off` disables). The surgical writer writes any axis-aligned
    within-frame crop
    (offset included) via the existing `_masked_media_fields` transform. Rotated and
    cross-member crops stay refused. Forced OFF when `offline_mode` is `off`."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_MASKCROP", "")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw not in {"", "1", "true", "yes", "on"}:
        if say:
            say(f"Unknown OBED_OFFLINE_MASKCROP value {raw!r}; forcing masked crops off.")
        return False
    if offline_mode == "off":
        if say:
            say("OBED_OFFLINE_MASKCROP needs OBED_OFFLINE_WRITE on; no offline slides to write.")
        return False
    return True


def offline_hides_mode(
    explicit: str | None = None, *, offline_mode: str | None = None,
    say: Callable[[str], None] | None = None,
) -> str:
    """`on` (default: pass 1 defers the hides of eligible slides; the IWA writer deletes them
    after the save), `off` (kill switch: pass 1 deletes hides in Keynote) or `verify` (plus a
    whole-deck reference check). Env `OBED_OFFLINE_HIDES`; unknown tokens force `off`, as in
    `offline_maskcrop_enabled`. Forced `off` when `offline_mode` is `off` (also covers a
    missing `iwa` extra via `probe_iwa_extra`)."""
    raw = (explicit if explicit is not None else os.environ.get("OBED_OFFLINE_HIDES", "")).strip().lower()
    if raw == "off":
        return "off"
    raw = raw or "on"
    if raw not in {"on", "verify"}:
        if say:
            say(f"Unknown OBED_OFFLINE_HIDES value {raw!r}; forcing offline hides off.")
        return "off"
    if offline_mode == "off":
        if say:
            say(f"OBED_OFFLINE_HIDES={raw!r} needs OBED_OFFLINE_WRITE on; forcing offline hides off.")
        return "off"
    return raw


def _debug_snapshot_pass1(
    dest: Path, say: Callable[[str], None] | None = None, *, variant: str | None = None,
) -> None:
    """Diagnostic: when `OBED_DEBUG_PASS1_SNAPSHOT` is a path, copy the pass-1-saved deck
    there for an offline `naturalSize` census (the owner-gated text experiment's conversion
    ceiling); `variant` writes `<stem>.<variant>.key` beside it instead. No-op otherwise;
    never fails the run."""
    target = os.environ.get("OBED_DEBUG_PASS1_SNAPSHOT", "").strip()
    if not target:
        return
    if variant:
        target = str(Path(target).with_name(f"{Path(target).stem}.{variant}.key"))
    try:
        import shutil  # noqa: PLC0415

        shutil.copy2(dest, target)
        if say:
            say(f"Pass-1 snapshot written to {target}.")
    except Exception as exc:  # noqa: BLE001 — diagnostic only, never break the run
        if say:
            say(f"Pass-1 snapshot failed ({type(exc).__name__}: {exc}); continuing.")


def _spec_addr(spec: dict[str, Any]) -> tuple:
    return (int(spec.get("slide", -1)), str(spec.get("kind")), int(spec.get("kindIndex", -1)))


def _spec_fields_equal(a: dict[str, Any], b: dict[str, Any], tol: float = 2.0) -> bool:
    for key in (set(a) | set(b)) - {"itemIndex"}:
        av, bv = a.get(key), b.get(key)
        if key in ("x", "y", "w", "h"):
            try:
                if abs(float(av) - float(bv)) > tol:
                    return False
            except (TypeError, ValueError):
                if av != bv:
                    return False
        elif key in ("start", "end"):
            if not (isinstance(av, (list, tuple)) and isinstance(bv, (list, tuple))
                    and len(av) >= 2 and len(bv) >= 2
                    and abs(float(av[0]) - float(bv[0])) <= tol
                    and abs(float(av[1]) - float(bv[1])) <= tol):
                if av != bv:
                    return False
        elif av != bv:
            return False
    return True


def _specs_equivalent(off: list[dict], jxa: list[dict]) -> bool:
    off_map = {_spec_addr(s): s for s in off}
    jxa_map = {_spec_addr(s): s for s in jxa}
    if set(off_map) != set(jxa_map):
        return False
    return all(_spec_fields_equal(off_map[k], jxa_map[k]) for k in off_map)


def _merge_legacy_slides(
    payload: dict[str, Any],
    source: Path,
    slide_numbers: list[int],
    *,
    use_cache: bool | None = None,
) -> None:
    """Replace the given slides' items in `payload` with one scoped legacy inspect."""
    if not slide_numbers:
        return
    legacy = inspect_keynote(
        source, slide_range=frozenset(int(n) for n in slide_numbers), use_cache=use_cache
    )
    by_number = {
        int(s.get("number") or (int(s.get("index") or 0) + 1)): s
        for s in legacy.get("slides") or []
    }
    for slide in payload.get("slides") or []:
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        repl = by_number.get(number)
        if repl is None:
            continue
        prior = {
            (it.get("kind"), it.get("kindIndex")): it.get("aspect")
            for it in (slide.get("items") or [])
            if "aspect" in it
        }
        for key in ("items", "groupedText", "master", "skipped"):
            if key in repl:
                slide[key] = repl[key]
        for it in slide.get("items") or []:
            if it.get("kind") in {"image", "movie"}:
                key = (it.get("kind"), it.get("kindIndex"))
                if key in prior:
                    it["aspect"] = prior[key]
        # This slide's items came from a scoped legacy (JXA) inspect, not the offline
        # decode — its group rects are live union frames, not archive offsets, so
        # attach_group_children must not attach children to it despite the payload's
        # overall reader staying "offline".
        slide["groupChildrenUnavailable"] = True


def _offline_payload_carries_iwa_ids(payload: dict[str, Any] | None) -> bool:
    """Every item of every offline-decoded slide carries its source `iwaId`; JXA-fallback
    slides (`groupChildrenUnavailable`) and non-offline payloads are exempt."""
    if not isinstance(payload, dict) or payload.get("reader") != "offline":
        return True
    for slide in payload.get("slides") or []:
        if slide.get("groupChildrenUnavailable"):
            continue
        if any(item.get("iwaId") is None for item in slide.get("items") or []):
            return False
    return True


def acquire_wall_payload(
    source: Path,
    *,
    slide_range: Any,
    mode: str,
    say: Callable[[str], None],
) -> dict[str, Any]:
    """Source-wall inspect honouring offline-read mode.

    `on`: IWA + bulk geometry, with per-slide legacy fallback — never drop the whole deck unless tier 1 fails.
    """
    cached = cached_payload(source)
    allowed_readers = {"jxa", "offline"} if mode == "on" else {"jxa"}
    rejected_cache = cached is not None
    usable = complete_cached_wall_payload(cached) and cached.get("reader") in allowed_readers
    carries_aspect = wall_payload_carries_aspect(cached)
    carries_ids = _offline_payload_carries_iwa_ids(cached)
    carries = mode != "on" or (carries_aspect and carries_ids)
    # A cached JXA read is coordinate-space-incompatible with `groupChildren` (archive
    # offsets vs a JXA group's live union frame — see attach_group_children's gate), so in
    # mode "on" it must not be served merely because a fresh offline decode would succeed;
    # re-read offline instead. A live JXA fallback stays allowed once offline read is
    # confirmed genuinely unavailable, below.
    stale_jxa = mode == "on" and usable and carries and cached.get("reader") == "jxa"
    # An offline cache written before per-slide `groupChildrenUnavailable` tagging
    # cannot tell a JXA-fallback slide from a genuinely offline one, so its
    # `groupChildren` may already mix coordinate spaces; re-read rather than trust it.
    stale_mixed = (
        mode == "on"
        and usable
        and carries
        and cached.get("reader") == "offline"
        and not cached.get("offlineFallbackTagged")
    )
    if usable and carries and not stale_jxa and not stale_mixed:
        bulk_errors = cached.get("bulkErrors") or []
        if bulk_errors:
            say(f"WARN: cached {cached['reader']} read for {source.name} carries "
                f"{len(bulk_errors)} bulk-geometry error(s) (see bulkErrors).")
        say(f"Read {source.name} from cached {cached['reader']} payload — "
            "skipped the Keynote source read.")
        return cached

    if stale_jxa:
        say(f"Cached jxa read of {source.name} cannot carry group children; "
            "re-reading offline.")

    if stale_mixed:
        say(f"Cached offline read of {source.name} is not from a mixed-slide-tagged "
            "two-tier read; re-reading offline.")

    if rejected_cache and mode == "on" and usable and not carries_aspect:
        say(f"Cached {cached['reader']} read of {source.name} predates per-item aspect; "
            "re-reading.")
    elif rejected_cache and mode == "on" and usable and not carries_ids:
        say(f"Cached {cached['reader']} read of {source.name} predates per-item "
            "source ids; re-reading.")

    legacy_cache_arg = {"use_cache": False} if rejected_cache else {}
    if mode == "off":
        return inspect_keynote(source, **legacy_cache_arg)

    try:
        from obed_edom.inspect import bulk_geometry  # noqa: PLC0415
        from obed_edom.offline_inspect import (  # noqa: PLC0415 (optional iwa extra)
            two_tier_wall_payload,
        )

        offline = two_tier_wall_payload(
            source, bulk_geometry_fn=bulk_geometry, log=say
        )
    except Exception as exc:  # noqa: BLE001 — any tier-1 failure drops to legacy
        if stale_jxa:
            # The cached jxa payload is complete and carries aspect; it is only
            # children-incompatible, and groupChildrenUnavailable makes any
            # collapsing-group refusal fire correctly on it — no Keynote re-read needed.
            say(f"Offline source read unavailable ({type(exc).__name__}: {exc}); "
                f"serving cached jxa payload for {source.name}.")
            return cached
        if stale_mixed:
            # Untagged: we cannot tell a fallback slide from a genuinely offline one, so
            # refuse every autosize group's size rather than re-read Keynote in full.
            for slide in cached.get("slides") or []:
                slide["groupChildrenUnavailable"] = True
            say(f"Offline source read unavailable ({type(exc).__name__}: {exc}); serving "
                f"cached offline payload for {source.name} with group sizes refused.")
            return cached
        say(f"Offline source read unavailable ({type(exc).__name__}: {exc}); "
            f"using Keynote inspect of {source.name}.")
        return inspect_keynote(source, **legacy_cache_arg)

    sidecar = offline.get("_offline") or {}
    fallback_slides = sidecar.get("fallback_slides") or []

    if not sidecar.get("bulk_ok") and fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Bulk geometry read of {source.name} unavailable and "
            f"{len(fallback_slides)} slide(s) need it {reasons}; "
            f"using Keynote inspect for the whole deck.")
        return inspect_keynote(source, **legacy_cache_arg)

    if fallback_slides:
        from collections import Counter  # noqa: PLC0415

        reasons = dict(Counter(f["reason"] for f in sidecar.get("fallback") or []))
        say(f"Two-tier read of {source.name}: {sidecar.get('spliced', 0)} item(s) "
            f"bulk-confirmed; {len(fallback_slides)} slide(s) fall back to Keynote "
            f"inspect {reasons}: {fallback_slides}.")
        _merge_legacy_slides(
            offline, source, fallback_slides, use_cache=False if rejected_cache else None
        )

    confirmed = "" if not fallback_slides else f" ({len(fallback_slides)} slide(s) via Keynote)"
    omitted = int(sidecar.get("skipped") or 0)
    skipped_note = "" if not omitted else f"; {omitted} Keynote-skipped slide(s) left to the offline tier"
    say(f"Read {source.name} two-tier (offline IWA + bulk geometry){confirmed}{skipped_note} — "
        f"skipped the full Keynote source inspect.")
    offline["reader"] = "offline"
    offline["offlineFallbackTagged"] = True
    if _truthy_cache(None, None):
        try:
            store_inspect_payload(source, offline)
        except OSError as exc:
            say(f"Could not cache the two-tier read of {source.name} ({type(exc).__name__}: {exc}).")
    return offline


def write_timing_enabled() -> bool:
    """When ON (`OBED_WRITE_TIMING=1`), record per-slide/per-phase JXA write timing."""
    return os.environ.get("OBED_WRITE_TIMING", "").strip().lower() in {"1", "true", "yes", "on"}


def geom_props_enabled() -> bool:
    """Fold size into one `set properties {width, height}`; position stays a separate last write.

    Height re-anchors ~18px about centre; folding position into the same record drifts the object.
    """
    return os.environ.get("OBED_GEOM_PROPS", "").strip().lower() not in {"0", "false", "no", "off"}


def _say_write_timing(timing: dict[str, Any], say: Callable[[str], None]) -> None:
    buckets: dict[str, Any] = timing.get("buckets") or {}
    rows = sorted(buckets.items(), key=lambda kv: -(kv[1].get("ms") or 0))
    say("── write timing: phases by total elapsed (ms) ──")
    for name, b in rows:
        ms = int(b.get("ms") or 0)
        n = int(b.get("n") or 0)
        avg = ms / n if n else 0
        say(f"    {name:32} {ms:>7} ms   {n:>4} ×   {avg:5.1f} ms/ea")
    slow = sorted(timing.get("slow") or [], key=lambda d: -(d.get("ms") or 0))
    if slow:
        say(f"── slowest objects (≥{int(timing.get('slowMs') or 0)} ms), top 25 ──")
        for d in slow[:25]:
            say(
                f"    {int(d.get('ms') or 0):>5} ms  {d.get('op',''):16} "
                f"slide {d.get('slide')} {d.get('kind','')}[{d.get('kindIndex')}] "
                f"role={d.get('role','') or '-'} @({d.get('x')},{d.get('y')})"
            )
        say(f"    ({len(slow)} object(s) over threshold total)")


_PASS1_JS_STAGES = (
    "open", "slideSize", "templateOpen", "layoutImport", "layoutApply", "trailingDelete",
    "templateClose", "attrs", "asScript", "hides", "finish", "save", "close",
)


def _path_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _fmt_bytes(n: int) -> str:
    return f"{n / 1e9:.2f} GB" if n >= 1e9 else f"{n / 1e6:.1f} MB"


def _say_pass1_stages(
    py_stages: dict[str, float],
    jxa: dict[str, Any],
    say: Callable[[str], None],
    py_notes: dict[str, str] | None = None,
) -> None:
    """Python stages in seconds; `jxa["stages"]` in ms."""
    notes = py_notes or {}
    for name, sec in py_stages.items():
        note = f" ({notes[name]})" if name in notes else ""
        say(f"Pass 1 stage {name}: {sec:.1f} s{note}")
    stages = jxa.get("stages")
    if not isinstance(stages, dict):
        return
    attributed = 0.0
    for name in _PASS1_JS_STAGES:
        if name not in stages:
            continue
        ms = float(stages[name] or 0)
        attributed += ms
        note = ""
        if name == "slideSize" and jxa.get("sizeProp"):
            note = f" (sizeProp: {jxa['sizeProp']})"
        elif name == "save":
            retried = "yes" if jxa.get("saveRetried") else "no"
            err = jxa.get("saveFirstError")
            note = f" (retried: {retried}{f'; first error: {err}' if err else ''})"
        say(f"Pass 1 stage {name}: {ms / 1000:.1f} s{note}")
    if "total" not in stages:
        return
    total = float(stages["total"] or 0)
    say(f"Pass 1 stage total: {total / 1000:.1f} s")
    wall = py_stages.get("runJxa")
    launch = f"{wall - total / 1000:.1f} s" if wall is not None else "n/a"
    say(f"Pass 1 unattributed: js {(total - attributed) / 1000:.1f} s, osascript/launch {launch}")


def _pass1_census(
    transform_dicts: list[dict[str, Any]],
    suppressed: set[int] | frozenset[int],
    as_geom_slides: set[int] | frozenset[int],
) -> dict[str, int]:
    """Mirror of js `geometryPathForSlide` over `slidesInPlan`, plus per-spec cost classes."""
    slides = {int(t["slide"]) for t in transform_dicts if t.get("slide") is not None}
    attrs = {n for n in slides if n in suppressed}
    as_path = {n for n in slides - attrs if n in as_geom_slides}
    attrs_or_as = attrs | as_path
    specs = [t for t in transform_dicts if t.get("role") != "hide"]
    return {
        "attrs": len(attrs),
        "as": len(as_path),
        "jxa": len(slides) - len(attrs) - len(as_path),
        "specs": len(specs),
        "hides": len(transform_dicts) - len(specs),
        "noAttr": sum(
            1 for t in specs
            if int(t.get("slide") or 1) in attrs_or_as
            and not t.get("font")
            and not t.get("fontSize")
            and len(t.get("color") or ()) < 3
            and t.get("opacity") is None
            and not t.get("locked")
        ),
        "locked": sum(1 for t in specs if t.get("locked")),
        "groupChildren": sum(1 for t in specs if t.get("children")),
    }


def _say_pass1_census(census: dict[str, int], say: Callable[[str], None]) -> None:
    say(
        f"Pass 1 census: slides attrs={census['attrs']} as={census['as']} jxa={census['jxa']}; "
        f"specs {census['specs']} (hides {census['hides']}, no-attr {census['noAttr']}, "
        f"locked {census['locked']}, group-children {census['groupChildren']})"
    )


def _as_num(value: Any) -> str:
    number = float(value)
    if number == int(number):
        return str(int(number))
    return repr(round(number, 2))


def _child_ops_lines(children: list[dict[str, Any]]) -> list[str]:
    """Absolute per-child writes for a group holding an autosize text box.

    The group itself is NEVER written. A Keynote 15.3.1 group resize is an aspect-locked
    uniform scale about the group's LIVE frame and it freezes autosize text children at
    their wrapped height for ever (no later width or font write re-flows them). Children
    take exact absolute writes in slide coordinates and the group's frame follows as the
    union. An autosize child gets a WIDTH only — a height write is ignored AND re-anchors
    the box — then a position centred on its mapped vertical centre using the height
    Keynote has just derived from the new width.

    All-or-nothing: the whole block is guarded by a live collection-count check before
    anything is written. Without it, a mis-addressed or already-stale child would be
    skipped silently while its siblings still get absolute writes — since the group is
    never resized, the group's live frame is the union of whatever landed, so a half
    write produces a phantom group straddling both the old and new positions with no
    repair path (a resize would only re-freeze whatever is left).
    """
    ops: list[str] = []
    required: dict[str, int] = {}
    for child in children:
        name = _AS_KIND_NAMES.get(str(child.get("kind") or ""))
        index = child.get("kindIndex")
        if not name or index is None:
            continue
        required[f"{name}s"] = max(required.get(f"{name}s", 0), int(index) + 1)
        ops += ["    try", f"      set _c to {name} {int(index) + 1} of theObj"]
        if child.get("autosize"):
            ops += [
                f"      set width of _c to {_as_num(child['w'])}",
                "      set _ch to height of _c",
                "      if _ch > 0 then",
                f"        set position of _c to {{{_as_num(child['x'])}, "
                f"({_as_num(child['cy'])} - (_ch / 2))}}",
                "      else",
                f"        set position of _c to {{{_as_num(child['x'])}, {_as_num(child['y'])}}}",
                "      end if",
            ]
        else:
            ops += [
                f"      set properties of _c to {{width:{_as_num(child['w'])}, "
                f"height:{_as_num(child['h'])}}}",
                f"      set position of _c to {{{_as_num(child['x'])}, {_as_num(child['y'])}}}",
            ]
        ops += ["    end try"]
    if not ops:
        return []
    guard = " and ".join(
        f"(count of {plural} of theObj) >= {n}" for plural, n in sorted(required.items())
    )
    return [f"    if {guard} then"] + ops + ["    end if"]


def _build_slide_geometry_script(specs: list[dict[str, Any]], slide_no: int) -> str:
    """One `tell slide N` block setting geometry.

    Width/height before position (height re-anchors ~18px). Lines use endpoints; AppleScript does not yank to (0,0).
    """
    body: list[str] = []
    for spec in specs:
        if spec.get("role") == "hide":
            continue
        kind = str(spec.get("kind") or "")
        name = _AS_KIND_NAMES.get(kind)
        if not name:
            continue
        kind_index = spec.get("kindIndex")
        if kind_index is None:
            kind_index = spec.get("itemIndex")
        if kind_index is None:
            continue
        addr = f"{name} {int(kind_index) + 1}"
        lines = [
            "  try",
            f"    set theObj to {addr}",
            "    set wasLocked to false",
            "    try",
            "      if locked of theObj then",
            "        set locked of theObj to false",
            "        set wasLocked to true",
            "      end if",
            "    end try",
        ]
        start = spec.get("start")
        end = spec.get("end")
        x = spec.get("x")
        y = spec.get("y")
        children = spec.get("children") if kind == "group" else None
        if children:
            # No group-level size or position write on this path — either one would
            # aspect-lock-scale the group about its wrapped live frame and freeze the
            # autosize child (Gold slide 2: 278x88 -> 23x88, name renders as "P").
            lines += _child_ops_lines(children)
        elif geom_props_enabled():
            # Position MUST stay a separate last write: height re-anchors ~18px about centre.
            # Lines have no re-anchor; fold endpoints into one atomic set.
            if kind == "line" and start and end:
                lines += [
                    "    try",
                    "      set properties of theObj to "
                    f"{{start point:{{{_as_num(start[0])}, {_as_num(start[1])}}}, "
                    f"end point:{{{_as_num(end[0])}, {_as_num(end[1])}}}}}",
                    "    end try",
                ]
            else:
                size_props: list[str] = []
                if spec.get("w") is not None:
                    size_props.append(f"width:{_as_num(spec['w'])}")
                if spec.get("h") is not None:
                    size_props.append(f"height:{_as_num(spec['h'])}")
                if size_props:
                    lines += [
                        "    try",
                        f"      set properties of theObj to {{{', '.join(size_props)}}}",
                        "    end try",
                    ]
                if x is not None and y is not None:
                    lines += [
                        "    try",
                        f"      set position of theObj to {{{_as_num(x)}, {_as_num(y)}}}",
                        "    end try",
                    ]
        elif kind == "line" and start and end:
            lines += [
                "    try",
                f"      set start point of theObj to {{{_as_num(start[0])}, {_as_num(start[1])}}}",
                "    end try",
                "    try",
                f"      set end point of theObj to {{{_as_num(end[0])}, {_as_num(end[1])}}}",
                "    end try",
            ]
        else:
            if spec.get("w") is not None:
                lines += [
                    "    try",
                    f"      set width of theObj to {_as_num(spec['w'])}",
                    "    end try",
                ]
            if spec.get("h") is not None:
                lines += [
                    "    try",
                    f"      set height of theObj to {_as_num(spec['h'])}",
                    "    end try",
                ]
            if x is not None and y is not None:
                lines += [
                    "    try",
                    f"      set position of theObj to {{{_as_num(x)}, {_as_num(y)}}}",
                    "    end try",
                ]
        lines += [
            "    try",
            "      if wasLocked then set locked of theObj to true",
            "    end try",
            "  on error",
            f'    log "{GEOM_UNWRITABLE_MARKER} slide={int(slide_no)} kind={kind} '
            f'kindIndex={int(kind_index)}"',
            "  end try",
        ]
        body += lines
    if not body:
        return ""
    # Geometry can run past osascript's 120s default.
    return "\n".join(
        ["with timeout of 3600 seconds", f"tell slide {int(slide_no)}"]
        + body
        + ["end tell", "end timeout"]
    )


def _spec_bears_geometry(spec: dict[str, Any]) -> bool:
    if spec.get("w") is not None or spec.get("h") is not None:
        return True
    if spec.get("x") is not None and spec.get("y") is not None:
        return True
    if spec.get("start") is not None and spec.get("end") is not None:
        return True
    return False


def _slide_geometry_addressable(specs: list[dict[str, Any]]) -> bool:
    """False if any geometry-bearing object is outside `_AS_KIND_NAMES` — keep that slide on JXA."""
    for spec in specs:
        if spec.get("role") == "hide":
            continue
        if not _spec_bears_geometry(spec):
            continue
        if str(spec.get("kind") or "") not in _AS_KIND_NAMES:
            return False
    return True


def _build_as_geometry(
    transform_dicts: list[dict[str, Any]],
    suppress: set[int] | frozenset[int] = frozenset(),
) -> dict[str, str]:
    """Per-slide AppleScript geometry bodies. Suppressed slides omitted so they stay attrs-only (no JXA fallback)."""
    by_slide: dict[int, list[dict[str, Any]]] = {}
    order: list[int] = []
    for spec in transform_dicts:
        slide_no = int(spec.get("slide") or 0)
        if slide_no < 1:
            continue
        if slide_no not in by_slide:
            by_slide[slide_no] = []
            order.append(slide_no)
        by_slide[slide_no].append(spec)
    out: dict[str, str] = {}
    for slide_no in order:
        if slide_no in suppress:
            continue
        specs = by_slide[slide_no]
        if not _slide_geometry_addressable(specs):
            continue
        body = _build_slide_geometry_script(specs, slide_no)
        if body:
            out[str(slide_no)] = body
    return out


def _run_jxa(plan: dict[str, Any]) -> dict[str, Any]:
    plan = {**plan, "bundleId": keynote_app.bundle_id()}
    proc = run_jxa(REMAP_JS, plan, launch=True)
    return parse_json_stdout(proc, "Keynote remap")


def copy_keynote(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    subprocess.run(["ditto", str(source), str(dest)], check=True)
    return dest


def recipe_for(wall: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    return learn_recipe(wall, template)


def _resolve_template_card_sample(card_samples: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Same resolution `plan_slide_transforms` does per wall match (dominant same-size
    cluster + `_card_pitch`), computed once here purely for the operator summary line —
    `recipe["cardSamples"]` is deck-wide and does not depend on which wall group matched."""
    if not card_samples:
        return None
    from collections import defaultdict  # noqa: PLC0415

    from obed_edom.map_remap import _card_pitch, _rect_from_dict  # noqa: PLC0415

    clusters: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for s in card_samples:
        clusters[(round(s["rect"]["w"], 1), round(s["rect"]["h"], 1))].append(s)
    _key, members = max(clusters.items(), key=lambda kv: len(kv[1]))
    w = sum(m["rect"]["w"] for m in members) / len(members)
    h = sum(m["rect"]["h"] for m in members) / len(members)
    raw = [
        {"rect": _rect_from_dict(s["rect"]), "aspect": s["aspect"], "caption": s["caption"]}
        for s in card_samples
    ]
    pitch = _card_pitch(raw, w, h)
    return {"w": w, "h": h, "gutterX": pitch["gutterX"], "gutterY": pitch["gutterY"]}


def preview_wanted_slides(
    wall: dict[str, Any],
    slide_range: Any,
    *,
    keep_side_panels: bool,
    side_content_slides: set[int] | None,
) -> list[int] | None:
    """Slide numbers whose previews the plan will consume: whitelisted slides plus
    roster-keep slides, which pack names from measured free space without the
    whitelist. None means every slide; [] means none (skip preview resolution).
    Decoding only the consumed slides keeps a full-wall run off the ~3.9 GB cost
    of the whole preview set as RGB."""
    plan_slides = slides_for_plan(slide_range)
    if keep_side_panels:
        return plan_slides
    roster_keep, _roster_drop = roster_slides(wall.get("slides") or [])
    packable = set(side_content_slides or ()) | roster_keep
    if plan_slides is not None:
        packable &= set(plan_slides)
    return sorted(packable)


def resolve_source_previews(
    source: Path,
    wall: dict[str, Any],
    *,
    folder: Path | str | None = None,
    wanted: list[int] | None = None,
) -> tuple[dict[int, Any], str, Path | None]:
    """Rendered wall slides keyed by number, for measuring empty space for loose text.
    The third return value is the resolved candidate directory (None when no candidate
    yielded any usable image), for run-record provenance."""
    from PIL import Image  # noqa: PLC0415

    from obed_edom.baseline import deck_digest, preview_cache_dir  # noqa: PLC0415
    from obed_edom.diff_keynotes import map_preview_pngs  # noqa: PLC0415
    from obed_edom.inspect import preview_media  # noqa: PLC0415

    candidates: list[tuple[Path, str]] = []
    if folder:
        candidates.append((Path(folder).expanduser(), "supplied folder"))
    if wall.get("previewDir"):
        candidates.append((Path(str(wall["previewDir"])), "this run's export"))
    try:
        candidates.append((preview_cache_dir(deck_digest(source)), "preview cache"))
    except (OSError, FileNotFoundError):
        pass

    slides = wall.get("slides") or []
    for path, label in candidates:
        if not path.is_dir():
            continue
        images = [p for p in preview_media(path) if p.suffix.lower() != ".mov"]
        if not images:
            continue
        by_index = map_preview_pngs(slides, images)
        out: dict[int, Any] = {}
        for index, png in by_index.items():
            if index >= len(slides):
                continue
            number = int(slides[index].get("number") or index + 1)
            if wanted and number not in wanted:
                continue
            try:
                out[number] = Image.open(png).convert("RGB")
            except OSError:
                continue
        if out:
            detail = f"{label} ({len(images)} image(s) for {len(slides)} slide(s))"
            if len(images) != len(slides):
                detail += " — count differs, check the export is current"
            return out, detail, path
    return {}, "", None


def restore_card_stroke_widths(
    dest: Path, source: Path, wall: dict[str, Any], say: Callable[[str], None]
) -> dict[str, Any]:
    """Canvas shrink divides every image-card stroke width along with the geometry;
    restore each canvas-shrunk card border to its source width, unconditional (not
    gated by OBED_OFFLINE_WRITE), before the stat-finalize pass. Deck untouched on
    any refusal/pairing miss for a given style; a resolved style is patched alone."""
    try:
        from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415
        from obed_edom.iwa_write import (  # noqa: PLC0415
            card_styles,
            match_card_stroke_styles,
            patch_stroke_widths,
        )
    except Exception as exc:  # noqa: BLE001 — optional iwa extra; never break the run
        say(f"Card-border stroke patch unavailable ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    try:
        out_objects, out_id_to_file, _out_fi = _load_deck(dest)
        src_objects, src_id_to_file, _src_fi = _load_deck(source)
    except Exception as exc:  # noqa: BLE001 — offline read is opt-in; never break the run
        say(f"Card-border stroke patch could not read the deck(s) ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    wall_w = float(wall.get("slideWidth") or CG_WIDTH)
    canvas_scale = (CG_WIDTH / wall_w) if wall_w > 0 else 1.0

    match = match_card_stroke_styles(
        card_styles(out_objects, out_id_to_file),
        card_styles(src_objects, src_id_to_file),
        canvas_scale=canvas_scale,
        min_refs=10,
    )
    if not match["out_selected"]:
        return {"skipped": True, "reason": "no card styles selected in the output"}
    for note in match["notes"]:
        say(note)
    if not match["widths"]:
        return {"skipped": True, "reason": "no card style pair passed the guard"}

    for c in match["chosen"]:
        say(f"Card-border stroke: {c['id']} {c['old']} → {c['new']} ({c['refs']} refs).")

    result = patch_stroke_widths(dest, match["widths"])
    if result.get("refused"):
        say(f"Card-border stroke patch REFUSED: {result.get('reason')}")
    return result


def _surplus_slide_note(slide_no: int, patched_slides: set[int]) -> str:
    return f"slide {slide_no} ({'a patched reuse slide' if slide_no in patched_slides else 'NOT a patched reuse slide'})"


def restore_source_builds(
    dest: Path, source: Path, slides: set[int], say: Callable[[str], None]
) -> dict[str, Any]:
    """Verify every slide's builds/buildChunks/transition against the source deck.

    Only `slides` are rewritten (patch-none when that set is empty); every slide
    is still verified, and a surplus anywhere raises. Offline IWA write,
    unconditional (like restore_card_stroke_widths), after stat-finalize. The
    reveal order on a patched slide is restored from the source slide's own
    `buildChunks` (Keynote's render timeline, not `builds` — D8); a wrong reveal
    order on a patched slide raises."""
    try:
        from obed_edom import iwa_builds  # noqa: PLC0415
        from obed_edom.iwa_write import patch_slide_builds  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — optional iwa extra; never break the run
        say(f"Build/transition patch unavailable ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    try:
        src_by_number = iwa_builds.deck_builds(source)
    except Exception as exc:  # noqa: BLE001 — offline read is opt-in; never break the run
        say(f"Build/transition patch could not read the source deck ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}
    try:
        out_by_number = iwa_builds.deck_builds(dest)
    except Exception as exc:  # noqa: BLE001
        say(f"Build/transition patch could not read the output deck ({type(exc).__name__}: {exc}); skipping.")
        return {"skipped": True}

    if set(src_by_number) != set(out_by_number):
        say(
            "Build/transition patch REFUSED: source has "
            f"{len(src_by_number)} slide(s), output has {len(out_by_number)} — skipping."
        )
        return {"skipped": True}

    plan = iwa_builds.plan_build_patch(src_by_number, out_by_number, slides)
    slide_ids = {out_by_number[n]["slideId"] for n in slides if n in out_by_number}
    plans = {sid: p for sid, p in plan["plans"].items() if sid in slide_ids}
    patch_result = patch_slide_builds(dest, plans)
    if patch_result.get("refused"):
        say(f"Build/transition patch REFUSED: {patch_result.get('reason')}")
        return {"skipped": True, "reason": patch_result.get("reason")}

    out_after = iwa_builds.deck_builds(dest) if plans else out_by_number
    verify = iwa_builds.verify_builds(src_by_number, out_after)

    skipped_transitions = {r["slide"]: r["transitionSkipped"] for r in plan["report"] if r.get("transitionSkipped")}
    for slide_no, reason in skipped_transitions.items():
        say(f"WARNING builds: slide {slide_no} transition not restored ({reason}); the output's own transition is kept.")
    shortfall_totals: dict[tuple[int, Any], int] = {}
    for m in verify["missing"]:
        key = (m["slide"], m["effect"])
        shortfall_totals[key] = shortfall_totals.get(key, 0) + m["count"]
    for (slide_no, effect), count in sorted(shortfall_totals.items()):
        say(
            f"WARNING builds: slide {slide_no} lost {count} {effect} "
            "build(s) (the object is no longer on that slide)."
        )
    chain_headless_reasons = {
        "source": "the source itself starts mid-chain",
        "survivors": "the source's first build is not on the output slide, so nothing anchors the timing chain",
        "fields": (
            "the source's first build was kept, but the emitted first chunk is not flagged as a "
            "chain head, so nothing anchors the timing chain"
        ),
        "unresolved": (
            "the source's chunk-0 build could not be resolved to a drawable on the source slide, "
            "so nothing anchors the timing chain"
        ),
    }
    for r in plan["report"]:
        if r.get("chainHeadless"):
            reason = chain_headless_reasons.get(r["chainHeadless"], r["chainHeadless"])
            say(f"WARNING builds: slide {r['slide']} starts mid-chain ({reason}).")
    for r in plan["report"]:
        if r.get("ambiguousPairs"):
            say(
                f"WARNING builds: slide {r['slide']} has {r['ambiguousPairs']} build pair(s) the "
                "source cannot disambiguate; the pairing within them is arbitrary."
            )
    for o in verify["order"]:
        if o["slide"] not in slides:
            say(f"WARNING builds: slide {o['slide']} reveal order differs from source at position {o['at']}.")
    kept = sum(r.get("kept", 0) for r in plan["report"])
    dropped = sum(r.get("dropped", 0) for r in plan["report"])
    retimed = sum(1 for r in plan["report"] if r.get("retimed"))
    say(
        f"Builds follow source: {kept} kept, {dropped} dropped, {retimed} transition(s) restored "
        f"on {len(slides)} slide(s); reveal order follows the source's buildChunks."
    )

    if verify["surplus"]:
        notes = sorted({_surplus_slide_note(s["slide"], slides) for s in verify["surplus"]})
        raise RuntimeError(f"Build patch left a surplus build on {', '.join(notes)}: {verify['surplus'][:5]}")
    transitions = [t for t in verify["transitions"] if t["slide"] not in skipped_transitions]
    if transitions:
        raise RuntimeError(f"Build patch left a transition mismatch: {transitions[:5]}")
    order_on_patched = [o for o in verify["order"] if o["slide"] in slides]
    if order_on_patched:
        notes = sorted({_surplus_slide_note(o["slide"], slides) for o in order_on_patched})
        raise RuntimeError(f"Build patch left a wrong reveal order on {', '.join(notes)}: {order_on_patched[:5]}")

    return {
        "skipped": False,
        "kept": kept,
        "dropped": dropped,
        "retimed": retimed,
        "report": plan["report"],
        "shortfalls": verify["missing"],
        "order": verify["order"],
    }


_DETAIL_LOG_CAP = 40
_RESOLVE_RARE_KINDS = ("sigTwin", "unresolved", "dedupMiss", "skip")


def _say_chunked_detail(
    label: str, parts: list[str], say: Callable[[str], None], trailing_note: str = ""
) -> None:
    if not parts:
        return
    chunks = [parts[i : i + _DETAIL_LOG_CAP] for i in range(0, len(parts), _DETAIL_LOG_CAP)]
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        prefix = f"{label}: ({i}/{total}) " if total > 1 else f"{label}: "
        line = prefix + " ".join(chunk)
        if i == total:
            line += trailing_note
        say(line)


def _resolve_detail_parts(tokens: dict[str, list[str]]) -> tuple[list[str], str]:
    """Rare kinds are never dropped; only the `sigFallback` tail is capped."""
    parts = [f"{k}({a})" for k in _RESOLVE_RARE_KINDS for a in tokens.get(k) or ()]
    fallback = tokens.get("sigFallback") or ()
    kept = fallback[:_DETAIL_LOG_CAP]
    parts += [f"sigFallback({a})" for a in kept]
    note = f" (+{len(fallback) - len(kept)} more)" if len(fallback) > len(kept) else ""
    return parts, note


def _say_stat_finalize_detail(
    child_resize_result: dict[str, Any],
    say: Callable[[str], None],
) -> None:
    tokens = child_resize_result.get("tokens") or {}
    resolve_parts, resolve_note = _resolve_detail_parts(tokens)
    _say_chunked_detail("Stat resolve detail", resolve_parts, say, resolve_note)


def prepare_wall_payload(
    source: Path,
    wall: dict[str, Any],
    template_path: Path,
    template_data: dict[str, Any],
    say: Callable[[str], None],
    *,
    offline_read: str | None = None,
) -> float:
    """Attach group/caption/build context to `wall` and `template_data`; returns the card stroke."""
    try:
        from obed_edom.iwa_runs import attach_group_captions  # noqa: PLC0415

        attach_group_captions(template_path, template_data)
    except Exception as exc:  # noqa: BLE001 — card samples stay unavailable, cards keep the affine size
        say(
            f"Template caption geometry unavailable ({type(exc).__name__}: {exc}); "
            "photo cards will keep today's affine size instead of the template's."
        )

    card_stroke = DEFAULT_CARD_STROKE
    deck = None
    try:
        from obed_edom.iwa_runs import (  # noqa: PLC0415
            _load_deck, attach_group_autosize, attach_group_captions, attach_group_child_text,
            attach_group_children,
        )

        deck = _load_deck(source)
        attach_group_child_text(source, wall, deck=deck)
        attach_group_captions(source, wall, deck=deck)
        # Whether a group holds an autosize text box is an archive fact, valid under any
        # reader; attach it unconditionally so map_remap can refuse a collapsing group
        # write even when groupChildren (below) is unavailable.
        attach_group_autosize(source, wall, deck=deck)
        # Child offsets and offline-composed group frames share an archive coordinate
        # space. Live JXA group frames may instead be child unions, so only attach for
        # actual offline geometry. Reader-less injected payloads retain the old mode
        # contract for compatible callers.
        if wall.get("reader") == "offline" or (
            "reader" not in wall and offline_read_mode(offline_read) == "on"
        ):
            attach_group_children(source, wall, deck=deck)
        else:
            for slide in wall.get("slides") or []:
                slide["groupChildrenUnavailable"] = True
    except Exception as exc:  # noqa: BLE001 — no group signatures/captions on any failure
        say(
            f"Wall IWA decode unavailable ({type(exc).__name__}: {exc}); reuse group dedup "
            "will report a shortfall instead of deduping, photo cards will not be "
            "recognised as cards at all (no groupChildText signature to match on) — they "
            "keep today's affine-mapped size, same as any other unmatched group; groups "
            "holding an autosize text box are unmarked and keep today's group-level "
            "resize (which collapses them)."
        )

    try:
        from obed_edom.iwa_runs import attach_slide_builds  # noqa: PLC0415

        attach_slide_builds(source, wall, deck=deck)
    except Exception as exc:  # noqa: BLE001 — reuse targets keep the donor's builds/transition
        say(
            f"Wall build/transition read unavailable ({type(exc).__name__}: {exc}); reuse donor "
            "rejection for an unfixable build shortfall cannot run, and a coincident stat twin "
            "that carries a build cannot be told apart from a magic-move leftover (stays hidden)."
        )

    try:
        from obed_edom.iwa_runs import _load_deck  # noqa: PLC0415
        from obed_edom.iwa_write import card_styles, select_card_styles  # noqa: PLC0415

        objects, id_to_file, _file_ids = deck if deck is not None else _load_deck(source)
        selected = [
            s
            for s in select_card_styles(card_styles(objects, id_to_file), min_refs=10)
            if not s.get("inherited")
        ]
        widths = sorted(s["width"] for s in selected if s.get("width") is not None)
        if widths:
            card_stroke = widths[len(widths) // 2]
    except Exception as exc:  # noqa: BLE001 — fall back to the measured default
        say(
            f"Card-border stroke read unavailable ({type(exc).__name__}: {exc}); "
            f"the card grid's fallback-pitch floor uses {card_stroke}pt instead."
        )

    return card_stroke


def _require_pass1_saved_closed(jxa: dict[str, Any]) -> None:
    """Guard offline writes against a pass-1 deck that may still be open in Keynote."""
    if jxa.get("saved") is True and jxa.get("closed") is True:
        return
    raise RuntimeError(
        "pass 1 (remap) did not save and close cleanly "
        f"(saved={jxa.get('saved')}, closed={jxa.get('closed')}, "
        f"saveError={jxa.get('saveError')}, closeError={jxa.get('closeError')}): "
        "the deck may still be open in Keynote; resolve the failure and re-run."
    )


def remap_keynote(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    keep_side_panels: bool = False,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    framing_overrides: dict[int, int] | None = None,
    side_content_slides: set[int] | None = None,
    source_previews: Path | str | None = None,
    export_dir: Path | str | None = None,
    offline_read: str | None = None,
    plan_out: dict[str, Any] | None = None,
    log: Callable[[str], None] | None = None,
    offline_hides: str | None = None,
) -> dict[str, Any]:
    """Copy wall `source` to `dest` and remap in place from the CG template crop.
    `offline_hides` overrides `OBED_OFFLINE_HIDES` (None keeps the env)."""
    def say(message: str) -> None:
        if log:
            log(message)

    source = Path(source).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    template_path = Path(template).expanduser().resolve()
    if not template_path.exists():
        raise FileNotFoundError(template_path)

    if wall_payload is not None:
        wall = wall_payload
    else:
        wall = acquire_wall_payload(
            source,
            slide_range=slide_range,
            mode=offline_read_mode(offline_read),
            say=say,
        )
    if wall_payload is None:
        if slide_range:
            label = format_slide_range(slide_range)
            say(
                f"Inspected {source.name} slide {label}: "
                f"canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}."
            )
        else:
            say(
                f"Inspected {source.name}: canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}, "
                f"{wall.get('slideCount')} slides."
            )
        note = navigator_numbering(wall)
        if note:
            say(note)
    if template_payload is not None:
        template_data = template_payload
    else:
        say(f"Inspecting CG template {template_path.name}…")
        template_data = inspect_keynote(template_path)

    card_stroke = prepare_wall_payload(
        source, wall, template_path, template_data, say, offline_read=offline_read
    )

    recipe = recipe_for(wall, template_data)
    previews: dict[int, Any] = {}
    preview_note = ""
    preview_source_dir: Path | None = None
    preview_wanted = preview_wanted_slides(
        wall,
        slide_range,
        keep_side_panels=keep_side_panels,
        side_content_slides=side_content_slides,
    )
    if preview_wanted is None or preview_wanted:
        previews, preview_note, preview_source_dir = resolve_source_previews(
            source, wall, folder=source_previews, wanted=preview_wanted
        )
    plan = plan_payload(
        wall,
        recipe,
        slide_range=slide_range,
        keep_side_panels=keep_side_panels,
        template=template_data,
        previews=previews or None,
        framing_overrides=framing_overrides,
        side_content_slides=side_content_slides,
        card_stroke=card_stroke,
    )
    transforms = plan.transforms
    placements = plan.placements
    hidden = plan.skipped_slides
    fitted = plan.fitted_slides
    offframe = plan.offframe
    framing_rows = plan.framing
    child_resize = plan.child_resize
    badge_raises = plan.badge_raises
    card_grid = plan.card_grid
    roster = plan.roster
    hidden_addresses = {
        (t.slide_number, t.kind, t.kind_index) for t in transforms if t.role == "hide"
    }
    aspectless_count = 0
    aspectless_slides: set[int] = set()
    for slide in wall.get("slides") or []:
        if slide.get("skipped"):
            continue
        number = int(slide.get("number") or (int(slide.get("index") or 0) + 1))
        for item in slide.get("items") or []:
            address = (number, str(item.get("kind") or ""), item.get("kindIndex"))
            if (
                item.get("kind") in {"image", "movie", "group"}
                and address not in hidden_addresses
                and "aspect" not in item
            ):
                aspectless_count += 1
                aspectless_slides.add(number)
    if aspectless_count:
        say(f"WARN: aspect-snap unavailable for {aspectless_count} item(s) on {len(aspectless_slides)} slide(s) "
            "(no per-item aspect; legacy Keynote-read items) — those rects keep the raw affine.")
    confirmed = [r for r in framing_rows if r.get("confirmed")]
    if confirmed:
        overruled = [r for r in confirmed if r.get("fitted")]
        say(
            f"Used your confirmed framing on {len(confirmed)} slide(s)."
            + (
                f" {len(overruled)} of them still had to fall back to fitting content: "
                + ", ".join(str(r["slide"]) for r in overruled[:8])
                + " — that template slide cannot frame those pages."
                if overruled
                else ""
            )
        )
    reused = [r for r in framing_rows if r.get("reusedSibling") and r.get("uncoveredTopPx") is None]
    if reused:
        say(
            f"Kept {len(reused)} slide(s) 1:1 with the page before them by reusing "
            "that framing's transform: "
            + ", ".join(str(r["slide"]) for r in reused[:10])
            + ("…" if len(reused) > 10 else "")
            + " (their own art paired to a sliver, but they share the pin and are "
            "adjacent, so the magic-move map stays put)."
        )
    banded = [r for r in framing_rows if r.get("uncoveredTopPx") is not None]
    if banded:
        say(
            "Carried the previous slide's framing onto "
            + ", ".join(
                f"slide {r['slide']} (~{r['uncoveredTopPx']:.0f}px uncovered at the top)"
                for r in banded
            )
            + " to stay source-faithful — this backdrop has no content of its own to frame."
        )
    overridden = [r for r in framing_rows if r.get("pinOverridden")]
    if overridden:
        say(
            f"Your pinned framing could not frame {len(overridden)} slide(s) "
            + ", ".join(str(r["slide"]) for r in overridden[:10])
            + ("…" if len(overridden) > 10 else "")
            + " — it would have shrunk them to a sliver, so their own best framing "
            "was used instead."
        )
    coverage_rows = [r for r in framing_rows if r.get("excludedOffCanvas")]
    if coverage_rows:
        say("Framing coverage on " + ", ".join(
            f"slide {r['slide']} ({r['excludedOffCanvas']} of {r['excluded']} overlay object(s) off-frame)"
            for r in coverage_rows[:8]) + ("…" if len(coverage_rows) > 8 else "")
            + " is scored on the framed artwork only; those overlays are placed, not dropped.")
    if fitted:
        say(
            f"No template framing matched {len(fitted)} slide(s) "
            + ", ".join(str(n) for n in fitted[:10])
            + ("…" if len(fitted) > 10 else "")
            + "; scaled their content to fit instead. Add a template slide for that layout."
        )
    if offframe:
        by_slide: dict[int, int] = {}
        for row in offframe:
            by_slide[int(row["slide"])] = by_slide.get(int(row["slide"]), 0) + 1
        detail = ", ".join(f"slide {n}: {c}" for n, c in sorted(by_slide.items())[:8])
        say(
            f"{len(offframe)} object(s) visible on the wall land outside the CG frame "
            f"({detail}). They are still in the deck — drag them back or adjust the template."
        )
    card_rows = [r for r in child_resize if r.get("captionPt")]
    if recipe.get("cardSamples"):
        resolved = _resolve_template_card_sample(recipe.get("cardSamples"))
        card_slides = sorted({int(r["slide"]) for r in card_rows})
        if resolved is not None:
            gx, gy = resolved.get("gutterX"), resolved.get("gutterY")
            pitch_source = "template" if gx is not None and gy is not None else "wall fallback"
            gutter_txt = f"{gx:.2f}/{gy:.2f}" if gx is not None and gy is not None else "n/a"
            say(
                f"Template card sample: {len(recipe['cardSamples'])} copies at "
                f"{resolved['w']:.1f}×{resolved['h']:.1f}, gutters {gutter_txt} ({pitch_source}); "
                f"{len(card_rows)} wall card(s) matched"
                + (f" on slides {card_slides}" if card_slides else " (none)")
                + "."
            )
        else:
            say(
                f"Template card sample: {len(recipe['cardSamples'])} copies found; "
                f"{len(card_rows)} wall card(s) matched"
                + (f" on slides {card_slides}" if card_slides else " (none)")
                + "."
            )
    if card_grid:
        for row in card_grid:
            overlaps = row.get("overlaps") or []
            clear_x, clear_y = row.get("clearX"), row.get("clearY")
            below = (
                " (below 7pt)"
                if (clear_x is not None and clear_x < GRID_MIN_CLEAR)
                or (clear_y is not None and clear_y < GRID_MIN_CLEAR)
                else ""
            )
            say(
                f"Slide {row['slide']}: {row['n']} card(s) reflowed to {row['cols']}×{row['rows']}, "
                f"pitch {row['pitchX']}/{row['pitchY']} (gutter {row['gutterX']}/{row['gutterY']}, "
                f"clear {clear_x}/{clear_y} at {card_stroke}pt stroke{below}), "
                f"origin ({row['x0']}, {row['y0']}), {row['offCanvas']} off-canvas"
                + (f", {len(overlaps)} overlapping a stat group" if overlaps else "")
                + "."
            )
    if hidden:
        say(
            f"Left {len(hidden)} skipped slide(s) alone: "
            + ", ".join(str(n) for n in hidden[:10])
            + ("…" if len(hidden) > 10 else "")
            + ". Un-skip in Keynote and re-run to include them."
        )
    reuses: list[dict[str, Any]] = []
    stat_adjustments = adjust_child_resize_indexes(child_resize, transforms)
    if stat_adjustments:
        say(
            f"Adjusted {len(stat_adjustments)} stat-group index(es) for deleted group hides: "
            + ", ".join(f"slide {a['slide']} {a['from']}→{a['to']}" for a in stat_adjustments[:8])
            + "."
        )
    counts = summarize_plan(transforms)
    say(
        f"Recipe {recipe.get('source')}: map {recipe.get('mapSrc')} → {recipe.get('mapDst')}; "
        f"{counts.get('map', 0)} map, {counts.get('pin', 0)} pin, "
        f"{counts.get('list', 0)} list, {counts.get('hide', 0)} hidden"
        f"{'' if (keep_side_panels or side_content_slides) else ' (side-panel content dropped; keep it with --keep-side-panels N or the framing review)'}."
    )
    if roster.get("drop"):
        kept = format_slide_range(roster.get("keep") or set()).replace("–", "-")
        dropped = format_slide_range(roster["drop"]).replace("–", "-")
        say(
            f"Roster kept on slide(s) {kept}, dropped on {dropped} "
            "(a wall leftover behind newer content)."
        )
    if recipe.get("listFontSize") and (keep_side_panels or placements):
        if placements:
            crowded = [row for row in placements if row.get("overlap")]
            detail = f"{len(placements)} moved into empty space"
            if crowded:
                worst = max(row["overlap"] for row in crowded)
                detail += (
                    f", {len(crowded)} had to overlap artwork (worst {worst:.0%}) "
                    "— break those up by hand"
                )
            say(f"Church names → {recipe.get('listFontSize')}pt, {detail}. Measured from {preview_note}.")
        else:
            reason = "no wall previews found" if not previews else "nothing free to move"
            say(
                f"Church names → {recipe.get('listFontSize')}pt, packed from the right "
                f"(gutter first; extras may overlap the map) — {reason}."
            )
    styles = recipe.get("characterStyles") or []
    if styles:
        bits = []
        for s in styles:
            bit = f"{s.get('font') or 'sample'} {s.get('size')}pt"
            rgb = s.get("color")
            if rgb and len(rgb) >= 3:
                bit += f" rgb({int(rgb[0]*255)},{int(rgb[1]*255)},{int(rgb[2]*255)})"
            bits.append(bit)
        say(
            "Unpaired text picks a CG character style, its framing slide's own "
            "matching-colour sample first, "
            "else the closest of: " + "; ".join(bits) + "."
        )
    origin_pins = [
        t for t in transforms if t.role == "pin" and abs(t.x) < 2 and abs(t.y) < 2
    ]
    if len(origin_pins) > 10:
        raise RuntimeError(
            f"Planner put {len(origin_pins)} pins at (0,0); refusing to apply. "
            f"Wall canvas {wall.get('slideWidth')}×{wall.get('slideHeight')}. "
            f"mapSrc={recipe.get('mapSrc')} mapDst={recipe.get('mapDst')}. "
            "Use the original 7680 wall .key, not a previous CG output."
        )
    say(f"Copying {source.name} → {dest.name}…")
    source_bytes = _path_bytes(source)
    template_bytes = _path_bytes(template_path)
    t_prep = time.monotonic()
    py_stages: dict[str, float] = {}
    py_notes: dict[str, str] = {}
    t0 = time.monotonic()
    copy_keynote(source, dest)
    py_stages["copyDeck"] = time.monotonic() - t0
    py_notes["copyDeck"] = _fmt_bytes(source_bytes)
    layout_dir = Path(tempfile.mkdtemp(prefix="obed-layouts-"))
    layout_src = layout_dir / template_path.name
    try:
        say(f"Copying 16:9 slide layouts from {template_path.name} onto the wall copy…")
        t0 = time.monotonic()
        copy_keynote(template_path, layout_src)
        py_stages["copyTemplate"] = time.monotonic() - t0
        py_notes["copyTemplate"] = _fmt_bytes(template_bytes)
        say("Setting 16:9 canvas, applying CG layouts, then map/pin positions…")
        transform_dicts = [t.as_dict() for t in transforms]
        child_written = sum(1 for t in transform_dicts if t.get("children"))
        if child_written:
            say(
                f"Group child geometry: {child_written} group(s) hold an autosize text box "
                "and are written child-by-child (a group-level resize would freeze the text "
                "wrapped); all other groups keep the absolute group write."
            )
        wanted = slides_for_plan(slide_range)
        env_suppressed = suppress_geometry_slides()
        offline_mode = offline_write_mode(say=say)
        offline_mode = offline_write.probe_iwa_extra(offline_mode, say)
        offline_slides: set[int] = set()
        if offline_mode != "off":
            offline_slides = offline_write._offline_write_slides(transform_dicts, wanted)
            say(
                f"OBED_OFFLINE_WRITE={offline_mode}: {len(offline_slides)} slide(s) go "
                "offline (surgical IWA patch)."
            )
        suppressed = env_suppressed | offline_slides
        hides_mode = offline_hides_mode(offline_hides, offline_mode=offline_mode, say=say)
        hide_slides: set[int] = set()
        if hides_mode != "off":
            hide_slides = offline_write.offline_hide_slides(transform_dicts, wall, wanted)
            say(
                f"OBED_OFFLINE_HIDES={hides_mode}: {len(hide_slides)} slide(s) defer their "
                "hides to the offline delete after the pass-1 save."
            )
        plan: dict[str, Any] = {
            "dest": str(dest),
            "template": str(layout_src),
            "width": int(recipe.get("destWidth") or CG_WIDTH),
            "height": int(recipe.get("destHeight") or CG_HEIGHT),
            "transforms": transform_dicts,
            "reuses": reuses,
            "suppressGeometry": sorted(suppressed),
        }
        if env_suppressed:
            say(
                "OBED_SUPPRESS_GEOMETRY on: attrs-only (no geometry) for "
                f"slide(s) {sorted(env_suppressed)}."
            )
        if as_geometry_enabled():
            plan["asGeometry"] = True
            plan["asGeom"] = _build_as_geometry(transform_dicts, suppress=suppressed)
            say(
                "OBED_AS_GEOMETRY on: geometry via batched AppleScript "
                f"for {len(plan['asGeom'])} slide(s)."
            )
        if wanted:
            plan["slides"] = wanted
            plan["range"] = [wanted[0], wanted[-1]]
        if hides_mode != "off":
            plan["offlineHideSlides"] = sorted(hide_slides)
        if write_timing_enabled():
            plan["timing"] = {"slowMs": 120}
            say("OBED_WRITE_TIMING on: recording per-slide/per-phase write timing.")
        if plan_out is not None:
            plan_out["transforms"] = transform_dicts
            plan_out["reuses"] = reuses
            plan_out["suppressGeometry"] = plan.get("suppressGeometry")
            plan_out["asGeom"] = plan.get("asGeom")
            plan_out["groupRemoves"] = []
            plan_out["badgeRaises"] = list(badge_raises)
            # "statJobs" (not "childResize") — the run record's pass-2 RESULT dict already
            # uses "childResize" for `_run_stat_finalize`'s return; this is the JOB LIST.
            plan_out["statJobs"] = list(child_resize)
            plan_out["statSlides"] = sorted({int(cr.get("slide", -1)) for cr in child_resize})
            group_collapse_refused = [
                t["groupCollapseRefused"]
                for t in transform_dicts
                if t.get("groupCollapseRefused")
            ]
            if group_collapse_refused:
                plan_out["groupCollapseRefused"] = group_collapse_refused
        _say_pass1_census(
            _pass1_census(
                transform_dicts, suppressed, {int(k) for k in plan.get("asGeom") or {}}
            ),
            say,
        )
        py_stages = {
            "prep": time.monotonic() - t_prep - py_stages["copyDeck"] - py_stages["copyTemplate"],
            **py_stages,
        }
        t0 = time.monotonic()
        jxa = _run_jxa(plan)
        py_stages["runJxa"] = time.monotonic() - t0
    finally:
        shutil.rmtree(layout_dir, ignore_errors=True)
    _say_pass1_stages(py_stages, jxa, say, py_notes)
    if jxa.get("timing"):
        _say_write_timing(jxa["timing"], say)
    applied = int(jxa.get("applied") or 0)
    missed = int(jxa.get("missed") or 0)
    hides_deferred = int(jxa.get("hidesDeferred") or 0)
    if jxa.get("collections"):
        say(f"Keynote collections: {jxa.get('collections')}")
    if applied + hides_deferred == 0:
        detail = ""
        if jxa.get("collections"):
            detail += f" collections={jxa.get('collections')}"
        if jxa.get("missReasons"):
            detail += f" misses={jxa.get('missReasons')}"
        raise RuntimeError(
            "Keynote remap moved 0 objects; the copy was left at the wall canvas size."
            f" Planned {len(transforms)} transform(s), missed {missed}.{detail}"
        )
    if hides_mode == "off":
        say(f"Applied {applied}, missed {missed}.")
    for reason in jxa.get("missReasons") or []:
        say(f"WARNING remap: {reason}")
    layouts = jxa.get("layouts") or {}
    if layouts.get("imported"):
        say(f"Imported 16:9 layouts: {', '.join(str(n) for n in layouts['imported'])}.")
    applied_layouts = layouts.get("applied") or []
    if applied_layouts:
        sample = applied_layouts[0]
        say(
            f"Applied {sample.get('to') or 'CG layout'} to "
            f"{len(applied_layouts)} slide(s)."
        )
    _require_pass1_saved_closed(jxa)
    expected_deferred = sum(
        1 for t in transform_dicts if t.get("role") == "hide" and int(t.get("slide", -1)) in hide_slides
    )
    if hides_deferred != expected_deferred:
        raise offline_write.OfflineHidesAborted(
            "pass 1 deferred a different number of hides than planned",
            f"deferred {hides_deferred}, expected {expected_deferred} on slide(s) "
            f"{sorted(hide_slides)}; refusing to delete hides by position",
        )
    hides_info = offline_write.run_offline_hides(
        dest, hides_mode, hide_slides, transform_dicts, wall, say,
    )
    if hides_info is not None:
        applied += hides_info["deleted"]
    if hides_mode != "off":
        say(f"Applied {applied}, missed {missed}.")
    _debug_snapshot_pass1(dest, say)
    text_reposition = offline_text_reposition_enabled(offline_mode=offline_mode, say=say)
    mask_crop = offline_maskcrop_enabled(offline_mode=offline_mode, say=say)
    offline_write_info = offline_write.run_offline_write(
        dest, offline_mode, offline_slides, transform_dicts, wall, child_resize, say,
        text_reposition=text_reposition, mask_crop=mask_crop,
    )
    zorder_mode = zorder_write_mode(offline_mode=offline_mode, say=say)
    zorder_refused = set((offline_write_info or {}).get("refused") or [])
    zorder_targets, zorder_eligibility = offline_write.zorder_eligible_slides(
        dest, zorder_mode, offline_slides, zorder_refused, child_resize, badge_raises,
        transform_dicts, say,
    )
    if zorder_mode != "off":
        gui_slides = zorder_eligibility["zorderGui"]
        say(
            f"OBED_ZORDER_WRITE={zorder_mode}: {len(zorder_targets)} slide(s) go offline "
            f"(surgical z-order patch); {len(gui_slides)} slide(s) left un-raised"
            f"{': ' + str(gui_slides) if gui_slides else ''}."
        )
        if gui_slides:
            gui_target_counts: dict[int, int] = {}
            for job in child_resize:
                if job.get("childSig") and int(job["slide"]) in gui_slides:
                    gui_target_counts[int(job["slide"])] = gui_target_counts.get(int(job["slide"]), 0) + 1
            for row in badge_raises:
                if int(row["slide"]) in gui_slides:
                    gui_target_counts[int(row["slide"])] = gui_target_counts.get(int(row["slide"]), 0) + 1
            detail = ", ".join(
                f"slide {s} ({gui_target_counts.get(s, 0)} target(s))" for s in sorted(gui_slides)
            )
            say(
                f"WARNING zorder: {len(gui_slides)} slide(s) the offline resolver left "
                f"un-raised ({detail}) — left in source stacking — the resolver could not "
                "prove a unique target set; see the unresolved tokens."
            )
    else:
        off_target_slides = sorted(
            {int(job["slide"]) for job in child_resize if job.get("childSig")}
            | {int(row["slide"]) for row in badge_raises}
        )
        if off_target_slides:
            say(
                f"OBED_ZORDER_WRITE=off: z-order raises skipped for "
                f"{len(off_target_slides)} slide(s) (left in source stacking): "
                f"{off_target_slides}."
            )
    # Card border stroke widths shrink with the canvas; restore them before the stat-finalize
    # pass. Always runs — not gated by OBED_OFFLINE_WRITE.
    card_stroke_result = restore_card_stroke_widths(dest, source, wall, say)
    map_slide = next((int(t.slide_number) for t in transforms if t.role == "map"), None)
    if jxa.get("mapReadback") and map_slide not in offline_slides:
        say(f"Map object after apply: {jxa.get('mapReadback')}")
    actual_w = jxa.get("width")
    actual_h = jxa.get("height")
    if actual_w and actual_h:
        say(f"Canvas after remap: {actual_w}×{actual_h}.")
    if jxa.get("skippedSlides"):
        say(f"Skipped {jxa.get('skippedSlides')} other slide(s) so the preview is this slide only.")
    if card_rows:
        swatch = max(r["captionPt"] for r in card_rows)
        downs = sorted(
            (r for r in card_rows if r["captionPt"] < swatch),
            key=lambda r: (-r["captionPt"], r.get("childSig") or ""),
        )
        detail = ", ".join(f"{r.get('childSig')} {int(r['captionPt'])}" for r in downs[:10])
        say(
            f"Card captions: {len(card_rows)} at the template swatch {int(swatch)}pt"
            + (
                f"; {len(downs)} stepped down to fit ({detail}"
                + ("…" if len(downs) > 10 else "")
                + ")"
                if downs
                else ""
            )
            + "."
        )
        refusals = [r for r in card_rows if r.get("captionRefusal")]
        if refusals:
            say(
                f"WARNING: {len(refusals)} card caption(s) could not be measured "
                f"({refusals[0].get('captionRefusal')}) — kept at the template swatch size."
            )
    size_refusals = [t for t in transform_dicts if t.get("sizeRefused")]
    if size_refusals:
        detail = ", ".join(f"s={t['slide']}/idx={t['kindIndex'] + 1}" for t in size_refusals)
        say(
            f"WARNING remap: {len(size_refusals)} group(s) with an autosize text box kept "
            f"their source size (reason={size_refusals[0]['sizeRefused']}): {detail}."
        )
    group_collapse_tokens = [
        t["groupCollapseRefused"] for t in transform_dicts if t.get("groupCollapseRefused")
    ]
    if group_collapse_tokens:
        say("WARNING remap: " + " ".join(group_collapse_tokens))
    # JXA cannot size grouped stat numbers or restack them; AppleScript sets template point size,
    # the offline z-order patch (below) restacks eligible slides.
    export_path = Path(export_dir).expanduser().resolve() if export_dir else None
    pass2_export_path = None if zorder_mode != "off" else export_path
    child_resize_result: dict[str, Any] | None = None
    if child_resize:
        stat_sizes = read_template_stat_sizes(template_path) if child_resize else {}
        say(
            f"Finalizing {len(child_resize)} stat group(s): template sizes "
            f"({', '.join(f'{k}→{int(v)}pt' for k, v in sorted(stat_sizes.items())) or 'none found'})"
            + "."
            + (" Exporting previews in the same session." if pass2_export_path else "")
            + (" Preview export moved after the z-order patch (extra Keynote open)."
               if export_path and pass2_export_path is None else "")
        )
        child_resize_result = _run_stat_finalize(
            dest,
            child_resize,
            stat_sizes,
            export_dir=pass2_export_path,
        )
        done = child_resize_result.get("done") or 0
        skipped = child_resize_result.get("skipped") or 0
        sized = child_resize_result.get("sized") or 0
        dedup_shortfall = child_resize_result.get("dedupShortfall") or 0
        sig_fallback = child_resize_result.get("sigFallback") or 0
        unresolved = child_resize_result.get("unresolved") or 0
        if child_resize_result.get("ok"):
            say(
                f"Stat-finalize pass: {done} group(s) done, {sized} number(s) sized to "
                "the template"
                + (f", {skipped} skipped" if skipped else "")
                + (f", {sig_fallback} sig-fallback(s)" if sig_fallback else "")
                + "."
            )
            if dedup_shortfall:
                say(
                    f"WARNING stat-finalize: {dedup_shortfall} donor-copy group(s) could "
                    "NOT be safely deduped (live count did not equal expectedKeep + "
                    "deleteCount, or the signature did not match) — kept, not guessed; "
                    "doubling may persist."
                )
            if unresolved:
                say(
                    f"WARNING stat-finalize: {unresolved} stat group(s) could NOT be "
                    "unambiguously resolved — kept, not guessed — those stat groups keep "
                    "their wall font size and stay buried."
                )
            _say_stat_finalize_detail(child_resize_result, say)
        else:
            say(
                "Stat-finalize pass did not complete; stat groups stay at the JXA "
                "placement/size. See the .stat-finalize.applescript dump."
            )
    if zorder_targets and child_resize_result is not None and not (
        child_resize_result.get("ok") and child_resize_result.get("closed")
    ):
        raise RuntimeError(
            f"zorder patch skipped on target slide(s) {sorted(zorder_targets)}: "
            "pass 2 (stat-finalize) did not complete, so the deck may still be open in "
            "Keynote; resolve the failure and re-run with OBED_ZORDER_WRITE=on. "
            "OBED_ZORDER_WRITE=off knowingly skips every z-order raise."
        )
    _require_pass1_saved_closed(jxa)
    say("Z-order patch…")
    zorder_write_info = offline_write.run_offline_zorder(dest, zorder_mode, zorder_targets, say)
    say("Builds/transitions: reading source and output decks…")
    # Builds/transitions follow the source. Unconditional and runs last — verify-all,
    # patch-none when the slide set is empty; must keep running LAST, after the z-order write.
    build_result = restore_source_builds(dest, source, set(), say)
    result: dict[str, Any] = {
        "source": str(source),
        "dest": str(dest),
        "template": str(template_path),
        "recipe": recipe,
        "counts": counts,
        "applied": applied,
        "missed": missed,
        "width": jxa.get("width"),
        "height": jxa.get("height"),
        "collections": jxa.get("collections"),
        "slideRange": slides_for_plan(slide_range),
        "skippedSlides": jxa.get("skippedSlides"),
        "layouts": jxa.get("layouts"),
        "templateScore": score_against_gold(transforms, template_data, wall=wall),
        "placements": placements,
        "placementSource": preview_note,
        "previews": {
            "source": str(preview_source_dir) if preview_source_dir else None,
            "placements": len(placements),
        },
        "skippedSlidesLeftAlone": hidden,
        "fittedSlides": fitted,
        "offFrame": offframe,
        "framingReport": framing_rows,
        "childResize": child_resize_result,
        "exported": bool(child_resize_result and child_resize_result.get("exported")),
        "previewFiles": list(
            (child_resize_result or {}).get("previewFiles") or []
        ),
    }
    if offline_write_info is not None:
        result["offlineWrite"] = offline_write_info
    if hides_info is not None:
        result["offlineHides"] = hides_info
    if zorder_mode != "off":
        merged_zorder = dict(zorder_write_info) if zorder_write_info is not None else {
            "mode": zorder_mode, "slides": [], "zorderSlides": 0, "zorderStatRaised": 0,
            "zorderBadgeRaised": 0, "zorderNoop": 0, "zorderRefused": 0, "zorderLost": 0,
        }
        merged_zorder["zorderRefused"] = (
            merged_zorder.get("zorderRefused", 0) + zorder_eligibility["zorderRefused"]
        )
        merged_zorder["zorderUnresolved"] = zorder_eligibility["zorderUnresolved"]
        merged_zorder["zorderGui"] = zorder_eligibility["zorderGui"]
        say(
            f"Stat zorder detail: zorderSlides={merged_zorder.get('zorderSlides', 0)} "
            f"zorderStatRaised={merged_zorder.get('zorderStatRaised', 0)} "
            f"zorderBadgeRaised={merged_zorder.get('zorderBadgeRaised', 0)} "
            f"zorderNoop={merged_zorder.get('zorderNoop', 0)} "
            f"zorderRefused={merged_zorder['zorderRefused']} "
            f"zorderUnresolved={zorder_eligibility['zorderUnresolved']} "
            f"zorderLost={merged_zorder.get('zorderLost', 0)} "
            f"zorderGui={len(zorder_eligibility['zorderGui'])}."
        )
        result["zorderWrite"] = merged_zorder
        failures = merged_zorder.get("failures") or []
        if failures:
            raise RuntimeError(
                f"zorder patch failed on target slide(s) {sorted(n for n, _ in failures)}: "
                "deck saved; resolve the failure and re-run with OBED_ZORDER_WRITE=on. "
                "OBED_ZORDER_WRITE=off knowingly skips every z-order raise."
            )
    result["cardStroke"] = card_stroke_result
    result["builds"] = build_result
    return result


def _readback_payload(
    dest: Path,
    export_dir: Path | str | None,
    slide_range: tuple[int, int] | frozenset[int] | None,
    log: Callable[[str], None] | None,
    *,
    offline_read: str | None = None,
    force_legacy: bool = False,
) -> dict[str, Any]:
    """Validated resize readback: two-tier offline+bulk, fail-safe to legacy JXA, cache off.

    `force_legacy` is set when the just-applied offline-write ran in ``verify`` mode:
    `verify_live_frames` exists as an INDEPENDENT oracle beside `verify_offline_frames`, and
    a two-tier readback would self-confirm the `shape`/`line` frames the surgical float patch
    just wrote (their geometry never rides the bulk tier, see `offline_inspect.BULK_KINDS`).
    """
    if force_legacy:
        if log:
            log("Offline-write verify is on; reading the deck back with Keynote inspect so "
                "the live-frame check stays an independent oracle.")
        return inspect_keynote(dest, export_dir=export_dir, slide_range=slide_range, use_cache=False)
    if offline_read_mode(offline_read) == "off":
        return inspect_keynote(dest, export_dir=export_dir, slide_range=slide_range, use_cache=False)
    if dest.is_dir():
        if log:
            log(f"{dest.name} was saved as a package directory; offline read unavailable -- "
                "using Keynote inspect.")
        return inspect_keynote(dest, export_dir=export_dir, slide_range=slide_range, use_cache=False)
    try:
        return inspect_keynote_checker(
            dest, export_dir=export_dir, slide_range=slide_range, use_cache=False, log=log
        )
    except LegacyInspectFailed:
        raise  # legacy already ran and failed inside the checker; today's behaviour is to raise
    except Exception as exc:  # noqa: BLE001 — fail-safe, matches acquire_wall_payload
        if log:
            log(f"Two-tier readback failed ({type(exc).__name__}: {exc}); using Keynote inspect.")
    return inspect_keynote(dest, export_dir=export_dir, slide_range=slide_range, use_cache=False)


def remap_and_inspect(
    source: Path | str,
    dest: Path | str,
    *,
    template: Path | str,
    slide_range: tuple[int, int] | frozenset[int] | None = None,
    keep_side_panels: bool = False,
    export_dir: Path | str | None = None,
    source_previews: Path | str | None = None,
    framing_overrides: dict[int, int] | None = None,
    side_content_slides: set[int] | None = None,
    wall_payload: dict[str, Any] | None = None,
    template_payload: dict[str, Any] | None = None,
    validate: bool = True,
    plan_out: dict[str, Any] | None = None,
    offline_read: str | None = None,
    log: Callable[[str], None] | None = None,
    offline_hides: str | None = None,
) -> dict[str, Any]:
    info = remap_keynote(
        source,
        dest,
        template=template,
        slide_range=slide_range,
        keep_side_panels=keep_side_panels,
        source_previews=source_previews,
        framing_overrides=framing_overrides,
        side_content_slides=side_content_slides,
        wall_payload=wall_payload,
        template_payload=template_payload,
        plan_out=plan_out,
        export_dir=export_dir if not validate else None,
        offline_read=offline_read,
        log=log,
        offline_hides=offline_hides,
    )
    if not validate:
        if export_dir and not info.get("exported"):
            if log:
                log("Exporting previews (validation off, so the deck is not read back)…")
            error = export_slide_images(Path(dest), Path(export_dir))
            if error and log:
                log(error)
        info["inspect"] = {"exported": bool(export_dir), "exportError": ""}
        if export_dir:
            info["previewFiles"] = [p.name for p in preview_pngs(Path(export_dir))]
        return info
    if log:
        log("Inspecting remapped deck…")
    ow = info.get("offlineWrite")
    payload = _readback_payload(
        Path(dest),
        export_dir,
        slide_range,
        log,
        offline_read=offline_read,
        force_legacy=bool(ow and ow.get("mode") == "verify"),
    )
    info["inspect"] = {
        "slideWidth": payload.get("slideWidth"),
        "slideHeight": payload.get("slideHeight"),
        "slideCount": payload.get("slideCount"),
        "exported": payload.get("exported"),
        "exportError": payload.get("exportError") or "",
    }
    info["payload"] = payload
    if ow and ow.get("mode") == "verify":
        report = offline_write.live_verify(ow, info.get("zorderWrite"), payload, log=log)
        ow.update(report.ow_updates())
    if export_dir:
        info["previewFiles"] = [p.name for p in preview_pngs(Path(export_dir))]
    return info
