## Why

v2.6.0 makes the knowledge-cache boundary explicit, but it still does not
produce the compact, searchable wiki-style layer that Agents actually need at
read time. Today an Agent can search accepted memory and raw evidence directly,
but it cannot first inspect a small claim/topic/entity index with tight source
provenance and then drill down only when needed.

v2.6.1 adds the smallest useful wiki bridge: compile accepted memory and
curated docs into generated claim/index artifacts, keep every generated claim
traceable back to memory/doc sources, and keep generated artifacts outside
runtime truth.

## What Changes

- Add a wiki-bridge compiler that reads accepted memory plus curated docs and
  writes generated knowledge-cache artifacts.
- Add a compact claim index with claim/topic/entity/source references.
- Add drawer-style drilldown pointers so every claim can jump back to memory,
  observation, or curated-doc source.
- Add explicit authority markers so generated outputs never masquerade as
  confirmed truth.
- Extend docs and read surfaces so users and Agents can understand manual vs
  accepted vs generated authority levels.

## Impact

- This change introduces generated wiki/index artifacts under the knowledge
  cache's `generated/` root.
- This change does not let generated claims enter wake/current truth by
  default.
- Contradiction, stale, and merge suggestions remain deferred to v2.6.2.
