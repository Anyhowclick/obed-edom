# Dashboard preview: draw Magic Move leaves at Keynote's opacity

**IMPLEMENTED — merged #235 (`2a2ce095`, 2026-09-25).** **Follow-up:** the hand-back geometry fix (R6–R8, `keynote_live_handback_geometry.plan.md`, decision 4a)
is appended to the same tuple, so the preview gets it through `patch_rendering` with no preview change. **APPROVED (owner, 2026-09-25): decisions 1–3 as recommended.** Base note: the parent branch gained a fifth
replacement (`0f6d0380`, synchronous DOM hide at the GL handover); the split must carry every `_MM_OPACITY_REPLACEMENTS` entry.

**DRAFT rev 1**, 2026-09-25, Opus planner. Plan only: no product code, no commits, no browser, no Keynote.
Branch `claude/preview-mm-opacity`, stacked on `claude/mm-translucent-opacity` @ `66567617` (parent PR, not yet merged).
Line numbers are read on `66567617`.
Parent: `keynote_live_mm_opacity.plan.md` §0 (root cause), §1 (semantics), §3 (R1–R4), §13 "Follow-up (owner 2026-09-25)".

## 0. Goal

The live host serves `patch_player(stock, mm_opacity=True)`: slot 4 of the P2 1→2 move draws at α 0.2947, like Keynote.
The dashboard preview serves the stock `main.js`, so the author sees the square opaque during the move. Make the preview serve
the same **rendering** bytes (R1–R4) without the live observation hook, and never break the preview on another player version.

## 1. How the preview serves an export today

- **Build.** `POST /api/html-preview` → `propose_preview` (`html_preview.py:936`); `POST …/apply` → `apply_preview` (`:985`)
  exports into `.html-preview/<cache_key>/html/` and writes `manifest.json` (`:1024–1031`).
- **Cache key.** `cache_key(digest) = "<sourceDigest>-p{PARSER_VERSION}-r{RENDERER_CONTRACT_VERSION}"` (`:164–166`);
  `MANIFEST_VERSION = 2` (`:30`), `PARSER_VERSION = 3` (`:31`), `RENDERER_CONTRACT_VERSION = 1` (`:35`, the export/hash-channel
  contract, not the player bytes).
- **Player digest.** `manifest_from_export` stores `playerDigest = file_sha256(export_root / PLAYER_JS)` (`:686`, `:581`).
  `load_cached` reuses a cache only if the **on-disk** `main.js` still hashes to it (`:866`). Nothing else in the preview reads
  it.
- **Serve.** `GET /api/html-preview/{job_id}/player/{rel_path}` (`web/app.py:984–1008`): `registered_export_root` +
  `safe_export_file`; `index.html` goes through `inject_player_diagnostics` (`html_preview.py:115`, a first `<script>` that
  postMessages `{source:"obed-edom-preview", label}`) with `Cache-Control: no-cache`; everything else, `main.js` included, is a
  `FileResponse` with no `Cache-Control` (`app.py:1003`).
- **Other readers of the same on-disk `main.js`, all of which need the STOCK bytes:**
  - `web/live.py:211–214`: live start refuses unless `sha(disk main.js) == PLAYER_SHA256 == manifest.playerDigest`;
  - `live_host.py:1062–1066`: reads disk `main.js` and applies `patch_player`; `_AssetServer` serves the result (`:339`);
  - `html_alpha_probe.py:2985–3024`: copies an export and refuses a changed `main.js` (paint oracle, stock by design).

## 2. The change

### 2.1 `live_runtime.py`: split the rendering replacements out

- New private `_apply_mm_opacity(player: bytes) -> bytes`: the existing loop (`live_runtime.py:138–144`), same two count
  checks, same messages.
- New public `patch_rendering(player: bytes) -> bytes`: the same sha pin as `patch_player` (`:128`), then
  `_apply_mm_opacity`. No `_ANCHOR`, no `_INSTALL`. Raises `LiveRuntimeUnsupported` (its sha message names the preview, not
  "live output").
- `patch_player` keeps its signature, check order (sha, anchor, hook) and messages; its tail becomes
  `return _apply_mm_opacity(patched) if mm_opacity else patched`. Output byte-identical both ways (§5 T1, T1b).
- Move `MM_OPACITY_ENV = "OBED_LIVE_MM_OPACITY"` from `live_host.py:46` to `live_runtime.py`; `live_host` imports it, so
  `live_host.MM_OPACITY_ENV` still resolves (`tests/test_live_host.py:2519`). Needed because `html_preview` must not import
  `live_host` (which imports `html_preview`, `live_host.py:33`).

### 2.2 `html_preview.py`: one serve helper

- `preview_player(stock: bytes) -> tuple[bytes, str]`, mode in `on | off | unsupported | invalid`:
  - env `OBED_LIVE_MM_OPACITY` trimmed and lower-cased; `off` → stock, `off`; empty or `auto` → `patch_rendering(stock)`, `on`;
  - `LiveRuntimeUnsupported` → stock, `unsupported`; any other env value → stock, `invalid` (live refuses it at start,
    `live_host.py:1041`; the preview never refuses).
- Imports `live_runtime` only (it imports nothing but `hashlib`), so the "no `web.*`" rule (`html_preview.py:5`) holds.

### 2.3 `web/app.py`: serve at request time

- In `html_preview_player`, when the resolved file is `root / PLAYER_JS` (compare resolved paths, not the raw string), return
  `Response(bytes, media_type="text/javascript", headers={"Cache-Control": "no-cache", "X-Obed-Mm-Opacity": mode})`.
- For `index.html`, when the player's mode is `unsupported` or `invalid`, pass a note to `inject_player_diagnostics` (new optional
  `note` kwarg; the script calls `send("preview", note)` once). It surfaces in BuildPreview's existing "Player issues" line
  (`dashboard/src/components/BuildPreview.tsx:247–250`, `:435`). `on`/`off` add nothing. Decision 2.
- Cost per `main.js` request: one sha256 + four `bytes.replace` on ~2.3 MB. The implementer measures it; only if > 50 ms add a
  single-entry cache keyed by the stock sha.

### 2.4 Why serve time, not cache-build time

- Writing patched bytes into the cache would break live start (`web/live.py:212` sha check), make `live_host` refuse
  (`patch_player` sha pin) or double-patch, and trip the paint oracle (`html_alpha_probe.py:3024`). The cache stays stock.
- Serve time makes the switch take effect on the next page load with no re-export (no Keynote launch).

### 2.5 Cache and manifest: no version bump

- The cache content, the manifest and `playerDigest` are unchanged (still the stock sha), so `MANIFEST_VERSION`,
  `PARSER_VERSION`, `RENDERER_CONTRACT_VERSION` and `cache_key` stay. Every existing cache is served patched on its next load.
  A bump would force a Keynote re-export of every cached deck for no gain.
- The parent note (§13) says `player_digest` should "key on the served bytes". Not needed: the served bytes are a pure function
  of (stock sha, env), and the stock sha is already pinned. The mode is reported per response instead.
- Residual: a browser that fetched `main.js` before the upgrade (old `FileResponse`, no `Cache-Control`) may reuse it by
  heuristic freshness for the same job URL (jobs persist, `web/jobs.py:243`). One reload clears it; new responses carry
  `no-cache`.

### 2.6 Stays stock

- `html_alpha_probe.py`: untouched; it reads files, never the app route.
- `live_continuity.py`, `web/live.py`: read disk bytes through `safe_export_file`; untouched.

## 3. Off switch

Reuse `OBED_LIVE_MM_OPACITY` (`off | auto`, default `auto`), read per request. One knob keeps preview and program output in
parity, which is the point of this change. Decision 1.

## 4. Dashboard UI impact

None in TS. The front end reads no player bytes, `playerDigest` or manifest version for the preview (`dashboard/src/api.ts:405–443`
types; `htmlPreviewPlayerUrl` builds the URL only). `dashboard/src/live/api.ts:15` `playerDigest` is the live session identity,
still the stock sha. The unsupported note (§2.3) reuses the existing postMessage channel.

## 5. Tests

Before editing, record on `66567617` `sha256(patch_player(real, mm_opacity=True))` and `(…, False)` for T1b.

- **`tests/test_live_runtime.py`**
  - T1 (synthetic, `_pin`): `patch_player(p, False) == _hook_only(p)` (existing); `patch_player(p, True) ==
    _hook_only(patch_rendering(p))`; `patch_rendering(p)` contains no `_INSTALL` bytes.
  - T1b (REAL-gated, `_real_player`): both `patch_player` shas equal the pre-refactor constants; `node --check` passes on
    `patch_rendering(real)`.
  - T2: `patch_rendering` refuses an unknown sha and a missing/duplicated anchor or non-unique replacement (parametrise the
    existing cases, `:194`, `:206`, over both functions).
  - T3 (REAL-gated, Node): the existing extracted-methods run (`_run_extracted`, `:279`) on `patch_rendering(real)` gives
    `[1,1,1,1,α]` at p = 0 and `[1,0,1,1,α]` at 0.5 and 1, as on the live bytes.
- **`tests/test_html_preview.py`**: `preview_player` modes: pinned synthetic → `on` and patched; unknown sha → `unsupported`,
  stock bytes; env `off` → stock; env `bogus` → `invalid`, stock.
- **`tests/test_html_preview_api.py`** (fake export with a synthetic pinned player via `monkeypatch` of
  `live_runtime.PLAYER_SHA256`):
  - served `main.js` equals `patch_rendering(disk)`, header `X-Obed-Mm-Opacity: on`, `Cache-Control: no-cache`;
  - env `off` → stock bytes, `off`; the existing fake player (`/* keynote player */`, unknown sha) → stock, `unsupported`, and
    `index.html` carries the note; `on` → no note;
  - after serving, the on-disk `main.js` still hashes to `manifest.playerDigest`, and a second `propose` reuses the cache
    (`reused: True`): the cache is neither invalidated nor rewritten.
- **Headless preview check: none.** T1 proves the preview's rendering bytes are exactly live's minus the hook, and MO-1
  (parent gate record) measured those bytes at α in headless Chrome; T3 re-runs the patched methods on the preview bytes
  without Chrome. A preview-route Chrome run would need a new driver, since `scripts/mm_opacity_probe.py` drives
  `LiveOutputHost`. Decision 3.
- **Full local suites** (no CI): `uv run pytest tests/ -n auto --dist loadfile`; in `dashboard/`: `npm run test:ui`,
  `npm run test:maps`.

## 6. Docs

- `README.md` Build Preview section (~:57): one sentence: the preview draws Magic Move opacity as live output does;
  `OBED_LIVE_MM_OPACITY=off` turns it off for both.
- Parent plan §13 follow-up bullet: point to this plan.

## 7. Owner decisions

1. **Off switch.** Reuse `OBED_LIVE_MM_OPACITY` for the preview (**recommended**: one knob, parity) / none / a separate env.
2. **Unsupported player.** Serve stock and show one "Player issues" note in the preview (**recommended**: visible, zero TS) /
   serve stock with the response header only / refuse the preview (not recommended: breaks previews on other Keynote versions).
3. **Headless preview check.** None; rely on T1 byte identity + T3 + parent MO-1 (**recommended**) / a report-only headless
   Chrome run on the preview route after the OBS run finishes.

## 8. Work stream

- One implementer (Opus MEDIUM, per the delegation rule). Files: `live_runtime.py`, `live_host.py` (import move only),
  `html_preview.py`, `web/app.py`, the three test files, `README.md`, the parent plan bullet. Opus reviewer (owner 2026-09-24: Codex limit low). Only the
  coordinator commits.
- Order: record T1b constants → split `live_runtime` + T1–T3 → `preview_player` + unit tests → route + API tests → docs →
  full suites.
- Stacked on `claude/mm-translucent-opacity`. After the parent PR merges, rebase onto `main`, re-run the full suites, and open
  the PR against `main`. Never merge without the owner.

## 9. Review log

- Opus r1 (code, no written round): nothing blocking. Folded: an unreadable `main.js` keeps `index.html` serving, a
  case-insensitive `main.js` match, `</` escaped in the note, and the shared media type. Left: `index.html` builds the
  full patch to learn the mode (~5 ms).
- Patch cost on the real player is ~5.4 ms per request, so there's no cache. The `patch_player` shas are pinned in
  `tests/test_live_runtime.py`.
- Also fixed in #235: `test_live_continuity_probe.py::…test_a_setup_time_system_exit_stamps_forced_fail` was not
  self-contained (it needed the git-ignored `output/p2-recovery` fixture).
