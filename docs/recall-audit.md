# Recall Audit Contract

`harness-mem` 0.8.2 adds an explainable recall wrapper without replacing the
existing governed memory loop.

## What changed

MCP `search_memory` and `trace_relations` now include an additive `recall`
object:

- `evidence`: selected memory, relation, or raw evidence items
- `sources`: drilldown pointers and read surfaces
- `steps`: observable retrieval/trace stages
- `planning`: selected effort and expected result shape
- `status`: `answered`, `partial`, `empty`, or `failed`

Legacy response arrays such as `memory_entries`, `relation_facts`,
`observations`, and `paths` remain in place for compatibility.

## Governance boundary

The recall contract is read-path explanation. It does not turn raw evidence or
pending candidates into durable truth. Durable memory still follows:

```text
observation -> candidate -> review -> confirmed truth
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
