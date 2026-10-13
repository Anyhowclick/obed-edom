# Prepared-deck staleness — plan (rev 1)

Owner request 2026-10-13: the Live tab must make clear that prepared decks are snapshots and flag a prepared deck whose
source Keynote was edited afterwards (trigger: `Alpha_DSK.key` edited 18:19 after its 17:53 prepare, export `7e3c9301…`).

**Owner decisions (fixed):** detect edits by digest; warning only — Start stays enabled; a yellow-ish **Prepare again**
button; no flag during an active show; no package-directory caching. Planner and implementer read
`.agents/skills/ui-ux-pro-max/SKILL.md` (owner).

**Roster (2026-10-13 override):** plan Codex GPT-6 Astra high + one Astra high critique (r1: 0 blocker/major, 2 medium,
1 low — all folded below); implement Codex GPT-5.6 Sol high; review Opus 5.5 high. Status: planned; implementation
2026-10-14.


**One implementation stream.** Compare each prepared deck’s saved source digest with its original Keynote and warn about changed snapshots. Staleness does not change qualification or disable Start.

All paths are relative to the repo root.

### 1. Verified basis and scope

`html_preview.propose_preview`, `apply_preview`, and `_ready_result` retain the original source `path` and prepare-time `sourceDigest`; `web/jobs.py` persists the result. The export uses a scratch copy.

`baseline.deck_digest()` canonicalizes the path and caches regular-file hashes using stat metadata. Several prepared versions of one source compare their own saved digests against its current digest.

No active-show/filebar warnings, start blocking, background polling, preview-pipeline changes, or package-directory caching.

### 2. Server — `src/obed_edom/web/live.py`

Import `deck_digest` from `obed_edom.baseline` and add:

```python
def _source_state(result: dict[str, Any]) -> Literal["current", "changed", "missing"]:
```

Behavior:

- Missing, null, or empty `result.path` returns `missing` before constructing a `Path`.
- Expand the path for a cheap `os.access(path, os.R_OK)` check. Failed access returns `missing`.
- Call `deck_digest(path)` inside `try/except OSError`; a read failure or disappearance returns `missing`.
- Compare the returned digest with the saved `sourceDigest`: equal → `current`; different → `changed`.

Let `deck_digest()` perform its existing resolution and caching. Add no separate existence check, hash cache, or package traversal.

In `live_router.decks()` and `live_router.qualification()`, add:

```text
sourceState: "current" | "changed" | "missing"
sourcePath: recorded result.path, or null when absent/null/empty
```

Use `Path(source_path or "")` in the existing name expressions so a null path cannot raise `TypeError`.

Contain source-read errors inside `_source_state()`: they must neither omit prepared rows nor produce qualification HTTP 409 responses. Keep `prepared_deck()`, `start()`, and `qualified: True` unchanged.

### 3. Types and freshness — `dashboard/src/live/api.ts`, `LivePresenter.tsx`

Add:

```ts
export type LiveSourceState = "current" | "changed" | "missing";
```

Extend `LivePreparedDeck` with required fields:

```ts
sourceState: LiveSourceState;
sourcePath: string | null;
```

`LiveQualification` inherits them.

**Make the existing qualification effect the sole deck-list loader:**

- Remove the deck request and deck-selection logic from mount-time `loadChoices()`; retain display loading and display selection there.
- The qualification effect requests `client.decks()` on initialization and whenever its existing dependencies rerun.
- Perform the deck request even when there is no selected job or output settings are still loading. Guard only the qualification request with the existing `jobId`, output-settings, and inactive-session conditions.
- Handle deck and qualification responses independently, under the same effect cancellation guard. A failure in one must not discard success in the other. Retain existing qualification checking/error behavior; report list failures through the existing message UI.
- On the first accepted list, if `selectionTouched.current` is false, preserve a valid initial ID or select `nextDecks[0]?.previewJobId || ""`. Mark that initial selection decision consumed using the existing ref.
- Later list responses update rows only. `selectDeck()` continues to mark explicit selection/preparation changes and remains authoritative.
- Do not add `decks` to effect dependencies.

This removes competing list writers and prevents delayed responses from older effect runs from overwriting newer rows. It also preserves new-job selection when the old row remains first.

Retain the fallback option for a selected ID absent from the current list.

For changed rows, append:

> · Keynote changed — re-prepare

### 4. Warning and preparation — `LivePresenter.tsx`, `LiveDeckInput.tsx`

Extend `DeckReady` with:

```ts
onPrepareAgain: () => void;
prepareDisabled: boolean;
```

Immediately after the deck name/slide-count paragraph, render the source status inside the existing polite live region.

For `changed`, use:

```text
div.notice.warning
  p: warning text
  div.actions
    button.btn.secondary.tone-alt
```

Warning text:

> This Keynote was edited after this deck was prepared. This deck still plays the old version. Prepare again to pick up the edits.

The native button has `type="button"` and label **Prepare again**. `tone-alt` makes the button yellow using existing styles; no CSS changes are needed.

For `missing`, render a neutral `p.note.path-note`:

> Original Keynote not found at {sourcePath} — can't check for edits.

When no path was recorded:

> Original Keynote path unavailable — can't check for edits.

For `current`, show neither message.

**Reuse the existing preparation owner through a small imperative handle:**

```ts
export type LiveDeckInputHandle = {
  preparePath(path: string): Promise<void>;
};
```

Convert `LiveDeckInput` to the repo’s React 18 `forwardRef` / `useImperativeHandle` pattern. Refactor its existing preparation function to:

```ts
async function prepare(path: string): Promise<void>
```

Both **Qualify Keynote** and `preparePath` call this function.

- Guard empty paths, external `disabled`, and `working.current` before starting.
- Set `working.current` synchronously.
- Set the displayed `ChosenFile` from the explicit path and pass that same path directly to `startHtmlPreview()`.
- Preserve `onPrepared("")`, `onPreparing`, polling, conditional apply, progress, logs, error handling, and `onPrepared(done.id)`.
- Expose the current function through the handle so it observes current disabled props.

`LivePresenter` holds the ref and calls:

```ts
void inputRef.current?.preparePath(qualification.sourcePath);
```

Guard the call when no source path is available. Do not invoke the chooser or pass the old digest.

Disable **Prepare again** for `active || pending || checking || preparing` or an absent source path. Pass the corresponding external lock to `LiveDeckInput`; its existing working guard prevents duplicate preparation. Active sessions already unmount setup.

Preparation success selects the returned job ID, triggers qualification, and refreshes the list. Preparation failures use the existing error UI. Start keeps its existing preparation/session/output checks; `sourceState` never enters its eligibility condition.

Replace only the copy sentence in the existing explanatory paragraph with:

> A prepared deck is a snapshot: editing the Keynote afterwards does not update it. Prepare it again after edits.

### 5. Minimal tests and documentation

**`tests/test_live_api.py`**

Add one parametrized `test_prepared_deck_source_state`, reusing `client_for`, with five cases:

- Current source.
- Edited source.
- Missing file.
- Digest raises `PermissionError`/`OSError` after the access check.
- No recorded path.

Use a temporary source and real digest for current/changed, with `OBED_EDOM_CACHE_DIR` isolated to `tmp_path`. Warm the original digest before editing; no separate cache-internals assertions.

Assert both endpoints’ `sourceState`/`sourcePath`, successful qualification with `qualified: true`, and successful start. Update the existing exact qualification-response assertion. Existing baseline tests remain responsible for sidecar internals and symlink convergence.

**`dashboard/tests-ui/live-presenter.ui.test.tsx`**

Update existing typed fakes with the required fields. Add one scenario using the existing preview mocks:

1. Supply an initial prepared ID and defer the first deck response. Let a newer effect response show `changed`; resolve the older response afterward and assert it cannot remove the stale suffix.
2. Assert warning text, `notice warning`, the button’s `tone-alt` class, and Start enabled.
3. Click **Prepare again**; assert `startHtmlPreview(sourcePath)`, no chooser call, and conditional apply through the existing flow. Hold preparation pending long enough to check that Start and intake controls are disabled.
4. Complete with a different job ID. Assert that ID is selected and qualified even when the older row remains first.
5. Select a missing-source row; assert the neutral path note and absence of the changed warning.

Keep initial auto-selection covered by the existing start test. Do not duplicate cache-ready and preparation-error tests.

**Documentation**

- `.agents/skills/obed-edom/SKILL.md`: add one line near the Live qualification bullet documenting snapshot semantics, source status, re-preparation, and warning-only behavior.
- `README.md`, **Alpha Keynote experiment**: add a short operator paragraph explaining saved snapshots, the yellow warning/button, and the missing-source note. Describe freshness checks on loading/selecting/qualifying; do not imply continuous monitoring.

### 6. Verification

From the repo root:

```bash
env -u PYTHONDONTWRITEBYTECODE UV_PYTHON=3.12 uv run pytest tests/ -n auto --dist worksteal
env -u PYTHONDONTWRITEBYTECODE UV_PYTHON=3.10 uv run pytest tests/ -n auto --dist worksteal
cd dashboard && npm install && npm run build && npm run test:ui && npm run test:maps
```

Confirm fixture-backed tests have their required worktree fixtures. Restart the dashboard after building, then visually check the yellow warning and button, keyboard focus, preparation feedback, and wrapping of a long missing-source path at a narrow viewport.

Keep implementation comments minimal; add no new abstractions beyond the source-state helper and preparation handle.