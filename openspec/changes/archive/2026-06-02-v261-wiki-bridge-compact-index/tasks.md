## 1. Data model

- [x] 1.1 Define generated claim/index artifact schemas for wiki bridge output.
- [x] 1.2 Represent claim text, topics, entities, authority, and source drilldown pointers.
- [x] 1.3 Keep generated artifacts JSON-serializable and easy to diff.

## 2. Compiler

- [x] 2.1 Add a wiki-bridge compiler that reads accepted memory + curated docs.
- [x] 2.2 Write outputs only under `knowledge-cache/generated/`.
- [x] 2.3 Reuse source-manifest hashes to support incremental rebuild / stale detection.

## 3. Compact index and drilldown

- [x] 3.1 Build a compact claim index keyed by claim/topic/entity/source ids.
- [x] 3.2 Add drawer-style drilldown back to memory/doc source.
- [x] 3.3 Ensure generated claims never appear as confirmed truth in wake/search defaults.

## 4. Visibility

- [x] 4.1 Add operator-visible docs for authority levels.
- [x] 4.2 Add doctor or read-path visibility for generated claim/index counts.
- [x] 4.3 Add a maintenance entry point to rebuild the wiki bridge explicitly.

## 5. Validation

- [x] 5.1 Add focused tests for compiler output, drilldown fidelity, and no-hidden-truth boundary.
- [x] 5.2 Run `python -m pytest -q`
- [x] 5.3 Run `python -m ruff check harness_mem tests`
- [x] 5.4 Run `python -m mypy harness_mem`
