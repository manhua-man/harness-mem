# Agent Benchmark: `harness-mem enabled` vs `disabled`

> Status: methodology only. This file defines how to produce the first honest
> "does harness-mem save real work?" benchmark. It does **not** claim results
> have already been collected.
>
> Last updated: 2026-06-05.

## Why this benchmark exists

Current `harness-mem` benchmark coverage is strong on retrieval quality
(`LongMemEval`, embedding shootout, wake/search latency samples), but weak on
the question that matters most to users:

> In a real agent task, does `harness-mem` reduce token use, runtime, or
> repeated rediscovery compared with having no memory system at all?

This document defines the first publishable answer.

## What this benchmark should prove

We want one user-facing page that can honestly answer all three questions below:

1. Does `harness-mem` reduce total tokens on real continuation tasks?
2. Does `harness-mem` reduce wall-clock completion time?
3. Does `harness-mem` increase first-pass recovery of prior project truth?

If the answer is "sometimes", the benchmark must show **which task types**
benefit and which do not.

## Non-goals

This benchmark is **not** trying to prove:

- raw MCP tool latency in the `codedb-mcp` sense
- retrieval leaderboard superiority over MemPal or other systems
- end-to-end "AI quality" in a subjective sense
- automatic distill quality in a no-LLM environment

Those need separate benchmark surfaces.

## Comparison target

This benchmark is the closest honest counterpart to the kinds of claims often
made by memory systems such as:

- "`~10x token savings`" style progressive-disclosure claims
- "`cost savings, no quality loss`" style routing claims

`harness-mem` should not publish those styles of claims until it has the
matching enabled-vs-disabled evidence on the same task set.

## Benchmark shape

Each task is run twice:

1. `enabled`: normal `harness-mem` flow allowed
2. `disabled`: same client, same model, same repo snapshot, but no
   `harness-mem` reads or writes allowed

The benchmark only compares **paired runs of the same task**.

## Task selection

Use `3-5` tasks. Fewer than `3` is too noisy; more than `5` adds cost before we
have a stable method.

The first benchmark set should contain the following task types:

### T1. Continue a previously discussed repo truth task

Goal: recover a settled repo fact or prior decision without rereading a large
history manually.

Good example:

- "What embedding model is currently the default baseline here, and what is the
  evidence?"

Why include it:

- this is the most direct test of memory-assisted context recovery

### T2. Continue an in-flight release or packet validation thread

Goal: recover what is already done, what remains open, and what must not be
overclaimed.

Good example:

- "What is still missing in the packet full matrix, and what near-neighbor
  evidence already exists?"

Why include it:

- this tests whether `wake` and accepted truth reduce status re-discovery

### T3. Resume a constraint-heavy design decision

Goal: recover prior constraints, accepted boundaries, and non-goals before
suggesting next steps.

Good example:

- "Should dream maintenance rely on a daemon or client-side scheduling?"

Why include it:

- this tests whether memory reduces repeated policy rediscovery

### T4. Retrieve prior operational procedure

Goal: recover a known workflow or user-facing path with minimal re-derivation.

Good example:

- "How should a user recover project context vs distill recent sessions?"

Why include it:

- this tests whether the system helps with procedural continuity

### T5. Optional negative-control task

Goal: include one task that should gain little or nothing from memory.

Good example:

- "Fix a brand-new local syntax error in a newly added file"

Why include it:

- it stops us from publishing a misleading "memory helps everything" story

## Task acceptance rule

Every task must have a binary acceptance check defined **before** running it.

Allowed acceptance styles:

- exact fact recovery
- specific file/path/version recovery
- exact list of remaining gaps
- exact workflow reconstruction

Avoid tasks that need vague human taste to judge correctness.

## Environment controls

For each paired run, hold the following constant:

- same repository commit or same dirty working tree snapshot
- same client family (`Codex`, `Claude Code`, `Cursor`, etc.)
- same model
- same machine
- same workspace path
- same benchmark prompt
- same allowed tool set, except memory on/off

If the client exposes token metrics, record them directly. If not, mark token
count as unavailable rather than estimating loosely.

## Enabled condition

Allowed:

- `wake`
- `search_memory`
- `timeline`
- `get_observations`
- normal `harness-mem` project status checks

Not required:

- `distill`
- candidate writes
- review flows

This benchmark is about **memory retrieval helping active work**, not about
growing the memory base during the run.

## Disabled condition

Disabled means the agent must solve the same task **without using**
`harness-mem` reads or writes.

Disallowed:

- `wake`
- `search_memory`
- `timeline`
- `get_observations`
- any slash wrapper that delegates to the above

Allowed:

- normal repo/file search
- tests
- docs lookup
- shell commands

This is intentionally a strong control: it measures the value of memory versus
plain repo rediscovery.

## Metrics to record

Record the following for every run:

| Metric | Meaning |
|---|---|
| `task_id` | Stable task label such as `T1` |
| `condition` | `enabled` or `disabled` |
| `client` | `Codex`, `Claude Code`, `Cursor`, etc. |
| `model` | Exact model string if visible |
| `workspace_path` | Absolute path used in the run |
| `runtime_seconds` | Wall-clock time from prompt send to final answer |
| `prompt_turns` | Number of user/agent turns needed to finish |
| `followup_count` | Number of clarifying or repair follow-ups required |
| `token_total` | Total tokens if the client reports them |
| `accepted` | `yes` or `no` |
| `acceptance_notes` | Why it passed or failed |
| `memory_calls` | Exact memory tools used; empty in disabled mode |
| `repo_calls` | Key non-memory calls used to solve the task |

Derived metrics for the final report:

- token delta: `disabled - enabled`
- runtime delta: `disabled - enabled`
- turn delta: `disabled - enabled`
- acceptance delta: paired success comparison

## Success criteria

The first benchmark page is worth publishing only if all of the following hold:

1. At least `3` paired tasks are completed cleanly.
2. Each task has a predeclared binary acceptance rule.
3. All artifacts are stored, not summarized from memory later.
4. The report includes at least one task where benefit is small or absent, if
   such a task exists.
5. The report separates "token unavailable" from real zero savings.

## Artifact requirements

For each run, store:

- raw prompt text
- client-facing transcript
- tool call list if visible
- token/runtime readout if visible
- final accepted answer
- acceptance judgment with evidence

Recommended artifact layout:

```text
harness_mem/integration/artifacts/agent-benchmark/
  2026-06-xx/
    T1-enabled-<client>.md
    T1-disabled-<client>.md
    T2-enabled-<client>.md
    T2-disabled-<client>.md
    summary.csv
    report.md
```

## Reporting format

The publishable report should contain:

1. benchmark setup
2. paired result table
3. per-task short analysis
4. what improved
5. what did not improve
6. limitations and threats to validity

Minimum result table shape:

| Task | Condition | Accepted | Runtime (s) | Turns | Tokens | Notes |
|---|---|---|---:|---:|---:|---|

And a paired delta table:

| Task | Token Delta | Runtime Delta | Turn Delta | Outcome |
|---|---:|---:|---:|---|

## Threats to validity

These must be stated explicitly in any public write-up:

- different clients expose different token counters
- user intervention may vary by run
- memory value depends on whether accepted truth already exists
- some tasks benefit more from memory than others
- retrieval benefit is not the same as reasoning quality

## Recommended first execution path

Run the first benchmark in a single client first, preferably the client with the
clearest token/runtime visibility on this machine.

Recommended order:

1. `Codex` if token totals are visible and stable
2. otherwise `Claude Code`
3. otherwise `Cursor`

Do **not** try to make the first benchmark cross-client. Cross-client should be a
follow-up once the single-client method is stable.

## Relationship to other benchmark surfaces

This benchmark complements, not replaces:

- `docs/benchmark/v151-baseline.md` for wake/search latency samples
- `docs/benchmark/v160-baseline.md` for retrieval quality and end-to-end dataset
  runtime
- `docs/benchmark/v162-embedding-shootout.md` for embedding-model selection

In short:

- `v151/v160/v162` answer "how the retrieval/runtime substrate behaves"
- this document answers "whether users actually save work on real tasks"

## Next step after this doc

Once the first `3-5` paired runs exist, add a separate results page rather than
overwriting this methodology file.
