# DSK "template style" milestone — badge on the rose pill in the template's style, verse text in the template's run styles

Status: planned (read-only design pass, 2026-09-15, worktree `dsk-gen`, branch `feat/dsk-gen`).
No Keynote was opened. Every number below is reproduced by a script in the planner
scratchpad `plan-style/`: `s0_dump.py` (per-slide drawable + run dump), `s1_roles.py`
(compact role table), `s2_badges.py` (badge-candidate survey), `s3_layouts.py` (layout-slide
slot styles), `s4_caps_width.py` (all-caps vs title-case shaped width), `p1_patch_styles.py`
(the offline stylesheet patch, dry-run already executed).

Decks read (read-only): TEMPLATE `~/Desktop/Default Templates/2026_Lower-Thirds (ENG).key`,
GOLD `~/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key` (43 slides),
SOURCE `~/Desktop/Diff-Checker/Sermon_PK (GW).key` (63 slides),
OUTPUT `~/Desktop/dsk-d4-work/out-r13/Sermon_PK_DSK.refused.key` (25 ordinals).

---

## §0 OWNER SUMMARY

1. **Nothing needs re-typing, re-casing or re-fonting.** The badge string is byte-identical
   in source and gold (`Genesis 11`, `1 Samuel 10`, `James 5 (AMP)`). The "GENESIS 11" the
   owner sees is the character property `capitalization: kAllCaps`, nothing else.
2. **There are exactly three style deltas** between today's output and gold: badge colour
   (cyan → white), badge caps (`kAllCaps` → `kNoCaps`), verse-number colour (cyan → yellow).
   Body font/size, emphasis (ArgentCF-Bold ≤50 pt yellow), small-caps `Lord`, superscripts
   and point headings **already match gold**.
3. **All three live in one file**, `Index/DocumentStylesheet.iwa`, on a handful of style
   archives. A surgical patch of that one member does the whole job — the same class of
   write as the proven media-stroke patch. **Dry-run already done** on the r13 deck: 6
   archives edited, exactly 1 ZIP member changed, resulting run table equals gold.
4. **AppleScript cannot do it.** `capitalization` is in the documented sdef gap, so the
   live pass can never clear `kAllCaps`. This must be an offline post-pass, mirroring
   `_write_pill_pass` (L4), not a new live script.
5. **It also fixes the pill.** The L4 width law was fitted on gold's *title-case* badges;
   with `kAllCaps` still set, the rendered badge is 10–63 pt wider than the pill drawn for
   it (`s4_caps_width.py`). Fixing caps makes the landed pill law correct, not just prettier.
6. **One real conflict:** the TEMPLATE's own sample runs are amber `[254,180,0]` with
   `AzoSans-Regular` bold emphasis; GOLD is yellow `[255,251,0]` with `ArgentCF-Bold` 50 pt.
   "Match the template" read literally contradicts the gold example the owner cited (Q1).
7. Cost: 3 small sonnet pieces (~250, ~170, ~120 lines) plus one live probe.

---

## §1 Measurements

### 1.1 Role → style, the three decks side by side (`s1_roles.py`, `s3_layouts.py`)

| role | SOURCE GW (wall) | TEMPLATE layout sample | GOLD DSK | OUTPUT r13 |
|---|---|---|---|---|
| verse badge | `AzoSans-Bold` 65, cyan `[0,253,255]`, **kAllCaps** | `AzoSans-Bold` 40, **white**, **kNoCaps** | `AzoSans-Bold` 40, **white**, **kNoCaps** | `AzoSans-Bold` 40, **cyan**, **kAllCaps** |
| verse number | `AzoSans-Regular` 70, cyan, `kSuperscript` | `AzoSans-Regular` 45, **amber `[254,180,0]`**, `kSuperscript` | `AzoSans-Regular` 45, **yellow `[255,251,0]`**, `kSuperscript` | `AzoSans-Regular` 45, **cyan**, `kSuperscript` |
| body | `AzoSans-Regular` 70 white | `AzoSans-Regular` 45 white | `AzoSans-Regular` 45 white | `AzoSans-Regular` 45 white ✔ |
| emphasis | `ArgentCF-Bold` 85 yellow | **`AzoSans-Regular` bold, amber** | `ArgentCF-Bold` 50 yellow | `ArgentCF-Bold` 50 yellow ✔ |
| point heading | `ArgentCF-Bold` 190–220 yellow | (none in slot sample) | `ArgentCF-Bold` 60 yellow | `ArgentCF-Bold` 60/80 yellow (size = L5) |
| point-column ref badge | as verse badge | — | `AzoSans-Bold` 40, **cyan**, kNoCaps (gold 29/30; 35 pt on 34) | `AzoSans-Bold` 40/52.66, cyan, kAllCaps |

Template extra palette colours in the slot sample (the owner's "colour 1/2/3"):
amber `[254,180,0]` (`Highlight`, `Verse Number`), green `[151,231,136]`, teal `[76,231,221]`.
The bold face in the template's sample emphasis is **`AzoSans-Regular` + `bold=True`**, not a
serif — only GOLD uses `ArgentCF-Bold`.

Slot paragraph metrics (identical in template and gold, `s3_layouts.py`):
verse box `align=TATvalue0` (left), `vAlign=kFrameAlignTop`, `lineSpacing 0.8`, padding 4.0;
badge box `align=TATvalue0`, `vAlign=kFrameAlignMiddle`, `lineSpacing 0.9`, padding 4.0.
Output boxes carry padding 1.0 and, on some slides, `TATvalue2` (centre) inherited from the
wall — see §2.5, out of scope for this milestone.

### 1.2 Badge text is identical in source and gold — only `capitalization` differs

`s2_badges.py` over both decks, grouped by (text, capitalization, colour, size):

| badge string | GW (source) | GOLD |
|---|---|---|
| `Genesis 1` / `Genesis 11` / `Matthew 18` / `John 17` / `Acts 4` / `Exodus 13` / `Luke 5` / `2 Chronicles 5` / `2 Corinthians 2` / `1 Samuel 10` / `2 Kings 3` | kAllCaps, cyan, 65 pt | kNoCaps, white, 40 pt (cyan for the point-column `2 Kings 3`) |
| `James 5 (AMP)` | kAllCaps, cyan, 65 pt | `James 5 (MSG)` kNoCaps, **cyan**, 40 pt (point column) |

So **the version suffix already travels verbatim** from the source string; there is no
NIV-suffix synthesis, no book-number expansion, no roman numerals, no re-casing.
Exceptions found: GOLD `Samuel 10` (the deck's own injected mistake — GW says
`1 Samuel 10`), and GOLD `James 5 (MSG)` vs GW `James 5 (AMP)` (a second injected
translation mistake). Neither is a normalisation rule. The template's sample badge string
is `John 1 (NIV) • Jesus loves you to the very end`, i.e. the template *demonstrates* a
version-plus-tagline format that gold never uses (Q3).

### 1.3 Where the styles live (`p1_patch_styles.py` planning pass, r13 deck)

Every character and paragraph style archive in the output deck lives in
**`Index/DocumentStylesheet.iwa`** — including the anonymous per-size derivatives the
existing size writes create. Chains measured:

| box | leading style chain |
|---|---|
| verse badge `17259644` | para `17646732` (anon: `AzoSans-Bold` 40, **cyan**, **kAllCaps**) → `2651100` `Title Small`; **no `tableCharStyle` entries at all** |
| verse body `17259615` | per-run anon char styles (`fontSize` only) → named parents `SuperScript` `2684601` (cyan 70), `None` `2651125`, `Yellow Bold` `2651127` (`ArgentCF-Bold` yellow) |
| point-column badge `17432278` | para `17651798` (anon: `AzoSans-Bold` 52.66, cyan, kAllCaps) → `2651100` |

Because the badge box carries **no** character-style entries, its colour and caps come
purely from its own anonymous paragraph style — which is why the fix is a paragraph-style
patch, not a run patch.

Named-style archives, compared across decks:

| style | TEMPLATE | GOLD | GW / output |
|---|---|---|---|
| `Verse Number` `2040813` | amber `(0.998,0.706,0)` | **yellow `(0.999,0.986,0)`** | absent (GW uses `SuperScript` `2684601`, cyan) |
| `Highlight` `2040743` | amber, `AzoSans-Regular`, bold | **yellow, `ArgentCF-Bold` 50** | absent (GW uses `Yellow Bold` `2651127`, already yellow `ArgentCF-Bold`) |

GOLD reuses the template's style **ids** with **edited values** — i.e. the gold author
deliberately overrode the template's amber/sans to yellow/serif. That is the evidence
behind the Q1 recommendation.

### 1.4 The patch, dry-run (`p1_patch_styles.py`, already executed)

```
edit 17643269 fontColor->white capitalization->kNoCaps   verse badge para (size 40.0)
edit 17646732 fontColor->white capitalization->kNoCaps   verse badge para (size 40.0)
edit 2663956  fontColor->white capitalization->kNoCaps   verse badge para (size 60.0)
edit 14602709 fontColor->white capitalization->kNoCaps   badge para (size 64.0)   <- point column
edit 17651798 fontColor->white capitalization->kNoCaps   badge para (size 52.66)  <- point column
edit 2684601  fontColor->yellow                          SuperScript (verse number)
applied: 6
```

Verification of the output: ZIP member list identical (161 members), **exactly one member
changed** (`Index/DocumentStylesheet.iwa`), and `s1_roles.py` on the patched deck reports
badge `AzoSans-Bold 40 white 'Genesis 11'`, verse number `yellow kSuperscript`, body and
`Yellow Bold` emphasis untouched. The naive property predicate also caught the two
point-column badges; production must target by box id instead (§2.2).

### 1.5 Caps → pill width (`s4_caps_width.py`, `AzoSans-Bold` 40 pt, L4 pad 54.85)

| badge | title-case width | ALL-CAPS width | delta | pill (title+pad) |
|---|---|---|---|---|
| `Luke 5` | 146.52 | 157.72 | +11.20 | 201.37 |
| `Genesis 11` | 223.80 | 238.40 | +14.60 | 278.65 |
| `John 17` | 165.52 | 188.04 | +22.52 | 220.37 |
| `1 Samuel 10` | 248.20 | 271.60 | +23.40 | 303.05 |
| `Matthew 18` | 247.12 | 288.68 | +41.56 | 301.97 (gold pill 301.829) |
| `2 Chronicles 5` | 289.40 | 343.84 | +54.44 | 344.25 |
| `2 Corinthians 2` | 309.16 | 371.92 | +62.76 | 364.01 |

`iwa_text_shape.shaped_width` has **no capitalization input** — it always measures the
stored string, i.e. title case. So the landed L4 law is already the title-case law, fitted
against gold's title-case badges (`Matthew 18` reproduces gold's 301.829 pill to 0.14 pt).
Leaving `kAllCaps` in place means the drawn pill under-runs the rendered badge by the
delta column. **No estimator recalibration is needed**: the font family never changes
(AzoSans stays AzoSans, ArgentCF stays ArgentCF), only colour and caps, and
`wrapped_height_runs` reads neither.

---

## §2 Design and decision

### 2.1 Mechanism comparison

| | what it can write | verdict |
|---|---|---|
| **A — restyle in place, live** (`set color/font/size of characters i thru j of object text`) | colour ✔, face-by-name ✔ (the precedent exists: `keynote.py:337-354` already does exactly this per run, and `dsk_assemble.py:2878/3038/3334` do per-range `size`), **capitalization ✘** | **rejected as the whole answer**: cannot clear `kAllCaps`, which is the visible defect. Also writes on the box the split engine just sized — more ordering risk for no gain. |
| **B — pour into the layout placeholder** | inherits the template's kNoCaps/white/amber for free | **rejected**: `_layout_set_with_cleanup_lines` deletes the materialized `Text`/`Text-1` instances by design; keeping them means re-writing text and losing superscripts (every source verse box has one: 42 `kSuperscript` runs in GW) and character-level builds (banked r12b evidence: a run-size write already destroyed slide 17's `apple:dissolve character` build). |
| **C — A for the body, badge poured/rewritten** | badge only | **rejected**: the badge needs no text change at all (§1.2); rewriting it would be a lossy no-op. |
| **D — surgical `DocumentStylesheet.iwa` style patch** (offline post-pass) | colour ✔, capitalization ✔, superscript preserved (untouched), builds untouched, text untouched | **RECOMMENDED**. One member, ~6 archives, dry-run green (§1.4). Same write class as the proven `patch_media_stroke` / `patch_stroke_widths` DocumentStylesheet float patch. |

### 2.2 The recommended design

A new module `src/obed_edom/dsk_style.py` exposing `write_styles(key_path, *, specs, out_path)`,
modelled line-for-line on `dsk_pill.write_pills`, plus a `_write_style_pass` in
`dsk_assemble.py` that runs **immediately before** `_write_pill_pass`.

Targeting is **by box id, never by property predicate** (the dry-run showed a predicate
over-reaches onto the point column):

* the verse badge box per ordinal is already resolved — `plan.slot_badge_ids[number]`,
  the same map `_pill_specs` consumes;
* the verse body box per ordinal is the slot's long-text box, the same one
  `_run_size_ranges` sized;
* from each box, resolve its leading `tableParaStyle` entry (badge) and its
  `SuperScript`-parented run styles (body) through `offline_inspect._leading_sid`.

Two edits per ordinal:

1. badge paragraph style → `fontColor` white `(1,1,1)`, `capitalization` `kNoCaps`;
2. the verse-number character style ancestor → `fontColor` gold yellow
   `(0.99942404, 0.9855537, 0.0)` — the exact float triple already present in the deck on
   `Yellow Bold`, so the two yellows match bit-for-bit.

**Sharing guard.** One anonymous paragraph style can serve several boxes (`17643269` serves
many verse badges — which is fine and desirable) but could in principle be shared between a
verse badge and a point-column badge. The pass must compute, for every style it intends to
patch, the complete set of boxes that resolve to it, and **refuse** (`OfflineWriteRefused`,
lifted to `AssemblyRefusal` by the caller, exactly like the pill pass) when that set is not
a subset of the verse badges. Cloning the archive is the follow-up if the refusal ever
fires; do not build it speculatively.

Ordering: **width → run sizes → deletes → position** (live, unchanged) → offline style pass
→ offline pill pass → verify. The style pass reads and writes only `DocumentStylesheet.iwa`
and the pill pass only slide members and `Data/`, so they cannot collide; the style pass
must run first so any later read-back verification sees the final styles.

### 2.3 What is explicitly NOT in this milestone

* point-heading sizes (60 pt flat) and the point-column badge size — L5 owns those;
* badge slot x (still 45/714/778/1312 on r13 slides) — L2/L3 slot wiring;
* paragraph alignment (`TATvalue2` inherited from the wall on some output boxes where the
  slot is `TATvalue0`) and box padding (1.0 vs the slot's 4.0). Both are real template
  deltas but neither is in the owner rule, and alignment has **no** measured write path
  (no `alignment` write exists anywhere in `src/`, and it is not in the sdef gap list
  either way) — worth its own measured round rather than a guess here.

### 2.4 Owner questions

**Q1 — template amber/sans, or gold yellow/serif?** The owner's rule says "match the
TEMPLATE"; the owner's gold example says yellow verse numbers and yellow bold *serif*
emphasis. The template's own slot sample is amber `[254,180,0]` with `AzoSans-Regular` bold
emphasis (§1.1), and gold reuses the template's very style archives with those values
**edited to yellow/`ArgentCF-Bold`** (§1.3).
*Recommended default:* **follow GOLD** — yellow `[255,251,0]`, emphasis left as the source's
`ArgentCF-Bold` (already correct, so zero work). The template's sample runs read as a
palette demo, not a spec, and gold is the finished human DSK deck the owner pointed at.

**Q2 — the point+verse column ref badge.** Gold 29/30/34 put the verse reference in the
right column with **no pill**, in **cyan**, at 40 pt (35 pt on 34). Today's output is cyan
too, so doing nothing already matches gold.
*Recommended default:* **leave it cyan and uppercase-free only if it is also re-cased** —
concretely, patch its `capitalization` to `kNoCaps` (gold is title case there too) but
**keep the colour cyan**. Confirm, since the naive patch in §1.4 whitened it.

**Q3 — version suffix and the template's tagline.** Source strings already carry
`(AMP)`/`(MSG)` and omit the suffix for NIV; the template's sample badge is
`John 1 (NIV) • Jesus loves you to the very end`.
*Recommended default:* **pass the source badge string through verbatim** — no synthesised
`(NIV)`, no `•` tagline. The owner's "other versions should have the version shown" is
already satisfied by the source.

---

## §3 Pieces (one sonnet each, in order)

**S1 — `dsk_style.write_styles` (offline, no wiring).** New
`src/obed_edom/dsk_style.py`: a `StyleSpec` per ordinal (`badge_box_id`,
`body_box_id`, `badge_color`, `badge_caps`, `verse_number_color`), resolution of the
target style archives through `offline_inspect._leading_sid` / the `super.parent` chain,
the sharing guard of §2.2, and the single-member patch/re-encode/verbatim-copy write
(lift the member loop and `_preserve_raw_name` discipline from `iwa_write`, do not
re-implement the ZIP rules). Read-back verification inside the function: every targeted
box resolves to the new colour/caps, every non-targeted box is unchanged, exactly one
member differs. Tests (`tests/test_dsk_style.py`): style-chain resolution on a gold
fixture; the r13-shaped case pinning the 6→4 edit list of §1.4 (verse badges + SuperScript
only, point column excluded); a sharing-guard refusal; a member-isolation assertion.
A/B expectation: `s1_roles.py` on the output equals §1.1's GOLD column. ~250 lines.

**S2 — `_write_style_pass` wiring in `dsk_assemble.py`.** Mirror `_write_pill_pass`
exactly: a `_style_specs(...)` builder off `plan.slot_badge_ids` and the slot long-text
ids (per-part, like `_pill_specs`), the `OfflineWriteRefused` → `AssemblyRefusal` lift,
the `-style` staging suffix, the log line, and a `--no-styles` flag defaulting **off**
(styles on). Insert before the pill pass. Tests: extend `tests/test_dsk_assemble.py` with
the spec-builder mapping (including a split part getting its own part's badge id) and the
flag. ~170 lines.

**S3 — acceptance pinning.** Pin the exact colour triples and caps enums as module
constants with a test naming their provenance (gold archive `2040813`/`2040743` values,
`Yellow Bold` `2651127` float triple), plus the §1.5 pill-width consequence as a regression
test (`shaped_width` title-case vs upper, asserting the law is the title-case one). Add the
§5 acceptance rows to the staged verifier if one already covers run styles; otherwise leave
them as the live checklist. ~120 lines.

---

## §4 Live probes (ready to run; scratch copies only)

Run order: `p1` (offline, already green on r13) → copy the patched deck to
`~/Desktop/style-probe/` → `p2` → re-read with `s1_roles.py` → `p3` (only if Q1/Q2 push us
back towards mechanism A).

* `plan-style/p1_patch_styles.py <deck.key> <out.key>` — the offline patch itself.
  Already executed against the r13 deck (§1.4). **Status: GREEN offline.**
* `plan-style/p2_open_save.applescript "<~/Desktop/…/patched.key>"` — opens the patched
  deck by bundle id, saves, closes. **The one thing still unproven:** that Keynote 15.3.1
  accepts a `DocumentStylesheet.iwa` charProperties patch and keeps it across a save. The
  media-stroke precedent (same member, float field, probed 2026-09-02) says yes; a
  `capitalization` enum write is the new part. Re-run `s1_roles.py` afterwards and diff
  against the pre-save dump — expect byte-identical run tables and no other member damaged.
* `plan-style/p3_range_writes.applescript "<scratch.key>"` — the fallback probe:
  per-range `color`/`font`/`size` writes on a mixed-run box carrying a superscript run
  (do the superscript and the other faces survive? does `font … to "AzoSans-Bold"` resolve
  the bold face by name?), and an explicit attempt to write `capitalization` — expected to
  **fail**, which is the evidence that mechanism D is required rather than merely preferred.

Operator rules from the skill apply: work on a copy, never under `/private/tmp`, no other
Keynote document open, generous `with timeout`, never force-quit while the owner's deck is open.

---

## §5 Acceptance rows (live run, r13 keep list)

| # | check | expected |
|---|---|---|
| 1 | verse badge text | byte-identical to the source string, incl. `(AMP)`/`(MSG)`; no re-casing |
| 2 | verse badge face | `AzoSans-Bold`, 40 pt (slot `badge_pt`) |
| 3 | verse badge colour | white `[255,255,255]` |
| 4 | verse badge caps | `kNoCaps` — renders `Genesis 11`, not `GENESIS 11` |
| 5 | verse number | `AzoSans-Regular`, yellow `[255,251,0]`, `kSuperscript` **still set** |
| 6 | verse body | `AzoSans-Regular`, white, 45 pt (or the split/shrink size), unchanged |
| 7 | emphasis | `ArgentCF-Bold`, yellow `[255,251,0]`, ≤ 50 pt, unchanged |
| 8 | small caps | `Lord` keeps `kSmallCaps` on every slide that had it |
| 9 | per-run check on 3 slides | ordinals 4 (`Genesis 11`), 21 (`Luke 5`), 17 (`James 5 (AMP)`) match rows 1–8 |
| 10 | pill | present on every verse ordinal; mask width = `shaped_width(title-case badge) + 54.85`; right edge pinned at 1832.5315 |
| 11 | point-column ref badge | still cyan `[0,253,255]`, `kNoCaps` (pending Q2) |
| 12 | isolation | exactly one ZIP member (`Index/DocumentStylesheet.iwa`) changed by the style pass; member list identical |
| 13 | builds | build count and reveal order unchanged vs the pre-style staging deck (`_verify_builds` already gates this) |

## Probe results (2026-09-15 11:35, orchestrator)
- p2 round 1 (fontColor-only patch, as planned): FAILED — after open+save every badge/verse-number run reverted to cyan. Post-mortem: each target archive carries the colour TWICE in `charProperties` (`fontColor` and `tsdFill.color`); Keynote treats `tsdFill.color` as authoritative and resyncs `fontColor` from it on save; anonymous paragraph-style variations are regenerated with new ids on save (17646732 → 17654928); `capitalization: kNoCaps` DID survive (Keynote dropped the now-redundant override because the parent "Title Small" is kNoCaps). The reader (`resolve_style`) only reads `fontColor`, which is why the dry run looked green.
- p2 round 2 (`p1_patch_styles.py` also writes `tsdFill.color` = the new colour when `tsdFill` is present): PASSED — run tables byte-identical before and after the save (`~/Desktop/style-probe/roles.diff` empty): badges white AzoSans-Bold 40 title-case, verse numbers [255,251,0] superscript. Mechanism D stands with the dual-field rule. Reader must learn `tsdFill.color` (verification must read the authoritative field).
- p3 (per-range live writes) not run: no longer needed.
- Owner defaults adopted pending answers: Q1 follow GOLD (yellow ArgentCF-Bold emphasis — no emphasis work); Q2 point-column badge keeps cyan, caps cleared; Q3 badge string verbatim.
