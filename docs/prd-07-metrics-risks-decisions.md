# PRD 07: Metrics, Risks, Decisions

This document records product-level risks and release gates that should shape v1.x prioritization.

## Product Positioning Risk

Source: `review-office-hours-v13-v14.md`.

The Office Hours review classifies the current problem as real but mild: cross-session memory loss is painful, but many users can bypass it with one long session, manual `CLAUDE.md` notes, or repeated context setup. The same review classifies the current product shape as closer to a feature than a standalone product while Claude Code or other AI tools could absorb most of the obvious memory value.

### Risk Statement

If the core loop stays as a manual CLI workflow, harness-mem risks being perceived as a useful utility rather than a daily runtime. The moat is thin unless the product proves local-first ownership, multi-client coverage, and auditability in one reliable workflow.

### Counter-Strategy

- Prioritize the closed loop over feature breadth: `ingest -> search/wake -> correct -> confirm/reject -> resume`.
- Make local-first data ownership visible: JSON blobs and SQLite remain inspectable and portable.
- Use multi-client support as differentiation, but only after the current Claude/Codex loop is stable.
- Defer pricing and broad commercialization until 5-10 daily users show repeated use and can name the saved work.

## Release Gates

- The user-visible loop must pass through CLI tests before new platform adapters are added.
- Quality gates must be green before release: `ruff`, `mypy`, `pytest`, and OpenSpec strict validation.
- Roadmap claims must cite live verification or clearly say they are review-derived and may be stale.

