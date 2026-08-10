---
name: answer-memory-evidence
description: Gather compact, current code, documentation, configuration, test, command, or user-statement evidence for a harness-mem candidate whose promotion question is not yet answered. Automatically use during hm-distill or hm-review when current-source refs are missing, incomplete, conflicting, or stale; the user does not need to invoke it. Never writes or promotes memory.
---

# Answer Memory Evidence

Answer one candidate verification question from current, auditable sources.

Run when routed by `hm-distill`; do not wait for explicit user invocation. Skip when the candidate already carries sufficient current hashes.

Prefer project-relative files and content hashes for repository facts. Prefer a user-role exchange and its hash for explicit preferences or decisions. Return:

```text
answer_status: ANSWERED | PARTIAL | UNANSWERED | CONTRADICTED | STALE | NOT_APPLICABLE
answer: <concise finding>
evidence_refs: <content-free refs suitable for the existing evidence envelope>
uncertainty: <remaining gap, if any>
recommended_action: admit | narrow | defer | reject
```

Only `ANSWERED` can continue toward promotion. Do not call `govern_memory`, approve candidates, or create another evidence store. The caller owns candidate wording and the runtime independently revalidates every ref during auto-review/finalize.
