# Magic Move movie still: hold the frame that was on screen

Status: **DRAFT rev 1 (2026-10-13), planning only. Awaiting owner review.** Read-only against main `e9db8284`.
Owner report (Stage T G4, 2026-10-13): on `Alpha_DSK.key` 8→9→10 with continuity off, the movie's still during the
Magic Move is "a few frames behind" the frame that was playing at the press. The owner wants it seamless.

Governing decisions (not reopened): pin hold, R9, a runtime carry refusal lasts until the next go-to, main freeze
bracket option A, OQ-B1 (the GL feed is the design, poster hold is the fallback), instrument scope.

## 1. Measured cause (headless, `LiveOutputHost(headless=True, continuity="off", gl_replay="off")`, `show` first)
Export `7e3c9301…` (scratch copy), go to 8, 4 s dwell, Space, then 9→10. In-page log: keydown, `play`/`pause`
wrappers, rVFC per decoder, per-rAF decoder state; CDP shots matched against every decoded WA0125 frame
(160×90 MAD). Evidence: main checkout `output/evidence/mm-freeze-2026-10-13/` (`probe.py`, `run1/`, `montage.png`).

| t (ms, page clock) | Event |
|---|---|
| 5839.5 | Space keydown (the host's `execute` starts 2 ms earlier) |
| 5851–5935 | The decoder keeps presenting: mediaTime 5.033, 5.067, **5.100** (the last frame on screen) |
| 5951.6 | First rAF of the move: the decoder is detached and paused at `currentTime` 5.087. **No JS `pause()` call**: removing it from the DOM paused it. |
| 5927–6027 shot | The movie slot shows **WA0125 frame 0** (MAD 7.7; the live frame at 5.1 s reads 57.8 against frame 0) |
| 7759 | Slide 9 settles; the player starts a fresh WA0125 element from `currentTime` 0 |

- **The still is not a late frame. It is Keynote's baked poster.** The move draws each movie leaf from a static
  PDF texture (`C01CA…` on slides 8, 9 and 10). It matches WA0125 frame 0 (MAD 9.4, the PDF-vs-decode tone floor).
  The player never reads a frame from the `<video>` (no `currentTime`, no `texImage2D(video)` in `main.js`).
- **Why it reads as "a few frames behind":** the destination restarts the clip at 0, so the poster joins the restart
  seamlessly. The only jump the eye sees is at the press: from the live frame back to frame 0. On this run that was
  5.1 s (153 frames) back. The size of the jump is the dwell time, not lag.
- **Latency is real but points the other way.** About 110 ms (3 frames at 30 fps) pass between the keydown and the
  move's first frame. The video keeps playing through it, so latency alone would freeze a few frames *ahead* of the
  press, never behind. The host's own cost is ~2 ms (one `observe` and focus, then the key).
- **A trap for any pause-based hold:** at the teardown, `currentTime` (5.087) lies *before* the last presented frame
  (5.100). A hold that seeks to or decodes at `currentTime` would show the frame one before the one on screen.
- 9→10 on this unrepaired export: WA0125's slot shows WA0121's poster (Stage T open item 2). It is the same class:
  a baked still, not the live frame.

## 2. How this meets Stage B
- **Fed move (B's design, Chrome and the managed OBS once Q6 passes):** the decoder keeps playing *through* the move.
  There is no freeze at all, which is better than an exact freeze. After B, Alpha_DSK 8→9 and 9→10 are fed (today they
  are `overlap` refusals), so the owner's deck stops showing this in Chrome.
- **B's poster hold (external attach, feed off, a stand-down):** B rev 3.1 pauses at departure and resumes from the
  pause point at settle. During the move, though, it shows **the baked frame 0** (B §"What the owner will see", §8
  residual). This is the same jump the owner just reported, kept as a known residual. **This plan fixes exactly that.**
- **Continuity off (the operator's or env's escape hatch) and any non-carried move:** the stock player restarts at
  settle. Freezing on the exact frame here would only move the jump from the press to the settle (exact frame → frame
  0). Fixing it needs a carry, which is what continuity is.

## 3. Proposal: exact-frame poster hold, as a part of Stage B (recommended)
B's hidden-ride poster hold gains a **one-shot upload**. At the move's first frame with draws, upload the held decoder's
current picture into the leaf's planned textures with B's existing binding (draw index and upload ordinals, never a
texture id). That is one `texImage2D(decoder)` per bound texture under each texture's own FLIP_Y/PREMULTIPLY state,
restoring GL state afterwards: B's feed step, run once instead of every frame. Nothing else changes: pause at
departure, resume from the pause point at settle, no restart.
- **Frame identity:** upload from the paused element, which holds its last presented picture, before any seek. The
  pause stays at hidden-ride start, which is the teardown, so the held picture is the one on screen when the move
  began. Never seek to `currentTime` (§1 trap). The dev loop must confirm this on GPU Chrome. If the paused element
  instead yields the `currentTime` frame, fall back to a `VideoFrame(decoder)` taken in the take hook before teardown
  (the D4 slot `jumpToScene_partFour`, same task as F3's take) and upload that.
- **Stand-down mid-move** (B's `onStandDown`): the last fed upload is already the live frame, so the textures keep it.
  Stop feeding, pause, no re-upload.
- **Where the binding is not unique** (B's "Not uniquely bindable → poster hold"): keep the baked poster and record the
  reason per entry, as B does. Nothing is guessed.
- **External attach (CEF):** `texImage2D(video)` in CEF 127 is B's open Q6. If Q6 fails (OQ-B10), the one-shot path
  stands down with the feed, and the baked poster remains there.
- **Size:** one branch in B's feed module (a "once" mode) and one call in the hidden ride's hold path. No new
  player-byte replacement, no Python plan change, the plan sha is unchanged.

Rejected:
- (b) A standalone player patch for continuity off: it duplicates B's texture binding outside the core, and it moves
  the visible jump to the settle (§2).
- (c) A DOM overlay of the paused `<video>` over the moving GL leaf: that is the pin hold under artwork that OQ-B1
  replaced with the feed.

## 4. Gate (folds into B's Q3, Q5 and Q7)
- **`holdFrame` verdict (new, per poster-held entry):** in-page `readPixels` of the GL canvas at the leaf's planned
  rect at the move's first draw, at p≈0.5, and at the last frame before settle. Each crop is matched against the
  decoded source frames, and its index must equal the decoder's **last rVFC-presented frame before departure**
  (exact, 0 frames tolerance; match margin over the next-best frame under the PDF-vs-decode floor). The first frame
  presented after settle must be held+1 (B's `posterHold` resume rule, tightened from "within 1 frame").
- **Null control:** the same capture with the one-shot disabled (`--mm-feed off` plus a hold-upload kill switch in the
  probe build only) reads frame 0, so `holdFrame` is red.
- **Positive control:** a fed arm reads advancing frames, so `holdFrame` is not applicable and `feedLive` is green.
- **Arms:** Alpha_DSK 8→9 and 9→10 (on Stage T's repaired export) with dwells of 2, 5 and 12 s, so the held frame
  differs from frame 0 by a margin; D7 attach arm. Headless runs as in §1, plus ≥ 10 real-clock GPU Chrome runs in B's
  dev loop.
- **Q7 (owner):** external attach on Alpha. At the press the movie stops on the frame that was showing, travels with
  the move, and resumes from it.

## 5. Owner questions
1. **OQ-F1: fold this into Stage B as the poster hold's one-shot upload (§3)?** **Rec: yes.** It turns B's documented
   frame-0 residual into an exact hold and reuses B's binding and gates.
2. **OQ-F2: continuity off keeps the stock frame-0 still plus restart.** **Rec: yes.** Off is the escape hatch. An
   exact freeze there trades the press jump for a settle jump.
3. **OQ-F3: the held frame = the frame on screen when the move starts** (≈110 ms and 3 frames after the press), not the
   frame at the instant of the press. **Rec: yes.** Holding the press-instant frame would step back 3 frames, which is
   the artefact reported.
