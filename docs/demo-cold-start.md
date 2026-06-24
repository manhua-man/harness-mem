# Cold-Start Demo

This demo shows the core `harness-mem` job: a fresh Agent joins a real project
without reading old chats, recovers useful context, and proposes new memory
without silently changing project truth.

The flow is intentionally small:

```text
wake -> search -> distill -> review
```

## What You Need

- A real project with at least one prior decision, convention, or handoff worth
  remembering.
- An MCP-capable Agent client such as Codex, Claude Code, Cursor, Gemini CLI,
  or another client that can call the `harness-mem` MCP server.
- `harness-mem` installed and connected through MCP. See
  [Quickstart](quickstart.md) and [MCP setup](mcp-setup.md).

## Demo Shape

Use two sessions:

| Session | Role | Goal |
|---|---|---|
| Session A | Project owner / existing Agent | Create or confirm a few project memories. |
| Session B | Fresh Agent | Recover those memories without reading old chat history. |

This makes the cold-start problem visible. Session B should start with only the
repo and the memory backend, not the previous conversation.

## Five-Minute Script

Copy these prompts into your Agent client after MCP is connected.

Session A:

```text
Use harness-mem to distill the recent project session into memory candidates.
Review the candidates and confirm only stable project facts that a future Agent should know.
Reject noisy, speculative, or one-off items.
```

Session B:

```text
Use harness-mem to wake this project.
Search harness-mem for the current release boundary or claim boundary.
Use the recovered context to make one small safe update.
Distill this session into memory candidates, but do not confirm new truth silently.
Review the new candidates and keep only stable project facts.
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
- A review result: "Only confirmed memory should appear in wake/search."

Ask the existing Agent:

```text
Use harness-mem to distill the recent project session into memory candidates.
Review the candidates and confirm only the stable project facts.
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
Use harness-mem to distill this session into memory candidates. Do not confirm new truth silently.
```

Expected result:

- New information is proposed as candidates.
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
- `distill` creates candidates instead of directly changing confirmed truth.
- Review decides what becomes durable memory.
- The user can understand the value in under five minutes.

## Common Failure Modes

| Failure | Fix |
|---|---|
| `wake` is empty | Confirm at least one real memory in Session A. |
| `search` finds generic noise | Use narrower queries and reject low-value candidates during review. |
| Too many candidates | Distill fewer sessions or ask the Agent to keep only reusable project facts. |
| The Agent asks for CLI commands | Redirect it to the Agent-facing action: "use harness-mem to wake/search/distill/review." |
| The demo sounds like a claim benchmark | Remove percentages, speedup language, and broad quality claims. Show the workflow instead. |
