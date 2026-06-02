## Why

v2.7.0 and v2.7.1 make skills reusable and explicitly activatable, but they
still treat a confirmed skill as static. We already record skill success and
failure signals, and replay-window logic already knows how to identify
low-success skills. The next step is to turn that evidence into reviewed
improvement suggestions without letting the system silently rewrite confirmed
procedures.

## What Changes

- Add a reviewed `skill_revision_suggestion` candidate type.
- Add a detector that scans low-success skills and creates pending revision
  suggestions from skill-result evidence.
- Expose those suggestions through the MCP candidate review surface.
- Keep confirmed skills unchanged even when a suggestion is accepted.

## Impact

- Operators get a focused queue of weak skills to inspect.
- Revision provenance stays attached to concrete failure signals and current
  success metrics.
- The system remains candidate-before-truth; confirmed skills are not
  auto-rewritten.
