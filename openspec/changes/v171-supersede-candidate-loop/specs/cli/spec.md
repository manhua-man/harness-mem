## ADDED Requirements

### Requirement: CLI supersede fallback commands

The CLI SHALL provide fallback commands for creating, confirming, and rejecting supersede candidates.

#### Scenario: Create supersede candidate

```bash
$ harness-mem supersede --target-type confirmed_rule --target-id rule-old --replacement-type confirmed_rule --replacement-id rule-new --reason "new route replaces old" --evidence "docs changed"
Created SupersedeCandidate: <id>
```

#### Scenario: Confirm supersede candidate

```bash
$ harness-mem confirm-supersede <id>
Confirmed SupersedeCandidate: <id>
```

#### Scenario: Reject supersede candidate

```bash
$ harness-mem reject-supersede <id>
Rejected SupersedeCandidate: <id>
```

### Requirement: CLI candidate list includes supersede candidates

`harness-mem candidates` SHALL include supersede candidates in the same review list as other candidate types.

#### Scenario: List pending supersede

```bash
$ harness-mem candidates
# Candidates (demo): 1 items (pending)
  [Supersede] <id>: confirmed_rule -> confirmed_rule
```
