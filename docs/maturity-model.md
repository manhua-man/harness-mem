# harness-mem maturity model (v1)

This document replaces the informal **ten-dimension radar** for judging product
readiness. The old ten dimensions map to the six-track model below; the convergence
canvas records **product boundaries and verifiable release evidence** only. It
does not carry forward ten-dimension scores, reference-project peaks, or legacy
canvas completion percentages.

## Purpose

`harness-mem` is a **local-first Agent memory runtime**. Maturity is measured
by whether operators can rely on the daily loop, trust governance, and install
the package — not by feature breadth (wiki, graph DB, PyPI) or reference-project
peaks.

## Three layers

### Layer 1 — Readiness Ladder (six tracks, scored 0–100)

Each track has a one-line acceptance sentence and observable signals (tests,
doctor, MCP contracts, release smoke).

| Track | Weight | Acceptance one-liner |
|-------|--------|----------------------|
| **L1 Memory loop** | 20% | `wake → search → distill → review → dream` runs end-to-end with guided flow and Daily slash surfaces. |
| **L2 Truth & governance** | 25% | Durable truth never silently overwritten; candidates, auto-promote, audit ledger, supersede, and finalize gates hold. |
| **L3 Retrieval & recall** | 15% | Filter-first hybrid recall with stable `recall.steps`, abstention, and vec0 KNN when sqlite-vec is available. |
| **L4 Evidence & distillation** | 20% | Lossless transcript ledger, resumable distill jobs, revision idempotency, and multi-host adapters. |
| **L5 Host integration** | 15% | Hooks, MCP entry, install drift checks, and per-host transcript ingest work for declared hosts. |
| **L6 Ops & release** | 5% | CLI doctor/maintenance, GitHub Release channel, version alignment, MCP export CI. |

**Weighted readiness** = Σ (weight × track score). Report which track pulls the
composite down; do not publish a single number without track breakdown.

### Layer 2 — Scope Ledger (no percentage score)

Four states only:

| State | Meaning |
|-------|---------|
| `shipped` | In product; covered by acceptance tests or release smoke. |
| `in_progress` | Active branch or known gap with owner. |
| `deferred` | Explicitly queued; see `docs/roadmap/defer.md`. |
| `out_of_product` | Intentionally not memory core; do not penalize readiness. |

Examples of `out_of_product`: M10 wiki bridge, PyPI publish, graph DB default,
`code/mcps/grok_com_github/**` maintenance.

### Layer 3 — Claim boundary (checklist, not scored)

Binary yes/no: public docs and agent skills must stay inside verified capability.

- No PyPI-as-canonical-channel claim (GitHub Releases only).
- No global cost-savings claim (`cost_budget` is advisory).
- No broad “memory answer quality” claim from `retrieval_profile=quality` alone.
- No wiki-as-truth or second truth store narrative.
- No silent durable writes outside review / finalize gates.

## Scoring rules

1. **Anchor to evidence** — prefer pytest, contract tests, doctor, release smoke,
   and `get_project_status` / `integration_health` over subjective guesses.
2. **Do not score deferred or out-of-product items** — list them in Scope Ledger.
3. **Regressions lower the track** — a broken export CI lowers L6 even if L2 is strong.
4. **WIP is explicit** — `in_progress` scope items may cap the related track (e.g. L5
   while hooks bootstrap is unfinished).

## Mechanical score rubric (v2)

Numeric track scores are allowed only when they are **mechanically derived** from fixed
checklists. Subjective maintainer estimates (e.g. “feels like 96”) are not valid headline
scores.

### Formula

For each track **L1–L6** (and comparison tracks **D7–D8**):

```text
track_score = Σ earned_points
```

Each track defines checks that sum to **100 points**. A check earns its full points only
when its probe passes:

| Probe kind | Pass rule | Fail / pending rule |
|------------|-----------|---------------------|
| `outcome` | Mapped claim in `.codex/outcomes.json` is `passed` on the current machine run | `failed` → 0 points |
| `fact` | Static repo fact verified in the scoring session (version, pytest collect count, documented implementation) | unverified → 0 points |
| `contract` | Named pytest/script ran in the scoring session and passed | `not_run` or `failed` → 0 points |
| `defer_cap` | Explicit gap in Scope Ledger / defer.md is **closed** | open gap → 0 points for that check |

**Weighted readiness (L1–L6 only)**:

```text
readiness = round( Σ (track_weight × track_score) )
```

Weights match Layer 1: L1 20%, L2 25%, L3 15%, L4 20%, L5 15%, L6 5%.

### Score bands

| Band | Meaning |
|------|---------|
| 90–100 | All mapped outcomes for the track pass; contract checks run in-session also pass |
| 80–89 | Core outcomes pass; minor deferrals or not-run contracts deduct |
| 60–79 | Mixed pass/fail on mapped outcomes |
| 40–59 | Majority weight of mapped outcomes failed |
| 0–39 | Track-critical outcomes largely unproven |

### Canonical checklist location

The live checklist, point weights, and current-machine results are maintained in:

- IDE canvas `harness-mem-convergence.canvas.tsx` (computed UI)
- Outcome source: `python code/tools/outcome-verifier/scripts/verify_outcomes.py --config .codex/outcomes.json`

Re-score after every outcome-verifier run or when contract probes are executed. Do not
copy release-qualification 14/14 into a device headline without a fresh run.

### Reference projects

External products do **not** share harness-mem outcome probes. Compare them with
`docs/reference-projects/` adopt/adapt/reject tables — not with a single competitor
percentile unless an explicit shared checklist exists.

Autonomous isolation outcomes verify **current-release** unattended execution
(`execution_mode=agent`, hook-reentry ledger, no Hook re-entry,
auditable receipt) for the authorized host CLI agent. **Product default mode is
agent** (`enabled=false` turns background off). See
[`docs/background-memory.md`](background-memory.md) and
`docs/roadmap.md`.

## Migration from ten dimensions

| Old dimension | New home |
|---------------|----------|
| ① Wake | L1 sub-capability |
| ② Storage | L3 index + L4 ledger |
| ③ Retrieval | L3 |
| ④ Truth | L2 |
| ⑤ MCP | L5 + L6 |
| ⑥ Temporal | L1/L3 sub-capability |
| ⑦ Wiki | Scope Ledger `out_of_product` |
| ⑧ Cost | Claim boundary |
| ⑨ Maintenance | L1 dream + L4 distill maintenance |
| ⑩ Evidence | L6 + per-track contract tests |

## Current snapshot (v0.9.26)

See `canvases/harness-mem-readiness-v1.canvas.tsx` for the compact architecture panel and
`canvases/harness-mem-convergence.canvas.tsx` for the convergence narrative. The full
Readiness Ladder lives in the IDE panel `harness-mem-readiness-v3.canvas.tsx`. The
source facts are refreshed for `0.9.26`; the published package is
`0.9.26`, and individual device-throughput rows
remain operational measurements rather than a release-quality claim.
It deliberately does not merge repository release maturity with one device's live
operations into one headline. When a numeric headline is shown, it must follow
**Mechanical score rubric (v2)** on the current machine — not release-narrative guesses.

Historical operator snapshot (2026-08-12; not a current throughput claim):

| View | Evidence | Current result |
|------|----------|----------------|
| Release maturity | source package/plugin 0.9.26, exact 27-tool contract, archive cohort acceptance, and seven-host qualification | full Python and Rust release lanes must pass before the next tag CI qualifies built artifacts |
| Runtime alignment | repository/plugin 0.9.26; installed MCPs may remain on an earlier package until upgraded | refresh and restart any older live installation after publication |
| Distill operations | active 2, parked 198, 0.43 completed/day over seven days | `needs-distill`; throughput is the primary operational gap |
| Retrieval feedback | 2 surfaced, no used/ignored/misleading outcomes | insufficient live feedback |

The versioned 0.9.10 canvases remain historical snapshots; the unversioned v1
panel carries the current release evidence.

The public MCP contract currently contains 27 tools (~27.8 KiB compact
`tools/list` JSON). The former low-level suggest/confirm/reject schemas and
registry entries are retired; their private implementations remain behind
`govern_memory` in `mcp/governance_handlers.py`. Read/status/dream/distill
capability modules keep the facade below 900 lines.

## Review cadence

- Update track scores on **semver releases** or when a scope-lock closes.
- Keep Scope Ledger aligned with `docs/roadmap/defer.md`.
- Re-run claim boundary checklist when README, skills, or public MCP schemas change.
