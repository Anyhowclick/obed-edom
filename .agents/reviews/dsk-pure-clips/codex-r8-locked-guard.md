Clean.

The shared delete block preserves valid `try` nesting, keeps genuine delete failures under the existing `DELETEFAIL` handler, and leaves image/placeholder behavior unchanged. Both export branches use `_delete_block`.

Validation:

- Exact group/image deletion blocks compiled successfully with `osacompile`.
- Four relevant string-generation tests passed via direct invocation.
- Full pytest execution was unavailable because the read-only sandbox cannot create its required temporary directory.