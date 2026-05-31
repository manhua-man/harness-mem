## Why

v2.5.2 adds file-context recall, but v2.6 still lacks an explicit boundary
between manual authority and future generated wiki/cache outputs. Without that
boundary, a later wiki bridge could quietly mix curated docs, accepted memory,
and generated artifacts into one opaque surface.

v2.6.0 adds the smallest safe foundation: project-scoped manual/generated cache
layout, visible sync mapping, source hashes for incremental compile detection,
and generated-cache cleanup that never touches canonical truth.

## What Changes

- Add a project-scoped knowledge-cache layout with separate `manual/` and
  `generated/` roots under runtime storage.
- Define a visible sync map and source manifest that track accepted-memory and
  curated-doc inputs plus their source hashes.
- Extend project profiles with curated doc paths so manual authority is explicit.
- Extend doctor with read-only knowledge-cache visibility.
- Add maintenance actions to prepare the boundary metadata and clean orphaned
  generated outputs.

## Impact

- This change does not compile wiki claims yet.
- This change does not let generated cache become runtime truth.
- Cleanup only removes generated outputs that are not tracked by the generated
  index; it does not delete accepted memory, rules, relation facts, or docs.
