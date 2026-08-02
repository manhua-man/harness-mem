# harness-mem maturity model (v1)

This document replaces the informal **ten-dimension radar** for judging product
readiness. The old ten dimensions remain useful as **historical convergence
narrative** (`canvases/harness-mem-convergence-before-after.canvas.tsx`) but
must not be used as the headline completion score.

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
`mcps/grok_com_github/**` maintenance.

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

## Current snapshot (v0.9.10)

See `canvases/harness-mem-readiness-v1.canvas.tsx` for the living panel. As of
2026-08-02:

| Track | Score | Primary gap |
|-------|------:|-------------|
| L1 | 96 | — |
| L2 | 97 | — |
| L3 | 97 | 60-case replay, pre-limit `as_of` filtering, content-hashed batch-index generations, and context-budget traces ship; ranking diversity remains iterative |
| L4 | 99 | Exact offered-job claims, bounded restart recovery, separate truth-preserving/full-erasure paths, native privacy deletion, and receipt-first Storage v2 migration are verified |
| L5 | 99 | Seven-host native transcript→Dream→wake replay, explicit capabilities, and one all-host repair path are verified |
| L6 | 99 | Risk-classified Doctor recovery, compact/full parity, exact 27-tool equality, real sqlite-vec, and install/upgrade/restore release gates are verified |
| **Weighted** | **~98** | **Retrieval ranking remains the main iterative quality track** |

The public MCP contract currently contains 27 tools (~27.8 KiB compact
`tools/list` JSON). The former low-level suggest/confirm/reject schemas and
registry entries are retired; their private implementations remain behind
`govern_memory` in `mcp/governance_handlers.py`. Read/status/dream/distill
capability modules keep the facade below 900 lines.

## Review cadence

- Update track scores on **semver releases** or when a scope-lock closes.
- Keep Scope Ledger aligned with `docs/roadmap/defer.md`.
- Re-run claim boundary checklist when README, skills, or public MCP schemas change.
