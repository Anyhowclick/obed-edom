# Handover — Alpha Keynote live continuity, state at 2026-09-22 (evening)

Supersedes `keynote-live-continuity-2026-09-22.md` (removed 2026-09-23; in git history). Owner rules unchanged: no merge without an
explicit request; Opus plans / Sonnet implements / Codex reviews; hands off Keynote unless told it is free.

## Where things are (verified after #200 merged, `7b826f13`)
| Item | State |
|---|---|
| `main` | #196 paint oracle, #198 DSK correctness, #199 picker host, **#200 GL-replay opacity offline half** merged 2026-09-22. |
| Full suite | `uv run pytest tests/ -n auto --dist loadfile` ≈ 95–120 s; 5454 passed, 89 skipped, 1 xfailed on the #200 tree with the real export symlinked. |
| Worktrees | `gl-opacity-offline` removed after merge. `go-to-autoplay-fix-719a2e` belongs to another session (13 uncommitted files, nothing past main) — do not touch. |
| Fixture | Durable P2 fixture = MAIN checkout `output/p2-recovery/html-adversarial` (git-ignored). **Symlink it into any worktree** (`output/p2-recovery/html-adversarial`) or the real-export tests SKIP silently — run with `-rs` and read the skips. |
| Owner decks | `~/Desktop/Convert wall to 16x9 CGs/Positive Control.key` (4 slides) and `Minimal Alpha_DSK.key` S4–S9. HTML exports in MAIN checkout `output/gl-decks/<deck>/html/` (git-ignored). Re-export with `obed_edom.html_preview.export_html` (strictly serial; Keynote must be closed; a documentless Keynote may linger between batches — `count documents` == 0 ⇒ quit it). |
| Research evidence | `output/gate-runner-archive/{research-harnesses,requal-paint-oracle,run_gates.sh}` (git-ignored, 2.0 GB). |

## GL-replay opacity fix — stage G2, offline half SHIPPED (#200)
Plan `.agents/plans/keynote_live_gl_replay_opacity.plan.md` rev 2; owner accepted decisions 1–5 (arithmetic blend
reference over a READ background + α=0 identity control; patch on air — it REMOVES the build-1 pop; tolerance = settled
leaf rect / MVP ≤ 1 px / ablation ≤ grid+2 px; additive behind `OBED_LIVE_GL_REPLAY`; green ROI → `{800,690,330×90}`).
Shipped: `_check_effect_encoding` (one recursive schema of validator combinators; unmeasured ⇒ refuse) and
`effect_opacity_overrides(effect)` in `live_continuity.py`; sanitized fixture `tests/fixtures/live_continuity/effect_1_to_2.json`.
**Not wired**: `derive_plan` has no `glReplay` action, `to_runtime` untouched, `QUALIFIED_PLAN_SHA256` untouched.
P2 fixture 1→2 ⇒ one override (slot 4, α = 0.29468628764152527, 178×157), slot 1 excluded `fade`.
Review trail: two Fable peers (plan critique; 36-mutation coverage verdict = ACCEPT) + four Codex rounds; further rounds
should be gated on a SECOND measured deck, not more mutations of this fixture.

## Deck status (arming plan §6 Q4, all checked offline via `derive_plan` on the exports)
(i) `Minimal` S4→S5: `pin`; destination Start Movie = **On Click** (Keynote always emits a Start Movie build, so "no
events" is not authorable; After Transition exports as an automatic first event and heals the window like 3→4).
(ii) S6→S7: both movies at identical rects, `pin` per movie; opacity computation refuses on unmeasured `transform.rotation.z`.
(iii) S8→S9: two movie objects at the identical rect on both slides ⇒ **measured refusal** (`ambiguous ownership … 4
geometry-equal pairs`), which is a whole-deck refusal — gate 4→5 / 6→7 as sub-decks with the rest skipped.
(iv) MOOT — Keynote cannot mask movies; a generator "mask" is a pre-cropped file with a plain rect.
(v) `Positive Control`: `pin` / `bridge` / `restart`, no refusals.

## Next (owner: another agent takes G1 then G2)
- **G1** (`live_continuity.py` + tests): `glReplay` derivation per arming plan §2 (WebGL-listed effect; exactly one
  carried movie, geometry-static; destination first event click-driven; no mask/vocabulary refusal), call
  `effect_opacity_overrides` for `opacityOverrides`/`slotSizes`/`slotRects`, `fallback: "retire"`, `to_runtime` guards
  mirroring `retire`, **replace** `QUALIFIED_PLAN_SHA256` + P2 injected plan + pinned literal in one commit,
  `CONTINUITY_VERSION` stays (G3 owns 4→5). Fixtures: P2 1→2 ⇒ glReplay with the slot-4 override; decks (i) glReplay,
  (ii) refuse (two movies), (iii) refuse (ambiguous). Add the operator warning follow-up (arming plan Q4 note): carried
  movie whose destination Start Movie is After Transition ⇒ validation warning; the DSK generator should set the build
  start itself.
- **G2** (`live_gl_replay_js.py`, new): wrapper/recorder/marker swap/rVFC loop/stand-down per arming plan §3–§4, plus
  opacity plan §2 runtime half (ARM-POST proofs, rest-Opacity == 1.0, per-draw `uniform1f` inside the `replaying`
  counter, `progOpacityBefore` write-back, `contextLost` exemption, `glreplay-opacity-unproven` notes,
  `GL_REPLAY_VERSION`). Gated on Q3 (20-min long-run, context loss injected — NOT measured) and Q0b at n = 2 headless only.
  Must publish `window.__OBED_GL_ORACLE__` (as built in `src/obed_edom/live_gl_replay_js.py`).
- Then G3–G6 per the arming plan; green-ROI relocation (O4) needs the composited margins re-measured in the patched state.
- Still open elsewhere: go-to autoplay (in flight in the other worktree) · `instanceCheck.painting` 1↔2 on slide 3 ·
  freeze-control fixture refresh (owner-gated) · DeckLink venue test 2026-10-10.

## Lessons this round
Enumerated fail-closed checks did not converge over three Codex rounds; one recursive schema + one accumulated
geometry budget + `except Exception` closed the shape class in one round · an implementer reported skipped real-export
tests as passing — always `-rs` and read the skips · measure the export FORMAT before planning a proof (animation keys
were `property/from/to/fillMode`, not `keyPath/fromValue`) · half of Q4's decks were written for shapes Keynote cannot
author · `osascript tell application "Keynote"` LAUNCHES Keynote; `pgrep -x Keynote` first, and quit a 0-document stray.
