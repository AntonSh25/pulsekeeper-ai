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
    HealthSummaryArgs,
    LogHealthEntryArgs,
    ask_clarifying_question,
    get_health_summary,
    log_health_entry,
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
        ]
    )


__all__ = ["ToolRegistry", "ToolSpec", "build_default_tool_registry"]
