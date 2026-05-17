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
}


def doctor_error(code_name: str) -> CliErrorCode:
    """Return a documented doctor error code."""
    return CLI_ERROR_CODES[code_name]


def format_error_summary(error: CliErrorCode) -> str:
    """Render a compact CLI-facing summary line."""
    return f"{error.level.title()}: {error.summary} (code: {error.code})"
