No BLOCKER found. The mandatory post-write read-back retains all three checks, and production `ValueError` paths name the slide.

- **SHOULD-FIX — new class** — `src/obed_edom/offline_write.py:1439-1458`: One batch `ValueError` refuses every verified slide, inflating `failures`/`zorderRefused` and removing valid slides. The `say` line also mislabels read failures as mismatches.  
  **Exact fix:** “Keep the one-load success path, but on batch `ValueError` fall back to `read_slide_zorder` per slide; fail only slides whose fallback raises and emit `reason=verify read failed: …`. Add a two-slide regression proving one bad slide does not fail the other.”

- **SHOULD-FIX — edge case** — `src/obed_edom/iwa_zorder.py:377`: The batch reader runs when every result is refused—or input is empty—adding an unnecessary full-deck load and potentially replacing a valid all-refused return with `RuntimeError`.  
  **Exact fix:** “Compute the non-refused slide list and call `read_deck_zorders` only when it is non-empty; add an all-refused test asserting the reader is not called.”

- **SHOULD-FIX — new class** — `tests/test_iwa_zorder_write.py:265`: The batch test uses `read_slide_zorder` as its oracle, but that function now delegates directly to the batch function. A shared indexing or extraction defect therefore passes both sides.  
  **Exact fix:** “Assert a literal expected mapping, including distinct `drawablesZOrder` and `ownedDrawables` values, then separately assert the wrapper returns the expected tuple for one slide.”

- **NIT — new class** — `src/obed_edom/iwa_zorder.py:305-309`: The contract docstring incorrectly says read-back uses `read_slide_zorder`.  
  **Exact fix:** “State that all non-refused patched slides are re-read in one `read_deck_zorders` call, retaining the three checks and deck-already-written wording.”

- **NIT — closed class** — `tests/test_iwa_zorder_write.py:258-267`: No test pins the batch API’s preserved load-failure translation.  
  **Exact fix:** “Mock `_load_deck` to raise and assert a chained `RuntimeError` containing the deck path, `_load_deck failed on`, and the `keynote_parser` version hint.”

fix-then-ship