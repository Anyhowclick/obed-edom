"""Offline mode-aware text-box geometry, shaped with AppKit ``NSAttributedString``.

:mod:`obed_edom.iwa_geometry` composes every drawable's laid-out ``(x, y, w, h)``
offline EXCEPT autosize text, where it ships a best-effort ``naturalSize`` that is
stale on ~20% of boxes (height always, width on auto-width boxes) — see its
``_autosize_rect`` and the ``autosize-soft`` flag. This module closes that gap by
LAYING THE TEXT OUT offline: it reads the box's sizing mode from
``TSD.GeometryArchive.flags`` and, for the modes whose extent Keynote computes by
shaping, reproduces the shape with AppKit's text engine (the installed ``pyobjc``
``AppKit`` bridge — no CoreText bridge, no new dependency).

The sizing mode (empirically confirmed on the GW checker deck's 99 boxes and the
Full deck's 788, cross-checked against each deck's cached JXA v3 payload):

    ``geometry.flags`` bit 0 (``0x1``) set  <=> WIDTH is authored/fixed
    ``geometry.flags`` bit 1 (``0x2``) set  <=> HEIGHT is authored/fixed

so the three observed values are:

    * ``flags == 3`` — fixed width + fixed height. The frame ``(fx, fy, fw, fh)`` is
      EXACT (GW 31/31, Full 5/5); no shaping. Handled by the frame rule.
    * ``flags == 1`` — fixed width + AUTO height (the dominant overflow case). Width
      is ``bezierPathSource.naturalSize.width`` EXACT (GW 36/36, Full 123/123); the
      left/top ``(fx, fy)`` are exact; only the HEIGHT is missing and is shaped by
      wrapping the text at ``width - 2*inset``.
    * ``flags == 0`` — auto width + auto height, centre-anchored. Both extents are
      shaped: width from the unconstrained longest line, height from that width.
      ``geometry.position`` is the CENTRE anchor, so ``x = anchor_x - w/2`` and
      ``y = anchor_y - h/2``.

The current ``iwa_geometry._autosize_rect`` conflates flags 0 and 1 (its ``h == 0``
test) and uses the flags-0 vertical anchor (``y - h/2``) for BOTH; for a flags-1 box
the true convention is ``y = top`` (verified 36/36 on GW). This module uses the
per-mode anchor.

CALIBRATION (frozen constants below) was fit against each deck's cached JXA/bulk
payload as the oracle (Keynote-free — the laid-out ``h`` on a flags-1 box IS the
shaped height). See :data:`TEXT_INSET`, :data:`HEIGHT_MODEL`.

GUARD / GATE ENVELOPE: the shaped extent is only trustworthy under a set of
conditions; when any of them fails the box is marked UNVOUCHED with a ``reason`` and
a caller must fall back to a Keynote read for it (see :func:`_gate_reason` and
:class:`TextGeometry`). ``font-missing`` (substitute-font metrics) is the top risk;
the others gate uncalibrated fonts, under-determined multi-line families,
auto-width boxes, exotic line-spacing modes and unsatisfiable bold/italic traits.

STEP-3 WIRING CONTRACT (this module is INERT today — nothing calls
:func:`compose_text_geometry`; the checker's text geometry still comes from the
Keynote bulk pass — so none of this can regress v1 until a SEPARATE wiring task).
When step-3 does wire the shaper in, two invariants keep it fail-safe:

    * A VOUCHED shaped box (``reason is None``) must be emitted with a NEW EXACT
      ``geom_source`` that is OUTSIDE ``offline_inspect.SOFT_GEOM_SOURCES``
      (``{"group-union", "autosize"}``, ``offline_inspect.py:97``). If it reused a
      soft source, dropping the bulk read would make every text box "bulk-missing"
      and fall back (``offline_inspect.py:717-724``) — zero speedup.
    * An UNVOUCHED box (``reason is not None``) must map to a NON-vouched
      ``needs_keynote`` reason — NEVER ``"autosize-soft"``, the only value in
      ``offline_inspect.VOUCHED_NEEDS_KEYNOTE`` (``offline_inspect.py:78``) — so an
      unvouched box forces the fallback read instead of being silently trusted.

That contract is the safety linchpin; step-3 builds it, this task only records it.

Public entry points:
    * :func:`shape_style` — the shaping style for a text box (font + paragraph metrics).
    * :func:`shaped_height` / :func:`shaped_width` — the AppKit measurements.
    * :func:`compose_text_geometry` — the mode-aware ``(x, y, w, h)`` composer + gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from obed_edom.iwa_geometry import _frame_rect, _geom_dict, _natural_size, _xywha
from obed_edom.iwa_runs import resolve_para_style, resolve_style
from obed_edom.offline_inspect import _leading_sid, _storage_of

# --------------------------------------------------------------------------
# Frozen calibration constants.
#
# The height model is SIZE-DEPENDENT:
#
#     shaped_height = layout(text, wrap_width, lineHeightMultiple=lineSpacing) * m
#                     + b * size
#
# where ``layout`` is AppKit's wrapped bounding-box height, ``wrap_width`` is
# ``box_width - 2*TEXT_INSET`` (minus any left/right indent), ``size`` is the font
# point size and ``(m, b)`` are per-family. The ``b*size`` term is the top+bottom
# vertical padding Keynote adds around the laid-out block: it is PROPORTIONAL to the
# font size, not the absolute 32pt the old model used (32 == 0.455*70, i.e. that
# absolute pad was this proportional pad frozen at the GW size-70 boxes).
#
# Fit ONCE by least-squares over the flags==1 boxes of each deck with a real cached
# laid-out height, Keynote-free (the laid-out box height on an auto-height box is
# exactly the shaped text height). ``a`` (a pure constant term) is ~0 and is dropped:
# on GW AzoSans it is under-determined (all GW AzoSans flags-1 boxes are size 70, so
# ``size`` and a constant column are collinear) and the a=0 model already achieves
# the residual floor.
#
# The residual floor is set by Keynote's per-line glyph-dependent line heights, which
# a uniform ``lineHeightMultiple`` cannot reproduce (two 2-line AzoSans boxes with
# identical AppKit layouts land at JXA 193 vs 198 — a ~5px spread no closed form
# removes), so parity is ~2.5px median / ~6px max on flags==1 AzoSans, NOT <=2px on
# every box. That is far inside the overflow flag's half-line slack (~0.5*1.15*size)
# and the bounds cut thresholds — which is what the A/B harness verifies.
#
# FIT SETS (this session; `scratchpad/ab_text_shape.py` + `fit_height.py`):
#   * AzoSans (1.013, 0.455): GW-v3, 31 MULTI-line flags==1 boxes, all size 70 but
#     spanning 2..7 lines — that line-count spread (not a size spread) is what lets
#     ``m`` (per-line advance scale) and ``b`` (per-box pad) separate. GW resid
#     med 2.5 / max 5.9 (unchanged vs the old model); applied to DSK-v4 AzoSans
#     (sizes 27/40/45, 30 boxes): med 0.83.
#
# KNOWN RESIDUAL (mixed-run-size boxes; step-3 caveat). The shaper measures a box
# with ONE style — its leading run's font/size. A box whose runs mix sizes (a verse
# number at one size, body at another) is therefore approximated. On ~68 flags==1
# vouched boxes across both decks this is benign (the mix rides inside the ~few-px
# residual), EXCEPT one DSK box (slide 19: a size-45 lead over size-50 body, split by
# a hard U+2028): shaped 126 vs oracle 177, a 51px underestimate that EXCEEDS that
# box's overflow half-line slack (~26px at size 45). No offline signal separates it
# from the 31 benign GW boxes that share the same leading<body structure (measured:
# every run-size gate that catches slide 19 also gates ~all of them), and per-run
# shaping just relocates the tail to a different box while forcing a re-fit — so the
# single-style model is kept and this box is a documented, accepted residual. Because
# the box is auto-HEIGHT it cannot overflow itself; the only exposure is a bounds
# straddle/off-canvas false-negative if such a box sits against a wall edge. STEP-3
# MUST account for this: either keep a cheap Keynote confirmation for flags==1 boxes
# with mixed run sizes, or accept the ~1.5% tail. The A/B harness reports it.
#   * ArgentCF (1.013, 0.294): GW-v3 has ONLY 5 identical single-line size-120
#     ArgentCF boxes, so its slope is UNDER-DETERMINED from this data. ``b`` is fit
#     with ``m`` fixed to the AzoSans slope (per-line advance assumed ~family-
#     invariant); GW resid 0/0, DSK single-line resid max 7. Because the slope is
#     unproven, ArgentCF is SINGLE-LINE-ONLY calibrated: a multi-line ArgentCF box
#     is GATED ``uncalibrated-multiline`` (see :data:`SINGLE_LINE_ONLY`).
# --------------------------------------------------------------------------

# exteriorTextWrap.margin — the text inset Keynote wraps inside, each side. Wrapping
# width = box width - 2*TEXT_INSET (- left/right indent). Frozen on GW; the gate +
# caller fallback cover decks it was not fit on.
TEXT_INSET = 12.0

# Per-family height model ``family -> (m, b)`` for ``shaped_height = layout*m + b*size``.
# CALIBRATED families are exactly this mapping's keys; a shaped box whose family is
# absent is GATED ``uncalibrated-font``. See the calibration note above for fit sets.
HEIGHT_MODEL: dict[str, tuple[float, float]] = {
    "AzoSans": (1.013, 0.455),
    "ArgentCF": (1.013, 0.294),
}

# Families whose ``(m, b)`` was fit from SINGLE-LINE data only (slope under-determined
# for multi-line). A multi-line box in one of these families is gated
# ``uncalibrated-multiline``; single-line boxes may vouch. See gate B2 in the module
# docstring / spec.
SINGLE_LINE_ONLY: frozenset[str] = frozenset({"ArgentCF"})


# --------------------------------------------------------------------------
# geometry.flags — the autosize-mode discriminator.
# --------------------------------------------------------------------------
def geometry_flags(geom: dict) -> int:
    """``geometry.flags`` (0 when absent). Bit 0 = width fixed, bit 1 = height fixed."""
    return int(geom.get("flags") or 0)


def width_fixed(flags: int) -> bool:
    """True when the box's width is authored (not shaped)."""
    return bool(flags & 0x1)


def height_fixed(flags: int) -> bool:
    """True when the box's height is authored (not shaped)."""
    return bool(flags & 0x2)


def _family(font_name: str | None) -> str:
    """The family key for :data:`HEIGHT_MODEL` (PostScript name up to the first ``-``)."""
    if not font_name:
        return ""
    return font_name.split("-")[0]


# --------------------------------------------------------------------------
# Shaping style for a text box.
# --------------------------------------------------------------------------
@dataclass
class ShapeStyle:
    """The style the shaper needs for one text box's leading run + paragraph."""

    font_name: str | None
    size: float
    line_multiple: float  # lineSpacing amount (relative); 1.0 when unset
    alignment: str | None
    tracking: float  # character tracking/kerning (points); 0.0 when unset
    bold: bool  # leading run OR paragraph asks for bold
    italic: bool  # leading run OR paragraph asks for italic
    first_line_indent: float  # points; 0.0 when unset
    left_indent: float  # points; 0.0 when unset
    right_indent: float  # points; 0.0 when unset
    line_spacing_mode: Any  # lineSpacing.mode; None == relative multiple (the norm)


def shape_style(obj: dict, objects: dict[str, dict], cache: dict) -> ShapeStyle | None:
    """Build the :class:`ShapeStyle` from a text box's leading char + paragraph style.

    Font name / size resolve char-first then paragraph (a char override usually
    carries only colour/weight and leaves the font on the paragraph style — same
    resolution as :func:`offline_inspect._item_text_style`). Bold/italic are the
    OR of the char and paragraph flags (``resolve_style`` returns them as non-None
    bools, ``iwa_runs.py:120-121``, so a ``pick``-style char-first fallthrough would
    never see the paragraph flag — hence an explicit OR). Indents + line-spacing mode
    come from the paragraph metrics. Returns ``None`` when the box has no text storage.
    """
    storage = _storage_of(obj, objects)
    if storage is None:
        return None
    char_sid = _leading_sid(storage.get("tableCharStyle"))
    para_sid = _leading_sid(storage.get("tableParaStyle"))
    cstyle = resolve_style(char_sid, objects, cache) if char_sid else None
    pstyle = resolve_style(para_sid, objects, cache) if para_sid else None
    pmetrics = resolve_para_style(para_sid, objects, cache) if para_sid else {}

    def pick(field: str) -> Any:
        if cstyle is not None and cstyle.get(field) is not None:
            return cstyle[field]
        if pstyle is not None and pstyle.get(field) is not None:
            return pstyle[field]
        return None

    line_spacing = pmetrics.get("lineSpacing")
    amount = line_spacing.get("amount") if isinstance(line_spacing, dict) else None
    mode = line_spacing.get("mode") if isinstance(line_spacing, dict) else None
    tracking = cstyle.get("tracking") if cstyle else None
    cs = cstyle or {}
    ps = pstyle or {}
    return ShapeStyle(
        font_name=pick("fontName"),
        size=float(pick("size") or 0.0),
        line_multiple=float(amount) if amount else 1.0,
        alignment=pmetrics.get("alignment"),
        tracking=float(tracking) if tracking else 0.0,
        bold=bool(cs.get("bold")) or bool(ps.get("bold")),
        italic=bool(cs.get("italic")) or bool(ps.get("italic")),
        first_line_indent=float(pmetrics.get("firstLineIndent") or 0.0),
        left_indent=float(pmetrics.get("leftIndent") or 0.0),
        right_indent=float(pmetrics.get("rightIndent") or 0.0),
        line_spacing_mode=mode,
    )


# --------------------------------------------------------------------------
# AppKit shaping.  Lazy import so the module loads on non-mac / test hosts.
# --------------------------------------------------------------------------
def _ns_font(
    font_name: str | None, size: float, bold: bool = False, italic: bool = False
) -> tuple[Any, bool, bool]:
    """``(NSFont, missing, trait_bad)`` for a PostScript ``font_name`` at ``size``.

    ``missing`` is True when the exact font is not installed (the metrics would be a
    substitute's, so the box is unvouched); the system font of the same size is
    returned so a measurement still happens.

    The PostScript name usually already encodes weight/style (e.g.
    ``ArgentCF-RegularItalic``), so the resolved font's traits are checked FIRST and
    a bold/italic request that the font already satisfies applies nothing (idempotent
    — and skipped anyway). Only a requested trait the font LACKS is applied via
    ``NSFontManager.convertFont_toHaveTrait_``, then VERIFIED: the result must carry
    the requested trait bit(s) AND keep the same family (a substitution to a
    different family would silently change metrics). If verification fails,
    ``trait_bad`` is True and the ORIGINAL font is returned so the caller can gate
    (``trait-unsatisfiable``) rather than measure with a wrong face.
    """
    from AppKit import (  # noqa: PLC0415 (optional pyobjc bridge, lazy)
        NSBoldFontMask,
        NSFont,
        NSFontManager,
        NSItalicFontMask,
    )

    font = NSFont.fontWithName_size_(font_name, size) if font_name else None
    if font is None:
        return (NSFont.systemFontOfSize_(size), True, False)
    if not (bold or italic):
        return (font, False, False)

    mgr = NSFontManager.sharedFontManager()
    have = mgr.traitsOfFont_(font)
    want_masks = []
    if bold and not (have & NSBoldFontMask):
        want_masks.append(NSBoldFontMask)
    if italic and not (have & NSItalicFontMask):
        want_masks.append(NSItalicFontMask)
    if not want_masks:
        return (font, False, False)  # font already satisfies every requested trait

    family = font.familyName()
    converted = font
    for mask in want_masks:
        converted = mgr.convertFont_toHaveTrait_(converted, mask)
    new_traits = mgr.traitsOfFont_(converted)
    ok = converted.familyName() == family
    if bold and not (new_traits & NSBoldFontMask):
        ok = False
    if italic and not (new_traits & NSItalicFontMask):
        ok = False
    if not ok:
        return (font, False, True)  # trait unsatisfiable -> gate, don't trust metrics
    return (converted, False, False)


def _resolve_font(style: ShapeStyle) -> tuple[Any, bool, bool]:
    """``(NSFont, missing, trait_bad)`` for a :class:`ShapeStyle` (traits included)."""
    return _ns_font(style.font_name, style.size or 1.0, style.bold, style.italic)


def _attributed(text: str, style: ShapeStyle) -> Any:
    from AppKit import (  # noqa: PLC0415
        NSAttributedString,
        NSFontAttributeName,
        NSKernAttributeName,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
    )

    font, _missing, _trait_bad = _resolve_font(style)
    para = NSMutableParagraphStyle.alloc().init()
    if style.line_multiple and style.line_multiple != 1.0:
        para.setLineHeightMultiple_(style.line_multiple)
    # Indents are handled by EXPLICIT wrap-width arithmetic (see shaped_height /
    # shaped_width), NOT by the paragraph style, so they are deliberately not set
    # here — setting them too would double-count the inset.
    attrs = {NSFontAttributeName: font, NSParagraphStyleAttributeName: para}
    if style.tracking:
        attrs[NSKernAttributeName] = style.tracking
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def _layout_height(text: str, wrap_width: float, style: ShapeStyle) -> float:
    from AppKit import NSStringDrawingUsesLineFragmentOrigin  # noqa: PLC0415
    from Foundation import NSMakeSize  # noqa: PLC0415

    astr = _attributed(text, style)
    rect = astr.boundingRectWithSize_options_context_(
        NSMakeSize(max(1.0, wrap_width), 1.0e6),
        NSStringDrawingUsesLineFragmentOrigin,
        None,
    )
    return float(rect.size.height)


def _layout_width(text: str, style: ShapeStyle) -> float:
    """Unconstrained longest laid-out line WIDTH via TextKit ``boundingRectWithSize_``.

    Uses ``boundingRectWithSize_(1e6, 1e6, UsesLineFragmentOrigin)`` rather than
    ``NSAttributedString.size().width`` so the width primitive is the same TextKit
    line-fragment path as the height, keeping the two measurements consistent (and
    letting the A/B harness judge whether auto-width boxes are ever cleanly vouchable;
    they are gated ``autowidth-soft`` for now regardless).
    """
    from AppKit import NSStringDrawingUsesLineFragmentOrigin  # noqa: PLC0415
    from Foundation import NSMakeSize  # noqa: PLC0415

    astr = _attributed(text, style)
    rect = astr.boundingRectWithSize_options_context_(
        NSMakeSize(1.0e6, 1.0e6),
        NSStringDrawingUsesLineFragmentOrigin,
        None,
    )
    return float(rect.size.width)


def _height_wrap_width(box_width: float, style: ShapeStyle) -> float:
    """Wrap width for :func:`shaped_height`: box width minus insets minus L/R indent."""
    return box_width - 2.0 * TEXT_INSET - style.left_indent - style.right_indent


def _one_line_height(style: ShapeStyle) -> float:
    """Height of a single unwrapped line for this style (the multi-line detector unit)."""
    return _layout_height("Ag", 1.0e6, style)


def _is_multiline(text: str, box_width: float, style: ShapeStyle) -> bool:
    """True when the flags==1 wrapped layout spans more than one line.

    Detected by ``wrapped_layout / one_line_height`` rounding to >= 2; the 1.5x
    threshold tolerates Keynote's ~5% per-line height spread.
    """
    one = _one_line_height(style)
    if one <= 0:
        return False
    return _layout_height(text, _height_wrap_width(box_width, style), style) > 1.5 * one


def shaped_height(text: str, box_width: float, style: ShapeStyle) -> float:
    """Keynote's laid-out box HEIGHT for auto-height text at a fixed ``box_width``.

    Wraps at ``box_width - 2*TEXT_INSET - left_indent - right_indent``, then applies
    the per-family size-aware model ``layout*m + b*size`` (:data:`HEIGHT_MODEL`).
    Unknown families fall back to the AzoSans coefficients — the box is gated
    ``uncalibrated-font`` by :func:`compose_text_geometry` regardless, so this value
    is only ever a best-effort for a box the caller will re-read.

    ``first_line_indent`` is intentionally NOT modelled in the wrap width: when it
    differs from ``left_indent`` its height effect is at most one word's worth of
    wrapping, which sits inside the overflow half-line slack.
    """
    layout = _layout_height(text, _height_wrap_width(box_width, style), style)
    m, b = HEIGHT_MODEL.get(_family(style.font_name), HEIGHT_MODEL["AzoSans"])
    return layout * m + b * style.size


def shaped_width(text: str, style: ShapeStyle) -> float:
    """Keynote's laid-out box WIDTH for an auto-width box (longest line + insets).

    Unconstrained longest laid-out line (TextKit :func:`_layout_width`) plus
    ``2*TEXT_INSET`` for the box's left/right inset and any left/right indent.
    """
    return _layout_width(text, style) + 2.0 * TEXT_INSET + style.left_indent + style.right_indent


def font_missing(style: ShapeStyle) -> bool:
    """True when the box's exact font is not installed (extent would be a substitute's)."""
    _font, missing, _trait_bad = _resolve_font(style)
    return missing


# --------------------------------------------------------------------------
# Gate envelope — every non-None reason forces a Keynote bulk fallback.
# --------------------------------------------------------------------------
def _gate_reason(
    style: ShapeStyle, flags: int, text: str, box_width: float
) -> str | None:
    """First failing gate condition for a shaped (flags 0/1) box, else ``None``.

    Reasons, all UNVOUCHED (a caller must fall back to a Keynote read):

        * ``font-missing`` — the exact font is not installed (substitute metrics).
        * ``uncalibrated-font`` — the family has no :data:`HEIGHT_MODEL` entry.
        * ``linespacing-mode`` — a ``lineSpacing.mode`` other than the relative
          multiple (``None``); 0 occur on GW/DSK, pure safety (B4).
        * ``trait-unsatisfiable`` — a bold/italic request AppKit could not apply
          without changing family (C).
        * ``uncalibrated-multiline`` — a :data:`SINGLE_LINE_ONLY` family (slope
          under-determined) whose shaped layout is multi-line (B2).
        * ``autowidth-soft`` — a flags==0 (auto-width) box: ~15px w / 25px h error
          even on GW, and a wrong ``w`` corrupts ``x`` (``x=anchor-w/2``); gated by
          default (B3).
    """
    _font, missing, trait_bad = _resolve_font(style)
    if missing:
        return "font-missing"
    fam = _family(style.font_name)
    if fam not in HEIGHT_MODEL:
        return "uncalibrated-font"
    if style.line_spacing_mode is not None:
        return "linespacing-mode"
    if trait_bad:
        return "trait-unsatisfiable"
    if fam in SINGLE_LINE_ONLY and flags == 1 and _is_multiline(text, box_width, style):
        return "uncalibrated-multiline"
    if flags == 0:
        return "autowidth-soft"
    return None


# --------------------------------------------------------------------------
# Mode-aware composer.
# --------------------------------------------------------------------------
@dataclass
class TextGeometry:
    """Composed text-box geometry + vouching."""

    x: float
    y: float
    w: float
    h: float
    flags: int
    geom_source: str  # "frame" | "shaped-height" | "shaped-both"
    # None when vouched; else one of the :func:`_gate_reason` strings (or
    # "font-missing" from the no-style fallback). Every non-None value forces the
    # caller to fall back to a Keynote read for this box.
    reason: str | None


def compose_text_geometry(
    rec: dict, objects: dict[str, dict], cache: dict
) -> TextGeometry:
    """Mode-aware ``(x, y, w, h)`` for a text record, dispatched on ``geometry.flags``.

    ``rec`` is a :func:`iwa_geometry.compose_geometry` text record (carries ``id`` and
    ``text``). Returns a :class:`TextGeometry`; ``reason`` is a non-None gate string
    (see :func:`_gate_reason`) when the box is unvouched, else ``None``.

        * ``flags`` with bit 1 set (height fixed; ``flags in {2, 3}``) — frame rule,
          EXACT, always vouched (no shaping, so no font dependency).
        * ``flags == 1`` — ``x=fx``, ``y=fy`` (TOP), ``w=naturalSize.width`` (exact),
          ``h=shaped_height``.
        * ``flags == 0`` — ``w=shaped_width``, ``h=shaped_height(text, w)``,
          ``x=anchor_x - w/2``, ``y=anchor_y - h/2`` (centre anchor); always gated —
          ``autowidth-soft`` unless an earlier gate (e.g. ``font-missing``) fires first.
    """
    obj = objects.get(rec["id"]) or {}
    geom = _geom_dict(obj)
    flags = geometry_flags(geom)
    text = rec.get("text") or ""

    # Height authored -> the frame is exact; no shaping (hence no font dependency).
    if height_fixed(flags):
        fx, fy, fw, fh = _frame_rect(geom)
        return TextGeometry(fx, fy, fw, fh, flags, "frame", None)

    style = shape_style(obj, objects, cache)
    if style is None or not style.font_name or not style.size:
        # No resolvable style to shape with: fall back to the raw autosize best-effort
        # and mark unvouched so the caller confirms it against Keynote.
        fx, fy, fw, fh, _a = _xywha(geom)
        nw, nh = _natural_size(obj)
        if flags == 1:
            return TextGeometry(fx, fy, nw, nh, flags, "shaped-height", "font-missing")
        return TextGeometry(fx - nw / 2.0, fy - nh / 2.0, nw, nh, flags, "shaped-both", "font-missing")

    if flags == 1:  # fixed width + auto height
        fx, fy, _fw, _fh, _a = _xywha(geom)
        nw, _nh = _natural_size(obj)
        reason = _gate_reason(style, flags, text, nw)
        h = shaped_height(text, nw, style)
        return TextGeometry(fx, fy, nw, h, flags, "shaped-height", reason)

    # flags == 0 (and any other auto-width-auto-height): shape both, centre anchor.
    anchor_x, anchor_y, _fw, _fh, _a = _xywha(geom)
    w = shaped_width(text, style)
    reason = _gate_reason(style, flags, text, w)
    h = shaped_height(text, w, style)
    return TextGeometry(anchor_x - w / 2.0, anchor_y - h / 2.0, w, h, flags, "shaped-both", reason)
