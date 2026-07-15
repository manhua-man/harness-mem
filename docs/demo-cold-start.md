# Cold-Start Demo

This demo shows the core `harness-mem` job: a fresh Agent joins a real project
without reading old chats, recovers useful context, and proposes new memory
without hiding memory changes from the audit trail.

The product flow is intentionally small:

```text
wake -> search -> distill -> review -> dream
```

For this controlled walkthrough, the prompts below invoke stages explicitly.
In normal use, hooks only capture an immutable native transcript source revision
and queue its complete ordered chunks at a save point or session end. Hooks do
not summarize the session. The next Agent-capable wake, or `/hm:distill`,
resumes chunk processing and checkpoints each completed chunk.

Distillation never truncates a chunk. After every expected chunk is
checkpointed, the Agent must perform a final-session review of outcomes,
contradictions, unfinished work, and evidence strength. Only then may it create
idempotent candidates. `finalize_session_distill` verifies that contract, runs
the normal candidate auto-review, and runs Dream. The public model remains:

```text
wake -> search -> distill -> review -> dream
```

## What You Need

- A real project with at least one prior decision, convention, or handoff worth
  remembering.
- An MCP-capable Agent client such as Codex, Claude Code, Cursor, Gemini CLI,
  or another client that can call the `harness-mem` MCP server.
- `harness-mem` installed and connected through MCP. See
  [Quickstart](quickstart.md) and [MCP setup](mcp-setup.md).

## Demo Shape

Use two sessions. Session A is only controlled setup for the demo, not the
normal daily workflow:

| Session | Role | Goal |
|---|---|---|
| Session A | Project owner / existing Agent | Create or confirm a few project memories. |
| Session B | Fresh Agent | Recover those memories without reading old chat history. |

This makes the cold-start problem visible. Session B should start with only the
repo and the memory backend, not the previous conversation.

When the demo uses a project-scoped MCP entry, the first MCP initialization
creates the project profile and installs the matching IDE hooks automatically.
If hooks are missing, the next MCP initialization repairs the project-local
installation without overwriting existing files.
Codex users must then review and trust the newly installed project hooks once
in **Settings > Hooks** and start a new task. Check `get_project_status`:
`hooks=review_required` means Codex has not yet run the current Hook
configuration; `hooks=ok` means the matching `SessionStart` Hook completed.

## Five-Minute Script

Copy these prompts into your Agent client after MCP is connected.

Session A:

```text
Use harness-mem to distill the recent project session into memory candidates.
Let the normal auto-review policy process low-risk candidates. Use review only
to audit or correct stable facts that a future Agent should know, and reject
noisy, speculative, or one-off items.
```

Session B:

```text
Use harness-mem to wake this project.
Search harness-mem for the current release boundary or claim boundary.
Use the recovered context to make one small safe update.
Distill this session into memory candidates.
Open the review inbox only to audit what was auto-promoted or kept pending.
```

If Session B can recover a real prior decision without pasted chat history, the
demo is showing the intended product loop.

## Session A: Prepare Real Memory

Pick 2-4 facts that would matter to a future Agent. Good demo memories are
small but consequential:

- A release boundary: "Do not claim X until Y is verified."
- A project convention: "Use MCP as the Agent surface; CLI is for setup and
  diagnostics."
- A handoff: "The next useful step is to build a cold-start demo."
- A review result: "Only readable trust-tier memory should appear in wake/search."

Ask the existing Agent:

```text
Use harness-mem to distill the recent project session into memory candidates.
Apply the normal low-risk review policy; keep suspicious items pending and let Dream maintain the ledger.
```

Keep the review strict. The demo is stronger when noisy or speculative items
remain rejected or pending instead of becoming confirmed memory.

## Session B: Cold Start A Fresh Agent

Start a new Agent session in the same project. Do not paste old chat history.

### 1. Wake

Ask:

```text
Use harness-mem to wake this project. Summarize only confirmed context and tell me what you would do next.
```

Expected result:

- The Agent sees a compact project brief.
- The brief is based on confirmed memory, not the previous chat transcript.
- The Agent can name at least one relevant decision, convention, or handoff.

### 2. Search

Ask for one specific historical point:

```text
Search harness-mem for the current release boundary or claim boundary.
```

Expected result:

- The Agent retrieves a specific prior decision or rule.
- The answer includes enough source or memory metadata to explain why it was
  returned.
- The Agent does not invent a stronger claim than the memory supports.

### 3. Do A Small Task

Give the Agent a short task that depends on recovered context:

```text
Based on the remembered release boundary, update the public wording so it stays inside the confirmed claim.
```

Expected result:

- The Agent uses the remembered context to avoid repeating old decisions.
- The task output should be small enough to review quickly.

### 4. Distill

After the task, ask:

```text
Use harness-mem to distill this session into memory candidates.
```

Expected result:

- The immutable source revision is processed through every ordered chunk, with
  no truncation and a durable checkpoint for each chunk.
- Candidate creation waits for the required final-session review and is
  idempotent when an interrupted distill resumes.
- `finalize_session_distill` verifies completeness, then runs auto-review and
  Dream.
- New information is proposed as candidates, then the shared policy may
  auto-confirm only low-risk items with audit metadata.
- One-off task details are not promoted as durable memory.
- Anything broad, risky, or under-evidenced remains pending.

### 5. Review

Ask:

```text
Review the new harness-mem candidates. Confirm stable project facts, reject noise, and leave uncertain items pending.
```

Expected result:

- Confirmed memories become eligible for future `wake` and `search`.
- Rejected or pending material does not pollute future wake context.

## What To Capture

For a design partner or public walkthrough, capture only these artifacts:

- The initial Session B `wake` summary.
- One `search` result that recovers a prior decision.
- One candidate created by `distill`.
- The review outcome for that candidate.
- A short note on whether the fresh Agent avoided rereading old chats.

Avoid turning this into a benchmark. The point is product comprehension: can a
new Agent recover project context and keep new memory reviewable?

## Success Criteria

The demo is working when:

- A fresh Agent can explain the project state without pasted chat history.
- `search` can recover a real prior decision by topic.
- `distill` consumes every ordered chunk without truncation, checkpoints each
  chunk, and requires a final-session review before creating idempotent
  candidates instead of directly changing confirmed truth.
- `finalize_session_distill` runs auto-review and Dream only after structural
  completeness is verified.
- The shared policy handles low-risk promotion; review audits, corrects, or
  promotes the remaining uncertain material.
- The user can understand the value in under five minutes.

## Common Failure Modes

| Failure | Fix |
|---|---|
| `wake` is empty | Confirm at least one real memory in Session A. |
| `search` finds generic noise | Use narrower queries and reject low-value candidates during review. |
| Too many candidates | Distill fewer sessions or ask the Agent to keep only reusable project facts. |
| The Agent asks for CLI commands | Redirect it to the Agent-facing action: "use harness-mem to wake/search/distill/review." |
| The demo sounds like a claim benchmark | Remove percentages, speedup language, and broad quality claims. Show the workflow instead. |
