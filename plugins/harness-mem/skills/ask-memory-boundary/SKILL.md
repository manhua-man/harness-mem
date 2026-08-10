---
name: ask-memory-boundary
description: Resolve architecture, product-scope, roadmap, or long-lived-rule boundaries for a harness-mem candidate when evidence alone cannot determine safe durable wording. Automatically use when hm-distill leaves such a boundary unresolved; the user does not need to invoke it. Never writes or promotes memory and is skipped when evidence already decides the claim.
---

# Ask Memory Boundary

Return a concise recommendation, scope, tradeoffs, risks, safer wording, and what must remain out of durable memory until verified or explicitly decided by the user.

Run when routed by `hm-distill`; do not wait for explicit user invocation.

Do not call `govern_memory` or convert design advice into truth. Ask the user only when the remaining uncertainty is their preference, intent, or product decision. The runtime Answer Gate remains the promotion authority.
