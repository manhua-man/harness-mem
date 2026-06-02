## Why

`tools/session-distill/bin/session-distill.py` already contains a `prd-sync`
command that scans bundled packets for PRD/roadmap-related topics and can write
an output artifact under `prd-distilled/`. But today that behavior is only a
half-productized script path: it has no user-facing slash instruction, no test
coverage, and no formal OpenSpec boundary around what it may or may not mutate.

Without a contract, a future refactor could silently turn it into a direct PRD
editor or treat it like a project-scoped command that requires cwd resolution,
even though the current behavior is really a maintenance-side candidate
generator.

## What Changes

- Add a formal workflow contract for `/hm:prd-sync [--apply]`.
- Keep the flow candidate-only: it reads bundled packets and may write a
  candidate markdown artifact, but does not mutate canonical PRD/roadmap/docs
  or confirmed truth.
- Make dry-run the default behavior; `--apply` only writes the candidate file.
- Align README, plugin command docs, and session-distill references with the
  new maintenance entry.

## Impact

- `prd-sync` becomes a versioned, testable maintenance surface instead of an
  undocumented helper.
- The maintenance family gains a safe bridge between bundled session evidence
  and later product-doc review work.
- The slash-first, candidate-before-truth boundary remains intact.
