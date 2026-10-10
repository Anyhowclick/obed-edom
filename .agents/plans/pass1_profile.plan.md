---
name: Pass 1 profile — pull only the levers the profile names
overview: >-
  2026-09-23. `obed-edom remap` on Full_Report_Card_Wall.key was profiled stage by stage
  (`.agents/reviews/pass1-profile-2026-09-23/README.md`): pass 1 is 36% of the run, not the assumed
  55%. The levers it named are pulled or measured dead; the bulk seed read is the one still open.
  Whole run 785 s → 584 s (z-order patch) and a further −63/−88 s (hides offline).
todos:
  - id: h-bulk-seed-read
    content: >-
      NEW from the profile (2026-09-23): the bulk live seed read (`inspect.bulk_geometry`,
      `bulk_geometry.js`) takes 150 s (19%) for 104 slides ≈ 1.4 s/slide. Establish what it reads
      per slide versus what the writer consumes (`_OFFLINE_SOFT_SEED_KINDS` = text only; group rows
      unused since the groups branch stopped) and whether the read can be narrowed to the kinds and
      slides that need a seed. Gate: projected saving ≥ 60 s; needs one owner-gated live run.
      DESIGNED 2026-10-10 (§ h-bulk-seed-read): text-only seed read via an opt-in `kinds`;
      projected 49–130 s by cost model; awaiting owner go + one live A/B with an early stop.
    status: pending
  - id: followup-single-rewrite
    content: >-
      GATED (moved from the hides-offline plan). Fold the hide delete into `patch_deck_geometry`'s rewrite
      (one decode and one rewrite instead of two). Precondition: the bulk seed read must run on the
      undeleted deck, with rows re-keyed through `bridge_kind_index`, which changes a live-validated
      path (offline_write.py:122-133). Pursue only if the measured hide stage is ≥ 10 s AND
      `h-bulk-seed-read` has settled what the seed read looks like.
    status: pending
  - id: seed-error-cap-guard
    content: >-
      From the h-bulk-seed-read design (owner 2026-10-10: separate todo). `bulk_geometry.js` caps
      `errors` at 50 (js:77-89); past the cap a text `item:i` error can be dropped, so its zero-filled
      row survives `_drop_unreadable_seed_rows` and can pass `seed_ok`. Treat `errorCount >
      len(errors)` as an untrusted seed. Latent today; the text-only read makes it rarer.
    status: pending
  - id: js-tests-runner
    content: >-
      From the h-bulk-seed-read design (owner 2026-10-10: separate todo). `tests/*.test.js`
      (e.g. `tests/bulk_geometry.test.js`) run by hand only; wire them into pytest or an npm script
      so the full-suite rule covers them.
    status: pending
---

# Pass 1 profile

## Done (detail in git history, `git show 0f0a70aa:.agents/plans/pass1_profile.plan.md`)

| todo | outcome |
|---|---|
| `m1-stage-timer` | always-on pass-1 stage map (`STAGES`/`_stage`, `_say_pass1_stages`), 2026-09-23 |
| `m1-run` | three runs, record in the review README; pass 1 = 267–280 s of a 769–785 s run |
| `h-attrs-roundtrips` | (i)+(ii) per-slide cached lookup + skip applyGeom: attrs ≈ 97–107 s → ≈ 19 s; one `doc.slides()` per slide deferred (≈ 2–5 s, below gate) |
| `h-copy-clone` | dead: copy 5 s |
| `h-save` | dead: save 0.9 s, never retried |
| `h-layouts` | below gate: 39 s total |
| `h-open-size` | recorded: open 3.6 s, slideSize 6.0 s |
| `h-zorder-patch` | read-back loads the deck once (`d9cf7f2b`): z-order block 183 → 20 s |
| `h-hides-offline` | `git show 1379b2df:.agents/plans/pass1_hides_offline.plan.md`, `OBED_OFFLINE_HIDES` default on |
| `deferred-build-hides` | not planned: hides carrying a build (slide 122, ≈ 0.7 s) stay on the Keynote delete; offline would need `buildEventCount`/`hasBuilds`, formula unknown — revisit only if a deck puts material time there |
| `design-offline-attrs` | not triggered: its gate was attrs ≥ 60 s after `h-attrs-roundtrips`; attrs is ≈ 19 s |

## What pass 1 does today (OBED_OFFLINE_WRITE on)

py: ditto deck (:1415, `copy_keynote` :699-707) → ditto template (:1420) → build plan (as_dict on
3822 transforms, `_build_as_geometry` twice — once inside `_offline_write_slides`, once at :1459)
→ `_run_jxa` (:1487; `open -b` + 0.4 s settle, plan JSON to a temp file osascript_runner.py:167-170,
wall limit `DEFAULT_TIMEOUT` 3900 s unless `OBED_OSASCRIPT_TIMEOUT`; `OsaResult.elapsed` :123 is
dropped by `parse_json_stdout` :184-193, so `_run_jxa` is timed from outside).
js `run`: open → setSlideSize → template open, importCgLayouts, applyCgLayouts, deleteTrailingSlides,
layoutNames, template close → per slide in `slidesInPlan(transforms)` (js:329-340, NOT the wanted
range): applyTransforms "attrs" for suppressed slides else "as"/"jxa" (:670-706), then deleteHides
→ readMapGeom, skipOutsideRange (writes `skipped` on every slide, ~155 AEs) → save, on throw
`save in` again → close saving yes (:793-811).

Attrs mode writes per spec (applyGeom :200-261): opacity, objectText font / size / color (color
fallback to attributeRuns[0]), unlock/relock around them if locked. No size, position or child write.

With `OBED_OFFLINE_HIDES` on (default) eligible slides skip `deleteHides`; the IWA writer deletes their
hides after the pass-1 save (`git show 1379b2df:.agents/plans/pass1_hides_offline.plan.md`). Line numbers above are from 2026-09-23.

## Levers

Pursue a lever only if its stage is ≥ 60 s (~8% of 720 s) and the projected saving is ≥ 30 s; take
them in profile order, not prior belief. Each lever run repeats m1-run's pass criteria (residuals
R1 ≤ 2 s and R2 ≤ 15 s; "Applied N, missed M" and the fallback line unchanged — the null control)
plus its own oracle.

## Must not change

`_require_pass1_saved_closed` (py:1108-1117, :1678) and the saved/closed contract; applied/missed
semantics incl. attrs specs counting as applied (js:460) and the 0-applied abort (js:771-786,
py:1496-1507); hides deleted after attrs, per slide, highest index first (js:2, :482-498); byte rules
for untouched ZIP members; never quit Keynote, bundle-id addressing (js:22, py:694), KEYNOTE_LOCK;
always work on a copy; `_run_jxa(plan)` / `copy_keynote(source, dest)` signatures; `OBED_WRITE_TIMING`.

## h-bulk-seed-read — design (2026-10-10, read-only planning pass)

### Finding

**What the read does.** The seed read reads four collections on every soft slide: text, image, movie and group.
- Path: offline_write.py:704-711 → `inspect.bulk_geometry` (inspect.py:338-397) → bulk_geometry.js.
- Each collection costs one fetch plus bulk position, width and height reads (js:140-145, :154-189, :191-201).
- An empty collection costs the fetch only (js:176).

**What the writer uses.** `_slide_edits` (iwa_write.py:585-779) consumes text rows only.

| kind | seed fields read | evidence |
|---|---|---|
| text, autosize (stored w or h = 0) | x and y (delta); w (grow-height gate); w > 0 and h > 0 (`seed_ok`). With no row, it misses with `text-autosize` | iwa_write.py:702-731, :307-312 |
| text, fixed frame | deltas on y, w and h. With no row, it writes the composed frame and counts `soft_fallbacks`+1 | iwa_write.py:313-323, :668, :767-772 |
| group | none; uses the composed child union | iwa_write.py:680-695; `git show 10438d18` |
| image/movie, unmasked | none; `_shape_fields` works from the stored frame | iwa_write.py:752-756 |
| image/movie, masked | x/y, only when the spec's x/y is None. That never happens, because `as_dict` always emits x and y | iwa_write.py:480-481, :770; map_remap.py:162-169; remap_keynote.py:1645 |

**Slide selection is already text-only.** `_soft_seed_slides` keys off `_OFFLINE_SOFT_SEED_KINDS = {"text"}` (offline_write.py:38, :422-437).
- Masked media on non-text slides already get no seed today.
- If a masked spec ever lacked x/y, it would soft-fall-back and be counted in `soft_fallbacks`, so it would show in the logs (iwa_write.py:767-772). It cannot happen silently.

**Census.** Source: banked plan `output/bank/2026-09-21/text-mask-default-flip/B_flagged.run.json`. A_unflagged has identical in-range transforms. Limited to `--slides 1-129,135-143,145-155`.
- 3822 transforms and 947 hides.
- 148 offline slides and 104 soft slides, which matches run 3.
- 0 non-hide image/movie specs with x or y None.
- 103 of the 104 soft slides carry autosize text. Slide 74 has fixed-frame text only.

**Items the read sees on the 104 slides.** Hides are deleted before the read (remap_keynote.py:1777, then :1784 snapshot, then :1787 write). Counts are source items minus planned hides:

| kind | items |
|---|---:|
| text | 443 IWA records, up to 651 with Keynote placeholders (text slack 2 per slide, iwa_kindindex.py:22) |
| image | 529 |
| movie | 47 |
| group | 156 |

**Baseline.** The 150 s figure comes from run 3 (2026-09-23). It was measured before hides-offline, the attrs fix and Keynote 15.4.
- Inference: the hides-offline p1-B whole run was 442 s. Subtracting the other stages leaves ≈150 s for the seed read. The subtracted stages are pass 1 74.7, offline hides 26.3, fallback 81, stat 44, z-order 20, card/captions 17, IWA patch 15.5, ditto+planner 9 and builds 4.4 (hides-offline README:28; pass1-profile README:72-82, :112).
- The in-session S(A) is the real baseline.

**Projection.** The r-nested-bulk-probe found that cost is per object-property inside Keynote: images ≈33–70 ms, text ≈9 ms (`git show f5ed2f13:.agents/plans/cg_resizer.plan.md`, line 15). Those rates come from decks whose text was already laid out.
- Today's read: 3 × (443–651 + 529 + 47 + 156) = 3525–4149 object-property reads.
- Text-only read: 1329–1953.

| model | text-only read | saving vs 150 s |
|---|---:|---:|
| probe rates (object-bound) | ≈20–26 s | ≈124–130 s |
| every property read costs the same (3.9 s open kept) | ≈59–73 s | ≈77–91 s |
| a per-slide cost that does not depend on kind (two-point fit) | ≈89–101 s | 49–61 s |

The third row has a concrete mechanism. Pass 1 zeroes naturalSize on autosize text, so the boxes are un-laid-out (iwa_write.py:713-718). Keynote must lay them out when their geometry is read, and that cost stays with text in a text-only read. Text is already read first on each slide (js:140-145), so any first-touch cost also stays.

The gate (≥ 60 s) sits inside the 49–130 s range. Only a live A/B can decide it, which is why the protocol stops early.

### Decision: smallest change first

| option | verdict |
|---|---|
| (a) read only `_OFFLINE_SOFT_SEED_KINDS` (text), at the writer's call only | **TAKE** |
| (b1) slides: only those with autosize text | reject. Only slide 74 would drop. Fixed-frame text reads y/w/h, and live geometry is whole-point while stored is float, so the output would change and a soft fallback would be added to save ≈1 slide |
| (b2) items: only the text items that need a seed | reject. The bulk read takes whole collections, and per-item reads cost ≈11 ms per property-event, no cheaper. Text is already the cheapest kind |
| (b3) fields: drop width or height | reject. `seed_ok` needs w and h; the grow-height gate reads w; fixed-frame `size_h` reads h |
| (c1) keep the seed document open for the fallback | reject. `patch_deck_geometry` rewrites the zip in between (offline_write.py:729-738), and the fallback closes by name and reopens (:599-614). It would save ≤ 4 s |
| (c2) read the seed inside pass 1 | reject. It needs a pass-1 JS change. Hides are still present at that point, so rows need `bridge_kind_index` re-keying, which is the live-validated change that belongs to `followup-single-rewrite`. It saves one open |
| (c3) derive the seed offline | reject. The autosize live frame comes from Keynote layout, which pass 1 left un-laid-out. Fixed-frame text is at most 5 boxes and would not be bit-identical |
| (c4) also narrow the source two-tier read | reject. The splice and `reconcile_counts` count every `BULK_KINDS` kind, and an absent kind counts as 0, so every slide would get a count-mismatch fallback (offline_inspect.py:22, :441-452; iwa_kindindex.py:174-188). That read is cached anyway |
| (c5) nested whole-deck events; skip empty collections | dead per r-nested-bulk-probe; moot after (a) |
| dynamic kinds (add image/movie when a masked spec lacks x/y) | reject. The condition never occurs, and the failure mode is already visible in the logs |

**Effect on `followup-single-rewrite`.** Either gate outcome settles the seed-read shape it depends on: the read stays on the hide-deleted deck, and it is text-only on PASS or all four kinds on FAIL.

### Changes (one PR, ≈20 product lines, no env flag)

**`src/obed_edom/inspect.py` `bulk_geometry`** (validation lives here — advisor 2026-10-10)
- Add `BULK_GEOMETRY_KINDS = ("text", "image", "movie", "group")`, in the JS `COLLECTIONS` order.
- Add keyword-only `kinds: Collection[str] | None = None` (`collections.abc`; the repo idiom, dsk_live.py:56).
  The file has `from __future__ import annotations`, so this works on 3.10.
- Right after the `LAST_BULK_*` reset (so a rejected call never leaves the previous call's errors
  visible): if `kinds is not None`, `want = set(kinds)`; empty or not a subset of
  `BULK_GEOMETRY_KINDS` → `ValueError` naming `sorted(want)`, before osascript runs. Otherwise
  `plan["kinds"] = sorted(want)`. A bare `"text"` becomes `{"t","e","x"}` and is rejected.
- Add one docstring clause: `kinds` limits the read; an unread kind is absent.
- `None` sends no key, so the plan JSON and output stay byte-identical for:
  - the two-tier read (remap_keynote.py:443-449; offline_inspect.py:536-542 passes only `slides`/`log`);
  - the checker (inspect.py:551-577, including the `keep_open` partial);
  - the probe (scripts/probe_nested_bulk.py:779, :794).
- No `INSPECT_VERSION` bump (baseline.py:25).
- The `ValueError` is loud only in tests: in a live run the writer's `except Exception`
  (offline_write.py:712-717) turns it into the logged whole-run AppleScript fallback, the same as a
  JS `{error}`. The writer's except stays as it is (never patch blind).

**`src/obed_edom/bulk_geometry.js`** (a plain filter, no validation — the repo's JXA scripts never
validate plan fields; they default with `plan.x || null`, e.g. js:235, remap_keynote.js:781-783)
- `slideGeom(slide, index, kinds)` skips a `COLLECTIONS` entry when `kinds && kinds.indexOf(kind) < 0`.
  It still loops in `COLLECTIONS` order, so text is read first whatever the plan order.
- `run()` passes `plan.kinds || null` to `slideGeom`.
- A kind that was not read is absent from the slide's object, never `[]` (`[]` already means
  "Keynote reports zero items", js:176). `reconcile_counts` counts an absent kind as 0
  (iwa_kindindex.py:183), so a two-tier read narrowed by mistake fails safe as a count mismatch.
- No new export and no new `{error}` path.

**`src/obed_edom/offline_write.py`**
- :707 becomes `_inspect.bulk_geometry(dest, slides=sorted(soft_slides), kinds=_OFFLINE_SOFT_SEED_KINDS, log=say)`. The slide set and the kinds now come from one constant.
- The log lines at :706 and :708 stay unchanged; they are the timing oracle.
- `_reported_from_bulk_rows` and `_drop_unreadable_seed_rows` are unchanged.
- Owner decision 4: correct the `_patch_offline_slides` docstring (:689-690). Fixed-frame text without a seed writes the composed frame and is counted as a soft fallback; it is not a refusal.

**Must not change: untouched.**
- No pass-1 JS or Python change and no hide-path change.
- ZIP byte rules, `KEYNOTE_LOCK`, bundle-id addressing and the `_run_jxa`/`copy_keynote` signatures are untouched.
- The read still opens only the `dest` copy.

### Tests

| file | test |
|---|---|
| tests/bulk_geometry.test.js | `slideGeom(slide, 7, ["text"])` on a slide whose images/movies/groups accessors record a call and throw: keys `["text"]`, rows equal to the default read's text rows, 0 non-text calls, 0 errors. The existing 2-argument `slideGeom` tests stay as they are |
| | `slideGeom(slide, 7, ["group", "text"])` with recorded call order: text is read before group |
| | `run()` with `kinds: ["text"]` on accessors that record calls (not `emptySlide`): every geometry entry has keys `["text"]`, 0 image/movie/group calls, and the doc closes. A keys-only check would pass a read-all-then-drop implementation |
| | `run()` with no `kinds`: all four keys come back (no current `run()` test checks the geometry; "absent means all four" is what protects every other caller) |
| tests/test_bulk_read.py | a default call carries no `kinds` key; `kinds=frozenset({"text","image"})` → plan `["image","text"]` (via `_capture_bulk_plan`, :333) |
| | parametrized `kinds` = `set()`, `{"texts"}`, `"text"` → `ValueError`, and the `_capture_bulk_plan` capture stays empty (osascript never ran) |
| | JS↔Python parity: the `COLLECTIONS` kinds regex-parsed from bulk_geometry.js equal `BULK_GEOMETRY_KINDS` in order (precedent: test_remap_keynote.py `test_pass1_js_stage_names_match_js_source`) |
| tests/test_offline_write.py | the first `_patch_offline_slides` test with a text spec (`_spec()`, slide 3; today only shape specs are tested, :1855, :1874). Fake `bulk_geometry(key_path, slides=None, *, kinds=None, keep_open=False, log=None)` returns `{2: {"text": [[1, 2, 3, 4]]}}`; `LAST_BULK_ERRORS=[]`; a fake `patch_deck_geometry` captures kwargs. Assert `slides == [3]`, `kinds == _OFFLINE_SOFT_SEED_KINDS`, `reported_by_slide == {3: {("text", 0): [1.0, 2.0, 3.0, 4.0]}}`, on the kwargs the fake `patch_deck_geometry` captured (offline_write.py:712 would swallow a `TypeError`, so `out` or the log lines alone would miss a bad call), and that both log lines are said |
| tests/test_iwa_write.py | `_slide_edits` on the `deck` fixture (:274; shape, line, fixed text, masked image, group) with `text_reposition=True, mask_crop=True`. A full seed (text, image and group rows that differ from composed) must equal the text-filtered seed. Positive controls: dropping the text row changes the result, and an image spec with `x=None` makes the full and text-filtered seeds differ |

**Two-tier test doubles.** The existing doubles `fn(key_path, slides=None)` in tests/test_offline_inspect.py stay as they are. They guard only indirectly: `two_tier_wall_payload` swallows a `TypeError` into bulk-missing (offline_inspect.py:539-548), so only the tests that assert spliced output would notice. That is acceptable, because the PR does not touch two-tier code.

**Suites (there is no CI).** First set up the worktree: `uv sync --frozen --all-extras --all-groups`, `cd dashboard && npm ci`, and symlink the fixtures.
- `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal -rs`.
- The same suite on the 3.10 floor: `UV_PROJECT_ENVIRONMENT=<dir> uv sync --frozen --all-extras --all-groups --python 3.10`, then pytest with that env.
- `node tests/bulk_geometry.test.js`. It is not wired into pytest or npm, so run it by hand and paste the pass count.
- `cd dashboard && npm run test:ui && npm run test:maps`.

### Keynote-free proof, before any live run

- **P1.** The tests above.
- **P2.** Real-shape equivalence of the consumer across the 148 offline slides.
  - Decode the source deck once (_load_deck ≈ 1.7 s, pass1-profile README:103).
  - Take specs from the banked plan with hides dropped, so the wall kindIndex equals the deck kindIndex (`_resolve_positional` with no hides, iwa_write.py:572-576).
  - Build a four-kind seed from the cached 15.4 JXA wall payload.
  - Compare all six `_slide_edits` outputs for the full seed against the text-filtered seed.

  This tests the consumer on production-shaped specs and records, not on the post-pass-1 state. It is light (under a minute) but still waits until the machine is free. It runs on either worktree.

```sh
cd "$B" && uv run --no-sync python - <<'EOF'
import json
from pathlib import Path
from obed_edom import iwa_write as W
from obed_edom.offline_write import _OFFLINE_SOFT_SEED_KINDS as K, _offline_write_slides, _soft_seed_slides
M = Path("/Users/anyhowclick/Desktop/work/obed-edom")
T = json.load(open(M / "output/bank/2026-09-21/text-mask-default-flip/B_flagged.run.json"))["plan"]["transforms"]
wall = json.load(open(M / ".cache/inspect/549343a6f95275e7ad458b1551b87cc32d0cc0e1b0cc091096ec85161776334b.v5.k15.4.json"))
off = sorted(_offline_write_slides(T, sorted({*range(1, 130), *range(135, 144), *range(145, 156)})))
specs = {n: [t for t in T if int(t["slide"]) == n and t.get("role") != "hide"] for n in off}
seed = {int(s["number"]): {(i["kind"], int(i["kindIndex"])): [float(i[c]) for c in "xywh"]
        for i in s["items"] if i["kind"] in ("text", "image", "movie", "group")} for s in wall["slides"]}
objects, id_to_file, _ = W._load_deck("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key")
order = W.slide_order(objects)
def edits(n, keep, sp):
    rep = {k: v for k, v in seed.get(n, {}).items() if keep(k[0])}
    return W._slide_edits(n, sp, objects, id_to_file, order, reported=rep, text_reposition=True, mask_crop=True)
ALL, TXT, NOTXT = (lambda k: True), (lambda k: k in K), (lambda k: k not in K)
nomedia = {n: [dict(s, x=None) if s["kind"] in ("image", "movie") else s for s in sp] for n, sp in specs.items()}
print("offline", len(off), "soft", len(_soft_seed_slides(set(off), specs)))
print("DIFF full vs text (must be [])", [n for n in off if edits(n, ALL, specs[n]) != edits(n, TXT, specs[n])])
print("PC text rows dropped (expect close to soft)", sum(edits(n, ALL, specs[n]) != edits(n, NOTXT, specs[n]) for n in off))
print("PC media x=None (expect > 0)", sum(edits(n, ALL, nomedia[n]) != edits(n, TXT, nomedia[n]) for n in off))
EOF
```

**P2 passes when:**
- the output reads `offline 148 soft 104`;
- the diff list is `[]`;
- both positive controls are non-zero.

The media control proves the harness would see image-seed use: a masked spec with `x=None` reads `rep[0]` and adds a soft fallback when no row is present.

**What P2 cannot show.** It cannot show that text rows are identical between a four-kind and a text-only Keynote read.
- No seed rows are banked.
- The JS shares only its error and note lists across kinds.
- The live O1 and O2 checks cover this: a changed text row shifts `pos_x`/`pos_y` (iwa_write.py:307-312) or flips a grow-height or seed miss.

### Live gate (ONE owner-gated session, ≈40 min of Keynote; ≈20 min if it stops early)

**Preconditions**
- Owner go. The Alpha Keynote session has released Keynote and the CPU (it has priority).
- `pgrep -x Keynote`. If Keynote is running, the owner confirms it has 0 open documents. Never probe it with osascript, because that launches Keynote. Never quit it.
- All launchers run unsandboxed, from detached worktrees:
  - A = merge base (f4a44ca0);
  - B = branch head.
  - In each, run `uv sync --frozen --all-extras --all-groups`, then use `uv run --no-sync`. Without the `iwa` extra, offline write is forced off (offline_write.py:55-70).
- Load guard before P0 and before each run.
  - Wait for a 1-minute load below 4, with a 10-minute deadline. macOS has no `timeout`, so loop on `date +%s`; under the agent harness, use a background task or a Monitor until-loop.
  - Stop the session if the load is still ≥ 8. A cold Keynote under load once inflated a baseline 5×, in run 5.
  - Log `uptime` for each run.
- Decks go in the visible main-checkout `output/seed-read-ab/`, because Keynote cannot open `.claude/` paths.
- Disk: ≈60 GB peak (four final decks, four snapshots, and dest plus `.obedwrite.tmp` during a run); 460 GB is free.
- Record `shasum -a 256` of the source deck and the template before P0 and after A2. Both must be unchanged.

**Cache hazard.**
- Installed Keynote is 15.4. The main `.cache` 15.4 entry for the Full wall is the banked JXA read. In mode `on` it is stale_jxa (remap_keynote.py:390), so a run would re-read the deck and overwrite it (:512-514).
- The banked 15.3.1 offline entry is no help: it lacks `spliceAspectRefreshed`, so it is stale_aspect (:403-409) and would also be re-read.
- So both arms use a dedicated `OBED_EDOM_CACHE_DIR` (baseline.py:34-44), and P0 primes it.
- P0 also primes the 15.4 template stat (there is only a 15.3.1 entry; keynote.py:1146-1160, remap_keynote.py:1885). Otherwise A1 alone would pay that Keynote read.
- P0 also leaves Keynote warm for A1.

```sh
OUT=/Users/anyhowclick/Desktop/work/obed-edom/output/seed-read-ab; SRC="/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs"
export OBED_EDOM_CACHE_DIR="$OUT/cache"; mkdir -p "$OUT/cache"
cp -Rp /Users/anyhowclick/Desktop/work/obed-edom/.cache/{deck_digest,pairings,template_stat,settings.json} "$OUT/cache/"
shasum -a 256 "$SRC/Full_Report_Card_Wall.key" "$SRC/Base_CG_Assets.key" > "$OUT/sha.before"
# P0 (Keynote ≈ 5-6 min): fresh 15.4 two-tier source read + template stat into the dedicated cache
(cd "$A" && uv run --no-sync python -c "from pathlib import Path; from obed_edom.remap_keynote import acquire_wall_payload, offline_read_mode; from obed_edom.keynote import read_template_stat_sizes; S='$SRC'; p = acquire_wall_payload(Path(S + '/Full_Report_Card_Wall.key'), slide_range=None, mode=offline_read_mode(), say=print); print(p['reader'], len(p['slides'])); print(len(read_template_stat_sizes(Path(S + '/Base_CG_Assets.key'))))")
ls "$OUT/cache/inspect" "$OUT/cache/template_stat"   # expect a *.v5.k15.4.json (reader offline) and a template *.k15.4.json
set -o pipefail   # bash and zsh: a failed remap must not hide behind `tee`
run() {
  [ ! -e "$OUT/out.key" ] || { echo "stale out.key"; return 1; }
  uptime > "$OUT/$1.uptime"
  (cd "$2" && OBED_DEBUG_PASS1_SNAPSHOT="$OUT/$1-pass1.key" uv run --no-sync obed-edom remap "$SRC/Full_Report_Card_Wall.key" --template "$SRC/Base_CG_Assets.key" --slides 1-129,135-143,145-155 --no-export --out "$OUT/out.key" 2>&1 | tee "$OUT/$1.log") || { echo "$1 FAILED (deck left at out.key)"; return 1; }
  mv "$OUT/out.key" "$OUT/$1-final.key"
}
# S = seconds between exactly one "bulk live seed read of" and one later "bulk seed read done" line
S() { awk 'match($0, /^\[\+ *[0-9.]+s\]/) { t = substr($0, 3, RLENGTH - 4) + 0 } /Offline-write: bulk live seed read of/ { a = t; na++ } /Offline-write: bulk seed read done/ { if (na == 1) b = t; nb++ } END { if (na != 1 || nb != 1 || b == "") { print "S: bad seed-read markers in " FILENAME > "/dev/stderr"; exit 1 } printf "%.1f", b - a }' "$OUT/$1.log"; }
W() { grep -oE '^\[\+ *[0-9.]+s\]' "$OUT/$1.log" | tail -1 | tr -d '[+ s]'; }
gate1() { awk -v a="$(S A1)" -v b="$(S B1)" 'BEGIN { d = a - b; printf "pair1 S(A1)=%s S(B1)=%s saving %.1f s\n", a, b, d; exit !(a != "" && b != "" && d >= 60) }'; }
if run A1 "$A" && run B1 "$B" && gate1; then run B2 "$B" && run A2 "$A"; else echo "EARLY STOP: run failure or pair-1 gate FAIL — record and stop"; fi
shasum -a 256 "$SRC/Full_Report_Card_Wall.key" "$SRC/Base_CG_Assets.key" | diff - "$OUT/sha.before" && echo "sources unchanged"
```

- Every run writes to the same `--out`, so the logged paths and the Keynote document name are identical across runs.
- The snapshot (`shutil.copy2`, remap_keynote.py:239-259) is taken before the offline write (:1784), so it falls outside S.

**Early stop.** If S(A1) − S(B1) < 60 s after the first pair, the gate has already failed.
- Stop the session.
- Record S, the whole-run times and O1 for A1/B1.
- Close the PR unmerged.

**O1 — null control: A1 = B1 = B2 = A2**

```sh
NC='^(Read .* from cached|Applied [0-9]|Pass 1 census:|Offline hides|Offline-write|Stat zorder detail:|Card-border stroke:|Builds follow source:)'
norm() { sed -E 's/^\[\+ *[0-9.]+s\] //; s/, [0-9.]+s\.$/./' "$1" | grep -E "$NC" | grep -v 'snapshot written'; }
for r in B1 B2 A2; do diff <(norm "$OUT/A1.log") <(norm "$OUT/$r.log") > "$OUT/O1-$r.diff" && echo "$r identical"; done
grep -h 'Pass 1 unattributed' "$OUT"/{A1,B1,B2,A2}.log; grep -hE 'Bulk geometry:|^\[\+ *[0-9.]+s\]   slide=' "$OUT"/*.log
```

The lines covered by O1:
- the cached-offline source read line, present in all four runs;
- `Applied N, missed M` (remap_keynote.py:1783) and the CLI line `Applied N objects … missed M` (cli.py:740-744);
- the census line;
- the offline-hides summary (its trailing seconds are stripped);
- `Offline-write (on): patching 148`;
- `bulk live seed read of N slide(s)`;
- every `Offline-write slide N: applied= missed= value_clean= [soft_fallbacks=]` line;
- the fallback count, reasons and worst-slides lines;
- `Stat zorder detail`;
- `Card-border stroke`;
- `Builds follow source`.

Also required:
- No "needs the `iwa` extra" line in any log.
- Pass-1 residuals R1 ≤ 2 s and R2 ≤ 15 s.

**Allowed difference.** Only the `Offline-write soft seed: dropped N` count, and only when A1/A2's `Bulk geometry:` lines name image, movie or group.

**O2 — deck comparison** (Keynote-free and CPU-heavy; run after the live runs, when the machine is free)

```sh
cd "$B" && for p in "A1 A2" "A1 B1" "A2 B2"; do l=${p% *}; r=${p#* }; uv run --no-sync python scripts/deck_decode_diff.py "$OUT/$l-final.key" "$OUT/$r-final.key" --json "$OUT/O2-$l-$r.json" | tail -1; done
python3 -I -c "import json,re,sys; k=lambda f:{re.sub(r'[0-9A-Fa-f-]{8,}','#',d['key']) for d in json.load(open(f))['diffs']}; n=k(sys.argv[1]); [print(f, sorted(k(f)-n) or 'within null') for f in sys.argv[2:]]" "$OUT"/O2-A1-A2.json "$OUT"/O2-A1-B1.json "$OUT"/O2-A2-B2.json
```

- Every comparison must print `differing slides: none`.
- The A-vs-B non-slide key classes must fall within the A1-vs-A2 null. Investigate any new class by hand before calling it noise.
- If a slide differs, diff the same pair's `-pass1.key` snapshots to locate the cause. Those must be identical, because the change sits downstream of the snapshot.

**O3 — timing.**
- S = the elapsed-prefix delta between offline_write.py:706 and :708 (`S()` above).
- Whole = the last elapsed prefix (`W()`).
- Record S and Whole for all four runs, with each run's uptime.

**Gate. PASS iff all of these hold:**
- P1 and P2 pass;
- O1 holds in all four runs;
- O2: 0 differing slides, and non-slide key classes within the null;
- S(A1) ≥ 60 s and S(A2) ≥ 60 s, which re-checks the stage gate in-session;
- S(A1) − S(B1) ≥ 60 s **and** S(A2) − S(B2) ≥ 60 s;
- Whole(A1) − Whole(B1) ≥ 30 s **and** Whole(A2) − Whole(B2) ≥ 30 s. This is the plan-wide saving floor, pass1_profile.plan.md:66, and it guards against cost moving into the fallback session;
- sources unchanged.

Any FAIL means no merge; record all S and Whole values.

**Optional diagnostic** (only if O3 lands at 60–75 s or fails unexpectedly):
- Run `I.bulk_geometry(B1-pass1.key, slides=<the banked 104>, kinds=k)` interleaved for k = None, ("text",), ("text",), None.
- Read the snapshot in place, after O2: the read closes without saving (js:215-223). Check `xattr -p com.apple.quarantine` first.
- Record the times, and check that the text rows are equal across all four reads.

**Record and clean up.**
- Record everything in `.agents/reviews/seed-read-narrow-<date>/README.md`.
- Trash the decks with `/usr/bin/trash` once the diffs are recorded.

### Owner decisions (2026-10-10)

1. **API shape:** the owner leaned yes and asked for a second opinion; one Opus extra-high advisor
   returned ENDORSE-WITH-CHANGES (adopted): keyword-only opt-in `kinds`, plan key only when set,
   kind names, absent-not-`[]`, writer-only caller, no env flag (the `OBED_*` modes gate
   output-changing writes; the earlier pass-1 speedups `20499e0b`/`d9cf7f2b` shipped without one;
   rollback is a revert). Change: validate in Python (`ValueError` before osascript); JS is a plain
   filter.
2. **Text only:** decided. The image/movie safety net would cover a dead path (`as_dict` always
   emits x/y) and re-read 529 + 47 objects.
3. **Order:** decided. Build the PR first (Keynote-free), then ONE live session after the Alpha
   Keynote session releases Keynote: P0 primes a dedicated cache, early stop after pair 1. (The
   renamed-15.3.1-payload shortcut is withdrawn: that payload is stale_aspect.)
4. **Follow-ups:** decided. Fold the `_patch_offline_slides` docstring correction into this PR;
   track the error-cap truncation guard and the JS test-runner wiring as separate todos
   (`seed-error-cap-guard`, `js-tests-runner`).

### Review log

Gate record: `.agents/reviews/seed-read-narrow-2026-10-10/README.md`.

- **Design advisor** (Opus, extra-high): ENDORSE-WITH-CHANGES, folded. Validation moved to Python; tests tightened.
- **Codex r1** (GPT-6 Astra, high): APPROVE-WITH-NITS. EDGE CASE: non-string member → `TypeError`; folded. NEW CLASS ×2 in this plan's live script (zsh word split; unenforced success/early stop); fixed. CLOSED CLASS ×4.
- **P2:** full seed vs text-only seed, `[]` differing slides on 148 offline slides; positive controls 104 and 103.

### Risks

- **Projection.**
  - If Keynote's cost is per slide or text-bound on the post-pass-1 deck (it lays out un-laid-out autosize text when that text is read), the saving is 49–61 s and the gate fails.
  - The early stop limits the loss to ≈20 min of Keynote plus one small PR, closed.
- **Baseline drift.**
  - Keynote went from 15.3.1 to 15.4, and the source read is fresh, so the plan counts may move from 3822/947/104.
  - The gate compares A and B within the session; the historical 150 s and 3822 are informational only.
- **Read order inside Keynote.** Text rows could depend on read order (layout-on-read). There is no evidence for this, and O1/O2 would catch it.
- **Cost shift.** Keynote work avoided in the seed read could reappear when the fallback session reopens the deck. The whole-run gate covers this.
- **Lost log lines.** The seed read no longer logs `Bulk geometry:` errors or notes for non-text kinds. The source two-tier read still reports all kinds.
- **Pathological cases, now safer.**
  - Non-text failures can no longer fill the shared 50-entry error cap (js:77-89) and push text `item:i` errors out of it.
  - They also cannot reach the outer catch (js:255-260).
  - Per-collection throws were already caught (js:157-175).

### Out of scope

- `followup-single-rewrite` (still gated; this design settles only its seed-read precondition).
- The source two-tier read.
- The error-cap guard and the JS test-runner wiring.
- The `LAST_BULK_ERRORS` per-path filter in the writer (pre-existing; offline_write.py:707-711 against offline_inspect.py:556-570).
- An offline seed for fixed-frame text.
- Standing owner decisions, not re-proposed: groups (stopped), Keynote-side hide batching (dropped), pill sizing (operator).