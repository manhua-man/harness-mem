# v1.7.3 Verbatim Exact Evidence Search

## Why

Semantic and FTS retrieval are useful for recall, but evidence location often needs exact strings: error codes, paths, function names, and regex-shaped log lines. Before this change, exact evidence lookup either relied on broad FTS behavior or required scanning raw observation blobs.

## What Changes

- Add a minimal trigram inverted index for `Observation.raw_content`.
- Maintain exact-search postings when observations are saved, deleted, or soft-deleted.
- Add regex search that first prunes candidates through the trigram index and then validates with Python `re`.
- Expose exact evidence search through CLI and MCP.
- Add a maintenance rebuild command for old or repaired stores.
- Add doctor health hints for missing exact index data.

## Out Of Scope

- Workspace file/code search.
- Replacing FTS or hybrid semantic search.
- Sparse n-gram optimization beyond the initial trigram implementation.
