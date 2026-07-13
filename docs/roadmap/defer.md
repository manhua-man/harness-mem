# Deferred work (living list)

Items here are explicitly out of scope for v0.8.15–v0.8.18 PRs unless a dedicated scope-lock amendment says otherwise.

| Item | Reason | Earliest revisit |
|------|--------|------------------|
| Golden CI infrastructure + fixture expansion | Separate read-path benchmark track | v0.8.19+ |
| Admission preflight / grill metadata on `confirm_*` | Write-path governance; not blocking vec0/KNN | v0.8.19+ |
| Rust zero-copy parameter passing | No golden hotspot proof yet | v0.9+ |
| RRF algorithm tuning / adaptive IDF | Needs stable golden gate first | v0.8.20+ |
| PyPI publishing | GitHub Releases are the canonical package channel | not planned |
| Bulk `mcp-router` / `mcp_router` JSON sync | Non-canonical copies; `tool_specs` is source of truth | on demand |
| `mcps/grok_com_github/**` maintenance | Not harness-mem product surface | never in hm PRs |
| Docs reorganization | YAGNI until release hardening lands | post-0.8.18 |
