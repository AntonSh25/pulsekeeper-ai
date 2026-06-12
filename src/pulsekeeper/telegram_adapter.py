from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pulsekeeper.domain import parse_health_log
from pulsekeeper.storage import JsonlHealthLog, user_health_log_path
from pulsekeeper.summary import summarize_entries

HELP_TEXT = """Напиши вес, еду, тренировку или сон обычным текстом.
Команды:
/summary — сводка за сегодня
/summary week — сводка за 7 дней
/help — помощь"""


def handle_telegram_text(
    text: str,
    *,
    log_path: Path | None = None,
    storage_dir: Path | None = None,
    telegram_user_id: str | None = None,
) -> str:
    target_log_path = _resolve_log_path(
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

    entry = parse_health_log(message)
    JsonlHealthLog(target_log_path).append(entry)
    return f"Записал: {entry.kind} — {entry.note}"


def _resolve_log_path(
    *,
    log_path: Path | None,
    storage_dir: Path | None,
    telegram_user_id: str | None,
) -> Path:
    if log_path is not None:
        return log_path
    if storage_dir is None or telegram_user_id is None:
        raise ValueError("log_path or storage_dir with telegram_user_id is required")
    return user_health_log_path(storage_dir, telegram_user_id)


def _handle_summary(message: str, log_path: Path) -> str:
    end = date.today()
    period = "week" if message == "/summary week" else "day"
    start = end if period == "day" else end - timedelta(days=6)
    entries = JsonlHealthLog(log_path).read_all()
    return summarize_entries(entries, start=start, end=end).to_markdown()
