from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pulsekeeper.agent_runtime import (
    AgentRuntime,
    MessageContext,
    ModelRuntime,
    ToolCall,
    ToolExecutor,
)
from pulsekeeper.storage import JsonlHealthLog, user_health_log_path
from pulsekeeper.summary import summarize_entries

HELP_TEXT = """Напиши обычным текстом, что нужно записать или узнать.
Команды:
/summary — сводка за сегодня
/summary week — сводка за 7 дней
/help — помощь"""

MODEL_REQUIRED_TEXT = """Нужен BYOK LLM provider, чтобы понимать сообщения и вызывать health tools.
Сейчас parser-based Telegram UX отключён: пользовательский ввод должен идти через AgentRuntime."""


def handle_telegram_text(
    text: str,
    *,
    log_path: Path | None = None,
    storage_dir: Path | None = None,
    telegram_user_id: str | None = None,
    model_runtime: ModelRuntime | None = None,
) -> str:
    target_storage_dir, target_user_id, target_log_path = _resolve_targets(
        log_path=log_path,
        storage_dir=storage_dir,
        telegram_user_id=telegram_user_id,
    )
    message = text.strip()
    if not message:
        return HELP_TEXT
    if message == "/help":
        return HELP_TEXT
    if message.startswith("/summary"):
        return _handle_summary(message, target_log_path)
    if message.startswith("/"):
        return f"Не понял команду.\n\n{HELP_TEXT}"
    if model_runtime is None:
        return MODEL_REQUIRED_TEXT

    runtime = AgentRuntime(model_runtime=model_runtime, tool_executor=ToolExecutor())
    response = runtime.handle_message(
        message,
        MessageContext(
            user_id=target_user_id,
            storage_dir=target_storage_dir,
            log_path_override=target_log_path,
        ),
    )
    return response.text


def _resolve_targets(
    *,
    log_path: Path | None,
    storage_dir: Path | None,
    telegram_user_id: str | None,
) -> tuple[Path, str, Path]:
    if storage_dir is not None and telegram_user_id is not None:
        target_log_path = user_health_log_path(storage_dir, telegram_user_id)
        return storage_dir, telegram_user_id, target_log_path
    if log_path is not None:
        return log_path.parent, "local", log_path
    raise ValueError("log_path or storage_dir with telegram_user_id is required")


def _handle_summary(message: str, log_path: Path) -> str:
    end = date.today()
    period = "week" if message == "/summary week" else "day"
    start = end if period == "day" else end - timedelta(days=6)
    entries = JsonlHealthLog(log_path).read_all()
    return summarize_entries(entries, start=start, end=end).to_markdown()


class ToolCallFixtureModel:
    """Dev/test helper: returns pre-baked tool calls without parsing user text."""

    def __init__(self, calls: list[ToolCall]) -> None:
        self.calls = calls

    def complete_with_tools(self, message: str, context: MessageContext) -> list[ToolCall]:
        return self.calls
