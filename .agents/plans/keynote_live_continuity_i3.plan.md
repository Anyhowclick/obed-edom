# Keynote live continuity — I3 scaled-stage mapping (APPROVED 2026-09-19, decisions 1a · 2a · 3a)

Drafted 2026-09-19 at `a64d489` on `claude/keynote-live-continuity-next`. Parent:
[`keynote_live_continuity.plan.md`](keynote_live_continuity.plan.md) §2 "Scaled stage", §7 I3.

## 1. Problem
Continuity installs only when the page viewport equals the authored canvas (`live_host.py`
`_continuity_plan_script`: `w===innerWidth&&h===innerHeight`). On the owner's 2560×1440 HDMI monitor the
session reports `unsupported: viewport is not the authored size` and plays the raw player (movies vanish
after 1→2). Plan rects are authored px; the runtime writes and compares them as screen px.

## 2. Measured (headless host, 2560×1440, fixture, this branch — scratch run 2026-09-19)
- `#stage`: `offsetWidth/Height` = 1920×1080 (authored, transform-blind), `style.left/top` = 320/180,
  computed `transform: matrix(1.33333,0,0,1.33333,0,0)`, `getBoundingClientRect()` = (0,0,2560,1440).
  Source: player `adjustStageToFit` — `scaleX(g) scaleY(B)` on `#stage` and `#hyperlinkPlane`.
- Slide-1 movie `<video>` (inside `#stage`, authored-px style 951.5×267.6) renders at
  (145.8,1060.05,1268.71,356.81) = authored (109.35,795.04,951.5,267.6) × 1.3333. Poster canvases likewise.
- `#body` **is** `<body>`: the runtime's stage-level overlays (`bridgeTo34`, `keepThroughBridge`, the
  `tryRemount` fallback) are viewport-positioned ⇒ need SCREEN px. In-layer remounts live inside the
  scaled `#stage` ⇒ their inline `left/top/width/height` are AUTHORED px.

⇒ one mapping, read live each time it is used:
`s = stageRect.width / stage.offsetWidth`, `screen = stageRect.origin + authored × s`. Exact identity at
1:1 (`s = 1`, origin 0) so P2's numbers do not move.

## 3. Design
**Runtime (`live_continuity_js.py`, `CONTINUITY_VERSION` 3, new sha; plan object UNCHANGED ⇒ allowlist
signature and P2's injected plan unchanged):**
- `stageMap()` → `{s, ox, oy}` from `#stage`; fail-closed `null` when `#stage` is missing, has a zero box,
  or `|sx − sy|` exceeds 0.1 % (non-uniform). `toScreen(rect)` / `toAuthoredLen(px)`.
- Screen-space consumers map the plan rect per rAF: `keepThroughBridge` (src/dst), `keepAtSlot` +
  `bridgeTo34` (`slide4Rect`), the `tryRemount` footprint fallback, `footprintKeyForRect`.
- In-layer writes divide by `s`: `remount-into-authored-layer` width/height and its measure-and-correct
  delta; `keepAtFootprint` delta. (`__obedRect` stays a screen-px measurement.)
- `captureLayout` style fallback (authored w/h + screen parent origin) → scale w/h by `s`.
- Tolerances scale with `s`: `findMovieCanvas` 10/16, `footprintKeyForRect` 20/30. IoU 0.75 is
  scale-free. The 0.5/1 px deadbands stay screen px.
- Measurement API contract: `footprintOwnerDecoderId(rect)` takes an AUTHORED rect and maps internally —
  P2 and host-probe call sites unchanged. `snapshot()` gains `stageMap` for the probe.
- No mapping cache: a display-mode re-fit is picked up on the next frame (geometry only — not qualified).

**Host (`live_host.py`):** replace the viewport-equality gate with a stage gate: `#stage` resolves,
`offsetWidth/Height` == header canvas, uniform scale. Reasons become `stage is not the authored size` /
`stage scale is non-uniform`. The player sizes `#stage` only after load, so the gate cannot run at
injection time: the plan always installs, the host evaluates the gate (its own JS, independent of the
runtime) once the player is ready, polling to an absolute deadline, and on failure calls the runtime's new
`disable()` (clear + every hook pass-through) and confirms `disabled === true` — else `LiveHostError`.
Off/unsupported HTML stays byte-identical to pre-I2 (existing hash tests). Attach (OBS) stays 1920×1080.

**Probe (`scripts/live_continuity_probe.py`):** `--viewport WxH`; each sample records the stage map and
rects are converted to AUTHORED space before scoring, so every existing threshold and red control applies
unchanged. Identity/owner/clock/landing checks untouched.

## 4. Qualification (positive + red, per parent §6)
| Arm | Viewport | Expect |
|---|---|---|
| 1:1 regression | 1920×1080 | host gate PASS as today; P2 fast 14/14, slow 14/14, `--disable-bridge34` RED only on `continueThroughMovingMagicMove3to4` |
| scaled | 2560×1440 | host gate PASS (A + attach-style arm); B (continuity off) and C (bridge off) RED at the same findings as 1:1 |
| **letterboxed** | 1600×1000 (16:10 ⇒ stage origin ≠ 0) | PASS — 2560×1440 has origin (0,0) and cannot see an offset bug |
| red-without-the-fix | 2560×1440, new probe vs the **v2** runtime (gate bypassed via the test helper) | RED on rect checks — run BEFORE landing the runtime change, artifact kept |

Node behavioural tests (`tests/test_live_continuity_js.py`): fake `#stage` at s = 1, 4/3 and a letterboxed
origin — bridge motion endpoints, slot pin, in-layer correction converges in one step, tolerance scaling,
`stageMap()` null cases. Then HDMI run with the owner watching 1→2 and 3→4 (ask before using the monitor).
P2 bank: use a private copy of `html-adversarial` — another session is running P2 gates out of
`pr158-handover-findings-4366b9` right now.

## 5. Work split (disjoint files; Sonnet implements, Codex gpt-5.6-sol reviews)
| # | Files | Order |
|---|---|---|
| A | `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py` | first → produces the RED artifact against v2 |
| B | `src/obed_edom/live_continuity_js.py`, `tests/test_live_continuity_js.py` | parallel with A |
| C | `src/obed_edom/live_host.py`, `tests/test_live_host.py` | parallel with A/B |
| D | `dashboard/src/live/LivePresenter.tsx` (+test, `dist`), README "Alpha Keynote" | after gates: drop the "at 1920 × 1080" wording |
Main session: gates (P2 ×3, host probe ×3 viewports), Codex round, handover update. No push / PR without a go.

## 6. Owner decisions (approved: 1a · 2a · 3a)
1. **Authored size source**: (a) `#stage.offsetWidth/Height`, cross-checked by the host against the header
   canvas (refuse on mismatch) — no plan change · (b) add `canvas` to the runtime plan — changes the
   allowlist signature and P2's injected plan for no extra safety.
2. **Letterboxed / non-16:9 displays**: (a) supported, gated by the 1600×1000 arm · (b) refuse unless the
   stage fills the viewport.
3. **Mid-session display-mode change**: (a) mapping follows it, documented as unqualified · (b) detect a
   stage-map change after start and drop to `unsupported`.

**Risks**: `bindFacade` DOM-swap + in-layer remount under scale is exercised only at 1→2; sub-pixel
rounding at s = 4/3 against the 0.5 px deadband (watch for per-frame jitter in the rect trace); per-rAF
`getBoundingClientRect` on `#stage` adds one layout read per pinned video per frame.
**Out of scope**: I5 codec, DeckLink/HEVC, native easing parity, relaxing the allowlist.

## 7. Status — DONE 2026-09-19 (commit `ee97861`; PR #175 onto #158 after merging the presenter tip, `dfd1c13`)
Runtime `CONTINUITY_VERSION` 3, sha `54db9b0f65474bdb20ff110b5d1c715d93a845fb7275a4b67f3cbffe45428a3f`;
plan object and allowlist signature unchanged. Final gates on those bytes:
- P2 fast 14/14 · slow 14/14 · `--disable-bridge34` RED only on `continueThroughMovingMagicMove3to4`.
- Host gate PASS at 1920×1080 (s 1), 2560×1440 (s 1.3333), letterboxed 1600×1000 (s 0.8333, origin (0,50));
  every viewport: B red at 1→2 + 3→4, C red at 3→4 only, attach green, `stageFit` green.
- Red-without-the-fix: new probe vs the v2 runtime @2560×1440 = RED (1→2 235/237 rect, 3→4 212/223 rect).
- 444 unit tests (1 pre-existing skip); dashboard UI 173 pass + the 6 known-red maps tests.
- Codex gpt-5.6-sol r1 (1 blocker + 4 majors) → r2 PASS → r3 PASS: `.agents/reviews/live-continuity-i3/`.
Evidence (ignored): `output/live-continuity-i3/`.

Deviations from §3: `disable()` added to the runtime (startup-only: refuses once anything was preserved; the
host treats an unconfirmed disable as `LiveHostError`), also used for a partially installed core. The probe's
owner query converts its measured rect to authored px with its own stage map (the API is authored-in).
Lesson kept as a test: a DETACHED video reports literal viewport (0,0), not the stage origin — the
"unpositioned" check is `nearZero || nearStageOrigin` (the stage-origin-only variant passed review and unit
tests but failed the live letterboxed gate).

**Codex r1 major #4 (`keepAtSlot` re-detach):** driven on the real player through slide 4's second build to the end
of the deck — NOT reproduced (the bridged video is a `<body>` child the player never touches). Hardened anyway in
`073546d` (re-attach while the bridge generation is live).
After the merge the runtime sha is `7288246d…ceff` (adds `stash()` plan-named filter); gates re-run green from a clean
pinned worktree. **Superseding finding:** the carried movie is invisible on the fixture's slide 2 — see
`keynote_live_visible_content.plan.md`.
**Still open:** HDMI run on the 2560×1440 monitor with the owner watching 1→2 and 3→4 (ask first); real OBS
re-run; I5 codec; DeckLink/HEVC; native easing parity.
