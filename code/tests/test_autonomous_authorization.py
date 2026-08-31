from __future__ import annotations

from harness_mem.autonomous.authorization import (
    background_on,
    background_ready,
    background_status,
)
from harness_mem.config.merge import MergedConfig


def test_background_ready_requires_enabled_only() -> None:
    assert background_ready(None) is False
    assert background_ready(MergedConfig(distill_autonomous_enabled=True)) is True
    assert background_ready(MergedConfig(distill_autonomous_enabled=False)) is False
    assert background_ready(MergedConfig(semantic_execution_restricted=False)) is False


def test_legacy_restricted_off_counts_as_off() -> None:
    config = MergedConfig(
        distill_autonomous_enabled=True,
        semantic_execution_restricted=False,
    )
    assert background_on(config) is False
    assert background_ready(config) is False
    status = background_status(config)
    assert status.reason == "legacy_restricted_off"
    assert status.legacy_off is True


def test_background_ready_accepts_runtime_dict_without_profile() -> None:
    runtime = {
        "distill": {"autonomous": {"enabled": True}},
        "semantic": {
            "execution": {
                "restricted": True,
                "mode": "agent",
            },
        },
    }
    assert background_ready(runtime) is True

    runtime["distill"]["autonomous"]["enabled"] = False
    assert background_ready(runtime) is False

    runtime["distill"]["autonomous"]["enabled"] = True
    runtime["semantic"]["execution"]["restricted"] = False
    assert background_ready(runtime) is False
    assert background_status(runtime).reason == "legacy_restricted_off"


def test_background_status_lists_legacy_profiles_when_present() -> None:
    status = background_status(
        MergedConfig(
            distill_autonomous_enabled=True,
            semantic_execution_profile="hermes-sub2api",
            extras={
                "semantic": {
                    "providers": {
                        "hermes-sub2api": {"approved": True},
                    }
                }
            },
        )
    )
    assert status.profiles == ("hermes-sub2api",)
    assert status.reason == "ok"
    assert status.ready is True


def test_profile_name_is_optional_for_background_ready() -> None:
    assert background_ready(MergedConfig(distill_autonomous_enabled=True)) is True
    assert background_ready(
        MergedConfig(
            distill_autonomous_enabled=True,
            semantic_execution_profile="missing-name",
        )
    ) is True
