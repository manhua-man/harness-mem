"""Shared CLI error-code catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CliErrorCode:
    """Documented CLI error or warning with a default repair command."""

    code: str
    level: str
    summary: str
    fix_command: str
    note: str


CLI_ERROR_CODES: dict[str, CliErrorCode] = {
    "doctor_not_initialized": CliErrorCode(
        code="HM-001",
        level="error",
        summary="harness-mem data directory has not been initialized yet.",
        fix_command="harness-mem quickstart",
        note="Creates the local runtime directory and walks through first-time setup.",
    ),
    "doctor_no_active_project": CliErrorCode(
        code="HM-002",
        level="warning",
        summary="doctor has no project context to inspect.",
        fix_command="harness-mem use <project-name>",
        note="Sets the active project so doctor can inspect project-scoped memory and sessions.",
    ),
    "doctor_wake_budget_large": CliErrorCode(
        code="HM-003",
        level="warning",
        summary="wake-up context is trending too large for a lightweight resume.",
        fix_command="harness-mem purge -p <project-name> --before <yyyy-mm-dd> --category all --dry-run",
        note="Preview archival candidates before the wake-up payload grows further.",
    ),
    "doctor_wake_bucket_quota_sum": CliErrorCode(
        code="HM-101",
        level="error",
        summary="wake bucket quotas must sum to 1.0.",
        fix_command="edit ~/.harness-mem/config.toml [wake] bucket_quota_* (default: 0.5 / 0.5 / 0.0)",
        note="Three quota values for semantic / episodic / procedural buckets must total 1.0; tolerance is 0.001.",
    ),
    "doctor_wake_bucket_quota_range": CliErrorCode(
        code="HM-102",
        level="error",
        summary="wake bucket quota out of range.",
        fix_command="edit ~/.harness-mem/config.toml [wake] bucket_quota_* (each value in [0.0, 1.0])",
        note="Each bucket_quota_* value must be a finite float in [0.0, 1.0].",
    ),
    "doctor_unused_confirmed_rules": CliErrorCode(
        code="HM-401",
        level="warning",
        summary="confirmed rules have not been surfaced in any wake-up for the configured retention window.",
        fix_command="harness-mem rules  # review unused rules; manually reject or supersede stale ones",
        note=(
            "Rules with usage_count == 0 or last_surfaced_at older than the retention window are likely "
            "no longer relevant. doctor only flags them; deletion remains a deliberate human action."
        ),
    ),
}


def doctor_error(code_name: str) -> CliErrorCode:
    """Return a documented doctor error code."""
    return CLI_ERROR_CODES[code_name]


def format_error_summary(error: CliErrorCode) -> str:
    """Render a compact CLI-facing summary line."""
    return f"{error.level.title()}: {error.summary} (code: {error.code})"
