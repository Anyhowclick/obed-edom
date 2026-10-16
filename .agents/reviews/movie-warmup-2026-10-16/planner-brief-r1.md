NON-INTERACTIVE. Do not ask questions: investigate, then write the plan file, then a short final report.

ROLE: planner (one HIGH pass). Write the implementation plan to ./keynote_live_movie_warmup.plan.md (current directory, which is a scratch dir).
The repo is READ-ONLY for you, at absolute path /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f (branch claude/trusting-aryabhata-f69fdc = claude/stage-b-arch + docs).
Read it by absolute path. Do not try to write into it.

## Goal (owner-approved 2026-10-15)
A product change in the Alpha Keynote live presenter: a one-shot movie "warm-up" at deck load. It removes the entry cold start of the first movie
a page mounts (Keynote's poster shows ~14 frames in managed OBS before the first movie decodes).
Read the evidence and the owner's decision first: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/handovers/f4-faststart-measure-2026-10-15.md (whole file).
The measured shape is /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/output/evidence/stage-b-2026-10-13/f4-faststart/warm-load/index.html:
- an inline script at page parse creates a detached, muted <video preload=auto> on one H.264 movie the deck references;
- on 'loadeddata' it releases the element (removeAttribute('src'); load()).
Any movie works (the cost is a once-per-page media-pipeline start, not the file).
Measured: managed OBS first session 280 → 56 ms (14 → 3 frames); headless real player 214 → 28 ms; benefit holds 3 min after release.
No faststart remux (rejected; do not plan one).

## Code you must ground the plan in (read them)
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_host.py: LiveOutputHost load path (~1640-1720: _resolve_codecs → codec_report, _resolve_continuity_static,
  patch_player, server_factory(..., continuity_script=...), goto); the asset server class with _program_html (~615-643), which injects
  the overlay + continuity_script + fit script after <body>; _codec_supported / _codec_display (~226-240, ~1310-1370);
  pre-navigation scripts (Page.addScriptToEvaluateOnNewDocument).
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_continuity.py: codec_report / _referenced_movies (~2700-2770): every referenced movie with its codec
  family, available even when continuity is off/unsupported.
- /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/src/obed_edom/live_runtime.py: injected-runtime conventions, player patching (owner rule: never modify main.js on disk; only
  sha-pinned in-memory patches).
- Tests near these: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/tests/test_live_host*.py and others that assert on _program_html output or injected scripts (find them with grep).
- Repo rules: /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/skills/obed-edom/SKILL.md (sections on Alpha Keynote live / managed OBS); plan format reference:
  /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/angry-mestorf-abe88f/.agents/plans/keynote_live_alpha_movies.plan.md.

## Constraints
- Do NOT plan edits to these refactor-owned files (a parallel restructure owns them): scripts/live_continuity_probe.py,
  scripts/mm_feed_instrument.py, scripts/live_evidence_contract.py, scripts/paint_instrument.py, scripts/managed_obs_qualify.py,
  scripts/run_gates.sh, scripts/binary_counter_movie.py, scripts/obs_cadence_decode.py and their tests. Acceptance runs may use
  them unedited, plus import-time monkeypatch wrappers kept outside the repo (as the handover's tools/ do).
- Keep it simple; match local style; minimal NatSpec, no inline comments unless essential; tests: maximum coverage with the fewest new tests.
- Never block or fail the session because of the warm-up; it must be invisible (detached, never in the DOM the player or instruments
  inspect), silent (muted), and release its decoder.
- Must work in all output modes the host has: headless, headful launch, managed OBS (CEF), external attach — or state why a mode is excluded.

## Decisions the plan must make (with reasons, citing code)
1. Where it lives: in _program_html (served HTML) vs a pre-navigation script vs part of continuity_script. Note continuity_script is
   empty when continuity is off/unsupported, but the warm-up should apply whenever the deck has a playable movie.
2. Which movie: first movie in slide order (first slide that references one), only a codec family the output can play
   (_codec_supported); how to resolve its served URL (an asset key maps to several per-slide files; use one that exists).
3. VP9-only / no-H.264 decks: warm with WebM, or skip? If unknown, plan a measurement (the f4 gap harness works for this) and a
   default (skip until measured).
4. On/off control: an env var or host option following existing patterns (e.g. CONTINUITY_ENV / GL_REPLAY_ENV), default on; and what
   the session log records (warm-up asset, mode, and readiness time if the page can report it cheaply).
5. Interaction with poster holds, mm_feed, gl_replay, the dashboard preview (does preview use LiveOutputHost?), and the
   instruments' video samplers (a detached element must not appear in document.querySelectorAll('video')).

## Acceptance (put these in the plan, with exact commands where possible)
A1. Unit tests: served HTML contains the warm-up for an H.264 deck; absent when disabled / no playable movie; picks the right movie.
A2. Headless real player on Alpha (probe, feed off + no-pre-move-capture wrapper as in the handover's tools/): slide-4 entry
    cold start ≤ ~50 ms median over 5 runs vs ~214 ms baseline; verdicts unchanged.
A3. Feed-on paint verdict on Alpha: b3to4 'not-decoded' frames drop from ~12 to ≤ 3 (with the observer-effect patch).
A4. Managed OBS (owner go needed per session): first-session entry ≤ ~80 ms over 4 runs vs ~280 ms; gate verdicts unchanged.
A5. No new verdict changes on the Alpha/D7/D7s gates; full suites pass locally on Python 3.13 and 3.10 (no CI in this repo).

## Output
The plan file: context, decisions, exact file-by-file changes (function names, signatures), tests (few), acceptance with commands,
risks, and an explicit "not in scope". Be concrete and grounded; cite line numbers you read.
