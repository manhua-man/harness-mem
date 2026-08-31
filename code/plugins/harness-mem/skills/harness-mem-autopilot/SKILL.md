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

This skill has no separate user-facing master switch. Capture, explicit active-
host distill, and unattended Dream have separate boundaries. Dream additionally
requires project-level autonomous authorization (`distill.autonomous.enabled=true`)
and uses the current host CLI for background semantic work.

The skill may proactively
wake and route in-flight context/tool/save-point events through
`autopilot_search_tick`. It may suggest explicit distill at clear task
boundaries, but it never claims a queued job or starts background semantic work.
Durable memory still goes through point-level verification and trusted-runtime
assimilation. `/hm:review` remains the post-hoc audit, correction, and undo
surface. Hook-started work is handled only by an authorized Dream run.

## Trigger map

| Situation | Action |
|---|---|
| New task, resume, continue, pick up where we left off | Call project status, then read-only `wake`; use only current governed knowledge. Do not claim a queued job or consume a maintenance offer. |
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
- turn candidates into truth outside trusted verification and assimilation;
- hard-delete confirmed truth;
- treat generated prose as truth;
- inject every memory into wake;
- run hook or daemon maintenance outside the runtime gates;
- use wake as a semantic job runner or let one job's failure mutate another job;
- bypass the project profile, autonomous authorization, or Dream gate;
- present CLI as the normal daily workflow when MCP or Slash/Skill is available.

## Output discipline

When this skill takes action, keep user-visible output short:

- state the memory action in plain language;
- show only the useful result or next decision;
- keep raw evidence behind drilldown unless the user asks for proof.
