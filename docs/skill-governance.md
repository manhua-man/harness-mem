# Skill Governance

Skill governance is the dedicated operator workflow for procedural skills in
`harness-mem`.

It is not part of the daily memory MCP surface. The normal product loop remains:

```text
wake -> search -> distill -> review -> dream
```

## What It Owns

Use skill governance only when you explicitly want to maintain procedural skill
inventory:

- list pending procedural skill candidates;
- search confirmed procedural skills;
- suggest a new procedural candidate from a repeatable workflow;
- confirm or reject a procedural candidate;
- record whether a confirmed skill helped.

Read-only procedural hints can still help `wake` or search results, but skill
lifecycle decisions do not run through public MCP tools or Daily slash commands.

## CLI Workflow

```bash
harness-mem skill-governance list-candidates -p <project>
harness-mem skill-governance search -p <project> --query "<workflow>"
harness-mem skill-governance suggest -p <project> \
  --activation-condition "<when this should run>" \
  --step "<first step>" \
  --step "<second step>" \
  --termination-condition "<when complete>"
harness-mem skill-governance confirm <candidate_id>
harness-mem skill-governance reject <candidate_id>
harness-mem skill-governance record-result <skill_id> --success
harness-mem skill-governance record-result <skill_id> --failure
```

`suggest` writes a pending procedural candidate. It does not create an active
skill until `confirm` promotes the candidate.

## Boundary

- Public MCP exposes memory workflow and read-only procedural hints, not skill
  lifecycle governance.
- `/hm:*` Daily commands do not manage skill lifecycle.
- The dedicated `harness-mem-skill-governance` plugin skill is the guided flow
  for this work.
- This does not edit installed Claude/Codex/Cursor skill files. It governs
  harness-mem procedural memory records.
