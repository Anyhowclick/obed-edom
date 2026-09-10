#!/usr/bin/env python3
"""Probe: does an offline ``TSD.MovieArchive.posterTime`` patch drive Keynote's
displayed/navigator poster frame, and does it survive an open + save?

Read-only against the owner's deck; ``patch``/``reopen`` only ever write a COPY this
script makes itself, under ``output/`` (never ``/private/tmp`` -- Keynote cannot
reliably open work there). ``dump`` and ``patch`` never open Keynote; ``reopen`` does,
and is gated behind ``--yes-open-keynote`` so it can never run by accident.

Subcommands:
  dump <deck.key>                       -- print every TSD.MovieArchive, read-only.
  patch <deck.key> --poster last|<sec>   -- copy, patch posterTime offline, re-dump.
  reopen <deck.key> --yes-open-keynote   -- close-by-name -> open -> activate ->
                                             document 1 -> delay -> save -> close
                                             saving yes, then re-dump the copy.

Ask the owner to run ``dump`` on the deck where they have already set a poster frame
by hand, AND on an untouched export of the same deck -- diffing the two answers
whether a manual poster-frame set writes posterTime alone or posterTime plus a fresh
posterImageData.

``patch`` default selection skips full-width background fly movies (WALL centre
band, width >= 3840, or frame spans the full slide height 1080) and only patches
landmark-sized archives; pass ``--all`` to patch every archive found, or ``--id``
to patch one specific archive regardless of size.

Probe result (2026-09-10, Keynote 15.3.1): setting a poster frame by hand in the
Keynote UI changes only ``posterTime`` (to ``endTime``) -- no ``posterImageData``,
database-backed poster image, or alpha-support field changes.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from obed_edom import keynote_app
from obed_edom.iwa_movies import movie_archives, patch_movie_posters
from obed_edom.iwa_runs import _load_deck

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "output" / "movie-poster-probe"


def _extra_fields(deck: Path, ids: list[str]) -> dict[str, dict]:
    """Fields ``movie_archives`` doesn't carry: playsAcrossSlides, alpha-support flag,
    and whether a database-backed poster image reference is set."""
    objects, _id_to_file, _file_ids = _load_deck(deck)
    out: dict[str, dict] = {}
    for oid in ids:
        obj = objects.get(oid) or {}
        out[oid] = {
            "playsAcrossSlides": bool(obj.get("playsAcrossSlides") or False),
            "posterAlphaSupport": bool(obj.get("poster_image_generated_with_alpha_support") or False),
            "hasDatabasePosterImageData": bool((obj.get("database_posterImageData") or {}).get("identifier")),
        }
    return out


def _print_dump(deck: Path) -> list[dict]:
    archives = movie_archives(deck)
    extra = _extra_fields(deck, [a["id"] for a in archives])
    print(f"{'id':>10}  {'member':28}  {'x':>6} {'y':>6} {'w':>6} {'h':>6}  "
          f"{'start':>6} {'end':>6} {'poster':>6}  {'auto':>5} {'spans':>5}  "
          f"{'hasImg':>6} {'dbImg':>5} {'alpha':>5}  dataName")
    for a in archives:
        e = extra.get(a["id"], {})
        print(
            f"{a['id']:>10}  {str(a['member']):28}  "
            f"{a['x']:>6.1f} {a['y']:>6.1f} {a['w']:>6.1f} {a['h']:>6.1f}  "
            f"{a['startTime']:>6.2f} {a['endTime']:>6.2f} {a['posterTime']:>6.2f}  "
            f"{str(a['autoPlay']):>5} {str(e.get('playsAcrossSlides')):>5}  "
            f"{str(a['hasPosterImageData']):>6} {str(e.get('hasDatabasePosterImageData')):>5} "
            f"{str(e.get('posterAlphaSupport')):>5}  {a['dataName']}"
        )
    return archives


def cmd_dump(args: argparse.Namespace) -> int:
    if not args.deck.exists():
        raise SystemExit(f"--deck not found: {args.deck}")
    _print_dump(args.deck)
    return 0


def _resolve_poster(archive: dict, poster: str) -> float:
    if poster == "last":
        # A freshly imported movie can encode endTime == 0 to mean "movie end", not
        # "the first instant" -- max(startTime, endTime) would then silently patch
        # the first frame while reporting success. Refuse rather than guess; the
        # caller must pass explicit seconds (or a resolved media duration).
        if archive["endTime"] <= 0:
            raise SystemExit(
                f"--poster last refused for archive {archive['id']}: no explicit positive "
                f"endTime (startTime={archive['startTime']}, endTime={archive['endTime']}); "
                "pass --poster <seconds> instead"
            )
        return max(archive["startTime"], archive["endTime"])
    return float(poster)


FULL_WIDTH_MIN = 3840.0
FULL_HEIGHT = 1080.0


def select_archives_to_patch(
    archives: list[dict], *, all_archives: bool = False, only_id: str | None = None
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Pick which archives ``patch`` touches. Returns (selected, skipped) where
    skipped is [(id, reason), ...].

    Default: skip full-width background fly movies (WALL centre band width
    >= FULL_WIDTH_MIN, or a frame spanning the full slide height FULL_HEIGHT) so
    ``patch`` without flags can't silently repoint a background movie's poster;
    only landmark-sized archives are kept. ``--all`` opts back into everything.
    ``--id`` overrides selection entirely and patches just that one archive.
    """
    if only_id is not None:
        selected = [a for a in archives if a["id"] == only_id]
        return selected, []
    if all_archives:
        return list(archives), []
    selected: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for a in archives:
        if a["w"] >= FULL_WIDTH_MIN:
            skipped.append((a["id"], f"width {a['w']:.1f} >= {FULL_WIDTH_MIN:.0f} (WALL centre band)"))
        elif a["h"] >= FULL_HEIGHT:
            skipped.append((a["id"], f"height {a['h']:.1f} spans full slide height {FULL_HEIGHT:.0f}"))
        else:
            selected.append(a)
    return selected, skipped


def cmd_patch(args: argparse.Namespace) -> int:
    if not args.deck.exists():
        raise SystemExit(f"--deck not found: {args.deck}")
    args.out.mkdir(parents=True, exist_ok=True)
    copy_path = args.out / f"{args.deck.stem}_poster.key"
    if copy_path.resolve() == args.deck.resolve():
        raise SystemExit("--out would alias --deck")
    if copy_path.exists() and not args.force:
        raise SystemExit(f"{copy_path} exists; pass --force")
    shutil.copyfile(args.deck, copy_path)
    print(f"copied {args.deck} -> {copy_path}")

    all_archives = movie_archives(copy_path)
    if args.id and args.id not in {a["id"] for a in all_archives}:
        raise SystemExit(f"--id {args.id} not found in deck")
    archives, skipped = select_archives_to_patch(all_archives, all_archives=args.all, only_id=args.id)
    for oid, reason in skipped:
        print(f"SKIP {oid}: {reason}")
    if not archives:
        raise SystemExit("no archives selected to patch")
    posters = {a["id"]: _resolve_poster(a, args.poster) for a in archives}
    result = patch_movie_posters(copy_path, posters)
    print(f"PATCH: refused={result['refused']} applied={result.get('applied')}")
    if result["refused"]:
        print(f"REFUSED: {result['reason']}")
        return 2

    print("re-dump after offline patch:")
    _print_dump(copy_path)
    return 0


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def reopen_applescript(deck_path: Path, *, doc_name: str) -> str:
    """close-by-name -> open -> activate -> document 1 -> delay -> save -> close
    saving yes. Never addresses Keynote by name -- always the bundle id."""
    key = _as_escape(str(Path(deck_path).resolve()))
    app = keynote_app.bundle_id()
    return "\n".join(
        [
            f'using terms from application id "{app}"',
            f'tell application id "{app}"',
            "  with timeout of 3600 seconds",
            "  try",
            f'    close (every document whose name is "{doc_name}") saving no',
            f'    close (every document whose name is "{doc_name}.key") saving no',
            "    delay 0.3",
            "  end try",
            f'  set theFile to POSIX file "{key}"',
            "  open theFile",
            "  activate",
            "  delay 0.4",
            "  set theDoc to document 1",
            "  set gotPath to POSIX path of (file of theDoc as alias)",
            f'  if gotPath is not "{key}" then error '
            f'"bound wrong document, expected {key} but got: " & gotPath',
            "  delay 2",
            "  save theDoc",
            "  close theDoc saving yes",
            "  end timeout",
            "end tell",
            "end using terms from",
        ]
    )


def _run_osascript(script: str) -> str:
    subprocess.run(["open", "-b", keynote_app.bundle_id()], check=False)
    time.sleep(0.4)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(["osascript", str(script_path)], capture_output=True, text=True, check=False)
    finally:
        script_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("osascript failed:\n" + (proc.stderr or "") + "\n" + (proc.stdout or ""))
    return (proc.stdout or "").strip()


def cmd_reopen(args: argparse.Namespace) -> int:
    if not args.yes_open_keynote:
        raise SystemExit("reopen drives Keynote; pass --yes-open-keynote to confirm")
    if not args.deck.exists():
        raise SystemExit(f"--deck not found: {args.deck}")
    # Never open the owner's deck in place -- always drive Keynote against a copy
    # this script makes itself, under --out.
    args.out.mkdir(parents=True, exist_ok=True)
    copy_path = args.out / f"{args.deck.stem}_reopen.key"
    if copy_path.resolve() == args.deck.resolve():
        raise SystemExit("--out would alias --deck")
    if copy_path.exists() and not args.force:
        raise SystemExit(f"{copy_path} exists; pass --force")
    shutil.copyfile(args.deck, copy_path)
    print(f"copied {args.deck} -> {copy_path}")

    print("dump before reopen:")
    before = _print_dump(copy_path)
    poster_before = {a["id"]: a["posterTime"] for a in before}

    _run_osascript(reopen_applescript(copy_path, doc_name=copy_path.stem))

    print("dump after Keynote open + save:")
    after = _print_dump(copy_path)
    for a in after:
        prior = poster_before.get(a["id"])
        print(f"  {a['id']}: posterTime before={prior} after={a['posterTime']} "
              f"survived={prior == a['posterTime']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    dump_ap = sub.add_parser("dump", help="read-only: print every TSD.MovieArchive")
    dump_ap.add_argument("deck", type=Path)
    dump_ap.set_defaults(func=cmd_dump)

    patch_ap = sub.add_parser("patch", help="offline: copy, patch posterTime, re-dump")
    patch_ap.add_argument("deck", type=Path)
    patch_ap.add_argument("--poster", default="last", help='"last" or a literal seconds value')
    patch_ap.add_argument("--id", default=None, help="patch only this archive id, regardless of size")
    patch_ap.add_argument("--all", action="store_true",
                           help="patch every archive found, including full-width background movies")
    patch_ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="scratch dir for the copy")
    patch_ap.add_argument("--force", action="store_true", help="overwrite an existing copy at --out")
    patch_ap.set_defaults(func=cmd_patch)

    reopen_ap = sub.add_parser("reopen", help="drives Keynote -- close/open/save cycle on a COPY of --deck")
    reopen_ap.add_argument("deck", type=Path)
    reopen_ap.add_argument("--yes-open-keynote", action="store_true",
                            help="required: confirms this subcommand opens Keynote")
    reopen_ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="scratch dir for the copy")
    reopen_ap.add_argument("--force", action="store_true", help="overwrite an existing copy at --out")
    reopen_ap.set_defaults(func=cmd_reopen)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
