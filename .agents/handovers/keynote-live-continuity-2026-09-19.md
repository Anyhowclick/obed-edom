# Handover → Codex: Alpha Keynote live continuity, deferred items (2026-09-19 night)

> **SUPERSEDED for branch/PR state** by later handovers (current: `keynote-live-continuity-2026-09-23-c.md`). Kept because the DeckLink field-test runbook uses its real-OBS findings as background and logs venue results here.

Owner field-tests DeckLink fill/key through OBS **tomorrow morning**. You have ~2 h. Work the list
top-down; stop at a green, committed state. Owner rules (AGENTS.md wins): accuracy and code quality over
speed · keep it simple · match local style · **no inline comments in src** (tests may be verbose) ·
root-cause before touching a test · **never weaken a gate** · no merge / no PR-merge / no force-push ·
never launch Keynote · **never open a visible (non-headless) browser window** — headless Chrome only ·
source decks untouched.

## Where things are
- Branch `claude/keynote-live-planning-handover-4e550b` @ `6f605b9` (pushed). PR #158 branch
  (`feat/keynote-alpha-p2-html-mm` @ `6236ffe`) does NOT yet contain tonight's commits — do not push to it.
- **Make your own worktree + branch** from that tip (e.g. `codex/live-continuity-deferred`); Claude keeps
  using `.claude/worktrees/pr158-handover-findings-4366b9` READ-ONLY for OBS checks while you work, and
  will not edit files. Commit small, scoped commits; push your branch; owner integrates.
- Plan: `.agents/plans/keynote_live_continuity.plan.md` · P2 index: `.agents/plans/keynote-alpha.md` ·
  README "Alpha Keynote" section · local (ignored) notes + run sheet:
  `/Users/anyhowclick/Desktop/work/obed-edom/output/keynote-live-planning-2026-09-19/{HANDOVER,DECKLINK-RUNSHEET}.md`.
- Code: `src/obed_edom/live_continuity_js.py` (shared preserve runtime — P2 re-exports it; ONE copy of the
  bytes; `CONTINUITY_VERSION`, `js_sha256()`), `live_continuity.py` (`derive_plan`, `to_runtime`,
  `QUALIFIED_PLAN_SHA256` allowlist), `live_host.py` (launch + `OBED_LIVE_ATTACH` attach mode, continuity
  injection, `_SessionLogger`), `live_session.py`, `web/live.py`; probes `scripts/live_continuity_probe.py`
  (host gate, strict scoring), `scripts/live_host_probe.py`, `scripts/live_fixture_session.py` (terminal
  operator tool), `scripts/live_alpha_testcard.html`.

## Commands
Python: `/Users/anyhowclick/Desktop/work/obed-edom/.venv/bin/python`, always `PYTHONPATH=$PWD/src`
(the venv is an editable install of the MAIN checkout). Node (dashboard only): prepend
`/Users/anyhowclick/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin` to PATH.
- Unit: `… -m pytest tests/test_live_api.py tests/test_live_session.py tests/test_live_host.py tests/test_live_runtime.py tests/test_live_continuity.py tests/test_live_continuity_js.py tests/test_live_continuity_probe.py tests/test_p2_adversarial.py tests/test_html_alpha_probe.py -q` (all green now).
- Fixture (read-only; the `keynote-parser-module-error-*` worktree was removed 2026-09-19 — use the presenter worktree's copy): `F=/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/pr158-handover-findings-4366b9/output/p2-recovery/html-adversarial` → `--fixture $F/html-player --original-index $F/html-unmodified/index.html`.
- Host gate: `… -u scripts/live_continuity_probe.py --fixture … --original-index … --artifact <scratch>.json` (3 arms + attach arm, ~3 min).
- **P2 gate (the oracle for ANY change to `live_continuity_js.py` or the P2 scripts):**
  `… scripts/p2_recovery_html_adversarial.py --reuse-export --disposable --wait-profile fast` → must print
  `success: **True**` with 14 findings True; and with `--disable-bridge34` → RED **only** on
  `continueThroughMovingMagicMove3to4`. Also run `--wait-profile slow` before you finish. Needs
  `output/p2-recovery/html-adversarial/` inside YOUR worktree (ignored, 608 MB): symlink it from
  `.claude/worktrees/pr158-handover-findings-4366b9/output/p2-recovery` (the run writes `html-disposable`
  + reports there — do not run it concurrently with another P2 run). ~6 min per run.
- After every browser run: `pgrep -fl obed-live-chrome` must be empty; kill only Chromes you started.

## Gotchas already paid for
- Never send `nativeVirtualKeyCode` in CDP key events on macOS (browser UI thread stalls 6–35 s).
- rerere + a file-watcher can revert the index between git calls → `git add … && git commit …` in ONE shell.
- Headless `--window-size=W,H` gives innerHeight = H−32; probes compensate (`HEADLESS_CHROME_HEIGHT_PAD`)
  or use `Emulation.setDeviceMetricsOverride`.
- Continuity installs only when the PAGE viewport == authored canvas (1920×1080) and the runtime plan's
  signature is in `QUALIFIED_PLAN_SHA256` (today: the fixture). Host tests bypass the allowlist via the
  `host_with_continuity` helper; the allowlist is tested in `tests/test_live_continuity.py`.
- 6 maps Python tests + 6 maps UI tests are red on pristine `origin/main` — not yours.
- Export slide-3 movie rect is y=797.1; P2's constant says 795 (on-screen measurement, within tolerance).

## UPDATE 2026-09-19 late — attach mode verified against REAL OBS 32.2.2 (CEF = Chrome/127.0.6533.120)
Read-only run by Claude at `d16119c`, fixture (H.264) deck, `OBED_LIVE_ATTACH=http://127.0.0.1:9222`,
`OBED_LIVE_ATTACH_MATCH=about:blank#program`: exactly-one-target match OK · page viewport exactly
1920×1080, dpr 1, html/body background `rgba(0,0,0,0)` · continuity **qualified** · **CDP Space/digits/Enter
DO reach the CEF page** (5 advances settle 1.3–2.3 s; goTo 1 in 0.34 s) ⇒ **P0-b click fallback is now
LOW priority** · both H.264 movies decode (readyState 4, 0–3 dropped of ~60 frames) · hide ⇒ not visible
and both movie clocks keep advancing (+1.5 s in 1.5 s) · CDP screenshot of slide 3 has real alpha (81 %
alpha 0, 18.9 % opaque) · stop ⇒ page at `about:blank`, OBS still running, log written. Not yet seen:
DeckLink output itself, HEVC originals in CEF, the 3→4 in-move artifact through OBS (expected, same bytes).

## Deferred items — priority order
### P0-a · 3→4 in-move position (owner WILL see this tomorrow)
With continuity on, the movie is carried through the 3→4 moving Magic Move on one decoder (clock
monotonic, lands at (327,709,1266,356)), but for the ~1.5 s move (scene 7) the live `<video>` is pinned
at the movie's slide-1 footprint (109,795,952,268) — it should travel/scale from (198,797,952,268) —
while the player animates its poster texture to slide 4; then it snaps to the destination. Strict host
probe: arm A `continue3to4` RED on the before-cut rect; everything else green. Same bytes ⇒ same in P2's
harness (its finding checks identity/clock/landing only). Look at `keepAtFootprint`, `keepAtSlot`,
`slide4Rect`, `bridgeTo34`, `isCompositing`, `findMovieCanvas` in `live_continuity_js.py`. Preferred fix:
while a bridge boundary's Magic Move is compositing, pin the live video per rAF to the on-screen rect of
the player's own animated movie texture/element for that movie (follow what the player draws — do not
re-implement Keynote's easing); if that element cannot be resolved unambiguously, fall back to a
time-based interpolation src→dst ONLY if you can read the transition duration from the plan/export, else
keep today's behaviour and say so. The plan object may gain the bridge `srcRect` (derive_plan already has
it; `to_runtime` drops it — adding it changes the runtime plan ⇒ recompute the allowlist signature and the
P2 scripts' injected plan). Acceptance: P2 gate green fast+slow, bridge-off RED on the one finding; host
probe overall `pass` with arm A 3→4 green under the CURRENT strict scoring (you may make the probe's
"before" check path-aware — rect within tolerance of the src→dst path, monotonic progress — but not
laxer about identity/owner/clock/landing); arm C still RED at 3→4 only. Evidence of the defect:
frame captures in Claude's scratchpad `slide3/mm34-on-*.jpg`.
### P0-b · click-advance fallback for OBS
CDP key events should reach OBS's CEF page without OS focus, but this is unverified. Add
`OBED_LIVE_ADVANCE=click` (resolved at start, logged): advance = CDP mouse press/release at the stage
centre instead of Space. Earlier measurement: click-advance settles identically on this player. goTo still
needs digits+Enter — if keys fail in OBS, goTo reports a clear refusal rather than hanging. Unit tests +
one headless run of `scripts/live_host_probe.py` with the env set.
### P1 · correctness debts from the Codex review of `3f0068c..fd1890b`
1. `qualified` read-back uses `!!window.__OBED_P2_PRESERVE__`, which is assigned before hooks/observers
   install. Add a final `ready` marker at the very end of the core and read that + `__OBED_CONTINUITY_INFO__`
   (JS change ⇒ P2 gate). A core exception must surface as `unsupported: runtime failed to install`, not the
   viewport reason.
2. `live_continuity._movie_rect` accepts a video layer at arbitrary depth but composes only base + leaf;
   require a direct child (or compose/validate every ancestor) — else `Unsupported`.
3. `to_runtime` ordering: accept at most one bridge, nothing actionable after it, no bridge-before-restart —
   moot under the allowlist today, but make the structural rule explicit so the allowlist can be relaxed later.
4. Review `e8ac805` yourself (it has not had a second review): attach teardown via fresh socket, the
   queued logger's close/drain, the absolute CDP deadline, `_pick_target`, loopback validators.
5. HDMI page when continuity is off/unsupported should be byte-identical to pre-I2 (a stray blank line was
   reported) — assert it in a test.
### P2 · next plan increments (only if time remains; each is independently shippable)
- **I3 scaled-stage mapping**: authored→screen per rAF via `#stage` rect ÷ header size, tolerances scaled;
  lifts the 1920×1080-viewport limit (owner's HDMI monitor is 2560×1440). Gate: host probe green at
  2560×1440 AND P2 gate green at 1:1.
- **I5 codec report**: detect movie codecs at prepare time; HEVC + headless/CEF ⇒ `unsupported` with reason.
- **I6 UI**: continuity badge + off-switch in `dashboard/src/live/` (`npm run test:ui`, rebuild `dist`).

## Report back (in your final message + a commit on your branch updating this file)
Commits, what is green (exact gate outputs), what you deliberately left, and anything the owner must know
before pressing Show tomorrow.

---

## Codex PAUSE checkpoint — 2026-09-19, owner requested pause at ~16:32 UTC

**WIP, NOT a green/demo-ready checkpoint.** Owner saw weekly balance go from 10% to 5%,
then explicitly requested “pause, prep handover now.” Do not continue automatically.

### Resume location

- Branch: `codex/live-continuity-deferred`, based on `d16119c` (includes the handover itself).
- Worktree: `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/live-continuity-deferred`.
- Main checkout and Claude presenter worktree were not edited. No Keynote or visible browser was
  launched. No PR/merge/force-push. Only disposable headless test browsers were used.
- All test processes finished; final `pgrep` for owned live Chrome / host probe / P2 probe was empty.
- No dashboard server was restarted; production assets are built, but serving the new UI requires
  restarting the intended dashboard from this worktree when the owner resumes.

### Implemented, pending final qualification

1. **P0-a motion fallback:** shared runtime version 2 now moves/scales the preserved movie during
   scene 7, using `srcRect` and `durationSeconds` derived from the export. Real DOM diagnosis showed
   every movie-sized poster canvas remains static throughout the move; animation is inside WebGL,
   so no unambiguous moving DOM rect was available. Used the handover-approved **linear interpolation
   over exported duration** fallback. This does **not** prove exact Keynote easing or movie/poster
   compositing parity. Source `(198,797,952,268)` → destination `(327,709,1266,356)` in 1.5s.
   Headless trace confirms intermediate positions/scales, one owner, monotonic clock, exact landing.
   Repeated detach initially reset the motion: independent review caught it; fixed by retaining the
   per-generation/boundary start time and reattaching before the active-loop return. Node behavioral
   regressions cover both detach timings and clear-generation cancellation.
2. **P0-b OBS fallback:** `OBED_LIVE_ADVANCE=click` resolved/logged at start, CDP stage-centre mouse
   press/release. Go-to still uses digit/Enter and reports a clear missing-ack refusal.
   **Required click-mode real headless host probe has NOT run yet.**
3. **P1:** final runtime `ready` marker + strict readback; install failure distinguished from viewport
   refusal; direct-child-only movie geometry; bridge needs source/destination/finite positive export
   duration; reject repeat bridges, bridge-before-restart and actionable boundaries after bridge.
   Review caught mixed bridge+pin silently disappearing into an allowlisted plan; rejected now with
   regression coverage. Updated allowlist signature:
   `ec4b0cb3eeaf393ec00a7313d1c68b640a90282c80d408767c99984b710800cf`.
   Fixture transition duration metadata restored from real export, full fixture/real comparison kept.
4. **Host hardening review:** fixed full-log-queue close (event-signalled drain, writer owns file
   close), failed attach discovery cleanup, URL/title concatenation matching, malformed endpoint
   ports and websocket userinfo/fragment rejection. Off/unsupported HTML already matched pre-I2;
   added byte-hash regression tests for HDMI and alpha.
5. **I6 UI:** continuity badge and exact reason above Show; pre-start checkbox defaults enabled.
   Unchecked sends `continuity: "off"`; API permits `auto|off`; host obeys request off OR environment
   off (UI cannot override environment). Applies to next session, not a live hot-toggle.
   Qualified label explicitly limited to 1920×1080. Targeted UI tests and build pass.

### Verification and evidence (local, ignored)

All paths below are relative to this worktree's `output/live-continuity-deferred/`:

- `unit.log`: **378 passed in 2.33s** for the full handover unit command (including host suite).
- UI: **20 live-presenter tests passed**, UI typecheck and production build passed. Package lock
  unchanged. `git diff --check` passed.
- `p2-fast.log`, `p2-fast-initial.json`, `p2-fast-initial-sha.json`: initial fast P2 run
  **success: True; all 14 findings True; source unchanged**. IMPORTANT: Python imported the shared
  runtime BEFORE the repeated-detach fix. This is NOT qualification of final runtime bytes.
- `diagnose.py`, `diagnose.json`, `events.json`: disposable headless DOM trace. Movie moves through
  approximately x207/236/265/293/322 then lands x327. This diagnostic predates the repeated-detach
  correction; final host run below includes it.
- `host-gate.json` (~4.3 MB raw sampled evidence), `host-gate.log`: final current-runtime strict
  host run **status: fail**. Runtime SHA in run is
  `cc09d246a89391ccff65bb9555878be4a65d91c93713ad6745301eaac0bac8bd`.
  A and attach: 1→2 TRUE, deliberate restart TRUE, 3→4 FALSE. B and C are correctly RED at 3→4;
  C remains GREEN at 1→2. Cleanup fields empty.
- `run_p2_gates.py`: prepared helper for final fast / bridge-off / slow, saving each report and
  fingerprints before next run overwrites bank. **Not run.** It is a convenience wrapper, not a gate
  replacement: inspect exact findings and runtime SHA, not merely process return code.

### Immediate next work: root-cause strict host probe failures using saved samples FIRST

Motion itself has **97 sampled frames, monotonic shared-scalar path, no motion errors**, no owner
mismatches. Strict host failure exposes two measurement/state issues; no gates were loosened:

- A has 105 `missingSamples`, attach 106. Expanded motion window starts ~9577/9611 ms and includes
  **scene 5 before the intentional scene-6 decoder restart**. Naturally the continuing slide-3
  decoder did not exist yet. Window must be grounded at the settled slide-3/source phase while
  still including the ENTIRE scene-7 move; it must not silently ignore absence within that window.
- A has 14 `rectMismatches`, attach 15. First examples ~13311/13345 ms are scene 7,
  `playerState: WaitingToJump`, busy true, movie ALREADY at destination `(327,709,1266,356)`.
  Scorer currently recognizes destination-before-scene8 only for `IdleAtFinalState`, and incorrectly
  expects source again during post-animation WaitingToJump. Model observed transition phases and
  assert the ordering (Playing → final → WaitingToJump), rather than blanket allowing arbitrary
  pre-cut destination rects. Keep early-jump/stationary-snap/backwards/off-path controls RED.

Probe review already fixed two OTHER issues: prioritise phase-correct true ownership over a
same-asset stationary ghost when choosing candidate; fail any sampled disappearance of selected
movie. 54 probe tests passed before latest combined 378-test run. Preserve those checks.

After fixing/re-scoring saved host samples with meaningful regressions:
1. Run fresh full host gate A/B/C/attach, require overall PASS; don't substitute re-score for live gate.
2. Run final P2 fast + slow; run bridge-off and require RED **only**
   `continueThroughMovingMagicMove3to4`. Initial fast pass is stale relative to final shared bytes.
3. Run `scripts/live_host_probe.py` with `OBED_LIVE_ADVANCE=click`, explicit absolute fixture/original
   index paths and artifact destination. No visible browser.
4. Review final source diff and targeted tests; only then mark a green checkpoint.
5. Owner must eyeball output at the receiver: fallback easing is approximate; OBS/DeckLink fill/key
   and real CEF input remain unqualified. Ask before using the external monitor.

### Deliberately untouched / pending

- I3 scaled-stage mapping: still unsupported outside authored 1920×1080. Monitor at 2560×1440 needs
  later work or a supported 1920×1080 output; the UI now exposes the refusal.
- I5 codec reporting, HDMI/receiver verification, actual OBS click/go-to behavior, native easing
  parity, audio/notes remain deferred.
- `scripts/p2_alpha_spike.py` still has `nativeVirtualKeyCode`; did not alter that unrelated payload.
- No extra full maps test runs; known baseline map failures remain outside scope.

P2 export-bank symlink in this worktree points at Claude's
`pr158-handover-findings-4366b9/output/p2-recovery/html-adversarial` (as original handover prescribed).
P2 reruns overwrite its disposable player/reports: coordinate serial access and retain copied evidence.

---

## STATE AT CLOSE — 2026-09-19 late night (Claude). Read this first when resuming.

**Branch** `claude/keynote-live-planning-handover-4e550b`, pushed; **code frozen at `62e1ab7`**, later commits
are docs. Contains Codex's `codex/live-continuity-deferred` (`2dd7b7c`, merged) — that branch needs nothing
more. NOT in PR #158 (`feat/keynote-alpha-p2-html-mm` @ `6236ffe`) and not in `main`; fast-forwarding #158
to this tip is the owner's call (it fast-forwards cleanly). No merges were made.

**Tomorrow (2026-09-20 morning): first DeckLink fill/key contact via OBS.** Operator doc for the owner and the
standby peer: [`decklink-field-test-runbook.md`](decklink-field-test-runbook.md) — hardware is unidentified
(owner sends photos), routes A external key / B internal key / C scan converter + luma key, test-card alpha
verdict, field tool, triage table, log reader, what to bring back. Fallback build `9dab02c`.

**What exists now**
- Live host: owned Chrome over HDMI (stage fitted to any display) OR attach to an OBS Browser Source over
  CDP (`OBED_LIVE_ATTACH`, `_MATCH`), transparent background + transparent hide on the alpha path, Stop
  blanks back to the target's original blank URL and never kills OBS, exactly-one-target + real loopback
  checks, queued JSONL session log, absolute CDP deadlines, `OBED_LIVE_ADVANCE=click` fallback.
- Session service: per-session state holder, Stop always possible/terminal, bounded request cache.
- Continuity: ONE shared runtime (`live_continuity_js.py`, v2, sha `4946708d…`) re-exported by the P2
  scripts; `derive_plan` → `to_runtime` (fail-closed) → in-page viewport gate → `ready` read-back;
  modes `qualified | unsupported(reason) | off` in the snapshot, the log and a UI badge; pre-start
  checkbox / `OBED_LIVE_CONTINUITY=off`. Only plan-named movies are preserved. 3→4 motion = linear
  src→dst over the export's duration.
- Instruments: P2 gate (oracle for the shared bytes), `scripts/live_continuity_probe.py` (3 arms + attach,
  windowed phase-ordered scoring, red controls), `scripts/live_host_probe.py` (`--viewport`, stage fit),
  `scripts/live_alpha_testcard.html`, `scripts/live_fixture_session.py`.
- Verified on the final bytes: P2 fast 14/14 · slow 14/14 · `--disable-bridge34` RED only on
  `continueThroughMovingMagicMove3to4` · host gate PASS · host probe pass (key + click) · 381 unit tests ·
  real OBS 32.2.2 (Chromium 127): attach, alpha, keys, H.264 decode, hide-keeps-playing, 3→4 travel, one
  movie on slide 4, re-attach after Stop.

**Known limits / open work (priority order)**
1. **Generalisation beyond the fixture** — allowlist `QUALIFIED_PLAN_SHA256` is an interim narrowing of owner
   decision 3a. Brief for a peer: [`../plans/keynote_live_continuity_generalisation.md`](../plans/keynote_live_continuity_generalisation.md)
   (boundary-specific runtime, instance identity by geometry, stray-movie check in both gates, qualification decks).
2. **I3 scaled-stage mapping** — continuity only qualifies at a 1920×1080 viewport (owner's monitor is 2560×1440).
3. 3→4 easing is linear (Keynote's is not; WebGL animation exposes no DOM rect) — owner to judge at the receiver.
4. **I5 codec report** — fresh exports carry HEVC; OBS's Chromium may not decode it (untested). Fixture is H.264.
5. Native DeckLink sender (OBS is only the bridge); audio; presenter notes; HDMI receiver qualification.
6. Housekeeping: fixture export now lives ONLY in the presenter worktree's ignored
   `output/p2-recovery/html-adversarial/` (P2 runs rewrite `html-player`) — make a durable copy;
   `scripts/p2_alpha_spike.py:260` still sends `nativeVirtualKeyCode`; 6 maps Python + 6 maps UI tests are
   red on pristine `main`; owner has ~3 % Codex left — a final review of `9dab02c..62e1ab7` was not run.

**Lessons worth keeping**: real OBS found two defects that every headless gate passed (stray pooled clip;
Stop breaking the next attach) — a gate proves only what it asks, so assert absence too and always do a
pass on the real target · tightening a scorer turned a green red and that was the finding · zsh does not
word-split `$var` (a "gate run" silently did nothing) · verify a subagent actually did the work (one
delegated and returned; one stopped after the easy parts) · stage + commit in ONE shell (rerere/watcher).
