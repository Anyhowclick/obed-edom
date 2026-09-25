# Hand-back geometry headless gates r1 (2026-09-25, W4)

Plan `.agents/plans/keynote_live_handback_geometry.plan.md` rev 2, §5 item 5. The code under test is `7cd51e9f` (R6–R8 in
`live_runtime.py`). `src/` was unchanged through `7b260aa6`, which only touched `mm_handback_score.py`. The runtime sha was
`e9338aff…`. Fixtures (main checkout): P2 `output/p2-recovery/html-adversarial` (symlinked) and `output/p2-binary`.
Evidence: `output/evidence/handback-geometry/w4/`, with `batches.txt` in each subfolder (time, `uptime` and the Chrome
count before each run). Each run used one fresh headless Chrome and ran serially. Load averages were 15–76, since other
agents were active.

**Verdict:** host continuity, V/Voff/Vgl and paint oracle PASS, P2 fast/slow 14/14. The fast-advance bracket behaves as
stock. There is **one fix-attributable red**, on the P2 bridge-off arm (below): R8's extra preload delays the first
slide-3 observation by ≈ 0.15–0.25 s. Isolation pins it on R8.

## Gates

| Gate | Verdict | Key numbers |
|---|---|---|
| HB-1 ×3 viewports / HB-2 (cited, `hb-probe-r1/verdict.json`) | PASS | on/on2 max 0 / 0.018 / 0.005 px (1920/2560/1600); KB off 2.78 / 3.74 / 2.42; HB-2 on 0, off 2.79 |
| Host probe ×3 viewports (`host/host-*.json`) | PASS | `mmOpacity.mode` on. A/B/C/attach verdict sets == baseline (`loop-gates/l4-final`, `mmo-gates/round-7c20dde4`) at 2560/1600/1920. V and Voff: slides 1–4 all True |
| Host probe `--gl-replay auto` 1920: Vgl + paint oracle (`host/hostgl-1920x1080.json`) | PASS | Vgl slides 1–4 True. armedSlide: inpageLive, pausedDead, screenshotLive, masked, noPainting all True. Hand-back parity maxOutside 0. liveRing max 0 (n 4740 == glc r2). In-page oracle True on slide 2 |
| P2 fast (`p2/`) | PASS 14/14 | `mmOpacity` true. Non-GL arm (`--disable-gpu`): `mmPatchExercised` false. deliberateRestart2to3 earliest slide-3 t 0.262 s (history 0.11–0.16) |
| P2 slow | PASS 14/14 | Same; t 0.294 s (history 0.09–0.15) |
| P2 bridge-off (negative arm) | **FAIL (fix-attributable)** | Expected: only `continueThroughMovingMagicMove3to4` False. With the fix, `deliberateRestart2to3` and `preserveDidNotBlockRestart` also go False, in 3 of 6 fix-on runs; 0 of 3 stock; 0 of 2 R1–R7 (R8 dropped) |
| P2 GL arm `--gl-replay auto` fast, full vs R8-dropped, interleaved (`p2gl-r2/`, reports + `runs/` copied) | PASS 14/14 ×4, margin eroded | `mmPatchExercised` true. t full 0.212 / 0.330 vs R8-dropped 0.139 / 0.139 (load 12–30) |
| Fast-advance bracket (`fastadv/`) | PASS (as stock); engagement not guaranteed | See below |

## P2 bridge-off red: root cause

- **Interleave** (`p2/`, `p2i/`, `isolate/`; fast profile, `--disable-bridge34`). First slide-3 observation of movie1
  (`t`, the scorer needs < 0.35 s):
  - fix on: 0.360, 0.364, 0.413, 0.298, 0.302, 0.278;
  - stock (`--mm-opacity off`): 0.219, 0.123, 0.109;
  - R8 dropped (`isolate/drop_r.py`, in memory, patched sha `3730d38e…` vs full `e17264c0…`): 0.101, 0.119.
  - History (9 earlier bridge-off reports, including MMO R1–R5 on): 0.10–0.18.
- **Mechanism.** The restart itself is fine: `firstAfterClick` is 0.02 s in both arms. The first `#7` (slide 3) sample
  simply arrives ≈ 0.2 s later relative to the restart. When `t` crosses 0.35 s, the scorer finds no near-zero decoder at
  the boundary (`restartDecoderId` None, `firstSeenAtBoundary` False). `preserveDidNotBlockRestart` then fails because it
  needs that decoder.
- **Cause.** R8 makes `preloadTextures` also load scene B+1. In P2, at scene #6 (the last build of slide 2) stock loads
  #7 (slide 3). R8 also loads #8 (slide 4, the 3→4 MM destination), so slide 4's pdf.js render moves from after
  slide-3 arrival into the 2→3 dissolve. This is plan §3.4's "R8 timing" risk (critique finding 8), observed. It was not
  measured on the page's main thread; the inference comes from the preload order.
- **Scope.** The same shift appears in the GL arm (real WebGL): 0.21 / 0.33 with the fix vs 0.14 / 0.14 without R8. So it
  is not a `--disable-gpu` artefact. It fails outright in the non-GL arm (`--disable-gpu`, software raster), where the MM patch itself never paints. The
  bridged fast and slow arms still pass, but their margin to 0.35 shrinks from ≈ 0.2 s to ≈ 0.06–0.09 s.
- **Decision for the owner.** Plan decision 3(b) scopes R8 to "next scene is an MM transition", which would not preload
  at #6 → #7 (a dissolve). The alternative is to accept it and re-baseline the P2 threshold. Not changed here: W4 makes no
  product edits.

## Fast-advance bracket (`fastadv/fast_advance.py`, `output/p2-binary`, 1920)

Each arm runs these steps in order:
- show, then advance immediately. The advance lands at movie t ≈ 0.05 s, i.e. dwell 0 after decode;
- a queued double Space (b1 + b2);
- b3;
- a queued double Space (d23 + mm34, the second press landing mid-dissolve);
- goTo 1, then advance immediately;
- goTo 3, then goTo 2.

The arms were GL off and GL auto, each on (`auto`) vs stock (`off`).

- **Navigation / go-to.** The hash sequence is identical on vs off in both GL modes: `#2 #4 #5 #9 | #1 #2 | #7 #2`.
  Queued presses coalesce as stock (b1b2 → `#4`, d23mm34 → `#9`).
- **Continuity carry.** The preserve-event kind counts are identical on vs off (GL off: 11 kinds; GL auto: 17 kinds,
  including `glreplay-arm/hold/release/standdown`). The G2 end state is `RETIRED` with standDowns `[assetUnbound]` in
  both arms, after the go-to walk. This is not fix-related.
- **Errors.** 0 page exceptions, 0 console errors or warnings, 0 `player-build-error`, 0 logger errors, in all 8 runs.
- **Engagement** (`obedMix` setter trap, leaf textureIds):
  - Advance at dwell 0: **not engaged** (no `obedMix`, max blended draws 1 == stock). The 1→2 move and its settle are
    stock (old geometry).
  - The same page after goTo 1 → advance: engaged on exactly {`1FDCDA05…`, `8F325ED2…`}, blended 3 (= 1 + 2).
  - Dwell sweep 0.25 / 0.5 / 1.0 / 2.0 s: engaged every time.
  - Engagement is all-or-nothing per move: R6 runs at effect build, so there is no mid-move step. This matches critique
    finding 3. An operator who advances within ≈ 0.25 s of slide-1 arrival gets today's geometry, not an error.
  - The queued d23 + mm34 has no affected leaves (census), so no `obedMix` is expected, and none appeared.

## Discarded runs

`p2gl/` (17:41–18:06) is **void**. A peer session's concurrent P2 `--gl-replay auto` run shared the fixture tree
(`gl-replay/runs`, `report.json`) around 18:00, and the first loop also copied a stale `report.json`. Those runs were
re-run as `p2gl-r2/` with no other P2 process running (`p2procs=0` in `batches.txt`). The non-GL P2 runs (`p2/`, `p2i/`,
`isolate/`) all ended by 17:36, before the collision. They write to the fixture root, not `gl-replay/`. The last W4 P2
run ended 18:19:44.

## Not run / out of scope

- `mm_opacity_probe.py` (MO gates): W3's item.
- Full suites.
- Managed OBS (owner-authorised session only).
- `managed_obs_qualify.py`: another agent's file, neither touched nor run.

## r2 (decision 3b) — `0bb21fcc`, served sha `574274e8…`

R8 now preloads only when the event about to play is a Magic Move. `src/` is clean at `0bb21fcc`. Evidence is in
`output/evidence/handback-geometry/w4/r2/`, with `batches.txt` (time, `uptime`, Chrome and P2 process counts).

### Non-P2 items (done)

| Gate | Verdict | Key numbers |
|---|---|---|
| Fast-advance bracket, fix vs stock (`r2/fastadv/`, `output/p2-binary`, GL off, 1920) | PASS | See below |
| Host probe 1920, fix on (`r2/host/`, item 4, host part) | PASS | Arm A and attach `continue3to4` True; B/C False, as baseline. A/B/C/attach verdict sets == r1 and history. V and Voff slides 1–4 True |

- **Engagement (dwell 0.5 s).** The fix blends exactly {`1FDCDA05…`, `8F325ED2…`} at 1→2, with max blended draws 3; stock
  shows none and reads 1. The fix engages again after goTo 1 → advance.
- **Dwell 0.** With an immediate advance the fix does not engage (blended 1), as in r1.
- **Everything else identical to stock:**
  - hashes `#2 #4 #5 #9 | #1 #2 | #7 #2`;
  - preserve-event kinds, 11 kinds with the same counts;
  - 0 page exceptions, console errors or warnings, player build errors and logger errors in all 3 runs.
- **Served shas.** `on` 574274e8…, `off` 7cf00b56….

### P2 items (pending the P2 slot hand-off)

Pending: bridge-off (fix ×6 interleaved with stock ×3), fast/slow, GL fast (2 fix + 2 stock), and the 3→4 freeze bracket.
