# Dissolve cross-fade — implementation handover (updated 2026-10-12 afternoon)

## READ FIRST — end of day 2026-10-12 ~22:30 (supersedes everything below; resume here)

**State.** Branch `claude/keynote-live-dissolve-crossfade` REBASED onto `origin/main` `b3b06bc9` (S2 merged) — HEAD
`99b7271a`, local only, NOT pushed, no PR. Backup of the pre-rebase branch: `backup/dissolve-pre-rebase-243ee9a1`.
Pinned run tree `.claude/worktrees/dx3-ac008f88` (detached at `99b7271a`; fixture symlinks under `output/` added by hand).
Local `main` ref still old (it is checked out in the main checkout) — `git pull` there. Owner rules in force: plan
critiques ≤ 3 rounds; reviews F3-only, stop when no major/blocker, ignore ≤ medium; no scope creep; owner hears only on a
failure or when the draft PR is up.

**Done today (after 16:45).**
- Full suites at `958d0be0` (rebased): 3.12 and 3.10 each 10827 passed / 28 skipped / 1 xfailed. NOT re-run at `99b7271a`
  (W3's commit touched only `scripts/managed_obs_qualify.py`, `scripts/dissolve_probe.py` + their tests: 456 passed / 1 skipped).
- Rebase fixes: `5259d120` (dissolve census excludes S2's `qual_decks` copies), `958d0be0` (S2's `detach_experiment`
  slices the R1–R8 prefix; no pins changed). One import conflict in `managed_obs_qualify.py`. No player digests changed.
- Probe fixes found live: `de836d0c` (serve P2's `.mp4` as exported), `bef6a4d9` (raw-page driver waits on the hash;
  `UC` is module-scoped, unreachable), `243ee9a1` (F3-critical instrument: rVFC `presentationTime` reference — the
  "frame +1" was the INSTRUMENT, holder == reference after the fix; pending-rAF curve samples; capture to the hand-off;
  destination movies excluded only after it).
- **DX-1 F3-critical round at `958d0be0` (owner scope: grant, scope, frozen frame, base cross-fade model): ALL PASS**
  (model, complement, no_dip, curve, monotone, handoff, frozen_frame, frozen_region, cost, grant, scope; `m-raw-prod`
  needed one rerun for "5 mid frames < 6", first run retired). Evidence:
  `output/evidence/s2-dev/dissolve-alpha-2026-10-11/dx1-2026-10-12/` (`dx1-final-958d0be0/`, scores, `dx1_paced.py`
  = the load-paced runner used: waits for load < 3.5 per arm, MAX_LOAD guard unchanged). Out of owner scope, still
  INCONCLUSIVE: reference capture ("null timing while paused", all `m-snap*`/`m-tone`), DPR arms open 1920×993,
  `m-geo*`, `life-*`, cut, `overlay` (`m-bridge-off` = S2-bridge territory / Q6 follow-up).
- `mmo-cef` regression at `958d0be0`: PASS (`mmo-cef-summary-958d0be0.json`).
- **DX-2 (managed OBS) NOT passing yet.** Run 1 at `958d0be0` failed every session (advance never acked). W3 fixed at
  `99b7271a`: (1) CEF drops CDP key input right after load → `await_input()` (Shift keyUp until a page keyup listener sees
  one, ~0.2 s; 12/12 acks); (2) G2 state is legitimately None under gl_replay off; (3) **rAF-gap rule (coordinator
  decision, ALL profiles):** a gap > 50 ms is allowed only before any animation starts and only if the first post-gap record
  shows every animation pending at initial values (CEF pre-start gap 69–74 ms, recorded `preStartGapsMs`); (4)
  `GetSourceScreenshot` returns premultiplied RGB → `source_shots(straight=True)` for DX-2 (offline re-score: `on`/`on2`/
  `cef-skip` residual 1.1–1.6 vs τ 4; `off`/`noblend` controls still FAIL) — **fix 4 not yet confirmed live**. Latest live
  run (r3, before fix 4): placement `{grant: null, reason: attached}` everywhere, no holder bound anywhere; `off`, `cut-off`
  MATCH; others INCONCLUSIVE; `cut-on` MISMATCH. Debug records: `.../dx1-2026-10-12/w3-dx2-debug/`.

**Open decisions for tomorrow (DX-2; owner or coordinator call — all instrument, none touch the take):**
1. **Mid frames 5 < 6** in every CEF fade arm: `GetSourceScreenshot` costs ~60 ms idle, 130–175 ms during the 1.5 s
   dissolve; PNG quality 100 is slower (dead end). Options: accept 5 in the CEF profile / longer in-memory dissolve for DX-2
   arms / a faster lossless capture.
2. **`cut-on` FAIL:** one out-only pixel (543, 792), 3 px above the movie rect (y 795), alpha 223 before the cut — fits
   CEF's unsnapped movie edge (§8.6). Option: `score_cut` excludes padded media rects like the fade scorer does.
3. **`cef-skip-dsk`:** "class out: 1470 px < 2000" — DSK 7→8 has too few out-only pixels for the arm's class set; change
   the class set or the minimum for this arm.

**Next steps (in order):**
1. Decide 1–3; apply in `scripts/dissolve_probe.py` (resume agent `w3-obs` or a fresh one; brief: no scope creep).
2. Re-run the DX-1 F3-critical round from the pinned tree at the new commit (the rAF-gap rule changed for all profiles):
   `PYTHONPATH=$D/src <main>/.venv/bin/python <evidence>/dx1_paced.py <out> <scratch> <q0b1 decision> grant-chrome,grant-attach,channel-predefined,life-grant-reload,opaque-off,off,noblend,on,on2,m-paused,m-off,m-on,m-hold,m-raw,m-raw-prod,m-preview-prod`
   then `scripts/dissolve_probe.py --score <out> --decision <q0b1>` (unsandboxed; load < 3.5; decision file
   `output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json`).
3. Re-run DX-2: `scripts/managed_obs_qualify.py --arm dissolve --out <new> --decision <q0b1>` from the pinned tree.
4. Full suites 3.12 + 3.10 (3.10 venv: `UV_PROJECT_ENVIRONMENT=<dir> uv sync --frozen --all-extras --all-groups --python 3.10`).
5. Open the DRAFT PR to `main` (never merge; never auto-merge). Body: DX-3 PASS, DX-1 F3 PASS, DX-2, suites, Astra impl
   r1 APPROVE, r13 #1/#3 open items (followups handover), out-of-scope INCONCLUSIVE DX-1 checks listed as follow-up.
6. Cleanup after the PR: trash the session scratchpad (`/private/tmp/claude-501/...brave-goodall-bd9851/5bd19c3f-.../scratchpad`,
   ~4 GB incl. `w3/` 2.1 GB shots, `dx1/` 1 GB) once evidence is confirmed copied.

**Machine etiquette:** other sessions may be back tomorrow — send "need window" before Chrome/OBS/suite runs.

## READ FIRST — update 2026-10-12 ~16:45 (supersedes the 14:45 state below)

- **Implemented rev 17** (owner: no rev 18 / r14; plan critiques ≤ 3 rounds; reviews F3-only, stop when no major/blocker,
  ignore ≤ medium; decision 16 keeps the lease dropped). Commits: `3941b845` W1, `619f21ca` W6 (r13 #2 + item g folded),
  `0f29cf99` W2, `66b4145b` W3, `d2cac632` W4, `2012caf3` plan log, `ac008f88` Astra impl r1 **APPROVE**. r13 #1/#3 are
  recorded open items in the followups handover. Nothing pushed, no PR.
- Per-file tests before the pause: live_runtime 125, live_host 337, dissolve_probe 266, managed_obs_qualify 150/1 skipped
  (2 later W3 cases and W2's final run still owed).
- **DX-3 PASS (owner, ~16:30)** on the HDMI host from detached worktree `.claude/worktrees/dx3-ac008f88` via
  `scripts/live_fixture_session.py` on the P2 fixture (both Minimal Alpha_DSK decks are refused by main's continuity
  qualifier); grant `snap` on Chrome 154 GPU; null run showed the old behaviour. Record:
  `output/evidence/s2-dev/dissolve-alpha-2026-10-11/dx3-2026-10-12/README.md`.
- **Next (owner: live checks before the PR), each in an S2 "free now" window:** (1) 4 test files + full suites 3.12/3.10;
  (2) Q0b-ter grant arms + DX-1 headless; (3) DX-2 managed OBS; then draft PR (never merge). Owner wants to hear only on a
  failure or when the draft PR is up.

## READ FIRST — current state (2026-10-12 ~14:45; the night section below is history)

Branch `claude/keynote-live-dissolve-crossfade` (local only: NOT pushed, no PR), worktree `.claude/worktrees/brave-goodall-bd9851`.
Plan `.agents/plans/keynote_live_dissolve_crossfade.plan.md`: **rev 17 committed, NOT yet Astra-critiqued (owner: stop before
critique rounds)** = the **decision-15 split** (owner ~14:40): this PR ships the freeze only where the snapped rule is proven (the Chrome host launched
by `LiveOutputHost`, qualified engine version via CDP `Browser.getVersion`), granted through a host-only, page-unforgeable
per-document channel; **CEF/OBS skips** (today's jump) with the reason in `output.placement`. The startup placement probe
(rev 16 §3.3: fractional draw for CEF 127, isolated probe target / OBS calibrate scene, output gate, lifecycle, recalibrate
command + dashboard button, W5 tone map) becomes the **next PR**, starting with a 5-min OBS feasibility check (does
`GetSourceScreenshot` render a non-program source?). Owner decisions 8–15 in §12 (14: raw / Build Preview no longer freeze).

| Item | State |
|---|---|
| Code on branch | rev 13 take bytes (`69db0c0d`, `7834624c`: device-grid snap, DPR 1/1.5/2, exterior proof, top-layer/shadow refusal, identity tone); probe + DX-2 for rev 13/14 (`a8e4fd3c`). Rev 17 deltas NOT started: take grant read + integer left/top (W1; D1 10 305 B; candidate pins on e9b2fad4 `81ac1a33…`, 17c0c938 `a9aa0bde…`, rendering `dd0db318…` / `c6c1eb5e…`), grant channel in `live_host.py` + `tests/test_live_host.py` (W6), CEF-skip arms (W2/W3), docs (W4). |
| Reviews | W1 rev 12 Astra impl r1–r2 folded; W2/W3 rev 12 r1–r3 folded; rev 13 deltas verified locally only. Plan critiques r8–r12 folded; rev 17 not yet critiqued. |
| Tests (latest) | `test_live_runtime` 125 / 0 skipped (266 rows); dissolve + managed_obs 409 / 1 skipped; sweep 912/924 INCONCLUSIVE, 12 accepted survivors. Full suite last green at `1c5d3004` (3.12 9324 passed; 3.10 green at `de83681b`). |
| Measurements | Q0b-bis (`output/evidence/.../q0bbis-2026-10-12/`): engagement PASS (host + raw + negatives); cost PASS (headless ≤ 18.3 ms, CEF ≤ 34.8 ms); 18-cell DPR×origin×clip matrix PASS with a REAL `--force-device-scale-factor` (CDP emulation is void); W5 GO (indicative). Hi-DPI (`hidpi-2026-10-12/`) → device-grid snap. CEF (`cef-frac-2026-10-12/`): CEF 127 draws the video quad unsnapped → follow-up PR. |

**Path to a PR (estimate from 14:45):**
1. Rev 17 written (see §3.3 grant, §13.1 follow-up outline; evidence `plan-rev17-2026-10-12/`) → **next: Astra plan critique**
   (expect 1–2 rounds). Planner's re-check list for the reviewer: lease dropped (residual: auto transition while CDP is
   disconnected after an unobserved GPU→software fallback); grant also requires GPU compositing; pin exact build vs major 154;
   `cef-skip` hard FAIL and CEF media/tone sessions removed from DX-2; integer left/top kept as pure narrowing; DX-3 split (freeze
   on the HDMI host — confirm the owner can run it; cross-fade in OBS); context-bound commit vs `ChromeCdp` event plumbing.
   Open defaults: major 154 only; automatic re-grant after renderer crash + reload.
2. Implement W1 / W6 (grant channel) / W2 / W3 / W4 in parallel (~1 h; W1 is small, W6 is the only new host code) → Astra impl
   review + folds (history: 2–4 rounds per stream).
3. Full suites 3.12 + 3.10 (~10 min; book a window with the S2 session). Dashboard untouched in this PR.
4. **Draft PR can open here** (realistically this evening if reviews converge): code reviewed, suites green, qualification pending.
5. Ready for review after: Chrome-only DX-1 (~65 browser-min, booked window), DX-2 confirming CEF skips with reason, `mmo-cef`
   and §9.4 regression, then DX-3 (owner, real OBS / HDMI). Never merge.

Not run yet (still owed in this PR): m-geo-*, hide-row, D2, m-tone-twin dry runs; crop A/B. Dropped to the follow-up: CEF frac
clip matrix, probe controls, CEF HEVC tone.

Machine etiquette (S2 session "Keynote test optimization" runs timed validations today): send "need window" before any Chrome,
OBS or test run; S2 replies "free now"; send "done" after. Untimed work may overlap untimed work.

---

## Night of 2026-10-11 → 12 (written before the 02:00 shutdown; history)

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
| W2 `dissolve_probe.py` | `15dc7d33`; folds `34f4779e` (r1), `243de015` (r2), `1c5d3004` (r3) | Astra impl r1–r4 on W2+W3, r4 folded in `f51f70d7` (physical value ranges in every record validator; lifecycle fades need 6 mid frames; goto/back act at 1.3 s of the 1.5 s fade so the mid window precedes the action). **r5 APPROVE** (136 scorer cases re-run in memory; goto/back at 1.3 s still a mid-dissolve action). **Open owner/next-session item:** hide / hide-screen lifecycle rows are INCONCLUSIVE-by-construction at DX-1's ~6 fps full-res screenshots (hidden interval eats the mid window) — coordinator recommendation: capture those rows' fade with the per-frame screencast as the cut arms do (measurement change, no contract change). Pattern that converged: per-record schema validation before any filtering + one `COVERAGE` table + shared integrity always reaching the arm. Tone risk: P2 build-frame canvas `3231B69B` (960×276) covers the movie rect → tone mask empty → `m-tone` INCONCLUSIVE; needs a tone fixture with exposed ramp/patch interiors or a painted-pixel foreground mask (never count covered pixels). no_flash needs a pre-animation rAF on real captures (fail-closed; check at first gate run). |
| W3 `managed_obs_qualify.py --arm dissolve` | `47135f64` (+ CEF profile switch in `34f4779e`) | 19 CEF sessions, calibration from `opaque-off` first (re-derived, cached copy compared); cut shots keep `[t0,t1]` and must lie inside the cut window; reviewed with W2 (r2–r4), no open W3-specific item. |
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

- Full suite at `1c5d3004` (after W2 r3): **3.12: 9324 passed, 28 skipped, 1 xfailed** (127 s).
- Full suite at `de83681b` (all W1–W4 code + W2 r1 fold): **3.12: 9291 passed, 28 skipped, 1 xfailed** (143 s); **3.10.10 floor: 9291 passed, 28 skipped, 1 xfailed** (187 s; venv in session scratch). Dashboard suites not run (no dashboard files touched).

## Not done (in plan order)

0. **Owner: decide the five re-plan triggers above** (planner revs §3/§9 → W1 code + tests, re-pin). Nothing below is gated
   on product bytes except DX-1/DX-2.
1. CEF part of Q0b 1 (two OBS launches; tone movie paused at frames 30/300/900 in h264u/h264t/hevc10 + Keynote HEVC; needs a
   scratch `ManagedObs` driver) → final `Q`/`L` (re-pin only if they change).
2. Hide/hide-screen lifecycle cadence (screencast capture recommended), then the W2 tone-fixture item.
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

## Final note (01:20, before the 02:00 shutdown)

- All work is committed on `claude/keynote-live-dissolve-crossfade`; tree clean; nothing pushed, no PR, nothing merged.
- Reviews: W1 Astra impl r6 APPROVE; W2+W3 Astra impl r5 APPROVE (raw rounds in `.agents/reviews/dissolve-crossfade/`).
- Tests at HEAD: `test_dissolve_probe` + `test_managed_obs_qualify` + `test_live_runtime` re-run by the coordinator at `f51f70d7`:
  **404 passed, 1 skipped** (pre-existing REAL recording skip); full suite last run at `1c5d3004` (only probe files changed since).
- No agents running. Keynote untouched. OBS never launched. The S2 session holds the machine for its 3.11 run.
- Session scratch (Q0b drivers, 3.10 venv, review prompts) lives under `/private/tmp/claude-501/…/scratchpad/` and may not
  survive the reboot; the Q0b evidence copy and every review are in durable locations.

