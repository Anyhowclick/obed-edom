# Dissolve cross-fade — implementation handover (2026-10-12, written before the 02:00 shutdown)

**READ FIRST.** Plan rev 9 `.agents/plans/keynote_live_dissolve_crossfade.plan.md` (owner GO 2026-10-11 22:10, all streams
launched). Branch `claude/keynote-live-dissolve-crossfade` (local only: NOT pushed, no PR), worktree
`.claude/worktrees/brave-goodall-bd9851`. Follow-ups (Q6 bridge/hold, G2 `L`, F2):
`keynote-live-dissolve-crossfade-followups.md`. Raw review rounds: `.agents/reviews/dissolve-crossfade/impl-*.md`.

## State by stream

| Stream | Commits | State |
|---|---|---|
| W0 | `7fa7c8dd` | strip fix `715cb3f1` cherry-picked |
| W4 docs | `571237e2` | README fallback line, SKILL sentence, follow-ups handover (Q/L placeholder still TBD) |
| W1 `live_runtime.py` | `debfc685` + test folds `dc4dad8b`, `2aadd074`, `1091285c`, `8a53c0b9`, `de83681b` | D1–D4 byte-exact to §3.1 (product bytes unchanged since `debfc685`); §8 counts reproduced; **Astra impl r1–r6, r6 APPROVE** (all folds were test hardening: proxy guards on every stub element, real node-move semantics, whole-tree/placement invariants, deep tree compare, call-site spies, full LUT, work clock; 61 mutants caught, two decoded-size mutants accepted as safety-equivalent). 125 passed / 0 skipped. Pins on/rendering: e9b2fad4 `49d56adc…` / `117fd39d…`; 17c0c938 `7a5e315b…` / `52d7edb5…`; off unchanged. **`Q`/`L` provisional** (`_FREEZE_QUALIFIED_TUPLES`, `_FREEZE_TONE_LUT`): swap + re-pin when Q0b's decision record lands. |
| W2 `dissolve_probe.py` | `15dc7d33`, r1 fold `34f4779e` | Astra r1 (13) folded; **Astra r2 on W2+W3: CHANGES REQUIRED** (10: B1 absent inventories → MATCH, B2 incomplete captures satisfy negative controls, M3–M8, m9–m10) — fold in flight at handover time: _see final note_. Tone risk: P2 build-frame canvas `3231B69B` (960×276) covers the movie rect → tone mask empty → `m-tone` INCONCLUSIVE; needs a tone fixture with exposed ramp/patch interiors or a painted-pixel foreground mask (never count covered pixels). no_flash needs a pre-animation rAF on real captures (fail-closed; check at first gate run). |
| W3 `managed_obs_qualify.py --arm dissolve` | `47135f64` (+ CEF profile switch in `34f4779e`) | 19 CEF sessions, calibration from `opaque-off` first; reviewed with W2 in r2 (M7 cut-shot timing interval, m9 cached calibration) — folded by W2's agent. |
| Q0b step 0 | evidence only | headless done, CEF pending; **five re-plan triggers** (below) |

## Q0b results (headless Chrome 154; evidence `output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/README.md`)

Bytes: rev 9 rebuilt from `dpatch12` = §3.1 = W1's code. Every timed run at 1-min load < 4 (others in `discard/`, not copied).
Resume state (drivers, analysers, builds, DSK H.264 copies): session scratch `.../scratchpad/q0b/` (lost at reboot if /private/tmp
is cleared; the evidence copy has the scripts and decision JSON).

- **Decision record (Q0b 1), headless only:** decoded tuple `bt709/bt709/bt709/false` for untagged H.264, tagged H.264 and HEVC
  Main 10 on GPU; measured LUT = analytic gamma 1.961 within 1 everywhere observed (128 → 139); criteria (i), (iii) PASS; (ii)
  PENDING-CEF. Recommendation `Q = ["bt709/bt709/bt709/false"]`, `L` = analytic (= W1's provisional constants, so no re-pin yet).
  **Caveat:** `--disable-gpu` (software compositing) live == snapshot (identity); untagged H.264 decodes `smpte170m…` there;
  HEVC undecodable. Applying `L` under software compositing would add +11 at mid-grey and the tuple cannot tell the paths
  apart (OBS with browser hardware acceleration off is probably the same).
- **Engagement (Q0b 2):** host program page: gate passes; P2 2→3 and DSK 2/3/5/7 admitted (redraws as §8); P2 4→end not
  admitted (main's bridge visible — as designed). **Raw export / Build Preview: MISS** — `#slideshowNavigator` (visible,
  off-screen thumbnails with text) fails the whole-page gate, so raw/preview never freeze (contradicts §4 "preview inherits").
- **Foreground (Q0b 3):** `m-fg` PASS (≤ 1.3), `-omit` / `-swap` FAIL as expected; geometry exact (≤ 0.04 px), flat ≤ 1.4,
  **edges up to 78 LSB** (3.4 % px > τ) — "every pixel ≤ τ" not met (resampling: native video scale vs CSS-scaled canvas).
- **Cost (Q0b 4): STOP** — DSK 7→8 take 47.6–51.9 ms (> 50 ms); 1282×1080 clip alone 41 ms. Others 12–25 ms.
- **Geometry (Q0b 5):** holder style identical at 1920×1080 / letterboxed / 2560×1440 / DSF 2; flat 3–11, edges 23–250 LSB.
  Stock + rev 9 P2 4→end: bridged decoder at opacity 1 through all 157 fade rAFs — §1.4 bridge confirmed.
- **Q0b 6 dry run:** every control and candidate as expected (cut, freeze m-on/paused/hold/off, screen, on/off/noblend, CvC,
  D2, `--disable-gpu`, DSK, delay, tone `m-tone` PASS / `-raw` FAIL −11, lifecycle advance/replay PASS).

**Re-plan triggers (owner decision):** (1) take cost > 50 ms on DSK 7→8; (2) raw/preview gate miss on `#slideshowNavigator`;
(3) full-resolution holder edge residuals > τ; (4) software compositing needs identity `L` but is undetectable by tuple;
(5) CEF (criterion (ii), DX-2) not run. **Astra xhigh advisory on these:** `.agents/reviews/dissolve-crossfade/replan-astra-xhigh.md`
— its recommendations, for the owner to accept or override:

| Trigger | Advisory recommendation | Owner design call? |
|---|---|---|
| 1 cost | keep 50 ms; first remove unneeded work (identity `L` skips RGB writes + `putImageData`, keep the alpha scan), try a source-resolution crop; profile per stage first | only if the bound or budget-skip changes |
| 2 gate | keep preview coverage: stage admission + a conservative exterior pass that prunes an outside subtree only when its paint extent is proven disjoint (e.g. a validated clipping ancestor); must still see main's bridge outside `#stage` | yes (gate proof / preview scope) |
| 3 edges | draw the snapshot at the device-pixel content grid (not natural size + CSS scale), keep strict τ; replace Q0b's Pillow reference with browser-rendered references before considering an edge envelope | yes (holder representation / acceptance) |
| 4 tone | ship identity `L` now (§12.5 fallback, already authorised); give a host-side compositing-path calibration a focused feasibility measurement before finalising Q5; reject page-side heuristics | identity = authorised; selector = yes |
| 5 CEF | early CEF preflight on current bytes (tone ×2 launches, engagement, DSK 7→8 cost), final DX-2 on final bytes | no (measurement) |

## Verified

- Full suite at `de83681b` (all W1–W4 code + W2 r1 fold): **3.12: 9291 passed, 28 skipped, 1 xfailed** (143 s); **3.10.10 floor: 9291 passed, 28 skipped, 1 xfailed** (187 s; venv in session scratch). Dashboard suites not run (no dashboard files touched).

## Not done (in plan order)

0. **Owner: decide the five re-plan triggers above** (planner revs §3/§9 → W1 code + tests, re-pin). Nothing below is gated
   on product bytes except DX-1/DX-2.
1. CEF part of Q0b 1 (two OBS launches; tone movie paused at frames 30/300/900 in h264u/h264t/hevc10 + Keynote HEVC; needs a
   scratch `ManagedObs` driver) → final `Q`/`L` (re-pin only if they change).
2. W2 Astra r2 fold (see final note), then one more Astra round on W2+W3.
3. Re-run full local suites after the re-plan code lands (`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`), Python 3.10 floor
   (`UV_PROJECT_ENVIRONMENT=<dir> uv sync --frozen --all-extras --all-groups --python 3.10`), dashboard suites untouched.
   Coordinate the heavy window with peer sessions (one heavy job machine-wide).
4. DX-1 live gate (`scripts/dissolve_probe.py`, every arm, controls first) from a fresh pinned worktree; then DX-2
   (`managed_obs_qualify.py --arm dissolve`), `mmo-cef`, regression (§9.4); DX-3 owner check in real OBS.
5. One PR to `main`. Never merge.

## Session notes

- Machine: shared with the S2 session ("Keynote test optimization"); they ran a full suite ~23:40; load spikes > 20 seen
  around 22:50 — discard timed runs started at load ≥ 4.
- Keynote was open all session (owner's); untouched.
