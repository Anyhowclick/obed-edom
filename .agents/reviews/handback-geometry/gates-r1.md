# Hand-back geometry headless gates r1 (2026-09-25, W4)

Plan `.agents/plans/keynote_live_handback_geometry.plan.md` rev 2, §5 item 5. The code under test is `7cd51e9f` (R6–R8 in
`live_runtime.py`). `src/` was unchanged through `7b260aa6`, which only touched `mm_handback_score.py`. The runtime sha was
`e9338aff…`. Fixtures (main checkout): P2 `output/p2-recovery/html-adversarial` (symlinked) and `output/p2-binary`.
Evidence: main checkout `output/evidence/handback-geometry/w4/` (reports, logs, `batches.txt`; raw P2 `runs/` not retained), with `batches.txt` in each subfolder (time, `uptime` and the Chrome
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

### P2 items (slot handed over by the peer; run serially 18:31–19:12)

Before every launch `pgrep -f p2_recovery_html_adversarial` was empty. Each report and `runs/` was copied out right after
its run. All runs used `--reuse-export --disposable`. Load averages were 9–58.

| Gate | Verdict | Key numbers |
|---|---|---|
| P2 bridge-off, fix ×6 interleaved with stock ×3 (`r2/p2-nobridge/`) | PASS (red fixed) | Every run is False only on `continueThroughMovingMagicMove3to4`, the negative arm. Slide-3 restart clock t (limit 0.35 s) below |
| P2 fast / slow, fix (`r2/p2/`) | PASS 14/14 each | t 0.146 / 0.137 (r1: 0.262 / 0.294) |
| P2 with GL replay on, fast, 2 fix + 2 stock interleaved (`r2/p2gl/`) | PASS 14/14 ×4 | Fix `mmPatchExercised` true, stock false. t: fix 0.116 / 0.137, stock 0.098 / 0.129. Margin to 0.35 ≥ 0.21 s (r1 fix: 0.212 / 0.330) |
| 3→4 freeze bracket + slide-3 playback | PASS | `freezeControlCaughtByCounter` verdict `pass` in fix fast/slow and both GL fix runs, and also in both stock GL runs. `continueThroughMovingMagicMove3to4` True in all 6 bridged runs. `deliberateRestart2to3` True, with progression, in all 15 runs. In bridge-off the bracket reads `skipped` ("bridge disabled"), which is by design and non-blocking |

Slide-3 restart clock t in bridge-off:
- fix (574274e8): 0.122, 0.113, 0.118, 0.094, 0.119, 0.145. Median 0.118, max 0.145;
- stock (7cf00b56): 0.120, 0.160, 0.099;
- r1 for comparison: fix 0.28–0.41 (3 of 6 over the limit), stock 0.11–0.22, R8 dropped 0.10–0.14;
- history: 0.10–0.18.

With 3b, the fix sits inside the stock and R8-dropped band, so the r1 shift is gone.

**r2 verdict:** every headless gate passes at `0bb21fcc`. The only P2 finding is `continueThroughMovingMagicMove3to4`,
the expected red of the negative bridge-off arm. The preload now fires at slide-3 idle, before the 3→4 Magic Move, and
leaves the freeze control, the 3→4 carry and slide-3 playback unchanged. The last W4 P2 run ended **19:12:37**.

## OBS r1 (owner go 2026-09-25, managed OBS, PR head `ad13d8a3`, binary fixture `output/p2-binary`, quiet machine: load ≈4.5, no headless Chrome)

| Gate | Verdict | Key numbers |
|---|---|---|
| `--arm mmo` 25 + 30 (MO-2, MO-4, HB-OBS report) | PASS both rates | HB-OBS max \|DOM − GL\|: patch on (g2-on, g2off-on, CvC g2-on-2) 0.029 px at both rates; patch off (g2-mmoff, g2off-mmoff) 2.765 / 2.751 px; GL/DOM nulls 0.000. MO-2 CvC 0.0 at both rates; R1 0 frames within τ (KB 50 / 223); R2 4.31 (KB 124.31); R4 0.0 (KB 180). MO-4: CEF `frameLen` 96 on / 88 off, unproven `[{4,size}]` / `[]`, occludedBands 0 / 20, G2 LIVE, no stand-downs |
| `--arm mmo-cef` (MO-3) | PASS | all sessions in CEF |
| `--arm g2 --rate 25` (M0–M4) | PASS | M3 edge re-cast: G2-S vs G2-P3 (DOM) 0 (KB stock geometry 73, unscaled KB 180); `frameLen` 96 |

Recordings: `qualify-home/recordings/mmo-20260925-193948/` (25) and `mmo-20260925-194247/` (30). Runs: main checkout
`output/evidence/handback-geometry/obs-hb{1,2-cef,3-g2}/`. Eyeball copies (H.264, decision 8a): `output/evidence/handback-geometry/eyeball/`
— `…LEFT-thisPR_RIGHT-mainMMOonly…` pairs this PR's `g2off-on` (19-40-35) with main's MMO-only `g2off-on` from the MO-7 take
(`mmo-20260925-143530/14-36-16.avi`; same frame timing, jump at 435), at speed, mm-move stepped 8×, build 1 stepped 8×. The
`…LEFT-fix_RIGHT-stock…` pairs compare against patch off (opaque square), so they mix the opacity fix with this one.
Owner eyeball (decision 8a): PASS (owner, 2026-09-25) — no visible blending/ghosting vs main MMO-only; build-1 snap gone.
