# Handover → Codex: Alpha Keynote live continuity, deferred items (2026-09-19 night)

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
- Fixture (read-only): `F=/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/output/p2-recovery/html-adversarial` → `--fixture $F/html-player --original-index $F/html-unmodified/index.html`.
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
