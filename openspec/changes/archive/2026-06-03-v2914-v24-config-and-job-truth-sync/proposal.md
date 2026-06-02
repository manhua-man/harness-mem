## Why

The shipped v2.4 merged-config loader only recognizes four keys:
`triggers.after_agent`, `triggers.scheduler`, `distill.mode`, and
`worker.mode`. It does not resolve `project_name`, and it does not consult
`active_project.txt`. The shipped queue model also has one durable
`ReflectionJob` type; `review` is a phase of that job, not a separate
`ReviewJob` schema.

But `roadmap-v24` still carried planning-era wording that suggested otherwise.
That can mislead maintainers who use the roadmap as current-truth documentation
after the version line has already shipped.

## What Changes

- Update the remaining v2.4 roadmap wording so the merged-config section only
  describes the shipped recognized-key scope.
- Remove the remaining wording that implied a separate `ReviewJob` schema.
- Add a focused regression test that fails fast if current-truth docs drift back
  to those planning-era statements.

## Impact

- Current docs stop teaching config-loader behavior and queue types the shipped
  runtime does not implement.
- Future doc edits that reintroduce those planning-era statements fail fast in
  CI.
