# Acceptance Checklist: `client_enabled_vs_disabled`

Use this checklist before judging any T1-T5 result. A run passes only when the
task-specific required facts are present, forbidden claims are absent, and the
answer is backed by visible evidence from the allowed condition.

## Global Checks

- [ ] `task_id` is one of `T1`, `T2`, `T3`, `T4`, `T5`.
- [ ] `condition` is exactly `enabled` or `disabled`.
- [ ] Client, model, workspace path, and repo state match the paired run.
- [ ] Runtime, turn count, follow-up count, and token total are recorded; token
      total is `"unavailable"` if the client does not expose it.
- [ ] Transcript exists for this task/condition.
- [ ] Enabled condition records every harness-mem read call in `memory_calls`.
- [ ] Disabled condition records an empty `memory_calls` list.
- [ ] Disabled transcript contains no `wake`, `search_memory`, `timeline`,
      `get_observations`, or slash wrapper delegating to those tools.
- [ ] Acceptance was judged against the predeclared task rubric, not adjusted
      after seeing the answer.

## T1: Embedding Baseline Truth

Pass requires all of:

- [ ] States that LongMemEval / benchmark docs default to `all-MiniLM-L6-v2`.
- [ ] States that `bge-small-en-v1.5` and `nomic-embed-text-v1.5` are configurable
      shootout candidates, not the current default.
- [ ] Provides at least one concrete evidence pointer from repo truth or memory
      evidence.
- [ ] Does not claim the default changed unless it cites a later shootout result
      with a concrete file/path.

Primary failure signals:

- Claims `bge-small-en-v1.5` or `nomic-embed-text-v1.5` is the default without
  evidence.
- Gives a generic embedding recommendation instead of recovering repo truth.

## T2: Release / Packet Status Recovery

Pass requires all of:

- [ ] Identifies at least three current packet or release-status items by concrete
      name, file, scenario id, or artifact path.
- [ ] Separates completed evidence from missing or not-yet-claimable evidence.
- [ ] Names the next verification step without asking the user to hand-run
      obsolete daily workflow CLI commands.
- [ ] Avoids public/user-facing claims that are stronger than the available
      artifact evidence.

Primary failure signals:

- Treats near-neighbor evidence as full proof.
- Collapses "docs mention it" and "real client transcript exists" into the same
  evidence tier.

## T3: Scheduling / Daemon Boundary

Pass requires all of:

- [ ] States that current implementation has no background daemon, IDE hook, or
      turn-end autonomous learning path for ordinary coding tasks.
- [ ] States that `suggest_*` writes are explicit agent-flow candidate writes.
- [ ] Recommends keeping benchmark or scheduling experiments isolated until the
      runtime contract is proven.
- [ ] Does not describe autonomous learning as already shipped.

Primary failure signals:

- Recommends a daemon as if it exists today.
- Equates Slash/MCP explicit workflows with automatic background learning.

## T4: User Workflow Recovery

Pass requires all of:

- [ ] Explains that user-facing daily entry points are Slash, MCP, and Skills.
- [ ] Correctly routes wake/search/timeline/candidate review to MCP or Slash,
      not to user hand-typed CLI commands.
- [ ] Describes CLI as local operations / troubleshooting surface for install,
      doctor, purge, maintenance, API server, and file imports.
- [ ] Includes a concise next-step recommendation for context recovery and for
      distilling recent sessions.

Primary failure signals:

- Tells the user to run removed or non-primary daily commands such as
  `harness-mem wake`, `harness-mem search`, `harness-mem timeline`, or
  `harness-mem candidates`.
- Omits the Slash/MCP boundary.

## T5: Negative Control

Pass requires all of:

- [ ] Solves the new local syntax error using normal repo/file/test evidence.
- [ ] Uses no memory calls in either condition unless the prompt explicitly
      instructs otherwise.
- [ ] Does not invent historical project context as necessary for the fix.
- [ ] Records whether memory provided no measurable advantage.

Primary failure signals:

- Uses memory to solve a task designed to require only fresh local file evidence.
- Frames a brand-new syntax error as a memory retrieval problem.

## Pair-Level Acceptance

After both conditions for a task finish:

- [ ] Both results were judged independently before computing deltas.
- [ ] Runtime delta is `disabled - enabled`.
- [ ] Turn delta is `disabled - enabled`.
- [ ] Token delta is `disabled - enabled` or `"unavailable"`.
- [ ] Outcome is recorded as one of:
      `enabled_only_passed`, `disabled_only_passed`, `both_passed`,
      `both_failed`.
- [ ] Notes state whether any difference came from memory retrieval, repo search,
      model variance, missing evidence, or operator intervention.
