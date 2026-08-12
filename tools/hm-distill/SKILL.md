---
name: hm-distill
description: Process project-scoped Codex, Claude Code, Cursor, Antigravity, opencode, Hermes, or generic Agent sessions into a readable session summary, optional governed memory candidates, and an auditable completion result. Use when the user asks to process, distill, summarize, learn from, or hand off one or more sessions, especially when a session ID is provided.
---

# HM Distill

Use one public flow: native session evidence → semantic review → optional memory candidates → finalize → readable Note. Run it through the configured harness-mem MCP tools; do not create a parallel CLI or local promotion workspace.

## Explicit session ID fast path

For a user-provided session ID:

1. Call `prepare_session_distill` once with:
   - `session_id=<id>`
   - `client="auto"`
   - `scope="project"`
   - `project_root=<current workspace root>`
   - `evidence_mode="semantic"`
   - `detail_level="compact"`
   - `budget_tokens=<configured or user target>`
2. Read the complete compact manifest and bundled decision exchanges returned by that call.
3. Produce the final semantic review and run the candidate admission check below.
4. Write only admitted candidates or a justified unfinished-work handoff.
5. Call `finalize_session_distill` once.
6. Return the readable summary. Finalize writes the immutable audit Note at
   `~/.codex/hm-distill/sessions/revisions/<job_id>/<session_id>.md` and advances
   `~/.codex/hm-distill/sessions/<session_id>.md` as the convenient latest view,
   all from the same review without rereading the transcript.

The bundled zero-candidate template is fail-closed. Detected decision, solution,
workflow, preference, migration, or handoff signals start as `candidate_required`;
do not submit that template unchanged as a no-candidate verdict. Missing current
repository proof is an evidence gap, not a reason to discard the claim.

When an explicit session ID points to a legacy completed `no_candidate` job whose
detected signals were downgraded without signal-specific reasons, prepare creates a
new policy-recheck job. The old completion remains immutable audit history.

The common no-candidate path is exactly `prepare → finalize`. Do not add status, list, export, or local diagnostic calls unless the MCP result reports an error or compatibility fallback.

## Project or batch path

When no session ID is supplied, resolve the current project with `get_project_status`, then call `prepare_session_distill` with `client="auto"`, project scope, the real workspace root, and the requested count (default 5). Process each returned job independently; an explicit invocation may complete at most three jobs.

## Evidence contract

- The native transcript revision is authoritative.
- The runtime must hash-check and checkpoint every expected raw chunk before final review.
- The compact response is a complete navigation view, not a truncated transcript substitute.
- `budget_tokens` is a soft target for the complete serialized MCP response. Expansion is allowed for complete coverage; malformed or clipped JSON is not.
- Use bundled `semantic_decision_exchanges` first.
- Request semantic or raw drilldown only when a candidate needs exact wording, commands, versions, errors, or repository proof.
- Use `detail_level="full"` only for an explicitly requested full semantic audit.
- If the runtime explicitly falls back to raw mode, read and submit every ordered chunk with `submit_distill_chunk` until the job reaches `reviewing`.

## Final semantic review

Complete these fields from the whole session, never from one isolated chunk:

- `session_summary`: 1–3 sentences covering topic, actual result, and important unfinished work;
- `final_user_request`;
- `final_outcome`;
- `last_turn_status`;
- `contradictions`: unresolved conflicts in the evidence for a current candidate;
- `unfinished_work`;
- `evidence_status`;
- `promotion_decision`.

The summary is always required and is independent of memory promotion. `no_candidate` means “nothing should enter durable memory,” not “the session had no content.” An older approach explicitly replaced by a later decision belongs in the summary or final outcome. Do not label that history as a current candidate evidence contradiction, because doing so can incorrectly suppress an otherwise Answered candidate.

## Candidate admission

Apply the following check inline before any memory write:

1. Is the claim reusable beyond this session?
2. Is its destination clear: memory, rule, relation, handoff, repository documentation, or no durable write?
3. Is its scope narrow enough to avoid misleading future Agents?
4. Is the evidence complete and appropriate for the claim?
5. Is it current, non-duplicative, and free of unresolved contradiction?

Use one outcome:

- `admit`: write the candidate;
- `narrow`: correct its wording or scope, then write it;
- `defer`: do not write until missing evidence or intent is available;
- `reject`: do not write session noise, duplication, transient state, or unsupported claims.

For ordinary candidates, run the check in one pass without asking the user. For high-impact rules, architecture, security, release policy, or repo-wide defaults, verify repository evidence first. Ask the user only when the remaining uncertainty is genuinely their preference, intent, or product decision.

Treat each surviving claim as an evidence question. Gather the smallest current-source proof needed to answer it, then attach the evidence envelope to the candidate. The runtime derives the Answer Gate status after revalidating those refs; the Agent cannot self-declare `ANSWERED`. Only runtime-derived `ANSWERED` candidates may enter the truth layer. `PARTIAL`, `UNANSWERED`, `CONTRADICTED`, `STALE`, and `NOT_APPLICABLE` remain blocked or are rejected. This gate is part of the existing govern/finalize calls and must not add a default MCP round trip.

### Conditional collaborator routing

Route collaborators automatically after the first-pass check; do not wait for the user to invoke them and do not load all three pre-emptively:

- Invoke `answer-memory-evidence` when a surviving claim lacks current-source refs, has incomplete or conflicting proof, or has unresolved freshness. Skip it when the required repository or user-statement hashes are already current.
- Invoke `grill-before-distill` when a claim is high-impact, repo-wide, security/release-sensitive, ambiguous, or likely to be overgeneralized, even if evidence exists.
- Invoke `ask-memory-boundary` when evidence cannot decide an architecture, product-scope, roadmap, or long-lived-default choice. Ask the user only if that consultation reduces the gap to a genuine user/product decision.

Routes are independent: answer and grill may both fire; ask fires only for a remaining boundary decision. Run at most one pass of each route per candidate unless it identifies one new concrete question. If the current host does not expose the named collaborator, apply that collaborator's contract inline. A collaborator never writes or promotes memory and does not add an MCP call by itself. When a route ran, include `collaborator_answer`, `collaborator_grill`, or `collaborator_boundary` in `verification_reason_codes` for audit.

A claim survives long enough to route as soon as a bundled exchange exposes plausible
durable value. Do not reject it merely because current-source proof is missing; route
answer first. If completed durable claims coexist with unfinished work, write the
durable candidates plus a scoped handoff and use `promotion_decision="partial"`.
Finalize may auto-review Answered candidates in that state, while Dream remains blocked.

When no candidate remains, use the bundled `zero_candidate_challenge_template`. Check corrections, decisions, successful solutions, repeated failures, preferences, reusable workflows or facts, migrations, and unfinished handoffs. Submit the returned exchange hashes unchanged. Detected signals are prefilled as `candidate_required`. Downgrade one to `not_durable` only after reviewing its complete window, and name that exact signal key plus the session-only reason in `rationale`. A durable finding requires a candidate or handoff; otherwise conclude `no_durable_candidate`.

Apply [distillation-rules.md](references/distillation-rules.md) for claim classification and noise rejection.

## Governed writes

Use `govern_memory(action="suggest")` only for admitted or narrowed durable claims. Use `govern_memory(action="handoff")` for concrete unfinished state that another task must resume. Pass the current `distill_job_id` to both candidate and handoff writes so finalize governs only artifacts produced by this job.

Every candidate must include:

- `evidence_basis`;
- `verification_outcome`;
- `verification_refs`.

For repository claims, answer “Is this still true in the current repo/runtime?” with current file hashes. For user preferences or decisions, answer “Did the user explicitly state this?” with a user-role exchange hash. Apply the conditional collaborator routing above whenever its trigger matches; the user never needs to request a collaborator explicitly.

Repository facts require current repository verification and project-relative paths with content hashes. Explicit user preferences or decisions require user-statement evidence. Transcript-only unverified claims may explain rejection but must not become durable truth.

## Finalize

Call `finalize_session_distill(project_name=<project>, job_id=<job>, semantic_review=<review>)` as the only commit point.

Finalize must:

- revalidate the source revision, checkpoints, and zero-candidate hashes;
- govern only candidates created by this job;
- automatically settle safe, rejected, contradicted, or unverified candidates;
- run Dream only when the semantic review permits promotion;
- record `promoted` or `no_candidate` and the actual source cleanup status.

Use `$hm-review` later for audit, correction, undo, replacement, or explicit trust upgrades. Do not run a second project-level auto-review or Dream to close the same job.

## User-visible result

Return a short result that includes:

```text
会话：<session_summary>
整理：<形成长期记忆 / 无需长期记忆>
未完成：<无 / concise unfinished work>
原文：<retained / deleted / partial failure / unsupported>
Note：<path>
```

`Note` is the immutable path returned as `note.path`. `note.latest_path` is the stable user shortcut for the newest completed revision of that session; it is not used as the audit receipt.

When durable memories were formed, add one bullet per memory in this shape:

```text
- **<title>**: <one precise, verifiable fact> (<verified date; repository verified / user confirmed>).
```

Do not append session, job, candidate, memory, evidence, or source IDs to those
bullets or to the default readable Note. IDs, token counts, policy reasons, and
verification refs belong only in audit detail when the user asks for them.

## Boundaries

- Do not ask users to run maintenance CLI commands when MCP tools are available.
- Do not import global cross-project history unless the user explicitly requests it.
- Do not infer whole-session outcomes from partial evidence.
- Do not create parallel knowledge bases, promotion files, or duplicate truth stores.
- Do not turn the distillation procedure itself into project memory unless harness-mem is the project being documented.
- If MCP evidence is unavailable or incomplete, report the gap instead of claiming completion.
