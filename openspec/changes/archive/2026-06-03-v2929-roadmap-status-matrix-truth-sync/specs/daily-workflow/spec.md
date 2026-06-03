## MODIFIED Requirements

### Requirement: Historical rows in current-truth status matrices use current-truth states

When a current-truth status matrix includes older shipped release rows, those
rows MUST use statuses that are still true in the present, rather than keeping a
time-local release-day label that has since gone stale.

#### Scenario: historical roadmap-status rows are marked completed

- **WHEN** a reader scans historical release rows in `docs/roadmap-status.md`
- **THEN** older rows such as `v2.8.2` and `v2.9.8` are marked `已完成`
- **AND** they are not marked `当前收口基线`
