# Alpha movies increment 1 — gate record r1

Plan: `.agents/plans/keynote_live_alpha_movies.plan.md` (rev 3 + owner decisions §9). Branch `claude/alpha-movies-inc1`.
Roster: plan Codex GPT-6 Astra high; plan critique Opus 5.5 high (3 rounds); implementation Codex GPT-5.6 Sol high
(4 rounds); code review Opus 5.5 high (2 rounds, verdict approve). Evidence below is results only; raw probe
captures were session scratch (outside every `output/`), not retained.

## Step 0 / AM-0 — decode and alpha compositing (2026-10-15)

Inputs: F2 `PIN DROP WAVE.mov` (ProRes 4444, 500×500, 25 fps, 66 frames) and its CRF 20 VP9-alpha WebM (246,543 B),
the same bytes named `.mov`; negative controls opaque H.264 and opaque VP9 of the same clip. Served by the product
`_AssetServer` (Range 206 recorded). Seeks 0.2 / 1.0 / 2.0 s, `requestVideoFrameCallback` mediaTime exact (frames
5 / 25 / 50). RGBA captures: CDP `Page.captureScreenshot` with transparent background (Chrome); OBS
`GetSourceScreenshot` on `Program` (CEF), scale 1.0. Classes = source alpha 0 / 255 eroded 2 px.

| Output | Engine | VP9-alpha (.webm and .mov) | Opaque controls | Scorer null |
|---|---|---|---|---|
| Headless Chrome | Chrome 155.0.8059.79 | PASS ×6 | REJECT ×6 | 0 / 0 |
| Headful Chrome (owner-approved window) | Chrome 155.0.8059.79 | PASS ×6 | REJECT ×6 | 0 / 0 |
| Managed OBS 32.2.2, 25 fps | CEF Chrome/127.0.6533.120 | PASS ×6 | REJECT ×6 | 0 / 0 |
| Managed OBS 32.2.2, 30 fps | CEF Chrome/127.0.6533.120 | PASS ×6 | REJECT ×6 | 0 / 0 |

VP9-alpha numbers (identical on every output; CEF alpha bit-identical to headless Chrome): zero class ≤2 at
100 % / 100 % / 99.998 %; opaque class ≥253 at 99.875 % (4,008 px) / 99.993 % (43,636 px) / — (no opaque pixels at
2.0 s); alpha MAE 0.011 / 0.100 / 0.071, p99 0 / 3 / 2. Controls keep 100 % of source-transparent pixels opaque.
`VideoFrame.colorSpace` = smpte170m / smpte170m / bt709, limited range — outside the freeze tuple, so freeze refuses
on the tuple first (expected; freeze unchanged).

## AM-1 — offline F2 conversion (no Keynote)

Scratch copy of `F2-html` under a scratch `OBED_EDOM_OUTPUT_ROOT`, `manifest_from_export` + real `convert_movies`:
- Baseline (main): refuses "pin drop wave.mov: it has transparency, and H.264 has none".
- Candidate: converts only `PIN DROP WAVE.mov` → VP9 alpha (246,543 B; `webm_info` V_VP9 500×500 2.64 s 25 fps
  alpha); every other file byte-identical; `unconverted` empty after; a second `convert_movies` converts nothing and
  changes nothing.
- Negative control (alpha encode forced to `yuv420p`): refused "lost transparency during conversion"; export
  byte-identical.

## AM-2 — full prepare without Keynote (HEAD e4d5f864, on main 60c53c85 with the #289 slide-4 fix)

Real `propose_preview` + `apply_preview` on current `F2.key` (`f99a68ef…`), `OBED_EDOM_OUTPUT_ROOT` =
`~/Desktop/Convert wall to 16x9 CGs/alpha-am2` (outside every `output/`), `export_html_fn` copying the retained
`F2-html` export of that deck: PASS. Texture repair "Repaired slide 4 176×205 image: D2" (1 repaired, no refusal), then
"Converting pin drop wave.mov to VP9 alpha"; manifest `movieConversion.converted[0].targetCodec` = "VP9 alpha"
(246,543 B); ready in 3.1 s. A second propose + apply reused the cache (0.6 s, export copy not called again).

## AM-3 / AM-4

Owner eye on the product path (HDMI Chrome, managed-OBS Keyer, beside native Keynote) — PENDING. Managed-OBS physical
fill/key at the DeckLink field test (owner D3).

## AM-5 — suites (rebased on origin/main 60c53c85, HEAD 62dde6c9)

- Python 3.13 worktree venv: 11027 passed, 38 skipped, 1 xfailed (252.8 s).
- Python 3.10.10 floor: 11027 passed, 38 skipped, 1 xfailed (317.9 s).
- Dashboard `npm run test:ui`: 44 files, 330 tests passed. `npm run test:maps`: 542 + 2 (perf) passed, 0 failed.

## Review log

- R1 (Opus 5.5 high, d50eaf0e): changes requested — M1 per-copy probes, M2 misleading VP9 continuity reason, M3
  SKILL.md, M4 EBML reader size; L1–L9. All folded (d0b283e0; SKILL.md by the coordinator).
- D3 follow-through (853e4a22): CEF probe passed → `_codec_supported(..., managed=)` admits VP9 in managed OBS.
- R2 (Opus 5.5 high, d50eaf0e..853e4a22): approve; lows L-a/L-b folded (e7e81218), L-c = this record, including the 30 fps CEF row.
