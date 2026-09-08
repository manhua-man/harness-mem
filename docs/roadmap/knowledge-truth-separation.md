# Current Memory Storage

This document describes the current `0.9.28` storage contract. Earlier plans in
the `0.9.16`--`0.9.27` line used knowledge versions, mutation records, archived
knowledge, and undo. Those parts have been removed from the current design.

## One current memory

SQLite `knowledge_entries` is the only source of current long-term memory.
Normal wake, search, counting, Review, Dream, and successful-write checks all
use it.

The rules are deliberately small:

- add a new fact by writing one current row;
- correct a fact by deleting the old row and writing the replacement in one
  transaction;
- remove an invalid fact by deleting its current row;
- do not keep old knowledge versions, archived knowledge copies, knowledge
  change records, or undo data.

`knowledge_sources` may retain the minimum source link needed to check whether a
current item is supported. The source is not another memory item and does not
make deleted knowledge current again.

## Other stored data

Not everything in the data directory is memory:

| Data | Purpose | Current memory? |
|---|---|---|
| `knowledge_entries` | Current reusable project facts | Yes |
| `knowledge_sources` | Minimum source links for current facts | No |
| Native session revisions and chunks | Source material for session processing | No |
| Candidate, evidence, and proposed-decision rows | Temporary work for retry or an unfinished task | No |
| Job, lease, receipt, and idempotency rows | Safe background processing | No |
| Session Note | Readable summary of one processed session | No |
| Legacy `memory_entries` | Old compatibility data | No |
| FTS/vector/Markdown projections | Rebuildable views of current rows | No |

Successful jobs clean temporary processing material according to policy.
Unfinished work may keep only what it needs to resume. Transaction and retry
data must never be shown or counted as memory.

## Write and read checks

Session processing follows this order:

```text
complete source
→ extract separate points
→ check each point
→ decide add / replace / no write / unfinished
→ change knowledge_entries in one SQLite transaction
→ read the result through ordinary project search
→ only then report success
```

After an add or replacement, ordinary search must find the new wording. After a
replacement or deletion, ordinary search must not return the old wording. A job
stays unfinished if either check fails.

The operation may be retried safely through its idempotency key, but retry state
does not preserve a knowledge history. Once a current item is replaced or
deleted, harness-mem does not offer knowledge undo.

## Compatibility

Old `MemoryEntry` rows remain readable during the `0.9.x` compatibility period.
They do not participate in current search, current counts, write success, or
Dream/Review decisions. Normal startup does not migrate, rewrite, or delete
them.

New databases do not create `knowledge_versions` or `knowledge_mutations`.
Existing installations may still contain those old tables; `0.9.28` leaves the
tables untouched and does not read or write them as current memory.

## Session archives and Notes

An archived conversation is source material, not archived knowledge. Processing
an archived conversation may add, replace, or delete current memory after each
point is checked. A conversation with nothing worth keeping still receives a
clear no-write result.

A Session Note is only a readable summary of what happened in that conversation
processing job. It is not an immutable proof, a knowledge version, or a way to
restore deleted knowledge.

## Safe maintenance

Real-data maintenance requires an explicit project scope and one writer during
the maintenance window. It does not make automatic backups. A successful,
user-requested processing run may delete only the selected session's source,
matching host-history file, and its generated Session Note; it creates no
session backup. Dream keeps its source and Note as an archive. Failed,
unfinished, unsupported, or ambiguous sources remain untouched.

Every real maintenance run must be explicitly authorized for one project and
the concrete current scope selected by its operator. Recompute that project's
knowledge and archive inventory before the run; do not reuse an old archive
count. Other projects and archives whose project cannot be established are out
of scope.

For every change:

1. read the current project list from `knowledge_entries`;
2. check the original source;
3. add, replace, or delete through the normal harness-mem path;
4. immediately search for the new and old wording;
5. stop the batch on a disconnected MCP, wrong runtime version, failed readback,
   or cross-project write.

## Required tests

The storage and user-path checks must prove:

- a new database creates current knowledge and source tables without knowledge
  version or mutation tables;
- replacement leaves only the new current item;
- deletion removes the item and its current source links;
- retries do not create duplicates;
- normal search and counts read only `knowledge_entries`;
- the public MCP surface has 20 tools and does not expose `temporal_query` or
  `undo_dream_item`;
- finalize reports success only after ordinary search reads the change back;
- project isolation and the operator-selected maintenance boundary hold.
