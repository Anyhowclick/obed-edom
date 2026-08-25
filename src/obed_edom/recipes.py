"""Saved recipes: a transform learnt from a page that worked, kept for pages that
cannot learn one of their own.

A page whose artwork pairs with a template slide learns its own recipe. A page
whose artwork pairs with nothing — the LED chrome plus a movie, a full-bleed photo
the template has no counterpart for — learns nothing, and every framing candidate
degrades to the same fit-to-frame. Offering that operator more template slides
does not help; offering them a transform that already worked does.

Recipes live in `recipes/` at the repo root rather than under `output/` or
`.cache/`. They are curated by hand, one per layout the operator recognises, and
both of those folders are things people clear.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from obed_edom.paths import find_repo_root

RECIPES_DIR_ENV = "OBED_EDOM_RECIPES_DIR"
SLUG_RE = re.compile(r"[^a-z0-9]+")


def recipes_dir(root: Path | None = None) -> Path:
    """Where saved recipes live. Overridable so a test run cannot write into the
    operator's library."""
    if root is not None:
        return Path(root) / "recipes"
    override = (os.environ.get(RECIPES_DIR_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return find_repo_root() / "recipes"


def slugify(label: str) -> str:
    slug = SLUG_RE.sub("-", (label or "").strip().lower()).strip("-")
    return slug[:60] or "recipe"


def recipe_id(label: str, existing: set[str]) -> str:
    """A readable file name, suffixed only when it would collide."""
    base = slugify(label)
    if base not in existing:
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if candidate not in existing:
            return candidate
    return f"{base}-{int(time.time())}"


def save_recipe(
    portable: dict[str, Any],
    label: str,
    *,
    source: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Write one recipe and return its record.

    `source` is free text naming where it came from ("Extracted_Wall_3rd slide
    2"), so a library of a dozen stays readable a season later.
    """
    folder = recipes_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    existing = {p.stem for p in folder.glob("*.json")}
    record = {
        **portable,
        "id": recipe_id(label, existing),
        "label": (label or "").strip() or "Untitled recipe",
        "source": source,
    }
    (folder / f"{record['id']}.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    return record


def load_recipes(root: Path | None = None) -> list[dict[str, Any]]:
    """Every saved recipe, newest label order aside — sorted by id so the picker
    does not reshuffle between reloads."""
    folder = recipes_dir(root)
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or not (data.get("affine") or {}).get("s"):
            continue
        data.setdefault("id", path.stem)
        data.setdefault("label", path.stem)
        out.append(data)
    return out


def get_recipe(recipe_id_: str, root: Path | None = None) -> dict[str, Any] | None:
    for recipe in load_recipes(root):
        if str(recipe.get("id")) == str(recipe_id_):
            return recipe
    return None


def delete_recipe(recipe_id_: str, root: Path | None = None) -> bool:
    path = recipes_dir(root) / f"{slugify(str(recipe_id_))}.json"
    # The id is already a slug, but a caller could hand back a label.
    if not path.is_file():
        path = recipes_dir(root) / f"{recipe_id_}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True
