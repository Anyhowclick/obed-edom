# Alpha Keynote live: one-shot movie warm-up at deck load

**r3 · 2026-10-16 · implemented and merged into `claude/stage-b-arch` (#295, `19cb4eae`)**

Acceptance numbers: `.agents/reviews/movie-warmup-2026-10-16/acceptance-record.md`.

## Review log
- **Plan r1:** GPT-6 Astra high planner.
- **Critique r1** (Opus 5.5 high): NOT READY.
  - Blocker: the suite commands would wipe the `.venv`.
  - Mediums: the ordering rationale was overstated (pre-core injection is evidence hygiene, not retention); the
    plan was over-built; gate discipline was missing.
  - Lows: URL derivation, invalid env value should raise, honest hash test.
  - All folded into r2.
- **Critique r2** (Opus 5.5 high): NOT READY on stale r1 text only; design confirmed. Folded into r3, a clean
  rewrite (pinned-worktree A5, mandatory snapshot readiness field, Node test included, `None` paths).
- **Implementation:** Codex GPT-5.6 Sol high (`41800609`).
- **Code review r1** (Opus 5.5 high): APPROVE.
  - Five LOW findings folded: pin the embedded URL literal, log after the codec census, guarded observe log,
    simpler readiness check. A fifth, extra env hygiene in `host()`, was kept as is.
- **Acceptance:**
  - A1 pass; A2 pass (212 → 17 ms); A4 pass (282 → 60 ms).
  - A3 unscorable on the base (`47bc3698` starts paint at decode).
  - A5: on/off gate rounds identical bar flakes. Suites pass bar a timing flake, since fixed on the base.
  - Revalidated after the rebase onto `7746df27`.

**This file is self-contained. Nothing in r1 applies unless it is restated here.**

Line references are to `be37fb01`. `live_host.py`, `live_continuity*.py` and `test_live_host.py` are unchanged on
`claude/stage-b-arch` `cf5099d5`.

## 1. Goal and evidence

- **Owner decision (2026-10-15):** ship a best-effort, one-shot movie warm-up at deck load; no faststart.
  Evidence is in `.agents/handovers/f4-faststart-measure-2026-10-15.md`.
- **Cause:** the first movie a page mounts pays a one-time media-pipeline start. Keynote's poster shows meanwhile.
- **Measured shape:** `output/evidence/stage-b-2026-10-13/f4-faststart/warm-load/index.html`.
- **Measured effect:**

  | output | without warm-up | with warm-up |
  |---|---|---|
  | managed OBS, first session | 280 ms (14 frames) | 56 ms (3 frames) |
  | headless, real player | 214 ms | 28 ms |

- The benefit holds 3 min after release.
- Any H.264 file warms the pipeline.

The warm-up must:
- never fail or delay a session;
- stay invisible and silent;
- release its decoder;
- change no export bytes, player pins, plan signatures or `main.js`.

## 2. Design

### 2.1 Where it is injected
- `_AssetServer._program_html` (`live_host.py:615-643`) injects `overlay + continuity_script + fit_script` after
  `<body>`.
- Add `movie_warmup_script` and inject `overlay + movie_warmup_script + continuity_script + fit_script`.
- Every output mode (headless, headful, managed OBS, external attach) serves this page through one
  `server_factory`/`goto` site in `start()` (`:1694-1700`).
- Inline scripts run in order before the synchronous `main.js`, so the warm-up starts before the player and before
  the continuity core.
- It is not part of `continuity_script`, which is empty when no runtime plan derives (`:1689-1693`). The warm-up
  applies whenever the deck has an H.264 movie.

**Why before the core:** this is evidence hygiene, not retention.
- Core would not pool a warm element. It has no `*-video` id, so `instanceOf` is null and `nextEntry(null)` is null
  (`live_continuity_js.py:409-410, 430-432`). That makes `poolable` false (`:766-769`). `stash` then returns and
  `origRemove` runs (`:2400-2407`).
- Created after the core, though, the `createElement` hook would:
  - `tag()` it, consuming `nextId` and shifting every player video's `__obedElId` (`:756-759`, `:2567`);
  - add a `createElement-video` note (`:2569`);
  - make the `src` setter `reidentify` it.
- The script also captures `Element.prototype.removeAttribute` and `HTMLMediaElement.prototype.load` at parse time
  and releases through them.

### 2.2 The script
`_movie_warmup_script(url: str) -> str` returns one `<script>` IIFE. It:
- captures `removeAttribute` and `load`;
- creates a detached `video`, sets `muted = defaultMuted = true` and `preload = "auto"`, adds its listeners, then
  sets `src` and calls the captured `load`;
- never appends it, never calls `play()`/`pause()`, never seeks.

One idempotent `finish(state)`:
- clears the timer and listeners;
- calls the captured `removeAttribute("src")` then the captured `load()`, each guarded;
- drops the reference.

| trigger | state |
|---|---|
| `loadeddata` | `"ready"`, with `readyMs` measured from warm-up start |
| `error` | `"error"` |
| 5 s `setTimeout` | `"timeout"` (resource cleanup only, not a readiness deadline) |

- It sets `window.__obedMovieWarmup = {state, readyMs}`: scalars only, `state` starting at `"loading"`.
- The whole body sits in try/catch. No retry, sentinel or `pagehide`: a served inline script runs once per document.
- The URL is embedded as `json.dumps(url).replace("</", "<\\/")`, as `_continuity_plan_script` does
  (`live_host.py:186-207`).

### 2.3 Which movie
In `live_continuity.py`, beside `_referenced_movies` (`:2702-2732`):

```python
def first_h264_movie(export_root: Path, slides: list[dict[str, Any]], *, resolver: Callable[[Path, str], Path] = safe_export_file,
                     probe: Callable[[Path], str | None] = movie_codec) -> tuple[str, Path] | None:
```

- Iterate `_referenced_movies` keys, which are in slide order with skipped slides excluded (`:2710`), then each
  key's paths in order.
- Skip `None` paths (as `codec_report` does, `:2757`).
- Return the first `(asset, path)` whose `codec_family(probe(path)) == "h264"`. Catch per-file errors.
- Do not use `codec_report`, which is alphabetically sorted and aggregates copies.
- **Non-H.264 decks** (VP9-only, HEVC-only): skip.
- **Mixed decks:** warm the first H.264 movie.
- No `_codec_supported` intersection is needed: `_codec_supported("h264")` is always True (`live_host.py:230-231`).

**URL:** `quote(path.resolve().relative_to(export_root.resolve()).as_posix(), safe="/")`.
- This handles `/var` vs `/private/var` and the test resolver's unresolved paths.
- The handler unquotes before the resolver (`:475-491`).

### 2.4 Host wiring (`live_host.py`)
- **Env switch:** `MOVIE_WARMUP_ENV = "OBED_LIVE_MOVIE_WARMUP"`, values `off|auto`, default `auto`.
  - Parse it with the neighbours at `:1629-1649`, before any resource starts.
  - An invalid value raises `LiveHostError("OBED_LIVE_MOVIE_WARMUP must be off or auto.")`, matching
    GL_REPLAY/MM_OPACITY/MM_FEED.
- **`_resolve_movie_warmup(self) -> str`:**
  - called in `start()` right after `_resolve_codecs()` (`:1665`);
  - catches every exception and returns `""`;
  - logs one `movieWarmup` record: `preference`, `asset`, `url`, `reason` (`off` | `no-h264` | `error` | `None`);
  - passes its result as `server_factory(..., movie_warmup_script=...)`.
- **`_LIVE_SNAPSHOT_EXPR`** (`:102-107`): add one guarded copy, mirroring the mm_feed block:
  `try{var w=window.__obedMovieWarmup;if(w&&typeof w==='object')o.__obedMovieWarmup={state:w.state,readyMs:w.readyMs}}catch(x){}`.
- **`observe()`** (`:2791-2806`):
  - when `__obedMovieWarmup.state` is terminal and `self._movie_warmup_logged` is False, log `movieWarmup`
    `{state, readyMs}` once and set the flag;
  - reset the flag in `start()`;
  - malformed values are ignored.
- No other public fields and no UI change.

### 2.5 Unchanged
- `live_runtime.py`, `patch_player`, `main.js`, and the continuity/GL replay/mm_feed JS.
- Codec parsing, manifests, media, and the dashboard.
- Build Preview: `web/app.py` serves its own player, not `_program_html`.
- The refactor-owned files and their tests:
  - `scripts/live_continuity_probe.py`, `mm_feed_instrument.py`, `live_evidence_contract.py`, `paint_instrument.py`;
  - `scripts/managed_obs_qualify.py`, `run_gates.sh`, `binary_counter_movie.py`, `obs_cadence_decode.py`.
- **Isolation:** pre-navigation instruments hook only `play`/`pause`/`getContext`/WebGL. The samplers use
  `querySelectorAll('video')`, which never sees a detached element.

### 2.6 README
- One short paragraph near the live continuity controls (`README.md` ~98, ~261-284).
- It covers: one warm-up at deck load, H.264 only, independent of continuity, `OBED_LIVE_MOVIE_WARMUP=off` to
  disable, a residual 1–3 frames remains.

## 3. Tests
New tests are kept to the minimum.

1. **`test_live_continuity.py`: one parametrized `first_h264_movie` test**, using the existing census fixture
   patterns (~1956-2076). Cases:
   - slide order beats alphabetical order;
   - a skipped slide;
   - a `None` first copy with a valid second copy;
   - a first key that is non-H.264 while a later key is H.264;
   - no H.264 → `None`.
2. **`test_live_host.py`: extend, don't add.**
   - `FakeServer.__init__` (`:155-157`) accepts and stores `movie_warmup_script`.
   - `host_with_continuity` (`:1430-1432`) adds `monkeypatch.delenv(live_host.MOVIE_WARMUP_ENV, raising=False)`.
   - **Injection-order test (`:1745-1763`):** assert the warm-up tag sits after the overlay and before the
     continuity core and the player, and carries the quoted URL. Include one filename with a space and `%`.
   - **`test_continuity_off_env_installs_nothing` (`:1446-1453`):** assert `output._server.movie_warmup_script`
     contains the URL. This proves the warm-up is independent of continuity.
   - **Invalid env:** parametrize `test_invalid_gl_replay_env_refuses_before_starting_resources` (`:3135-3144`) over
     `(env, message)` and add `MOVIE_WARMUP_ENV`.
   - **Historical hash test (`:1920-1937`):** set `MOVIE_WARMUP_ENV=off` and forward
     `movie_warmup_script=output._server.movie_warmup_script` when rebuilding `_AssetServer`. Keep the hashes.
     Forward it in `served_html` (`:2641`) too.
   - **One observe case:** a snapshot carrying `__obedMovieWarmup={state:"ready",readyMs:30}` logs once; a repeat
     does not log again.
3. **One Node run**, following the pattern at `:3610-3636`, with a small media/timer stub. It checks:
   - muted is set before `src`;
   - the element is never appended and `play()` is never called;
   - `loadeddata` → release (`src` removed, `load()`), state `"ready"`;
   - a separate timer fire → `"timeout"` plus release;
   - after the script runs, replacing `Element.prototype.removeAttribute` with a throwing spy does not affect the
     release.

## 4. Acceptance

**Machine rules:**
- One heavy job machine-wide; message the linked sessions "need window" before each batch and "done" after.
- Record `uptime` per batch.
- At most 3 headless Chromes.

**Fresh implementation worktree:**
- Run `uv sync --frozen --all-extras --all-groups`.
- Symlink the main checkout's `output/{fixtures,evidence,bank}` and `Sermon Outlines/*.docx` (`SKILL.md:56-58`).
- Rebase on the current `claude/stage-b-arch` before starting.

**Wrappers:**
- They live outside the repo, copied from `output/evidence/stage-b-2026-10-13/f4-faststart/tools/`:
  `run_probe_ab.py`, `run_obs_ab.py`, `coldstart.py`, `obs_coldstart.py`.
- `NO_PREMOVE_CAPTURE=1` patches the exact one-match guard in `scripts/mm_feed_instrument.py:109`. If the
  restructure moved it, adapt only the wrapper.
- Both arms use the **unwarmed** `$FX/html-unmodified/index.html`, where
  `FX="$HOME/Desktop/Convert wall to 16x9 CGs/Continuity/q7-fixtures/Alpha"`.
- The product injects the warm-up; `OBED_LIVE_MOVIE_WARMUP=off|auto` selects the arm.

### A1: unit tests
`env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/test_live_host.py tests/test_live_continuity.py tests/test_live_runtime.py tests/test_live_api.py -q`

All pass, and the Node test runs (not skipped).

### A2: headless real player, 5 + 5 runs, interleaved
```
env PROBE_WT="$WT" NO_PREMOVE_CAPTURE=1 OBED_LIVE_MOVIE_WARMUP=$mode "$WT/.venv/bin/python" "$RUN/tools/run_probe_ab.py" \
  --fixture "$FX/html-player" --original-index "$FX/html-unmodified/index.html" \
  --skip-arms B,C,V,Voff,attach --mm-feed off --artifact "$RUN/headless/$mode-$i.json"
```
Exit 1 is expected while the known b5to6..b7to8 fails stand.

Pass if all of these hold:
- `coldstart.py`: the slide-4 Untitled entry (sampler id1, scene 4) is ≤ ~50 ms median in the `auto` arm, against an
  `off` control that reproduces ~214 ms;
- per-boundary verdicts are identical across arms;
- the run's host session log (`player.output["logPath"]`, under `<preview_root>/live-logs/`) shows `movieWarmup`
  `state: "ready"`;
- the first sampled video is still the player's.

### A3: feed-on paint verdict
- Same command as A2 with `--mm-feed on`, keeping `NO_PREMOVE_CAPTURE=1`.
- Pass if the b3to4 paint classification `not-decoded` is ≤ 3 in each `auto` run, against ~12 in `off`.
- Other verdicts must not change.

### A4: managed OBS, 4 + 4 runs, alternating
The owner's go is required at that time.
```
env PROBE_WT="$WT" OBED_LIVE_MOVIE_WARMUP=$mode "$WT/.venv/bin/python" "$RUN/tools/run_obs_ab.py" --arm feed --launch hidden \
  --fixture "$FX" --out "$RUN/obs/$mode-$i" --home "$RUN/obs-home"
```
Pass if:
- `obs_coldstart.py`: the first session's (`feed`) id1 entry is ≤ ~80 ms in all four `auto` runs, against ~280 ms
  `off`;
- `feed-off` is reported separately, never pooled;
- named gate checks are unchanged across arms;
- `movieWarmup` is `ready` in the host log;
- OBS quits after every run.

### A5: gates, then the full suites
1. **Pin a worktree.** Never run gates from `$WT`:
   ```
   IMPL=$(git -C "$WT" rev-parse HEAD); git -C "$WT" worktree add --detach "$RUN/gate-wt" "$IMPL"
   ```
2. **Default-on round** (load settled, nothing else running):
   ```
   env -u OBED_LIVE_MOVIE_WARMUP GATE_JOBS=3 zsh "$RUN/gate-wt/scripts/run_gates.sh" "$RUN/gate-wt" "$RUN/gates-auto" --tier full
   ```
3. **Comparator:** a full round recorded on the exact rebased base commit, if one exists.
   - Otherwise (expected while `claude/stage-b-arch` moves), or on any named-verdict difference, run the same command
     with `OBED_LIVE_MOVIE_WARMUP=off` into `$RUN/gates-off`, from the same pinned worktree.
   - Compare named verdicts for Alpha_DSK, D7 and D7s. No new changes.
4. **Suites in `$WT`**, never just before a gate round:
   - 3.13: `env -u PYTHONDONTWRITEBYTECODE uv run pytest tests/ -n auto --dist worksteal`
   - 3.10 floor:
     ```
     UV_PROJECT_ENVIRONMENT=$RUN/venv310 uv sync --frozen --all-extras --all-groups --python 3.10
     env -u PYTHONDONTWRITEBYTECODE UV_PROJECT_ENVIRONMENT=$RUN/venv310 uv run --frozen --python 3.10 pytest tests/ -n auto --dist worksteal
     ```
   - Dashboard tests are not needed: there is no frontend change.
5. **Clean up:** remove the gate worktree with `/usr/bin/trash "$RUN/gate-wt"` then `git worktree prune`.

**Completion:** implementation review (Opus 5.5 high; Sol implements) plus A1–A5. WebM stays an open follow-up;
non-H.264 decks skip the warm-up.

## 5. Risks
- **Created after the core,** the warm element would be tagged and noted. Mitigation: pre-core injection and the
  captured `removeAttribute`.
- **Early fetch/decode at load** could contend with a deck whose first slide plays a movie. The output is hidden at
  load and there is no readiness barrier; A5 gates cover the decks we have.
- **Idle beyond 3 min** is unmeasured. There is no periodic re-warm.
- **A suspended renderer** can delay the 5 s cleanup. Document teardown still releases the element.

## 6. Not in scope
- Faststart, re-encoding, media or manifest changes, `main.js` or player-pin changes.
- Per-slide warm-up, persistent or periodic decoders, waiting for warm-up before show.
- A VP9/HEVC warm-up policy and the WebM experiment (follow-up).
- Headful and external-attach smoke runs: the same served HTML is covered by A2 and A4.
- Build Preview, UI, and API or evidence-schema changes.
- Any edit to the refactor-owned files listed in §2.5.
