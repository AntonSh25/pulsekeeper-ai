from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from pulsekeeper.llm.agent import (
    AgentDeps,
    AskClarifyingQuestionArgs,
    CancelReminderArgs,
    DeleteLastEntryArgs,
    GetUserProfileArgs,
    HealthSummaryArgs,
    ListRemindersArgs,
    LogHealthEntryArgs,
    ScheduleReminderArgs,
    SearchHealthMemoryArgs,
    SetUserProfileFactArgs,
    UpdateLastEntryArgs,
    WriteSummaryMemoryArgs,
    ask_clarifying_question,
    cancel_reminder,
    delete_last_entry,
    get_health_summary,
    get_user_profile,
    list_reminders,
    log_health_entry,
    schedule_reminder,
    search_health_memory,
    set_user_profile_fact,
    update_last_entry,
    write_summary_memory,
)

ToolHandler = Callable[[RunContext[AgentDeps], Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_shape: str
    handler: ToolHandler
    permissions: frozenset[str] = frozenset()
    safety_notes: tuple[str, ...] = ()


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: OrderedDict[str, ToolSpec] = OrderedDict()
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool registered: {spec.name}")
        self._specs[spec.name] = spec

    def names(self) -> list[str]:
        return list(self._specs)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def validate_args(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        return self.get(name).input_model.model_validate(arguments)

    def register_with_agent(self, agent: Agent[AgentDeps, str]) -> None:
        for spec in self._specs.values():
            agent.tool(spec.handler, name=spec.name)


def build_default_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolSpec(
                name="log_health_entry",
                description="Log a user-provided health journal entry exactly as represented.",
                input_model=LogHealthEntryArgs,
                output_shape="ToolResult",
                handler=log_health_entry,
                permissions=frozenset({"health_entries:write"}),
                safety_notes=(
                    "Record facts only; do not diagnose or infer medical conclusions.",
                    "Do not invent precise nutrition, medication, or symptom facts.",
                ),
            ),
            ToolSpec(
                name="get_health_summary",
                description=(
                    "Return deterministic counts and summary data for stored health entries."
                ),
                input_model=HealthSummaryArgs,
                output_shape="ToolResult",
                handler=get_health_summary,
                permissions=frozenset({"health_entries:read"}),
                safety_notes=(
                    "Summarize patterns conservatively; do not diagnose.",
                    "Use deterministic stored data before optional prose generation.",
                ),
            ),
            ToolSpec(
                name="ask_clarifying_question",
                description="Ask the user a clarification question without writing to storage.",
                input_model=AskClarifyingQuestionArgs,
                output_shape="ToolResult",
                handler=ask_clarifying_question,
                permissions=frozenset(),
                safety_notes=("Use when the requested health action is ambiguous.",),
            ),
            ToolSpec(
                name="update_last_entry",
                description=(
                    "Correct the latest health entry, optionally filtering by kind before applying "
                    "provided replacement fields."
                ),
                input_model=UpdateLastEntryArgs,
                output_shape="ToolResult",
                handler=update_last_entry,
                permissions=frozenset({"health_entries:write"}),
                safety_notes=(
                    "Use only for user-requested corrections to the latest matching entry.",
                    "Ask a clarifying question first when the correction target is ambiguous.",
                ),
            ),
            ToolSpec(
                name="delete_last_entry",
                description="Soft delete the latest health entry, optionally filtering by kind.",
                input_model=DeleteLastEntryArgs,
                output_shape="ToolResult",
                handler=delete_last_entry,
                permissions=frozenset({"health_entries:write"}),
                safety_notes=(
                    "Use soft delete so deletion remains auditable and excludes entries "
                    "from normal lists.",
                    "Ask a clarifying question first when the delete target is ambiguous.",
                ),
            ),
            ToolSpec(
                name="set_user_profile_fact",
                description="Remember an explicit stable profile fact provided by the user.",
                input_model=SetUserProfileFactArgs,
                output_shape="ToolResult",
                handler=set_user_profile_fact,
                permissions=frozenset({"profile:write"}),
                safety_notes=(
                    "Only store stable user-provided facts; do not infer sensitive medical facts.",
                ),
            ),
            ToolSpec(
                name="get_user_profile",
                description="Return saved user profile facts.",
                input_model=GetUserProfileArgs,
                output_shape="ToolResult",
                handler=get_user_profile,
                permissions=frozenset({"profile:read"}),
                safety_notes=("Use profile facts as context, not as medical diagnosis.",),
            ),
            ToolSpec(
                name="search_health_memory",
                description="Search durable summary memory for prior health observations.",
                input_model=SearchHealthMemoryArgs,
                output_shape="ToolResult",
                handler=search_health_memory,
                permissions=frozenset({"summary_memory:read"}),
                safety_notes=("Return stored observations; do not overstate weak patterns.",),
            ),
            ToolSpec(
                name="write_summary_memory",
                description="Save durable weekly/monthly health observations for future summaries.",
                input_model=WriteSummaryMemoryArgs,
                output_shape="ToolResult",
                handler=write_summary_memory,
                permissions=frozenset({"summary_memory:write"}),
                safety_notes=(
                    "Only save durable observations, not transient daily noise or diagnoses.",
                ),
            ),
            ToolSpec(
                name="schedule_reminder",
                description="Schedule a timezone-aware daily reminder for a health check-in.",
                input_model=ScheduleReminderArgs,
                output_shape="ToolResult",
                handler=schedule_reminder,
                permissions=frozenset({"reminders:write"}),
                safety_notes=(
                    "Use the user's configured timezone unless they explicitly provide another.",
                    "Ask a clarifying question when reminder timing is ambiguous.",
                ),
            ),
            ToolSpec(
                name="list_reminders",
                description="List the user's active reminders.",
                input_model=ListRemindersArgs,
                output_shape="ToolResult",
                handler=list_reminders,
                permissions=frozenset({"reminders:read"}),
                safety_notes=("Return only this user's reminders.",),
            ),
            ToolSpec(
                name="cancel_reminder",
                description="Disable a specific reminder by id.",
                input_model=CancelReminderArgs,
                output_shape="ToolResult",
                handler=cancel_reminder,
                permissions=frozenset({"reminders:write"}),
                safety_notes=(
                    "Ask a clarifying question first when the reminder target is ambiguous.",
                ),
            ),
        ]
    )


__all__ = ["ToolRegistry", "ToolSpec", "build_default_tool_registry"]
