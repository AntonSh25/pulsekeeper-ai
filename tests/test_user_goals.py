from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pulsekeeper.llm.agent import (
    DEFAULT_POLICY_PROMPT,
    AgentDeps,
    AgentStores,
    LLMConfig,
    MessageContext,
    build_agent,
    run_turn,
)
from pulsekeeper.profile import GoalProfile
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.memory import ProfileStore
from pulsekeeper.storage.sqlite import Database


def run(coro):
    return asyncio.run(coro)


async def create_user(db: Database) -> int:
    cursor = await db.execute("INSERT INTO users DEFAULT VALUES")
    user_id = cursor.lastrowid
    assert user_id is not None
    return user_id


def test_goal_profile_flags_are_not_shared_between_instances():
    first = GoalProfile()
    second = GoalProfile()

    first.flags.append("ed_history")

    assert first.flags == ["ed_history"]
    assert second.flags == []


def test_profile_store_keeps_goal_profile_and_tracking_focus_separate(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            profile = ProfileStore(db)

            await profile.set_tracking_focus(user_id, ["weight", "food"], source="test")
            await profile.set_goal_profile(
                user_id,
                GoalProfile(goal_type="lose", target_rate_kg_per_week=0.5),
                source="test",
            )

            assert await profile.get_tracking_focus(user_id) == ["weight", "food"]
            goal = await profile.get_goal_profile(user_id)
            assert goal == GoalProfile(goal_type="lose", target_rate_kg_per_week=0.5)
            assert await profile.get_fact(user_id, "tracking_focus") == ["weight", "food"]
            assert await profile.get_fact(user_id, "goal_profile") == {
                "goal_type": "lose",
                "target_rate_kg_per_week": 0.5,
                "target_weight_kg": None,
                "flags": [],
            }
        finally:
            await db.close()

    run(scenario())


def test_policy_prompt_distinguishes_goal_profile_from_tracking_focus():
    prompt = DEFAULT_POLICY_PROMPT.lower()

    assert "goalprofile" in prompt
    assert "tracking focus" in prompt
    assert "tracking focus is not a goal" in prompt
    assert "target_rate_kg_per_week" in prompt
    assert "set ed_history only from an explicit user statement" in prompt


def test_agent_tool_roundtrip_stores_tracking_focus_without_overwriting_goal(tmp_path):
    async def scenario() -> None:
        db = Database(tmp_path / "state.db")
        await db.initialize()
        try:
            user_id = await create_user(db)
            health_entries = HealthEntryStore(db)
            profile = ProfileStore(db)
            deps = AgentDeps(
                user_id=user_id,
                health_entries=health_entries,
                stores=AgentStores(health_entries=health_entries, profile=profile),
                now=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
            )
            context = MessageContext(
                user_id=user_id,
                chat_id=123,
                text="хочу следить за весом и питанием",
                attachments=[],
                now=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
                timezone="UTC",
                source="telegram",
            )
            calls = 0
            tool_payloads: list[dict] = []

            def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                nonlocal calls
                calls += 1
                if calls == 1:
                    tool_names = {tool.name for tool in info.function_tools}
                    assert "set_user_profile_fact" in tool_names
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "set_user_profile_fact",
                                {"key": "tracking_focus", "value": ["weight", "food"]},
                                tool_call_id="focus-1",
                            )
                        ]
                    )
                for message in messages:
                    for part in message.parts:
                        if isinstance(part, ToolReturnPart):
                            tool_payloads.append(part.content)
                return ModelResponse(
                    parts=[
                        TextPart(
                            "Ок, буду помогать с весом и питанием: коротко записывать "
                            "события и собирать сводки по паттернам."
                        )
                    ]
                )

            agent = build_agent(
                LLMConfig(auth_mode="test", base_url=None, model="function"),
                policy_prompt=DEFAULT_POLICY_PROMPT,
                model=FunctionModel(model, model_name="tracking-focus-test"),
            )

            reply = await run_turn(agent, context, deps)

            assert "весом и питанием" in reply.text
            assert await profile.get_tracking_focus(user_id) == ["weight", "food"]
            assert await profile.get_goal_profile(user_id) == GoalProfile()
            assert tool_payloads[-1]["data"] == {
                "key": "tracking_focus",
                "status": "saved",
                "value": ["weight", "food"],
            }
        finally:
            await db.close()

    run(scenario())
