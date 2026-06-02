## 1. Scope model

- [x] 1.1 Extend confirmed skill schema with `scope = project | workspace | global`.
- [x] 1.2 New confirmed skills default to `scope=project` unless a reviewed promotion path explicitly creates a shared skill.
- [x] 1.3 Persist `origin_project`, `source_ids`, and portability metadata for shared skills.
- [x] 1.4 Migrate existing confirmed skills as `scope=project` while preserving project ownership, usage counters, and existing default search behavior.
- [x] 1.5 Verify the scope-model slice does not enable promotion candidates, shared search, or default wake/search inclusion of shared skills before those later tasks are implemented.

## 2. Promotion candidate loop

- [ ] 2.1 Add a reviewed candidate type for promoting a project skill to shared scope.
- [ ] 2.2 Expose promotion candidates through `list_candidates`.
- [ ] 2.3 Confirming a promotion creates or updates a shared skill without mutating unrelated project skills.
- [ ] 2.4 Rejecting a promotion leaves the original project skill unchanged.

## 3. Explicit cross-project search

- [ ] 3.1 Add explicit shared-skill search parameters to MCP `search_skills`.
- [ ] 3.2 Return origin project, scope, source ids, and portability notes in search results.
- [ ] 3.3 Keep default skill search project-scoped.

## 4. Conflict and provenance

- [ ] 4.1 Prefer project-scoped skills over shared skills when both match.
- [ ] 4.2 Surface portability warnings and disabled assumptions before a shared skill is activated.
- [ ] 4.3 Record usage feedback separately for project and shared skills.

## 5. Validation

- [x] 5.1 Add schema/store migration tests.
- [ ] 5.2 Add MCP promotion review tests.
- [ ] 5.3 Add explicit cross-project search tests.
- [x] 5.4 Verify default wake and default skill search do not include shared skills.
