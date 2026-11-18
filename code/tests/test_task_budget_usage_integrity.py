"""A partial native usage subtotal is not exact task accounting."""
from dataclasses import replace

import pytest

from harness_mem.autonomous.executors.host_structured_cli import _native_result_from_provider
from harness_mem.autonomous.provider import ProviderResult


@pytest.mark.parametrize("changes", [
    {"total_tokens": None}, {"total_tokens": 1}, {"total_tokens": True},
    {"duration_seconds": float('inf')}, {"duration_seconds": float('nan')},
])
def test_partial_or_inconsistent_usage_is_unknown(changes):
    complete = ProviderResult(
        decision=None, provider="isolated", model=None, duration_seconds=1.0,
        input_sha256="a", response_sha256="b", input_tokens=10,
        output_tokens=3, total_tokens=13, event_count=1,
    )
    assert _native_result_from_provider(complete).usage_exact is True
    unknown = _native_result_from_provider(replace(complete, **changes))
    assert unknown.usage_exact is False
    assert unknown.input_tokens is None
    assert unknown.output_tokens is None
