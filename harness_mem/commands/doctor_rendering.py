"""Doctor CLI rendering with no probe-side mutations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS
from harness_mem.hook_runtime import HookRuntimeReport
from harness_mem.version import runtime_version_payload
from harness_mem.commands.doctor_probes import (
    _CANDIDATE_TABLE_KEYS,
    _SIGNAL_FRESHNESS_TYPES,
)

logger = logging.getLogger(__name__)

_CANDIDATE_STALE_FIX = "Use hm to review or correct this memory"
_CANDIDATE_HIGH_RISK_FIX = "Use hm to review or correct this memory"


def _doctor_legacy_accepted_block(legacy_report: dict[str, Any]) -> None:
    """Report legacy ``status=accepted`` blobs (invisible to readable_truth)."""
    if "warnings" in legacy_report:
        for warning in legacy_report["warnings"]:
            print(f"⚠️  Legacy accepted scan unavailable: {warning}")
        return

    total = int(legacy_report.get("total", 0))
    by_table = legacy_report.get("by_table") or {}
    if total <= 0:
        print(
            f"Legacy status={LEGACY_ACCEPTED_STATUS}: 0 records "
            "(invisible to readable_truth; governance migration complete)"
        )
        return

    parts = ", ".join(f"{table}={count}" for table, count in sorted(by_table.items()))
    print(
        f"⚠️  Legacy status={LEGACY_ACCEPTED_STATUS}: {total} record(s) ({parts}) "
        "— invisible to readable_truth; preview with `harness-mem maintenance "
        "migrate-legacy-accepted --dry-run`, then use hm to audit pending rows"
    )


def _doctor_candidate_health_block(candidate_report: dict[str, Any]) -> None:
    """Render the candidate-health slice of a local health payload.

    Silent absence (Req 2.5): a table only produces output when it has at
    least one stale pending candidate — no "0 stale" filler. High-risk-stale
    candidates (stale + low confidence) get a separate escalated bullet
    (Req 2.4). Degraded shape (``{"warnings": [...]}`` per Req 6.7) is
    rendered as warning lines instead of the normal aggregate.
    """
    if "warnings" in candidate_report:
        for warning in candidate_report["warnings"]:
            print(f"⚠️  Candidate health unavailable: {warning}")
        return

    printed_header = False
    for table in _CANDIDATE_TABLE_KEYS:
        summary = candidate_report.get(table)
        if not summary:
            continue
        stale_count = summary.get("stale_count", 0)
        if stale_count <= 0:
            continue
        if not printed_header:
            print("Candidate health:")
            printed_header = True
        print(
            f"⚠️  {table}: {stale_count} stale pending candidate(s). "
            f"Fix: {_CANDIDATE_STALE_FIX}"
        )
        high_risk = summary.get("high_risk_stale_count")
        if high_risk is not None and high_risk > 0:
            print(
                f"    ⚠️  {table}: {high_risk} high-risk stale (low confidence). "
                f"Fix: {_CANDIDATE_HIGH_RISK_FIX}"
            )


def _doctor_signal_freshness_block(
    signal_report: dict[str, Any], project_name: str
) -> None:
    """Render the signal-freshness slice of a local health payload.

    Info-level only (Req 3.4): dormancy may be intentional, so this block
    never escalates to a warning. When every signal type is silent
    (``all_silent``) it emits one summary line naming the project rather than
    five "never" lines (Req 3.7). Otherwise it emits one info line per
    Dormant_Signal_Type (Req 3.3); fresh types stay silent (Req 3.5).
    Degraded shape (Req 6.7) renders as warning lines.
    """
    if "warnings" in signal_report:
        for warning in signal_report["warnings"]:
            print(f"⚠️  Signal freshness unavailable: {warning}")
        return

    if signal_report.get("all_silent"):
        print(
            "Signal freshness: no retrieval signals recorded yet for project "
            f"{project_name}"
        )
        return

    printed_header = False
    for signal_type in _SIGNAL_FRESHNESS_TYPES:
        summary = signal_report.get(signal_type)
        if not summary or not summary.get("is_dormant"):
            continue
        if not printed_header:
            print("Signal freshness:")
            printed_header = True
        latest = summary.get("latest_timestamp")
        if latest is None:
            print(f"  {signal_type}: dormant (last event: never)")
        else:
            age_days = (summary.get("age_seconds") or 0) // 86400
            print(f"  {signal_type}: dormant (last event: {latest}, {age_days}d ago)")


def _doctor_maintenance_block(maintenance_report: dict[str, Any]) -> None:
    """Render the maintenance-hints slice of a local health payload.

    Silent absence (Req 5.3): nothing is printed when the hint list is empty.
    Each hint preserves the underlying index-health ``message`` and
    ``fix_command`` verbatim (Req 5.2 / 5.5) so operator-visible text is
    unchanged from the previous inline emissions — only the grouping moved
    under a single "Maintenance" heading. Degraded shape (Req 6.7) renders as
    warning lines.
    """
    if "warnings" in maintenance_report:
        for warning in maintenance_report["warnings"]:
            print(f"⚠️  Maintenance hints unavailable: {warning}")
        return

    hints = maintenance_report.get("hints", [])
    if not hints:
        return

    print("Maintenance:")
    for hint in hints:
        print(f"⚠️  {hint['message']}")
        print(f"Fix: {hint['fix_command']}")


def _doctor_runtime_health_block(runtime_report: dict[str, Any]) -> None:
    if not runtime_report:
        return
    if "warnings" in runtime_report:
        for warning in runtime_report["warnings"]:
            print(f"⚠️  Runtime health unavailable: {warning}")
        return
    print("Runtime health:")
    versions = runtime_version_payload()
    print(
        "  versions: "
        f"runtime={versions['runtime_version']} | wire={versions['wire_format_version']}"
    )
    jobs = runtime_report.get("job_health", {})
    dream = jobs.get("dream", {})
    print(
        "  dream maintenance: "
        f"last={dream.get('last_status') or 'none'}, "
        f"failures={dream.get('failure_count', 0)}, "
        f"retryable={dream.get('retryable_count', 0)}"
    )
    retrieval = runtime_report.get("retrieval_health", {})
    surfaces = retrieval.get("surfaces", [])
    if surfaces:
        high = sum(int(row.get("high_output_calls") or 0) for row in surfaces)
        print(
            f"  retrieval: {len(surfaces)} active surface(s), {high} high-cost call(s)"
        )
    drift = runtime_report.get("version_drift", {})
    if drift.get("has_drift"):
        print(f"⚠️  version/install drift: {len(drift.get('issues', []))} issue(s)")
        for issue in drift.get("issues", [])[:3]:
            print(f"    {issue.get('surface')}: {issue.get('message')}")


def _doctor_storage_v2_block(storage_report: dict[str, Any]) -> None:
    if not storage_report:
        return
    if "warnings" in storage_report:
        for warning in storage_report["warnings"]:
            print(f"⚠️  Storage v2 health unavailable: {warning}")
        return
    status = storage_report.get("status") or "unknown"
    runtime_state = storage_report.get("runtime_state") or "canonical"
    print("Storage v2:")
    print(f"  runtime truth: {runtime_state}")
    print(
        "  canonical: "
        f"{status} | rows={storage_report.get('canonical_row_count', 0)} | "
        f"legacy={storage_report.get('legacy_json_file_count', 0)}"
    )
    print(
        "  checksum: "
        f"{'match' if storage_report.get('checksum_match') else 'not matched'} | "
        f"wal={storage_report.get('wal_size_bytes', 0)} bytes"
    )
    relation = storage_report.get("checksum_relation")
    explanation = storage_report.get("checksum_relation_explanation")
    if relation:
        print(f"  checksum relation: {relation}")
    if explanation and relation != "exact_match":
        print(f"  relation detail: {explanation}")
    gate = storage_report.get("dual_write_gate") or {}
    if gate:
        print(
            "  dual-write: "
            f"{'enabled' if gate.get('enabled') else 'off'} ({gate.get('env')})"
        )
    legacy_policy = storage_report.get("legacy_reader_policy") or {}
    if legacy_policy:
        print(
            "  legacy reader: "
            f"{legacy_policy.get('conversion_status', 'unknown')} | "
            f"supported through {legacy_policy.get('supported_through')} | "
            "removal no earlier than "
            f"{legacy_policy.get('earliest_removal_version')} and "
            f"{legacy_policy.get('earliest_removal_date')}"
        )
        if legacy_policy.get("conversion_status") == "migration_required":
            print(
                f"  migration preview: {legacy_policy.get('migration_preview_command')}"
            )
    if status != "healthy" and storage_report.get("fix_command"):
        print(f"⚠️  Storage v2: {status} ({runtime_state})")
        print(f"Fix: {storage_report['fix_command']}")
    recovery_hint = storage_report.get("recovery_hint")
    if (
        isinstance(recovery_hint, str)
        and recovery_hint
        and runtime_state == "degraded_fallback"
    ):
        print(f"  recovery: {recovery_hint}")
    drift = storage_report.get("index_drift") or []
    if drift:
        print(f"⚠️  Storage v2 index drift: {len(drift)} missing index(es)")


def _doctor_recovery_plan_block(plan: Mapping[str, Any]) -> None:
    """Render a structured plan without executing any recovery command."""

    assessment = str(plan.get("assessment") or "unknown")
    items = list(plan.get("items") or [])
    print(f"Recovery plan: {assessment} (read-only, {len(items)} action(s))")
    summary = plan.get("summary")
    if summary:
        print(f"  {summary}")
    for item in items:
        action_class = item.get("action_class") or "manual_review"
        risk = item.get("risk") or "unknown"
        marker = "⚠️ " if action_class in {"manual_review", "destructive"} else "  "
        print(f"{marker}[{action_class}/{risk}] {item.get('reason', '')}")
        preview = item.get("preview_command")
        if preview:
            print(f"    preview: {preview}")
        apply_command = item.get("apply_command")
        if apply_command:
            print(f"    apply (operator only): {apply_command}")
        no_action = item.get("no_automatic_action")
        if no_action:
            print(f"    guardrail: {no_action}")


def _doctor_distribution_block(distribution: dict[str, Any]) -> None:
    if not distribution:
        return
    if set(distribution.keys()) == {"warnings"}:
        for warning in distribution["warnings"]:
            print(f"⚠️  Distribution report unavailable: {warning}")
        return
    rust = distribution.get("rust_core") or {}
    fallback = distribution.get("fallback") or {}
    wheel = distribution.get("wheel_matrix") or {}
    index = distribution.get("index_fabric") or {}
    policy = distribution.get("rust_policy", rust.get("policy", "prefer"))
    print("Distribution:")
    print(
        "  rust core: "
        f"{rust.get('mode', 'unknown')} | native={str(rust.get('available')).lower()} | "
        f"policy={policy}"
    )
    print(
        "  platform: "
        f"{wheel.get('current_target', 'unknown')} | fallback={fallback.get('mode')}"
    )
    print(
        "  index fabric: "
        f"{index.get('freshness', 'unknown')} | sidecars={index.get('sidecar_count', 0)}"
    )
    for warning in distribution.get("warnings") or []:
        if policy == "required" and not rust.get("available"):
            print(f"❌  {warning}")
        else:
            print(f"⚠️  {warning}")


def _doctor_hook_runtime_block(report: HookRuntimeReport) -> None:
    """Render project-scoped hook runtime diagnostics."""

    installed = [
        hook
        for hook in report.hooks
        if hook.exists and (hook.configured or hook.runner_bound or hook.legacy_python)
    ]
    configured_clients = {hook.client for hook in installed}
    expected = [hook for hook in report.hooks if hook.client in configured_clients]
    missing_hooks = [hook for hook in expected if hook not in installed]
    missing = len(missing_hooks)
    probe = report.runner_probe
    legacy = [hook for hook in installed if hook.legacy_python]
    unbound = [
        hook for hook in installed if not hook.runner_bound and not hook.legacy_python
    ]
    if not probe.ok:
        state = "unavailable"
    elif not installed:
        state = "not installed"
    elif missing or legacy or unbound:
        state = "repair needed"
    else:
        state = "ready"

    print(f"Hook runtime: {state}")
    if probe.ok:
        print(f"  runner: {probe.path} ({probe.version or 'unknown version'})")
    else:
        print("  runner: unavailable")
        if probe.error:
            print(f"    error: {_doctor_one_line(probe.error)}")
        print("    fix: reinstall harness-mem, then reinstall the project Hook suite.")

    if not installed:
        print("  hook files: none installed")
    else:
        print(
            f"  hook files: {len(installed)} installed / {missing} missing "
            f"for {len(configured_clients)} configured host(s)"
        )
        for hook in installed:
            if hook.legacy_python:
                binding = "legacy python"
            elif hook.runner_bound:
                binding = "runner bound"
            else:
                binding = "runner not found"
            if hook.project_root_match:
                root_match = "project-root match"
            else:
                root_match = "project-root not found"
            scope = "global" if hook.scope == "global" else "project"
            print(
                f"    {hook.client} {hook.label}: {binding}, {root_match} "
                f"[{scope}] ({_doctor_hook_path(report.project_root, hook.path)})"
            )

    if missing or legacy or unbound:
        print("  fix: reinstall the Hook suite to bind the verified runner.")


def _doctor_hook_path(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.expanduser().resolve().as_posix()
    except OSError:
        return str(path)


def _doctor_one_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _doctor_dream_status_block(dream_report: dict[str, Any]) -> None:
    """Render read-only v3.1 dream status without creating a review queue."""
    state = "enabled" if dream_report.get("enabled") else "off"
    print("Dream auto maintenance:")
    print(f"  enabled: {state}")
    if dream_report.get("last_run_id"):
        print(
            "  last run: "
            f"{dream_report.get('last_status')} "
            f"(processed {dream_report.get('last_processed', 0)}, "
            f"failed {dream_report.get('last_failed', 0)})"
        )
    else:
        print("  last run: none")
    if dream_report.get("enabled"):
        print(
            "  auto gate: "
            f"{'eligible' if dream_report.get('scheduler_eligible') else 'not eligible'} "
            f"({dream_report.get('scheduler_reason')})"
        )
        next_at = dream_report.get("next_eligible_at")
        if next_at:
            print(f"  next eligible: {next_at}")
