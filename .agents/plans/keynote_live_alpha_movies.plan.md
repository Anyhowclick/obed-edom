# Alpha Keynote: live movies with real alpha

**Rev 3 · 2026-10-15 · planned by Codex GPT-6 Astra high; critiqued by Opus 5.5 high (rounds 1–3); awaiting owner review**

Reviewed base: `a70bbc0e358d6845fc36f526ac62d9a039e7a05f`.

Planning only. The numbers below are results from the planning session's offline reproduction and headless Chrome probe (raw probe files were session scratch, not retained). Headful Chrome, OBS CEF, real-player/physical-output gates and full suites remain outstanding.

## 1. Finding and intended result

Prepare converts non-H.264 movies to H.264 and refuses real transparency. F2 slide 8 therefore needs an alpha-preserving conversion path.

Input: `~/Desktop/Convert wall to 16x9 CGs/F2.key`, SHA-256 `f99a68ef3dc53f5e46e639e8607954b7fa4a8d69ba9a863b453f93b5320cc51b`; export `F2-html`; movie:

`assets/29A80700-2E22-4F5A-8CC1-934BEE748D1C/assets/PIN DROP WAVE.mov-0.0000-2.6400.mov`

- ProRes 4444 (`ap4h`), `yuva444p12le`, 500×500, 25 fps, 66 frames, 2.64 s; identity matrix/edit, square pixels, timecode track, no audio.
- Source and retained probe copy are byte-identical; source size **6,524,302 B**.
- Frames 0 and 65 are fully transparent. Frame 25 has mean alpha **55.064/255**; approximately 77.4% transparent and 20.7% opaque pixels.
- Authored movie size is approximately **113.31×113.31 slide pixels**. Slide 8 starts the movie automatically; its outgoing transition is Revolve.
- Other F2 movies remain H.264. The supported player digest is `17c0c938…`.

**Recommendation:** convert supported real-alpha ProRes movies to VP9-alpha WebM, retaining exported filenames and the existing opaque conversion path. VP9-alpha passes headless decode and compositing; headful Chrome and OBS CEF remain open.

**Completion:** current F2 completes full prepare and slide 8 passes every advertised product output. An isolated transparent video or successful encode is insufficient.

**Independent blocker:** Stage T’s slide-4 per-character glyph refusal occurs before movie conversion (`html_preview.py:1088`, `:1101`; handover §3). An owner-made copy with slide 4 skipped can unblock interim eye checks; it cannot establish full-current-F2 completion.

## 2. Evidence and output semantics

### Decode evidence

The probes used Chrome **155.0.8059.79**, not 154. Round 2 changed only the server to one supporting Range requests.

| Candidate | Existing observation | Remaining limitation |
|---|---|---|
| VP9-alpha WebM, CRF 20, `yuva420p` | Headless seek reaches **1.0 s**. Canvas2D/WebGL alpha MAE **0.1/255**; 100% of source-transparent pixels have α<16 and 100% of source-opaque pixels have α>239. DOM over magenta: **100%/0%** magenta in transparent/opaque classes. Identical result for retained `.mov` name served as `video/quicktime`. | Headless only; coarse 16/239 classes, not gate thresholds 2/253; native 500 px, not product 113 px. Headful Chrome, OBS CEF and real player untested. |
| HEVC-alpha MOV | Headless `PIPELINE_ERROR_DECODE`. | Deferred; no headful/CEF qualification. |
| Original ProRes | `DEMUXER_ERROR_NO_SUPPORTED_STREAMS`. | Conversion required. |
| Opaque H.264 / opaque VP9 | Decode opaque; **0% magenta** in source-transparent pixels. | Retain as negative transparency controls. |

The stuck seek is **A/B-confirmed as server-dependent**: only the server changed, and the seek then landed. Step 0 uses `_AssetServer`, which already supports Range requests.

A movie that fails to decode composites as fully transparent: HEVC-alpha and ProRes showed **100% magenta in both classes**. The oracle therefore requires successful decode and the opaque class; transparent pixels alone cannot prove success. `canPlayType` is insufficient.

The VP9 candidate is **246,543 B**. Explicit libvpx decoding reproduced all 66 retained candidate alpha planes exactly. Native ffmpeg VP9 decoding instead reports `yuv420p` and fails `alphaextract`.

### HDMI Chrome

`Display.as_output()` reports HDMI with `alpha=False` (`live_host.py:382`). The page retains its background and uses an opaque black hide overlay (`:604`).

There is **no separate HDMI key output**. Correct alpha means transparent movie pixels reveal underlying authored content and partial pixels blend with it. HDMI acceptance proves compositing; a black screenshot proves neither transparency nor physical fill/key.

### Managed OBS Keyer

Attached output uses `_AssetServer(alpha=True)` (`live_host.py:1497`): transparent `html/body/#body`, with opacity-based hide (`:592`). Authored opaque textures remain opaque.

OBS uses one `Program` browser source with normal blending (`managed_obs.py:117`) and external keyer setting `keyer=1` (`:144`). No separate grayscale key page exists. OBS 32.2.2 requests BGRA and passes the configured keyer mode to the device. [Pinned OBS source](https://raw.githubusercontent.com/obsproject/obs-studio/32.2.2/plugins/decklink/decklink-output.cpp)

For premultiplied movie colour/alpha `(P,a)` over page `(P_b,a_b)`:

`P_out = P + (1−a)P_b`; `a_out = a + (1−a)a_b`.

Transparent movie pixels add no key while preserving underlying content’s key. Over empty transparent page, alpha 0/1 must yield key 0/1; partial alpha must retain intermediate key. Opaque black remains keyed. Never substitute luma-keying.

Capture page/source RGBA, then inspect physical fill, key and switcher composite. The NV12 profile/recording setting (`managed_obs.py:162`) does not make an opaque recording an alpha oracle.

## 3. Encoding and container choice

| Option | Decision |
|---|---|
| **VP9-alpha WebM** | First increment, subject to Step 0 and product gates. |
| HEVC-alpha | Out of scope; existing headless failure prevents a common-path recommendation. |
| Packed colour+matte H.264 | Separate fallback design if VP9 fails a required output; requires player reconstruction and changes to every movie consumer. |
| VP8-alpha, image sequences, other formats | Out of scope; no additional encoder matrix. |
| Flattened H.264 | Verified opaque inputs and negative controls only. Never flatten real alpha. |

Keep exported filenames and URLs. Encode with explicit `-f webm` into a temporary sibling, verify, then replace cached bytes. `convert_movies` must not rewrite slide JSON/JSONP or exported `main.js`.

WebM uses EBML/Matroska structures, not ISO-BMFF; its conventional MIME is `video/webm`. [WebM guidelines](https://www.webmproject.org/docs/container/)

Retained `.mov` serving as `video/quicktime` already passes headless Chrome. Change MIME only if a required output demonstrates a need; then share one byte-based helper between live serving and Build Preview. Leave `MOVIE_SUFFIXES` unchanged: converted files retain existing suffixes; native `.webm` source discovery is outside increment 1.

## 4. Assumption inventory

References are under `src/obed_edom/` unless otherwise stated.

| Seam | Planned treatment |
|---|---|
| `preview_movies.py:1`, `:32`, `:35` — descriptions, encoder, remedy | Describe both targets; retain opaque encoder; make progress, failures and remedies target-specific. |
| `preview_movies.py:33`, `:54` — suffixes/discovery | Preserve `.mov`/`.mp4`/`.m4v` discovery and missing-file reporting; no `.webm` suffix addition. |
| `preview_movies.py:78`, `:246` — H.264-only acceptance | Share one predicate: existing H.264 acceptance, or supported WebM VP9 with `AlphaMode=1` and readable required metadata. Opaque/unknown VP9 stays unconverted. |
| `preview_movies.py:97`, `:257` — `mdat` deduplication | Keep BMFF source grouping; include target in the key. Accepted WebM bypasses this helper. |
| `preview_movies.py:122`, `:128`, `:144` — format/alpha/refusals | Select opaque versus supported real-alpha target; use explicit libvpx for VP9 alpha decoding. Preserve unreadable-alpha and unsupported-source refusals. |
| `preview_movies.py:163`, `:178` — encoding/messages | Preserve H.264/AAC path; add video-only VP9/WebM argv without MOV timescale or AAC options. |
| `preview_movies.py:202` — verification | Preserve opaque verification; add WebM metadata, decoded frame count, duration and alpha comparison. |
| `preview_movies.py:234`, `:288` — conversion/manifest | Preserve preflight, deduplication and per-file replacement; record target per entry and encoder per target. |
| `live_codec.py:22`, `:311`, `:328`, `:351` — codec recognition | Add bounded WebM parsing; return `V_VP9`, mapped to `vp9`. Preserve BMFF `vp09` recognition. |
| `live_codec.py:255`, `:287`, `:334`, `:340`, `:346` — timing/geometry | Keep BMFF structures. WebM helper exposes dimensions, duration and available DefaultDuration; `movie_fps` uses that rate when readable. Never invent BMFF sample counts/timescales or infer CFR. |
| `live_continuity.py:2303`, `:2336` — codec census | Keep shared-reader propagation across referenced copies, independent of continuity; census remains best-effort diagnostics. |
| `live_host.py:203`, `:1271` — support/warnings | Admit ordinary VP9 only in qualified modes; distinguish managed OBS from external attach. Preserve warnings; implement selected start policy, including unknown census results. |
| `live_host.py:1305`, `:1323` — continuity/G2 | Explicitly refuse planned VP9 despite ordinary-playback admission; retain G2 cleanup. No deck-wide alpha shutdown. |
| `live_host.py:1030`, `:1041` — rate/Program guard | Preserve rate warnings, including 25→30; no resampling or new cadence metric. |
| `live_host.py:493`, `:556`, `:575`; `web/app.py:1211`, `:1235` — serving | Calibration MP4 unchanged; preserve Range handling and suffix MIME unless an output proves a MIME change necessary. |
| `live_host.py:592`, `:1487`, `:1497` — composition/player | Preserve alpha page and independent player patching; no new key renderer. |
| `live_runtime.py:65`, `:136`, `:158`, `:406`, `:434` — freeze/rendering | Preserve tuple, placement and whole-backing opacity guards. Build Preview remains without freeze take/attachment. |
| `live_continuity_js.py:243`, `:1698`, `:1906` — snapshot/poster/feed | No changes. JPEG snapshots cannot prove alpha; alpha carry/remount remains unqualified. |
| `live_gl_replay_js.py:342`, `:1280` — video textures | No changes. Reused Canvas2D backing is drawn without clearing; transparent replay remains unqualified. |
| `html_preview.py:136`, `:900`, `:920`, `:1088`, `:1101` | Preserve rendering patch, bytes-based cache checks, repair-before-conversion and successful-manifest publication. |
| `web/live.py:82`; `dashboard/src/live/api.ts:7`; `dashboard/src/live/LivePresenter.tsx:62` | Pass/display conversion target with legacy H.264 fallback; no provenance plumbing or deck-wide continuity mirror. |
| `managed_obs.py:39`, `:117`, `:144`, `:162` | Preserve OBS pin, source, keyer and profile; coordinate qualification with OBS owner. |
| `dsk_movie_export.py:142`, `:150`, `:752`, `:914`, `:1171`; `maps_movie.py:156`; `cli.py:127` | Separate opaque-export workflows and shared H.264 defaults remain unchanged. |
| `placement_probe.py:26`, `:475`; `data/placement_probe.json:17` | Existing H.264/BT.709 calibration unchanged; alpha playback grants no placement/tone qualification. |
| `README.md:19`, `:59`, `:299`, `:336`; obed-edom `SKILL.md:737` | Update conversion/cache/support wording and retained limitations. |

Harness H.264 assumptions remain controls: `scripts/binary_counter_movie.py:103`, `p2_recovery_html_dissolve_live.py:461`, `p2_recovery_html_adversarial.py`, `run_gates.sh:276`, `live_fixture_session.py:5`, `dissolve_probe.py`, `line_draw_probe.py`, `obs_cadence_decode.py:51`, `managed_obs_qualify.py`. Do not generalize these fixtures or use opaque recording scorers to prove key alpha.

## 5. Step 0 — bounded qualification

Use one small probe and existing capture infrastructure. Retain inputs, argv, hashes, raw PNGs, frame timestamps and offline scores outside `output/`. No synthetic movie, browser framework or trail metric.

Run sequentially on headless Chrome, host-launched headful Chrome and pinned OBS **32.2.2** CEF. Record actual engines, GPU/settings, player digest, viewport/DPR, `VideoFrame.colorSpace` and HTTP responses. Qualify OBS 25/30 separately when both rates are advertised.

The planning-session headless row is not AM-0 evidence: its raw captures were not retained and it used the coarse 16/239 classes. Step 0 repeats headless at **2/253** with frame-identity evidence.

### Serving, frame identity and capture

- Use F2 source, retained VP9-alpha candidate and opaque H.264/VP9 twins. Canvas2D/WebGL rows are informational; DOM and product-player rendering decide support.
- Serve through `_AssetServer._send_file` (`live_host.py:556`); record a **206** response. Do not separately re-test existing Content-Range/body handling.
- Test `.webm` and retained `.mov` URLs. Preserve existing MIME unless a required output fails specifically because of it.
- Seek to **0.2, 1.0 and 2.0 s**; require completed seek and `requestVideoFrameCallback.mediaTime` within **40 ms**, timeout **5 s**. Register frame observation before seeking.
- Decode errors fail; stale frames, timeouts or missing timestamps are INCONCLUSIVE. Fully transparent frame 0 cannot qualify playback.
- Capture stable frames with CDP `Page.captureScreenshot` and transparent default-background override; for OBS use `GetSourceScreenshot` PNG on **Program**, following `scripts/line_draw_probe.py:1146`. Verify PNG alpha and coordinate with the OBS owner. Do not reuse the calibration-only `capture_png` adapter.

### Native-size and product thresholds

The retained all-66-frame encoder measurements are:

| Alpha metric, units 0–255 | CRF 20 baseline | Gate |
|---|---:|---:|
| Whole-clip MAE / p99 | 0.0697 / 2 | ≤0.25 / ≤4 |
| Whole-clip PSNR | 53.44 dB | ≥48 dB |
| Opaque pixels ≥253, no erosion | 98.956% | Report only |
| Opaque pixels ≥253, 2-source-pixel erosion | 99.978% | ≥99.5% |
| Zero pixels ≤2, same erosion | 99.997% | ≥99.5% |
| Partial-alpha share / MAE / p99 | 1.592% / 2.866 / 12 | Report only; owner eye |

**MAE/p99/PSNR comparisons against source alpha apply only at native size**, in encode verification and native-size probes. They must not measure browser scaling at the authored 113 px size. Maximum observed alpha error is 33; no global edge-p99 gate.

Product captures use interior classes only: map source masks to the authored rect, account for DPR, and erode by **at least 2 display pixels**. At 113 px, the measured opaque populations after erosion are **31 pixels at 0.2 s, 666 at 1.0 s, zero at 2.0 s**.

At **t≈1.0 s**, require ≥100 pixels in each zero/opaque class and ≥99.5% at alpha **≤2/≥253**. At **0.2 and 2.0 s**, score only the zero class, with ≥100 pixels. Missing required classes are INCONCLUSIVE. Apply movie-alpha scoring over empty transparent page; where authored content lies beneath, assess the composite defined in §2.

Both opaque controls must decode and reject the transparency oracle: ≥99% of source-zero interior pixels remain alpha ≥253. Scorer self-comparison must yield exactly zero differences. Inspect partial edges, colour and halos over one contrasting backdrop beside native Keynote.

Use `_ProgramGuard` for cadence/media advancement; unknown evidence is not PASS. Advertise an output only after its decode and product gates pass. Chrome success does not qualify CEF; retain failures/inconclusives and reconsider packed-matte separately if a required output fails.

## 6. Minimal implementation

### Conversion and verification

In `preview_movies.py`, support real-alpha **ProRes 4444** using the existing readable timing/geometry and even-size checks, with identity rotation/edits for this alpha path, real alpha measured as today, and **no audio stream**. Preserve opaque behaviour, including alpha-capable sources whose alpha is entirely opaque.

Add no size/duration/rate caps, CFR proof, square-pixel requirement, single-video-stream restriction or new colour/HDR refusal. Select the first video stream with `-map 0:v:0`; passthrough timing accommodates VFR timestamps. Refuse unreadable timing/geometry/transparency, unsupported alpha sources and audio by asset name.

Candidate encoding: `libvpx-vp9`, `-pix_fmt yuva420p -crf 20 -b:v 0`, `-fps_mode passthrough`, video-only mapping and explicit `-f webm`. Drop timecode; do not synthesize audio or retag colour to BT.709.

For VP9 alpha inspection and verification, put **`-c:v libvpx-vp9` before `-i`**. Missing encoder/decoder or alpha loss refuses publication.

Verify `V_VP9`, `AlphaMode=1`, dimensions, matching decoded frame count and duration within half a source frame, following existing `_verify` shape. F2 must retain **66 frames** and **2.64 s within 20 ms**. No per-frame timestamp matching or separate 1 ms quantization rule.

Use one ffmpeg-filter comparison of corresponding source/result alpha planes, such as `alphaextract` followed by `psnr`; enforce **≥48 dB**. This guards against alpha loss, not edge damage, because transparent pixels dominate the clip. Edge quality remains owner eye/Q2. Keep percentile/mask scoring in qualification; no Python raw-frame streaming subsystem.

Preserve preflight refusal collection, equivalent-source deduplication and verified per-file replacement. Do not promise whole-export rollback: `apply_preview` removes incomplete cached exports on failure (`html_preview.py:1105`).

### Small WebM reader and existing cache model

Add a bounded EBML reader in `live_codec.py` for the selected ffmpeg output: DocType, Segment Info, video-track codec, dimensions, duration, available DefaultDuration and AlphaMode. Stop before media clusters; reject malformed or incomplete required metadata. Do not make DefaultDuration a CFR admission test.

Measured candidate offsets: EBML **0**, DocType payload **24**, Segment **36**, Info **209**, actual Tracks **262**, TrackEntry **267**, CodecID **300**/payload **302**, DefaultDuration **310**, Video **318**, AlphaMode **331**, Tags **354**, first Cluster **652**. Byte 73 is a SeekHead reference; parse structure, never search byte substrings.

Keep `MovieTiming`/`MovieGeometry` BMFF-specific. `movie_codec` and `movie_fps` dispatch by bytes; reuse the WebM helper for acceptance and verification. No ffprobe dependency, general Matroska demuxer or invented timing metadata.

Keep bytes-based cache acceptance (`html_preview.py:920`): no manifest version bump, mandatory provenance, startup SHA revalidation or second integrity layer. Metadata recognition does not prove full decode integrity.

Extend `movieConversion` with `converted[].targetCodec` and encoder descriptions per target; retain existing hashes as informational records. Preserve legacy records: absent target means H.264. A mixed record must not claim every asset used libx264.

### Ordinary playback, continuity and freeze

Extend `_codec_supported` for ordinary VP9 only in qualified modes; distinguish managed OBS and keep external attach unsupported. Retain census, `codecWarnings` and rate warnings. Record engine builds as evidence; preserve `PINNED_OBS`. Chrome upgrade policy is Q5; no exact-build/provenance admission table.

The proposed release default is a named VP9 start refusal on unqualified outputs, as the brief requests. Q4 may explicitly select existing warning-only behaviour. **If blocking is selected**, also refuse when the census is empty despite referenced movies, or any referenced movie has an unreadable family on an unqualified output: `_resolve_codecs` currently catches exceptions and returns `[], []` (`live_host.py:1275`); unreadable codecs map to `other`. Keep warnings for diagnostics.

Example refusals: “PIN DROP WAVE.mov has audio; alpha conversion currently supports silent movies”; “PIN DROP WAVE.mov lost transparency during conversion”; “VP9-alpha playback is not qualified for this output”; “Movie codec census unavailable; playback cannot be qualified for this output.”

**No deck-wide continuity stand-down.** Retained F2 derivations, with G2 disabled and enabled, are `{"schema":2,"movies":{},"boundaries":[]}`. PIN DROP WAVE participates in no continuity boundary.

Explicitly reject `family=="vp9"` in the planned-movie loop (`live_host.py:1305`) before ordinary-playback admission. Preserve G2-script removal on refusal and all other planned-codec behaviour.

Freeze is independent of continuity (`live_host.py:1487`). On F2 7→8, the outgoing movie is slide 7’s H.264; slide 8’s alpha movie starts after arrival. Revolve is outside the dissolve/cut freeze shape.

Keep `_FREEZE_QUALIFIED_TUPLES=["bt709/bt709/bt709/false"]`, placement guards and whole-backing opacity scan unchanged. Source/candidate tags indicate SMPTE170M primaries/matrix with BT.709 transfer; a nonqualified browser tuple is an inference until actual `VideoFrame.colorSpace` is recorded. Unknown/outside tuples refuse freeze; matching tuples still require fully opaque backing.

Chrome 155 gets no knowledge-mode `snap` grant (`live_host.py:77`, `:1545`, `:1754`), so freeze is not admitted on host-launched Chrome today. Do not expand placement qualification in this increment.

No changes to peer-owned continuity JS, MM feed or G2 hooks; no player patch planned. If ordinary playback/poster/transition rendering fails, revise scope. Any necessary player fix remains SHA-pinned, count-checked and in-memory, with both players re-pinned on the composed base.

## 7. Gates, tests and delivery

| Gate | Acceptance |
|---|---|
| **AM-0 decode** | Step 0 passes per advertised output, including strict re-scoring, frame identity, opaque controls and scorer null. |
| **AM-1 offline F2 conversion** | Scratch export outside `output/`: baseline reproduces refusal; candidate converts only the alpha movie. Existing H.264 bytes, filenames, JSON/JSONP and player remain unchanged. Repeated conversion/cache checks accept it; forced alpha loss refuses. |
| **AM-2 full prepare** | Real `apply_preview` without Keynote: `OBED_EDOM_OUTPUT_ROOT` set to a scratch root outside every `output/` (`paths.py:16`), and an `export_html_fn` (`html_preview.py:1048`) that copies a retained export. Run now on the export of the owner's slide-4-skipped copy (if Q6 approves), and on current F2 once texture repair passes. Acceptance: texture repair then conversion completes, `movieConversion` records the VP9 target, and a second apply reuses the cache. AM-1 carries the positive/negative controls. Never bypass repair to claim current-F2 success. |
| **AM-3 product playback** | Prepared owner copy: automatic start, advance/go-to, restart/seek, end, hide/show; no opaque poster rectangle or stale image. Check 7→8. Check 8→9 against peer Revolve implementation/status and record the dependency. |
| **AM-4 output eye** | Host-launched HDMI Chrome and managed-OBS physical fill/key beside native Keynote, at every advertised rate. Repeat Build Preview specifically in Chrome; another dashboard browser does not qualify Chrome. |
| **AM-5 regressions** | Focused tests, then required full local suites on the composed base; diagnose failures before changing expectations. |

Keep committed tests small:

1. Move existing constant-0.5 `alpha_real` fixture (`tests/test_preview_movies.py:54`, refusal row `:157`) into the positive conversion case; cover mixed targets, deduplication, unchanged opaque bytes, manifest and idempotence.
2. Add one alpha-loss refusal row by changing candidate argv to `yuv420p`; retain existing failure coverage.
3. Add one parametrized `test_live_codec.py` case for WebM under `.mov`, alpha/opaque metadata and truncated input; retain BMFF tests.
4. Extend host mode rows for VP9, external attach, planned-VP9 continuity/G2 refusal and the selected blocking policy’s empty/unreadable census cases.
5. Update existing API/UI mixed/legacy conversion-summary expectations; reuse freeze alpha/tuple tests.

No tamper, exact-version or bypass framework. Add a focused serving assertion only if serving code changes.

Delivery: **W0** evidence → **W1** codec/conversion/cache metadata → **W2** host support and conversion UI → **W3** prepared-copy eye, peer composition and full-current-F2 completion.

Before any code PR: full Python suites in the worktree **3.13 venv** and **3.10 floor**, plus dashboard `npm run test:ui` and `npm run test:maps`. Dashboard source changes require `npm install`, `npm run build` and restart before eye checks. No CI substitute; minimal comments and local patterns.

Coordinate one heavy job machine-wide with “need window”/“done”. Keynote/osascript runs are owner-run; visible external-monitor work needs owner scheduling. Keep exports/caches outside every `output/`; Keynote copies belong on Desktop, not `/private/tmp`. Never merge without explicit owner request.

Out of scope: HEVC-alpha, packed-matte implementation, alpha audio, nonidentity alpha rotation/edits, native `.webm` source discovery, alpha continuity/G2/freeze, new HDMI key transport, texture-identity repair and peer-owned F2 effect fixes. Risks remain browser updates, encode cost, chroma/bit-depth loss, colour/halos and physical-output alpha; no new colour/HDR admission policy is introduced here.

## 8. Review log

- **R1.1 folded:** initial probe proved transparent frame 0 only; Range serving required. Round 2 supersedes the stuck-seek limitation.
- **R1.2 folded:** empty F2 runtime; remove deck-wide stand-down, preserve planned-VP9 refusal and independent freeze limits.
- **R1.3 folded:** reuse mode/census seams; drop exact-build/provenance admission; retain policy decisions.
- **R1.4 folded; offset subclaim refuted:** retain bytes-based reuse/small reader; measured Tracks **262**, byte 73 is SeekHead. R2 confirms.
- **R1.5 folded:** explicit input `libvpx-vp9`; ffmpeg-filter alpha verification.
- **R1.6 folded:** measured margins, report-only edges and display-pixel erosion.
- **R1.7 folded:** DOM/product captures, seek identity, controls/null and ProgramGuard; no synthetic/trail/new-cadence gates.
- **R1.8 folded:** remove F2-shaped caps; structural envelope/audio refusal, simplified further in R2.
- **R1.9 folded:** suffix MIME retained unless demonstrated need (`live_host.py:575`, `web/app.py:1230`).
- **R1.10 folded:** repair precedes conversion; current-F2 blocker, interim copy and Revolve dependency explicit.
- **R1.11 folded:** Build Preview qualification explicitly names Chrome.
- **R1.12 folded:** reuse constant-alpha fixture and existing test cases.
- **R1.13 folded:** colour tags do not establish actual VideoFrame tuple.
- **R1.14 folded:** owner-only decisions, measured quality/size facts; remove moot HEVC/continuity questions.
- **R2.1 folded:** headless seek/compositing evidence upgraded; server-only A/B confirmed; decode-error false positive explicit; strict re-score or rerun required.
- **R2.2 folded:** remove CFR, square-pixel, single-stream and colour/HDR refusals; first-video mapping and existing structural checks.
- **R2.3 folded:** native-only MAE/p99/PSNR; product both classes at 1 s, zero class only at 0.2/2 s; measured populations recorded.
- **R2.4 folded:** PSNR guards alpha loss, not edges; frame-count/duration verification, no timestamp/quantization rule.
- **R2.5 folded:** blocking policy covers empty census with movie references and unreadable families on unqualified outputs.
- **R2.6 folded:** no `.webm` addition to `MOVIE_SUFFIXES`.
- **R2.7 folded:** Program screenshot precedent is `scripts/line_draw_probe.py:1146`; calibration adapter excluded.
- **R2.8 folded:** use `_AssetServer`, record 206; no redundant Range verification.
- **R2 owner questions folded:** merge conversion/envelope decisions; state both Chrome-upgrade policy costs. No round-2 findings refuted.
- **R3 (coordinator-applied, critic verdict "ready for owner review"):** AM-2 row rewritten (scratch `OBED_EDOM_OUTPUT_ROOT`, `export_html_fn` seam, runnable on the slide-4-skipped copy; controls stay in AM-1); Chrome-155 freeze wording pinned to the knowledge-mode `snap` grant.

## OWNER QUESTIONS

1. **Conversion policy:** auto-convert any structurally verified, silent ProRes 4444 with real alpha, without size/duration caps, matching opaque conversion today—or ask the operator first?
2. **Quality/budget:** accept CRF 20 subject to eye review, or specify different quality, size or preparation-time limits? Measured: **246,543 B versus 6,524,302 B**, alpha MAE **0.0697/255**, p99 **2**, partial-band p99 **12**. Preparation time and colour/halo acceptance remain unmeasured.
3. **Output priority:** allow a Chrome-only initial release if CEF fails, or require managed-OBS physical fill/key before release? Neither product path is qualified yet.
4. **Unqualified outputs:** adopt the proposed fail-closed VP9 start policy, including empty/unreadable census cases, or explicitly retain warning-and-proceed behaviour?
5. **Chrome upgrades:** mode-based support means alpha can play on an unqualified engine after a silent update; a qualified Chrome-major list blocks alpha until requalification. Which policy? Placement already uses the latter, so Chrome **155.0.8059.79** lacks the **154** freeze grant. OBS remains pinned **32.2.2**.
6. **Interim eye copy:** use an owner-made Desktop copy with slide 4 skipped for AM-3/AM-4, or defer those gates until text-identity repair? The copy would not satisfy full-current-F2 completion.