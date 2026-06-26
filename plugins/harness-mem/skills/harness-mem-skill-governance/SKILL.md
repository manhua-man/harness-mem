---
name: harness-mem-skill-governance
description: Use only when the user explicitly wants to audit, optimize, promote, reject, or record procedural skills stored by harness-mem. This is a dedicated operator workflow, not the normal memory MCP workflow.
---

# harness-mem Skill Governance

Use this skill for explicit procedural skill inventory and lifecycle work:

- audit repeated workflows that may deserve a reusable procedural skill;
- list pending procedural skill candidates;
- search confirmed procedural skills;
- promote or reject procedural candidates after review;
- record whether a confirmed skill actually helped.

Do not use this skill during ordinary `wake`, `search`, `distill`, `review`, or
dream maintenance. Normal project memory remains the default harness-mem
workflow. This workflow is closer to `skill-optimizer` and
`skill-activation-auditor`: inspect the skill inventory, reduce noise, and only
mutate lifecycle state when the user intentionally asked for skill governance.

## Boundary

- Do not call skill lifecycle MCP tools. They are not part of the public memory MCP surface.
- Read-only procedural hints may appear in normal memory context, but lifecycle decisions belong here.
- Start with an audit or search before proposing writes.
- Confirm/reject only after the user has approved the candidate decision.
- Never rewrite Claude/Codex/Cursor skill files from this workflow. This governs harness-mem procedural memory, not installed client skills.

## Commands

Use the CLI operator workflow from the project root:

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

## Workflow

1. Identify the project and the user's intent: audit, search, propose, confirm, reject, or record outcome.
2. For audit/search requests, run `list-candidates` and/or `search`; summarize the useful items and obvious noise.
3. For a new procedural candidate, create it with `suggest` only when the workflow is stable, repeatable, and evidence-backed.
4. For promotion or rejection, show the candidate id and reason, then run `confirm` or `reject` only after the user agrees.
5. For outcome tracking, run `record-result` after a confirmed skill was actually used.

## Candidate Quality Bar

Create a procedural candidate only when all of these hold:

- the activation condition is specific;
- the steps are reusable across future sessions;
- the termination condition is clear;
- the workflow is not just a one-off project fact;
- the candidate would reduce future context or decision noise.

If a workflow is just project truth, use normal memory candidates instead.
