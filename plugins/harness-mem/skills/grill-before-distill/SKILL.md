---
name: grill-before-distill
description: Pressure-test a broad or high-impact harness-mem candidate before promotion. Automatically use for repo-wide rules, architecture, security, release policy, ambiguous scope, or likely overgeneralization; the user does not need to invoke it. Never writes or promotes memory and is skipped for ordinary low-risk candidates.
---

# Grill Before Distill

Pressure-test only the risky conclusion. Return `keep`, `narrow`, `defer`, or `reject`, with the strongest evidence, missing evidence, likely failure mode, and safer wording.

Run when routed by `hm-distill`; do not wait for explicit user invocation.

Do not turn this into a mandatory interview or an extra default MCP round trip. Route concrete evidence gaps to `answer-memory-evidence`; route unresolved product or architecture choices to `ask-memory-boundary`. The runtime Answer Gate remains the promotion authority.
