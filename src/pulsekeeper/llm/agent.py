from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelRequest, ToolReturnPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from pulsekeeper.domain import (
    HealthEntry,
    HealthEntryDraft,
    HealthEntryKind,
    HealthEntryPatch,
    SummaryMemoryDraft,
)
from pulsekeeper.storage.health_entries import HealthEntryStore
from pulsekeeper.storage.memory import ConversationStateStore, ProfileStore, SummaryMemoryStore

AuthMode = Literal["api_key", "subscription", "test"]
SUBSCRIPTION_PROVIDER_API_KEY = "pulsekeeper-hermes-proxy"
SummaryPeriod = Literal["day", "week", "month", "custom"]
ToolOutcome = Literal["success", "failed", "denied"]


DEFAULT_POLICY_PROMPT = """
You are PulseKeeper, a private health journaling assistant.
Safety and scope:
- Do not diagnose medical conditions.
- Do not provide treatment instructions, medication dosing advice, or instructions to
  start/stop medication.
- For emergency symptoms or urgent risk, advise the user to seek emergency care or
  contact local emergency services.
- Be eating disorder aware: avoid shame, avoid coercive restriction language, and do
  not encourage unsafe weight loss.
- Privacy boundary: health notes are stored locally, but message content may be sent
  to the configured LLM provider.
- Provider boundary: you are not a clinician or a replacement for a licensed healthcare provider.
Use tools to record and summarize user-provided facts. Do not invent precise nutrition
or medical facts.
""".strip()


@dataclass(frozen=True)
class LLMConfig:
    auth_mode: AuthMode
    base_url: str | None
    model: str
    api_key: str | None = None
    timeout: int = 60
    max_tool_iterations: int = 4

    def __repr__(self) -> str:
        redacted_api_key = "***" if self.api_key else None
        return (
            "LLMConfig("
            f"auth_mode={self.auth_mode!r}, "
            f"base_url={self.base_url!r}, "
            f"model={self.model!r}, "
            f"api_key={redacted_api_key!r}, "
            f"timeout={self.timeout!r}, "
            f"max_tool_iterations={self.max_tool_iterations!r}"
            ")"
        )


@dataclass(frozen=True)
class MessageContext:
    user_id: int
    chat_id: int | str
    text: str
    attachments: list[Any]
    now: datetime
    timezone: str
    message_id: int | None = None
    source: Literal["telegram", "cli"] = "telegram"

    @property
    def user_text(self) -> str:
        """Temporary compatibility alias for pre-spec callers/tests."""
        return self.text

    @property
    def received_at(self) -> datetime:
        """Temporary compatibility alias for pre-spec callers/tests."""
        return self.now


@dataclass(frozen=True)
class AgentStores:
    """Stores bundle used by typed agent tools."""

    health_entries: HealthEntryStore
    profile: ProfileStore | None = None
    summary_memory: SummaryMemoryStore | None = None
    conversation_state: ConversationStateStore | None = None


@dataclass(frozen=True)
class AgentDeps:
    user_id: int
    health_entries: HealthEntryStore
    profile: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None
    recent_memory: list[Any] | None = None
    now: datetime | None = None
    timezone: str = "UTC"
    source: Literal["telegram", "cli"] = "telegram"
    stores: AgentStores | None = None

    def __post_init__(self) -> None:
        if self.now is None:
            object.__setattr__(self, "now", datetime.now(UTC))
        if self.stores is None:
            object.__setattr__(self, "stores", AgentStores(health_entries=self.health_entries))


@dataclass(frozen=True)
class AgentReply:
    text: str
    tool_trace: list[dict[str, str]]
    used_iterations: int
    finished_reason: str


class ToolResult(BaseModel):
    ok: bool
    summary: str
    data: dict[str, Any] | None = None


class LogHealthEntryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HealthEntryKind
    note: str | None = None
    logged_at: datetime | None = None
    value: float | None = None
    unit: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("logged_at", mode="before")
    @classmethod
    def logged_at_none_or_datetime(cls, value: Any) -> Any:
        if value is None:
            return None
        return value

    def to_draft(
        self,
        *,
        source: Literal["telegram", "cli", "import", "manual"] = "telegram",
        default_logged_at: datetime | None = None,
    ) -> HealthEntryDraft:
        return HealthEntryDraft(
            kind=self.kind,
            note=self.note,
            logged_at=self.logged_at or default_logged_at or datetime.now(UTC),
            value=self.value,
            unit=self.unit,
            source=source,
            metadata=self.metadata,
        )


class HealthSummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: SummaryPeriod
    start: date | None = None
    end: date | None = None


class AskClarifyingQuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    state_type: str | None = None
    payload: dict[str, Any] | None = None
    ttl_seconds: int = 900


class UpdateLastEntryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HealthEntryKind | None = None
    new_kind: HealthEntryKind | None = None
    note: str | None = None
    logged_at: datetime | None = None
    value: float | None = None
    unit: str | None = None
    metadata: dict[str, Any] | None = None

    def to_patch(self) -> HealthEntryPatch:
        patch_data: dict[str, Any] = {}
        if "new_kind" in self.model_fields_set:
            patch_data["kind"] = self.new_kind
        for field_name in ("note", "logged_at", "value", "unit", "metadata"):
            if field_name in self.model_fields_set:
                patch_data[field_name] = getattr(self, field_name)
        return HealthEntryPatch(**patch_data)


class DeleteLastEntryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HealthEntryKind | None = None


class SetUserProfileFactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any


class GetUserProfileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_empty: bool = False


class SearchHealthMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    limit: int = 5


class WriteSummaryMemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    kind: str
    text: str
    metadata: dict[str, Any] | None = None


async def log_health_entry(ctx: RunContext[AgentDeps], args: LogHealthEntryArgs) -> dict[str, Any]:
    """Log a health journal entry exactly as represented by the user."""
    stored = await ctx.deps.health_entries.append(
        ctx.deps.user_id,
        args.to_draft(source=ctx.deps.source, default_logged_at=ctx.deps.now),
    )
    return ToolResult(
        ok=True,
        summary=f"Logged {stored.kind} entry.",
        data={
            "id": stored.id,
            "kind": stored.kind,
            "logged_at": _datetime_json(stored.logged_at),
            "status": "logged",
        },
    ).model_dump()


async def get_health_summary(ctx: RunContext[AgentDeps], args: HealthSummaryArgs) -> dict[str, Any]:
    """Return deterministic counts of stored health entries for a period."""
    start_dt, end_dt = _summary_bounds(args, now=ctx.deps.now or datetime.now(UTC))
    entries = await ctx.deps.health_entries.list(ctx.deps.user_id, start=start_dt, end=end_dt)
    counts = Counter(entry.kind for entry in entries)
    return ToolResult(
        ok=True,
        summary=f"Found {len(entries)} health entries.",
        data={
            "period": args.period,
            "start": start_dt.date().isoformat(),
            "end": end_dt.date().isoformat(),
            "total_count": len(entries),
            "counts_by_kind": dict(sorted(counts.items())),
        },
    ).model_dump()


async def ask_clarifying_question(
    ctx: RunContext[AgentDeps],
    args: AskClarifyingQuestionArgs,
) -> dict[str, Any]:
    """Ask a clarification without writing anything to health storage."""
    if args.state_type is not None and args.payload is not None:
        store = _require_conversation_state_store(ctx.deps)
        await store.put(
            ctx.deps.user_id,
            args.state_type,
            args.payload,
            ttl_seconds=args.ttl_seconds,
        )
    return ToolResult(
        ok=True,
        summary=args.text,
        data={"status": "clarification_requested"},
    ).model_dump()


async def update_last_entry(
    ctx: RunContext[AgentDeps],
    args: UpdateLastEntryArgs,
) -> dict[str, Any]:
    """Correct the latest non-deleted health entry, optionally constrained by kind."""
    entry = await ctx.deps.health_entries.get_last(ctx.deps.user_id, kind=args.kind)
    if entry is None or entry.id is None:
        return ToolResult(
            ok=False,
            summary="No matching health entry to update.",
            data={"status": "not_found"},
        ).model_dump()

    patch = args.to_patch()
    if not patch.model_fields_set:
        return ToolResult(
            ok=False,
            summary="No correction fields were provided.",
            data={"status": "no_changes", "entry_id": entry.id},
        ).model_dump()

    updated = await ctx.deps.health_entries.update(entry.id, patch)
    return ToolResult(
        ok=True,
        summary=f"Updated latest {updated.kind} entry.",
        data={"status": "updated", "entry": _entry_json(updated)},
    ).model_dump()


async def delete_last_entry(
    ctx: RunContext[AgentDeps],
    args: DeleteLastEntryArgs,
) -> dict[str, Any]:
    """Soft-delete the latest non-deleted health entry, optionally constrained by kind."""
    entry = await ctx.deps.health_entries.get_last(ctx.deps.user_id, kind=args.kind)
    if entry is None or entry.id is None:
        return ToolResult(
            ok=False,
            summary="No matching health entry to delete.",
            data={"status": "not_found"},
        ).model_dump()

    await ctx.deps.health_entries.soft_delete(entry.id)
    return ToolResult(
        ok=True,
        summary=f"Deleted latest {entry.kind} entry.",
        data={"status": "deleted", "entry": _entry_json(entry)},
    ).model_dump()


async def set_user_profile_fact(
    ctx: RunContext[AgentDeps],
    args: SetUserProfileFactArgs,
) -> dict[str, Any]:
    """Remember an explicit stable user profile fact."""
    store = _require_profile_store(ctx.deps)
    await store.set_fact(ctx.deps.user_id, args.key, args.value, source=ctx.deps.source)
    return ToolResult(
        ok=True,
        summary=f"Saved profile fact: {args.key}.",
        data={"key": args.key, "status": "saved"},
    ).model_dump()


async def get_user_profile(
    ctx: RunContext[AgentDeps],
    args: GetUserProfileArgs,
) -> dict[str, Any]:
    """Return saved profile facts for this user."""
    store = _require_profile_store(ctx.deps)
    facts = await store.list_facts(ctx.deps.user_id)
    if not facts and not args.include_empty:
        summary = "No profile facts saved yet."
    else:
        summary = f"Found {len(facts)} profile facts."
    return ToolResult(ok=True, summary=summary, data={"facts": facts}).model_dump()


async def search_health_memory(
    ctx: RunContext[AgentDeps],
    args: SearchHealthMemoryArgs,
) -> dict[str, Any]:
    """Search durable health summary memory."""
    store = _require_summary_memory_store(ctx.deps)
    matches = await store.search(ctx.deps.user_id, args.query, limit=args.limit)
    data = [
        {
            "id": item.id,
            "period_start": item.period_start.isoformat(),
            "period_end": item.period_end.isoformat(),
            "kind": item.kind,
            "text": item.text,
            "metadata": item.metadata,
        }
        for item in matches
    ]
    return ToolResult(
        ok=True,
        summary=f"Found {len(data)} memory matches.",
        data={"matches": data},
    ).model_dump()


async def write_summary_memory(
    ctx: RunContext[AgentDeps],
    args: WriteSummaryMemoryArgs,
) -> dict[str, Any]:
    """Write a durable summary observation."""
    store = _require_summary_memory_store(ctx.deps)
    await store.write(
        ctx.deps.user_id,
        SummaryMemoryDraft(
            period_start=args.period_start,
            period_end=args.period_end,
            kind=args.kind,
            text=args.text,
            metadata=args.metadata,
        ),
    )
    return ToolResult(
        ok=True,
        summary="Saved summary memory.",
        data={"status": "saved", "kind": args.kind},
    ).model_dump()


def _require_profile_store(deps: AgentDeps) -> ProfileStore:
    if deps.stores is None or deps.stores.profile is None:
        raise RuntimeError("profile store is not configured")
    return deps.stores.profile


def _require_summary_memory_store(deps: AgentDeps) -> SummaryMemoryStore:
    if deps.stores is None or deps.stores.summary_memory is None:
        raise RuntimeError("summary memory store is not configured")
    return deps.stores.summary_memory


def _require_conversation_state_store(deps: AgentDeps) -> ConversationStateStore:
    if deps.stores is None or deps.stores.conversation_state is None:
        raise RuntimeError("conversation state store is not configured")
    return deps.stores.conversation_state


@dataclass(frozen=True)
class PulseKeeperAgent:
    agent: Agent[AgentDeps, str]
    config: LLMConfig


def build_agent(
    config: LLMConfig,
    policy_prompt: str = DEFAULT_POLICY_PROMPT,
    *,
    model: Model | str | None = None,
) -> PulseKeeperAgent:
    """Build the pydantic-ai agent used by the rest of PulseKeeper.

    Tests inject a local FunctionModel/TestModel via ``model``. Non-test configs are wired to an
    OpenAI-compatible provider using the configured base URL and optional API key. No network call
    is made while constructing the agent.
    """
    resolved_model: Model | str
    if model is not None:
        resolved_model = model
    elif config.auth_mode == "test":
        raise ValueError("test auth_mode requires an injected pydantic-ai test/function model")
    else:
        provider_api_key = (
            SUBSCRIPTION_PROVIDER_API_KEY if config.auth_mode == "subscription" else config.api_key
        )
        provider = OpenAIProvider(
            base_url=config.base_url,
            api_key=provider_api_key,
            http_client=httpx.AsyncClient(timeout=config.timeout),
        )
        resolved_model = OpenAIModel(config.model, provider=provider)

    agent: Agent[AgentDeps, str] = Agent(
        resolved_model,
        deps_type=AgentDeps,
        system_prompt=policy_prompt,
    )
    from pulsekeeper.llm.tools import build_default_tool_registry

    build_default_tool_registry().register_with_agent(agent)
    return PulseKeeperAgent(agent=agent, config=config)


async def run_turn(
    agent: PulseKeeperAgent | Agent[AgentDeps, str],
    context: MessageContext,
    deps: AgentDeps,
) -> AgentReply:
    if isinstance(agent, PulseKeeperAgent):
        pydantic_agent = agent.agent
        max_tool_iterations = agent.config.max_tool_iterations
    else:
        pydantic_agent = agent
        max_tool_iterations = 4

    effective_deps = replace(
        deps,
        user_id=context.user_id,
        now=context.now,
        timezone=context.timezone,
        source=context.source,
    )

    try:
        result = await pydantic_agent.run(
            context.text,
            deps=effective_deps,
            usage_limits=UsageLimits(
                request_limit=max_tool_iterations + 1,
                tool_calls_limit=max_tool_iterations,
            ),
        )
    except UsageLimitExceeded:
        return AgentReply(
            text="I hit the tool-use limit while handling that. Please try a smaller request.",
            tool_trace=[],
            used_iterations=0,
            finished_reason="max_iterations",
        )
    except (ModelAPIError, UnexpectedModelBehavior):
        return AgentReply(
            text="The language model had a problem. Please try again in a moment.",
            tool_trace=[],
            used_iterations=0,
            finished_reason="model_error",
        )
    messages = result.all_messages()
    tool_trace = _tool_trace(messages)
    return AgentReply(
        text=str(result.output),
        tool_trace=tool_trace,
        used_iterations=len(tool_trace),
        finished_reason="completed",
    )


def _tool_trace(messages: list[ModelMessage]) -> list[dict[str, str]]:
    trace: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                trace.append({"tool_name": part.tool_name, "outcome": part.outcome})
    return trace


def _summary_bounds(args: HealthSummaryArgs, *, now: datetime) -> tuple[datetime, datetime]:
    if args.period == "custom":
        if args.start is None or args.end is None:
            raise ValueError("custom summary requires start and end dates")
        return _date_start(args.start), _date_start(args.end)

    if args.start is not None:
        start = args.start
    elif args.period == "day":
        start = now.date()
    elif args.period == "week":
        start = now.date() - timedelta(days=now.weekday())
    else:
        start = now.date().replace(day=1)

    if args.end is not None:
        end = args.end
    elif args.period == "day":
        end = start + timedelta(days=1)
    elif args.period == "week":
        end = start + timedelta(days=7)
    else:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month

    return _date_start(start), _date_start(end)


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _datetime_json(value: datetime | date) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _entry_json(entry: HealthEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "note": entry.note,
        "value": entry.value,
        "unit": entry.unit,
        "logged_at": _datetime_json(entry.logged_at),
        "source": entry.source,
        "metadata": entry.metadata,
    }


__all__ = [
    "AgentDeps",
    "AgentReply",
    "AgentStores",
    "DEFAULT_POLICY_PROMPT",
    "DeleteLastEntryArgs",
    "GetUserProfileArgs",
    "HealthSummaryArgs",
    "LLMConfig",
    "LogHealthEntryArgs",
    "MessageContext",
    "PulseKeeperAgent",
    "SearchHealthMemoryArgs",
    "SetUserProfileFactArgs",
    "ToolResult",
    "UpdateLastEntryArgs",
    "WriteSummaryMemoryArgs",
    "build_agent",
    "delete_last_entry",
    "get_health_summary",
    "get_user_profile",
    "log_health_entry",
    "run_turn",
    "search_health_memory",
    "set_user_profile_fact",
    "update_last_entry",
    "write_summary_memory",
]
