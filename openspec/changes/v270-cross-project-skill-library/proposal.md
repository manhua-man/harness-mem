## Why

v1.8 added project-scoped procedural skills, and v2.3 added usage/result
signals. Those skills are useful inside one project, but repeated workflows
such as release hygiene, validation gates, and evidence-first debugging should
be reusable across projects without silently injecting project-specific
assumptions.

v2.7.0 introduces the library boundary for cross-project skills. The key
product constraint is explicitness: project skills may be promoted to shared
scope only through review, and shared skills are consumed only through explicit
cross-project search or future opt-in hints.

## What Changes

- Add a skill scope model: `project`, `workspace`, and `global`.
- Record `origin_project`, source ids, and portability notes for shared skills.
- Add promotion candidates so a project skill can request shared scope without
  directly mutating the confirmed skill library.
- Define explicit cross-project skill search behavior.
- Preserve project-specific precedence when shared and project skills conflict.

## Impact

- Reusable procedural knowledge can flow across projects.
- Shared skill adoption stays review-gated and source-attributed.
- Default wake/search behavior does not start pulling in global skills.
