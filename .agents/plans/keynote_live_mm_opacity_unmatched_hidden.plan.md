# Magic Move: keep zero-ancestor source leaves invisible through the held endpoint

**rev 2 after Opus 5.5 high critique r1; r2 (Opus 5.5 high): ready to implement, two lows folded — critique closed** **Owner 2026-10-15: approved rev 2 — go to implementation (Codex GPT-5.6 Sol high implements, Opus 5.5 high reviews).**

2026-10-15 · GPT-6 Astra · Implementation plan. Source review and an in-memory extracted-method probe completed. No product code changed; full suites and rendered gates have not run. Read-only repository: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/inspiring-feynman-06914e`. Evidence: its `.agents/reviews/mm-opacity-unmatched-hidden/investigation.md` and `offline_evidence.json`; exports: `~/Desktop/Convert wall to 16x9 CGs/F2-evidence-2026-10-14/` (`TEX` below).

## 1. Finding and scope

Old F2 slide 3→4, zero-based textured-leaf slots 7/8: source map images at `[568,510,44,50]` and `[652,506,88,59]`, proved constant-zero wrappers, leaf initial opacity 1/hidden false, and constant `opacity 0→0` plus `hidden true→true` tracks. Stock GL loses the wrapper and ignores those tracks. The current patch discards its proved ancestor zero when leaf admission returns unknown, so both draw at Opacity 1 throughout MM and its held endpoint. This is not end-of-track reversion.

Make a **proved effective ancestor zero absorb descendant uncertainty** in the existing chain calculation. Do not infer zero from raw initial state: legitimate F2 slots 10/11 have initial-zero wrappers animated `1→1 both`, hence effective product 1. Unknown ancestry before any proved zero remains unknown. Preserve normal fades, geometry, draw topology, automatic destination-build timing, and all existing patch consumers; no effect-name restriction or general animation/fill evaluator is needed. The shared helper also serves existing shimmer/sparkle paths; the recorded corpus has zero such effects, so make no rendered coverage claim for them.

## 2. Minimal patch and verified draw behavior

In `src/obed_edom/live_runtime.py`, change only the start of `__obedChainOpacity` within `_MM_OPACITY_NODE`:

```js
__obedChainOpacity(X,A){if(null===X)return null;if(0===X)return 0;var B=this.__obedNodeOpacity(A);
```

Keep its remaining return expression, `__obedNodeOpacity`, `__obedFade`, R1–R4, and all timing unchanged. In `tests/test_live_runtime.py`, add the corresponding `if parent == 0: return 0` immediately after `_chain_opacity`'s `parent is None` guard. No leaf predicate, helper, new switch, or per-frame work.

**Zero precedence verified before adopting this rule.** SHA-verified stock players A (`e9b2fad4…`) and B (`17c0c938…`) have identical relevant methods. In the composed current patch, R3 is:

```js
d!==U&&(T=d+(U-d)*K),null!=e.obedOpacity?T=e.obedOpacity:null!=e.obedParentOpacity&&1===e.parentOpacity&&(T*=e.obedParentOpacity),A.setGLFloat(T,"Opacity")
```

All leaf track evaluation, including unequal-endpoint opacity fades, precedes this override. A non-null `obedOpacity=0` selects the first ternary arm; the fade-parent arm is not evaluated. The rest of QB changes matrices, textures and `mixFactor`, with no later Opacity write. R4's static expression is `hidden?0:null!=obedOpacity?obedOpacity:parentOpacity*opacity`, followed directly by the uniform write. Thus every leaf reaching either draw path with the proved zero submits 0, including hidden leaves and leaves whose own fade is accepted or rejected. R1 stores the result and R2 propagates it through unknown middle nodes. A textured root without a proved ancestor retains existing behavior. No escaping drawn-leaf shape was found; no R3/R4 fix is required. This does not promise to make malformed input that already throws renderable.

A revision-time probe used the existing test helpers to execute real extracted setup/QB/R4 code with only the chain insertion applied in memory. Static, unequal `0→1` fade, constant-opacity/hidden pair, and zero→unknown-middle→leaf cases all returned 0 at `PERCENTS=(0,0.5,1)`, on both players and both `patch_player`/`patch_rendering` outputs. This verifies arithmetic, not pixels or canvas lifetime.

Keep the SHA-pinned, count-checked, in-memory replacement mechanism, `mm_opacity` precedence/rollback, and `RUNTIME_VERSION`. Unknown SHA, ambiguous/missing anchors and wrong output pins still raise `LiveRuntimeUnsupported`. Never rewrite exported `assets/player/main.js` in the evidence tree. Recompute on/rendering pins for both players from the full implementation tuple; verify off bytes unchanged **relative to that base**. Preserve draw count/order, textures and bindings; zero the uniform rather than remove leaves.

## 3. Minimal evidence and tests

Extend existing extraction/census tests, with minimal comments and no new framework:

- One compact sanitized real F2 subtree fixture retaining original slots 7, 8 and 10, with its own fingerprint and local slot mapping. On both real players, use `_real_player()`, `_hook_only`, current patched outputs, and existing `PERCENTS`. Original 7/8 change 1→0; original 10 retains its nonzero baseline. Check preview/live agreement and the Python mirror against extracted methods.
- One `SYNTHETIC_TREES` entry: proved-zero wrapper → unknown middle → static leaf and unequal-endpoint fading leaf, both 0 at every sample. This covers zero propagation, R4 and R3 precedence without a mutation matrix. Existing unknown-ancestor, matched and Alpha_DSK fade cases retain their expectations.
- Reuse existing uniqueness, syntax, unsupported-input, and on/off/rendering pin checks for both players. Committed census expectations refer to the new subtree's own fingerprint/local slots, never the full F2 fingerprint.
- Separately run the current-base and candidate mirrors over the corpus plus read-only old F2. Record exactly two changed full-effect leaves, `(f2350147…,7)` and `(f2350147…,8)`, and zero changes in the existing 26-effect/122-leaf corpus. Keep F2 out of `output/`; do not commit the whole deck. The base mirror is the implementation base commit's `_chain_opacity` (without the zero line); the one-off must report exactly the two F2 leaves changed, and 0 changed is INCONCLUSIVE.

Known-bad arms are stock and the **current implementation base's pre-change** `patch_player`/`patch_rendering` outputs on identical data. The inspected B base rendering pin is `c0faaa3c…`; regenerate/record baselines at implementation time. `TEX/F2-html-old-repaired-patched/assets/player/main.js` (`7d9eb308…`) is an immutable one-off provenance check, not the regression baseline. The investigation's `offline_scan.py` hardcodes vanished paths: retain its report as provenance and use current evidence paths for the new one-off scan.

## 4. Gates

Required missing evidence, unavailable GL, wrong fixture/effect or a missed hold/build window is INCONCLUSIVE and blocks promotion. Edited-F2 absence controls are optional: `newexp3` was not retained. The current owner re-export (`F2.key f99a68ef…`, per critique) may be used if available after verifying its identity; its absence does not block a gate.

| Gate | Required evidence and controls |
|---|---|
| **UH-0 methods and pins** | Both supported players, real F2 slice and synthetic tree at PERCENTS; zero for target leaves, matched control unchanged, mirror agreement, expected output pins, off unchanged from base. Stock/current-base reproduce the two nonzero targets. |
| **UH-1 headless F2** | Player B only, because F2 ships B; A differs only outside the anchors and is covered by UH-0. At 1920×1080 with automatic timing intact, exercise `patch_rendering` and `patch_player`, continuity/replay off. Every target draw has effective Opacity 0 and exact before/after target-ROI equality. Stock and current-base arms on the same data must reproduce both contributions and the held artifact. Null controls: candidate repeat and visible siblings 1/10/11 contributing nonzero pixels in the same trace. |
| **UH-2 corpus and existing regressions** | Run once on the composed base: exact offline changed set above, committed subtree census, explicit zero shimmer/sparkle census; existing MO/HB headless and Alpha_DSK PF checks green with established known-bad and fixed-vs-fixed controls. No threshold or expectation rebaseline to conceal failures. |
| **UH-3 Stage B composition** | Re-run only the UH-1 candidate arm with continuity on, on the composed base. Suppression and hold remain correct with effective cached uniforms and hook order recorded. Record actual replay engagement or fail-closed stand-down; do not claim F2 G2 qualification when replay does not engage. UH-2 already covers the qualified P2 GL-on/forced-stand-down and hand-back regressions. |
| **UH-4 owner eye** | Actual product path, old F2 3→4: no small copies during zoom or held endpoint before automatic Malaysia build; main map motion, textures and build unchanged. Saved stock / `mm_opacity=off` reproduces the defect; visible matched pieces remain visible. |

Adapt `mm_opacity_probe.py`'s logger with a small scratch F2 driver, not its hardcoded P2 sequence. Identify targets by texture/program/rect, not ordinal alone; prove nonempty textures in known-bad arms. Record D0, Dlast (completion of the final draw task), removal R, scene identity, automatic build start, frame gaps and effective cached uniforms. Capture RGBA inside draw tasks before default framebuffer contents can be discarded. No derived export/twin is needed.

**Concrete hold oracle, each required arm:** after Dlast and before R, no GL calls occur on the MM context; its canvas remains connected until R; at least one page/compositor capture falls strictly inside `(Dlast,R)`. Candidate target ROIs match its own Dlast GL readback after coordinate/compositing alignment within calibrated candidate-repeat noise. Stock/current-base hold captures retain their own terminal target contributions and differ from the corresponding candidate ROIs by at least the measured known map contribution. Correlate captures to measured timestamps, not a slide label or sleep. No interior capture ⇒ INCONCLUSIVE. Continue coverage through destination build onset; do not alter scheduling to lengthen the hold. Page-level noise must remain decisively below each known-bad contribution; per-target-draw framebuffer equality remains exact.

Reuse `scripts/mm_opacity_probe.py` for MO-1/MO-4/MO-5 including GL-on/forced stand-down; `scripts/mm_handback_probe.py` for HB-1/HB-2; and PF-1/PF-2 Alpha_DSK samples (6→7 slot 3; 7→8 slots 4/8 and stable slot 6). No new OBS qualification or replay feature is part of this fix.

## 5. Work boundaries and Stage B coordination

| Work | Completion |
|---|---|
| **W1 patch + focused checks** | Chain/mirror insertion, compact fixture and existing test extensions, pins; UH-0 and precise changed-set evidence; **full suites (3.13 + 3.10 floor + dashboard `test:ui`/`test:maps`) before every code PR**. |
| **W2 rendered evidence** | Scratch F2 driver and gate report; UH-1/UH-2, measured hold and controls. |
| **W3 composition + review** | Serial integration with Stage B, UH-3/UH-4, final gate record. |

These are later ownership boundaries, not instructions to spawn agents now. Stage B's local `claude/stage-b-implementation` also edits **`live_runtime.py` R12 / `_CONTINUITY_TAKE_ANCHOR` / MM-feed take in `jumpToScene_partFour`, all six pins including off, and `tests/test_live_runtime.py`**, alongside continuity/replay files. This overlap was verified in the branch diff. Neither stream edits the other's replacement or copies stale pins. Expected order: this fix lands on main first and pins against main only; Stage B rebases second. Whichever actually lands second rebases, recomputes all six pins from composed outputs, re-runs UH-0 and the full suites (3.13 + 3.10 floor + dashboard `test:ui`/`test:maps`). This fix's off invariant is relative to its base, not a historical global hash.

Keep continuity retirement/hold timing and replay hooks under Stage B ownership. Install diagnostics so they observe final effective uniforms without perturbing draw topology or recorder state. `proveOpacity` requires `restOpacity===1` for selected override slots: a non-hidden constant-`forwards` leaf newly suppressed under zero could fail that proof and stand down. None is in the recorded corpus; preserve that fail-closed behavior and inspect it in UH-3 if encountered, without adding a speculative fixture or relaxing replay proof. Agree one writer for any shared probe/expectation edit.

## 6. Delivery constraints

Retain only a compact sanitized regression fixture; keep raw evidence read-only and scratch render artifacts outside `output/`. Preserve existing style, minimal NatSpec/comments and tests. No owner question is pending for this revision. Headless evidence, existing regressions, composed integration, full local suites and the later owner visual gate remain the implementation release bar; no CI substitution.

## 7. Acceptance and rollback

Ship only after UH-0…UH-4 and the **full suites (3.13 + 3.10 floor + dashboard `test:ui`/`test:maps`) before every code PR** pass. Record base commit, input/output hashes, exact changed leaf set, per-draw/hold evidence, composition and owner-eye results. `mm_opacity=off` is the byte-identical rollback relative to the implementation base. No renderer fallback, texture repair, scene timer change or evidence-player disk rewrite.

## §8 Critique r1 dispositions

| Finding | Disposition |
|---|---|
| 1 · absorbing zero | **Folded.** Replace leaf admission with chain/mirror zero absorption; real R3/R4 source and both-player extracted probes confirm fades cannot override the final zero. |
| 2 · Stage B overlap | **Folded.** Shared runtime/tests and all six pins named; second stream rebases, composes/re-pins and reruns UH-0/full suites; off relative to base. |
| 3 · absent controls | **Folded.** Edited-F2 control optional; unavailable old re-export is no blocker. |
| 4 · baseline | **Folded.** Stock/current-base outputs are known-bad arms; immutable `7d9eb308…` is provenance only. |
| 5 · UH-1 scope | **Folded.** B-only rendering, no derived twin; repeat and visible siblings 1/10/11 are null controls. |
| 6 · hold oracle | **Folded.** No post-final-draw GL calls, connected canvas, timestamped interior capture and terminal-ROI comparison required per arm. |
| 7 · duplicated gates | **Folded.** UH-2 runs once on composed base; UH-3 repeats only UH-1 candidate with continuity on. |
| 8 · full suites | **Folded.** Explicit in W1, composition and acceptance; required before every code PR. |
| 9 · samples | **Folded.** Existing PERCENTS only; no timing predicate or endpoint-adjacent sample matrix. |
| 10 · fixture census | **Folded.** Commit subtree fingerprint/local slots; record full F2 changed set in one-off offline evidence, outside `output/`. |
| 11 · evidence paths | **Folded.** Use persisted TEX path; stale scan is provenance, not a runnable instruction. |
| r2 low 1 · investigation wording | **Folded** (coordinator): investigation §4 notes the supersession. |
| r2 low 2 · base mirror | **Folded** (coordinator): §3 names the base commit's mirror; 0 changed ⇒ INCONCLUSIVE. |

## §9 Review log

- Plan critique r1 (Opus 5.5 high): 1 major (replace the leaf predicate with an absorbing proved zero), 5 medium, 5 low. All folded in rev 2 (Astra); dispositions are in §8.
- Plan critique r2 (Opus 5.5 high): ready. It independently re-verified R3/R4 precedence and the two-leaf changed set. 2 lows, folded by the coordinator. Critique closed.
- Owner approved rev 2 on 2026-10-15.
- Implementation (Codex GPT-5.6 Sol high): `ab58fdd6`.
- Code review r1 (Opus 5.5 high): approved after 3 lows, folded in `ebe9704d`:
  - the evidence script's base is now explicit;
  - a redundant census loop was removed;
  - the pin history now names the superseded hashes.
- Gates: UH-0, UH-1 and UH-2 PASS, full suites green, owner eye (UH-4) PASS. See `.agents/reviews/mm-opacity-unmatched-hidden/gates-r1.md`.
- Merged as #282 (`2bd0811b`) on 2026-10-15. UH-3 (Stage B composition) is re-run by Stage B on its rebase.
