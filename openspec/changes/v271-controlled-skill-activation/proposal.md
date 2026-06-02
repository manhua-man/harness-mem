## Why

v2.7.0 made cross-project skills reviewable and searchable, but `wake` still
has only two extremes: no procedural guidance at all, or an out-of-band agent
search that fetches the full skill body. The next step is controlled
activation: let an agent see a small set of compact skill hints at task start
without silently injecting full procedures into the default wake payload.

## What Changes

- Add opt-in compact skill hints to default MCP `wake`.
- Keep default wake unchanged when hints are not explicitly enabled.
- Render hint rows as id/title/reason only; never inline full steps.
- Add an explicit `get_skill` MCP read tool so agents can expand a hinted skill
  on demand.
- Keep skill hints on a separate small budget so they do not squeeze L0/L1/L2
  truth sections.

## Impact

- Agents can discover likely-useful project skills at task start with low token
  cost.
- Procedural detail remains explicit pull, not implicit push.
- The default wake contract and truth surfaces stay stable for existing users.
