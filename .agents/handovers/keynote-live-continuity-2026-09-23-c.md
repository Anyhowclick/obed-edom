# Handover — GL-replay option (c), state at 2026-09-24 (merged as #218)

Supersedes the earlier GL-replay handovers (09-22-opacity, 09-22-g3, 09-23-g5; pruned after #218, see `git show ed7ff63c:.agents/handovers/`). Owner rules unchanged: no merge
without an explicit request; hands off Keynote; full local suites for every code PR (no CI).

## Where things are
| Item | State |
|---|---|
| Branch | `feat/gl-replay-c` (dev worktree `.claude/worktrees/autoprompts-toggle-cfdda0`), off `origin/main` d56fb0dd. Merged as #218 (`ed7ff63c`). |
| Plan | `git show ed7ff63c:.agents/plans/keynote_live_gl_replay_c.plan.md` rev 1 (completed, pruned) (Opus EXTRA HIGH → Opus HIGH critique §13). All OQs closed by the owner (§0); OQ-2 reversed (below). |
| Commits | f6a44dfe plan · 4ce4fb1f probe N3 live-ring · ca08e2e4 G2 inner-rect upload + `probe(rect)` · d5c71661 P2 GL probe series in (f) + A7′ scorer · 9989e8bf G2 stays version 1 + real-core arming test |
| G2 sha | `10a5b36a1f6008a3213bd90729915f6c15284448406f2a62dbc74ae884fe5288` (was `4f8850e0…`). Core `e9338aff` untouched; off path byte-identical. |
| Full suites at c58f4403 | pytest 6705 passed / 88 skipped / 1 xfailed; `test:ui` 238; `test:maps` 542 + perf 2. |
| Gates | r1 (ca08e2e4) superseded, pruned after merge. **r2 COMPLETE, all PASS** (phase 1 on 9989e8bf, phase 2 + Q3 on bef57a23): `.agents/reviews/gl-replay-c/gates-r2.md`. A7 limit widened to ≤ 3 by the owner. |
| Review | Codex GPT-5.6 Sol r1: 4 findings (2 major P2 fail-closed, 2 minor), fixed in 60707c45 + bef57a23; r2: all closed, 0 new (raw rounds pruned after merge; see git history of #218). |

## Owner decisions this session
- OBS hedge passed (rVFC present, pooled decoders warm, G2 LIVE in OBS). OBS upload rate ≈14/s vs ≈30/s headless Chrome ⇒ OBS/CEF-specific, an attach-qualification item, not (c).
- Readback probe `probe(rect)` in scope. OQ-1 2D canvas + `texSubImage2D` (own FBO draw rejected: "a lot of work for marginal benefit"; fallback only if uploads/s drops > 10 %). OQ-3 inner rect computed in page. OQ-4 P2 only. OQ-5 N2 gates if CvC passes. OQ-6 harness-side splices.
- **OQ-2 reversed: G2 stays version 1.** The core (`live_continuity_js.py:531`) retires any module version ≠ 1 with `moduleVersion`; r1 gate 2 showed 0 uploads. Making the core accept 2 would break the byte-identical off path.

## Gate results r2 (9989e8bf) — all run checks PASS
N1 KB RED (251–252) / CvC 0 / armed ×3 0 · N2 CvC passes ⇒ gates; KB RED; PASS · gates 1, 2 (**29.9 uploads/s vs 29.97 old bytes — no
drop**), 4/4b, 6 (20+3), 7 · G-OFF host ×3 verdicts match G-0′ · P5-7 · P5-A ×3 + 1 rep 2560, P5-H, KBs RED / controls 0 · **N3 max 0**
(2560 ×2, 1600, 1920), KB RED 245 (only red check), CvC 0 at 2560 · P5-L 3.3–3.5 ms.
Caveats: G-OFF 1600 arm C `continue3to4` False in both but via a different failure path than G-0′ (load 45, likely timing — re-run
queued); a foreign headless Chrome may have overlapped gate 6's first arms (gate 6 passed).
NOT RUN: 2nd P5-A rep at 2560; N3 CvC at 1600/1920; P5-F; G-OFF 1600 re-run; **all of phase 2** (G-OFF P2, G6 + N5 with frozen-upload KB
sha `413a00ba…`, A7′, A7 re-run); Q3 soak.

## r1 (ca08e2e4, superseded)
N1 KB RED for the right reason (ring 251/251/252; r3 recorded 251), CvC 0 · N2 CvC passes ⇒ N2 gates; KB RED · gate 1 PASS ·
gate 2 FAIL (never armed, version). One v1-diagnostic arm (not a gate): LIVE, inner rect {4,4,952,268}, 0 GL errors, 29.89 uploads/s vs
29.93 old bytes, N1 0, all hand-off checks green.

## Next
1. OBS attach qualification on the final G2 (OD-2), incl. the ≈14/s OBS upload rate.

## Lessons
- A plan claim "X is unchanged" needs a cross-module test, not a grep of Python constants: both planners missed the core's own version
  check, and G2's unit tests run without the core. 9989e8bf adds `test_the_real_core_arms_the_zone_for_the_real_module` (RED on v2).
- The version-1 diagnostic arm localised the blocker in one run before asking the owner — do that before escalating.
- Implementers share one worktree safely when files are disjoint and only the coordinator commits.
