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

CALIBRATION (frozen constants below) was fit ONCE against the cached JXA GW payload
as the oracle (Keynote-free — JXA's laid-out ``h`` on a flags-1 box IS the shaped
height). See :data:`TEXT_INSET`, :data:`VERTICAL_PAD`, :data:`LINE_CORRECTION`.

GUARD: the shaped extent is only valid when the box's exact font is installed. If
``NSFont.fontWithName_`` returns ``nil`` the metrics would be a substitute font's, so
the box is marked UNVOUCHED (reason ``font-missing``) and a caller must fall back to
a Keynote read for it. This is the top accuracy risk.

Public entry points:
    * :func:`shape_style` — the shaping style for a text box (font + paragraph metrics).
    * :func:`shaped_height` / :func:`shaped_width` — the AppKit measurements.
    * :func:`compose_text_geometry` — the mode-aware ``(x, y, w, h)`` composer + guard.
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
# Fit ONCE by minimising |shaped_height - JXA_height| over the 36 flags==1 boxes
# of the GW checker deck (`Sermon_PK (GW).key`) with a real cached JXA height,
# Keynote-free (JXA's laid-out box height on an auto-height box is exactly the
# shaped text height). The model is
#
#     shaped_height = layout(text, W - 2*TEXT_INSET, lineHeightMultiple=lineSpacing)
#                     * LINE_CORRECTION[family] + VERTICAL_PAD
#
# where ``layout`` is AppKit's wrapped bounding-box height. The residual is
# dominated by Keynote's per-line glyph-dependent line heights, which a uniform
# ``lineHeightMultiple`` cannot reproduce (two 2-line AzoSans boxes with identical
# AppKit layouts land at JXA 193 vs 198 — a ~5px spread no closed form removes), so
# the achievable parity is ~3px median / ~6px max on flags==1, NOT <=2px on every
# box. That residual is far inside the overflow flag's half-line slack
# (~41px at size 70) and the bounds cut thresholds, which is what the A/B verifies.
# --------------------------------------------------------------------------

# exteriorTextWrap.margin — the text inset Keynote wraps inside, each side. Wrapping
# width = box width - 2*TEXT_INSET.
TEXT_INSET = 12.0

# Top+bottom vertical padding Keynote adds around the laid-out text block. Empirically
# 32pt (not 2*TEXT_INSET) on the GW deck; all GW calibration boxes are size 70, so this
# is frozen as an absolute value and the font-missing guard + caller fallback cover
# decks it was not fit on.
VERTICAL_PAD = 32.0

# Per-family correction mapping AppKit's line advance to Keynote's (their intrinsic
# line heights differ slightly). Applied to the wrapped layout height. Fit on GW:
# AzoSans from 31 multi-line boxes; ArgentCF from single-line boxes only (its slope is
# under-determined there — documented risk). Unknown families use DEFAULT_LINE_CORRECTION.
LINE_CORRECTION: dict[str, float] = {
    "AzoSans": 1.012,
    "ArgentCF": 1.042,
}
DEFAULT_LINE_CORRECTION = 1.02


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
    """The family key for :data:`LINE_CORRECTION` (PostScript name up to the first ``-``)."""
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


def shape_style(obj: dict, objects: dict[str, dict], cache: dict) -> ShapeStyle | None:
    """Build the :class:`ShapeStyle` from a text box's leading char + paragraph style.

    Font name / size resolve char-first then paragraph (a char override usually
    carries only colour/weight and leaves the font on the paragraph style — same
    resolution as :func:`offline_inspect._item_text_style`). Returns ``None`` when
    the box has no text storage.
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
    tracking = cstyle.get("tracking") if cstyle else None
    return ShapeStyle(
        font_name=pick("fontName"),
        size=float(pick("size") or 0.0),
        line_multiple=float(amount) if amount else 1.0,
        alignment=pmetrics.get("alignment"),
        tracking=float(tracking) if tracking else 0.0,
    )


# --------------------------------------------------------------------------
# AppKit shaping.  Lazy import so the module loads on non-mac / test hosts.
# --------------------------------------------------------------------------
def _ns_font(font_name: str | None, size: float) -> tuple[Any, bool]:
    """``(NSFont, missing)``. ``missing`` True when the exact font is not installed.

    The PostScript ``font_name`` already encodes weight/style (e.g.
    ``ArgentCF-RegularItalic``), so it is looked up verbatim — no trait re-application.
    On a miss, the system font of the same size is returned so a measurement still
    happens, but ``missing`` tells the caller the extent is a substitute's (unvouched).
    """
    from AppKit import NSFont  # noqa: PLC0415 (optional pyobjc bridge, lazy)

    font = NSFont.fontWithName_size_(font_name, size) if font_name else None
    if font is None:
        return (NSFont.systemFontOfSize_(size), True)
    return (font, False)


def _attributed(text: str, style: ShapeStyle) -> Any:
    from AppKit import (  # noqa: PLC0415
        NSAttributedString,
        NSFontAttributeName,
        NSKernAttributeName,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
    )

    font, _missing = _ns_font(style.font_name, style.size)
    para = NSMutableParagraphStyle.alloc().init()
    if style.line_multiple and style.line_multiple != 1.0:
        para.setLineHeightMultiple_(style.line_multiple)
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


def shaped_height(text: str, box_width: float, style: ShapeStyle) -> float:
    """Keynote's laid-out box HEIGHT for auto-height text at a fixed ``box_width``.

    Wraps at ``box_width - 2*TEXT_INSET``, scales AppKit's line advance to Keynote's
    per :data:`LINE_CORRECTION`, and adds :data:`VERTICAL_PAD`. See the calibration note.
    """
    layout = _layout_height(text, box_width - 2.0 * TEXT_INSET, style)
    corr = LINE_CORRECTION.get(_family(style.font_name), DEFAULT_LINE_CORRECTION)
    return layout * corr + VERTICAL_PAD


def shaped_width(text: str, style: ShapeStyle) -> float:
    """Keynote's laid-out box WIDTH for an auto-width box (longest line + insets).

    Unconstrained longest laid-out line via ``NSAttributedString.size().width`` plus
    ``2*TEXT_INSET`` for the box's left/right inset.
    """
    astr = _attributed(text, style)
    return float(astr.size().width) + 2.0 * TEXT_INSET


def font_missing(style: ShapeStyle) -> bool:
    """True when the box's exact font is not installed (extent would be a substitute's)."""
    _font, missing = _ns_font(style.font_name, style.size or 1.0)
    return missing


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
    reason: str | None  # None when vouched; else "font-missing"


def compose_text_geometry(
    rec: dict, objects: dict[str, dict], cache: dict
) -> TextGeometry:
    """Mode-aware ``(x, y, w, h)`` for a text record, dispatched on ``geometry.flags``.

    ``rec`` is a :func:`iwa_geometry.compose_geometry` text record (carries ``id`` and
    ``text``). Returns a :class:`TextGeometry`; ``reason`` is ``"font-missing"`` (the
    box unvouched) when the exact font is not installed, else ``None``.

        * ``flags`` with bit 1 set (height fixed; ``flags in {2, 3}``) — frame rule,
          EXACT, always vouched (no shaping, so no font dependency).
        * ``flags == 1`` — ``x=fx``, ``y=fy`` (TOP), ``w=naturalSize.width`` (exact),
          ``h=shaped_height``.
        * ``flags == 0`` — ``w=shaped_width``, ``h=shaped_height(text, w)``,
          ``x=anchor_x - w/2``, ``y=anchor_y - h/2`` (centre anchor).
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

    missing = font_missing(style)
    reason = "font-missing" if missing else None

    if flags == 1:  # fixed width + auto height
        fx, fy, _fw, _fh, _a = _xywha(geom)
        nw, _nh = _natural_size(obj)
        h = shaped_height(text, nw, style)
        return TextGeometry(fx, fy, nw, h, flags, "shaped-height", reason)

    # flags == 0 (and any other auto-width-auto-height): shape both, centre anchor.
    anchor_x, anchor_y, _fw, _fh, _a = _xywha(geom)
    w = shaped_width(text, style)
    h = shaped_height(text, w, style)
    return TextGeometry(anchor_x - w / 2.0, anchor_y - h / 2.0, w, h, flags, "shaped-both", reason)
