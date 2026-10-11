NON-INTERACTIVE. Do not propose a plan, do not ask for approval, do not edit any file. You are ROUND 4 of the critique on a written implementation plan. Read files, verify claims, output findings only.

# Target
Plan rev 5 (commit e5c644bb; earlier: rev 4 4ffcd8ad, rev 3 f3bd8b55, rev 2 cd289a05, rev 1 8e572864; `git diff 4ffcd8ad e5c644bb -- .agents/plans/keynote_live_dissolve_crossfade.plan.md` shows the latest fold):
/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851/.agents/plans/keynote_live_dissolve_crossfade.plan.md
Repo worktree (origin/main 1589d096): /Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/brave-goodall-bd9851
Your earlier rounds and prompts: .agents/reviews/dissolve-crossfade/plan-astra-r{1,2,3}.md in that worktree.
Main checkout (git-ignored): /Users/anyhowclick/Desktop/work/obed-edom/output/ — players output/fixtures/p2-recovery/html-adversarial/html-unmodified/assets/player/main.js (e9b2fad4) and output/fixtures/keynote-player-17c0c938/main.js (17c0c938); planning scratch (builders dpatch7.py = Q7(a), dpatch8.py = Q7(b), Node checks, result JSON) at output/evidence/s2-dev/dissolve-alpha-2026-10-11/plan-2026-10-11/{planner,rootcause,coord}/.
S2 branch: git refs only (origin/claude/s2-detach-fix).

# Context
Keynote's export player draws `apple:dissolve` (and the `none` cut) with its CSS renderer over two flattened textures; with fill-less textures the incoming slide pops in (cut: both slides for a frame). The plan: in-memory, count-checked, sha-pinned `patch_player` replacements D1–D4 (owner rule: never modify main.js on disk; unknown players refused): commit-before-construct cross-fade (verified `plus-lighter`/`isolation` rules for the ids the player will allocate + mirrored incoming fade), a mirrored cut, and F3 — the outgoing movie freezes on its current frame and fades with its slide (owner's observation of the Keynote app), taken by drawImage snapshot in `jumpToScene_partFour` (D4) and attached inside the outgoing fading wrapper (D3), add-only, never touching the <video>.
Owner decisions 1–4 are FINAL (fold into mm_opacity; every output; F1 cut in this patch, F2 follow-up; F3 in this patch, splitting declined). Questions 5–7 carry PROVISIONAL DEFAULTS (5a accept the ~11/255 mid-tone step; 6b player-only on main, S2 ends its hold and the bridge; 7b redraw overlying plain canvases into the snapshot): review the design under those defaults, and say if a default is unsound.
Owner rules: minimal tests (max coverage, fewest tests, parametrized); null + positive controls for every instrument; integrity failures INCONCLUSIVE and never satisfy an expected FAIL; keep it simple — prefer conservative skips (documented residuals) over reproducing complex cases.
The owner plans to stop this critique loop at round 7. Prioritise: findings that would make the implementation wrong, unsafe, or the acceptance unable to detect a failure come first; do not re-raise closed items or relitigate final owner decisions; mark pure polish as nit.

# Your job
A. Status of every round-3 finding (r3-1 … r3-11) under rev 5: closed / partly closed / open / regressed, with evidence.
B. NEW findings on rev 5, verified against primary sources (re-run cheap checks in memory/stdout only: anchor counts in both players, containment including self, order independence of R1–R5 / R6–R8 / D1–D4, `node --check` of the patched players for BOTH Q7 builders). Focus on what rev 5 added: the admission rules (occlusion / paint-order / geometry / full-resolution opacity), the Q7(b) canvas redraw (correctness of geometry, opacity, order; can it ever paint something Keynote would not show, or double-paint content already baked into the outgoing texture?), decoder binding and the demixed outgoing estimate in the media oracle, per-arm media evidence, `m-bridge`, the cut timing restriction, DX-2 additions, Q5–Q7 wording and cost accuracy, test/stream disjointness and the minimal-tests rule.
C. CLOSING SWEEP: one inventory table over every verifiable claim class in rev 5 with status VERIFIED / FINDING # / NOT VERIFIABLE STATICALLY (what measurement settles it; scheduled where).

# Output format
Part A: table r3 # | status | evidence | remaining fix wording.
Part B: numbered NEW findings, most severe first: **Severity** (blocker / major / minor / nit), **Class** (new class / closed class / edge case), plan section, claim, evidence (file:line or byte offset, command summary), exact fix wording.
Part C: the inventory table.
End with a one-line verdict: ready for owner review / ready for owner review after listed fixes / needs another planning pass.
