No Standards findings or §3.1 byte departures. **Four Spec findings remain.** Product mutations below were applied after extraction; each survived all 234 committed freeze rows on both players.

1. **Major — CLASS: new class (shadow-invariant bypass)** — [tests/test_live_runtime.py:428](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:428).  
   The checker accepts both `<template SHADOWROOTMODE="closed">` and `host['attach'+'Shadow']({mode:'closed'})`. These create author roots without matching its case-sensitive substrings. A closed root containing fixed paint escapes the runtime’s document traversal and `shadowRoot` check.  
   **Exact fix:** inspect HTML attribute names case-insensitively and normalize JavaScript property names, including escaped literals and constant concatenation. Add both examples as planted rejection controls; the current four controls only establish literal-substring detection.

2. **Major — CLASS: new class (exterior-proof coverage)** — [tests/test_live_runtime.py:1155](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1155), [tests/test_live_runtime.py:1422](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1422).  
   Pseudo computed styles expose only `content`, so no row exercises fixed pseudo positioning. Deleting the entire `::before`/`::after` fixed-position refusal survives. A fixed pseudo can consequently escape an otherwise valid exterior clip and paint over the movie. Independently deleting the witness’s namespace, display, outline, border-image, reflection, or vertical-overflow check also survives.  
   **Exact fix:** support pseudo-style records on exterior nodes; add fixed-before/after negatives below and on the witness, with non-fixed positives. Add isolated witness negatives for those predicates, including non-HTML `div`, `display:inline`, and hidden-X/visible-Y overflow. Complete §10.3’s remaining exterior rows and require each isolated guard-removal mutant to fail.

3. **Minor — CLASS: edge case (terminal alpha pixel)** — [tests/test_live_runtime.py:1447](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1447).  
   Changing `j<d.length` to `j<d.length-4` survives: the “last row” case tests that row’s first pixel. A transparent final backing pixel is then admitted, contrary to reviewer brief 9.  
   **Exact fix:** add `alphaAt=952*268-1` (`255135`), `alphaVal=0`, requiring rejection and the complete readback trace. Independently demonstrated: current code rejects this row; the mutant admits it.

4. **Minor — CLASS: edge case (fractional horizontal origin)** — [tests/test_live_runtime.py:1453](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/tests/test_live_runtime.py:1453).  
   Only a fractional Y origin is tested. Removing `||R.left%1` survives, admitting an unsupported horizontally fractional stage.  
   **Exact fix:** add an X-only fractional-origin row, such as `off=[0.5,60]`, `viewport=[1921,1200]`, requiring rejection before candidate processing. Current code rejects it; the mutant admits it.

Verified: D1 is exactly **10,195 bytes including boundaries**; on/rendering/off pins match. Planner inputs reproduce **47 admissions**, committed inputs **55**. `lowerTransparency` correctly targets the new backing. DSK7 movie 2 correctly snaps to `1068−799=269`; redraws match canvas coordinates. Construction, census, deck results and four Node syntax checks pass. Earlier proxy, movement, placement, call-site and clock protections persist; both prior detach/reparent mutants are caught. **No pytest run; suite tallies remain implementer evidence.**

**CHANGES REQUIRED**