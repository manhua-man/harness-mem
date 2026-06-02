## 1. Boundary model

- [x] 1.1 Add runtime helpers for project-scoped knowledge-cache paths.
- [x] 1.2 Split manual and generated directories and persist placeholder metadata.
- [x] 1.3 Add source manifest + sync map with accepted-memory and curated-doc sources.

## 2. Source authority and hashes

- [x] 2.1 Extend `ProjectProfile` with curated doc paths.
- [x] 2.2 Hash accepted memory and curated docs into a source manifest.
- [x] 2.3 Detect stale / missing sources by comparing the current hash set to the stored manifest.

## 3. Visibility and maintenance

- [x] 3.1 Extend doctor with a read-only knowledge-cache block.
- [x] 3.2 Add `maintenance prepare-knowledge-cache`.
- [x] 3.3 Add `maintenance cleanup-generated-cache`.

## 4. Validation

- [x] 4.1 Add focused tests for layout, stale detection, and cleanup invariants.
- [x] 4.2 Run `python -m pytest -q`
- [x] 4.3 Run `python -m ruff check harness_mem tests`
- [x] 4.4 Run `python -m mypy harness_mem`
