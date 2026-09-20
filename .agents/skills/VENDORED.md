# Vendored skills

Copied verbatim from upstream (MIT). Re-vendor by copying again at a newer commit; do not edit in place.

| Skills | Source | Commit |
|---|---|---|
| `ui-ux-pro-max` (replaces `emil-design-eng`) | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill — `.claude/skills/ui-ux-pro-max` | `de5f12b400775997d213524ef02a7c7d2746806f` |
| `code-review`, `codebase-design`, `diagnosing-bugs`, `domain-modeling`, `improve-codebase-architecture`, `prototype`, `research`, `resolving-merge-conflicts`, `tdd`, `grilling`, `grill-me`, `handoff`, `to-questionnaire`, `wait-what`, `writing-for-agents` | https://github.com/mattpocock/skills — `skills/{engineering,productivity}/*`, flattened | `c55ee46073ed923f86ce59a5eb3b6d895095d1b7` |

`obed-edom` and `sermon-validation` are this repo's own skills and remain the source of truth for project contracts.

Not vendored from mattpocock/skills, on purpose: the issue-tracker workflow (`setup-matt-pocock-skills`, `triage`, `to-spec`,
`to-tickets`, `wayfinder`, `implement`, `implement-spec`, `ask-matt`) — this repo plans in `.agents/plans/`; TypeScript or
course tooling (`migrate-to-shoehorn`, `setup-ts-deep-modules`, `setup-pre-commit`, `scaffold-exercises`); settings/credential
installers (`git-guardrails-claude-code`, `wizard`); article writing (`writing-beats`, `writing-fragments`, `writing-shape`);
and `pr`, `retro`, `claude-handoff`, `loop-me`, `teach`, `grill-with-docs`, which overlap this repo's own PR, handover and
Hall-of-Witnesses conventions.
