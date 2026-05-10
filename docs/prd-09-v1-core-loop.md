# PRD 09: V1 Core Loop

This document defines the V1 operational loop and the quality baseline required before extending the product surface.

## Core Loop

The V1 loop is:

1. `ingest`: bring recent local sessions into the memory store.
2. `search` / `wake-up`: retrieve useful project context.
3. `correct`: turn user corrections into rule candidates.
4. `confirm-rule` / `reject-rule`: curate the rule set.
5. `handoff`: preserve task state for the next session.

The Office Hours review warns that harness-mem is not meaningfully better than asking the assistant again unless this loop is reliable. That makes loop stability higher priority than adding new adapters or new memory types.

## Quality Baseline

Source: `review-health-v13-v14.md`.

The health review called out lint/type debt and missing direct storage tests as release risks. The baseline for V1 work is now:

- `python -m ruff check .`
- `python -m mypy harness_mem`
- `python -m pytest -q`
- `openspec validate --all --strict`

Storage behavior must have direct tests, not only CLI-level coverage. At minimum, `local_structured_store.py` and `sqlite_index.py` should cover blob/index synchronization, soft delete filtering, FTS insert/update/delete behavior, and task handoff ordering.

## Current Quality Policy

- Type errors and lint errors block feature work unless the feature fixes a user-visible outage.
- User-facing CLI validation bugs rank above internal refactors.
- Review reports are source evidence, but stale numeric counts must be refreshed against the current checkout before being used as release status.

