from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pulsekeeper.llm.agent import DEFAULT_POLICY_PROMPT, LLMConfig, build_agent
from pulsekeeper.llm.tools import build_default_tool_registry


def test_default_tool_registry_exposes_metadata_for_initial_tools():
    registry = build_default_tool_registry()

    assert registry.names() == [
        "log_health_entry",
        "get_health_summary",
        "ask_clarifying_question",
        "set_user_profile_fact",
        "get_user_profile",
        "search_health_memory",
        "write_summary_memory",
    ]

    log_spec = registry.get("log_health_entry")
    assert log_spec.description
    assert log_spec.input_model.__name__ == "LogHealthEntryArgs"
    assert log_spec.output_shape == "ToolResult"
    assert "diagnose" in " ".join(log_spec.safety_notes).lower()
    assert log_spec.permissions == frozenset({"health_entries:write"})

    summary_spec = registry.get("get_health_summary")
    assert summary_spec.permissions == frozenset({"health_entries:read"})

    clarify_spec = registry.get("ask_clarifying_question")
    assert clarify_spec.permissions == frozenset()

    profile_spec = registry.get("set_user_profile_fact")
    assert profile_spec.permissions == frozenset({"profile:write"})

    memory_spec = registry.get("search_health_memory")
    assert memory_spec.permissions == frozenset({"summary_memory:read"})


def test_tool_registry_validates_arguments_with_pydantic_schema():
    registry = build_default_tool_registry()

    validated = registry.validate_args(
        "log_health_entry",
        {
            "kind": "weight",
            "note": "morning weigh-in",
            "logged_at": "2026-06-13T07:00:00+00:00",
            "value": 84.2,
            "unit": "kg",
            "metadata": {"source_text": "вес 84.2"},
        },
    )

    assert validated.kind == "weight"
    assert validated.logged_at == datetime(2026, 6, 13, 7, 0, tzinfo=UTC)

    with pytest.raises(ValidationError):
        registry.validate_args("log_health_entry", {"kind": "mood", "note": "ok"})

    with pytest.raises(KeyError):
        registry.validate_args("unknown_tool", {})


def test_tool_registry_rejects_duplicate_tool_names():
    registry = build_default_tool_registry()

    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(registry.get("log_health_entry"))


def test_build_agent_registers_tools_from_default_registry():
    seen_tool_names: list[str] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal seen_tool_names
        seen_tool_names = sorted(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    agent = build_agent(
        LLMConfig(auth_mode="test", base_url=None, model="function"),
        policy_prompt=DEFAULT_POLICY_PROMPT,
        model=FunctionModel(model, model_name="tool-registry-test"),
    )

    result = agent.agent.run_sync(
        "hello",
        deps=_fake_deps(),
    )

    assert result.output == "ok"
    assert seen_tool_names == [
        "ask_clarifying_question",
        "get_health_summary",
        "get_user_profile",
        "log_health_entry",
        "search_health_memory",
        "set_user_profile_fact",
        "write_summary_memory",
    ]


def _fake_deps():
    from pulsekeeper.llm.agent import AgentDeps

    class FakeHealthEntryStore:
        pass

    return AgentDeps(user_id=1, health_entries=FakeHealthEntryStore())  # type: ignore[arg-type]
