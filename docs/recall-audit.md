# Recall Audit Contract

This contract originated in `harness-mem` 0.8.9 and remains the current 0.9.x
explainable recall boundary. It does not replace the governed memory loop.
Trust hardening, retrieval quality, and maintenance closure extend the read and
governance paths documented below.

## What changed

Normal MCP `search_memory` returns a compact `memories` list containing only
canonical `title` and `statement` prose. It does not expose record IDs,
provenance, scores, source kinds, raw observations, or lifecycle diagnostics.
Cross-project search includes the project name because that scope is needed to
interpret a result.

Explicit `search_memory(deep_recall=true)` and the dedicated raw/timeline/audit
tools retain the diagnostic read contract. That detailed mode includes an
additive `recall` object:

- `evidence`: selected memory, relation, or raw evidence items
- `sources`: drilldown pointers and read surfaces
- `steps`: observable retrieval/trace stages
- `planning`: selected effort and expected result shape
- `status`: `answered`, `partial`, `empty`, or `failed`

For detailed `search_memory`, recall steps are stable and additive:

```text
filter -> fts -> vector -> merge -> hydrate -> context
```

Skipped stages stay present with `status: skipped`. Evidence can include
optional `metadata.score_details` (`fts_score`, `vector_score`, `rrf_score`,
`boosts`, `confidence_tier`, and `fts_match_count`) without changing
`RECALL_RESULT_SCHEMA_VERSION`.

Weak multi-token matches can now be filtered by low-confidence abstention. The
search response records this in `retrieval_quality.abstention`; additive recall
then returns `empty` or `partial` from the remaining evidence instead of
presenting a single-token hit as confident context.

Decision entries can receive a small explainable 1-hop relation boost when a
returned relation fact shares source/target entity tokens with the decision.
The boost appears in `metadata.score_details.boosts` as `one_hop_relation`.

Detailed responses retain the `memory_entries`, `relation_facts`,
`observations`, and `recall` diagnostic structures. They are not part of the
ordinary long-term-memory view.

Surface boundary: `search_memory` and `trace_relations` are part of the single
public MCP memory surface. They are read-path tools; they do not create or
confirm candidates.

## Governance boundary

The recall contract is read-path explanation. It does not turn raw evidence or
job-scoped candidates into durable truth. Current durable memory follows:

```text
immutable session/source -> candidate + evidence -> Answer Gate -> assimilation
                                                     -> SQLite knowledge_entries
Dream / review -> source-backed recheck, correction, or reversible undo
```

## State audit ledger

MCP and CLI review/suggest surfaces append governance events to:

```text
~/.harness-mem/data/state-events.log
```

Use:

```bash
harness-mem maintenance state-audit -p <project>
```

The ledger is append-only and local. It records governance transitions such as
candidate creation, confirmation, rejection, and supersede completion. It is not
a replacement for source blobs or SQLite indexes; it is the audit trail that
explains how durable truth changed. The command also replays the ledger into a
latest-state projection so audits can see each target's most recent governance
status.
