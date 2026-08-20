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
runtime-gated maintenance only; no background semantic claims
```

## Configuration contract

This skill has no separate user-facing master switch. Capture, automatic distill,
autonomous provider use, and Dream each use their own explicit policy key, so a
single nominal switch cannot imply that all runtime behavior stopped.

The skill may proactively
wake, route in-flight context/tool/save-point events through
`autopilot_search_tick`, and create evidence-backed candidates or distill
handoffs at clear task boundaries. Durable memory still goes through the
normal candidate and automatic-governance loop. Autopilot never bypasses the
shared policy or writes truth directly; `/hm:review` remains the post-hoc audit,
correction, and undo surface. Dream is enabled by default, but it still follows
runtime auto gates, audit ledgers, and undo metadata.
Users can opt out with `dream.auto.enabled=false`.

## Trigger map

| Situation | Action |
|---|---|
| New task, resume, continue, pick up where we left off | Call project status, then `wake`; only use readable truth (`auto_confirmed` / `user_confirmed`). If wake returns a structured distill maintenance offer, consume its ordered exact job IDs sequentially up to `process_limit`, using the returned semantic/compact prepare budget and `run_ingest=false`; finalize or defer each owned job before continuing, without asking the user to run distill. |
| Runtime context/tool/save-point event has uncertainty, conflict, failure, durable-claim grounding, or long-horizon task switch | Call `autopilot_search_tick`; inject returned `context_injection` into the next context when search runs. |
| User asks “previously”, “last time”, “why did we decide”, “history” | Use `autopilot_search_tick` when inside a runtime event; use `search_memory` as the explicit fallback path. Drill down with `timeline` or observations only when needed. |
| User explicitly says “remember this”, “make this a rule”, “以后都这样” | Run the high-impact candidate admission check, then `govern_memory(action="suggest")` on `admit` / narrowed `narrow`; let the shared automatic policy govern it and never direct-confirm it. |
| User asks to organize, distill, archive, or close recent sessions | `/hm:distill` path with **light** checklist default; deep for high-impact items. |
| Work reaches a stable, reusable boundary | Light admission then suggest distill or handoff. |
| Repeated mistakes or durable workflow patterns appear | **Deep** admission then suggest rule candidate. |
| New evidence conflicts with existing memory | Suggest supersede or correction; never overwrite confirmed truth in place. |

## Candidate-worthy test

Before any `govern_memory(action="suggest")`, run the candidate admission check
defined by `hm-distill`: verify high-impact rules against current evidence and
use one inline pass for ordinary candidates. Continue on `admit`; rewrite and
continue on `narrow`; do not write on `reject` or `defer` without an evidence plan.

## Forbidden behaviors

Do not:

- write memory every turn;
- summarize the whole conversation automatically;
- turn candidates into truth outside the shared automatic governance policy;
- hard-delete confirmed truth;
- treat generated prose as truth;
- inject every memory into wake;
- run hook or daemon maintenance outside the runtime gates;
- exceed the wake offer's bounded `process_limit`, process jobs concurrently, or let one job's failure mutate another job;
- bypass `dream.auto.enabled` when handing eligible candidates or memories to dream maintenance;
- present CLI as the normal daily workflow when MCP or Slash/Skill is available.

## Output discipline

When this skill takes action, keep user-visible output short:

- state the memory action in plain language;
- show only the useful result or next decision;
- keep raw evidence behind drilldown unless the user asks for proof.
