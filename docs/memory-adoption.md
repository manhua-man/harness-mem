# Memory Evidence Verification

`hm-distill` has one public path. Agent collaborators are conditionally and automatically routed when a candidate needs evidence, pressure testing, or boundary consultation; users do not invoke them manually. They are not runtimes, MCP tools, or memory writers.

```text
session evidence
  → candidate claim
  → evidence question
  → current-source verification
  → runtime Answer Gate
  → only ANSWERED
  → scoped auto-review
  → truth layer
```

The Answer Gate is runtime-derived from the existing candidate evidence envelope. An Agent supplies `evidence_basis`, its requested `verification_outcome`, and content-free `verification_refs`; auto-review re-reads the current repository or immutable user-statement source before assigning the gate status.

| Runtime status | Meaning | Promotion |
|---|---|---|
| `ANSWERED` | Current repository or explicit user-statement evidence validates the claim | Eligible for scoped policy review |
| `PARTIAL` | Some evidence exists, but the proof is incomplete | Blocked |
| `UNANSWERED` | No qualifying proof | Blocked |
| `CONTRADICTED` | Evidence conflicts with the claim | Rejected |
| `STALE` | A content-addressed source changed after the claim was formed | Rejected or superseded |
| `NOT_APPLICABLE` | The question does not establish durable truth | Blocked |

`answer-memory-evidence` runs automatically for an unresolved evidence gap. `grill-before-distill` runs automatically for a high-risk or overbroad conclusion. `ask-memory-boundary` runs automatically when evidence leaves a product or architecture decision unresolved. The routes are independent rather than a fixed chain; ordinary verified low-risk candidates skip all three. None can declare promotion or add an MCP call by itself.

This preserves the useful upstream separation—candidate extraction, evidence verification, promotion gate—without restoring packet workspaces, a second knowledge base, or mandatory helper loops.
