# C6 code review r2 (Opus 5.5 high; three/two lenses, each finding adversarially verified by Opus 5.5 high)

Confirmed 6, refuted 0. Implementer: Codex GPT-5.6 Sol high. All confirmed findings were folded (fold report summarised in the C6 gate record).

## low · folds · Fold item 4 only partly resolved: the Chrome-root regex matches anywhere in argv and any executable whose name starts with 'Google Chrome '
`scripts/live_continuity_probe.py:4688` · class: edge case

**Scenario.** Item 4 asked for 'a root is a process whose executable path ends in /Contents/MacOS/Google Chrome (or CfT) with no --type='. The code uses re.match(r"^.*?/Contents/MacOS/(?:Google Chrome|Google Chrome for Testing)(?:\s|$)", command) over the full `command=` string. The lazy `^.*?` lets the path match inside the arguments, and `(?:\s|$)` accepts any executable whose name continues with a space. I checked both with the regex. (1) `/usr/bin/python3 scripts/chrome_requal.py --chrome /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --out d` matches. This is the documented re-qualification invocation, and it is exactly what a peer session runs, so its Python process counts as an extra foreign Chrome root on top of the Chrome it launches. (2) `.../Helpers/Google Chrome Helper (Alerts).app/Contents/MacOS/Google Chrome Helper (Alerts)` has no --type= and also matches. So before/during/after foreign counts are still inflated whenever these processes exist. The single-snapshot and vanished-pid parts of item 4 are resolved, and the counts fail closed rather than open.

**Fix.** Anchor the regex to the executable at the start of the command, and require end-of-line or a following ` -` flag right after the binary name. For example: `re.match(r"/(?:(?! -).)*?\.app/Contents/MacOS/Google Chrome(?: for Testing)?(?= -|$)", command)`. This rejects matches inside argv (such as the python `--chrome <path>` line) and helper names that continue past "Google Chrome". Add the python `--chrome` line and the Alerts helper line to the existing fake snapshot in `test_environment_observation_counts_only_chrome_roots_from_one_snapshot`, and assert that the owned/foreign counts are unchanged.

## low · folds · Fold item 11 incomplete: the score_arm parametrization still branches internally, so each case asserts a different subset
`tests/test_live_continuity_probe.py:8111` · class: closed class

**Scenario.** Item 11 asked for 'per-case explicit expected values instead of internal if-branches'. The fold replaced `if producer is None` with a three-way `if feed_state == "absent" / elif "producer-only" / else` branch and kept `if stale_alias:`, whose value is the same for every case because all cases use _p2_facts(). The expected_continuous parameter is asserted only in the normalized branch. Its values for missing-producer (False) and runtime-not-installed (None) are dead, and result["continuousExpected"] is never checked for those cases. The absent case never asserts that the normalizer was skipped. The fake scorer also still reads selected["planSha256"] into seen["scorer"]["plan"], which no assertion uses; it is a leftover of the removed relabel. Mutation check: the item 2 and item 3 behaviours are guarded, since reverting either one fails the test. Only the test-shape part of item 11 is unresolved.

**Fix.** Make every case assert the same things in tests/test_live_continuity_probe.py, in TestArmInterface.test_score_arm_owns_the_complete_pure_scoring_interface:

1. Add `assert result.get("continuousExpected") is expected_continuous`. I checked that this holds for all four cases.
2. Replace the feed_state if/elif/else with per-case parameters, either `expected_normalizer_continuous` (None meaning the normalizer was not called) and `expected_feed_evidence`, or a direct per-case check of `(seen.get("normalizer") or {}).get("continuous")` and `seen["scorer"]["feed"]`.
3. Drop both `if stale_alias:` guards. The alias "continue1to2" is always present, so set the capture alias and assert the alias row unconditionally.
4. Remove the unused `"plan": selected["planSha256"]` read from the fake scorer.

Do not add any new tests.

## medium · regressions · chrome_process_counts lets UnicodeDecodeError escape, so one non-UTF-8 argv anywhere on the machine aborts the capture mid-drive
`scripts/live_continuity_probe.py:4664` · class: new class

**Scenario.** chrome_process_counts runs `ps -axo pid=,ppid=,command=` with text=True (strict UTF-8 decoding) and catches only OSError/SubprocessError. macOS ps prints argv bytes as they are, so any process on the machine with a non-UTF-8 argument makes subprocess.run raise UnicodeDecodeError, which is a ValueError. Reproduced: with `tail -f /dev/null $'\xff'` running, probe.environment_observation() raised `UnicodeDecodeError ... byte 0xff`. capture_arm calls environment_observation for 'before' just before driving and for 'during' inside the drive_and_sample observer at mid-deck, so the exception aborts run_arm, run_attach_arm, the OBS feed session or an advance leg partway through. That breaks the rule that a failing observation must never abort a capture. The existing check_no_leftover_chrome pattern catches Exception and would not abort. Related fabrication edge: if ps exits 0 but no rows parse, the result is {owned: 0, foreign: 0}, which reads as a clean machine.

**Fix.** Decode leniently: add errors="replace" to the ps subprocess.run in chrome_process_counts and to the uptime run in environment_observation. Also return {"owned": None, "foreign": None} when os.getpid() is missing from the parsed rows, so a snapshot that cannot be parsed reads as unproven, never clean. For the test, add one undecodable byte to the fake ps output in the existing test_environment_observation_counts_only_chrome_roots_from_one_snapshot and assert the observation still returns counts. Do not add a new test.

## medium · regressions · The Chrome-root regex matches the Chrome path anywhere in a command line, so shells and peer tools count as Chrome roots
`scripts/live_continuity_probe.py:4688` · class: new class

**Scenario.** The brief defines a root as a process whose executable path ends in /Contents/MacOS/Google Chrome. The code uses re.match(r"^.*?/Contents/MacOS/(?:Google Chrome|...)(?:\s|$)", command), and the lazy `.*?` lets the path appear anywhere in the argv text. Measured on this Mac with zero Google Chrome processes running (`ps -axo comm=` count 0): one call made while a command line mentioned the Chrome path returned {owned: 1, foreign: 2}. The probe's own python -c process, its child sh, and the enclosing zsh/uv wrappers were all counted. Without that text the same call returned {0, 0}. In practice, a peer session running `chrome_requal.py --chrome ".../Contents/MacOS/Google Chrome"`, or a Claude Bash `zsh -c` wrapper containing the path, inflates `foreign` for the whole take, and C2 is planned to treat foreign Chrome as environment invalidity.

**Fix.** Find roots from the executable or argv[0], not from anywhere in the argv text. Either of these works:
- **Take a `pid=,ppid=,comm=` snapshot instead.** comm is the last column, so the full path survives `split(None, 2)`. Root = comm ends with "/Contents/MacOS/Google Chrome" or "/Contents/MacOS/Google Chrome for Testing". The `--type=` check can then go, because helpers and crashpad have different comm. The `calls` assertion in the existing test changes with this option.
- **Or keep `command=`** and anchor the regex to argv[0]: `^\S.*?/Contents/MacOS/(?:Google Chrome|Google Chrome for Testing)(?:\s+--|$)`. Simpler still, require that the text before the match contains no space-separated argument.

Keep the descendant walk unchanged.

**Test:** add one row to the existing fake snapshot in `test_environment_observation_counts_only_chrome_roots_from_one_snapshot` with the Chrome path unquoted mid-argv, e.g. `"200 1 python3 scripts/chrome_requal.py --chrome /Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`, and keep `foreign == 1`. Do not use the quoted zsh row the finding proposes: the current regex already rejects it, so it would pass against the buggy code. No new test is needed.

**Separately:** also catch UnicodeDecodeError, or decode with errors="replace", so a non-UTF-8 argv anywhere on the machine fails closed to None instead of raising.

## low · regressions · Advance-leg environment, hostKind and continuousExpected are built (three ps snapshots, git, a CDP call) and then dropped from the leg artifact
`scripts/live_continuity_probe.py:6709` · class: edge case

**Scenario.** For fold item 6, run_advance_leg now calls static_environment (git rev-parse plus Browser.getVersion) and three environment_observation calls. The 'during' call spawns ps and uptime while the leg sampler is still recording the settled destination. All of this goes into the capture passed to score_arm, but the returned leg dict keeps only specs, verdicts, sampler, endOfShow, reached, reasons, scope and verdict. destinations[*].advanceCarry in the Pass G artifact therefore carries no environment, hostKind or continuousExpected. The report's claim that advance-leg captures 'carry' browser version, git head, identity and observations is true only of the transient capture. TestAdvanceLeg checks only what score_arm received, not what the leg persists. The cost is paid during the sampled window and nothing is kept.

**Fix.** In run_advance_leg's return dict, add "hostKind": arm["hostKind"], "continuousExpected": arm["continuousExpected"] and "environment": arm["environment"] next to "scope". Read hostKind and continuousExpected from the capture or arguments if score_arm does not copy them through. In the existing TestAdvanceLeg test, the fake score_arm already returns {**capture, ...}. Add one assertion to that test: leg["environment"]["observations"] has the keys before, during and after, and leg["hostKind"] == probe.HOST_HEADLESS_CHROME. Do not add a new test.

## low · regressions · _feed_producer reads a 'feedProducer' capture key that nothing writes
`scripts/live_continuity_probe.py:4561` · class: closed class

**Scenario.** `if "feedProducer" in capture: return capture.get("feedProducer")`: a git grep finds no writer of feedProducer in scripts/ or tests/. capture_arm, OBS and stored artifacts all put the producer under feedEvidence.producer. The branch is speculative generality of the same kind as the deleted CAPTURE_FIELDS. It also creates a second, silent source that would override feedEvidence.producer if a stray key ever appeared.

**Fix.** Delete the `if "feedProducer" in capture` branch so that `_feed_producer` reads only `feedEvidence.producer`. Alternatively, inline that two-line lookup into score_arm and remove the helper. No test change is needed, because no test supplies feedProducer.
