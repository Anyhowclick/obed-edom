# Hand-back geometry: Opus review r1

2026-09-25. Branch `claude/mm-handback-geometry` @ `2abfd233`, diff `0df5ea10...HEAD` (6 commits). The local `main` ref is
stale (`b4d62152`), so the review uses the SHA. Read-only. No headless Chrome was started (3 were already running, which is
the cap). Player `e9b2fad4…`.

## Verified

- **R6–R8 against the real bytes.**
  - All three anchors sit at the cited offsets and are `count == 1`. R7's `var T=` extension is sound: `}}` closes the
    switch and the loop, and `C` is the loop's own `var`.
  - `node --check` passes on both `patch_player` and `patch_rendering` output.
  - 5b is exactly `1===sx&&1===sy&&(ok=!1);`.
  - `mm_opacity=False` is still `7cf00b56…`, i.e. hook only.
  - MMO∘HB == HB∘MMO on the real and the synthetic player.
- **Scope.**
  - The free names in `__obedHandbackTextures` are `R`, `UC` and `Math` only.
  - `R` is the module GL util (`setupTexture` uses it itself).
  - `UC` is the module-level `let … UC=null`, set by `UC=new Eg`, so it resolves in `patch_rendering` too.
  - The inner `W(...)` call resolves to the named function expression, not to the hoisted `var W`.
- **`this.textureAssets`.** It is `slideCache[this.slideIndex].textureAssets` (`animateEffect`, byte ≈2316555).
  `unloadTextures` deletes an evicted entry outright, so a cleared canvas can never be matched.
- **`catch(E){}` fails closed.** `toTexture` and `obedMix` are set in one comma expression, per leaf, and nothing can throw
  between them. A throw leaves the leaf (or the rest of the effect) on stock behaviour, never a half-set leaf.
- **Stale `obedMix` cannot happen.** `textureInfoFromEffect` builds a fresh `var e={}` on every `setupTexture`.
- **Destination not rendered yet.** `textureAssets[id]` is assigned only in the render-promise and image-load callbacks,
  and the `D.textureAssets[m[0].t]&&` guard keeps the leaf stock.
- **R8.**
  - `B+1<A.numScenes` guards stock `loadScene`'s off-by-one (`A>g.numScenes`), so no `slideCache["undefined"]` entry is
    created.
  - `requestPdfDocument` dedupes via `requested`.
  - No callback handler is touched.
  - The retention window is unchanged in both `tg` and idle.
- **Preview.** `preview_player` patches at serve time, so no stale patched cache survives the upgrade.
- **Instruments: HB-1 and HB-2.**
  - A KB that does not fail reads INCONCLUSIVE, and so do a CvC, null or shift drift and integrity/premise/engagement
    breaks.
  - No page-computed verdict is scored.
  - The `Object.prototype` trap is non-enumerable and changes no player path.
- **M3 re-cast.** It is sound. The enforced edge check G2-S = G2-P3 now covers both opacity and geometry, and the new KB
  (G2-P3 vs stock-geometry opaque×0.2947) proves that the band sees the 2–2.8 px shift.
- **MO-4 `ROI_TOP` move to x ≥ 797.** It hides no regression: the stock ramp ends at about 794.2, and the edge is now
  gated by HB-2.
- **HB-OBS.** It is `enforced=False` and runs inside `handback_geometry_safe`, so it cannot change a verdict or fail a take.
- **Tests (spot-run).**
  - runtime + handback + probe: 158 passed.
  - qualify + mm_opacity_probe: 251 passed, including the REAL pre-fix recording test.
  - preview/host/api/adversarial/continuity-probe: 1386 passed.
  - No skips.

## Findings

| # | Sev | Class | Where | Finding | Fix |
|---|---|---|---|---|---|
| 1 | minor | new-class | `scripts/mm_handback_probe.py:69`, `:368` | HB-2 pins the on-arm G2 `frameLen` 96 as a FAIL check, but the off-arm pin was dropped for a mechanism that applies to both arms. The player's `setGLFloat` (byte 2187031) queues a uniform write only when `setProposedGLfloatValue` flags `_needsUpdate`, so the settle frame's call count depends on whether the previous frame had the same percent. That is confirmed in the bytes; it is not just "likely". A timing artefact can therefore FAIL a blocking gate. | Report `frameLen` on both arms. Engagement is already proven by `mixTextures`, `blended12` and unproven `size`. Say in the docstring that the variance comes from uniform caching. |
| 2 | minor | edge-case | `scripts/managed_obs_qualify.py:1373` | Engagement is asserted on `g2-on` only. `g2-on-2` feeds the enforced MO-2 CvC R2 check (:1350–1353) without that assertion, and `g2off-on` (patch on, G2 off) has no engagement signal at all. That breaks plan §3.4's rule that no non-engaged run is read as a twin. | Run `handback_unengaged` over every patch-on G2 session (`g2-on`, `g2-on-2`) for MO-2 and MO-4 INVALID. State in the docstring and SKILL that `g2off-on` engagement is unasserted under OBS. |
| 3 | minor | edge-case | `scripts/mm_handback_probe.py:420–421`, `:513–521` | `overall` reads PASS on a partial set: one viewport with `--viewports`, or no HB-2 with `--gl off`. `load_runs` also merges every `runs/*/record.json` in a reused `--out`, so arms served by an older build can be scored together with new ones. | `overall` INCONCLUSIVE unless HB-1 × 3 viewports and HB-2 are all present. Add a premise that each record's `output.mmOpacity.sha256` equals the current `patch_player(stock, mode)` sha. |
| 4 | minor | edge-case | `scripts/mm_handback_probe.py:482–483`, `measure_run` | The on-arm `mm12` shot cannot tell "GL settled on DOM geometry" from "slide-2 DOM already visible" (an R5 or continuity regression). With the fix both read 0, and the KB runs on different (stock) bytes. | At the `mm12` shot, read in-page that the MM canvas is displayed and the swapped DOM node is hidden; otherwise INCONCLUSIVE. |
| 5 | nit | edge-case | `src/obed_edom/live_runtime.py:25–29` | The destination walk ignores an ancestor's `hidden` and the leaf's `rotation`, `scale` and `affineTransform`. A hidden-ancestor or transformed leaf with a coincident rect could match. The census has 0 such leaves, and the result is fail-soft at worst. | Carry `h\|\|t.hidden` down the walk. Push only when `0===t.rotation&&1===t.scale`. Mirror both in `_destination_leaves`. |
| 6 | nit | closed-class | R6 `R.createTexture` | Each MM setup adds one GL texture that is never deleted. The stock player has no `deleteTexture` at all, so it leaks its own `texture`/`toTexture` the same way, bounded by the fB context. | None; note it in plan §3.4. |
| 7 | nit | edge-case | `live_runtime.py:26`, `:36` | `W` names both the named function expression and `var W`. It is correct but fragile. | Rename one (re-pin the shas). |
| 8 | nit | doc | plan §3.2/§3.3 | The plan still shows R7's old anchor and the old served shas (`ba709b7a…`/`1c779a82…`); the tests pin `e17264c0…`/`5797b302…`. | Add an "as implemented" note: the R7 anchor, the 5b shas, the tuple name kept, and off-arm `frameLen` reported only. |
| 9 | nit | doc | `README.md` hand-back paragraph | The operator guide states G2 developer baselines (`frameLen` 96, unproven `size`) as fact, while SKILL calls `frameLen` timing-dependent. | Drop them from the README (SKILL already has them), or qualify them. |
| 10 | nit | dup | `src/obed_edom/mm_handback_score.py:207–208` vs `tests/test_live_runtime_handback.py:_destination_leaves` | Two mirrors of the same player walk with different rounding: Python's banker's `round` vs `_js_round6`. `layer_rects` keys by texture id, so duplicate ids drop silently. | Share one JS-round helper. |
| 11 | nit | style | `scripts/mm_opacity_probe.py` (`STOCK_BLENDED` `#:`), `managed_obs_qualify.py:1738` | New `#:` comment in a file that had none, and prose inside a `noqa`. | Drop both, or keep them to the local idiom. |

UNVERIFIED (gates-r1 or OBS):
- MO-2 R1/R2 with the mid-move blend inside ROI_top on OBS;
- R8's earlier pdf.js render against cadence;
- HB-1 CvC at 1440/1600;
- whether on-arm `frameLen` is stable across runs.

## Verdict

**Ready after fixes.** No blocker or major finding. The product bytes (R6–R8) are correct and fail closed. Fix 1–3 before
merge, because they are instrument soundness. 4 is cheap and recommended. 5–11 are optional. The merge is still gated on
gates-r1 and the owner's eyeball (decision 8).

## r2 (2026-09-25)

Scope: `git diff 685e046f..HEAD` (`d0c43e71`, `0bb21fcc`) and the r1 folds `572d1fbf` (W3) and `7b260aa6` (W2).
Read-only; no Chrome started. The affected suites (runtime, handback, probe, qualify, mm_opacity_probe) pass: 422 passed.

### r1 findings

| r1 # | Status | Evidence |
|---|---|---|
| 1 frameLen pinned in HB-2 | closed | `G2_EXPECTED` no longer pins `frameLen`. It is reported on both arms, and the docstring gives the `setGLFloat` cause. |
| 2 engagement only on `g2-on` | closed | MO-2 is INVALID on `g2-on` or `g2-on-2` unengaged. `g2-off`/`g2off-on` are documented as unchecked in the docstring and SKILL. |
| 3 partial set / stale runs PASS | closed | `score_all` returns INCONCLUSIVE with `missing` unless HB-1 × 3 and HB-2 are present. Each record's served sha must equal today's `patch_player` output for its mode. |
| 4 GL vs early DOM | closed, UNVERIFIED live | Both mm12 shots read `0-canvas` shown and every swapped node hidden. The `nodeToSwapId` trap works because the player *assigns* it (`C.nodeToSwapId=E`, byte 2312953; `B.nodeToSwapId=I`, 2314304). `MM12_CANVAS = "0-canvas"` is not yet confirmed in Chrome; a wrong id reads INCONCLUSIVE, never PASS. |
| 5 walk ignores ancestor hidden / transforms | open (nit, optional) | Unchanged. |
| 6 texture per setup | closed-class, no action | — |
| 7 `W` reuse | open (nit, optional) | Unchanged. |
| 8 plan anchor and shas | partly closed | The R7 anchor is recorded. The plan's shas (`e17264c0…`/`5797b302…`) and its §3.2 R8 row are stale again after `0bb21fcc` (see r2-2). |
| 9 README baselines | closed | The README now says `frameLen` is timing-dependent. |
| 10 rounding mirrors | closed | `layer_rects` uses player rounding. |
| 11 comment style | closed | The `#:` lines are gone and the `noqa` is bare. |

### New R8 (decision 3b), checked on the real bytes

- **Which event is read.** `preloadTextures` resolves `B` as the current scene in `IdleAtInitialState` and the next scene
  in `IdleAtFinalState` (`tg` = "IdleAtFinalState", byte 2336406). In both cases that is the scene whose event the next
  advance plays: `playCurrentScene` renders `script.events[sceneIndex]` (≈2355081). So `A.events[B]` is the event about to
  play.
- **Loop wrap.**
  - In `IdleAtFinalState` at the last scene, `B` wraps to 0, and R8 loads scene 1's slide only if `events[0]` is an MM. It
    is harmless.
  - The last→first MM itself (`IdleAtInitialState` at the last scene) is never preloaded, because `B+1<numScenes` is
    false. It stays stock, which is fail-closed and as §3.4 describes.
- **Names.** `var M,N` are function-scoped locals of `preloadTextures`. The rest of the method references neither, so
  shadowing a module-level `M`/`N` has no effect.
- **Odd data.** A missing event, empty `effects`, a non-MM first effect or a negative `B` all fall through to the stock
  load only. The one exception is a missing `A.events`, which would throw inside `doIdleProcessing` and drop the queued
  action. The player's own code iterates `script.events` unguarded, so this is unreachable on a real script.
- **Node tests.** They exercise the real method: `_cut(player, "preloadTextures(){", "unloadTextures(){")` is taken from
  the hooked, patched and rendering bytes. They cover the full P2 state × scene grid (only
  `(FINAL,0)`/`(INITIAL,1)`/`(FINAL,6)`/`(INITIAL,7)` gain a load), stock equivalence with `mm_opacity=False`, the last
  scene, the loop wrap and `B=-1`. `tg` is stubbed with the player's literal value.

### r2 findings

| # | Sev | Class | Where | Finding | Fix |
|---|---|---|---|---|---|
| r2-1 | nit | edge-case | `src/obed_edom/live_runtime.py` R8 | `A.events[B]` throws if `script.events` is missing, inside `doIdleProcessing`, before the queued action runs. That is unreachable with real scripts. | Optional: `var M=A.events&&A.events[B]`. |
| r2-2 | minor | doc | plan §0/§3.2 (R8 row, line 170), §3.4 "R8 widens preloading for every slide", served shas (line 206); SKILL line 755 "R8 preloads one scene ahead" | These still describe the 3a bytes and the old shas. The tests now pin `574274e8…`/`fd811938…`. | Update the R8 row, the §3.4 risk bullet, the shas, and SKILL to "preloads the next slide only when the event about to play is a Magic Move". |
| r2-3 | note | edge-case | R8 | An automatic-play MM that is chained without an idle stop is never preloaded, so it stays stock (fail-closed). That was equally true under 3a. | Mention it with the queued-advance case in the README and SKILL. |

UNVERIFIED (W4):
- the `0-canvas` id and the swap read in live Chrome;
- P2 bridge-off green again under 3b. Slide 4 still renders while idle on slide 3, before 3→4, and overlaps slide 3's
  playing movie.

### r2 verdict

**Ready after r2-2 (docs).** No correctness finding in the new R8. r1 findings 1–4 are closed. Merge stays gated on W4's
gates (P2 bridge-off, HB-1/HB-2 with the swap premise) and the owner's eyeball.
