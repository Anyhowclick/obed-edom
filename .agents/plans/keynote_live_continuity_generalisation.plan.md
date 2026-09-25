# Live continuity — generalisation: retire `QUALIFIED_PLAN_SHA256`

Status: **rev 2 + S0, APPROVED by the owner 2026-09-25. OQ-1 is (c), objectID-only runtime identity; every other OQ follows its recommendation (see §6).** **S1 LANDED #237 (`2ee95223`, 2026-09-25); S2 in progress on `claude/continuity-generalisation-s2` (no PR), see §3 S2.** Read-only against
`386f28f2` (origin/main, #228), `claude/continuity-loopmode` @ `67643332` (local; rev 1 read `b3b57fc8`; the later
commits are docs only), and `origin/claude/od-2-gl-replay-managed-obs-5bd03f` @ `af76ed97` (rev 1 read `1dd21207`;
`af76ed97` makes the soak wrap windows length-relative, soak ≥ 3 min, and requires both windows on a looping fixture).
Supersedes the brief `keynote_live_continuity_generalisation.md` (2026-09-19; deleted, `git show 6fc85b78:.agents/plans/keynote_live_continuity_generalisation.md`). Parents: `keynote_live_continuity.plan.md` (policy 3a), `keynote_live_gl_replay_arming.plan.md` §11,
`keynote_live_continuity_loopmode.plan.md`, `keynote_live_gl_replay_managed_obs.plan.md`. Style: `~/.AGENTS.md`.
Citations: `lc` = `src/obed_edom/live_continuity.py`, `js` = `live_continuity_js.py`, `g2` = `live_gl_replay_js.py`.

**Goal.** Policy 3a ("bridge every geometry-changing Magic Move where the same movie continues") holds on structural
refusals alone. A deck is `qualified` exactly when every boundary of every planned movie instance can be expressed and is
unambiguous. Otherwise it is `unsupported`, or declines that one boundary, and the specific boundary and reason are named.

**Sequencing (owner-agreed).** No implementation until **OD-2 and loopMode have both merged**. Only one stage (S2)
changes core runtime bytes (`js`), so the P2 / G2 / managed-OBS / loop re-qualification runs **once**, at the end of S2
(§3.4).

## 0. Prerequisites the coordinator verifies at kickoff

| # | Check | Why |
|---|---|---|
| P1 | **DONE 2026-09-25:** OD-2 merged as #229 (`8fe3b551`), and #230 (managed-OBS false exit) followed (`07b1ad5d`). Since `386f28f2`, only `live_host.py` (+10, the managed default) and `managed_obs_qualify.py` changed among the cited files. The core, G2, derivation, probe and P2 files are untouched. | S2 re-runs OD-2's gates at both rates against main's harness |
| P2 | loopMode is merged, including WS-C (`p2-loop` rebuilt from `output/p2-binary`, `allow_soak_plan` deleted from `managed_obs_qualify.py`, L5 run) | S2 folds the `loops` annex; the probe is shared; S3 would otherwise break `allow_soak_plan` |
| P3 | `git diff` of main vs this plan's base for `lc`, `js`, `g2`, `live_host.py`, `scripts/live_continuity_probe.py`, `scripts/managed_obs_qualify.py`, `p2_verdict.py`, `scripts/p2_recovery_html_*.py` | Re-verify §1 citations before briefing implementers |

## 1. Verified current state (origin/main `386f28f2`; loop branch where marked)

| # | Brief limitation | State | Evidence |
|---|---|---|---|
| 1 | Implicit lifecycle; no "retire here" for a movie that ends | **Partial** | `stash` pools only plan-named **assets** (`js:744`), which closes the WA0125 stray. An explicit `retire` exists only as a **refusal**: at most one per plan, before the first restart/bridge (`lc:781,783`; `js` `retireBoundary` `:395-399`). `derive_plan` never emits an end: it only considers `continuing = set(outgoing) & set(incoming)` (`lc:1469`). Before the first cut, pin is **implicit** (no entry; `js` docstring `:31`). A remount with no measured rect falls back to a movie footprint picked by **elId parity** (`js:1392`). |
| 2 | Only the first restart and first bridge are honoured | **Open** | `restartMinHash`/`slide4MinHash`/`bridgeBoundary` take the minimum `atScene` (`js:374-393`). A `restart` entry carries no `movieKey`, so it applies to every movie. `to_runtime` refuses a second bridge (`lc:767-768`), anything actionable after a bridge (`lc:769-770`), a bridge before the first restart (`lc:828-829`). `_movie_table` refuses two distinct bridging assets (`lc:924`) and names only first-slide single-instance assets plus the bridging asset. |
| 3 | One static deck-global footprint; pin only before the first cut | **Open** | The footprint is the first slide's rect (`lc` `_movie_table` `:913-955`). `keepAtFootprint` stops at `restartMinHash` (`js:871`). `to_runtime` refuses a pin after a cut (`lc:825-826,864-867`). **P2's only pin (1→2) derives as a refusal → `retire`** (`tests/test_live_continuity.py:373-386`); P2 injects it as `glReplay` with the retire fallback (`p2_verdict.py:475,495`). No qualified plan exercises a plain pin. |
| 4 | Same-asset instances told apart by order | **Partial** | Reuse is FIFO by asset **filename**: `assetKey(value)` then `q.shift()` (`js:1747,1776`). Geometry identity exists only inside the glReplay zone: `glCarried` (`js:577-606`) matches the rect measured at `atScene-1` against `instanceRect` (≤1 px, exactly one match, else `ambiguous`), and `authoredRectOf` is null unless GL (`js:568-573`). Derivation (`_resolve_continuation`, `lc:1260-1275`) resolves only a single instance or a unique geometry-equal pin pair; anything else makes the **whole deck** Unsupported. The loop branch adds an every-instance loop-agreement rule (`lc:1541-1552` on that branch) for exactly this reason. |
| 5 | Linear src→dst interpolation, no native easing | **Open (accepted residual)** | `keepThroughBridge` (`js:914-968`) notes `geometrySource: 'export-duration-interpolation'`. |
| 6 | Viewport must equal the canvas | **Closed** (I3, #175) | `stageMap`/`toScreen` (`js:334-350`); host `_stage_gate_outcome` (`live_host.py:912-930`) accepts any uniform scale; README "Scaled stage". |
| 7 | "Play across slides" is inferred | **Open (policy residual)** | `derive_plan` treats every same-asset Magic Move as pin/bridge (`lc:1462-1503`). |
| I | Instrument gaps | **Partial** | The host probe **has** a DOM stray check: `PAINTING_VIDEOS_JS` (`live_continuity_probe.py:245`) plus `match_painting_videos` (`:2090`), giving `unexpectedVideos` per settled slide. **P2 has none** (pixel stray only, `p2_verdict.py` `STRAY_*` footprint params `:1493-1504`). The probe's verdicts are hard-wired to P2 slot positions (`ground_truth_facts` `:732-783`: needs exactly one pin and one bridge, ≥4 slides; `GOTO_MATRIX` `:164` is P2 ordinals). The only probe red arm is `bridge_disabled` (`:820`). No recorded run of the brief's "disable the stash filter" red control exists. |

**Facts this plan relies on (re-check in S0):**
- **F1 (verified in `main.js`, sha `e9b2fad4…`).** The player makes a movie element in `xB.initVideo`:
  `createElement("video")`, style, `setAttribute("id", this.movieId)`, **then** `setAttribute("src", …)`, where
  `movieId = objectID + "-video"`. So the runtime's `setAttribute('src')` hook knows which **destination instance** the
  fresh element is. Elements are cached per slide in `movieCache[objectID+"-video"]`, and `resetMediaCache()` runs on
  every slide change, go-to (`jumpToSlide`) and back (`goBackToPreviousBuild`): one fresh element per instance per slide.
  Exceptions, no `<video>`: web video (`initWebVideo`, an `<iframe>`) and image movies (`png|gif|heic*` → `LB`).
  The runtime moves ids only on the **pin** path (`js:1813`, `preserved.id = el.id`); on the **bridge** path the
  carried decoder keeps its old id (`bridgeTo34`, `js:1096`) and the suppressed `el` keeps the new one.
- **F2.** Every movie instance in the committed fixtures has a distinct `objectID`, per slide and across slides (6 slides of `tests/fixtures/live_continuity/minimal_alpha_dsk`).
- **F3 (corrected).** Keynote pairs a repeated class by **preference tiers first** ({stroke, opacity} > raw stored path
  > fill/style), **then** minimum total centre distance (`validate._mm_nearest`, `validate.py:946-988`; memory
  `mm-shape-identity`). This was live-measured on **images and shapes** (main checkout `output/evidence/mm-dup-pairing/gen.py`
  inserts `sq.png`), **not on movies**. Objects that build in on the destination or out on the source never pair;
  movie-start builds do not exclude them (owner-observed). The KPF export has `opacity` in `initialState` but no raw path
  or style tiers.
- **F4.** G2 reads its entry from `window.__OBED_CONTINUITY__.boundaries` (`action === 'glReplay'`, exactly one), needs
  `plan.movies[entry.movieKey]` to exist (`g2:109`), and ignores extra entry keys (`validEntry` `g2:104-137`,
  `validate_gl_replay_entry` `g2:1347-1417`). It reaches the core only via the seam (`carried(movieKey)`,
  `release(movieKey, {rect: slotRects[movieSlot]})`, `movieKeyOf`, `setKeepWarm`, `note`; `js:1826-1846`). The core
  retires the zone unless `m.version === 1` (`js:531`) and pins a release at `toScreen(GL.instanceRect)` (`js:682`).
- **F5 (new): the core's instrument API.** Scorers read these by name, so S2 must keep them byte-compatible:
  - note kinds `bridge-3to4` (`p2_verdict.py:123`, bridge engagement `:3159`), `reuse-decoder`, `reuse-skip-boundary`,
    `retire-on-start-movie` (P2 restart guard, `p2_recovery_html_adversarial.py:3716-3830,4150-4177`),
    `retire-boundary`, `preserve-refused`, `dom-swap`, `facade-block-clear`, `remount-*`, `pool-cleared`, `glreplay-*`
    (`p2_verdict.py:130-175`), each with today's `detail` fields (`key` = movieKey, `elId`/`newElId`/`elIds`);
  - element properties `__obedSuppressed34` (P2 sampler `p2_recovery_html_dissolve_live.py:266` → `suppressed34`
    painter classification), `dataset.obedPreserved`, `dataset.obedRemounted` (S1 retire hand-back reads it), `__obedElId`, `__obedGen`, `__obedFacadeFor`;
  - `footprintOwnerDecoderId` (`js:256-320`), which reads `movies[k].footprint` through `footprintKeyForRect` (`js:1217`).
- **F6 (new).** `scripts/managed_obs_qualify.py` (OD-2) imports 14 probe symbols (Opus r3 recount; all still exist) (`GL_REPLAY_READ_JS`,
  `PAINTING_VIDEOS_JS`, `_carried_el_id`, `_movie_entries`, `_notes`, `armed_evidence`, `forced_fail_seed`,
  `ground_truth_facts`, `ground_truth_plan`, `load_slides`, `matches_asset_keys`, `score_armed`,
  `wait_for_destination_hash`) and reads `ground_truth_facts(plan, armed=True)["armed"]["instanceRect"]`.
- **F7 (new).** Rects are measured by the 200 ms `captureLayout` interval (`js:1649-1652`) while a video is attached.
  At detach, `getBoundingClientRect` is empty. So a rect "measured on `atScene-1`" needs the source to be attached for
  ≥ one tick on the transition scene (`glCarried` already depends on this).

## 2. Target design

### 2.1 Runtime plan, schema 2 (`CONTINUITY_VERSION` 6)

One flat `boundaries` list with **one entry per (boundary, planned instance)**. The list stays flat so G2's filter and
validator still work unchanged (F4). Every entry keeps `movieKey`, because P2 scorers find entries by
(`action`, `atScene`, `movieKey`) (`p2_verdict.py:837,1405`).

```json
{
  "schema": 2,
  "movies": {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x":109,"y":795,"w":952,"h":268}}},
  "boundaries": [
    {"atScene": 8, "action": "bridge", "movieKey": "movie1", "durationSeconds": 1.5, "loop": false,
     "src": {"objectId": "…", "rect": {"x":198,"y":797,"w":952,"h":268}},
     "dst": {"objectId": "…", "rect": {"x":327,"y":709,"w":1266,"h":356}}}
  ],
  "transparentBackground": false
}
```

| action | needs | runtime meaning |
|---|---|---|
| `pin` | src, dst, loop | Carry `src` (§2.2). The fresh `dst` element is facaded onto it (existing `bindFacade`). Hold at `dst.rect` from `atScene-1` until the entry naming `dst.objectId` as its `src`. |
| `bridge` | src, dst, loop, durationSeconds | Carry `src`. Interpolate `src.rect→dst.rect` during `atScene-1` (existing motion code). Suppress the fresh `dst` element (`__obedSuppressed34`, name kept, F5) and hold at `dst.rect` (generalised `bridgeTo34`/`keepAtSlot`). |
| `restart` | src (dst informational) | If `src` is carried: retire it **when the fresh element of the same asset sets `src` at hash ≥ `atScene`**, today's point, emitting `reuse-skip-boundary` + `retire-on-start-movie` with today's fields (F5). Retiring at `atScene-1` would blank the outgoing movie during the Dissolve. The fresh element plays natively and can **start a new chain**. |
| `retire` | src, `reason: "refused"｜"ends"` | From `atScene-1`, retire the carried `src` decoder, if any, and hand back to the raw player: nothing pooled for `src`, clears really run, and `preserve-refused` / `retire-boundary` are noted per instance. `ends` = no instance continues on the far side. |
| `glReplay` | today's fields unchanged (`fallback`, `slotSizes`, `slotRects`, `opacityOverrides`, `instanceId`, `instanceRect`, `movieSlot`), plus src, dst, loop | Today's pending/armed/released/retired zone, keyed on the instance. `released` = `pin` at `dst.rect` (= `instanceRect`). The zone ends at the next entry naming `dst` as `src`. |

Rules the runtime relies on. `to_runtime` enforces them and the JS re-checks only `schema === 2` (fail closed: install nothing).
- **Chain invariant.** Every `dst` of a pin/bridge/glReplay entry is the `src` of exactly one entry at the next boundary, unless the deck ends. Each `src` appears at most once.
- **Carry candidates = pooled ∪ held.** A decoder the runtime already holds (a bridge overlay on `#body`, a pin overlay) is
  never detached by the player, so it never reaches `stash`. It is a candidate for the next entry that names its instance
  (rev 1 gap: without this, D1/D2/D3's chains through a bridge cannot continue).
- **Nothing un-planned is touched.** `stash` pools a decoder only when the upcoming boundary has a pin/bridge/glReplay entry whose `src` is its **instance** (§2.2). The reuse hook acts only when the fresh element's id is an entry's `dst.objectId + '-video'`. Every other `<video>` passes through. A suppressed `dst` element's clear **really runs** once its slide ends (today it is swallowed, so each bridge in a chain would leak a hidden decoder).
- **Deleted:** `restartMinHash`/`slide4MinHash`/`bridgeBoundary`/`retireBoundary`-as-singleton, the "dissolve restart zone" test in the reuse hook (replaced by the per-entry restart), and the elId-parity footprint fallback (replaced by the entry's `dst.rect`). **Kept:** every F5 name, even the `34`-suffixed ones. Renaming them is out of scope.
- **Per-slide resting rect** = the holding entry's `dst.rect`, never a deck-global footprint (#3). `movies` names every asset with at least one entry. `movies[k].footprint` = that asset's first planned instance rect, **instrument-only** (F5; nothing positions from it). For P2 it stays `109,795,952,268`.
- **At most one `glReplay` entry per plan** (G2 contract). Later glReplay-eligible refusals derive as `retire` (OQ-4).
- **Unchanged:** `clear()` (go-to) bumps the generation and drops pool + held set. `disable()` works only before anything is preserved.

### 2.2 Instance identity: objectID at runtime, rect offline (OQ-1 (c))

- **Plan side.** Each entry names `src`/`dst` by `objectId` (the export's `objectID`, already on `_MovieInstance.object_id`) and authored rect.
- **Runtime side.** `v.__obedInstance` is set from `el.id` (strip `-video`) when the fresh element sets `src` (F1: the id
  is set first). **On carry it is re-stamped to `entry.dst.objectId`**: the carried decoder now *is* the destination
  instance. After a bridge its DOM id still names the old source (F1), so rev 1's "stamp from DOM id / first stash" would
  refuse every boundary after a bridge. `v.__obedAuthoredRect` is still recorded when available, but only as
  **diagnostic** detail on the carry note. It never gates a carry.
- **Carry rule.** At an entry's fresh `dst` element, pick the candidate (pooled ∪ held) with `__obedInstance === entry.src.objectId`. There must be exactly one. On zero or several, that **boundary** is refused: the fresh element plays raw, and the runtime notes `preserve-refused {reason: 'absent'|'ambiguous'|'loopMismatch'}`. The carry note records the measured rect vs `entry.src.rect` for diagnosis only.
- **glReplay keeps its existing rule unchanged.** `glCarried` still requires the rect measured on `atScene-1` to be within 1.0 px of `instanceRect`, because G2's texture patch depends on that geometry and P2 is the oracle for it. It adds the objectId filter first.
- **Where the rect is checked (OQ-1 (c), owner 2026-09-25).**
  - Offline: `to_runtime` requires each entry's `objectId` and rect to name the same export instance.
  - In the gates: the probe scores every landing rect, and the stray check scores every painting video.
  - The runtime does not re-check the rect. This drops rev 2's F7 cost: there is no ≥ 200 ms dwell before a carry.
- **Why objectId suffices.** The player sets `id = objectID+"-video"` before `src` (F1); ids are unique per deck (S0 V3);
  the carried decoder is re-stamped on every carry. What (c) gives up is a live check that the page draws an instance where
  the export says. The gates catch that in qualification rather than on air.
- **Derivation pairing** (replaces `_resolve_continuation`). Pair the outgoing and incoming instances of one asset by minimum total centre distance (F3), over all `perm(n, k)` assignments (cap `MM_MAX_ASSIGNMENTS`, above it → refuse). Extract the distance-only assignment core of `validate._mm_nearest` into a small pure helper only if `validate`'s tests and golden report cards stay byte-identical. Otherwise keep a local helper in `lc`.
  - **R1.** Refuse the boundary when the best and second-best total distances are within **16 authored px** (OQ-2).
  - **R1b.** Refuse the boundary when the candidate instances differ in exported `opacity`, because Keynote's tier-1 preference would override distance (F3). The export cannot show the other tiers. That residual is covered by V4.
  - **R2.** Refuse the boundary when a continuing instance builds in on `dst` or out on `src` (OQ-10).
  - Pin vs bridge is decided by `close_to` on the chosen pair, as today.
  - Unpaired outgoing instances get no entry unless they can be carried (then `retire ends`). Unpaired incoming ones ("entering at a Magic Move") get none, so they play raw.
  - At a Dissolve / no transition, every carry-capable outgoing instance gets `restart` if its asset is on the far side, else `retire ends`.

### 2.3 Refusals: extended, never relaxed

Kept: rotation or a non-identity affine, nested video layers, masks/contentsRect, unknown transition kinds, >1 movie changing geometry in one move, missing/non-positive duration, overlap above the destination (→ retire or glReplay), and the codec gate.

New:
- **R1 / R1b / R2** as in §2.2.
- **R3.** The transition is not on the **last event** of the outgoing slide, so the runtime's `atScene-1` convention would be wrong (S0 V2; refuse the deck if violated).
- **R4.** The carried pair disagrees on loop (§2.4).
- **R5.** An objectId repeats across slides. Refuse the deck unless S0 shows the ids are only unique per slide, in which case key on (player index, objectId).
- **R6.** The chain invariant fails (the deck is `unsupported`, naming the entry).
- **R7.** A continuing movie is a web video or an image movie (F1: no `<video>`) → refuse that boundary.
- **R8.** The paired instances differ in trim, meaning the export movie node's `startTime`/`endTime` differ, or the
  asset URL's trim suffix does. Refuse that boundary. `_TRIM_SUFFIX_RE` (`live_continuity.py:34`) strips the trim range,
  so today two differently trimmed clips of one file count as the same movie and would be carried as continuous (owner
  2026-09-25).

Change of **granularity**: an ambiguous pairing refuses **one boundary** (retire), not the whole deck. Today it refuses the deck.

### 2.4 Loop and glReplay fold-in

- **Loop.** With exact instance identity, the loop branch's every-instance rule narrows to **the carried pair must agree** (src.loop == dst.loop). A carried decoder keeps its source's `loop` until the destination's movie-start build runs `setLoop(true)`. `bindFacade` **forwards** that to the carried decoder (`js:1521`), so only no-loop→loop is ever repaired, and only on a facaded pin (loopMode plan §1). Each pin/bridge/glReplay entry carries `loop`. The runtime checks `decoder.loop === entry.loop` at carry time (mismatch → `preserve-refused loopMismatch`). The **`loops` annex** is Python-emitted and never read by the core (loop branch: `lc:880-894`; no `js` change). It is deleted in S2: per-entry `loop` already makes a looping deck sign differently. `ContinuityPlan.loop_instances` (the probe's force-wrap scorer) stays.
- **glReplay.** G2 bytes are untouched: `GL_REPLAY_VERSION` stays 1, the sha stays `10a5b36a…`, the seam `glReplay.version` stays 1, and the core's `m.version !== 1` check is unchanged. The entry keeps every field G2 validates, and `src`/`dst`/`loop` are additive (F4). `instanceId` stays `asset#index` (the probe binds it, `live_continuity_probe.py:663`). The armed pooling and `glCarried` filter by objectId (§2.2) and then keep G2's existing ≤ 1 px check against `instanceRect`, unchanged, as §2.2 says. `src.rect` and `instanceRect` differ by ≤ 0.5 px on a pin (`lc:31`). S2 WS-R, 2026-09-25. `release` still pins at `instanceRect`.

### 2.5 Version and sha consequences (S2)

| Item | Change |
|---|---|
| `CONTINUITY_VERSION` | 5 → 6. `__OBED_P2_PRESERVE__.version` 8 → 9 (no reader asserts 8). `PINNED_CORE_SHA256` re-pinned (`tests/test_live_continuity_js.py:25,38`). |
| G2 | Unchanged (version 1, sha `10a5b36a…`). `test_the_real_core_arms_the_zone_for_the_real_module` (`tests/test_live_gl_replay_js.py:3268`) is fed a schema-2 plan and must still read `[pending→armed moduleReady]`. |
| Plan shas | All change: `EXPECTED_PLAN_SHA256` (`tests/test_live_continuity.py:386`), `GL_REPLAY_RUNTIME_PLAN_SHA256` (`:2658`), `OFF_PLAN_SHA256` (`tests/test_p2_adversarial_gl_replay.py:50`), loop shas. The allowlist is **replaced** by the new P2 off/on + p2-loop off/on shas + each S0 deck as it derives (S2 branch only; §3.4). |
| P2 injection | `p2_verdict.build_continuity_plan` (`:495`, `GL_REPLAY_BOUNDARY_1TO2` `:475`) emits schema 2 in the **same commit**. Equality with `derive_plan(…, gl_replay=True).to_runtime()` stays tested (`tests/test_p2_adversarial.py:3430-3444`). P2 thresholds and scorers are untouched (F5 is why). |
| Host | `_resolve_gl_replay`'s `CONTINUITY_VERSION < 5` gate (`live_host.py:882`) is unchanged. `output.continuity.notCarried` (`:973`) is emitted per (boundary, instance) with the R-code. |
| `managed_obs_qualify.py` | Asserts the G2 sha (`G2_SHA`) and imports the F6 probe symbols. It needs no edit **if** WS-G keeps those symbols and the `ground_truth_facts(…)["armed"]` contract. Rev 1 said "asserts only the G2 sha", which was wrong. |

## 3. Stages

Roster (owner default "[1xtraH → 1H]/N/Codex"): Opus MEDIUM implementers, **one per disjoint file set**, launched in one
message. Codex `gpt-5.6-sol` reviews the combined diff before any gate round (`codex exec -m gpt-5.6-sol -s read-only -o
<out> "$(cat p.md)" < /dev/null`, NON-INTERACTIVE prefix, the reviewer classifies each finding; Opus fallback if Codex is
limited, as for OD-2). Every code PR runs the **full local suites**: `uv run pytest tests/ -n auto --dist loadfile`,
`npm run test:ui`, `npm run test:maps`. Branch per stage. **No merge without the owner.** Browser gates run from a fresh
worktree pinned to a commit, with at most 3 headless Chromes; OBS only on the owner's word.

### S0: owner decks and offline verification (no product code; may start now: OQ-3)
- **Owner** authors D1–D6 (§5). `counter-a.mov` / `counter-b.mov` are already in main-checkout `output/fixtures/qual-movies/`.
- **Coordinator** exports-to-fixture layout, and a trimmed `tests/fixtures/live_continuity/<deck>/` per deck.
- **Checks:**
  - V1: F1 on every deck. Headless, on P2 and D1–D5: every `setAttribute('src')` on a player-created `<video>` sees `el.id === objectID + '-video'` of an instance on the current slide. Not "every `<video>` in the DOM": carried bridge decoders legitimately keep an old id.
  - V2: R3, the transition is always on the last event, across p2-recovery, gl-decks, p2-loop and D1–D6.
  - V3: R5, objectId uniqueness across slides (⌘D-duplicated slides included).
  - V4: F3 on each deck's pairs. Scratch-derive them, and have the owner confirm by eye in Keynote that the pairing matches. This is the only evidence that movies pair like images do.
  - V5: the D4 FIFO trap. Record which S1 decoder today's core pools first at the S1→S2 detach (diagnostic for `fifo-reuse`).
- **Output:** a §1/§2 amendment only. Nothing is committed but fixtures (in S2's PR).

### S1: instrument first (no product bytes; after loopMode merges, since it shares the probe)

**S1 DONE 2026-09-25 (gates PASS at merge `421b4f39`; record `.agents/reviews/continuity-generalisation/s1-gates-r1.md`).** Merged as #237 (`2ee95223`).

| WS | Files (exclusive) | Work |
|---|---|---|
| G | `scripts/live_continuity_probe.py`, `tests/test_live_continuity_probe.py`, **new** `scripts/continuity_core_variants.py` (+ its test), `scripts/managed_obs_qualify.py` + `tests/test_managed_obs*.py` (only if an F6 symbol must change) | Per-boundary verdicts **generated from `ContinuityPlan.boundaries[].movies[]`** (so they do not depend on the runtime schema), one per (boundary, instance, action): `carry` (pin/bridge: identity + owner agreement + windowed clock advance + accumulated stall + phase-ordered rect path + landing rect), `restart` (fresh clock from ~0 on dst, old decoder gone), `retire` (raw-player behaviour + no remount + `retire-boundary` noted), `armed` (existing). P2 legacy names (`continue1to2`, `restart2to3`, `continue3to4`, `refused*`, `armed1to2`) become aliases, so `run_gates.sh` output compares. `ground_truth_facts` stops requiring the P2 shape but **keeps its `["armed"]` contract and every F6 symbol**. `GOTO_MATRIX` is derived from the plan: into a mid-chain slide, then advance across the next carry. Red arms: `--strip ACTION[@atScene]` (a probe-only `to_runtime` monkeypatch dropping one entry, generalising `bridge_disabled`) and `--core-variant {stash-any,wrong-instance,fifo-reuse}` (string transforms of `PRESERVE_CORE_JS` in `continuity_core_variants.py`: pool every asset instance / carry a same-asset decoder that is **not** `src` / today's FIFO pick). A variant arm reports and expects the **variant's** core sha. |
| H | `scripts/p2_recovery_html_adversarial.py`, `scripts/p2_recovery_html_dissolve_live.py` (sampler rows only if needed), `src/obed_edom/p2_verdict.py` (verdict layer only), `tests/test_p2_adversarial*.py`, `scripts/run_gates.sh` | P2 verdict **`noStrayVideo`**: on each settled slide, the connected `<video>`s the P2 sampler already classifies as painting (`visible && !suppressed34`, `p2_recovery_html_dissolve_live.py:245-290`; no new page JS) match `ContinuityPlan.slide_instances` for that slide one-to-one by rect (every authored instance, planned or not). The finding count goes 14 → 15. `--core-variant` imported from WS-G's module. `run_gates.sh` gains the stray red arm and the `--strip` arms, and prints each arm's **pre-registered expected red set** so a human diff is not the check. |

**S1 gates (on main's runtime; no re-qualification):**
- **G-S1a, rescore control.** The plan-generated scorer on stored P2-host artifacts (main-checkout `output/evidence/gates-glc/`, `output/evidence/loop-gates/l4-final/host-*.json`) reproduces the legacy verdicts exactly.
- **G-S1b.** The P2 fixture is fully green: 15/15 off, plus `glReplayCarry1to2` under `--gl-replay auto`.
- **G-S1c, stray red.** `--core-variant stash-any` on P2: host `unexpectedVideos` non-empty on slide 4 (WA0125), and P2 `noStrayVideo` red **only** there.
- **G-S1d.** `--strip bridge@8` red only on 3→4. `--strip retire@2`, and `--strip glReplay@2` under `--gl-replay auto`, red only on the **1→2** verdicts. On main's runtime a stripped refusal falls back to the implicit pin, so `refused*` goes red as well as `armed1to2`. `--strip restart@6` is recorded as the current behaviour. Each arm's expected set is written into `run_gates.sh` before the run.

### S2: derivation v2 + core v6 (the only runtime-byte stage; after OD-2 and loopMode merge)

**S2 IN PROGRESS (paused 2026-09-25 for the owner's vacation).** S2.0 and all four streams are done. The dev loop is green on P2 and D1–D6 at 1920×1080 (core `9c4fc61f`). State and next steps: `.agents/handovers/keynote-live-continuity-2026-09-25-s2.md`.

| WS | Files (exclusive) | Work |
|---|---|---|
| D | `lc`, `src/obed_edom/validate.py` (helper extraction only, if byte-safe per §2.2), `tests/test_live_continuity.py`, `tests/test_live_continuity_decks.py`, `tests/test_validate*.py` (the helper's callers), `tests/fixtures/live_continuity/**` | §2.1 schema, §2.2 pairing, §2.3 R1–R8, §2.4 loop narrowing + annex removal, chain invariant, `retire ends`, one `Unsupported`/refusal test per R-code. Owns `tests/fixtures/live_continuity/runtime_v2_examples.json`, the frozen schema examples WS-R tests read. Adds each S0 deck's plan shas to the allowlist as the deck derives (S2 branch only). |
| R | `js`, `tests/test_live_continuity_js.py`, `tests/test_live_gl_replay_js.py` (cross-module test + its `RUNTIME_PLAN`) | The §2.1 walk (pooled ∪ held, restart timing, suppressed-dst clear), the §2.2 objectId-only matcher with carry-time re-stamp (glReplay keeps its rect check), diagnostic-only rects, §2.1 deletions, `CONTINUITY_VERSION` 6, re-pin. Node tests per action, plus: a two-instance FIFO trap, a looping mismatch, bridge→pin and bridge→bridge chains (the re-stamp), a go-to `clear()` mid-chain, and **one test per F5 name** asserting the note kind/fields and properties survive. Keeps every comment that encodes a model fact. |
| P | `p2_verdict.py` (`build_continuity_plan` only; WS-H owned it in S1), `tests/test_p2_adversarial.py` (equality test), `tests/test_p2_adversarial_gl_replay.py` (`OFF_PLAN_SHA256`), `tests/test_p2_adversarial_driver.py` (plan-signature use), `live_host.py`, `tests/test_live_host.py`, `README.md`, `.agents/skills/obed-edom/SKILL.md` | Schema-2 P2 injection, per-instance `notCarried`, capability-report wording (#5, #7), and a short **live-continuity contract** section in SKILL.md (chain invariant, refusal codes, identity rule, F5 names frozen). |
| G | the probe (as in S1) | Adapt to schema 2 where it reads the runtime plan (`armed_fact`, instance binding). Enable `--strip pin@…` and `--strip restart@…` against decks. |

**Dev loop (before the expensive round).** The headless probe on P2 + D1–D6 at 1920×1080 runs every iteration, with the
P2 harness fast profile on the S2 core. The iteration fixes are folded, and then Codex reviews. Bugs the decks find land
here, so the §3.4 round runs once.

### 3.4 The ONE re-qualification (end of S2, on the final S2 commit, interleaving main vs PR for P2)

| Q | Gate | PASS | Red control that must go red |
|---|---|---|---|
| Q1 | Full suites | green | — |
| Q2 | P2 oracle (`run_gates.sh`): fast, slow, `--gl-replay auto` | 15/15 (+ `glReplayCarry1to2` True under auto); every verdict equal to main's S1-scorer table | `--disable-bridge34` red only on `continueThroughMovingMagicMove3to4`; `stash-any` red only on `noStrayVideo` |
| Q3 | Host probe, 3 viewports, arms A/B/C + attach + V/Voff/Vgl + G (plan-derived go-to, incl. go-to mid-chain then carry) on P2 + D1–D6 | Every plan-generated verdict, `unexpectedVideos` empty | One `--strip` arm per action type (pin, bridge, restart, retire, glReplay), each red **only** on its boundary; `wrong-instance` red on D4's carry verdict (identity instrument); `Voff` red as today. `fifo-reuse` on D4 is recorded (red iff V5 showed A-near pooled first) |
| Q4 | G2 seam | cross-module test; Vgl hand-off; `--gl-force-fail` stands down to retire; go-to retires `cleared` | `--gl-force-fail` arm (the failsafe must fire) |
| Q5 | Loop L1 + L2 (loopMode plan §5, scorer unchanged) on the rebuilt `p2-loop` + D6 | as loop gates-r1 | non-loop fixture "no wrap recorded"; D6 S4→S5 mismatch must retire |
| Q6 | Managed OBS: `managed_obs_qualify.py` `--arm both`, `g2`, `failsafe`, `soak` at **25 and 30** (both default-on; binary counter gates cadence at both rates; 30 judged relative to same-take native per OD-2 OQ-2; soak on the looping fixture with both wrap windows, `af76ed97`) | OD-2's M1–M6 limits | OD-2's `--kb frozen/oldbytes/latelost` |
| Q7 | Real OBS (external attach) short pass on D1 + D4; **owner eyeball** in Keyer mode on D1–D5 | no stray, no visible restart where carried | — |

Gate record: `.agents/reviews/continuity-generalisation/gates-r1.md`. The gate commit keeps in the allowlist only the S2
shas of P2 off/on, p2-loop off/on, and the decks that passed Q3+Q7. The others are removed before the PR is offered.

### S3: delete the allowlist (owner's call, OQ-8; Python + docs only, no JS bytes → no re-qualification)
- **WS-D:** remove `QUALIFIED_PLAN_SHA256` and its `to_runtime` check. Keep `plan_signature` as a reported field (`output.continuity.planSha256`). WS-P updates `tests/test_p2_adversarial*.py`/`tests/test_live_host.py` uses of the allowlist.
- **Tests:** a negative corpus, one synthetic export per refusal code, derives the named reason.
- **WS-P:** README states plainly what is and is not carried.
- **Gates:** full suites, plus the probe on P2 + D1–D6, whose **runtime plans are byte-identical** to S2's, and whose verdicts must equal the S2 gate's. One **real owner sermon deck** dry-run, headless: it must derive `qualified` with a green probe, or `unsupported`/declined with named reasons.

### 3.7 F: `output/fixtures/` consolidation (owner decision relayed by the loop session, 2026-09-25; lands in S2's PR)

**Why.** Fixture paths are hard-coded all over. Counts on origin/main per the loop session:

| Fixture | Mentions |
|---|---|
| `p2-recovery` | ≈39 in 19 src/scripts/tests files, plus handovers, the runbook, and every worktree's symlink of `output/p2-recovery/html-adversarial` |
| `p2-binary` | 14 in 8 files |
| `p2-loop` / `p2-loop-grey` | 34 in 5 files |
| `p2-soak-loop` | 2 test files, absolute path |
| `gl-decks` | `tests/test_live_continuity_decks.py`, absolute path |

S2 re-runs every gate anyway, so moving the fixtures there breaks no worktree mid-flight. Gate evidence is a separate
docs PR by the loop session (`output/evidence/<name>`); this plan cites those paths.

**Scope.**
- **Move** (main checkout, `mv`, never copy+delete) to `output/fixtures/<name>`: p2-recovery, p2-binary, p2-loop,
  p2-loop-grey, p2-soak-loop, gl-decks, qual-decks, qual-movies.
- **Left alone:** `bank`, which is a cache.
- **One resolver:** new `src/obed_edom/fixture_paths.py` with `main_checkout()` (adopt `loop_fixture.main_checkout()`'s
  logic and make that script import it) and `fixture(name) -> Path`, resolving `<main checkout>/output/fixtures/<name>`,
  so a worktree needs no symlink. `binary_counter_movie.py`'s derivation from `P2_FIXTURE`'s parent goes through it too.
- **Every literal** in src/scripts/tests goes through `fixture(...)`. A test asserts that no `output/p2-`/`gl-decks`/
  `qual-` literal remains outside `fixture_paths.py` (grep-style, excluding docs).
- **Docs:** SKILL, `decklink-field-test-runbook.md`, the live handovers the plans still cite, and memory citations
  (coordinator). The worktree convention becomes "nothing to symlink". If some script still needs a relative
  `output/` path, one symlink of `output/fixtures`.

**Order inside S2.** Step **S2.0**: one Opus MEDIUM implementer, sequential, BEFORE the parallel work streams. It touches
files every stream owns, so it cannot run beside them. Its own check is the full suites, plus a resolver smoke (every
`fixture(name)` exists in the main checkout). The S2 re-qualification (§3.4) then exercises every moved path. The
coordinator does the `mv` in the main checkout only after S2.0's code is ready, and records the before/after listing in
the gate record.

### 3.6 V: validation rule `mm.movie_restart_midmove` (owner 2026-09-25; independent of S1–S3)

**Why.** A Magic Move whose outgoing movie has play-across off moves the movie, then restarts it midway along the path.
Observed natively on D2 with slide 1 set to off. The owner rules this an authoring error: severity **`error`**, surfaced to
the operator. Continuity still carries the pair (no refusal).

**Rule.**
- **Pairs:** for every Magic Move slide pair, take each movie pair from the existing `validate._mm_matches` (repeated movies
  paired by `_mm_nearest`, ambiguous ones skipped).
- **Flag:** raise when the **outgoing** movie's `playsAcrossSlides` is false. Message names both slides and the movie.
- **Data:**
  - The flag comes from the `.key`, read offline by `iwa_movies.movie_archives` (verified 2026-09-25 against D2,
    D2-across and Positive Control).
  - Each archive matches the validation item by slide index + rect, within 1 px.
  - No unique match → no finding. Never a guessed error.
  - Attach it where `attach_magic_move` is attached (checker + web-inspect validation sites).
  - When no `.key` is readable, the rule is silent and says so in the rule's debug detail.

**Files (one Opus MEDIUM implementer):**
- `src/obed_edom/validate.py` (rule + attach)
- `src/obed_edom/validation_rules.yaml` (`mm.movie_restart_midmove: error`, label "Magic Move restarts a movie midway")
- `tests/test_validate*.py`
- `.agents/skills/sermon-validation/SKILL.md` (rule-id contract)

**Tests:** fixture archives shaped like D2 (slide 1 set to off) → one finding. D2 → none (its off movie leaves by
Dissolve). D2-across → none. D4 → the near copy is unpaired, so no finding.

**Red control:** a D2 pair with the flag forced true must yield zero findings, and forced false exactly one.

**Gate:**
- full suites;
- run on `Continuity/D1–D6.key` → zero findings (all play-across on);
- run on `Minimal Alpha_DSK.key` (9 slides; its S3→S4 is a **Dissolve**, unlike the older 4-slide P2 export) → any
  play-across-off movie that leaves by Magic Move is listed for owner review. A play-across-off movie leaving by Dissolve
  is a normal restart and is never flagged.

**Sequencing:**
- **Collision:** it touches `validate.py`, which S2's WS-D also edits (helper extraction). V lands first, or WS-D rebases
  onto it.
- **Timing:** V touches no continuity bytes, so it may run before OD-2/loopMode merge (**OQ-16**).

## 4. Instrument rules (every gate has a red control)
- **Stray-movie check in both gates.** Host `unexpectedVideos` (exists) and P2 `noStrayVideo` (S1). `noStrayVideo` claims **only** that no painting `<video>` fails to claim an authored instance and no instance is claimed twice. It does **not** score presence (Codex R1-9, closed by narrowing): Magic-Move-settled slides legitimately paint through WebGL, so presence stays with `refusedCarry1to2`/`glReplayCarry1to2`, `deliberateRestart2to3` and `continueThroughMovingMagicMove3to4`. Red: `--core-variant stash-any` on the P2 fixture (WA0125 on slide 4).
- **Per-boundary verdicts from the plan.** Never from slide positions. The rescore control (G-S1a) proves the new scorer equals the old on stored artifacts before it replaces it.
- **A red arm per action type.** `--strip ACTION@atScene` must turn exactly its pre-registered set red, and every other verdict must match the unstripped run.
- **Identity red.** `--core-variant wrong-instance` on D4 must fail the carry verdict: the carried clock is A-near's, ~3 s ahead of A-far's (the probe dwells ≥ 3 s on S1 before click 1).
- **F5 is frozen instrument API.** A core change that drops or renames an F5 name is a finding, even if the suites pass.
- **P2 stays the oracle for shared bytes.** Any core byte change after Q2 re-opens Q2–Q6. A red under the stricter scorer is a finding, never a threshold change. INCONCLUSIVE on integrity failure (fail closed).

## 5. Deck-authoring spec (owner authors in Keynote; the coordinator never opens Keynote)

**Common to every deck:**
- **Canvas:** 1920×1080, the same theme/background as `Minimal Alpha_DSK` (black).
- **Movies:** `counter-a.mov` (60 s) and `counter-b.mov` (55 s). They are made by `scripts/binary_counter_movie.py` (1920×540 = **32:9**, 30 fps, H.264, binary frame counter; no marker option), sit in main-checkout `output/fixtures/qual-movies/`, and are distinct files so Keynote keeps two assets. "A" = counter-a, "B" = counter-b. Keep "Constrain proportions" on: every rect below is exactly 32:9.
- **Labels:** one text label per slide ("D1 S1"…) at x 40, y 40, ≤ 300×60. Nothing else on any slide, and **nothing overlapping a movie rect on any slide** (overlap = a refusal).
- **Making the "same movie" continue:** duplicate the previous slide (⌘D), then move or resize the movie.
- **Transitions:** Magic Move 1.5 s, and Dissolve 1.0 s where stated. Each transition sits on the **outgoing** slide. Magic Move match option, Start Movie and "play across slides": **copy exactly what the P2 deck (`Minimal Alpha_DSK`) uses**, and tell the coordinator the wording you saw. This plan does not guess Keynote's menu names.
- **Movie settings:** Repeat None unless stated. Start the movie as the P2 fixture's slide-1 movie does (the healthy authoring per arming §11 C), except D4's A-far, which starts on a click, the way the P2 deck's slide-2 movie starts on a click. No builds except those stated.
- **Rects** are x, y, w, h in points = authored px. Set them in the Format sidebar's Arrange tab.

**Export (each deck):**
1. Save as `~/Desktop/Convert wall to 16x9 CGs/qual/Dn.key`.
2. File ▸ Export To ▸ HTML, same options as the 2026-09-22 `output/fixtures/gl-decks/` exports, into `~/Desktop/Convert wall to 16x9 CGs/qual/Dn-html/`.
3. Tell the coordinator. The coordinator copies the export into `output/fixtures/qual-decks/Dn/` and prepares the `html-player`/`html-unmodified` pair.

Rects: coordinator's provisional 32:9 set (2026-09-25), re-checked here: all inside 1920×1080, no movie overlaps a
label or another movie on its slide, at most one geometry-changing movie per Magic Move. One change, D6's A-extra (§8).

| Deck | Slides: movie @ rect (transition to next) | Expected plan | Proves |
|---|---|---|---|
| **D1: two Magic Moves in a row** | S1 A @160,700,640,180 (MM) → S2 A @960,400,800,225 (MM) → S3 A @400,380,1120,315 (MM) → S4 A @400,380,1120,315 | bridge, bridge, pin | #2 each bridge lands at its own rect; #3 per-slide resting rect; held-decoder chain (bridge→bridge→pin) |
| **D2: restart after a bridge, then pin after the restart** | S1 A @160,700,640,180 (MM) → S2 A @960,400,800,225 (Dissolve) → S3 A @960,400,800,225 (MM) → S4 A same (MM) → S5 A @160,700,640,180 | bridge, restart, pin, bridge | #2 restart after a bridge is honoured (clock resets on S3); a restart starts a new chain; pin and bridge after a restart |
| **D3: one movie ends while another continues** | S1 A @100,400,800,225 + B @1020,400,800,225 (MM) → S2 A same + B @1100,700,640,180 (MM) → S3 B @1100,700,640,180 only (MM) → S4 B @400,380,1120,315 | S1→2: A pin + B bridge; S2→3: A **retire ends** + B pin; S3→4: B bridge | #1 explicit end of a carried decoder (no stray A on S3/S4); two planned movies; one bridge per move |
| **D4: two instances, the far one continues** | S1 A-near @160,800,640,180 (auto start) + A-far @1120,160,640,180 (starts on click 1; click 2 → MM) → S2 A @1000,400,800,225 (MM) → S3 A same | S1→2: bridge A-far→S2 (centre distances ≈266 vs ≈994 px: unambiguous), A-near gets no entry; S2→3: pin | #4 identity by objectId + rect; the fresh element can't take the near decoder; `wrong-instance` red arm; the ~3 s clock offset separates the instances |
| **D5: movie entering at a Magic Move** | S1 A @160,700,640,180 (MM) → S2 A same + A′ @1120,700,640,180 (new instance, auto start) + B @1120,160,640,180 (new, auto start) (MM) → S3 A @160,700,640,180 | S1→2: pin A; A′ and B get no entry (play raw from 0); S2→3: pin A, A′/B unpaired and not carried | Entering instances of the carried asset don't steal its decoder (today's FIFO can); unplanned movies untouched |
| **D6 (optional): looping** | Copy of D1 with A **Repeat: Loop** on S1–S4, plus S1 A-extra @**40,920,320,90** Repeat **None** (absent on S2), plus S5 A @400,380,1120,315 Repeat **None** after S4 (MM) | D1's plan with `loop: true`; S1's A-extra unpaired (≈1245 vs ≈923 px); S4→S5 **retire refused (R4)** | Loop rule narrowed to the carried pair (today every Magic Move here is declined); runtime `loopMismatch` never fires on a correct plan; R4 is visible in `notCarried` |

Before the gates run, the owner confirms by eye in Keynote (play the deck) that each Magic Move pairs as the "Expected
plan" column says (V4). For D4, wait ~3 s on S1 before click 1.

**S0 progress (2026-09-25).** Owner asked the coordinator to author, and gave a session go for Keynote. D1–D6 were built
by AppleScript from copies of the owner's template `Continuity/D1.key` (Blank Black; label = the template's top-right text
box at 1763,21, not 40,40). Start = After Transition was patched offline with `iwa_movies._patch_archive_fields`, except
D4's A-far, which stays On Click. The decks were exported with `html_preview.export_html`. The owner's `Continuity.key` and
`Continuity/D1.key` are unchanged (sha verified).
- **Decks:** `~/Desktop/Convert wall to 16x9 CGs/Continuity/built/Dn.key` + `Dn-html/`.
- **Exports:** main checkout `output/fixtures/qual-decks/Dn/html-unmodified/`.
- **Generator:** `output/fixtures/qual-decks/author/gen.py` + `decks.json`.
- **Offline read-back:** every movie rect, repeat, transition and start setting matches the table.

Offline S0 findings:
- **V2 holds:** each transition sits on the outgoing slide's last event.
- **V3 holds:** objectIDs are unique across each deck.
- **Keynote defaults:** an inserted movie defaults to `playsAcrossSlides: true`, `automatic: false`.
- **Export names:** Magic Move exports as `apple:magic-move-implied-motion-path`; the last slide exports as `none`.

On main, `derive_plan` gives each deck's expected classification, and every deck is refused today:

| Deck | Refused today by | Limitation |
|---|---|---|
| D1–D3 | "a bridge boundary precedes the first restart" | #2 |
| D4 | whole-deck "ambiguous ownership" | #4 |
| D5 | the allowlist | FIFO risk |
| D6 | `loopMode` | until loopMode merges |

D3's A end has no entry yet (#1). Still open: V1 (headless id census) and V4 (the owner plays each deck in Keynote).

**V4, owner playback in Keynote (2026-09-25).** Keynote's own playback, the reference the HTML export is judged against:
- **D2:** the Dissolve 2→3 did **not** restart. The authoring was wrong: the slide-2 movie kept Keynote's default
  `playsAcrossSlides: true`, and natively that carries it through a Dissolve. P2's 2→3 (slide-2 play-across off) and
  Positive Control S3→S4 restart. Fix: patch D2's slide-2 movie to play-across off and re-export. Keep the current build as
  `D2-across` for the investigation.
- **D1, D3:** confirmed. Every Magic Move carries; D3's A does not reappear on S3 or S4.
- **D2 (rebuilt):** the owner set slide 2's movie to play-across off, so the Dissolve 2→3 restarts natively. `D2-across` keeps
  play-across on and continues natively. Both are exported. Diff candidate: `D2-across` S2 carries one extra movie-sized
  texture (under investigation).
- **D4:** confirmed. The far copy starts on click, carries through both Magic Moves and plays throughout.
- **D5:** natively, the entering same-asset copy A′ **starts at the carried copy's frame** (a shared clock), not from 0.
- **D6:** S4→S5 (loop → no loop) restarts natively, which matches R4. S1's A-extra does not travel.

**OQ-14 answered (owner):** keep **named residuals**. An agent is investigating whether the export encodes `playsAcrossSlides`
in any form; so far it is not in any export's JSON.
- **R-res-1:** a play-across Dissolve or no-transition cut continues natively, but the export restarts it; not carried.
- **R-res-2:** an entering same-asset instance shares the carried clock natively, but the export plays it from 0.
- **R-res-3 answered (owner watch, D2 with slide 1 set to play-across off, 2026-09-25):** natively the movie **moves and
  restarts midway along the Magic Move path**. Owner decision: this is an authoring error that the **validation rule**
  (stage V, §3.6) catches with severity `error`. It is **not** a continuity refusal: AK carries the pair per 3a.

**Investigation result (2026-09-25, Opus, offline).** The HTML export does **not** encode `playsAcrossSlides` in any
form.
- **Pairs compared:** D2 vs D2-across; Positive Control S3/S4; Minimal Alpha_DSK S6/S7 and S1/S8. The movie node, the
  `movie-start` chain and `automaticPlay` are identical apart from ids.
- **The D2 extra texture is noise:** an exporter poster/background id collision that also occurs on D2 S5, which is `true`.
- **Player (`main.js`):**
  - It caches `objectID-video`, which is fresh per slide, and wipes the cache on every slide change.
  - The movie URL is per slide.
  - It never seeks or sets `currentTime`, so every incoming movie starts at 0.
- **Loop is encoded:** `movie.loopMode` changes across D6 S4→S5.
- **Limitation #7 is tightened:** continuity intent is not in the export; it can come only from the source `.key` or an
  operator decision.
- **Route if ever wanted (OQ-15):** a source-deck sidecar. `iwa_movies.movie_archives` returns `playsAcrossSlides`, and
  `_match_one_to_one` lines instances up with the export (export rects are inset about 2.5 px). `derive_plan` would then
  take the flag: `true` + Dissolve → bridge/pin, `false` → restart.

## 6. Owner questions (recommendation first)
1. **OQ-1 identity key. OWNER: (c)** (2026-09-25). ObjectID only at runtime; the rect is checked offline and by the gates (§2.2). No dwell cost. (a) was objectID + a live rect check with a ≥ 200 ms dwell; (b) was rect only.
2. **OQ-2 pairing rule.** **OWNER 2026-09-25: rec.** (a) Minimum total centre distance, refusing a boundary whose runner-up is within 16 authored px **or** whose candidates differ in opacity (R1b); (b) keep today's single-instance / geometry-equal pin pairs. **Rec (a).** It is needed for D4/D5, the margin is conservative, and V4 is the movie evidence F3 lacks.
3. **OQ-3 what may start before the merges.** **OWNER 2026-09-25: rec.** (a) S0 (deck authoring + offline checks) now, S1 after loopMode merges, S2 after both; (b) everything after both. **Rec (a).** S0 writes no code, and having D1–D6 lets S2's dev loop find bugs before the one re-qualification.
4. **OQ-4 more than one glReplay-eligible boundary.** **OWNER 2026-09-25: rec.** (a) The first becomes `glReplay`, later ones `retire`; (b) the deck is unsupported. **Rec (a).** G2 stays byte-identical.
5. **OQ-5 loop.** **OWNER 2026-09-25: rec.** (a) Narrow to the carried pair, per-entry `loop`, and delete the Python-only `loops` annex in S2; (b) keep the annex until S3. **Rec (a).**
6. **OQ-6 motion (#5).** **OWNER 2026-09-25: rec.** Keep linear interpolation as a named residual and do no easing work here. **Rec yes.**
7. **OQ-7 intent (#7).** **OWNER 2026-09-25: rec.** Keep 3a (carry every same-movie Magic Move), with the README and capability report saying "carried by inference". **Rec yes.**
8. **OQ-8 when to delete the allowlist (brief 5d).** **OWNER 2026-09-25: rec, including one real sermon deck from the owner.** **Rec:** in S3, once (i) Q1–Q7 are green with every red control recorded red, (ii) D1–D5 (+D6 if authored) pass headless, real OBS and your eyeball, (iii) the negative corpus covers every refusal code, and (iv) one real sermon deck dry-runs clean or with named refusals. Until then, decks join the allowlist one at a time (5c).
9. **OQ-9 R3.** **OWNER 2026-09-25: rec.** Refuse a deck whose transition is not on the outgoing slide's last event. **Rec yes** (S0 V2 measures whether it ever happens).
10. **OQ-10 R2.** **OWNER 2026-09-25: rec.** Refuse a boundary whose continuing instance builds in/out. **Rec yes** (unmeasured for movies).
11. **OQ-11 P2 verdict count.** **OWNER 2026-09-25: rec.** P2 gains `noStrayVideo` (15 findings); `run_gates.sh` updates in S1. **Rec yes.**
12. **OQ-12 review model.** **OWNER 2026-09-25: rec.** Codex `gpt-5.6-sol` per roster, with Opus as fallback if Codex is limited. **Rec yes.**
13. **OQ-13 Keynote wording in §5. MOOT (2026-09-25):** the coordinator authored D1–D6 by AppleScript, with start settings patched offline from `Positive Control.key`, so no menu wording is needed. The generator is `output/fixtures/qual-decks/author/gen.py`.

15. **OQ-15 read `playsAcrossSlides` from the `.key`.** **OWNER 2026-09-25: rec: scope as recommended; `.key` reading enters continuity only in the follow-up plan.**
    - **Owner 2026-09-25:** AK will import and read the `.key` anyway, so a mismatch between the export and the `.key` is
      not a concern.
    - **Proven:** `iwa_movies.movie_archives` returns `playsAcrossSlides`, `startTime`/`endTime`, slide and rect offline.
      It matches the owner's D2/D2-across/Positive Control playback.
    - **Remaining question:** scope.
      - (a) This plan's S2 takes the flag only where **no new runtime action** is needed. `derive_plan` gains an optional
        per-instance flag map, matched to export nodes by slide + rect via `_match_one_to_one`, and it is reported in
        `notCarried`. A Magic Move out of a play-across-off movie becomes a restart **if** the owner's R-res-3
        observation shows Keynote restarts there.
      - (b) A follow-up plan (S4) adds what needs new runtime behaviour: carrying through a play-across Dissolve
        (R-res-1, an overlay through a crossfade, unmeasured) and syncing an entering same-asset instance to the carried
        clock (R-res-2, a new `sync` action). That costs a second core-byte re-qualification.
    - **Rec: (a) in S2, then (b) as its own plan after S3.** This keeps S2's one re-qualification limited to measured
      behaviour.
    - **R-res-3 answered:** a Magic Move out of a play-across-off movie restarts midway natively. It is caught by
      validation (stage V), not by continuity, so (a) needs no continuity change today. The flag enters continuity only
      with (b).

16. **OQ-16 when V runs.** **Owner 2026-09-25: PARKED** (many concurrent sessions). Resume on the owner's word, as its own
    small PR, before S2 touches `validate.py` (or have WS-D rebase onto it).

## 7. Residuals kept visible
Linear bridge motion (#5), inferred intent (#7), the loop wrap-at-carry race (loopMode OQ-4), the Chromium native-layer
tone step at G2 hand-off, the linear-bridge poster sliver at the leading edge, and Keynote pairing tiers the export cannot show (R1b covers opacity only). Each one appears in the README.

## 8. Rev 2 critique: what changed

| # | Class | Change | Reason |
|---|---|---|---|
| 1 | design error | Carry re-stamps `__obedInstance = dst.objectId` | Bridge never copies the DOM id (`js:1096`), so rev 1's DOM-id stamp would refuse every boundary after a bridge (D1, D2, D3) |
| 2 | design error | Candidates = pooled ∪ **held** | A bridge/pin overlay is never detached by the player, so `stash` never sees it and no chain could pass a bridge |
| 3 | design error | `restart` retires at the fresh element's src set (hash ≥ `atScene`) and keeps `reuse-skip-boundary`/`retire-on-start-movie` | P2's restart guard requires those notes on the auto route (`p2_recovery_html_adversarial.py:4150-4177`); retiring at `atScene-1` blanks the Dissolve |
| 4 | wrong fact / design error | F5 added; rev 1's deletion of `__obedBridged34`/`__obedSuppressed34` naming withdrawn | `__obedSuppressed34` is read by the P2 sampler (`p2_recovery_html_dissolve_live.py:266`); `bridge-3to4` by `p2_verdict.py:123` |
| 5 | design error | Suppressed `dst` element's clear really runs after its slide | Today's swallow would leak one hidden decoder per bridge in a chain |
| 6 | wrong fact | F3 corrected: tiers before distance; measured on images, not movies; R1b opacity refusal | `validate.py:954-955`, `output/evidence/mm-dup-pairing/gen.py`; rev 1 stated distance only |
| 7 | wrong fact | F1 corrected: id is `movieId` = `objectID+"-video"`; per-slide cache reset; iframe/image movies; R7 added | `main.js` `xB.initVideo`, `resetMediaCache` |
| 8 | wrong fact | §2.5 `managed_obs_qualify` row + F6 | It imports 13 probe symbols incl. `ground_truth_facts`, which WS-G rewrites |
| 9 | wrong fact | Branch heads `af76ed97` / `67643332`; `lc`/`js` prefixes; line fixes (`lc:767-770`, `:825-826,864-867`, `g2:1347`, `tests/test_live_continuity_js.py:25,38`, P2 pixel-stray cite) | Rev 1 mixed files under bare line numbers and cited stale heads |
| 10 | deck-spec error | D6 A-extra moved 1500,920 → **40,920** | At 1500,920 it is 543 px from S2's A vs A's 923 px: Keynote would pair the extra, and R4 would retire S1→S2, voiding D6 |
| 11 | deck-spec error | Coordinator's 32:9 rects adopted (D4 distances updated ≈266/≈994); marker text dropped; menu wording deferred to the P2 deck (OQ-13) | The generator is 1920×540 with no marker; rev 1's UI names ("By Object", "Start Movie On Click") were unverified |
| 12 | missing gate | Red control `wrong-instance` (deterministic); `fifo-reuse` demoted to diagnostic + V5 | FIFO order at D4's detach is unknown, so `fifo-reuse` might pick the right decoder and stay green |
| 13 | missing gate | `GOTO_MATRIX` plan-derived incl. go-to mid-chain; F5 name tests in WS-R; variant arms expect the variant sha | Go-to and integrity checks were P2-hard-wired or would read INCONCLUSIVE |
| 14 | missing gate | G-S1d expectations corrected and pre-registered | On main's runtime a stripped refusal falls back to the implicit pin, so more than `armed1to2` goes red |
| 15 | nit | Ownership: `continuity_core_variants.py` (G, H imports), `test_p2_adversarial_gl_replay.py` + `_driver.py` → WS-P in S2, `p2_recovery_html_dissolve_live.py` → H | Orphaned files / shared variant code |
| 16 | nit | `noStrayVideo` built on existing sampler rows vs `slide_instances`; D-deck shas pinned in the S2 branch as decks derive; S3 "verdict-identical" | Avoid a second page predicate; rev 1's dev loop could not run D-decks with the allowlist in place; timing results are never byte-identical |

**Not folded:**
- A single `retire` with a timing flag instead of separate `restart`/`retire`. The two differ in timing and in the notes P2 scores, so merging them saves nothing.
- Renaming the `34`-suffixed names. Pure churn against frozen scorers.
- Measuring the source rect at detach instead of on the 200 ms tick (F7). The node is already detached then. A per-frame measurer is new machinery for a sub-200 ms press nobody makes on air, so it stays a residual.
- Pairing at a Dissolve. Restart needs only `src`, so no pairing ambiguity can arise there.
