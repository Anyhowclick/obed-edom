# C6 code review r4 (Opus 5.5 high; closing round, major/blocker only, self-refuted)

Scope: the r3 fold diff. Result: **NO MAJOR/BLOCKER**, so the review loop stops.

- **(a) The r3 medium is closed.** The reviewer ran 16 `rescore_generated` replay variants:
  - groundTruth present or removed;
  - stored verdicts set to None or left as stored;
  - a bad row of type int, str, None or list, appended or prepended.

  Every variant gives `ok=False`, `contractRejected=4`, `differ=0` and `equalsLegacyScorer=None`, and so does a bad row on the attach entry. HEAD `ad2bd89f` reproduces r3 exactly: `ok=True` with 16 reproduced, or 4 `differ`, or an AttributeError.
- **(b) Valid input is unchanged.** `score_arm` output is byte-identical between HEAD and the fold for 10 valid capture shapes, each with and without an expected stage:
  - authored rows, with and without a schema;
  - `[]`, plain and in screen space;
  - `sampleRows`-only, as a list and as `[]`;
  - both keys present;
  - `samples=None` with `sampleRows`;
  - screen-space rows;
  - a feed capture;
  - an advance-leg spec subset.

  The fresh paths cannot reach the new branch: `capture_arm`, the advance leg and managed-OBS `feed_script` all go through `drain_samples`, and `detach_experiment` returns its `drive_and_sample` result unchanged.
- **(c) The new tests fail on the unfixed code.** The non-dict-row case raises AttributeError on HEAD. The environment test fails under three mutations: `owned = 0`, removing the getpid guard, and breaking the descendant walk.
