# Design

## Index

`SQLiteIndex` owns an `observation_trigrams` table:

- `ngram TEXT`
- `observation_id TEXT`
- primary key `(ngram, observation_id)`

Only observation raw content is indexed.

## Query

`LocalVerbatimStore.regex_search_observations()`:

1. Compiles the caller regex.
2. Extracts the longest literal fragment from the pattern.
3. Builds trigrams from that fragment.
4. Uses the inverted index to find observation candidates containing every trigram.
5. Reads only those candidate blobs and validates the original regex against `raw_content`.
6. Returns observation identity, match span, candidate count, and a short snippet.

If a regex has no useful literal fragment, the store can fall back to a bounded raw observation scan. If a literal fragment exists but the index has no candidates, the search returns no matches rather than scanning the full store.

## Freshness

- Save: replace trigram postings for the observation.
- Delete: remove postings.
- Soft-delete: remove postings.
- Rebuild: iterate project observations and replace postings.

Doctor reports `HM-301` when project observations exist but the exact index is empty.
