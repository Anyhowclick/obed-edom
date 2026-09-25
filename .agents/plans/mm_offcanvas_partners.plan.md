---
name: Off-canvas Magic Move partners — keep them, placed off the CG canvas
overview: >-
  LANDED #224 (`c89d8296`, 2026-09-24). 2026-09-24, first-pass plan (Opus, high), from `pass1_hides_offline.plan.md` todo
  `followup-mm-leftovers`. The planner's off-slide-leftover rule (`map_remap.py:2498-2501`) hides every
  object wholly off the 7680×1080 wall. Some of those objects are Magic Move (MM) partners of on-wall objects on
  the neighbouring slide, so deleting them breaks the MM transition in the CG deck (owner: FRC 16→17). Fix:
  after the normal per-slide planning, a post-pass in `plan_payload` turns an off-slide hide into a
  keep when an MM transition joins its slide to a planned neighbour that keeps a content-identical, on-wall object.
  The kept object is mapped with its own slide's affine. If that lands it on the CG canvas, or within 24pt of
  it, it is moved just past the CG edge it was beyond on the wall. MM transitions and content identities come from
  the IWA archive during `prepare_wall_payload`, so the offline and JXA read paths behave the same and the
  payload cache is untouched. FRC: 22 of the 147 off-slide hides become keeps (slides 16, 17, 130). Gold: 0.
todos:
  - id: s0-census
    content: >-
      Keynote-free census on FRC and Gold with the content identity defined in §Partner rule (§Census).
      Scratch scripts only, not committed. DONE 2026-09-24 (this plan).
    status: completed
  - id: a-identity
    content: >-
      Stream A. `src/obed_edom/iwa_runs.py`: new `attach_magic_move(key_path, payload, *, deck=None)` →
      per-slide `magicMoveOut` + `mmKeys` (§Stream A). Tests in `tests/test_iwa_runs.py`.
    status: completed
  - id: b-planner
    content: >-
      Stream B. `src/obed_edom/map_remap.py`: `hide_reason` tag on the off-slide hide, the partner
      post-pass in `plan_payload`, `_mm_partner_transform`, `_push_past_edge`, `Plan.mm_partners`, a shared
      group-bookkeeping helper (§Stream B). Tests in `tests/test_map_remap.py`.
    status: completed
  - id: c-wiring
    content: >-
      Stream C. `src/obed_edom/remap_keynote.py`: call `attach_magic_move` in `prepare_wall_payload`,
      print one operator line, add `result["mmPartners"]`. Tests in `tests/test_remap_keynote.py`. Docs: SKILL.md
      §CG resizer + §Offline hide delete bullet, `pass1_hides_offline.plan.md` `followup-mm-leftovers` → pointer
      here (§Stream C).
    status: completed
  - id: d-golden
    content: >-
      After A+B+C are merged on the branch: Keynote-free `scripts/golden_plan.py capture` on FRC before/after and
      diff against the §Oracle. Then `update --deck Full_Report_Card_Wall.key`; Gold must be byte-identical
      (no update). Full suites.
    status: completed
  - id: e-live
    content: >-
      COORDINATOR-RUN, owner-checked. FRC remap `--slides 15-18,55-57,129-131` with production defaults. Owner plays
      MM 15→18, 55→57 and 129→131 against the wall deck (§Live). Record the result in this plan's review log.
    status: completed
---

# Off-canvas Magic Move partners

Scope (owner, 2026-09-24): only the off-slide-leftover hide (`wall_size and not is_visible`). The side-panel,
roster, chrome and coincident-duplicate hides are unchanged, and `--keep-side-panels` is still the
operator's control. Slide 122 is out of scope.

## Census (Keynote-free, 2026-09-24)

Inputs: `Full_Report_Card_Wall.key`, `Gold_Wall_Input.key`, `Base_CG_Assets.key`. Plan = `plan_payload` after
`prepare_wall_payload`, full deck (FRC: 4,658 transforms, 980 hides, 392 stat rows on 51 slides).

| | FRC | Gold |
|---|---:|---:|
| MM transitions (all `apple:magic-move-implied-motion-path`, text delivery `ByObject`, fade unmatched `true`) | 21 (out of 7, 8, 16, 19, 35, 56, 70, 84, 85, 102, 108, 109, 112, 117, 123, 126, 130, 146, 150, 151, 152) | 3 (11, 19, 22) |
| skipped slides | 0 | 0 |
| off-canvas hides | 147 | 14 |
| … on a slide touching an MM transition | 58 | 0 |
| … with a surviving content-identical partner (§Partner rule) | **22** | **0** |
| … in a repeated identity class (ambiguous) | 11 | 0 |
| … whose own-affine CG rect lands on the canvas | 0 | 0 |
| … whose own-affine CG rect is within `MM_EDGE_MARGIN` of the canvas (edge push fires, §Placement 3) | 2 | 0 |

The 22 by slide: 16 → 7 (text 'CHC Klang', 2 pasted-image PDFs, 4 rounded label plates); 17 → 5 (text 'CHC
Kuching', 2 PDFs, a pin dot, a label plate); 130 → 10 ('Suntec New 2.png', a PDF, the 'CHC' circle, 4 'UPG'
groups, 3 textless groups). By kind: shape 7, group 7, image 6, text 2. The earlier loose heuristic census
(text / fileName+aspect / w,h,colour) found 21 on 16, 17, 56 and 130. Its slide-56 matches were `pasted-image.pdf`
name collisions: slide 57 holds no object with the same data digest or text. Its slide-16 pin-dot matches
compared two different bezier paths (the 25×25 dot vs 17's 41×41 marker). All 22 are hidden only by
the off-slide rule. None is chrome, a coincident duplicate or roster content.

All 22 own-affine rects are already off the CG canvas, but two sit very close to it: 16 image 3 (-90,-396,335×391)
and image 4 (-39,-340,284×334) end 5 and 6pt above the top edge. That is because 16's affine maps the wall top to
y≈26. The other 20 are ≥33pt away. Examples: 16 'CHC Klang' → (-92,-122,119×32) at 25pt; 17 'CHC Kuching' →
(1813,1678) at 40pt; 130 Suntec → (388,2738,1303×733). Slides 16 and 17 frame at different scales (template 6,
s=0.645, vs template-layout 3, s=1.0). Slide 130 is fit-to-frame (s=1.633) and 131 is cover-fallback (s=1.0).

P2 re-ran the census with exactly the §Partner rule key: group media leaves by digest and group shape leaves by
the normalised key. P1 had used `_collect_group_content`'s fileName and raw-path leaves. Both keys give the same
22 on FRC and 0 on Gold.

## Partner rule

What Keynote matches on: Keynote documents MM as moving "objects that appear on both slides" and gives no
user control over pairing ([Apple](https://support.apple.com/guide/keynote/add-transitions-tanff5ae749e/mac),
[Apple Community](https://discussions.apple.com/thread/253234710)). In practice it matches on content:
same image data, same text, same shape. It does not use archive identity, because a duplicated slide mints
new archive ids. Our key approximates this. Live playback is the oracle (§Live).

**Identity key**, per top-level drawable, from the IWA archive (`derive_kind_index` keying, the same as
`groupChildText`):
- text (including the text record of a text/shape dual): `text:` + `_normalize_text`. Empty text gets no key.
  All 24 MM transitions in both decks deliver text `ByObject`. Word or character delivery would pair
  partial strings, which this key does not model; such transitions are left as today (hidden).
- image / movie: `image:` / `movie:` + `TSP.PackageMetadata.datas[].digest` of its `data`/`movieData`, falling back
  to the data id. Never `fileName`: FRC has dozens of distinct `pasted-image.pdf`.
- shape (not a dual): `shape:` + path-source key + preset `type` + sha1 of the path source with every `x`/`y`
  divided by its `naturalSize` (aspect-invariant, so a resized copy still matches; the rounded-rect `scalar`
  radius is kept).
- group: `group:` + the DFS leaf list in `_collect_group_content`'s walk order, with media leaves keyed by digest
  and shape leaves by the shape key above. Do not reuse the helper's output as is. Its `data_index` values are
  fileNames, and its shape leaves hash the raw path including `naturalSize`, which mirror dedup relies on. Pass a
  data-id → digest map as `data_index`, and re-key the `shape` leaves in the new code. Leave
  `_collect_group_content` unchanged.
- line: `line`. This is deliberately loose; see fail-safe below.
- anything unresolvable: no key, so it never matches and the hide stays as it is today.

**Pairs.** Slide n's transition is its transition out. `magicMoveOut` on n pairs n with n+1 only when both are
**planned**: in the payload, inside `--slides`, and not `skipped`. Keynote's behaviour across a skipped slide
is unmeasured and neither deck has one, so a skipped neighbour keeps today's hide. An out-of-range neighbour
is treated the same way, because it is skipped in the output too: `skipOutsideRange`
(`remap_keynote.js:414-425`, called at `:878`) marks every slide outside `--slides` skipped, so the
transition from a range-boundary slide into it never plays. The remap reads the whole deck whatever the range
(`acquire_wall_payload` ignores `slide_range`), so "in the payload" alone would not exclude it.

**Partner exists** for a candidate on slide a, paired with b, when b has at least one item with the same key that:
- is on the wall (`is_visible`),
- is not `duplicateOf`, and
- has no `role="hide"` transform in b's plan.

Because both slides of a pair are planned, b's survivors always come from b's real plan. A partial run
can therefore differ from a full run only at a range boundary, and only on a transition that does not play in
that output. A neighbour missing from the payload means no pair, which covers the web framing proposal's
sliced payload (`web/app.py:3062`).

**Candidates.** Only hides the off-slide rule produced *and* that no later rule would hide
(`hide_reason == "offslide"`, §Stream B).

**Ambiguity** (a key repeated on either slide: 11/22 on FRC). Every off-canvas member of the class already
passes the partner test on its own, so all of them are kept with no extra rule. The row is only reported
`ambiguous: true`. The costs are asymmetric. A wrong hide changes Keynote's candidate set
and breaks the move, which is the bug. A wrong keep adds one object parked off the canvas, which never
appears in a frame, and unmatched objects fade (`customMagicMoveFadeUnmatchedObjects` is true on all 24). Keeping
the whole class gives Keynote the same candidate set as the wall deck. The same argument makes the loose
`line` key safe.

Rejected alternative: keep every off-canvas object on any slide touching an MM transition (58 on FRC).
It is simpler, but it keeps 36 objects nothing moves to, and the owner scoped this to partners.

## Placement

The kept object on slide a gets slide a's own mapping. There is no change to the partner's transform.

1. `aff, _ = _group_for_item(item, _groups_from_recipe(framing_recipes[a]))`. If `aff is None`, keep the hide
   (reason `mm-no-affine`, reported). This never happens on FRC.
2. Mapped rect, mirroring the normal branches:
   - text: `match_character_style(item, styles, size_ratio=aff.s, prefer_slide=recipe.get("templateSlide"))` then
     `_style_text_box`. This gives `font_size`, and `font=_source_face(item) if style else None`. There is no
     overlay coupling.
   - line: start/end through `aff`. The role stays `line`.
   - image/movie/group: `aff.apply_rect`, then the same aspect snap as the main path (when there is no `child_src`).
   - No card, grid, badge, title, body, list, `x<16` clamp, backdrop `y=0`, line slot or off-dest line collapse.
     Each of those would pull the object onto the canvas or re-lay it out.
3. **Edge push** (`_push_past_edge`). Let E be the wall edges the source rect is wholly beyond, with the same
   zero-size rule as `is_visible`: top `y+h ≤ 0`, bottom `y ≥ H`, left `x+w ≤ 0`, right `x ≥ W`. If E is empty
   (a zero-size item inside the wall, which `is_visible` also rejects), keep the hide (`refused: "mm-no-edge"`).
   The rect tested is the one Keynote will draw: the source size when `size_refused` is set (as `offframe_rows`
   does), and the rotated bounding box when `rotation` is known and non-zero. If that rect, grown by
   `MM_EDGE_MARGIN` on every side, misses `[0,destW]×[0,destH]`, leave it. The margin is part of the trigger for
   the same reason it is part of the shift: a stroke or shadow 5pt away still shows. Otherwise, for each e in E
   compute the one-axis shift that
   leaves the rect `MM_EDGE_MARGIN` past that CG edge: top `dy = −(y+h) − m`, bottom `dy = destH + m − y`,
   left `dx = −(x+w) − m`, right `dx = destW + m − x`. Apply the smallest |shift|; ties go
   top, bottom, left, right. So a corner object leaves through whichever of its real edges is nearest, and the
   entry/exit direction is still a real one. Line endpoints and group `children` move by the same delta
   (children already derive from the final x/y). `MM_EDGE_MARGIN = 24.0` pt covers strokes, shadows and
   the rotated-frame overhang, and costs nothing visible in motion. On FRC the push fires twice, both through
   the top edge: 16 image 3 moves y -396 → -415 and 16 image 4 moves y -340 → -358.

**Consistency with the partner.** Each copy follows its own slide's framing, like every other object on
that slide. On FRC, 16→17 already rescales all visible content by 1.0/0.645. The kept 'CHC Klang' (25pt on
16 → 40pt on 17) and the visible 'CHC Kuching' (25pt on 16 → 40pt kept copy on 17) therefore scale exactly
like the rest of the map, and nothing morphs out of step. Forcing the partner's size onto the off-canvas copy
would make that copy the only object on its slide at another slide's scale.

**Transform shape.** Role `other` (or `line`), `src=item_rect(item)`, `opacity=None`. It must not be derived
from `_hide_item_transform`: its `opacity=0.0` would be written by `applyGeom` (`remap_keynote.js:217,241`)
and would mark the object dropped in `framing.py:376`. Role `other` also keeps it out of scoring
(`SCORED_ROLES`) and `readMapGeom`. A kept group takes the same `child_src` / `size_refused` /
`group_collapse_refused` and stat-row bookkeeping as a normal `other` group. That includes a
`child_resize` row with `s = mapped.w/src.w`, so pass 2 scales its child fonts and the z-order patch raises it
exactly like its partner on the next slide (131's 'UPG' groups already carry rows). This avoids an MM z-order
flip between the pair.

## Interactions (checked)

| Rule / consumer | Effect |
|---|---|
| coincident-duplicate hide (runs first) | unchanged; an off-canvas anchor may be kept while its dup stays hidden |
| chrome bg, roster drop | an off-canvas item they would also hide is never tagged `offslide`, so it stays hidden |
| side-panel hide | unaffected: `is_side_panel_item` is false for off-wall items |
| corner labels, title/badge, body, overlays, list packing, `_place_free_text`, card grid | bypassed; the post-pass runs after them and never touches role `list` |
| badge raises | none for kept items (they were hides when rows were built) |
| `offframe_rows` | kept items were never wall-visible, so they are not reported |
| `adjust_child_resize_indexes` | runs later in `remap_keynote` on final transforms; fewer group hides shift fewer indexes |
| JXA apply / AS body / offline geometry writer / verify | no canvas clamps or bounds checks (agent audit: `remap_keynote.js:280,125-160`; `iwa_write.py:494-514`, `652-756`); off-canvas autosize text uses the same bulk-read position path |
| pass-1 hides offline (#220) | eligibility and reconcile look at hides only (`offline_write.py:143-179`, `iwa_write.py:226-233`); fewer hides ⇒ equal or wider eligibility |
| builds follow source | identity-based, geometry-free; keeping objects can only shrink a build shortfall |
| validation bounds | wholly off-canvas objects are not flagged (`validate.py:822`) |
| z-order patch | 130's new stat rows are shared-sig groups ('UPG' ×4) → arm 3 cardinality set; '' sigs are skipped as today (`iwa_zorder.py:163`) |
| `--slides` partial run | out-of-range slides are skipped in the output (`skipOutsideRange`), so they never pair (§Pairs) |
| transform order | the planner's role sort (`map_remap.py:2940`) is placement order only, and pass 1 defers hide deletes until after geometry (`remap_keynote.js:472`), so a kept `other` left among the hides is addressed correctly |
| dashboard framing preview (`framing.planned_rects`) | plans one slide at a time, so it has no neighbour and shows kept partners as `willBeInOutput: false`. Accepted: they are off-canvas, and the preview is not the apply plan. Documented in SKILL.md |
| MM z-order validation follow-up (owner-approved, not started) | should reuse `magicMoveOut`/`mmKeys` rather than build a second MM pairing |

## Stream A — identity (`iwa_runs.py`, `tests/test_iwa_runs.py`)

`attach_magic_move(key_path, payload, *, deck=None) -> None`, read-only, in the style of `attach_slide_builds`.
It reads the transitions through `iwa_builds.deck_builds` (single source of truth) and, per payload slide
(0-based `index`), sets:
- `magicMoveOut: True` when the transition effect contains `magic-move` and `customTextDeliveryType` is absent or
  `…ByObject`. It is omitted otherwise.
- `mmKeys: {kind: {kindIndex(int): key(str)}}`, only on slides that are in a pair.

Unit tests on synthetic archives: effect gating (dissolve / MM / MM by-word); digest keying (two data ids with one
digest → one key; same `fileName` with different digests → different keys); the resized-shape match; a
different radius → a different key; an empty text gets no key; a dual shape is skipped; the group leaf
signature, where two groups whose media leaves share a fileName but not a digest key apart; `mmKeys` survives a
JSON round trip (str → int kindIndex on read).

## Stream B — planner (`map_remap.py`, `tests/test_map_remap.py`)

- `ItemTransform.hide_reason: str | None = None`, never emitted by `as_dict` (the golden hash stays stable).
  The off-slide branch sets `"offslide"` unless `is_chrome_bg(item)`, or `drop_roster` and the item is a
  pure roster carrier.
- Extract the existing post-append group bookkeeping (`map_remap.py:2892-2918`, plus the `child_src` /
  `size_refused` lines at 2804-2826) into one helper used by the main path and by `_mm_partner_transform`. Its
  null control is Gold's golden plan staying byte-identical.
- `_mm_partner_transform(item, slide, recipe, wall_size, child_resize_report) -> ItemTransform | None` and
  `_push_past_edge(rect, src, wall_w, wall_h, dest_w, dest_h) -> tuple[Rect, str | None]`.
- The post-pass at the end of `plan_payload` builds survivor key sets per slide and converts candidates **in
  place** (the same list position, so all other ordering is untouched). It appends stat rows, then stable-sorts
  `child_resize_report` by slide, which is a no-op when nothing was added. It fills
  `Plan.mm_partners: list[dict]`: `{slide, kind, kindIndex, partners: [{slide, kindIndex}], ambiguous, edge}`.
  Refusals get `refused: "mm-no-affine"` or `"mm-no-edge"`. The post-pass needs the planned slide set:
  pass `slide_range` through, or build it from `framing_recipes`, which covers exactly the planned, non-skipped
  slides.
- Tests: synthetic two/three-slide payloads carrying `magicMoveOut` / `mmKeys` directly:
  - positive: an above-wall text on slide 1 with a visible partner on slide 2 is kept, role `other`,
    `opacity is None`, `font_size` set, and ends wholly above the CG canvas; the partner spec is unchanged.
  - reverse direction: an off-wall item on slide 2 below the wall, partnered back to slide 1.
  - edge push: parametrized top/bottom/left/right with a recipe that maps the item on-canvas; a corner
    picks the minimal shift; the tie order; line endpoints and group children move with it.
  - margin trigger: a rect off-canvas by less than `MM_EDGE_MARGIN` is pushed; one off by exactly the margin
    or more is untouched. A `size_refused` group is tested at its source size.
  - text on a fit-to-frame recipe with no `templateSlide` (the slide 130 shape) plans without a KeyError.
  - direction: MM on slide 2 pairs 2↔3, not 1↔2.
  - zero-size off-slide item with a partner → hide kept, `refused: "mm-no-edge"`.
  - null controls, each still a `hide` identical to today's spec:
    - no MM transition;
    - MM but a different key;
    - partner hidden on its slide (chrome, side panel, roster);
    - partner itself off-wall;
    - skipped neighbour;
    - out-of-range neighbour (`slide_range={1}`, visible partner on unplanned slide 2);
    - neighbour absent from the payload;
    - no `mmKeys` at all (IWA unavailable);
    - an off-canvas chrome/roster item that has a partner;
    - `wall_size=None`.
  - ambiguous class → all members kept, `ambiguous` reported.
  - coincident off-canvas anchor+dup → anchor kept, dup hidden.
  - kept group → a stat row with `s`, `childSig`, `twin`; the report is slide-sorted.
  - `as_dict` of a kept spec has `w`/`h` and no `opacity` / `hide_reason`.
  - existing `test_off_screen_objects_are_hidden_not_left_alone` still passes unchanged (a single slide never
    has a partner).

## Stream C — wiring and docs (`remap_keynote.py`, `tests/test_remap_keynote.py`, docs)

- `prepare_wall_payload`: call `attach_magic_move(source, wall, deck=deck)` in its own `try`, after
  `attach_slide_builds`. On failure, print one line: "Magic Move read unavailable (…); off-canvas Magic Move
  partners stay hidden."
- After planning, if `plan.mm_partners` is non-empty, print: `Magic Move: kept N off-canvas partner(s) off-frame on
  slide(s) 16, 17, 130 (A in repeated-object classes, P pushed past an edge).` Also set
  `result["mmPartners"] = plan.mm_partners`. Do not add it to `plan_out`: that is hashed by the golden gate.
  Tests: attach is called and a failure is survivable (monkeypatched); the say line.
- Docs:
  - SKILL.md §CG resizer: a short "Off-canvas Magic Move partners" subsection (rule, planned-pair scope,
    placement, ambiguity = keep, the framing preview shows them as dropped).
  - Replace the §Offline hide delete bullet "the planner's off-slide-leftover rule also hides Magic Move
    partners" with a pointer to it.
  - `pass1_hides_offline.plan.md` `followup-mm-leftovers`: status note → this plan.

Streams A, B and C touch disjoint files and share only the `magicMoveOut`/`mmKeys` contract above, so
they can run in parallel. D and E run after them.

## Oracle (d-golden)

`scripts/golden_plan.py capture` on FRC at main and at the branch. The expected canonical diff is only:
- 22 transforms keep their list position, change `role` hide→other, drop `opacity`, and gain `w`/`h` (and
  `fontSize`/`font` on the two texts):
  - 16: text 0, image 3, 4, shape 7, 8, 9, 10
  - 17: text 0, image 1, 6, shape 0, 2
  - 130: image 3, 4, shape 1, group 0–6
- `statJobs` +7 (slide 130, groupIndex 1–7, `s≈1.633`); `statSlides` + {130}.
- `asGeom` may differ on 16, 17 and 130 only.
- `totals.transforms` unchanged (4,658).
- No kept rect, grown by `MM_EDGE_MARGIN`, intersects [0,1920]×[0,1080]. Test the rect, not the x/y corner.
- Exactly two edge pushes, both `top`: 16 image 3 (y -415) and 16 image 4 (y -358). The other 20 are at their
  own-affine positions.

Any other difference is a regression. Gold must reproduce its committed `planSha256` (0 partners). Then run
`update --deck Full_Report_Card_Wall.key` and commit the new fixture with the diff summary in the PR. Suites:
`uv run pytest tests/ -n auto --dist loadfile`, `cd dashboard && npm run test:ui`, `npm run test:maps` (no
dashboard code changes, but they are run per the no-CI rule).

## Live (e-live, coordinator runs Keynote; owner judges)

- FRC remap `--slides 15-18,55-57,129-131`, production defaults (offline read/write/hides/z-order on).
- The run must print the Magic Move line with 22 partners, show 0 offline-hide refusals, and pass geometry verify.
- Static previews of 16, 17 and 130 show no sliver of a kept object at any edge.
- Owner playback vs the wall deck:
  - 16→17: 'CHC Klang' + plate enter from the top; 'CHC Kuching' + plate + dot leave through the bottom; the map
    PDFs move rather than fade.
  - 129→131: Suntec, the 'CHC' circle and the 'UPG' groups rise from below.
  - 55→57: a null control. The 56→57 leftovers stay hidden, and the move should look the same as today.

## Open questions

None change the design. For owner veto only:
- an out-of-range or skipped neighbour keeps today's hide (§Pairs; P2 reversed P1's out-of-range keep because
  that slide is skipped in the output);
- `MM_EDGE_MARGIN` is 24pt, and it also sets when the push fires: within 24pt of the canvas counts as landing
  on it, which moves two FRC PDFs about 19pt further up.

## Review log

- P1 (2026-09-24, Opus high, planner): first pass. Census re-measured with the content identity: 22 FRC / 0 Gold
  conversions and 0 edge pushes on FRC. The earlier loose heuristic count (21, including slide 56) had
  false positives. Downstream audit found no canvas clamp anywhere. The one trap found is
  `_hide_item_transform`'s `opacity=0.0`, which must not carry over to kept items.
- P2 (2026-09-24, Opus high critic): no blockers. The census reproduces with the exact key (22 / 0).
  - MAJOR, folded in: an out-of-range neighbour is skipped in the output (`skipOutsideRange`), so P1's
    "something to move to" keep was wrong. Pairs are now between planned slides only.
  - MINOR, folded in:
    - the push trigger now includes the margin: 16 image 3/4 sat 5–6pt off the canvas, so FRC has 2 pushes;
    - the effective rect for the push (source size when `size_refused`, rotated bounding box);
    - a zero-size candidate is refused (`mm-no-edge`);
    - `recipe.get("templateSlide")` (fit-to-frame recipes);
    - the group key's digest and normalised-shape leaves are spelled out, because `_collect_group_content`
      emits fileNames;
    - ambiguity is a report flag, not a rule;
    - the oracle tests the rect, not the x/y corner;
    - the framing-preview divergence is documented;
    - the MM z-order follow-up should reuse `mmKeys`.
  - Verified correct, no change needed:
    - opacity is only written for non-hide specs, and hides are deleted after geometry;
    - no clamp in the AS body, the offline writer or verify; `validate` ignores wholly off-canvas objects;
    - `offframe_rows`, and `adjust_child_resize_indexes` running after `plan_payload`;
    - z-order: 130 'UPG'×4 resolves by arm 3, and the '' sigs are skipped;
    - builds are identity-based, and offline-hide eligibility is hides-only;
    - the transition field names;
    - `deck_builds` takes 0.05s, so the second read is cheap.
- Implementation (2026-09-24, Opus medium ×3, streams A/B/C): FRC plan diff equals §Oracle exactly (22 hide→other,
  2 top pushes on 16, statJobs +7 on 130, asGeom only 16/17/130); Gold unchanged. FRC golden re-baselined
  (35002fee…); `test_offline_write` aspect pins re-measured (+13 candidates: 12 asserted, 1 masked); propose-vs-apply
  parity pins the 22 apply-only rows.
- C1 (Codex GPT-5.6 Sol H): BLOCK, 1 MAJOR (rotated/line push extent recentred the rotated AABB) + 3 MINOR
  (non-transactional MM read; 3-decimal shape key; loose parity pin). Fixed #1, #2, #4; #3 refuted by measurement
  (finer precision splits save-noise twins and re-hides real partners). C2: all CLOSED; 1 new MINOR (fixed-frame
  text writer has no rotated-anchor correction) → rotated fixed-frame text misses to the live fallback
  (`text-rotated`; 0 rotated text on FRC/Gold). C3: PASS.
- LIVE (2026-09-24, owner playback, `be358922`): `--slides 15-18,55-57,129-131` kept 22, pushed 2, applied 277,
  missed 0, offline hides 70/0 refused — MM OK. `--slides 84-86` (Thailand → SEA → China; no partners, 9
  side-panel hides): OK. Thailand fades 100→0 and China 0→100 as on the wall; the SEA map lands within <1px. The wall's MM
  reads slightly more seamless, likely the canvas-size difference. Suites: 7039 passed / 88 skipped / 1 xfailed,
  test:ui 246, test:maps 542 + 2.
