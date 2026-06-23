# Security Policy

## Reporting

Please do not open a public issue for a vulnerability.

Use GitHub private vulnerability reporting when it is available for this
repository. If that is not available, contact the repository owner directly and
include:

- affected version or commit;
- reproduction steps;
- expected impact;
- whether the issue requires local access, repository access, or a malicious
  MCP client.

## Scope

Security-sensitive areas include:

- local memory storage;
- MCP tool boundaries;
- candidate review and confirmation paths;
- filesystem access during ingest or distillation;
- plugin installation scripts.

## Supported Versions

The current public baseline is `0.8.1`.
