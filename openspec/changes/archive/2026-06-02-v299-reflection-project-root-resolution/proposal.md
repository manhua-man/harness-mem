## Why

The shared reflection business command already has a commands-layer project-root
resolver, but `reflection_once(...)` still defaulted straight to the caller's
cwd whenever `project_root` was omitted. That makes hand-driven calls less
stable than they need to be and leaves a stale TODO in the runtime contract.

## What Changes

- Resolve `project_root` through the commands-layer known-root lookup before
  falling back to cwd.
- Add focused regression tests for the known-root path and the cwd fallback.
- Record the v2.9.9 slice in spec, roadmap, status, changelog, and version
  metadata.

## Impact

- Reflection jobs created without an explicit `project_root` now preserve a
  more accurate project provenance when the repo can already be located.
- The remaining cwd fallback stays intact for manual or ad-hoc invocations.
