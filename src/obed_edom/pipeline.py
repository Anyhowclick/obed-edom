from __future__ import annotations

from pathlib import Path

from obed_edom.annotate import annotate_outline
from obed_edom.contrast import check_contrast
from obed_edom.keynote import generate_both, output_dir_for
from obed_edom.models import Flag, GenerationResult
from obed_edom.parse_outline import parse_outline
from obed_edom.report import write_review
from obed_edom.slide_map import map_slides
from obed_edom.validate import validate_outline, validate_slide_specs


def _cleanup_output(out_dir: Path) -> None:
    for leftover in out_dir.glob("*.json"):
        leftover.unlink(missing_ok=True)
    md = out_dir / "review.md"
    if md.exists():
        md.unlink()


def generate(
    docx: Path | str,
    *,
    make_keynote: bool = True,
    check_visuals: bool = True,
    lw_template: Path | str | None = None,
    dsk_template: Path | str | None = None,
) -> GenerationResult:
    docx = Path(docx).expanduser().resolve()
    if docx.suffix.lower() != ".docx":
        raise ValueError(f"Generate expects a .docx outline, got {docx.name}")
    outline = parse_outline(docx)
    lw, dsk, map_flags = map_slides(outline)
    flags: list[Flag] = []
    flags.extend(validate_outline(outline))
    flags.extend(map_flags)
    flags.extend(validate_slide_specs(lw, dsk))

    out_dir = output_dir_for(docx)
    review_path = out_dir / "review.pdf"
    lw_key = None
    dsk_key = None
    stem = docx.stem.replace(" ", "_")
    cued_docx = annotate_outline(outline, lw, dsk, out_dir / f"{stem}_CUED.docx")

    if make_keynote:
        out_dir, lw_key, dsk_key, lw_result, dsk_result = generate_both(
            docx,
            lw,
            dsk,
            export=check_visuals,
            lw_template=lw_template,
            dsk_template=dsk_template,
        )
        for result, deck in ((lw_result, "LW"), (dsk_result, "DSK")):
            if result.get("skipped"):
                continue
            missing = result.get("missingMasters") or []
            if missing:
                flags.append(
                    Flag(
                        "error",
                        "keynote",
                        f"{deck} missing masters: {', '.join(missing)}",
                    )
                )
            if check_visuals and not result.get("exported"):
                flags.append(
                    Flag("warning", "contrast", f"{deck} PNG export did not run; contrast not measured.")
                )
            super_fix = result.get("superscriptFix") or {}
            if not super_fix.get("ok") and not super_fix.get("skipped"):
                if super_fix.get("accessibilityDenied"):
                    flags.append(
                        Flag(
                            "warning",
                            "keynote",
                            f"{deck} later verse numbers are not superscript. Keynote has no "
                            "scriptable superscript, so it needs the Format menu: grant "
                            "Accessibility to Terminal (or the dashboard app) in System Settings > "
                            "Privacy & Security > Accessibility, then regenerate.",
                        )
                    )
                else:
                    flags.append(
                        Flag(
                            "warning",
                            "keynote",
                            f"{deck} later verse numbers may not be superscript; check them in Keynote.",
                        )
                    )

        if check_visuals and lw_key:
            lw_flags, _ = check_contrast(lw, out_dir / "previews" / "lw", "lw")
            flags.extend(lw_flags)
        if check_visuals and dsk_key:
            dsk_flags, _ = check_contrast(dsk, out_dir / "previews" / "dsk", "dsk")
            flags.extend(dsk_flags)

    if not make_keynote:
        if lw_key is None:
            candidate = out_dir / f"{stem}_LW.key"
            if candidate.exists():
                lw_key = candidate
        if dsk_key is None:
            candidate = out_dir / f"{stem}_DSK.key"
            if candidate.exists():
                dsk_key = candidate

    write_review(review_path, outline, lw, dsk, flags, lw_key, dsk_key)
    _cleanup_output(out_dir)
    return GenerationResult(
        output_dir=out_dir,
        lw_key=lw_key,
        dsk_key=dsk_key,
        review_path=review_path,
        flags=flags,
        lw_slides=lw,
        dsk_slides=dsk,
        cued_docx=cued_docx,
    )
