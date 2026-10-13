# Handover: live continuity after Stage C (2026-10-13)

Read this first. It supersedes `keynote-live-continuity-2026-10-12.md` (deleted; `git show 000cacad:.agents/handovers/keynote-live-continuity-2026-10-12.md`
for the S2 history). Verify state on GitHub before acting. Evidence paths are in the MAIN checkout's git-ignored
`output/evidence/`.

## Where everything is
| Thing | State |
|---|---|
| S2 | Merged #259. Gate record `.agents/reviews/continuity-generalisation/gates-r1.md`. |
| Stage A (count only animated bridges toward the one-per-boundary limit) | On main via #264 (`87ab7240`). |
| DSK converter → H.264 CRF 14 | On main via #264 (`e6649cc6`, `d900b20b`). Keynote still exports ProRes LT; ffmpeg publishes libx264 yuv420p. Owner: no DSK clip needs real alpha. |
| Stage C (prepare-time H.264 conversion + partial continuity, no deck-start gate) | **Merged #264** (main `eb1fb6d2`). Plan `.agents/plans/keynote_live_continuity_stage_c.plan.md`; gate record `.agents/reviews/stage-c/gates-r1.md`. Owner G5 was pending at merge time — confirm with the owner whether it was done. |
| Stage T (repair Keynote HTML-export texture-id mis-mapping at prepare) | **APPROVED**, every OQ per rec. Plan `.agents/plans/keynote_export_texture_repair_stage_t.plan.md`; running in its own session (branch `claude/stage-t-orchestration`, handover `stage-t-orchestration-2026-10-13.md`). It will message this line of work with its PR, gate tallies and the repaired Alpha_DSK draw/upload table. |
| Stage B (carry under artwork via the GL texture feed; poster-hold fallback; N carries) | **Plan rev 3.1** (`.agents/plans/keynote_live_continuity_stage_b.plan.md`, `e1ee6f21`), critique r2 folded; **awaiting the owner's OQs** (§7: B2, B4, B5, B7, B8, B9, B10, B11 — all with recommendations). Not started. |
| S3 (delete the allowlist) | Next in the order after C, in parallel with T. Owner approved the order C → S3 → B (OQ-C2); confirm the go before starting. Parent plan §S3; negative corpus gains R11 (Stage C). |
| Branch | `claude/s2-followups-dsk-deck-902af1`: main merged at `000cacad` + plan/handover docs only (not pushed, no PR). Stage T's branch is cut from it, so T's PR carries these docs. |
| Real deck | `~/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key` (owner's real sermon deck; 11 slides, ordinal 7 skipped; all five movies H.264; last slide = FW slide 50's two stacked clips, Dissolve in, clip 2 on click — plays correctly, adds no refusals). Latest export `7e3c9301…` in the S2 follow-ups worktree's `output/.html-preview/`. Derives with 4 `overlap` refusals (5→6, 6→7, 7→8 ×2), fixed by B. |
| Evidence | `output/evidence/stage-b-2026-10-13/`: `glfeed/` (GL feed experiment: harness `instrument.js`/`spec.py`/`run.py`/`analyze.py`, results `out/run1`, `out/run2-direct*`, `out/run2-cmp/analyze.txt`, sheets `out/run1/sheet.png`/`sheet2.png`, slide-10 textures `out/slide10-tex/`), `textures/` + `critic-t/` (Stage T investigation), `critic-r2/` (B critique scratch), `mockup/` (OQ-B1 dip mockup, slide-10 compare), `consult-astra.md` + `consult-opus-peer-summary.md` + brief, `exports/*.result.json`, scripts (`export_decks.py`, `derive.py`, `goto10.py`, `slide11_check.py`, `mockup_capture.py`). H.264 copies made for the owner: `~/Desktop/Convert wall to 16x9 CGs/Untitled-H264.mov` (CRF 14; the deck still holds the CRF 16 copy — fine) and `src/*.h264.mov` (swapped in). |

## Next steps
1. **Owner OQs on Stage B rev 3.1**, then B waits for T and S3. Before B's contract freezes: the CEF dev-loop check of
   `texImage2D(video)` in OBS 127 (owner's OBS go), ≥ 10 real-clock runs for the first-feed stall, and B's feed
   bindings captured from the **repaired** Alpha export (Stage T).
2. **S3** (confirm the owner's go): Python + docs, no JS bytes; negative corpus per refusal code incl. R11; its own
   probe round on P2, D1–D6 and Alpha_DSK (dry run "with named refusals" now; "qualified" after B).
3. **Stage T**: review its PR when it lands (owner merges).
4. Carried from 2026-10-12: rebuild the 8 stripped P2 fixture variants with the strip fix (`715cb3f1`) and re-pin their
   digests; delete the main checkout's `output/<name>` compat symlinks once no live branch reads them; the dissolve
   follow-ups live in `keynote-live-dissolve-crossfade-followups.md`.

## Open items (symptom / expected / evidence)
1. **Slide-10 labels show movie posters** (Alpha_DSK raw export, any renderer incl. OBS) — expected: "Sunday Service" /
   "Children's Church" text. Cause: Keynote texture-id collision (plan T §1.2). Fix: Stage T. Evidence
   `stage-b-2026-10-13/glfeed/out/slide10-tex/`, `mockup/compare10.png`.
2. **9→10 crossfades WA0125 from WA0121's poster** (raw export, continuity off) — expected its own poster. Same cause;
   Stage T repairs it; the B feed overwrites it in-move.
3. **Tag dip** (OQ-B1, resolved by design): B feeds live video into the MM textures; poster hold (pause at departure,
   resume at settle, no restart) when the feed is unavailable (external attach) or stands down.
4. **Possible tone step at feed start/settle** (up to ~11/255 midtones, native vs GL video; gl-replay-managed finding) —
   owner to judge at Q7.
5. **End of show** (deferred, OQ-B4): carried movies stay held after the last slide.
6. **Show OBS cannot surface the tray-minimised managed OBS** (unchanged from 2026-10-12 item 5).
7. **`scripts/live_fixture_session.py`** CDP keepalive timeout on a hidden HDMI window (field tool only).
8. **Instrument follow-ups and watch items** — unchanged from 2026-10-12 items 7–8 (`git show 000cacad:` the old handover).
9. Dashboard gating (old item 4) is **superseded** by Stage C: continuity never blocks deck start.

## Owner decisions (still governing)
- Instrument scope: catch what the owner's eyes can catch; no theoretical tightening. Decision 14 (loop-wrap seek).
- Exact canonical asset matching; objectID-only runtime identity (no rect-based movie matching, Stage T M2).
- Pin hold accepted; R9; a runtime carry refusal lasts until the next go-to; main freeze bracket option A.
- Fail closed and name things: real-alpha movies (OQ-C1) and unrepairable textures (OQ-T1) refuse the prepare by name.
- OQ-B1: GL texture feed is the design; poster hold is the fallback. Sliver requirement: video-on-video overlap draws as
  authored.
- Order: C ✓ → T → B, S3 in parallel. Reviews: Codex GPT-6 Astra (high); rounds 1–3 fold mediums and lows too (owner
  rule relayed 2026-10-13 via the Stage C session — confirm with the owner and record in memory if so).

## Machine / coordination
- One heavy job machine-wide; message peer sessions ("need window" / "done") before suites, Chrome or encodes. Peers:
  the dissolve session (`brave-goodall-bd9851`) and the Stage T session. `run_gates` refuses above load 4.
- Keynote: hands-off without the owner's go. A dashboard-style export from a script: `OBED_DSK_RSS_LIMIT_GB=8` (or
  #263's 6 GB default), unsandboxed, `propose_preview`/`apply_preview` (`output/evidence/stage-b-2026-10-13/export_decks.py`).
- Headless captures: `LiveOutputHost(..., headless=True, continuity="off")`, call `execute("show")` first (black cover).
  Port 8765 is the dashboard.
- Worktree tests need the worktree's own venv (`uv sync --frozen --all-extras --all-groups`), else pytest imports the
  main checkout's package.
