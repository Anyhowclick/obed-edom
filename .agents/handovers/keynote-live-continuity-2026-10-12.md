# Handover: live continuity after S2 (2026-10-12)

Read this first. It supersedes `keynote-live-continuity-2026-10-11.md` (deleted; `git show 1a169482:.agents/handovers/keynote-live-continuity-2026-10-11.md`
for the S2 history, recipes and run logs). Verify state on GitHub before acting. Evidence paths are in the MAIN checkout's
git-ignored `output/evidence/`.

## Where everything is
| Thing | State |
|---|---|
| S2 | **Merged #259 (`1a169482`, 2026-10-12).** Gate record `.agents/reviews/continuity-generalisation/gates-r1.md` (Q1–Q7 PASS at `ecf1b553`, owner Q7 on D1–D6). Plan `.agents/plans/keynote_live_continuity_generalisation.plan.md` (S2 done, review log inside). |
| Allowlist | `QUALIFIED_PLAN_SHA256` = P2 off/on, p2-loop off/on, D1–D6 (D2-across shares D2's plan). |
| Evidence | `output/evidence/s2-dev/instr-v-ecf1b553/final/` (final gates, Phase D, Q6, Astra r26), `instr-v-8bdaf582/final/` (V2b, serial, V5), `instr-v-9d4fbef5/decision14/` (seek pixel check), `s2-dev/live-logs/<worktree>/` (host logs of every gate worktree). |
| Worktrees / branches | All S2 gate worktrees trashed; `claude/s2-detach-fix` merged. |
| Dissolve cross-fade | Separate owner-started session (`brave-goodall-bd9851`, branch `claude/keynote-live-dissolve-crossfade`); DX-1/DX-2 in progress. |

## Next steps
1. **S3 — delete the allowlist (owner's call, OQ-8).** Python + docs only, no JS bytes, so no re-qualification. Owner's
   conditions (plan §6 OQ-8): Q1–Q7 green with every red recorded red (done), D1–D5 (+D6) pass headless, real OBS and the
   owner's eye (done), the negative corpus covers every refusal code, and one real sermon deck dry-runs clean or with named
   refusals. Until then decks join the allowlist one at a time.
2. **Rebuild the 8 stripped P2 fixture variants** with the strip fix (`715cb3f1`) and re-pin their digests (owner
   2026-10-11). Until then P2 shows grey squares on transparent pages.
3. **Main checkout compat symlinks** `output/<name>` → `output/fixtures/<name>`: delete once no live branch reads the old
   paths (check the dissolve branch first).
4. **Dissolve follow-up (owner, 2026-10-11 Q6):** stopping S2's held decoder at the outgoing transition start is a
   follow-up PR now that S2 has merged (the dissolve patch itself stays player-only).

## Open items (owner-raised or found; symptom / expected / evidence)
1. **Dissolve pop-in on transparent pages** — slide 3 pops in; Keynote cross-fades. Cause: the export's CSS dissolve fades
   only the outgoing layer over a fill-less texture. Fix in the dissolve session. Evidence `s2-dev/dissolve-alpha-2026-10-11/`.
2. **Non-carried outgoing movie fades out on frame 0** (seen at Q7 on D4 S1→S2) — the export bakes the clip's opening
   frame into the transition texture; Keynote freezes on the current frame. Dissolve patch F3. Not S2.
3. **End of show** (deferred by owner): D1–D3 hold the carried movie at end of show; D5 ends empty. Resume options: a
   scene count in the schema-2 plan, or read `__obedLive`.
4. **SUPERSEDED by Stage C (owner, 2026-10-13):** start is never gated on continuity; see
   `.agents/plans/keynote_live_continuity_stage_c.plan.md` §3.3. Was: **Dashboard gating** (owner: keep): a continuity-refused deck cannot start even with continuity off. The fresh
   `Minimal Alpha_DSK` export refused on main before S2 ("ambiguous 'untitled.mov' ownership at 7 -> 8"); re-check it on
   the S2 qualifier before treating it as still blocked.
5. **Show OBS cannot surface the tray-minimised managed OBS** ("no available windows"; the button only appears on
   `obsWaiting`/`stuck`). Q7 previews used `chrome://inspect` on the managed CDP port (`ak-engine.json` `cdpPort`, new per
   launch; never press Close there — it closes the page → `obsPageLost`).
6. **`scripts/live_fixture_session.py`**: the CDP keepalive timed out on a hidden HDMI window before the first `s`
   (continuity off, D6). Field tool only.
7. **Instrument follow-ups (non-blocking, Astra-classified):** force-wrap 1to2 @375 always lands ~535–586 ms (INVALID =
   retake); `managed_obs_qualify` latelost take INVALID because the validity read has no movie after the KB (same on main);
   r21 P3 exact legacy rescore vs a renamed coverage diagnostic; r23 P3 paint window-edge interval; wrap excuse trusts
   `unwrap_clock` (no recorder alignment); D-deck pin windows open only 84–100 ms before the press; plus the r10–r17
   MINORs listed in the old handover §7/§7b (`git show` above). Owner rule: fix what the eye can catch — bring
   theoretical findings to the owner with their gate cost rather than folding them.
8. **Watch items:** the carry-cover null control can read inconclusive under round load (re-run at `GATE_JOBS=1`, never
   widen the gap); carry-cover thresholds are P2-calibrated and also run on D1; the strip rule rounds left/top up but
   right/bottom down (1 px; fix separately, never to pass a deck); with ≥ 2 playing movies Chrome animates at 30 fps.

## Owner decisions (still governing)
- Instrument scope (2026-10-12): catch what the owner's eyes can catch; paint coverage judges an unobserved gap at the
  slower side's cadence. Decision 14: the loop-wrap `seeking` frame is excused (readiness only; pixel-checked).
- Exact canonical asset matching everywhere; identity first, then source (rules A/B, 2026-10-11).
- Pin hold accepted (a pinned movie paints above authored content during its move). R9 = movie not fully opaque. A
  runtime carry refusal lasts until the next go-to. Main freeze bracket option A (never relax `firedVia`, marker
  identity, the 1 px detector).
- Pass G: no-consumption = settled position + exact auto-run kinds; runs inside `run_gates` (full tier).
- Reviews on GPT-6 Astra (high) while the owner's resets last; Codex `gpt-5.6-sol` otherwise.

## Machine / coordination
- One heavy job at a time machine-wide; message peer sessions before suites, gates or OBS. `run_gates` refuses above
  load 4; timed runs start below 3. `mediaanalysisd` (Photos analysis) can hold baseline load ~4: `killall mediaanalysisd`
  (no sudo; it restarts on demand).
- Gates from a fresh detached worktree with `output/{bank,evidence,fixtures}` links; `main` worktrees also need the
  `output/{p2-recovery,p2-binary,p2-loop}` compat links until item 3.
- Dashboard tests need the bundled Node on `PATH`:
  `PATH=~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH npm run test:ui` (system Node 16 lacks
  `node --test`).
- OBS: the owner launches it (`--remote-debugging-port=9222`); never drive it without the owner's go.
