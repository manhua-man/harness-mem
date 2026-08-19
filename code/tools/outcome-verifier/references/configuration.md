# Project outcome contract

Store the contract at `.codex/outcomes.json`. Paths and command working directories are resolved from the directory containing `.codex`.

## Minimal contract

```json
{
  "schema_version": 1,
  "project": "example",
  "claims": [
    {
      "id": "artifact_is_usable",
      "description": "The generated artifact exists and can be consumed.",
      "required": true,
      "checks": [
        {
          "id": "consumer_smoke",
          "description": "The real consumer opens the artifact.",
          "evidence_tier": "direct",
          "command": ["{python}", "code/scripts/probe.py", "consumer"],
          "expect": {
            "exit_code": 0,
            "json": {
              "opened": {"equals": true},
              "item_count": {"gte": 1}
            }
          }
        }
      ]
    }
  ]
}
```

## Fields

- `schema_version`: Must be `1`.
- `project`: Human-readable project name.
- `claims`: Non-empty list of outcome claims.
- `claim.id`: Stable machine-readable identifier.
- `claim.description`: User-visible result being proven.
- `claim.required`: Defaults to `true`. Failure of an optional claim makes the overall result `partial`.
- `checks`: Non-empty list. Every claim must contain at least one `direct` check.
- `check.evidence_tier`: `direct` or `supporting`.
- `check.command`: Argument array executed without a shell. Use `{python}` and `{project_root}` placeholders.
- `check.cwd`: Optional path relative to project root.
- `check.timeout_seconds`: Defaults to 60.
- `check.required`: Defaults to `true`.
- `check.expect.exit_code`: Defaults to `0`.
- `check.expect.stdout_contains`: Required substring.
- `check.expect.stdout_regex`: Required regular expression.
- `check.expect.json`: Assertions against a JSON object printed on stdout.

JSON assertion paths use dots, for example `hooks.wake_verified`. Supported assertions are `equals`, `not_equals`, `gte`, `lte`, `contains`, `in`, `exists`, and `regex`. Multiple assertions on the same value are ANDed.

## Verdicts

- `passed`: Every required claim passed and no optional claim failed.
- `partial`: Required claims passed, but an optional claim or optional check failed.
- `failed`: A required probe ran and disproved its claim.
- `blocked`: Required evidence could not be collected, timed out, or the contract is invalid.

Exit codes are `0` for passed, `1` for partial or failed, and `2` for blocked or invalid configuration.
