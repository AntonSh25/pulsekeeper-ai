from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from pulsekeeper.domain import HealthEntry, HealthEntryKind
from pulsekeeper.storage import JsonlHealthLog, user_health_log_path
from pulsekeeper.summary import summarize_entries

ToolName = Literal["log_health_entry", "get_health_summary", "ask_clarifying_question"]


class MessageContext(BaseModel):
    user_id: str
    chat_id: str | None = None
    gateway: str = "telegram"
    storage_dir: Path
    log_path_override: Path | None = None
    timestamp: datetime = Field(default_factory=datetime.now)

    @property
    def log_path(self) -> Path:
        if self.log_path_override is not None:
            return self.log_path_override
        return user_health_log_path(self.storage_dir, self.user_id)


class ToolCall(BaseModel):
    name: ToolName
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    name: ToolName
    text: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    text: str
    tool_results: list[ToolResult] = Field(default_factory=list)


class LogHealthEntryArgs(BaseModel):
    kind: HealthEntryKind
    note: str
    logged_at: date | None = None
    value: float | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GetHealthSummaryArgs(BaseModel):
    period: Literal["day", "week", "month", "custom"] = "day"
    start: date | None = None
    end: date | None = None


class AskClarifyingQuestionArgs(BaseModel):
    text: str


class ModelRuntime(Protocol):
    def complete_with_tools(self, message: str, context: MessageContext) -> list[ToolCall]: ...


class ToolExecutor:
    def execute(self, call: ToolCall, context: MessageContext) -> ToolResult:
        if call.name == "log_health_entry":
            args = LogHealthEntryArgs.model_validate(call.arguments)
            return self._log_health_entry(args, context)
        if call.name == "get_health_summary":
            args = GetHealthSummaryArgs.model_validate(call.arguments)
            return self._get_health_summary(args, context)
        if call.name == "ask_clarifying_question":
            return self._ask_clarifying_question(
                AskClarifyingQuestionArgs.model_validate(call.arguments),
            )
        raise ValueError(f"unknown tool: {call.name}")

    def _log_health_entry(self, args: LogHealthEntryArgs, context: MessageContext) -> ToolResult:
        entry = HealthEntry(
            kind=args.kind,
            note=args.note,
            value=args.value,
            unit=args.unit,
            logged_at=args.logged_at or context.timestamp.date(),
        )
        JsonlHealthLog(context.log_path).append(entry)
        return ToolResult(
            name="log_health_entry",
            text=f"Записал: {entry.kind} — {entry.note}",
            data={"kind": entry.kind, "note": entry.note},
        )

    def _get_health_summary(
        self,
        args: GetHealthSummaryArgs,
        context: MessageContext,
    ) -> ToolResult:
        end = args.end or context.timestamp.date()
        if args.start is not None:
            start = args.start
        elif args.period == "week":
            start = end - timedelta(days=6)
        elif args.period == "month":
            start = end - timedelta(days=29)
        else:
            start = end
        entries = JsonlHealthLog(context.log_path).read_all()
        text = summarize_entries(entries, start=start, end=end).to_markdown()
        return ToolResult(name="get_health_summary", text=text)

    def _ask_clarifying_question(self, args: AskClarifyingQuestionArgs) -> ToolResult:
        return ToolResult(name="ask_clarifying_question", text=args.text)


class AgentRuntime:
    def __init__(
        self,
        *,
        model_runtime: ModelRuntime,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.model_runtime = model_runtime
        self.tool_executor = tool_executor or ToolExecutor()

    def handle_message(self, message: str, context: MessageContext) -> AgentResponse:
        tool_calls = self.model_runtime.complete_with_tools(message, context)
        results = [self.tool_executor.execute(call, context) for call in tool_calls]
        if not results:
            return AgentResponse(
                text="Не понял, что сделать. Можешь переформулировать?",
                tool_results=[],
            )
        return AgentResponse(text=results[-1].text, tool_results=results)
