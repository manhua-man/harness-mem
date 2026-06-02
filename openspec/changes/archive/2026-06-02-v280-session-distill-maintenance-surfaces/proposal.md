## Why

The repo already treats `/hm:mark`, `/hm:prune`, `/hm:review-kb`,
`/hm:prune-kb`, and `/hm:verify-entry` as first-class user-facing maintenance
entries. They appear in the README, plugin docs, slash-command instructions,
and the `session-distill` skill. But the behavior is still defined mostly by a
repo-local script and prompt docs rather than a versioned runtime contract.

That leaves three gaps:

- session closure guardrails are documented, but not anchored in the main
  OpenSpec surface;
- manifest cleanup boundaries are easy to drift because they live in
  implementation-layer tooling;
- knowledge-base review / prune / verify flows are described as product surfaces
  without a formal lifecycle spec.

v2.8.0 should start by formalizing the session-closure and manifest-cleanup
surface. Later v2.8.x slices can cover knowledge-base review, prune, and verify
flows under the same maintenance family.

## What Changes

- Add a formal workflow contract for `/hm:mark` session closure guardrails.
- Add a formal workflow contract for `/hm:prune` manifest cleanup boundaries.
- Define the status model for handled manifest rows, including source-missing
  placeholders and raw-deletion metadata.
- Keep the user-facing surface slash/natural-language first; repo-local scripts
  remain implementation-layer tooling.

## Impact

- Distill maintenance becomes versioned product behavior instead of only a
  script convention.
- Future work on knowledge-base review/prune/verify can build on one shared
  maintenance model.
- The project keeps candidate-before-truth and maintenance-only CLI boundaries.
