REVISE

1. **Medium — rotated content uses unrotated/approximate dimensions for the anchor decision.** `src/obed_edom/dsk_assemble.py:407-412` unions payload rectangles directly. For rotated images, movies, masked media, and residual groups, those rectangles are not authoritative visual bounding boxes; a rotated wide item can incorrectly satisfy `w/h >= 2.5`. Thread exact transformed AABBs from the object graph—`_frame_aabb`/`_mask_aabb`, with authoritative group geometry—into `_content_anchor`. Add tests where a 90° item and a fractionally rotated mask cross the 2.5 threshold after rotation and clipping.

2. **Low — D3 still marks the union rule as awaiting owner confirmation.** `.agents/plans/dsk_content_rules.plan.md:319`, `:346-368`, and `:578-585` contradict the supplied 2026-09-12 owner rule. Remove the “confirmation pending” language and record union placement as confirmed.

Prior Codex review findings 1 and 2 are resolved.

The requested pytest command could not start because the sandbox has no writable temporary directory; pytest failed during capture initialization with `FileNotFoundError: No usable temporary directory`.