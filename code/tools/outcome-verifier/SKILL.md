---
name: outcome-verifier
description: Verify completion with direct evidence. Use after implementation, debugging, automation, hooks, background jobs, data processing, releases, deployments, migrations, or performance work when code, configuration, or tests alone are insufficient.
---

# Verification

Use direct evidence. A file, configuration, queue entry, unit test, or `completed` status is insufficient unless it proves the requested result.

## Workflow

1. Restate the requested result as one or more user-visible claims.
2. Identify direct evidence for each claim. Prefer runtime receipts, persisted artifacts, independent retrieval, public installation, or observed UI/API behavior.
3. Find `.codex/outcomes.json` from the project root. If it exists, run:

   ```text
   python <skill-dir>/scripts/verify_outcomes.py --config <project-root>/.codex/outcomes.json --output <project-root>/.codex/outcome-report.json
   ```

4. If no configuration exists, verify manually using the same claim/evidence model. Do not create project files unless the user asked to integrate verification.
5. Treat a missing direct probe as `blocked`, not passed. Supporting evidence may explain a result but may not establish it.
6. For async behavior, require evidence produced after the relevant trigger. Do not infer a future Stop, hook, deploy, or background action from its configuration.
7. For generated or processed data, verify the artifact exists, has meaningful content, and can be consumed or retrieved through the intended path.
8. Report `passed`, `partial`, `failed`, or `blocked`. Say “complete” only for `passed`.

Read [configuration.md](references/configuration.md) when creating or changing a project contract.

## Independent Verification

Use an independent subagent only when the host supports it and the task is high-risk, asynchronous, cross-system, release-related, or vulnerable to self-confirmation. Read [verifier-agent.md](references/verifier-agent.md) and instantiate that role with the task-local claim and artifacts. Give the verifier the user request, raw artifacts, and environment access. Do not give it the builder's conclusion or expected answer. The subagent must remain read-only unless the user separately authorized fixes.

Independent review supplements deterministic probes; it never replaces them.

## Evidence Rules

- Require at least one successful `direct` check per claim.
- Mark code presence, configuration presence, mocks, unit tests, queued jobs, and planned callbacks as `supporting` unless they are themselves the requested result.
- Prefer fresh evidence tied to the current project, configuration fingerprint, trigger, session, release, or deployment.
- Preserve negative evidence in the report. Do not hide a failed required check behind successful supporting checks.
- Distinguish “not run”, “ran and failed”, and “ran but produced no useful output”.
- Measure performance end to end: wall time, complete Agent/tool input where applicable, and useful output. A smaller intermediate file alone is not proof.

## Final Response Contract

Lead with the overall verdict and name any remaining user-visible gap. Include only the most decision-relevant checks. Use wording such as:

```text
Status: partial
PASS  public package installs
PASS  native hook receipt is fresh
FAIL  generated session note is absent

Conclusion: infrastructure shipped; the requested result is not complete.
```

Never translate `partial`, `failed`, or `blocked` into “done with minor caveats.”
