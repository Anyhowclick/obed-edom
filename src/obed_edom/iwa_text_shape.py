"""Offline mode-aware text-box geometry via AppKit NSAttributedString.

geometry.flags: 0x1 width fixed, 0x2 height fixed. flags==1 is top-anchored
(x,y=frame; w=naturalSize.width; h=shaped); flags==0 is centre-anchored
(x,y = anchor − size/2). Height = layout*m + b*size; wrap at width − 2*TEXT_INSET.

Wiring: a vouched box's geom_source must sit outside offline_inspect.SOFT_GEOM_SOURCES;
an unvouched box must never be autosize-soft.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from obed_edom.iwa_geometry import _frame_rect, _geom_dict, _natural_size, _xywha
from obed_edom.iwa_runs import resolve_para_style, resolve_style
from obed_edom.offline_inspect import _leading_sid, _storage_of

# Wrap width = box width − 2*TEXT_INSET (− L/R indent).
TEXT_INSET = 12.0

# shaped_height = layout*m + b*size. Mixed-run boxes are single-style approximated (accepted residual).
HEIGHT_MODEL: dict[str, tuple[float, float]] = {
    "AzoSans": (1.013, 0.455),
    "ArgentCF": (1.013, 0.294),
}

# ArgentCF slope is under-determined (single-line fit only); multi-line is gated.
SINGLE_LINE_ONLY: frozenset[str] = frozenset({"ArgentCF"})


def geometry_flags(geom: dict) -> int:
    """geometry.flags (0 when absent). Bit 0 = width fixed, bit 1 = height fixed."""
    return int(geom.get("flags") or 0)


def width_fixed(flags: int) -> bool:
    return bool(flags & 0x1)


def height_fixed(flags: int) -> bool:
    return bool(flags & 0x2)


def _family(font_name: str | None) -> str:
    if not font_name:
        return ""
    return font_name.split("-")[0]


@dataclass
class ShapeStyle:
    font_name: str | None
    size: float
    line_multiple: float  # lineSpacing amount (relative); 1.0 when unset
    alignment: str | None
    tracking: float  # character tracking/kerning (points); 0.0 when unset
    bold: bool  # leading run OR paragraph
    italic: bool  # leading run OR paragraph
    first_line_indent: float  # points; 0.0 when unset
    left_indent: float  # points; 0.0 when unset
    right_indent: float  # points; 0.0 when unset
    line_spacing_mode: Any  # lineSpacing.mode; None == relative multiple


def _resolve_shape_padding(
    style_id: str, objects: dict[str, dict], seen: set[str], hops: int = 0
) -> float | None:
    """First ``shapeProperties.padding.left`` found walking this style's own super-nesting,
    else its parent style (``...super.parent``, depth varies by archive type)."""
    if style_id in seen or hops > 8:
        return None
    seen.add(style_id)
    obj = objects.get(style_id)
    if not obj:
        return None
    cur: Any = obj
    parent_id: str | None = None
    for _ in range(6):
        if not isinstance(cur, dict):
            break
        props = cur.get("shapeProperties")
        if isinstance(props, dict):
            padding = props.get("padding")
            if isinstance(padding, dict) and padding.get("left") is not None:
                return float(padding["left"])
        parent = cur.get("parent")
        if isinstance(parent, dict) and parent_id is None and parent.get("identifier") is not None:
            parent_id = str(parent["identifier"])
        cur = cur.get("super")
    if parent_id:
        return _resolve_shape_padding(parent_id, objects, seen, hops + 1)
    return None


def shape_padding(obj: dict, objects: dict[str, dict], cache: dict) -> float:
    """Effective left-inset for a ``TSWP.ShapeInfoArchive``'s style (``obj.super.style``),
    walking the style → parent-style chain. 0.0 when never set. Does not touch TEXT_INSET,
    the separate LW verse-box wrap constant."""
    style_ref = (obj.get("super") or {}).get("style")
    style_id = style_ref.get("identifier") if isinstance(style_ref, dict) else None
    if style_id is None:
        return 0.0
    style_id = str(style_id)
    key = f"padding:{style_id}"
    if key in cache:
        return cache[key]
    value = _resolve_shape_padding(style_id, objects, set())
    result = float(value) if value is not None else 0.0
    cache[key] = result
    return result


def shape_style(obj: dict, objects: dict[str, dict], cache: dict) -> ShapeStyle | None:
    """Char then paragraph. Bold/italic are OR of both (pick would hide the paragraph flag)."""
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


def _ns_font(
    font_name: str | None, size: float, bold: bool = False, italic: bool = False
) -> tuple[Any, bool, bool]:
    """(NSFont, missing, trait_bad). Unsatisfiable traits keep the original font so callers gate."""
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
        return (font, False, False)

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
        return (font, False, True)
    return (converted, False, False)


def _resolve_font(style: ShapeStyle) -> tuple[Any, bool, bool]:
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
    # Don't set para indents — wrap-width arithmetic already subtracts them.
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
    """Unconstrained line width via the same TextKit path as height."""
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
    return box_width - 2.0 * TEXT_INSET - style.left_indent - style.right_indent


def _one_line_height(style: ShapeStyle) -> float:
    return _layout_height("Ag", 1.0e6, style)


def _is_multiline(text: str, box_width: float, style: ShapeStyle) -> bool:
    """Wrapped layout > 1.5 * one-line (tolerates Keynote's ~5% per-line spread)."""
    one = _one_line_height(style)
    if one <= 0:
        return False
    return _layout_height(text, _height_wrap_width(box_width, style), style) > 1.5 * one


def shaped_height(text: str, box_width: float, style: ShapeStyle) -> float:
    """layout*m + b*size at wrap = box − 2*inset − L/R indent. first_line_indent omitted."""
    layout = _layout_height(text, _height_wrap_width(box_width, style), style)
    m, b = HEIGHT_MODEL.get(_family(style.font_name), HEIGHT_MODEL["AzoSans"])
    return layout * m + b * style.size


def shaped_width(text: str, style: ShapeStyle) -> float:
    return _layout_width(text, style) + 2.0 * TEXT_INSET + style.left_indent + style.right_indent


def font_missing(style: ShapeStyle) -> bool:
    _font, missing, _trait_bad = _resolve_font(style)
    return missing


def _gate_reason(
    style: ShapeStyle, flags: int, text: str, box_width: float
) -> str | None:
    """First failing gate, else None. All non-None force a Keynote fallback."""
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


@dataclass
class TextGeometry:
    x: float
    y: float
    w: float
    h: float
    flags: int
    geom_source: str  # "frame" | "shaped-height" | "shaped-both"
    reason: str | None  # None = vouched; else gate string (forces Keynote fallback)


def compose_text_geometry(
    rec: dict, objects: dict[str, dict], cache: dict
) -> TextGeometry:
    """flags height-fixed → frame; flags==1 top-anchored shaped h; flags==0 centre-anchored (gated)."""
    obj = objects.get(rec["id"]) or {}
    geom = _geom_dict(obj)
    flags = geometry_flags(geom)
    text = rec.get("text") or ""

    if height_fixed(flags):
        fx, fy, fw, fh = _frame_rect(geom)
        return TextGeometry(fx, fy, fw, fh, flags, "frame", None)

    style = shape_style(obj, objects, cache)
    if style is None or not style.font_name or not style.size:
        fx, fy, fw, fh, _a = _xywha(geom)
        nw, nh = _natural_size(obj)
        if flags == 1:
            return TextGeometry(fx, fy, nw, nh, flags, "shaped-height", "font-missing")
        return TextGeometry(fx - nw / 2.0, fy - nh / 2.0, nw, nh, flags, "shaped-both", "font-missing")

    if flags == 1:
        fx, fy, _fw, _fh, _a = _xywha(geom)
        nw, _nh = _natural_size(obj)
        reason = _gate_reason(style, flags, text, nw)
        h = shaped_height(text, nw, style)
        return TextGeometry(fx, fy, nw, h, flags, "shaped-height", reason)

    anchor_x, anchor_y, _fw, _fh, _a = _xywha(geom)
    w = shaped_width(text, style)
    reason = _gate_reason(style, flags, text, w)
    h = shaped_height(text, w, style)
    return TextGeometry(anchor_x - w / 2.0, anchor_y - h / 2.0, w, h, flags, "shaped-both", reason)
