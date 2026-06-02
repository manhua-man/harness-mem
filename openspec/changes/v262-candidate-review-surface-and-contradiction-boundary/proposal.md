## Why

v2.3.1 already introduced `MergeSuggestionCandidate` and
`StaleTruthSuggestionCandidate`, but those suggestion types still sit behind
`metabolism_run` instead of the normal candidate review surface. That leaves a
gap between "the system can propose candidate-only cleanup actions" and "a user
or Agent can review them through the same pending-candidate path used by
`/hm:distill` and MCP review flows."

v2.6.2 should not re-implement metabolism. It should do two narrower things:

1. make existing merge/stale suggestions visible in the normal review surface,
2. define the contradiction/stale boundary for knowledge-cache/wiki-driven
   suggestion work without letting generated/wiki artifacts silently mutate
   truth.

## What Changes

- Extend the MCP/Slash candidate review surface so `list_candidates` includes
  `MergeSuggestionCandidate` and `StaleTruthSuggestionCandidate`.
- Add explicit serializer/read-path support so suggestion candidates can be
  inspected like rules, memory entries, relation facts, supersedes, and
  procedural candidates.
- Define the v2.6.2 contradiction/stale boundary: generated wiki/knowledge
  artifacts may provide evidence for suggestions, but suggestions remain review
  objects and never become hidden truth.
- Keep apply/confirm flows out of this first slice unless the repo already has a
  stable mutation contract to reuse.

## Impact

- This change improves review visibility without widening the default truth
  surface.
- This change does not let generated claims enter wake/search defaults.
- This change does not auto-apply contradiction, stale, or merge suggestions.
