# Live continuity, Stage B: carry under artwork, N carries per boundary, qualify Alpha_DSK

Status: **DRAFT rev 2 (2026-10-13), planning only; awaiting owner review.** Critique r1 (Opus HIGH): the settle test also requires an ev0 tree of only movie-start builds; §3 byte-identity limited to the allowlist, with the changed fixtures/tests named; the re-home also resets a decoder arriving from a held plain-bridge overlay (+ Node R1b); OQ-B8; exact `artworkAbove`/carry-cover criteria; P2 citation fixed; version pins added to WS R. Read-only against `claude/s2-followups-dsk-deck-902af1` (main `93963f4c` + `87ab7240`). Parent: `keynote_live_continuity_generalisation.plan.md` (S2 merged #259; S3 = delete the allowlist, OQ-8). Citations: `lc` = `src/obed_edom/live_continuity.py`, `js` = `src/obed_edom/live_continuity_js.py`, `probe` = `scripts/live_continuity_probe.py`.

**Goal (owner, 2026-10-13).** Qualify a real deck. `~/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key` (fresh H.264 export `output/.html-preview/3b9019f0…-p3-r1/html`) must derive `qualified` and pass the probe green. Every Magic Move where the same movie continues must carry, with the authored artwork drawn above the video once the slide settles.

**Owner decisions that still govern (not reopened).** Pin hold accepted. R9. A runtime carry refusal lasts until the next go-to. Main freeze bracket option A. Decision 14. Instrument scope = catch what the owner's eyes can catch. Exact canonical asset matching. objectID-only runtime identity.

## 1. Evidence (offline, from the export and the code)

### 1.1 Alpha_DSK, boundary by boundary
10 slides. Ordinal 7 is skipped, so player index p = ordinal−1 up to ordinal 6, and p = ordinal−2 after that. Each movie slide has exactly 2 events: ev0 is the auto `apple:movie-start` builds (`automaticPlay: true`; wa0125 on p5 starts nested "with previous" under the untitled start), and ev1 is the outgoing transition.

| Boundary (player / ordinal) | Transition | Derivation today | With overlap and the one-bridge guard stubbed out (scratch run) |
|---|---|---|---|
| 0→1, 1→2, 2→3 | none | no movies | same |
| 3→4 (ord 4→5) | MM 1.5 s | untitled-h264 **bridge**, carried | same; no artwork on p4 |
| 4→5 (ord 5→6) | Dissolve | restart | same |
| 5→6 (ord 6→8) | MM | wa0125 bridge **refused `overlap`** (p6 slots 2/3: 259×59 tag at 0.61 opacity + 224×36 text on the video's top-left) | bridge; R2/R4/R8/R9/R10 all pass |
| 6→7 (ord 8→9) | MM | wa0125 bridge refused `overlap` (p7 slots 5/6/7: tags, one straddling both videos) | bridge |
| 7→8 (ord 9→10) | MM | wa0121 (loops on both sides) + wa0125: **two bridges**, both refused `overlap` (p8 slot 2 = 13 px divider over wa0121; slots 4–7 = tags) | two bridges; the `_chain_refusal` R6 check passes. The real blocker is the guard at `lc:1779-1780` |
| 8→None | (`none`) | `restart` per asset, no `src_object_id` (`lc:1884-1890`). `to_runtime` drops it (`lc:807-808`) and the probe skips it (`probe` `verdict_specs` `:1349`) | unchanged. At runtime the two carried decoders stay held on the last slide (handover open item 3) |

Coordinator's measured fact: the refused carries have deliberate tags covering 3.3–8.3 % of the video, and the dividers 1.3–2.0 %. **No tolerance threshold can qualify them.** B has to really draw the artwork above the carried video.

Skipped slide: `derive_plan` drops skipped slides (`lc:1830-1832`). The export already builds ordinal 6's Magic Move against ordinal 8: the p5 transition carries ordinal 8's tag slots (259×59 and 224×36, `hidden`). So the plan's 5→6 is the move the player actually runs. The host maps ordinals correctly (`live_host.py:818-820`). Only the probe's synthetic slides (`probe:1024-1029`, ordinal = player+1) label the boundaries one off from the operator's numbering after slide 6. This is cosmetic: B records the mapping in the gate record and changes no code.

Audio (checked, needs no action): untitled-h264 has AAC at volume 1. A bridge's suppressed fresh element gets `src` (`js:2211`) and the player's `startMovie()`, so on a bridge it would double the audio. The host runs Chrome with `--mute-audio` (`live_host.py:522`; README "Audio is disabled"), so this is a latent residual only. It is listed in §8.

### 1.2 How the export draws, and where the core paints
- **Draw order:** each event's `baseLayer.layers[]` lists the slots in paint order, with a slot's object as its single child. `_overlap_refusal` (`lc:1218-1248`) treats every later slot as artwork.
- **Why the overlap rule exists:** a WebGL transition sets the DOM layers to opacity 0 and keeps its canvas until the **next event renders**. The player fires that event by itself only when it is `automaticPlay: true` (`.agents/plans/keynote_live_alternatives_research.md`, P2 code-read).
  - P2's 1→2 destination starts on a click (`p2-recovery/html-adversarial` p1 `0C652BEB`: `[False×4]`), so the GL canvas stays for the whole dwell. A movie inside a DOM layer is invisible there, which is why it is refused and glReplay exists.
  - Every Alpha_DSK destination (p6/p7/p8), every D1–D6 slide except D4's last (3 events), and P2's slide 4 is `[True, False]` with an ev0 tree of only `apple:movie-start`/`renderMovie`: the slide **settles back into its DOM layers** right after the move.
- **The carried decoder's stacking today:**
  - *Ride* (both actions, transition scene): `rideTransition` appends the decoder to `#body` (`js:1157-1161`), above everything. This is the owner-accepted pin hold.
  - *Settled pin:* the fresh element becomes a facade, and the decoder is re-homed **into the destination poster's authored layer**: `bindFacade` (`js:1812-1901`) calls `scheduleRemount('pin-rehome')`, then `tryRemount` runs its poster-canvas branch (`js:1698-1755`). That branch's own comment says the layer's stacking context "is what makes later-authored artwork … paint in front". It is proven live by D1/D3/D4/D5 pins and by G2's release (`js:733`).
  - *Settled bridge:* `carry()` takes `bridgeTo34` + `keepAtSlot` (`js:2140-2144`, `:1376-1409`, `:1297-1343`). The decoder stays an absolute overlay **on `#body`** at `dst.rect`, painted above every authored layer. **This is the only reason a bridge would hide labels on the settled slide.**
- **Bridge animation:** it runs per decoder. `markTransition` walks every held decoder (`js:789-794`). Each `keepThroughBridge` (`js:1192-1222`) owns its own `__obedMotion` and reads the one shared `departure` GL clock. `nextEntry`/`carryEntryTo`/`pickCarried` are per instance (`js:406-421`, `:2084-2109`). **The core has no one-bridge assumption left.** The limit is Python only: `_magic_move_movies` `lc:1779-1780`. `_gl_replay_attempt`'s `continuing_count != 1` (`lc:1520`) is glReplay's own rule and stays.

### 1.3 What the instruments assume
- **`probe` `verdict_specs`** (`:1334-1423`): one spec per (boundary, instance, kind), so several carries per boundary already work (D3 S1→2 pin + bridge). `--strip ACTION@scene:KEY` exists for picking one of two entries.
- **`probe` `ground_truth_facts`** (`:1517-1520`): `boundary_keys` is keyed by `atScene`, so a second carry at the same scene would overwrite the first. It is only used for the armed (glReplay) fact, whose boundary has exactly one carried movie. Leave it.
- **`probe` `score_carry_cover`** (`:8443-8451`): **reads INCONCLUSIVE when any other `bridge-motion-start` falls inside the capture.** With two bridges on one boundary, both captures would be inconclusive. The per-capture export tag `carry-cover-{boundary}` (`:8746`) would also collide.
- **Nothing scores "artwork above the carried movie."** The P2 green-square z-order is only a comment (`p2_verdict.py:103-108`). The pre-S2 `overlappingArtworkComposedAfter1to2` is gone. This is the gap B must close with a red control.
- **`p2_verdict.py` and `paint_instrument.py`** need no change: P2's plans are unchanged (§3), and paint reads already handle decoders inside layers (pins).

## 2. Design

### 2.1 (1) Carry under artwork — recommendation: **home the decoder in its authored layer at landing, only on slides that settle into the DOM**
- **Python (`lc`)**
  - In `_carry_refusal` (`lc:1732-1733`), an overlap is **not** a refusal when the destination *settles into DOM*: `len(events) == 2`, `events[0]["automaticPlay"] is True`, and every effect in ev0's tree (nested included) is `apple:movie-start` or `renderMovie` (fail closed otherwise). The third clause: a WebGL build run at ev0 keeps its canvas over the DOM until the click. Exactly two events: no later build re-renders the slide before the outgoing transition (the `keepAtSlot` history).
  - The carry is then marked `under_artwork=True`, and `to_runtime` emits `"underArtwork": true` on that entry (pin or bridge). The key is present only when true (`as_dict`, `to_runtime`).
  - Any other overlapping destination keeps code `overlap` (→ `retire`, or `glReplay` for a pin as today). The two domains are disjoint, because glReplay already requires a click-driven first event (`lc:1526-1530`).
  - `ContinuityPlan` gains `artwork_above: {player: [{objectId, asset, slot, rect}]}`, the later overlapping slot rects for the probe. It is not in `to_runtime()`.
- **JS (`js`, about 4 lines in `carry()` and the src hook)**
  - For a bridge with `underArtwork`, keep the `bridge-3to4` note (F5 unchanged), then take the **existing pin re-home path** instead of `bridgeTo34`, with `const rehome = !!entry.underArtwork || !!preserved.__obedBridged34`, so a decoder arriving from a held plain-bridge overlay is reset too (otherwise `tryRemount` stops at `__obedRemountEpoch === -1`, `js:1377-1378`): `bindFacade(el, preserved, true)` (removes the stub), `scheduleRemount(preserved, 'pin-rehome')` at `dst.rect`.
  - In the src hook (`js:2211`), do not set `src` on that stub.
  - This is exactly the state a pin leaves after a held bridge (D1 S3→S4, live-proven), so the next ride, restart, go-to and end-of-show behave as they already do after a pin.
  - Pins need no JS: they already settle in the layer.
- **Rejected options:**
  - (b) Re-home every bridge, flag or not: this changes P2 3→4 and D1–D6 behaviour, and `keepAtSlot` exists because a one-shot swap "did not survive slide-4's second build".
  - (c) Clip the ride overlay with holes interpolated along the labels' own paths: a new geometry pipeline and instrument, for 1.5 s.
  - (d) An overlap tolerance: ruled out by the coordinator's measurements.
- **What the owner will see:**
  - On settled slides ord 8/9/10: tags, the divider and the semi-transparent tag boxes sit over the live video exactly as authored.
  - During each 1.5 s Magic Move into, out of or between those slides, the moving video paints over the parts of the tags and divider it overlaps. Keynote keeps them on top. They come back on top as the slide settles, within the existing re-home retry schedule (sync, then 50–2000 ms; the D-deck pins land in the first ticks).
  - This is the pin hold extended to bridges: **OQ-B1**.
  - Unchanged: at 5→6 the non-carried untitled fades out on its frame 0 (open item 2, the dissolve session's F3).

### 2.2 (2) N carries per boundary, in authored stacking — recommendation: **delete the guard; order riders only when their paths can cross**
- **Python:** delete `lc:1779-1780`. For each pair of carries on one boundary, the two never intersect during the move when they are separated along the same axis, on the same side, at both ends. That is exact, because both move by the same eased progress p and each edge is linear in p (a pin is constant).
  - Separated = far edge ≤ near edge + `_OVERLAP_MIN_PX` (as `_overlaps`). Always emitting draw order would change D3's bytes.
  - If they are not separated that way, emit `"zOrder": <destination draw-slot index>` on **both** entries.
  - Alpha_DSK 7→8 is x-separated at both ends (930|930 → 763|764), so it emits no zOrder.
- **JS (about 6 lines in `rideTransition`):** when the entry has `zOrder`, insert the rider into `#body` before the first sibling rider with a greater `__obedRideZ`, instead of appending. Re-insert even when it is already a child of `#body`; compare only riders of the same `atScene`.
  - On the settled slide nothing more is needed. A video that a later-slot video overlaps is itself "under artwork", so it homes in its layer under the other video, and authored order holds for both.
- **Owner sliver requirement (2026-10-13):** a small accidental video-on-video overlap renders exactly as Keynote draws it, with no tolerance, on DOM-settling destinations (pins too, if **OQ-B2** = yes).
  - **Fallback, only if D7s shows two lifted decoders cannot keep authored order:** tolerate a video-on-video overlap under 1 % of the smaller video's area. Its red control would be a synthetic 1.5 % overlap that must still refuse, while 0.8 % carries.
  - Click-driven destinations keep refusing any overlap (a GL canvas is on top for the whole dwell) → **OQ-B8**.

### 2.3 (3) Everything else Alpha_DSK needs
- **Fixture:** the coordinator copies the export to main-checkout `output/fixtures/sermon/alpha-dsk/{html-player,html-unmodified}` (S0 recipe). Registrations: `DECK_PLAN_SHA256`, red expectations, and the allowlist (S2 branch practice) once the sha is known.
- **Carry-cover:** accept a `bridge-motion-start` note from a **sibling bridge of the same boundary** only when `_is_bridge_note` matches another bridge of that boundary, at most once each (`probe:8447-8451`; the masks already cover sibling slots, `probe:8180-8203`), and give each capture an asset suffix (`:8746`).
- **End of show (8→None):** no change in B (**OQ-B4**).
- **Codecs:** all three assets are H.264, already passing the codec gate.

## 3. Versions and shas
- `CONTINUITY_VERSION` 6→7, `__OBED_P2_PRESERVE__.version` 9→10, `PINNED_CORE_SHA256` re-pinned. G2 is untouched (v1, `10a5b36a…`).
- **Every allowlisted runtime plan stays byte-identical:**
  - P2 and p2-loop: the 1→2 destination is click-driven, so `overlap` is unchanged, and so is glReplay.
  - D1–D6: no overlap onto a settling slide, and D3's pin+bridge pair is x-separated (900 | 1020→1100), so no `zOrder`.
  - The existing plan-sha tests and allowlist entries must pass **unedited**. That is B's regression oracle.
- **Not identical (not allowlisted):** the Minimal Alpha_DSK family (`gl-decks/Minimal Alpha_DSK`, `p2-soak-loop`, the `minimal_alpha_dsk` fixture): its 5→6 `clip-10-1000001.mov` pin onto a settling slide becomes `underArtwork` under OQ-B2.
- **Tests that change on purpose:** `tests/test_live_continuity.py:363-390` (two clean bridges now derive); `:1604-1625` (keep it as the refusal test by making slide 4's ev0 click-driven; add the flagged twin); `tests/test_live_continuity_decks.py:59-97` (glReplay rule 2 stays covered at `tests/test_live_continuity.py:2702`).
- **Plan schema:** stays 2, with two optional additive keys (`underArtwork`, `zOrder`). The JS still checks only `schema === 2`. G2 ignores extra keys (F4).

## 4. Work streams (Opus MEDIUM, disjoint files, one message; then a Codex GPT-6 Astra (high) review of the combined diff)
**Frozen contract, set before launch:** `underArtwork` (bool, pin/bridge), `zOrder` (int, only on crossing pairs), `ContinuityPlan.artwork_above` shape, variant name `settle-on-stage`.

| WS | Files (exclusive) | Work | Tests (minimal) |
|---|---|---|---|
| D | `lc`, `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py`, `tests/fixtures/live_continuity/**` | §2.1 DOM-settling lift + `artwork_above`; §2.2 guard deletion + `zOrder`; rewrite `test_only_unrefused_geometry_changes_count…` (`tests/test_live_continuity.py:363-390`: two clean bridges now derive) | (1) trimmed Alpha_DSK fixture (p3–p8 JSON, `accessibility`/`hyperlinks` stripped; **OQ-B6**) derives the expected entries and keys; (2) one parametrised overlap test: settling dest → pin/bridge `underArtwork`, click-driven dest / extra event → `overlap`; (3) `zOrder` emitted iff paths can cross (separated vs sliver) |
| R | `js`, `tests/test_live_continuity_js.py`, `scripts/continuity_core_variants.py` (+ its test), `tests/test_live_gl_replay_js.py`, `scripts/detach_experiment.py` (`CORE_SHA256`), `tests/test_detach_experiment.py`, `tests/test_live_host.py` (re-pins only) | §2.1 `carry()`/src-hook branch, §2.2 rider ordering, version bump, docstring; variant `settle-on-stage` (drops the `underArtwork` branch = today's core) | Node: (1) an `underArtwork` bridge ends in the poster's layer, the stub is removed and never gets `src`, and it is not on `#body` after landing; (1b) a held plain-bridge overlay → `underArtwork` bridge ends in the layer; (2) two bridges at one `atScene` each ride with their own motion and land; (3) `zOrder` rider order; F5 names unchanged |
| G | `probe`, `tests/test_live_continuity_probe.py`, `scripts/run_gates.sh` | New verdict **`artworkAbove`** per (settled slide, carried instance, later overlapping slot) from `artwork_above`: a probe-only page read that forces `pointer-events:auto` on `#stage *` and `video` and calls `elementsFromPoint` at the centre of (slot ∩ instance) in screen px. PASS when the carried decoder (the carry verdict's elId) is listed and an element above it, not its ancestor, has IoU ≥ 0.5 with the slot rect. Read ≥ 2.5 s after settle (the last re-home retry is at 2000 ms). No carried decoder → INCONCLUSIVE. Restore pointer-events afterwards. Plus the carry-cover sibling fix (§2.3). | (1) `artworkAbove` scorer pass/fail/inconclusive; (2) carry-cover sibling acceptance; registrations as data |
| P | `README.md`, `.agents/skills/obed-edom/SKILL.md` | "What is carried": under artwork on DOM-settling slides, N carries per move, the bridge hold. Fix the stale "motion is linear" line (README:119-120; R10 eases). Contract section: the two keys. | — |

Every PR runs the full suites on 3.12 (`uv run pytest tests/ -n auto --dist loadfile`, `npm run test:ui`, `npm run test:maps`) and the 3.10 floor for the probe/paint/run_gates files, locally (no CI).

## 5. Re-qualification (core bytes change, so §4's rule re-opens Q2–Q6)

### 5.1 New decks (owner authors in Keynote, or gives a Keynote go for the S0 AppleScript generator; V4 eyeball as S0)
- **Common:** S0's common rules (1920×1080 black, `counter-a`=A / `counter-b`=B at 32:9, every movie starts After Transition so ev0 is auto, MM 1.5 s, Repeat None, template label).
- **Waived on purpose:** "nothing overlaps a movie".
- **Artwork:** TA = a **solid green** rectangle at 100 %. TB = a white rectangle at **61 %** opacity, like Alpha_DSK's tags. Divider DV = a white rectangle. **Draw order back→front: A, B, TA, TB, DV** (B must stay in front of A).

| Deck | Slides (rect x,y,w,h) | Expected plan (scenes) | Proves |
|---|---|---|---|
| **D7: two side-by-side movies with label tags shrink together, grow back, then hold** | S1 A 160,300,800,225 · B 960,300,800,225 · TA 140,280,240,56 · TB 940,280,240,56 (straddles A and B) · DV 954,300,12,225 → MM → S2 A 320,700,640,180 · B 960,700,640,180 · TA 300,684,200,48 · TB 940,684,200,48 · DV 955,700,10,180 → MM → S3 = S1 rects → MM → S4 = S3 rects | @2 bridge A+B, @4 bridge A+B, @6 pin A+B; all `underArtwork`, no `zOrder` | (1) artwork above on settled bridge and pin slides; (2) two bridges per boundary; a flagged bridge → bridge → pin chain |
| **D7s: the sliver variant** | D7 S1–S3 without DV; S2 B at **955**,700,640,180 (over A by 5 px = 0.78 % of A) | @2 and @4: bridge A+B, `underArtwork` both, **`zOrder` both** (B > A) | Authored video-on-video order on the settled slide and in flight, with no tolerance |
| **Alpha_DSK (real)** | as §1.1 | @6 bridge, @8 restart, @10/@12 bridge `underArtwork`, @14 bridge×2 `underArtwork`, no `zOrder` | the goal |

### 5.2 Gates
| Q | Run | Pass | Red controls (pre-registered) |
|---|---|---|---|
| Q1 | Full suites 3.12 + 3.10 floor | green | — |
| Q2 | P2 `run_gates` fast/slow/auto | 15/15, table equal to S2's | existing (`--disable-bridge34`, `stash-any`) |
| Q3 | Host probe A/B/C + attach + V/Voff/Vgl × 3 viewports, Pass G, deck sweep on **P2, D1–D6, D7, D7s, Alpha_DSK** | every verdict incl. `artworkAbove`; `unexpectedVideos` empty | existing D1–D6 arms unchanged. **New:** `settle-on-stage` on D7 → red only on `artworkAbove` at S2/S3 (green at S4 pins); on Alpha_DSK → red only on `artworkAbove` at p6/p7/p8. `--strip bridge@2:movie2` on D7 → red on B's chain only (+ listed `STRIP_CASCADE`), A green: proves simultaneous bridges are independent. `--strip bridge@14:movie2` on Alpha_DSK → red only on wa0121 b7to8. Alpha_DSK `--strip bridge@6` (+ that instance's `artworkAbove` INCONCLUSIVE, listed in `STRIP_CASCADE`) |
| Q3 | Carry-cover | D7 every bridge pass | `--carry-cover-null` on D7 fails; P2/D1 arms as today |
| Q4 | G2 seam (Vgl, `--gl-force-fail` ×4) | as S2 | `--gl-force-fail` |
| Q5 | Loop L1 + L2 | as S2 | as S2 |
| Q6 | Managed OBS `both`/`g2`/`failsafe`/`soak` at 25 and 30 (owner's go) | M1–M6 | `--kb` arms |
| Q7 | Owner, real OBS Keyer: D7, D7s, Alpha_DSK (+ D1 spot) | labels on top when settled; no visible restart where carried; bridge hold as described in §2.1 | — |

- `zOrder` in flight has no live verdict, because a 0–5 px sliver mid-move is below what the eye catches. It is covered by Node test R(3) plus the Q7 eye. `artworkAbove` covers the settled sliver on D7s.
- Pass G (go-to mid-chain, then carry) adds D7, D7s and Alpha_DSK to `PASSG_FIXTURES`.
- The gate commit adds the D7, D7s and Alpha_DSK shas to the allowlist (decks join one at a time).

## 6. S3 sequencing — recommendation: **B first, then S3 right after** (S3 prepared in parallel during B's gate round)
- B is what qualifies the real deck. S3 (OQ-8 (iv)) then uses Alpha_DSK as its real sermon deck, *qualified with a green probe*, not merely "with named refusals".
- S3's negative corpus (one synthetic export per refusal code) is written once against B's code set. B removes "more than one movie changes geometry" and narrows `overlap` to click-driven or multi-event destinations, so writing the corpus first would mean writing entries B deletes.
- S3 stays Python + docs. Its gate is: runtime plans byte-identical to B's, and probe verdicts equal on P2, D1–D7s and Alpha_DSK. It reuses B's round, so there is no new browser cost beyond one confirmation run.
- File overlap with B is only `lc:654-668,831-832` plus the allowlist monkeypatches in tests. Rebase after B merges.

## 7. Owner questions (recommendation first)
1. **OQ-B1: bridge hold under artwork.** During a 1.5 s Magic Move, tags and dividers that overlap the moving video are hidden under it and return on top at settle. **Rec: accept.** It is the same class as the accepted pin hold. The alternative (clip the overlay with holes that follow each label's path) costs a new geometry pipeline and its own instrument.
2. **OQ-B2: lift the overlap refusal for pins too (DOM-settling destinations only).** **Rec: yes.** No JS is needed (pins already settle in the layer). P2 is unchanged because its 1→2 destination starts on a click. It is needed for static side-by-side slivers.
3. **OQ-B3: order.** **Rec: B, then S3** (§6).
4. **OQ-B4: end of show.** Alpha_DSK's two carried movies stay held after the last slide (open item 3, deferred). **Rec: no change in B.** At Q7, press past the end once and say whether it is acceptable. A follow-up only if not.
5. **OQ-B5: re-qualification scope.** The new branches cannot run on any existing plan (byte-identical). **Rec: full Q2–Q6 anyway** (§4 rule, mechanical via `run_gates`). The cheaper option is Q5 = L1 only and Q6 = `both` at 25/30 only.
6. **OQ-B6: committing a trimmed Alpha_DSK fixture** (movie slides p3–p8, layer JSON only, `accessibility`/`hyperlinks` stripped, no movies or thumbnails). **Rec: yes.** It is the single test that covers the whole real-deck derivation. The alternative is a synthetic look-alike.
7. **OQ-B7: D7/D7s authoring.** **Rec:** the coordinator builds them with the S0 generator under your Keynote go. You confirm the draw order and pairing by eye (V4). Alpha_DSK itself is never opened.
8. **OQ-B8: slivers on click-driven slides.** Your sliver requirement holds only on slides that settle into the DOM. On click-driven slides any overlap still refuses (a GL canvas sits on top, and a plain pin there is unqualified). **Rec: accept for B** (no real deck needs it: Alpha_DSK's only click-driven movie slide, p3, has one movie); measure before adding any tolerance.

## 8. Residuals (README)
- The bridge/pin hold under artwork during the move (OQ-B1).
- Overlap on a click-driven or multi-build destination stays refused (`overlap`; glReplay for a single pin) (OQ-B8).
- Rider order between crossing carries is unit-tested only.
- A suppressed bridge destination still decodes its own copy (audible only if audio is ever enabled; `--mute-audio` today).
- The probe's ordinal labels are one off after a skipped slide.
- Linear interpolation and inferred intent, as before.
