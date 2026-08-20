---
name: "Harness: Init"
description: Ground this repository and safely initialize its AI truth files
category: Harness
tags: [harness, agents, protocol, initialization]
---

Run the agent-native Harness initialization workflow against the current workspace.

## Allowed Targets

- `<workspace>/AGENTS.md` — verifiable project facts.
- `<workspace>/CLAUDE.md` — collaboration protocol.
- `<workspace>/DESIGN.md` — conditional product, visual, content, or DX direction.
- `<workspace>/steering/harness-recommendations.md` — conditional project-specific scoped overrides.
- Cursor adapter pair when `.cursor/` exists:
  - `<workspace>/.cursor/rules/harness.mdc`
  - `<workspace>/.cursor/commands/harness-init.md`

Write nothing outside this set.

## Five Phases

1. **Ground** — inspect the workspace, manifests, README, existing truth files, tool traces, and design-surface evidence. Every fact must name a path that supports it.
2. **Read** — always read existing root truth files, top README, manifests, `steering/*.md`, and depth-one Cursor/Kiro rules or commands. Limit optional source and documentation reads to 30 files or 200 KB.
3. **Judge and draft** — select exactly one action per target: `create`, `patch-section`, `overwrite`, or `skip`. Draft exact bytes in memory and sanity-check them against grounded evidence.
4. **Show and confirm** — display one line per absolute target path:

   ```text
   <absolute-path> | action: <create|overwrite|patch-section|skip> | evidence: <one sentence>
   ```

   Then ask exactly: `Apply these changes? Reply yes or no.` Write nothing unless the reply is exactly `yes`.
5. **Apply** — write only the confirmed bytes. Create only required parent directories, re-read every target, and report applied, skipped, failed, or mismatched paths.

## Safety Rules

- Existing files without Harness-managed `##` sections may be patched by section or skipped; never overwrite them wholesale.
- A section patch preserves every byte outside the target `##` section.
- Create `DESIGN.md` only when the repository has a real UI, product, content, brand, documentation, plugin, or DX surface.
- Create steering only for concrete project-specific scoped overrides; never create placeholder steering.
- Keep all root truth bodies in one resolved locale.
- Root `AGENTS.md`, `CLAUDE.md`, and `steering/*.md` have no YAML frontmatter.
- Do not require Node, npm, npx, tsx, a package manager, external LLM API, detector JSON, or `.harness/runs/` artifacts.
- Preserve unrelated user changes and never use a broad Git reset for rollback.
