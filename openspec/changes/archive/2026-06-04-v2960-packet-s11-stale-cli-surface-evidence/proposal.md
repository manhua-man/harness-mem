## Why

The packet already defined `S11` as a string-scan scenario, but it still lacked
an actual recorded result for the current repo. That left the scenario at the
level of instructions instead of evidence.

## What Changes

- Add a packet entry recording the current scan command and observed hits
- Clarify that the remaining hits are only deletion / anti-guidance references
- Add a focused regression test for the packet entry
- Update release writeback for `v2.9.60`

## Impact

- The packet now records the current stale-CLI scan result as evidence
- The repo still does not overclaim anything beyond the packet-defined scan scope
