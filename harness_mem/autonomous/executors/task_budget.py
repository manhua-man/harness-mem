"""Task-scoped model budget reservation at the executor boundary.

``cost_budget.*`` limits returned context. The keys below limit one explicit
task across source processing, Dream, slices, and retries. They do not reset
when a call uses a new runtime directory.

``HostStructuredCliProvider.decide`` / ``verify`` / ``assimilate`` enter this
gate before ``subprocess.Popen`` and before ``CodexAppServer.run``. Production
hosts normally account actual usage, checking cumulative thresholds before the
next invocation. The final invocation can cross a token threshold. Explicit
host_max_output_tokens requests strict reservation and still require proven
native caps. A test double is never production-host proof.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterator, Literal, Mapping, Sequence
from uuid import uuid4

from harness_mem.config.merge import MergedConfig

__all__ = [
    "HostOutputLimitSurface",
    "NativeDispatchRequest",
    "NativeDispatchResult",
    "NativeInputCapability",
    "TASK_BUDGET_REFUSAL_CODES",
    "TaskBudgetBinding",
    "TaskBudgetDispatch",
    "TaskBudgetRefusal",
    "arm_provider_maintenance_task",
    "bind_maintenance_task",
    "dispatch_with_task_budget",
    "effective_task_budget_bounds",
    "grant_maintenance_allowance",
    "fake_input_capability",
    "fake_output_limit_surface",
    "host_input_capability",
    "host_output_limit_surface",
    "is_production_native_host",
    "maintenance_task_scope",
    "read_task_budget_receipt",
    "task_budget_coverage",
    "task_budget_observation",
    "task_budget_receipt_path",
    "task_budget_scheduling_reason",
    "seed_legacy_task_budget",
]

# Stable refusal codes. A pre-dispatch refusal is not unknown billed usage.
TASK_BUDGET_REFUSAL_CODES = frozenset({
    "task_binding_missing",
    "host_binding_missing",
    "slice_binding_missing",
    "phase_binding_missing",
    "time_bound_missing",
    "bounds_not_configured",
    "host_output_limit_unsupported",
    "complete_input_bound_unknown",
    "input_budget_exhausted",
    "output_budget_exhausted",
    "call_budget_exhausted",
    "time_budget_exhausted",
    "remaining_not_demonstrable",
    "task_bounds_changed",
    "task_host_changed",
    "receipt_unreadable",
    "retry_binding_missing",
    "malformed_native_result",
    "allowance_grant_invalid",
    "allowance_receipt_changed",
})

_SCHEMA_VERSION = 1
_PHASES = frozenset({"source", "dream"})
_PRODUCTION_HOSTS = frozenset(
    {"codex", "claude-code", "hermes", "opencode", "antigravity"}
)
_EXACT_STATUSES = frozenset(
    {"completed", "failed", "retried", "cancelled", "unknown", "malformed"}
)
_BOUND_FIELDS = (
    "max_calls",
    "max_seconds",
    "max_input_tokens",
    "max_output_tokens",
    "host_max_output_tokens",
)
_WHOLE_TASK = (
    "max_calls",
    "max_seconds",
    "max_input_tokens",
    "max_output_tokens",
)

_CODEX_LIMIT = (
    "Local codex exec --help documents -c overrides, --output-schema, and "
    "--output-last-message. It does not document a model output-token cap. "
    "The binary contains tool_output_token_limit and ConfigProfile.output_token_limit; "
    "neither is a proven completion cap on this exec surface, so neither is sent."
)
_CLAUDE_LIMIT = (
    "Claude Code 2.1.296 documents --task-budget as an API-side total token "
    "budget (output_config.task_budget, type tokens, total), --max-budget-usd "
    "as dollars, and --max-turns as turns. None of those is a hard output-token "
    "cap, so none is sent as one."
)
_HERMES_LIMIT = (
    "The local Hermes one-shot parser exposes --usage-file, --max-turns as "
    "tool-calling iterations, and --run-budget as seconds. It has no output-token flag."
)
_OPENCODE_LIMIT = (
    "opencode is not installed here. The in-repo opencode run invocation has "
    "no output-token flag, so no hard output cap is sent."
)
_AGY_LIMIT = (
    "Local agy.exe has model-catalog maxOutputTokens fields and no "
    "--max-output-tokens invocation flag on the structured command surface. "
    "No hard output cap is sent."
)


class TaskBudgetRefusal(Exception):
    """Scheduling stopped before native dispatch, or the ledger cannot move."""

    def __init__(self, message: str, *, code: str, kind: str) -> None:
        super().__init__(message)
        self.code = code
        self.kind = kind


@dataclass(frozen=True)
class HostOutputLimitSurface:
    """Whether one host invocation can hard-cap its own output tokens."""

    host_client: str
    enforced: bool
    scope: str
    mechanism: str
    provenance: str
    flag: tuple[str, ...] = ()

    def argv(self, limit: int) -> tuple[str, ...]:
        if not self.enforced:
            return ()
        return (*self.flag, str(limit))


@dataclass(frozen=True)
class TaskBudgetBinding:
    """One stable task. Runtime directories are not a task identity."""

    task_scope: str
    host_client: str
    data_dir: Path
    config: MergedConfig


@dataclass(frozen=True)
class NativeInputCapability:
    """Trusted-adapter statement of one call's complete native input.

    ``max_complete_input_tokens`` is a verified upper bound for the complete
    input this call would send. It is not a text-length estimate. ``None``
    means the bound is unknown, not unlimited.

    ``enforced_by_adapter`` is true only when that adapter itself refuses a
    larger complete input. A known number with the flag false is the
    scheduler's reservation ceiling. It is not a hard native cap.
    """

    host_client: str
    max_complete_input_tokens: int | None
    provenance: str
    enforced_by_adapter: bool
    mechanism: str


@dataclass(frozen=True)
class NativeDispatchRequest:
    call_id: str
    task_scope: str
    phase: str
    slice_id: str
    host_client: str
    output_limit_argv: tuple[str, ...]
    output_limit_tokens: int
    timeout_seconds: int
    runtime_dir: str | None
    input_bound_tokens: int
    input_bound_enforced_by_adapter: bool


@dataclass(frozen=True)
class NativeDispatchResult:
    status: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    usage_exact: bool = False


@dataclass(frozen=True)
class TaskBudgetDispatch:
    call_id: str
    request: NativeDispatchRequest
    result: NativeDispatchResult
    receipt: dict[str, Any]


def is_production_native_host(host_client: str) -> bool:
    """True for the five inspected host names. None of them has a proven cap."""

    return host_client in _PRODUCTION_HOSTS


def maintenance_task_scope(trigger_id: str, dispatch_generation: str) -> str:
    """One scope for source processing and every Dream slice of that request.

    The runtime directory, a new provider instance, a slice id, and the phase
    do not mint another scope. Neither identity may be a path.
    """

    _require_identity(trigger_id, code="task_binding_missing", label="trigger_id")
    _require_identity(
        dispatch_generation, code="task_binding_missing", label="dispatch_generation",
    )
    for label, value in (
        ("trigger_id", trigger_id),
        ("dispatch_generation", dispatch_generation),
    ):
        if "/" in value or "\\" in value or value.endswith("provider-runtime"):
            raise TaskBudgetRefusal(
                f"{label} must be the natural request identity, not a runtime directory",
                code="task_binding_missing",
                kind="setup",
            )
    return f"maintenance:{trigger_id}:{dispatch_generation}"


def bind_maintenance_task(
    *,
    data_dir: Path,
    host_client: str,
    config: MergedConfig,
    trigger_id: str,
    dispatch_generation: str,
) -> TaskBudgetBinding:
    """Bind the existing natural-request pair. This does not start a host."""

    if not isinstance(host_client, str) or not host_client.strip():
        raise TaskBudgetRefusal(
            "host binding is missing; native dispatch is closed",
            code="host_binding_missing",
            kind="setup",
        )
    return TaskBudgetBinding(
        task_scope=maintenance_task_scope(trigger_id, dispatch_generation),
        host_client=host_client.strip(),
        data_dir=Path(data_dir),
        config=config,
    )


def arm_provider_maintenance_task(
    provider: Any,
    *,
    data_dir: Path,
    config: MergedConfig,
    trigger_id: str,
    dispatch_generation: str,
    phase: Literal["source", "dream"],
    slice_id: str,
    retry_of: str | None = None,
    input_capability: NativeInputCapability | None = None,
    output_limit_surface: HostOutputLimitSurface | None = None,
    explicit_fake_transport: Any = None,
) -> TaskBudgetBinding | None:
    """Attach one persistent scope before a native decide, verify, or assimilate.

    Providers that are not native executors return ``None`` and do not gain a
    budget. A native provider with this scope refuses inside the real method
    when the host cap is unproven. Dream slices repeat this call with the same
    ``trigger_id`` and ``dispatch_generation``; a new runtime directory does
    not reset the ledger.
    """

    bind = getattr(provider, "bind_task_budget", None)
    if not callable(bind):
        return None
    host_client = getattr(provider, "host_client", None)
    binding = bind_maintenance_task(
        data_dir=data_dir,
        host_client=host_client,
        config=config,
        trigger_id=trigger_id,
        dispatch_generation=dispatch_generation,
    )
    bind(
        binding,
        phase=phase,
        slice_id=slice_id,
        retry_of=retry_of,
        input_capability=input_capability,
        output_limit_surface=output_limit_surface,
        explicit_fake_transport=explicit_fake_transport,
    )
    return binding


def task_budget_observation(
    data_dir: Path,
    trigger_id: str | None,
    dispatch_generation: str | None,
) -> dict[str, Any]:
    """Read scope, known native usage, and a pre-dispatch refusal.

    This does not create a ledger and does not start a host. A missing scope
    is a setup refusal, not unknown billed usage. ``max_seconds`` on the
    ledger is cumulative native request time, not lifecycle wall waiting.
    """

    if not trigger_id or not dispatch_generation:
        return {
            "task_scope": None,
            "known_usage": None,
            "reserved_calls": 0,
            "refusal": {
                "code": "task_binding_missing",
                "kind": "setup",
                "message": "maintenance task scope is missing; native dispatch stays closed",
            },
            "native_dispatch": "refused_before_transport",
            "max_seconds_includes_lifecycle_wall_wait": False,
        }
    try:
        scope = maintenance_task_scope(str(trigger_id), str(dispatch_generation))
    except TaskBudgetRefusal as exc:
        return {
            "task_scope": None,
            "known_usage": None,
            "reserved_calls": 0,
            "refusal": {"code": exc.code, "kind": exc.kind, "message": str(exc)},
            "native_dispatch": "refused_before_transport",
            "max_seconds_includes_lifecycle_wall_wait": False,
        }
    try:
        receipt = read_task_budget_receipt(Path(data_dir), scope)
    except TaskBudgetRefusal as exc:
        return {
            "task_scope": scope,
            "known_usage": None,
            "reserved_calls": 0,
            "refusal": {"code": exc.code, "kind": exc.kind, "message": str(exc)},
            "native_dispatch": "refused_before_transport",
            "max_seconds_includes_lifecycle_wall_wait": False,
        }
    if receipt is None:
        return {
            "task_scope": scope,
            "host_client": None,
            "known_usage": None,
            "reserved_calls": 0,
            "refusal": None,
            "native_dispatch": "not_started",
            "max_seconds_includes_lifecycle_wall_wait": False,
        }
    known: list[dict[str, Any]] = []
    for call in receipt.get("calls") or []:
        if not isinstance(call, dict) or not call.get("usage_exact"):
            continue
        known.append({
            "call_id": call.get("call_id"),
            "phase": call.get("phase"),
            "slice_id": call.get("slice_id"),
            "status": call.get("status"),
            "usage": call.get("usage"),
            "model_completion": call.get("model_completion") is True,
        })
    return {
        "task_scope": scope,
        "host_client": receipt.get("host_client"),
        "original_bounds": dict(receipt["bounds"]),
        "effective_bounds": effective_task_budget_bounds(receipt),
        "allowance_grants": receipt.get("allowance_grants", []),
        "known_usage": known,
        "unknown_calls": sum(not call.get("usage_exact") for call in receipt.get("calls", [])),
        "enforcement": receipt.get("enforcement", "strict_reservation"),
        "last_invocation_may_cross_token_threshold": receipt.get("enforcement") == "observed_usage",
        "reserved_calls": len(receipt.get("calls") or []),
        "refusal": None,
        "native_dispatch": "ledger_present",
        "max_seconds_includes_lifecycle_wall_wait": False,
    }


def host_output_limit_surface(host_client: str) -> HostOutputLimitSurface:
    """Return the inspected local CLI surface. None of these enforce output tokens."""

    mechanisms = {
        "codex": _CODEX_LIMIT,
        "claude-code": _CLAUDE_LIMIT,
        "hermes": _HERMES_LIMIT,
        "opencode": _OPENCODE_LIMIT,
        "antigravity": _AGY_LIMIT,
    }
    mechanism = mechanisms.get(
        host_client,
        f"No documented output-token cap is registered for host {host_client!r}.",
    )
    return HostOutputLimitSurface(
        host_client=host_client,
        enforced=False,
        scope="not_enforced",
        mechanism=mechanism,
        provenance="local_cli_inspection",
    )


def fake_output_limit_surface(
    host_client: str = "fake-host",
    flag: tuple[str, ...] = ("--max-output-tokens",),
) -> HostOutputLimitSurface:
    """A transport double. It does not describe a production host."""

    if host_client in _PRODUCTION_HOSTS:
        raise TaskBudgetRefusal(
            "A test double cannot vouch for a production host output limit",
            code="host_output_limit_unsupported",
            kind="setup",
        )
    return HostOutputLimitSurface(
        host_client=host_client,
        enforced=True,
        scope="one_native_request",
        mechanism="test double only; not a production host and not a billing guarantee",
        provenance="test_double",
        flag=flag,
    )


def host_input_capability(host_client: str) -> NativeInputCapability:
    """No proven complete-native-input bound for this invocation surface.

    The closed result is not a claim that the host can never enforce one.
    Nothing here reads a prompt or starts a host.
    """

    return NativeInputCapability(
        host_client=host_client,
        max_complete_input_tokens=None,
        provenance="unproven",
        enforced_by_adapter=False,
        mechanism=(
            "No current invocation surface proves a complete-native-input "
            "upper bound. That is not a claim the host can never enforce one. "
            "Text length is not a bound, and an unknown envelope is not a cap."
        ),
    )


def fake_input_capability(
    host_client: str,
    max_complete_input_tokens: int,
    *,
    enforced_by_adapter: bool = False,
) -> NativeInputCapability:
    """Test-double input evidence. It cannot vouch for a production host."""

    if host_client in _PRODUCTION_HOSTS:
        raise TaskBudgetRefusal(
            "A test double cannot vouch for a production host input bound",
            code="complete_input_bound_unknown",
            kind="setup",
        )
    if not isinstance(enforced_by_adapter, bool):
        raise TaskBudgetRefusal(
            "adapter enforcement flag must be an explicit bool",
            code="complete_input_bound_unknown",
            kind="setup",
        )
    tokens = _exact_token(max_complete_input_tokens)
    if tokens is None or tokens < 1:
        raise TaskBudgetRefusal(
            "fake complete-native-input bound must be a positive integer; "
            "text length is not a bound",
            code="complete_input_bound_unknown",
            kind="setup",
        )
    if enforced_by_adapter:
        mechanism = (
            "test double only; the double claims its adapter refuses a larger "
            "complete input. This is not production-host proof and not a "
            "billing guarantee."
        )
    else:
        mechanism = (
            "test double only; stated complete-native-input ceiling for the "
            "scheduler reservation. The adapter does not enforce it, so it is "
            "not a hard native cap and not a billing guarantee."
        )
    return NativeInputCapability(
        host_client=host_client,
        max_complete_input_tokens=tokens,
        provenance="test_double",
        enforced_by_adapter=enforced_by_adapter,
        mechanism=mechanism,
    )


def _bound_coverage(key: str, value: int | None) -> dict[str, Any]:
    if key == "max_seconds":
        covers = "whole_task_cumulative_native_request_time"
    elif key in _WHOLE_TASK:
        covers = "whole_task"
    else:
        covers = "one_native_request"
    described: dict[str, Any] = {
        "value": value,
        "covers": covers,
        "configured": value is not None,
    }
    if key == "max_seconds":
        described["includes_lifecycle_wall_wait"] = False
    return described


def task_budget_coverage(config: MergedConfig) -> dict[str, Any]:
    """Say what each configured number actually covers."""

    bounds = _bounds_from_config(config)
    return {
        "task_bounds": {
            key: _bound_coverage(key, bounds[key]) for key in _BOUND_FIELDS
        },
        "missing_bounds": [key for key in _WHOLE_TASK if bounds[key] is None],
        "enforcement": "strict_reservation" if bounds["host_max_output_tokens"] is not None else "observed_usage",
        "last_invocation_may_cross_token_threshold": bounds["host_max_output_tokens"] is None,
        "max_calls_means": "HM native executor invocations, not HTTP attempts or raw model response count",
        "whole_task_means": (
            "source processing, Dream, continued slices, retries, failures, "
            "cancellations, and unknown calls share one task_scope"
        ),
        "max_seconds_means": (
            "Cumulative native request time across the whole task. An exact "
            "call adds duration_seconds; a call without exact usage adds its "
            "full reserved timeout. Fractional native seconds count upward. "
            "Gaps, queue wait, and other lifecycle wall time are not included. "
            "Job receipts may still sum provider duration_seconds, and "
            "qualification samples may store wall_duration_seconds. Those "
            "clocks are not this budget."
        ),
        "host_max_output_tokens_means": (
            "optional explicit strict per-invocation cap, only when the CLI can enforce it; "
            "unset uses cumulative actual usage, not an unlimited task"
        ),
        "complete_native_input_bound_means": (
            "Strict reservation needs a verified complete-native-input upper bound "
            "from the trusted adapter. Missing, or larger than the remaining "
            "task input budget, denies before transport. Text length is not "
            "that bound. An unproven production invocation surface is not a "
            "cap. A stated bound with enforced_by_adapter false is only the "
            "reservation ceiling; the scheduler's refusal is not a hard native "
            "cap, and the selected host and model stay unchanged."
        ),
        "returned_context_budgets": {
            "covers": "rendered_context_only",
            "not_task_model_consumption": True,
            "cost_budget.wake_tokens": config.cost_budget_wake_tokens,
            "cost_budget.search_tokens": config.cost_budget_search_tokens,
            "cost_budget.file_context_tokens": config.cost_budget_file_context_tokens,
            "cost_budget.dream_tokens": config.cost_budget_dream_tokens,
            "cost_budget.distill_tokens": config.cost_budget_distill_tokens,
        },
        "cancellation_is_model_completion": False,
        "phase_handoff_resets_budget": False,
        "usage_from_text_length": False,
        "cross_host_equivalence": False,
        "background_authorization_required": False,
    }


def task_budget_scheduling_reason(config: Any, host_client: str) -> str:
    """Inspect configured bounds and proven host caps without any transport.

    This is scheduling readiness, not background authorization. It does not
    gate recall or a current Agent's supplied manual semantic judgment.
    """
    if isinstance(config, Mapping):
        raw = config.get("task_model_budget", {})
        values = raw if isinstance(raw, Mapping) else {}
        defaults = MergedConfig()
        bounds = {key: values.get(key, getattr(defaults, "task_model_budget_" + key)) for key in _BOUND_FIELDS}
    else:
        bounds = {
            key: getattr(config, "task_model_budget_" + key, None)
            for key in _BOUND_FIELDS
        }
    if any(type(bounds[key]) is not int or bounds[key] <= 0 for key in _WHOLE_TASK):
        return "bounds_not_configured"
    if bounds["host_max_output_tokens"] is None:
        return "ok"
    if type(bounds["host_max_output_tokens"]) is not int or bounds["host_max_output_tokens"] <= 0:
        return "bounds_not_configured"
    if not host_output_limit_surface(host_client).enforced:
        return "host_output_limit_unsupported"
    capability = host_input_capability(host_client)
    if capability.max_complete_input_tokens is None:
        return "complete_input_bound_unknown"
    return "ok"


def task_budget_receipt_path(data_dir: Path, task_scope: str) -> Path:
    digest = hashlib.sha256(task_scope.encode("utf-8")).hexdigest()[:32]
    return (
        Path(data_dir)
        / "autonomous"
        / "receipts"
        / "task-model-budget"
        / f"{digest}.json"
    )


def read_task_budget_receipt(
    data_dir: Path, task_scope: str
) -> dict[str, Any] | None:
    path = task_budget_receipt_path(data_dir, task_scope)
    if not path.is_file():
        return None
    return _read_receipt(path)


def _allowance_refusal(message: str) -> TaskBudgetRefusal:
    return TaskBudgetRefusal(message, code="allowance_grant_invalid", kind="setup")


def _content_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _allowance_request(
    binding: TaskBudgetBinding, grant_id: str, expected_receipt_sha256: str,
    additional_bounds: Mapping[str, Any], authorization: Mapping[str, Any],
) -> dict[str, Any]:
    _require_identity(grant_id, code="allowance_grant_invalid", label="grant_id")
    if (not isinstance(expected_receipt_sha256, str)
            or len(expected_receipt_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_receipt_sha256)):
        raise _allowance_refusal("an exact lowercase receipt SHA256 is required")
    if (not isinstance(additional_bounds, Mapping) or not additional_bounds
            or set(additional_bounds) - set(_WHOLE_TASK)
            or any(type(v) is not int or v < 0 for v in additional_bounds.values())
            or not any(additional_bounds.values())):
        raise _allowance_refusal("allowance must add finite nonnegative whole-task bounds only")
    if not isinstance(authorization, Mapping):
        raise _allowance_refusal("explicit instruction provenance is required")
    instruction_sha = authorization.get("instruction_sha256")
    context = authorization.get("message_context")
    if (authorization.get("kind") != "current_agent_explicit_user_instruction"
            or authorization.get("actor_chosen_limits") is not True
            or not isinstance(instruction_sha, str) or len(instruction_sha) != 64
            or any(c not in "0123456789abcdef" for c in instruction_sha)
            or not isinstance(context, (str, Mapping)) or not context
            or (isinstance(context, str) and not context.strip())
            or authorization.get("human_specified_amounts") not in (None, False)):
        raise _allowance_refusal("allowance needs actual instruction context and actor-chosen limits")
    request = {
        "task_scope": binding.task_scope, "host_client": binding.host_client,
        "grant_id": grant_id, "expected_receipt_sha256": expected_receipt_sha256,
        "additional_bounds": {key: additional_bounds.get(key, 0) for key in _WHOLE_TASK},
        "authorization": dict(authorization),
    }
    try:
        return json.loads(json.dumps(request, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise _allowance_refusal("allowance provenance must be finite JSON") from exc


def _closed_allowance_calls(calls: Sequence[Any]) -> None:
    ids: set[str] = set()
    for call in calls:
        usage = call.get("usage") if isinstance(call, dict) else None
        cid = call.get("call_id") if isinstance(call, dict) else None
        if (not isinstance(cid, str) or not cid or cid in ids
                or call.get("status") not in {"completed", "failed", "retried", "cancelled"}
                or call.get("usage_exact") is not True or call.get("bound_exceeded")
                or not isinstance(usage, dict)
                or _exact_token(usage.get("input_tokens")) is None
                or _exact_token(usage.get("output_tokens")) is None
                or _exact_seconds(usage.get("duration_seconds")) is None
                or not math.isfinite(usage["duration_seconds"])):
            raise _allowance_refusal("allowance requires closed calls with exact finite usage")
        ids.add(cid)


def effective_task_budget_bounds(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate allowance history and derive limits without changing original bounds.

    Hashes detect damaged accounting; instruction provenance records the caller's
    explicit authorization and is not a cryptographic identity assertion.
    """
    original = receipt.get("bounds")
    grants = receipt.get("allowance_grants", [])
    if not isinstance(grants, list):
        raise _allowance_refusal("allowance history must be a list")
    if not grants:
        return dict(original)
    if (not isinstance(original, Mapping) or set(original) != set(_BOUND_FIELDS)
            or any(type(original.get(k)) is not int or original[k] <= 0 for k in _WHOLE_TASK)
            or (original["host_max_output_tokens"] is not None
                and (type(original["host_max_output_tokens"]) is not int
                     or original["host_max_output_tokens"] <= 0))):
        raise _allowance_refusal("original task bounds are invalid")
    bounds = dict(original)
    seen: set[str] = set()
    last_count = 0
    try:
        for index, grant in enumerate(grants):
            request = grant["request"]
            grant_id = request["grant_id"]
            binding = TaskBudgetBinding(receipt["task_scope"], receipt["host_client"], Path(), None)
            normalized = _allowance_request(binding, grant_id, request["expected_receipt_sha256"],
                                            request["additional_bounds"], request["authorization"])
            if normalized != request or grant_id in seen:
                raise _allowance_refusal("allowance identity or request changed")
            seen.add(grant_id)
            count = grant["prior_call_count"]
            if type(count) is not int or count < last_count or count > len(receipt["calls"]):
                raise _allowance_refusal("allowance call prefix changed")
            _closed_allowance_calls(receipt["calls"][:count])
            prior = dict(receipt)
            prior["calls"] = receipt["calls"][:count]
            if index:
                prior["allowance_grants"] = grants[:index]
            else:
                prior.pop("allowance_grants", None)
            if grant["prior_content_sha256"] != _content_sha256(prior):
                raise _allowance_refusal("allowance prior accounting changed")
            unsigned = {key: value for key, value in grant.items() if key != "grant_sha256"}
            if grant["grant_sha256"] != _content_sha256(unsigned):
                raise _allowance_refusal("allowance record hash changed")
            for key in _WHOLE_TASK:
                bounds[key] += request["additional_bounds"][key]
            if grant["effective_bounds"] != bounds:
                raise _allowance_refusal("allowance effective bounds changed")
            last_count = count
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _allowance_refusal("allowance history is malformed") from exc
    return bounds


def grant_maintenance_allowance(
    binding: TaskBudgetBinding, *, grant_id: str, expected_receipt_sha256: str,
    additional_bounds: Mapping[str, Any], authorization: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one finite explicit grant to an existing, closed task account.

    This never starts a host, resets accounting, or changes per-request caps.
    Repeating the exact request is idempotent even after subsequent calls.
    """
    _require_binding(binding)
    request = _allowance_request(binding, grant_id, expected_receipt_sha256,
                                 additional_bounds, authorization)
    path = task_budget_receipt_path(binding.data_dir, binding.task_scope)
    with _receipt_lock(path):
        if not path.is_file():
            raise _allowance_refusal("allowance cannot create a new task account")
        receipt = _prepare_receipt(path, binding, host_output_limit_surface(binding.host_client), 0)
        bounds = effective_task_budget_bounds(receipt)
        _closed_allowance_calls(receipt["calls"])
        for existing in receipt.get("allowance_grants", []):
            if existing["request"]["grant_id"] == grant_id:
                if existing["request"] != request:
                    raise _allowance_refusal("grant ID already records a different request")
                return receipt
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_receipt_sha256:
            raise TaskBudgetRefusal("task receipt changed before allowance append",
                                    code="allowance_receipt_changed", kind="setup")
        effective = dict(bounds)
        for key in _WHOLE_TASK:
            effective[key] += request["additional_bounds"][key]
        grant = {
            "request": request, "prior_call_count": len(receipt["calls"]),
            "prior_content_sha256": _content_sha256(receipt),
            "granted_at_unix_seconds": time.time(),
            "effective_bounds": effective,
        }
        grant["grant_sha256"] = _content_sha256(grant)
        receipt.setdefault("allowance_grants", []).append(grant)
        effective_task_budget_bounds(receipt)
        _write_receipt(path, receipt)
        return receipt


def seed_legacy_task_budget(
    binding: TaskBudgetBinding, *, calls: Sequence[Mapping[str, Any]], legacy_run_id: str,
) -> dict[str, Any]:
    """Import verified historical native terminal usage before continuation.

    The Dream owner verifies source/job identity; this owner validates exact
    usage, deduplicates native call IDs and preserves ledger idempotence.
    """
    _require_binding(binding)
    if binding.config.task_model_budget_host_max_output_tokens is not None:
        raise TaskBudgetRefusal("historical actual usage cannot prove strict native bounds",
                                code="task_bounds_changed", kind="setup")
    unique: dict[str, dict[str, Any]] = {}
    for raw in calls:
        cid = raw.get("call_id")
        usage = raw.get("usage")
        duration = _exact_seconds(raw.get("duration_seconds"))
        if (not isinstance(cid, str) or not cid or not isinstance(usage, Mapping)
                or raw.get("unknown_response_usage_count") != 0
                or raw.get("status") != "completed" or raw.get("model_dispatched") is not True
                or raw.get("phase") not in _PHASES
                or duration is None or not math.isfinite(duration)
                or _exact_token(usage.get("input_tokens")) is None
                or _exact_token(usage.get("output_tokens")) is None
                or type(usage.get("total_tokens")) is not int
                or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
                or any(raw.get(key, binding.host_client) != binding.host_client
                       for key in ("host_client", "client"))
                or any(raw.get(key, 0) != 0 for key in (
                    "unknown_attempt_count", "unknown_native_call_usage_count",
                    "unknown_usage_count",
                ))):
            raise TaskBudgetRefusal("legacy native usage is incomplete or unknown",
                                    code="remaining_not_demonstrable", kind="budget")
        row = {"call_id": cid, "phase": raw["phase"], "duration_seconds": duration,
               "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]}
        if cid in unique and unique[cid] != row:
            raise TaskBudgetRefusal("legacy native call identity has conflicting usage",
                                    code="receipt_unreadable", kind="setup")
        unique[cid] = row
    if not unique:
        raise TaskBudgetRefusal("legacy continuation has no recoverable native usage",
                                code="remaining_not_demonstrable", kind="budget")
    proof = hashlib.sha256(json.dumps(sorted(unique.values(), key=lambda r: r["call_id"]),
                                      sort_keys=True).encode()).hexdigest()
    path = task_budget_receipt_path(binding.data_dir, binding.task_scope)
    with _receipt_lock(path):
        receipt = _prepare_receipt(path, binding, host_output_limit_surface(binding.host_client), time.monotonic())
        marker = receipt.get("legacy_import")
        if marker is not None:
            if marker != {"run_id": legacy_run_id, "usage_sha256": proof}:
                raise TaskBudgetRefusal("legacy accounting import changed",
                                        code="receipt_unreadable", kind="setup")
            persisted = {row.get("call_id"): row for row in receipt["calls"]}
            for call_id, expected in unique.items():
                prior = persisted.get(call_id) or {}
                if (not prior.get("usage_exact") or prior.get("phase") != expected["phase"]
                        or prior.get("usage") != {
                            "input_tokens": expected["input_tokens"],
                            "output_tokens": expected["output_tokens"],
                            "duration_seconds": expected["duration_seconds"],
                        }):
                    raise TaskBudgetRefusal("legacy imported calls are missing or changed",
                                            code="receipt_unreadable", kind="setup")
            return receipt
        if receipt["calls"]:
            raise TaskBudgetRefusal("cannot import historical usage after new dispatch",
                                    code="remaining_not_demonstrable", kind="budget")
        for row in unique.values():
            duration = row["duration_seconds"]
            receipt["calls"].append({
                "call_id": row["call_id"], "phase": row["phase"],
                "slice_id": "legacy:" + legacy_run_id, "runtime_dir": None,
                "retry_of": None, "status": "completed", "usage_exact": True,
                "model_completion": True, "bound_exceeded": False,
                "reserved": {"calls": 1, "seconds": math.ceil(duration),
                             "input_tokens": 0, "output_tokens": 0},
                "usage": {"input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
                          "duration_seconds": duration},
                "legacy_import": True,
            })
        receipt["legacy_import"] = {"run_id": legacy_run_id, "usage_sha256": proof}
        _write_receipt(path, receipt)
        return receipt


def dispatch_with_task_budget(
    binding: TaskBudgetBinding | None,
    *,
    transport: Callable[[NativeDispatchRequest], NativeDispatchResult],
    timeout_seconds: int,
    phase: Literal["source", "dream"],
    slice_id: str,
    clock: Callable[[], float] | None = None,
    runtime_dir: str | None = None,
    output_limit_surface: HostOutputLimitSurface | None = None,
    input_capability: NativeInputCapability | None = None,
    retry_of: str | None = None,
) -> TaskBudgetDispatch:
    """Reserve one call, then invoke transport. Refusal happens first.

    The complete native input is not trimmed and the bound host is not
    switched. A missing or too-large input capability returns before transport.
    """

    now = clock or time.monotonic
    _require_binding(binding)
    assert binding is not None
    _require_identity(slice_id, code="slice_binding_missing", label="slice_id")
    if phase not in _PHASES:
        raise TaskBudgetRefusal(
            "phase must be source or dream on the same task scope",
            code="phase_binding_missing",
            kind="setup",
        )
    timeout = _exact_token(timeout_seconds)
    if timeout is None or timeout < 1:
        raise TaskBudgetRefusal(
            "timeout_seconds must be a positive integer reservation",
            code="time_bound_missing",
            kind="setup",
        )
    surface = output_limit_surface or host_output_limit_surface(binding.host_client)
    observed = binding.config.task_model_budget_host_max_output_tokens is None
    if observed:
        # No caller-provided fake evidence may turn a production host into a
        # supposedly bounded adapter. Actual usage needs no invented bound.
        if output_limit_surface is not None or input_capability is not None:
            raise TaskBudgetRefusal(
                "observed usage does not accept injected native capability proofs",
                code="host_output_limit_unsupported", kind="setup",
            )
        capability = host_input_capability(binding.host_client)
        input_bound_tokens = 0
    else:
        _require_surface(binding, surface)
        capability, input_bound_tokens = _require_input_capability(binding, input_capability)
    path = task_budget_receipt_path(binding.data_dir, binding.task_scope)
    if not path.is_file():
        # Refuse before creating a receipt when the new ledger cannot reserve.
        provisional = _prepare_receipt(path, binding, surface, now())
        _reservation(
            provisional,
            timeout_seconds=timeout,
            input_bound_tokens=input_bound_tokens,
        )
        _known_retry(provisional, retry_of)
    with _receipt_lock(path):
        receipt = _prepare_receipt(path, binding, surface, now())
        _refuse_if_not_demonstrable(receipt)
        applied = _reservation(
            receipt,
            timeout_seconds=timeout,
            input_bound_tokens=input_bound_tokens,
        )
        call_id = uuid4().hex
        call = {
            "call_id": call_id,
            "phase": phase,
            "slice_id": slice_id,
            "runtime_dir": runtime_dir,
            "retry_of": retry_of,
            "status": "reserved",
            "reserved": applied,
            "input_bound": {
                "max_complete_input_tokens": None if observed else input_bound_tokens,
                "provenance": capability.provenance,
                "adapter_enforces_bound": capability.enforced_by_adapter,
                "from_text_length": False,
                "mechanism": capability.mechanism,
            },
            "usage": {
                "input_tokens": None,
                "output_tokens": None,
                "duration_seconds": None,
            },
            "usage_exact": False,
            "model_completion": False,
            "bound_exceeded": False,
            "reserved_at": now(),
            "reconciled_at": None,
        }
        _known_retry(receipt, retry_of)
        receipt["calls"].append(call)
        _write_receipt(path, receipt)
        request = NativeDispatchRequest(
            call_id=call_id,
            task_scope=binding.task_scope,
            phase=phase,
            slice_id=slice_id,
            host_client=binding.host_client,
            output_limit_argv=surface.argv(applied["output_tokens"]),
            output_limit_tokens=applied["output_tokens"],
            timeout_seconds=timeout,
            runtime_dir=runtime_dir,
            input_bound_tokens=applied["input_tokens"],
            input_bound_enforced_by_adapter=capability.enforced_by_adapter,
        )
    try:
        result = transport(request)
    except BaseException:
        with _receipt_lock(path):
            current = _read_receipt(path)
            _mark_unknown(current, call_id, now(), status="unknown")
            _write_receipt(path, current)
        raise
    if not isinstance(result, NativeDispatchResult):
        with _receipt_lock(path):
            current = _read_receipt(path)
            _mark_unknown(current, call_id, now(), status="malformed")
            _write_receipt(path, current)
        raise TaskBudgetRefusal(
            "native transport returned a malformed result; the reservation stands",
            code="malformed_native_result",
            kind="budget",
        )
    with _receipt_lock(path):
        current = _read_receipt(path)
        _reconcile(current, call_id, result, now())
        _write_receipt(path, current)
        stored = json.loads(json.dumps(current))
    return TaskBudgetDispatch(
        call_id=call_id,
        request=request,
        result=result,
        receipt=stored,
    )


def _require_binding(binding: TaskBudgetBinding | None) -> None:
    if binding is None or not isinstance(binding, TaskBudgetBinding):
        raise TaskBudgetRefusal(
            "task binding is missing; native dispatch is closed",
            code="task_binding_missing",
            kind="setup",
        )
    _require_identity(binding.task_scope, code="task_binding_missing", label="task_scope")
    if not isinstance(binding.host_client, str) or not binding.host_client.strip():
        raise TaskBudgetRefusal(
            "host binding is missing; native dispatch is closed",
            code="host_binding_missing",
            kind="setup",
        )
    if not isinstance(binding.data_dir, Path):
        raise TaskBudgetRefusal(
            "task receipt directory is missing; native dispatch is closed",
            code="task_binding_missing",
            kind="setup",
        )


def _require_identity(value: str, *, code: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise TaskBudgetRefusal(
            f"{label} must be an explicit non-empty scope, not a runtime directory",
            code=code,
            kind="setup",
        )


def _require_input_capability(
    binding: TaskBudgetBinding,
    capability: NativeInputCapability | None,
) -> tuple[NativeInputCapability, int]:
    """Deny before transport unless a test double states a positive bound.

    Production hosts stay closed: no current invocation cap is proven, and a
    caller-supplied number does not create one. ``adapter_verified`` is not
    accepted in this gate.
    """

    if not isinstance(capability, NativeInputCapability):
        capability = host_input_capability(binding.host_client)
    unproven = (
        capability.host_client != binding.host_client
        or binding.host_client in _PRODUCTION_HOSTS
        or capability.provenance != "test_double"
        or not isinstance(capability.enforced_by_adapter, bool)
    )
    tokens = _exact_token(capability.max_complete_input_tokens)
    if unproven or tokens is None or tokens < 1:
        raise TaskBudgetRefusal(
            "complete native input bound is missing or unproven; "
            "native dispatch is closed before transport. Text length is not "
            "a bound and an unknown envelope is not a cap. "
            + capability.mechanism,
            code="complete_input_bound_unknown",
            kind="setup",
        )
    return capability, tokens


def _require_surface(
    binding: TaskBudgetBinding, surface: HostOutputLimitSurface
) -> None:
    if surface.provenance == "test_double" and binding.host_client in _PRODUCTION_HOSTS:
        raise TaskBudgetRefusal(
            "A test double cannot vouch for a production host output limit",
            code="host_output_limit_unsupported",
            kind="setup",
        )
    if surface.host_client != binding.host_client:
        raise TaskBudgetRefusal(
            "output-limit surface does not match the bound host",
            code="host_output_limit_unsupported",
            kind="setup",
        )
    if surface.enforced:
        return
    raise TaskBudgetRefusal(
        "host cannot enforce host_max_output_tokens; scheduling is closed. "
        + surface.mechanism,
        code="host_output_limit_unsupported",
        kind="setup",
    )


def _bounds_from_config(config: MergedConfig) -> dict[str, int | None]:
    return {
        "max_calls": config.task_model_budget_max_calls,
        "max_seconds": config.task_model_budget_max_seconds,
        "max_input_tokens": config.task_model_budget_max_input_tokens,
        "max_output_tokens": config.task_model_budget_max_output_tokens,
        "host_max_output_tokens": config.task_model_budget_host_max_output_tokens,
    }


def _require_bounds(config: MergedConfig) -> dict[str, int | None]:
    bounds = _bounds_from_config(config)
    missing = [key for key in _WHOLE_TASK if type(bounds[key]) is not int or bounds[key] <= 0]
    if missing:
        names = ", ".join(f"task_model_budget.{key}" for key in missing)
        raise TaskBudgetRefusal(
            f"{names} unset. Missing bounds are not unlimited; scheduling is closed.",
            code="bounds_not_configured",
            kind="setup",
        )
    host_cap = bounds["host_max_output_tokens"]
    if host_cap is not None and (type(host_cap) is not int or host_cap <= 0):
        raise TaskBudgetRefusal(
            "host_max_output_tokens must be a positive explicit strict cap",
            code="bounds_not_configured", kind="setup",
        )
    return {key: int(value) if value is not None else None for key, value in bounds.items()}


def _prepare_receipt(
    path: Path,
    binding: TaskBudgetBinding,
    surface: HostOutputLimitSurface,
    reserved_at: float,
) -> dict[str, Any]:
    bounds = _require_bounds(binding.config)
    mode = "strict_reservation" if bounds["host_max_output_tokens"] is not None else "observed_usage"
    if path.is_file():
        receipt = _read_receipt(path)
        if receipt.get("task_scope") != binding.task_scope:
            raise TaskBudgetRefusal(
                "task receipt scope does not match the binding",
                code="receipt_unreadable",
                kind="setup",
            )
        if receipt.get("bounds") != bounds:
            raise TaskBudgetRefusal(
                "task bounds changed after accounting started; "
                "the existing ledger was kept and scheduling is closed",
                code="task_bounds_changed",
                kind="setup",
            )
        if receipt.get("host_client") != binding.host_client:
            raise TaskBudgetRefusal(
                "refusing to switch host on an open task budget",
                code="task_host_changed",
                kind="setup",
            )
        if receipt.get("enforcement", "strict_reservation") != mode:
            raise TaskBudgetRefusal(
                "task accounting mode changed; the previous ledger cannot be reinterpreted",
                code="task_bounds_changed", kind="setup",
            )
        return receipt
    return {
        "schema_version": _SCHEMA_VERSION,
        "kind": "task_model_budget",
        "task_scope": binding.task_scope,
        "host_client": binding.host_client,
        "bounds": bounds,
        "enforcement": mode,
        "last_invocation_may_cross_token_threshold": mode == "observed_usage",
        "coverage": {
            "max_calls": "whole_task",
            "max_seconds": "whole_task_cumulative_native_request_time",
            "max_seconds_includes_lifecycle_wall_wait": False,
            "max_input_tokens": "whole_task",
            "max_output_tokens": "whole_task",
            "host_max_output_tokens": "one_native_request",
            "complete_input_bound": "unproven_actual_usage_only" if mode == "observed_usage" else "per_request_verified_adapter_bound",
            "unenforced_input_bound_is_hard_native_cap": False,
            "returned_context": "separate_cost_budget_keys",
        },
        "output_limit": {
            "enforced": surface.enforced,
            "scope": surface.scope,
            "provenance": surface.provenance,
            "mechanism": surface.mechanism,
            "flag": list(surface.flag),
        },
        "cancellation_is_model_completion": False,
        "phase_handoff_resets_budget": False,
        "usage_from_text_length": False,
        "cross_host_equivalence": False,
        "background_authorization_required": False,
        "created_at": reserved_at,
        "calls": [],
    }


def _reservation(
    receipt: Mapping[str, Any],
    *,
    timeout_seconds: int,
    input_bound_tokens: int,
) -> dict[str, int]:
    bounds = effective_task_budget_bounds(receipt)
    used = _consumed(receipt)
    if used["calls"] + 1 > bounds["max_calls"]:
        raise TaskBudgetRefusal(
            "task call budget is exhausted",
            code="call_budget_exhausted",
            kind="budget",
        )
    remaining_seconds = bounds["max_seconds"] - used["seconds"]
    if timeout_seconds > remaining_seconds:
        raise TaskBudgetRefusal(
            "task time budget cannot reserve this call's timeout",
            code="time_budget_exhausted",
            kind="budget",
        )
    remaining_input = bounds["max_input_tokens"] - used["input_tokens"]
    observed = receipt.get("enforcement") == "observed_usage"
    if remaining_input < 1 or input_bound_tokens > remaining_input:
        raise TaskBudgetRefusal(
            "verified complete-native-input bound exceeds the remaining "
            "task input budget",
            code="input_budget_exhausted",
            kind="budget",
        )
    remaining_output = bounds["max_output_tokens"] - used["output_tokens"]
    if remaining_output < 1:
        raise TaskBudgetRefusal(
            "task output-token budget is exhausted",
            code="output_budget_exhausted",
            kind="budget",
        )
    # The host cap is per request. The reservation cannot exceed the
    # remaining whole-task output bound, or the host could legally emit
    # more than the task still has. Input reserves the verified per-request
    # bound, not the unused remainder of the task.
    output_cap = 0 if observed else min(bounds["host_max_output_tokens"], remaining_output)
    return {
        "calls": 1,
        "seconds": timeout_seconds,
        "input_tokens": input_bound_tokens,
        "output_tokens": output_cap,
    }


def _consumed(receipt: Mapping[str, Any]) -> dict[str, int]:
    totals = {"calls": 0, "seconds": 0, "input_tokens": 0, "output_tokens": 0}
    for call in receipt["calls"]:
        totals["calls"] += 1
        amounts = call["usage"] if call.get("usage_exact") else call["reserved"]
        seconds = amounts.get("duration_seconds", amounts.get("seconds"))
        totals["seconds"] += math.ceil(_exact_seconds(seconds) or 0)
        totals["input_tokens"] += _number(amounts.get("input_tokens"))
        totals["output_tokens"] += _number(amounts.get("output_tokens"))
    return totals


def _refuse_if_not_demonstrable(receipt: Mapping[str, Any]) -> None:
    for call in receipt["calls"]:
        if call.get("bound_exceeded"):
            raise TaskBudgetRefusal(
                "native usage exceeded the reserved bound; dependent calls stay stopped",
                code="remaining_not_demonstrable",
                kind="budget",
            )
        if not call.get("usage_exact"):
            raise TaskBudgetRefusal(
                "a prior call still holds an unknown reservation; "
                "dependent calls stay stopped until native usage is exact",
                code="remaining_not_demonstrable",
                kind="budget",
            )


def _known_retry(receipt: Mapping[str, Any], retry_of: str | None) -> None:
    if retry_of is None:
        return
    known = {call["call_id"] for call in receipt["calls"]}
    if retry_of not in known:
        raise TaskBudgetRefusal(
            "retry does not name a call on this task ledger",
            code="retry_binding_missing",
            kind="setup",
        )


def _reconcile(
    receipt: dict[str, Any],
    call_id: str,
    result: NativeDispatchResult,
    now: float,
) -> None:
    call = _find_call(receipt, call_id)
    status = result.status if result.status in _EXACT_STATUSES else "malformed"
    exact_input = _exact_token(result.input_tokens)
    exact_output = _exact_token(result.output_tokens)
    exact_duration = _exact_seconds(result.duration_seconds)
    exact = bool(
        result.usage_exact
        and exact_input is not None
        and exact_output is not None
        and exact_duration is not None
    )
    call["status"] = status
    call["reconciled_at"] = now
    call["model_completion"] = bool(exact and status == "completed")
    if not exact:
        call["usage_exact"] = False
        call["model_completion"] = False
        return
    assert exact_input is not None and exact_output is not None
    assert exact_duration is not None
    reserved = call["reserved"]
    strict = receipt.get("enforcement", "strict_reservation") == "strict_reservation"
    exceeded = strict and (
        exact_input > reserved["input_tokens"]
        or exact_output > reserved["output_tokens"]
        or exact_duration > reserved["seconds"]
    )
    call["usage"] = {
        "input_tokens": exact_input,
        "output_tokens": exact_output,
        "duration_seconds": exact_duration,
    }
    call["usage_exact"] = True
    call["bound_exceeded"] = exceeded
    if not strict:
        totals = _consumed(receipt)
        bounds = effective_task_budget_bounds(receipt)
        call["cumulative_token_threshold_excess"] = {
            "input_tokens": max(0, totals["input_tokens"] - bounds["max_input_tokens"]),
            "output_tokens": max(0, totals["output_tokens"] - bounds["max_output_tokens"]),
        }
    if exceeded:
        call["model_completion"] = False


def _mark_unknown(
    receipt: dict[str, Any], call_id: str, now: float, *, status: str
) -> None:
    call = _find_call(receipt, call_id)
    call["status"] = status
    call["usage_exact"] = False
    call["model_completion"] = False
    call["reconciled_at"] = now


def _find_call(receipt: dict[str, Any], call_id: str) -> dict[str, Any]:
    for call in receipt["calls"]:
        if call["call_id"] == call_id:
            return call
    raise TaskBudgetRefusal(
        "task receipt lost the reserved call",
        code="receipt_unreadable",
        kind="setup",
    )


def _exact_token(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _exact_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


def _number(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskBudgetRefusal(
            "task budget receipt is unreadable; scheduling is closed "
            "instead of starting a new ledger",
            code="receipt_unreadable",
            kind="setup",
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
        or payload.get("kind") != "task_model_budget"
        or not isinstance(payload.get("calls"), list)
        or not isinstance(payload.get("bounds"), dict)
    ):
        raise TaskBudgetRefusal(
            "task budget receipt is unreadable; scheduling is closed "
            "instead of starting a new ledger",
            code="receipt_unreadable",
            kind="setup",
        )
    if "allowance_grants" in payload:
        effective_task_budget_bounds(payload)
    return payload


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def _receipt_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
