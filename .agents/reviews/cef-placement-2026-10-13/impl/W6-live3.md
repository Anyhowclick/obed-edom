# W6 live pass 2A: offline root cause of the remaining CEF-placement INCONCLUSIVEs

Read first: `.agents/reviews/cef-placement-2026-10-13/live3-2A-analysis.md` (coordinator analysis, table of causes).
Evidence (READ-ONLY, never write there): `/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/cef-placement-live-2026-10-13/live3/raw-out`
(25 fps run `runs/placement-20261013-231739.json`; 30 fps `placement-20261013-234036.json` is INVALID for sleep but its
sessions may still show whether a cause repeats). Per-session records/images under `shots/<run>/runs/<arm>/`.

Offline re-score tool: `SCR/tools/rescore.py <run.json> <clone root> <decision> baseline|patched <detail.json>` where
`SCR=/private/tmp/claude-501/-Users-anyhowclick-Desktop-work-obed-edom--claude-worktrees-angry-mestorf-abe88f/eb4a45b4-7a63-49ef-b6ef-a8cb4c5426c5/scratchpad`.
`placement_gates` REWRITES record.json, so always score an APFS clone: `cp -cR <raw-out> SCR/w6/<name>` (fresh clone per run).
Decision: `/Users/anyhowclick/Desktop/work/obed-edom/output/evidence/s2-dev/dissolve-alpha-2026-10-11/q0b-2026-10-11/runs/decision_record_q0b1.json`.
Run with `PYTHONPATH=src .venv/bin/python` from the worktree (or the main checkout's `.venv` if absent). One score ≈ a few minutes.

Tasks:
1. FIX (your files): `dissolve_probe.anim_problem` — a `paused` animation has an unresolved `startTime` with a resolved held
   `currentTime` (Web Animations); a running animation awaiting its pending play task may also have `startTime` null. Make the
   rule spec-faithful (null `ct` in a timed state stays a problem). Extend the existing anim/schema tests (parametrize) with the
   live shape `{"ct": 750, "start": null, "state": "paused"}` and the still-bad shapes.
2. ROOT-CAUSE each remaining non-MATCH arm after the fix, with file:line evidence from records/images and code. Classify each as
   PRODUCT (player/snap/managed path), HARNESS (driver/session setup), or INSTRUMENT (scorer), and as new vs inherited:
   - `m-snap-cef-near-y`, `m-snap-cef-nooffset-y` (+ twins): 0 holders, no bound decoder, paused reference None. Compare with
     the x-clip cells that MATCH. Is the y clip setup reaching the slide at all? Is it a product admission refusal (log it)?
   - `m-snap-cef-nooffset-x` (+ twin), `m-snap-cef-dsk`: "holder strip does not decode at its device scale"; dsk also
     "4 mid frames < 5".
   - `m-snap-cef`, `wrongrule-cef`: `holder_pixels` "no kept interior or edge-band px" with interior 2.0 / 183.0, edge null.
     Is an empty edge band legitimate for the no-clip cell (plan §5 `m-snap-cef[clip]` row: "interior **and edge** scoring")?
   - `m-tone-cef`: tone FAIL worst 12 LSB with identity map; relate to the W5 tone-map open item and the plan's tone row.
   - `m-tone-raw-cef`: "no twin to verify the production mask" — is the twin session missing from PLACEMENT_ARMS by design?
   - `cut-on`/`cut-off`: "no screencast frame inside [DOM insertion, cut completion]" — confirm inherited (parent DX-1 cut).
3. FIX only INSTRUMENT/HARNESS causes that are unambiguous and within your files, with the fewest test additions. Do NOT edit
   product files (src/), plan or contracts; for PRODUCT causes or any fix that changes a §5/§11 contract or an expected outcome,
   report the proposed fix with evidence and stop — the coordinator decides.
4. Re-score the 25 fps run with your final code (baseline mode of the tool, since the fix is now in-tree) and report the
   per-arm outcome table and remaining gate reasons.

Report → `SCR/impl/W6-live3-report.md` (create the dir): per arm cause/class/evidence/fix-or-proposal, files changed, tests
run with exact counts, the re-score table, open items.
