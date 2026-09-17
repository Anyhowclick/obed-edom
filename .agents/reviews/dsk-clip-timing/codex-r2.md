Fold-in is not fully clean: items 1, 3, 4, and 5 are correct; item 2 still has one material edge case.

- Folded item 1 — **OK.** `clips_inserted` is captured from the visually ordered `plan.clips`, remains keyed by FW slide number, and is used by the only `_publish_generator_clips` caller. No crop-`None` lookup remains.
- Folded item 2 — **ISSUE.** Valid clip plans now place After Transition at position 0 and With Build 1 at position 1, but front-loading silently changes existing non-movie build timing.
- Folded item 3 — **OK.** Coverage and duplicate checks run for every clip slide before resolving IDs or invoking either writer.
- Folded item 4 — **OK.** The returned `{out_slide_id: {movie_id: state}}` shape is consumed correctly; write-time `ValueError` remains wrapped as `AssemblyRefusal`.
- Folded item 5 — **OK.** Live assembly always passes the FW object graph loaded at `dsk_assemble.py:5609`; the documented fallback remains planning-only.

1. **MAJOR** — [src/obed_edom/iwa_movies.py:413](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/iwa_movies.py:413): front-loading clips silently retimes legitimate non-movie builds.

   Failure scenario: the fixture at [tests/test_iwa_movies.py:624](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/tests/test_iwa_movies.py:624) starts with non-movie chunk `810` at position 0 using `(automatic=True, referent=True)`, meaning After Transition. The patch changes `[810, 930, 811, 910]` to `[910, 930, 810, 811]` while leaving `810`’s flags unchanged. It therefore becomes After Build 2; `811` similarly shifts from After Build 2 to After Build 3. Verification only examines planned movie chunks, so this semantic mutation passes.

   Fix: because the contract does not define how existing overlay builds should be retimed, refuse before any write when `non_target` is non-empty. Alternatively, define an explicit preservation policy and read back every affected non-target chunk. Refusal is safest and does not affect the confirmed real decks, whose overlays are static.

2. **MINOR** — [src/obed_edom/iwa_movies.py:403](/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/skills-memory-review-b2c054/src/obed_edom/iwa_movies.py:403): malformed timing-mode topology is accepted or raises the wrong exception.

   Failure scenario: a hand-built plan containing two `after_transition` entries produces positions 0 and 1 with identical `(True, True, 0)` flags. Verification passes because expected positions are derived from that generated order, although the second entry reads as After Build 1—not After Transition. An unknown mode instead raises `KeyError` from `_CLIP_TIMING_RANK`, contrary to the `ValueError` refusal contract.

   Fix: preflight every slide before writing: require only known modes and a sequence equivalent to `after_transition, with_build_1*, after_previous*`, with exactly one `after_transition`. Raise `ValueError` on violations.