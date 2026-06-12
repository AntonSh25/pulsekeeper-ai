from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from pulsekeeper.domain import parse_health_log
from pulsekeeper.storage import JsonlHealthLog
from pulsekeeper.summary import summarize_entries

HELP_TEXT = """Напиши вес, еду, тренировку или сон обычным текстом.
Команды:
/summary — сводка за сегодня
/summary week — сводка за 7 дней
/help — помощь"""


def handle_telegram_text(text: str, *, log_path: Path) -> str:
    message = text.strip()
    if not message:
        return HELP_TEXT
    if message == "/help":
        return HELP_TEXT
    if message.startswith("/summary"):
        return _handle_summary(message, log_path)
    if message.startswith("/"):
        return f"Не понял команду.\n\n{HELP_TEXT}"

    entry = parse_health_log(message)
    JsonlHealthLog(log_path).append(entry)
    return f"Записал: {entry.kind} — {entry.note}"


def _handle_summary(message: str, log_path: Path) -> str:
    end = date.today()
    period = "week" if message == "/summary week" else "day"
    start = end if period == "day" else end - timedelta(days=6)
    entries = JsonlHealthLog(log_path).read_all()
    return summarize_entries(entries, start=start, end=end).to_markdown()
