# Pill census — Gold wall deck (measured, 2026-09-19)

Payload: `/Users/anyhowclick/Desktop/work/obed-edom/.cache/inspect/dc036aea828742c1a1faa773efb72d497fcfe630f9d32c05919c1abf9678f1c6.v5.k15.3.1.json`
(`path` = `…/Convert wall to 16x9 CGs/Gold_Wall_Input.key`, 26 slides, 7680x1080).
Scripts (reproducible, run with `uv run python <script>` from the worktree):
`census.py` (pairing v1 + dots), `census2.py` (failure autopsy + small-shape census),
`census3.py` (final pairing rule + dot association), `collide.py` (collision sizing).

## 0. What the payload does and does NOT carry

| Field | Reality |
|---|---|
| `index` | **NOT z-order.** `derive_kind_index` (src/obed_edom/iwa_kindindex.py:98-130) walks `drawablesZOrder` but buckets records by `KIND_ORDER`, then `offline_inspect.py:302` enumerates the concatenation. Texts get 0..n, then images, then shapes. Relative z *within one kind* is z-order; **cross-kind z (text vs shape) is unrecoverable from the payload.** |
| `kindIndex` | z-order rank within the kind. Usable for tie-breaks between two shapes. |
| `color` | **Not the fill.** Every pill on slide 13 reports `[65535,65535,65535]` (white = its text colour); every dot reports `[0,0,0]` or `[0,65021,65535]`. There is no fill-colour field. **Colour cannot disambiguate a pill from anything.** `item_rgb` reads this same field. |
| `groupChildren` | Absent from the cached payload (attached at runtime by `iwa_runs._attach_group_children`). **No label/pill pair on slides 5/8/13/17/18 is inside a group** — all 45 labels and all their pills are top-level `text`/`shape` records. Slides 22-26 carry groups, but those are roster/stat groups with no Amplitude-Bold map labels. |

**Consequence for the design: "pill sits below the label in z-order" is not testable
offline.** The pairing rule must be geometric only. (It can be *asserted* later from
`drawablesZOrder` in the offline writer, but the planner does not see it.)

### Existing dot/pin notion
`is_pin_item` (map_remap.py:336) treats ANY shape/group ≤ `PIN_KIND_MAX` whose centre is
inside/near the map as a "pin". On slide 13 that swallows the 29 dots **and nothing else**
small — but it also has no notion of "which dot belongs to which label". `counts["pin"]`
(map_remap.py:3890) is a report-only tally. So a dot notion exists; a *dot↔label* notion
does not.

## 1. Label / pill inventory

CHC-prefixed text by slide:

| slide | map | labels | font | label h | pills found | dots (small square shapes) |
|---|---|---|---|---|---|---|
| 2 | — | 1 | 80 Amplitude-**Medium** | 186 | n/a | 0 |
| 5 | Malaysia | 2 | 40 Amplitude-Bold | 52 | 2 | 1 (25x25, rot 0) |
| 8 | Malaysia | 2 | 40 Amplitude-Bold | 52 | 2 | 1 (25x25) |
| 13 | Myanmar | 19 + 1 | 15 Amplitude-Bold (+1 × 80 Medium, 2 lines) | 22 | 19 (+1 plate) | 29 (17x17, rot 242) |
| 17 | China | 6 | 35 Amplitude-Bold | 46 | 6 | 6 (25x25) |
| 18 | China | 15 | 35 Amplitude-Bold | 46 | 15 | 20 (15×25x25 + 5×17x17) |
| 20/21/22 | roster | 12/182/180 | 42/45/30 Amplitude-**Regular** | — | none | 138 × 11x11 rot 242 (map micro-dots, no pills) |

**Face is a clean discriminator: every real map label is `Amplitude-Bold` and single-line.**
Roster text on 20-22 is `Amplitude-Regular`; slide 13's "CHC Yangon\nBible School" is
`Amplitude-Medium` and 2 lines — both fall out for free.

## 2. Pairing rule (measured)

First attempt (strict rect containment, tol 3px): **44/45 unique, 1 miss** —
slide 18 `CHC Jiang Shou` label 238x46 sits in a pill 253x**41**, i.e. the pill is
*shorter* than the text box. Vertical containment is the wrong test.

Final rule (`census3.py::pair_rule`), candidate `P` for label `L`:

1. `P.x <= L.x + 4` and `P.x + P.w >= L.x + L.w - 4`  (x-containment, 4px tol)
2. `P.y - 0.25*L.h <= L.centre_y <= P.y + P.h + 0.25*L.h`  (label centre in the pill band)
3. `0.6*L.h <= P.h <= 3.0*L.h`
4. `P` is not itself a dot (§3)

| slide | labels tested | 1 candidate | 0 | >1 |
|---|---|---|---|---|
| 5 | 2 | 2 | 0 | 0 |
| 8 | 2 | 2 | 0 | 0 |
| 13 | 20 | 20 | 0 | 0 |
| 17 | 6 | 6 | 0 | 0 |
| 18 | 15 | 15 | 0 | 0 |
| **total** | **45** | **45 (100 %)** | 0 | 0 |

**Uniqueness holds even on the crowded slide 13.** No colour, no z-order needed.

Padding (`pill − label`, px: left, right, top, bottom):

| slide | left | right | top | bottom |
|---|---|---|---|---|
| 5 | 3–7 | 3–7 | 3 | 3 |
| 13 (15pt) | 2–10 | 1–10 | −2…+1 | −1…+1 |
| 17 (35pt) | 2–6 | 3–7 | −2…+1 | −3…+2 |
| 18 (35pt) | 0–10 | 0–10 | −3…0 | −3…+2 |

Horizontal padding is real (2–10px, ~3–10 % of label width); **vertical padding is ~0 and
often negative** — the text box is as tall as or taller than the pill. Any formula must
carry the measured (possibly negative) pad through, not assume ≥ 0.

Template base slides for reference (from the brief): text 243x52@40 in pill 249x58;
text 133x34@25 in pill 138x36; text 192x46@35 in pill 212x46.

## 3. Dot association (measured)

Dot definition from real data: `kind == "shape"`, `w,h <= 1.6 * label_h`, `|w−h| <= 2`.
Sizes are per-slide uniform: 25x25 rot 0 (slides 5/8/17/18-China), 17x17 rot 242
(slide 13 and 5 stragglers on 18), 11x11 rot 242 (roster slides). Colour is useless (§0).

Distance = dot centre → **pill rect** (not centre-to-centre; pills are wide and
centre-distance mis-ranks a dot hugging a long pill's end).

| slide | pairs | dot distances (px) | no dot within radius | dots claimed twice |
|---|---|---|---|---|
| 5 | 2 | 33.5, 36.5 | 0 | 0 |
| 8 | 2 | 33.5, 36.5 | 0 | 0 |
| 13 | 20 | 6.4 … 23.5 (median 15.0) | 1 (the Bible-School plate) | 1 |
| 17 | 6 | 21.3 … 120.2 | 0 | 1 |
| 18 | 15 | 16.5 … 123.2 | 0 | 1 |

Proposed radius `R = 2.5 * pill_h + 30` (slide 13 → 85px, actual max 23.5; slides 17/18 →
~145px, actual max 123.2). Comfortable margin at both scales, and it correctly rejects the
2182px-away case. Tie-break when two pairs claim one dot: nearest wins, then lower
`kindIndex`. 3 of 43 dots are double-claimed — harmless, the dot is only read, never moved.

Side of the pill the dot sits on (H ∈ L/C/R by the pill's x-range, V ∈ U/M/D):

| slide | LU | LM | LD | CU | CD | RU | RM | RD | none |
|---|---|---|---|---|---|---|---|---|---|
| 13 | 1 | 6 | 1 | 0 | 1 | 3 | 4 | 3 | 1 |
| 17 | 3 | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 0 |
| 18 | 3 | 3 | 0 | 2 | 6 | 0 | 1 | 0 | 0 |

Horizontal: 18 L, 10 C, 13 R — genuinely mixed, so a horizontal anchor is decidable
for 31/41 and must fall back to centre for the 10 `C` cases.
Vertical: 14 M (dot inside the pill's y-band) — vertical anchoring is **undecidable for a
third of the population**, which is the empirical argument for always centring vertically.

## 4. Collision sizing — slide 13, r = 25/15 = 1.6667 (`collide.py`)

Measured with s = 1.0 (owner's measurement: slide-13 pills are x1.00), so wall-space
overlaps map 1:1 to dst overlaps. 19 paired pills.

### Pills

| mode | pill–pill overlapping pairs | pill–dot overlaps | x-extent |
|---|---|---|---|
| today (pill not grown) | 0 | 2 | 460px |
| **centre growth** | **16** | **40** | 537px |
| **growth away from dot** | **19** | **48** | 491px |

### Labels (the thing the viewer actually reads) — the fair baseline

| mode | label–label overlapping pairs | labels escaping their pill |
|---|---|---|
| **today** | **13** | **19 / 19 (100 %)** |
| centre growth | **13** | 0 |
| growth away from dot | **20** | 0 |

Frame: the grown cluster spans 537px of the 1920px CG width — **nothing leaves the frame**
in either mode. Slides 5 and 18 (r = 1.0) are unchanged in every mode, as required.

**Headline: growing away from the dot is measurably WORSE than centre growth** — 19 vs 16
overlapping pill pairs, 48 vs 40 pill–dot overlaps, 20 vs 13 overlapping labels. Centre
growth costs *nothing* against today's label overlap count (13 → 13) while fixing 19/19
escaping labels. Away-from-dot regresses readable text (13 → 20).

Intuition for why: the labels on slide 13 are laid out in tight vertical stacks; each
pill's nearest dot is usually on the *inside* of the cluster, so "grow away from the dot"
pushes every pill outward into its neighbour's column, whereas centre growth splits the
Δw = 0.667*w between both sides and half of it lands in the gap the layout already left.

## 5. Write path

- Pills are rounded rects → `scalarPathSource`. `iwa_write._shape_fields` writes
  `size_w/size_h` **and** `natural_w/natural_h`; `_write_natural_size` →
  `_scale_rect_scalar` multiplies the corner-radius `scalar` by `rx` **only when the
  resize is uniform** (`|rx−ry| <= 1e-3·max`). Our resize is `(r, r)` — exactly uniform, so
  **the corner radius scales by r offline, for free, reproducing the template proportions.**
- `_natural_unwritable` refuses a w+h resize only when the object has neither
  `originalSize` nor a writable path source. `scalarPathSource` is in
  `_NATURAL_PLAIN_KINDS` → **writable**. No new offline refusal expected; if a pill turns
  out to be a `callout`/`connectionLine`/path-source-less shape it falls back to
  AppleScript, which is acceptable.
- **AppleScript divergence:** Keynote cannot script corner radius. The repo already relies
  on this (map_remap.py:2421 comment: *"Keynote cannot script corner radius, so a resize
  squares the plate"* — the `corner_translate` badge-plate path exists precisely to avoid
  resizing a rounded plate live). So the live/AppleScript arm will produce a pill with the
  **old** radius on a 1.667x-larger body. Offline and live will not agree.
