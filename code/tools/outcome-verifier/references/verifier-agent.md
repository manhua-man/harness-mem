# Independent verifier role

Use this template to launch one bounded, read-only verifier. Replace bracketed values; do not include the builder's verdict.

```text
Goal: Independently determine whether [user-visible claim] actually occurred.
Working directory: [project root]
Inputs: [user request and raw artifacts or runtime locations]
Read scope: [specific files, logs, stores, URLs, or UI]
Write scope: none
Acceptance: collect direct evidence from the real consumer/runtime/persistence path; distinguish passed, partial, failed, and blocked; identify any proxy evidence that does not prove the claim.
Output: claim, direct evidence, negative evidence, verdict, and exact reproduction commands.
Hard boundaries: do not infer future async execution; do not accept code/config/tests/queue state as runtime proof; do not fix anything; do not split, delegate, or launch subagents.
```

Give the verifier the minimum sufficient context. Raw logs, receipts, reports, screenshots, persisted artifacts, and public URLs are appropriate. Prior conclusions and expected failures are not.
