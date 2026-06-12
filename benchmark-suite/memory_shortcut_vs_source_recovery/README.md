# Memory Shortcut vs Source Recovery

This collection is the positive-signal complement to
`client_enabled_vs_disabled`.

`client_enabled_vs_disabled` asks whether memory helps ordinary continuation
tasks. That is a useful anti-overclaim gate, but easy repo-truth tasks can make
the disabled condition cheaper than the memory-enabled condition.

This benchmark instead asks a narrower question:

- when the answer depends on prior decisions buried in long source material,
  can an accepted memory packet let the agent recover the same truth with less
  source-reading cost?

## Signal Source

The measured delta is still `disabled - enabled`, but the task design makes the
two paths meaningfully different:

- enabled condition must inspect the memory shortcut first, then read only the
  minimal cited source spans needed to verify it. The default hard budget is no
  more than two source files/artifacts unless the result records a contradiction
  or missing-evidence reason.
- disabled condition must recover the same truth from source docs, archived
  sessions, release packets, or benchmark artifacts without harness-mem memory
  reads.

The report shows two token views:

- total tokens from `token_usage.total`, which remains the conservative public
  claim gate
- a cache-adjusted local proxy,
  `max(input - cached_input, 0) + output + reasoning`, which is diagnostic only

The proxy helps explain Codex runs where cached prompt input distorts the total
token comparison. It must not be used by itself as proof of public cost savings
or real billing reduction.

## Task Design Trap

Do not turn a bounded shortcut task into a broad historical decision-chain
recovery task. If the packet lists many source pointers or the prompt asks for a
timeline across several roadmap generations, the enabled condition often reads
memory and then re-reads the whole chain. That is valid as a boundary diagnostic,
but it is not a discriminative saving case.

A saving-oriented task should have:

- a compact accepted packet that identifies the decision
- at most two source pointers needed for enabled verification
- a disabled path that must recover the same answer from wider source material
- no requirement for enabled mode to prove every historical hop

## Claim Boundary

Passing this benchmark may support a bounded memory-shortcut claim:

- "on long-source recovery tasks, accepted memory packets reduced token/source
  reading cost while preserving answer correctness"

It does not prove:

- global token/cost savings
- real billing savings
- better answer quality on fresh local debugging tasks
- savings when memory tools are unavailable or return stale packets

## Required Controls

- At least one negative-control task where memory should not help.
- A source-verification requirement in enabled mode, so summaries cannot replace
  evidence.
- A source/tool budget for negative controls, so they do not become broad local
  debugging tasks.
- Token/cost counters from a named source on both sides.
- Predeclared pass thresholds before reading run results.
