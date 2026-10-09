# Live gate round speed-up — gate record (2026-10-09)

Branch `claude/attach-viewport-session` (off main `dda62e86`). Machine: M1 Pro (10 cores), Chrome 154.0.8037.59.
Reviews (Codex GPT-5.6 Sol): r1 3 MAJOR + 4 MINOR, r2 3 MAJOR + 1 MINOR, r3 1 MAJOR + 3 MINOR — all folded; r4 (verification of
the last two commits) no MAJOR, no product regression; its settle-deadline MINOR folded, two test/style MINORs left as
follow-ups (shared fake DevTools endpoint helper; typed cache-provenance record, declined twice).

## Findings that drove the work
- **attach stageFit failure was Chrome 154, not the display.** Chrome 154 (auto-updated 2026-09-30) drops
  `Emulation.setDeviceMetricsOverride` when the setting CDP session closes; the probe closed it before the host
  attached, so the attach page fell back to 1920x1025 (scale 0.9491). Identical with a 5K external monitor. Two-session
  check: override closed -> 1025; held open -> 1080. Fix `b7f4ea50`; host gates then passed at all 3 viewports.
- **The largest P2 cost was a redundant encode, not waits.** `--disposable` re-encoded the same 46 s H.264 pattern
  into 4 slots per arm (~17.5 s each, ~70 s of a ~194 s arm); all 36 outputs of a round were byte-identical
  (sha256 `8b20587612e9…`). Content-addressed cache `5141980d` (cold 17.5 s, warm 0.035 s).
- Most other P2 "waits" are deadlines that already exit early; the remaining fixed costs are race windows or operator
  profiles (not trimmed).

## Owner decisions (2026-10-09)
Attach once (1920); host C at 2560/1600 only; B and Voff at 1920 only; P2 `--strip bridge@8` dropped (same plan as
`--disable-bridge34`); freeze bracket only in fast (DOM) and gl-auto (WebGL) — 8b amended; 8a promoted
(`movingIndexRunAtCut` gates `continueThroughMovingMagicMove3to4`, tri-state: unmeasurable = inconclusive);
`--tier dev|full`; live host Chrome on port 0. Plan texts amended (baseline, visible-content, generalisation,
keynote-alpha).

## Live rounds
| Round | Head | GATE_JOBS | Wall | Result | Load start / peak | Slide-3 restart t (fast) |
|---|---|---|---|---|---|---|
| Baseline serial (monitor on) | `dda62e86` (main) | 1 | 35 min | 14/14 arms MATCH; host x3 FAIL attach stageFit (Chrome 154) | ~2 / ~8 | 0.098 |
| Host gates only | `b7f4ea50` | 1 | 6 min | host x3 PASS (attach scale 1.0) | — | — |
| Pre-trim 3-wide | `5141980d` | 3 | 9m48s | 14/14 MATCH, host x3 PASS | ~4 / ~11 | 0.132 |
| Trimmed 3-wide | `3808c0f3` | 3 | 7.4 min | 1 host-red MISMATCH — **void**: started 1 min after a full `pytest -n auto` (5-min load 33) | 26.8 / 28.7 | 0.218 |
| Trimmed 5-wide | `3808c0f3` | 5 | 6.1 min | **3 P2 FAIL**: restart observed 0.479 s (> 0.35 limit), 3->4 red (visible competitor) | — / 8.4 | 0.479 |
| Trimmed serial | `3808c0f3` | 1 | 14.0 min | all MATCH, host x3 PASS | — / 7.4 | 0.096 |
| **Qualification r1** | `91f9daae` | 3 | 7m15s | **13/13 MATCH, host x3 PASS** | 3.20 / 10.8 | 0.222 |
| **Qualification r2** | `91f9daae` | 3 | 7m13s | **13/13 MATCH, host x3 PASS** | 3.47 / 10.8 | 0.124 |
| **Qualification r3** | `91f9daae` | 3 | 7m16s | **13/13 MATCH, host x3 PASS** | 3.47 / 7.4 | 0.138 |
| **Final** | `2bf11264` | 3 | 7m16s | **13/13 MATCH, host x3 PASS** (restart fast 0.148, gl 0.129, slow 0.124) | 3.33 / — | 0.148 |

Qualification rounds, all P2 positive arms (fast, gl-auto, slow x 3): restart t 0.106–0.222 s (limit 0.35);
`continueThroughMovingMagicMove3to4` pass with at-cut n 24–27; freeze bracket pass in fast and gl-auto; max rAF gap
33.8–35.1 ms.

**Verdict:** GATE_JOBS=3 qualified on this machine (round 35 min -> ~7¼ min). GATE_JOBS>3 NOT qualified (warns).
Rounds refuse to start above 1-min load 4 (`GATE_MAX_START_LOAD`). Never start a round within minutes of a suite run.

## Headed live host (port 0), external display, owner watching (2026-10-09, head 0ac4bd70)
Field-tool session (P2 fixture, display 3 = 2560x1440 at x=1512): port read from DevToolsActivePort (57214), window at
(1512, 0) 2560x1440, transport hdmi, continuity qualified (scale 1.3333); show -> visible; advance x3 -> slide 2 scenes
1-3; goTo 1 -> slide 1; stop left no Chrome. Owner: "looked fine, nothing seemed off". Interleaved startup (load 2.7-4.2):
main 1.27 s / 1.15 s vs branch 1.18 s / 1.12 s — port 0 costs nothing (the first session's 7.5 s was a cold Chrome start).
2bf11264 (ownership check) was verified headless by the final round above.

## Open
- `tests/test_watercolour.py::test_cancel_after_png_encoding_still_discards_the_item`: load-sensitive flake seen once
  under `-n auto` (untouched code; passes alone 5/5).
- `managed_obs.py` `free_port()` pre-picks OBS ports (bind-and-close); not Chrome, out of scope.
