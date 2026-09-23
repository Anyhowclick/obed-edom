# Pass 1 profile — 2026-09-23 (plan `pass1_profile.plan.md`, todo m1-run)

Instrument: the always-on stage timer (commit f3f7d0d2, Opus + Codex reviewed) plus the elapsed-seconds
log prefix (65e7342e). Deck `Full_Report_Card_Wall.key` 6.3 GB (du) / 6.77 GB (byte sum), template
`Base_CG_Assets.key` 1.06 GB, source and `output/` on the same APFS volume (disk3s5), Keynote WARM (the
zero-document instance a previous remap left), machine load ≈ 11 (the full test suite had just run).
Command: defaults, `--slides 1-129,135-143,145-155 --no-export`, `OBED_WRITE_TIMING` unset.

## Run 1 (11:16:59 → 11:30:05, 786 s) — pass 1 stages

Null control PASSED: `Applied 3822 objects … missed 0` and the fallback line
(`text-grow-height-width 88, group-residual 83, masked-media 57, group-child-scale 6`) identical to
the two earlier runs. Closure PASSED: R1 (JS unattributed) 0.1 s, R2 (osascript/launch) 0.9 s.

| stage | s | note |
|---|---:|---|
| prep | 0.0 | |
| copyDeck (ditto, 6.77 GB) | 4.8 | same-volume APFS; h-copy-clone is DEAD (gate ≥ 60 s) |
| copyTemplate (1.06 GB) | 0.7 | |
| **runJxa (pass 1 proper)** | **268.1** | |
| open | 3.9 | |
| slideSize | 6.0 | sizeProp: width (first property won, no retry) |
| templateOpen | 3.2 | |
| layoutImport | 7.8 | |
| layoutApply | 29.9 | 147 slides ⇒ 203 ms/slide (the O(slides × layouts) scan) |
| trailingDelete | 1.0 | |
| templateClose | 0.1 | |
| **attrs** | **96.8** | 1928 non-hide specs ⇒ 50 ms/spec; 2443 of them carry NO attribute |
| **hides** | **115.5** | 947 hides ⇒ 122 ms/hide |
| finish | 1.6 | |
| save | 0.9 | retried: no — h-save is DEAD |
| close | 0.2 | |
| total (JS) | 267.1 | |

Census: `slides attrs=148 as=0 jxa=1; specs 2875 (hides 947, no-attr 2443, locked 0, group-children 56)`
— ONE slide takes the full JXA path (the gap the planner critique predicted; identify it before
h-attrs-roundtrips so it is not misread as attrs cost).

**Headline:** pass 1 is 274 s (35%) of a 786 s run, not the ~12 min the mtime estimate said (ditto
preserves the source mtime, so that estimate was never decomposable). Inside pass 1, attrs + hides =
212 s (79%) and are pure per-object AppleEvent cost: 50 ms per attr spec (most of which write
nothing) and 122 ms per hide. The plan's h-attrs-roundtrips gate (≥ 60 s) is met with margin;
h-layouts (29.9 s) is below its gate; h-copy-clone, h-save and h-open-size are dead.

The other 512 s of the run are outside pass 1 and were untimed in run 1 — run 2 below.

## Run 2 (11:30:57 → 11:43:46, 769 s) — whole-run timeline (elapsed-seconds log prefix)

Pass 1 stages reproduced run 1 within noise (runJxa 267.4 s, attrs 99.4, hides 112.1, layoutApply 29.7;
R1 0.1 s, R2 0.9 s). Null control PASSED again.

| block | from → to (s) | s | share | what it is |
|---|---|---:|---:|---|
| planner + cached read | 0 → 3.2 | 3 | 0.4% | |
| deck + template ditto | 3.2 → 9.2 | 6 | 0.8% | |
| **pass 1 (JXA)** | 9.2 → 276.6 | **267** | **35%** | attrs 96 + hides 116 + layouts 39 + open/size 10 + rest |
| **bulk live seed read + offline IWA patch** | 276.7 → 442.7 | **166** | **22%** | untimed split (run 3 adds the boundary) |
| AppleScript fallback session | 442.7 → 523.9 | 81 | 11% | matches the m1 timer (78.7 s) |
| z-order announce, card-border, captions | 523.9 → 537.7 | 14 | 2% | |
| stat-finalize live pass (pass 2) | 537.7 → 582.7 | 45 | 6% | 173 groups |
| **offline z-order patch + builds/transitions patch** | 582.7 → 769.2 | **186** | **24%** | untimed split (run 3 adds the boundary); both are Keynote-free Python over the 6.7 GB zips |

So Keynote-driven time is pass 1 267 + fallback 81 + stat-finalize 45 + the bulk read (part of 166)
≈ 55–60%; the rest is Python decoding/patching 6.7 GB packages. The "22 min" of the first two runs
of the day is not reproduced here (13 min); those runs carried a loaded machine (test suites) and
the m1 dump hooks — treat 13 min as the baseline from now on.

## Run 3 (11:50:17 → 12:03:22, 785 s) — fully attributed (progress lines bb5d8180)

Null control PASSED (Applied 3822 / missed 0, identical fallback line). Pass 1 runJxa 280.0 s.

| # | block | s | share | driver |
|---|---|---:|---:|---|
| 1 | **pass 1 (JXA)** — attrs ~97 + hides ~114 + layouts ~39 + open/size ~10 + rest | **280** | **36%** | Keynote AppleEvents |
| 2 | **offline z-order patch** (`run_offline_zorder`, 83 slides) | **183** | **23%** | **pure Python** over the 6.7 GB zip |
| 3 | **bulk live seed read** (`inspect.bulk_geometry`, 104 slides) | **150** | **19%** | Keynote JXA, ≈1.4 s/slide |
| 4 | AppleScript fallback session (234 specs / 95 slides) | 81 | 10% | Keynote |
| 5 | stat-finalize live pass 2 (173 groups) | 44 | 6% | Keynote |
| 6 | card-border / captions / z-order planning | 17 | 2% | Python |
| 7 | offline IWA geometry patch (148 slides) | 15.5 | 2% | Python |
| 8 | ditto copies + planner | 9 | 1% | |
| 9 | builds/transitions patch | 4.4 | 1% | Python |

Keynote-bound ≈ 555 s (71%); Python ≈ 220 s (28%), of which the z-order patch is 183 s.

## Verdicts against the plan's gates (≥ 60 s stage, ≥ 30 s projected saving)

| todo | verdict |
|---|---|
| h-attrs-roundtrips | **LIVE**: attrs + hides ≈ 212 s; 2443 of 1928+947 specs carry no attribute yet cost getItem + locked read each; 947 hides at 122 ms each |
| h-copy-clone | DEAD: copy 5 s (same-volume APFS ditto is already fast) |
| h-save | DEAD: save 0.9 s, never retried |
| h-layouts | BELOW GATE: 39 s total (layoutApply 30 s = 203 ms/slide) — record only |
| h-open-size | RECORD: open 3.6 s, slideSize 6.0 s, `sizeProp: width` first try |
| NEW: z-order patch | **LIVE**: 183 s of pure Python for 83 slides (≈2.2 s/slide) — profile `run_offline_zorder` (`offline_write.py`, `iwa_zorder.patch_deck_zorder`) with cProfile offline on the run-3 output deck; no Keynote needed |
| NEW: bulk seed read | **LIVE**: 150 s for 104 slides — the JXA `bulk_geometry.js` read; check what it reads per slide (all kinds? all items?) vs what `_OFFLINE_SOFT_SEED_KINDS` (text only) actually needs |
| fallback session | 81 s; shrinks only with the parked regrow write (≈20–30 s) — unchanged |

Evidence: `output/pass1-profile{,-r2,-r3}/run.log` + `facts.txt` in the measuring worktree (git-ignored).

## Run 4 (14:34:10 → 14:43:54, 584 s) — null control for the z-order read-back fix (d9cf7f2b)

`patch_deck_zorder` re-read every patched slide through `read_slide_zorder`, each a full `_load_deck`
(1.7 s measured × 83). `read_deck_zorders` loads once. Offline A/B on the run-3 deck: 170.3 s → 14.5 s.

| block | run 3 | run 4 |
|---|---:|---:|
| pass 1 (JXA) | 280 | 239 |
| bulk seed read + IWA patch | 165 | 162 |
| fallback session | 81 | 81 |
| stat-finalize live | 44 | 44 |
| **offline z-order patch** | **183** | **20** |
| builds patch + tail | 5 | 5 |
| **total** | **785** | **584** |

Null control PASSED: `Applied 3822 objects … missed 0`, identical fallback line, identical
`Stat zorder detail` (zorderSlides=83, statRaised=173, badgeRaised=325, noop=20, refused=0). The
pass-1 delta (280 → 239) is machine noise (the runs differ in load), not a change.
Remaining ranking: pass 1 attrs+hides ≈ 210 s → bulk seed read ≈ 150 s → fallback 81 s.
