# Handover: Stage C orchestration (2026-10-13)

**Status (2026-10-13):** implemented on `claude/stage-c-orchestration`; Astra r1 1 major (folded), r2 clean; G1–G4 PASS (`.agents/reviews/stage-c/gates-r1.md`); integration PR open, awaiting the owner's G5.

Read this first, then the plan. You coordinate Stage C in your own worktree; the S2 follow-ups session
(branch `claude/s2-followups-dsk-deck-902af1`) keeps Stage B (tag-dip alternatives) and must not be disturbed.

## What and why
- **Plan:** `.agents/plans/keynote_live_continuity_stage_c.plan.md`, rev 2, **APPROVED** by the owner 2026-10-13.
  - OQ-C1 = (a): a movie with real transparency, or an HEVC movie whose transparency cannot be read, **fails the
    prepare and is named** with the fix ("replace it with an opaque movie").
  - OQ-C2 = **C → S3 → B**.
- **Goal:** (1) the prepare step converts every non-H.264 movie in the cached export to H.264 (libx264 CRF 14, fast,
  yuv420p; the `.key` is never touched); (2) partial continuity: carry the moves that qualify, name every other one in
  the dashboard, and **never gate deck start on continuity** (supersedes handover open item 4 "dashboard gating: keep").
- No JS core bytes change, so no live re-qualification (plan §6). Every allowlisted plan must stay byte-identical: the
  allowlist and plan-sha tests pass **unedited** (regression oracle).

## Where to start
- **Branch:** create `claude/stage-c-<suffix>` from the LOCAL branch `claude/s2-followups-dsk-deck-902af1` (not
  pushed; local branches are shared across worktrees). It holds: `87ab7240` (count only animated bridges),
  `e6649cc6` + `d900b20b` (DSK converter publishes H.264 CRF 14 — `_crop_encoder_args("h264")` is the encoder the
  plan reuses), and both plans. Rebase onto it if it moves; never rewrite it.
- **Worktree env:** `uv sync --frozen --all-extras --all-groups`; symlink the main checkout's
  `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx` (see memory `worktree-env-setup`). A 3.10 floor venv:
  `UV_PROJECT_ENVIRONMENT=<scratch>/venv310 uv sync --frozen --all-extras --all-groups --python 3.10`.
- **Test beds (git-ignored, in the S2 follow-ups worktree — read or copy, never edit in place):**
  - Minimal Alpha_DSK export (HEVC `untitled.mov` ×6 copies, ProRes LT `clip-10-*` ×2 each, H.264 WA0125):
    `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/output/.html-preview/59cb220d674317326e710ccdc7d65fe1d7e473c83646227d2f691e6373d6fa0c-p3-r1/html`
  - Alpha_DSK, current deck (11 slides, 1 skipped; all five movies H.264 → conversion is a no-op):
    `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/output/.html-preview/7e3c930194d00effe3a21ee0e86a20baddb74223f661b9fa23186282aaf7081d-p3-r1/html`
  - Dashboard result JSONs (slides with playerIndex/exportedUuid):
    `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-s2-followups-dsk-deck-902af1/6310093a-f359-4c10-bce6-f040a588f20d/scratchpad/exports/{Alpha_DSK,Minimal_Alpha_DSK}.result.json`
    (Minimal's JSON points at the old `59cb…` root above; Alpha_DSK's at `7e3c…`).
  - Offline derivations today (S2 code + `87ab7240`): Alpha_DSK derives with 4 `overlap` refusals (5→6, 6→7, 7→8 ×2),
    Minimal with 2; both fail only the allowlist. Alpha_DSK's new last slide (two stacked H.264 clips, Dissolve in, clip
    2 on click) adds no refusals; both clips play in headless Chrome.

## How to run it (roster, owner rules)
- Plan §7 work streams M / S / U / P → **parallel Opus implementers at effort MEDIUM**, one brief each, launched in one
  message, spawned INTO your worktree; the frozen contract (plan §5) goes in every brief. Then one **Codex GPT-6 Astra
  (high)** review of the combined diff (`codex exec -m gpt-6-astra -c model_reasoning_effort=high -s read-only -o out.md
  "$(cat p.md)" < /dev/null`), F3 stop rule: fold blockers/majors, ignore ≤ medium, no scope creep.
- Briefs: minimal tests (plan §4: the fewest tests for the most coverage); foreground long runs, no polling; scratch in
  your session scratchpad, never the main checkout's `output/`; tests `-n 2` or none until you say go.
- **Machine:** one heavy job machine-wide. Message peer sessions ("need window" / "done") before suites, Chrome runs or
  big encodes: the S2 follow-ups session and the dissolve session (`brave-goodall-bd9851`, branch
  `claude/keynote-live-dissolve-crossfade`). Load guard: diagnose and escalate within ~1 min (memory
  `feedback-load-guard-escalate`).
- **Keynote is hands-off** (owner's go per run; `pgrep -x Keynote` only). G5 needs the owner's prepare in the dashboard.
- Gates (plan §6): G1 full suites 3.12 + 3.10 floor (+ `npm run test:ui` / `test:maps` for WS U, with the bundled Node
  on PATH: `PATH=~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH`); G2 `convert_movies` on a
  COPY of the Minimal export (3 encodes; derive_plan equal before/after); G3 Alpha_DSK no-op; G4 headless smoke + API
  start of Alpha_DSK with continuity `unsupported` (allowlist) and no 409; G5 owner.
- **Never merge or enable auto-merge.** One integration PR for Stage C against `main` (stacked on the S2 follow-ups
  branch until that lands — say so in the PR body); the owner merges.

## Owner decisions that still govern (not reopenable)
Pin hold accepted; R9; a runtime carry refusal lasts until the next go-to; main freeze bracket option A; decision 14;
instrument scope = catch what the owner's eyes can catch (no theoretical tightening); exact canonical asset matching;
objectID-only runtime identity. DSK converter clips are H.264 CRF 14 (owner: no DSK clip needs real alpha).

## Hand back
When C's PR is up: post its URL and gate tallies to the S2 follow-ups session, update this handover's status line,
and draft memory notes for the owner's main session (subagents cannot write memory).
