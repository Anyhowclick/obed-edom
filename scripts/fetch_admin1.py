"""Prime the admin-1 (state/province) split offline.

The dashboard fetches this lazily on the first `/api/maps/ne/admin1/*` call; this
script only pays the ~40 MB download up front so an authoring session never waits.

    .venv/bin/python scripts/fetch_admin1.py [--force]
"""

from __future__ import annotations

import argparse

from obed_edom.maps_admin1 import admin1_stats, clear_admin1, ensure_admin1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if already split")
    args = parser.parse_args()

    if args.force:
        clear_admin1()
    dest = ensure_admin1()
    stats = admin1_stats()
    countries = len(list(dest.glob("*.geojson")))
    print(f"{dest}\n{countries} countries, {stats['bytes'] / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
