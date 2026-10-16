# Critique r1: Opus 5.5 high (plan r1 by GPT-6 Astra high)

Verdict: **NOT READY**. All findings were folded into plan r2 §0. Summary of findings, verified by the coordinator where marked:

1. **BLOCKER:** A1/A5 `uv run --python … --extra test` re-syncs the env to one extra and replaces the worktree
   `.venv`. Use the SKILL.md command and the `UV_PROJECT_ENVIRONMENT` 3.10 floor. (verified, `SKILL.md:49-51`)
2. **MEDIUM:** The ordering rationale is overstated. Core continuity would not pool or retain a warm element without a
   `*-video` id. The real reasons are `tag()`/`nextId` shift, a `createElement-video` note and `reidentify`. Drop the
   retention spy test.
3. **MEDIUM:** Over-built. Cut the sentinel, `pagehide`, the diagnostic validation matrix, headful/attach smoke runs,
   the WebM experiment and the `families` parameter. Shrink the Node test matrix to at most one run.
4. **MEDIUM:** A5 gates must follow gate discipline: one round at `GATE_JOBS=3`, from a pinned worktree, gates before
   suites.
5. **LOW:** URL: use `path.resolve().relative_to(root.resolve())`, `quote`, and `json.dumps(...).replace("</", "<\\/")`;
   no resolver round-trip.
6. **LOW:** Invalid env value: raise like the neighbouring controls. (verified, `live_host.py:1632-1649`)
7. **LOW:** Hash test: forward `movie_warmup_script` with env `off`; keep the hashes.
8. **Checked OK:** pre-navigation instrument hooks, inline-script ordering, `_referenced_movies` order, acceptance
   plumbing, and modes.

Simplest acceptable design: see plan r2 §0.
