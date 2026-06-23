# Changelog

## Unreleased

### Added

- Added a reproducible cold-start demo guide for the
  `wake -> search -> distill -> review` product path.

## [0.8.1] - 2026-06-24

### Changed

- Reset the public repository around the core product definition:
  **local-first, auditable, pluggable Agent memory backend**.
- Kept the runtime source code public under `harness_mem/`.
- Kept the Agent integration layer public under `plugins/harness-mem/`.
- Kept the session distillation reference skill public under
  `tools/session-distill/`.
- Reduced public documentation to the README, Chinese README, quickstart, MCP
  setup notes, changelog, license, security policy, and public README assets.
- Pruned non-product repository materials from the public baseline.
- Removed maintainer-only evaluation reporting from the public runtime surface.

### Validation

- `python -m compileall harness_mem`
- `python -m harness_mem.cli --help`
- `python -m ruff check harness_mem plugins tools`
- `cargo test --workspace`
