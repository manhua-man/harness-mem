## ADDED Requirements

### Requirement: Shell completion mirrors the current maintenance console

The CLI `--completion` surface MUST reflect the current maintenance-only top
level command set and MUST NOT omit supported namespaces such as `config` and
`integration`.

#### Scenario: bash completion includes current maintenance commands

```text
$ harness-mem --completion bash
... init quickstart doctor import purge maintenance config integration qs ...
```

The generated completion script MUST include `config`, `integration`, and `qs`.

#### Scenario: completion includes namespace actions

- **WHEN** the operator generates completion scripts for a supported shell
- **THEN** `config` action completion includes `get`, `set`, `list`, and `validate`
- **AND** `integration` action completion includes `install-cursor-hook` and `install-claude-hook`
