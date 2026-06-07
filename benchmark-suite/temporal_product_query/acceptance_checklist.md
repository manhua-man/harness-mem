# Acceptance Checklist: `temporal_product_query`

Use this checklist before judging any TQ1-TQ5 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `temporal_product_query`.
- [ ] `condition` is `temporal_guarded`.
- [ ] Transcript exists.
- [ ] The answer separates current truth, historical truth, and missing evidence.
- [ ] The answer cites concrete source files, ids, timestamps, or says the
      evidence is unavailable.

## TQ1: Default Current-Only Read

Pass requires all of:

- [ ] Returns current truth by default.
- [ ] Excludes superseded historical truth from the default answer.
- [ ] Mentions history only as optional drilldown if relevant.

Primary failure signals:

- Includes old superseded truth as current.

## TQ2: Explicit History Request

Pass requires all of:

- [ ] Surfaces historical truth when explicitly requested.
- [ ] Labels it as historical/superseded.
- [ ] Does not replace current truth with history.

Primary failure signals:

- Refuses to show history when asked.
- Presents history without status labels.

## TQ3: `as_of` Query

Pass requires all of:

- [ ] Uses timestamp or version evidence when available.
- [ ] States when `as_of` cannot be answered from current product evidence.
- [ ] Does not fabricate a time-travel answer.

Primary failure signals:

- Invents an `as_of` result without evidence.

## TQ4: Supersede Timeline

Pass requires all of:

- [ ] Identifies old and new truth.
- [ ] Names the supersede direction.
- [ ] Explains why default reads should prefer the new truth.

Primary failure signals:

- Reverses supersede direction.
- Omits the old truth from an explicit timeline answer.

## TQ5: Ambiguous Temporal Scope

Pass requires all of:

- [ ] Detects that the query is ambiguous.
- [ ] Asks for scope or gives a qualified answer.
- [ ] Does not collapse current, history, and `as_of` into one claim.

Primary failure signals:

- Gives a confident temporal answer when scope is missing.
