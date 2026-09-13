REVISE

1. **Medium — degenerate content still affects the fallback count.** `src/obed_edom/dsk_assemble.py:408-413` removes zero-width/zero-height rects from the union, but then uses `len(content_ids)`. Thus one valid squarish item plus two degenerate media items incorrectly centres as “3+”, and a lone degenerate item becomes `right` instead of the zero-content default `centre`. Use the count of positive-area, panel-clipped rects; return `centre` when that list is empty. Add tests for a lone zero rect and one valid item plus two degenerate rects.

Both findings from `codex-placement-review1.md` are resolved.

Tests could not start because the sandbox has no writable temporary directory; pytest failed in capture initialization with `FileNotFoundError: No usable temporary directory`.