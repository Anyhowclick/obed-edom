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
| Q0b step 0 | scratch only | _see below_ |

## Verified

- Full suite at `de83681b` (all W1–W4 code + W2 r1 fold): **3.12: 9291 passed, 28 skipped, 1 xfailed** (143 s); **3.10.10 floor: 9291 passed, 28 skipped, 1 xfailed** (187 s; venv in session scratch). Dashboard suites not run (no dashboard files touched).

## Not done (in plan order)

1. Q0b decision record → swap `Q`/`L` in `live_runtime.py`, re-pin, fill the follow-ups placeholder.
2. Astra review of W2 fold + W3 (one round), fold.
3. Full local suites (`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`), Python 3.10 floor
   (`UV_PROJECT_ENVIRONMENT=<dir> uv sync --frozen --all-extras --all-groups --python 3.10`), dashboard suites untouched.
   Coordinate the heavy window with peer sessions (one heavy job machine-wide).
4. DX-1 live gate (`scripts/dissolve_probe.py`, every arm, controls first) from a fresh pinned worktree; then DX-2
   (`managed_obs_qualify.py --arm dissolve`), `mmo-cef`, regression (§9.4); DX-3 owner check in real OBS.
5. One PR to `main`. Never merge.

## Session notes

- Machine: shared with the S2 session ("Keynote test optimization"); they ran a full suite ~23:40; load spikes > 20 seen
  around 22:50 — discard timed runs started at load ≥ 4.
- Keynote was open all session (owner's); untouched.
