# Client Enabled vs Disabled

First-pass prompt pack for paired real-client continuation benchmarks.

Run every task twice:

- `enabled`: the agent may use harness-mem read surfaces such as `wake`,
  `search_memory`, `timeline`, and `get_observations`.
- `disabled`: the agent must not use harness-mem read or write surfaces.

The prompts are intentionally task-level, not implementation-level. They ask the
client to recover prior project truth, then produce a small answer that can be
judged with the checklist before the run starts.

## Files

- `prompts.json`: stable T1-T5 prompt definitions.
- `acceptance_checklist.md`: binary pass/fail rubric for each task and condition.
- `token_usage.schema.json`: result-side token/cost evidence envelope for schema
  v2 paired runs.
- `run_codex_pair.py`: Codex paired runner. It writes a structured
  `token_usage` envelope for each result.
- `../tools/extract_codex_token_usage.py`: privacy-preserving helper that
  extracts only numeric `token_count` fields from Codex JSONL into a sidecar.
- `../tools/apply_token_usage_sidecars.py`: applies sidecars back into
  `results/*.json` and upgrades the run manifest to result schema v2 when every
  result has token evidence.

## Run Rule

Keep the client, model, workspace, repo state, and prompt text fixed across each
enabled/disabled pair. Record every result under `benchmark-suite/artifacts/`
with one result JSON per task/condition and a transcript for each run.

Token/cost evidence is optional but explicit:

- The runner first looks for a token usage sidecar when `--token-usage-dir` is
  provided.
- Sidecar filenames may be `T1-enabled-token-usage.json`, `T1-enabled.json`, or
  `T1.enabled.json`.
- Supported sidecar fields include `total_tokens`, `input_tokens`,
  `cached_input_tokens`, `output_tokens`, `reasoning_tokens`, and `cost_usd`.
- Schema v2 validation requires `token_usage`; `available=true` requires a
  named source and at least one non-negative numeric token/cost field.
- If no sidecar or Codex JSON event usage is available, the result must keep
  `token_usage.available=false` and `token_total="unavailable"`.

Do not publish token-saving or cost-saving deltas unless both enabled and
disabled results in a pair have available token totals from a named source.

Example sidecar extraction:

```bash
python benchmark-suite/tools/extract_codex_token_usage.py ^
  --input C:\\path\\to\\codex-session.jsonl ^
  --output benchmark-suite/artifacts/<run>/notes/T1-enabled-token-usage.json
```

The extractor does not copy prompt, message, or tool-output text into the
sidecar. It only exports numeric token fields and a short provenance note.

Apply sidecars to an existing run before rendering:

```bash
python benchmark-suite/tools/apply_token_usage_sidecars.py ^
  --run-dir benchmark-suite/artifacts/<run>
python benchmark-suite/tools/render_report.py ^
  --run-dir benchmark-suite/artifacts/<run>
python benchmark-suite/tools/validate_run.py ^
  --run-dir benchmark-suite/artifacts/<run>
```
