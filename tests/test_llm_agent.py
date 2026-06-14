from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pulsekeeper.llm.agent import (
    DEFAULT_POLICY_PROMPT,
    AgentDeps,
    AgentStores,
    LLMConfig,
    LogHealthEntryArgs,
    MessageContext,
    build_agent,
    run_turn,
)
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.memory import ProfileStore, SummaryMemoryStore
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_policy_prompt_contains_health_safety_boundaries():
    prompt = DEFAULT_POLICY_PROMPT.lower()

    assert "do not diagnose" in prompt
    assert "do not provide treatment instructions" in prompt
    assert "emergency" in prompt
    assert "eating disorder" in prompt
    assert "privacy" in prompt
    assert "provider" in prompt


def test_log_health_entry_args_validate_kind_and_metadata():
    args = LogHealthEntryArgs(
        kind="food",
        note="oatmeal",
        logged_at=datetime(2026, 6, 13, 8, 0, tzinfo=UTC),
        value=350,
        unit="kcal",
        metadata={"calories_kcal": 350, "confidence": "explicit"},
    )

    assert args.metadata == {"calories_kcal": 350, "confidence": "explicit"}

    with pytest.raises(ValidationError):
        LogHealthEntryArgs(kind="mood", note="not a supported health entry kind")


def test_function_model_can_log_health_entry_through_store(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            fixed_now = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)
            deps = AgentDeps(user_id=user_id, health_entries=store, now=fixed_now)
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="log breakfast oatmeal, 350 kcal",
                attachments=[],
                now=fixed_now,
                timezone="UTC",
                message_id=456,
                source="cli",
            )
            calls = 0

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls
                calls += 1
                assert any(tool.name == "log_health_entry" for tool in info.function_tools)
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "log_health_entry",
                                {
                                    "kind": "food",
                                    "note": "oatmeal breakfast",
                                    "value": 350,
                                    "unit": "kcal",
                                    "metadata": {
                                        "calories_kcal": 350,
                                        "confidence": "explicit",
                                    },
                                },
                                tool_call_id="call-log-1",
                            )
                        ]
                    )
                return ModelResponse(parts=[TextPart("Logged breakfast.")])

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                policy_prompt=DEFAULT_POLICY_PROMPT,
                model=FunctionModel(model, model_name="log-health-test"),
            )

            reply = await run_turn(agent, context, deps)
            stored = await store.list(
                user_id,
                start=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
                end=datetime(2026, 6, 14, 0, 0, tzinfo=UTC),
            )

            assert reply.text == "Logged breakfast."
            assert reply.finished_reason == "completed"
            assert reply.used_iterations >= 1
            assert reply.tool_trace == [
                {"tool_name": "log_health_entry", "outcome": "success"}
            ]
            assert len(stored) == 1
            assert stored[0].kind == "food"
            assert stored[0].note == "oatmeal breakfast"
            assert stored[0].value == 350
            assert stored[0].unit == "kcal"
            assert stored[0].logged_at == fixed_now
            assert stored[0].source == "cli"
            assert stored[0].metadata == {"calories_kcal": 350, "confidence": "explicit"}
        finally:
            await db.close()

    run(scenario())


def test_function_model_can_get_health_summary_from_store(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            await store.append(
                user_id,
                LogHealthEntryArgs(
                    kind="weight",
                    note="84.2 kg",
                    logged_at=datetime(2026, 6, 13, 7, 0, tzinfo=UTC),
                    value=84.2,
                    unit="kg",
                ).to_draft(source="telegram"),
            )
            await store.append(
                user_id,
                LogHealthEntryArgs(
                    kind="food",
                    note="lunch",
                    logged_at=datetime(2026, 6, 13, 12, 0, tzinfo=UTC),
                ).to_draft(source="telegram"),
            )
            fixed_now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)
            deps = AgentDeps(user_id=user_id, health_entries=store, now=fixed_now)
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="summarize today",
                attachments=[],
                now=fixed_now,
                timezone="UTC",
                message_id=456,
                source="telegram",
            )
            calls = 0
            tool_result_payload: dict[str, Any] | None = None

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls, tool_result_payload
                calls += 1
                assert any(tool.name == "get_health_summary" for tool in info.function_tools)
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "get_health_summary",
                                {"period": "day"},
                                tool_call_id="call-summary-1",
                            )
                        ]
                    )
                latest_part = messages[-1].parts[0]
                tool_result_payload = latest_part.content
                return ModelResponse(
                    parts=[TextPart("You have 2 entries today: food 1, weight 1.")]
                )

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                policy_prompt=DEFAULT_POLICY_PROMPT,
                model=FunctionModel(model, model_name="summary-test"),
            )

            reply = await run_turn(agent, context, deps)

            assert reply.text == "You have 2 entries today: food 1, weight 1."
            assert reply.tool_trace == [
                {"tool_name": "get_health_summary", "outcome": "success"}
            ]
            assert tool_result_payload is not None
            assert tool_result_payload["ok"] is True
            assert tool_result_payload["summary"] == "Found 2 health entries."
            assert tool_result_payload["data"]["start"] == "2026-06-13"
            assert tool_result_payload["data"]["end"] == "2026-06-14"
            assert tool_result_payload["data"]["total_count"] == 2
            assert tool_result_payload["data"]["counts_by_kind"] == {"food": 1, "weight": 1}
        finally:
            await db.close()

    run(scenario())


def test_function_model_can_manage_profile_and_summary_memory(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            health_entries = HealthEntryStore(db)
            profile = ProfileStore(db)
            summary_memory = SummaryMemoryStore(db)
            now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)
            deps = AgentDeps(
                user_id=user_id,
                health_entries=health_entries,
                stores=AgentStores(
                    health_entries=health_entries,
                    profile=profile,
                    summary_memory=summary_memory,
                ),
                now=now,
            )
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="remember my timezone and save a weekly observation",
                attachments=[],
                now=now,
                timezone="UTC",
                message_id=456,
                source="telegram",
            )
            calls = 0
            seen_payloads: list[dict[str, Any]] = []

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls
                calls += 1
                tool_names = {tool.name for tool in info.function_tools}
                assert "set_user_profile_fact" in tool_names
                assert "get_user_profile" in tool_names
                assert "write_summary_memory" in tool_names
                assert "search_health_memory" in tool_names
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "set_user_profile_fact",
                                {"key": "timezone", "value": "Europe/Moscow"},
                                tool_call_id="set-profile-1",
                            )
                        ]
                    )
                if calls == 2:
                    seen_payloads.append(messages[-1].parts[0].content)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "write_summary_memory",
                                {
                                    "period_start": "2026-06-08",
                                    "period_end": "2026-06-14",
                                    "kind": "weekly_observation",
                                    "text": "Weight was stable around 84 kg.",
                                },
                                tool_call_id="write-memory-1",
                            )
                        ]
                    )
                if calls == 3:
                    seen_payloads.append(messages[-1].parts[0].content)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "search_health_memory",
                                {"query": "stable weight", "limit": 3},
                                tool_call_id="search-memory-1",
                            )
                        ]
                    )
                if calls == 4:
                    seen_payloads.append(messages[-1].parts[0].content)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "get_user_profile",
                                {},
                                tool_call_id="get-profile-1",
                            )
                        ]
                    )
                seen_payloads.append(messages[-1].parts[0].content)
                return ModelResponse(parts=[TextPart("Saved profile and memory.")])

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                model=FunctionModel(model, model_name="memory-tools-test"),
            )

            reply = await run_turn(agent, context, deps)

            assert reply.text == "Saved profile and memory."
            assert await profile.get_timezone(user_id) == "Europe/Moscow"
            matches = await summary_memory.search(user_id, "weight")
            assert len(matches) == 1
            assert matches[0].text == "Weight was stable around 84 kg."
            assert seen_payloads[-1]["data"]["facts"] == {"timezone": "Europe/Moscow"}
        finally:
            await db.close()

    run(scenario())


def test_run_turn_returns_graceful_reply_on_usage_limit(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                raise UsageLimitExceeded("tool calls exceeded")

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function", max_tool_iterations=1),
                model=FunctionModel(model, model_name="usage-limit-test"),
            )

            reply = await run_turn(
                agent,
                MessageContext(
                    user_id=user_id,
                    chat_id=123,
                    text="keep using tools",
                    attachments=[],
                    now=now,
                    timezone="UTC",
                    message_id=456,
                    source="telegram",
                ),
                AgentDeps(user_id=user_id, health_entries=store, now=now),
            )

            assert reply.finished_reason == "max_iterations"
            assert "limit" in reply.text.lower() or "too many" in reply.text.lower()
            assert reply.tool_trace == []
        finally:
            await db.close()

    run(scenario())


def test_run_turn_returns_graceful_reply_on_model_error(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            store = HealthEntryStore(db)
            now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                raise ModelAPIError("function", "upstream unavailable")

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                model=FunctionModel(model, model_name="model-error-test"),
            )

            reply = await run_turn(
                agent,
                MessageContext(
                    user_id=user_id,
                    chat_id=123,
                    text="hello",
                    attachments=[],
                    now=now,
                    timezone="UTC",
                    message_id=456,
                    source="telegram",
                ),
                AgentDeps(user_id=user_id, health_entries=store, now=now),
            )

            assert reply.finished_reason == "model_error"
            assert "try again" in reply.text.lower()
            assert reply.tool_trace == []
        finally:
            await db.close()

    run(scenario())
