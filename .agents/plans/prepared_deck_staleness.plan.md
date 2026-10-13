# Prepared-deck staleness — plan (rev 2)

Owner request 2026-10-13: the Live tab must make clear that prepared decks are snapshots and flag a prepared deck whose
source Keynote was edited afterwards (trigger: `Alpha_DSK.key` edited 18:19 after its 17:53 prepare, export `7e3c9301…`).

**Owner decisions (fixed):** detect edits by digest; warning only — Start stays enabled; a yellow-ish **Prepare again**
button; no flag during an active show; no package-directory caching. Planner and implementer read
`.agents/skills/ui-ux-pro-max/SKILL.md` (owner).

**Roster (2026-10-13 override):** plan Codex GPT-6 Astra high + one Astra high critique (r1: 0 blocker/major, 2 medium,
1 low — folded into rev 1); critique r2 Opus 5.5 high (owner: critic's model family differs from the
planner's; 0 blocker/major, 3 medium, 6 low — folded into rev 2); implement Codex GPT-5.6 Sol high; review Opus 5.5 high. Status: planned; implementation
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
- Call `deck_digest(path)` inside `try/except OSError`; it already raises `FileNotFoundError`/`PermissionError` for a missing or unreadable source, so either returns `missing`. No `os.access` pre-check.
- Compare the returned digest with the saved `sourceDigest`: equal → `current`; different → `changed`.

Let `deck_digest()` perform its existing resolution and caching. Add no separate existence check, hash cache, or package traversal.

In `live_router.decks()` and `live_router.qualification()`, add:

```text
sourceState: "current" | "changed" | "missing"
sourcePath: recorded result.path, or null when absent/null/empty
```

Use `Path(source_path or "")` in the existing name expressions so a null path cannot raise `TypeError`.

Accepted cost (owner: no package caching): right after an edit, `/decks` and qualification may both hash the edited `.key` once; a package `.key` is walked in full on every call.

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

**Give the deck list its own effect (smallest race fix):**

- Move the deck request and the initial-selection logic out of mount-time `loadChoices()` (which keeps display loading/selection) into a dedicated effect keyed `[active, client, jobId, qualificationAttempt]`.
- It returns early when `active` (no `/decks` hashing at show start or mid-show), sets a `cancelled` flag in its cleanup, and ignores cancelled responses; list failures go to the existing message UI.
- Initial selection is unchanged: while `selectionTouched.current` is false, preserve a valid selected ID or pick `nextDecks[0]?.previewJobId || ""`. Later responses only replace rows; `selectDeck()` stays authoritative.
- Leave the qualification effect unchanged.

Effect cleanup drops a superseded response, so a slow earlier list cannot overwrite a newer one.

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

> This Keynote was edited after this deck was prepared. This deck still plays the old version. Save and close Keynote, then prepare again to pick up the edits.

The native button has `type="button"` and label **Prepare again**. `tone-alt` makes the button yellow using existing styles; no CSS changes are needed.

For `missing`, render a neutral `p.note.path-note`:

> Original Keynote not found or can't be read at {sourcePath} — can't check for edits.

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

Disable **Prepare again** for `active || pending || checking || preparing` (a `changed` deck always has a path; keep only the TypeScript null narrowing in the click handler). Pass the corresponding external lock to `LiveDeckInput`; its existing working guard prevents duplicate preparation. Active sessions already unmount setup.

Preparation success selects the returned job ID, triggers qualification, and refreshes the list. Preparation failures use the existing error UI; the expected one is apply's 409 "Close Keynote before exporting…" when Keynote is still open. Failure end state (accepted, no extra state): `onPrepared("")` has deselected the deck, so the warning is gone and Start is disabled; the operator retries with **Qualify Keynote** (the path stays in the file well) or re-picks the deck.

Clicking the button unmounts it (`onPrepared("")` clears qualification); `preparePath` moves focus to the progress paragraph (give it `tabIndex={-1}`) so keyboard focus is not dropped to `<body>`. Start keeps its existing preparation/session/output checks; `sourceState` never enters its eligibility condition.

Replace only the copy sentence in the existing explanatory paragraph with:

> A prepared deck is a snapshot: editing the Keynote afterwards does not update it. Prepare it again after edits.

### 5. Minimal tests and documentation

**`tests/test_live_api.py`**

Add one parametrized `test_prepared_deck_source_state`, reusing `client_for`, with five cases:

- Current source.
- Edited source.
- Missing file.
- Digest raises `PermissionError`.
- No recorded path.

Use a temporary source and real digest for current/changed (the session-wide `OBED_EDOM_CACHE_DIR` from `tests/conftest.py` already isolates the sidecar). Warm the original digest before editing; no separate cache-internals assertions.

Assert both endpoints’ `sourceState`/`sourcePath`, and successful qualification with `qualified: true`; assert a successful start once, in the `changed` case only. Update the existing exact qualification-response assertion. Existing baseline tests remain responsible for sidecar internals and symlink convergence.

**`dashboard/tests-ui/live-presenter.ui.test.tsx`**

Update existing typed fakes with the required fields. Add one scenario using the existing preview mocks:

1. Load a `changed` deck: assert the option suffix, warning text, `notice warning`, the button’s `tone-alt` class, and Start enabled.
2. Click **Prepare again**; assert `startHtmlPreview(sourcePath)`, no chooser call, and conditional apply through the existing flow. Hold preparation pending long enough to check that Start and intake controls are disabled.
3. Complete with a different job ID. Assert that ID is selected and qualified even when the older row remains first.
4. Select a missing-source row; assert the neutral path note and absence of the changed warning.

Keep initial auto-selection covered by the existing start test. Do not duplicate cache-ready and preparation-error tests.

**Documentation**

- `.agents/skills/obed-edom/SKILL.md`: extend the existing Live qualification bullet (it lists the response keys) with `sourceState`/`sourcePath`, snapshot semantics, re-preparation and warning-only behavior; no separate line.
- `README.md`, **Alpha Keynote experiment**: add a short operator paragraph explaining saved snapshots, the yellow warning/button, and the missing-source note. Describe freshness checks on loading/selecting/qualifying; do not imply continuous monitoring.

### 6. Verification

From the repo root:

```bash
env -u PYTHONDONTWRITEBYTECODE UV_PYTHON=3.12 uv run pytest tests/ -n auto --dist worksteal
env -u PYTHONDONTWRITEBYTECODE UV_PYTHON=3.10 uv run pytest tests/ -n auto --dist worksteal
cd dashboard && npm install && npm run build && npm run test:ui && npm run test:maps
```

Confirm fixture-backed tests have their required worktree fixtures. Restart the dashboard after building, then visually check the yellow warning and button, keyboard focus after **Prepare again** (lands on the progress text), the Keynote-still-open failure end state, preparation feedback, and wrapping of a long missing-source path at a narrow viewport.

Keep implementation comments minimal; add no new abstractions beyond the source-state helper and preparation handle.