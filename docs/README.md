# harness-mem Docs Index

This index lists the docs that exist in this checkout. Keep it synchronized when adding, renaming, or removing docs.

## PRD Docs

| File | Purpose |
|------|---------|
| `prd-02-roadmap.md` | Current roadmap and phase priorities |
| `prd-07-metrics-risks-decisions.md` | Product positioning risks, metrics, and release gates |
| `prd-09-v1-core-loop.md` | V1 core loop and quality baseline |

## Operating Docs

| File | Purpose |
|------|---------|
| `best-practices.md` | Daily usage guidance |
| `benchmark_system.md` | Benchmark system design |
| `benchmark_v1.md` | V1 benchmark findings |
| `cli-design-expert.md` | CLI design notes |
| `README.md` | This synchronized docs index |
| `roadmap-v13-v14-proposal.md` | Detailed v1.3/v1.4 proposal and current closure notes |
| `roadmap-blindspots-v13-v14.md` | Roadmap blind spots and follow-up ideas |
| `v1.0.1-release-notes.md` | v1.0.1 release notes |

## Workflow Skill Assets

| Path | Purpose |
|------|---------|
| `../session-distill/` | Raw session to packet / session note workflow asset |
| `../mem-distill/` | Existing memory / observations cleanup and consolidation asset |
| `../grill-me/` | Optional pressure-test collaborator for high-risk review conclusions |
| `../answer-me/` | Optional evidence-gathering collaborator for under-evidenced drafts |
| `../ask-me/` | Optional architecture and planning consultation collaborator |

Default promotion chain: `session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only`. Optional collaborators must not be treated as hard dependencies.

## Review Inputs

| File | Purpose |
|------|---------|
| `review-ceo-v13-v14.md` | Product strategy review |
| `review-cli-v13-v14.md` | CLI review |
| `review-design-v13-v14.md` | UX/design review |
| `review-devex-v13-v14.md` | Developer experience review |
| `review-eng-v13-v14.md` | Engineering architecture review |
| `review-health-v13-v14.md` | Health, lint, type, and coverage review |
| `review-linus-v13-v14.md` | Code-quality critique |
| `review-office-hours-v13-v14.md` | Office Hours product critique |

## Maintenance Rule

Review docs are evidence, not live release status. Before publishing a roadmap or release claim, refresh it with the current outputs of `ruff`, `mypy`, `pytest`, and OpenSpec validation.
