## MODIFIED Requirements

### Requirement: CLI exposes maintenance commands only

`harness-mem --help` MUST list only the current maintenance command set:
`init`, `quickstart`, `qs`, `doctor`, `import`, `purge`, `maintenance`,
`config`, and `integration`.

#### Scenario: help text excludes daily memory commands

```text
$ harness-mem --help
usage: harness-mem ... {init,quickstart,qs,doctor,import,purge,maintenance,config,integration} ...
```

The output MUST NOT list `wake`, `search`, `timeline`, `candidates`, `confirm`,
`reject`, `distill`, `search-raw`, or `trace-relations` as subcommands.

### Requirement: CLI exposes config as a maintenance namespace

The CLI MUST expose `config` as a maintenance-only namespace for reading,
writing, listing, and validating TOML configuration files. It MUST remain part
of the maintenance console rather than a daily-memory workflow surface.

#### Scenario: config help stays within maintenance scope

```text
$ harness-mem config --help
usage: harness-mem config {get,set,list,validate} ...
```

The help text MUST describe TOML configuration management and MUST NOT describe
`config` as a memory retrieval, wake, distill, or review command.

### Requirement: CLI exposes integration as a maintenance namespace

The CLI MUST expose `integration` as a maintenance-only namespace for
installing IDE hooks that invoke `python -m harness_mem.host_entry`.

#### Scenario: integration help advertises host-entry installers only

```text
$ harness-mem integration --help
usage: harness-mem integration {install-cursor-hook,install-claude-hook} ...
```

The help text MUST describe IDE hook installation and MUST NOT reintroduce
top-level business commands such as `wake`, `distill`, `ingest`, or
`reflection`.
