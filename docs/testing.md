# Testing Strategy

`pytest -q` is the release gate, not the default inner loop.

The suite has grown because it protects CLI/MCP surface truth, storage contracts,
config matrices, wake rendering, roadmap truth, and maintainer-only packet
evidence. Keep those guardrails, but run them at the right cadence.

## Daily Loop

For a narrow change, run the directly touched tests first:

```powershell
python -m pytest tests/path_or_file.py -q
```

When the touched surface is unclear, use the fast maintainer gate:

```powershell
.\scripts\test-fast.ps1
```

On bash-compatible shells:

```bash
./scripts/test-fast.sh
```

The fast gate is a nodeid whitelist, not a directory sweep. It covers
representative high-signal runtime and truth surfaces:

- CLI, MCP, wake-render, and storage smoke tests.
- Reflection job state/schema contracts.
- Config load/write contracts.
- Stale CLI and release-truth documentation guards.
- Wake and session-distill entrypoint truth guards.

If code changed and you want the quick static pass too:

```powershell
.\scripts\test-fast.ps1 -WithStatic
```

```bash
./scripts/test-fast.sh --with-static
```

## Full Gate

Run the full gate for release cuts, large refactors, storage schema changes,
packaging changes, or before publishing a broad status claim:

```powershell
.\scripts\test-full.ps1
```

On bash-compatible shells:

```bash
./scripts/test-full.sh
```

This runs:

```text
python -m pytest -q -p no:cacheprovider --basetemp .tmp/pytest-full
python -m ruff check .
python -m mypy harness_mem
python benchmark-suite/tools/check_release_artifacts.py
```

The checked-in scripts set pytest temp/cache behavior to repo-local `.tmp/`
paths. That keeps Windows sandboxed environments from touching an inaccessible
system `%TEMP%` or `.pytest_cache` while preserving the same test selection.

The benchmark artifact check verifies accepted BENCH run bundles, the tracked
`release-snapshot.json`, and its `claim_readiness` gates. It is intentionally in
the full gate, not the fast gate, because it protects release/status claims
rather than the normal edit-test loop.
In clean checkouts where raw `benchmark-suite/artifacts/*` bundles are absent,
the same command validates the tracked snapshot in `snapshot-only` mode.

## Pruning Rules

Do not delete tests only because the collected item count looks high. First
classify the cost:

- Delete or merge low-value tests that only duplicate another exact assertion.
- Keep matrix tests when they cover state transitions, CLI/MCP contract drift,
  config compatibility, storage schema behavior, or public docs truth.
- Move slow benchmark or release-audit checks behind explicit scripts or markers
  instead of making every small edit pay for them.
- When a test is mostly documenting a maintainer-only truth, prefer one focused
  regression guard over many near-identical prose checks.

As of the 2026-06-06 audit, `pytest --collect-only -q` collected 1147 items from
175 test files. The important metric is not item count; it is whether the default
gate matches the risk of the current change.
