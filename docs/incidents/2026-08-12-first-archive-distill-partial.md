# First Real Archive Distill Batch — Partial Incident Report

Date: 2026-08-12 to 2026-08-13

Incident classification: partial

Remediation status: completed and verified on 2026-08-13
Affected surface: harness-mem post-turn maintenance, processed-source cleanup,
autonomous completion evidence, Session Notes, and historical audit coverage

## Executive summary

The first real archived-session distill batch produced valid durable artifacts for
part of the batch, but it did not satisfy the complete user outcome. The harness-mem
cleanup path deleted Codex transcript files after checking completion, source
revision, content hash, and quiet time, without checking the Codex writer lock or
task activity. At least one active Codex task was therefore eligible for deletion.

The same run also exposed evidence-binding gaps. A detached worker receipt could say
`succeeded` without retaining a verifiable binding from the originating Hook trigger
to one completed job, provider execution, and immutable Note. Historical completed
jobs whose source identity had already been pruned were collapsed by the audit probe,
which overstated Note and summary coverage.

No attempt was made to invent lost transcript text. The user reviewed the available
recovery evidence and decided not to restore the deleted sessions.

## Impact

- Native Codex rollout files for completed distill jobs could be removed while the
  corresponding Desktop task still had an active writer.
- The affected raw transcript, chunks, checkpoints, semantic projection, and source
  locator could be removed after durable truth/receipts were retained.
- The autonomous outcome could not prove that the Hook trigger, completed job,
  isolated provider receipt, and Note belonged to the same execution.
- Historical audit coverage was overstated because pruned jobs with an empty
  `session_id` were grouped as one synthetic empty session.

Observed cleanup evidence included:

- Session `019ff734…`: 281,854 raw bytes and 11 chunks removed.
- Session `019ff735…`: 2,403,122 raw bytes and 85 chunks removed.
- Session `019ff897…`: 317,046 raw bytes and 12 chunks removed while its Codex
  writer lock still existed and was held.

The cleanup receipts reported the native source deleted and the processed raw,
chunk, checkpoint, and projection counts reduced to zero. These receipts prove the
deletion outcome; they do not prove that the task was inactive.

## Timeline

1. A real archive distill batch ingested and reviewed archived Codex sessions.
2. Canonical finalization produced Answer Packets, governance results, Notes, and
   cleanup receipts for eligible jobs.
3. Post-turn maintenance retried retained cleanup before ingesting the current Stop
   transcript.
4. Cleanup treated completed, hash-matching, quiet files as deletable. It did not
   query `~/.codex/thread-writer-locks/<session>.lock` or Codex task state.
5. The batch finished with a partial user outcome. The archive apply command itself
   took about 60.4 seconds, while investigation, review, retries, and verification
   made the user-visible end-to-end interval about 23 minutes 20 seconds.
6. Recovery assessment found complete native rollouts for some sessions and only
   partial DB/log evidence for the deleted or never-materialized sessions. The user
   chose not to restore them.
7. Outcome probes subsequently showed four remaining gaps: autonomous completion
   binding, autonomous Note binding, provider isolation evidence, and historical
   semantic-summary coverage.

## Root cause

The deletion eligibility contract stopped at the harness-mem storage boundary:

```text
completed job + quiet source + matching revision/hash -> delete
```

It did not include the host lifecycle boundary:

```text
Codex writer lock released + task not active -> eligible to claim
```

This was a cross-system race. The atomic rename and compare-and-swap checks protected
against content changes, but they could not protect a quiet yet still active task.

For autonomous execution, identity was sanitized before the completion receipt was
fully materialized. The Note temporarily reconstructed the pre-cleanup identity in
memory, while the receipt used the sanitized completed job. This produced empty or
unbound session fields in real cleanup-enabled runs.

For historical audit, the probe keyed completed jobs by `job.session_id`. Cleanup had
intentionally blanked this value, so many distinct jobs collapsed into one empty key.

## Detection gaps

- Cleanup tests covered revision changes, atomic-claim races, companion manifests,
  managed backups, and residual artifacts, but not a live Codex writer lock.
- No test acquired a writer lock after planning and before the atomic claim.
- No test treated an unreadable Codex state database as fail-closed.
- Autonomous unit tests ran with source deletion disabled, so they did not reproduce
  post-cleanup identity sanitization.
- Outcome probes checked the presence of a successful receipt before they checked a
  complete trigger/job/session/provider/Note binding.
- Historical coverage grouped by session identity instead of auditing every durable
  completed job and immutable Note directory.

## Remediation

1. Probe the operating-system state of the Codex writer lock at cleanup planning
   time. Do not equate lock-file existence with an actively held lock.
2. Read Codex durable task state as a second signal. Treat an open spawned task as
   active and any unreadable or unknown state as retained.
3. Repeat both liveness checks immediately before atomic claim.
4. Preserve an immutable, non-sensitive completion binding across trigger, job,
   source revision, provider hashes, and Note hash.
5. Refuse ambiguous Note paths such as `sessions/.md`.
6. Resolve historical Notes through `revisions/<job_id>/` and backfill summaries only
   when exactly one immutable Note supplies deterministic text.
7. Mark missing post-prune evidence as `historical_summary_unavailable`; never ask a
   model to reconstruct it.
8. Require a fresh real Hook-triggered run before claiming the autonomous path fixed.

## Why it took as long as it did

The 60.4-second archive apply was only one part of the elapsed time. The end-to-end
work also included raw transcript ingestion, hashing and chunking, semantic
projection, model review, candidate governance, per-session Answer Packet and Note
materialization, retrieval verification, cleanup verification, repeated ingestion
caused by interleaved maintenance, and forensic inspection after the unexpected
deletions. Reporting only command time would hide the user experience; reporting only
the 23-minute interval would hide where execution time was actually spent.

## Operating lessons

- A command returning `completed` is supporting evidence, not proof of the user
  outcome.
- Destructive cleanup must occur after identity, Answer Packet, immutable Note, and
  receipts are durable, and only after the host lifecycle is inactive.
- Real batches must be verified per session and per job. A global `latest succeeded`
  record is not a binding.
- Semantic projection is a disposable revision-scoped cache. The audit surface is
  the completed job, immutable Note, Answer Packet, governance truth, and receipt.
- Missing historical evidence must remain visibly unavailable rather than becoming
  plausible generated prose.

## Tooling improvements

- Keep cleanup as a two-stage plan/claim protocol with host-liveness checks at both
  stages.
- Emit stable reason codes for active writer, active task, unknown liveness, and
  reactivation before claim.
- Use one job-bound identity contract for provider, completion, Note, and probes.
- Report stage durations separately: ingest, projection, provider, finalize, Note,
  retrieval, and cleanup.
- Isolate real acceptance batches from unrelated Hook maintenance and require exact
  trigger IDs in receipts.
- Make probes enumerate job-bound artifacts instead of relying on global latest
  projections or blank identifiers.

## Acceptance status

The original batch remains classified as partial. Remediation acceptance required
all of the following direct demonstrations:

- A held writer lock and an active task both retain the source.
- A task that becomes active after planning is retained before claim.
- A completed inactive task can still be cleaned after its cooling period.
- One real detached Hook run binds trigger, job, provider, completion, Note, and
  retrieval evidence.
- Historical summary audit coverage is complete through either a deterministic
  summary or an explicit unavailable marker.
- The complete project outcome contract passes after the final implementation review.

All six acceptance conditions were demonstrated on 2026-08-13. The final project
outcome contract passed all 12 claims; this closes remediation without rewriting the
historical batch result from partial to passed.
