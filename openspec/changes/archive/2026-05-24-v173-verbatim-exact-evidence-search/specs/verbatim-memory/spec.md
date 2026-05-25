# Verbatim Memory Delta

## ADDED Requirements

### Requirement: Observation Exact Index

The verbatim store SHALL maintain a trigram inverted index for observation raw content.

#### Scenario: Save updates exact index

- **WHEN** an observation is saved
- **THEN** trigram postings for `Observation.raw_content` are written
- **AND** regex search can use those postings as candidates

#### Scenario: Soft delete removes exact postings

- **WHEN** an observation is soft-deleted
- **THEN** its trigram postings are removed from exact search

### Requirement: Regex Evidence Search

The verbatim store SHALL support regex search over raw observation text with candidate pruning and exact validation.

#### Scenario: Regex hit

- **WHEN** an observation contains `ERROR-1842`
- **AND** the caller searches `ERROR-\d+`
- **THEN** the observation is returned with a snippet and match span

#### Scenario: Regex miss

- **WHEN** no indexed observation candidate contains the required literal trigrams
- **THEN** the search returns no matches without a full raw-content scan

#### Scenario: Invalid regex

- **WHEN** the regex is invalid
- **THEN** the caller receives an explicit regex error
