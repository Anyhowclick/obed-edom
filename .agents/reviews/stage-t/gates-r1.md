# Stage T gate record, round 1 (2026-10-13)

Plan: `.agents/plans/keynote_export_texture_repair_stage_t.plan.md` rev 2 (approved, every OQ per its recommendation).
Branch `claude/stage-t-orchestration`. Implementers: three Opus 5.5 (effort medium) streams T1/T2/T3. Reviewer: Codex
GPT-6 Astra, effort high (owner 2026-10-13: the reviewer's model class differs from the implementers').

## Review (Codex GPT-6 Astra, effort high)
| Round | Scope | Result |
|---|---|---|
| r1 | `aba1a7a0..b9902352`, all severities | 1 major (new class: grouping let one event's text identity donate to a swapped label in another event), 4 medium (an R1 hit on an unrelated leaf barred a valid D2 donor; V4 skipped companions of untouched slides; missing evidence confirmed G2's negative control; G1 could pass without its positive controls), 1 low (non-poster image grafts recorded `verify: {}`). All folded in `d6142d66`. |
| r2 | the fold plus the whole diff, all severities | 1 major (closed class: an unattributed image borrowed a movie's identity through grouping), 3 medium (raw-text grouping split NFKC-equal labels; an R6 reference still barred a valid D2 donor; stationary noise could stand in for G2 move evidence). Folded in `4f276c27`. |
| r3 | the fold plus the whole diff, all severities (last round folding medium/low) | 2 major (same class: a flattened copy joined two movie groups; text and image leaves shared a group), 1 low (G1 did not require its clean controls). Fixed by class, not per finding: bad leaves are partitioned into groups that are provably one object (same id and rect, never text with non-text, equal normalised text, at most one movie owner, ambiguous copies refused by name), with a closing sweep of every group-level read. Folded in `d8431485`. |
| r4 | the fold plus the whole diff, major/blocker only | 1 major (same class: the ownership check was centred on the current hit, so a copy between two movies 0.4 px apart could take the wrong poster). Folded in `d1e73254` (owners collected around each copy itself). |
| r5 | the fold plus the whole diff, major/blocker only | No blocker or major findings. All six hit orders refuse the ambiguous copy; Alpha keeps its five groups. Loop closed. |

## Gates
| G | Run | Result |
|---|---|---|
| G1 | `scripts/texture_repair_check.py g1` over 28 exports, on temp copies (final commit) | PASS, exit 0. Alpha 7e3c (fixture `alpha-dsk-textures`): 6 JSON hits → 5 groups repaired, D1×1 (slide 8 label `B95077→67C064`, OCR "Sunday Service"), D3×1 (slide 9 WA0125 poster `309718→CF6BC1`, 4 leaves, corr 1.0), D2×3 (slide 9 label ← slide 8 p13, 3 leaves; slide 10 "Children's Church" ← slide 9 p19; slide 10 "Sunday Service" ← slide 9 p20); 0 hits after; 2 PDFs rewritten (+19 KB, +9 KB); 0.93–1.09 s. D2: 2 groups via D3 (`E606C252`, `B07083CF`); D2 across-first-build: 1 via D3. 3b9019: refused, "Cannot repair Keynote's HTML export: slide 9 (288×78 image): …; slide 10 (287×77 image): its texture is mis-mapped and no verified replacement exists". The 24 clean exports (D1, D2-across, D3–D6, p2-* ×15, gl-decks ×2, minimal-alpha-dsk-17c0c938, Minimal 59cb): 0 hits. Null controls: a missing D2 or D1 export → FAIL exit 1. |
| G2 | `texture_repair_check.py g2` (headless `LiveOutputHost`, continuity off, GL replay off) on a scratch copy of the full 7e3c export; `--no-repair` arm first | Repair arm: (b) PASS: OCR of slide 8 "Sunday Service", slide 9 "Children's Church" and "Sunday Service" all match. (c) PASS: WA0125 identified in its slot through the whole 9→10 move (mid-frame p 0.54: WA0125 0.943, WA0121 0.083). (a) FAIL by the plan's 0.9: label crops vs Keynote's flattened frame `AF8F0F` 0.836 / 0.823, but the untouched "Bible Study" label (never mis-mapped, the in-frame positive control) scores 0.826 in both arms, so screen-vs-Quartz rendering caps (a) at ≈0.83; by eye the repaired labels equal the oracle. No-repair arm: (a) FAIL measured (−0.017 / −0.123: movie posters inside the labels); (b) FAIL (OCR empty on the two mis-mapped labels); (c) INCONCLUSIVE by the strict r2 rule (no mid-move frame identifies a poster at 0.9 while the wrong poster cross-fades out), though the raw frames identify WA0121 in WA0125's slot at the start of the move (0.946). First proof pdf.js renders grafted pages: the slide 10 labels come from pages grafted from slide 9. |
| G3 | Plan signatures before/after repair; feed table | PASS. `derive_plan` (gl_replay off and on) on the repaired Alpha copy: `as_dict()` and refusals equal (4 `overlap`); its runtime is still refused by the allowlist on this base, so GL replay cannot run on Alpha until S3 lands. D2 and D2 across-first-build repaired copies keep the qualified signature `029a4c42…`. Fixtures never pass through repair; the 24 clean exports are untouched by it (G1). Stage B feed table (from the repaired JSON, `glfeed/spec.py` walk): draws/regular uploads unchanged, 5to6 5/7, 6to7 9/12, 7to8 12/17; 9→10 changes draw 4 WA0125 `from` 715×402 → 714×402 and draw 8 13×404 → 223×36 (table below). |
| Suites | `pytest tests/ -n auto --dist worksteal`, 3.12 and the 3.10 floor | Pre-fold (`b9902352`): 3.10 10791 passed, 36 skipped, 0 failed (3.12 before the census fix: 4 census failures from the new fixture, owner-approved exclusion). Final code (`da2a1c24`): 3.12 10791 passed, 36 skipped, 1 xfailed, 0 failed; 3.10 floor the same. No UI change, so no `test:ui`. |
| G4 | Owner's eye: slides 8, 9 and 10 on air in Chrome and the managed OBS Keyer | PASS (see below). |

## G4 attempt and follow-ups (2026-10-13)
- **First G4 prepare:** Keynote launch failed with -600 at the script's `activate` (chars 127–135). Not obed-edom code: every
  launch path worked once Keynote had been launched once via `open -b` (pane, Terminal, both Pythons, direct export,
  dashboard). One-off macOS launch state; nothing changed.
- **Second prepare refused** "slide 10 (582×327 image)" (export deleted, not inspectable). A direct export at 17:02 refused
  "slide 9 (288×78 image)". Fresh exports of the same deck collide differently. Owner reopened OQ-T4 + OQ-T1 (plan §7 note).
- **D4 + one re-export** (`8fb590af`, Opus implementers), reviewed by Codex GPT-6 Astra high r1 (1 major: D4 trusted a landing
  the same pass re-points; 1 medium; 1 low). Folds by Codex GPT-5.6 Sol high (owner: next-round folds by Sol), reviewed by
  Opus 5.5 high: r2 1 medium (from == to landings), r3 1 major (same class in D2: `_trusted_landing` shared by D2/D4),
  r4 no major/blocker, loop closed. Commits `3ac983b3`, `335f4f4e`, `e7c75a19`.
- **Prepare output modal** (Codex Sol; Opus 5.5 high review r1: 1 major duplicated logs, 3 medium, 4 low; r2: 1 medium CSS
  cascade, 1 low; folded): errors red, output lines in the accent colour (owner). Commits `12120fa1`, `7c64d5a1`, `eb6612a0`.
- **Re-gated on `e7c75a19`:** G1 PASS over 28 exports (3b9019 now refuses only "slide 10 (287×77 image)": D4 repairs slide 9;
  slide 10 has no same-slide candidate). The 17:02 direct export repairs 3 (slide 9 tag box D4 → `CE49CEF4` corr 1.0, slide 10
  WA0125 poster D3, slide 10 label D2). Suites 3.12 and 3.10: 10799 passed, 36 skipped, 0 failed; `test:ui` 321/321.
- **Later commits:** prepare status line in the accent colour (`50d3f098`) and an always-on texture-check log line
  (`69e31238`), Codex Sol, Opus 5.5 high review: no findings. Suites on `69e31238`: 3.12 and 3.10 10799 passed, 0 failed;
  `test:ui` 321/321. After merging main (S3 #266) at `4e3b7464`: 3.12 and 3.10 10813 passed, 0 failed; `test:ui` 321/321.
- **G4 PASS (owner, 2026-10-13, Chrome + managed OBS Keyer, on `e7c75a19`+):** text and pills transited correctly 8→9→10.
  The prepared export happened to have no collisions ("Checked textures" path), so repaired pages were not on air; G2 covers
  repaired-page rendering. Owner observations outside Stage T, filed as separate tasks: continuity off → freeze-frame
  fallback (allowlist; S3); pill backgrounds darken in-move; slide 11 plays only the latter stacked video (Stage C G5 fails);
  non-MM slide changes do not dissolve; MM freeze frames lag a few frames behind the playing frame.

### Repaired Alpha_DSK feed table (Stage B)
Regular uploads only (hand-back uploads follow them). `→` = the leaf's `contents` to-texture.

| Move (ord) | Draw | Upload | Size | Note |
|---|---|---|---|---|
| 5to6 (6→8) | 1 | #1 → #2 | 1920×1080 → 1920×1080 | |
| | 2 | #3 | 960×276 | retiring h264 |
| | 3 | #4 → #5 | 484×272 → 824×463 | movie WA0125 |
| | 4–5 | #6, #7 | 259×59, 224×36 | hidden |
| 6to7 (8→9) | 1 | #1 → #2 | 1920×1080 → 1920×1080 | |
| | 2–3 | #3, #4 | 715×402, 405×13 | hidden |
| | 4 | #5 → #6 | 824×463 → 714×402 | movie WA0125 |
| | 5–6 | #7, #8 | 288×78, 256×31 | hidden |
| | 7 | #9 | 259×59 | label box |
| | 8 | #10 → #11 | 224×36 → 223×36 | |
| | 9 | #12 | 231×111 | hidden |
| 7to8 (9→10) | 1 | #1 → #2 | 1920×1080 → 1920×1080 | |
| | 2 | #3 → #4 | 715×402 → 582×327 | movie WA0121 |
| | 3 | #5 | 405×13 | |
| | 4 | #6 → #7 | **714×402** → 582×327 | movie WA0125 (was 715×402) |
| | 5 | #8 | 288×78 | label box |
| | 6 | #9 → #10 | 256×31 → 256×31 | |
| | 7 | #11 | 266×59 | label box |
| | 8 | #12 → #13 | **223×36** → 224×36 | (was 13×404) |
| | 9–10 | #14, #15 | 391×330, 330×13 | hidden |
| | 11 | #16 | 231×111 | label box |
| | 12 | #17 | 166×36 | hidden |

Scripts and logs are in the orchestrator session's scratchpad (`gates/`, `feed/`); raw review rounds are kept there until
the PR's review loop closes. Not retained after merge.
