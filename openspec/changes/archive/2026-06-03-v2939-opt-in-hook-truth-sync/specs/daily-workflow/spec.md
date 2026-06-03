## MODIFIED Requirements

### Requirement: High-visibility product docs must describe hook capability as opt-in default-off

When high-visibility product docs summarize automatic memory behavior, they MUST
distinguish between absent always-on automation and shipped opt-in host-hook
capability rather than collapsing both into an absolute “no IDE hook” claim.

#### Scenario: README and AGENTS describe hooks as opt-in

- **WHEN** a reader opens `README.md` or `AGENTS.md`
- **THEN** the docs say there is no default automatic note-taking path
- **AND** they also say opt-in host hooks / scheduler triggers exist
- **AND** they state the triggers default to `off`
