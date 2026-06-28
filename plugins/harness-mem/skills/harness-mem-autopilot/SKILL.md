---
name: harness-mem-autopilot
description: Conversation autopilot for harness-mem. Use proactively when starting or resuming a task, when the user asks about previous decisions, when the user asks to remember a rule, when recent work becomes stable enough to preserve, or when a memory conflict appears.
---

# harness-mem-autopilot

## Purpose

Use this skill as the conversation-level auto-learning autopilot for `harness-mem`.

It decides when to read, preserve, or propose memory during a normal chat. It
does not replace the `harness-mem` runtime, and it does not write durable truth
directly.

Default posture:

```text
read by default
suggest before writing
candidate before truth
summary before raw evidence
learn through candidates, not silent truth writes
no hook or dream auto-maintenance unless the user opted in
```

## Configuration contract

Default is enabled. `autopilot.enabled=false` is not the default posture; it is
a hard opt-out for projects or users that explicitly disabled proactive memory
actions.

On activation, first check the merged `harness-mem` configuration when the
project/user config is available. If `autopilot.enabled=false`, stop proactive
autopilot behavior immediately: do not call status, wake, search, distill, or
`suggest_*` unless the user explicitly asks for a memory action in this turn.

| Key | Default | Meaning |
|---|---:|---|
| `autopilot.enabled` | `true` | Allow this skill to run conversation-level auto-learning actions. |

CLI owns configuration writes, for example `harness-mem config set autopilot.enabled false --scope project`. The normal user workflow remains Slash, Skill, natural language, and MCP behind the agent.

Autopilot has only this single user-facing switch. When enabled, it may proactively
wake/search and create evidence-backed candidates or distill handoffs at clear
task boundaries. Durable memory still goes through the normal candidate/review
loop; autopilot never silently confirms truth. Dream is enabled by default, but
it still follows runtime auto gates, audit ledgers, and undo metadata.
Users can opt out with `dream.auto.enabled=false`.

## Trigger map

| Situation | Action |
|---|---|
| New task, resume, continue, pick up where we left off | If enabled, call project status, then `wake`; only use accepted/current truth. |
| User asks “previously”, “last time”, “why did we decide”, “history” | If enabled, use `search_memory`; drill down with `timeline` or observations only when needed. |
| User explicitly says “remember this”, “make this a rule”, “以后都这样” | Create a candidate with `suggest_rule` or `suggest_memory_entry`; do not directly confirm unless the user explicitly decides. |
| User asks to organize, distill, archive, or close recent sessions | If enabled, run the normal `/hm:distill` equivalent path: prepare evidence, use session-distill, then auto-review low-risk candidates. |
| Work reaches a stable, reusable boundary | If enabled, suggest distill or create a handoff candidate; do not write vague transcript notes. |
| Repeated mistakes or durable workflow patterns appear | If enabled, suggest a rule candidate for project truth. Do not write procedural skill lifecycle candidates from autopilot. |
| New evidence conflicts with existing memory | Suggest supersede or correction; never overwrite confirmed truth in place. |

## Candidate-worthy test

Before writing any candidate, check whether the memory is stable enough:

```text
Can the useful work area be named clearly?
Is the statement durable beyond this turn?
Is there evidence or a user instruction?
Would future wake/search benefit from it?
Is it not just a draft, mood, or transient plan?
```

If the answer is unclear, do not write. Continue the task or suggest a later distill.

## Forbidden behaviors

Do not:

- write memory every turn;
- summarize the whole conversation automatically;
- turn pending candidates into confirmed truth without approval/policy;
- hard-delete confirmed truth;
- treat generated prose as truth;
- inject every memory into wake;
- run hook or daemon maintenance outside the runtime gates;
- bypass `dream.auto.enabled` when handing eligible candidates or memories to dream maintenance;
- present CLI as the normal daily workflow when MCP or Slash/Skill is available.

## Output discipline

When this skill takes action, keep user-visible output short:

- state the memory action in plain language;
- show only the useful result or next decision;
- keep raw evidence behind drilldown unless the user asks for proof.
