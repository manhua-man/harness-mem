#!/usr/bin/env python3
"""Verify project claims and emit an evidence report."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_EVIDENCE_CHARS = 4000


class ContractError(ValueError):
    pass


class OutputBusyError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _output_lock_path(output: Path) -> Path:
    return Path(f"{output}.lock")


class _OutputLock:
    """A fail-closed, process-safe lease for one report output path."""

    def __init__(self, output: Path, run_id: str) -> None:
        self.path = _output_lock_path(output)
        self.run_id = run_id
        self._owned = False

    def __enter__(self) -> "_OutputLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise OutputBusyError(
                f"output is already being verified: {self.path}"
            ) from exc
        try:
            payload = json.dumps(
                {
                    "run_id": self.run_id,
                    "pid": os.getpid(),
                    "started_at": _utc_now().isoformat(),
                },
                ensure_ascii=False,
            )
            os.write(descriptor, payload.encode("utf-8"))
            os.fsync(descriptor)
            self._owned = True
        except BaseException:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            raise
        finally:
            os.close(descriptor)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._owned:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self._owned = False


def _write_report_atomic(output: Path, serialized: str, run_id: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{run_id}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _project_root(config_path: Path) -> Path:
    parent = config_path.resolve().parent
    return parent.parent if parent.name == ".codex" else parent


def _load_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read contract: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ContractError("schema_version must be 1")
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ContractError("claims must be a non-empty list")
    seen: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("id"), str):
            raise ContractError("every claim needs a string id")
        if claim["id"] in seen:
            raise ContractError(f"duplicate claim id: {claim['id']}")
        seen.add(claim["id"])
        checks = claim.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ContractError(f"claim {claim['id']} needs checks")
        if not any(check.get("evidence_tier") == "direct" for check in checks if isinstance(check, dict)):
            raise ContractError(f"claim {claim['id']} needs at least one direct check")
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("id"), str):
                raise ContractError(f"claim {claim['id']} has a check without a string id")
            if check.get("evidence_tier") not in {"direct", "supporting"}:
                raise ContractError(f"check {check.get('id')} has invalid evidence_tier")
            command = check.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                raise ContractError(f"check {check['id']} command must be a non-empty string array")
    return payload


def _expand(value: str, root: Path) -> str:
    return value.replace("{python}", sys.executable).replace("{project_root}", str(root))


def _lookup(payload: Any, path: str) -> tuple[bool, Any]:
    current = payload
    if not path:
        return True, current
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _assert_value(found: bool, actual: Any, rules: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for operator, expected in rules.items():
        try:
            ok = {
                "equals": lambda: found and actual == expected,
                "not_equals": lambda: found and actual != expected,
                "gte": lambda: found and actual >= expected,
                "lte": lambda: found and actual <= expected,
                "contains": lambda: found and expected in actual,
                "in": lambda: found and actual in expected,
                "exists": lambda: found is bool(expected),
                "regex": lambda: found and re.search(str(expected), str(actual)) is not None,
            }[operator]()
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            failures.append(f"{operator} expected {expected!r}, got {actual!r}" if found else f"{operator} expected {expected!r}, path missing")
    return failures


def _evaluate(stdout: str, returncode: int, expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    wanted_code = expect.get("exit_code", 0)
    if returncode != wanted_code:
        failures.append(f"exit_code expected {wanted_code}, got {returncode}")
    if "stdout_contains" in expect and str(expect["stdout_contains"]) not in stdout:
        failures.append(f"stdout missing {expect['stdout_contains']!r}")
    if "stdout_regex" in expect and re.search(str(expect["stdout_regex"]), stdout) is None:
        failures.append(f"stdout did not match {expect['stdout_regex']!r}")
    json_rules = expect.get("json")
    if json_rules is not None:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            failures.append(f"stdout is not JSON: {exc}")
        else:
            if not isinstance(json_rules, dict):
                failures.append("expect.json must be an object")
            else:
                for path, rules in json_rules.items():
                    if not isinstance(rules, dict):
                        failures.append(f"assertion for {path} must be an object")
                        continue
                    found, actual = _lookup(payload, path)
                    failures.extend(f"{path}: {item}" for item in _assert_value(found, actual, rules))
    return failures


def _run_check(
    check: dict[str, Any],
    root: Path,
    cache: dict[tuple[tuple[str, ...], str, int], dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    command = [_expand(item, root) for item in check["command"]]
    cwd = root / check.get("cwd", ".")
    timeout = int(check.get("timeout_seconds", 60))
    result: dict[str, Any] = {
        "id": check["id"],
        "run_id": run_id,
        "description": check.get("description", ""),
        "evidence_tier": check["evidence_tier"],
        "required": check.get("required", True),
        "command": command,
    }
    cache_key = (tuple(command), str(cwd.resolve()), timeout)
    if cache_key not in cache:
        started_at = _utc_now()
        started_clock = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            outcome: tuple[int, str, str] | Exception = (
                completed.returncode,
                completed.stdout,
                completed.stderr,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            outcome = exc
        completed_at = _utc_now()
        cache[cache_key] = {
            "outcome": outcome,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_seconds": max(0.0, time.perf_counter() - started_clock),
        }
    cached_entry = cache[cache_key]
    result.update(
        started_at=cached_entry["started_at"],
        completed_at=cached_entry["completed_at"],
        duration_seconds=cached_entry["duration_seconds"],
    )
    cached = cached_entry["outcome"]
    if isinstance(cached, subprocess.TimeoutExpired):
        result.update(status="blocked", failures=[f"timed out after {timeout}s"])
        return result
    if isinstance(cached, OSError):
        result.update(status="blocked", failures=[f"could not execute: {cached}"])
        return result
    returncode, stdout, stderr = cached
    failures = _evaluate(stdout, returncode, check.get("expect", {}))
    result.update(
        status="passed" if not failures else "failed",
        returncode=returncode,
        failures=failures,
        stdout=stdout[-MAX_EVIDENCE_CHARS:],
        stderr=stderr[-MAX_EVIDENCE_CHARS:],
    )
    return result


def _claim_status(checks: list[dict[str, Any]]) -> str:
    required = [item for item in checks if item["required"]]
    if any(item["status"] == "blocked" for item in required):
        return "blocked"
    if any(item["status"] == "failed" for item in required):
        return "failed"
    if not any(item["status"] == "passed" and item["evidence_tier"] == "direct" for item in checks):
        return "blocked"
    if any(item["status"] != "passed" for item in checks):
        return "partial"
    return "passed"


def verify(
    contract: dict[str, Any],
    root: Path,
    selected: set[str],
    *,
    run_id: str | None = None,
    started_at: datetime | None = None,
    started_clock: float | None = None,
) -> dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    started_at = started_at or _utc_now()
    started_clock = started_clock if started_clock is not None else time.perf_counter()
    claims: list[dict[str, Any]] = []
    cache: dict[tuple[tuple[str, ...], str, int], dict[str, Any]] = {}
    for claim in contract["claims"]:
        if selected and claim["id"] not in selected:
            continue
        checks = [
            _run_check(check, root, cache, run_id) for check in claim["checks"]
        ]
        claims.append({
            "id": claim["id"],
            "description": claim.get("description", ""),
            "required": claim.get("required", True),
            "status": _claim_status(checks),
            "checks": checks,
        })
    if selected and {item["id"] for item in claims} != selected:
        missing = sorted(selected - {item["id"] for item in claims})
        raise ContractError(f"unknown claim ids: {', '.join(missing)}")
    required = [item for item in claims if item["required"]]
    if any(item["status"] == "blocked" for item in required):
        status = "blocked"
    elif any(item["status"] == "failed" for item in required):
        status = "failed"
    elif any(item["status"] != "passed" for item in claims):
        status = "partial"
    else:
        status = "passed"
    completed_at = _utc_now()
    return {
        "schema_version": 1,
        "run_id": run_id,
        "project": contract.get("project", root.name),
        "project_root": str(root),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": max(0.0, time.perf_counter() - started_clock),
        "generated_at": completed_at.isoformat(),
        "status": status,
        "claims": claims,
    }


def _render(report: dict[str, Any]) -> None:
    print(f"Status: {report['status']}")
    for claim in report["claims"]:
        print(f"{claim['status'].upper():7} {claim['id']} - {claim['description']}")
        for check in claim["checks"]:
            if check["status"] != "passed":
                print(f"         {check['id']}: {'; '.join(check.get('failures', []))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--claim", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON")
    args = parser.parse_args(argv)
    if args.output:
        args.output = args.output.resolve()
    run_id = str(uuid.uuid4())
    started_at = _utc_now()
    started_clock = time.perf_counter()
    try:
        lock = _OutputLock(args.output, run_id) if args.output else None
        if lock is None:
            contract = _load_contract(args.config)
            report = verify(
                contract,
                _project_root(args.config),
                set(args.claim),
                run_id=run_id,
                started_at=started_at,
                started_clock=started_clock,
            )
        else:
            with lock:
                contract = _load_contract(args.config)
                report = verify(
                    contract,
                    _project_root(args.config),
                    set(args.claim),
                    run_id=run_id,
                    started_at=started_at,
                    started_clock=started_clock,
                )
                serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                _write_report_atomic(args.output, serialized, run_id)
    except ContractError as exc:
        print(f"Status: blocked\nConfiguration error: {exc}", file=sys.stderr)
        return 2
    except OutputBusyError as exc:
        print(f"Status: blocked\nOutput error: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(serialized, end="") if args.json else _render(report)
    return 0 if report["status"] == "passed" else 2 if report["status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
