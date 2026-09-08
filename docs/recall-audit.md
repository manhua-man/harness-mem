# Recall Details

> The filename is retained for existing links. The current `0.9.28` product is
> a lightweight memory tool, not a knowledge-audit system.

Normal `search_memory` returns current project memory from SQLite
`knowledge_entries`. Its default result contains readable titles and statements,
plus a project name when the user explicitly searches across projects.

Raw conversations, candidates, processing decisions, receipts, internal IDs,
and ranking details do not appear in the normal result. When troubleshooting
retrieval, explicit diagnostic options may show how the current result was
selected. Those details do not become memory and do not preserve deleted or
replaced knowledge.

The current write path is:

```text
session/source → extract → check → add, replace, delete, or no write
                                  → SQLite knowledge_entries
```

Replacement deletes the old current item and writes the new one. Deletion
removes the current item. There is no knowledge timeline, archived knowledge
copy, mutation history, or knowledge undo.

Older releases exposed more history and governance detail, including a state
event ledger and reversible knowledge changes. Those were historical `0.8.x`
and early `0.9.x` designs and are not the current `0.9.28` memory contract.
