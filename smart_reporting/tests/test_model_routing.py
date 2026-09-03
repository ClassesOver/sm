from __future__ import annotations

import pytest

from smart_reporting.model_routing import (
    DEFAULT_MODEL_PROFILES,
    DEFAULT_TASK_POLICIES,
    ModelRouter,
    ModelRouteRequest,
    RouteFailure,
    build_model_profiles,
    log_model_selection,
)


def test_default_profiles_use_requested_model_presets() -> None:
    assert DEFAULT_MODEL_PROFILES["fast"].model_id == "qwen3.6-35b-a3b"
    assert DEFAULT_MODEL_PROFILES["standard"].model_id == "deepseek-v4-flash-0731"
    assert DEFAULT_MODEL_PROFILES["strong"].model_id == "deepseek-v4-flash-0731"


def test_deployment_can_override_profile_model_ids_without_changing_policy() -> None:
    profiles = build_model_profiles(
        fast_model_id="fast-deployment-model",
        standard_model_id="standard-deployment-model",
        strong_model_id="strong-deployment-model",
    )
    router = ModelRouter(profiles, DEFAULT_TASK_POLICIES)

    selection = router.select(ModelRouteRequest(task_kind="analysis_item", complexity="complex"))

    assert selection.tier == "strong"
    assert selection.model_id == "strong-deployment-model"


@pytest.mark.parametrize(
    ("task_kind", "complexity", "tier"),
    [
        ("data_understanding", "simple", "fast"),
        ("data_understanding", "standard", "standard"),
        ("data_understanding", "complex", "strong"),
        ("analysis_item", "simple", "standard"),
        ("analysis_item", "complex", "strong"),
        ("facade", "complex", "standard"),
    ],
)
def test_router_selects_tier_from_task_policy(task_kind: str, complexity: str, tier: str) -> None:
    router = ModelRouter(DEFAULT_MODEL_PROFILES, DEFAULT_TASK_POLICIES)

    selection = router.select(
        ModelRouteRequest(task_kind=task_kind, complexity=complexity)  # type: ignore[arg-type]
    )

    assert selection.tier == tier
    assert selection.reason == "complexity_route"
    assert selection.attempt == 0


def test_schema_failure_upgrades_to_strong_only_once() -> None:
    router = ModelRouter(DEFAULT_MODEL_PROFILES, DEFAULT_TASK_POLICIES)
    request = ModelRouteRequest(
        task_kind="analysis_item", complexity="standard", failure=RouteFailure.SCHEMA
    )

    selection = router.select(request)

    assert selection.tier == "strong"
    assert selection.reason == "schema_repair"
    assert selection.attempt == 1


def test_strong_schema_failure_fails_closed() -> None:
    router = ModelRouter(DEFAULT_MODEL_PROFILES, DEFAULT_TASK_POLICIES)
    request = ModelRouteRequest(
        task_kind="analysis_item",
        complexity="complex",
        failure=RouteFailure.SCHEMA,
        attempt=1,
    )

    with pytest.raises(ValueError, match="没有可用的升级档位"):
        router.select(request)


def test_transient_failure_keeps_same_tier_and_marks_fallback() -> None:
    router = ModelRouter(DEFAULT_MODEL_PROFILES, DEFAULT_TASK_POLICIES)
    request = ModelRouteRequest(
        task_kind="analysis_item", complexity="complex", failure=RouteFailure.TRANSIENT
    )

    selection = router.select(request)

    assert selection.tier == "strong"
    assert selection.reason == "transient_retry"
    assert selection.attempt == 1


def test_router_emits_selection_event_without_sensitive_payload() -> None:
    events: list[dict[str, object]] = []
    router = ModelRouter(
        DEFAULT_MODEL_PROFILES,
        DEFAULT_TASK_POLICIES,
        event_sink=events.append,
    )

    router.select(ModelRouteRequest(task_kind="facade", complexity="standard"))

    assert events == [
        {
            "event": "report_model_selected",
            "task_kind": "facade",
            "complexity": "standard",
            "tier": "standard",
            "model_id": "deepseek-v4-flash-0731",
            "attempt": 0,
            "reason": "complexity_route",
            "policy_version": "v1",
        }
    ]


def test_selection_log_uses_stable_event_and_selection_fields(monkeypatch) -> None:
    recorded: list[tuple[str, tuple[object, ...]]] = []

    class FakeLogger:
        def info(self, template: str, *args: object) -> None:
            recorded.append((template, args))

    monkeypatch.setattr("smart_reporting.model_routing.observability.logger", FakeLogger())

    log_model_selection(
        {
            "event": "report_model_selected",
            "task_kind": "facade",
            "complexity": "standard",
            "tier": "standard",
            "model_id": "deepseek-v4-flash-0731",
            "attempt": 0,
            "reason": "complexity_route",
            "policy_version": "v1",
        }
    )

    assert recorded == [
        (
            "report_model_selected task_kind={} complexity={} tier={} model_id={} "
            "attempt={} reason={} policy_version={}",
            (
                "facade",
                "standard",
                "standard",
                "deepseek-v4-flash-0731",
                0,
                "complexity_route",
                "v1",
            ),
        )
    ]


def test_unknown_task_and_invalid_attempt_fail_closed() -> None:
    router = ModelRouter(DEFAULT_MODEL_PROFILES, DEFAULT_TASK_POLICIES)

    with pytest.raises(ValueError, match="未知 task_kind"):
        router.select(ModelRouteRequest(task_kind="unknown", complexity="simple"))
    with pytest.raises(ValueError, match="attempt"):
        router.select(ModelRouteRequest(task_kind="facade", complexity="simple", attempt=2))
