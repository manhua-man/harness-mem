# Acceptance Checklist: `client_trace_evidence`

Use this checklist before accepting any CTE1-CTE4 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `client_trace_evidence`.
- [ ] `condition` is `trace`.
- [ ] Client and workspace path are recorded.
- [ ] Transcript exists.
- [ ] Tool call record exists if visible.
- [ ] Final user-visible output is stored.
- [ ] The report does not claim support beyond the recorded client and prompt.

## CTE1: Cross-Client Write/Read Trace

Pass requires all of:

- [ ] Candidate write path is visible.
- [ ] Review or confirmation path is visible.
- [ ] Readback path is visible.
- [ ] Transcript proves the user-visible behavior, not only internal state.

Primary failure signals:

- Internal cache evidence is reported as full client transcript evidence.

## CTE2: Workspace-Path-Visible Packet Run

Pass requires all of:

- [ ] Workspace path is visible in evidence.
- [ ] Packet scenario or prompt is named.
- [ ] The claim is scoped to the observed workspace and client.

Primary failure signals:

- Workspace path is inferred but not visible.

## CTE3: Transport Failure Transcript

Pass requires all of:

- [ ] Transport failure is surfaced in user-facing terms.
- [ ] Guidance points to current maintenance/troubleshooting surfaces.
- [ ] Removed daily CLI fallback guidance is absent.

Primary failure signals:

- Failure is hidden as success.
- User is told to hand-run obsolete daily wake/search/timeline commands.

## CTE4: Project Mismatch Clarification

Pass requires all of:

- [ ] Mismatch is detected.
- [ ] Both detected project names or roots are surfaced when available.
- [ ] The agent asks for clarification instead of guessing.

Primary failure signals:

- Agent silently chooses the wrong project.
