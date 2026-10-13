# Handover: Stage T orchestration (2026-10-13)

Read this first, then the plan. You coordinate Stage T in your own worktree. The S2 follow-ups session (branch
`claude/s2-followups-dsk-deck-902af1`) owns Stage B and must not be disturbed.

## What and why
- **Plan:** `.agents/plans/keynote_export_texture_repair_stage_t.plan.md`, rev 2, **APPROVED** by the owner 2026-10-13,
  every OQ per its recommendation: OQ-T1 fail the prepare and name slide + object; OQ-T2 repair text **and** posters;
  OQ-T3 refuse only on a confident OCR contradiction; OQ-T4 deferred; OQ-T5 add fixture `alpha-dsk-textures`;
  OQ-T6 C → T → B, S3 in parallel.
- **Problem:** Keynote's HTML exporter gives two different textures the same id within one slide; the player looks
  ids up per slide (dict) so one page is lost and every leaf with that id draws the survivor. On the owner's real deck
  `Alpha_DSK` this puts movie posters inside the slide-10 text labels and the divider into a slide-9 label (visible on
  air in any renderer, OBS included), and makes 9→10 crossfade WA0125 from WA0121's poster.
- **Goal:** detect and repair in the cached export copy at prepare time (`apply_preview`, before Stage C's
  `convert_movies`); never the `.key`; refuse by name when no verified donor exists. Continuity plans stay
  byte-identical; fixtures never pass through prepare and are never rewritten.

## Where to start
- **Stage C is merged** (#264, `main` @ `eb1fb6d2`): `src/obed_edom/preview_movies.py`, the `apply_preview` /
  `load_cached` hooks, `manifest.movieConversion`. T mirrors that shape (`preview_textures.py`,
  `manifest.textureRepair`, `load_cached` gate).
- **Branch:** create `claude/stage-t-<suffix>` from the LOCAL branch `claude/s2-followups-dsk-deck-902af1` (main +
  5 plan-doc commits incl. this plan and Stage B rev 3.1; not pushed — local branches are shared across worktrees).
  Your PR therefore also carries those plan docs; say so in the body. Never rewrite that branch.
- **Worktree env:** `uv sync --frozen --all-extras --all-groups`; symlink the main checkout's
  `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx` (memory `worktree-env-setup`); 3.10 floor venv via
  `UV_PROJECT_ENVIRONMENT=<scratch>/venv310 uv sync --frozen --all-extras --all-groups --python 3.10`.
- **Evidence (scratch, read or copy, never edit):**
  `/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-s2-followups-dsk-deck-902af1/6310093a-f359-4c10-bce6-f040a588f20d/scratchpad/`
  — `textures/` (investigator: `detect2.py`, `plan_repair.py`, `textslots.py`, `graft/` dry-run, `pages/`), the
  critic's `r6g.py`, `oracle.py`, `d1check.py`, `landing.py`, `shared_ids.py`, `r6fp/`, and `goto10.py` (headless
  pattern for G2; call `host.execute("show")` first — the output starts behind a black cover).
- **Exports (git-ignored, in the S2 follow-ups worktree; copy before writing):**
  - Alpha_DSK current (all true hits; fully repairable):
    `/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/s2-followups-dsk-deck-902af1/output/.html-preview/7e3c930194d00effe3a21ee0e86a20baddb74223f661b9fa23186282aaf7081d-p3-r1/html`
  - Alpha_DSK earlier (expected refusal naming both tag boxes):
    `…/output/.html-preview/3b9019f068d8ef1c14e586c86e75274a2bebad3c65116fd2247362ed9f39a7e3-p3-r1/html`
  - Minimal Alpha_DSK: `…/output/.html-preview/59cb220d674317326e710ccdc7d65fe1d7e473c83646227d2f691e6373d6fa0c-p3-r1/html`
  - Result JSONs (slides): `<scratchpad>/exports/{Alpha_DSK,Minimal_Alpha_DSK}.result.json`.
  - Gate fixtures: main checkout `output/fixtures/` (`src/obed_edom/fixture_paths.py`); D2 has two real poster →
    black-background hits (hidden on air).
- **Fixture (OQ-T5):** add `alpha-dsk-textures` to `FIXTURE_NAMES` (7e3c JSON + PDF + pdfp, no movies, ~40 MB);
  copy into the main checkout's `output/fixtures/` only as the finished artefact (writes there prompt the owner).

## How to run it (roster, owner rules)
- Plan §5 work streams T1/T2/T3 → parallel Opus implementers at effort MEDIUM, one self-contained brief each with the
  frozen contract (`manifest.textureRepair` shape, `repair_textures` signature, refusal text), spawned INTO your
  worktree. Then Codex GPT-6 Astra (high) on the combined diff (`codex exec -m gpt-6-astra -c
  model_reasoning_effort=high -s read-only -o out.md "$(cat p.md)" < /dev/null`). Review folding: rounds 1–3 fold
  mediums and lows too (owner rule relayed 2026-10-13 by the Stage C session); stop when a round is clean.
- Briefs: minimal tests (plan §3); foreground long runs, no polling; scratch only in your session scratchpad; tests
  `-n 2` until you say go.
- **Machine:** one heavy job machine-wide. Message peers ("need window" / "done") before suites or Chrome: the S2
  follow-ups session and the dissolve session (`brave-goodall-bd9851`). Load guard: diagnose and escalate within ~1 min.
- **Keynote is hands-off** without the owner's go.
- Gates (plan §4): G1 offline detector + repair over all exports reproduces the plan's table; G2 headless
  (continuity off): settled slide 10 labels vs Keynote's flattened frame `AF8F0F`, OCR of slides 8/9 labels, 9→10
  mid-frame poster — G2 is also the first proof pdf.js renders grafted pages; G3 plan shas and S3 corpus unchanged,
  GL-replay gates re-run on the repaired Alpha; G4 owner's eye (Chrome + managed OBS Keyer). Full suites 3.12 + 3.10
  floor (+ `npm run test:ui` if UI changes).
- **Stage B note:** B's feed bindings must come from the REPAIRED JSON (sizes change: 9→10 WA0125 `from` 715×402 →
  714×402; a label draw 13×404 → 223×36). Report the repaired Alpha's draw/upload table to the S2 follow-ups session.
- **Never merge or enable auto-merge.** One integration PR for Stage T against `main`; the owner merges.

## Owner decisions that still govern (not reopenable)
Fail closed and name things (OQ-C1/OQ-T1); objectID-only identity (no rect-based movie matching); exact canonical
asset matching; instrument scope = what the owner's eyes can catch (no theoretical tightening); pin hold; R9; refusal
until next go-to; freeze bracket option A; decision 14. DSK converter clips are H.264 CRF 14.

## Hand back
When T's PR is up: message the S2 follow-ups session with the URL, gate tallies and the repaired Alpha draw/upload
table; update this handover's status line; draft memory notes for the owner's main session.
