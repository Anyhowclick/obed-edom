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
| Managed OBS 32.2.2, 30 fps | PENDING | | | |

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

## AM-2 to AM-4

Blocked on the separate F2 slide-4 text-identity fix (owner D6). Managed-OBS physical fill/key eye rides on the
DeckLink field test (owner D3).

## AM-5 — suites

PENDING.

## Review log

- R1 (Opus 5.5 high, d50eaf0e): changes requested — M1 per-copy probes, M2 misleading VP9 continuity reason, M3
  SKILL.md, M4 EBML reader size; L1–L9. All folded (d0b283e0; SKILL.md by the coordinator).
- D3 follow-through (853e4a22): CEF probe passed → `_codec_supported(..., managed=)` admits VP9 in managed OBS.
- R2 (Opus 5.5 high, d50eaf0e..853e4a22): approve; lows L-a/L-b folded (e7e81218), L-c = this record.
