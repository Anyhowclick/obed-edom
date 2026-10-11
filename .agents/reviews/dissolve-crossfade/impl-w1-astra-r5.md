**R4 blocker: CLOSED.** Every freeze element now receives the guard ([tests:1087](tests/test_live_runtime.py:1087)); unknown parent methods are recorded ([tests:1071](tests/test_live_runtime.py:1071)) and rejected by the assertion ([tests:1614](tests/test_live_runtime.py:1614)). The exact r4 `v.parentElement.removeChild(v)` mutation fails on both players.

**New demonstrated blocker: moving the video into a generated holder survives.** At [runtime:143](src/obed_edom/live_runtime.py:143), replace:

```js
H.push(h),ad.push(v)
```

with:

```js
H.push(h),ad.push(v),h.appendChild(v)
```

In a browser, this detaches and reparents the live video. Both generated-holder stubs merely push into `children`, leaving its recorded parent unchanged ([freeze:1115](tests/test_live_runtime.py:1115), [deck:1435](tests/test_live_runtime.py:1435)). The snapshot excludes generated holders, and freeze holder inspection reads only the first child ([tests:1088](tests/test_live_runtime.py:1088), [tests:1131](tests/test_live_runtime.py:1131)). Deck assertions likewise miss the added video ([tests:1439](tests/test_live_runtime.py:1439)).

In-memory verification: all eight baseline behavioral cases passed. All seven reported safety mutations failed on both players. **The new mutation passed construction, census, all 200 freeze rows, and deck cases on both players**, with `touched=[]` and `treeChanged=false`.

The deck stub therefore leaves this concrete gap. Generated-node append operations must expose reparenting of existing live nodes, with this mutation retained as a negative control.

**CHANGES REQUIRED**