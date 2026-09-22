Blocking: **yes**—the apply flow can violate the donor hierarchy.

## Spec

1. **New class — blocking** — [DskGenerator.tsx:224](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/tabs/dsk/DskGenerator.tsx:224), [DskGenerator.tsx:230](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/tabs/dsk/DskGenerator.tsx:230)

   Run always sends the remembered template as an explicit override. If Propose selected tier 1 (no donor) or tier 2 (reference donor), merely having a remembered template silently replaces that selection with tier 3.

   **Exact fix:** “Do not send `dskTemplate` on Apply by default. Track template changes made after the proposal separately and send an override only when the operator explicitly changes it during review.”

   The test at [dsk-generator.ui.test.tsx:239](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/tests-ui/dsk-generator.ui.test.tsx:239) passes for the wrong reason by positively asserting the unconditional override. Add tier-1 and tier-2 cases with a remembered template.

2. **New class** — [prefs.ts:195](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:195)

   A legacy localStorage key is removed only when imported. If settings.json already contains a value, the stale key remains; after Forget and reload, it resurrects the obsolete template.

   **Exact fix:** “When the fetched settings value wins, delete the corresponding readable legacy key immediately. When migration requires PUT, delete it only after that PUT succeeds.”

   [dsk-generator.ui.test.tsx:211](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/tests-ui/dsk-generator.ui.test.tsx:211) should assert removal and verify Forget plus refresh does not restore it.

## Standards

3. **Closed class** — [prefs.ts:220](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:220), [prefs.ts:258](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:258)

   The sibling-preserving rollback still fails when PUT rejects while the initial GET is pending. `previous` is `NO_TEMPLATES`; the generation guard discards the fetched sibling, then rollback restores both fields blank.

   **Exact fix:** “Retain or await the fetched baseline before taking the rollback snapshot, or roll back only the written field while preserving values learned from GET.”

   [stored-file-sync.ui.test.tsx:111](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/tests-ui/stored-file-sync.ui.test.tsx:111) waits for GET first, so it does not cover the claimed fix.

4. **Edge case** — [prefs.ts:258](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/src/prefs.ts:258)

   Concurrent PUT responses can commit or roll back out of order and overwrite a newer same-field or sibling update.

   **Exact fix:** “Serialize template writes, or gate commits and rollbacks by per-field generation and merge only the affected field. Add reversed-completion success/failure tests.”

## Minor nits

- [test_dsk_assemble.py:152](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/tests/test_dsk_assemble.py:152) claims to test FW ownership but only builds a script using a nonexistent deck; it never exercises the assembler’s alpha-safe ownership guard.
- [dsk-generator.ui.test.tsx:501](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/dashboard/tests-ui/dsk-generator.ui.test.tsx:501) tests a callback, not the actual `DskTab` transition.
- [app.py:2208](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/dsk-generator-template-memory-9b60ba/src/obed_edom/web/app.py:2208) catches every `Exception`, potentially disguising programming defects as reference-deck fallback.

Summary: **2 Spec findings, 2 Standards findings; the unconditional apply override is the blocking issue.**