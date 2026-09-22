# DSK template optional — review rounds (PR #204, 2026-09-22)

Scope: settings.json template memory; Preview builds off the DSK generator + History DSK card;
finished-deck card; DSK template optional with donor order wall deck → reference deck → template.

## Round 1 — Opus (Agent, model opus)
| # | Finding | Disposition |
|---|---|---|
| 1 | Assembler `layout_template=None` guard checked "any name", text path needs every name | Fixed: per-name ownership check in `assemble_dsk_deck` |
| 2 | In-flight GET could clobber a completed PUT in `useStoredTemplate` | Fixed: write generations (per field after Codex r1) |
| 3 | Migration PUT failure discarded fetched settings | Fixed: migration has its own catch returning the fetched values |
| 4 | Failed-PUT rollback restored `null`, blanking the sibling field | Fixed: field-scoped rollback |
| 5 | Apply-time override silently discarded when tier 1 resolves | Fixed: explicit override validated and honoured |
| 6 | Reference tier swallowed every refusal; unreadable reference → 500 | Fixed: catch narrowed to `(ValueError, OSError, KeyError, BadZipFile)`; a wall-deck refusal resurfaces from the template tier |
| nit | `export_slide_clips` still falls back to `DEFAULT_LAYOUT_TEMPLATE` when given `None` | Left: harmless (import guarded by `if blackLayoutName is ""`), CLI callers rely on it |

## Round 2 — Codex GPT-5.6 Sol (`codex-r1.md`)
| # | Class | Finding | Disposition |
|---|---|---|---|
| 1 | new, blocking | Run always sent the remembered template as an override, defeating tiers 1–2 | Fixed: override sent only when the template changed after the proposal (`templateOverride` ref) |
| 2 | new | Legacy localStorage key kept when settings.json wins → resurrects after Forget + reload | Fixed: key removed when the fetched value wins |
| 3 | closed class | Rollback while first GET pending still blanked the sibling | Fixed: per-field generations, field-scoped commit/rollback, GET merges only unwritten fields |
| 4 | edge | Out-of-order PUT completions | Fixed: per-field generation gate; test for reversed completion |
| nit | | `test_dsk_assemble` no-template test only checks the script, not the ownership guard | Left: guard needs a real `.key`; covered by the `@pytest.mark.deck` suite when decks are present |
| nit | | Continue in Exporter test checks the callback, not `DskTab` | Left |

## Round 3 — Codex GPT-5.6 Sol, second pass (`codex-r2.md`), after the tier-1 live run
| # | Class | Finding | Disposition |
|---|---|---|---|
| 1 | closed class (claimed) | An explicit override on a tier-1 proposal is stored but the name-deduped import keeps the wall-owned `Blank Black` | Left, pre-existing by design: `layout_import_lines` has always kept a layout the deck owns (plan §3 dedupe rule); a replace mode is out of scope. The stored path is the validated donor, not a promise it was imported |
| 2 | closed class | `templateOverride` set only after the PUT resolved; a Run in that window used the proposal's donor | Fixed: override set optimistically before the save, reverted on failure. Sub-tab switch dropping the override is the conservative outcome (proposal donor) and left |
| 3 | new / edge | v2 apply bumped the review revision before validating the override, so a 400 left the browser's revision stale (409 on retry) | Fixed: override validated before `_save_v2_dsk_review`; test asserts revision unchanged |
| 4 | closed class / edge | Reversed PUTs or a migration PUT after an explicit choice could persist the older value | Fixed: template writes serialized through one tail; migration skips fields written since the fetch began |
| 5 | edge | Rollback after a failed write restored blank instead of the value the fetch found | Fixed: rollback restores the last server-known value |
| nits | | script-only assembler test; callback-only Exporter test | Left (as round 2) |
