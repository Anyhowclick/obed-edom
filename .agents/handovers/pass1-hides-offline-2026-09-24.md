# Handover — pass-1 hides offline, resume (2026-09-24)

Supersedes `pass1-hides-offline-2026-09-23.md` for this work. Plan and single source of truth:
`.agents/plans/pass1_hides_offline.plan.md`. Read its §Owner decisions 1–5c and §Review log first.

## Where things stand

- **Branch:** `claude/pass1-hides-offline`. It is local and unpushed, based on origin/main 5b3b55e8. Its worktree is
  `.claude/worktrees/pass1-hides-offline-review-0930ce`.
  - Before pushing or opening a PR, merge `origin/main` and rerun the suites.
- **Built:**
  - Writer: `src/obed_edom/iwa_hides.py`.
  - Wiring and the AppleScript fallback: `offline_write.py` and `remap_keynote.py`.
  - JS deferral: `remap_keynote.js`.
  - Comparison checker: `scripts/deck_decode_diff.py`.
  - Dashboard abort UX: `web/app.py`, `ResizeTab.tsx`, `HistoryTab.tsx`, `api.ts`.
  - `needsKeynote`, `maskGeom` and `maskedDescendant` on offline payload items: `offline_inspect.py`.
- **Flag:** `OBED_OFFLINE_HIDES` defaults to off. It flips to on only after a GREEN live gate (owner decision 2, todo `g-flip-docs`).
- **Offline evidence at HEAD:**
  - FRC dry run: 129 slides, 929 hides, 0 refused, verify passes, 44 orphan `Data/` dropped.
  - Slides 20 (twin risk) and 122 (builds) are excluded before deferral and stay on the Keynote delete.
  - Stage time: 24.4 s at load average ~5; 37.6 s at load ~35, which is not comparable. Re-time on a quiet machine.
  - `planSha256` is unchanged.
- **Suites at HEAD:** pytest 6455 passed, 86 skipped, 1 xfailed; node tests ok; test:ui 248; test:maps 542 + 2; tsc clean.
- **Round 7 (Sol S6 fixes) is committed but not dry-run.** The FRC figures above are from round 6. Round 7 added a refusal for a
  header reference with no decoded body counterpart. That rule is unmeasured on real decks and could refuse real hides, and under
  decision 4 a post-save refusal aborts the run.

## Review state

- **Rounds so far:** C1 (Sol), A1 (Astra H advisory), A2 and A3 (Astra H), S4 and S5 (Sol H).
  - All findings are closed except those listed under the S6 line of the review log.
  - The owner switched the reviewer back to **GPT-5.6 Sol, high effort**:
    `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s read-only -o out.md "$(cat p.md)" < /dev/null`.
- **Raw rounds:**
  - They live in the worktree's git-ignored `output/pass1-hides-offline-review/`: `*.prompt.md` and the outputs.
  - Pass the previous rounds to each new round so it can classify findings and check that fixes closed.
  - Delete them once the item lands; the plan's review log is the durable record.
- **Stopping rule:** the owner hasn't set one. The coordinator's rule has been to continue until Sol returns no BLOCKER or MAJOR.

## Next steps

1. **FRC dry run first**, at load average under 10: an APFS clone in the scratchpad, trashed afterwards, recording `uptime`.
   - Gates: 0 refusals; only slides 20 and 122 excluded; stage ≤ 30 s; `planSha256` unchanged.
   - If the header-only-ref rule refuses real hides, list the fields and decide with the owner.
2. Sol H round 7 on HEAD. Give it the previous raw rounds (`sol-r6.md` and earlier), then fix, rerun the suites, and commit until it returns no BLOCKER or MAJOR.
3. **Live gate** (`f-live-gate`, plan §Oracles O1–O4 and §Gate). This needs the owner's go or a peer's all-clear, because
   Keynote is shared with the AK and GL-replay sessions. Add these to the plan's gate:
   - Live-only checks:
     - In a real AppleScript fallback session (force it with `OBED_DEBUG_HIDES_REFUSE=<eligible slide>`), `POSIX path of ((file of d) as alias)` works.
     - The `do shell script` path check works.
     - Close is confirmed.
   - Owner playback of 2–3 Magic Move transitions into and out of hide-heavy slides on the B final deck (owner condition, decision 1).
   - Keynote opens the patched deck with no repair prompt: Metadata/`Data/` removal has only offline precedent for additions.
   - Interleaved A/B pairs: A,B then B,A, with `uptime` per run. Whole run ≥ 45 s faster; `runJxa` ≥ 60 s faster.
4. After a GREEN gate: `g-flip-docs` (default on; README, SKILL.md §Offline writes, and the `pass1_profile.plan.md` todo),
   one integration PR, never merge.

## Implementer roster used

- Planners: both Opus at extra-high (the new default).
- Implementers: Opus at medium effort, split by disjoint files:
  - A: the checker.
  - B: the writer, plus `offline_inspect.py`.
  - C: the JS.
  - D: the wiring.
  - E: the dashboard.
- Resume these peers by name if they are still live. Otherwise brief fresh ones from the plan.
