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
from pulsekeeper.storage.memory import ConversationStateStore, ProfileStore, SummaryMemoryStore
from pulsekeeper.storage.reminders import ReminderStore
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
            assert tool_result_payload["data"]["blocks"] == {
                "food": ["1 food entry: lunch"],
                "weight": ["Latest 84.2 kg."],
            }
            assert tool_result_payload["data"]["patterns"] == []
            assert "prose_prompt" in tool_result_payload["data"]
            prose_prompt = tool_result_payload["data"]["prose_prompt"]
            assert "Write a concise Telegram-friendly health journal summary" in prose_prompt
            assert "Do not diagnose, prescribe, or infer causes." in prose_prompt
        finally:
            await db.close()

    run(scenario())


def test_weekly_summary_writes_durable_patterns_to_summary_memory(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            health_entries = HealthEntryStore(db)
            summary_memory = SummaryMemoryStore(db)
            for logged_at, value in (
                (datetime(2026, 6, 8, 7, 0, tzinfo=UTC), 84.2),
                (datetime(2026, 6, 10, 7, 0, tzinfo=UTC), 83.4),
                (datetime(2026, 6, 14, 7, 0, tzinfo=UTC), 82.6),
            ):
                await health_entries.append(
                    user_id,
                    LogHealthEntryArgs(
                        kind="weight",
                        note=f"{value} kg",
                        logged_at=logged_at,
                        value=value,
                        unit="kg",
                    ).to_draft(source="telegram"),
                )
            fixed_now = datetime(2026, 6, 14, 18, 0, tzinfo=UTC)
            deps = AgentDeps(
                user_id=user_id,
                health_entries=health_entries,
                now=fixed_now,
                stores=AgentStores(
                    health_entries=health_entries,
                    summary_memory=summary_memory,
                ),
            )
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="summarize this week",
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
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "get_health_summary",
                                {"period": "week"},
                                tool_call_id="call-weekly-summary",
                            )
                        ]
                    )
                tool_result_payload = messages[-1].parts[0].content
                return ModelResponse(parts=[TextPart("Weekly summary ready.")])

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                policy_prompt=DEFAULT_POLICY_PROMPT,
                model=FunctionModel(model, model_name="weekly-summary-memory-test"),
            )

            reply = await run_turn(agent, context, deps)
            matches = await summary_memory.search(user_id, "diagnosis")

            assert reply.text == "Weekly summary ready."
            assert tool_result_payload is not None
            assert tool_result_payload["data"]["summary_memory_saved"] == 2
            assert len(matches) == 1
            assert matches[0].kind == "weekly_pattern"
            assert matches[0].period_start.isoformat() == "2026-06-08"
            assert matches[0].period_end.isoformat() == "2026-06-14"
            assert "Notable weight change: 1.6 kg over 6 days" in matches[0].text
        finally:
            await db.close()

    run(scenario())


def test_function_model_can_correct_and_delete_last_health_entry(tmp_path):
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
                    note="morning weight 84.2 kg",
                    logged_at=datetime(2026, 6, 13, 7, 0, tzinfo=UTC),
                    value=84.2,
                    unit="kg",
                ).to_draft(source="telegram"),
            )
            fixed_now = datetime(2026, 6, 13, 8, 0, tzinfo=UTC)
            deps = AgentDeps(user_id=user_id, health_entries=store, now=fixed_now)
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="не 84.2, а 83.9, потом удали последнюю запись",
                attachments=[],
                now=fixed_now,
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
                assert "update_last_entry" in tool_names
                assert "delete_last_entry" in tool_names
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "update_last_entry",
                                {"kind": "weight", "value": 83.9, "unit": "kg"},
                                tool_call_id="update-last-1",
                            )
                        ]
                    )
                if calls == 2:
                    seen_payloads.append(messages[-1].parts[0].content)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "delete_last_entry",
                                {"kind": "weight"},
                                tool_call_id="delete-last-1",
                            )
                        ]
                    )
                seen_payloads.append(messages[-1].parts[0].content)
                return ModelResponse(
                    parts=[TextPart("Corrected then deleted the latest weight entry.")]
                )

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                policy_prompt=DEFAULT_POLICY_PROMPT,
                model=FunctionModel(model, model_name="correction-tools-test"),
            )

            reply = await run_turn(agent, context, deps)
            remaining = await store.list(
                user_id,
                start=datetime(2026, 6, 13, 0, 0, tzinfo=UTC),
                end=datetime(2026, 6, 14, 0, 0, tzinfo=UTC),
            )

            assert reply.text == "Corrected then deleted the latest weight entry."
            assert reply.tool_trace == [
                {"tool_name": "update_last_entry", "outcome": "success"},
                {"tool_name": "delete_last_entry", "outcome": "success"},
            ]
            assert seen_payloads[0]["summary"] == "Updated latest weight entry."
            assert seen_payloads[0]["data"]["entry"]["value"] == 83.9
            assert seen_payloads[1]["summary"] == "Deleted latest weight entry."
            assert remaining == []
        finally:
            await db.close()

    run(scenario())


def test_function_model_persists_pending_ambiguous_correction_when_asking_clarification(
    tmp_path,
):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            health_entries = HealthEntryStore(db)
            conversation_state = ConversationStateStore(db)
            now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)
            deps = AgentDeps(
                user_id=user_id,
                health_entries=health_entries,
                stores=AgentStores(
                    health_entries=health_entries,
                    conversation_state=conversation_state,
                ),
                now=now,
            )
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="исправь вчерашнюю запись на 83.9",
                attachments=[],
                now=now,
                timezone="UTC",
                message_id=456,
                source="telegram",
            )

            calls = 0

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls
                calls += 1
                assert any(tool.name == "ask_clarifying_question" for tool in info.function_tools)
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "ask_clarifying_question",
                                {
                                    "text": "Which entry should I correct?",
                                    "state_type": "pending_correction",
                                    "payload": {
                                        "action": "update_last_entry",
                                        "value": 83.9,
                                        "unit": "kg",
                                        "reason": "ambiguous target",
                                    },
                                    "ttl_seconds": 900,
                                },
                                tool_call_id="clarify-correction-1",
                            )
                        ]
                    )
                return ModelResponse(parts=[TextPart("Which entry should I correct?")])

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                model=FunctionModel(model, model_name="ambiguous-correction-test"),
            )

            reply = await run_turn(agent, context, deps)
            pending = await conversation_state.get(user_id, "pending_correction")

            assert reply.text == "Which entry should I correct?"
            assert reply.tool_trace == [
                {"tool_name": "ask_clarifying_question", "outcome": "success"}
            ]
            assert pending == {
                "action": "update_last_entry",
                "value": 83.9,
                "unit": "kg",
                "reason": "ambiguous target",
            }
            assert await health_entries.get_last(user_id) is None
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


def test_function_model_can_schedule_list_and_cancel_reminders(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            health_entries = HealthEntryStore(db)
            reminders = ReminderStore(db)
            now = datetime(2026, 6, 13, 18, 0, tzinfo=UTC)
            deps = AgentDeps(
                user_id=user_id,
                health_entries=health_entries,
                stores=AgentStores(health_entries=health_entries, reminders=reminders),
                now=now,
                timezone="Europe/Moscow",
            )
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="напомни взвешиваться каждый день в 09:00, покажи и отключи",
                attachments=[],
                now=now,
                timezone="Europe/Moscow",
                message_id=456,
                source="telegram",
            )
            calls = 0
            seen_payloads: list[dict[str, Any]] = []

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls
                calls += 1
                tool_names = {tool.name for tool in info.function_tools}
                assert "schedule_reminder" in tool_names
                assert "list_reminders" in tool_names
                assert "cancel_reminder" in tool_names
                if calls == 1:
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "schedule_reminder",
                                {"type": "weight", "time": "09:00"},
                                tool_call_id="schedule-reminder-1",
                            )
                        ]
                    )
                if calls == 2:
                    seen_payloads.append(messages[-1].parts[0].content)
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "list_reminders",
                                {},
                                tool_call_id="list-reminders-1",
                            )
                        ]
                    )
                if calls == 3:
                    seen_payloads.append(messages[-1].parts[0].content)
                    reminder_id = seen_payloads[0]["data"]["reminder"]["id"]
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "cancel_reminder",
                                {"reminder_id": reminder_id},
                                tool_call_id="cancel-reminder-1",
                            )
                        ]
                    )
                seen_payloads.append(messages[-1].parts[0].content)
                return ModelResponse(parts=[TextPart("Reminder configured and cancelled.")])

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                model=FunctionModel(model, model_name="reminder-tools-test"),
            )

            reply = await run_turn(agent, context, deps)
            stored = await reminders.list(user_id)

            assert reply.text == "Reminder configured and cancelled."
            assert reply.tool_trace == [
                {"tool_name": "schedule_reminder", "outcome": "success"},
                {"tool_name": "list_reminders", "outcome": "success"},
                {"tool_name": "cancel_reminder", "outcome": "success"},
            ]
            assert seen_payloads[0]["summary"] == (
                "Scheduled daily weight reminder at 09:00 Europe/Moscow."
            )
            assert seen_payloads[0]["data"]["reminder"]["next_due_at"] == (
                "2026-06-14T06:00:00+00:00"
            )
            assert seen_payloads[1]["data"]["reminders"][0]["type"] == "weight"
            assert seen_payloads[2]["summary"] == "Cancelled reminder #1."
            assert len(stored) == 1
            assert stored[0].enabled is False
            assert stored[0].schedule == {"kind": "daily", "time": "09:00"}
            assert stored[0].timezone == "Europe/Moscow"
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
