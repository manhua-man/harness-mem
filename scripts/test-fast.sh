#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

with_static="false"
if [[ "${1:-}" == "--with-static" ]]; then
  with_static="true"
fi

pytest_targets=(
  "tests/cli/test_cli_entrypoint.py"
  "tests/cli/test_search_and_wake.py::test_profile_and_wake_surface_conventions"
  "tests/cli/test_onboarding.py::test_doctor_reports_uninitialized_state"
  "tests/mcp/test_smoke.py::test_initialize"
  "tests/mcp/test_smoke.py::test_tools_list"
  "tests/mcp/test_smoke.py::test_search_memory"
  "tests/mcp/test_smoke.py::test_suggest_confirm_search_and_record_skill"
  "tests/mcp/test_smoke.py::test_prepare_session_distill_returns_one_call_evidence_packet"
  "tests/mcp/test_smoke.py::test_tool_error_message_includes_class_and_message"
  "tests/mcp/test_wake_render_stdout.py"
  "tests/storage/test_memory_entry.py"
  "tests/storage/test_local_structured_store.py"
  "tests/storage/test_sqlite_index.py::test_search_memory_entries"
  "tests/storage/test_sqlite_index.py::test_fts_sync_on_insert"
  "tests/test_reflection_job_state_machine.py"
  "tests/test_reflection_job_schema.py"
  "tests/test_load_merged_config.py"
  "tests/test_config_writer.py::test_set_value_then_load_merged_config_reads_it_back"
  "tests/test_stale_cli_surface.py"
  "tests/test_docs_readme_truth_authority_sync.py"
  "tests/test_usage_docs_truth_authority_sync.py"
  "tests/test_root_truth_authority_sync.py"
  "tests/test_wake_entrypoint_truth.py"
  "tests/test_session_distill_skill_truth.py"
)

echo "Running fast pytest gate..."
python -m pytest -q "${pytest_targets[@]}"

if [[ "$with_static" == "true" ]]; then
  echo "Running static checks..."
  python -m ruff check .
  python -m mypy harness_mem
fi
