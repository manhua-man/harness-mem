## ADDED Requirements

### Requirement: V2 user test packet distill chain matches the shipped review path

The v2 user test packet's generic distill chain SHALL describe
`auto_review_candidates` as the review step for the default generic MCP
distill path.

#### Scenario: Packet does not teach the older generic MCP review chain

- **WHEN** maintainers update `docs/v2-user-test-packet.md`
- **THEN** its generic MCP distill chain points to `auto_review_candidates`
- **AND** it does not teach `suggest_* -> list_candidates -> auto_review_candidates` as the default generic path
