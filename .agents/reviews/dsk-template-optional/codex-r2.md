## Spec

1. **Closed class — blocking** — [app.py:2218](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/src/obed_edom/web/app.py:2218), [dsk_live.py:425](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/src/obed_edom/dsk_live.py:425)

   An explicit override on a tier-1 proposal is recorded but not actually used. Because the FW deck already owns `Blank Black`, `layout_import_lines` skips importing the override donor. The new test mocks `_run_dsk_apply`, so it verifies only the stored path—not the assembled deck.

   **Exact fix:** “Add an explicit-override assembly mode that replaces or bypasses the existing same-named FW layout and verifies the override donor was used; if replacement cannot be performed safely, return a structured field error before mutating the proposal.”

2. **Closed class — blocking** — [DskGenerator.tsx:88](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/tabs/dsk/DskGenerator.tsx:88), [DskGenerator.tsx:122](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/tabs/dsk/DskGenerator.tsx:122)

   `templateOverride` is component-local and assigned only after the settings PUT resolves. Immediate Run can use the old donor; reversed A/B completions can leave override A while the hook displays B; switching to Exporter and back loses the override entirely. Explicit Forget is also indistinguishable from “unchanged.”

   **Exact fix:** “Persist the proposal-time template candidate separately from the resolved donor, await the latest template write, and derive a tagged `{changed, path}` override from the current successfully saved value.”

3. **New class / edge case** — [app.py:803](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/src/obed_edom/web/app.py:803)

   V2 Apply saves the review and increments its revision before validating the override. A missing or invalid override returns 400 but leaves the browser’s revision stale, so the corrected retry receives 409.

   **Exact fix:** “Validate the review revision and template override without mutation, then persist the merged review and donor in one update; rejected applies must leave revision and result unchanged.”

## Standards

4. **Closed class / edge case** — [prefs.ts:194](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:194), [app.py:260](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/src/obed_edom/web/app.py:260)

   Generations protect only the in-memory cache. Reversed PUTs—or a legacy-migration PUT started after an explicit choice—can persist the older value while the UI displays the newer one.

   **Exact fix:** “Serialize template writes, omit migration fields modified since GET began, lock the backend read-modify-write, and test final GET/file state.”

5. **Edge case** — [prefs.ts:232](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:232)

   If GET discovers `old.key` during an optimistic write and that write fails, rollback restores blank rather than the persisted `old.key`.

   **Exact fix:** “Retain a fetched per-field baseline and restore it when the newest write fails.”

## Minor nits

- The assembler test still checks script text, not the ownership guard.
- The Exporter test still checks only the callback, not `DskTab`.

**Blocking: yes—findings 1 and 2.** Test tallies were accepted as provided; no tests were rerun.